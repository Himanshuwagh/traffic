from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import logging
import os
from dotenv import load_dotenv

load_dotenv()

# Prefer Supabase (has PostGIS) over the Replit-managed DB (no PostGIS)
DATABASE_URL = os.getenv("SUPABASE_DATABASE_URL") or os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL or SUPABASE_DATABASE_URL is required")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def should_ensure_performance_indexes() -> bool:
    return _env_flag("AUTO_CREATE_INDEXES", default=False)


def _execute_transactional_statements(statements: list[str]) -> None:
    for statement in statements:
        try:
            with engine.begin() as connection:
                connection.execute(text(statement))
        except SQLAlchemyError as exc:
            logger.warning("Failed to execute transactional schema statement: %s | sql=%s", exc, statement)


def _execute_autocommit_statements(statements: list[str]) -> None:
    for statement in statements:
        try:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(statement))
        except SQLAlchemyError as exc:
            logger.warning("Failed to execute autocommit schema statement: %s | sql=%s", exc, statement)


def ensure_traffic_observation_schema():
    tx_statements = [
        "ALTER TABLE traffic_observations ADD COLUMN IF NOT EXISTS observed_at_hour TIMESTAMP",
        "ALTER TABLE traffic_observations ADD COLUMN IF NOT EXISTS speed_ratio DOUBLE PRECISION",
        "ALTER TABLE traffic_observations ADD COLUMN IF NOT EXISTS hour_of_day SMALLINT",
        "ALTER TABLE traffic_observations ADD COLUMN IF NOT EXISTS day_of_week SMALLINT",
        """
        UPDATE traffic_observations
        SET
            observed_at_hour = DATE_TRUNC('hour', observed_at),
            speed_ratio = CASE
                WHEN free_flow_speed_kmph IS NOT NULL AND free_flow_speed_kmph > 0 AND speed_kmph IS NOT NULL
                    THEN GREATEST(0.0, LEAST(1.0, speed_kmph / free_flow_speed_kmph))
                ELSE NULL
            END,
            hour_of_day = EXTRACT(HOUR FROM observed_at)::smallint,
            day_of_week = (EXTRACT(ISODOW FROM observed_at)::int - 1)::smallint
        WHERE observed_at IS NOT NULL
          AND (
              observed_at_hour IS NULL
              OR hour_of_day IS NULL
              OR day_of_week IS NULL
              OR (
                  free_flow_speed_kmph IS NOT NULL
                  AND free_flow_speed_kmph > 0
                  AND speed_kmph IS NOT NULL
                  AND speed_ratio IS NULL
              )
          )
        """,
        """
        DELETE FROM traffic_observations stale
        USING (
            SELECT id
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY source, source_ref
                        ORDER BY observed_at DESC NULLS LAST, id DESC
                    ) AS rn
                FROM traffic_observations
                WHERE source IS NOT NULL
                  AND source_ref IS NOT NULL
            ) ranked
            WHERE ranked.rn > 1
        ) dupes
        WHERE stale.id = dupes.id
        """,
        """
        DELETE FROM traffic_observations stale
        USING (
            SELECT id
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY road_segment_id, observed_at_hour
                        ORDER BY observed_at DESC NULLS LAST, id DESC
                    ) AS rn
                FROM traffic_observations
                WHERE source = 'tomtom'
                  AND road_segment_id IS NOT NULL
                  AND observed_at_hour IS NOT NULL
            ) ranked
            WHERE ranked.rn > 1
        ) dupes
        WHERE stale.id = dupes.id
        """,
        "ALTER TABLE traffic_observations ALTER COLUMN observed_at_hour SET NOT NULL",
        "ALTER TABLE traffic_observations ALTER COLUMN hour_of_day SET NOT NULL",
        "ALTER TABLE traffic_observations ALTER COLUMN day_of_week SET NOT NULL",
    ]
    concurrent_statements = [
        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_traffic_observations_source_ref ON traffic_observations (source, source_ref)",
        """
        CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uq_traffic_observations_segment_hour
        ON traffic_observations (road_segment_id, observed_at_hour)
        WHERE road_segment_id IS NOT NULL AND source = 'tomtom'
        """,
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_traffic_observations_observed_hour ON traffic_observations (observed_at_hour)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_traffic_observations_city_hour ON traffic_observations (LOWER(city), observed_at_hour)",
    ]
    _execute_transactional_statements(tx_statements)
    _execute_autocommit_statements(concurrent_statements)


def ensure_performance_indexes():
    # Split heavy index statements that must run CONCURRENTLY from the
    # lightweight statements that can run inside a transaction.
    concurrent_statements = [
        # Spatial index — build concurrently because it can take a long time
        # on large tables and must not block writes.
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_road_segments_geometry_gist ON road_segments USING GIST (geometry)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_traffic_observations_geometry_gist ON traffic_observations USING GIST (geometry)",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_traffic_observations_geometry_geog_gist ON traffic_observations USING GIST ((geometry::geography))",
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_traffic_hotspots_geometry_geog_gist ON traffic_hotspots USING GIST ((geometry::geography))",
    ]

    tx_statements = [
        # City filter
        "CREATE INDEX IF NOT EXISTS idx_road_segments_city_lower ON road_segments (LOWER(city))",
        # Highway type filter (zoom-based road class filtering)
        "CREATE INDEX IF NOT EXISTS idx_road_segments_highway_type ON road_segments (highway_type)",
        # Composite: city + highway_type — used by tile queries to narrow road_segments before spatial join
        "CREATE INDEX IF NOT EXISTS idx_road_segments_city_hw ON road_segments (LOWER(city), highway_type)",
        # Covering index for traffic_data — segment_id + date + payload cols avoid heap fetch
        # Used by the scoped tile query: WHERE segment_id IN (...) AND date BETWEEN ...
        "CREATE INDEX IF NOT EXISTS idx_traffic_data_seg_date_covering ON traffic_data (segment_id, date, speed, travel_time)",
        # Date-only index for any remaining range scans
        "CREATE INDEX IF NOT EXISTS idx_traffic_data_date ON traffic_data (date)",
        "CREATE INDEX IF NOT EXISTS idx_traffic_observations_city_time ON traffic_observations (LOWER(city), observed_at)",
        "CREATE INDEX IF NOT EXISTS idx_traffic_observations_city_hour_day ON traffic_observations (LOWER(city), observed_at_hour, hour_of_day)",
        "CREATE INDEX IF NOT EXISTS idx_traffic_observations_city_time_congested ON traffic_observations (LOWER(city), observed_at) WHERE congestion_index IS NOT NULL",
        "CREATE INDEX IF NOT EXISTS idx_traffic_observations_road_time ON traffic_observations (road_segment_id, observed_at)",
        "CREATE INDEX IF NOT EXISTS idx_traffic_observations_jam_time ON traffic_observations (jam_level, observed_at)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_traffic_tile_cache_tile ON traffic_tile_cache (city, date_hour, z, x, y)",
        "CREATE INDEX IF NOT EXISTS idx_traffic_tile_cache_lookup ON traffic_tile_cache (city, date_hour, z, x, y)",
        "CREATE INDEX IF NOT EXISTS idx_traffic_hotspots_city_status ON traffic_hotspots (LOWER(city), status)",
        "CREATE INDEX IF NOT EXISTS idx_daily_hotspot_stats_hotspot_date ON daily_hotspot_stats (hotspot_id, date)",
        "CREATE INDEX IF NOT EXISTS idx_tomtom_runs_day_mode ON tomtom_ingestion_runs (started_at, mode)",
        "CREATE INDEX IF NOT EXISTS idx_traffic_signals_city_lower ON traffic_signals (LOWER(city))",
        "CREATE INDEX IF NOT EXISTS idx_weather_data_city_timestamp ON weather_data (LOWER(city), timestamp)",
    ]

    if not should_ensure_performance_indexes():
        logger.info("Skipping startup index creation; set AUTO_CREATE_INDEXES=true to enable it.")
        return

    # Run the lightweight index statements individually so a timeout on one
    # index does not prevent the application from starting.
    _execute_transactional_statements(tx_statements)

    # Run the concurrent statements outside a transaction (Postgres requires
    # CONCURRENTLY to not be executed inside a transaction block).
    _execute_autocommit_statements(concurrent_statements)


def bootstrap_database():
    ensure_traffic_observation_schema()
    ensure_performance_indexes()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
