"""Unit tests for core.catchment_graph module."""

from unittest.mock import MagicMock

import numpy as np
import pytest
from scipy import sparse

from core.catchment_graph import CatchmentGraph


@pytest.fixture
def small_graph():
    """
    Build a small hand-crafted catchment graph for testing.

    Graph structure (threshold=10000):
        1 → 3
        2 → 3
        3 → 4
        4 (outlet, no downstream)

    4 catchments, each with pre-computed stats.
    """
    cg = CatchmentGraph()
    n = 4
    cg._n = n
    cg._loaded = True

    # Node 0: seg_idx=1, upstream of 3
    # Node 1: seg_idx=2, upstream of 3
    # Node 2: seg_idx=3, upstream of 4
    # Node 3: seg_idx=4, outlet
    cg._segment_idx = np.array([1, 2, 3, 4], dtype=np.int32)
    cg._threshold_m2 = np.array([10000, 10000, 10000, 10000], dtype=np.int32)
    cg._area_km2 = np.array([5.0, 3.0, 8.0, 10.0], dtype=np.float32)
    cg._elev_min = np.array([150.0, 160.0, 140.0, 120.0], dtype=np.float32)
    cg._elev_max = np.array([200.0, 210.0, 195.0, 180.0], dtype=np.float32)
    cg._elev_mean = np.array([175.0, 185.0, 167.5, 150.0], dtype=np.float32)
    cg._slope_mean = np.array([5.0, 6.0, 4.0, 3.0], dtype=np.float32)
    cg._perimeter_km = np.array([10.0, 8.0, 15.0, 20.0], dtype=np.float32)
    cg._stream_length_km = np.array([2.0, 1.5, 3.0, 4.0], dtype=np.float32)
    cg._strahler = np.array([1, 1, 2, 3], dtype=np.int8)

    # Histograms
    cg._histograms = [
        {"base_m": 150, "interval_m": 1, "counts": [10, 20, 30, 20, 10, 5, 3, 2]},
        {"base_m": 160, "interval_m": 1, "counts": [5, 15, 25, 15, 5]},
        {"base_m": 140, "interval_m": 1, "counts": [8, 12, 18, 22, 18, 12, 8]},
        {
            "base_m": 120,
            "interval_m": 1,
            "counts": [3, 5, 10, 15, 20, 25, 20, 15, 10, 5, 3],
        },
    ]

    # Lookup
    cg._lookup = {
        (10000, 1): 0,
        (10000, 2): 1,
        (10000, 3): 2,
        (10000, 4): 3,
    }

    # Upstream adjacency: adj[downstream, upstream] = 1
    # 1→3: edge (0, 2), 2→3: edge (1, 2), 3→4: edge (2, 3)
    row = np.array([2, 2, 3], dtype=np.int32)
    col = np.array([0, 1, 2], dtype=np.int32)
    data = np.ones(3, dtype=np.int8)
    cg._upstream_adj = sparse.csr_matrix(
        (data, (row, col)),
        shape=(n, n),
        dtype=np.int8,
    )

    return cg


class TestCatchmentGraphTraversal:
    """Tests for BFS traversal."""

    def test_traverse_from_outlet_finds_all(self, small_graph):
        """Traversal from outlet (node 3) should find all 4 nodes."""
        indices = small_graph.traverse_upstream(3)
        assert set(indices) == {0, 1, 2, 3}

    def test_traverse_from_middle_finds_upstream(self, small_graph):
        """Traversal from node 2 (seg_idx=3) should find nodes 0, 1, 2."""
        indices = small_graph.traverse_upstream(2)
        assert set(indices) == {0, 1, 2}

    def test_traverse_from_headwater_finds_self(self, small_graph):
        """Traversal from headwater (node 0) should find only itself."""
        indices = small_graph.traverse_upstream(0)
        assert set(indices) == {0}

    def test_traverse_not_loaded_raises(self):
        """Traversal on unloaded graph should raise RuntimeError."""
        cg = CatchmentGraph()
        with pytest.raises(RuntimeError, match="not loaded"):
            cg.traverse_upstream(0)


class TestCatchmentGraphSegmentIndices:
    """Tests for get_segment_indices."""

    def test_returns_correct_segment_idxs(self, small_graph):
        """Should return segment_idx values for matching threshold."""
        indices = np.array([0, 1, 2, 3])
        result = small_graph.get_segment_indices(indices, 10000)
        assert sorted(result) == [1, 2, 3, 4]

    def test_filters_by_threshold(self, small_graph):
        """Should return empty for non-existent threshold."""
        indices = np.array([0, 1, 2, 3])
        result = small_graph.get_segment_indices(indices, 99999)
        assert result == []


class TestCatchmentGraphAggregateStats:
    """Tests for aggregate_stats."""

    def test_total_area_sum(self, small_graph):
        """Area should be sum of individual catchments."""
        indices = np.array([0, 1, 2, 3])
        stats = small_graph.aggregate_stats(indices)
        assert stats["area_km2"] == pytest.approx(26.0, abs=0.01)

    def test_elevation_min_max(self, small_graph):
        """Elevation min/max should be global extremes."""
        indices = np.array([0, 1, 2, 3])
        stats = small_graph.aggregate_stats(indices)
        assert stats["elevation_min_m"] == pytest.approx(120.0)
        assert stats["elevation_max_m"] == pytest.approx(210.0)

    def test_weighted_mean_elevation(self, small_graph):
        """Mean elevation should be area-weighted."""
        indices = np.array([0, 1, 2, 3])
        stats = small_graph.aggregate_stats(indices)
        # (175*5 + 185*3 + 167.5*8 + 150*10) / 26 = 163.27 (approx)
        expected = (175 * 5 + 185 * 3 + 167.5 * 8 + 150 * 10) / 26
        assert stats["elevation_mean_m"] == pytest.approx(expected, abs=0.5)

    def test_max_strahler(self, small_graph):
        """Max Strahler should be the maximum value."""
        indices = np.array([0, 1, 2, 3])
        stats = small_graph.aggregate_stats(indices)
        assert stats["max_strahler_order"] == 3

    def test_stream_length_sum(self, small_graph):
        """Stream length should be sum."""
        indices = np.array([0, 1, 2, 3])
        stats = small_graph.aggregate_stats(indices)
        assert stats["stream_length_km"] == pytest.approx(10.5, abs=0.01)

    def test_drainage_density(self, small_graph):
        """Drainage density = total_stream_length / total_area."""
        indices = np.array([0, 1, 2, 3])
        stats = small_graph.aggregate_stats(indices)
        expected_dd = 10.5 / 26.0
        assert stats["drainage_density_km_per_km2"] == pytest.approx(
            expected_dd,
            abs=0.01,
        )

    def test_partial_traversal_stats(self, small_graph):
        """Stats for partial traversal (only headwaters)."""
        indices = np.array([0, 1])
        stats = small_graph.aggregate_stats(indices)
        assert stats["area_km2"] == pytest.approx(8.0, abs=0.01)
        assert stats["elevation_min_m"] == pytest.approx(150.0)
        assert stats["elevation_max_m"] == pytest.approx(210.0)


class TestCatchmentGraphHypsometric:
    """Tests for aggregate_hypsometric."""

    def test_returns_curve(self, small_graph):
        """Should return a list of hypsometric points."""
        indices = np.array([0, 1, 2, 3])
        curve = small_graph.aggregate_hypsometric(indices)
        assert len(curve) > 0
        # First point: relative_height=0, relative_area should be ~1.0
        assert curve[0]["relative_height"] == 0.0
        assert curve[0]["relative_area"] >= 0.9  # Nearly all area above min
        # Last point: relative_height=1, relative_area should be ~0.0
        assert curve[-1]["relative_height"] == 1.0
        assert curve[-1]["relative_area"] <= 0.1  # Little area above max

    def test_empty_histograms(self):
        """Should return empty list when no histograms."""
        cg = CatchmentGraph()
        cg._loaded = True
        cg._histograms = [None, None]
        cg._n = 2
        curve = cg.aggregate_hypsometric(np.array([0, 1]))
        assert curve == []

    def test_single_node(self, small_graph):
        """Should work for a single node."""
        curve = small_graph.aggregate_hypsometric(np.array([0]))
        assert len(curve) > 0
        assert curve[0]["relative_height"] == 0.0


class TestCatchmentGraphFindAtPoint:
    """Tests for find_catchment_at_point."""

    def test_found(self, small_graph):
        """Should return internal index when ST_Contains finds a match."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.segment_idx = 3
        mock_db.execute.return_value.fetchone.return_value = mock_result

        idx = small_graph.find_catchment_at_point(
            500000.0,
            300000.0,
            10000,
            mock_db,
        )
        assert idx == 2  # (10000, 3) → internal index 2

    def test_not_found(self, small_graph):
        """Should raise ValueError when no catchment contains the point."""
        mock_db = MagicMock()
        mock_db.execute.return_value.fetchone.return_value = None

        with pytest.raises(ValueError, match="Nie znaleziono"):
            small_graph.find_catchment_at_point(
                500000.0,
                300000.0,
                10000,
                mock_db,
            )

    def test_not_loaded_raises(self):
        """Should raise RuntimeError if graph not loaded."""
        cg = CatchmentGraph()
        with pytest.raises(RuntimeError, match="not loaded"):
            cg.find_catchment_at_point(0, 0, 10000, MagicMock())


class TestTraverseToConfluence:
    """Tests for traverse_to_confluence."""

    def test_traverse_to_confluence_linear(self):
        """Linear chain A→B→C: traverse from C returns all [C, B, A]."""
        cg = CatchmentGraph()
        n = 3
        cg._n = n
        cg._loaded = True
        cg._segment_idx = np.array([1, 2, 3], dtype=np.int32)
        cg._threshold_m2 = np.array([10000, 10000, 10000], dtype=np.int32)

        # A(0)→B(1)→C(2): upstream adj[1,0]=1, adj[2,1]=1
        row = np.array([1, 2], dtype=np.int32)
        col = np.array([0, 1], dtype=np.int32)
        data = np.ones(2, dtype=np.int8)
        cg._upstream_adj = sparse.csr_matrix(
            (data, (row, col)),
            shape=(n, n),
            dtype=np.int8,
        )

        result = cg.traverse_to_confluence(2)
        assert set(result) == {0, 1, 2}

    def test_traverse_to_confluence_stops_at_junction(self):
        """A→C, B→C, C→D: traverse from D returns [D, C], stops at confluence C."""
        cg = CatchmentGraph()
        n = 4
        cg._n = n
        cg._loaded = True
        cg._segment_idx = np.array([1, 2, 3, 4], dtype=np.int32)
        cg._threshold_m2 = np.array([10000, 10000, 10000, 10000], dtype=np.int32)

        # A(0)→C(2), B(1)→C(2), C(2)→D(3)
        # upstream adj: adj[2,0]=1, adj[2,1]=1, adj[3,2]=1
        row = np.array([2, 2, 3], dtype=np.int32)
        col = np.array([0, 1, 2], dtype=np.int32)
        data = np.ones(3, dtype=np.int8)
        cg._upstream_adj = sparse.csr_matrix(
            (data, (row, col)),
            shape=(n, n),
            dtype=np.int8,
        )

        result = cg.traverse_to_confluence(3)
        # C has 2 upstream neighbors → confluence → include but don't continue past
        assert set(result) == {2, 3}
        assert 0 not in result
        assert 1 not in result

    def test_traverse_to_confluence_single_node(self):
        """Headwater with no upstream: returns just [start]."""
        cg = CatchmentGraph()
        n = 2
        cg._n = n
        cg._loaded = True
        cg._segment_idx = np.array([1, 2], dtype=np.int32)
        cg._threshold_m2 = np.array([10000, 10000], dtype=np.int32)

        # Only edge: 0→1 (upstream adj[1,0]=1)
        row = np.array([1], dtype=np.int32)
        col = np.array([0], dtype=np.int32)
        data = np.ones(1, dtype=np.int8)
        cg._upstream_adj = sparse.csr_matrix(
            (data, (row, col)),
            shape=(n, n),
            dtype=np.int8,
        )

        result = cg.traverse_to_confluence(0)
        assert list(result) == [0]
