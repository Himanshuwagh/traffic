import React, { useRef, useEffect, useState } from 'react';
import mapboxgl from 'mapbox-gl';
import 'mapbox-gl/dist/mapbox-gl.css';
import { type City } from '../data/mockData';
import { apiUrl } from '../lib/api';

// Placeholder or real token
mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN || 'pk.eyJ1IjoiZHVtbXl1c2VyIiwiYSI6ImNsdW1teXRva2VuIn0.dummy';

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

const TRAFFIC_SOURCE_ID = 'segments';
const TRAFFIC_SOURCE_LAYER = 'traffic';
const SIGNALS_SOURCE_ID = 'signals';
const SIGNALS_LAYER_ID = 'signals-layer';
const CLICK_LAYER_ID = 'segments-click-layer';
const VISUAL_LAYER_ID = 'segments-layer';

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
  ].join(',');
};

const formatSelectedLineWidth = (selectedSegmentId: string | null) => ([
  'interpolate', ['linear'], ['zoom'],
  10, 1.2,
  13, [
    'match',
    ['get', 'highway_type'],
    ['motorway', 'motorway_link', 'trunk', 'trunk_link'], 4,
    ['primary', 'primary_link'], 3,
    ['secondary', 'secondary_link'], 2.5,
    ['tertiary', 'tertiary_link'], 2,
    1.2,
  ],
  16, [
    'case',
    ['==', ['to-string', ['get', 'id']], selectedSegmentId || ''],
    8,
    4.5,
  ],
]) as mapboxgl.Expression;

const formatSelectedOpacity = (selectedSegmentId: string | null) => ([
  'case',
  ['==', ['to-string', ['get', 'id']], selectedSegmentId || ''],
  1.0,
  0.8,
]) as mapboxgl.Expression;

const removeTrafficLayersAndSource = (map: mapboxgl.Map) => {
  if (map.getLayer(CLICK_LAYER_ID)) map.removeLayer(CLICK_LAYER_ID);
  if (map.getLayer(VISUAL_LAYER_ID)) map.removeLayer(VISUAL_LAYER_ID);
  if (map.getSource(TRAFFIC_SOURCE_ID)) map.removeSource(TRAFFIC_SOURCE_ID);
};

const addTrafficLayers = (map: mapboxgl.Map, selectedSegmentId: string | null) => {
  map.addLayer({
    id: CLICK_LAYER_ID,
    type: 'line',
    source: TRAFFIC_SOURCE_ID,
    'source-layer': TRAFFIC_SOURCE_LAYER,
    layout: {
      'line-cap': 'round',
      'line-join': 'round',
    },
    paint: {
      'line-width': 20,
      'line-color': 'transparent',
    },
  });

  map.addLayer({
    id: VISUAL_LAYER_ID,
    type: 'line',
    source: TRAFFIC_SOURCE_ID,
    'source-layer': TRAFFIC_SOURCE_LAYER,
    layout: {
      'line-cap': 'round',
      'line-join': 'round',
    },
    paint: {
      'line-width': formatSelectedLineWidth(selectedSegmentId),
      'line-color': ['get', 'color'],
      'line-opacity': formatSelectedOpacity(selectedSegmentId),
    },
  });
};

const MapboxMap: React.FC<MapboxMapProps> = ({ city, cityId, selectedSegmentId, onSegmentClick, timeHour, selectedDate, onSummaryLoaded }) => {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<mapboxgl.Map | null>(null);
  const [mapLoaded, setMapLoaded] = useState(false);
  const lastSummaryRequestKey = useRef<string>('');

  // Initialize Map
  useEffect(() => {
    if (map.current) return; // initialize map only once
    if (!mapContainer.current) return;

    map.current = new mapboxgl.Map({
      container: mapContainer.current,
      style: 'mapbox://styles/mapbox/dark-v11',
      center: city.center,
      zoom: city.zoom,
      pitch: 0,
      bearing: 0,
    });

    map.current.on('load', () => {
      setMapLoaded(true);
      
      map.current?.addSource(SIGNALS_SOURCE_ID, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      });

      // Mapbox does not natively support emojis in text-fields, so we load an image
      map.current?.loadImage('https://upload.wikimedia.org/wikipedia/commons/thumb/d/d3/Emoji_u1f6a6.svg/128px-Emoji_u1f6a6.svg.png', (error, image) => {
        if (error) {
          console.error('Could not load traffic light image', error);
          return;
        }
        if (image && map.current && !map.current.hasImage('traffic-light-icon')) {
          map.current.addImage('traffic-light-icon', image);
        }
        
        if (map.current && !map.current.getLayer(SIGNALS_LAYER_ID)) {
          map.current.addLayer({
            id: SIGNALS_LAYER_ID,
            type: 'symbol',
            source: SIGNALS_SOURCE_ID,
            minzoom: 12.5, // Start showing when slightly zoomed in
            layout: {
              'icon-image': 'traffic-light-icon',
              'icon-size': 0.15, // Keep it small (15% of 128px)
              'icon-allow-overlap': false,
            }
          });
        }
      });

      map.current?.on('click', (e) => {
        if (!map.current || !map.current.getLayer(CLICK_LAYER_ID)) return;
        const features = map.current.queryRenderedFeatures(e.point, { layers: [CLICK_LAYER_ID] });
        const id = features[0]?.properties?.id;
        if (id) onSegmentClick(String(id));
      });

      map.current?.on('mousemove', (e) => {
        if (map.current) map.current.getCanvas().style.cursor = '';
        if (!map.current || !map.current.getLayer(CLICK_LAYER_ID)) return;
        const features = map.current.queryRenderedFeatures(e.point, { layers: [CLICK_LAYER_ID] });
        if (features.length > 0 && map.current) {
          map.current.getCanvas().style.cursor = 'pointer';
        }
      });
    });

    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []); // Empty dependency array means this runs once

  // Fly to new city when city prop changes
  useEffect(() => {
    if (map.current && mapLoaded) {
      map.current.flyTo({
        center: city.center,
        zoom: city.zoom,
        essential: true
      });
    }
  }, [city, mapLoaded]);

  // Switch the visible road network to vector tiles keyed by time and city.
  useEffect(() => {
    if (!map.current || !mapLoaded) return;
    const [year, month, day] = selectedDate.split('-').map(Number);
    const targetTime = new Date(year, month - 1, day, timeHour, 0, 0);
    const dateStr = targetTime.toISOString().split('.')[0];
    const tileTemplate = apiUrl(`/api/traffic/tiles/${dateStr}/{z}/{x}/{y}.mvt?city=${encodeURIComponent(cityId)}`);

    removeTrafficLayersAndSource(map.current);
    map.current.addSource(TRAFFIC_SOURCE_ID, {
      type: 'vector',
      tiles: [tileTemplate],
      minzoom: 0,
      maxzoom: 22,
    });
    addTrafficLayers(map.current, selectedSegmentId);
  }, [cityId, timeHour, selectedDate, mapLoaded]);

  // Keep the sidebar metrics lightweight by fetching summary-only data for the viewport.
  useEffect(() => {
    if (!map.current || !mapLoaded) return;

    const controller = new AbortController();
    let debounceTimer: number | undefined;

    const fetchTrafficSummary = async () => {
      try {
        const [year, month, day] = selectedDate.split('-').map(Number);
        const targetTime = new Date(year, month - 1, day, timeHour, 0, 0);
        const dateStr = targetTime.toISOString().split('.')[0];

        const bounds = map.current!.getBounds();
        if (!bounds) return;
        const bbox = paddedBounds(bounds);
        const zoom = map.current!.getZoom();
        const zoomBucket = Math.round(zoom * 10) / 10;
        const requestKey = `${cityId}|${dateStr}|${zoomBucket}|${bbox}`;
        if (requestKey === lastSummaryRequestKey.current) return;
        lastSummaryRequestKey.current = requestKey;

        const url = apiUrl(`/api/traffic/summary/${dateStr}?city=${encodeURIComponent(cityId)}&bbox=${encodeURIComponent(bbox)}&zoom=${encodeURIComponent(String(zoomBucket))}`);
        const response = await fetch(url, { signal: controller.signal });
        const summary = await response.json();
        onSummaryLoaded?.(summary.error ? null : summary);
      } catch (error) {
        if ((error as { name?: string })?.name === 'AbortError') return;
        console.error('Failed to fetch traffic summary:', error);
        onSummaryLoaded?.(null);
      }
    };

    const scheduleFetch = () => {
      if (debounceTimer) window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(fetchTrafficSummary, 150);
    };

    fetchTrafficSummary();
    map.current.on('moveend', scheduleFetch);

    return () => {
      map.current?.off('moveend', scheduleFetch);
      if (debounceTimer) window.clearTimeout(debounceTimer);
      controller.abort();
    };
  }, [cityId, timeHour, selectedDate, mapLoaded, onSummaryLoaded]);

  // Update selected opacity dynamically (no refetch needed).
  useEffect(() => {
    if (!map.current || !mapLoaded) return;
    if (map.current.getLayer(VISUAL_LAYER_ID)) {
      map.current.setPaintProperty(VISUAL_LAYER_ID, 'line-width', formatSelectedLineWidth(selectedSegmentId));
      map.current.setPaintProperty(VISUAL_LAYER_ID, 'line-opacity', formatSelectedOpacity(selectedSegmentId));
    }
  }, [selectedSegmentId, mapLoaded]);

  // Fetch signals when city changes
  useEffect(() => {
    if (!map.current || !mapLoaded) return;

    const fetchSignals = async () => {
      try {
        const response = await fetch(apiUrl(`/api/signals?city=${encodeURIComponent(cityId)}`));
        const data = await response.json();
        
        const source = map.current?.getSource(SIGNALS_SOURCE_ID) as mapboxgl.GeoJSONSource;
        if (source) {
          source.setData(data);
        }
      } catch (error) {
        console.error('Failed to fetch signals:', error);
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
