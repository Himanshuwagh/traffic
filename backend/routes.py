from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
import json
import time
try:
    from .database import get_db
except ImportError:
    from database import get_db

router = APIRouter()

TRAFFIC_CACHE_TTL_SECONDS = 30
TRAFFIC_CACHE_MAX_ENTRIES = 128
traffic_response_cache: dict[tuple, tuple[float, str]] = {}
traffic_summary_cache: dict[tuple, tuple[float, dict]] = {}
traffic_tile_cache: dict[tuple, tuple[float, bytes]] = {}
MVT_LAYER_NAME = "traffic"

MAJOR_HIGHWAY_TYPES = (
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
)

MEDIUM_HIGHWAY_TYPES = MAJOR_HIGHWAY_TYPES + (
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
)


def get_traffic_color(speed):
    """Map speed to traffic color (Google Maps style)"""
    if speed is None:
        return "#888888"  # Gray for unknown
    elif speed >= 40:
        return "#00C700"  # Green - free flow
    elif speed >= 25:
        return "#FFFF00"  # Yellow - moderate
    elif speed >= 15:
        return "#FF9900"  # Orange - heavy
    else:
        return "#FF0000"  # Red - congested


def traffic_detail_for_zoom(zoom: float | None, requested_limit: int) -> tuple[tuple[str, ...] | None, int, float]:
    if zoom is None or zoom <= 12:
        return MAJOR_HIGHWAY_TYPES, min(requested_limit, 1500), 0.0004
    if zoom < 14:
        return MEDIUM_HIGHWAY_TYPES, min(requested_limit, 6000), 0.00015
    if zoom < 16:
        return None, min(requested_limit, 10000), 0.00003
    return None, min(requested_limit, 20000), 0.0


def rounded_bbox_key(bbox_vals: tuple[float, float, float, float] | None) -> tuple[float, ...] | None:
    if bbox_vals is None:
        return None
    return tuple(round(value, 4) for value in bbox_vals)


def parse_bbox(bbox: str | None) -> tuple[float, float, float, float] | None:
    if not bbox:
        return None
    parts = [p.strip() for p in bbox.split(",")]
    if len(parts) != 4:
        return None
    try:
        return (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
    except ValueError:
        return None


def lookup_cached_response(cache: dict[tuple, tuple[float, object]], cache_key: tuple, now: float):
    cached = cache.get(cache_key)
    if cached and now - cached[0] <= TRAFFIC_CACHE_TTL_SECONDS:
        return cached[1]
    return None


def store_cached_response(cache: dict[tuple, tuple[float, object]], cache_key: tuple, payload: object, now: float):
    if len(cache) >= TRAFFIC_CACHE_MAX_ENTRIES:
        expired_keys = [
            key
            for key, (cached_at, _) in cache.items()
            if now - cached_at > TRAFFIC_CACHE_TTL_SECONDS
        ]
        for key in expired_keys:
            cache.pop(key, None)
        if len(cache) >= TRAFFIC_CACHE_MAX_ENTRIES:
            cache.clear()
    cache[cache_key] = (now, payload)


def build_common_filters(
    *,
    city: str | None,
    highway_types: tuple[str, ...] | None,
    bbox_vals: tuple[float, float, float, float] | None = None,
    geometry_column: str = "rs.geometry",
) -> tuple[str, dict]:
    where_clauses: list[str] = []
    params: dict = {}
    if city:
        where_clauses.append("LOWER(rs.city) = LOWER(:city)")
        params["city"] = city
    if bbox_vals:
        where_clauses.append(
            f"{geometry_column} && ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)"
        )
        params.update(
            {"min_lon": bbox_vals[0], "min_lat": bbox_vals[1], "max_lon": bbox_vals[2], "max_lat": bbox_vals[3]}
        )
    if highway_types:
        where_clauses.append("(rs.highway_type IS NULL OR rs.highway_type = ANY(CAST(:highway_types AS text[])))")
        params["highway_types"] = list(highway_types)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    return where_sql, params

@router.get("/api/traffic/{date_str}")
async def get_traffic_by_date(
    date_str: str,
    city: str | None = None,
    bbox: str | None = Query(default=None, description="minLon,minLat,maxLon,maxLat"),
    zoom: float | None = Query(default=None),
    limit: int = Query(default=20000, ge=1, le=50000),
    db: Session = Depends(get_db),
):
    """Get traffic data for a specific date/time in ISO format"""
    try:
        target_time = datetime.fromisoformat(date_str)
        bbox_vals = parse_bbox(bbox)

        highway_types, limit, simplify_tolerance = traffic_detail_for_zoom(zoom, limit)
        cache_key = (
            city.lower() if city else None,
            target_time.isoformat(timespec="hours"),
            round(zoom or 0, 1),
            limit,
            simplify_tolerance,
            highway_types,
            rounded_bbox_key(bbox_vals),
        )
        now = time.monotonic()
        cached = lookup_cached_response(traffic_response_cache, cache_key, now)
        if cached:
            return Response(content=cached, media_type="application/json")

        params: dict = {
            "target_time": target_time,
            "limit": limit,
            "simplify_tolerance": simplify_tolerance,
        }
        where_sql, filter_params = build_common_filters(city=city, highway_types=highway_types, bbox_vals=bbox_vals)
        params.update(filter_params)

        base_query = f"""
            WITH closest_traffic AS (
                SELECT DISTINCT ON (td.segment_id)
                    td.segment_id,
                    td.speed,
                    td.travel_time,
                    td.date
                FROM traffic_data td
                WHERE td.date BETWEEN :target_time - INTERVAL '7 days' AND :target_time + INTERVAL '7 days'
                ORDER BY td.segment_id, abs(extract(epoch from td.date - :target_time))
            ),
            limited AS (
                SELECT
                    rs.id,
                    rs.name,
                    rs.highway_type,
                    CASE
                        WHEN :simplify_tolerance > 0 THEN ST_SimplifyPreserveTopology(rs.geometry, :simplify_tolerance)
                        ELSE rs.geometry
                    END AS geometry,
                    ct.speed,
                    ct.travel_time,
                    ct.date
                FROM road_segments rs
                JOIN closest_traffic ct ON ct.segment_id = rs.id
                {where_sql}
                ORDER BY rs.id
                LIMIT :limit
            ),
            features AS (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'geometry', ST_AsGeoJSON(geometry, 5)::jsonb,
                    'properties', jsonb_build_object(
                        'id', id,
                        'name', COALESCE(name, 'Unknown'),
                        'highway_type', COALESCE(highway_type, 'unknown'),
                        'speed', speed,
                        'travel_time', travel_time,
                        'color', CASE
                            WHEN speed IS NULL THEN '#888888'
                            WHEN speed >= 40 THEN '#00C700'
                            WHEN speed >= 25 THEN '#FFFF00'
                            WHEN speed >= 15 THEN '#FF9900'
                            ELSE '#FF0000'
                        END
                    )
                ) AS feature
                FROM limited
                WHERE geometry IS NOT NULL
            )
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(feature), '[]'::jsonb)
            )::text AS geojson
            FROM features
        """
        
        query = text(base_query)
        geojson = db.execute(query, params).scalar() or '{"type":"FeatureCollection","features":[]}'
        store_cached_response(traffic_response_cache, cache_key, geojson, now)
        return Response(content=geojson, media_type="application/json")
    except Exception as e:
        return {"error": str(e), "type": "FeatureCollection", "features": []}


@router.get("/api/traffic/summary/{date_str}")
async def get_traffic_summary(
    date_str: str,
    city: str | None = None,
    bbox: str | None = Query(default=None, description="minLon,minLat,maxLon,maxLat"),
    zoom: float | None = Query(default=None),
    limit: int = Query(default=2000, ge=1, le=10000),
    db: Session = Depends(get_db),
):
    """Return lightweight metrics for the visible viewport without geometry payloads."""
    try:
        target_time = datetime.fromisoformat(date_str)
        bbox_vals = parse_bbox(bbox)
        highway_types, limit, _ = traffic_detail_for_zoom(zoom, limit)
        cache_key = (
            "summary",
            city.lower() if city else None,
            target_time.isoformat(timespec="hours"),
            round(zoom or 0, 1),
            limit,
            highway_types,
            rounded_bbox_key(bbox_vals),
        )
        now = time.monotonic()
        cached = lookup_cached_response(traffic_summary_cache, cache_key, now)
        if cached:
            return cached

        where_sql, filter_params = build_common_filters(city=city, highway_types=highway_types, bbox_vals=bbox_vals)
        params = {"target_time": target_time, "limit": limit, **filter_params}

        query = text(
            f"""
            WITH closest_traffic AS (
                SELECT DISTINCT ON (td.segment_id)
                    td.segment_id,
                    td.speed,
                    td.travel_time,
                    td.date
                FROM traffic_data td
                WHERE td.date BETWEEN :target_time - INTERVAL '7 days' AND :target_time + INTERVAL '7 days'
                ORDER BY td.segment_id, abs(extract(epoch from td.date - :target_time))
            ),
            visible_segments AS (
                SELECT
                    rs.id,
                    COALESCE(rs.name, 'Unknown') AS name,
                    COALESCE(rs.highway_type, 'unknown') AS highway_type,
                    ct.speed,
                    ct.travel_time
                FROM road_segments rs
                JOIN closest_traffic ct ON ct.segment_id = rs.id
                {where_sql}
                ORDER BY rs.id
                LIMIT :limit
            ),
            bottlenecks AS (
                SELECT
                    id,
                    name,
                    highway_type,
                    speed,
                    travel_time
                FROM visible_segments
                WHERE speed IS NOT NULL
                ORDER BY speed ASC, id ASC
                LIMIT 10
            )
            SELECT jsonb_build_object(
                'avg_speed', ROUND(AVG(speed)::numeric, 1),
                'active_segments', COUNT(*) FILTER (WHERE speed IS NOT NULL),
                'top_corridor_name', (
                    SELECT name
                    FROM bottlenecks
                    ORDER BY speed ASC, id ASC
                    LIMIT 1
                ),
                'status', 'live',
                'top_bottlenecks', COALESCE((
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'id', id,
                            'name', name,
                            'highway_type', highway_type,
                            'speed', speed,
                            'travel_time', travel_time,
                            'color', CASE
                                WHEN speed IS NULL THEN '#888888'
                                WHEN speed >= 40 THEN '#00C700'
                                WHEN speed >= 25 THEN '#FFFF00'
                                WHEN speed >= 15 THEN '#FF9900'
                                ELSE '#FF0000'
                            END,
                            'cfi', GREATEST(0, 100 - COALESCE(speed, 0) * 2.5)
                        )
                        ORDER BY speed ASC, id ASC
                    )
                    FROM bottlenecks
                ), '[]'::jsonb)
            ) AS summary
            FROM visible_segments
            """
        )

        summary = db.execute(query, params).scalar() or {
            "avg_speed": None,
            "active_segments": 0,
            "top_corridor_name": None,
            "status": "live",
            "top_bottlenecks": [],
        }
        store_cached_response(traffic_summary_cache, cache_key, summary, now)
        return summary
    except Exception as e:
        return {
            "error": str(e),
            "avg_speed": None,
            "active_segments": 0,
            "top_corridor_name": None,
            "status": "unavailable",
            "top_bottlenecks": [],
        }


@router.get("/api/traffic/tiles/{date_str}/{z}/{x}/{y}.mvt")
async def get_traffic_tile(
    date_str: str,
    z: int,
    x: int,
    y: int,
    city: str | None = None,
    db: Session = Depends(get_db),
):
    """Serve traffic as vector tiles so the browser can incrementally render visible roads."""
    try:
        target_time = datetime.fromisoformat(date_str)
        highway_types, _, simplify_tolerance = traffic_detail_for_zoom(float(z), 50000)
        cache_key = (
            "tile",
            city.lower() if city else None,
            target_time.isoformat(timespec="hours"),
            z,
            x,
            y,
            simplify_tolerance,
            highway_types,
        )
        now = time.monotonic()
        cached = lookup_cached_response(traffic_tile_cache, cache_key, now)
        if cached:
            return Response(
                content=cached,
                media_type="application/vnd.mapbox-vector-tile",
                headers={"Cache-Control": "public, max-age=30"},
            )

        where_sql, filter_params = build_common_filters(
            city=city,
            highway_types=highway_types,
            bbox_vals=None,
            geometry_column="rs.geometry",
        )
        if where_sql:
            where_sql = f"{where_sql} AND rs.geometry && bounds.bounds_4326"
        else:
            where_sql = "WHERE rs.geometry && bounds.bounds_4326"

        params = {
            "target_time": target_time,
            "z": z,
            "x": x,
            "y": y,
            "simplify_tolerance": simplify_tolerance,
            **filter_params,
        }

        query = text(
            f"""
            WITH bounds AS (
                SELECT
                    ST_TileEnvelope(:z, :x, :y) AS bounds_3857,
                    ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326) AS bounds_4326
            ),
            closest_traffic AS (
                SELECT DISTINCT ON (td.segment_id)
                    td.segment_id,
                    td.speed,
                    td.travel_time,
                    td.date
                FROM traffic_data td
                WHERE td.date BETWEEN :target_time - INTERVAL '7 days' AND :target_time + INTERVAL '7 days'
                ORDER BY td.segment_id, abs(extract(epoch from td.date - :target_time))
            ),
            tile_rows AS (
                SELECT
                    rs.id,
                    COALESCE(rs.name, 'Unknown') AS name,
                    COALESCE(rs.highway_type, 'unknown') AS highway_type,
                    ct.speed,
                    ct.travel_time,
                    CASE
                        WHEN ct.speed IS NULL THEN '#888888'
                        WHEN ct.speed >= 40 THEN '#00C700'
                        WHEN ct.speed >= 25 THEN '#FFFF00'
                        WHEN ct.speed >= 15 THEN '#FF9900'
                        ELSE '#FF0000'
                    END AS color,
                    ST_AsMVTGeom(
                        ST_Transform(
                            CASE
                                WHEN :simplify_tolerance > 0 THEN ST_SimplifyPreserveTopology(rs.geometry, :simplify_tolerance)
                                ELSE rs.geometry
                            END,
                            3857
                        ),
                        bounds.bounds_3857,
                        4096,
                        256,
                        true
                    ) AS geom
                FROM road_segments rs
                JOIN closest_traffic ct ON ct.segment_id = rs.id
                CROSS JOIN bounds
                {where_sql}
            )
            SELECT ST_AsMVT(tile_rows, '{MVT_LAYER_NAME}', 4096, 'geom')
            FROM tile_rows
            WHERE geom IS NOT NULL
            """
        )

        tile = db.execute(query, params).scalar() or b""
        store_cached_response(traffic_tile_cache, cache_key, tile, now)
        return Response(
            content=tile,
            media_type="application/vnd.mapbox-vector-tile",
            headers={"Cache-Control": "public, max-age=30"},
        )
    except Exception as e:
        return Response(content=str(e), media_type="text/plain", status_code=500)

@router.get("/api/signals")
async def get_traffic_signals(city: str | None = None, db: Session = Depends(get_db)):
    """Get traffic signals for a city"""
    try:
        base_query = """
            SELECT
                id,
                ST_AsGeoJSON(geometry)::text as geometry
            FROM traffic_signals
        """
        
        params = {}
        if city:
            base_query += " WHERE LOWER(city) = LOWER(:city)"
            params["city"] = city
            
        query = text(base_query)
        results = db.execute(query, params).fetchall()
        
        features = []
        for row in results:
            try:
                geometry = json.loads(row.geometry) if row.geometry else None
            except Exception:
                geometry = None
                
            if geometry:
                feature = {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {
                        "id": row.id,
                        "type": "traffic_signal"
                    }
                }
                features.append(feature)
        
        return {"type": "FeatureCollection", "features": features}
    except Exception as e:
        return {"error": str(e), "type": "FeatureCollection", "features": []}

@router.get("/api/weather/{date_str}")
async def get_weather(date_str: str, city: str, db: Session = Depends(get_db)):
    """Get closest weather data for a city at a specific time."""
    try:
        target_time = datetime.fromisoformat(date_str)
        
        # Find the single closest weather record
        query = text("""
            SELECT temperature, condition, precipitation 
            FROM weather_data 
            WHERE LOWER(city) = LOWER(:city)
            ORDER BY abs(extract(epoch from timestamp - :target_time)) 
            LIMIT 1
        """)
        
        result = db.execute(query, {"city": city, "target_time": target_time}).fetchone()
        
        if result:
            return {
                "temperature": result.temperature,
                "condition": result.condition,
                "precipitation": result.precipitation
            }
        return {"error": "No weather data found"}
    except Exception as e:
        return {"error": str(e)}
