"""
Unit tests for in-memory flow graph module.
"""

import numpy as np
import pytest
from scipy import sparse

from core.flow_graph import FlowGraph


def _make_graph(n_cells, edges, flow_acc=None):
    """
    Build a FlowGraph from a simple spec.

    Parameters
    ----------
    n_cells : int
        Number of cells (IDs will be 1..n_cells)
    edges : list[tuple[int, int]]
        (upstream_id, downstream_id) pairs
    flow_acc : dict[int, int] | None
        Override flow_accumulation values {db_id: value}
    """
    g = FlowGraph()
    g._n = n_cells
    g._min_id = 1
    g._contiguous = True

    g._x = np.arange(n_cells, dtype=np.float64) * 5.0 + 500000
    g._y = np.full(n_cells, 600000.0, dtype=np.float64)
    g._elevation = np.linspace(200, 150, n_cells).astype(np.float32)
    g._flow_acc = np.zeros(n_cells, dtype=np.int32)
    g._slope = np.full(n_cells, 2.5, dtype=np.float32)
    g._cell_area = np.full(n_cells, 1.0, dtype=np.float32)
    g._is_stream = np.zeros(n_cells, dtype=np.bool_)

    # Build adjacency
    if edges:
        us_ids = [e[0] for e in edges]
        ds_ids = [e[1] for e in edges]
        us_idx = [uid - 1 for uid in us_ids]
        ds_idx = [did - 1 for did in ds_ids]
        data = np.ones(len(edges), dtype=np.int8)
        g._upstream_adj = sparse.csr_matrix(
            (data, (ds_idx, us_idx)),
            shape=(n_cells, n_cells),
            dtype=np.int8,
        )
    else:
        g._upstream_adj = sparse.csr_matrix(
            (n_cells, n_cells), dtype=np.int8
        )

    # Set flow_accumulation
    if flow_acc:
        for db_id, val in flow_acc.items():
            g._flow_acc[db_id - 1] = val

    g._loaded = True
    return g


class TestFlowGraphResolveIdx:
    """Tests for ID ↔ index conversion."""

    def test_contiguous_id_to_idx(self):
        g = _make_graph(10, [])
        assert g._resolve_idx(1) == 0
        assert g._resolve_idx(5) == 4
        assert g._resolve_idx(10) == 9

    def test_contiguous_idx_to_id(self):
        g = _make_graph(10, [])
        assert g._idx_to_id(0) == 1
        assert g._idx_to_id(4) == 5
        assert g._idx_to_id(9) == 10

    def test_resolve_invalid_id_raises(self):
        g = _make_graph(10, [])
        with pytest.raises(ValueError, match="not found"):
            g._resolve_idx(0)
        with pytest.raises(ValueError, match="not found"):
            g._resolve_idx(11)

    def test_non_contiguous_resolve(self):
        """Test searchsorted-based resolution."""
        g = FlowGraph()
        g._n = 5
        g._contiguous = False
        g._ids = np.array([10, 20, 30, 40, 50], dtype=np.int64)
        g._loaded = True

        assert g._resolve_idx(10) == 0
        assert g._resolve_idx(30) == 2
        assert g._resolve_idx(50) == 4

    def test_non_contiguous_missing_id(self):
        g = FlowGraph()
        g._n = 3
        g._contiguous = False
        g._ids = np.array([10, 20, 30], dtype=np.int64)
        g._loaded = True

        with pytest.raises(ValueError, match="not found"):
            g._resolve_idx(15)


class TestFlowGraphTraversal:
    """Tests for BFS upstream traversal."""

    def test_single_cell_watershed(self):
        """Outlet with no upstream cells."""
        g = _make_graph(5, [])
        indices = g.traverse_upstream(3)
        assert list(indices) == [2]  # idx = id-1

    def test_linear_chain(self):
        """Linear chain: 5→4→3→2→1."""
        edges = [(2, 1), (3, 2), (4, 3), (5, 4)]
        g = _make_graph(5, edges, flow_acc={1: 4})
        indices = g.traverse_upstream(1)
        assert sorted(indices) == [0, 1, 2, 3, 4]

    def test_tree_graph(self):
        """
        Tree:
            1 (outlet)
           / \\
          2   3
         / \\
        4   5
        """
        edges = [(2, 1), (3, 1), (4, 2), (5, 2)]
        g = _make_graph(5, edges, flow_acc={1: 4})
        indices = g.traverse_upstream(1)
        assert sorted(indices) == [0, 1, 2, 3, 4]

    def test_subtree_from_middle(self):
        """Traverse from node 2, should get 2, 4, 5."""
        edges = [(2, 1), (3, 1), (4, 2), (5, 2)]
        g = _make_graph(5, edges, flow_acc={2: 2})
        indices = g.traverse_upstream(2)
        assert sorted(indices) == [1, 3, 4]

    def test_max_cells_limit(self):
        """Raise ValueError when watershed exceeds max_cells."""
        edges = [(2, 1), (3, 2), (4, 3)]
        g = _make_graph(4, edges, flow_acc={1: 3})
        with pytest.raises(ValueError, match="zbyt duza"):
            g.traverse_upstream(1, max_cells=2)

    def test_preflight_check(self):
        """Pre-flight check rejects large flow_accumulation."""
        g = _make_graph(10, [], flow_acc={5: 500_000})
        with pytest.raises(ValueError, match="zbyt duza"):
            g.traverse_upstream(5, max_cells=100)

    def test_not_loaded_raises(self):
        g = FlowGraph()
        with pytest.raises(RuntimeError, match="not loaded"):
            g.traverse_upstream(1)

    def test_invalid_outlet_raises(self):
        g = _make_graph(5, [])
        with pytest.raises(ValueError, match="not found"):
            g.traverse_upstream(99)


class TestFlowGraphGetCells:
    """Tests for get_flow_cells data extraction."""

    def test_returns_correct_attributes(self):
        g = _make_graph(3, [])
        g._x[0] = 500000.0
        g._y[0] = 600000.0
        g._elevation[0] = 150.0
        g._flow_acc[0] = 1000
        g._slope[0] = 2.5
        g._cell_area[0] = 1.0
        g._is_stream[0] = True

        cells = g.get_flow_cells(np.array([0]))
        assert len(cells) == 1
        c = cells[0]
        assert c[0] == 1  # db_id
        assert c[1] == 500000.0  # x
        assert c[2] == 600000.0  # y
        assert c[3] == pytest.approx(150.0, abs=0.1)  # elevation
        assert c[4] == 1000  # flow_acc
        assert c[5] == pytest.approx(2.5, abs=0.01)  # slope
        assert c[6] is None  # downstream_id (not stored)
        assert c[7] == 1.0  # cell_area
        assert c[8] is True  # is_stream

    def test_nan_slope_becomes_none(self):
        g = _make_graph(3, [])
        g._slope[1] = np.nan
        cells = g.get_flow_cells(np.array([1]))
        assert cells[0][5] is None

    def test_multiple_cells(self):
        g = _make_graph(5, [])
        cells = g.get_flow_cells(np.array([0, 2, 4]))
        assert len(cells) == 3
        assert cells[0][0] == 1  # id of idx 0
        assert cells[1][0] == 3  # id of idx 2
        assert cells[2][0] == 5  # id of idx 4


class TestFlowGraphLoadedProperty:
    """Tests for loaded state."""

    def test_initially_not_loaded(self):
        g = FlowGraph()
        assert g.loaded is False

    def test_loaded_after_setup(self):
        g = _make_graph(3, [])
        assert g.loaded is True
