"""Tests for the Open-Meteo bronze ingest. No real API calls: every request
goes to an `httpx.MockTransport`, and files land in pytest's `tmp_path`."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from skiiprep_common.resorts import Point, Resort
from skiiprep_ingestion.open_meteo import (
    FORECAST_URL,
    HOURLY_VARIABLES,
    bronze_path,
    build_params,
    fetch_point,
    ingest,
)

BASE = Point(name="base", latitude=46.9355, longitude=-121.4745, elevation_m=1341)
SUMMIT = Point(name="summit", latitude=46.9282, longitude=-121.5045, elevation_m=2094)
CRYSTAL = Resort(
    id="crystal",
    name="Crystal Mountain",
    state="WA",
    pass_="ikon",
    timezone="America/Los_Angeles",
    points=(BASE, SUMMIT),
)
FETCHED_AT = datetime(2026, 10, 20, 0, 51, 5, tzinfo=timezone.utc)

# A tiny response with the same shape as the real one: parallel hourly arrays.
FAKE_RESPONSE = {
    "latitude": 46.921776,
    "longitude": -121.4852,
    "elevation": 2094.0,
    "timezone": "UTC",
    "utc_offset_seconds": 0,
    "hourly_units": {"time": "iso8601", "snowfall": "cm"},
    "hourly": {"time": ["2026-10-20T00:00", "2026-10-20T01:00"], "snowfall": [0.0, 0.7]},
}


def ok_client(seen: list[httpx.Request] | None = None) -> httpx.Client:
    """A client whose every request returns FAKE_RESPONSE; records requests in `seen`."""
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=FAKE_RESPONSE)

    return httpx.Client(transport=httpx.MockTransport(handler))


def bronze_files(root: Path) -> list[Path]:
    """All bronze files under `root`, sorted so comparisons don't depend on order."""
    return sorted(root.rglob("*.json"))


# --- build_params -----------------------------------------------------------

def test_build_params_takes_location_from_its_own_point():
    """Each point sends its own lat/lon/elevation; mixing them gives wrong temperatures (SD1)."""
    base, summit = build_params(BASE), build_params(SUMMIT)

    assert (base["latitude"], base["longitude"], base["elevation"]) == (46.9355, -121.4745, 1341)
    assert (summit["latitude"], summit["longitude"], summit["elevation"]) == (46.9282, -121.5045, 2094)


def test_build_params_fixed_values():
    """UTC, 7 days and exactly the 12 hourly variables, whatever the point."""
    params = build_params(BASE)

    assert params["timezone"] == "UTC"
    assert params["forecast_days"] == 7
    assert set(params["hourly"].split(",")) == set(HOURLY_VARIABLES)
    assert len(HOURLY_VARIABLES) == 12
    assert "name" not in params  # the point name belongs in the envelope, not the request


# --- bronze_path ------------------------------------------------------------

def test_bronze_path_layout(tmp_path):
    """Hive-style folders and a colon-free UTC file name, as in system design §4."""
    path = bronze_path("crystal", "summit", FETCHED_AT, root=tmp_path)

    assert path == tmp_path / "open_meteo/resort_id=crystal/point=summit/2026-10-20T005105Z.json"


def test_bronze_path_converts_aware_times_to_utc(tmp_path):
    """A non-UTC time is converted, so the `Z` in the name is always true."""
    pacific = timezone(timedelta(hours=-7))
    local = datetime(2026, 10, 19, 17, 51, 5, tzinfo=pacific)  # same instant as FETCHED_AT

    assert bronze_path("crystal", "base", local, root=tmp_path).name == "2026-10-20T005105Z.json"


def test_bronze_path_rejects_naive_datetime(tmp_path):
    """A naive time has no timezone, so we can't know it's UTC: refuse it."""
    with pytest.raises(ValueError):
        bronze_path("crystal", "base", datetime(2026, 10, 20, 0, 51, 5), root=tmp_path)


@pytest.mark.parametrize("resort_id, point_name", [("", "base"), ("crystal", "")])
def test_bronze_path_rejects_empty_names(tmp_path, resort_id, point_name):
    """An empty id or point name would produce a broken folder like `resort_id=`."""
    with pytest.raises(ValueError):
        bronze_path(resort_id, point_name, FETCHED_AT, root=tmp_path)


# --- fetch_point ------------------------------------------------------------

def test_fetch_point_writes_envelope(tmp_path):
    """The file holds the lineage envelope and the response exactly as received."""
    seen: list[httpx.Request] = []

    path = fetch_point(ok_client(seen), CRYSTAL, SUMMIT, root=tmp_path, fetched_at=FETCHED_AT)

    assert path == bronze_path("crystal", "summit", FETCHED_AT, root=tmp_path)
    envelope = json.loads(path.read_text())
    assert envelope["source"] == "open_meteo"
    assert envelope["resort_id"] == "crystal"
    assert envelope["point"] == "summit"
    assert envelope["elevation_m"] == 2094
    assert envelope["fetched_at"] == "2026-10-20T00:51:05+00:00"
    assert envelope["request"] == {"url": FORECAST_URL, "params": build_params(SUMMIT)}
    assert envelope["response"] == FAKE_RESPONSE  # saved exactly as received

    # The request that went out used the summit's own values.
    (request,) = seen
    assert request.url.params["elevation"] == "2094"
    assert request.url.params["timezone"] == "UTC"


def test_fetch_point_http_error_raises_and_writes_nothing(tmp_path):
    """An error body must never land in bronze, where phase 2 would parse it as a forecast."""
    error = {"error": True, "reason": "Invalid value: ... snow_depths"}
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, json=error)))

    with pytest.raises(httpx.HTTPStatusError):
        fetch_point(client, CRYSTAL, BASE, root=tmp_path, fetched_at=FETCHED_AT)

    assert bronze_files(tmp_path) == []


def test_fetch_point_never_overwrites(tmp_path):
    """Bronze is immutable: the same file name twice fails and the first file is untouched."""
    path = fetch_point(ok_client(), CRYSTAL, BASE, root=tmp_path, fetched_at=FETCHED_AT)
    original = path.read_bytes()

    with pytest.raises(FileExistsError):
        fetch_point(ok_client(), CRYSTAL, BASE, root=tmp_path, fetched_at=FETCHED_AT)

    assert path.read_bytes() == original


def test_fetch_point_twice_adds_a_new_file_and_keeps_the_first(tmp_path):
    """Re-running ingest adds new evidence; it never replaces old evidence."""
    first = fetch_point(ok_client(), CRYSTAL, BASE, root=tmp_path, fetched_at=FETCHED_AT)
    original = first.read_bytes()

    later = FETCHED_AT + timedelta(hours=1)
    second = fetch_point(ok_client(), CRYSTAL, BASE, root=tmp_path, fetched_at=later)

    assert first != second
    assert bronze_files(tmp_path) == sorted([first, second])
    assert first.read_bytes() == original


# --- ingest -----------------------------------------------------------------

def test_ingest_writes_one_file_per_point(tmp_path):
    """One request and one file per point, base before summit."""
    seen: list[httpx.Request] = []

    paths = ingest([CRYSTAL], client=ok_client(seen), root=tmp_path)

    assert [p.parent.name for p in paths] == ["point=base", "point=summit"]
    assert bronze_files(tmp_path) == sorted(paths)
    assert len(seen) == 2


def test_ingest_leaves_a_passed_in_client_open(tmp_path):
    """Whoever creates a client closes it; ingest only closes clients it made itself."""
    client = ok_client()

    ingest([CRYSTAL], client=client, root=tmp_path)

    assert not client.is_closed
