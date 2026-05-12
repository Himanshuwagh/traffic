from sqlalchemy import Column, Integer, String, DateTime, Float, Text
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
