"""Tests for the weather silver job: bronze envelopes in a temp folder, MERGEd into
an Iceberg table in a temp warehouse. No real API calls and nothing under data/."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

from skiiprep_transformation.jobs.weather_hourly import execute
from skiiprep_transformation.tables.weather_hourly import WeatherHourlyTable

pytestmark = pytest.mark.spark

TABLE = WeatherHourlyTable.full_table_name
GRAIN = ["resort_id", "point", "valid_time", "fetched_at"]
# Everything except the audit columns (dw_processing_time, last_changed_at), which
# are allowed to differ between runs (SD14).
DATA_COLUMNS = GRAIN + [
    "source", "elevation_m", "temp_c", "feels_like_c", "precip_mm", "rain_mm",
    "snowfall_cm", "snow_depth_m", "freezing_level_m", "wind_kmh", "gust_kmh",
    "weather_code", "cloud_cover_pct", "visibility_m", "bronze_file",
]

FETCHED_AT = datetime(2026, 10, 20, 5, 45, 11, 818429, tzinfo=timezone.utc)
HOURS = ["2026-10-20T00:00", "2026-10-20T01:00"]
ELEVATION = {"base": 1341, "summit": 2094}


def write_bronze(root: Path, point: str, fetched_at: datetime = FETCHED_AT,
                 temps: tuple[float, float] = (3.8, 3.1)) -> Path:
    """Write one envelope shaped like the ingest job's output, for two hours."""
    hourly = {
        "time": HOURS,
        "temperature_2m": list(temps),
        "apparent_temperature": [0.8, 0.2],
        "precipitation": [0.0, 0.4],
        "rain": [0.0, 0.1],
        "snowfall": [0.0, 0.3],
        "snow_depth": [0.0, 0.01],
        "freezing_level_height": [2660.0, 2500.0],
        "wind_speed_10m": [7.9, 9.2],
        "wind_gusts_10m": [9.0, 15.1],
        "weather_code": [0, 71],
        "cloud_cover": [9, 100],
        "visibility": [14900.0, 800.0],
    }
    envelope = {
        "source": "open_meteo",
        "resort_id": "crystal",
        "point": point,
        "elevation_m": ELEVATION[point],
        "fetched_at": fetched_at.isoformat(),
        "request": {"url": "https://api.open-meteo.com/v1/forecast", "params": {}},
        "response": {"timezone": "UTC", "utc_offset_seconds": 0, "hourly": hourly},
    }
    stamp = fetched_at.strftime("%Y-%m-%dT%H%M%SZ")
    path = root / "resort_id=crystal" / f"point={point}" / f"{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope, indent=2))
    return path


@pytest.fixture
def bronze(tmp_path: Path) -> Path:
    """A bronze folder with one fetch for base and one for summit."""
    root = tmp_path / "bronze" / "open_meteo"
    write_bronze(root, "base")
    write_bronze(root, "summit")
    return root


@pytest.fixture(autouse=True)
def empty_table(spark: SparkSession):
    """Each test starts without the table; the job must create it."""
    spark.sql(f"DROP TABLE IF EXISTS {TABLE} PURGE")
    yield


def data_rows(spark: SparkSession) -> list[tuple]:
    return sorted(tuple(r) for r in spark.table(TABLE).select(*DATA_COLUMNS).collect())


def file_count(spark: SparkSession) -> int:
    return spark.sql(f"SELECT count(*) FROM {TABLE}.files").collect()[0][0]


def one_row(spark: SparkSession, point: str, valid_time_utc: str):
    """The row for one point and hour. Filtering in SQL uses the session timezone (UTC)."""
    return spark.table(TABLE).where(
        f"point = '{point}' AND valid_time = TIMESTAMP '{valid_time_utc}'").collect()[0]


def utc_text(spark: SparkSession, column: str, where: str) -> str:
    """A timestamp column formatted inside Spark, so it shows UTC.

    collect() would turn it into a Python datetime in the machine's *local* time
    (e.g. PDT), which is a trap for SD2: compare absolute times in Spark, not Python.
    """
    return spark.sql(
        f"SELECT date_format({column}, 'yyyy-MM-dd HH:mm:ss.SSSSSS') FROM {TABLE} WHERE {where}"
    ).collect()[0][0]


def test_creates_table_with_audit_columns(spark, bronze):
    """The job creates the table itself, including both audit columns."""
    execute(spark=spark, bronze_dir=bronze)

    columns = spark.table(TABLE).columns
    assert "dw_processing_time" in columns
    assert "last_changed_at" in columns


def test_one_row_per_point_and_hour(spark, bronze):
    """Parallel arrays become rows: 2 points × 2 hours = 4 rows, grain unique."""
    execute(spark=spark, bronze_dir=bronze)

    table = spark.table(TABLE)
    assert table.count() == 4
    assert table.select(*GRAIN).distinct().count() == 4


def test_maps_and_types_values(spark, bronze):
    """Times parse as UTC timestamps; values land in the unit-named columns."""
    execute(spark=spark, bronze_dir=bronze)

    where = "point = 'summit' AND valid_time = TIMESTAMP '2026-10-20 01:00:00'"
    row = one_row(spark, "summit", "2026-10-20 01:00:00")  # exists, so time parsed as UTC
    assert utc_text(spark, "fetched_at", where) == "2026-10-20 05:45:11.818429"
    assert row.elevation_m == 2094
    assert row.temp_c == 3.1
    assert row.snowfall_cm == 0.3
    assert row.weather_code == 71
    assert row.cloud_cover_pct == 100
    assert row.bronze_file.endswith("point=summit/2026-10-20T054511Z.json")
    assert row.last_changed_at == row.dw_processing_time  # set together on insert


def test_parses_fetched_at_on_a_whole_second(spark, tmp_path):
    """isoformat() drops the fraction when microseconds are 0; that file must still load."""
    root = tmp_path / "open_meteo"
    write_bronze(root, "base", fetched_at=datetime(2026, 10, 20, 5, 45, 11, tzinfo=timezone.utc))

    execute(spark=spark, bronze_dir=root)

    assert utc_text(spark, "fetched_at", "point = 'base'") == "2026-10-20 05:45:11.000000"


def test_rerun_changes_no_data_and_writes_no_files(spark, bronze):
    """Idempotency: the same bronze twice leaves the data and the data files as they were."""
    execute(spark=spark, bronze_dir=bronze)
    rows, files = data_rows(spark), file_count(spark)
    first_load = spark.table(TABLE).select("dw_processing_time").distinct().collect()

    execute(spark=spark, bronze_dir=bronze)

    assert data_rows(spark) == rows
    assert file_count(spark) == files  # unchanged rows aren't rewritten (SD14)
    assert spark.table(TABLE).select("dw_processing_time").distinct().collect() == first_load


def test_new_fetch_adds_rows(spark, bronze):
    """A later fetch of the same hours is a different forecast, so it adds rows."""
    execute(spark=spark, bronze_dir=bronze)
    later = datetime(2026, 10, 20, 23, 2, 27, 172644, tzinfo=timezone.utc)
    write_bronze(bronze, "base", fetched_at=later)

    execute(spark=spark, bronze_dir=bronze)

    assert spark.table(TABLE).count() == 6  # 4 + 2 hours of the new base fetch


def test_changed_value_updates_row_and_last_changed_at(spark, bronze, tmp_path):
    """A corrected value for an existing grain (e.g. a reprocessed file) updates the row,
    moves last_changed_at and bronze_file, and keeps dw_processing_time."""
    execute(spark=spark, bronze_dir=bronze)
    before = one_row(spark, "base", "2026-10-20 00:00:00")

    # Same point and fetched_at, so the same grain, but a different temperature.
    corrected = tmp_path / "corrected" / "open_meteo"
    write_bronze(corrected, "base", temps=(-1.5, 3.1))
    execute(spark=spark, bronze_dir=corrected)

    # Comparing audit times with each other is fine in Python: both are shifted alike.
    changed = one_row(spark, "base", "2026-10-20 00:00:00")
    unchanged = one_row(spark, "base", "2026-10-20 01:00:00")

    assert changed.temp_c == -1.5
    assert changed.last_changed_at > before.last_changed_at
    assert changed.dw_processing_time == before.dw_processing_time
    assert "corrected" in changed.bronze_file
    # Hour 1 had identical values, so it wasn't touched.
    assert unchanged.last_changed_at == before.last_changed_at
    assert "corrected" not in unchanged.bronze_file
    assert spark.table(TABLE).count() == 4
