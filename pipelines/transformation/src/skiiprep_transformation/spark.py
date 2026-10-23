from pathlib import Path

from pyspark.sql import SparkSession
from skiiprep_common.settings import DATA_WAREHOUSE_DIR
import os

def get_spark(
    env: str = "dev",
    target_cores: int = 2,
    warehouse_dir: Path | str = DATA_WAREHOUSE_DIR,
) -> SparkSession:
    """
    Initializes a highly modular and environment-aware SparkSession for Iceberg.

    :param env: Deployment environment ('dev', 'test', 'prod')
    :param target_cores: Set partitions lower for local/dev workloads, higher for prod cluster sizing
    :param warehouse_dir: Where the local Hadoop catalog keeps its tables. Defaults to
        data/warehouse; tests pass a temp folder so they never write into data/.
    """
    _catalog = "lake"

    # 1. Standard configurations across all environments
    base_configs = {
        "spark.app.name": f"SkiiprepIcebergPipeline-{env.upper()}",
        "spark.sql.session.timeZone": "UTC",
        "spark.sql.shuffle.partitions": str(target_cores),
        
        # Iceberg Core
        "spark.jars.packages": "org.apache.iceberg:iceberg-spark-runtime-4.0_2.13:1.10.0",
        "spark.sql.extensions": "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
        
        # Catalog Setup
        f"spark.sql.catalog.{_catalog}": "org.apache.iceberg.spark.SparkCatalog",
    }
    
    # 2. Dynamic environment overriding 
    if env == "prod":
        base_configs.update({
            "spark.master": "yarn",  # or k8s cluster URL
            f"spark.sql.catalog.{_catalog}.type": "glue",  # Production meta-store
            f"spark.sql.catalog.{_catalog}.warehouse": "s3a://prod-data-lake-warehouse/",
            f"spark.sql.catalog.{_catalog}.io-impl": "org.apache.iceberg.aws.s3.S3FileIO",
        })
    else:
        # Default to a localized sandbox configuration
        base_configs.update({
            "spark.master": "local[*]",
            f"spark.sql.catalog.{_catalog}.type": "hadoop",
            f"spark.sql.catalog.{_catalog}.warehouse": str(warehouse_dir),
        })
    builder = SparkSession.builder 

    # 3. Pull sensitive runtime credentials strictly from environment scopes
    aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    
    if aws_access_key and aws_secret_key:
        base_configs.update({
            "spark.hadoop.fs.s3a.access.key": aws_access_key,
            "spark.hadoop.fs.s3a.secret.key": aws_secret_key
        })

    return SparkSession.builder \
        .config(map=base_configs) \
        .getOrCreate()
