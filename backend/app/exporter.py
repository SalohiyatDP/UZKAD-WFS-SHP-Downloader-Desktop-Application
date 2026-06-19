"""Export stored features to ESRI Shapefile (zipped), GeoPackage, GeoJSON,
KML and (optionally) DXF.

Features are read back from SQLite (WKB geometry, stored in EPSG:3857),
assembled into a GeoDataFrame, reprojected to the requested export CRS and
written with pyogrio/fiona via geopandas.
"""
from __future__ import annotations

import datetime as _dt
import zipfile
from pathlib import Path
from typing import List, Optional

import geopandas as gpd
from shapely import wkb as shapely_wkb

from . import config
from .database import FeatureDB
from .logging_setup import get_logger

log = get_logger("exporter")

_ATTR_COLUMNS = [
    "uid",
    "suid",
    "cadastral_number",
    "region",
    "district",
    "legal_area",
    "gis_area",
    "property_kind",
]


def _build_geodataframe(
    db: FeatureDB,
    region: Optional[str] = None,
    district: Optional[str] = None,
) -> gpd.GeoDataFrame:
    geometries = []
    records = []
    for row in db.iter_features(region=region, district=district):
        try:
            geom = shapely_wkb.loads(bytes(row["geometry_wkb"]))
        except Exception:  # noqa: BLE001
            continue
        geometries.append(geom)
        records.append({col: row.get(col) for col in _ATTR_COLUMNS})

    gdf = gpd.GeoDataFrame(records, geometry=geometries, crs=config.SOURCE_CRS)
    return gdf


def _safe_name(region: Optional[str], district: Optional[str]) -> str:
    parts = [p for p in (region, district) if p and p.lower() not in ("hammasi", "all")]
    base = "_".join(parts) if parts else "uzkad_export"
    # Keep only ascii-friendly filename characters.
    cleaned = "".join(c if c.isalnum() else "_" for c in base)
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{cleaned}_{ts}"


class Exporter:
    def __init__(self, db: FeatureDB, out_dir: Path = config.EXPORTS_DIR) -> None:
        self.db = db
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def export(
        self,
        formats: List[str],
        region: Optional[str] = None,
        district: Optional[str] = None,
        export_crs: str = config.DEFAULT_EXPORT_CRS,
    ) -> List[str]:
        gdf = _build_geodataframe(self.db, region, district)
        if gdf.empty:
            raise ValueError("No features stored to export. Run a download first.")

        if export_crs and export_crs.upper() != config.SOURCE_CRS:
            gdf = gdf.to_crs(export_crs)

        base = _safe_name(region, district)
        produced: List[str] = []
        for fmt in formats:
            fmt = str(fmt).lower()
            try:
                if fmt == "shp":
                    produced.append(self._export_shp(gdf, base))
                elif fmt == "gpkg":
                    produced.append(self._export_gpkg(gdf, base))
                elif fmt == "geojson":
                    produced.append(self._export_geojson(gdf, base))
                elif fmt == "kml":
                    produced.append(self._export_kml(gdf, base))
                elif fmt == "dxf":
                    produced.append(self._export_dxf(gdf, base))
                else:
                    log.warning("Unknown export format ignored: %s", fmt)
            except Exception:  # noqa: BLE001
                log.exception("Export to %s failed", fmt)
                raise
        return produced

    # ------------------------------------------------------------------ #
    def _export_shp(self, gdf: gpd.GeoDataFrame, base: str) -> str:
        shp_dir = self.out_dir / f"{base}_shp"
        shp_dir.mkdir(parents=True, exist_ok=True)
        shp_path = shp_dir / f"{base}.shp"
        # DBF column names are limited to 10 chars; geopandas/pyogrio handle this.
        gdf.to_file(shp_path, driver="ESRI Shapefile", encoding="utf-8")

        zip_path = self.out_dir / f"{base}_shp.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for part in shp_dir.iterdir():
                zf.write(part, arcname=part.name)
        log.info("SHP exported: %s", zip_path)
        return str(zip_path)

    def _export_gpkg(self, gdf: gpd.GeoDataFrame, base: str) -> str:
        path = self.out_dir / f"{base}.gpkg"
        gdf.to_file(path, driver="GPKG", layer=base)
        log.info("GPKG exported: %s", path)
        return str(path)

    def _export_geojson(self, gdf: gpd.GeoDataFrame, base: str) -> str:
        path = self.out_dir / f"{base}.geojson"
        # GeoJSON is conventionally WGS84.
        out = gdf.to_crs("EPSG:4326") if str(gdf.crs).upper() != "EPSG:4326" else gdf
        out.to_file(path, driver="GeoJSON")
        log.info("GeoJSON exported: %s", path)
        return str(path)

    def _export_kml(self, gdf: gpd.GeoDataFrame, base: str) -> str:
        path = self.out_dir / f"{base}.kml"
        out = gdf.to_crs("EPSG:4326") if str(gdf.crs).upper() != "EPSG:4326" else gdf
        try:
            out.to_file(path, driver="KML")
        except Exception:
            # Some GDAL builds need the LIBKML/KML driver enabled explicitly.
            import fiona
            fiona.supported_drivers["KML"] = "rw"
            out.to_file(path, driver="KML")
        log.info("KML exported: %s", path)
        return str(path)

    def _export_dxf(self, gdf: gpd.GeoDataFrame, base: str) -> str:
        path = self.out_dir / f"{base}.dxf"
        import fiona
        fiona.supported_drivers["DXF"] = "rw"
        # DXF carries geometry only (no attributes).
        gdf[["geometry"]].to_file(path, driver="DXF")
        log.info("DXF exported: %s", path)
        return str(path)
