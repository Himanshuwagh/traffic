#!/usr/bin/env bash
# generate_pmtiles.sh
# -------------------
# Converts road_segments.ndjson → india-roads.pmtiles using tippecanoe.
#
# Prerequisites:
#   brew install tippecanoe          (macOS)
#   sudo apt install tippecanoe      (Ubuntu / Debian)
#
# Run from the project root:
#   bash scripts/generate_pmtiles.sh
#
# The output file india-roads.pmtiles is written to the project root.
# tippecanoe does NOT touch the database — it reads only the local .ndjson file.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
INPUT="$PROJECT_ROOT/road_segments.ndjson"
OUTPUT="$PROJECT_ROOT/india-roads.pmtiles"

# ── Sanity checks ─────────────────────────────────────────────────────────────

if ! command -v tippecanoe &>/dev/null; then
  echo "ERROR: tippecanoe not found."
  echo "  macOS : brew install tippecanoe"
  echo "  Linux : sudo apt install tippecanoe"
  exit 1
fi

if [[ ! -f "$INPUT" ]]; then
  echo "ERROR: $INPUT not found."
  echo "  Run first: cd backend && python export_roads_geojson.py --out ../road_segments.ndjson"
  exit 1
fi

LINE_COUNT=$(wc -l < "$INPUT" | tr -d ' ')
echo "=== Generating PMTiles ==="
echo "  Input  : $INPUT  ($LINE_COUNT features)"
echo "  Output : $OUTPUT"
echo "  Zoom   : z4 – z14"
echo ""

# ── tippecanoe ───────────────────────────────────────────────────────────────
# Flag rationale:
#
#   --layer=segments
#       Must match BASE_SOURCE_LAYER = "segments" in MapboxMap.tsx.
#
#   --minimum-zoom=4  --maximum-zoom=14
#       z4  → country overview (India fits in one tile cluster)
#       z14 → street-level detail (Mapbox overzooms z14 tiles for z>14)
#       SOURCE_MAXZOOM in the frontend is also 14.
#
#   --simplification=10  --simplify-only-low-zooms
#       Reduces LineString vertex count at z4-z10 (lower detail = smaller tiles).
#       At z11+ full geometry is kept so roads look sharp when zoomed in.
#
#   --drop-densest-as-needed
#       If a tile still exceeds 500 kB after simplification, tippecanoe
#       drops the densest features to keep tile sizes sane.
#       Road networks in dense cities (Mumbai, Delhi) trigger this at low zooms.
#
#   --extend-zooms-if-still-dropping
#       Any feature dropped at zoom N will appear at zoom N+1 instead, so
#       no road silently disappears — it just becomes visible at a higher zoom.
#
#   --buffer=4
#       4 pixel buffer prevents line caps from being clipped at tile edges.
#       (Mapbox default is 128; 4 is enough for lines and reduces tile size.)
#
#   --no-progress-indicator
#       Keeps the log clean in CI / Railway environments.
#
#   --force
#       Overwrites the output file if it already exists.

tippecanoe \
  --output="$OUTPUT" \
  --layer=segments \
  --minimum-zoom=4 \
  --maximum-zoom=14 \
  --simplification=10 \
  --simplify-only-low-zooms \
  --drop-densest-as-needed \
  --extend-zooms-if-still-dropping \
  --buffer=4 \
  --no-progress-indicator \
  --force \
  "$INPUT"

SIZE_MB=$(du -sm "$OUTPUT" | awk '{print $1}')
echo ""
echo "✅  Done — $OUTPUT  (${SIZE_MB} MB)"
echo "    Next step: bash scripts/upload_r2.sh"
