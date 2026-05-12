import logging
import os
import osmnx as ox
try:
    from .database import SessionLocal, engine
    from .models import RoadSegment
except ImportError:  # allows `python backend/fetch_segments.py`
    from database import SessionLocal, engine
    from models import RoadSegment
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

# Major Indian Cities for easy reference
MAJOR_INDIAN_CITIES = [
    "Mumbai, India", "Delhi, India", "Bangalore, India", "Hyderabad, India",
    "Ahmedabad, India", "Chennai, India", "Kolkata, India", "Surat, India",
    "Pune, India", "Jaipur, India", "Lucknow, India", "Kanpur, India",
    "Nagpur, India", "Indore, India", "Thane, India", "Bhopal, India"
]

def print_progress(iteration: int, total: int, prefix: str = '', suffix: str = '', length: int = 40) -> None:
    if total <= 0:
        return
    percent = 100 * (iteration / float(total))
    filled_length = int(length * iteration // total)
    bar = '█' * filled_length + '-' * (length - filled_length)
    print(f'\r{prefix} |{bar}| {percent:6.2f}% {suffix}', end='')
    if iteration >= total:
        print()

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
        try:
            count = 0
            processed = 0
            short_city_name = city_query.split(',')[0].strip().lower()

            for idx, row in gdf.iterrows():
                processed += 1
                if processed % 100 == 0:
                    print_progress(processed, total_rows, prefix='Processing', suffix=f'{processed}/{total_rows}')

                geom = row.geometry
                if geom.geom_type == 'LineString':
                    wkt = geom.wkt
                    name = row.get('name', 'Unknown')
                    if isinstance(name, list): name = name[0]

                    lanes_raw = row.get('lanes', None)
                    lanes = None
                    if lanes_raw:
                        try:
                            lanes = int(lanes_raw[0] if isinstance(lanes_raw, list) else lanes_raw)
                        except: pass

                    highway_raw = row.get('highway', 'Unknown')
                    highway_type = highway_raw[0] if isinstance(highway_raw, list) else highway_raw

                    oneway_raw = row.get('oneway', False)
                    oneway = str(oneway_raw[0] if isinstance(oneway_raw, list) else oneway_raw)

                    query = text("""
                        INSERT INTO road_segments (name, city, geometry, lanes, highway_type, oneway)
                        VALUES (:name, :city, ST_GeomFromText(:wkt, 4326), :lanes, :highway_type, :oneway)
                        ON CONFLICT DO NOTHING
                    """)
                    db.execute(query, {
                        "name": str(name),
                        "city": short_city_name,
                        "wkt": wkt,
                        "lanes": lanes,
                        "highway_type": str(highway_type),
                        "oneway": str(oneway)
                    })
                    count += 1

            db.commit()
            logging.info(f"Successfully inserted/updated {count} segments for {short_city_name}")
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
