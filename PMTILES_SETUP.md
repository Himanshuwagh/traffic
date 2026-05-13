# Road Segment Tile Server — Setup Guide

Road segments are served via a **Cloudflare Worker** that reads from a **PMTiles** file on **Cloudflare R2**.

```
Browser
  → Cloudflare Worker  (public URL, ~5-20 ms cached / ~50-200 ms cold tile)
      → Cloudflare R2  (internal binding, no HTTP — reads PMTiles byte ranges)
```

The Worker serves standard `{z}/{x}/{y}.mvt` URLs, which Mapbox GL JS handles natively.  
No custom protocol or library changes are needed on the frontend.

The traffic overlay (coloured speed data) still comes from the Render API — that's dynamic and unchanged.

---

## Why this architecture?

| | Old (Render API for segments) | New (Worker + PMTiles) |
|---|---|---|
| First tile load (cold start) | 30–60 s | ~50-200 ms (cold) |
| Repeated tile loads | 2–5 s (in-memory cache lost on restart) | ~5-20 ms (Cloudflare CDN) |
| Cost | Free (Render free) | Free (CF free tier) |
| Scales to 8 M records | Slower | Same (tippecanoe handles it) |
| Supabase queries per tile | ~10-20 | 0 |

---

## Prerequisites (install once on your machine)

```bash
# tippecanoe — converts GeoJSON to PMTiles
brew install tippecanoe          # macOS
# sudo apt install tippecanoe   # Ubuntu/Debian

# wrangler — Cloudflare CLI (used for both R2 and Worker deployment)
npm install -g wrangler
wrangler login                   # opens browser — authenticate once
```

---

## First-time setup (run steps in order)

### Step 1 — Export road segments from Supabase (read-only, ~5 min for 292 K rows)

```bash
cd backend
python export_roads_geojson.py --out ../road_segments.ndjson
```

This creates `road_segments.ndjson` at the project root.  
**It is a pure SELECT — nothing in the database is changed or deleted.**

### Step 2 — Generate PMTiles (~2–10 min depending on CPU)

```bash
# from project root
bash scripts/generate_pmtiles.sh
```

Creates `india-roads.pmtiles` at the project root.  
Typical size: **30–120 MB** for 292 K segments.

### Step 3 — Create a Cloudflare account and enable R2

1. Sign up at <https://dash.cloudflare.com> (free).
2. Left sidebar → **R2 Object Storage** → enable it (free tier: 10 GB storage + 10 M reads/month).

### Step 4 — Upload PMTiles to R2

```bash
# from project root
bash scripts/upload_r2.sh
```

This creates the `traffic-tiles` bucket and uploads `india-roads.pmtiles`.  
The R2 bucket does **not** need to be public — the Worker accesses it via an internal binding.

### Step 5 — Deploy the Cloudflare Worker

```bash
# from project root
bash scripts/deploy_worker.sh
```

This installs dependencies and runs `wrangler deploy`.  
The output will print the Worker URL, like:
```
https://traffic-tile-server.YOUR_NAME.workers.dev
```

Verify it works by opening in your browser:
```
https://traffic-tile-server.YOUR_NAME.workers.dev/tiles/10/780/500.mvt
```
You should get a binary response (MVT tile data), not a 404.

### Step 6 — Set environment variable in Vercel

1. Vercel dashboard → your project → **Settings** → **Environment Variables**
2. Add:

   | Name | Value |
   |------|-------|
   | `VITE_TILE_SERVER_URL` | `https://traffic-tile-server.YOUR_NAME.workers.dev` |

3. Click **Save** → **Redeploy**.

### Step 7 — Verify in the deployed app

Open the app → DevTools → **Network** tab → filter by `workers.dev`.  
You should see tile requests completing in **< 100 ms** (after first load caches them).  
The first load of each tile will take 50–200 ms; all subsequent loads will be ~5–20 ms.

---

## Updating tiles after new districts are fetched

Whenever `fetch_india_districts.py` adds new districts, run:

```bash
# from project root (DATABASE_URL must be set or in backend/.env)
bash scripts/regen_tiles.sh
```

This re-exports from Supabase, regenerates PMTiles, and re-uploads to R2.  
**No Worker redeploy needed** — the Worker always reads the latest file from R2.  
The Cloudflare Cache API is keyed per tile, so tiles that haven't changed stay cached.

---

## Fallback behaviour

If `VITE_TILE_SERVER_URL` is **not set**, the map falls back to the original  
live MVT tiles from the Render API (`/api/segments/tiles/{z}/{x}/{y}.mvt`).  
This means the feature is fully opt-in and non-breaking — the app still works without it.

---

## File sizes (estimates)

| Records | NDJSON export | PMTiles (z4–z14) |
|---------|--------------|-----------------|
| 292 K (current) | ~200–350 MB | ~30–80 MB |
| 8 M (full India) | ~5–8 GB | ~500 MB–1.5 GB |

R2 free tier: **10 GB storage** — sufficient for the full India dataset.

---

## Cloudflare Worker free tier limits

| Metric | Free limit | Expected usage |
|--------|-----------|----------------|
| Worker requests/day | 100 K | Only cache misses count. After tiles are warmed up (each tile fetched once), nearly all requests hit the Cache API and cost 0 invocations. |
| R2 Class A ops (write) | 1 M/month | Only on upload — essentially 0 ongoing |
| R2 Class B ops (read) | 10 M/month | Only on Worker cache miss — very low ongoing |
| R2 storage | 10 GB | ~30-80 MB currently, ~1.5 GB at full India scale |

If you need more than 100 K Worker requests/day, upgrade to Cloudflare Workers paid plan ($5/month = 10 M req/day).

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Worker returns 500 | PMTiles file not in R2 | Run `scripts/upload_r2.sh` |
| Worker returns 500 with "not found in R2" | Bucket name mismatch | Check `wrangler.toml` `bucket_name` matches what `upload_r2.sh` created |
| Tiles are empty but no error | Wrong `source-layer` name | Must be `"segments"` — matches tippecanoe `--layer=segments` |
| CORS error on tile request | Worker CORS issue | Check Worker is deployed and URL is correct in Vercel env |
| `VITE_TILE_SERVER_URL` not picked up | Env var missing in Vercel | Add it in Vercel → Settings → Environment Variables, then redeploy |
| tippecanoe not found | Not installed | `brew install tippecanoe` |
| wrangler not found | Not installed | `npm install -g wrangler` |
