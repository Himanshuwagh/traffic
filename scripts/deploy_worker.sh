#!/usr/bin/env bash
# deploy_worker.sh
# ----------------
# Installs dependencies and deploys the Cloudflare Worker tile server.
#
# Prerequisites:
#   npm install -g wrangler
#   wrangler login       (once — opens browser to authenticate)
#
# Run from the project root:
#   bash scripts/deploy_worker.sh
#
# After deploying, the Worker URL is printed:
#   https://traffic-tile-server.YOUR_SUBDOMAIN.workers.dev
# Set that as VITE_TILE_SERVER_URL in Vercel environment variables.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKER_DIR="$(dirname "$SCRIPT_DIR")/cloudflare-worker"

if ! command -v wrangler &>/dev/null; then
  echo "ERROR: wrangler CLI not found."
  echo "  Install: npm install -g wrangler"
  echo "  Auth   : wrangler login"
  exit 1
fi

echo "=== Deploying Cloudflare Worker tile server ==="
echo "  Directory: $WORKER_DIR"
echo ""

cd "$WORKER_DIR"

echo "[1/2] Installing Worker dependencies…"
npm install

echo ""
echo "[2/2] Deploying Worker with wrangler…"
echo "      (first deploy may take ~30 seconds)"
npm run deploy

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅  Worker deployed!"
echo ""
echo "  The Worker URL was printed above by wrangler."
echo "  It looks like: https://traffic-tile-server.YOUR_NAME.workers.dev"
echo ""
echo "  Set it in Vercel environment variables:"
echo "    VITE_TILE_SERVER_URL = https://traffic-tile-server.YOUR_NAME.workers.dev"
echo ""
echo "  Then redeploy your Vercel frontend."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
