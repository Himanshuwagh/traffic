/**
 * MapboxMap — production traffic overlay
 *
 * Architecture (why it works this way):
 *
 *  BASE source  (/api/segments/tiles)
 *   └─ "base-roads" layer  — permanent gray skeleton, never removed.
 *      Roads always visible even while traffic tiles are loading.
 *      Cached 1 hour server-side + browser-side.
 *
 *  TRAFFIC source  (/api/traffic/tiles/{datetime})
 *   ├─ "traffic-lines" layer  — coloured traffic overlay (LEFT JOIN → gray if no data).
 *   └─ "traffic-click" layer  — wide transparent hit-target for pointer events.
 *      On time / date / city change: source.setTiles([newUrl]).
 *      Mapbox keeps old tiles painted while new tiles load → zero flicker.
 *
 *  Total layers: 3  (down from 18 in the previous iteration).
 *  Total tile requests per viewport: 2× (down from 18× with per-class layers).
 *
 *  Progressive zoom reveal is driven by the TILE SERVER, not by layer minzoom:
 *   z 7-9   → motorway / motorway_link only
 *   z 9-11  → + trunk
 *   z 11-12.5 → + primary
 *   z 12.5-14 → + secondary
 *   z 14-15 → + tertiary
 *   z 15+   → + residential / service / unclassified
 *
 *  Source maxzoom: 14 → Mapbox overzooms z=14 tiles for z>14 camera positions.
 *  This eliminates tile requests at z 15-22 (no DB queries for those zooms).
 */

import React, { useRef, useEffect, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { type City } from "../data/mockData";
import { apiUrl } from "../lib/api";

mapboxgl.accessToken =
  import.meta.env.VITE_MAPBOX_TOKEN ||
  "pk.eyJ1IjoiZHVtbXl1c2VyIiwiYSI6ImNsdW1teXRva2VuIn0.dummy";

// ── Tile server URL (Cloudflare Worker) ──────────────────────────────────
// Set VITE_TILE_SERVER_URL in Vercel env vars to the deployed Worker URL
// (e.g. https://traffic-tile-server.YOUR_NAME.workers.dev).
// The Worker reads PMTiles from R2 and serves plain {z}/{x}/{y}.mvt URLs,
// which Mapbox GL JS handles natively — no custom protocol needed.
// When not set the map falls back to live MVT tiles from the Render API.
const TILE_SERVER_URL = (
  import.meta.env.VITE_TILE_SERVER_URL as string | undefined
)
  ?.trim()
  ?.replace(/\/+$/, "");

// ─── Types ────────────────────────────────────────────────────────────────────

interface MapboxMapProps {
  city: City;
  cityId: string;
  knownCities: City[];
  onViewportCityChange?: (cityId: string) => void;
  selectedSegmentId: string | null;
  onSegmentClick: (id: string) => void;
  timeHour: number;
  selectedDate: string;
  onSummaryLoaded?: (summary: TrafficSummary | null) => void;
}

export type TrafficSummary = {
  avg_speed: number | null;
  active_segments: number;
  active_hotspots?: number;
  worst_congestion_index?: number | null;
  top_corridor_name: string | null;
  status: string;
  top_bottlenecks: Array<{
    id: number | string;
    name: string;
    highway_type: string;
    speed: number | null;
    travel_time: number | null;
    congestion_index?: number | null;
    jam_level?: string | null;
    color: string;
    cfi: number;
  }>;
};

// ─── Layer / source IDs ───────────────────────────────────────────────────────

const BASE_SOURCE_ID = "seg-base";
const BASE_SOURCE_LAYER = "segments"; // MVT layer name from /api/segments/tiles
const BASE_LAYER_ID = "base-roads";

const TRAFFIC_SOURCE_ID = "seg-traffic";
const TRAFFIC_SOURCE_LAYER = "traffic"; // MVT layer name from /api/traffic/tiles
const TRAFFIC_LAYER_ID = "traffic-lines";
const TRAFFIC_CLICK_ID = "traffic-click";

const SIGNALS_SOURCE_ID = "signals";
const SIGNALS_LAYER_ID = "signals-layer";

// ─── Source settings ──────────────────────────────────────────────────────────
// maxzoom:14 → Mapbox overzooms z=14 tiles for camera z>14.
// This means we never request z=15-22 tiles → fewer DB queries, better UX.
// minzoom:6  → tiles are not requested below zoom 6 (backend returns empty anyway).
const SOURCE_MINZOOM = 0;
const SOURCE_MAXZOOM = 14;

// ─── Paint expressions ────────────────────────────────────────────────────────

/**
 * Line-width expression.
 * Interpolates by zoom level; within each zoom stop uses a match on highway_type
 * to size roads by class — exactly how Google Maps / Mapbox Traffic styles work.
 */
const LINE_WIDTH: mapboxgl.Expression = [
  "interpolate",
  ["linear"],
  ["zoom"],
  // z=6-7: only motorways, thin
  6,
  [
    "match",
    ["get", "highway_type"],
    ["motorway", "motorway_link"],
    1.2,
    ["trunk", "trunk_link"],
    0.8,
    0.5,
  ],
  // z=9-10
  9,
  [
    "match",
    ["get", "highway_type"],
    ["motorway", "motorway_link"],
    2.5,
    ["trunk", "trunk_link"],
    2.0,
    ["primary", "primary_link"],
    1.5,
    0.8,
  ],
  // z=11-12
  11,
  [
    "match",
    ["get", "highway_type"],
    ["motorway", "motorway_link"],
    3.5,
    ["trunk", "trunk_link"],
    2.8,
    ["primary", "primary_link"],
    2.2,
    ["secondary", "secondary_link"],
    1.6,
    ["tertiary", "tertiary_link"],
    1.2,
    0.8,
  ],
  // z=13-14 — detail view
  13,
  [
    "match",
    ["get", "highway_type"],
    ["motorway", "motorway_link"],
    6.0,
    ["trunk", "trunk_link"],
    5.0,
    ["primary", "primary_link"],
    4.0,
    ["secondary", "secondary_link"],
    3.0,
    ["tertiary", "tertiary_link"],
    2.2,
    ["unclassified", "residential", "living_street", "service"],
    1.6,
    1.2,
  ],
  // z=17+ — fully zoomed in
  17,
  [
    "match",
    ["get", "highway_type"],
    ["motorway", "motorway_link"],
    14.0,
    ["trunk", "trunk_link"],
    11.0,
    ["primary", "primary_link"],
    9.0,
    ["secondary", "secondary_link"],
    7.0,
    ["tertiary", "tertiary_link"],
    5.0,
    ["unclassified", "residential", "living_street", "service"],
    3.5,
    2.5,
  ],
];

/**
 * Same as LINE_WIDTH but the selected segment is 2.5× wider at high zoom.
 */
const buildWidthWithSelection = (
  selectedId: string | null,
): mapboxgl.Expression => {
  if (!selectedId) return LINE_WIDTH;
  return [
    "case",
    ["==", ["to-string", ["get", "id"]], selectedId],
    // Selected: multiply each stop width by 2.5 — reuse the same zoom structure
    [
      "interpolate",
      ["linear"],
      ["zoom"],
      6,
      [
        "match",
        ["get", "highway_type"],
        ["motorway", "motorway_link"],
        3.0,
        ["trunk", "trunk_link"],
        2.0,
        1.2,
      ],
      9,
      [
        "match",
        ["get", "highway_type"],
        ["motorway", "motorway_link"],
        6.0,
        ["trunk", "trunk_link"],
        5.0,
        ["primary", "primary_link"],
        3.5,
        2.0,
      ],
      13,
      [
        "match",
        ["get", "highway_type"],
        ["motorway", "motorway_link"],
        14.0,
        ["trunk", "trunk_link"],
        12.0,
        ["primary", "primary_link"],
        10.0,
        ["secondary", "secondary_link"],
        8.0,
        ["tertiary", "tertiary_link"],
        6.0,
        4.0,
      ],
      17,
      [
        "match",
        ["get", "highway_type"],
        ["motorway", "motorway_link"],
        20.0,
        ["trunk", "trunk_link"],
        16.0,
        ["primary", "primary_link"],
        14.0,
        ["secondary", "secondary_link"],
        12.0,
        ["tertiary", "tertiary_link"],
        10.0,
        7.0,
      ],
    ],
    // Not selected: normal width
    LINE_WIDTH,
  ];
};

const buildOpacity = (selectedId: string | null): mapboxgl.Expression =>
  selectedId
    ? ["case", ["==", ["to-string", ["get", "id"]], selectedId], 1.0, 0.85]
    : (0.85 as unknown as mapboxgl.Expression);

// ─── Helpers ─────────────────────────────────────────────────────────────────

const buildDateTimeKey = (date: string, hour: number): string => {
  const [y, m, d] = date.split("-").map(Number);
  return new Date(y, m - 1, d, hour, 0, 0).toISOString().split(".")[0];
};

const roundCoord = (v: number) => Number(v.toFixed(4));

const CITY_SWITCH_DISTANCE_KM = 60;

const distanceKm = (
  [lon1, lat1]: [number, number],
  [lon2, lat2]: [number, number],
): number => {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const earthRadiusKm = 6371;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) *
      Math.cos(toRad(lat2)) *
      Math.sin(dLon / 2) ** 2;
  return 2 * earthRadiusKm * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
};

const paddedBounds = (b: mapboxgl.LngLatBounds): string => {
  const [w, s, e, n] = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
  const lp = (e - w) * 0.35,
    bp = (n - s) * 0.35;
  return [
    roundCoord(w - lp),
    roundCoord(s - bp),
    roundCoord(e + lp),
    roundCoord(n + bp),
  ].join(",");
};

type VecSource = mapboxgl.VectorTileSource & {
  setTiles?: (t: string[]) => void;
};

/** Upsert a vector tile source. Returns true if the source was newly created. */
const upsertSource = (
  m: mapboxgl.Map,
  id: string,
  tileUrl: string,
): boolean => {
  const src = m.getSource(id) as VecSource | undefined;
  if (!src) {
    const sourceSpec: mapboxgl.VectorSourceSpecification = {
      type: "vector",
      tiles: [tileUrl],
      minzoom: SOURCE_MINZOOM,
      maxzoom: SOURCE_MAXZOOM,
    };

    m.addSource(id, sourceSpec);
    return true; // newly added — caller must add layers
  }
  if (typeof src.setTiles === "function") {
    src.setTiles([tileUrl]);
  }
  return false;
};

// ─── Component ────────────────────────────────────────────────────────────────

const MapboxMap: React.FC<MapboxMapProps> = ({
  city,
  cityId,
  knownCities,
  onViewportCityChange,
  selectedSegmentId,
  onSegmentClick,
  timeHour,
  selectedDate,
  onSummaryLoaded,
}) => {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<mapboxgl.Map | null>(null);
  const [mapLoaded, setMapLoaded] = useState(false);
  const lastSummaryKey = useRef<string>("");

  // ── 1. Init map once ────────────────────────────────────────────────────────
  useEffect(() => {
    if (map.current || !mapContainer.current) return;

    map.current = new mapboxgl.Map({
      container: mapContainer.current,
      style: "mapbox://styles/mapbox/outdoors-v12",
      center: city.center,
      zoom: city.zoom,
      pitch: 0,
      bearing: 0,
      // Improve render performance
      fadeDuration: 200,
      antialias: true,
    });

    map.current.on("load", () => {
      setMapLoaded(true);

      // Signals source
      map.current!.addSource(SIGNALS_SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      map.current!.loadImage(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d3/Emoji_u1f6a6.svg/128px-Emoji_u1f6a6.svg.png",
        (err, image) => {
          if (err || !map.current) return;
          if (image && !map.current.hasImage("traffic-light-icon"))
            map.current.addImage("traffic-light-icon", image);
          if (!map.current.getLayer(SIGNALS_LAYER_ID))
            map.current.addLayer({
              id: SIGNALS_LAYER_ID,
              type: "symbol",
              source: SIGNALS_SOURCE_ID,
              minzoom: 13,
              layout: {
                "icon-image": "traffic-light-icon",
                "icon-size": 0.15,
                "icon-allow-overlap": false,
              },
            });
        },
      );

      // Pointer events — use the click layer (wide transparent target)
      map.current!.on("click", (e) => {
        if (!map.current?.getLayer(TRAFFIC_CLICK_ID)) return;
        const features = map.current.queryRenderedFeatures(e.point, {
          layers: [TRAFFIC_CLICK_ID],
        });
        const id = features[0]?.properties?.id;
        if (id) onSegmentClick(String(id));
      });

      map.current!.on("mousemove", (e) => {
        if (!map.current) return;
        map.current.getCanvas().style.cursor = "";
        if (!map.current.getLayer(TRAFFIC_CLICK_ID)) return;
        const f = map.current.queryRenderedFeatures(e.point, {
          layers: [TRAFFIC_CLICK_ID],
        });
        if (f.length) map.current.getCanvas().style.cursor = "pointer";
      });
    });

    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── 2. Fly to city on city change ───────────────────────────────────────────
  useEffect(() => {
    if (map.current && mapLoaded)
      map.current.flyTo({
        center: city.center,
        zoom: city.zoom,
        essential: true,
      });
  }, [city, mapLoaded]);

  useEffect(() => {
    if (!map.current || !mapLoaded || !onViewportCityChange) return;

    const updateViewportCity = () => {
      const center = map.current?.getCenter();
      if (!center) return;

      const nearest = knownCities
        .map((candidate) => ({
          id: candidate.id,
          distance: distanceKm(
            [center.lng, center.lat],
            [candidate.center[0], candidate.center[1]],
          ),
        }))
        .sort((a, b) => a.distance - b.distance)[0];

      if (
        nearest &&
        nearest.id !== cityId &&
        nearest.distance <= CITY_SWITCH_DISTANCE_KM
      ) {
        onViewportCityChange(nearest.id);
      }
    };

    map.current.on("moveend", updateViewportCity);
    return () => {
      map.current?.off("moveend", updateViewportCity);
    };
  }, [cityId, knownCities, mapLoaded, onViewportCityChange]);

  // ── 3. BASE layer — road skeleton from Worker tile server or API fallback ───
  //
  // Worker path  (VITE_TILE_SERVER_URL is set):
  //   • Source added ONCE when the map loads — covers all of India.
  //   • Worker reads PMTiles from R2 and serves {z}/{x}/{y}.mvt URLs.
  //   • Zero Render/Supabase involvement for the road skeleton.
  //
  // Fallback path (VITE_TILE_SERVER_URL is NOT set):
  //   • Behaves exactly as before — live MVT tiles from /api/segments/tiles.
  //   • upsertSource / setTiles() called on every city change.
  useEffect(() => {
    if (!map.current || !mapLoaded) return;

    const existingSrc = map.current.getSource(BASE_SOURCE_ID) as
      | VecSource
      | undefined;

    if (TILE_SERVER_URL) {
      // ── Cloudflare Worker tile server: wire up once, covers all India ──────
      // Source already exists → nothing to do on city change
      if (existingSrc) return;

      map.current.addSource(BASE_SOURCE_ID, {
        type: "vector",
        // Worker serves standard {z}/{x}/{y}.mvt URLs — Mapbox GL JS handles
        // these natively. No custom protocol or library changes needed.
        tiles: [`${TILE_SERVER_URL}/tiles/{z}/{x}/{y}.mvt`],
        minzoom: SOURCE_MINZOOM,
        maxzoom: SOURCE_MAXZOOM,
      });
    } else {
      // ── Fallback: live MVT tiles from Render API (original behaviour) ───────
      const fallbackUrl = apiUrl(
        `/api/segments/tiles/{z}/{x}/{y}.mvt?city=${encodeURIComponent(cityId)}`,
      );
      if (existingSrc) {
        // City changed — swap the tile URL; source + layer already exist
        if (typeof existingSrc.setTiles === "function")
          existingSrc.setTiles([fallbackUrl]);
        return;
      }
      map.current.addSource(BASE_SOURCE_ID, {
        type: "vector",
        tiles: [fallbackUrl],
        minzoom: SOURCE_MINZOOM,
        maxzoom: SOURCE_MAXZOOM,
      });
    }

    // Reached only when the source was just created (both paths)
    map.current.addLayer({
      id: BASE_LAYER_ID,
      type: "line",
      source: BASE_SOURCE_ID,
      // "segments" must match tippecanoe --layer=segments in generate_pmtiles.sh
      "source-layer": BASE_SOURCE_LAYER,
      minzoom: 0,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": "#8a8a9a",
        "line-width": LINE_WIDTH,
        "line-opacity": 0.9,
      },
    });
  }, [cityId, mapLoaded]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── 4. TRAFFIC layer — coloured overlay, updated on time/date/city change ───
  // setTiles() is called on every change; Mapbox keeps the old tiles painted
  // while new tiles are fetching → zero blank canvas.
  useEffect(() => {
    if (!map.current || !mapLoaded) return;

    const dateStr = buildDateTimeKey(selectedDate, timeHour);
    const tileUrl = apiUrl(
      `/api/traffic/tiles/${dateStr}/{z}/{x}/{y}.mvt?city=${encodeURIComponent(cityId)}`,
    );

    const isNew = upsertSource(map.current, TRAFFIC_SOURCE_ID, tileUrl);

    if (isNew) {
      // Wide transparent click target — must be added BEFORE the visual layer
      // so it sits on top in the hit-test stack.
      map.current.addLayer({
        id: TRAFFIC_CLICK_ID,
        type: "line",
        source: TRAFFIC_SOURCE_ID,
        "source-layer": TRAFFIC_SOURCE_LAYER,
        minzoom: 0,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": "transparent",
          "line-width": 20,
        },
      });

      // Visual traffic colour layer
      map.current.addLayer(
        {
          id: TRAFFIC_LAYER_ID,
          type: "line",
          source: TRAFFIC_SOURCE_ID,
          "source-layer": TRAFFIC_SOURCE_LAYER,
          minzoom: 0,
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": ["get", "color"],
            "line-width": buildWidthWithSelection(selectedSegmentId),
            "line-opacity": buildOpacity(selectedSegmentId),
          },
        },
        // Insert below the click layer so click layer always sits on top
        TRAFFIC_CLICK_ID,
      );
    }
  }, [cityId, timeHour, selectedDate, mapLoaded]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── 5. Selection highlight — no tile refetch needed ─────────────────────────
  useEffect(() => {
    if (!map.current || !mapLoaded) return;
    if (map.current.getLayer(TRAFFIC_LAYER_ID)) {
      map.current.setPaintProperty(
        TRAFFIC_LAYER_ID,
        "line-width",
        buildWidthWithSelection(selectedSegmentId),
      );
      map.current.setPaintProperty(
        TRAFFIC_LAYER_ID,
        "line-opacity",
        buildOpacity(selectedSegmentId),
      );
    }
  }, [selectedSegmentId, mapLoaded]);

  // ── 6. Traffic summary ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!map.current || !mapLoaded) return;
    const ctrl = new AbortController();
    let timer: number | undefined;

    const fetch_ = async () => {
      try {
        const dateStr = buildDateTimeKey(selectedDate, timeHour);
        const bounds = map.current!.getBounds();
        if (!bounds) return;
        const bbox = paddedBounds(bounds);
        const zoom = Math.round(map.current!.getZoom() * 10) / 10;
        const key = `${cityId}|${dateStr}|${zoom}|${bbox}`;
        if (key === lastSummaryKey.current) return;
        lastSummaryKey.current = key;

        const url = apiUrl(
          `/api/traffic/summary/${dateStr}?city=${encodeURIComponent(cityId)}&bbox=${encodeURIComponent(bbox)}&zoom=${zoom}`,
        );
        const res = await fetch(url, { signal: ctrl.signal });
        const summary = await res.json();
        onSummaryLoaded?.(summary.error ? null : summary);
      } catch (e) {
        if ((e as { name?: string })?.name === "AbortError") return;
        onSummaryLoaded?.(null);
      }
    };

    const schedule = () => {
      clearTimeout(timer);
      timer = window.setTimeout(fetch_, 200);
    };

    fetch_();
    map.current.on("moveend", schedule);
    return () => {
      map.current?.off("moveend", schedule);
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [cityId, timeHour, selectedDate, mapLoaded, onSummaryLoaded]);

  // ── 7. Signals ───────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!map.current || !mapLoaded) return;
    fetch(apiUrl(`/api/signals?city=${encodeURIComponent(cityId)}`))
      .then((r) => r.json())
      .then((d) => {
        const src = map.current?.getSource(
          SIGNALS_SOURCE_ID,
        ) as mapboxgl.GeoJSONSource;
        if (src) src.setData(d);
      })
      .catch(() => {});
  }, [cityId, mapLoaded]);

  return (
    <div className="w-full h-full relative bg-[#f1ede0] overflow-hidden">
      <div ref={mapContainer} className="w-full h-full" />
    </div>
  );
};

export default MapboxMap;
