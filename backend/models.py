from sqlalchemy import Column, Integer, String, DateTime, Float
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