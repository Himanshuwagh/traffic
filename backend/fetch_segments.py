import logging
import osmnx as ox
try:
    from .database import SessionLocal, engine
    from .models import RoadSegment
except ImportError:  # allows `python backend/fetch_segments.py`
    from database import SessionLocal, engine
    from models import RoadSegment
from sqlalchemy import text

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


def fetch_pune_segments():
    # Get road network for Pune center (10km radius)
    G = ox.graph_from_point((18.5204, 73.8567), dist=10000, network_type='drive')
    
    # Convert to GeoDataFrame
    gdf = ox.graph_to_gdfs(G, nodes=False)
    total_rows = len(gdf)
    logging.info(f'Loaded {total_rows} candidate road segments from OSMnx')
    
    db = SessionLocal()
    try:
        count = 0
        max_segments = 150000  # Increased limit
        processed = 0
        for idx, row in gdf.iterrows():
            processed += 1
            print_progress(processed, total_rows, prefix='Processing', suffix=f'{processed}/{total_rows} rows')
            if count >= max_segments:
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
                    "city": 'pune', 
                    "wkt": wkt,
                    "lanes": lanes,
                    "highway_type": str(highway_type),
                    "oneway": str(oneway)
                })
                count += 1
                logging.info(f'Inserted segment {count}: "{name}" (OSM ID {idx})')
        print_progress(total_rows, total_rows, prefix='Processing', suffix=f'{total_rows}/{total_rows} rows')

        db.commit()
        logging.info(f"Inserted {count} road segments")
    except Exception as e:
        db.rollback()
        logging.error('Error inserting road segments', exc_info=e)
    finally:
        db.close()

if __name__ == "__main__":
    fetch_pune_segments()