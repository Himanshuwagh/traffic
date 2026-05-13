#!/usr/bin/env bash
# upload_r2.sh
# ------------
# Applies CORS rules and uploads india-roads.pmtiles to Cloudflare R2.
#
# Prerequisites:
#   npm install -g wrangler
#   wrangler login                  (opens browser — authenticate once)
#
# Required env vars (or pass as CLI arguments):
#   R2_BUCKET   — name of your R2 bucket (default: traffic-tiles)
#
# Run from the project root:
#   bash scripts/upload_r2.sh
#   R2_BUCKET=my-bucket bash scripts/upload_r2.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PMTILES_FILE="$PROJECT_ROOT/india-roads.pmtiles"
CORS_FILE="$SCRIPT_DIR/r2_cors.json"

R2_BUCKET="${R2_BUCKET:-traffic-tiles}"
R2_OBJECT_KEY="india-roads.pmtiles"

# ── Sanity checks ─────────────────────────────────────────────────────────────

if ! command -v wrangler &>/dev/null; then
  echo "ERROR: wrangler CLI not found."
  echo "  Install: npm install -g wrangler"
  echo "  Auth   : wrangler login"
  exit 1
fi

if [[ ! -f "$PMTILES_FILE" ]]; then
  echo "ERROR: $PMTILES_FILE not found."
  echo "  Run first: bash scripts/generate_pmtiles.sh"
  exit 1
fi

echo "=== Uploading to Cloudflare R2 ==="
echo "  Bucket : $R2_BUCKET"
echo "  Object : $R2_OBJECT_KEY"
echo "  File   : $PMTILES_FILE"
SIZE_MB=$(du -sm "$PMTILES_FILE" | awk '{print $1}')
echo "  Size   : ${SIZE_MB} MB"
echo ""

# ── Step 1: Create bucket if it does not exist ───────────────────────────────
echo "[1/3] Ensuring bucket '$R2_BUCKET' exists…"
# 'wrangler r2 bucket create' is idempotent — it succeeds even if the bucket exists
wrangler r2 bucket create "$R2_BUCKET" 2>/dev/null || true
echo "      OK"

# ── Step 2: Apply CORS rules (required for browser HTTP range requests) ───────
echo "[2/3] Applying CORS rules from $CORS_FILE…"
# Range requests (Accept-Ranges / Content-Range) are required by the pmtiles
# JavaScript library to fetch individual tile byte ranges from the single file.
wrangler r2 bucket cors put "$R2_BUCKET" --rules "$CORS_FILE"
echo "      OK"

# ── Step 3: Upload the PMTiles file ──────────────────────────────────────────
echo "[3/3] Uploading $PMTILES_FILE → r2://$R2_BUCKET/$R2_OBJECT_KEY"
echo "      (this may take a few minutes for large files)"
wrangler r2 object put "$R2_BUCKET/$R2_OBJECT_KEY" \
  --file="$PMTILES_FILE" \
  --content-type="application/octet-stream"

echo ""
echo "✅  Upload complete."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  NEXT STEP: Enable public access for your R2 bucket"
echo ""
echo "  1. Go to https://dash.cloudflare.com → R2 → $R2_BUCKET → Settings"
echo "  2. Under 'Public access', click 'Allow Access'"
echo "  3. Copy the public URL shown (looks like:"
echo "       https://pub-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX.r2.dev)"
echo ""
echo "  4. Set this in Vercel environment variables:"
echo "       VITE_PMTILES_URL=https://pub-XXX.r2.dev/india-roads.pmtiles"
echo ""
echo "  5. Redeploy on Vercel."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
