"""
Fetch real-time traffic data from TomTom Flow Segment Data API
and store it in the traffic_data table in Supabase.

TomTom Flow Segment API:
  GET https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json
      ?point={lat},{lon}&key={API_KEY}

Returns per-segment: currentSpeed, freeFlowSpeed, currentTravelTime, freeFlowTravelTime
"""

import os
import time
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY")
TOMTOM_BASE = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"

# Rate limiting: TomTom free tier is 2,500 calls/day.
# We batch calls with a small delay to avoid hammering.
DELAY_BETWEEN_CALLS = 0.5  # seconds
MAX_SEGMENTS_PER_RUN = 200  # conservative limit per fetch run


def _midpoint(start_lat, start_lon, end_lat, end_lon):
    return (start_lat + end_lat) / 2, (start_lon + end_lon) / 2


def fetch_tomtom_segment(lat: float, lon: float) -> dict | None:
    """
    Query TomTom Flow Segment Data for a road near the given coordinate.
    Returns a dict with speed/travel_time or None on failure.
    """
    if not TOMTOM_API_KEY:
        logger.error("TOMTOM_API_KEY is not set")
        return None
    try:
        resp = requests.get(
            TOMTOM_BASE,
            params={
                "point": f"{lat},{lon}",
                "key": TOMTOM_API_KEY,
                "unit": "KMPH",
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json().get("flowSegmentData", {})
            current_speed = data.get("currentSpeed")
            current_travel_time = data.get("currentTravelTime")
            free_flow_speed = data.get("freeFlowSpeed")
            confidence = data.get("confidence", 1.0)
            if current_speed is not None and current_speed > 0:
                return {
                    "speed": float(current_speed),
                    "travel_time": float(current_travel_time) if current_travel_time else None,
                    "free_flow_speed": float(free_flow_speed) if free_flow_speed else None,
                    "confidence": float(confidence),
                }
        elif resp.status_code == 429:
            logger.warning("TomTom rate limit hit — pausing 5s")
            time.sleep(5)
        else:
            logger.debug("TomTom %s for point %s,%s", resp.status_code, lat, lon)
    except Exception as e:
        logger.warning("TomTom request error: %s", e)
    return None


def fetch_traffic_tomtom(city: str | None = None, limit: int = MAX_SEGMENTS_PER_RUN) -> dict:
    """
    Main entry point. Fetches traffic for up to `limit` segments
    (optionally filtered by city) and inserts rows into traffic_data.

    Returns a summary dict for the API response.
    """
    try:
        from database import SessionLocal
    except ImportError:
        from backend.database import SessionLocal

    from sqlalchemy import text

    if not TOMTOM_API_KEY:
        return {"error": "TOMTOM_API_KEY not configured", "fetched": 0, "failed": 0}

    db = SessionLocal()
    fetched = 0
    failed = 0
    skipped = 0
    snapshot_time = datetime.utcnow()

    try:
        city_clause = "AND LOWER(city) = LOWER(:city)" if city else ""
        rows = db.execute(
            text(f"""
                SELECT
                    id,
                    ST_Y(ST_StartPoint(geometry)) AS start_lat,
                    ST_X(ST_StartPoint(geometry)) AS start_lon,
                    ST_Y(ST_EndPoint(geometry))   AS end_lat,
                    ST_X(ST_EndPoint(geometry))   AS end_lon
                FROM road_segments
                WHERE geometry IS NOT NULL
                {city_clause}
                ORDER BY id
                LIMIT :limit
            """),
            {"city": city, "limit": limit} if city else {"limit": limit},
        ).fetchall()

        insert_q = text("""
            INSERT INTO traffic_data (segment_id, date, speed, travel_time)
            VALUES (:segment_id, :date, :speed, :travel_time)
        """)

        for row in rows:
            if None in (row.start_lat, row.start_lon, row.end_lat, row.end_lon):
                skipped += 1
                continue

            mid_lat, mid_lon = _midpoint(
                row.start_lat, row.start_lon, row.end_lat, row.end_lon
            )

            result = fetch_tomtom_segment(mid_lat, mid_lon)
            if result:
                db.execute(insert_q, {
                    "segment_id": row.id,
                    "date": snapshot_time,
                    "speed": result["speed"],
                    "travel_time": result["travel_time"],
                })
                fetched += 1
            else:
                failed += 1

            time.sleep(DELAY_BETWEEN_CALLS)

        db.commit()
        logger.info(
            "TomTom fetch complete: fetched=%d failed=%d skipped=%d city=%s",
            fetched, failed, skipped, city or "all",
        )
    except Exception as e:
        db.rollback()
        logger.exception("fetch_traffic_tomtom error: %s", e)
        return {"error": str(e), "fetched": fetched, "failed": failed}
    finally:
        db.close()

    return {
        "fetched": fetched,
        "failed": failed,
        "skipped": skipped,
        "snapshot_time": snapshot_time.isoformat(),
        "city": city or "all",
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    city_arg = sys.argv[1] if len(sys.argv) > 1 else None
    print(fetch_traffic_tomtom(city=city_arg))
