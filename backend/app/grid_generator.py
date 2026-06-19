"""Grid generation for the BBOX-based bulk downloader.

Given a region bounding box, the territory is subdivided into square cells of a
configurable size (metres, in EPSG:3857). Each cell becomes one WFS GetFeature
BBOX request, which sidesteps GeoServer maxFeatures / paging limits when
collecting a whole region.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from pyproj import Transformer

from .logging_setup import get_logger

log = get_logger("grid")

# Lazily-created transformer 4326 -> 3857.
_T_4326_TO_3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)


@dataclass(frozen=True)
class GridCell:
    index: int
    bbox: Tuple[float, float, float, float]  # xmin, ymin, xmax, ymax (EPSG:3857)


def bbox_4326_to_3857(
    bbox_4326: Tuple[float, float, float, float]
) -> Tuple[float, float, float, float]:
    """Convert a lon/lat bbox to Web Mercator metres."""
    min_lon, min_lat, max_lon, max_lat = bbox_4326
    xmin, ymin = _T_4326_TO_3857.transform(min_lon, min_lat)
    xmax, ymax = _T_4326_TO_3857.transform(max_lon, max_lat)
    return (min(xmin, xmax), min(ymin, ymax), max(xmin, xmax), max(ymin, ymax))


def generate_grid(
    bbox_3857: Tuple[float, float, float, float], cell_size_m: float
) -> List[GridCell]:
    """Split a Web-Mercator bbox into square cells of ``cell_size_m`` metres."""
    if cell_size_m <= 0:
        raise ValueError("cell_size_m must be positive")

    xmin, ymin, xmax, ymax = bbox_3857
    if xmax <= xmin or ymax <= ymin:
        raise ValueError(f"Invalid bbox: {bbox_3857}")

    cells: List[GridCell] = []
    index = 0
    y = ymin
    while y < ymax:
        cy_max = min(y + cell_size_m, ymax)
        x = xmin
        while x < xmax:
            cx_max = min(x + cell_size_m, xmax)
            cells.append(GridCell(index=index, bbox=(x, y, cx_max, cy_max)))
            index += 1
            x += cell_size_m
        y += cell_size_m

    log.info(
        "Generated %s grid cells (cell=%sm) for bbox %s",
        len(cells),
        cell_size_m,
        tuple(round(v, 1) for v in bbox_3857),
    )
    return cells


def grid_for_region_bbox_4326(
    bbox_4326: Tuple[float, float, float, float],
    cell_size_m: float,
    padding_deg: float = 0.0,
    clamp_to: Optional[Tuple[float, float, float, float]] = None,
) -> List[GridCell]:
    """Convert a 4326 region bbox (optionally padded/clamped) then build the grid.

    ``padding_deg`` expands the region box so approximate extents never clip
    edge features. ``clamp_to`` (e.g. the layer's full WGS84 extent) bounds the
    padded box so we never grid empty ocean far outside the data.
    """
    bbox = pad_bbox_4326(bbox_4326, padding_deg)
    if clamp_to:
        bbox = _intersect_bbox(bbox, clamp_to) or bbox
    return generate_grid(bbox_4326_to_3857(bbox), cell_size_m)


def pad_bbox_4326(
    bbox_4326: Tuple[float, float, float, float], padding_deg: float
) -> Tuple[float, float, float, float]:
    if padding_deg <= 0:
        return bbox_4326
    min_lon, min_lat, max_lon, max_lat = bbox_4326
    return (
        min_lon - padding_deg,
        min_lat - padding_deg,
        max_lon + padding_deg,
        max_lat + padding_deg,
    )


def _intersect_bbox(
    a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]
) -> Optional[Tuple[float, float, float, float]]:
    min_lon = max(a[0], b[0])
    min_lat = max(a[1], b[1])
    max_lon = min(a[2], b[2])
    max_lat = min(a[3], b[3])
    if max_lon <= min_lon or max_lat <= min_lat:
        return None
    return (min_lon, min_lat, max_lon, max_lat)


def estimate_cell_count(
    bbox_4326: Tuple[float, float, float, float], cell_size_m: float
) -> int:
    """Cheap estimate of how many cells a grid will contain."""
    xmin, ymin, xmax, ymax = bbox_4326_to_3857(bbox_4326)
    nx = max(1, int((xmax - xmin) // cell_size_m) + 1)
    ny = max(1, int((ymax - ymin) // cell_size_m) + 1)
    return nx * ny
