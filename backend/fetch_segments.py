import logging
import os

import osmnx as ox
from sqlalchemy import text

try:
    from .database import SessionLocal, engine
    from .models import RoadSegment
except ImportError:  # allows `python backend/fetch_segments.py`
    from database import SessionLocal, engine
    from models import RoadSegment

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

# Major Indian Cities for easy reference
MAJOR_INDIAN_CITIES = [
    "Mumbai, India", "Delhi, India", "Bangalore, India", "Hyderabad, India",
    "Ahmedabad, India", "Chennai, India", "Kolkata, India", "Surat, India",
    "Pune, India", "Jaipur, India", "Lucknow, India", "Kanpur, India",
    "Nagpur, India", "Indore, India", "Thane, India", "Bhopal, India"
]

INSERT_BATCH_SIZE = max(1, int(os.getenv("SEGMENT_INSERT_BATCH_SIZE", "500")))


def print_progress(iteration: int, total: int, prefix: str = '', suffix: str = '', length: int = 40) -> None:
    if total <= 0:
        return
    percent = 100 * (iteration / float(total))
    filled_length = int(length * iteration // total)
    bar = '█' * filled_length + '-' * (length - filled_length)
    print(f'\r{prefix} |{bar}| {percent:6.2f}% {suffix}', end='')
    if iteration >= total:
        print()


def _flush_segment_batch(db, query, batch_params: list[dict], short_city_name: str, total_saved: int) -> int:
    """Insert one batch and commit immediately so Railway restarts lose minimal work."""
    if not batch_params:
        return total_saved

    db.execute(query, batch_params)
    db.commit()
    total_saved += len(batch_params)
    logging.info(
        'Persisted %s/%s road segments for %s to Supabase',
        total_saved,
        total_saved,
        short_city_name,
    )
    batch_params.clear()
    return total_saved


def fetch_segments_for_city(city_query: str) -> bool:
    logging.info(f'Fetching road network for "{city_query}" (15km radius) from OSMnx...')
    try:
        # Use graph_from_address with a radius to be more reliable than boundary polygons
        G = ox.graph_from_address(city_query, dist=15000, network_type='drive', simplify=True)

        # Convert to GeoDataFrame
        gdf = ox.graph_to_gdfs(G, nodes=False)
        total_rows = len(gdf)
        logging.info(f'Loaded {total_rows} road segments for {city_query}')

        db = SessionLocal()
        saved_ok = False
        short_city_name = city_query.split(',')[0].strip().lower()
        insert_query = text("""
            INSERT INTO road_segments (name, city, geometry, lanes, highway_type, oneway)
            VALUES (:name, :city, ST_GeomFromText(:wkt, 4326), :lanes, :highway_type, :oneway)
        """)

        try:
            # Clear any previous partial import so retries are deterministic.
            deleted = db.execute(
                text("DELETE FROM road_segments WHERE city = :city"),
                {"city": short_city_name},
            ).rowcount or 0
            db.commit()
            if deleted:
                logging.info(
                    'Removed %s existing road segments for %s before re-import',
                    deleted,
                    short_city_name,
                )

            total_saved = 0
            processed = 0
            batch_params: list[dict] = []

            for _, row in gdf.iterrows():
                processed += 1
                if processed % 100 == 0:
                    print_progress(processed, total_rows, prefix='Processing', suffix=f'{processed}/{total_rows}')

                geom = row.geometry
                if geom.geom_type != 'LineString':
                    continue

                name = row.get('name', 'Unknown')
                if isinstance(name, list):
                    name = name[0]

                lanes_raw = row.get('lanes', None)
                lanes = None
                if lanes_raw:
                    try:
                        lanes = int(lanes_raw[0] if isinstance(lanes_raw, list) else lanes_raw)
                    except Exception:
                        lanes = None

                highway_raw = row.get('highway', 'Unknown')
                highway_type = highway_raw[0] if isinstance(highway_raw, list) else highway_raw

                oneway_raw = row.get('oneway', False)
                oneway = str(oneway_raw[0] if isinstance(oneway_raw, list) else oneway_raw)

                batch_params.append({
                    'name': str(name),
                    'city': short_city_name,
                    'wkt': geom.wkt,
                    'lanes': lanes,
                    'highway_type': str(highway_type),
                    'oneway': str(oneway),
                })

                if len(batch_params) >= INSERT_BATCH_SIZE:
                    total_saved = _flush_segment_batch(db, insert_query, batch_params, short_city_name, total_saved)

            if total_rows > 0:
                print_progress(total_rows, total_rows, prefix='Processing', suffix=f'{total_rows}/{total_rows}')

            total_saved = _flush_segment_batch(db, insert_query, batch_params, short_city_name, total_saved)
            logging.info('Successfully inserted %s segments for %s', total_saved, short_city_name)
            saved_ok = True
        except Exception as e:
            db.rollback()
            logging.error(f'Error saving segments for {city_query}', exc_info=e)
        finally:
            db.close()
        return saved_ok
    except Exception as e:
        logging.error(f'Failed to fetch data for {city_query}: {e}')
        return False


if __name__ == "__main__":
    target_city = os.getenv("CITY_NAME", "Pune, India")
    fetch_segments_for_city(target_city)
