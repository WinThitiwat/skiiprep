# Silver table for hourly weather forecasts, built from bronze by the transform job.
#
# Grain: one row per resort_id × point × valid_time × fetched_at.
#   Iceberg does not enforce this. The MERGE in the job does, so keep the
#   MERGE keys in sync with this grain.
# Partitioning: resort_id, days(valid_time) (Iceberg hidden partitioning, system design §4)
# Lineage: bronze_file points back to the raw file each row came from.

class WeatherHourlyTable:
    table_name = "silver_weather_hourly"
    catalog_name = "lake"
    namespace_name = "weather"
    full_table_name = f"{catalog_name}.{namespace_name}.{table_name}"

    create_statement  = (f"""
        CREATE TABLE IF NOT EXISTS {full_table_name}
        (
            resort_id STRING COMMENT "Stable resort id from config/resorts.yaml, e.g. crystal.",
            point STRING COMMENT "Point name within the resort: base or summit.",
            valid_time TIMESTAMP COMMENT "The UTC hour this forecast row is for.",
            fetched_at TIMESTAMP COMMENT "When we fetched this forecast from Open-Meteo (UTC). Two fetches of the same hour are two different forecasts.",
            source STRING COMMENT "The weather data source. Here it is always open_meteo.",

            -- Measures
            elevation_m INT COMMENT "Elevation in meters that the forecast was adjusted to (the point's height from config/resorts.yaml).",
            temp_c DOUBLE COMMENT "Air temperature at 2 meters above ground, in Celsius.",
            feels_like_c DOUBLE COMMENT "Apparent temperature in Celsius: how cold or warm it feels, combining temperature, wind, humidity and radiation.",
            precip_mm DOUBLE COMMENT "Total precipitation (rain, showers, snow) in the preceding hour, in millimeters.",
            rain_mm DOUBLE COMMENT "Rain from large-scale weather systems in the preceding hour, in millimeters. Excludes showers.",
            snowfall_cm DOUBLE COMMENT "Snowfall in the preceding hour, in centimeters.",
            snow_depth_m DOUBLE COMMENT "Snow depth on the ground, in meters.",
            freezing_level_m DOUBLE COMMENT "Altitude above sea level, in meters, of the 0 Celsius level.",
            wind_kmh DOUBLE COMMENT "Wind speed at 10 meters above ground, in km/h.",
            gust_kmh DOUBLE COMMENT "Maximum wind gust at 10 meters above ground in the preceding hour, in km/h.",
            weather_code INT COMMENT "Weather condition as a WMO weather interpretation code.",
            cloud_cover_pct INT COMMENT "Total cloud cover in percent, from 0 to 100.",
            visibility_m DOUBLE COMMENT "Viewing distance in meters. Reduced by low cloud, humidity and aerosols.",

            -- Lineage and auditing
            bronze_file STRING COMMENT "The bronze file that last changed this row. Used for auditing and debugging.",
            dw_processing_time TIMESTAMP COMMENT "When this row was first loaded into silver (UTC). Never changes after insert.",
            last_changed_at TIMESTAMP COMMENT "When a data value in this row last changed (UTC). Re-runs with identical values do not move it. Null on rows loaded before this column existed."
        )
        USING iceberg
        PARTITIONED BY (resort_id, days(valid_time))
    """
    )

    merge_statement = ("""
        MERGE INTO {target_table} AS t
        USING {temp_view_name} AS s
        ON t.resort_id = s.resort_id 
            AND t.point = s.point 
            AND t.valid_time = s.valid_time 
            AND t.fetched_at = s.fetched_at
        -- Only touch a matched row when a data value differs. Identical re-runs
        -- then write nothing, so no new data files are created for them.
        -- <=> is null-safe: two NULLs count as equal.
        WHEN MATCHED AND (
                NOT (t.source <=> s.source)
                OR NOT (t.elevation_m <=> s.elevation_m)
                OR NOT (t.temp_c <=> s.temp_c)
                OR NOT (t.feels_like_c <=> s.feels_like_c)
                OR NOT (t.precip_mm <=> s.precip_mm)
                OR NOT (t.rain_mm <=> s.rain_mm)
                OR NOT (t.snowfall_cm <=> s.snowfall_cm)
                OR NOT (t.snow_depth_m <=> s.snow_depth_m)
                OR NOT (t.freezing_level_m <=> s.freezing_level_m)
                OR NOT (t.wind_kmh <=> s.wind_kmh)
                OR NOT (t.gust_kmh <=> s.gust_kmh)
                OR NOT (t.weather_code <=> s.weather_code)
                OR NOT (t.cloud_cover_pct <=> s.cloud_cover_pct)
                OR NOT (t.visibility_m <=> s.visibility_m)
            )
        THEN
            UPDATE SET
                t.source = s.source,
                t.elevation_m = s.elevation_m,
                t.temp_c = s.temp_c,
                t.feels_like_c = s.feels_like_c,
                t.precip_mm = s.precip_mm,
                t.rain_mm = s.rain_mm,
                t.snowfall_cm = s.snowfall_cm,
                t.snow_depth_m = s.snow_depth_m,
                t.freezing_level_m = s.freezing_level_m,
                t.wind_kmh = s.wind_kmh,
                t.gust_kmh = s.gust_kmh,
                t.weather_code = s.weather_code,
                t.cloud_cover_pct = s.cloud_cover_pct,
                t.visibility_m = s.visibility_m,
                t.bronze_file = s.bronze_file,
                t.last_changed_at = s.dw_processing_time
                -- dw_processing_time is deliberately not updated: it's the first-load time

        WHEN NOT MATCHED THEN
            INSERT (
                resort_id, 
                point, 
                valid_time, 
                fetched_at, 
                source, 
                elevation_m, 
                temp_c, 
                feels_like_c, 
                precip_mm, 
                rain_mm, 
                snowfall_cm, 
                snow_depth_m, 
                freezing_level_m, 
                wind_kmh, 
                gust_kmh, 
                weather_code, 
                cloud_cover_pct, 
                visibility_m, 
                bronze_file,
                dw_processing_time,
                last_changed_at
            )
            VALUES (s.resort_id, 
                s.point, 
                s.valid_time, 
                s.fetched_at, 
                s.source, 
                s.elevation_m, 
                s.temp_c, 
                s.feels_like_c, 
                s.precip_mm, 
                s.rain_mm, 
                s.snowfall_cm, 
                s.snow_depth_m, 
                s.freezing_level_m, 
                s.wind_kmh, 
                s.gust_kmh, 
                s.weather_code, 
                s.cloud_cover_pct, 
                s.visibility_m, 
                s.bronze_file,
                s.dw_processing_time,
                s.dw_processing_time
            )
    """)


