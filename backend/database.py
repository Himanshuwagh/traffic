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


def ensure_performance_indexes():
    index_statements = [
        "CREATE INDEX IF NOT EXISTS idx_road_segments_geometry_gist ON road_segments USING GIST (geometry)",
        "CREATE INDEX IF NOT EXISTS idx_road_segments_city_lower ON road_segments (LOWER(city))",
        "CREATE INDEX IF NOT EXISTS idx_road_segments_highway_type ON road_segments (highway_type)",
        "CREATE INDEX IF NOT EXISTS idx_traffic_data_segment_date ON traffic_data (segment_id, date)",
        "CREATE INDEX IF NOT EXISTS idx_traffic_data_date ON traffic_data (date)",
        "CREATE INDEX IF NOT EXISTS idx_traffic_signals_city_lower ON traffic_signals (LOWER(city))",
        "CREATE INDEX IF NOT EXISTS idx_weather_data_city_timestamp ON weather_data (LOWER(city), timestamp)",
    ]
    with engine.begin() as connection:
        for statement in index_statements:
            connection.execute(text(statement))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
