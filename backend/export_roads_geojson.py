"""
export_roads_geojson.py
-----------------------
Exports the road_segments table from Supabase (or any PostgreSQL/PostGIS DB)
as GeoJSON NDJSON — one Feature per line — to a local file.

This script is READ-ONLY: it issues only SELECT queries, never writes,
updates, or deletes anything in the database.

Why NDJSON (newline-delimited JSON)?
    tippecanoe accepts NDJSON directly and processes it line-by-line
    without loading the entire file into RAM, which is important at
    scale (8 M+ records).

Why offset-based pagination?
    Supabase uses PgBouncer in transaction-pooling mode, which does not
    support PostgreSQL server-side cursors.  Offset pagination avoids
    that limitation entirely, at the cost of slightly more round-trips.

Usage:
    # from inside the backend/ directory:
    python export_roads_geojson.py --out road_segments.ndjson

    # override page size (default 1 000):
    python export_roads_geojson.py --out road_segments.ndjson --batch 2000

    # dry-run: print first 10 features to stdout, don't write a file:
    python export_roads_geojson.py --limit 10
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL — pure SELECT, nothing is modified
# ---------------------------------------------------------------------------
# ST_AsGeoJSON returns the geometry as a GeoJSON string (e.g. {"type":"LineString",...}).
# We parse it in Python and embed it as a proper JSON object inside the Feature.
_SELECT_SQL = text("""
    SELECT
        id,
        COALESCE(name, 'Unknown')          AS name,
        COALESCE(city, '')                 AS city,
        COALESCE(highway_type, 'unknown')  AS highway_type,
        lanes,
        COALESCE(oneway, 'False')          AS oneway,
        ST_AsGeoJSON(geometry)             AS geom_json
    FROM road_segments
    WHERE geometry IS NOT NULL
    ORDER BY id
    LIMIT  :limit
    OFFSET :offset
""")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export road_segments as GeoJSON NDJSON (read-only)"
    )
    parser.add_argument(
        "--out", default="-",
        help="Output file path. Use '-' for stdout (default: -).",
    )
    parser.add_argument(
        "--batch", type=int, default=1_000,
        help="Rows fetched per DB round-trip (default: 1 000).",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Stop after this many rows total (0 = no limit, default: 0).",
    )
    args = parser.parse_args()

    # ── Load env ─────────────────────────────────────────────────────────────
    load_dotenv()
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        log.error("DATABASE_URL environment variable is not set.")
        log.error("Copy backend/.env.example to backend/.env and fill in the value.")
        sys.exit(1)

    log.info("Connecting to database…")
    engine = create_engine(db_url, pool_pre_ping=True)

    # ── Open output ───────────────────────────────────────────────────────────
    out_is_file = args.out != "-"
    if out_is_file:
        out = open(args.out, "w", encoding="utf-8")
        log.info("Writing NDJSON to: %s", args.out)
    else:
        out = sys.stdout
        log.info("Writing NDJSON to stdout")

    # ── Stream with offset pagination ─────────────────────────────────────────
    start   = time.monotonic()
    count   = 0
    offset  = 0
    batch   = args.batch
    hard_limit = args.limit or float("inf")  # type: ignore[assignment]

    try:
        with engine.connect() as conn:
            while True:
                rows = conn.execute(
                    _SELECT_SQL,
                    {"limit": batch, "offset": offset},
                ).fetchall()

                if not rows:
                    break  # no more rows

                for row in rows:
                    if count >= hard_limit:
                        break

                    # Parse PostGIS GeoJSON string into a Python dict
                    geometry = json.loads(row.geom_json)

                    feature = {
                        "type": "Feature",
                        "id": row.id,
                        "geometry": geometry,
                        "properties": {
                            "name":         row.name,
                            "city":         row.city,
                            "highway_type": row.highway_type,
                            "lanes":        int(row.lanes) if row.lanes is not None else None,
                            "oneway":       row.oneway,
                        },
                    }

                    out.write(json.dumps(feature, separators=(",", ":")) + "\n")
                    count += 1

                    if count % 10_000 == 0:
                        elapsed = time.monotonic() - start
                        rate = count / elapsed if elapsed > 0 else 0
                        log.info(
                            "  exported %9d rows  |  offset %-9d  |  %.0f rows/s",
                            count, offset, rate,
                        )

                if count >= hard_limit:
                    break

                offset += batch

    finally:
        if out_is_file:
            out.close()

    elapsed = time.monotonic() - start
    log.info(
        "✅  Done — exported %d road segments in %.1f s  →  %s",
        count, elapsed, args.out if out_is_file else "stdout",
    )
    if out_is_file:
        size_mb = os.path.getsize(args.out) / 1_048_576
        log.info("    File size: %.1f MB", size_mb)


if __name__ == "__main__":
    main()
