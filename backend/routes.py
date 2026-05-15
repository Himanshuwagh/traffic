from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
import json
import time
try:
    from .database import get_db
    from .tile_cache import build_live_traffic_tile, cache_live_traffic_tile, lookup_cached_traffic_tile
except ImportError:
    from database import get_db
    from tile_cache import build_live_traffic_tile, cache_live_traffic_tile, lookup_cached_traffic_tile

router = APIRouter()

TRAFFIC_CACHE_TTL_SECONDS = 300
TRAFFIC_CACHE_MAX_ENTRIES = 128
traffic_response_cache: dict[tuple, tuple[float, str]] = {}
traffic_summary_cache: dict[tuple, tuple[float, dict]] = {}
traffic_tile_cache: dict[tuple, tuple[float, bytes]] = {}
MVT_LAYER_NAME = "traffic"

SEGMENT_TILE_CACHE_TTL_SECONDS = 3600  # 1 hour – geometry changes very rarely
segment_tile_cache: dict[tuple, tuple[float, bytes]] = {}

# ── Road hierarchy buckets (Google-Maps-style progressive reveal) ────────────
# Each zoom level unlocks an additional road class.
# These are used by BOTH tile endpoints so backend & frontend stay in sync.

HW_MOTORWAY   = ("motorway", "motorway_link")
HW_TRUNK      = HW_MOTORWAY + ("trunk", "trunk_link")
HW_PRIMARY    = HW_TRUNK    + ("primary", "primary_link")
HW_SECONDARY  = HW_PRIMARY  + ("secondary", "secondary_link")
HW_TERTIARY   = HW_SECONDARY + ("tertiary", "tertiary_link")
HW_MINOR      = HW_TERTIARY + (
    "unclassified",
    "residential",
    "living_street",
    "service",
    "traffic",
    "unknown",
)

# Legacy aliases kept so nothing else breaks
MAJOR_HIGHWAY_TYPES = HW_PRIMARY
MEDIUM_HIGHWAY_TYPES = HW_TERTIARY


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


def build_observation_filters(
    *,
    city: str | None,
    bbox_vals: tuple[float, float, float, float] | None = None,
    alias: str = "o",
) -> tuple[str, dict]:
    where_clauses: list[str] = []
    params: dict = {}
    if city:
        where_clauses.append(f"LOWER({alias}.city) = LOWER(:city)")
        params["city"] = city
    if bbox_vals:
        where_clauses.append(
            f"{alias}.geometry && ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)"
        )
        params.update(
            {"min_lon": bbox_vals[0], "min_lat": bbox_vals[1], "max_lon": bbox_vals[2], "max_lat": bbox_vals[3]}
        )
    return (f"AND {' AND '.join(where_clauses)}" if where_clauses else ""), params


def traffic_detail_for_zoom(zoom: float | None, requested_limit: int) -> tuple[tuple[str, ...] | None, int, float]:
    """
    Returns (highway_types, row_limit, simplify_tolerance) for a given map zoom.

    Road classes progressively unlock by zoom. This keeps country/state views
    readable and makes live tile payloads match the frontend reveal hierarchy.
    """
    if zoom is None or zoom < 9:
        return HW_PRIMARY, min(requested_limit, 50000), 0.0006
    if zoom < 12:
        return HW_SECONDARY, min(requested_limit, 50000), 0.0002
    if zoom < 14:
        return HW_TERTIARY, min(requested_limit, 50000), 0.00005
    return HW_MINOR, min(requested_limit, 50000), 0.0


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
        # Strict match: only the exact road classes for this zoom level.
        # Roads with NULL highway_type are excluded — they would clutter low-zoom views.
        where_clauses.append("rs.highway_type = ANY(CAST(:highway_types AS text[]))")
        params["highway_types"] = list(highway_types)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    return where_sql, params


def city_has_road_segments(db: Session, city: str | None) -> bool:
    if not city:
        return False
    return bool(
        db.execute(
            text("SELECT EXISTS (SELECT 1 FROM road_segments WHERE LOWER(city) = LOWER(:city))"),
            {"city": city},
        ).scalar()
    )

@router.post("/api/traffic/fetch")
async def trigger_traffic_fetch(
    city: str | None = Query(default=None, description="City to fetch (omit for all)"),
    limit: int = Query(default=100, ge=1, le=500),
):
    """
    Trigger a manual TomTom traffic observation ingest run.
    Runs synchronously — response contains fetch stats.
    """
    try:
        try:
            from .ingest_tomtom_traffic import run_ingestion
        except ImportError:
            from ingest_tomtom_traffic import run_ingestion
        result = run_ingestion(cities=[city] if city else None, mode="discovery", max_tiles_per_city=limit)
        return {
            "fetched": result["observations_saved"],
            "failed": 0,
            "skipped": result["observations_skipped"],
            "snapshot_time": datetime.utcnow().isoformat(),
            "city": city or "all",
            "scope_limit": limit,
        }
    except Exception as e:
        return {"error": str(e), "fetched": 0, "failed": 0}


@router.get("/api/traffic/hourly")
async def get_hourly_speed_profile(
    city: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Return average speed bucketed by hour-of-day across stored traffic observations.
    Used for the CityOverview hourly bar chart.
    """
    try:
        params: dict = {}
        city_clause = ""
        if city:
            city_clause = "AND LOWER(o.city) = LOWER(:city)"
            params["city"] = city

        rows = db.execute(
            text(f"""
                SELECT
                    o.hour_of_day,
                    ROUND(AVG(o.speed_kmph)::numeric, 1) AS avg_speed,
                    COUNT(*) AS count
                FROM traffic_observations o
                WHERE o.speed_kmph IS NOT NULL
                {city_clause}
                GROUP BY o.hour_of_day
                ORDER BY o.hour_of_day
            """),
            params,
        ).fetchall()

        bucket: dict[int, dict] = {r.hour_of_day: {"avg_speed": float(r.avg_speed), "count": int(r.count)} for r in rows}
        result = []
        for h in range(24):
            label = f"{h:02d}:00"
            if h in bucket:
                result.append({"hour": label, "avg_speed": bucket[h]["avg_speed"], "count": bucket[h]["count"]})
            else:
                result.append({"hour": label, "avg_speed": None, "count": 0})

        return result
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/traffic/latest")
async def get_latest_traffic_stats(
    city: str | None = None,
    db: Session = Depends(get_db),
):
    """Return stats about the most recent traffic observations in the DB."""
    try:
        params: dict = {}
        city_clause = ""
        if city:
            city_clause = "AND LOWER(o.city) = LOWER(:city)"
            params["city"] = city

        result = db.execute(
            text(f"""
                SELECT
                    COUNT(*) AS total_records,
                    MAX(o.observed_at_hour) AS latest_snapshot,
                    MIN(o.observed_at_hour) AS earliest_snapshot,
                    COUNT(DISTINCT COALESCE(o.road_segment_id, o.id)) AS unique_segments,
                    ROUND(AVG(o.speed_kmph)::numeric, 1) AS avg_speed
                FROM traffic_observations o
                WHERE 1=1 {city_clause}
            """),
            params,
        ).fetchone()

        if result:
            return {
                "total_records": result.total_records,
                "latest_snapshot": result.latest_snapshot.isoformat() if result.latest_snapshot else None,
                "earliest_snapshot": result.earliest_snapshot.isoformat() if result.earliest_snapshot else None,
                "unique_segments": result.unique_segments,
                "avg_speed": result.avg_speed,
                "city": city or "all",
            }
        return {"total_records": 0, "city": city or "all"}
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/traffic/{date_str}")
async def get_traffic_by_date(
    date_str: str,
    city: str | None = None,
    bbox: str | None = Query(default=None, description="minLon,minLat,maxLon,maxLat"),
    zoom: float | None = Query(default=None),
    limit: int = Query(default=20000, ge=1, le=50000),
    db: Session = Depends(get_db),
):
    """Get normalized TomTom traffic observations for a specific date/time."""
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
        if highway_types:
            params["highway_types"] = list(highway_types)
        observation_where, filter_params = build_observation_filters(city=city, bbox_vals=bbox_vals)
        params.update(filter_params)
        highway_where = (
            "AND COALESCE(rs.highway_type, 'traffic') = ANY(CAST(:highway_types AS text[]))"
            if highway_types else ""
        )

        base_query = f"""
            WITH closest_traffic AS (
                SELECT DISTINCT ON (COALESCE(o.road_segment_id, o.id))
                    o.id,
                    o.road_segment_id,
                    o.geometry,
                    o.speed_kmph,
                    o.travel_time_seconds,
                    o.congestion_index,
                    o.jam_level,
                    o.observed_at,
                    COALESCE(rs.name, h.name, 'Unmatched traffic hotspot') AS name,
                    COALESCE(rs.highway_type, 'traffic') AS highway_type
                FROM traffic_observations o
                LEFT JOIN road_segments rs ON rs.id = o.road_segment_id
                LEFT JOIN traffic_hotspots h
                    ON LOWER(h.city) = LOWER(o.city)
                   AND ST_DWithin(h.geometry::geography, o.geometry::geography, 250)
                WHERE o.observed_at BETWEEN :target_time - INTERVAL '7 days' AND :target_time + INTERVAL '7 days'
                  AND o.geometry IS NOT NULL
                  {observation_where}
                  {highway_where}
                ORDER BY COALESCE(o.road_segment_id, o.id), abs(extract(epoch from o.observed_at - :target_time))
            ),
            limited AS (
                SELECT
                    COALESCE(road_segment_id, id) AS id,
                    name,
                    highway_type,
                    CASE
                        WHEN :simplify_tolerance > 0 THEN ST_SimplifyPreserveTopology(geometry, :simplify_tolerance)
                        ELSE geometry
                    END AS geometry,
                    speed_kmph,
                    travel_time_seconds,
                    congestion_index,
                    jam_level,
                    observed_at
                FROM closest_traffic
                ORDER BY COALESCE(congestion_index, 0) DESC, id
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
                        'speed', speed_kmph,
                        'travel_time', travel_time_seconds,
                        'congestion_index', congestion_index,
                        'jam_level', jam_level,
                        'color', CASE
                            WHEN congestion_index IS NULL THEN '#a0a0b0'
                            WHEN congestion_index >= 0.75 THEN '#FF0000'
                            WHEN congestion_index >= 0.50 THEN '#FF9900'
                            WHEN congestion_index >= 0.25 THEN '#FFFF00'
                            ELSE '#00C700'
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
        print(f"DEBUG: get_traffic_summary: date={date_str}, city={city}, zoom={zoom}, bbox={bbox}")
        target_time = datetime.fromisoformat(date_str)
        bbox_vals = parse_bbox(bbox)
        highway_types, limit, _ = traffic_detail_for_zoom(zoom, limit)
        cache_key = (
            "summary",
            city.lower() if city else None,
            target_time.isoformat(timespec="hours"),
            round(zoom or 0, 1),
            limit,
            rounded_bbox_key(bbox_vals),
        )
        now = time.monotonic()
        cached = lookup_cached_response(traffic_summary_cache, cache_key, now)
        if cached:
            return cached

        observation_where, filter_params = build_observation_filters(city=city, bbox_vals=bbox_vals)
        params = {"target_time": target_time, "limit": limit, **filter_params}
        if highway_types:
            params["highway_types"] = list(highway_types)
        highway_where = (
            "AND COALESCE(rs.highway_type, 'traffic') = ANY(CAST(:highway_types AS text[]))"
            if highway_types else ""
        )

        query = text(
            f"""
            WITH closest_traffic AS (
                SELECT DISTINCT ON (COALESCE(o.road_segment_id, o.id))
                    o.id,
                    o.road_segment_id,
                    o.speed_kmph,
                    o.travel_time_seconds,
                    o.congestion_index,
                    o.jam_level,
                    o.observed_at,
                    COALESCE(rs.name, h.name, 'Unmatched traffic hotspot') AS name,
                    COALESCE(rs.highway_type, 'traffic') AS highway_type
                FROM traffic_observations o
                LEFT JOIN road_segments rs ON rs.id = o.road_segment_id
                LEFT JOIN traffic_hotspots h
                    ON LOWER(h.city) = LOWER(o.city)
                   AND ST_DWithin(h.geometry::geography, o.geometry::geography, 250)
                WHERE o.observed_at BETWEEN :target_time - INTERVAL '7 days' AND :target_time + INTERVAL '7 days'
                  AND o.geometry IS NOT NULL
                  {observation_where}
                  {highway_where}
                ORDER BY COALESCE(o.road_segment_id, o.id), abs(extract(epoch from o.observed_at - :target_time))
            ),
            visible_segments AS (
                SELECT
                    COALESCE(road_segment_id, id) AS id,
                    name,
                    highway_type,
                    speed_kmph AS speed,
                    travel_time_seconds AS travel_time,
                    congestion_index,
                    jam_level
                FROM closest_traffic
                ORDER BY COALESCE(congestion_index, 0) DESC, id
                LIMIT :limit
            ),
            bottlenecks AS (
                SELECT
                    id,
                    name,
                    highway_type,
                    speed,
                    travel_time,
                    congestion_index,
                    jam_level
                FROM visible_segments
                WHERE congestion_index IS NOT NULL
                ORDER BY congestion_index DESC, id ASC
                LIMIT 10
            )
            SELECT jsonb_build_object(
                'avg_speed', ROUND(AVG(speed)::numeric, 1),
                'active_segments', COUNT(*) FILTER (WHERE speed IS NOT NULL),
                'top_corridor_name', (
                    SELECT name
                    FROM bottlenecks
                    ORDER BY congestion_index DESC, id ASC
                    LIMIT 1
                ),
                'status', 'live',
                'active_hotspots', COUNT(*) FILTER (WHERE congestion_index >= 0.25),
                'worst_congestion_index', ROUND((MAX(congestion_index) * 100)::numeric, 1),
                'top_bottlenecks', COALESCE((
                    SELECT jsonb_agg(
                        jsonb_build_object(
                            'id', id,
                            'name', name,
                            'highway_type', highway_type,
                            'speed', speed,
                            'travel_time', travel_time,
                            'congestion_index', congestion_index,
                            'jam_level', jam_level,
                            'color', CASE
                                WHEN congestion_index IS NULL THEN '#a0a0b0'
                                WHEN congestion_index >= 0.75 THEN '#FF0000'
                                WHEN congestion_index >= 0.50 THEN '#FF9900'
                                WHEN congestion_index >= 0.25 THEN '#FFFF00'
                                ELSE '#00C700'
                            END,
                            'cfi', COALESCE(congestion_index, 0) * 100
                        )
                        ORDER BY congestion_index DESC, id ASC
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
            "active_hotspots": 0,
            "worst_congestion_index": None,
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
            "active_hotspots": 0,
            "worst_congestion_index": None,
            "top_bottlenecks": [],
        }


# Empty tile bytes (valid empty MVT) returned instantly for out-of-range zooms
_EMPTY_TILE = b""
_EMPTY_TILE_RESPONSE_HEADERS = {"Cache-Control": "public, max-age=600"}


@router.get("/api/traffic/tiles/{date_str}/{z}/{x}/{y}.mvt")
async def get_traffic_tile(
    date_str: str,
    z: int,
    x: int,
    y: int,
    city: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Serve traffic as Mapbox Vector Tiles.

    Performance design:
    - Ingest can pre-generate this tile into traffic_tile_cache.
    - Requests first do a keyed lookup by city/hour/z/x/y.
    - Cache misses fall back to the live PostGIS MVT query and populate the cache.
    """
    try:
        target_time = datetime.fromisoformat(date_str)
        try:
            persistent_tile = lookup_cached_traffic_tile(db, city=city, target_time=target_time, z=z, x=x, y=y)
        except Exception:
            db.rollback()
            persistent_tile = None
        if persistent_tile is not None:
            headers = {
                "Cache-Control": "public, max-age=3600, stale-while-revalidate=3600",
                "ETag": persistent_tile.etag,
            }
            if persistent_tile.encoding:
                headers["Content-Encoding"] = persistent_tile.encoding
            return Response(
                content=persistent_tile.data,
                media_type="application/vnd.mapbox-vector-tile",
                headers=headers,
            )

        _, _, simplify_tolerance = traffic_detail_for_zoom(float(z), 50000)
        cache_key = (
            "tile",
            city.lower() if city else None,
            target_time.isoformat(timespec="hours"),
            z,
            x,
            y,
            simplify_tolerance,
        )
        now = time.monotonic()
        cached = lookup_cached_response(traffic_tile_cache, cache_key, now)
        if cached is not None:
            return Response(
                content=cached,
                media_type="application/vnd.mapbox-vector-tile",
                headers={"Cache-Control": "public, max-age=60"},
            )

        tile = build_live_traffic_tile(db, city=city, target_time=target_time, z=z, x=x, y=y)
        try:
            cache_live_traffic_tile(db, city=city, target_time=target_time, z=z, x=x, y=y, tile=tile)
            db.commit()
        except Exception:
            db.rollback()
        store_cached_response(traffic_tile_cache, cache_key, tile, now)
        return Response(
            content=tile,
            media_type="application/vnd.mapbox-vector-tile",
            headers={"Cache-Control": "public, max-age=60"},
        )
    except Exception as e:
        print(f"TILE ERROR z={z} x={x} y={y}: {e}")
        return Response(content=b"", media_type="application/vnd.mapbox-vector-tile", status_code=200)


@router.get("/api/hotspots/{date_str}")
async def get_hotspots(
    date_str: str,
    city: str | None = None,
    bbox: str | None = Query(default=None, description="minLon,minLat,maxLon,maxLat"),
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Return hotspot summaries for the selected date/time and visible area."""
    try:
        target_time = datetime.fromisoformat(date_str)
        bbox_vals = parse_bbox(bbox)
        where_clauses: list[str] = [
            "h.last_seen_at BETWEEN :target_time - INTERVAL '7 days' AND :target_time + INTERVAL '7 days'"
        ]
        params: dict = {"target_time": target_time, "limit": limit}
        if city:
            where_clauses.append("LOWER(h.city) = LOWER(:city)")
            params["city"] = city
        if bbox_vals:
            where_clauses.append("h.geometry && ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326)")
            params.update(
                {"min_lon": bbox_vals[0], "min_lat": bbox_vals[1], "max_lon": bbox_vals[2], "max_lat": bbox_vals[3]}
            )

        rows = db.execute(
            text(
                f"""
                SELECT
                    h.id,
                    h.city,
                    COALESCE(h.name, 'Traffic hotspot') AS name,
                    ST_AsGeoJSON(ST_Centroid(h.geometry), 5)::text AS centroid,
                    h.severity_score,
                    h.frequency_score,
                    h.duration_minutes,
                    h.status,
                    h.last_seen_at,
                    ds.peak_hour,
                    ds.avg_congestion_index,
                    ds.max_congestion_index,
                    ds.minutes_congested
                FROM traffic_hotspots h
                LEFT JOIN daily_hotspot_stats ds
                    ON ds.hotspot_id = h.id
                   AND ds.date = CAST(:target_time AS date)
                WHERE {" AND ".join(where_clauses)}
                ORDER BY h.severity_score DESC NULLS LAST, h.last_seen_at DESC NULLS LAST
                LIMIT :limit
                """
            ),
            params,
        ).fetchall()

        hotspots = []
        for row in rows:
            hotspots.append({
                "id": row.id,
                "city": row.city,
                "name": row.name,
                "centroid": json.loads(row.centroid) if row.centroid else None,
                "severity_score": row.severity_score,
                "frequency_score": row.frequency_score,
                "duration_minutes": row.duration_minutes,
                "status": row.status,
                "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
                "peak_hour": row.peak_hour,
                "avg_congestion_index": row.avg_congestion_index,
                "max_congestion_index": row.max_congestion_index,
                "minutes_congested": row.minutes_congested,
            })
        return {"hotspots": hotspots}
    except Exception as e:
        return {"error": str(e), "hotspots": []}


@router.get("/api/segments/tiles/{z}/{x}/{y}.mvt")
async def get_segment_tile(
    z: int,
    x: int,
    y: int,
    city: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Geometry-only vector tiles for the permanent road skeleton (no traffic data).
    Cached for 1 hour on both server and browser — road geometry rarely changes.
    Road classes progressively unlock by zoom so low-zoom tiles remain readable.
    """
    try:
        highway_types, _, simplify_tolerance = traffic_detail_for_zoom(float(z), 50000)

        cache_key = (
            "seg_tile",
            city.lower() if city else None,
            z,
            x,
            y,
            simplify_tolerance,
        )
        now = time.monotonic()
        cached = segment_tile_cache.get(cache_key)
        if cached and now - cached[0] <= SEGMENT_TILE_CACHE_TTL_SECONDS:
            return Response(
                content=cached[1],
                media_type="application/vnd.mapbox-vector-tile",
                headers={"Cache-Control": "public, max-age=3600"},
            )

        use_road_segments = city_has_road_segments(db, city)
        city_clauses: list[str] = []
        filter_params: dict = {}
        if city:
            filter_params["city"] = city
            city_clauses.append("LOWER(src.city) = LOWER(:city)")
        city_where = ("WHERE " + " AND ".join(city_clauses)) if city_clauses else "WHERE TRUE"

        params = {
            "z": z,
            "x": x,
            "y": y,
            "simplify_tolerance": simplify_tolerance,
            **filter_params,
        }
        highway_where = ""
        if highway_types:
            params["highway_types"] = list(highway_types)
            highway_where = "AND src.highway_type = ANY(CAST(:highway_types AS text[]))"

        source_rows_sql = """
                SELECT
                    rs.id,
                    rs.city,
                    COALESCE(rs.name, 'Unknown') AS name,
                    COALESCE(rs.highway_type, 'unknown') AS highway_type,
                    rs.geometry
                FROM road_segments rs
        """
        if city and not use_road_segments:
            source_rows_sql = """
                SELECT DISTINCT ON (COALESCE(o.road_segment_id, o.id))
                    COALESCE(o.road_segment_id, o.id) AS id,
                    o.city,
                    COALESCE(rs.name, h.name, 'Observed traffic segment') AS name,
                    COALESCE(rs.highway_type, 'traffic') AS highway_type,
                    o.geometry
                FROM traffic_observations o
                LEFT JOIN road_segments rs ON rs.id = o.road_segment_id
                LEFT JOIN traffic_hotspots h
                    ON LOWER(h.city) = LOWER(o.city)
                   AND ST_DWithin(h.geometry::geography, o.geometry::geography, 250)
                WHERE o.geometry IS NOT NULL
                  AND LOWER(o.city) = LOWER(:city)
                  AND o.observed_at >= NOW() - INTERVAL '14 days'
                ORDER BY COALESCE(o.road_segment_id, o.id), o.observed_at DESC
            """

        query = text(
            f"""
            WITH
            bounds AS (
                SELECT
                    ST_TileEnvelope(:z, :x, :y)                      AS bounds_3857,
                    ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326)  AS bounds_4326
            ),
            tile_rows AS (
                SELECT
                    src.id,
                    src.name,
                    src.highway_type,
                    ST_AsMVTGeom(
                        ST_Transform(
                            CASE
                                WHEN :simplify_tolerance > 0
                                    THEN ST_SimplifyPreserveTopology(src.geometry, :simplify_tolerance)
                                ELSE src.geometry
                            END,
                            3857
                        ),
                        bounds.bounds_3857,
                        4096,
                        256,
                        true
                    ) AS geom
                FROM (
                    {source_rows_sql}
                ) src, bounds
                {city_where}
                  AND src.geometry && bounds.bounds_4326
                  {highway_where}
            )
            SELECT ST_AsMVT(tile_rows, 'segments', 4096, 'geom')
            FROM tile_rows
            WHERE geom IS NOT NULL
            """
        )

        tile = db.execute(query, params).scalar() or b""
        if len(segment_tile_cache) >= TRAFFIC_CACHE_MAX_ENTRIES * 4:
            segment_tile_cache.clear()
        segment_tile_cache[cache_key] = (now, tile)

        return Response(
            content=tile,
            media_type="application/vnd.mapbox-vector-tile",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except Exception as e:
        print(f"SEGMENT TILE ERROR z={z} x={x} y={y}: {e}")
        return Response(content=b"", media_type="application/vnd.mapbox-vector-tile", status_code=200)


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
