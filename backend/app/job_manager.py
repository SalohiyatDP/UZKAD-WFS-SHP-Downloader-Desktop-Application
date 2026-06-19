"""In-process job manager: tracks running downloads and their latest progress.

Each download runs in its own worker thread. The downloader's progress callback
writes the latest progress dict into a shared store, which both the REST
``GET /api/jobs/{id}`` endpoint and the WebSocket poller read from. This avoids
cross-thread/event-loop coupling while still giving near-real-time updates.
"""
from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from .database import FeatureDB
from .downloader import GridDownloader
from .logging_setup import get_logger
from .session import get_cookies_for_domain
from .wfs_client import WFSClient

log = get_logger("jobs")


class JobManager:
    def __init__(self, db: FeatureDB) -> None:
        self.db = db
        self._downloaders: Dict[str, GridDownloader] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._progress: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    def start(
        self,
        layer: str,
        region: str,
        district: Optional[str],
        grid_size: int,
        max_workers: int,
        proxy: Optional[str] = None,
        resume: bool = False,
        job_id: Optional[str] = None,
    ) -> str:
        cookies, browser = get_cookies_for_domain()
        client = WFSClient(cookies=cookies, proxy=proxy)
        db = self.db

        def _cb(progress: Dict[str, Any]) -> None:
            with self._lock:
                self._progress[progress["job_id"]] = progress

        downloader = GridDownloader(client, db, progress_cb=_cb, job_id=job_id)
        jid = downloader.job_id
        self._downloaders[jid] = downloader
        self._progress[jid] = downloader.stats.to_dict()

        def _run() -> None:
            try:
                downloader.run(
                    layer=layer,
                    region=region,
                    district=district,
                    grid_size=grid_size,
                    max_workers=max_workers,
                    resume=resume,
                )
            except Exception as exc:  # noqa: BLE001
                log.exception("Job %s crashed", jid)
                stats = downloader.stats
                stats.state = "failed"
                stats.message = f"Error: {exc}"
                with self._lock:
                    self._progress[jid] = stats.to_dict()

        thread = threading.Thread(target=_run, name=f"download-{jid}", daemon=True)
        self._threads[jid] = thread
        thread.start()
        log.info("Started job %s (%s/%s) browser=%s", jid, region, district, browser)
        return jid

    # ------------------------------------------------------------------ #
    def get_progress(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._progress.get(job_id)

    def pause(self, job_id: str) -> bool:
        d = self._downloaders.get(job_id)
        if d:
            d.pause()
            return True
        return False

    def resume(self, job_id: str) -> bool:
        d = self._downloaders.get(job_id)
        if d:
            d.resume()
            return True
        return False

    def cancel(self, job_id: str) -> bool:
        d = self._downloaders.get(job_id)
        if d:
            d.cancel()
            return True
        return False

    def is_running(self, job_id: str) -> bool:
        t = self._threads.get(job_id)
        return bool(t and t.is_alive())
