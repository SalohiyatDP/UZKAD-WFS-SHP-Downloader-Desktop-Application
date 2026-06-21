"""SQLite persistence for downloaded features with de-duplication.

The ``features`` table stores one row per unique spatial object. Geometry is
kept as WKB (``geometry_wkb``) so exports can rebuild shapely geometries
without re-querying the WFS. De-duplication uses ``uid`` first, falling back to
``cadastral_number`` (see config.DEDUP_KEYS).
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from . import config
from .logging_setup import get_logger

log = get_logger("db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS features (
    dedup_key       TEXT PRIMARY KEY,
    uid             TEXT,
    suid            TEXT,
    cadastral_number TEXT,
    region          TEXT,
    district        TEXT,
    legal_area      REAL,
    gis_area        REAL,
    property_kind   TEXT,
    source_layer    TEXT,
    geometry_wkb    BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_features_cadastral ON features(cadastral_number);
CREATE INDEX IF NOT EXISTS idx_features_district  ON features(district);
CREATE INDEX IF NOT EXISTS idx_features_region    ON features(region);
CREATE INDEX IF NOT EXISTS idx_features_layer     ON features(source_layer);

CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,
    region        TEXT,
    district      TEXT,
    layer         TEXT,
    grid_size     INTEGER,
    state         TEXT,
    total_cells   INTEGER,
    completed_cells INTEGER,
    features_stored INTEGER,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS job_cells (
    job_id    TEXT,
    cell_index INTEGER,
    status     TEXT,
    PRIMARY KEY (job_id, cell_index)
);
"""

_COLUMNS = [
    "uid",
    "suid",
    "cadastral_number",
    "region",
    "district",
    "legal_area",
    "gis_area",
    "property_kind",
]


class FeatureDB:
    """Thread-safe-ish SQLite wrapper (serialised through a lock)."""

    def __init__(self, db_path: Path = config.DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        with self._lock:
            self._conn.executescript(SCHEMA)
            # Migrate older DBs that predate the source_layer column.
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(features)")}
            if "source_layer" not in cols:
                self._conn.execute("ALTER TABLE features ADD COLUMN source_layer TEXT")
            self._conn.commit()

    # ------------------------------------------------------------------ #
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ #
    # Feature insertion / dedup
    # ------------------------------------------------------------------ #
    def upsert_features(self, rows: Iterable[Dict[str, Any]]) -> int:
        """Insert features, ignoring duplicates on ``dedup_key``.

        Returns the number of *new* rows actually stored.
        """
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            "INSERT OR IGNORE INTO features "
            "(dedup_key, uid, suid, cadastral_number, region, district, "
            " legal_area, gis_area, property_kind, source_layer, geometry_wkb) "
            "VALUES (:dedup_key, :uid, :suid, :cadastral_number, :region, "
            ":district, :legal_area, :gis_area, :property_kind, :source_layer, "
            ":geometry_wkb)"
        )
        with self._lock:
            before = self._conn.total_changes
            self._conn.executemany(sql, rows)
            self._conn.commit()
            return self._conn.total_changes - before

    def count_features(self, region: Optional[str] = None,
                        district: Optional[str] = None,
                        source_layer: Optional[str] = None) -> int:
        clauses, params = [], []
        if region:
            clauses.append("region = ?")
            params.append(region)
        if district:
            clauses.append("district = ?")
            params.append(district)
        if source_layer:
            clauses.append("source_layer = ?")
            params.append(source_layer)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            cur = self._conn.execute(f"SELECT COUNT(*) FROM features{where}", params)
            return int(cur.fetchone()[0])

    def iter_features(
        self, region: Optional[str] = None, district: Optional[str] = None,
        source_layer: Optional[str] = None, batch_size: int = 5000,
    ) -> Iterator[Dict[str, Any]]:
        """Yield stored feature rows (including geometry_wkb) in batches."""
        clauses, params = [], []
        if region:
            clauses.append("region = ?")
            params.append(region)
        if district:
            clauses.append("district = ?")
            params.append(district)
        if source_layer:
            clauses.append("source_layer = ?")
            params.append(source_layer)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        cols = ", ".join(_COLUMNS + ["geometry_wkb"])
        with self._lock:
            cur = self._conn.execute(
                f"SELECT {cols} FROM features{where}", params
            )
            names = [d[0] for d in cur.description]
            while True:
                batch = cur.fetchmany(batch_size)
                if not batch:
                    break
                for row in batch:
                    yield dict(zip(names, row))

    def clear_features(self, region: Optional[str] = None,
                       district: Optional[str] = None) -> int:
        clauses, params = [], []
        if region:
            clauses.append("region = ?")
            params.append(region)
        if district:
            clauses.append("district = ?")
            params.append(district)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            cur = self._conn.execute(f"DELETE FROM features{where}", params)
            self._conn.commit()
            return cur.rowcount

    # ------------------------------------------------------------------ #
    # Job / resume bookkeeping
    # ------------------------------------------------------------------ #
    def save_job(self, job: Dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs (job_id, region, district, layer, grid_size, "
                "state, total_cells, completed_cells, features_stored, updated_at) "
                "VALUES (:job_id, :region, :district, :layer, :grid_size, :state, "
                ":total_cells, :completed_cells, :features_stored, CURRENT_TIMESTAMP) "
                "ON CONFLICT(job_id) DO UPDATE SET state=:state, "
                "total_cells=:total_cells, completed_cells=:completed_cells, "
                "features_stored=:features_stored, updated_at=CURRENT_TIMESTAMP",
                job,
            )
            self._conn.commit()

    def mark_cell(self, job_id: str, cell_index: int, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO job_cells (job_id, cell_index, status) VALUES (?, ?, ?) "
                "ON CONFLICT(job_id, cell_index) DO UPDATE SET status=excluded.status",
                (job_id, cell_index, status),
            )
            self._conn.commit()

    def completed_cells(self, job_id: str) -> set[int]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT cell_index FROM job_cells WHERE job_id=? AND status='done'",
                (job_id,),
            )
            return {int(r[0]) for r in cur.fetchall()}

    def get_last_job(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(
                "SELECT job_id, region, district, layer, grid_size, state, "
                "total_cells, completed_cells, features_stored "
                "FROM jobs ORDER BY updated_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                return None
            names = [d[0] for d in cur.description]
            return dict(zip(names, row))


def make_dedup_key(props: Dict[str, Any]) -> Optional[str]:
    """Return the first available dedup key value (uid, then cadastral_number)."""
    for key in config.DEDUP_KEYS:
        val = props.get(key)
        if val not in (None, ""):
            return f"{key}:{val}"
    return None
