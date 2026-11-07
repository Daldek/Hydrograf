"""Steps 7 and 9 find the rasters of step 3, whole or as the mosaic of a unit run."""

import os
from pathlib import Path

from scripts.bootstrap import _saved_raster


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_a_raster_of_the_whole_run_is_a_geotiff_in_the_nmt_directory(tmp_path):
    tif = _touch(tmp_path / "dem_mosaic_02_filled.tif")

    assert _saved_raster(tmp_path, "02_filled") == tif


def test_a_unit_run_leaves_the_vrt_mosaic_in_the_active_run(tmp_path):
    vrt = _touch(tmp_path / "active_run" / "dem_mosaic_02_filled.vrt")

    assert _saved_raster(tmp_path, "02_filled") == vrt


def test_the_raster_of_the_later_run_wins(tmp_path):
    tif = _touch(tmp_path / "dem_mosaic_07_stream_order.tif")
    vrt = _touch(tmp_path / "active_run" / "dem_mosaic_07_stream_order.vrt")
    os.utime(tif, (1_000, 1_000))
    os.utime(vrt, (2_000, 2_000))
    assert _saved_raster(tmp_path, "07_stream_order") == vrt

    os.utime(tif, (3_000, 3_000))
    assert _saved_raster(tmp_path, "07_stream_order") == tif


def test_a_raster_that_was_not_saved_is_none(tmp_path):
    _touch(tmp_path / "active_run" / "dem_mosaic_02_filled.vrt")

    assert _saved_raster(tmp_path, "07_stream_order") is None
