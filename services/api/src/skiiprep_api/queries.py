"""The layer between the endpoints and the data: one method per question.

Endpoints stay short (look up the resort, call one method, return the result),
and all SQL, timezone handling and row-to-model mapping live here, where they
can be tested without HTTP.

Two sources, two classes:
- ResortCatalog: resorts come from config/resorts.yaml (guardrail 9), not the lake.
- ForecastRepository: forecasts come from DuckDB views over silver (db.py).

Timestamps: the views hold TIMESTAMP WITH TIME ZONE. Fetching those into Python
would need the `pytz` package, so every query returns them as naive UTC with
`timezone('UTC', ...)`, and Python attaches the timezone. Grouping by a local
date happens in SQL with `timezone(<resort tz>, ...)`, so "Saturday" is
Saturday at the resort (SD2).
"""
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from skiiprep_common.resorts import Resort, load_resorts

from skiiprep_api.db import IcebergTableQuerier
from skiiprep_api.models import (
    DailyRecord,
    DailyResponse,
    HistoryRecord,
    HistoryResponse,
    HourlyRecord,
    HourlyResponse,
    PointInfo,
    ResortInfo,
)


class NoForecastData(Exception):
    """The table has no forecast for this resort yet. The API answers 503:
    the pipeline hasn't run, which the caller can't fix by changing the request."""


def _utc(naive_utc: datetime) -> datetime:
    """Attach UTC to a naive datetime that a query returned as UTC."""
    return naive_utc.replace(tzinfo=timezone.utc)


class ResortCatalog:
    """Resorts from config, loaded once. Cheap to query: it's a handful of entries."""

    def __init__(self, resorts: dict[str, Resort] | None = None) -> None:
        # Tests pass their own resorts; the API reads config/resorts.yaml.
        self._resorts = resorts if resorts is not None else load_resorts()

    def get(self, resort_id: str) -> Resort | None:
        """The resort with this id, or None. The router turns None into a 404."""
        return self._resorts.get(resort_id)

    def list_resorts(self, state: str | None = None, name: str | None = None) -> list[ResortInfo]:
        """All resorts, optionally filtered by state code and by part of the name."""
        resorts = sorted(self._resorts.values(), key=lambda r: r.name)
        if state:
            resorts = [r for r in resorts if r.state.upper() == state.upper()]
        if name:
            resorts = [r for r in resorts if name.lower() in r.name.lower()]
        return [self._to_info(r) for r in resorts]

    @staticmethod
    def _to_info(resort: Resort) -> ResortInfo:
        return ResortInfo(
            id=resort.id,
            name=resort.name,
            state=resort.state,
            timezone=resort.timezone,
            points=[PointInfo(name=p.name, elevation_m=p.elevation_m) for p in resort.points],
        )


class ForecastRepository:
    """Forecast questions answered with SQL over the DuckDB views.

    Each method takes the config `Resort`, not just its id, because it needs the
    resort's timezone. Each returns a full response model, envelope included.

    The envelope's `fetched_at` is the *oldest* fetch any returned number comes
    from. `view_latest_forecast` takes the newest fetch per hour, but hours the
    newest fetch doesn't cover come from older ones, and reporting the newest
    fetch would overstate how fresh the answer is.
    """

    def __init__(self, querier: IcebergTableQuerier) -> None:
        self._querier = querier

    # --- GET /health --------------------------------------------------------

    def newest_fetched_at(self, resort_id: str | None = None) -> datetime | None:
        """When the newest forecast in the table was fetched, or None if there's none."""
        sql = "SELECT timezone('UTC', max(fetched_at)) AS newest FROM view_weather_hourly"
        params: list[Any] = []
        if resort_id is not None:
            sql += " WHERE resort_id = ?"
            params.append(resort_id)
        newest = self._querier.execute_query(sql, params)[0]["newest"]
        return _utc(newest) if newest is not None else None

    # --- GET /resorts/{id}/forecast/hourly (Q2, Q3, Q4) ---------------------

    def hourly(
        self,
        resort: Resort,
        point: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> HourlyResponse:
        """Hourly rows from the newest forecast, with times in the resort's local time.

        `start` (inclusive) and `end` (exclusive) must be timezone-aware; the
        router makes naive input resort-local before calling this.
        """
        sql = """
            SELECT point,
                   timezone('UTC', valid_time) AS valid_time_utc,
                   timezone('UTC', fetched_at) AS fetched_at_utc,
                   temp_c, feels_like_c, precip_mm, rain_mm, snowfall_cm, snow_depth_m,
                   freezing_level_m, wind_kmh, gust_kmh, weather_code, cloud_cover_pct,
                   visibility_m
            FROM view_latest_forecast
            WHERE resort_id = ?
        """
        params: list[Any] = [resort.id]
        if point is not None:
            sql += " AND point = ?"
            params.append(point)
        if start is not None:
            sql += " AND valid_time >= CAST(? AS TIMESTAMPTZ)"
            params.append(start.isoformat())
        if end is not None:
            sql += " AND valid_time < CAST(? AS TIMESTAMPTZ)"
            params.append(end.isoformat())
        sql += " ORDER BY point, valid_time"

        rows = self._querier.execute_query(sql, params)
        tz = ZoneInfo(resort.timezone)
        items = [
            HourlyRecord(
                **{k: v for k, v in row.items() if k not in ("valid_time_utc", "fetched_at_utc")},
                # Converting in Python, from UTC, gets DST right on the two days it changes.
                valid_time=_utc(row["valid_time_utc"]).astimezone(tz),
            )
            for row in rows
        ]
        oldest = min((row["fetched_at_utc"] for row in rows), default=None)
        return HourlyResponse(
            resort_id=resort.id,
            timezone=resort.timezone,
            fetched_at=self._envelope_fetched_at(resort, oldest),
            items=items,
        )

    # --- GET /resorts/{id}/forecast/daily (Q1–Q5) ---------------------------

    def daily(self, resort: Resort, days: int = 7, start_date: date | None = None) -> DailyResponse:
        """Daily totals and extremes per local day and point, from the newest forecast.

        Covers `days` local dates from `start_date`, which defaults to today at
        the resort. `hours_covered` counts the hours the forecast has for that
        day, so a partial first or last day is visible as such.
        """
        start_date = start_date or datetime.now(ZoneInfo(resort.timezone)).date()
        end_date = start_date + timedelta(days=days)

        rows = self._querier.execute_query(
            """
            WITH local AS (
                SELECT *, CAST(timezone(?, valid_time) AS DATE) AS local_date
                FROM view_latest_forecast
                WHERE resort_id = ?
            )
            SELECT point,
                   local_date AS date,
                   count(*) AS hours_covered,
                   round(sum(snowfall_cm), 2) AS snowfall_cm_total,
                   round(sum(rain_mm), 2) AS rain_mm_total,
                   round(sum(precip_mm), 2) AS precip_mm_total,
                   min(temp_c) AS temp_c_min,
                   max(temp_c) AS temp_c_max,
                   min(feels_like_c) AS feels_like_c_min,
                   max(gust_kmh) AS gust_kmh_max,
                   min(freezing_level_m) AS freezing_level_m_min,
                   timezone('UTC', min(fetched_at)) AS oldest_fetched_at_utc
            FROM local
            WHERE local_date >= ? AND local_date < ?
            GROUP BY point, local_date
            ORDER BY local_date, point
            """,
            [resort.timezone, resort.id, start_date, end_date],
        )
        items = [DailyRecord(**{k: v for k, v in row.items() if k != "oldest_fetched_at_utc"}) for row in rows]
        oldest = min((row["oldest_fetched_at_utc"] for row in rows), default=None)
        return DailyResponse(
            resort_id=resort.id,
            timezone=resort.timezone,
            fetched_at=self._envelope_fetched_at(resort, oldest),
            items=items,
        )

    # --- GET /resorts/{id}/forecast/changes (Q6) ----------------------------

    def history(self, resort: Resort, local_date: date) -> HistoryResponse:
        """How each fetch forecast one local date, per point, oldest fetch first.

        Reads every fetch (`view_weather_hourly`), not just the newest.
        """
        rows = self._querier.execute_query(
            """
            WITH local AS (
                SELECT *, CAST(timezone(?, valid_time) AS DATE) AS local_date
                FROM view_weather_hourly
                WHERE resort_id = ?
            )
            SELECT point,
                   local_date AS date,
                   timezone('UTC', fetched_at) AS fetched_at_utc,
                   count(*) AS hours_covered,
                   round(sum(snowfall_cm), 2) AS snowfall_cm_total,
                   round(sum(rain_mm), 2) AS rain_mm_total,
                   min(temp_c) AS temp_c_min,
                   max(temp_c) AS temp_c_max
            FROM local
            WHERE local_date = ?
            GROUP BY point, local_date, fetched_at
            ORDER BY point, fetched_at
            """,
            [resort.timezone, resort.id, local_date],
        )
        items = [
            HistoryRecord(
                **{k: v for k, v in row.items() if k != "fetched_at_utc"},
                fetched_at=_utc(row["fetched_at_utc"]),
            )
            for row in rows
        ]
        oldest = min((row["fetched_at_utc"] for row in rows), default=None)
        return HistoryResponse(
            resort_id=resort.id,
            timezone=resort.timezone,
            fetched_at=self._envelope_fetched_at(resort, oldest),
            items=items,
        )

    # --- helpers ------------------------------------------------------------

    def _envelope_fetched_at(self, resort: Resort, oldest_naive_utc: datetime | None) -> datetime:
        """The envelope's fetched_at: the oldest fetch used, or, when the filters
        matched nothing, the resort's newest fetch. No data at all raises NoForecastData."""
        if oldest_naive_utc is not None:
            return _utc(oldest_naive_utc)
        newest = self.newest_fetched_at(resort.id)
        if newest is None:
            raise NoForecastData(f"No forecast data for resort '{resort.id}' yet; run ingest and transform")
        return newest
