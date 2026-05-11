import logging
import osmnx as ox
try:
    from .database import SessionLocal, engine
    from .models import TrafficSignal
except ImportError:  # allows `python backend/fetch_signals.py`
    from database import SessionLocal, engine
    from models import TrafficSignal
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

def fetch_pune_signals():
    # Fetch traffic signals for Pune
    logging.info('Fetching traffic signals from OSMnx...')
    try:
        # Get nodes tagged as traffic_signals
        tags = {"highway": "traffic_signals"}
        gdf = ox.features_from_point((18.5204, 73.8567), dist=10000, tags=tags)
        
        # Keep only point geometries (nodes)
        gdf = gdf[gdf.geometry.type == 'Point']
        
        total_rows = len(gdf)
        logging.info(f'Loaded {total_rows} traffic signals from OSMnx')
        
        db = SessionLocal()
        count = 0
        
        for idx, row in gdf.iterrows():
            geom = row.geometry
            wkt = geom.wkt
            
            # Use raw SQL to insert with ST_GeomFromText and city metadata
            query = text("""
                INSERT INTO traffic_signals (city, geometry)
                VALUES (:city, ST_GeomFromText(:wkt, 4326))
            """)
            db.execute(query, {"city": 'pune', "wkt": wkt})
            count += 1
            if count % 100 == 0:
                logging.info(f'Inserted {count} signals...')

        db.commit()
        logging.info(f"Successfully inserted {count} traffic signals into database")
    except Exception as e:
        db.rollback()
        logging.error('Error fetching or inserting traffic signals', exc_info=e)
    finally:
        db.close()

if __name__ == "__main__":
    fetch_pune_signals()
