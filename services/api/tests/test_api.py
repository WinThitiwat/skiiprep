"""Endpoint tests through FastAPI's TestClient, against the fixture table (see conftest)."""
from api_fixture_data import F1, F2

BASE = "/api/v1/resorts/testpeak/forecast"


def iso(moment) -> str:
    """How FastAPI writes a UTC datetime in JSON."""
    return moment.isoformat().replace("+00:00", "Z")


# --- /resorts --------------------------------------------------------------------

def test_resorts_come_from_the_catalog(client):
    items = client.get("/api/v1/resorts").json()["items"]
    assert [r["id"] for r in items] == ["otherpeak", "testpeak"]  # sorted by name
    assert items[1]["points"] == [{"name": "base", "elevation_m": 1341}, {"name": "summit", "elevation_m": 2094}]


def test_resorts_filter_by_state_and_name(client):
    assert [r["id"] for r in client.get("/api/v1/resorts", params={"state": "wa"}).json()["items"]] == ["testpeak"]
    assert [r["id"] for r in client.get("/api/v1/resorts", params={"name": "OTHER"}).json()["items"]] == ["otherpeak"]


# --- /health ---------------------------------------------------------------------

def test_health_reports_newest_fetch(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["newest_fetched_at"] == iso(F2)


def test_health_with_empty_table_is_no_data_not_an_error(empty_client):
    response = empty_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "no_data"
    assert response.json()["newest_fetched_at"] is None


# --- /hourly ---------------------------------------------------------------------

def test_hourly_reads_naive_times_as_resort_local(client):
    """22:00–00:00 without an offset means Seattle time (05:00–07:00 UTC), not UTC."""
    response = client.get(f"{BASE}/hourly", params={"point": "base", "start": "2026-10-20T22:00", "end": "2026-10-21T00:00"})
    items = response.json()["items"]
    assert [i["valid_time"] for i in items] == ["2026-10-20T22:00:00-07:00", "2026-10-20T23:00:00-07:00"]
    assert [i["snowfall_cm"] for i in items] == [2.0, 2.0]  # from the newer fetch


def test_hourly_keeps_explicit_offsets(client):
    response = client.get(f"{BASE}/hourly", params={"point": "base", "start": "2026-10-21T07:00Z", "end": "2026-10-21T08:00Z"})
    assert [i["valid_time"] for i in response.json()["items"]] == ["2026-10-21T00:00:00-07:00"]


def test_hourly_envelope_and_nulls(client):
    body = client.get(f"{BASE}/hourly", params={"point": "summit", "start": "2026-10-21T00:00"}).json()
    assert (body["resort_id"], body["timezone"]) == ("testpeak", "America/Los_Angeles")
    assert body["fetched_at"] == iso(F2)
    assert body["items"][0]["visibility_m"] is None  # NULL stays null, never 0


def test_hourly_fetched_at_is_the_oldest_fetch_used(client):
    """09:00 UTC only exists in F1, so an answer that includes it is only as fresh as F1."""
    body = client.get(f"{BASE}/hourly", params={"point": "base", "start": "2026-10-21T01:00"}).json()
    assert [i["valid_time"] for i in body["items"]] == ["2026-10-21T01:00:00-07:00", "2026-10-21T02:00:00-07:00"]
    assert body["fetched_at"] == iso(F1)


def test_hourly_errors(client):
    assert client.get("/api/v1/resorts/nowhere/forecast/hourly", params={"point": "base", "start": "2026-10-21T00:00"}).status_code == 404
    bad_point = client.get(f"{BASE}/hourly", params={"point": "top", "start": "2026-10-21T00:00"})
    assert bad_point.status_code == 422
    assert "base" in bad_point.json()["detail"]
    assert client.get(f"{BASE}/hourly", params={"point": "base", "start": "2026-10-21T02:00", "end": "2026-10-21T01:00"}).status_code == 422
    assert client.get(f"{BASE}/hourly", params={"point": "base"}).status_code == 422  # start is required


def test_hourly_without_data_is_503(empty_client):
    response = empty_client.get(f"{BASE}/hourly", params={"point": "base", "start": "2026-10-21T00:00"})
    assert response.status_code == 503
    assert "run ingest and transform" in response.json()["detail"]


# --- /daily ----------------------------------------------------------------------

def test_daily_groups_by_local_date(client):
    """Hours before 07:00 UTC on the 21st belong to the 20th in Seattle."""
    items = client.get(f"{BASE}/daily", params={"start": "2026-10-20", "days": 2}).json()["items"]
    summary = [(i["date"], i["point"], i["hours_covered"], i["snowfall_cm_total"]) for i in items]
    assert summary == [
        ("2026-10-20", "base", 2, 4.0),    # 22:00 and 23:00 local, 2.0 each from F2
        ("2026-10-21", "base", 3, 7.0),    # 00:00 and 01:00 from F2 (3.0 each), 02:00 from F1 (1.0)
        ("2026-10-21", "summit", 1, 5.0),
    ]


def test_daily_extremes_and_partial_days(client):
    items = client.get(f"{BASE}/daily", params={"start": "2026-10-21", "days": 1}).json()["items"]
    base = items[0]
    assert (base["temp_c_min"], base["temp_c_max"]) == (-0.5, 0.5)
    assert base["hours_covered"] < 24  # a partial day is visible as partial
    assert base["gust_kmh_max"] is None  # no gust data at all: null, not 0


def test_daily_never_mixes_in_other_resorts(client):
    items = client.get(f"{BASE}/daily", params={"start": "2026-10-21", "days": 1}).json()["items"]
    assert all(i["snowfall_cm_total"] != 99.0 for i in items)


def test_daily_fetched_at_is_the_oldest_fetch_used(client):
    assert client.get(f"{BASE}/daily", params={"start": "2026-10-20", "days": 2}).json()["fetched_at"] == iso(F1)


def test_daily_validation(client):
    assert client.get(f"{BASE}/daily", params={"days": 30}).status_code == 422
    assert client.get(f"{BASE}/daily", params={"start": "2026-10-21T10:30"}).status_code == 422  # a date, not a time
    assert client.get("/api/v1/resorts/nowhere/forecast/daily").status_code == 404


def test_daily_without_data_is_503(empty_client):
    assert empty_client.get(f"{BASE}/daily", params={"start": "2026-10-21"}).status_code == 503


# --- /changes --------------------------------------------------------------------

def test_changes_lists_each_fetch_oldest_first(client):
    items = client.get(f"{BASE}/changes", params={"date": "2026-10-21"}).json()["items"]
    summary = [(i["point"], i["fetched_at"], i["hours_covered"], i["snowfall_cm_total"]) for i in items]
    assert summary == [
        ("base", iso(F1), 3, 3.0),    # F1 had 00:00, 01:00, 02:00 local, 1.0 each
        ("base", iso(F2), 2, 6.0),    # F2 had 00:00 and 01:00, 3.0 each: the forecast got snowier
        ("summit", iso(F2), 1, 5.0),
    ]


def test_changes_for_a_date_with_no_forecast_is_empty(client):
    response = client.get(f"{BASE}/changes", params={"date": "2026-11-15"})
    assert response.status_code == 200
    assert response.json()["items"] == []


def test_changes_validation(client):
    assert client.get(f"{BASE}/changes").status_code == 422  # date is required
    assert client.get("/api/v1/resorts/nowhere/forecast/changes", params={"date": "2026-10-21"}).status_code == 404


def test_changes_without_data_is_503(empty_client):
    assert empty_client.get(f"{BASE}/changes", params={"date": "2026-10-21"}).status_code == 503
