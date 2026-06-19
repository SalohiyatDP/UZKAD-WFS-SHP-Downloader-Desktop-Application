"""WFS GetFeature client for the UZKAD GeoServer.

Handles authenticated requests (cookies injected from a browser session),
BBOX-filtered GetFeature calls with paging, retries, and distinct-value
discovery used to dynamically populate region/district/layer dropdowns.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

from . import config
from .logging_setup import get_logger

log = get_logger("wfs")


class WFSError(RuntimeError):
    """Raised when the WFS service returns an unrecoverable error."""


class WFSClient:
    """Thin wrapper around requests for WFS 2.0.0 GetFeature operations."""

    def __init__(
        self,
        base_url: str = config.WFS_URL,
        cookies: Optional[Dict[str, str]] = None,
        timeout: int = config.REQUEST_TIMEOUT,
        proxy: Optional[str] = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.USER_AGENT,
                "Accept": "application/json, */*",
            }
        )
        if cookies:
            self.session.cookies.update(cookies)
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})

    # ------------------------------------------------------------------ #
    # Low level request helper with retry/backoff
    # ------------------------------------------------------------------ #
    def _request(self, params: Dict[str, Any]) -> requests.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(1, config.REQUEST_RETRIES + 1):
            try:
                resp = self.session.get(
                    self.base_url, params=params, timeout=self.timeout
                )
                if resp.status_code == 200:
                    return resp
                # 401/403 indicate an expired or missing session.
                if resp.status_code in (401, 403):
                    raise WFSError(
                        f"Authentication required (HTTP {resp.status_code}). "
                        "Open mulk.kadastr.uz in your browser and sign in."
                    )
                log.warning(
                    "WFS HTTP %s on attempt %s/%s",
                    resp.status_code,
                    attempt,
                    config.REQUEST_RETRIES,
                )
                last_exc = WFSError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            except (requests.RequestException, WFSError) as exc:
                last_exc = exc
                log.warning("WFS request error attempt %s: %s", attempt, exc)
            if attempt < config.REQUEST_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
        raise WFSError(f"WFS request failed after retries: {last_exc}")

    # ------------------------------------------------------------------ #
    # GetFeature with BBOX + paging
    # ------------------------------------------------------------------ #
    def get_features_bbox(
        self,
        layer: str,
        bbox: Tuple[float, float, float, float],
        srs: str = config.SOURCE_CRS,
        cql_filter: Optional[str] = None,
        page_size: int = config.DEFAULT_PAGE_SIZE,
    ) -> List[Dict[str, Any]]:
        """Return all GeoJSON features inside ``bbox`` for ``layer``.

        Uses WFS 2.0.0 startIndex/count paging so cells that exceed the server
        page limit are still fully retrieved.
        """
        xmin, ymin, xmax, ymax = bbox
        # WFS 2.0.0 expects BBOX as minx,miny,maxx,maxy,SRS for EPSG:3857.
        bbox_param = f"{xmin},{ymin},{xmax},{ymax},{srs}"

        features: List[Dict[str, Any]] = []
        start_index = 0
        while True:
            params: Dict[str, Any] = {
                "service": "WFS",
                "version": config.WFS_VERSION,
                "request": "GetFeature",
                "typeNames": layer,
                "outputFormat": config.OUTPUT_FORMAT,
                "srsName": srs,
                "bbox": bbox_param,
                "count": page_size,
                "startIndex": start_index,
            }
            if cql_filter:
                params["cql_filter"] = cql_filter

            resp = self._request(params)
            try:
                data = resp.json()
            except ValueError as exc:
                raise WFSError(f"Invalid JSON from WFS: {exc}; body={resp.text[:200]}")

            page = data.get("features", []) or []
            features.extend(page)

            if len(page) < page_size:
                break
            start_index += page_size
            if len(features) >= config.MAX_FEATURES_PER_CELL:
                log.warning(
                    "Cell hit MAX_FEATURES_PER_CELL (%s); consider a smaller grid.",
                    config.MAX_FEATURES_PER_CELL,
                )
                break
        return features

    # ------------------------------------------------------------------ #
    # Hits count (cheap GetFeature with resultType=hits)
    # ------------------------------------------------------------------ #
    def count_features(
        self, layer: str, cql_filter: Optional[str] = None
    ) -> Optional[int]:
        params: Dict[str, Any] = {
            "service": "WFS",
            "version": config.WFS_VERSION,
            "request": "GetFeature",
            "typeNames": layer,
            "resultType": "hits",
        }
        if cql_filter:
            params["cql_filter"] = cql_filter
        try:
            resp = self._request(params)
        except WFSError:
            return None
        # GeoServer returns numberMatched / numberOfFeatures in XML for hits.
        text = resp.text
        for token in ("numberMatched=", "numberOfFeatures="):
            idx = text.find(token)
            if idx != -1:
                start = idx + len(token) + 1
                end = text.find('"', start)
                try:
                    return int(text[start:end])
                except ValueError:
                    continue
        return None

    # ------------------------------------------------------------------ #
    # Distinct values - used to populate dropdowns dynamically
    # ------------------------------------------------------------------ #
    def get_distinct_values(
        self, layer: str, attribute: str, cql_filter: Optional[str] = None
    ) -> List[str]:
        """Fetch distinct values of ``attribute`` using a property-only query.

        Falls back to scanning a page of features when the server does not
        support GROUP BY on the WFS endpoint.
        """
        params: Dict[str, Any] = {
            "service": "WFS",
            "version": config.WFS_VERSION,
            "request": "GetFeature",
            "typeNames": layer,
            "outputFormat": config.OUTPUT_FORMAT,
            "propertyName": attribute,
            "count": 10000,
        }
        if cql_filter:
            params["cql_filter"] = cql_filter
        resp = self._request(params)
        try:
            data = resp.json()
        except ValueError as exc:
            raise WFSError(f"Invalid JSON for distinct values: {exc}")
        values = set()
        for feat in data.get("features", []) or []:
            val = (feat.get("properties") or {}).get(attribute)
            if val not in (None, ""):
                values.add(str(val))
        return sorted(values)

    def describe_layer_attributes(self, layer: str) -> List[str]:
        """DescribeFeatureType to learn the real attribute list of a layer."""
        params = {
            "service": "WFS",
            "version": config.WFS_VERSION,
            "request": "DescribeFeatureType",
            "typeNames": layer,
            "outputFormat": "application/json",
        }
        try:
            resp = self._request(params)
            data = resp.json()
        except (WFSError, ValueError):
            return list(config.DEFAULT_ATTRIBUTES)
        attrs: List[str] = []
        for ft in data.get("featureTypes", []):
            for prop in ft.get("properties", []):
                name = prop.get("name")
                if name and name != config.GEOMETRY_FIELD:
                    attrs.append(name)
        return attrs or list(config.DEFAULT_ATTRIBUTES)


def build_region_filter(region: Optional[str], district: Optional[str]) -> Optional[str]:
    """Build a CQL filter from region/district selections.

    ``district`` of None / 'Hammasi' (all) restricts only by region.
    """
    clauses: List[str] = []
    if region:
        clauses.append(f"region='{_escape(region)}'")
    if district and district.lower() not in ("hammasi", "all", "barchasi"):
        clauses.append(f"district='{_escape(district)}'")
    return " AND ".join(clauses) if clauses else None


def _escape(value: str) -> str:
    """Escape single quotes for CQL string literals."""
    return value.replace("'", "''")
