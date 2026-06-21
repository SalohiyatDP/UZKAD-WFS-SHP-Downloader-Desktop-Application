"""FastAPI application exposing the UZKAD downloader to the frontend.

REST endpoints cover region/district/layer discovery, download job control,
boundary/feature map data and export. A WebSocket streams live job progress.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import config, regions as regions_data
from .database import FeatureDB
from .exporter import Exporter
from .job_manager import JobManager
from .logging_setup import get_logger
from .models import DownloadRequest, ExportFormat
from .grid_generator import estimate_cell_count

log = get_logger("api")

app = FastAPI(title="UZKAD WFS SHP Downloader", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_db = FeatureDB()
_jobs = JobManager(_db)


# --------------------------------------------------------------------------- #
# Health & config
# --------------------------------------------------------------------------- #
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "version": app.version}


@app.get("/api/config")
def app_config() -> dict:
    """Expose filesystem locations so the UI can open the exports folder."""
    return {
        "version": app.version,
        "exports_dir": str(config.EXPORTS_DIR),
        "storage_dir": str(config.STORAGE_DIR),
        "logs_dir": str(config.LOGS_DIR),
        "data_source": config.DATA_SOURCE,
    }


# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #
@app.get("/api/regions")
def list_regions() -> dict:
    return {"regions": regions_data.list_regions()}


@app.get("/api/regions/{region}/districts")
def list_districts(region: str) -> dict:
    return {"region": region, "districts": regions_data.list_districts(region)}


@app.get("/api/layers")
def list_layers() -> dict:
    return {"layers": config.active_layers(), "source": config.DATA_SOURCE}


@app.get("/api/wfs/probe")
def wfs_probe(layer: Optional[str] = None) -> dict:
    """Diagnostic: send ONE small query to the active data source and return the
    raw server response so layer/format/connectivity problems are visible."""
    from .arcgis_client import ArcGISClient

    target_layer = layer or config.active_layers()[0]["name"]
    client = ArcGISClient()
    params = {
        "f": "geojson",
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "false",
        "resultRecordCount": 1,
    }
    info: dict = {"layer": target_layer, "source": config.DATA_SOURCE}
    try:
        resp = client.raw_request(target_layer, params)
    except Exception as exc:  # noqa: BLE001
        info.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return info
    text = resp.text or ""
    info.update({
        "ok": resp.status_code == 200,
        "status": resp.status_code,
        "content_type": resp.headers.get("Content-Type"),
        "request_url": str(resp.url),
        "snippet": text[:900],
    })
    try:
        data = resp.json()
        feats = data.get("features", []) or []
        info["feature_count"] = len(feats)
        if feats:
            info["property_keys"] = list((feats[0].get("properties") or {}).keys())
        elif data.get("error"):
            info["ok"] = False
    except ValueError:
        info["is_json"] = False
    return info


@app.get("/api/estimate")
def estimate(region: str, grid_size: int = config.DEFAULT_GRID_SIZE) -> dict:
    region_info = regions_data.get_region(region)
    if not region_info:
        raise HTTPException(status_code=404, detail=f"Unknown region: {region}")
    cells = estimate_cell_count(tuple(region_info["bbox_4326"]), float(grid_size))
    return {
        "region": region,
        "grid_size": grid_size,
        "estimated_cells": cells,
        "bbox_4326": list(region_info["bbox_4326"]),
    }


# --------------------------------------------------------------------------- #
# Map support: boundary polygon + live feature sample
# --------------------------------------------------------------------------- #
@app.get("/api/boundary")
def boundary(region: str, district: Optional[str] = None) -> dict:
    """Return the selected region/district boundary as WGS84 GeoJSON (for the map)."""
    if config.DATA_SOURCE != "arcgis":
        return {"geometry": None, "bbox": None}
    from .arcgis_client import ArcGISClient

    client = ArcGISClient(region=region, district=district)
    geom = client.boundary_geojson_4326()
    if geom is None:
        return {"geometry": None, "bbox": None}
    return {"geometry": geom["geometry"], "bbox": geom["bbox"]}


@app.get("/api/features/sample")
def features_sample(
    region: Optional[str] = None,
    district: Optional[str] = None,
    limit: int = 3000,
) -> dict:
    """Return centroids (lon/lat) of stored features for live map plotting."""
    from shapely import wkb as _wkb
    from pyproj import Transformer

    t = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    points: List[List[float]] = []
    for blob in _db.sample_geometry_wkb(region=region, district=district, limit=limit):
        try:
            geom = _wkb.loads(bytes(blob))
            pt = geom.representative_point()
            lon, lat = t.transform(pt.x, pt.y)
            points.append([round(lon, 6), round(lat, 6)])
        except Exception:  # noqa: BLE001
            continue
    return {"points": points, "count": _db.count_features(region=region, district=district)}


@app.post("/api/features/clear")
def features_clear(region: Optional[str] = None, district: Optional[str] = None) -> dict:
    """Delete stored features (optionally scoped) to start a clean run."""
    removed = _db.clear_features(region=region, district=district)
    return {"removed": removed, "total_in_db": _db.count_features()}


# --------------------------------------------------------------------------- #
# Download jobs
# --------------------------------------------------------------------------- #
@app.post("/api/download")
def start_download(req: DownloadRequest) -> dict:
    if not regions_data.get_region(req.region):
        raise HTTPException(status_code=404, detail=f"Unknown region: {req.region}")
    layers = req.effective_layers()
    if not layers:
        raise HTTPException(status_code=400, detail="Kamida bitta qatlam tanlang")
    job_id = _jobs.start(
        layers=layers,
        region=req.region,
        district=req.district,
        grid_size=req.grid_size,
        max_workers=req.max_workers,
        formats=[f.value for f in req.formats],
        export_crs=req.export_crs,
        auto_export=req.auto_export,
    )
    return {"job_id": job_id, "state": "running"}


@app.get("/api/jobs/{job_id}")
def job_progress(job_id: str) -> dict:
    progress = _jobs.get_progress(job_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    return progress


@app.post("/api/jobs/{job_id}/pause")
def pause_job(job_id: str) -> dict:
    if not _jobs.pause(job_id):
        raise HTTPException(status_code=404, detail="Unknown job")
    return {"job_id": job_id, "state": "paused"}


@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str) -> dict:
    if not _jobs.resume(job_id):
        raise HTTPException(status_code=404, detail="Unknown job")
    return {"job_id": job_id, "state": "running"}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    if not _jobs.cancel(job_id):
        raise HTTPException(status_code=404, detail="Unknown job")
    return {"job_id": job_id, "state": "cancelled"}


@app.get("/api/last-session")
def last_session() -> dict:
    last = _db.get_last_job()
    return {"job": last}


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
@app.post("/api/export")
def export(
    formats: List[ExportFormat],
    region: Optional[str] = None,
    district: Optional[str] = None,
    export_crs: str = config.DEFAULT_EXPORT_CRS,
) -> dict:
    exporter = Exporter(_db)
    try:
        files = exporter.export(
            formats=[f.value for f in formats],
            region=region,
            district=district,
            export_crs=export_crs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"files": [Path(f).name for f in files], "paths": files}


@app.get("/api/features/count")
def features_count(region: Optional[str] = None, district: Optional[str] = None) -> dict:
    return {"count": _db.count_features(region=region, district=district)}


@app.get("/api/exports/{filename}")
def download_export(filename: str) -> FileResponse:
    path = config.EXPORTS_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Export file not found")
    return FileResponse(str(path), filename=filename)


# --------------------------------------------------------------------------- #
# WebSocket progress
# --------------------------------------------------------------------------- #
@app.websocket("/ws/progress/{job_id}")
async def ws_progress(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    try:
        last_sent = None
        while True:
            progress = _jobs.get_progress(job_id)
            if progress is not None and progress != last_sent:
                await websocket.send_json(progress)
                last_sent = progress
                if progress.get("state") in ("completed", "failed", "cancelled"):
                    break
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        log.debug("WebSocket disconnected for job %s", job_id)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Static frontend (browser / Docker mode). Mounted last so /api and /ws win.
# --------------------------------------------------------------------------- #
if config.STATIC_DIR.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="ui")
    log.info("Serving frontend from %s", config.STATIC_DIR)


def main() -> None:
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="UZKAD WFS downloader backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    log.info("Starting UZKAD backend on %s:%s", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
