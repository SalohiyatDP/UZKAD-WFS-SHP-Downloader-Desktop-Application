# UZKAD WFS SHP Downloader

Desktop/web application for bulk-collecting cadastral parcels and other spatial
features for a chosen **region (viloyat)** and **district (tuman)** of Uzbekistan,
and exporting them to **Shapefile (SHP)**, **GeoPackage (GPKG)**, **GeoJSON**,
**KML** (optionally **DXF**).

Data comes from the public **NGIS ArcGIS REST** services (`db.ngis.uz`) that back
the [open.ngis.uz](https://open.ngis.uz) map — no login or token required. A
**grid-based downloader** splits the area into cells, queries each cell in
parallel, **clips results to the exact region/district boundary**, de-duplicates,
stores them in SQLite, and exports. A live map shows the boundary and the
collected features as they arrive.

---

## 🚀 Tez ishga tushirish (Docker)

Avval **Docker Desktop** ni o‘rnating va ishga tushiring (Docker xizmati ishlab
turishi kerak): [Docker Desktop yuklab olish](https://www.docker.com/products/docker-desktop/)

So‘ng loyiha papkasida:

```bash
docker compose up --build
```

Tayyor bo‘lgach, brauzerda oching: **http://localhost:8000**

- Ma'lumot manbai **NGIS ArcGIS REST** (`db.ngis.uz`) — login/token talab qilmaydi.
- Eksport fayllari host'dagi `exports/`, ma'lumotlar bazasi `storage/` ga
  saqlanadi (Docker volume orqali).
- To‘xtatish: `Ctrl+C` yoki `docker compose down`.


---

## Architecture

```
project/
├── backend/                 # Python 3.13 + FastAPI
│   ├── app/
│   │   ├── config.py        # data source, CRS, NGIS layers, boundary URLs
│   │   ├── regions.py       # Uzbekistan regions/districts + bounding boxes
│   │   ├── arcgis_client.py # ArcGIS REST query, paging, boundary mask/clip
│   │   ├── wfs_client.py    # legacy WFS client (optional source)
│   │   ├── grid_generator.py# bbox -> grid cells (pyproj 4326->3857)
│   │   ├── database.py      # SQLite features store + dedup + bookkeeping
│   │   ├── downloader.py    # parallel grid downloader (ThreadPoolExecutor)
│   │   ├── exporter.py      # SHP/GPKG/GeoJSON/KML/DXF (fiona, streamed)
│   │   ├── job_manager.py   # job lifecycle + live progress
│   │   └── main.py          # FastAPI app + WebSocket progress + static UI
│   ├── tests/test_pipeline.py
│   └── requirements.txt
├── frontend/                # Electron + React + TypeScript (Vite)
│   ├── electron/            # main.ts (spawns backend), preload.ts
│   └── src/                 # React UI: form, progress, live Leaflet map
├── Dockerfile, docker-compose.yml
├── storage/  exports/  logs/
```

The backend serves both the REST/WebSocket API and the built UI on one port, so
it runs as a Docker web app (browser) or, optionally, inside Electron.

---

## How it works

1. The selected region/district **boundary polygon** is fetched from the NGIS
   boundary layers (`VILOYAT_BORDER`, `TUMAN_BORDER`).
2. A **grid** of `500 / 1000 / 2000 m` cells is built over the boundary's bbox.
3. Each cell is queried in parallel against the ArcGIS FeatureServer
   (`f=geojson` + `resultOffset` paging, EPSG:3857).
4. Returned features are **clipped to the boundary polygon** (so neighbouring
   districts/regions are excluded), converted to WKB and stored in **SQLite**.
5. **De-duplication** uses `uid` then `cadastral_number` (namespaced per layer).
6. The collected layer(s) are **exported** to the chosen formats — one file set
   per selected layer.

Parallelism is configurable (1–16 workers; default 12). Jobs can be **paused,
resumed and cancelled**.


---

## Using the app

1. Choose **Viloyat** (region) and **Tuman** (district, or *Hammasi* = whole region).
2. Tick one or more **Qatlamlar** (layers) — use *Hammasini tanlash* / *Tozalash*.
3. Pick **Grid o‘lchami** and one or more **Format**s, adjust parallel workers.
4. Click **EXPORT**. Collection runs, results are clipped to the boundary,
   de-duplicated, and — when finished — written to `exports/` automatically.
5. The produced files appear as **download links** (plus *Papkani ochish* in the
   desktop build). *Qayta eksport* re-exports the stored data; *Bazani tozalash*
   clears the database for a fresh run.

The right panel shows **progress** (cells, objects, duplicates, speed, ETA) and a
**live map**: the blue outline is the selected boundary, green dots are the
collected features appearing in real time.

---

## Local development

```bash
# Backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.main                      # http://127.0.0.1:8000

# Frontend (browser dev)
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Optional Electron desktop shell (spawns the backend itself):

```bash
cd frontend
UZKAD_PYTHON=../backend/.venv/bin/python npm start
```

---

## Configuration (environment variables, all optional)

| Variable | Default | Purpose |
|----------|---------|---------|
| `UZKAD_DATA_SOURCE` | `arcgis` | `arcgis` (NGIS, public) or `wfs` (legacy) |
| `UZKAD_ARCGIS_BASE` | `https://db.ngis.uz/db/rest/services/UZKAD` | ArcGIS REST base |
| `UZKAD_ARCGIS_REGION_BORDER` | `.../Hosted/VILOYAT_BORDER/FeatureServer/0` | Region boundary layer |
| `UZKAD_ARCGIS_DISTRICT_BORDER` | `.../Hosted/TUMAN_BORDER/FeatureServer/2` | District boundary layer |
| `UZKAD_USE_BOUNDARY_MASK` | `1` | Clip results to the boundary polygon |
| `UZKAD_DB_PATH` | `storage/features.sqlite` | SQLite database path |
| `UZKAD_EXPORTS_DIR` | `exports/` | Export output directory |
| `UZKAD_STATIC_DIR` | `frontend/dist` | Built UI served by the backend |
| `UZKAD_PYTHON` | `python3` | Interpreter Electron uses to start the backend |


---

## REST / WebSocket API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/config` | Data source + filesystem locations |
| GET | `/api/regions` | List regions |
| GET | `/api/regions/{region}/districts` | Districts of a region |
| GET | `/api/layers` | Selectable layers for the active source |
| GET | `/api/estimate?region=&grid_size=` | Estimated cells + region bbox |
| GET | `/api/boundary?region=&district=` | Boundary polygon (GeoJSON) for the map |
| POST | `/api/download` | Start a download job (multiple layers) |
| GET | `/api/jobs/{job_id}` | Job progress snapshot |
| POST | `/api/jobs/{job_id}/pause\|resume\|cancel` | Control a job |
| POST | `/api/export` | Export stored features to file(s) |
| GET | `/api/features/count` | Stored feature count |
| GET | `/api/features/sample?region=&district=` | Feature centroids for the live map |
| POST | `/api/features/clear` | Clear stored features |
| GET | `/api/exports/{filename}` | Download an exported file |
| GET | `/api/wfs/probe` | One-shot connectivity diagnostic |
| WS | `/ws/progress/{job_id}` | Live progress stream |

---

## Testing

```bash
cd backend && source .venv/bin/activate
python -m tests.test_pipeline      # offline: grid -> download -> dedup -> export
```

---

## Notes & limitations

- Because the data layers lack region/district attributes, results are clipped
  to the **boundary polygon** from `VILOYAT_BORDER` / `TUMAN_BORDER`. If a
  boundary can't be resolved, it falls back to the region bounding box.
- Geometry is stored in **EPSG:3857** and reprojected on export (default
  **EPSG:4326**); GeoJSON/KML are written in WGS84.
- Exports are **streamed from SQLite in batches** (fiona), so large areas don't
  need to fit in memory. DXF carries geometry only.
- Large regions can require many cell requests; the UI warns on high estimates.
- The legacy `mulk.kadastr.uz` WFS source requires auth and returns HTTP 403
  even from the logged-in page; it is kept only as an optional fallback.
