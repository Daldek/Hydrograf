"""Tests for core.raster_service: the precise delineation in a window of the rasters.

The rasters are synthetic and carry the names of the pipeline in one directory:
the flow directions ``dem_mosaic_03_flowdir.tif`` (int16, 0 for no data and for
pits, as the pipeline saves them) and the DEM ``dem_mosaic.vrt`` (a VRT of two
GeoTIFF tiles, as the mosaic of the NMT sheets). The reference is the
delineation on the whole rasters: pyflwdir's basin of the cell of the point, as
the precise mode computed it before it read windows.
"""

from unittest.mock import patch

import numpy as np
import pyflwdir
import pytest
import rasterio
from rasterio.features import shapes
from rasterio.transform import Affine, from_origin
from shapely.geometry import Point, shape
from shapely.ops import unary_union

from core.config import Settings
from core.errors import StoreUnavailableError, UnsupportedError
from core.raster_service import delineate_from_point

X0, Y_TOP, CELL = 500000.0, 600000.0, 10.0
TRANSFORM = from_origin(X0, Y_TOP, CELL, CELL)
DEM_NODATA = -9999.0
# D8 codes of the pipeline (core.hydrology.D8_DIRECTIONS)
E, S, W, N = 1, 4, 16, 64


def _write_tif(path, values, nodata, transform=TRANSFORM):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype=values.dtype,
        crs="EPSG:2180",
        transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(values, 1)


def _write_dem(directory, dem, transform=TRANSFORM):
    """The DEM as ``dem_mosaic.vrt`` of a west and an east GeoTIFF tile."""
    rows, cols = dem.shape
    split = cols // 2
    _write_tif(directory / "west.tif", dem[:, :split].copy(), DEM_NODATA, transform)
    _write_tif(
        directory / "east.tif",
        dem[:, split:].copy(),
        DEM_NODATA,
        transform * Affine.translation(split, 0),
    )
    sources = "".join(
        "<SimpleSource>"
        f'<SourceFilename relativeToVRT="1">{name}</SourceFilename>'
        "<SourceBand>1</SourceBand>"
        f'<SrcRect xOff="0" yOff="0" xSize="{width}" ySize="{rows}"/>'
        f'<DstRect xOff="{col}" yOff="0" xSize="{width}" ySize="{rows}"/>'
        "</SimpleSource>"
        for name, col, width in (
            ("west.tif", 0, split),
            ("east.tif", split, cols - split),
        )
    )
    geotransform = ", ".join(map(repr, transform.to_gdal()))
    (directory / "dem_mosaic.vrt").write_text(
        f'<VRTDataset rasterXSize="{cols}" rasterYSize="{rows}">'
        f"<GeoTransform>{geotransform}</GeoTransform>"
        '<VRTRasterBand dataType="Float32" band="1">'
        f"<NoDataValue>{DEM_NODATA}</NoDataValue>{sources}"
        "</VRTRasterBand></VRTDataset>"
    )


class Rasters:
    """The rasters of a test in ``directory``, with their settings."""

    def __init__(self, directory, fdir, dem):
        self.fdir, self.dem = fdir, dem
        _write_tif(directory / "dem_mosaic_03_flowdir.tif", fdir, 0)
        _write_dem(directory, dem)
        self.settings = Settings(dem_dir=str(directory), dem_path="")

    def delineate(self, row, col, bounds=None, **kwargs):
        """Delineate from the centre of cell (row, col); bounds: the point alone."""
        x, y = _centre(row, col)
        with patch("core.raster_service.get_settings", return_value=self.settings):
            return delineate_from_point(x, y, bounds or (x, y, x, y), **kwargs)

    def whole(self, row, col):
        """The mask, polygon and statistics of the delineation on the whole rasters."""
        d8 = self.fdir.astype(np.uint8)
        d8[self.dem == DEM_NODATA] = 247
        d8[row, col] = 0
        flw = pyflwdir.from_array(d8, ftype="d8", transform=TRANSFORM, latlon=False)
        mask = flw.basins(idxs=[np.ravel_multi_index((row, col), d8.shape)]) > 0
        polygon = unary_union(
            [
                shape(geom)
                for geom, value in shapes(mask.astype(np.uint8), transform=TRANSFORM)
                if value == 1
            ]
        )
        elevations = self.dem[mask & (self.dem != DEM_NODATA)]
        stats = {
            "area_m2": mask.sum() * CELL * CELL,
            "elevation_min_m": elevations.min(),
            "elevation_max_m": elevations.max(),
            "elevation_mean_m": elevations.mean(),
        }
        return mask, polygon, stats


def _centre(row, col):
    return X0 + (col + 0.5) * CELL, Y_TOP - (row + 0.5) * CELL


def _bounds(mask):
    """Bounding box of the cells of the mask, as ST_Extent of their polygons."""
    rows, cols = np.nonzero(mask)
    return (
        X0 + cols.min() * CELL,
        Y_TOP - (rows.max() + 1) * CELL,
        X0 + (cols.max() + 1) * CELL,
        Y_TOP - rows.min() * CELL,
    )


def _assert_same(result, polygon, stats):
    assert result["polygon"].equals(polygon)
    assert result["stats"] == pytest.approx(stats)


# Valleys every 60 columns (lines at 30, 90, 150, 210) fall south from a divide
# at row 40; a hole of no data lies in the valley of the outlet.
ROWS, COLS = 200, 240
OUTLET = (150, 90)


@pytest.fixture
def valleys(tmp_path):
    rows = np.arange(ROWS)[:, None]
    cols = np.arange(COLS)[None, :]
    noise = np.random.default_rng(7).uniform(0.0, 0.4, (ROWS, COLS))
    dem = 500.0 - 0.5 * np.abs(rows - 40) + 0.3 * np.abs(cols % 60 - 30) + noise
    dem = dem.astype(np.float32)
    dem[100:104, 86:92] = DEM_NODATA
    d8 = pyflwdir.from_dem(
        dem, nodata=DEM_NODATA, transform=TRANSFORM, latlon=False
    ).to_array("d8")
    fdir = np.where(d8 == 247, 0, d8).astype(np.int16)
    return Rasters(tmp_path, fdir, dem)


@pytest.fixture
def loop(tmp_path):
    """A watershed whose upper cells drain out of the first window and back.

    The outlet P is cell (40, 20); A, five rows north of it, flows north to row
    25, east to column 35, south to row 40 and west to P. Every other cell is a
    pit, so the watershed of P is these 56 cells.
    """
    fdir = np.zeros((60, 60), dtype=np.int16)
    fdir[26:36, 20] = N
    fdir[25, 20:35] = E
    fdir[25:40, 35] = S
    fdir[40, 21:36] = W
    dem = (100.0 + np.arange(60, dtype=np.float32)[:, None]) * np.ones(
        (1, 60), dtype=np.float32
    )
    return Rasters(tmp_path, fdir, dem)


class TestWindowedDelineation:
    def test_window_of_the_precomputed_watershed_gives_the_whole_raster_result(
        self, valleys
    ):
        mask, polygon, stats = valleys.whole(*OUTLET)

        result = valleys.delineate(
            *OUTLET, bounds=_bounds(mask), max_cells=ROWS * COLS // 2
        )

        _assert_same(result, polygon, stats)
        assert 2_000 < mask.sum() < ROWS * COLS // 4

    def test_window_grows_until_the_watershed_is_inside(self, valleys):
        """From a window around the point alone, far smaller than the watershed."""
        _, polygon, stats = valleys.whole(*OUTLET)

        result = valleys.delineate(*OUTLET)

        _assert_same(result, polygon, stats)

    def test_watershed_leaving_the_window_and_coming_back(self, loop):
        """The first window holds A but not its path to P: A drains out of the
        window, so only the edge cell where the path comes back shows it."""
        _, polygon, stats = loop.whole(40, 20)

        result = loop.delineate(40, 20)

        _assert_same(result, polygon, stats)
        assert result["stats"]["area_m2"] == 56 * CELL * CELL
        assert result["polygon"].contains(Point(_centre(35, 20)))

    def test_cells_off_the_dem_are_not_in_the_watershed(self, valleys):
        """The hole of no data in the valley of the outlet."""
        result = valleys.delineate(*OUTLET)

        assert not result["polygon"].contains(Point(_centre(101, 88)))
        assert result["polygon"].contains(Point(_centre(110, 90)))


class TestRefusals:
    @pytest.mark.parametrize(
        ("first_window", "max_cells"),
        [("watershed", 1_000), ("point", 200)],
        ids=["precomputed watershed over the cap", "grown window over the cap"],
    )
    def test_window_over_the_cap_is_refused(self, valleys, first_window, max_cells):
        """The window of the precomputed watershed holds more than 1000 cells; the
        one of the point alone (13 x 13 cells) fits in 200, but not once it grows."""
        mask, _, _ = valleys.whole(*OUTLET)
        bounds = _bounds(mask) if first_window == "watershed" else None

        with pytest.raises(UnsupportedError) as raised:
            valleys.delineate(*OUTLET, bounds=bounds, max_cells=max_cells)

        error = raised.value
        assert (error.code, error.http_status) == ("unsupported", 422)
        assert error.details["reason"] == "window_too_large"
        assert error.details["cells"] > error.details["max_cells"] == max_cells

    @pytest.mark.parametrize(
        "change",
        ["one more column", "origin half a cell east", "cells of 5 m"],
    )
    def test_dem_off_the_grid_of_the_flow_directions_is_refused(
        self, valleys, tmp_path, change
    ):
        dem = valleys.dem
        if change == "one more column":
            _write_dem(tmp_path, np.pad(dem, ((0, 0), (0, 1)), constant_values=0))
        elif change == "origin half a cell east":
            _write_dem(tmp_path, dem, TRANSFORM * Affine.translation(0.5, 0))
        else:
            _write_dem(tmp_path, dem, from_origin(X0, Y_TOP, CELL / 2, CELL / 2))

        with pytest.raises(StoreUnavailableError) as raised:
            valleys.delineate(*OUTLET)

        error = raised.value
        assert (error.code, error.http_status) == ("store_unavailable", 503)
        assert error.details["reason"] == "raster_grids_differ"

    def test_point_off_the_rasters_is_refused(self, valleys):
        with pytest.raises(ValueError, match="outside the raster extent"):
            valleys.delineate(-1, 5)

    @pytest.mark.parametrize(
        ("missing", "message"),
        [("dem_mosaic_03_flowdir.tif", "Flow direction"), ("dem_mosaic.vrt", "DEM")],
    )
    def test_missing_raster_is_refused(self, valleys, tmp_path, missing, message):
        (tmp_path / missing).unlink()

        with pytest.raises(FileNotFoundError, match=message):
            valleys.delineate(*OUTLET)
