"""Fetch Open-Meteo hourly forecasts and save each response to bronze.

One file per point per fetch, saved exactly as received inside a lineage
envelope. Files are never overwritten (see docs/phases/phase-01-bronze-ingest.md).
"""
import json
import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from skiiprep_common.resorts import Point, Resort
from skiiprep_common.settings import DATA_BRONZE_DIR

logger = logging.getLogger(__name__)

SOURCE = "open_meteo"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# The 12 hourly variables silver needs. Order doesn't matter to the API.
HOURLY_VARIABLES = (
    "temperature_2m",
    "apparent_temperature",
    "precipitation",
    "rain",
    "snowfall",
    "snow_depth",
    "freezing_level_height",
    "wind_speed_10m",
    "wind_gusts_10m",
    "weather_code",
    "cloud_cover",
    "visibility",
)
FORECAST_DAYS = 7

# Open-Meteo doesn't require a User-Agent, but a descriptive one is polite.
USER_AGENT = "skiiprep/0.1 (personal ski trip assistant)"
TIMEOUT_S = 10.0


def build_params(point: Point) -> dict[str, Any]:
    """Query parameters for one point's forecast.

    Latitude, longitude and elevation all come from the same point, so the
    API downscales temperature to that point's height (SD1). Times come back
    in UTC (SD2).
    """
    return {
        "latitude": point.latitude,
        "longitude": point.longitude,
        "elevation": point.elevation_m,
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": "UTC",
        "forecast_days": FORECAST_DAYS,
    }


def bronze_path(
    resort_id: str,
    point_name: str,
    fetched_at: datetime,
    root: Path = DATA_BRONZE_DIR,
) -> Path:
    """Where one fetch is stored, e.g.
    <root>/open_meteo/resort_id=crystal/point=summit/2026-10-20T005105Z.json

    Only builds the path; it doesn't touch the disk. `root` is a parameter so
    tests can point it at a temp folder.
    """
    if not resort_id or not point_name:
        raise ValueError("resort_id and point_name must not be empty")
    # A naive datetime has no timezone, so we can't know it's UTC. Refuse it
    # rather than writing a file name that claims `Z` for a local time.
    if fetched_at.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware (UTC)")

    # No colons: they're awkward in file names.
    file_name = fetched_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ") + ".json"
    return root / SOURCE / f"resort_id={resort_id}" / f"point={point_name}" / file_name


def fetch_point(
    client: httpx.Client,
    resort: Resort,
    point: Point,
    root: Path = DATA_BRONZE_DIR,
    fetched_at: datetime | None = None,
) -> Path:
    """GET one point's forecast, wrap it in the envelope and write it to bronze.

    Returns the path of the file written. If the request fails, it raises
    before anything is written, so an error body never lands in bronze.
    `fetched_at` defaults to now; tests pass a fixed value.
    """
    params = build_params(point)
    fetched_at = fetched_at or datetime.now(timezone.utc)

    response = client.get(FORECAST_URL, params=params)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        # The exception only names the status and URL; the body has the reason.
        logger.error(
            "Open-Meteo request failed for %s/%s: %s %s",
            resort.id, point.name, response.status_code, response.text,
        )
        raise

    # The envelope adds what the response doesn't say: which point we asked
    # for and when. The API snaps coordinates to its grid, so the request
    # params are the only record of what we actually requested.
    envelope = {
        "source": SOURCE,
        "resort_id": resort.id,
        "point": point.name,
        "elevation_m": point.elevation_m,
        "fetched_at": fetched_at.astimezone(timezone.utc).isoformat(),
        "request": {"url": FORECAST_URL, "params": params},
        "response": response.json(),
    }

    path = bronze_path(resort.id, point.name, fetched_at, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # "x" fails if the file already exists: bronze is never overwritten.
    with path.open("x", encoding="utf-8") as f:
        json.dump(envelope, f, ensure_ascii=False, indent=2)

    logger.info("Wrote %s", path)
    return path


def ingest(
    resorts: Iterable[Resort],
    client: httpx.Client | None = None,
    root: Path = DATA_BRONZE_DIR,
) -> list[Path]:
    """Fetch every point of every resort. Returns the files written, in order.

    Pass a `client` to control how requests are made (tests use
    `httpx.MockTransport`). Without one, a client with a timeout is created
    here and closed at the end. A client passed in is left open for the
    caller to close.
    """
    if client is None:
        with httpx.Client(timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT}) as own_client:
            return ingest(resorts, client=own_client, root=root)

    # One shared timestamp per run would also work; per-point timestamps keep
    # each file's name and envelope honest about when it was actually fetched.
    # If one point fails, the run stops (see "Think about it" in the guide).
    return [
        fetch_point(client, resort, point, root=root)
        for resort in resorts
        for point in resort.points
    ]
