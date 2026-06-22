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

const BOUNDARY_STYLE: L.PathOptions = {
  color: "#38bdf8",
  weight: 2.5,
  fillColor: "#38bdf8",
  fillOpacity: 0.08,
};

/**
 * Live map of the download: dark basemap, the actual region/district boundary
 * polygon (filled), and the real collected features plotted as they are stored.
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
    const map = L.map(containerRef.current, {
      zoomControl: true,
      attributionControl: true,
    }).setView([41.3, 69.2], 6);
    L.tileLayer(
      "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
      { maxZoom: 19, subdomains: "abcd", attribution: "© OpenStreetMap, © CARTO" }
    ).addTo(map);
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

  // Draw the region/district boundary when the selection changes.
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
            style: BOUNDARY_STYLE,
          }).addTo(map);
          boundaryRef.current = layer;
          map.fitBounds(layer.getBounds(), { padding: [16, 16] });
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
          BOUNDARY_STYLE
        ).addTo(map);
        boundaryRef.current = rect;
        map.fitBounds(rect.getBounds(), { padding: [16, 16] });
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
          6000
        );
        const group = pointsRef.current;
        if (!group) return;
        group.clearLayers();
        for (const [lon, lat] of points) {
          L.circleMarker([lat, lon], {
            renderer: rendererRef.current ?? undefined,
            radius: 3,
            color: "#0b3b1e",
            weight: 0.5,
            fillColor: "#22c55e",
            fillOpacity: 0.85,
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

  const pct =
    progress && progress.total_cells > 0
      ? Math.min(100, Math.round((progress.completed_cells / progress.total_cells) * 100))
      : 0;

  return (
    <section className="map-panel">
      <div className="map-head">
        <h3>Xaritada jarayon</h3>
        {progress && (
          <span className="map-stat">
            {progress.features_stored.toLocaleString()} obyekt
          </span>
        )}
      </div>
      <div className="map-wrap">
        <div ref={containerRef} className="map-canvas" />
        {progress && progress.state !== "idle" && (
          <div className="map-badge">{pct}% · {progress.state}</div>
        )}
        <div className="map-legend">
          <span><i className="lg-line" /> Hudud chegarasi</span>
          <span><i className="lg-dot" /> Yuklab olingan obyektlar</span>
        </div>
      </div>
    </section>
  );
}
