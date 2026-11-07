"""Steps 7 and 9 find the rasters of step 3, whole or as the mosaic of a unit run."""

from pathlib import Path

from core.active_run import ACTIVE_RUN_FILE, clear_active_run, write_active_run
from scripts.bootstrap import _saved_raster


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def test_a_raster_of_the_whole_run_is_a_geotiff_in_the_nmt_directory(tmp_path):
    tif = _touch(tmp_path / "dem_mosaic_02_filled.tif")

    assert _saved_raster(tmp_path, "02_filled") == tif


def test_the_active_unit_run_gives_its_vrt_mosaic_over_an_older_geotiff(tmp_path):
    tif = _touch(tmp_path / "dem_mosaic_07_stream_order.tif")
    vrt = _touch(tmp_path / "unit_runs" / "abc" / "dem_mosaic_07_stream_order.vrt")
    write_active_run(tmp_path, 4, vrt.parent)

    assert _saved_raster(tmp_path, "07_stream_order") == vrt

    # A run of the whole raster removes the pointer: its GeoTIFF is the raster again
    clear_active_run(tmp_path)
    assert _saved_raster(tmp_path, "07_stream_order") == tif


def test_a_unit_run_that_is_not_active_is_not_read(tmp_path):
    _touch(tmp_path / "unit_runs" / "abc" / "dem_mosaic_02_filled.vrt")
    _touch(tmp_path / "active_run" / "dem_mosaic_02_filled.vrt")  # the old link

    assert _saved_raster(tmp_path, "02_filled") is None


def test_a_dangling_pointer_falls_back_to_the_geotiff(tmp_path):
    tif = _touch(tmp_path / "dem_mosaic_02_filled.tif")
    (tmp_path / ACTIVE_RUN_FILE).write_text('{"run_id": 4, "run_dir": "unit_runs/x"}')

    assert _saved_raster(tmp_path, "02_filled") == tif


def test_a_raster_that_was_not_saved_is_none(tmp_path):
    vrt = _touch(tmp_path / "unit_runs" / "abc" / "dem_mosaic_02_filled.vrt")
    write_active_run(tmp_path, 4, vrt.parent)

    assert _saved_raster(tmp_path, "07_stream_order") is None
