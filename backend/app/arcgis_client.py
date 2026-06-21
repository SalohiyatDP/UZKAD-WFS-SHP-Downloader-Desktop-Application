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
    ) -> None:
        self.base_url = (base_url or config.ARCGIS_BASE).rstrip("/")
        self.timeout = timeout
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
        features: List[Dict[str, Any]] = []
        offset = 0
        max_pages = 200
        for _ in range(max_pages):
            params = {
                "f": "geojson",
                "where": "1=1",
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
        return features

    # ------------------------------------------------------------------ #
    def get_layer_extent_4326(
        self, layer: str
    ) -> Optional[Tuple[float, float, float, float]]:
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
