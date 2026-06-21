import type {
  AppConfig,
  DownloadRequest,
  ExportFormat,
  JobProgress,
  Layer,
} from "./types";

// In Electron the backend URL is provided by the preload bridge. When running
// the renderer in a plain browser (vite dev without Electron), fall back to the
// well-known local backend address.
let cachedBackendUrl: string | null = null;

export async function backendUrl(): Promise<string> {
  if (cachedBackendUrl) return cachedBackendUrl;
  if (window.uzkad?.getBackendUrl) {
    cachedBackendUrl = await window.uzkad.getBackendUrl();
  } else if (
    typeof window !== "undefined" &&
    window.location?.origin?.startsWith("http")
  ) {
    // Browser / Docker: backend serves the UI, so use the same origin.
    cachedBackendUrl = window.location.origin;
  } else {
    cachedBackendUrl = "http://127.0.0.1:8000";
  }
  return cachedBackendUrl;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const base = await backendUrl();
  const res = await fetch(`${base}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export const Api = {
  health: () => api<{ status: string }>("/api/health"),
  config: () => api<AppConfig>("/api/config"),
  regions: () => api<{ regions: string[] }>("/api/regions"),
  districts: (region: string) =>
    api<{ region: string; districts: string[] }>(
      `/api/regions/${encodeURIComponent(region)}/districts`
    ),
  layers: () => api<{ layers: Layer[]; source: string }>("/api/layers"),
  probe: (layer?: string) =>
    api<Record<string, unknown>>(
      `/api/wfs/probe${layer ? `?layer=${encodeURIComponent(layer)}` : ""}`
    ),
  estimate: (region: string, gridSize: number) =>
    api<{ estimated_cells: number; bbox_4326: number[] }>(
      `/api/estimate?region=${encodeURIComponent(region)}&grid_size=${gridSize}`
    ),
  boundary: (region: string, district?: string) => {
    const p = new URLSearchParams({ region });
    if (district) p.set("district", district);
    return api<{ geometry: unknown | null; bbox: number[] | null }>(
      `/api/boundary?${p.toString()}`
    );
  },
  featuresSample: (region?: string, district?: string, limit = 3000) => {
    const p = new URLSearchParams({ limit: String(limit) });
    if (region) p.set("region", region);
    if (district) p.set("district", district);
    return api<{ points: number[][]; count: number }>(
      `/api/features/sample?${p.toString()}`
    );
  },
  clearFeatures: (region?: string, district?: string) => {
    const p = new URLSearchParams();
    if (region) p.set("region", region);
    if (district) p.set("district", district);
    return api<{ removed: number; total_in_db: number }>(
      `/api/features/clear?${p.toString()}`,
      { method: "POST" }
    );
  },
  startDownload: (req: DownloadRequest) =>
    api<{ job_id: string; state: string }>("/api/download", {
      method: "POST",
      body: JSON.stringify(req),
    }),
  jobProgress: (jobId: string) => api<JobProgress>(`/api/jobs/${jobId}`),
  pause: (jobId: string) => api(`/api/jobs/${jobId}/pause`, { method: "POST" }),
  resumeJob: (jobId: string) => api(`/api/jobs/${jobId}/resume`, { method: "POST" }),
  cancel: (jobId: string) => api(`/api/jobs/${jobId}/cancel`, { method: "POST" }),
  featuresCount: (region?: string, district?: string) => {
    const params = new URLSearchParams();
    if (region) params.set("region", region);
    if (district) params.set("district", district);
    return api<{ count: number }>(`/api/features/count?${params.toString()}`);
  },
  exportData: (
    formats: ExportFormat[],
    region?: string,
    district?: string,
    exportCrs = "EPSG:4326"
  ) => {
    const params = new URLSearchParams();
    if (region) params.set("region", region);
    if (district) params.set("district", district);
    params.set("export_crs", exportCrs);
    return api<{ files: string[]; paths: string[] }>(
      `/api/export?${params.toString()}`,
      { method: "POST", body: JSON.stringify(formats) }
    );
  },
};

export async function exportFileUrl(filename: string): Promise<string> {
  const base = await backendUrl();
  return `${base}/api/exports/${encodeURIComponent(filename)}`;
}

const TERMINAL_STATES = ["completed", "failed", "cancelled"];

/**
 * Track a job's progress robustly: opens a WebSocket AND runs a REST polling
 * fallback so the UI keeps updating even if the socket fails to connect or
 * drops. Returns a cleanup function that stops both and should be called when
 * the component unmounts or a new job starts.
 */
export async function subscribeJob(
  jobId: string,
  onProgress: (p: JobProgress) => void,
  onDone?: (p: JobProgress | null) => void
): Promise<() => void> {
  let stopped = false;
  let latest: JobProgress | null = null;
  let ws: WebSocket | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  const finish = () => {
    if (stopped) return;
    stopped = true;
    if (pollTimer) clearInterval(pollTimer);
    try {
      ws?.close();
    } catch {
      /* ignore */
    }
    onDone?.(latest);
  };

  const handle = (p: JobProgress) => {
    latest = p;
    onProgress(p);
    if (TERMINAL_STATES.includes(p.state)) finish();
  };

  // WebSocket (primary).
  try {
    const base = await backendUrl();
    const wsUrl = base.replace(/^http/, "ws") + `/ws/progress/${jobId}`;
    ws = new WebSocket(wsUrl);
    ws.onmessage = (evt) => {
      try {
        handle(JSON.parse(evt.data) as JobProgress);
      } catch {
        /* ignore malformed */
      }
    };
  } catch {
    ws = null;
  }

  // REST polling (fallback / safety net), every 1.5s.
  pollTimer = setInterval(async () => {
    if (stopped) return;
    try {
      const p = await Api.jobProgress(jobId);
      handle(p);
    } catch {
      /* job may not be registered yet; keep trying */
    }
  }, 1500);

  return finish;
}
