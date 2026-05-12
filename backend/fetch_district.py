"""
fetch_district.py
-----------------
Fetch road segments for a single Indian district using OSMnx graph_from_place.

Unlike the radius-based fetch_segments.py, this uses the actual OSM
administrative boundary of the district, so:
  - Coverage is complete (no artificial radius cutoff)
  - No overlap between adjacent districts
  - Memory usage is bounded by district size (not a fixed 15 km circle)

Segments are committed in batches of BATCH_SIZE rows so Railway crashes lose
at most one batch worth of work.

The `city` column is set to the lowercased district name, matching the
convention used by the existing city-based imports, so the API can filter by
district name.
"""

from __future__ import annotations

import logging
import os

import osmnx as ox
from sqlalchemy import text

try:
    from .database import SessionLocal
except ImportError:
    from database import SessionLocal  # type: ignore[no-redef]

log = logging.getLogger(__name__)

BATCH_SIZE: int = max(1, int(os.getenv("SEGMENT_INSERT_BATCH_SIZE", "500")))

# ---------------------------------------------------------------------------
# Road filter — only fetch highway types that are relevant for traffic
# analytics.  Skipping residential/service/living_street cuts memory use by
# 60-70% and is the right data for a traffic intelligence platform anyway.
#
# Override via HIGHWAY_FILTER env var, e.g.:
#   HIGHWAY_FILTER="motorway|trunk|primary" for only major highways
# ---------------------------------------------------------------------------
_DEFAULT_HIGHWAY_FILTER = (
    "motorway|motorway_link"
    "|trunk|trunk_link"
    "|primary|primary_link"
    "|secondary|secondary_link"
    "|tertiary|tertiary_link"
)
HIGHWAY_FILTER: str = os.getenv("HIGHWAY_FILTER", _DEFAULT_HIGHWAY_FILTER)
OSMNX_CUSTOM_FILTER: str = f'["highway"~"{HIGHWAY_FILTER}"]'

_INSERT_SQL = text("""
    INSERT INTO road_segments (name, city, geometry, lanes, highway_type, oneway)
    VALUES (:name, :city, ST_GeomFromText(:wkt, 4326), :lanes, :highway_type, :oneway)
""")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _flush(db, batch: list[dict], label: str, saved: int) -> int:
    """Commit one batch to DB immediately. Clears the batch list in-place."""
    if not batch:
        return saved
    db.execute(_INSERT_SQL, batch)
    db.commit()
    saved += len(batch)
    log.info("  💾  +%d rows committed for %-30s  (running total: %d)", len(batch), label, saved)
    batch.clear()
    return saved


def _parse_lanes(raw) -> int | None:
    if raw is None:
        return None
    try:
        v = raw[0] if isinstance(raw, list) else raw
        return int(v)
    except Exception:
        return None


def _first(raw, default: str = "Unknown") -> str:
    if isinstance(raw, list):
        return str(raw[0]) if raw else default
    return str(raw) if raw is not None else default


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_segments_for_district(district: str, state: str) -> bool:
    """
    Fetch and persist road segments for *district* in *state*.

    Returns True on success (including empty districts), False on any error.
    Never raises.
    """
    place = f"{district}, {state}, India"
    short = district.strip().lower()

    log.info('Fetching road network for "%s" from OSMnx (place boundary)…', place)

    # ── Step 1: Download graph from OSM ──────────────────────────────────────
    log.info(
        '  Highway filter : %s',
        HIGHWAY_FILTER,
    )
    try:
        G = ox.graph_from_place(
            place,
            custom_filter=OSMNX_CUSTOM_FILTER,
            simplify=True,
            retain_all=False,
        )
    except Exception as exc:
        log.error('OSMnx could not fetch "%s": %s', place, exc)
        return False

    # ── Step 2: Convert to GeoDataFrame ──────────────────────────────────────
    try:
        gdf = ox.graph_to_gdfs(G, nodes=False)
    except Exception as exc:
        log.error('graph_to_gdfs failed for "%s": %s', place, exc)
        return False

    total = len(gdf)
    log.info('Loaded %d road segments for %s', total, place)

    if total == 0:
        log.warning('No road segments found for "%s" — marking success (empty graph).', place)
        return True

    # ── Step 3: Persist to DB ─────────────────────────────────────────────────
    db = SessionLocal()
    try:
        # Remove any previous partial import so retries are deterministic.
        deleted = db.execute(
            text("DELETE FROM road_segments WHERE city = :city"),
            {"city": short},
        ).rowcount or 0
        db.commit()
        if deleted:
            log.info("Removed %d stale rows for '%s' before re-import.", deleted, short)

        saved = 0
        batch: list[dict] = []

        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom.geom_type != "LineString":
                continue

            batch.append({
                "name":         _first(row.get("name"), "Unknown"),
                "city":         short,
                "wkt":          geom.wkt,
                "lanes":        _parse_lanes(row.get("lanes")),
                "highway_type": _first(row.get("highway"), "Unknown"),
                "oneway":       _first(row.get("oneway"), "False"),
            })

            if len(batch) >= BATCH_SIZE:
                saved = _flush(db, batch, short, saved)

        # Flush remainder
        saved = _flush(db, batch, short, saved)
        log.info("✅  %d segments saved for '%s'", saved, short)
        return True

    except Exception as exc:
        db.rollback()
        log.error("DB error while saving '%s': %s", place, exc, exc_info=True)
        return False
    finally:
        db.close()


# ---------------------------------------------------------------------------
# CLI entry point (for one-off testing)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    if len(sys.argv) < 3:
        print("Usage: python fetch_district.py <district> <state>")
        print('Example: python fetch_district.py "Pune" "Maharashtra"')
        sys.exit(1)
    ok = fetch_segments_for_district(sys.argv[1], sys.argv[2])
    sys.exit(0 if ok else 1)
