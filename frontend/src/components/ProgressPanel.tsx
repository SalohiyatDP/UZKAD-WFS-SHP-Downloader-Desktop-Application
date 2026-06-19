import type { JobProgress } from "../types";

interface Props {
  progress: JobProgress | null;
  onPause: () => void;
  onResume: () => void;
  onCancel: () => void;
}

function formatDuration(seconds: number | null): string {
  if (seconds == null || !isFinite(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}s ${m}m ${sec}s`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

export function ProgressPanel({ progress, onPause, onResume, onCancel }: Props) {
  if (!progress) return null;
  const pct =
    progress.total_cells > 0
      ? Math.min(100, (progress.completed_cells / progress.total_cells) * 100)
      : 0;
  const running = progress.state === "running";
  const paused = progress.state === "paused";

  return (
    <section className="progress-panel">
      <div className="progress-header">
        <h3>Jarayon monitoringi</h3>
        <span className={`state-chip state-${progress.state}`}>
          {progress.state}
        </span>
      </div>

      <div className="progress-bar">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
        <span className="progress-label">{pct.toFixed(1)}%</span>
      </div>

      <div className="stats-grid">
        <Stat label="Yuklangan kataklar" value={`${progress.completed_cells} / ${progress.total_cells}`} />
        <Stat label="Xato kataklar" value={progress.failed_cells} />
        <Stat label="Topilgan obyektlar" value={progress.features_found} />
        <Stat label="Saqlangan (unikal)" value={progress.features_stored} />
        <Stat label="Dublikatlar" value={progress.duplicates_removed} />
        <Stat label="Tezlik" value={`${progress.rate_cells_per_sec.toFixed(2)} katak/s`} />
        <Stat label="O‘tgan vaqt" value={formatDuration(progress.elapsed_seconds)} />
        <Stat label="Taxminiy qolgan" value={formatDuration(progress.eta_seconds)} />
      </div>

      {progress.message && <p className="progress-message">{progress.message}</p>}

      <div className="progress-actions">
        {running && (
          <button className="btn secondary" onClick={onPause}>
            To‘xtatish
          </button>
        )}
        {paused && (
          <button className="btn secondary" onClick={onResume}>
            Davom ettirish
          </button>
        )}
        {(running || paused) && (
          <button className="btn danger" onClick={onCancel}>
            Bekor qilish
          </button>
        )}
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}
