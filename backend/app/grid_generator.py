"""Grid generation for the BBOX-based bulk downloader.

Given a region bounding box, the territory is subdivided into square cells of a
configurable size (metres, in EPSG:3857). Each cell becomes one WFS GetFeature
BBOX request, which sidesteps GeoServer maxFeatures / paging limits when
collecting a whole region.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

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
    bbox_4326: Tuple[float, float, float, float], cell_size_m: float
) -> List[GridCell]:
    """Convenience: convert a 4326 region bbox then build the 3857 grid."""
    return generate_grid(bbox_4326_to_3857(bbox_4326), cell_size_m)


def estimate_cell_count(
    bbox_4326: Tuple[float, float, float, float], cell_size_m: float
) -> int:
    """Cheap estimate of how many cells a grid will contain."""
    xmin, ymin, xmax, ymax = bbox_4326_to_3857(bbox_4326)
    nx = max(1, int((xmax - xmin) // cell_size_m) + 1)
    ny = max(1, int((ymax - ymin) // cell_size_m) + 1)
    return nx * ny
