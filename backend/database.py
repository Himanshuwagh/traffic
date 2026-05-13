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


def ensure_performance_indexes():
    # Split heavy index statements that must run CONCURRENTLY from the
    # lightweight statements that can run inside a transaction.
    concurrent_statements = [
        # Spatial index — build concurrently because it can take a long time
        # on large tables and must not block writes.
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_road_segments_geometry_gist ON road_segments USING GIST (geometry)",
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
        "CREATE INDEX IF NOT EXISTS idx_traffic_signals_city_lower ON traffic_signals (LOWER(city))",
        "CREATE INDEX IF NOT EXISTS idx_weather_data_city_timestamp ON weather_data (LOWER(city), timestamp)",
    ]

    if not should_ensure_performance_indexes():
        logger.info("Skipping startup index creation; set AUTO_CREATE_INDEXES=true to enable it.")
        return

    # Run the lightweight index statements individually so a timeout on one
    # index does not prevent the application from starting.
    for statement in tx_statements:
        try:
            with engine.begin() as connection:
                connection.execute(text(statement))
        except SQLAlchemyError as exc:
            logger.warning("Failed to create transactional index during startup: %s | sql=%s", exc, statement)

    # Run the concurrent statements outside a transaction (Postgres requires
    # CONCURRENTLY to not be executed inside a transaction block).
    for statement in concurrent_statements:
        try:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(statement))
        except SQLAlchemyError as exc:
            # Log a warning but don't fail the entire startup.
            logger.warning("Failed to create concurrent index during startup: %s | sql=%s", exc, statement)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
