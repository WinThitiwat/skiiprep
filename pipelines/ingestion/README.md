# skiiprep-ingestion

Fetches raw data from sources and saves it to bronze (`data/bronze/`), exactly as received, one file per fetch. See `docs/phases/phase-01-bronze-ingest.md`.

## Open-Meteo: findings from exploring the API (phase 1, step 1)

Explored by hand on 2026-10-19 (local) / 2026-10-20 (UTC).

### Request
Endpoint: `https://api.open-meteo.com/v1/forecast`

| Param | Value | Why |
|-------|-------|-----|
| `latitude`, `longitude`, `elevation` | From one point in `config/resorts.yaml` (base: 46.9355, -121.4745, 1341 m; summit: 46.9282, -121.5045, 2094 m) | All three must come from the **same** point. Mixing base coordinates with summit elevation gives temperatures about 5 °C too cold |
| `hourly` | `temperature_2m, apparent_temperature, precipitation, rain, snowfall, snow_depth, freezing_level_height, wind_speed_10m, wind_gusts_10m, weather_code, cloud_cover, visibility` | The 12 variables silver needs |
| `timezone` | `UTC` | SD2. `GMT` gives the same offset, but we use the word UTC everywhere |
| `forecast_days` | `7` | It's the default, but we set it explicitly so the request saved in bronze explains itself |

- `elevation` isn't in the docs' URL builder. It's in the parameter table under "API Documentation" (used for statistical downscaling). Without it, the API uses its own terrain model (e.g. 2109 m at the summit coordinates).
- Default units already match silver: °C, km/h, mm, with snowfall in cm. No unit parameters needed.

### Response
- **Echoed location:** `latitude`/`longitude` snap to the model grid (about 1.5 km from what we sent). `elevation` echoes what we asked for. **The bronze envelope must keep our request params**, because the response alone doesn't say which point we asked for.
- **Shape:** `hourly` holds **parallel arrays**: one `time` array plus one array per variable, all the same length (7 days × 24 = 168). `hourly_units` gives the unit of each. Phase 2 zips and explodes these into rows.
- **Time format:** `2026-10-20T00:00`, which is ISO 8601 with **no offset and no seconds**. It's UTC only because we sent `timezone=UTC`, which the response confirms in `timezone` and `utc_offset_seconds: 0`. Phase 2 parses it with `yyyy-MM-dd'T'HH:mm` and a Spark session set to UTC. (`timeformat=unixtime` is available. We keep ISO because bronze stays readable.)
- **Time range:** starts at **00:00 of the current UTC date**, not at the time of the fetch, and runs to 23:00 on the 7th day. Fetched at 2026-10-19 17:51 PDT (= 2026-10-20 00:51 UTC), it covered `2026-10-20T00:00` to `2026-10-26T23:00`. In local time that looks like "starting tomorrow", but it's "today in UTC". The first hours of each response are already in the past, and fetches on the same day overlap. That's why silver's grain includes `fetched_at`.
- **Nulls:** none in the responses we checked, but treat every variable as nullable (other resorts, other variables, the far end of the forecast). In silver, null means "no data", never 0.

### Errors
An invalid variable (e.g. `snow_depths`) returns **HTTP 400** with a JSON body:
```json
{"reason": "Invalid value: Cannot initialize ... from invalid String value snow_depths", "error": true}
```
- `raise_for_status()` raises before anything is written, so an error body never becomes a bronze file.
- The exception message doesn't include `reason`, so log `response.text` when a request fails.

### Still to look at
- Base vs summit `temperature_2m`: the difference is sometimes above 5 °C. Check the min, max and mean over all hours, check for inversions (summit warmer), and check whether both points land in the same grid cell.
- Rate limits and terms for the free tier (needed before adding many resorts).
