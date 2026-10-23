from skiiprep_transformation.tables.weather_hourly import WeatherHourlyTable
from skiiprep_transformation.spark import get_spark
from skiiprep_common.settings import DATA_BRONZE_DIR, DATA_WAREHOUSE_DIR
from pyspark.sql import DataFrame, SparkSession, functions as F
from pyspark.errors import PySparkException
from pathlib import Path
import sys

# Where this job reads its input. A parameter default, so tests can pass a temp folder.
OPEN_METEO_BRONZE_DIR = DATA_BRONZE_DIR / "open_meteo"


def _create_table_if_not_exist(spark: SparkSession, create_statement: str, catalog:str, namespace:str, table_name: str ):
    """Ensures both the namespace and target Iceberg table exist in the catalog."""
    full_table_path = f"{catalog}.{namespace}.{table_name}"
    # 1. Ensure the namespace exists first
    try:
        print(f"[STAGE 1] Checking if namespace '{namespace}' exists in catalog '{catalog}'...")
        
        # Check current databases/namespaces in the given catalog
        namespaces_df = spark.sql(f"SHOW NAMESPACES IN {catalog}")
        namespaces_list = [row[0] for row in namespaces_df.collect()]
        
        if namespace not in namespaces_list:
            print(f"[STAGE 1] Namespace '{namespace}' not found. Creating it now...")
            spark.sql(f"CREATE NAMESPACE IF NOT EXISTS {catalog}.{namespace}")
            print(f"[STAGE 1] Namespace '{namespace}' created successfully.")
        else:
            print(f"[STAGE 1] Namespace '{namespace}' verified.")
            
    except PySparkException as e:
        print(f"[STAGE 1] Critical Failure checking/creating namespace: {e}", file=sys.stderr)
        raise e
    
    # 2. Proceed to create the table safely
    try:
        print(f"[STAGE 1] Creating table {full_table_path} if it does not exist...")
        spark.sql(create_statement)
        print(f"[STAGE 1] Success: Table {full_table_path} verified.")
    except PySparkException as e:
        print(f"[STAGE 1/3] Critical Failure (Spark DDL Error): {e}", file=sys.stderr)
        raise e
    except Exception as e:
        print(f"[STAGE 1/3] Critical Failure (Python Error): {e}", file=sys.stderr)
        raise e

def _transform(spark: SparkSession, bronze_dir: Path = OPEN_METEO_BRONZE_DIR) -> DataFrame:
    """Read every bronze file under `bronze_dir` and flatten it to one row per hour."""
    try:
        print("[STAGE 2/3] Preparing batch update data...")

        # recursiveFileLookup turns off partition discovery. Without it, Spark turns the
        # folder names (resort_id=, point=) into columns that clash with the same fields
        # in the envelope. resort_id and point come from the envelope, which is the same data.
        df = (spark
                .read
                .option("recursiveFileLookup", True)
                .option("multiLine", True)
                .json(str(bronze_dir))
            )
        
        zipped_df = (
            df.withColumn(
                "zipped_hourly_measures",
                F.arrays_zip(
                    "response.hourly.temperature_2m",
                    "response.hourly.apparent_temperature",
                    "response.hourly.precipitation",
                    "response.hourly.rain",
                    "response.hourly.snowfall",
                    "response.hourly.snow_depth",
                    "response.hourly.freezing_level_height",
                    "response.hourly.wind_speed_10m",
                    "response.hourly.wind_gusts_10m",
                    "response.hourly.weather_code",
                    "response.hourly.cloud_cover",
                    "response.hourly.visibility",
                    "response.hourly.time",
                )
            )
        )

        exploded_df = zipped_df.withColumn("zipped_hourly_measures_struct", F.explode(F.col("zipped_hourly_measures")))

        final_df = (
            exploded_df
            .withColumn("bronze_file", F.col("_metadata.file_path"))
            .withColumn("dw_processing_time", F.current_timestamp())
            .select(
                F.col("resort_id"),
                F.col("point"),
                F.to_timestamp(F.col("zipped_hourly_measures_struct.time"), "yyyy-MM-dd'T'HH:mm").alias("valid_time"),
                # [.SSSSSS] is optional: Python's isoformat() omits the fraction when the
                # microseconds are exactly 0, and that bronze file is kept forever.
                F.to_timestamp(F.col("fetched_at"), "yyyy-MM-dd'T'HH:mm:ss[.SSSSSS]xxx").alias("fetched_at"),
                F.lit("open_meteo").alias("source"),
                F.col("elevation_m"),
                F.col("zipped_hourly_measures_struct.temperature_2m").alias("temp_c"),
                F.col("zipped_hourly_measures_struct.apparent_temperature").alias("feels_like_c"),
                F.col("zipped_hourly_measures_struct.precipitation").alias("precip_mm"),
                F.col("zipped_hourly_measures_struct.rain").alias("rain_mm"),
                F.col("zipped_hourly_measures_struct.snowfall").alias("snowfall_cm"),
                F.col("zipped_hourly_measures_struct.snow_depth").alias("snow_depth_m"),
                F.col("zipped_hourly_measures_struct.freezing_level_height").alias("freezing_level_m"),
                F.col("zipped_hourly_measures_struct.wind_speed_10m").alias("wind_kmh"),
                F.col("zipped_hourly_measures_struct.wind_gusts_10m").alias("gust_kmh"),
                F.col("zipped_hourly_measures_struct.weather_code").alias("weather_code"),
                F.col("zipped_hourly_measures_struct.cloud_cover").alias("cloud_cover_pct"),
                F.col("zipped_hourly_measures_struct.visibility").alias("visibility_m"),
                F.col("bronze_file"),
                F.col("dw_processing_time")
            )
        )
        print("[STAGE 2/3] Success: DataFrame created.")
        return final_df
    
    except Exception as e:
        print(f"[STAGE 2/3] Critical Failure (Data ingestion error): {e}", file=sys.stderr)
        raise e

def _upsert_to_iceberg(spark: SparkSession, merge_statement:str, source_df: DataFrame, target_table: str) -> None:
    """Registers the source DataFrame and runs the MERGE INTO statement."""
    temp_view_name = "staged_updates"
    try:
        print(f"[STAGE 3/3] Executing upsert transaction onto: {target_table}")
        # 1. Truncate lineage by saving streaming rows to local disk
        # eager=True forces the evaluation immediately so it's ready for the SQL block
        # checkpointed_df = source_df.localCheckpoint(eager=True)
        
        # print(f"[STAGE 3/3] Executing merge onto: {target_table}")
        # checkpointed_df.createOrReplaceTempView(temp_view_name)
        
        #  # 1. Cache the DataFrame
        # source_df.cache()
        # # 2. Trigger an action to force Spark to evaluate input_file_name() completely
        # _ = source_df.count() 

        source_df.createOrReplaceTempView(temp_view_name)
        
        spark.sql(merge_statement.format(
            target_table=target_table,
            temp_view_name=temp_view_name
        ))
        print("[STAGE 3/3] Success: Merge transaction committed.")
    except PySparkException as e:
        print(f"[STAGE 3/3] Critical Failure (Iceberg write error): {e}", file=sys.stderr)
        raise e
    except Exception as e:
        print(f"[STAGE 3/3] Critical Failure (General error): {e}", file=sys.stderr)
        raise e
    finally:
        # Clean up the temp view from the Spark catalog memory
        spark.catalog.dropTempView(temp_view_name)

def execute(
    spark: SparkSession | None = None,
    bronze_dir: Path = OPEN_METEO_BRONZE_DIR,
    warehouse_dir: Path = DATA_WAREHOUSE_DIR,
) -> None:
    """Run the weather silver job: create the table if needed, then MERGE bronze into it.

    Without `spark`, a session is created on `warehouse_dir` and stopped at the end.
    A session passed in (tests share one) is used as-is and left running for the
    caller to stop; its warehouse is whatever it was created with.
    """
    owns_session = spark is None
    if owns_session:
        spark = get_spark(warehouse_dir=warehouse_dir)
    try:
        _create_table_if_not_exist(
            spark=spark,
            create_statement=WeatherHourlyTable.create_statement,
            catalog=WeatherHourlyTable.catalog_name,
            namespace=WeatherHourlyTable.namespace_name,
            table_name=WeatherHourlyTable.table_name  # bare name; the function adds catalog and namespace
        )

        df = _transform(spark=spark, bronze_dir=bronze_dir)

        _upsert_to_iceberg(
            spark=spark,
            merge_statement=WeatherHourlyTable.merge_statement,
            source_df=df,
            target_table=WeatherHourlyTable.full_table_name
        )
    finally:
        # Stop the session even when a stage fails, so the JVM doesn't outlive the job.
        # Stop only after the MERGE: it is the last Spark action. Only stop a session
        # this function created.
        if owns_session:
            spark.stop()