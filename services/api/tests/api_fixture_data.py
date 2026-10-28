"""Fixture data shared by the API tests (see conftest.py for what it contains).

A module with a unique name: importing from `conftest` directly is ambiguous when
several components each have a conftest.py and the whole suite runs together.
"""
from datetime import datetime, timezone

F1 = datetime(2026, 10, 20, 5, 0, tzinfo=timezone.utc)
F2 = datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc)

# Same columns and types as lake.weather.silver_weather_hourly, so values come back
# as the same Python types (DOUBLE -> float, not DECIMAL -> Decimal).
SILVER_SCHEMA = """
    resort_id VARCHAR, point VARCHAR, valid_time TIMESTAMPTZ, fetched_at TIMESTAMPTZ,
    source VARCHAR, elevation_m INTEGER,
    temp_c DOUBLE, feels_like_c DOUBLE, precip_mm DOUBLE, rain_mm DOUBLE,
    snowfall_cm DOUBLE, snow_depth_m DOUBLE, freezing_level_m DOUBLE,
    wind_kmh DOUBLE, gust_kmh DOUBLE, weather_code INTEGER, cloud_cover_pct INTEGER,
    visibility_m DOUBLE,
    bronze_file VARCHAR, dw_processing_time TIMESTAMPTZ, last_changed_at TIMESTAMPTZ
"""

# (resort_id, point, valid_time UTC hour on the 21st, fetch, snowfall_cm, temp_c)
ROWS = [
    ("testpeak", "base", 5, F1, 1.0, 2.0),
    ("testpeak", "base", 6, F1, 1.0, 2.0),
    ("testpeak", "base", 7, F1, 1.0, 1.0),
    ("testpeak", "base", 8, F1, 1.0, 1.0),
    ("testpeak", "base", 9, F1, 1.0, 0.5),
    ("testpeak", "base", 5, F2, 2.0, 1.5),
    ("testpeak", "base", 6, F2, 2.0, 1.0),
    ("testpeak", "base", 7, F2, 3.0, 0.0),
    ("testpeak", "base", 8, F2, 3.0, -0.5),
    ("testpeak", "summit", 7, F2, 5.0, -4.0),
    ("otherpeak", "base", 7, F2, 99.0, 9.0),
]
