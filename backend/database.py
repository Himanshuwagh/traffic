from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


import logging

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

    # Run the lightweight index statements inside a transaction
    with engine.begin() as connection:
        for statement in tx_statements:
            connection.execute(text(statement))

    # Run the concurrent statements outside a transaction (Postgres requires
    # CONCURRENTLY to not be executed inside a transaction block).
    for statement in concurrent_statements:
        try:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(statement))
        except Exception as exc:
            # Log a warning but don't fail the entire startup.
            logging.warning(f"Failed to create concurrent index; will retry later: {exc}")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
