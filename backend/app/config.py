"""Application configuration and constants.

Central place for WFS endpoint settings, CRS, default layer attributes and
filesystem locations used across the backend.
"""
from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------- #
# Filesystem layout
# --------------------------------------------------------------------------- #
# The backend lives in <project>/backend/app. The project root is two levels up.
PROJECT_ROOT = Path(os.environ.get("UZKAD_PROJECT_ROOT", Path(__file__).resolve().parents[2]))

STORAGE_DIR = Path(os.environ.get("UZKAD_STORAGE_DIR", PROJECT_ROOT / "storage"))
EXPORTS_DIR = Path(os.environ.get("UZKAD_EXPORTS_DIR", PROJECT_ROOT / "exports"))
LOGS_DIR = Path(os.environ.get("UZKAD_LOGS_DIR", PROJECT_ROOT / "logs"))

for _d in (STORAGE_DIR, EXPORTS_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.environ.get("UZKAD_DB_PATH", STORAGE_DIR / "features.sqlite"))
LOG_FILE = LOGS_DIR / "application.log"

# --------------------------------------------------------------------------- #
# WFS endpoint
# --------------------------------------------------------------------------- #
WFS_URL = os.environ.get("UZKAD_WFS_URL", "https://mulk.kadastr.uz/gis/wfs")
WFS_VERSION = "2.0.0"
OUTPUT_FORMAT = "application/json"  # GeoJSON

# All UZKAD spatial data is published in Web Mercator.
SOURCE_CRS = "EPSG:3857"
# Common output CRS for exports (WGS84 lon/lat). SHP/.prj will use the chosen one.
DEFAULT_EXPORT_CRS = "EPSG:4326"

# GeoServer paging / safety limits.
DEFAULT_PAGE_SIZE = 1000          # features fetched per WFS page
MAX_FEATURES_PER_CELL = 50000     # hard ceiling guard per grid cell
REQUEST_TIMEOUT = 60              # seconds per HTTP request
REQUEST_RETRIES = 3
RETRY_BACKOFF = 2.0               # seconds, multiplied per attempt

# Parallelism for the grid downloader.
DEFAULT_MAX_WORKERS = 12          # spec: 8-16 parallel requests
MIN_WORKERS = 1
MAX_WORKERS = 16

# Default grid cell size options (metres, EPSG:3857).
GRID_SIZE_OPTIONS = (500, 1000, 2000)
DEFAULT_GRID_SIZE = 1000

# --------------------------------------------------------------------------- #
# Layers
# --------------------------------------------------------------------------- #
# Known WFS layers. `attributes` lists the non-geometry columns we persist.
# The first attribute that exists is used as the dedup primary key (uid first,
# falling back to cadastral_number) - see downloader.dedup logic.
DEFAULT_ATTRIBUTES = [
    "uid",
    "suid",
    "cadastral_number",
    "region",
    "district",
    "legal_area",
    "gis_area",
    "property_kind",
]

LAYERS = [
    {
        "name": "uzbekistan:all_pending_spatial_units",
        "title": "Pending spatial units (Yer uchastkalari)",
        "geometry_type": "MultiPolygon",
        "attributes": DEFAULT_ATTRIBUTES,
    },
]

# Geometry / dedup configuration.
GEOMETRY_FIELD = "geometry"
DEDUP_KEYS = ["uid", "cadastral_number"]  # checked in order

# Default User-Agent so requests look like a normal browser session.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Browsers we will try to read cookies from, in priority order.
SUPPORTED_BROWSERS = ["chrome", "edge", "brave", "chromium", "firefox"]

# The cookie domain we care about for the UZKAD session.
SESSION_DOMAIN = "mulk.kadastr.uz"
