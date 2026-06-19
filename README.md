# UZKAD WFS SHP Downloader

Desktop application for bulk-collecting spatial parcels and other features from
the **UZKAD GIS** system (`mulk.kadastr.uz`) via its WFS service, and exporting
them to **Shapefile (SHP)**, **GeoPackage (GPKG)**, **GeoJSON** and **KML**
(optionally **DXF**).

The app uses the authorized session you already have in your browser (OneID +
ERI sign-in), so no separate login window is needed. It works around GeoServer
`maxFeatures` / paging limits with a **grid-based downloader**: a region is
split into square cells and each cell is fetched with a `BBOX` query in
parallel, results are de-duplicated and stored in SQLite, then exported.

---

## Architecture

```
project/
├── backend/                 # Python 3.13 + FastAPI
│   ├── app/
│   │   ├── config.py        # WFS endpoint, CRS (EPSG:3857), limits, layers
│   │   ├── regions.py       # Uzbekistan regions/districts + bounding boxes
│   │   ├── wfs_client.py    # WFS GetFeature (BBOX, paging, retries, distinct values)
│   │   ├── grid_generator.py# bbox -> grid cells (pyproj 4326->3857)
│   │   ├── database.py      # SQLite features store + dedup + resume bookkeeping
│   │   ├── downloader.py    # parallel grid downloader (ThreadPoolExecutor)
│   │   ├── exporter.py      # SHP / GPKG / GeoJSON / KML / DXF (geopandas/pyogrio)
│   │   ├── session.py       # in-app login session capture + browser fallback
│   │   ├── job_manager.py   # job lifecycle + live progress
│   │   └── main.py          # FastAPI app + WebSocket progress
│   ├── tests/test_pipeline.py
│   └── requirements.txt
├── frontend/                # Electron + React + TypeScript (Vite)
│   ├── electron/main.ts     # spawns backend, creates window
│   ├── electron/preload.ts  # safe IPC bridge
│   └── src/                 # React UI (dropdowns, grid/format pickers, progress)
├── storage/                 # SQLite database (generated)
├── exports/                 # generated SHP/GPKG/GeoJSON/KML files
└── logs/                    # application.log
```

The Electron main process launches the FastAPI backend on
`http://127.0.0.1:8000`, waits for `/api/health`, then loads the React UI which
talks to the backend over HTTP + a WebSocket for live progress.

---

## How it works (download algorithm)

1. **Bounding box** of the selected region is determined (EPSG:3857).
2. The area is split into a **grid** of `500 / 1000 / 2000 m` cells.
3. Each cell issues a `WFS GetFeature` request with `BBOX(xmin,ymin,xmax,ymax)`
   (+ a CQL filter on `region` / `district`), with **startIndex/count paging**.
4. Features are converted to **WKB** and written to **SQLite**.
5. **De-duplication** uses `uid` as the primary key, falling back to
   `cadastral_number` (then feature id / geometry hash).
6. The collected, de-duplicated layer is **exported** to the chosen formats.

Parallelism is configurable (1–16 workers; default 12) via `ThreadPoolExecutor`.
Jobs can be **paused, resumed and cancelled**, and the last session is saved so
a download can be **resumed** (already-completed cells are skipped).

---

## Prerequisites

- **Python 3.11+** (3.13 recommended) with system GDAL available for
  `geopandas` / `pyogrio` / `fiona`.
- **Node.js 18+** and npm.
- A desktop browser (Chrome/Edge/Brave/Chromium/Firefox) where you have signed
  in to `https://mulk.kadastr.uz`.

- A desktop browser is **optional**: the app has a built-in portal window
  (`mulk.kadastr.uz`) where you open a ready, signed-in portal link. The
  `browser_cookie3` fallback can reuse an existing desktop-browser session too.

> Authentication: open a ready portal link (e.g.
> `https://mulk.kadastr.uz/index.jsp#portal/details/transaction/<uuid>/`) in the
> app's portal window. The app captures the `kadastr.uz` cookies (and bearer
> token, if the portal uses one) for the WFS endpoint. No credentials are stored.

---

## Setup & run (development)

### 1. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app.main               # serves on http://127.0.0.1:8000
```

### 2. Frontend (Electron + React)

```bash
cd frontend
npm install
npm run dev                      # Vite dev server on http://localhost:5173
# in another terminal, build the electron entry then launch:
npm run build:electron && npm run electron
```

For a one-shot production-style launch (builds renderer + electron, then runs
Electron which itself starts the Python backend):

```bash
cd frontend
npm start
```

Set `UZKAD_PYTHON` to point Electron at a specific Python interpreter
(e.g. the venv), for example:

```bash
UZKAD_PYTHON=../backend/.venv/bin/python npm start
```

### 3. Package a desktop installer

```bash
cd frontend
npm run package                  # electron-builder; bundles backend/ as a resource
```

---

## Using the app

1. **Sessiya (portal havolasi).** In the **"1. Tizimga kirish / sessiya"** panel,
   paste a ready, signed-in portal link (e.g. a `mulk.kadastr.uz`
   `index.jsp#portal/details/transaction/<uuid>/` URL) into the field and click
   **"Portalni ochish"**. The app opens it in a portal window; sign in with
   **OneID / ERI** if prompted. Once the page loads with your session, click
   **"Sessiyani import qilish"**: the app captures the `kadastr.uz` cookies and
   any auth token and hands them to the backend. The **session badge** turns green.
   *(If you are already signed in to `mulk.kadastr.uz` in a desktop browser, the
   app can also auto-detect those cookies — just press "Sessiyani import qilish".)*
2. If a previous run was interrupted, a banner offers to **resume** it.
3. Choose **Viloyat** (region), **Tuman** (district, or *Hammasi* = all),
   **Qatlam** (layer), **Grid o‘lchami** and one or more **Format**s.
4. Click **EXPORT**. The app collects features through the authorized session,
   removes duplicates, and — as soon as collection finishes — **automatically
   writes the chosen file(s)** into `exports/`. The progress panel shows
   downloaded cells, found objects, duplicates removed, speed and ETA.
5. When finished, the produced files are listed with **clickable download
   links** and a **"Papkani ochish"** button to open the exports folder.
   Use **"Qayta eksport"** to re-export the same data to another format.

### Example

> Viloyat = **Namangan**, Tuman = **Hammasi**, Qatlam = **Yer uchastkalari**,
> Format = **SHP** → the app collects the whole Namangan region through the
> authorized session, removes duplicates, and produces a single zipped
> Shapefile (`.shp/.dbf/.shx/.prj`).

---

## Configuration

Environment variables (all optional):

| Variable | Default | Purpose |
|----------|---------|---------|
| `UZKAD_WFS_URL` | `https://mulk.kadastr.uz/gis/wfs` | WFS endpoint |
| `UZKAD_WFS_BBOX_SRS` | `EPSG:3857` | CRS token in the WFS BBOX param (use URN form if needed) |
| `UZKAD_REGION_BBOX_PADDING` | `0.05` | Degrees of padding around region bbox |
| `UZKAD_DB_PATH` | `storage/features.sqlite` | SQLite database path |
| `UZKAD_EXPORTS_DIR` | `exports/` | Export output directory |
| `UZKAD_PYTHON` | `python3` | Interpreter Electron uses to start backend |

> The backend port is chosen automatically by Electron (a free port is picked at
> launch), so a busy port 8000 is no longer a problem. The renderer discovers the
> URL through the preload bridge.

WFS layers, default attributes, grid sizes, paging and worker limits are in
`backend/app/config.py`.

---

## REST / WebSocket API (backend)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/config` | Filesystem locations (exports dir, etc.) |
| GET | `/api/session` | Browser session / cookie status |
| GET | `/api/session/login-url` | Portal login URL for the in-app window |
| POST | `/api/session/cookies` | Store cookies/auth captured by the login window |
| POST | `/api/session/clear` | Clear the captured session |
| GET | `/api/regions` | List regions |
| GET | `/api/regions/{region}/districts?refresh=` | Districts (static or live WFS) |
| GET | `/api/layers` | Available WFS layers |
| GET | `/api/estimate?region=&grid_size=` | Estimated grid cell count |
| POST | `/api/download` | Start a download job |
| POST | `/api/download/resume?job_id=` | Resume last job |
| GET | `/api/jobs/{job_id}` | Job progress snapshot |
| POST | `/api/jobs/{job_id}/pause\|resume\|cancel` | Control a job |
| GET | `/api/last-session` | Last saved job (for resume) |
| POST | `/api/export` | Export stored features to file(s) |
| GET | `/api/features/count` | Stored feature count |
| GET | `/api/exports/{filename}` | Download an exported file |
| WS | `/ws/progress/{job_id}` | Live progress stream |

---

## Testing

An offline pipeline test mocks the WFS service and exercises grid generation,
parallel download, de-duplication, SQLite storage and export:

```bash
cd backend
source .venv/bin/activate
python -m tests.test_pipeline
```

---

## Notes & limitations

- Geometry is stored in **EPSG:3857** (the source CRS) and reprojected on
  export (default **EPSG:4326**). GeoJSON/KML are always written in WGS84.
- Exports are **streamed from SQLite in batches** (`fiona`), so whole-province
  exports with millions of geometries do not need to fit in memory.
- The region grid uses approximate bounding boxes, **padded** by
  `UZKAD_REGION_BBOX_PADDING` degrees and validated against the layer's true
  WGS84 extent (from WFS GetCapabilities) so edge features are not clipped.
- DXF carries geometry only (no attributes), as per the DXF format.
- Reading browser cookies depends on OS permissions and the browser's cookie
  encryption; if detection fails, sign in again and refresh the session badge.
- Large regions can require **tens of thousands of cell requests** and take a
  long time; the UI warns when the estimate is high. Pause/resume and the
  resume-last-session banner help with long runs.
