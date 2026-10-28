"""Response models: the API's contract, and later the MCP tools' contract (phase 4).

Field names carry their units (guardrail 8). Nullable values are `| None`, since
silver keeps NULL for "no data" and never writes 0 in its place.

Every field has a `description`. FastAPI shows them in `/docs` and in the OpenAPI
schema, which is also what the MCP tools (phase 4) and an LLM read to understand
a field. The hourly descriptions follow the column comments of the silver table.

Resort configuration itself (`Point`, `Resort`, `ResortsConfig` for reading the YAML)
lives in `skiiprep_common.resorts`. These models describe what the API returns.
"""
from datetime import date as Date, datetime  # alias: a field named `date` would hide the type
from typing import Literal

from pydantic import BaseModel, Field


class Envelope(BaseModel):
    """Carried by every forecast answer, so every answer says which resort, which
    timezone and how fresh its data is (requirements, freshness)."""

    resort_id: str = Field(description="Stable resort id from config/resorts.yaml, e.g. crystal.")
    timezone: str = Field(
        description="The resort's IANA timezone, e.g. America/Los_Angeles. "
        "All local times and dates in this answer use it.",
    )
    fetched_at: datetime = Field(
        description="When the data in this answer was fetched from the source, in UTC (SD2). "
        "If the answer combines several fetches, this is the oldest of them, "
        "so the answer is never shown as fresher than it is.",
    )


# --- Discovery: GET /resorts ----------------------------------------------------

class PointInfo(BaseModel):
    name: str = Field(description="Point name within the resort: base or summit.")
    elevation_m: int = Field(description="Elevation in meters that the forecast is adjusted to (SD1).")


class ResortInfo(BaseModel):
    """Configuration, not a forecast, so it has no fetched_at."""

    id: str = Field(description="Stable resort id, used in every forecast URL, e.g. crystal.")
    name: str = Field(description="Display name, e.g. Crystal Mountain.")
    state: str = Field(description="Two-letter US state code, e.g. WA.")
    timezone: str = Field(description="The resort's IANA timezone, e.g. America/Los_Angeles.")
    points: list[PointInfo] = Field(description="The points the resort has forecasts for.")


class ResortsResponse(BaseModel):
    items: list[ResortInfo] = Field(description="The matching resorts, sorted by name.")


# --- Forecast rows --------------------------------------------------------------

class HourlyRecord(BaseModel):
    """One hour at one point. Used for Q2, Q3 and Q4 in detail."""

    point: str = Field(description="Point name within the resort: base or summit.")
    valid_time: datetime = Field(
        description="The hour this row is for, in the resort's local time with its UTC offset.",
    )
    temp_c: float | None = Field(description="Air temperature at 2 meters above ground, in Celsius.")
    feels_like_c: float | None = Field(
        description="Apparent temperature in Celsius: how cold or warm it feels, "
        "combining temperature, wind, humidity and radiation.",
    )
    precip_mm: float | None = Field(
        description="Total precipitation (rain, showers, snow as water) in the preceding hour, in millimeters.",
    )
    rain_mm: float | None = Field(
        description="Rain from large-scale weather systems in the preceding hour, in millimeters. Excludes showers.",
    )
    snowfall_cm: float | None = Field(description="Snowfall in the preceding hour, in centimeters.")
    snow_depth_m: float | None = Field(description="Snow depth on the ground, in meters.")
    freezing_level_m: float | None = Field(
        description="Altitude above sea level, in meters, of the 0 Celsius level. "
        "Below the point's elevation means snow, above it means rain is possible.",
    )
    wind_kmh: float | None = Field(description="Wind speed at 10 meters above ground, in km/h.")
    gust_kmh: float | None = Field(
        description="Maximum wind gust at 10 meters above ground in the preceding hour, in km/h.",
    )
    weather_code: int | None = Field(description="Weather condition as a WMO weather interpretation code.")
    cloud_cover_pct: int | None = Field(description="Total cloud cover in percent, from 0 to 100.")
    visibility_m: float | None = Field(
        description="Viewing distance in meters. Reduced by low cloud, humidity and aerosols.",
    )


class DailyRecord(BaseModel):
    """One local day at one point, from the newest fetch. Answers Q1–Q5.

    `hours_covered` says how many of the day's 24 hours the forecast includes.
    The first and last local day are usually partial (SD2), so a total with
    fewer than 24 hours is incomplete, not small.
    """

    point: str = Field(description="Point name within the resort: base or summit.")
    date: Date = Field(description="A local calendar date in the resort's timezone.")
    hours_covered: int = Field(
        description="How many of the day's 24 local hours the forecast includes. "
        "Fewer than 24 means the totals below are for part of the day only.",
    )
    snowfall_cm_total: float | None = Field(description="Total snowfall over the covered hours, in centimeters.")
    rain_mm_total: float | None = Field(description="Total rain over the covered hours, in millimeters.")
    precip_mm_total: float | None = Field(
        description="Total precipitation (rain, showers, snow as water) over the covered hours, in millimeters.",
    )
    temp_c_min: float | None = Field(description="Lowest hourly air temperature of the day, in Celsius.")
    temp_c_max: float | None = Field(description="Highest hourly air temperature of the day, in Celsius.")
    feels_like_c_min: float | None = Field(description="Lowest hourly apparent temperature of the day, in Celsius.")
    gust_kmh_max: float | None = Field(description="Strongest wind gust of the day, in km/h.")
    freezing_level_m_min: float | None = Field(
        description="Lowest freezing level of the day, in meters above sea level.",
    )


class HistoryRecord(BaseModel):
    """One local day at one point, as one specific fetch saw it. Answers Q6.

    The `changes` endpoint returns one of these per fetch, oldest to newest, so the
    caller can see whether the forecast for a day got better or worse.
    """

    point: str = Field(description="Point name within the resort: base or summit.")
    date: Date = Field(description="The local calendar date this forecast is for, in the resort's timezone.")
    fetched_at: datetime = Field(
        description="When this forecast was fetched from the source, in UTC. "
        "Not when it was loaded into silver.",
    )
    hours_covered: int = Field(description="How many of the day's 24 local hours this fetch includes.")
    snowfall_cm_total: float | None = Field(description="Total snowfall over the covered hours, in centimeters.")
    rain_mm_total: float | None = Field(description="Total rain over the covered hours, in millimeters.")
    temp_c_min: float | None = Field(description="Lowest hourly air temperature of the day, in Celsius.")
    temp_c_max: float | None = Field(description="Highest hourly air temperature of the day, in Celsius.")


# --- Response wrappers: one per endpoint ----------------------------------------

class HourlyResponse(Envelope):
    items: list[HourlyRecord] = Field(description="One row per hour, oldest hour first.")


class DailyResponse(Envelope):
    items: list[DailyRecord] = Field(description="One row per local day and point, by date then point.")


class HistoryResponse(Envelope):
    items: list[HistoryRecord] = Field(
        description="One row per fetch and point for the requested day, oldest fetch first.",
    )


class HealthResponse(BaseModel):
    """Lets a caller (the MCP server, phase 4) explain a failure without guessing."""

    status: Literal["ok", "no_data"] = Field(
        description="ok when the table has data. no_data when the pipeline hasn't loaded anything yet.",
    )
    table: str = Field(description="The silver table the API reads.")
    newest_fetched_at: datetime | None = Field(
        description="The most recent fetch in the table, in UTC. Null when the table is empty.",
    )
