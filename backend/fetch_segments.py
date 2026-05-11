import logging
import os
import osmnx as ox
from dotenv import load_dotenv

try:
    from .database import SessionLocal, engine
    from .models import RoadSegment
except ImportError:  # allows `python backend/fetch_segments.py`
    from database import SessionLocal, engine
    from models import RoadSegment
from sqlalchemy import text

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

def print_progress(iteration: int, total: int, prefix: str = '', suffix: str = '', length: int = 40) -> None:
    if total <= 0:
        return
    percent = 100 * (iteration / float(total))
    filled_length = int(length * iteration // total)
    bar = '█' * filled_length + '-' * (length - filled_length)
    print(f'\r{prefix} |{bar}| {percent:6.2f}% {suffix}', end='')
    if iteration >= total:
        print()


def fetch_road_segments():
    location = os.getenv("FETCH_LOCATION", "Pune, India")
    city_tag = os.getenv("CITY_TAG", location.split(',')[0].lower().strip())
    
    logging.info(f'Fetching road network for: {location}...')
    
    try:
        # Try fetching by place name first
        G = ox.graph_from_place(location, network_type='drive')
    except Exception as e:
        logging.warning(f"Could not fetch by place name '{location}', trying coordinates... Error: {e}")
        # Fallback to Pune coordinates if place name fails and no specific coordinates provided
        lat = float(os.getenv("FETCH_LAT", "18.5204"))
        lon = float(os.getenv("FETCH_LON", "73.8567"))
        dist = int(os.getenv("FETCH_DIST", "10000"))
        G = ox.graph_from_point((lat, lon), dist=dist, network_type='drive')
    
    # Convert to GeoDataFrame
    gdf = ox.graph_to_gdfs(G, nodes=False)
    total_rows = len(gdf)
    logging.info(f'Loaded {total_rows} candidate road segments')
    
    db = SessionLocal()
    try:
        count = 0
        max_segments = int(os.getenv("MAX_SEGMENTS", "150000"))
        processed = 0
        for idx, row in gdf.iterrows():
            processed += 1
            if processed % 100 == 0:
                print_progress(processed, total_rows, prefix='Processing', suffix=f'{processed}/{total_rows} rows')
            
            if count >= max_segments:
                logging.info(f"Reached max segments limit ({max_segments})")
                break
            
            # Create LineString from geometry
            geom = row.geometry
            if geom.geom_type == 'LineString':
                # Convert to WKT format for SQL insertion
                wkt = geom.wkt
                name = row.get('name', 'Unknown')
                if isinstance(name, list): name = name[0]
                
                # Extract infrastructure data safely
                lanes_raw = row.get('lanes', None)
                lanes = None
                if lanes_raw:
                    try:
                        lanes = int(lanes_raw[0] if isinstance(lanes_raw, list) else lanes_raw)
                    except:
                        pass
                
                highway_raw = row.get('highway', 'Unknown')
                highway_type = highway_raw[0] if isinstance(highway_raw, list) else highway_raw
                
                oneway_raw = row.get('oneway', False)
                oneway = str(oneway_raw[0] if isinstance(oneway_raw, list) else oneway_raw)
                
                # Use raw SQL to insert with ST_GeomFromText and infra metadata
                query = text("""
                    INSERT INTO road_segments (name, city, geometry, lanes, highway_type, oneway)
                    VALUES (:name, :city, ST_GeomFromText(:wkt, 4326), :lanes, :highway_type, :oneway)
                """)
                db.execute(query, {
                    "name": str(name), 
                    "city": city_tag, 
                    "wkt": wkt,
                    "lanes": lanes,
                    "highway_type": str(highway_type),
                    "oneway": str(oneway)
                })
                count += 1
        
        print_progress(total_rows, total_rows, prefix='Processing', suffix=f'{total_rows}/{total_rows} rows')
        db.commit()
        logging.info(f"Successfully inserted {count} road segments for {city_tag}")
    except Exception as e:
        db.rollback()
        logging.error('Error inserting road segments', exc_info=e)
    finally:
        db.close()

if __name__ == "__main__":
    fetch_road_segments()