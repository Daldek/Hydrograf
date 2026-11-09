"""Tests for core.hydrology module."""

import numpy as np
import pytest

from core.hydrology import (
    D8_DIRECTIONS,
    VALID_D8_SET,
    fill_depressions_d8,
    fill_internal_nodata_holes,
    interpolate_enclosed_nodata,
    recompute_flow_accumulation,
)
from tests.dem_equivalence import NODATA, synthetic_dem


class TestD8Constants:
    """Tests for D8 direction constants."""

    def test_8_directions(self):
        assert len(D8_DIRECTIONS) == 8

    def test_valid_set_matches_dict(self):
        assert set(D8_DIRECTIONS.keys()) == VALID_D8_SET

    def test_all_powers_of_2(self):
        for d in D8_DIRECTIONS:
            # D8 codes are powers of 2: 1,2,4,8,16,32,64,128
            assert d > 0 and (d & (d - 1)) == 0

    def test_offsets_are_neighbors(self):
        for _d, (di, dj) in D8_DIRECTIONS.items():
            assert abs(di) <= 1 and abs(dj) <= 1
            assert abs(di) + abs(dj) > 0  # not (0,0)


class TestFillInternalNodataHoles:
    """Tests for fill_internal_nodata_holes."""

    def test_fills_single_hole(self):
        dem = np.array(
            [
                [10, 10, 10],
                [10, -9999, 10],
                [10, 10, 10],
            ],
            dtype=np.float64,
        )
        filled, n = fill_internal_nodata_holes(dem, -9999)
        assert filled[1, 1] != -9999
        assert n == 1

    def test_no_holes_unchanged(self):
        dem = np.array([[1, 2], [3, 4]], dtype=np.float64)
        filled, n = fill_internal_nodata_holes(dem, -9999)
        assert n == 0
        np.testing.assert_array_equal(filled, dem)

    def test_boundary_nodata_preserved(self):
        dem = np.array(
            [
                [-9999, 10, 10],
                [10, 10, 10],
                [10, 10, -9999],
            ],
            dtype=np.float64,
        )
        filled, n = fill_internal_nodata_holes(dem, -9999)
        assert filled[0, 0] == -9999
        assert filled[2, 2] == -9999


def _plane(nrows: int = 12, ncols: int = 14) -> np.ndarray:
    rows, cols = np.indices((nrows, ncols), dtype=np.float64)
    return (100.0 + rows + 0.5 * cols).astype(np.float32)


class TestInterpolateEnclosedNodata:
    """Tests for interpolate_enclosed_nodata."""

    def test_an_enclosed_area_takes_values_from_the_data_around_it(self):
        dem = _plane()
        dem[4:8, 5:9] = NODATA
        around = dem[2:10, 3:11]
        around = around[around != NODATA]

        filled, count = interpolate_enclosed_nodata(dem, NODATA)

        assert count == 16
        hole = filled[4:8, 5:9]
        assert hole.min() >= around.min() and hole.max() <= around.max()
        kept = np.ones(dem.shape, dtype=bool)
        kept[4:8, 5:9] = False
        np.testing.assert_array_equal(filled[kept], dem[kept])
        # A copy: the DEM given is not changed
        assert np.all(dem[4:8, 5:9] == NODATA)

    def test_nodata_that_reaches_the_frame_stays(self):
        dem = _plane()
        dem[:, -2:] = NODATA
        dem[0, 0] = NODATA
        # Touches the corner cell diagonally only: the outside too (8-connected)
        dem[1:3, 1:3] = NODATA
        enclosed = np.s_[8:10, 4:7]
        dem[enclosed] = NODATA
        reaching = dem == NODATA
        reaching[enclosed] = False

        filled, count = interpolate_enclosed_nodata(dem, NODATA)

        assert count == 6
        assert np.all(filled[enclosed] != NODATA)
        assert np.all(filled[reaching] == NODATA)

    def test_nan_nodata(self):
        dem = _plane()
        dem[0, :] = np.nan
        dem[5:7, 6:8] = np.nan

        filled, count = interpolate_enclosed_nodata(dem, np.nan)

        assert count == 4
        assert not np.any(np.isnan(filled[1:]))
        assert np.all(np.isnan(filled[0]))

    @pytest.mark.parametrize("nodata_border", [False, True])
    def test_the_depression_fill_then_drains_to_the_outer_edge_only(
        self, nodata_border
    ):
        """The holes that stay after the repair are outlets until they are filled."""
        dem, _ = synthetic_dem(nodata_border=nodata_border, holes=True)
        outside = _outside(dem)
        _, d8 = fill_depressions_d8(dem.copy(), NODATA)
        assert np.any(_pits(d8) & ~_next_to(outside)), "enclosed holes are outlets"

        filled, count = interpolate_enclosed_nodata(dem, NODATA)
        _, d8 = fill_depressions_d8(filled, NODATA)

        assert count == int(np.count_nonzero((dem == NODATA) & ~outside))
        # Every cell but the outside routes (cells of the outside that the repair
        # fills route too), and the pits lie on the outer edge
        assert not np.any((d8 == 247) & ~outside)
        assert not np.any(_pits(d8) & ~_next_to(outside))


def _outside(dem: np.ndarray) -> np.ndarray:
    """The nodata that reaches the frame of the raster (8-connected)."""
    from scipy import ndimage

    nodata = dem == NODATA
    labels, _ = ndimage.label(nodata, structure=np.ones((3, 3), dtype=bool))
    frame = np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
    return np.isin(labels, frame[frame > 0])


def _next_to(outside: np.ndarray) -> np.ndarray:
    """The cells on the frame of the raster or next to the outside nodata."""
    padded = np.pad(outside, 1, constant_values=True)
    near = np.zeros(outside.shape, dtype=bool)
    nrows, ncols = outside.shape
    for dr in range(3):
        for dc in range(3):
            near |= padded[dr : dr + nrows, dc : dc + ncols]
    return near


def _pits(d8: np.ndarray) -> np.ndarray:
    """The cells pyflwdir routes and gives no direction (its outlets)."""
    return np.asarray(d8 == 0)


class TestRecomputeFlowAccumulation:
    """Tests for recompute_flow_accumulation."""

    def test_simple_chain(self):
        # 3x1 grid: cell 0 → cell 1 → cell 2 (E direction = 1)
        fdir = np.array([[1, 1, 1]], dtype=np.int16)
        nodata = -9999
        dem = np.array([[100, 90, 80]], dtype=np.float64)
        acc = recompute_flow_accumulation(fdir, dem, nodata)
        assert acc[0, 0] == 1  # only itself
        assert acc[0, 1] == 2  # itself + upstream cell
        assert acc[0, 2] >= 2  # itself + upstream (may flow off grid)

    def test_nodata_excluded(self):
        fdir = np.array([[1, 1, 1]], dtype=np.int16)
        dem = np.array([[-9999, 90, 80]], dtype=np.float64)
        acc = recompute_flow_accumulation(fdir, dem, -9999)
        assert acc[0, 0] == 0  # nodata cell
