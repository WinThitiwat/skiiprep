"""Tests for the DuckDB layer: the session settings and the two views."""
from api_fixture_data import F2


def test_cursors_use_utc(querier):
    """Every query runs on a new cursor; SET GLOBAL makes UTC their default too."""
    assert querier.execute_query("SELECT current_setting('TimeZone') AS tz") == [{"tz": "UTC"}]


def test_rows_come_back_as_dicts(querier):
    rows = querier.execute_query("SELECT point, snowfall_cm FROM view_weather_hourly LIMIT 1")
    assert set(rows[0]) == {"point", "snowfall_cm"}


def test_ddl_returns_no_rows(querier):
    assert querier.execute_query("CREATE VIEW scratch AS SELECT 1") == []


def test_weather_hourly_keeps_every_fetch(querier):
    n = querier.execute_query("SELECT count(*) AS n FROM view_weather_hourly")[0]["n"]
    assert n == 11


def test_latest_forecast_keeps_newest_fetch_per_hour(querier):
    """One row per resort, point and hour, from the newest fetch that covers that hour."""
    rows = querier.execute_query("""
        SELECT point, hour(valid_time) AS h, snowfall_cm, timezone('UTC', fetched_at) AS f
        FROM view_latest_forecast WHERE resort_id = 'testpeak' ORDER BY point, h
    """)
    assert [(r["point"], r["h"], r["snowfall_cm"]) for r in rows] == [
        ("base", 5, 2.0), ("base", 6, 2.0), ("base", 7, 3.0), ("base", 8, 3.0),
        ("base", 9, 1.0),  # only F1 covers 09:00, so the older fetch is the latest for it
        ("summit", 7, 5.0),
    ]
    assert rows[0]["f"] == F2.replace(tzinfo=None)


def test_query_before_connect_is_an_error():
    from skiiprep_api.db import IcebergTableQuerier
    import pytest

    with pytest.raises(RuntimeError):
        IcebergTableQuerier(source_sql="silver_fixture").execute_query("SELECT 1")
