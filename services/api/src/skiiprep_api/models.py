"""Response models: the API's contract, and later the MCP tools' contract (phase 4).

Field names carry their units (guardrail 8). Nullable values are `| None`, since
silver keeps NULL for "no data" and never writes 0 in its place.

Resort configuration itself (`Point`, `Resort`, `ResortsConfig` for reading the YAML)
lives in `skiiprep_common.resorts`. These models describe what the API returns.
"""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class Envelope(BaseModel):
    """Carried by every forecast answer, so every answer says which resort, which
    timezone and how fresh its data is (requirements, freshness)."""

    resort_id: str
    timezone: str  # IANA name, e.g. America/Los_Angeles. Tells the caller what "Saturday" means
    fetched_at: datetime  # when the data used was fetched, in UTC (SD2)


# --- Discovery: GET /resorts ----------------------------------------------------

class PointInfo(BaseModel):
    name: str  # base or summit
    elevation_m: int  # the height the forecast was adjusted to (SD1)


class ResortInfo(BaseModel):
    """Configuration, not a forecast, so it has no fetched_at."""

    id: str
    name: str
    state: str
    timezone: str
    points: list[PointInfo]


class ResortsResponse(BaseModel):
    items: list[ResortInfo]


# --- Forecast rows --------------------------------------------------------------

class HourlyRecord(BaseModel):
    """One hour at one point. Used for Q2, Q3 and Q4 in detail."""

    point: str
    valid_time: datetime  # the hour this row is for, as an aware datetime in the resort's local timezone
    temp_c: float | None
    feels_like_c: float | None
    precip_mm: float | None
    rain_mm: float | None
    snowfall_cm: float | None
    snow_depth_m: float | None
    freezing_level_m: float | None
    wind_kmh: float | None
    gust_kmh: float | None
    weather_code: int | None
    cloud_cover_pct: int | None
    visibility_m: float | None


class DailyRecord(BaseModel):
    """One local day at one point, from the newest fetch. Answers Q1–Q5.

    `hours_covered` says how many of the day's 24 hours the forecast includes.
    The first and last local day are usually partial (SD2), so a total with
    fewer than 24 hours is incomplete, not small.
    """

    point: str
    date: date  # a local calendar date in the resort's timezone
    hours_covered: int
    snowfall_cm_total: float | None
    rain_mm_total: float | None
    precip_mm_total: float | None
    temp_c_min: float | None
    temp_c_max: float | None
    feels_like_c_min: float | None
    gust_kmh_max: float | None
    freezing_level_m_min: float | None


class HistoryRecord(BaseModel):
    """One local day at one point, as one specific fetch saw it. Answers Q6.

    The `changes` endpoint returns one of these per fetch, oldest to newest, so the
    caller can see whether the forecast for a day got better or worse.
    """

    point: str
    date: date
    fetched_at: datetime  # which fetch made this forecast (not when it was loaded into silver)
    hours_covered: int
    snowfall_cm_total: float | None
    rain_mm_total: float | None
    temp_c_min: float | None
    temp_c_max: float | None


# --- Response wrappers: one per endpoint ----------------------------------------

class HourlyResponse(Envelope):
    items: list[HourlyRecord]


class DailyResponse(Envelope):
    items: list[DailyRecord]


class HistoryResponse(Envelope):
    items: list[HistoryRecord]


class HealthResponse(BaseModel):
    """Lets a caller (the MCP server, phase 4) explain a failure without guessing."""

    status: Literal["ok", "no_data"]
    table: str
    newest_fetched_at: datetime | None  # None when the table is empty
