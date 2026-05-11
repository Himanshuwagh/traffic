try:
    from .database import SessionLocal
except ImportError:  # allows `python backend/fetch_traffic.py`
    from database import SessionLocal
from sqlalchemy import text
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

DEPARTURE_TIME_BUFFER_MINUTES = 5
SEGMENT_LIMIT = 10000


def next_departure_time() -> datetime:
    # Keep the request ahead of "now" so long runs do not drift into the past.
    return datetime.now() + timedelta(minutes=DEPARTURE_TIME_BUFFER_MINUTES)

def fetch_traffic_data():
    import googlemaps

    gmaps = googlemaps.Client(key=os.getenv("GOOGLE_API_KEY"))
    db = SessionLocal()
    try:
        segments = db.execute(text("""
            SELECT
                id,
                ST_Y(ST_StartPoint(geometry)) AS start_lat,
                ST_X(ST_StartPoint(geometry)) AS start_lon,
                ST_Y(ST_EndPoint(geometry)) AS end_lat,
                ST_X(ST_EndPoint(geometry)) AS end_lon
            FROM road_segments
            WHERE geometry IS NOT NULL
            ORDER BY id
            LIMIT :limit
        """), {"limit": SEGMENT_LIMIT})
        insert_query = text("""
            INSERT INTO traffic_data (segment_id, date, speed, travel_time)
            VALUES (:segment_id, :date, :speed, :travel_time)
        """)

        api_calls = 0
        max_calls = SEGMENT_LIMIT  # Stays under Google budget while maximizing roads
        
        for segment in segments:
            if api_calls >= max_calls:
                break

            if None in (segment.start_lat, segment.start_lon, segment.end_lat, segment.end_lon):
                continue

            start = (segment.start_lat, segment.start_lon)
            end = (segment.end_lat, segment.end_lon)
            
            if api_calls >= max_calls:
                break

            try:
                # Compute departure time immediately before the request to avoid drift.
                departure_time = next_departure_time()
                try:
                    directions = gmaps.directions(
                        start, end,
                        mode="driving",
                        departure_time=departure_time,
                        traffic_model="best_guess"
                    )
                except Exception as e:
                    # If we still get a "departure_time is in the past" error (long pauses, clock skew),
                    # retry once with a freshly computed value.
                    if "departure_time is in the past" in str(e):
                        departure_time = next_departure_time()
                        directions = gmaps.directions(
                            start, end,
                            mode="driving",
                            departure_time=departure_time,
                            traffic_model="best_guess"
                        )
                    else:
                        raise
                api_calls += 1
                if directions:
                    duration = directions[0]['legs'][0]['duration_in_traffic']['value']
                    distance = directions[0]['legs'][0]['distance']['value']
                    if duration <= 0 or distance <= 0:
                        print(f"Skipping segment {segment.id} because duration or distance is zero")
                    else:
                        speed = (distance / 1000) / (duration / 3600)  # km/h

                        # Store the timestamp used for the API request as the snapshot time.
                        db.execute(insert_query, {
                            "segment_id": segment.id,
                            "date": departure_time,
                            "speed": speed,
                            "travel_time": duration
                        })
            except Exception as e:
                print(f"API error for segment {segment.id}: {e}")
                api_calls += 1
        
        db.commit()
        print(f"Traffic data inserted, API calls made: {api_calls}")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    fetch_traffic_data()
