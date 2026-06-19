export type ExportFormat = "shp" | "gpkg" | "geojson" | "kml" | "dxf";

export type JobState =
  | "idle"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled";

export interface Layer {
  name: string;
  title: string;
  geometry_type: string;
  attributes: string[];
}

export interface SessionStatus {
  authenticated: boolean;
  source?: string | null;
  browser: string | null;
  cookie_count: number;
  has_token?: boolean;
  message: string;
}

export interface JobProgress {
  job_id: string;
  state: JobState;
  total_cells: number;
  completed_cells: number;
  failed_cells: number;
  features_found: number;
  duplicates_removed: number;
  features_stored: number;
  rate_cells_per_sec: number;
  eta_seconds: number | null;
  elapsed_seconds: number;
  message: string;
  export_files: string[];
}

export interface DownloadRequest {
  region: string;
  district: string | null;
  layer: string;
  grid_size: number;
  formats: ExportFormat[];
  max_workers: number;
  export_crs: string;
  auto_export: boolean;
}

export interface AppConfig {
  version: string;
  exports_dir: string;
  storage_dir: string;
  logs_dir: string;
  wfs_url: string;
}

export interface LastJob {
  job_id: string;
  region: string;
  district: string | null;
  layer: string;
  grid_size: number;
  state: string;
  total_cells: number;
  completed_cells: number;
  features_stored: number;
}
