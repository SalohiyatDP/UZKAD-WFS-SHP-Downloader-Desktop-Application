import type {
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
  session: () => api<SessionStatus>("/api/session"),
  regions: () => api<{ regions: string[] }>("/api/regions"),
  districts: (region: string, refresh = false, layer?: string) =>
    api<{ region: string; districts: string[]; source: string }>(
      `/api/regions/${encodeURIComponent(region)}/districts?refresh=${refresh}` +
        (layer ? `&layer=${encodeURIComponent(layer)}` : "")
    ),
  layers: () => api<{ layers: Layer[] }>("/api/layers"),
  estimate: (region: string, gridSize: number) =>
    api<{ estimated_cells: number }>(
      `/api/estimate?region=${encodeURIComponent(region)}&grid_size=${gridSize}`
    ),
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

export async function openProgressSocket(
  jobId: string,
  onMessage: (p: JobProgress) => void,
  onClose?: () => void
): Promise<WebSocket> {
  const base = await backendUrl();
  const wsUrl = base.replace(/^http/, "ws") + `/ws/progress/${jobId}`;
  const ws = new WebSocket(wsUrl);
  ws.onmessage = (evt) => {
    try {
      onMessage(JSON.parse(evt.data) as JobProgress);
    } catch {
      /* ignore malformed */
    }
  };
  ws.onclose = () => onClose?.();
  return ws;
}
