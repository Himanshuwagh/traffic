from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import text

try:
    from mapbox_vector_tile import decode as decode_mvt
except ImportError:  # pragma: no cover - handled at runtime for deploy clarity
    decode_mvt = None

try:
    from .database import SessionLocal, bootstrap_database, engine
    from .models import Base
    from .tile_cache import pregenerate_traffic_tiles_for_observations
    from .tomtom_client import (
        TileCoord,
        TomTomClient,
        compact_json,
        stable_ref,
        tile_point_to_lonlat,
        tiles_for_bbox,
    )
except ImportError:
    from database import SessionLocal, bootstrap_database, engine  # type: ignore[no-redef]
    from models import Base  # type: ignore[no-redef]
    from tile_cache import pregenerate_traffic_tiles_for_observations  # type: ignore[no-redef]
    from tomtom_client import (  # type: ignore[no-redef]
        TileCoord,
        TomTomClient,
        compact_json,
        stable_ref,
        tile_point_to_lonlat,
        tiles_for_bbox,
    )


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

JAM_LEVELS = (
    ("severe", 0.75),
    ("heavy", 0.50),
    ("moderate", 0.25),
    ("free", 0.0),
)


@dataclass
class ObservationCandidate:
    city: str
    observed_at: datetime
    source_kind: str
    source_ref: str
    geometry_wkt: str
    properties: dict[str, Any]
    speed_kmph: float | None
    free_flow_speed_kmph: float | None
    travel_time_seconds: float | None
    free_flow_travel_time_seconds: float | None
    confidence: float | None
    congestion_index: float | None
    jam_level: str
    road_closure: bool | None


@dataclass(frozen=True)
class CityScope:
    city: str
    center: tuple[float, float]
    bbox: tuple[float, float, float, float]


class DailyTileBudget:
    def __init__(self, *, used: int, limit: int) -> None:
        self._used = used
        self._limit = limit
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        return self._limit

    def try_consume(self, count: int = 1) -> bool:
        with self._lock:
            if self._used + count > self._limit:
                return False
            self._used += count
            return True

    def snapshot_used(self) -> int:
        with self._lock:
            return self._used


def _float_prop(props: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = props.get(name)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _bool_prop(props: dict[str, Any], *names: str) -> bool | None:
    for name in names:
        value = props.get(name)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes"}
    return None


def _jam_level(congestion_index: float | None) -> str:
    if congestion_index is None:
        return "unknown"
    for label, threshold in JAM_LEVELS:
        if congestion_index >= threshold:
            return label
    return "unknown"


def _congestion_index(props: dict[str, Any]) -> float | None:
    current_speed = _float_prop(props, "currentSpeed", "current_speed", "speed", "averageSpeedKmph")
    free_flow_speed = _float_prop(props, "freeFlowSpeed", "free_flow_speed", "freeFlow", "freeFlowSpeedKmph")
    if current_speed is not None and free_flow_speed and free_flow_speed > 0:
        return max(0.0, min(1.0, 1.0 - current_speed / free_flow_speed))

    traffic_level = _float_prop(props, "traffic_level", "trafficLevel", "trafficLevelRatio", "relativeDelay")
    if traffic_level is None:
        return None
    if traffic_level > 1:
        traffic_level = traffic_level / 100.0
    return max(0.0, min(1.0, traffic_level))


def _coords_to_wkt(coords: Any) -> str | None:
    if not isinstance(coords, list) or len(coords) < 2:
        return None
    points: list[tuple[float, float]] = []
    for point in coords:
        if not isinstance(point, list | tuple) or len(point) < 2:
            continue
        lon, lat = float(point[0]), float(point[1])
        points.append((lon, lat))
    if len(points) < 2:
        return None
    return "LINESTRING(" + ",".join(f"{lon} {lat}" for lon, lat in points) + ")"


def _transform_raw_coords(coords: Any, tile: TileCoord) -> Any:
    if isinstance(coords, list) and coords and isinstance(coords[0], (int, float)):
        lon, lat = tile_point_to_lonlat(tile, float(coords[0]), float(coords[1]))
        return [lon, lat]
    if isinstance(coords, list):
        return [_transform_raw_coords(item, tile) for item in coords]
    return coords


def _line_coords_from_geometry(geometry: dict[str, Any], tile: TileCoord) -> list[list[float]] | None:
    coords = geometry.get("coordinates")
    if coords is None:
        return None
    if _coords_need_transform(coords):
        coords = _transform_raw_coords(coords, tile)
    if geometry.get("type") == "LineString":
        return coords
    if geometry.get("type") == "MultiLineString" and coords:
        return max(coords, key=len)
    return None


def _coords_need_transform(coords: Any) -> bool:
    if isinstance(coords, list) and coords and isinstance(coords[0], (int, float)):
        return abs(float(coords[0])) > 180 or abs(float(coords[1])) > 90
    if isinstance(coords, list):
        return any(_coords_need_transform(item) for item in coords[:2])
    return False


def _decode_tile(tile: TileCoord, payload: bytes) -> list[dict[str, Any]]:
    if decode_mvt is None:
        raise RuntimeError("mapbox-vector-tile is required to decode TomTom flow tiles")
    try:
        decoded = decode_mvt(
            payload,
            default_options={
                "y_coord_down": True,
                "transformer": lambda x, y: tile_point_to_lonlat(tile, x, y),
            },
        )
    except TypeError:
        decoded = decode_mvt(payload)

    features: list[dict[str, Any]] = []
    for layer_name, layer in decoded.items():
        for idx, feature in enumerate(layer.get("features", [])):
            feature["layer_name"] = layer_name
            feature["feature_index"] = idx
            features.append(feature)
    return features


def candidates_from_tile(
    *,
    city: str,
    observed_at: datetime,
    tile: TileCoord,
    payload: bytes,
    threshold: float,
    include_baseline: bool,
) -> tuple[list[ObservationCandidate], int]:
    candidates: list[ObservationCandidate] = []
    skipped = 0
    for feature in _decode_tile(tile, payload):
        props = dict(feature.get("properties") or {})
        geometry = feature.get("geometry") or {}
        coords = _line_coords_from_geometry(geometry, tile)
        wkt = _coords_to_wkt(coords)
        if not wkt:
            skipped += 1
            continue

        congestion_index = _congestion_index(props)
        if congestion_index is None:
            skipped += 1
            continue
        if congestion_index < threshold and not include_baseline:
            skipped += 1
            continue

        speed = _float_prop(props, "currentSpeed", "current_speed", "speed", "averageSpeedKmph")
        free_flow_speed = _float_prop(props, "freeFlowSpeed", "free_flow_speed", "freeFlowSpeedKmph")
        travel_time = _float_prop(props, "currentTravelTime", "current_travel_time", "travelTimeSeconds")
        free_flow_time = _float_prop(props, "freeFlowTravelTime", "free_flow_travel_time")
        confidence = _float_prop(props, "confidence")
        source_ref = stable_ref(city, observed_at.isoformat(), tile.cache_key, feature.get("layer_name"), feature.get("feature_index"))
        candidates.append(
            ObservationCandidate(
                city=city,
                observed_at=observed_at,
                source_kind="flow_tile",
                source_ref=source_ref,
                geometry_wkt=wkt,
                properties=props,
                speed_kmph=speed,
                free_flow_speed_kmph=free_flow_speed,
                travel_time_seconds=travel_time,
                free_flow_travel_time_seconds=free_flow_time,
                confidence=confidence,
                congestion_index=congestion_index,
                jam_level=_jam_level(congestion_index),
                road_closure=_bool_prop(props, "roadClosure", "road_closure"),
            )
        )
    return candidates, skipped


def _parse_peak_windows(raw: str) -> list[tuple[time, time]]:
    windows: list[tuple[time, time]] = []
    for item in raw.split(","):
        if "-" not in item:
            continue
        start_raw, end_raw = item.split("-", 1)
        start_h, start_m = [int(part) for part in start_raw.split(":", 1)]
        end_h, end_m = [int(part) for part in end_raw.split(":", 1)]
        windows.append((time(start_h, start_m), time(end_h, end_m)))
    return windows


def _is_peak(now: datetime) -> bool:
    windows = _parse_peak_windows(os.getenv("TOMTOM_PEAK_WINDOWS", "07:00-11:00,17:00-21:00"))
    local_time = now.astimezone(IST).time()
    return any(start <= local_time <= end for start, end in windows)


def _is_baseline_hour(now: datetime) -> bool:
    hours = {
        int(item.strip())
        for item in os.getenv("TOMTOM_BASELINE_HOURS", "13,22").split(",")
        if item.strip().isdigit()
    }
    return now.astimezone(IST).hour in hours


def _quota_used_today(db) -> tuple[int, int]:
    start = datetime.combine(date.today(), time.min, tzinfo=IST).astimezone(timezone.utc).replace(tzinfo=None)
    row = db.execute(
        text("""
            SELECT
                COALESCE(SUM(tile_requests), 0) AS tile_requests,
                COALESCE(SUM(non_tile_requests), 0) AS non_tile_requests
            FROM tomtom_ingestion_runs
            WHERE started_at >= :start AND status IN ('success', 'partial')
        """),
        {"start": start},
    ).fetchone()
    return int(row.tile_requests or 0), int(row.non_tile_requests or 0)


def load_city_scopes(db) -> dict[str, CityScope]:
    rows = db.execute(
        text("""
            SELECT
                LOWER(TRIM(city)) AS city,
                ST_XMin(ST_Extent(geometry)) - 0.01 AS min_lon,
                ST_YMin(ST_Extent(geometry)) - 0.01 AS min_lat,
                ST_XMax(ST_Extent(geometry)) + 0.01 AS max_lon,
                ST_YMax(ST_Extent(geometry)) + 0.01 AS max_lat
            FROM road_segments
            WHERE city IS NOT NULL
              AND TRIM(city) <> ''
              AND geometry IS NOT NULL
            GROUP BY LOWER(TRIM(city))
            HAVING ST_Extent(geometry) IS NOT NULL
            ORDER BY LOWER(TRIM(city))
        """)
    ).fetchall()

    scopes: dict[str, CityScope] = {}
    for row in rows:
        bbox = (float(row.min_lon), float(row.min_lat), float(row.max_lon), float(row.max_lat))
        center = ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
        scopes[row.city] = CityScope(city=row.city, center=center, bbox=bbox)
    return scopes


def _normalize_city_name(city: str) -> str:
    return city.strip().lower()


def _active_hotspot_bboxes(db, city: str) -> list[tuple[float, float, float, float]]:
    interval_hours = int(os.getenv("TOMTOM_TRACKING_INTERVAL_HOURS", "3"))
    rows = db.execute(
        text("""
            SELECT
                ST_XMin(ST_Expand(geometry::box2d, 0.01)) AS min_lon,
                ST_YMin(ST_Expand(geometry::box2d, 0.01)) AS min_lat,
                ST_XMax(ST_Expand(geometry::box2d, 0.01)) AS max_lon,
                ST_YMax(ST_Expand(geometry::box2d, 0.01)) AS max_lat
            FROM traffic_hotspots
            WHERE LOWER(city) = LOWER(:city)
              AND status = 'active'
              AND last_seen_at >= NOW() - (:hours || ' hours')::interval
            ORDER BY severity_score DESC NULLS LAST
            LIMIT 25
        """),
        {"city": city, "hours": interval_hours},
    ).fetchall()
    return [(row.min_lon, row.min_lat, row.max_lon, row.max_lat) for row in rows]


def _derived_observation_fields(
    observed_at: datetime,
    speed_kmph: float | None,
    free_flow_speed_kmph: float | None,
) -> tuple[datetime, float | None, int, int]:
    observed_at_hour = observed_at.replace(minute=0, second=0, microsecond=0)
    speed_ratio = None
    if speed_kmph is not None and free_flow_speed_kmph and free_flow_speed_kmph > 0:
        speed_ratio = max(0.0, min(1.0, speed_kmph / free_flow_speed_kmph))
    return (
        observed_at_hour,
        speed_ratio,
        observed_at.hour,
        observed_at.weekday(),
    )


def _insert_candidate(db, candidate: ObservationCandidate, raw_ttl_expires_at: datetime) -> int | None:
    observed_at_hour, speed_ratio, hour_of_day, day_of_week = _derived_observation_fields(
        candidate.observed_at,
        candidate.speed_kmph,
        candidate.free_flow_speed_kmph,
    )
    row = db.execute(
        text("""
            WITH incoming AS (
                SELECT ST_GeomFromText(:wkt, 4326) AS geom
            ),
            matched AS (
                SELECT rs.id, COALESCE(rs.name, 'Unknown') AS name
                FROM road_segments rs, incoming i
                WHERE LOWER(rs.city) = LOWER(:city)
                  AND rs.geometry && ST_Expand(i.geom, 0.002)
                  AND ST_DWithin(rs.geometry::geography, i.geom::geography, 150)
                ORDER BY ST_Distance(rs.geometry::geography, i.geom::geography)
                LIMIT 1
            ),
            inserted AS (
                INSERT INTO traffic_observations (
                    observed_at, observed_at_hour, source, source_kind, source_ref, road_segment_id,
                    geometry, city, speed_kmph, free_flow_speed_kmph,
                    speed_ratio, travel_time_seconds, free_flow_travel_time_seconds, confidence,
                    hour_of_day, day_of_week,
                    congestion_index, jam_level, road_closure, raw_payload, raw_ttl_expires_at
                )
                SELECT
                    :observed_at, :observed_at_hour, 'tomtom', :source_kind, :source_ref, matched.id,
                    incoming.geom, :city, :speed_kmph, :free_flow_speed_kmph,
                    :speed_ratio, :travel_time_seconds, :free_flow_travel_time_seconds, :confidence,
                    :hour_of_day, :day_of_week,
                    :congestion_index, :jam_level, :road_closure, :raw_payload, :raw_ttl_expires_at
                FROM incoming
                LEFT JOIN matched ON true
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM traffic_observations existing
                    WHERE existing.source = 'tomtom'
                      AND existing.source_ref = :source_ref
                )
                ON CONFLICT (road_segment_id, observed_at_hour)
                WHERE road_segment_id IS NOT NULL AND source = 'tomtom'
                DO UPDATE SET
                    observed_at = EXCLUDED.observed_at,
                    source_kind = EXCLUDED.source_kind,
                    source_ref = EXCLUDED.source_ref,
                    geometry = EXCLUDED.geometry,
                    city = EXCLUDED.city,
                    speed_kmph = EXCLUDED.speed_kmph,
                    free_flow_speed_kmph = EXCLUDED.free_flow_speed_kmph,
                    speed_ratio = EXCLUDED.speed_ratio,
                    travel_time_seconds = EXCLUDED.travel_time_seconds,
                    free_flow_travel_time_seconds = EXCLUDED.free_flow_travel_time_seconds,
                    confidence = EXCLUDED.confidence,
                    hour_of_day = EXCLUDED.hour_of_day,
                    day_of_week = EXCLUDED.day_of_week,
                    congestion_index = EXCLUDED.congestion_index,
                    jam_level = EXCLUDED.jam_level,
                    road_closure = EXCLUDED.road_closure,
                    raw_payload = EXCLUDED.raw_payload,
                    raw_ttl_expires_at = EXCLUDED.raw_ttl_expires_at
                RETURNING id
            )
            SELECT id FROM inserted
        """),
        {
            "observed_at": candidate.observed_at,
            "observed_at_hour": observed_at_hour,
            "source_kind": candidate.source_kind,
            "source_ref": candidate.source_ref,
            "wkt": candidate.geometry_wkt,
            "city": candidate.city,
            "speed_kmph": candidate.speed_kmph,
            "free_flow_speed_kmph": candidate.free_flow_speed_kmph,
            "speed_ratio": speed_ratio,
            "travel_time_seconds": candidate.travel_time_seconds,
            "free_flow_travel_time_seconds": candidate.free_flow_travel_time_seconds,
            "confidence": candidate.confidence,
            "hour_of_day": hour_of_day,
            "day_of_week": day_of_week,
            "congestion_index": candidate.congestion_index,
            "jam_level": candidate.jam_level,
            "road_closure": candidate.road_closure,
            "raw_payload": compact_json(candidate.properties),
            "raw_ttl_expires_at": raw_ttl_expires_at,
        },
    ).fetchone()
    return int(row.id) if row else None


def _upsert_hotspot(db, observation_id: int) -> bool:
    row = db.execute(
        text("""
            WITH obs AS (
                SELECT id, city, geometry, congestion_index, observed_at, road_segment_id
                FROM traffic_observations
                WHERE id = :observation_id
            ),
            named AS (
                SELECT
                    obs.*,
                    COALESCE(rs.name, 'Unmatched traffic hotspot') AS road_name
                FROM obs
                LEFT JOIN road_segments rs ON rs.id = obs.road_segment_id
            ),
            existing AS (
                SELECT h.id
                FROM traffic_hotspots h, named n
                WHERE LOWER(h.city) = LOWER(n.city)
                  AND ST_DWithin(h.geometry::geography, n.geometry::geography, 250)
                ORDER BY ST_Distance(h.geometry::geography, n.geometry::geography)
                LIMIT 1
            ),
            updated AS (
                UPDATE traffic_hotspots h
                SET
                    last_seen_at = n.observed_at,
                    severity_score = GREATEST(COALESCE(h.severity_score, 0), COALESCE(n.congestion_index, 0) * 100),
                    frequency_score = COALESCE(h.frequency_score, 0) + 1,
                    duration_minutes = COALESCE(h.duration_minutes, 0) + 60,
                    status = 'active',
                    promoted_polling_until = n.observed_at + INTERVAL '3 hours'
                FROM named n, existing e
                WHERE h.id = e.id
                RETURNING h.id
            ),
            inserted AS (
                INSERT INTO traffic_hotspots (
                    city, name, geometry, first_seen_at, last_seen_at,
                    severity_score, frequency_score, duration_minutes,
                    status, promoted_polling_until
                )
                SELECT
                    n.city, n.road_name, n.geometry, n.observed_at, n.observed_at,
                    COALESCE(n.congestion_index, 0) * 100, 1, 60,
                    'active', n.observed_at + INTERVAL '3 hours'
                FROM named n
                WHERE NOT EXISTS (SELECT 1 FROM updated)
                RETURNING id
            )
            SELECT id FROM updated
            UNION ALL
            SELECT id FROM inserted
            LIMIT 1
        """),
        {"observation_id": observation_id},
    ).fetchone()
    return row is not None


def _record_run(
    db,
    *,
    run_id: str,
    started_at: datetime,
    finished_at: datetime | None,
    city: str | None,
    mode: str,
    tile_requests: int,
    non_tile_requests: int,
    observations_saved: int,
    observations_skipped: int,
    hotspots_updated: int,
    status: str,
    error_message: str | None = None,
) -> None:
    db.execute(
        text("""
            INSERT INTO tomtom_ingestion_runs (
                run_id, started_at, finished_at, city, mode, tile_requests,
                non_tile_requests, observations_saved, observations_skipped,
                hotspots_updated, status, error_message
            )
            VALUES (
                :run_id, :started_at, :finished_at, :city, :mode, :tile_requests,
                :non_tile_requests, :observations_saved, :observations_skipped,
                :hotspots_updated, :status, :error_message
            )
        """),
        {
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "city": city,
            "mode": mode,
            "tile_requests": tile_requests,
            "non_tile_requests": non_tile_requests,
            "observations_saved": observations_saved,
            "observations_skipped": observations_skipped,
            "hotspots_updated": hotspots_updated,
            "status": status,
            "error_message": error_message,
        },
    )
    db.commit()


def _refresh_daily_stats(db, city: str, target_date: date) -> None:
    start_of_day = datetime.combine(target_date, time.min)
    end_of_day = start_of_day + timedelta(days=1)
    db.execute(
        text("""
            WITH city_hotspots AS (
                SELECT
                    id,
                    geometry
                FROM traffic_hotspots
                WHERE LOWER(city) = LOWER(:city)
            ),
            city_observations AS (
                SELECT
                    observed_at,
                    congestion_index,
                    geometry
                FROM traffic_observations
                WHERE LOWER(city) = LOWER(:city)
                  AND observed_at >= :start_of_day
                  AND observed_at < :end_of_day
                  AND congestion_index IS NOT NULL
            ),
            hotspot_observations AS (
                SELECT
                    h.id AS hotspot_id,
                    o.observed_at,
                    o.congestion_index
                FROM city_hotspots h
                JOIN city_observations o
                  ON ST_DWithin(o.geometry::geography, h.geometry::geography, 250)
            ),
            ranked_peak AS (
                SELECT DISTINCT ON (hotspot_id)
                    hotspot_id,
                    EXTRACT(HOUR FROM observed_at)::integer AS peak_hour
                FROM hotspot_observations
                ORDER BY hotspot_id, congestion_index DESC, observed_at
            ),
            aggregated AS (
                SELECT
                    hotspot_id,
                    AVG(congestion_index) AS avg_congestion_index,
                    MAX(congestion_index) AS max_congestion_index,
                    COUNT(*) * 60 AS minutes_congested,
                    COUNT(*) AS sample_count
                FROM hotspot_observations
                GROUP BY hotspot_id
            ),
            deleted AS (
                DELETE FROM daily_hotspot_stats ds
                USING traffic_hotspots h
                WHERE ds.hotspot_id = h.id
                  AND LOWER(h.city) = LOWER(:city)
                  AND ds.date = :target_date
            )
            INSERT INTO daily_hotspot_stats (
                hotspot_id, date, peak_hour, avg_congestion_index,
                max_congestion_index, minutes_congested, sample_count,
                weather_summary, incident_count
            )
            SELECT
                a.hotspot_id,
                :target_date,
                rp.peak_hour,
                a.avg_congestion_index,
                a.max_congestion_index,
                a.minutes_congested,
                a.sample_count,
                NULL,
                0
            FROM aggregated a
            LEFT JOIN ranked_peak rp ON rp.hotspot_id = a.hotspot_id
        """),
        {
            "city": city,
            "target_date": target_date,
            "start_of_day": start_of_day,
            "end_of_day": end_of_day,
        },
    )


def _expire_raw_payloads(db, now: datetime) -> None:
    db.execute(
        text("""
            UPDATE traffic_observations
            SET raw_payload = NULL
            WHERE raw_payload IS NOT NULL
              AND raw_ttl_expires_at IS NOT NULL
              AND raw_ttl_expires_at < :now
        """),
        {"now": now},
    )


def ingest_city(
    city: str,
    city_scope: CityScope,
    mode: str,
    observed_at: datetime,
    budget: DailyTileBudget,
    *,
    finalize_city: bool = True,
    max_tiles_per_city: int | None = None,
) -> dict[str, int]:
    db = SessionLocal()
    client = TomTomClient()
    run_id = uuid.uuid4().hex[:10]
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    tile_requests = 0
    observations_saved = 0
    observations_skipped = 0
    hotspots_updated = 0
    try:
        raw_retention_days = int(os.getenv("TOMTOM_RAW_RETENTION_DAYS", "7"))
        threshold = float(os.getenv("TOMTOM_CONGESTION_THRESHOLD", "0.35"))
        include_baseline = mode == "baseline"
        zoom = int(os.getenv("TOMTOM_DISCOVERY_ZOOM", "12"))
        bboxes = [city_scope.bbox]
        if mode == "tracking":
            zoom = int(os.getenv("TOMTOM_HOTSPOT_ZOOM", "13"))
            bboxes = _active_hotspot_bboxes(db, city) or []
        # Bootstrap behavior: if tracking is scheduled but no hotspots exist yet,
        # fall back to a small discovery scan so we start collecting observations.
        if not bboxes and mode == "tracking" and os.getenv("TOMTOM_TRACKING_BOOTSTRAP_DISCOVERY", "true").lower() in {"1", "true", "yes", "on"}:
            zoom = int(os.getenv("TOMTOM_DISCOVERY_ZOOM", "12"))
            bboxes = [city_scope.bbox]
        if not bboxes:
            _record_run(
                db,
                run_id=run_id,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc).replace(tzinfo=None),
                city=city,
                mode=mode,
                tile_requests=0,
                non_tile_requests=0,
                observations_saved=0,
                observations_skipped=0,
                hotspots_updated=0,
                status="skipped",
                error_message="No active hotspot boxes",
            )
            return {"tile_requests": 0, "observations_saved": 0, "observations_skipped": 0, "hotspots_updated": 0}

        ttl = observed_at + timedelta(days=raw_retention_days)
        for bbox in bboxes:
            tiles = tiles_for_bbox(bbox, zoom, max_tiles=max_tiles_per_city)
            for tile in tiles:
                if not budget.try_consume():
                    raise RuntimeError("TomTom tile daily limit reached")
                payload = client.fetch_flow_tile(tile)
                tile_requests += 1
                candidates, skipped = candidates_from_tile(
                    city=city,
                    observed_at=observed_at,
                    tile=tile,
                    payload=payload,
                    threshold=threshold,
                    include_baseline=include_baseline,
                )
                observations_skipped += skipped
                for candidate in candidates:
                    observation_id = _insert_candidate(db, candidate, ttl)
                    if observation_id is None:
                        observations_skipped += 1
                        continue
                    observations_saved += 1
                    if candidate.jam_level in {"moderate", "heavy", "severe"} and _upsert_hotspot(db, observation_id):
                        hotspots_updated += 1
                db.commit()

        if finalize_city:
            _refresh_daily_stats(db, city, observed_at.date())
            _expire_raw_payloads(db, observed_at)
        db.commit()
        if finalize_city:
            try:
                generated_tiles = pregenerate_traffic_tiles_for_observations(db, city=city, observed_at=observed_at)
                if generated_tiles:
                    log.info("Pre-generated %s traffic tiles for %s at %s", generated_tiles, city, observed_at.isoformat())
            except Exception as exc:
                db.rollback()
                log.warning("Traffic tile pregeneration failed for %s at %s: %s", city, observed_at.isoformat(), exc)
        _record_run(
            db,
            run_id=run_id,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc).replace(tzinfo=None),
            city=city,
            mode=mode,
            tile_requests=tile_requests,
            non_tile_requests=0,
            observations_saved=observations_saved,
            observations_skipped=observations_skipped,
            hotspots_updated=hotspots_updated,
            status="success",
        )
        return {
            "tile_requests": tile_requests,
            "observations_saved": observations_saved,
            "observations_skipped": observations_skipped,
            "hotspots_updated": hotspots_updated,
        }
    except Exception as exc:
        db.rollback()
        _record_run(
            db,
            run_id=run_id,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc).replace(tzinfo=None),
            city=city,
            mode=mode,
            tile_requests=tile_requests,
            non_tile_requests=0,
            observations_saved=observations_saved,
            observations_skipped=observations_skipped,
            hotspots_updated=hotspots_updated,
            status="partial" if observations_saved else "failed",
            error_message=str(exc),
        )
        raise
    finally:
        db.close()


def finalize_city_ingestion(city: str, observed_at: datetime) -> None:
    db = SessionLocal()
    try:
        _refresh_daily_stats(db, city, observed_at.date())
        _expire_raw_payloads(db, observed_at)
        db.commit()
        try:
            generated_tiles = pregenerate_traffic_tiles_for_observations(db, city=city, observed_at=observed_at)
            if generated_tiles:
                log.info("Pre-generated %s traffic tiles for %s at %s", generated_tiles, city, observed_at.isoformat())
        except Exception as exc:
            db.rollback()
            log.warning("Traffic tile pregeneration failed for %s at %s: %s", city, observed_at.isoformat(), exc)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run_ingestion(
    *,
    cities: list[str] | None = None,
    mode: str = "auto",
    observed_at: datetime | None = None,
    max_tiles_per_city: int | None = None,
) -> dict[str, int]:
    Base.metadata.create_all(bind=engine)
    bootstrap_database()
    observed_at = observed_at or datetime.now(timezone.utc).replace(tzinfo=None)
    modes = modes_for_now(datetime.now(IST)) if mode == "auto" else [mode]
    if not modes:
        log.info("No ingestion mode due at this hour.")
        return {"tile_requests": 0, "observations_saved": 0, "observations_skipped": 0, "hotspots_updated": 0}

    db = SessionLocal()
    try:
        city_scopes = load_city_scopes(db)
        tile_used, _ = _quota_used_today(db)
    finally:
        db.close()

    if not city_scopes:
        raise RuntimeError("No road_segments city scopes found; ingest cannot determine discovery areas.")

    selected_cities = [_normalize_city_name(city) for city in (cities or list(city_scopes.keys()))]
    invalid_cities = [city for city in selected_cities if city not in city_scopes]
    if invalid_cities:
        raise ValueError(
            f"Unsupported city selection: {', '.join(sorted(invalid_cities))}. "
            f"Available cities: {', '.join(sorted(city_scopes))}"
        )

    budget = DailyTileBudget(
        used=tile_used,
        limit=int(os.getenv("TOMTOM_TILE_DAILY_LIMIT", "45000")),
    )
    max_workers = max(1, int(os.getenv("TOMTOM_MAX_CITY_WORKERS", "5")))
    totals = {"tile_requests": 0, "observations_saved": 0, "observations_skipped": 0, "hotspots_updated": 0}
    successful_cities: set[str] = set()

    for current_mode in modes:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(selected_cities))) as executor:
            future_map = {
                executor.submit(
                    ingest_city,
                    city,
                    city_scopes[city],
                    current_mode,
                    observed_at,
                    budget,
                    finalize_city=False,
                    max_tiles_per_city=max_tiles_per_city,
                ): city
                for city in selected_cities
            }
            for future in as_completed(future_map):
                city = future_map[future]
                log.info("Ingesting %s traffic for %s", current_mode, city)
                try:
                    result = future.result()
                except Exception as exc:
                    log.error("TomTom ingestion failed for %s/%s: %s", city, current_mode, exc)
                    continue
                successful_cities.add(city)
                for key, value in result.items():
                    totals[key] += value

    for city in sorted(successful_cities):
        try:
            finalize_city_ingestion(city, observed_at)
        except Exception as exc:
            log.error("Daily hotspot stats refresh failed for %s: %s", city, exc)

    log.info("TomTom ingestion complete: %s", json.dumps(totals, sort_keys=True))
    return totals


def modes_for_now(now: datetime) -> list[str]:
    modes: list[str] = []
    if _is_peak(now):
        modes.append("discovery")
    if _is_baseline_hour(now):
        modes.append("baseline")
    if now.astimezone(IST).hour % int(os.getenv("TOMTOM_TRACKING_INTERVAL_HOURS", "3")) == 0:
        modes.append("tracking")
    return modes


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest TomTom hotspot-first traffic observations.")
    parser.add_argument("--mode", choices=["auto", "discovery", "tracking", "baseline"], default="auto")
    parser.add_argument("--city", action="append")
    args = parser.parse_args()
    run_ingestion(cities=args.city, mode=args.mode)


if __name__ == "__main__":
    main()
