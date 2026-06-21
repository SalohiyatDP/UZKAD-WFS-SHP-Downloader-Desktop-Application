"""Pydantic models shared by the FastAPI layer."""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from .config import DEFAULT_GRID_SIZE, DEFAULT_MAX_WORKERS


class ExportFormat(str, Enum):
    shp = "shp"
    gpkg = "gpkg"
    geojson = "geojson"
    kml = "kml"
    dxf = "dxf"


class JobState(str, Enum):
    idle = "idle"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class DownloadRequest(BaseModel):
    region: str = Field(..., description="Region (viloyat) name")
    district: Optional[str] = Field(
        None, description="District (tuman) name; None or 'Hammasi' means whole region"
    )
    layers: List[str] = Field(
        default_factory=list, description="One or more layer/service names"
    )
    layer: Optional[str] = Field(None, description="Single layer (legacy/back-compat)")
    grid_size: int = Field(DEFAULT_GRID_SIZE, description="Grid cell size in metres (EPSG:3857)")
    formats: List[ExportFormat] = Field(default_factory=lambda: [ExportFormat.shp])
    max_workers: int = Field(DEFAULT_MAX_WORKERS, ge=1, le=16)
    export_crs: str = Field("EPSG:4326", description="CRS for exported files")
    auto_export: bool = Field(
        True, description="Export to files automatically when the download finishes"
    )

    def effective_layers(self) -> List[str]:
        layers = [l for l in (self.layers or []) if l]
        if not layers and self.layer:
            layers = [self.layer]
        return layers


class JobProgress(BaseModel):
    job_id: str
    state: JobState
    total_cells: int = 0
    completed_cells: int = 0
    failed_cells: int = 0
    features_found: int = 0
    duplicates_removed: int = 0
    features_stored: int = 0
    rate_cells_per_sec: float = 0.0
    eta_seconds: Optional[float] = None
    elapsed_seconds: float = 0.0
    message: str = ""
    last_error: str = ""
    export_files: List[str] = Field(default_factory=list)


class SessionStatus(BaseModel):
    authenticated: bool
    browser: Optional[str] = None
    cookie_count: int = 0
    message: str = ""


class SetSessionRequest(BaseModel):
    """Cookies/headers captured by the in-app login window."""

    cookies: dict = Field(default_factory=dict, description="{name: value}")
    headers: dict = Field(
        default_factory=dict,
        description="Extra request headers, e.g. {'Authorization': 'Bearer ...'}",
    )
    source: str = Field("in-app", description="Where the session came from")
