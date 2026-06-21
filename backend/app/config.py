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
# CRS token used inside the WFS BBOX parameter. Some GeoServer deployments
# prefer the URN form (urn:ogc:def:crs:EPSG::3857); override via env if needed.
WFS_BBOX_SRS = os.environ.get("UZKAD_WFS_BBOX_SRS", SOURCE_CRS)
# Common output CRS for exports (WGS84 lon/lat). SHP/.prj will use the chosen one.
DEFAULT_EXPORT_CRS = "EPSG:4326"

# Padding (in degrees) added around a region bounding box before building the
# grid, so approximate region extents never clip features at the edges.
REGION_BBOX_PADDING_DEG = float(os.environ.get("UZKAD_REGION_BBOX_PADDING", "0.05"))

# Batch size used when streaming features out of SQLite during export, to keep
# memory bounded for very large regions.
EXPORT_BATCH_SIZE = 5000

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

# --------------------------------------------------------------------------- #
# ArcGIS REST FeatureServer source (open.ngis.uz / db.ngis.uz) - PRIMARY
# --------------------------------------------------------------------------- #
# The open.ngis.uz map is served by public ArcGIS REST FeatureServers. This is
# queryable without authentication, unlike the locked mulk.kadastr.uz WFS.
ARCGIS_BASE = os.environ.get(
    "UZKAD_ARCGIS_BASE", "https://db.ngis.uz/db/rest/services/UZKAD"
)
ARCGIS_SR = int(os.environ.get("UZKAD_ARCGIS_SR", "102100"))  # 102100 == EPSG:3857

# Data source selector: "arcgis" (default, NGIS) or "wfs" (legacy kadastr.uz).
DATA_SOURCE = os.environ.get("UZKAD_DATA_SOURCE", "arcgis").lower()

# NGIS FeatureServer services (the "Qatlam" choices).
NGIS_LAYERS = [
    {"name": "TURAR_UZKAD_DB16", "title": "Turar-joy yer uchastkalari (TURAR)"},
    {"name": "NOTURAR_UZKAD_DB16", "title": "Noturar-joy obyektlari (NOTURAR)"},
    {"name": "AGR_ONLY_UZKAD_DB16", "title": "Qishloq xo'jaligi yerlari (AGR)"},
    {"name": "AVTOYUL_UZKAD_DB16", "title": "Avtomobil yo'llari (AVTOYUL)"},
    {"name": "FOREST_UZKAD_DB16", "title": "O'rmon fondi (FOREST)"},
    {"name": "WATER_UZKAD_DB16", "title": "Suv obyektlari (WATER)"},
    {"name": "MAHALLA_UZKAD_DB16", "title": "Mahallalar (MAHALLA)"},
    {"name": "MUHOFAZA_UZKAD_DB16", "title": "Muhofaza zonalari (MUHOFAZA)"},
    {"name": "DZY_UZKAD_DB16", "title": "Yer uchastkalari (DZY)"},
]


def active_layers() -> list:
    """Return the layer list for the configured data source."""
    if DATA_SOURCE == "arcgis":
        return [
            {
                "name": l["name"],
                "title": l["title"],
                "geometry_type": "MultiPolygon",
                "attributes": DEFAULT_ATTRIBUTES,
            }
            for l in NGIS_LAYERS
        ]
    return LAYERS


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

# Portal the user opens (already signed in via OneID / ERI in another window).
# Using mulk.kadastr.uz directly means the captured cookies are first-party to
# the WFS host, which is more reliable than a cross-subdomain (sap) session.
# Accepts any ready portal link, e.g.
# https://mulk.kadastr.uz/index.jsp#portal/details/transaction/<uuid>/
PORTAL_URL = os.environ.get(
    "UZKAD_PORTAL_URL",
    os.environ.get("UZKAD_SAP_LOGIN_URL", "https://mulk.kadastr.uz/index.jsp"),
)

# Parent domain whose cookies (and bearer token) authorise the WFS endpoint.
SESSION_COOKIE_DOMAIN = "kadastr.uz"

# Where the captured session (cookies + headers) is persisted so it survives
# backend restarts within a work session.
SESSION_FILE = STORAGE_DIR / "session.json"
