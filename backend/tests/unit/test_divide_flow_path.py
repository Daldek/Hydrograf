"""Tests for the flow paths of a watershed (core.divide_flow_path)."""

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString

from core.divide_flow_path import compute_flow_paths
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
    x, y = TRANSFORM * (col + 0.5, row + 0.5)
    return float(x), float(y)


WATERSHED_BOUNDS = (10.0, 10.0, 60.0, 60.0)


def _paths(segment_idxs, rasters, bounds=WATERSHED_BOUNDS, baseline_m=0.0):
    paths = {k: v for k, v in rasters.items() if k != "dist"}
    return compute_flow_paths(segment_idxs, bounds, baseline_m, **paths)


class TestLongestFlowPath:
    def test_runs_from_the_farthest_cell_to_the_outlet(self, rasters):
        path = _paths([1, 2], rasters).longest

        assert path is not None
        # The centre of the spiral, 25th from the outlet; the flow leaves the
        # watershed into the pit at (1, 0).
        assert path.length_km == pytest.approx(0.25)
        assert path.coords_2180[0] == pytest.approx(_centre(3, 3))
        assert path.coords_2180[-1] == pytest.approx(_centre(1, 0))

    def test_line_is_as_long_as_the_flow_path(self, rasters):
        path = _paths([1, 2], rasters).longest

        assert path is not None
        assert LineString(path.coords_2180).length == pytest.approx(
            path.length_km * 1000
        )

    def test_line_keeps_only_the_turns_of_the_cells(self, rasters):
        path = _paths([1, 2], rasters).longest

        # The flow unwinds the spiral: from the centre (3, 3) west, south,
        # east, north, west, south, east, north and west to the pit; the cells
        # between the turns lie on the straight runs.
        assert path is not None
        assert path.coords_2180 == pytest.approx(
            [
                _centre(r, c)
                for r, c in [
                    (3, 3),
                    (3, 2),
                    (4, 2),
                    (4, 4),
                    (2, 4),
                    (2, 1),
                    (5, 1),
                    (5, 5),
                    (1, 5),
                    (1, 0),
                ]
            ]
        )

    def test_length_is_measured_from_the_outlet_baseline(self, rasters):
        path = _paths([1, 2], rasters, baseline_m=10.0).longest

        assert path is not None
        assert path.length_km == pytest.approx(0.24)


class TestDivideFlowPath:
    def test_farthest_cell_inside_gives_a_shorter_path_from_the_boundary(self, rasters):
        paths = _paths([1, 2], rasters)

        watershed = rasters["dist"][ROW0 : ROW0 + SIZE, COL0 : COL0 + SIZE]
        longest_km = watershed.max() / 1000
        assert longest_km == pytest.approx(0.25)  # the centre of the spiral
        # The farthest boundary cell is (2, 1), 16th from the outlet; the
        # cells of sub-catchment 2 next to the centre are inside the watershed
        # and the farther cells of watershed 3 next to it are not in it.
        assert paths.divide is not None
        assert paths.divide.length_km == pytest.approx(0.16)
        assert paths.divide.length_km < longest_km
        assert paths.divide.coords_2180[0] == pytest.approx(_centre(2, 1))

    def test_line_ends_where_the_flow_leaves_the_watershed(self, rasters):
        path = _paths([1, 2], rasters).divide

        assert path is not None
        assert path.coords_2180[-1] == pytest.approx(_centre(1, 0))
        assert LineString(path.coords_2180).length == pytest.approx(
            path.length_km * 1000
        )

    def test_length_is_measured_from_the_outlet_baseline(self, rasters):
        path = _paths([1, 2], rasters, baseline_m=10.0).divide

        assert path is not None
        assert path.length_km == pytest.approx(0.15)

    def test_window_grows_to_the_whole_watershed(self, rasters):
        # Bounds of the centre cell only
        path = _paths([1, 2], rasters, bounds=(30.0, 30.0, 40.0, 40.0)).divide

        assert path is not None
        assert path.length_km == pytest.approx(0.16)
        assert path.coords_2180[0] == pytest.approx(_centre(2, 1))

    def test_one_sub_catchment_has_its_own_boundary(self, rasters):
        # Sub-catchment 2 alone: its farthest cell (4, 2), 23rd from the
        # outlet, is on its boundary with sub-catchment 1; its flow leaves 2
        # into 1 at (3, 4).
        path = _paths([2], rasters).divide

        assert path is not None
        assert path.length_km == pytest.approx(0.23)
        assert path.coords_2180[0] == pytest.approx(_centre(4, 2))
        assert path.coords_2180[-1] == pytest.approx(_centre(3, 4))


def test_labels_not_in_the_raster_give_no_paths(rasters):
    paths = _paths([9], rasters)

    assert paths.longest is None
    assert paths.divide is None
