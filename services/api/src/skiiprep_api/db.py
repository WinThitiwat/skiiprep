"""DuckDB access for the API: one connection, the two forecast views, and a query helper.

The API only reads (guardrail 2). DuckDB reads the silver Iceberg table in place
with `iceberg_scan` (SD9), so there's no copy of the data and no server to run.
"""
import logging
import time
from typing import Any

import duckdb

from skiiprep_common.settings import SILVER_WEATHER_TABLE_DIR

logger = logging.getLogger(__name__)

# Where `view_weather_hourly` reads from. Tests pass the name of a plain table instead.
DEFAULT_SOURCE_SQL = f"iceberg_scan('{SILVER_WEATHER_TABLE_DIR}')"


class IcebergTableQuerier:
    """Owns the DuckDB connection and the views every endpoint queries.

    Call `connect()` once at startup (FastAPI's lifespan), before any request,
    then `execute_query()` from any request thread. Each query gets its own cursor.

    `source_sql` is what `view_weather_hourly` selects from: `iceberg_scan(...)`
    in production, a plain table in tests. `connection` lets a test pass in a
    connection where it has already created that table.
    """

    def __init__(
        self,
        source_sql: str = DEFAULT_SOURCE_SQL,
        connection: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        self.source_sql = source_sql
        self._con = connection

    def connect(self) -> None:
        """Open (or take) the connection, configure it, and create the views.

        Called once at startup, so two requests can never race to open two
        connections.
        """
        if self._con is None:
            self._con = duckdb.connect()  # in-memory: the data stays in Iceberg
        self._configure_session()
        self.create_views()

    def _configure_session(self) -> None:
        """Load the Iceberg extension and make UTC the timezone for every cursor."""
        assert self._con is not None
        # INSTALL downloads the extension the first time only; later it's a no-op.
        self._con.execute("INSTALL iceberg; LOAD iceberg;")
        # GLOBAL, not plain SET: cursors don't inherit a session-level SET, and
        # every query runs on a cursor. Resort time is only for serving (SD2).
        self._con.execute("SET GLOBAL TimeZone = 'UTC';")

    def create_views(self) -> None:
        """Create the two views the endpoints read.

        - view_weather_hourly: every fetch, for history questions (Q6).
        - view_latest_forecast: the newest fetch per resort, point and hour.
          It's ordered by fetched_at (when the forecast was made), never by
          dw_processing_time (when silver loaded it).
        """
        self.execute_query(f"""
            CREATE OR REPLACE VIEW view_weather_hourly AS
            SELECT *
            FROM {self.source_sql};
        """)
        self.execute_query("""
            CREATE OR REPLACE VIEW view_latest_forecast AS
            SELECT *
            FROM view_weather_hourly
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY resort_id, point, valid_time
                ORDER BY fetched_at DESC
            ) = 1;
        """)

    def execute_query(self, sql_query: str, parameters: list[Any] | None = None) -> list[dict[str, Any]]:
        """Run one query on its own cursor and return the rows as dicts.

        Dicts keyed by column name keep callers independent of column order, and
        they're what Pydantic models are built from. Use `?` placeholders and
        `parameters` for values, never string formatting.

        >>> querier.execute_query("SELECT point, temp_c FROM view_latest_forecast LIMIT 1")
        [{'point': 'base', 'temp_c': 9.6}]
        """
        if self._con is None:
            raise RuntimeError("IcebergTableQuerier.connect() must be called before querying")

        # A cursor per query: a DuckDB connection shouldn't be used by two
        # threads at once, and FastAPI runs plain `def` endpoints in a thread pool.
        cursor = self._con.cursor()
        start_time = time.perf_counter()
        try:
            cursor.execute(sql_query, parameters or [])
            # DDL such as CREATE VIEW has no result set, so no description.
            if cursor.description is None:
                return []
            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            cursor.close()
            logger.debug("Query took %.4f s: %s", time.perf_counter() - start_time, sql_query.strip())

    def close(self) -> None:
        """Close the connection. Called once at shutdown."""
        if self._con is not None:
            self._con.close()
            self._con = None


def startup(source_sql: str = DEFAULT_SOURCE_SQL) -> IcebergTableQuerier:
    """Build a querier that's connected and has its views, ready to serve.

    `main.py`'s lifespan calls this once and keeps the result for the app's life.
    """
    querier = IcebergTableQuerier(source_sql=source_sql)
    querier.connect()
    return querier


def main() -> None:
    """Manual check against the real table: `uv run --package skiiprep-api python -m skiiprep_api.db`."""
    logging.basicConfig(level=logging.INFO)
    querier = startup()
    try:
        logger.info("view_weather_hourly: %s", querier.execute_query("SELECT count(*) AS n FROM view_weather_hourly"))
        logger.info("view_latest_forecast: %s", querier.execute_query("SELECT count(*) AS n FROM view_latest_forecast"))
    finally:
        querier.close()


if __name__ == "__main__":
    main()
