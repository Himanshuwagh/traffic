from sqlalchemy import Boolean, Column, Date, DateTime, Float, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from geoalchemy2 import Geometry
try:
    from .database import Base
except ImportError:
    from database import Base

class RoadSegment(Base):
    __tablename__ = "road_segments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)
    city = Column(String, nullable=True, index=True)
    geometry = Column(Geometry('LINESTRING', srid=4326))  # WGS84
    lanes = Column(Integer, nullable=True)
    highway_type = Column(String, nullable=True)
    oneway = Column(String, nullable=True)

class TrafficData(Base):
    __tablename__ = "traffic_data"

    id = Column(Integer, primary_key=True, index=True)
    segment_id = Column(Integer, index=True)
    date = Column(DateTime)
    speed = Column(Float)  # km/h
    travel_time = Column(Float)  # seconds


class TrafficObservation(Base):
    __tablename__ = "traffic_observations"

    id = Column(Integer, primary_key=True, index=True)
    observed_at = Column(DateTime, index=True)
    source = Column(String, nullable=False, index=True)
    source_kind = Column(String, nullable=False, index=True)
    source_ref = Column(String, nullable=True, index=True)
    road_segment_id = Column(Integer, nullable=True, index=True)
    geometry = Column(Geometry('GEOMETRY', srid=4326))
    city = Column(String, nullable=True, index=True)
    speed_kmph = Column(Float, nullable=True)
    free_flow_speed_kmph = Column(Float, nullable=True)
    travel_time_seconds = Column(Float, nullable=True)
    free_flow_travel_time_seconds = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    congestion_index = Column(Float, nullable=True, index=True)
    jam_level = Column(String, nullable=True, index=True)
    road_closure = Column(Boolean, nullable=True)
    raw_payload = Column(Text, nullable=True)
    raw_ttl_expires_at = Column(DateTime, nullable=True, index=True)


class TrafficTileCache(Base):
    __tablename__ = "traffic_tile_cache"
    __table_args__ = (
        UniqueConstraint("city", "date_hour", "z", "x", "y", name="uq_traffic_tile_cache_tile"),
        Index("idx_traffic_tile_cache_lookup", "city", "date_hour", "z", "x", "y"),
    )

    id = Column(Integer, primary_key=True, index=True)
    city = Column(String, nullable=False, index=True)
    date_hour = Column(DateTime, nullable=False, index=True)
    z = Column(Integer, nullable=False)
    x = Column(Integer, nullable=False)
    y = Column(Integer, nullable=False)
    data = Column(LargeBinary, nullable=False)
    etag = Column(String, nullable=False)
    encoding = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class TrafficHotspot(Base):
    __tablename__ = "traffic_hotspots"

    id = Column(Integer, primary_key=True, index=True)
    city = Column(String, nullable=True, index=True)
    name = Column(String, nullable=True)
    geometry = Column(Geometry('GEOMETRY', srid=4326))
    first_seen_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, nullable=True, index=True)
    severity_score = Column(Float, nullable=True, index=True)
    frequency_score = Column(Float, nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    status = Column(String, nullable=True, index=True)
    promoted_polling_until = Column(DateTime, nullable=True, index=True)


class DailyHotspotStat(Base):
    __tablename__ = "daily_hotspot_stats"

    id = Column(Integer, primary_key=True, index=True)
    hotspot_id = Column(Integer, nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    peak_hour = Column(Integer, nullable=True)
    avg_congestion_index = Column(Float, nullable=True)
    max_congestion_index = Column(Float, nullable=True)
    minutes_congested = Column(Integer, nullable=True)
    sample_count = Column(Integer, nullable=True)
    weather_summary = Column(Text, nullable=True)
    incident_count = Column(Integer, nullable=True)


class TomTomIngestionRun(Base):
    __tablename__ = "tomtom_ingestion_runs"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String, nullable=True, index=True)
    started_at = Column(DateTime, nullable=True, index=True)
    finished_at = Column(DateTime, nullable=True)
    city = Column(String, nullable=True, index=True)
    mode = Column(String, nullable=True, index=True)
    tile_requests = Column(Integer, nullable=True)
    non_tile_requests = Column(Integer, nullable=True)
    observations_saved = Column(Integer, nullable=True)
    observations_skipped = Column(Integer, nullable=True)
    hotspots_updated = Column(Integer, nullable=True)
    status = Column(String, nullable=True, index=True)
    error_message = Column(Text, nullable=True)

class TrafficSignal(Base):
    __tablename__ = "traffic_signals"

    id = Column(Integer, primary_key=True, index=True)
    city = Column(String, nullable=True, index=True)
    geometry = Column(Geometry('POINT', srid=4326))  # WGS84

class WeatherData(Base):
    __tablename__ = "weather_data"

    id = Column(Integer, primary_key=True, index=True)
    city = Column(String, index=True)
    timestamp = Column(DateTime, index=True)
    temperature = Column(Float)  # Celsius
    condition = Column(String)   # e.g., "Rain", "Clear", "Cloudy"
    precipitation = Column(Float) # mm


class FetchProgress(Base):
    """Tracks per-city status for the fetch_all_india.py batch job.

    Each row = one city in one batch run.  Survives Railway restarts so you
    can always query the DB to see what has been done.

    Queryable example:
        SELECT city, status, segments_fetched, duration_seconds
        FROM   fetch_progress
        ORDER  BY started_at;
    """
    __tablename__ = "fetch_progress"

    id               = Column(Integer, primary_key=True, index=True)
    run_id           = Column(String,  nullable=True,  index=True)   # short UUID for this batch run
    city             = Column(String,  nullable=False, index=True)
    status           = Column(String,  nullable=False)               # skipped | running | success | failed
    segments_fetched = Column(Integer, nullable=True)
    started_at       = Column(DateTime, nullable=True)
    finished_at      = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer,  nullable=True)
    error_message    = Column(Text,     nullable=True)
