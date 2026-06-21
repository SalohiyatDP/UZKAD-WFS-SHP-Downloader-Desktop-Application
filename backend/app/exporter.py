"""Export stored features to ESRI Shapefile (zipped), GeoPackage, GeoJSON,
KML and (optionally) DXF.

Features are streamed back from SQLite in batches (WKB geometry, stored in
EPSG:3857), reprojected to the requested export CRS on the fly and written with
``fiona`` so memory stays bounded even for very large regions (whole-province
exports with millions of geometries do not need to fit in RAM at once).
"""
from __future__ import annotations

import datetime as _dt
import zipfile
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import fiona
from fiona.crs import from_epsg
from pyproj import Transformer
from shapely import wkb as shapely_wkb
from shapely.geometry import mapping
from shapely.ops import transform as shapely_transform

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

# fiona schema shared by every driver. UZKAD geometry is MultiPolygon; single
# Polygons are promoted to MultiPolygon for a uniform schema.
_SCHEMA = {
    "geometry": "MultiPolygon",
    "properties": {
        "uid": "str",
        "suid": "str",
        "cadastral_number": "str",
        "region": "str",
        "district": "str",
        "legal_area": "float",
        "gis_area": "float",
        "property_kind": "str",
    },
}


def _epsg_code(crs: str) -> int:
    return int(str(crs).upper().replace("EPSG:", "").strip())


def _safe_name(region: Optional[str], district: Optional[str],
               source_layer: Optional[str] = None) -> str:
    parts = [p for p in (region, district, source_layer)
             if p and p.lower() not in ("hammasi", "all")]
    base = "_".join(parts) if parts else "uzkad_export"
    cleaned = "".join(c if c.isalnum() else "_" for c in base)
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{cleaned}_{ts}"


def _to_multipolygon(geom):
    if geom.geom_type == "Polygon":
        from shapely.geometry import MultiPolygon

        return MultiPolygon([geom])
    return geom


class Exporter:
    def __init__(self, db: FeatureDB, out_dir: Path = config.EXPORTS_DIR) -> None:
        self.db = db
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    def _iter_records(
        self,
        region: Optional[str],
        district: Optional[str],
        target_crs: str,
        source_layer: Optional[str] = None,
    ) -> Iterator[Dict]:
        """Yield fiona records, reprojecting geometry from source to target CRS."""
        transformer = None
        if target_crs and target_crs.upper() != config.SOURCE_CRS:
            transformer = Transformer.from_crs(
                config.SOURCE_CRS, target_crs, always_xy=True
            )
        for row in self.db.iter_features(
            region=region, district=district, source_layer=source_layer,
            batch_size=config.EXPORT_BATCH_SIZE,
        ):
            try:
                geom = shapely_wkb.loads(bytes(row["geometry_wkb"]))
            except Exception:  # noqa: BLE001
                continue
            if geom.is_empty:
                continue
            if transformer is not None:
                geom = shapely_transform(transformer.transform, geom)
            geom = _to_multipolygon(geom)
            props = {col: row.get(col) for col in _ATTR_COLUMNS}
            yield {"geometry": mapping(geom), "properties": props}

    def _write_collection(
        self,
        path: Path,
        driver: str,
        target_crs: str,
        region: Optional[str],
        district: Optional[str],
        layer: Optional[str] = None,
        geometry_only: bool = False,
        source_layer: Optional[str] = None,
    ) -> int:
        """Stream records into a fiona collection. Returns number written."""
        schema = _SCHEMA
        if geometry_only:
            schema = {"geometry": "MultiPolygon", "properties": {}}

        open_kwargs = dict(
            driver=driver,
            schema=schema,
            crs=from_epsg(_epsg_code(target_crs)),
        )
        if layer:
            open_kwargs["layer"] = layer

        written = 0
        batch: List[Dict] = []
        with fiona.open(str(path), "w", **open_kwargs) as sink:
            for rec in self._iter_records(region, district, target_crs, source_layer):
                if geometry_only:
                    rec = {"geometry": rec["geometry"], "properties": {}}
                batch.append(rec)
                if len(batch) >= config.EXPORT_BATCH_SIZE:
                    sink.writerecords(batch)
                    written += len(batch)
                    batch = []
            if batch:
                sink.writerecords(batch)
                written += len(batch)
        return written

    # ------------------------------------------------------------------ #
    def export(
        self,
        formats: List[str],
        region: Optional[str] = None,
        district: Optional[str] = None,
        export_crs: str = config.DEFAULT_EXPORT_CRS,
        source_layer: Optional[str] = None,
    ) -> List[str]:
        if self.db.count_features(region=region, district=district,
                                  source_layer=source_layer) == 0:
            raise ValueError("No features stored to export. Run a download first.")

        _enable_optional_drivers()
        base = _safe_name(region, district, source_layer)
        sl = source_layer
        produced: List[str] = []
        for fmt in (str(f).lower() for f in formats):
            try:
                if fmt == "shp":
                    produced.append(self._export_shp(base, export_crs, region, district, sl))
                elif fmt == "gpkg":
                    produced.append(self._export_gpkg(base, export_crs, region, district, sl))
                elif fmt == "geojson":
                    produced.append(self._export_geojson(base, region, district, sl))
                elif fmt == "kml":
                    produced.append(self._export_kml(base, region, district, sl))
                elif fmt == "dxf":
                    produced.append(self._export_dxf(base, export_crs, region, district, sl))
                else:
                    log.warning("Unknown export format ignored: %s", fmt)
            except Exception:  # noqa: BLE001
                log.exception("Export to %s failed", fmt)
                raise
        return produced

    # ------------------------------------------------------------------ #
    def _export_shp(self, base, crs, region, district, sl=None) -> str:
        shp_dir = self.out_dir / f"{base}_shp"
        shp_dir.mkdir(parents=True, exist_ok=True)
        shp_path = shp_dir / f"{base}.shp"
        n = self._write_collection(
            shp_path, "ESRI Shapefile", crs, region, district, source_layer=sl
        )
        zip_path = self.out_dir / f"{base}_shp.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for part in shp_dir.iterdir():
                zf.write(part, arcname=part.name)
        log.info("SHP exported (%s features): %s", n, zip_path)
        return str(zip_path)

    def _export_gpkg(self, base, crs, region, district, sl=None) -> str:
        path = self.out_dir / f"{base}.gpkg"
        n = self._write_collection(path, "GPKG", crs, region, district,
                                   layer=base, source_layer=sl)
        log.info("GPKG exported (%s features): %s", n, path)
        return str(path)

    def _export_geojson(self, base, region, district, sl=None) -> str:
        path = self.out_dir / f"{base}.geojson"
        n = self._write_collection(path, "GeoJSON", "EPSG:4326", region, district,
                                   source_layer=sl)
        log.info("GeoJSON exported (%s features): %s", n, path)
        return str(path)

    def _export_kml(self, base, region, district, sl=None) -> str:
        path = self.out_dir / f"{base}.kml"
        n = self._write_collection(path, "KML", "EPSG:4326", region, district,
                                   source_layer=sl)
        log.info("KML exported (%s features): %s", n, path)
        return str(path)

    def _export_dxf(self, base, crs, region, district, sl=None) -> str:
        path = self.out_dir / f"{base}.dxf"
        n = self._write_collection(
            path, "DXF", crs, region, district, geometry_only=True, source_layer=sl
        )
        log.info("DXF exported (%s features): %s", n, path)
        return str(path)


def _enable_optional_drivers() -> None:
    """Ensure KML/DXF write support is enabled where the GDAL build allows."""
    for drv in ("KML", "LIBKML", "DXF"):
        try:
            fiona.supported_drivers[drv] = "rw"
        except Exception:  # noqa: BLE001
            pass
