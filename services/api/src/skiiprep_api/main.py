"""FastAPI app: `uv run --package skiiprep-api uvicorn skiiprep_api.main:app --reload`.

Endpoints stay short: look up the resort, call one method in queries.py,
return the response model. Interactive docs at http://localhost:8000/docs.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query, Request, status, HTTPException
from datetime import date, datetime
from zoneinfo import ZoneInfo

import duckdb
from skiiprep_common.settings import SILVER_WEATHER_TABLE_DIR

from skiiprep_api import db, helper
from skiiprep_api.models import ResortsResponse, HealthResponse, HourlyResponse, DailyResponse, HistoryResponse
from skiiprep_api.queries import ForecastRepository, NoForecastData, ResortCatalog

# Shown by /health: namespace.table, e.g. weather.silver_weather_hourly. Taken from
# the settings path rather than imported from transformation (guardrail 4).
SILVER_WEATHER_TABLE_NAME = f"{SILVER_WEATHER_TABLE_DIR.parent.name}.{SILVER_WEATHER_TABLE_DIR.name}"

# main.py is the entry point, so this is where logging is configured.
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the DuckDB connection and load the resort config once, at startup.

    Doing it here, before any request, means requests never race to open a
    connection. `app.state` belongs to this app, so a test app gets its own.
    """
    app.state.querier = db.startup()
    app.state.resorts = ResortCatalog()
    try:
        yield  # the app serves requests here
    finally:
        app.state.querier.close()


app = FastAPI(title="SkiiPrep API", lifespan=lifespan)


# --- Dependencies: how an endpoint gets what it needs --------------------------
# Tests override these with app.dependency_overrides to swap in fakes.

def get_resort_catalog(request: Request) -> ResortCatalog:
    return request.app.state.resorts


def get_forecasts(request: Request) -> ForecastRepository:
    return ForecastRepository(request.app.state.querier)


# --- Endpoints -------------------------------------------------------------------

@app.get(
    "/api/v1/resorts",
    response_model=ResortsResponse,
    summary="List resorts",
    description="Resorts from config/resorts.yaml, with their points, elevations and timezone.",
    status_code=status.HTTP_200_OK
)
def list_resorts(
    state: str | None = Query(None, description="Two-letter state code, e.g. WA"),
    name: str | None = Query(None, description="Part of the resort name, case-insensitive"),
    limit: int = Query(50, ge=1, le=250, description="Maximum number of resorts to return"),
    catalog: ResortCatalog = Depends(get_resort_catalog),
) -> ResortsResponse:
    return ResortsResponse(items=catalog.list_resorts(state=state, name=name)[:limit]) 
    

@app.get(
    "/api/v1/health",
    response_model=HealthResponse,
    summary="Check the forecast data is readable",
    description=(
        "Reports whether the silver forecast table can be read and when its newest forecast was fetched. "
        "`status` is `no_data` when the table is empty, so a caller (the MCP server) can say "
        "\"run the pipeline first\" instead of guessing."
    ),
)
def get_health(
    forecast_repo: ForecastRepository = Depends(get_forecasts),
) -> HealthResponse:
    try:
        newest = forecast_repo.newest_fetched_at()
    except duckdb.Error as e:
        # The table can't be read at all (e.g. its files were removed after
        # startup). That's not a request problem, so 503, with DuckDB's reason.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Can't read the forecast table: {e}",
        )

    # An empty table is still a working API, so this is a 200 that says so,
    # not an error. newest_fetched_at() returns None when there are no rows.
    return HealthResponse(
        status="ok" if newest is not None else "no_data",
        table=SILVER_WEATHER_TABLE_NAME,
        newest_fetched_at=newest,
    )

@app.get(
    "/api/v1/resorts/{resort_id}/forecast/hourly",
    response_model=HourlyResponse,
    summary="Get hourly weather forecast from the given resort_id",
    description="Get hourly weather forecast from the given resort_id",
)
def get_hourly_forecast(
    resort_id: str,
    point: str = Query(..., description="Point name at the resort, e.g. base or summit"),
    start: datetime = Query(..., description="First hour, inclusive. Without an offset it's read as resort local time"),
    end: datetime | None = Query(None, description="End, exclusive. Without an offset it's read as resort local time"),
    forecast_repo: ForecastRepository = Depends(get_forecasts),
    catalog: ResortCatalog = Depends(get_resort_catalog)
) -> HourlyResponse:
    resort_obj = catalog.get(resort_id=resort_id)
    if not resort_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"`{resort_id}` was not found in the resort's catalog."
        )

    # An unknown point would otherwise return 200 with an empty list.
    point_names = [p.name for p in resort_obj.points]
    if point not in point_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unknown point `{point}` for `{resort_id}`; use one of {point_names}.",
        )

    # A time without an offset (e.g. 2026-10-21T06:00) means that time at the
    # resort, not UTC: "6am" is 6am in Seattle (SD2).
    resort_tz = ZoneInfo(resort_obj.timezone)
    start = helper.as_resort_local(start, resort_tz)
    end = helper.as_resort_local(end, resort_tz) if end is not None else None
    if end is not None and end <= start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="`end` must be after `start`.",
        )

    try:
        # Always returns a response; empty `items` just means no hours matched.
        return forecast_repo.hourly(resort=resort_obj, point=point, start=start, end=end)
    except NoForecastData as e:
        # No data at all for this resort: the pipeline hasn't run, which the
        # caller can't fix by changing the request.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))


@app.get(
    "/api/v1/resorts/{resort_id}/forecast/daily",
    response_model=DailyResponse,
    summary="Daily forecast per local day and point",
    description=(
        "Totals and extremes per local calendar day and point, from the newest forecast. "
        "`hours_covered` below 24 means the forecast only has part of that day."
    ),
)
def get_daily_forecast(
    resort_id: str,
    days: int = Query(7, ge=1, le=16, description="Number of local days to return (Open-Meteo forecasts at most 16)"),
    # A date, not a datetime: a calendar date is already "at the resort", so there's
    # no timezone to convert. Default None, not date.today(): a default is evaluated
    # once when the module loads, and in the server's timezone, not the resort's.
    start: date | None = Query(None, description="First local date, inclusive, e.g. 2026-10-21. Defaults to today at the resort"),
    forecast_repo: ForecastRepository = Depends(get_forecasts),
    catalog: ResortCatalog = Depends(get_resort_catalog)
) -> DailyResponse:
    resort_obj = catalog.get(resort_id=resort_id)
    if not resort_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"`{resort_id}` was not found in the resort's catalog."
        )

    try:
        # start=None makes daily() use today at the resort, computed per request.
        # Always returns a response; empty `items` just means no days matched.
        return forecast_repo.daily(resort=resort_obj, days=days, start_date=start)
    except NoForecastData as e:
        # No data at all for this resort: the pipeline hasn't run, which the
        # caller can't fix by changing the request.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

@app.get(
    "/api/v1/resorts/{resort_id}/forecast/changes",
    response_model=HistoryResponse,
    summary="How the forecast for one local day changed between fetches",
    description=(
        "For one local date, the daily totals from each fetch, oldest first, per point. "
        "Answers \"did the forecast for Saturday get better or worse?\" (Q6)."
    ),
)
def get_history_change(
    resort_id: str,
    # Named local_date in Python so it doesn't hide the `date` type; the URL still says ?date=.
    local_date: date = Query(..., alias="date", description="Local date at the resort, e.g. 2026-10-25"),
    forecast_repo: ForecastRepository = Depends(get_forecasts),
    catalog: ResortCatalog = Depends(get_resort_catalog)
) -> HistoryResponse:
    resort_obj = catalog.get(resort_id=resort_id)
    if not resort_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"`{resort_id}` was not found in the resort's catalog."
        )

    try:
        # Always returns a response; empty `items` means no fetch covered that date.
        return forecast_repo.history(resort=resort_obj, local_date=local_date)
    except NoForecastData as e:
        # No data at all for this resort: the pipeline hasn't run, which the
        # caller can't fix by changing the request.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
