"""Tests for the flow path from the boundary of a watershed (core.divide_flow_path)."""

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from core.divide_flow_path import compute_divide_flow_path
from core.hydrology import D8_DIRECTIONS

CELL = 10.0
TRANSFORM = from_origin(0.0, 70.0, CELL, CELL)
# Watershed: the 5x5 block at rows 1-5, cols 1-5 of a 7x8 grid, two
# sub-catchments (1 above, 2 below). Its flow spirals in from the centre to
# the top-left cell, which drains west into sub-catchment 4 (a pit). The
# neighbouring watershed 3 (cols 6-7) is farther from the outlet of the grid.
ROW0, COL0, SIZE = 1, 1, 5
NEIGHBOUR_DIST = 10_000.0


def _spiral(size: int) -> list[tuple[int, int]]:
    """Cells of a size x size block, clockwise from the top-left to the centre."""
    cells, top, left, bottom, right = [], 0, 0, size - 1, size - 1
    while top <= bottom and left <= right:
        cells += [(top, c) for c in range(left, right + 1)]
        cells += [(r, right) for r in range(top + 1, bottom + 1)]
        if top < bottom:
            cells += [(bottom, c) for c in range(right - 1, left - 1, -1)]
        if left < right:
            cells += [(r, left) for r in range(bottom - 1, top, -1)]
        top, left, bottom, right = top + 1, left + 1, bottom - 1, right - 1
    return cells


def _code(d_row: int, d_col: int) -> int:
    return next(k for k, v in D8_DIRECTIONS.items() if v == (d_row, d_col))


def _write(path, array, dtype, nodata):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=dtype,
        crs="EPSG:2180",
        transform=TRANSFORM,
        nodata=nodata,
    ) as dst:
        dst.write(array.astype(dtype), 1)
    return str(path)


@pytest.fixture
def rasters(tmp_path):
    labels = np.zeros((7, 8), dtype=np.int32)
    fdir = np.zeros((7, 8), dtype=np.int16)
    dist = np.full((7, 8), -1.0, dtype=np.float32)

    labels[ROW0 : ROW0 + 3, COL0 : COL0 + SIZE] = 1
    labels[ROW0 + 3 : ROW0 + SIZE, COL0 : COL0 + SIZE] = 2
    labels[:, 6:] = 3
    dist[:, 6:] = NEIGHBOUR_DIST
    fdir[:, 6:] = _code(0, 1)
    labels[1, 0] = 4  # the cell the watershed drains to: a pit
    dist[1, 0] = 0.0

    spiral = [(ROW0 + r, COL0 + c) for r, c in _spiral(SIZE)]
    for k, (row, col) in enumerate(spiral):
        down = spiral[k - 1] if k > 0 else (1, 0)
        fdir[row, col] = _code(down[0] - row, down[1] - col)
        dist[row, col] = CELL * (k + 1)

    return {
        "labels_path": _write(tmp_path / "labels.tif", labels, "int32", 0),
        "flow_dist_path": _write(tmp_path / "dist.tif", dist, "float32", -1.0),
        "flowdir_path": _write(tmp_path / "fdir.tif", fdir, "int16", 0),
        "dist": dist,
    }


def _centre(row: int, col: int) -> tuple[float, float]:
    return TRANSFORM * (col + 0.5, row + 0.5)


WATERSHED_BOUNDS = (10.0, 10.0, 60.0, 60.0)


class TestComputeDivideFlowPath:
    def test_farthest_cell_inside_gives_a_shorter_path_from_the_boundary(self, rasters):
        dist = rasters.pop("dist")
        path = compute_divide_flow_path([1, 2], WATERSHED_BOUNDS, 0.0, **rasters)

        longest_km = dist[ROW0 : ROW0 + SIZE, COL0 : COL0 + SIZE].max() / 1000
        assert longest_km == pytest.approx(0.25)  # the centre of the spiral
        # The farthest boundary cell is (2, 1), 16th from the outlet; the
        # cells of sub-catchment 2 next to the centre are inside the watershed
        # and the farther cells of watershed 3 next to it are not in it.
        assert path is not None
        assert path.length_km == pytest.approx(0.16)
        assert path.length_km < longest_km
        assert path.coords_2180[0] == pytest.approx(_centre(2, 1))

    def test_line_ends_where_the_flow_leaves_the_watershed(self, rasters):
        rasters.pop("dist")
        path = compute_divide_flow_path([1, 2], WATERSHED_BOUNDS, 0.0, **rasters)

        assert path is not None
        assert path.coords_2180[-1] == pytest.approx(_centre(1, 0))

    def test_length_is_measured_from_the_outlet_baseline(self, rasters):
        rasters.pop("dist")
        path = compute_divide_flow_path([1, 2], WATERSHED_BOUNDS, 10.0, **rasters)

        assert path is not None
        assert path.length_km == pytest.approx(0.15)

    def test_window_grows_to_the_whole_watershed(self, rasters):
        rasters.pop("dist")
        # Bounds of the centre cell only
        path = compute_divide_flow_path(
            [1, 2], (30.0, 30.0, 40.0, 40.0), 0.0, **rasters
        )

        assert path is not None
        assert path.length_km == pytest.approx(0.16)
        assert path.coords_2180[0] == pytest.approx(_centre(2, 1))

    def test_one_sub_catchment_has_its_own_boundary(self, rasters):
        rasters.pop("dist")
        # Sub-catchment 2 alone: its farthest cell (4, 2), 23rd from the
        # outlet, is on its boundary with sub-catchment 1; its flow leaves 2
        # into 1 at (3, 4).
        path = compute_divide_flow_path([2], WATERSHED_BOUNDS, 0.0, **rasters)

        assert path is not None
        assert path.length_km == pytest.approx(0.23)
        assert path.coords_2180[0] == pytest.approx(_centre(4, 2))
        assert path.coords_2180[-1] == pytest.approx(_centre(3, 4))

    def test_labels_not_in_the_raster_give_none(self, rasters):
        rasters.pop("dist")
        assert compute_divide_flow_path([9], WATERSHED_BOUNDS, 0.0, **rasters) is None
