import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Api, exportFileUrl, subscribeJob } from "./api";
import { ProgressPanel } from "./components/ProgressPanel";
import { MapPanel } from "./components/MapPanel";
import type { AppConfig, ExportFormat, JobProgress, Layer } from "./types";

const GRID_SIZES = [500, 1000, 2000];
const FORMATS: ExportFormat[] = ["shp", "gpkg", "geojson", "kml"];
const ALL_DISTRICTS = "Hammasi";

export default function App() {
  const [appConfig, setAppConfig] = useState<AppConfig | null>(null);
  const [regions, setRegions] = useState<string[]>([]);
  const [districts, setDistricts] = useState<string[]>([]);
  const [layers, setLayers] = useState<Layer[]>([]);

  const [region, setRegion] = useState("");
  const [district, setDistrict] = useState(ALL_DISTRICTS);
  const [selectedLayers, setSelectedLayers] = useState<string[]>([]);
  const [gridSize, setGridSize] = useState(1000);
  const [formats, setFormats] = useState<ExportFormat[]>(["shp"]);
  const [maxWorkers, setMaxWorkers] = useState(12);

  const [estimate, setEstimate] = useState<number | null>(null);
  const [regionBbox, setRegionBbox] = useState<number[] | null>(null);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportResult, setExportResult] = useState<string[] | null>(null);

  const unsubscribeRef = useRef<(() => void) | null>(null);

  // ---- Initial load -------------------------------------------------- //
  useEffect(() => {
    (async () => {
      try {
        const [r, l, cfg] = await Promise.all([
          Api.regions(),
          Api.layers(),
          Api.config().catch(() => null),
        ]);
        setRegions(r.regions);
        setLayers(l.layers);
        if (cfg) setAppConfig(cfg);
        if (l.layers[0]) setSelectedLayers([l.layers[0].name]);
        if (r.regions[0]) setRegion(r.regions[0]);
      } catch (e) {
        setError(`Backendga ulanib bo‘lmadi: ${e}`);
      }
    })();
    return () => unsubscribeRef.current?.();
  }, []);

  // ---- Districts depend on region ------------------------------------ //
  useEffect(() => {
    if (!region) return;
    (async () => {
      try {
        const d = await Api.districts(region);
        setDistricts(d.districts);
        setDistrict(ALL_DISTRICTS);
      } catch {
        setDistricts([]);
      }
    })();
  }, [region]);

  // ---- Estimate cells ------------------------------------------------ //
  useEffect(() => {
    if (!region) return;
    let cancelled = false;
    (async () => {
      try {
        const est = await Api.estimate(region, gridSize);
        if (!cancelled) {
          setEstimate(est.estimated_cells);
          setRegionBbox(est.bbox_4326 ?? null);
        }
      } catch {
        if (!cancelled) setEstimate(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [region, gridSize]);

  const toggleFormat = (f: ExportFormat) =>
    setFormats((prev) =>
      prev.includes(f) ? prev.filter((x) => x !== f) : [...prev, f]
    );

  const toggleLayer = (name: string) =>
    setSelectedLayers((prev) =>
      prev.includes(name) ? prev.filter((x) => x !== name) : [...prev, name]
    );

  const canStart = useMemo(
    () =>
      !!region &&
      selectedLayers.length > 0 &&
      formats.length > 0 &&
      !busy &&
      progress?.state !== "running",
    [region, selectedLayers, formats, busy, progress]
  );

  const track = useCallback((id: string) => {
    unsubscribeRef.current?.();
    setProgress(null);
    setExportResult(null);
    subscribeJob(
      id,
      (p) => setProgress(p),
      (final) => {
        setBusy(false);
        if (final?.export_files?.length) setExportResult(final.export_files);
      }
    ).then((unsub) => {
      unsubscribeRef.current = unsub;
    });
  }, []);

  const startDownload = async () => {
    setError(null);
    setExportResult(null);
    setBusy(true);
    try {
      const { job_id } = await Api.startDownload({
        region,
        district: district === ALL_DISTRICTS ? null : district,
        layers: selectedLayers,
        grid_size: gridSize,
        formats,
        max_workers: maxWorkers,
        export_crs: "EPSG:4326",
        auto_export: true,
      });
      setJobId(job_id);
      track(job_id);
    } catch (e) {
      setError(String(e));
      setBusy(false);
    }
  };

  const doExport = async () => {
    setError(null);
    try {
      const res = await Api.exportData(
        formats,
        region,
        district === ALL_DISTRICTS ? undefined : district
      );
      setExportResult(res.files);
    } catch (e) {
      setError(String(e));
    }
  };

  const openFile = async (filename: string) => {
    const url = await exportFileUrl(filename);
    if (window.uzkad?.openExternal) window.uzkad.openExternal(url);
    else window.open(url, "_blank");
  };

  const openFolder = async () => {
    if (appConfig?.exports_dir && window.uzkad?.openPath) {
      await window.uzkad.openPath(appConfig.exports_dir);
    }
  };

  const pause = () => jobId && Api.pause(jobId);
  const resume = () => jobId && Api.resumeJob(jobId);
  const cancel = () => jobId && Api.cancel(jobId);

  const downloadFinished =
    progress?.state === "completed" || progress?.state === "cancelled";

  return (
    <div className="app">
      <header className="app-header">
        <h1>UZKAD SHP Downloader</h1>
        <span className="source-badge">Manba: NGIS (ochiq)</span>
      </header>

      {error && <div className="alert error">{error}</div>}

      <main className="layout">
        <section className="form-card">
          <Field label="Viloyat">
            <select value={region} onChange={(e) => setRegion(e.target.value)}>
              {regions.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Tuman">
            <select value={district} onChange={(e) => setDistrict(e.target.value)}>
              <option value={ALL_DISTRICTS}>{ALL_DISTRICTS}</option>
              {districts.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Qatlamlar (bir nechtasini tanlash mumkin)">
            <div className="checkbox-list">
              {layers.map((l) => (
                <label key={l.name} className="checkbox-row">
                  <input
                    type="checkbox"
                    checked={selectedLayers.includes(l.name)}
                    onChange={() => toggleLayer(l.name)}
                  />
                  <span>{l.title}</span>
                </label>
              ))}
            </div>
          </Field>

          <Field label="Grid o‘lchami (m)">
            <div className="chip-row">
              {GRID_SIZES.map((g) => (
                <button
                  key={g}
                  className={`chip ${gridSize === g ? "active" : ""}`}
                  onClick={() => setGridSize(g)}
                  type="button"
                >
                  {g}
                </button>
              ))}
            </div>
          </Field>

          <Field label="Format">
            <div className="chip-row">
              {FORMATS.map((f) => (
                <button
                  key={f}
                  className={`chip ${formats.includes(f) ? "active" : ""}`}
                  onClick={() => toggleFormat(f)}
                  type="button"
                >
                  {f.toUpperCase()}
                </button>
              ))}
            </div>
          </Field>

          <Field label={`Parallel so‘rovlar: ${maxWorkers}`}>
            <input
              type="range"
              min={1}
              max={16}
              value={maxWorkers}
              onChange={(e) => setMaxWorkers(Number(e.target.value))}
            />
          </Field>

          {estimate != null && (
            <p className="hint">
              Taxminiy kataklar soni (har qatlam uchun):{" "}
              <strong>{estimate.toLocaleString()}</strong>
              {selectedLayers.length > 1 && (
                <> × {selectedLayers.length} qatlam</>
              )}
              {estimate > 5000 && (
                <span className="warn-text"> — katta hudud, uzoq davom etishi mumkin.</span>
              )}
            </p>
          )}

          <div className="actions">
            <button className="btn primary" onClick={startDownload} disabled={!canStart}>
              {busy ? "Yuklanmoqda..." : "EXPORT"}
            </button>
            {downloadFinished && (
              <button className="btn secondary" onClick={doExport}>
                Qayta eksport
              </button>
            )}
          </div>

          {exportResult && (
            <div className="alert success">
              <strong>Eksport tayyor:</strong>
              {exportResult.length === 0 ? (
                <p className="hint">Tanlangan hududda obyekt topilmadi.</p>
              ) : (
                <ul>
                  {exportResult.map((f) => (
                    <li key={f}>
                      <button className="link-btn" onClick={() => openFile(f)}>
                        {f}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {appConfig?.exports_dir && window.uzkad?.openPath && (
                <button className="btn secondary small" onClick={openFolder}>
                  Papkani ochish
                </button>
              )}
            </div>
          )}
        </section>

        <div className="right-col">
          <ProgressPanel
            progress={progress}
            onPause={pause}
            onResume={resume}
            onCancel={cancel}
          />
          <MapPanel bbox={regionBbox} progress={progress} />
        </div>
      </main>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
    </label>
  );
}
