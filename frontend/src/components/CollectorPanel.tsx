import { useState } from "react";
import { Api, exportFileUrl } from "../api";
import type { ExportFormat } from "../types";

interface Props {
  region: string;
  district: string | null;
  gridSize: number;
  layer: string;
  formats: ExportFormat[];
}

/**
 * Browser-collector workflow (works around the WFS 403 by harvesting from the
 * already-authenticated map page):
 *   1) generate a bookmarklet / console script for the chosen region,
 *   2) run it on the UZKAD map page -> it downloads a GeoJSON file,
 *   3) import that file here -> the app stores + de-duplicates it,
 *   4) export to SHP / GPKG / GeoJSON / KML.
 */
export function CollectorPanel({
  region,
  district,
  gridSize,
  layer,
  formats,
}: Props) {
  const [script, setScript] = useState("");
  const [bookmarklet, setBookmarklet] = useState("");
  const [cells, setCells] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [exportFiles, setExportFiles] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const prepare = async () => {
    setError(null);
    try {
      const r = await Api.collector(region, district ?? undefined, gridSize, layer);
      setScript(r.script);
      setBookmarklet(r.bookmarklet);
      setCells(r.estimated_cells);
    } catch (e) {
      setError(String(e));
    }
  };

  const copyScript = async () => {
    try {
      await navigator.clipboard.writeText(script);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Nusxalab bo‘lmadi — skriptni qo‘lda belgilab nusxalang.");
    }
  };

  const onFile = async (file: File | null) => {
    if (!file) return;
    setError(null);
    setResult(null);
    setExportFiles(null);
    setImporting(true);
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const features = Array.isArray(data) ? data : data.features;
      if (!Array.isArray(features) || features.length === 0) {
        throw new Error("Faylda 'features' topilmadi (GeoJSON FeatureCollection kerak).");
      }
      const res = await Api.importFeatures(
        features,
        region,
        district ?? undefined
      );
      setResult(
        `Import: ${res.found} obyekt, yangi saqlandi ${res.stored_new}, ` +
          `bazada jami ${res.total_in_db}.`
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setImporting(false);
    }
  };

  const doExport = async () => {
    setError(null);
    try {
      const res = await Api.exportData(
        formats,
        region,
        district ?? undefined
      );
      setExportFiles(res.files);
    } catch (e) {
      setError(String(e));
    }
  };

  const openFile = async (filename: string) => {
    const url = await exportFileUrl(filename);
    if (window.uzkad?.openExternal) window.uzkad.openExternal(url);
    else window.open(url, "_blank");
  };

  return (
    <section className="collector-panel">
      <h3>2. Brauzer orqali yig‘ish (tavsiya etiladi)</h3>
      <p className="hint">
        WFS to‘g‘ridan-to‘g‘ri ulanishni rad etsa (403), yig‘ishni{" "}
        <strong>brauzeringizning login qilingan UZKAD sahifasida</strong> bajaring —
        sessiya avtomatik ishlaydi.
      </p>

      <button className="btn primary small" onClick={prepare}>
        Yig‘ish skriptini tayyorlash ({region}
        {district ? ` / ${district}` : ""}, {gridSize}m)
      </button>

      {bookmarklet && (
        <div className="collector-out">
          {cells != null && (
            <p className="hint">
              Taxminiy {cells.toLocaleString()} katak.
            </p>
          )}
          <ol className="login-steps">
            <li>
              <span className="step-no">1</span>
              <div className="step-body">
                <span>
                  Quyidagi havolani <strong>xatcho‘plar paneliga sudrab</strong>{" "}
                  qo‘ying (yoki konsol skriptidan foydalaning):
                </span>
                {/* eslint-disable-next-line jsx-a11y/anchor-is-valid */}
                <a className="bookmarklet-link" href={bookmarklet}>
                  ⬇ UZKAD yig‘ish
                </a>
                <button className="btn secondary small" onClick={copyScript}>
                  {copied ? "Nusxalandi ✓" : "Konsol skriptini nusxalash"}
                </button>
              </div>
            </li>
            <li>
              <span className="step-no">2</span>
              <span>
                UZKAD <strong>xarita</strong> sahifasini oching (login qilingan).
                Xatcho‘pni bosing — yoki <strong>F12 → Console</strong> ga
                skriptni qo‘yib Enter bosing. O‘ng pastda jarayon ko‘rinadi va
                tugagach <strong>.geojson fayl</strong> yuklab olinadi.
              </span>
            </li>
            <li>
              <span className="step-no">3</span>
              <div className="step-body">
                <span>Yuklab olingan GeoJSON faylni shu yerga import qiling:</span>
                <input
                  type="file"
                  accept=".geojson,.json,application/json"
                  onChange={(e) => onFile(e.target.files?.[0] ?? null)}
                  disabled={importing}
                />
              </div>
            </li>
          </ol>
        </div>
      )}

      {result && (
        <div className="alert success error-small">
          {result}
          <div style={{ marginTop: 8 }}>
            <button className="btn primary small" onClick={doExport}>
              Faylga eksport ({formats.map((f) => f.toUpperCase()).join(", ")})
            </button>
          </div>
        </div>
      )}

      {exportFiles && (
        <div className="alert success error-small">
          <strong>Eksport tayyor:</strong>
          <ul>
            {exportFiles.map((f) => (
              <li key={f}>
                <button className="link-btn" onClick={() => openFile(f)}>
                  {f}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && <div className="alert error error-small">{error}</div>}
    </section>
  );
}
