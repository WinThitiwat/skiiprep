"""Shared fixtures for the transformation tests.

Starting Spark takes seconds, so all Spark tests share one session per test run.
Its Iceberg warehouse is a temp folder, so tests never touch data/.
"""
import pytest
from pyspark.sql import SparkSession

from skiiprep_transformation.spark import get_spark


@pytest.fixture(scope="session")
def spark(tmp_path_factory: pytest.TempPathFactory) -> SparkSession:
    warehouse = tmp_path_factory.mktemp("warehouse")
    session = get_spark(env="test", warehouse_dir=warehouse)
    session.sparkContext.setLogLevel("ERROR")

    # getOrCreate() reuses a session that already exists, with its old settings.
    # Fail loudly rather than run the tests against the real warehouse.
    assert session.conf.get("spark.sql.catalog.lake.warehouse") == str(warehouse)

    yield session
    session.stop()
