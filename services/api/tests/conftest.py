"""Shared fixtures for the API tests.

The tests never read the real lake. A small DuckDB table stands in for the silver
table, with the same column types, and is passed to the querier as its source.
FastAPI's dependencies are overridden to use it, and `TestClient(app)` is used
*without* a `with` block, so the app's lifespan (which opens the real table)
never runs.

Fixture data, for resort `testpeak` (America/Los_Angeles, UTC-7 in October):

    fetch F1 = 2026-10-20 05:00 UTC (older)    fetch F2 = 2026-10-20 23:00 UTC (newer)

    point   valid_time (UTC)  local time        F1 snowfall  F2 snowfall
    base    21st 05:00        20th 22:00        1.0          2.0
    base    21st 06:00        20th 23:00        1.0          2.0
    base    21st 07:00        21st 00:00        1.0          3.0
    base    21st 08:00        21st 01:00        1.0          3.0
    base    21st 09:00        21st 02:00        1.0          (not in F2)
    summit  21st 07:00        21st 00:00        -            5.0

Plus one row for `otherpeak`, which must never leak into testpeak's answers.
The hours cross local midnight, so a test grouping by UTC date instead of local
date would fail.
"""
from datetime import datetime, timezone

import duckdb
import pytest
from fastapi.testclient import TestClient

from skiiprep_common.resorts import Point, Resort

from skiiprep_api.db import IcebergTableQuerier
from skiiprep_api.main import app, get_forecasts, get_resort_catalog
from skiiprep_api.queries import ForecastRepository, ResortCatalog

from api_fixture_data import F1, F2, ROWS, SILVER_SCHEMA  # noqa: F401 (F1, F2 used by tests)


def make_querier(rows: list[tuple]) -> IcebergTableQuerier:
    """A connected querier whose views read an in-memory table holding `rows`."""
    con = duckdb.connect()
    con.execute(f"CREATE TABLE silver_fixture ({SILVER_SCHEMA})")
    for resort_id, point, hour, fetched_at, snowfall_cm, temp_c in rows:
        valid_time = datetime(2026, 10, 21, hour, tzinfo=timezone.utc)
        # Only the columns the tests check are set; the rest stay NULL, which also
        # checks that NULLs come through as null, never as 0.
        con.execute(
            """INSERT INTO silver_fixture (resort_id, point, valid_time, fetched_at, source,
                                           elevation_m, snowfall_cm, temp_c)
               VALUES (?, ?, ?, ?, 'open_meteo', 1341, ?, ?)""",
            [resort_id, point, valid_time.isoformat(), fetched_at.isoformat(), snowfall_cm, temp_c],
        )
    querier = IcebergTableQuerier(source_sql="silver_fixture", connection=con)
    querier.connect()
    return querier


def make_resort(resort_id: str, name: str, state: str) -> Resort:
    return Resort(
        id=resort_id,
        name=name,
        state=state,
        pass_="ikon",
        timezone="America/Los_Angeles",
        points=(
            Point(name="base", latitude=46.9, longitude=-121.4, elevation_m=1341),
            Point(name="summit", latitude=46.9, longitude=-121.5, elevation_m=2094),
        ),
    )


@pytest.fixture
def querier():
    q = make_querier(ROWS)
    yield q
    q.close()


@pytest.fixture
def empty_querier():
    """The same table with no rows: the pipeline hasn't run yet."""
    q = make_querier([])
    yield q
    q.close()


@pytest.fixture
def catalog() -> ResortCatalog:
    """Resorts passed in directly, so the tests don't depend on config/resorts.yaml."""
    return ResortCatalog(resorts={
        "testpeak": make_resort("testpeak", "Test Peak", "WA"),
        "otherpeak": make_resort("otherpeak", "Other Peak", "CO"),
    })


@pytest.fixture
def repo(querier) -> ForecastRepository:
    return ForecastRepository(querier)


def _client(querier: IcebergTableQuerier, catalog: ResortCatalog):
    app.dependency_overrides[get_forecasts] = lambda: ForecastRepository(querier)
    app.dependency_overrides[get_resort_catalog] = lambda: catalog
    # No `with`: the lifespan, which would open the real table, doesn't run.
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def client(querier, catalog):
    yield from _client(querier, catalog)


@pytest.fixture
def empty_client(empty_querier, catalog):
    yield from _client(empty_querier, catalog)
