"""FastAPI application exposing the UZKAD downloader to the Electron frontend.

REST endpoints cover session status, region/district/layer discovery, download
job control and export. A WebSocket streams live job progress to the UI.
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
from .models import DownloadRequest, ExportFormat, SetSessionRequest
from .session import (
    clear_session,
    get_active_cookies,
    get_active_headers,
    get_session_status,
    set_session,
)
from .wfs_client import WFSClient, WFSError, build_region_filter
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
# Health & session
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
        "wfs_url": config.WFS_URL,
    }


@app.get("/api/session")
def session_status() -> dict:
    return get_session_status()


@app.get("/api/session/login-url")
def session_login_url() -> dict:
    """The portal URL the in-app login window should open by default."""
    return {"url": config.PORTAL_URL, "session_domain": config.SESSION_COOKIE_DOMAIN}


@app.post("/api/session/cookies")
def set_session_cookies(req: SetSessionRequest) -> dict:
    """Receive cookies / auth headers captured by the in-app login window."""
    return set_session(cookies=req.cookies, headers=req.headers, source=req.source)


@app.post("/api/session/clear")
def clear_session_endpoint() -> dict:
    clear_session()
    return get_session_status()


# --------------------------------------------------------------------------- #
# Reference data
# --------------------------------------------------------------------------- #
@app.get("/api/regions")
def list_regions() -> dict:
    return {"regions": regions_data.list_regions()}


@app.get("/api/regions/{region}/districts")
def list_districts(region: str, refresh: bool = False, layer: Optional[str] = None) -> dict:
    static = regions_data.list_districts(region)
    if not refresh:
        return {"region": region, "districts": static, "source": "static"}

    # Try to refresh distinct districts from the live WFS.
    client = WFSClient(cookies=get_active_cookies(), headers=get_active_headers())
    target_layer = layer or config.LAYERS[0]["name"]
    try:
        cql = build_region_filter(region, None)
        dynamic = client.get_distinct_values(target_layer, "district", cql_filter=cql)
        if dynamic:
            return {"region": region, "districts": dynamic, "source": "wfs"}
    except WFSError as exc:
        log.warning("Dynamic district refresh failed: %s", exc)
    return {"region": region, "districts": static, "source": "static-fallback"}


@app.get("/api/layers")
def list_layers() -> dict:
    return {"layers": config.LAYERS}


@app.get("/api/wfs/probe")
def wfs_probe(
    layer: Optional[str] = None,
    region: Optional[str] = None,
    district: Optional[str] = None,
) -> dict:
    """Diagnostic: send ONE small GetFeature with the active session and return
    the raw server response so auth/layer/format problems can be identified."""
    target_layer = layer or config.LAYERS[0]["name"]
    client = WFSClient(cookies=get_active_cookies(), headers=get_active_headers())
    cql = build_region_filter(region, district) if region else None
    params = {
        "service": "WFS",
        "version": config.WFS_VERSION,
        "request": "GetFeature",
        "typeNames": target_layer,
        "outputFormat": config.OUTPUT_FORMAT,
        "count": 1,
    }
    if cql:
        params["cql_filter"] = cql

    info: dict = {"layer": target_layer, "cql_filter": cql}
    try:
        resp = client.raw_request(params)
    except Exception as exc:  # noqa: BLE001
        info.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return info

    text = resp.text or ""
    info.update(
        {
            "ok": resp.status_code == 200,
            "status": resp.status_code,
            "content_type": resp.headers.get("Content-Type"),
            "request_url": str(resp.url),
            "snippet": text[:900],
        }
    )
    try:
        data = resp.json()
        feats = data.get("features", []) or []
        info["feature_count"] = len(feats)
        info["numberMatched"] = data.get("numberMatched")
        if feats:
            info["property_keys"] = list((feats[0].get("properties") or {}).keys())
    except ValueError:
        info["is_json"] = False
    return info


@app.get("/api/estimate")
def estimate(region: str, grid_size: int = config.DEFAULT_GRID_SIZE) -> dict:
    region_info = regions_data.get_region(region)
    if not region_info:
        raise HTTPException(status_code=404, detail=f"Unknown region: {region}")
    cells = estimate_cell_count(tuple(region_info["bbox_4326"]), float(grid_size))
    return {"region": region, "grid_size": grid_size, "estimated_cells": cells}


# --------------------------------------------------------------------------- #
# Download jobs
# --------------------------------------------------------------------------- #
@app.post("/api/download")
def start_download(req: DownloadRequest) -> dict:
    if not regions_data.get_region(req.region):
        raise HTTPException(status_code=404, detail=f"Unknown region: {req.region}")
    job_id = _jobs.start(
        layer=req.layer,
        region=req.region,
        district=req.district,
        grid_size=req.grid_size,
        max_workers=req.max_workers,
        formats=[f.value for f in req.formats],
        export_crs=req.export_crs,
        auto_export=req.auto_export,
    )
    return {"job_id": job_id, "state": "running"}


@app.post("/api/download/resume")
def resume_download(job_id: str) -> dict:
    last = _db.get_last_job()
    if not last or last["job_id"] != job_id:
        raise HTTPException(status_code=404, detail="Job not found for resume")
    new_id = _jobs.start(
        layer=last["layer"],
        region=last["region"],
        district=last["district"],
        grid_size=last["grid_size"],
        max_workers=config.DEFAULT_MAX_WORKERS,
        resume=True,
        job_id=job_id,
        formats=["shp"],
        auto_export=True,
    )
    return {"job_id": new_id, "state": "running", "resumed": True}


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
