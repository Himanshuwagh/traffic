import React, { useRef, useEffect, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { type City } from "../data/mockData";
import { apiUrl } from "../lib/api";

// Placeholder or real token
mapboxgl.accessToken =
  import.meta.env.VITE_MAPBOX_TOKEN ||
  "pk.eyJ1IjoiZHVtbXl1c2VyIiwiYSI6ImNsdW1teXRva2VuIn0.dummy";

interface MapboxMapProps {
  city: City;
  cityId: string;
  selectedSegmentId: string | null;
  onSegmentClick: (id: string) => void;
  timeHour: number;
  selectedDate: string;
  onSummaryLoaded?: (summary: TrafficSummary | null) => void;
}

export type TrafficSummary = {
  avg_speed: number | null;
  active_segments: number;
  top_corridor_name: string | null;
  status: string;
  top_bottlenecks: Array<{
    id: number | string;
    name: string;
    highway_type: string;
    speed: number | null;
    travel_time: number | null;
    color: string;
    cfi: number;
  }>;
};

// ─── Source / Layer IDs ───────────────────────────────────────────────────────
// BASE layer: permanent road geometry, never removed, geometry-only tiles
const BASE_SOURCE_ID = "segments-base";
const BASE_SOURCE_LAYER = "segments"; // MVT layer name in /api/segments/tiles
const BASE_CLICK_LAYER = "segments-base-click";
const BASE_VISUAL_LAYER = "segments-base-visual";

// TRAFFIC layer: traffic-coloured overlay, tile URL swapped on time/date change
const TRAFFIC_SOURCE_ID = "segments-traffic";
const TRAFFIC_SOURCE_LAYER = "traffic"; // MVT layer name in /api/traffic/tiles
const TRAFFIC_VISUAL_LAYER = "segments-traffic-visual";

const SIGNALS_SOURCE_ID = "signals";
const SIGNALS_LAYER_ID = "signals-layer";

// ─── Helpers ─────────────────────────────────────────────────────────────────
const buildDateTimeKey = (selectedDate: string, timeHour: number) => {
  const [year, month, day] = selectedDate.split("-").map(Number);
  return new Date(year, month - 1, day, timeHour, 0, 0)
    .toISOString()
    .split(".")[0];
};

const roundCoord = (value: number) => Number(value.toFixed(4));

const paddedBounds = (bounds: mapboxgl.LngLatBounds) => {
  const west = bounds.getWest();
  const south = bounds.getSouth();
  const east = bounds.getEast();
  const north = bounds.getNorth();
  const lngPad = (east - west) * 0.35;
  const latPad = (north - south) * 0.35;
  return [
    roundCoord(west - lngPad),
    roundCoord(south - latPad),
    roundCoord(east + lngPad),
    roundCoord(north + latPad),
  ].join(",");
};

// Width expression shared by both the click-target and visual layers
const lineWidthExpression = (): mapboxgl.Expression => [
  "interpolate",
  ["linear"],
  ["zoom"],
  10,
  1.2,
  13,
  [
    "match",
    ["get", "highway_type"],
    ["motorway", "motorway_link", "trunk", "trunk_link"],
    4,
    ["primary", "primary_link"],
    3,
    ["secondary", "secondary_link"],
    2.5,
    ["tertiary", "tertiary_link"],
    2,
    1.2,
  ],
  16,
  4.5,
];

const selectedWidthExpression = (
  selectedSegmentId: string | null,
): mapboxgl.Expression => [
  "interpolate",
  ["linear"],
  ["zoom"],
  10,
  1.2,
  13,
  [
    "match",
    ["get", "highway_type"],
    ["motorway", "motorway_link", "trunk", "trunk_link"],
    4,
    ["primary", "primary_link"],
    3,
    ["secondary", "secondary_link"],
    2.5,
    ["tertiary", "tertiary_link"],
    2,
    1.2,
  ],
  16,
  [
    "case",
    ["==", ["to-string", ["get", "id"]], selectedSegmentId || ""],
    8,
    4.5,
  ],
];

const selectedOpacityExpression = (
  selectedSegmentId: string | null,
): mapboxgl.Expression => [
  "case",
  ["==", ["to-string", ["get", "id"]], selectedSegmentId || ""],
  1.0,
  0.8,
];

// ─── Component ────────────────────────────────────────────────────────────────
const MapboxMap: React.FC<MapboxMapProps> = ({
  city,
  cityId,
  selectedSegmentId,
  onSegmentClick,
  timeHour,
  selectedDate,
  onSummaryLoaded,
}) => {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<mapboxgl.Map | null>(null);
  const [mapLoaded, setMapLoaded] = useState(false);

  // Track which city's base tiles are already loaded so we never remove them
  const loadedBaseCityRef = useRef<string>("");
  const lastSummaryRequestKey = useRef<string>("");

  // ── 1. Initialize map once ──────────────────────────────────────────────────
  useEffect(() => {
    if (map.current) return;
    if (!mapContainer.current) return;

    map.current = new mapboxgl.Map({
      container: mapContainer.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: city.center,
      zoom: city.zoom,
      pitch: 0,
      bearing: 0,
    });

    map.current.on("load", () => {
      setMapLoaded(true);

      // Signals source (GeoJSON, static until city changes)
      map.current?.addSource(SIGNALS_SOURCE_ID, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      map.current?.loadImage(
        "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d3/Emoji_u1f6a6.svg/128px-Emoji_u1f6a6.svg.png",
        (error, image) => {
          if (error) {
            console.error("Could not load traffic light image", error);
            return;
          }
          if (
            image &&
            map.current &&
            !map.current.hasImage("traffic-light-icon")
          ) {
            map.current.addImage("traffic-light-icon", image);
          }
          if (map.current && !map.current.getLayer(SIGNALS_LAYER_ID)) {
            map.current.addLayer({
              id: SIGNALS_LAYER_ID,
              type: "symbol",
              source: SIGNALS_SOURCE_ID,
              minzoom: 12.5,
              layout: {
                "icon-image": "traffic-light-icon",
                "icon-size": 0.15,
                "icon-allow-overlap": false,
              },
            });
          }
        },
      );

      // Click & hover handlers wired once
      map.current?.on("click", (e) => {
        if (!map.current) return;
        // Try traffic layer first (has segment ids), then base layer
        for (const layerId of [BASE_CLICK_LAYER]) {
          if (!map.current.getLayer(layerId)) continue;
          const features = map.current.queryRenderedFeatures(e.point, {
            layers: [layerId],
          });
          const id = features[0]?.properties?.id;
          if (id) {
            onSegmentClick(String(id));
            return;
          }
        }
      });

      map.current?.on("mousemove", (e) => {
        if (!map.current) return;
        map.current.getCanvas().style.cursor = "";
        if (!map.current.getLayer(BASE_CLICK_LAYER)) return;
        const features = map.current.queryRenderedFeatures(e.point, {
          layers: [BASE_CLICK_LAYER],
        });
        if (features.length > 0)
          map.current.getCanvas().style.cursor = "pointer";
      });
    });

    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []); // runs once

  // ── 2. Fly to city when city prop changes ───────────────────────────────────
  useEffect(() => {
    if (map.current && mapLoaded) {
      map.current.flyTo({
        center: city.center,
        zoom: city.zoom,
        essential: true,
      });
    }
  }, [city, mapLoaded]);

  // ── 3. BASE layer – load/replace geometry tiles when city changes ───────────
  //    Road segments are NEVER removed — only replaced when the city switches.
  //    This ensures roads stay visible while traffic colors are refreshed.
  useEffect(() => {
    if (!map.current || !mapLoaded) return;

    const segmentTileUrl = apiUrl(
      `/api/segments/tiles/{z}/{x}/{y}.mvt?city=${encodeURIComponent(cityId)}`,
    );

    const existingSource = map.current.getSource(BASE_SOURCE_ID) as
      | (mapboxgl.VectorTileSource & { setTiles?: (tiles: string[]) => void })
      | undefined;

    if (!existingSource) {
      // First load: add source + layers
      map.current.addSource(BASE_SOURCE_ID, {
        type: "vector",
        tiles: [segmentTileUrl],
        minzoom: 0,
        maxzoom: 22,
      });

      // Invisible wide click-target
      map.current.addLayer({
        id: BASE_CLICK_LAYER,
        type: "line",
        source: BASE_SOURCE_ID,
        "source-layer": BASE_SOURCE_LAYER,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-width": 20, "line-color": "transparent" },
      });

      // Gray placeholder until traffic colors arrive
      map.current.addLayer({
        id: BASE_VISUAL_LAYER,
        type: "line",
        source: BASE_SOURCE_ID,
        "source-layer": BASE_SOURCE_LAYER,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-width": selectedWidthExpression(selectedSegmentId),
          "line-color": "#555566", // neutral gray placeholder
          "line-opacity": 0.6,
        },
      });
    } else if (loadedBaseCityRef.current !== cityId) {
      // City changed – swap the tile URL; layers stay in place
      if (typeof existingSource.setTiles === "function") {
        existingSource.setTiles([segmentTileUrl]);
      } else {
        // Rare fallback: remove and re-add source + layers
        if (map.current.getLayer(BASE_VISUAL_LAYER))
          map.current.removeLayer(BASE_VISUAL_LAYER);
        if (map.current.getLayer(BASE_CLICK_LAYER))
          map.current.removeLayer(BASE_CLICK_LAYER);
        map.current.removeSource(BASE_SOURCE_ID);

        map.current.addSource(BASE_SOURCE_ID, {
          type: "vector",
          tiles: [segmentTileUrl],
          minzoom: 0,
          maxzoom: 22,
        });
        map.current.addLayer({
          id: BASE_CLICK_LAYER,
          type: "line",
          source: BASE_SOURCE_ID,
          "source-layer": BASE_SOURCE_LAYER,
          layout: { "line-cap": "round", "line-join": "round" },
          paint: { "line-width": 20, "line-color": "transparent" },
        });
        map.current.addLayer({
          id: BASE_VISUAL_LAYER,
          type: "line",
          source: BASE_SOURCE_ID,
          "source-layer": BASE_SOURCE_LAYER,
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-width": selectedWidthExpression(selectedSegmentId),
            "line-color": "#555566",
            "line-opacity": 0.6,
          },
        });
      }
    }

    loadedBaseCityRef.current = cityId;
  }, [cityId, mapLoaded]);

  // ── 4. TRAFFIC layer – swap tile URL on time / date / city change ───────────
  //    Only the traffic color overlay changes; the base road geometry stays put.
  useEffect(() => {
    if (!map.current || !mapLoaded) return;

    const dateStr = buildDateTimeKey(selectedDate, timeHour);
    const trafficTileUrl = apiUrl(
      `/api/traffic/tiles/${dateStr}/{z}/{x}/{y}.mvt?city=${encodeURIComponent(cityId)}`,
    );

    const existingTrafficSource = map.current.getSource(TRAFFIC_SOURCE_ID) as
      | (mapboxgl.VectorTileSource & { setTiles?: (tiles: string[]) => void })
      | undefined;

    if (!existingTrafficSource) {
      map.current.addSource(TRAFFIC_SOURCE_ID, {
        type: "vector",
        tiles: [trafficTileUrl],
        minzoom: 0,
        maxzoom: 22,
      });

      map.current.addLayer({
        id: TRAFFIC_VISUAL_LAYER,
        type: "line",
        source: TRAFFIC_SOURCE_ID,
        "source-layer": TRAFFIC_SOURCE_LAYER,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-width": selectedWidthExpression(selectedSegmentId),
          "line-color": ["get", "color"],
          "line-opacity": selectedOpacityExpression(selectedSegmentId),
        },
      });
    } else {
      // Just swap the tile URL – layers remain, no flicker
      if (typeof existingTrafficSource.setTiles === "function") {
        existingTrafficSource.setTiles([trafficTileUrl]);
      } else {
        // Rare fallback
        if (map.current.getLayer(TRAFFIC_VISUAL_LAYER))
          map.current.removeLayer(TRAFFIC_VISUAL_LAYER);
        map.current.removeSource(TRAFFIC_SOURCE_ID);
        map.current.addSource(TRAFFIC_SOURCE_ID, {
          type: "vector",
          tiles: [trafficTileUrl],
          minzoom: 0,
          maxzoom: 22,
        });
        map.current.addLayer({
          id: TRAFFIC_VISUAL_LAYER,
          type: "line",
          source: TRAFFIC_SOURCE_ID,
          "source-layer": TRAFFIC_SOURCE_LAYER,
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-width": selectedWidthExpression(selectedSegmentId),
            "line-color": ["get", "color"],
            "line-opacity": selectedOpacityExpression(selectedSegmentId),
          },
        });
      }
    }
  }, [cityId, timeHour, selectedDate, mapLoaded]);

  // ── 5. Traffic summary fetch ────────────────────────────────────────────────
  useEffect(() => {
    if (!map.current || !mapLoaded) return;

    const controller = new AbortController();
    let debounceTimer: number | undefined;

    const fetchTrafficSummary = async () => {
      try {
        const dateStr = buildDateTimeKey(selectedDate, timeHour);
        const bounds = map.current!.getBounds();
        if (!bounds) return;
        const bbox = paddedBounds(bounds);
        const zoom = map.current!.getZoom();
        const zoomBucket = Math.round(zoom * 10) / 10;
        const requestKey = `${cityId}|${dateStr}|${zoomBucket}|${bbox}`;
        if (requestKey === lastSummaryRequestKey.current) return;
        lastSummaryRequestKey.current = requestKey;

        const url = apiUrl(
          `/api/traffic/summary/${dateStr}?city=${encodeURIComponent(cityId)}&bbox=${encodeURIComponent(bbox)}&zoom=${encodeURIComponent(String(zoomBucket))}`,
        );
        const response = await fetch(url, { signal: controller.signal });
        const summary = await response.json();
        onSummaryLoaded?.(summary.error ? null : summary);
      } catch (error) {
        if ((error as { name?: string })?.name === "AbortError") return;
        console.error("Failed to fetch traffic summary:", error);
        onSummaryLoaded?.(null);
      }
    };

    const scheduleFetch = () => {
      if (debounceTimer) window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(fetchTrafficSummary, 150);
    };

    fetchTrafficSummary();
    map.current.on("moveend", scheduleFetch);

    return () => {
      map.current?.off("moveend", scheduleFetch);
      if (debounceTimer) window.clearTimeout(debounceTimer);
      controller.abort();
    };
  }, [cityId, timeHour, selectedDate, mapLoaded, onSummaryLoaded]);

  // ── 6. Update selected segment highlight without refetching ────────────────
  useEffect(() => {
    if (!map.current || !mapLoaded) return;
    if (map.current.getLayer(BASE_VISUAL_LAYER)) {
      map.current.setPaintProperty(
        BASE_VISUAL_LAYER,
        "line-width",
        selectedWidthExpression(selectedSegmentId),
      );
    }
    if (map.current.getLayer(TRAFFIC_VISUAL_LAYER)) {
      map.current.setPaintProperty(
        TRAFFIC_VISUAL_LAYER,
        "line-width",
        selectedWidthExpression(selectedSegmentId),
      );
      map.current.setPaintProperty(
        TRAFFIC_VISUAL_LAYER,
        "line-opacity",
        selectedOpacityExpression(selectedSegmentId),
      );
    }
  }, [selectedSegmentId, mapLoaded]);

  // ── 7. Fetch signals when city changes ─────────────────────────────────────
  useEffect(() => {
    if (!map.current || !mapLoaded) return;

    const fetchSignals = async () => {
      try {
        const response = await fetch(
          apiUrl(`/api/signals?city=${encodeURIComponent(cityId)}`),
        );
        const data = await response.json();
        const source = map.current?.getSource(
          SIGNALS_SOURCE_ID,
        ) as mapboxgl.GeoJSONSource;
        if (source) source.setData(data);
      } catch (error) {
        console.error("Failed to fetch signals:", error);
      }
    };

    fetchSignals();
  }, [cityId, mapLoaded]);

  return (
    <div className="w-full h-full relative bg-[#0F1117] overflow-hidden">
      <div ref={mapContainer} className="w-full h-full" />
    </div>
  );
};

export default MapboxMap;
