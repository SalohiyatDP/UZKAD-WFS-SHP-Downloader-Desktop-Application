import { useCallback, useEffect, useMemo, useState } from "react";
import { Api, openProgressSocket } from "./api";
import { SessionBadge } from "./components/SessionBadge";
import { ProgressPanel } from "./components/ProgressPanel";
import type {
  ExportFormat,
  JobProgress,
  Layer,
  SessionStatus,
} from "./types";

const GRID_SIZES = [500, 1000, 2000];
const FORMATS: ExportFormat[] = ["shp", "gpkg", "geojson", "kml"];
const ALL_DISTRICTS = "Hammasi";

export default function App() {
  const [session, setSession] = useState<SessionStatus | null>(null);
  const [regions, setRegions] = useState<string[]>([]);
  const [districts, setDistricts] = useState<string[]>([]);
  const [layers, setLayers] = useState<Layer[]>([]);

  const [region, setRegion] = useState("");
  const [district, setDistrict] = useState(ALL_DISTRICTS);
  const [layer, setLayer] = useState("");
  const [gridSize, setGridSize] = useState(1000);
  const [formats, setFormats] = useState<ExportFormat[]>(["shp"]);
  const [maxWorkers, setMaxWorkers] = useState(12);

  const [estimate, setEstimate] = useState<number | null>(null);
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportResult, setExportResult] = useState<string[] | null>(null);

  // ---- Initial load -------------------------------------------------- //
  const refreshSession = useCallback(async () => {
    try {
      setSession(await Api.session());
    } catch (e) {
      setSession({
        authenticated: false,
        browser: null,
        cookie_count: 0,
        message: String(e),
      });
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const [r, l] = await Promise.all([Api.regions(), Api.layers()]);
        setRegions(r.regions);
        setLayers(l.layers);
        if (l.layers[0]) setLayer(l.layers[0].name);
        if (r.regions[0]) setRegion(r.regions[0]);
      } catch (e) {
        setError(`Backendga ulanib bo‘lmadi: ${e}`);
      }
      refreshSession();
    })();
  }, [refreshSession]);

  // ---- Districts depend on region ------------------------------------ //
  useEffect(() => {
    if (!region) return;
    (async () => {
      try {
        const d = await Api.districts(region);
        setDistricts(d.districts);
        setDistrict(ALL_DISTRICTS);
      } catch (e) {
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
        if (!cancelled) setEstimate(est.estimated_cells);
      } catch {
        if (!cancelled) setEstimate(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [region, gridSize]);

  const toggleFormat = (f: ExportFormat) => {
    setFormats((prev) =>
      prev.includes(f) ? prev.filter((x) => x !== f) : [...prev, f]
    );
  };

  const canStart = useMemo(
    () => !!region && !!layer && !busy && progress?.state !== "running",
    [region, layer, busy, progress]
  );

  // ---- Start download ------------------------------------------------ //
  const startDownload = async () => {
    setError(null);
    setExportResult(null);
    setBusy(true);
    try {
      const { job_id } = await Api.startDownload({
        region,
        district: district === ALL_DISTRICTS ? null : district,
        layer,
        grid_size: gridSize,
        formats,
        max_workers: maxWorkers,
        export_crs: "EPSG:4326",
      });
      setJobId(job_id);
      const ws = await openProgressSocket(
        job_id,
        (p) => setProgress(p),
        () => setBusy(false)
      );
      // Safety: also poll once on socket open failure.
      void ws;
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

  const pause = () => jobId && Api.pause(jobId);
  const resume = () => jobId && Api.resumeJob(jobId);
  const cancel = () => jobId && Api.cancel(jobId);

  const downloadFinished =
    progress?.state === "completed" || progress?.state === "cancelled";

  return (
    <div className="app">
      <header className="app-header">
        <h1>UZKAD SHP Downloader</h1>
        <SessionBadge session={session} onRefresh={refreshSession} />
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
            <select
              value={district}
              onChange={(e) => setDistrict(e.target.value)}
            >
              <option value={ALL_DISTRICTS}>{ALL_DISTRICTS}</option>
              {districts.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Qatlam">
            <select value={layer} onChange={(e) => setLayer(e.target.value)}>
              {layers.map((l) => (
                <option key={l.name} value={l.name}>
                  {l.title}
                </option>
              ))}
            </select>
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
              Taxminiy kataklar soni: <strong>{estimate.toLocaleString()}</strong>
            </p>
          )}

          <div className="actions">
            <button
              className="btn primary"
              onClick={startDownload}
              disabled={!canStart}
            >
              {busy ? "Yuklanmoqda..." : "EXPORT (yig‘ish)"}
            </button>
            {downloadFinished && (
              <button className="btn secondary" onClick={doExport}>
                Faylga eksport
              </button>
            )}
          </div>

          {exportResult && (
            <div className="alert success">
              <strong>Eksport tayyor:</strong>
              <ul>
                {exportResult.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
              <small>Fayllar “exports/” papkasida.</small>
            </div>
          )}
        </section>

        <ProgressPanel
          progress={progress}
          onPause={pause}
          onResume={resume}
          onCancel={cancel}
        />
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
