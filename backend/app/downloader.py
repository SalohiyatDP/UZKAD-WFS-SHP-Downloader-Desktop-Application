"""Parallel grid-based bulk downloader with de-duplication and progress.

Orchestrates: region bbox -> grid cells -> parallel WFS GetFeature(BBOX) ->
GeoJSON parse -> WKB conversion -> SQLite upsert (dedup). Emits progress
callbacks consumed by the FastAPI WebSocket layer. Supports pause / resume /
cancel and resumable jobs (already-completed cells are skipped).
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from concurrent.futures import ThreadPoolExecutor, as_completed

from shapely.geometry import shape
from shapely import wkb as shapely_wkb

from . import config
from .database import FeatureDB, make_dedup_key
from .exporter import Exporter
from .grid_generator import GridCell, grid_for_region_bbox_4326
from .logging_setup import get_logger
from .regions import get_region
from .wfs_client import WFSClient, WFSError, build_region_filter

log = get_logger("downloader")

ProgressCallback = Callable[[Dict[str, Any]], None]


@dataclass
class DownloadStats:
    job_id: str
    state: str = "idle"
    total_cells: int = 0
    completed_cells: int = 0
    failed_cells: int = 0
    features_found: int = 0
    duplicates_removed: int = 0
    features_stored: int = 0
    started_at: float = 0.0
    elapsed_seconds: float = 0.0
    message: str = ""
    last_error: str = ""
    export_files: List[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        if self.elapsed_seconds <= 0:
            return 0.0
        return self.completed_cells / self.elapsed_seconds

    @property
    def eta(self) -> Optional[float]:
        remaining = self.total_cells - self.completed_cells
        if self.rate <= 0 or remaining <= 0:
            return None
        return remaining / self.rate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "state": self.state,
            "total_cells": self.total_cells,
            "completed_cells": self.completed_cells,
            "failed_cells": self.failed_cells,
            "features_found": self.features_found,
            "duplicates_removed": self.duplicates_removed,
            "features_stored": self.features_stored,
            "rate_cells_per_sec": round(self.rate, 3),
            "eta_seconds": round(self.eta, 1) if self.eta is not None else None,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "message": self.message,
            "last_error": self.last_error,
            "export_files": self.export_files,
        }


class GridDownloader:
    """Runs one download job. Create a fresh instance per job."""

    def __init__(
        self,
        client: WFSClient,
        db: FeatureDB,
        progress_cb: Optional[ProgressCallback] = None,
        job_id: Optional[str] = None,
    ) -> None:
        self.client = client
        self.db = db
        self.progress_cb = progress_cb
        self.job_id = job_id or uuid.uuid4().hex[:12]
        self.stats = DownloadStats(job_id=self.job_id)

        self._pause = threading.Event()
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Controls
    # ------------------------------------------------------------------ #
    def pause(self) -> None:
        self._pause.set()
        self.stats.state = "paused"
        self._emit()

    def resume(self) -> None:
        self._pause.clear()
        if self.stats.state == "paused":
            self.stats.state = "running"
        self._emit()

    def cancel(self) -> None:
        self._cancel.set()
        self._pause.clear()
        self.stats.state = "cancelled"
        self._emit()

    # ------------------------------------------------------------------ #
    def _emit(self) -> None:
        if self.stats.started_at:
            self.stats.elapsed_seconds = time.time() - self.stats.started_at
        if self.progress_cb:
            try:
                self.progress_cb(self.stats.to_dict())
            except Exception:  # progress must never break the download
                log.exception("progress callback failed")

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #
    def run(
        self,
        layers,
        region: str,
        district: Optional[str],
        grid_size: int,
        max_workers: int = config.DEFAULT_MAX_WORKERS,
        resume: bool = False,
        formats: Optional[List[str]] = None,
        export_crs: str = config.DEFAULT_EXPORT_CRS,
        auto_export: bool = True,
    ) -> DownloadStats:
        if isinstance(layers, str):
            layers = [layers]
        layers = [l for l in (layers or []) if l]
        if not layers:
            raise ValueError("No layers selected")

        region_info = get_region(region)
        if not region_info:
            raise ValueError(f"Unknown region: {region}")

        eff_district = (
            district
            if district and district.lower() not in ("hammasi", "all", "barchasi")
            else None
        )
        cql = build_region_filter(region, district)

        # Validate / extend the (approximate) region bbox against the layer's
        # true extent so the grid never under-covers the data.
        clamp_to = None
        try:
            clamp_to = self.client.get_layer_extent_4326(layers[0])
        except Exception:  # noqa: BLE001
            clamp_to = None

        cells = grid_for_region_bbox_4326(
            tuple(region_info["bbox_4326"]),
            float(grid_size),
            padding_deg=(0.0 if config.DATA_SOURCE == "arcgis"
                         else config.REGION_BBOX_PADDING_DEG),
            clamp_to=clamp_to,
        )
        n_cells = len(cells)
        tasks = [
            (li * n_cells + cell.index, layer, cell)
            for li, layer in enumerate(layers)
            for cell in cells
        ]
        self.stats.total_cells = len(tasks)
        self.stats.started_at = time.time()
        self.stats.state = "running"
        self.stats.message = (
            f"Yuklanmoqda: {region} / {district or 'Hammasi'} — "
            f"{len(layers)} qatlam"
        )

        joined = ",".join(layers)
        self.db.save_job(self._job_row(joined, region, district, grid_size))

        already = self.db.completed_cells(self.job_id) if resume else set()
        if already:
            self.stats.completed_cells = len(already)
            log.info("Resuming job %s; %s tasks already done", self.job_id, len(already))
        pending = [t for t in tasks if t[0] not in already]
        self._emit()

        workers = max(config.MIN_WORKERS, min(max_workers, config.MAX_WORKERS))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    self._download_cell, layer, cell, cql, region, eff_district
                ): (gi, layer, cell)
                for (gi, layer, cell) in pending
            }
            for future in as_completed(futures):
                gi, layer, cell = futures[future]
                if self._cancel.is_set():
                    break
                self._wait_if_paused()
                try:
                    found, stored = future.result()
                    with self._lock:
                        self.stats.features_found += found
                        self.stats.features_stored += stored
                        self.stats.duplicates_removed += max(0, found - stored)
                        self.stats.completed_cells += 1
                    self.db.mark_cell(self.job_id, gi, "done")
                except Exception as exc:  # noqa: BLE001
                    with self._lock:
                        self.stats.failed_cells += 1
                        self.stats.completed_cells += 1
                        self.stats.last_error = str(exc)[:300]
                    self.db.mark_cell(self.job_id, gi, "failed")
                    log.warning("Task %s (%s) failed: %s", gi, layer, exc)
                self._emit()

        if self._cancel.is_set():
            self.stats.state = "cancelled"
            self.stats.message = "Yuklash bekor qilindi"
            self.db.save_job(self._job_row(joined, region, district, grid_size))
            self._emit()
            return self.stats

        if auto_export and formats:
            self._run_export(formats, region, eff_district, layers, export_crs)

        self.stats.state = "completed"
        self.stats.message = (
            f"Tayyor: {self.stats.features_stored} ta unikal obyekt "
            f"({self.stats.duplicates_removed} dublikat olib tashlandi)"
        )
        self.db.save_job(self._job_row(joined, region, district, grid_size))
        self._emit()
        return self.stats

    # ------------------------------------------------------------------ #
    def _run_export(
        self,
        formats: List[str],
        region: str,
        district: Optional[str],
        layers: List[str],
        export_crs: str,
    ) -> None:
        from .exporter import Exporter

        self.stats.message = "Eksport qilinmoqda (faylga yozilmoqda)..."
        self._emit()
        exporter = Exporter(self.db)
        files: List[str] = []
        for layer in layers:
            try:
                files.extend(
                    exporter.export(
                        formats=formats,
                        region=region,
                        district=district,
                        source_layer=layer,
                        export_crs=export_crs,
                    )
                )
            except ValueError as exc:
                # Layer produced no features in this area; skip it.
                log.info("Export skipped for %s: %s", layer, exc)
            except Exception as exc:  # noqa: BLE001
                log.exception("Export failed for %s", layer)
                self.stats.last_error = str(exc)[:300]
        self.stats.export_files = files
        if not files:
            self.stats.last_error = self.stats.last_error or (
                "Eksport uchun obyekt topilmadi (tanlangan hududda 0 obyekt)."
            )
        log.info("Auto-export produced %s file(s)", len(files))

    # ------------------------------------------------------------------ #
    def _wait_if_paused(self) -> None:
        while self._pause.is_set() and not self._cancel.is_set():
            time.sleep(0.25)

    def _download_cell(
        self, layer: str, cell: GridCell, cql: Optional[str],
        region: Optional[str] = None, district: Optional[str] = None,
    ) -> Tuple[int, int]:
        """Download one cell; return (features_found, features_stored_new)."""
        if self._cancel.is_set():
            return 0, 0
        self._wait_if_paused()
        features = self.client.get_features_bbox(layer, cell.bbox, cql_filter=cql)
        rows = self._features_to_rows(features, region, district, layer)
        stored = self.db.upsert_features(rows) if rows else 0
        return len(features), stored

    @staticmethod
    def _features_to_rows(
        features: List[Dict[str, Any]],
        region: Optional[str] = None,
        district: Optional[str] = None,
        source_layer: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for feat in features:
            props = feat.get("properties") or {}
            geom = feat.get("geometry")
            if not geom:
                continue
            dedup_key = make_dedup_key(props)
            if dedup_key is None:
                fid = feat.get("id")
                dedup_key = f"id:{fid}" if fid is not None else None
            try:
                wkb_bytes = shapely_wkb.dumps(shape(geom))
            except Exception:  # noqa: BLE001 - skip invalid geometries
                continue
            if dedup_key is None:
                dedup_key = f"geom:{hash(wkb_bytes)}"
            # Namespace the dedup key by layer so ids from different services
            # never collide.
            if source_layer:
                dedup_key = f"{source_layer}|{dedup_key}"
            rows.append(
                {
                    "dedup_key": dedup_key,
                    "uid": _s(props.get("uid")),
                    "suid": _s(props.get("suid")),
                    "cadastral_number": _s(props.get("cadastral_number")),
                    # Stamp the selected region/district when the source data
                    # lacks them (e.g. ArcGIS layers), so exports can filter.
                    "region": _s(props.get("region")) or _s(region),
                    "district": _s(props.get("district")) or _s(district),
                    "legal_area": _f(props.get("legal_area")),
                    "gis_area": _f(props.get("gis_area")),
                    "property_kind": _s(props.get("property_kind")),
                    "source_layer": _s(source_layer),
                    "geometry_wkb": wkb_bytes,
                }
            )
        return rows

    def _job_row(self, layer, region, district, grid_size) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "region": region,
            "district": district,
            "layer": layer,
            "grid_size": grid_size,
            "state": self.stats.state,
            "total_cells": self.stats.total_cells,
            "completed_cells": self.stats.completed_cells,
            "features_stored": self.stats.features_stored,
        }


def _s(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def _f(value: Any) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
