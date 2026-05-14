from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


TOMTOM_API_BASE = "https://api.tomtom.com"
DEFAULT_TIMEOUT_SECONDS = 20


class TomTomConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class TileCoord:
    z: int
    x: int
    y: int

    @property
    def cache_key(self) -> str:
        return f"{self.z}-{self.x}-{self.y}"


class TomTomClient:
    def __init__(
        self,
        api_key: str | None = None,
        flow_style: str | None = None,
        cache_dir: str | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.api_key = (api_key or os.getenv("TOMTOM_API_KEY") or "").strip()
        if not self.api_key:
            raise TomTomConfigError("TOMTOM_API_KEY is required")
        self.flow_style = flow_style or os.getenv("TOMTOM_FLOW_STYLE", "relative-delay")
        self.timeout_seconds = timeout_seconds
        self.cache_dir = Path(cache_dir or os.getenv("TOMTOM_TILE_CACHE_DIR", "/tmp/tomtom_tile_cache"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_flow_tile(self, tile: TileCoord, *, use_cache: bool = True) -> bytes:
        cache_file = self.cache_dir / f"{self.flow_style}-{tile.cache_key}.pbf"
        if use_cache and cache_file.exists():
            return cache_file.read_bytes()

        # TomTom Vector Flow Tiles endpoint:
        #   /traffic/map/4/tile/flow/{type}/{z}/{x}/{y}.pbf
        url = (
            f"{TOMTOM_API_BASE}/traffic/map/4/tile/flow/"
            f"{self.flow_style}/{tile.z}/{tile.x}/{tile.y}.pbf"
        )
        response = requests.get(
            url,
            params={"key": self.api_key},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.content
        if use_cache:
            cache_file.write_bytes(payload)
        return payload

    def fetch_flow_tiles(self, bbox: tuple[float, float, float, float], zoom: int) -> list[tuple[TileCoord, bytes]]:
        return [(tile, self.fetch_flow_tile(tile)) for tile in tiles_for_bbox(bbox, zoom)]

    def fetch_flow_segment(
        self,
        point: tuple[float, float],
        *,
        zoom: int = 13,
        style: str = "absolute",
        open_lr: bool = True,
    ) -> dict[str, Any]:
        lat, lon = point
        url = f"{TOMTOM_API_BASE}/traffic/services/4/flowSegmentData/{style}/{zoom}/json"
        response = requests.get(
            url,
            params={
                "key": self.api_key,
                "point": f"{lat},{lon}",
                "unit": "KMPH",
                "openLr": str(open_lr).lower(),
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()


def lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    lat_rad = math.radians(lat)
    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def tile_point_to_lonlat(tile: TileCoord, px: float, py: float, extent: int = 4096) -> tuple[float, float]:
    n = 2**tile.z
    lon = (tile.x + px / extent) / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * (tile.y + py / extent) / n)))
    return lon, math.degrees(lat_rad)


def tiles_for_bbox(bbox: tuple[float, float, float, float], zoom: int, max_tiles: int | None = None) -> list[TileCoord]:
    min_lon, min_lat, max_lon, max_lat = bbox
    min_x, max_y = lonlat_to_tile(min_lon, min_lat, zoom)
    max_x, min_y = lonlat_to_tile(max_lon, max_lat, zoom)
    tiles = [
        TileCoord(zoom, x, y)
        for x in range(min(min_x, max_x), max(min_x, max_x) + 1)
        for y in range(min(min_y, max_y), max(min_y, max_y) + 1)
    ]
    limit = max_tiles or int(os.getenv("TOMTOM_MAX_TILES_PER_CITY", "120"))
    if len(tiles) > limit:
        raise ValueError(f"bbox at zoom {zoom} expands to {len(tiles)} tiles, above limit {limit}")
    return tiles


def stable_ref(*parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def compact_json(payload: Any) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)
