import logging
import os
import osmnx as ox
try:
    from .database import SessionLocal, engine
    from .models import TrafficSignal
except ImportError:  # allows `python backend/fetch_signals.py`
    from database import SessionLocal, engine
    from models import TrafficSignal
from sqlalchemy import text

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

def fetch_signals_for_city(city_query: str):
    logging.info(f'Fetching traffic signals for "{city_query}" from OSMnx...')
    try:
        # Get nodes tagged as traffic_signals
        tags = {"highway": "traffic_signals"}
        gdf = ox.features_from_place(city_query, tags=tags)
        
        # Keep only point geometries (nodes)
        gdf = gdf[gdf.geometry.type == 'Point']
        
        total_rows = len(gdf)
        logging.info(f'Loaded {total_rows} traffic signals for {city_query}')
        
        db = SessionLocal()
        try:
            count = 0
            short_city_name = city_query.split(',')[0].strip().lower()
            
            for idx, row in gdf.iterrows():
                geom = row.geometry
                wkt = geom.wkt
                
                query = text("""
                    INSERT INTO traffic_signals (city, geometry)
                    VALUES (:city, ST_GeomFromText(:wkt, 4326))
                    ON CONFLICT DO NOTHING
                """)
                db.execute(query, {"city": short_city_name, "wkt": wkt})
                count += 1
                if count % 100 == 0:
                    logging.info(f'Inserted {count} signals...')

            db.commit()
            logging.info(f"Successfully inserted {count} signals for {short_city_name}")
        except Exception as e:
            db.rollback()
            logging.error(f'Error saving signals for {city_query}', exc_info=e)
        finally:
            db.close()
    except Exception as e:
        logging.error(f'Failed to fetch signals for {city_query}: {e}')

if __name__ == "__main__":
    target_city = os.getenv("CITY_NAME", "Pune, India")
    fetch_signals_for_city(target_city)
