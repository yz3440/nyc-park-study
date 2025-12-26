'use client';

import mapboxgl from 'mapbox-gl';
import 'mapbox-gl/dist/mapbox-gl.css';
import { useEffect, useRef, useCallback } from 'react';

import { env } from '~/env';

// GeoJSON geometry type
interface GeoJSONGeometry {
  type: string;
  coordinates: number[] | number[][] | number[][][] | number[][][][];
}

interface Park {
  id: number;
  geometry: GeoJSONGeometry;
  centroidLng: number;
  centroidLat: number;
}

interface MapViewProps {
  park: Park | null;
  onMapReady?: () => void;
}

// Helper to calculate bounds from geometry
function getBounds(
  geometry: GeoJSONGeometry
): [[number, number], [number, number]] | null {
  const coords: number[][] = [];

  function extractCoords(arr: unknown): void {
    if (Array.isArray(arr)) {
      if (typeof arr[0] === 'number' && typeof arr[1] === 'number') {
        coords.push([arr[0] as number, arr[1] as number]);
      } else {
        for (const item of arr) {
          extractCoords(item);
        }
      }
    }
  }

  extractCoords(geometry.coordinates);

  if (coords.length === 0) return null;

  let minLng = Infinity,
    maxLng = -Infinity;
  let minLat = Infinity,
    maxLat = -Infinity;

  for (const [lng, lat] of coords) {
    if (lng! < minLng) minLng = lng!;
    if (lng! > maxLng) maxLng = lng!;
    if (lat! < minLat) minLat = lat!;
    if (lat! > maxLat) maxLat = lat!;
  }

  return [
    [minLng, minLat],
    [maxLng, maxLat],
  ];
}

export function MapView({ park, onMapReady }: MapViewProps) {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<mapboxgl.Map | null>(null);
  const isMapReady = useRef(false);

  // Initialize map once
  useEffect(() => {
    if (!mapContainer.current || map.current) return;

    mapboxgl.accessToken = env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN;

    const newMap = new mapboxgl.Map({
      container: mapContainer.current,
      style: 'mapbox://styles/mapbox/satellite-v9',
      center: [-73.95, 40.75], // NYC default
      zoom: 15,
      interactive: false,
      attributionControl: true,
    });

    newMap.on('load', () => {
      // Add park polygon source (empty initially)
      newMap.addSource('park-polygon', {
        type: 'geojson',
        data: {
          type: 'Feature',
          geometry: { type: 'Polygon', coordinates: [] },
          properties: {},
        },
      });

      // Add fill layer
      newMap.addLayer({
        id: 'park-fill',
        type: 'fill',
        source: 'park-polygon',
        paint: {
          'fill-color': '#ffffff',
          'fill-opacity': 0.4,
        },
      });

      // Add outline layer
      newMap.addLayer({
        id: 'park-outline',
        type: 'line',
        source: 'park-polygon',
        paint: {
          'line-color': '#ffffff',
          'line-width': 3,
        },
      });

      isMapReady.current = true;
      onMapReady?.();
    });

    map.current = newMap;

    return () => {
      newMap.remove();
      map.current = null;
      isMapReady.current = false;
    };
  }, [onMapReady]);

  // Update map when park changes
  const updatePark = useCallback((newPark: Park) => {
    const currentMap = map.current;
    if (!currentMap || !isMapReady.current) return;

    // Update polygon source
    const source = currentMap.getSource(
      'park-polygon'
    ) as mapboxgl.GeoJSONSource;
    if (source) {
      source.setData({
        type: 'Feature',
        geometry: newPark.geometry as GeoJSON.Geometry,
        properties: {},
      });
    }

    // Fly to new location with bounds
    const bounds = getBounds(newPark.geometry);
    if (bounds) {
      currentMap.fitBounds(bounds, {
        padding: 80,
        maxZoom: 18,
        duration: 300, // Faster transition
        essential: true,
      });
    } else {
      currentMap.flyTo({
        center: [newPark.centroidLng, newPark.centroidLat],
        zoom: 17,
        duration: 300, // Faster transition
        essential: true,
      });
    }
  }, []);

  // Effect to update park when it changes
  useEffect(() => {
    if (park && isMapReady.current) {
      updatePark(park);
    }
  }, [park, updatePark]);

  return <div ref={mapContainer} className='absolute inset-0 h-full w-full' />;
}
