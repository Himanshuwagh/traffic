/**
 * traffic-tile-server — Cloudflare Worker
 * ----------------------------------------
 * Serves road-segment vector tiles (MVT) by reading from a PMTiles file
 * stored in an R2 bucket.
 *
 * Request pattern:
 *   GET /tiles/{z}/{x}/{y}.mvt
 *
 * Caching strategy:
 *   • Road geometry never changes once published, so tiles are cached
 *     in Cloudflare's Cache API with a 1-year TTL ("immutable").
 *   • On a cache hit, zero Worker CPU is consumed (served by Cloudflare CDN).
 *   • On a cache miss (first request for a tile), the Worker performs ~3 R2
 *     range reads to resolve the tile location via the PMTiles directory, then
 *     caches the result forever.
 *
 * R2 access:
 *   • Uses the R2 binding (server-side, no HTTP overhead).
 *   • The R2 bucket does NOT need to be public — the Worker accesses it
 *     directly via the binding defined in wrangler.toml.
 *
 * Architecture:
 *   Browser → Cloudflare Worker (public URL) → R2 (internal, via binding)
 *   ↑ first request: ~50-200 ms  (R2 reads + cache.put)
 *   ↑ repeat requests: ~5-20 ms  (Cache API hit, no Worker invocation)
 */

import { PMTiles } from "pmtiles";

// ---------------------------------------------------------------------------
// Env bindings (defined in wrangler.toml)
// ---------------------------------------------------------------------------

interface Env {
  R2_BUCKET: R2Bucket;
  PMTILES_KEY?: string; // optional override; default: "india-roads.pmtiles"
}

// ---------------------------------------------------------------------------
// R2 source — custom PMTiles source backed by the R2 bucket binding.
// The pmtiles library's PMTiles class accepts any object that implements
// getKey() and getBytes(offset, length).  We use the R2 binding so all
// reads are in-datacenter (no public HTTP round-trips).
// ---------------------------------------------------------------------------

class R2PMTilesSource {
  private readonly bucket: R2Bucket;
  private readonly key: string;

  constructor(bucket: R2Bucket, key: string) {
    this.bucket = bucket;
    this.key = key;
  }

  getKey(): string {
    // Prefix with "r2://" so the PMTiles internal cache uses a distinct key
    // space from HTTP sources and avoids cross-source cache collisions.
    return `r2://${this.key}`;
  }

  async getBytes(
    offset: number,
    length: number,
  ): Promise<{ data: ArrayBuffer }> {
    const obj = await this.bucket.get(this.key, {
      range: { offset, length },
    });
    if (!obj) {
      throw new Error(
        `PMTiles object "${this.key}" not found in R2 bucket. ` +
          `Run scripts/upload_r2.sh first.`,
      );
    }
    return { data: await obj.arrayBuffer() };
  }
}

// ---------------------------------------------------------------------------
// CORS headers
// ---------------------------------------------------------------------------

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
  "Access-Control-Allow-Headers": "Range, Cache-Control",
  "Access-Control-Max-Age": "86400",
} as const;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function emptyTileResponse(): Response {
  // Empty MVT tile (0 bytes) — returned when a tile is out of bounds or
  // the zoom level is outside the PMTiles min/max zoom range.
  return new Response(new Uint8Array(0), {
    status: 200,
    headers: {
      "Content-Type": "application/vnd.mapbox-vector-tile",
      "Cache-Control": "public, max-age=86400", // 1 day for empty tiles
      ...CORS_HEADERS,
    },
  });
}

// ---------------------------------------------------------------------------
// Worker entry point
// ---------------------------------------------------------------------------

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    // ── CORS preflight ──────────────────────────────────────────────────────
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method not allowed", {
        status: 405,
        headers: CORS_HEADERS,
      });
    }

    const url = new URL(request.url);

    // ── Route: /tiles/{z}/{x}/{y}.mvt ──────────────────────────────────────
    const match = url.pathname.match(/^\/tiles\/(\d+)\/(\d+)\/(\d+)\.mvt$/);
    if (!match) {
      return new Response("Not found — use /tiles/{z}/{x}/{y}.mvt", {
        status: 404,
        headers: CORS_HEADERS,
      });
    }

    const z = parseInt(match[1], 10);
    const x = parseInt(match[2], 10);
    const y = parseInt(match[3], 10);

    // ── Cloudflare Cache API ────────────────────────────────────────────────
    // Road geometry is immutable — once cached, a tile never needs to be
    // re-fetched from R2.  Cached responses count as zero Worker invocations,
    // so the free-plan 100 K req/day limit only applies to cold tiles.
    const cacheUrl = `${url.origin}/tiles/${z}/${x}/${y}.mvt`;
    const cacheKey = new Request(cacheUrl, { method: "GET" });
    const cache = caches.default;

    const cached = await cache.match(cacheKey);
    if (cached) {
      // Re-attach CORS headers in case the cached response is missing them
      const headers = new Headers(cached.headers);
      Object.entries(CORS_HEADERS).forEach(([k, v]) => headers.set(k, v));
      return new Response(cached.body, { status: cached.status, headers });
    }

    // ── Read tile from PMTiles on R2 ────────────────────────────────────────
    const key = (env.PMTILES_KEY ?? "india-roads.pmtiles").trim();
    const source = new R2PMTilesSource(env.R2_BUCKET, key);

    // PMTiles internally caches the header + directory between getZxy calls
    // within a single Worker invocation — it won't re-read the header for
    // each tile pixel (the SharedPromiseCache is worker-instance-local).
    const pmtiles = new PMTiles(source);

    let tileBytes: Uint8Array;
    try {
      const tile = await pmtiles.getZxy(z, x, y);
      tileBytes = tile ? new Uint8Array(tile.data) : new Uint8Array(0);
    } catch (err) {
      // Log for Cloudflare dashboard visibility; return empty tile rather
      // than a 500 so the map still renders the rest of the viewport.
      console.error(`[tile-server] z=${z} x=${x} y=${y} error:`, err);
      return emptyTileResponse();
    }

    if (tileBytes.length === 0) {
      // Tile is out of bounds or zoom level is outside the PMTiles range
      return emptyTileResponse();
    }

    const response = new Response(tileBytes, {
      status: 200,
      headers: {
        "Content-Type": "application/vnd.mapbox-vector-tile",
        // 1 year immutable cache — road geometry does not change
        "Cache-Control": "public, max-age=31536000, immutable",
        ...CORS_HEADERS,
      },
    });

    // Store in Cache API — subsequent requests for this tile cost zero
    // Worker CPU time and are served directly from Cloudflare's CDN.
    await cache.put(cacheKey, response.clone());

    return response;
  },
};
