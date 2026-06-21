import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { JobProgress } from "../types";

interface Props {
  bbox: number[] | null; // [minLon, minLat, maxLon, maxLat]
  progress: JobProgress | null;
}

const COLS = 24; // visualization grid resolution

const STYLE_IDLE: L.PathOptions = {
  color: "#334155",
  weight: 1,
  fillColor: "#1e293b",
  fillOpacity: 0.12,
};
const STYLE_DONE: L.PathOptions = {
  color: "#16a34a",
  weight: 1,
  fillColor: "#22c55e",
  fillOpacity: 0.55,
};

/**
 * Live map view of the download. Shows the region as a coarse visualization
 * grid whose cells fill green in proportion to the job's progress, giving a
 * real-time "scan" of how the area is being collected.
 */
export function MapPanel({ bbox, progress }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const cellsRef = useRef<L.Rectangle[]>([]);

  // Init map once.
  useEffect(() => {
    if (mapRef.current || !containerRef.current) return;
    const map = L.map(containerRef.current, {
      attributionControl: true,
      zoomControl: true,
    }).setView([41.3, 69.2], 6);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "© OpenStreetMap",
    }).addTo(map);
    mapRef.current = map;
    // Ensure correct sizing after layout.
    setTimeout(() => map.invalidateSize(), 200);
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Rebuild the visualization grid when the region bbox changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !bbox || bbox.length !== 4) return;
    cellsRef.current.forEach((r) => r.remove());
    cellsRef.current = [];

    const [minLon, minLat, maxLon, maxLat] = bbox;
    const bounds = L.latLngBounds([minLat, minLon], [maxLat, maxLon]);
    map.fitBounds(bounds, { padding: [12, 12] });

    const aspect = (maxLat - minLat) / Math.max(1e-9, maxLon - minLon);
    const rows = Math.max(6, Math.min(40, Math.round(COLS * aspect)));
    const dLon = (maxLon - minLon) / COLS;
    const dLat = (maxLat - minLat) / rows;

    // South -> north, west -> east, so the fill sweeps naturally.
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < COLS; c++) {
        const y0 = minLat + r * dLat;
        const x0 = minLon + c * dLon;
        const rect = L.rectangle(
          [
            [y0, x0],
            [y0 + dLat, x0 + dLon],
          ],
          STYLE_IDLE
        ).addTo(map);
        cellsRef.current.push(rect);
      }
    }
    setTimeout(() => map.invalidateSize(), 100);
  }, [bbox?.[0], bbox?.[1], bbox?.[2], bbox?.[3]]);

  // Fill cells according to progress fraction.
  useEffect(() => {
    const cells = cellsRef.current;
    if (!cells.length) return;
    const total = progress?.total_cells ?? 0;
    const done = progress?.completed_cells ?? 0;
    const frac = total > 0 ? Math.min(1, done / total) : 0;
    const fill = Math.round(frac * cells.length);
    cells.forEach((rect, i) => {
      rect.setStyle(i < fill ? STYLE_DONE : STYLE_IDLE);
    });
  }, [progress?.completed_cells, progress?.total_cells]);

  return (
    <section className="map-panel">
      <div className="map-head">
        <h3>Xaritada jarayon</h3>
        {progress && (
          <span className="map-stat">
            {progress.completed_cells}/{progress.total_cells} katak ·{" "}
            {progress.features_found} obyekt
          </span>
        )}
      </div>
      <div ref={containerRef} className="map-canvas" />
      <p className="hint map-note">
        Yashil kataklar — yuklab olingan hudud (taxminiy vizualizatsiya).
      </p>
    </section>
  );
}
