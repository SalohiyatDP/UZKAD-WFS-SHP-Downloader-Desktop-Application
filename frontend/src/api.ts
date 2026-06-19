import type {
  AppConfig,
  DownloadRequest,
  ExportFormat,
  JobProgress,
  Layer,
  LastJob,
  SessionStatus,
} from "./types";

// In Electron the backend URL is provided by the preload bridge. When running
// the renderer in a plain browser (vite dev without Electron), fall back to the
// well-known local backend address.
let cachedBackendUrl: string | null = null;

export async function backendUrl(): Promise<string> {
  if (cachedBackendUrl) return cachedBackendUrl;
  if (window.uzkad?.getBackendUrl) {
    cachedBackendUrl = await window.uzkad.getBackendUrl();
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
  session: () => api<SessionStatus>("/api/session"),
  loginUrl: () =>
    api<{ url: string; session_domain: string }>("/api/session/login-url"),
  clearSession: () =>
    api<SessionStatus>("/api/session/clear", { method: "POST" }),
  setSession: (
    cookies: Record<string, string>,
    headers: Record<string, string> = {},
    source = "manual"
  ) =>
    api<SessionStatus>("/api/session/cookies", {
      method: "POST",
      body: JSON.stringify({ cookies, headers, source }),
    }),
  regions: () => api<{ regions: string[] }>("/api/regions"),
  districts: (region: string, refresh = false, layer?: string) =>
    api<{ region: string; districts: string[]; source: string }>(
      `/api/regions/${encodeURIComponent(region)}/districts?refresh=${refresh}` +
        (layer ? `&layer=${encodeURIComponent(layer)}` : "")
    ),
  layers: () => api<{ layers: Layer[] }>("/api/layers"),
  probe: (layer?: string, region?: string, district?: string) => {
    const params = new URLSearchParams();
    if (layer) params.set("layer", layer);
    if (region) params.set("region", region);
    if (district) params.set("district", district);
    return api<Record<string, unknown>>(`/api/wfs/probe?${params.toString()}`);
  },
  estimate: (region: string, gridSize: number) =>
    api<{ estimated_cells: number }>(
      `/api/estimate?region=${encodeURIComponent(region)}&grid_size=${gridSize}`
    ),
  collector: (
    region: string,
    district: string | undefined,
    gridSize: number,
    layer?: string
  ) => {
    const p = new URLSearchParams({ region, grid_size: String(gridSize) });
    if (district) p.set("district", district);
    if (layer) p.set("layer", layer);
    return api<{
      script: string;
      bookmarklet: string;
      filename: string;
      estimated_cells: number;
    }>(`/api/collector?${p.toString()}`);
  },
  importFeatures: (features: unknown[], region?: string, district?: string) =>
    api<{
      found: number;
      valid: number;
      stored_new: number;
      total_in_db: number;
    }>("/api/import", {
      method: "POST",
      body: JSON.stringify({ features, region, district }),
    }),
  startDownload: (req: DownloadRequest) =>
    api<{ job_id: string; state: string }>("/api/download", {
      method: "POST",
      body: JSON.stringify(req),
    }),
  jobProgress: (jobId: string) => api<JobProgress>(`/api/jobs/${jobId}`),
  pause: (jobId: string) =>
    api(`/api/jobs/${jobId}/pause`, { method: "POST" }),
  resumeJob: (jobId: string) =>
    api(`/api/jobs/${jobId}/resume`, { method: "POST" }),
  cancel: (jobId: string) =>
    api(`/api/jobs/${jobId}/cancel`, { method: "POST" }),
  resumeDownload: (jobId: string) =>
    api<{ job_id: string; resumed: boolean }>(
      `/api/download/resume?job_id=${encodeURIComponent(jobId)}`,
      { method: "POST" }
    ),
  lastSession: () => api<{ job: LastJob | null }>("/api/last-session"),
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
