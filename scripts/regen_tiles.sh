#!/usr/bin/env bash
# regen_tiles.sh
# --------------
# Full pipeline: export Supabase data → generate PMTiles → upload to R2.
# Run this whenever fetch_india_districts.py adds new districts.
#
# Prerequisites: see generate_pmtiles.sh and upload_r2.sh headers.
#
# Run from the project root:
#   DATABASE_URL="postgresql://..." bash scripts/regen_tiles.sh
#   R2_BUCKET=my-bucket DATABASE_URL="..." bash scripts/regen_tiles.sh
#
# The script is idempotent — safe to re-run. It overwrites the local
# .ndjson and .pmtiles files and replaces the R2 object in-place.
# Nothing in the database is modified.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/backend"

NDJSON_FILE="$PROJECT_ROOT/road_segments.ndjson"
PMTILES_FILE="$PROJECT_ROOT/india-roads.pmtiles"

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "  🗺   PMTiles Regeneration Pipeline"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# ── Step 1: Export from Supabase ──────────────────────────────────────────────
echo "STEP 1/3 — Export road_segments from Supabase (read-only)"
echo "──────────────────────────────────────────────────────────"

# Load .env if DATABASE_URL is not already in the environment
if [[ -z "${DATABASE_URL:-}" && -f "$BACKEND_DIR/.env" ]]; then
  # shellcheck source=/dev/null
  set -a
  source "$BACKEND_DIR/.env"
  set +a
  echo "  Loaded DATABASE_URL from backend/.env"
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is not set."
  echo "  Either:"
  echo "    export DATABASE_URL='postgresql://...'"
  echo "  or ensure backend/.env contains DATABASE_URL=postgresql://..."
  exit 1
fi

# Run from backend/ so that dotenv & local imports resolve correctly
(
  cd "$BACKEND_DIR"
  python export_roads_geojson.py --out "$NDJSON_FILE"
)

FEATURES=$(wc -l < "$NDJSON_FILE" | tr -d ' ')
echo "  Exported $FEATURES features → $NDJSON_FILE"
echo ""

# ── Step 2: Generate PMTiles ──────────────────────────────────────────────────
echo "STEP 2/3 — Generate PMTiles with tippecanoe"
echo "────────────────────────────────────────────"
bash "$SCRIPT_DIR/generate_pmtiles.sh"
echo ""

# ── Step 3: Upload to Cloudflare R2 ──────────────────────────────────────────
echo "STEP 3/3 — Upload to Cloudflare R2"
echo "────────────────────────────────────"
bash "$SCRIPT_DIR/upload_r2.sh"
echo ""

echo "════════════════════════════════════════════════════════════════════"
echo "  ✅  Pipeline complete"
echo ""
echo "  Files:"
NDJSON_MB=$(du -sm "$NDJSON_FILE" | awk '{print $1}')
PMTILES_MB=$(du -sm "$PMTILES_FILE" | awk '{print $1}')
echo "    road_segments.ndjson : ${NDJSON_MB} MB  (can be deleted after upload)"
echo "    india-roads.pmtiles  : ${PMTILES_MB} MB  (can be deleted after upload)"
echo ""
echo "  The R2 object has been replaced in-place."
echo "  No Vercel redeploy needed — browsers will pick up the new"
echo "  tiles automatically (R2 ETag changes, PMTiles re-fetches header)."
echo "════════════════════════════════════════════════════════════════════"
