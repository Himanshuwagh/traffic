from __future__ import annotations

import gzip
import hashlib
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text

log = logging.getLogger(__name__)

MVT_LAYER_NAME = "traffic"

HW_MOTORWAY = ("motorway", "motorway_link")
HW_TRUNK = HW_MOTORWAY + ("trunk", "trunk_link")
HW_PRIMARY = HW_TRUNK + ("primary", "primary_link")
HW_SECONDARY = HW_PRIMARY + ("secondary", "secondary_link")
HW_TERTIARY = HW_SECONDARY + ("tertiary", "tertiary_link")
HW_MINOR = HW_TERTIARY + (
    "unclassified",
    "residential",
    "living_street",
    "service",
    "traffic",
    "unknown",
)


@dataclass(frozen=True)
class CachedTile:
    data: bytes
    etag: str
    encoding: str | None


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def traffic_tile_cache_enabled() -> bool:
    return _env_flag("TRAFFIC_TILE_CACHE_ENABLED", default=True)


def traffic_tile_pregeneration_enabled() -> bool:
    return _env_flag("TRAFFIC_TILE_PREGENERATE", default=True)


def floor_to_hour(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0, tzinfo=None)


def traffic_detail_for_zoom(zoom: float | None, requested_limit: int) -> tuple[tuple[str, ...] | None, int, float]:
    if zoom is None or zoom < 9:
        return HW_PRIMARY, min(requested_limit, 50000), 0.0006
    if zoom < 12:
        return HW_SECONDARY, min(requested_limit, 50000), 0.0002
    if zoom < 14:
        return HW_TERTIARY, min(requested_limit, 50000), 0.00005
    return HW_MINOR, min(requested_limit, 50000), 0.0


def lookup_cached_traffic_tile(db, *, city: str | None, target_time: datetime, z: int, x: int, y: int) -> CachedTile | None:
    if not traffic_tile_cache_enabled() or not city:
        return None
    row = db.execute(
        text("""
            SELECT data, etag, encoding
            FROM traffic_tile_cache
            WHERE city = LOWER(:city)
              AND date_hour = :date_hour
              AND z = :z
              AND x = :x
              AND y = :y
            LIMIT 1
        """),
        {"city": city, "date_hour": floor_to_hour(target_time), "z": z, "x": x, "y": y},
    ).fetchone()
    if not row:
        return None
    data = bytes(row.data) if isinstance(row.data, memoryview) else row.data
    return CachedTile(data=data, etag=row.etag, encoding=row.encoding)


def build_live_traffic_tile(db, *, city: str | None, target_time: datetime, z: int, x: int, y: int) -> bytes:
    highway_types, _, simplify_tolerance = traffic_detail_for_zoom(float(z), 50000)
    city_filter = "AND LOWER(o.city) = LOWER(:city)" if city else ""
    highway_filter = (
        "AND COALESCE(rs.highway_type, 'traffic') = ANY(CAST(:highway_types AS text[]))"
        if highway_types else ""
    )
    filter_params: dict = {"city": city} if city else {}
    if highway_types:
        filter_params["highway_types"] = list(highway_types)
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
        WITH
        bounds AS (
            SELECT
                ST_TileEnvelope(:z, :x, :y)                        AS bounds_3857,
                ST_Transform(ST_TileEnvelope(:z, :x, :y), 4326)    AS bounds_4326
        ),
        tile_observations AS (
            SELECT
                o.id,
                o.road_segment_id,
                o.geometry,
                o.speed_kmph,
                o.travel_time_seconds,
                o.congestion_index,
                o.jam_level,
                COALESCE(rs.name, h.name, 'Unmatched traffic hotspot') AS name,
                COALESCE(rs.highway_type, 'traffic') AS highway_type
            FROM traffic_observations o
            LEFT JOIN road_segments rs ON rs.id = o.road_segment_id
            LEFT JOIN traffic_hotspots h
                ON LOWER(h.city) = LOWER(o.city)
               AND ST_DWithin(h.geometry::geography, o.geometry::geography, 250)
            CROSS JOIN bounds
            WHERE o.observed_at BETWEEN :target_time - INTERVAL '3 hours'
                                    AND :target_time + INTERVAL '3 hours'
              AND o.geometry && bounds.bounds_4326
              {city_filter}
              {highway_filter}
        ),
        closest_traffic AS (
            SELECT DISTINCT ON (COALESCE(road_segment_id, id))
                *
            FROM tile_observations
            ORDER BY COALESCE(road_segment_id, id), COALESCE(congestion_index, 0) DESC
        ),
        tile_rows AS (
            SELECT
                COALESCE(ct.road_segment_id, ct.id) AS id,
                COALESCE(ct.name, 'Unknown') AS name,
                COALESCE(ct.highway_type, 'traffic') AS highway_type,
                ct.speed_kmph AS speed,
                ct.travel_time_seconds AS travel_time,
                ct.congestion_index,
                ct.jam_level,
                CASE
                    WHEN ct.congestion_index IS NULL THEN '#a0a0b0'
                    WHEN ct.congestion_index >= 0.75 THEN '#FF0000'
                    WHEN ct.congestion_index >= 0.50 THEN '#FF9900'
                    WHEN ct.congestion_index >= 0.25 THEN '#FFFF00'
                    ELSE '#00C700'
                END AS color,
                ST_AsMVTGeom(
                    ST_Transform(
                        CASE
                            WHEN :simplify_tolerance > 0
                                THEN ST_SimplifyPreserveTopology(ct.geometry, :simplify_tolerance)
                            ELSE ct.geometry
                        END,
                        3857
                    ),
                    bounds.bounds_3857,
                    4096,
                    256,
                    true
                ) AS geom
            FROM closest_traffic ct
            CROSS JOIN bounds
        )
        SELECT ST_AsMVT(tile_rows, '{MVT_LAYER_NAME}', 4096, 'geom')
        FROM tile_rows
        WHERE geom IS NOT NULL
        """
    )
    return db.execute(query, params).scalar() or b""


def store_cached_traffic_tile(
    db,
    *,
    city: str,
    target_time: datetime,
    z: int,
    x: int,
    y: int,
    tile: bytes,
) -> None:
    compressed = gzip.compress(tile, compresslevel=6)
    etag = hashlib.sha256(compressed).hexdigest()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.execute(
        text("""
            INSERT INTO traffic_tile_cache (
                city, date_hour, z, x, y, data, etag, encoding, created_at, updated_at
            )
            VALUES (
                LOWER(:city), :date_hour, :z, :x, :y, :data, :etag, 'gzip', :now, :now
            )
            ON CONFLICT (city, date_hour, z, x, y)
            DO UPDATE SET
                data = EXCLUDED.data,
                etag = EXCLUDED.etag,
                encoding = EXCLUDED.encoding,
                updated_at = EXCLUDED.updated_at
        """),
        {
            "city": city,
            "date_hour": floor_to_hour(target_time),
            "z": z,
            "x": x,
            "y": y,
            "data": compressed,
            "etag": etag,
            "now": now,
        },
    )


def cache_live_traffic_tile(db, *, city: str | None, target_time: datetime, z: int, x: int, y: int, tile: bytes) -> None:
    if not traffic_tile_cache_enabled() or not city:
        return
    store_cached_traffic_tile(db, city=city, target_time=target_time, z=z, x=x, y=y, tile=tile)


def _lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def tiles_for_bbox_uncapped(bbox: tuple[float, float, float, float], zoom: int) -> list[tuple[int, int, int]]:
    min_lon, min_lat, max_lon, max_lat = bbox
    min_x, max_y = _lonlat_to_tile(min_lon, min_lat, zoom)
    max_x, min_y = _lonlat_to_tile(max_lon, max_lat, zoom)
    return [
        (zoom, x, y)
        for x in range(min(min_x, max_x), max(min_x, max_x) + 1)
        for y in range(min(min_y, max_y), max(min_y, max_y) + 1)
    ]


def _pregenerate_zooms() -> list[int]:
    raw = os.getenv("TRAFFIC_TILE_PREGENERATE_ZOOMS", "10,11,12,13,14")
    zooms = sorted({int(part.strip()) for part in raw.split(",") if part.strip().isdigit()})
    return [zoom for zoom in zooms if 0 <= zoom <= 22]


def pregenerate_traffic_tiles_for_observations(db, *, city: str, observed_at: datetime) -> int:
    if not traffic_tile_pregeneration_enabled():
        return 0
    row = db.execute(
        text("""
            SELECT
                ST_XMin(ST_Extent(geometry)) AS min_lon,
                ST_YMin(ST_Extent(geometry)) AS min_lat,
                ST_XMax(ST_Extent(geometry)) AS max_lon,
                ST_YMax(ST_Extent(geometry)) AS max_lat
            FROM traffic_observations
            WHERE LOWER(city) = LOWER(:city)
              AND observed_at = :observed_at
              AND geometry IS NOT NULL
        """),
        {"city": city, "observed_at": observed_at},
    ).fetchone()
    if not row or row.min_lon is None:
        return 0

    bbox = (float(row.min_lon), float(row.min_lat), float(row.max_lon), float(row.max_lat))
    max_tiles = int(os.getenv("TRAFFIC_TILE_PREGENERATE_MAX_TILES", "2500"))
    tile_coords: list[tuple[int, int, int]] = []
    for zoom in _pregenerate_zooms():
        tile_coords.extend(tiles_for_bbox_uncapped(bbox, zoom))
    if len(tile_coords) > max_tiles:
        log.warning(
            "Skipping traffic tile pregeneration for %s at %s: %s tiles exceeds limit %s",
            city,
            observed_at.isoformat(),
            len(tile_coords),
            max_tiles,
        )
        return 0

    generated = 0
    for z, x, y in tile_coords:
        tile = build_live_traffic_tile(db, city=city, target_time=observed_at, z=z, x=x, y=y)
        store_cached_traffic_tile(db, city=city, target_time=observed_at, z=z, x=x, y=y, tile=tile)
        generated += 1
    db.commit()
    return generated
