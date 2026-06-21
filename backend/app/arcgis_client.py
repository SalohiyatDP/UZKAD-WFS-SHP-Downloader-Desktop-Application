"""ArcGIS REST FeatureServer client for the NGIS (db.ngis.uz) data source.

The open.ngis.uz map is backed by public ArcGIS REST FeatureServers, e.g.
``https://db.ngis.uz/db/rest/services/UZKAD/TURAR_UZKAD_DB16/FeatureServer/0``.
These accept standard ``/query`` requests (no authentication observed), so we
query them per grid cell with ``f=geojson`` and ``resultOffset`` paging.

This client exposes the same surface the grid downloader expects from the WFS
client (``get_features_bbox`` and ``get_layer_extent_4326``) so the rest of the
pipeline is unchanged.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from . import config
from .logging_setup import get_logger

log = get_logger("arcgis")


class ArcGISError(RuntimeError):
    pass



class ArcGISClient:
    def __init__(
        self,
        base_url: str = None,
        timeout: int = config.REQUEST_TIMEOUT,
        proxy: Optional[str] = None,
        cookies: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
        region: Optional[str] = None,
        district: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or config.ARCGIS_BASE).rstrip("/")
        self.timeout = timeout
        self.region = region
        self.district = (
            district
            if district and district.lower() not in ("hammasi", "all", "barchasi")
            else None
        )
        self._where_cache: Dict[str, str] = {}
        self._mask = None            # shapely geometry (EPSG:3857) or None
        self._prepared = None        # prepared mask for fast intersects
        self._mask_bbox_4326 = None  # (minlon, minlat, maxlon, maxlat) or None
        self._mask_resolved = False
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.USER_AGENT, "Accept": "*/*"})
        if headers:
            self.session.headers.update({k: v for k, v in headers.items() if v})
        if cookies:
            self.session.cookies.update(cookies)
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})

    # ------------------------------------------------------------------ #
    def _layer_query_url(self, layer: str) -> str:
        # `layer` is a service name like "TURAR_UZKAD_DB16"; default to layer 0.
        return f"{self.base_url}/{layer}/FeatureServer/0/query"

    def _layer_info_url(self, layer: str) -> str:
        return f"{self.base_url}/{layer}/FeatureServer/0"

    def _request(self, url: str, params: Dict[str, Any]) -> requests.Response:
        last: Optional[Exception] = None
        for attempt in range(1, config.REQUEST_RETRIES + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp
                if resp.status_code in (401, 403):
                    raise ArcGISError(
                        f"Access denied (HTTP {resp.status_code}) for {url}"
                    )
                last = ArcGISError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            except (requests.RequestException, ArcGISError) as exc:
                last = exc
                log.warning("ArcGIS request error attempt %s: %s", attempt, exc)
            if attempt < config.REQUEST_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
        raise ArcGISError(f"ArcGIS request failed after retries: {last}")

    def raw_request(self, layer: str, params: Dict[str, Any]) -> requests.Response:
        return self.session.get(
            self._layer_query_url(layer), params=params, timeout=self.timeout
        )

    # ------------------------------------------------------------------ #
    # Region / district attribute filtering (so a district selection does not
    # download the whole region or bleed into neighbouring regions).
    # ------------------------------------------------------------------ #
    def get_layer_fields(self, layer: str) -> List[Dict[str, Any]]:
        try:
            resp = self._request(self._layer_info_url(layer), {"f": "json"})
            return resp.json().get("fields") or []
        except (ArcGISError, ValueError):
            return []

    @staticmethod
    def _esc(value: str) -> str:
        return str(value).replace("'", "''")

    @staticmethod
    def _pick_field(fields: List[Dict[str, Any]], keywords: List[str]) -> Optional[str]:
        # Prefer string fields whose name/alias matches a keyword.
        for f in fields:
            name = (f.get("name") or "")
            alias = (f.get("alias") or "")
            hay = f"{name} {alias}".lower()
            if any(k in hay for k in keywords) and "id" not in name.lower()[-3:]:
                if str(f.get("type", "")).lower().find("string") >= 0 or not f.get("type"):
                    return name
        # Fall back to any field (incl. code fields) matching a keyword.
        for f in fields:
            hay = f"{f.get('name','')} {f.get('alias','')}".lower()
            if any(k in hay for k in keywords):
                return f.get("name")
        return None

    def _validate_where(self, layer: str, where: str) -> bool:
        """Return True if ``where`` is valid and matches at least one feature."""
        try:
            resp = self.raw_request(
                layer, {"f": "json", "where": where, "returnCountOnly": "true"}
            )
            data = resp.json()
            if not isinstance(data, dict) or data.get("error"):
                return False
            return int(data.get("count", 0)) > 0
        except Exception:  # noqa: BLE001
            return False

    def _build_where(self, layer: str) -> str:
        fields = self.get_layer_fields(layer)
        if not fields:
            return "1=1"
        region_f = self._pick_field(fields, ["region", "viloyat", "vil", "obl"])
        district_f = self._pick_field(fields, ["district", "tuman", "rayon", "rai"])

        region_clause = (
            f"UPPER({region_f}) LIKE UPPER('{self._esc(self.region)}%')"
            if region_f and self.region else None
        )
        district_clause = (
            f"UPPER({district_f}) LIKE UPPER('{self._esc(self.district)}%')"
            if district_f and self.district else None
        )

        # Prefer the most specific valid filter: region+district, then district,
        # then region. Validate each against the live layer to avoid zeroing out
        # results when field names/values do not match (then fall back to bbox).
        candidates = []
        if region_clause and district_clause:
            candidates.append(f"{region_clause} AND {district_clause}")
        if district_clause:
            candidates.append(district_clause)
        if region_clause:
            candidates.append(region_clause)
        for where in candidates:
            if self._validate_where(layer, where):
                log.info("ArcGIS filter for %s: %s", layer, where)
                return where
        log.warning(
            "No region/district attribute filter matched for %s; using bbox only "
            "(region=%s district=%s).", layer, self.region, self.district,
        )
        return "1=1"

    def _resolve_where(self, layer: str) -> str:
        if layer not in self._where_cache:
            self._where_cache[layer] = self._build_where(layer)
        return self._where_cache[layer]

    # ------------------------------------------------------------------ #
    # Boundary mask: clip results precisely to the region/district polygon.
    # ------------------------------------------------------------------ #
    def _query_boundary(self, border_url: str, name: str, keywords: List[str]):
        """Return a shapely (EPSG:3857) polygon for the admin unit, or None."""
        from shapely.geometry import shape as _shape
        from shapely.ops import unary_union

        try:
            finfo = self._request(border_url, {"f": "json"}).json()
        except (ArcGISError, ValueError):
            return None
        field = self._pick_field(finfo.get("fields") or [], keywords)
        if not field:
            return None
        params = {
            "f": "geojson",
            "where": f"UPPER({field}) LIKE UPPER('{self._esc(name)}%')",
            "outFields": field,
            "returnGeometry": "true",
            "outSR": config.ARCGIS_SR,
        }
        try:
            data = self._request(border_url + "/query", params).json()
        except (ArcGISError, ValueError):
            return None
        geoms = []
        for feat in data.get("features", []) or []:
            g = feat.get("geometry")
            if not g:
                continue
            try:
                geoms.append(_shape(g))
            except Exception:  # noqa: BLE001
                continue
        if not geoms:
            return None
        try:
            return unary_union(geoms)
        except Exception:  # noqa: BLE001
            return geoms[0]

    def _resolve_mask(self) -> None:
        if self._mask_resolved:
            return
        self._mask_resolved = True
        if not config.USE_BOUNDARY_MASK:
            return
        geom = None
        if self.district and config.ARCGIS_DISTRICT_BORDER_URL:
            geom = self._query_boundary(
                config.ARCGIS_DISTRICT_BORDER_URL, self.district,
                ["district", "tuman", "rayon", "nomi", "name"],
            )
        if geom is None and self.region and config.ARCGIS_REGION_BORDER_URL:
            geom = self._query_boundary(
                config.ARCGIS_REGION_BORDER_URL, self.region,
                ["region", "viloyat", "vil", "obl", "nomi", "name"],
            )
        if geom is None or geom.is_empty:
            return
        from shapely.prepared import prep
        from pyproj import Transformer

        self._mask = geom
        self._prepared = prep(geom)
        xmin, ymin, xmax, ymax = geom.bounds  # EPSG:3857
        t = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
        lon0, lat0 = t.transform(xmin, ymin)
        lon1, lat1 = t.transform(xmax, ymax)
        self._mask_bbox_4326 = (
            min(lon0, lon1), min(lat0, lat1), max(lon0, lon1), max(lat0, lat1)
        )
        log.info("Boundary mask resolved (%s/%s)", self.region, self.district)



    # ------------------------------------------------------------------ #
    # Feature query by bbox (compatible with the grid downloader)
    # ------------------------------------------------------------------ #
    def get_features_bbox(
        self,
        layer: str,
        bbox: Tuple[float, float, float, float],
        srs: str = config.SOURCE_CRS,
        cql_filter: Optional[str] = None,
        page_size: int = config.DEFAULT_PAGE_SIZE,
    ) -> List[Dict[str, Any]]:
        """Return GeoJSON features intersecting ``bbox`` (EPSG:3857 metres)."""
        xmin, ymin, xmax, ymax = bbox
        url = self._layer_query_url(layer)
        where = self._resolve_where(layer)
        self._resolve_mask()
        features: List[Dict[str, Any]] = []
        offset = 0
        max_pages = 200
        for _ in range(max_pages):
            params = {
                "f": "geojson",
                "where": where,
                "geometry": f"{xmin},{ymin},{xmax},{ymax}",
                "geometryType": "esriGeometryEnvelope",
                "inSR": config.ARCGIS_SR,
                "outSR": config.ARCGIS_SR,
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "*",
                "returnGeometry": "true",
                "returnExceededLimitFeatures": "true",
                "resultOffset": offset,
                "resultRecordCount": page_size,
            }
            resp = self._request(url, params)
            try:
                data = resp.json()
            except ValueError as exc:
                raise ArcGISError(f"Invalid JSON from ArcGIS: {exc}; {resp.text[:200]}")
            if isinstance(data, dict) and data.get("error"):
                raise ArcGISError(str(data["error"])[:300])

            page = data.get("features", []) or []
            for feat in page:
                _normalize_feature(feat)
                features.append(feat)

            exceeded = bool(data.get("exceededTransferLimit") or data.get("properties", {}).get("exceededTransferLimit"))
            if len(page) < page_size and not exceeded:
                break
            offset += len(page) if page else page_size
            if len(features) >= config.MAX_FEATURES_PER_CELL:
                log.warning("Cell hit MAX_FEATURES_PER_CELL; use a smaller grid.")
                break
        # Precisely clip to the region/district boundary when a mask is set.
        if self._prepared is not None and features:
            from shapely.geometry import shape as _shape

            kept = []
            for feat in features:
                g = feat.get("geometry")
                if not g:
                    continue
                try:
                    if self._prepared.intersects(_shape(g)):
                        kept.append(feat)
                except Exception:  # noqa: BLE001
                    kept.append(feat)
            features = kept
        return features

    # ------------------------------------------------------------------ #
    def get_layer_extent_4326(
        self, layer: str
    ) -> Optional[Tuple[float, float, float, float]]:
        # Prefer the resolved admin boundary bbox so the grid covers exactly the
        # selected region/district (not a padded region rectangle).
        self._resolve_mask()
        if self._mask_bbox_4326:
            return self._mask_bbox_4326
        try:
            resp = self._request(self._layer_info_url(layer), {"f": "json"})
            info = resp.json()
        except (ArcGISError, ValueError):
            return None
        ext = info.get("extent") or {}
        try:
            xmin, ymin = float(ext["xmin"]), float(ext["ymin"])
            xmax, ymax = float(ext["xmax"]), float(ext["ymax"])
        except (KeyError, TypeError, ValueError):
            return None
        wkid = ((ext.get("spatialReference") or {}).get("latestWkid")
                or (ext.get("spatialReference") or {}).get("wkid"))
        if wkid in (102100, 3857):
            from pyproj import Transformer
            t = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
            lon0, lat0 = t.transform(xmin, ymin)
            lon1, lat1 = t.transform(xmax, ymax)
            return (min(lon0, lon1), min(lat0, lat1), max(lon0, lon1), max(lat0, lat1))
        if wkid in (4326, None):
            return (xmin, ymin, xmax, ymax)
        return None



    # ------------------------------------------------------------------ #
    def list_services(self) -> List[Dict[str, str]]:
        """List FeatureServer services under the UZKAD folder."""
        try:
            resp = self._request(self.base_url, {"f": "json"})
            data = resp.json()
        except (ArcGISError, ValueError):
            return []
        out: List[Dict[str, str]] = []
        for svc in data.get("services", []) or []:
            if svc.get("type") == "FeatureServer":
                name = svc.get("name", "")
                short = name.split("/")[-1]
                out.append({"name": short, "full": name})
        return out


def _normalize_feature(feat: Dict[str, Any]) -> None:
    """Ensure a stable ``uid`` exists in properties for de-duplication."""
    props = feat.get("properties")
    if props is None:
        props = {}
        feat["properties"] = props
    if not props.get("uid"):
        for cand in (feat.get("id"), props.get("id"), props.get("objectid"),
                     props.get("OBJECTID")):
            if cand is not None:
                props["uid"] = cand
                break
