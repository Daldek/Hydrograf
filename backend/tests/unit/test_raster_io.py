"""Tests for core.raster_io module."""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin, rowcol

from core.raster_io import read_ascii_grid, read_raster_window, save_raster_geotiff


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


# A 6 x 16 grid of 10 m cells whose values tell their place: 100 * row + col
X0, Y_TOP, CELL, NODATA = 500000.0, 600000.0, 10.0, -9999.0
GRID = (100.0 * np.arange(6)[:, None] + np.arange(16)[None, :]).astype(np.float32)


def _write_tif(path, values, west=X0, nodata=NODATA):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=from_origin(west, Y_TOP, CELL, CELL),
        nodata=nodata,
    ) as dst:
        dst.write(values, 1)
    return path


def _write_vrt(path, tiles):
    """VRT mosaic of GRID from GeoTIFF tiles given as (file name, first column)."""
    rows, cols = GRID.shape
    sources = []
    for i, (name, col) in enumerate(tiles):
        width = (tiles[i + 1][1] if i + 1 < len(tiles) else cols) - col
        sources.append(
            "<SimpleSource>"
            f'<SourceFilename relativeToVRT="1">{name}</SourceFilename>'
            "<SourceBand>1</SourceBand>"
            f'<SrcRect xOff="0" yOff="0" xSize="{width}" ySize="{rows}"/>'
            f'<DstRect xOff="{col}" yOff="0" xSize="{width}" ySize="{rows}"/>'
            "</SimpleSource>"
        )
    path.write_text(
        f'<VRTDataset rasterXSize="{cols}" rasterYSize="{rows}">'
        f"<GeoTransform>{X0}, {CELL}, 0.0, {Y_TOP}, 0.0, {-CELL}</GeoTransform>"
        '<VRTRasterBand dataType="Float32" band="1">'
        f"<NoDataValue>{NODATA}</NoDataValue>{''.join(sources)}"
        "</VRTRasterBand></VRTDataset>"
    )
    return path


def _on_grid(window):
    """GRID under the centre of each cell of the window, NODATA off it."""
    expected = np.full(window.data.shape, NODATA, dtype=np.float32)
    for r, c in np.ndindex(window.data.shape):
        x, y = window.transform * (c + 0.5, r + 0.5)
        row, col = int((Y_TOP - y) // CELL), int((x - X0) // CELL)
        if 0 <= row < GRID.shape[0] and 0 <= col < GRID.shape[1]:
            expected[r, c] = GRID[row, col]
    return expected


def _centre(row, col):
    return X0 + (col + 0.5) * CELL, Y_TOP - (row + 0.5) * CELL


class TestReadRasterWindow:
    """Tests for read_raster_window (the reads of the API at query time)."""

    @pytest.fixture(params=["GeoTIFF", "VRT of two tiles"])
    def raster(self, request, tmp_path):
        """GRID as one GeoTIFF or as a VRT of a west and an east tile."""
        if request.param == "GeoTIFF":
            return _write_tif(tmp_path / "dem.tif", GRID)
        _write_tif(tmp_path / "west.tif", GRID[:, :7].copy())
        _write_tif(tmp_path / "east.tif", GRID[:, 7:].copy(), west=X0 + 7 * CELL)
        return _write_vrt(tmp_path / "dem.vrt", [("west.tif", 0), ("east.tif", 7)])

    def test_window_inside_holds_the_cells_of_the_bounds_and_one_more(self, raster):
        """From the centre of cell (2, 3) to the centre of cell (3, 9)."""
        (x0, y1), (x1, y0) = _centre(2, 3), _centre(3, 9)

        window = read_raster_window(raster, (x0, y0, x1, y1))

        assert np.array_equal(window.data, GRID[1:5, 2:11])
        assert window.transform * (0, 0) == (X0 + 2 * CELL, Y_TOP - CELL)
        assert window.nodata == NODATA

    def test_window_crossing_the_edge_is_filled_with_nodata(self, raster):
        """Around the south-east corner: 3 x 3 cells on the raster."""
        (x0, y1), (x1, y0) = _centre(4, 14), _centre(7, 17)

        window = read_raster_window(raster, (x0, y0, x1, y1))

        assert window.data.shape == (6, 6)
        assert np.array_equal(window.data, _on_grid(window))
        assert np.array_equal(window.data[:3, :3], GRID[3:, 13:])
        assert (window.data != NODATA).sum() == 9

    def test_window_off_the_raster_is_all_nodata(self, raster):
        x, y = _centre(-20, 40)

        window = read_raster_window(raster, (x, y, x + 2 * CELL, y + CELL))

        assert window.data.shape == (4, 5)
        assert np.all(window.data == NODATA)
        assert window.transform * (0, 0) == (X0 + 39 * CELL, Y_TOP + 22 * CELL)

    def test_margin_widens_the_window(self, raster):
        x, y = _centre(2, 3)

        window = read_raster_window(raster, (x, y, x, y), margin_m=2 * CELL)

        assert window.data.shape == (7, 7)
        assert window.transform * (0, 0) == (X0, Y_TOP + CELL)
        assert np.array_equal(window.data, _on_grid(window))

    def test_points_on_the_edges_of_the_bounds_lie_in_the_window(self, raster):
        """Bounds on cell edges: a point on the east or south edge is in the
        next cell, which the window holds too."""
        bounds = (X0 + 2 * CELL, Y_TOP - 5 * CELL, X0 + 6 * CELL, Y_TOP - CELL)
        xs = [bounds[0], bounds[2], bounds[0], bounds[2]]
        ys = [bounds[1], bounds[1], bounds[3], bounds[3]]

        window = read_raster_window(raster, bounds)

        rows, cols = rowcol(window.transform, xs, ys)
        assert np.all((rows >= 0) & (rows < window.data.shape[0]))
        assert np.all((cols >= 0) & (cols < window.data.shape[1]))
        grid_rows, grid_cols = rowcol(from_origin(X0, Y_TOP, CELL, CELL), xs, ys)
        assert np.array_equal(window.data[rows, cols], GRID[grid_rows, grid_cols])

    def test_raster_without_nodata_is_filled_with_zero(self, tmp_path):
        path = _write_tif(tmp_path / "slope.tif", GRID, nodata=None)
        x, y = _centre(0, 0)

        window = read_raster_window(path, (x, y, x, y))

        assert window.nodata is None
        assert np.array_equal(window.data[0], [0.0, 0.0, 0.0])
        assert np.array_equal(window.data[1:, 1:], GRID[:2, :2])
