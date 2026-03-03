"""Tests for core.raster_io module."""

from pathlib import Path

import numpy as np
import pytest

from core.raster_io import read_ascii_grid, save_raster_geotiff


class TestReadAsciiGrid:
    """Tests for read_ascii_grid function."""

    def _write_asc(self, path: Path, content: str):
        path.write_text(content)

    def test_reads_valid_asc(self, tmp_path):
        asc_file = tmp_path / "test.asc"
        self._write_asc(
            asc_file,
            "ncols 3\nnrows 2\nxllcorner 500000\nyllcorner 500000\n"
            "cellsize 1.0\nNODATA_value -9999\n"
            "1 2 3\n4 5 6\n",
        )
        dem, meta = read_ascii_grid(asc_file)
        assert dem.shape == (2, 3)
        assert meta["ncols"] == 3
        assert meta["nrows"] == 2
        assert meta["cellsize"] == 1.0
        assert meta["nodata_value"] == -9999.0
        assert dem[0, 0] == pytest.approx(1.0)
        assert dem[1, 2] == pytest.approx(6.0)

    def test_nodata_handling(self, tmp_path):
        asc_file = tmp_path / "test.asc"
        self._write_asc(
            asc_file,
            "ncols 2\nnrows 2\nxllcorner 0\nyllcorner 0\n"
            "cellsize 10\nNODATA_value -9999\n"
            "1 -9999\n3 4\n",
        )
        dem, meta = read_ascii_grid(asc_file)
        assert dem[0, 1] == pytest.approx(-9999.0)

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            read_ascii_grid(Path("/nonexistent/file.asc"))


class TestSaveRasterGeotiff:
    """Tests for save_raster_geotiff function."""

    def test_saves_and_is_valid(self, tmp_path):
        import rasterio

        dem = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
        metadata = {
            "xllcorner": 500000.0,
            "yllcorner": 500000.0,
            "cellsize": 1.0,
            "ncols": 2,
            "nrows": 2,
            "nodata_value": -9999.0,
        }
        out_path = tmp_path / "test.tif"
        save_raster_geotiff(
            dem,
            metadata,
            out_path,
            nodata=-9999,
            dtype="float32",
        )
        assert out_path.exists()

        with rasterio.open(out_path) as src:
            data = src.read(1)
            assert data.shape == (2, 2)
            assert src.crs.to_epsg() == 2180
