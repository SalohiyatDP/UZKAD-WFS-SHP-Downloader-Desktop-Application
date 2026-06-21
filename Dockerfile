# syntax=docker/dockerfile:1

# ---------- Stage 1: build the React/Vite frontend ----------
FROM node:22-slim AS frontend
WORKDIR /app/frontend
ENV ELECTRON_SKIP_BINARY_DOWNLOAD=1
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build:renderer

# ---------- Stage 2: Python backend + serve static UI ----------
FROM python:3.13-slim
WORKDIR /app/backend

# System libs needed at runtime by the GDAL wheels (fiona/pyogrio) and TLS.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Geospatial wheels (pyogrio/fiona/shapely/pyproj) bundle GDAL/GEOS/PROJ,
# so no full system GDAL is required (only libexpat1 above).
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ /app/backend/
COPY --from=frontend /app/frontend/dist /app/frontend/dist

ENV UZKAD_DATA_SOURCE=arcgis \
    UZKAD_STATIC_DIR=/app/frontend/dist \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["python", "-m", "app.main", "--host", "0.0.0.0", "--port", "8000"]
