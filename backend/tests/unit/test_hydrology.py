"""Tests for core.hydrology module."""

import numpy as np

from core.hydrology import (
    D8_DIRECTIONS,
    VALID_D8_SET,
    fill_internal_nodata_holes,
    recompute_flow_accumulation,
)


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
        dem = np.array([
            [10, 10, 10],
            [10, -9999, 10],
            [10, 10, 10],
        ], dtype=np.float64)
        filled, n = fill_internal_nodata_holes(dem, -9999)
        assert filled[1, 1] != -9999
        assert n == 1

    def test_no_holes_unchanged(self):
        dem = np.array([[1, 2], [3, 4]], dtype=np.float64)
        filled, n = fill_internal_nodata_holes(dem, -9999)
        assert n == 0
        np.testing.assert_array_equal(filled, dem)

    def test_boundary_nodata_preserved(self):
        dem = np.array([
            [-9999, 10, 10],
            [10, 10, 10],
            [10, 10, -9999],
        ], dtype=np.float64)
        filled, n = fill_internal_nodata_holes(dem, -9999)
        assert filled[0, 0] == -9999
        assert filled[2, 2] == -9999


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
