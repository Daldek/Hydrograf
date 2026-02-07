"""
Unit tests for DEM processing fixes: nodata hole filling, sink fixing,
and flow accumulation recomputation.
"""

import numpy as np

from scripts.process_dem import (
    fill_internal_nodata_holes,
    fix_internal_sinks,
    recompute_flow_accumulation,
)

NODATA = -9999.0


class TestFillInternalNodataHoles:
    """Tests for fill_internal_nodata_holes()."""

    def test_fills_single_hole(self):
        """Single nodata cell surrounded by valid values is filled."""
        dem = np.array(
            [
                [10.0, 10.0, 10.0],
                [10.0, NODATA, 10.0],
                [10.0, 10.0, 10.0],
            ]
        )
        result, count = fill_internal_nodata_holes(dem, NODATA)

        assert count == 1
        assert result[1, 1] != NODATA
        assert result[1, 1] == 10.0

    def test_preserves_boundary_nodata(self):
        """Nodata on corner/edge with few valid neighbors is not filled."""
        dem = np.array(
            [
                [NODATA, 10.0, 10.0, 10.0],
                [10.0, 10.0, 10.0, 10.0],
                [10.0, 10.0, 10.0, 10.0],
                [10.0, 10.0, 10.0, NODATA],
            ]
        )
        result, count = fill_internal_nodata_holes(dem, NODATA, min_valid_neighbors=5)

        # Corner cells have at most 3 neighbors — should NOT be filled
        assert result[0, 0] == NODATA
        assert result[3, 3] == NODATA
        assert count == 0

    def test_fills_with_average(self):
        """Filled value equals the mean of valid neighbors."""
        dem = np.array(
            [
                [10.0, 20.0, 30.0],
                [10.0, NODATA, 30.0],
                [10.0, 20.0, 30.0],
            ]
        )
        result, count = fill_internal_nodata_holes(dem, NODATA)

        assert count == 1
        expected = np.mean([10.0, 20.0, 30.0, 10.0, 30.0, 10.0, 20.0, 30.0])
        assert abs(result[1, 1] - expected) < 0.01

    def test_no_holes_unchanged(self):
        """DEM without nodata holes is returned unchanged."""
        dem = np.array(
            [
                [10.0, 20.0, 30.0],
                [10.0, 20.0, 30.0],
                [10.0, 20.0, 30.0],
            ]
        )
        result, count = fill_internal_nodata_holes(dem, NODATA)

        assert count == 0
        np.testing.assert_array_equal(result, dem)

    def test_large_nodata_not_filled(self):
        """Large block of nodata — center cells should NOT be filled."""
        dem = np.full((7, 7), NODATA)
        # Only the border is valid
        dem[0, :] = 10.0
        dem[-1, :] = 10.0
        dem[:, 0] = 10.0
        dem[:, -1] = 10.0

        result, count = fill_internal_nodata_holes(dem, NODATA, min_valid_neighbors=5)

        # Center cell (3,3) has 0 valid neighbors initially — should stay nodata
        assert result[3, 3] == NODATA

    def test_iterative_filling(self):
        """Two adjacent holes are filled across iterations."""
        dem = np.array(
            [
                [10.0, 10.0, 10.0, 10.0, 10.0],
                [10.0, 10.0, 10.0, 10.0, 10.0],
                [10.0, 10.0, NODATA, NODATA, 10.0],
                [10.0, 10.0, 10.0, 10.0, 10.0],
                [10.0, 10.0, 10.0, 10.0, 10.0],
            ]
        )
        result, count = fill_internal_nodata_holes(
            dem, NODATA, min_valid_neighbors=5, max_iterations=3
        )

        # Both holes should be filled
        # (first has 6 valid, second has 5 valid + 1st gets filled)
        assert result[2, 2] != NODATA
        assert result[2, 3] != NODATA
        assert count >= 1  # At least one filled


class TestFixInternalSinks:
    """Tests for fix_internal_sinks()."""

    def test_fixes_by_steepest_descent(self):
        """Internal sink is fixed to flow toward steepest downhill neighbor."""
        # 3x3 grid: center is a sink (fdir=0), lower neighbor is lower
        dem = np.array(
            [
                [100.0, 100.0, 100.0],
                [100.0, 50.0, 100.0],
                [100.0, 30.0, 100.0],
            ]
        )
        inflated = dem.copy()
        fdir = np.array(
            [
                [4, 4, 4],
                [0, 0, 16],  # center is sink
                [0, 0, 16],
            ],
            dtype=np.int16,
        )
        acc = np.array(
            [
                [1, 1, 1],
                [1, 1, 1],
                [1, 2, 1],
            ],
            dtype=np.int32,
        )

        fdir_fixed, acc_fixed, diag = fix_internal_sinks(
            fdir, acc, inflated, dem, NODATA
        )

        # Center should now point S (dir 4) — steepest descent to (2,1)=30
        assert fdir_fixed[1, 1] == 4
        assert diag["total_fixed"] >= 1
        assert diag["by_strategy"]["steepest"] >= 1

    def test_no_sinks_unchanged(self):
        """No internal sinks — arrays returned unchanged."""
        dem = np.array(
            [
                [100.0, 100.0, 100.0],
                [100.0, 50.0, 100.0],
                [100.0, 100.0, 100.0],
            ]
        )
        fdir = np.array(
            [
                [4, 4, 4],
                [1, 4, 16],
                [0, 0, 0],  # edge sinks are OK (outlets)
            ],
            dtype=np.int16,
        )
        acc = np.ones((3, 3), dtype=np.int32)

        fdir_fixed, acc_fixed, diag = fix_internal_sinks(
            fdir, acc, dem, dem, NODATA
        )

        assert diag["total_fixed"] == 0
        np.testing.assert_array_equal(fdir_fixed, fdir)

    def test_edge_sinks_not_fixed(self):
        """Sinks on raster edge are not modified (valid outlets)."""
        dem = np.array(
            [
                [100.0, 100.0, 100.0],
                [100.0, 50.0, 100.0],
                [100.0, 100.0, 100.0],
            ]
        )
        fdir = np.array(
            [
                [0, 4, 0],
                [1, 4, 16],
                [0, 0, 0],
            ],
            dtype=np.int16,
        )
        acc = np.ones((3, 3), dtype=np.int32)

        fdir_fixed, _, diag = fix_internal_sinks(fdir, acc, dem, dem, NODATA)

        # All edge cells with fdir=0 should remain 0
        assert fdir_fixed[0, 0] == 0
        assert fdir_fixed[0, 2] == 0
        assert fdir_fixed[2, 0] == 0
        assert fdir_fixed[2, 1] == 0
        assert fdir_fixed[2, 2] == 0
        assert diag["total_fixed"] == 0

    def test_recomputes_accumulation(self):
        """Flow accumulation is recomputed after sink fixes."""
        # 5x5 grid with a sink at (2,2) blocking flow
        dem = np.full((5, 5), 100.0)
        dem[2, 2] = 50.0
        dem[3, 2] = 30.0
        dem[4, 2] = 10.0

        # All cells point south except center which is a sink
        fdir = np.full((5, 5), 4, dtype=np.int16)
        fdir[4, :] = 0  # bottom edge = outlets
        fdir[2, 2] = 0  # sink

        acc = np.ones((5, 5), dtype=np.int32)
        inflated = dem.copy()

        fdir_fixed, acc_fixed, diag = fix_internal_sinks(
            fdir, acc, inflated, dem, NODATA
        )

        # Sink should be fixed
        assert fdir_fixed[2, 2] != 0
        assert diag["total_fixed"] == 1
        # Accumulation should be recomputed (downstream of fixed sink gets more flow)
        assert acc_fixed[3, 2] > 1

    def test_flat_area_uses_max_acc(self):
        """Flat area sink uses max accumulation strategy when no slope exists."""
        # All same elevation — no steepest descent possible
        dem = np.full((5, 5), 50.0)
        inflated = dem.copy()  # No micro-gradients either

        fdir = np.full((5, 5), 1, dtype=np.int16)  # all flow East
        fdir[4, :] = 0  # bottom edge
        fdir[:, 4] = 0  # right edge
        fdir[2, 2] = 0  # internal sink

        # Give east neighbor high accumulation
        acc = np.ones((5, 5), dtype=np.int32)
        acc[2, 3] = 100

        fdir_fixed, _, diag = fix_internal_sinks(fdir, acc, inflated, dem, NODATA)

        assert fdir_fixed[2, 2] != 0
        assert diag["total_fixed"] == 1
        # Should route toward the neighbor with max accumulation (east = direction 1)
        assert diag["by_strategy"]["max_acc"] >= 1


class TestRecomputeFlowAccumulation:
    """Tests for recompute_flow_accumulation()."""

    def test_simple_chain(self):
        """3 cells E→E→outlet: accumulation = 1, 2, 3."""
        dem = np.array([[10.0, 10.0, 10.0]])
        fdir = np.array([[1, 1, 0]], dtype=np.int16)  # E, E, outlet

        acc = recompute_flow_accumulation(fdir, dem, NODATA)

        assert acc[0, 0] == 1
        assert acc[0, 1] == 2
        assert acc[0, 2] == 3

    def test_nodata_excluded(self):
        """Nodata cell has acc=0 and doesn't contribute to downstream."""
        dem = np.array([[10.0, NODATA, 10.0]])
        fdir = np.array([[1, 1, 0]], dtype=np.int16)

        acc = recompute_flow_accumulation(fdir, dem, NODATA)

        assert acc[0, 0] == 1  # valid, no upstream
        assert acc[0, 1] == 0  # nodata
        assert acc[0, 2] == 1  # valid, but no valid upstream (nodata blocks)

    def test_converging_flow(self):
        """Two cells converging to one: downstream acc = 3."""
        dem = np.array(
            [
                [10.0, 10.0],
                [10.0, 10.0],
            ]
        )
        # (0,0)→S, (0,1)→SW, both flow to (1,0). (1,0)→E to (1,1)
        fdir = np.array(
            [
                [4, 8],
                [1, 0],
            ],
            dtype=np.int16,
        )

        acc = recompute_flow_accumulation(fdir, dem, NODATA)

        assert acc[0, 0] == 1  # headwater
        assert acc[0, 1] == 1  # headwater
        assert acc[1, 0] == 3  # self + 2 upstream
        assert acc[1, 1] == 4  # self + 3 from (1,0)
