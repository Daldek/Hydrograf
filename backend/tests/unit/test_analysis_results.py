"""Tests for core.analysis_results (water levels along a terrain profile)."""

import json

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin

from core.analysis_results import sample_water_levels

NODATA = -9999.0
X0, Y_TOP, CELL = 500000.0, 600000.0, 5.0
# Centres of the four cells of the test raster (one row)
CENTRES = [(X0 + CELL * (i + 0.5), Y_TOP - CELL / 2) for i in range(4)]


def _write_raster(path, data, transform, crs="EPSG:2180"):
    data = np.asarray(data, dtype=np.float32)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=NODATA,
    ) as dst:
        dst.write(data, 1)


def _write_manifest(data_dir, results):
    results_dir = data_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "index.json").write_text(
        json.dumps({"schema": "hydrograf-results/1", "results": results})
    )


def _result(result_id, path):
    return {
        "id": result_id,
        "kind": "raster_tiles",
        "water_level": {"path": path, "crs": "EPSG:2180", "unit": "m n.p.m."},
    }


@pytest.fixture
def data_dir(tmp_path):
    """frontend/data with one result whose water level raster has wet and dry cells."""
    raster_dir = tmp_path / "results" / "sfincs"
    raster_dir.mkdir(parents=True)
    _write_raster(
        raster_dir / "wse_max.tif",
        [[250.5, NODATA, np.nan, 251.25]],
        from_origin(X0, Y_TOP, CELL, CELL),
    )
    _write_manifest(tmp_path, [_result("sfincs", "/data/results/sfincs/wse_max.tif")])
    return tmp_path


class TestSampleWaterLevels:
    def test_levels_follow_the_samples(self, data_dir):
        """Wet cells give the level; nodata, NaN and points off the raster None."""
        outside = (X0 - 10.0, Y_TOP - CELL / 2)
        profiles = sample_water_levels(str(data_dir), ["sfincs"], [*CENTRES, outside])

        assert profiles == [("sfincs", [250.5, None, None, 251.25, None])]

    def test_result_off_the_line_is_left_out(self, data_dir):
        far = [(X0 + 1000.0, Y_TOP + 1000.0), (X0 + 1100.0, Y_TOP + 1000.0)]

        assert sample_water_levels(str(data_dir), ["sfincs"], far) == []

    def test_only_requested_results_with_a_water_level(self, data_dir):
        _write_manifest(
            data_dir,
            [
                _result("sfincs", "/data/results/sfincs/wse_max.tif"),
                {"id": "depth-only", "kind": "raster_tiles"},
            ],
        )

        assert (
            sample_water_levels(str(data_dir), ["depth-only", "unknown"], CENTRES) == []
        )
        assert [
            p[0] for p in sample_water_levels(str(data_dir), ["sfincs"], CENTRES)
        ] == ["sfincs"]

    def test_path_outside_results_dir_is_refused(self, data_dir):
        """A manifest path escaping frontend/data/results is never opened."""
        _write_raster(
            data_dir / "secret.tif",
            [[1.0, 1.0, 1.0, 1.0]],
            from_origin(X0, Y_TOP, CELL, CELL),
        )
        _write_manifest(data_dir, [_result("evil", "/data/results/../secret.tif")])

        assert sample_water_levels(str(data_dir), ["evil"], CENTRES) == []

    def test_missing_manifest_gives_no_levels(self, tmp_path):
        assert sample_water_levels(str(tmp_path), ["sfincs"], CENTRES) == []

    def test_raster_in_another_crs_is_sampled_at_the_same_place(self, data_dir):
        lon, lat = Transformer.from_crs(
            "EPSG:2180", "EPSG:4326", always_xy=True
        ).transform(*CENTRES[0])
        _write_raster(
            data_dir / "results" / "sfincs" / "wse_4326.tif",
            [[300.0]],
            from_origin(lon - 0.001, lat + 0.001, 0.002, 0.002),
            crs="EPSG:4326",
        )
        _write_manifest(data_dir, [_result("geo", "/data/results/sfincs/wse_4326.tif")])

        assert sample_water_levels(str(data_dir), ["geo"], CENTRES[:1]) == [
            ("geo", [300.0])
        ]
