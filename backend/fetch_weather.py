import requests
import logging
from datetime import datetime
try:
    from .database import SessionLocal, engine
    from .models import WeatherData, Base
except ImportError:  # allows `python backend/fetch_weather.py`
    from database import SessionLocal, engine
    from models import WeatherData, Base

# Ensure tables are created
Base.metadata.create_all(bind=engine)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

def get_condition_string(wmo_code):
    """Map Open-Meteo WMO weather codes to simple strings."""
    if wmo_code == 0:
        return "Clear"
    elif wmo_code in [1, 2, 3]:
        return "Cloudy"
    elif wmo_code in [45, 48]:
        return "Fog"
    elif wmo_code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82]:
        return "Rain"
    elif wmo_code in [71, 73, 75, 77, 85, 86]:
        return "Snow"
    elif wmo_code in [95, 96, 99]:
        return "Thunderstorm"
    else:
        return "Unknown"

def fetch_weather_for_city(city_name: str, lat: float, lon: float):
    logging.info(f"Fetching weather data for {city_name}...")
    try:
        # Open-Meteo API (Free, no key required)
        # Fetching past 2 days and forecast for next 2 days to cover our traffic time windows
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,precipitation,weathercode&past_days=2&forecast_days=2"
        
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        temps = hourly.get("temperature_2m", [])
        precips = hourly.get("precipitation", [])
        codes = hourly.get("weathercode", [])
        
        db = SessionLocal()
        inserted_count = 0
        
        for i in range(len(times)):
            try:
                # Open-Meteo returns ISO8601 strings (e.g. "2023-10-25T00:00")
                timestamp = datetime.fromisoformat(times[i])
                temp = temps[i]
                precip = precips[i]
                condition = get_condition_string(codes[i])
                
                # Upsert logic: delete existing record for this city/time, then insert
                db.query(WeatherData).filter(
                    WeatherData.city == city_name, 
                    WeatherData.timestamp == timestamp
                ).delete()
                
                weather_record = WeatherData(
                    city=city_name,
                    timestamp=timestamp,
                    temperature=temp,
                    condition=condition,
                    precipitation=precip
                )
                db.add(weather_record)
                db.commit()
                inserted_count += 1
            except Exception as e:
                db.rollback()
                logging.error(f"Error processing row {i}: {e}")
                
        logging.info(f"Successfully updated {inserted_count} hourly weather records for {city_name}.")
    except Exception as e:
        logging.error(f"Failed to fetch weather: {e}")
    finally:
        if 'db' in locals():
            db.close()

if __name__ == "__main__":
    # Pune coordinates
    fetch_weather_for_city("pune", 18.5204, 73.8567)
    
    # Example for Bengaluru if needed
    # fetch_weather_for_city("bengaluru", 12.9716, 77.5946)
