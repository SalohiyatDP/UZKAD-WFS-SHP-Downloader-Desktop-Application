"""Offline verification of the core backend pipeline.

Mocks the WFS client so no network/auth is needed, then runs:
grid generation -> parallel download -> WKB conversion -> SQLite dedup ->
export to GeoJSON/GPKG/SHP. Run with:  python -m tests.test_pipeline
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Ensure the package is importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.grid_generator import (  # noqa: E402
    bbox_4326_to_3857,
    estimate_cell_count,
    generate_grid,
)
from app.database import FeatureDB, make_dedup_key  # noqa: E402
from app.downloader import GridDownloader  # noqa: E402
from app.exporter import Exporter  # noqa: E402
from app.regions import get_region, list_regions  # noqa: E402
from app.wfs_client import build_region_filter  # noqa: E402


def _square(x: float, y: float, size: float = 100.0) -> dict:
    return {
        "type": "MultiPolygon",
        "coordinates": [[[[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]]],
    }


class FakeWFS:
    """Returns deterministic features, including cross-cell duplicates."""

    def __init__(self) -> None:
        self.calls = 0

    def get_features_bbox(self, layer, bbox, cql_filter=None, **kw):
        self.calls += 1
        xmin, ymin, xmax, ymax = bbox
        cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
        # Two unique features per cell, plus one shared duplicate across all cells.
        return [
            {
                "id": f"f{self.calls}a",
                "geometry": _square(cx, cy),
                "properties": {
                    "uid": f"uid-{self.calls}-a",
                    "cadastral_number": f"06:{self.calls:03d}:001",
                    "region": "Namangan",
                    "district": "Chust",
                    "legal_area": 100.5,
                    "gis_area": 99.8,
                    "property_kind": "land",
                },
            },
            {
                "id": f"f{self.calls}b",
                "geometry": _square(cx + 10, cy + 10),
                "properties": {
                    "uid": f"uid-{self.calls}-b",
                    "cadastral_number": f"06:{self.calls:03d}:002",
                    "region": "Namangan",
                    "district": "Chust",
                    "legal_area": 200.0,
                    "gis_area": 198.0,
                    "property_kind": "building",
                },
            },
            {  # duplicate shared by every cell -> must be deduped to one row
                "id": "shared",
                "geometry": _square(cx, cy),
                "properties": {
                    "uid": "uid-shared",
                    "cadastral_number": "06:999:999",
                    "region": "Namangan",
                    "district": "Chust",
                    "legal_area": 1.0,
                    "gis_area": 1.0,
                    "property_kind": "land",
                },
            },
        ]


def assert_eq(name, got, want):
    status = "OK " if got == want else "FAIL"
    print(f"  [{status}] {name}: got={got} want={want}")
    if got != want:
        raise AssertionError(f"{name}: {got} != {want}")


def main() -> int:
    print("== Reference data ==")
    regions = list_regions()
    assert_eq("region count (14)", len(regions), 14)
    nm = get_region("Namangan")
    assert nm is not None
    print(f"  Namangan bbox_4326 = {nm['bbox_4326']}")

    print("== CQL filter ==")
    cql = build_region_filter("Namangan", "Chust")
    assert_eq("cql", cql, "region='Namangan' AND district='Chust'")
    assert_eq("cql all-districts", build_region_filter("Namangan", "Hammasi"),
              "region='Namangan'")

    print("== Grid generation ==")
    bbox3857 = bbox_4326_to_3857((71.0, 41.0, 71.05, 41.05))
    cells = generate_grid(bbox3857, 1000.0)
    print(f"  {len(cells)} cells for a small 0.05deg box at 1000m")
    assert len(cells) >= 4
    est = estimate_cell_count((71.0, 41.0, 71.05, 41.05), 1000.0)
    print(f"  estimate_cell_count = {est}")

    print("== make_dedup_key ==")
    assert_eq("uid key", make_dedup_key({"uid": "X", "cadastral_number": "Y"}), "uid:X")
    assert_eq("cad fallback", make_dedup_key({"cadastral_number": "Y"}), "cadastral_number:Y")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        db = FeatureDB(tmp / "features.sqlite")

        print("== Downloader (mocked WFS, parallel) ==")
        dl = GridDownloader(FakeWFS(), db, progress_cb=None)
        stats = dl.run(
            layers=["uzbekistan:all_pending_spatial_units"],
            region="Namangan",
            district="Chust",
            grid_size=1000,
            max_workers=8,
        )
        n_cells = stats.total_cells
        print(f"  total_cells={n_cells} found={stats.features_found} "
              f"stored={stats.features_stored} dupes={stats.duplicates_removed} "
              f"state={stats.state}")
        # Each cell yields 3 features; unique = 2*n_cells + 1 shared.
        assert_eq("features_found", stats.features_found, n_cells * 3)
        assert_eq("features_stored (unique)", stats.features_stored, n_cells * 2 + 1)
        assert_eq("state", stats.state, "completed")
        assert_eq("db count", db.count_features(), n_cells * 2 + 1)

        print("== Resume bookkeeping ==")
        done = db.completed_cells(stats.job_id)
        assert_eq("completed cells recorded", len(done), n_cells)
        last = db.get_last_job()
        assert last and last["region"] == "Namangan"
        print(f"  last job: {last['job_id']} {last['region']}/{last['district']}")

        print("== Export ==")
        exporter = Exporter(db, out_dir=tmp / "exports")
        files = exporter.export(
            formats=["geojson", "gpkg", "shp"],
            region="Namangan",
            district="Chust",
            export_crs="EPSG:4326",
        )
        for f in files:
            p = Path(f)
            print(f"  produced {p.name} ({p.stat().st_size} bytes)")
            assert p.exists() and p.stat().st_size > 0
        assert any(f.endswith(".zip") for f in files), "SHP zip missing"
        assert any(f.endswith(".geojson") for f in files)
        assert any(f.endswith(".gpkg") for f in files)

        db.close()

    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
