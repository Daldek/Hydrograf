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
    # Hydraulic length: max flow path distance to outlet per sub-catchment [km]
    # Node 0 (headwater, far upstream): 12.5 km from most remote cell to global outlet
    # Node 1 (headwater, tributary): 10.0 km
    # Node 2 (mid-basin): 8.0 km
    # Node 3 (outlet sub-catchment): 5.0 km
    cg._hydraulic_length_km = np.array([12.5, 10.0, 8.0, 5.0], dtype=np.float32)
    cg._strahler = np.array([1, 1, 2, 3], dtype=np.int8)
    cg._max_flow_dist_m = np.array([12500.0, 10000.0, 8000.0, 5000.0], dtype=np.float64)

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


class TestLookupBySegmentIdx:
    """Tests for lookup_by_segment_idx."""

    def test_found(self, small_graph):
        """Known (threshold, segment_idx) returns correct internal index."""
        # (10000, 3) → internal index 2 based on fixture setup
        idx = small_graph.lookup_by_segment_idx(10000, 3)
        assert idx == 2

    def test_not_found_returns_none(self, small_graph):
        """Unknown segment_idx returns None."""
        idx = small_graph.lookup_by_segment_idx(10000, 999)
        assert idx is None

    def test_wrong_threshold_returns_none(self, small_graph):
        """Correct segment_idx but wrong threshold returns None."""
        idx = small_graph.lookup_by_segment_idx(99999, 3)
        assert idx is None

    def test_not_loaded_raises(self):
        """RuntimeError if graph not loaded."""
        cg = CatchmentGraph()
        with pytest.raises(RuntimeError, match="not loaded"):
            cg.lookup_by_segment_idx(10000, 1)


class TestTraceMainChannel:
    """Tests for trace_main_channel."""

    def test_main_channel_from_outlet(self, small_graph):
        """Main channel from outlet (node 3) follows highest Strahler upstream.

        Graph: 0(s=1,len=2.0) -> 2(s=2,len=3.0) -> 3(s=3,len=4.0, outlet)
               1(s=1,len=1.5) -> 2

        Path should be [3, 2, 0]: at node 2 choose node 0 (strahler=1, len=2.0)
        over node 1 (strahler=1, len=1.5) by stream_length tie-breaker.
        """
        upstream = small_graph.traverse_upstream(3)
        result = small_graph.trace_main_channel(3, upstream)

        assert result["main_channel_nodes"] == [3, 2, 0]
        assert result["main_channel_length_km"] == pytest.approx(9.0, abs=0.01)
        # Slope = (elev_max[0] - elev_min[3]) / (9.0 * 1000) = (200-120)/9000
        expected_slope = (200.0 - 120.0) / (9.0 * 1000)
        assert result["main_channel_slope_m_per_m"] == pytest.approx(
            expected_slope, abs=1e-5
        )

    def test_main_channel_shorter_than_total(self, small_graph):
        """Main channel length should be less than total network length."""
        upstream = small_graph.traverse_upstream(3)
        result = small_graph.trace_main_channel(3, upstream)
        stats = small_graph.aggregate_stats(upstream)

        assert result["main_channel_length_km"] < stats["stream_length_km"]

    def test_main_channel_single_node(self, small_graph):
        """Headwater node (no upstream): path is just [node], length = own stream."""
        upstream = np.array([0])
        result = small_graph.trace_main_channel(0, upstream)

        assert result["main_channel_nodes"] == [0]
        assert result["main_channel_length_km"] == pytest.approx(2.0, abs=0.01)

    def test_main_channel_partial(self, small_graph):
        """Trace from node 2 with upstream [0, 1, 2]: path [2, 0], length=5.0."""
        upstream = small_graph.traverse_upstream(2)
        result = small_graph.trace_main_channel(2, upstream)

        assert result["main_channel_nodes"] == [2, 0]
        assert result["main_channel_length_km"] == pytest.approx(5.0, abs=0.01)
        # Slope = (elev_max[0] - elev_min[2]) / (5.0 * 1000) = (200-140)/5000
        expected_slope = (200.0 - 140.0) / (5.0 * 1000)
        assert result["main_channel_slope_m_per_m"] == pytest.approx(
            expected_slope, abs=1e-5
        )

    def test_main_channel_not_loaded_raises(self):
        """RuntimeError if graph not loaded."""
        cg = CatchmentGraph()
        with pytest.raises(RuntimeError, match="not loaded"):
            cg.trace_main_channel(0, np.array([0]))


class TestContiguousRealChannel:
    """Test that real_channel_length_km only counts contiguous real from outlet.

    The DEM flow-path can run between two parallel BDOT channels (e.g. drainage
    ditches) whose 15m buffers alternate coverage, producing a fragmented pattern:
    real -> not-real -> real -> not-real -> real.

    The correct model: from the outlet upstream, the first contiguous stretch of
    is_real_stream=True segments is the actual channel.  The first False segment
    marks the transition to overland flow — everything above is overland, even if
    later segments happen to be flagged True.
    """

    @staticmethod
    def _build_linear_graph(n, is_real, seg_lengths_km):
        """Build a linear chain graph: 0 <- 1 <- 2 <- ... <- n-1.

        Node 0 is the outlet.  Returns (cg, upstream_indices).
        """
        cg = CatchmentGraph()
        cg._n = n
        cg._loaded = True
        cg._segment_idx = np.arange(1, n + 1, dtype=np.int32)
        cg._threshold_m2 = np.full(n, 10000, dtype=np.int32)
        cg._area_km2 = np.full(n, 1.0, dtype=np.float32)
        cg._elev_min = np.arange(100, 100 + n * 10, 10, dtype=np.float32)[::-1]
        cg._elev_max = cg._elev_min + 10.0
        cg._elev_mean = cg._elev_min + 5.0
        cg._slope_mean = np.full(n, 3.0, dtype=np.float32)
        cg._perimeter_km = np.full(n, 5.0, dtype=np.float32)
        cg._stream_length_km = np.array(seg_lengths_km, dtype=np.float32)
        cg._hydraulic_length_km = np.full(n, 10.0, dtype=np.float32)
        cg._strahler = np.ones(n, dtype=np.int8)
        cg._histograms = [None] * n

        cg._is_real_stream = np.array(is_real, dtype=np.bool_)
        cg._segment_length_km = np.array(seg_lengths_km, dtype=np.float64)

        cg._lookup = {(10000, i + 1): i for i in range(n)}

        # Linear chain: node i+1 drains into node i
        if n > 1:
            rows = np.arange(0, n - 1, dtype=np.int32)
            cols = np.arange(1, n, dtype=np.int32)
            data = np.ones(n - 1, dtype=np.int8)
            cg._upstream_adj = sparse.csr_matrix(
                (data, (rows, cols)), shape=(n, n), dtype=np.int8
            )
        else:
            cg._upstream_adj = sparse.csr_matrix((n, n), dtype=np.int8)

        upstream = cg.traverse_upstream(0)
        return cg, upstream

    def test_fragmented_flags_only_count_contiguous_from_outlet(self):
        """Pattern real-real-FALSE-real: only first 2 segments counted."""
        #                  outlet                     head
        # Node:              0      1      2      3
        # is_real:          True   True   False  True
        # seg_length_km:    0.5    0.3    0.4    0.6
        cg, upstream = self._build_linear_graph(
            n=4,
            is_real=[True, True, False, True],
            seg_lengths_km=[0.5, 0.3, 0.4, 0.6],
        )
        result = cg.trace_main_channel(0, upstream)
        # Contiguous from outlet: 0.5 + 0.3 = 0.8 (stop at node 2, False)
        assert result["real_channel_length_km"] == pytest.approx(0.8, abs=0.001)

    def test_all_real_gives_full_length(self):
        """All segments real -> real_channel = full channel length."""
        cg, upstream = self._build_linear_graph(
            n=3,
            is_real=[True, True, True],
            seg_lengths_km=[1.0, 0.5, 0.7],
        )
        result = cg.trace_main_channel(0, upstream)
        assert result["real_channel_length_km"] == pytest.approx(2.2, abs=0.001)

    def test_first_segment_not_real_gives_zero(self):
        """If outlet segment is not real -> real_channel = 0."""
        cg, upstream = self._build_linear_graph(
            n=3,
            is_real=[False, True, True],
            seg_lengths_km=[1.0, 0.5, 0.7],
        )
        result = cg.trace_main_channel(0, upstream)
        assert result["real_channel_length_km"] == pytest.approx(0.0, abs=0.001)

    def test_alternating_pattern_stops_at_first_gap(self):
        """Pattern real-FALSE-real-FALSE-real: only 1st segment counted."""
        cg, upstream = self._build_linear_graph(
            n=5,
            is_real=[True, False, True, False, True],
            seg_lengths_km=[0.3, 0.2, 0.4, 0.1, 0.5],
        )
        result = cg.trace_main_channel(0, upstream)
        # Only node 0 (0.3 km) before first gap
        assert result["real_channel_length_km"] == pytest.approx(0.3, abs=0.001)

    def test_all_not_real_gives_zero(self):
        """All segments not real -> real_channel = 0."""
        cg, upstream = self._build_linear_graph(
            n=3,
            is_real=[False, False, False],
            seg_lengths_km=[1.0, 0.5, 0.7],
        )
        result = cg.trace_main_channel(0, upstream)
        assert result["real_channel_length_km"] == pytest.approx(0.0, abs=0.001)

    def test_single_node_real(self):
        """Single real node -> real_channel = its length."""
        cg, upstream = self._build_linear_graph(
            n=1,
            is_real=[True],
            seg_lengths_km=[1.5],
        )
        result = cg.trace_main_channel(0, upstream)
        assert result["real_channel_length_km"] == pytest.approx(1.5, abs=0.001)

    def test_single_node_not_real(self):
        """Single non-real node -> real_channel = 0."""
        cg, upstream = self._build_linear_graph(
            n=1,
            is_real=[False],
            seg_lengths_km=[1.5],
        )
        result = cg.trace_main_channel(0, upstream)
        assert result["real_channel_length_km"] == pytest.approx(0.0, abs=0.001)


class TestGetCatchmentGraphThreadSafety:
    """Tests for get_catchment_graph() singleton thread safety (CR7)."""

    def test_returns_same_instance(self):
        """Concurrent calls return the same CatchmentGraph instance."""
        import threading

        import core.catchment_graph as cg_module

        cg_module._catchment_graph = None
        instances = []

        def get_instance():
            instances.append(cg_module.get_catchment_graph())

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(instances) == 10
        assert all(inst is instances[0] for inst in instances)
        cg_module._catchment_graph = None

    def test_lock_exists(self):
        """Module-level lock exists for singleton protection."""
        import threading

        from core.catchment_graph import _catchment_graph_lock
        assert isinstance(_catchment_graph_lock, threading.Lock)


class TestTraverseToConfluenceDeque:
    """Verify traverse_to_confluence uses collections.deque (CR4)."""

    def test_uses_deque_not_list(self):
        """Implementation must use deque for O(1) popleft."""
        import inspect

        from core.catchment_graph import CatchmentGraph
        source = inspect.getsource(
            CatchmentGraph.traverse_to_confluence,
        )
        assert "deque" in source, (
            "traverse_to_confluence should use collections.deque"
        )
        assert ".pop(0)" not in source, (
            "traverse_to_confluence should not use list.pop(0)"
        )


class TestGetSegmentIdx:
    """Tests for public get_segment_idx() accessor (CR6)."""

    def test_returns_correct_segment_idx(self, small_graph):
        assert small_graph.get_segment_idx(0) == 1
        assert small_graph.get_segment_idx(1) == 2
        assert small_graph.get_segment_idx(2) == 3
        assert small_graph.get_segment_idx(3) == 4

    def test_returns_int(self, small_graph):
        result = small_graph.get_segment_idx(0)
        assert isinstance(result, int)

    def test_raises_when_not_loaded(self):
        import pytest

        from core.catchment_graph import CatchmentGraph
        cg = CatchmentGraph()
        with pytest.raises(RuntimeError, match="not loaded"):
            cg.get_segment_idx(0)


class TestHydraulicLength:
    """Tests for hydraulic_length_km in aggregate_stats."""

    def test_full_watershed_max(self, small_graph):
        """Hydraulic length of full watershed = max across all sub-catchments."""
        indices = np.array([0, 1, 2, 3])
        stats = small_graph.aggregate_stats(indices)
        # Node 0 has highest hydraulic_length_km = 12.5
        assert stats["hydraulic_length_km"] == pytest.approx(12.5, abs=0.01)

    def test_partial_watershed(self, small_graph):
        """Hydraulic length of partial watershed (only headwaters)."""
        indices = np.array([0, 1])
        stats = small_graph.aggregate_stats(indices)
        # max(12.5, 10.0) = 12.5
        assert stats["hydraulic_length_km"] == pytest.approx(12.5, abs=0.01)

    def test_single_subcatchment(self, small_graph):
        """Hydraulic length of single sub-catchment is its own value."""
        indices = np.array([3])
        stats = small_graph.aggregate_stats(indices)
        assert stats["hydraulic_length_km"] == pytest.approx(5.0, abs=0.01)

    def test_hydraulic_length_positive(self, small_graph):
        """Hydraulic length must be positive."""
        for node_idx in range(4):
            indices = np.array([node_idx])
            stats = small_graph.aggregate_stats(indices)
            assert stats["hydraulic_length_km"] > 0

    def test_hydraulic_length_ge_channel_length(self, small_graph):
        """Hydraulic length >= main channel length (includes overland flow)."""
        upstream = small_graph.traverse_upstream(3)
        stats = small_graph.aggregate_stats(upstream)
        main_ch = small_graph.trace_main_channel(3, upstream)
        assert stats["hydraulic_length_km"] >= main_ch["main_channel_length_km"]

    def test_nan_handling(self):
        """If all sub-catchments have NaN hydraulic length, return None."""
        cg = CatchmentGraph()
        n = 2
        cg._n = n
        cg._loaded = True
        cg._segment_idx = np.array([1, 2], dtype=np.int32)
        cg._threshold_m2 = np.array([10000, 10000], dtype=np.int32)
        cg._area_km2 = np.array([5.0, 3.0], dtype=np.float32)
        cg._elev_min = np.full(n, np.nan, dtype=np.float32)
        cg._elev_max = np.full(n, np.nan, dtype=np.float32)
        cg._elev_mean = np.full(n, np.nan, dtype=np.float32)
        cg._slope_mean = np.full(n, np.nan, dtype=np.float32)
        cg._perimeter_km = np.full(n, np.nan, dtype=np.float32)
        cg._stream_length_km = np.full(n, np.nan, dtype=np.float32)
        cg._hydraulic_length_km = np.full(n, np.nan, dtype=np.float32)
        cg._strahler = np.zeros(n, dtype=np.int8)
        cg._upstream_adj = sparse.csr_matrix((n, n), dtype=np.int8)

        stats = cg.aggregate_stats(np.array([0, 1]))
        assert stats["hydraulic_length_km"] is None
