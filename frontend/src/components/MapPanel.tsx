import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { Api } from "../api";
import type { JobProgress } from "../types";

interface Props {
  region: string;
  district: string | null;
  bbox: number[] | null; // [minLon, minLat, maxLon, maxLat] fallback
  progress: JobProgress | null;
}

const RUNNING_STATES = ["running", "paused"];

/**
 * Live map of the download: draws the actual region/district boundary polygon
 * and plots the real collected features (sampled centroids) as they are stored,
 * so the map reflects the true area and progress.
 */
export function MapPanel({ region, district, bbox, progress }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const rendererRef = useRef<L.Canvas | null>(null);
  const boundaryRef = useRef<L.Layer | null>(null);
  const pointsRef = useRef<L.LayerGroup | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);


  // Init map once.
  useEffect(() => {
    if (mapRef.current || !containerRef.current) return;
    const map = L.map(containerRef.current, { zoomControl: true }).setView(
      [41.3, 69.2],
      6
    );
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "© OpenStreetMap",
    }).addTo(map);
    rendererRef.current = L.canvas({ padding: 0.5 });
    pointsRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    setTimeout(() => map.invalidateSize(), 200);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Draw the region/district boundary when selection changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !region) return;
    let cancelled = false;
    pointsRef.current?.clearLayers();

    (async () => {
      try {
        const { geometry } = await Api.boundary(region, district ?? undefined);
        if (cancelled || !map) return;
        if (boundaryRef.current) {
          map.removeLayer(boundaryRef.current);
          boundaryRef.current = null;
        }
        if (geometry) {
          const layer = L.geoJSON(geometry as GeoJSON.GeoJsonObject, {
            style: { color: "#38bdf8", weight: 2, fill: false },
          }).addTo(map);
          boundaryRef.current = layer;
          map.fitBounds(layer.getBounds(), { padding: [12, 12] });
          return;
        }
      } catch {
        /* fall through to bbox */
      }
      if (!cancelled && bbox && bbox.length === 4) {
        const rect = L.rectangle(
          [
            [bbox[1], bbox[0]],
            [bbox[3], bbox[2]],
          ],
          { color: "#38bdf8", weight: 1, fill: false }
        ).addTo(map);
        boundaryRef.current = rect;
        map.fitBounds(rect.getBounds(), { padding: [12, 12] });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [region, district, bbox?.[0], bbox?.[1], bbox?.[2], bbox?.[3]]);


  // Plot the real collected features (sampled) live while a job runs.
  useEffect(() => {
    const state = progress?.state;
    const fetchSample = async () => {
      try {
        const { points } = await Api.featuresSample(
          region || undefined,
          district ?? undefined,
          5000
        );
        const group = pointsRef.current;
        if (!group) return;
        group.clearLayers();
        for (const [lon, lat] of points) {
          L.circleMarker([lat, lon], {
            renderer: rendererRef.current ?? undefined,
            radius: 2,
            color: "#22c55e",
            weight: 0,
            fillColor: "#22c55e",
            fillOpacity: 0.7,
          }).addTo(group);
        }
      } catch {
        /* ignore */
      }
    };

    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (state && RUNNING_STATES.includes(state)) {
      fetchSample();
      pollRef.current = setInterval(fetchSample, 2500);
    } else if (state === "completed") {
      fetchSample();
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [progress?.state, region, district]);

  return (
    <section className="map-panel">
      <div className="map-head">
        <h3>Xaritada jarayon</h3>
        {progress && (
          <span className="map-stat">
            {progress.completed_cells}/{progress.total_cells} katak ·{" "}
            {progress.features_stored} obyekt
          </span>
        )}
      </div>
      <div ref={containerRef} className="map-canvas" />
      <p className="hint map-note">
        Ko‘k chiziq — tanlangan hudud chegarasi; yashil nuqtalar — yuklab
        olingan obyektlar (jonli, namuna).
      </p>
    </section>
  );
}
