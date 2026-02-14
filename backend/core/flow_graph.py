"""
In-memory flow graph for fast upstream traversal.

DEPRECATED: This module is no longer used by the API runtime.
Watershed delineation now uses CatchmentGraph (~87k nodes, ~8 MB)
instead of FlowGraph (~19.7M cells, ~1 GB). This module is retained
for potential use by CLI scripts (e.g., process_dem.py).

Loads the flow_network graph structure and cell attributes from PostGIS
into numpy arrays and a scipy sparse matrix at API startup, enabling
BFS traversal in ~50-200ms instead of 2-5s via SQL recursive CTE.
"""

import logging
import time

import numpy as np
from cachetools import TTLCache
from scipy import sparse
from scipy.sparse.csgraph import breadth_first_order
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Chunk size for server-side cursor fetching
_FETCH_SIZE = 100_000


class FlowGraph:
    """
    In-memory representation of the flow_network graph.

    Stores cell attributes in numpy arrays and upstream adjacency
    as a scipy CSR sparse matrix for fast BFS traversal.

    Memory usage: ~50 bytes/cell → ~1 GB for 19.7M cells.
    """

    def __init__(self):
        self._loaded = False
        self._n = 0
        self._min_id = 0
        self._contiguous = False
        self._traverse_cache: TTLCache = TTLCache(maxsize=128, ttl=3600)

        # DB ids sorted (for non-contiguous case)
        self._ids: np.ndarray | None = None

        # Cell attributes indexed 0..n-1
        self._x: np.ndarray | None = None
        self._y: np.ndarray | None = None
        self._elevation: np.ndarray | None = None
        self._flow_acc: np.ndarray | None = None
        self._slope: np.ndarray | None = None
        self._cell_area: np.ndarray | None = None
        self._is_stream: np.ndarray | None = None

        # Graph: adj[i, j] = 1 means cell j flows into cell i
        self._upstream_adj: sparse.csr_matrix | None = None

    @property
    def loaded(self) -> bool:
        return self._loaded

    def _resolve_idx(self, db_id: int) -> int:
        """Convert a database ID to internal array index."""
        if self._contiguous:
            idx = db_id - self._min_id
            if 0 <= idx < self._n:
                return idx
            raise ValueError(f"ID {db_id} not found in flow graph")
        idx = int(np.searchsorted(self._ids, db_id))
        if idx < self._n and self._ids[idx] == db_id:
            return idx
        raise ValueError(f"ID {db_id} not found in flow graph")

    def _idx_to_id(self, idx: int) -> int:
        """Convert internal array index to database ID."""
        if self._contiguous:
            return idx + self._min_id
        return int(self._ids[idx])

    def load(self, db: Session) -> None:
        """
        Load flow network from database into memory.

        Uses a server-side cursor to stream rows without loading all
        into Python memory at once. Populates numpy arrays and builds
        a sparse upstream adjacency matrix.
        """
        if self._loaded:
            return

        t0 = time.time()
        logger.info("Loading flow graph into memory...")

        # 1. Get table stats
        stats = db.execute(
            text("SELECT COUNT(*), MIN(id), MAX(id) FROM flow_network")
        ).fetchone()

        n = stats[0]
        if n == 0:
            logger.warning("flow_network is empty, graph not loaded")
            return

        min_id = stats[1]
        max_id = stats[2]
        id_range = max_id - min_id + 1
        contiguous = id_range == n

        logger.info(
            f"flow_network: {n:,} cells, "
            f"ID range {min_id}–{max_id} "
            f"({'contiguous' if contiguous else 'sparse'})"
        )

        self._n = n
        self._min_id = min_id
        self._contiguous = contiguous

        # 2. Pre-allocate numpy arrays
        self._x = np.empty(n, dtype=np.float64)
        self._y = np.empty(n, dtype=np.float64)
        self._elevation = np.empty(n, dtype=np.float32)
        self._flow_acc = np.empty(n, dtype=np.int32)
        self._slope = np.full(n, np.nan, dtype=np.float32)
        self._cell_area = np.empty(n, dtype=np.float32)
        self._is_stream = np.zeros(n, dtype=np.bool_)

        if not contiguous:
            self._ids = np.empty(n, dtype=np.int64)

        # Sparse matrix edge lists
        edge_from = []  # upstream cell index
        edge_to = []  # downstream cell index

        # 3. Stream rows via server-side cursor
        raw_conn = db.connection().connection
        cursor = raw_conn.cursor(name="flow_graph_load")
        cursor.itersize = _FETCH_SIZE
        cursor.execute(
            "SELECT id, ST_X(geom), ST_Y(geom), elevation, "
            "flow_accumulation, slope, downstream_id, "
            "cell_area, is_stream "
            "FROM flow_network ORDER BY id"
        )

        i = 0
        while True:
            rows = cursor.fetchmany(_FETCH_SIZE)
            if not rows:
                break
            for r in rows:
                cell_id = r[0]
                if contiguous:
                    idx = cell_id - min_id
                else:
                    idx = i
                    self._ids[i] = cell_id

                self._x[idx] = r[1]
                self._y[idx] = r[2]
                self._elevation[idx] = r[3]
                self._flow_acc[idx] = r[4]
                if r[5] is not None:
                    self._slope[idx] = r[5]
                self._cell_area[idx] = r[7]
                self._is_stream[idx] = bool(r[8])

                downstream_id = r[6]
                if downstream_id is not None:
                    if contiguous:
                        ds_idx = downstream_id - min_id
                        if 0 <= ds_idx < n:
                            edge_to.append(ds_idx)
                            edge_from.append(idx)
                    else:
                        # Defer resolution: store raw IDs
                        edge_from.append(cell_id)
                        edge_to.append(downstream_id)

                i += 1

        cursor.close()

        t_load = time.time() - t0
        logger.info(f"Fetched {i:,} rows in {t_load:.1f}s")

        # 4. Build sparse upstream adjacency matrix
        t_sparse = time.time()

        if not contiguous and edge_from:
            # Resolve raw IDs to indices via searchsorted
            edge_from_arr = np.array(edge_from, dtype=np.int64)
            edge_to_arr = np.array(edge_to, dtype=np.int64)
            edge_from_idx = np.searchsorted(self._ids, edge_from_arr)
            edge_to_idx = np.searchsorted(self._ids, edge_to_arr)
            # Filter valid edges
            valid = (
                (edge_from_idx < n)
                & (edge_to_idx < n)
                & (self._ids[edge_from_idx] == edge_from_arr)
                & (self._ids[edge_to_idx] == edge_to_arr)
            )
            edge_from_final = edge_from_idx[valid].astype(np.int32)
            edge_to_final = edge_to_idx[valid].astype(np.int32)
        else:
            edge_from_final = np.array(edge_from, dtype=np.int32)
            edge_to_final = np.array(edge_to, dtype=np.int32)

        n_edges = len(edge_from_final)

        # adj[downstream_idx, upstream_idx] = 1
        # This means: row i contains all cells that flow into cell i
        self._upstream_adj = sparse.csr_matrix(
            (
                np.ones(n_edges, dtype=np.int8),
                (edge_to_final, edge_from_final),
            ),
            shape=(n, n),
            dtype=np.int8,
        )

        t_build = time.time() - t_sparse

        # 5. Report memory usage
        mem_arrays = (
            self._x.nbytes
            + self._y.nbytes
            + self._elevation.nbytes
            + self._flow_acc.nbytes
            + self._slope.nbytes
            + self._cell_area.nbytes
            + self._is_stream.nbytes
        )
        mem_sparse = (
            self._upstream_adj.data.nbytes
            + self._upstream_adj.indices.nbytes
            + self._upstream_adj.indptr.nbytes
        )
        if self._ids is not None:
            mem_arrays += self._ids.nbytes

        total_mb = (mem_arrays + mem_sparse) / 1024 / 1024
        elapsed = time.time() - t0

        logger.info(
            f"Flow graph loaded: {n:,} cells, {n_edges:,} edges "
            f"in {elapsed:.1f}s ({total_mb:.0f} MB RAM, "
            f"sparse build {t_build:.1f}s)"
        )

        self._loaded = True

    def traverse_upstream(
        self,
        outlet_id: int,
        max_cells: int = 2_000_000,
    ) -> np.ndarray:
        """
        BFS upstream traversal from outlet cell.

        Uses scipy's Cython-optimized breadth_first_order on the
        sparse upstream adjacency matrix.

        Parameters
        ----------
        outlet_id : int
            Database ID of the outlet cell
        max_cells : int
            Safety limit for maximum watershed size

        Returns
        -------
        np.ndarray
            Internal indices of all cells in the watershed

        Raises
        ------
        RuntimeError
            If graph has not been loaded
        ValueError
            If outlet not found or watershed too large
        """
        if not self._loaded:
            raise RuntimeError("Flow graph not loaded")

        # Check cache
        if outlet_id in self._traverse_cache:
            return self._traverse_cache[outlet_id]

        outlet_idx = self._resolve_idx(outlet_id)

        # Pre-flight check using flow_accumulation
        estimated = int(self._flow_acc[outlet_idx]) + 1
        if estimated > max_cells:
            raise ValueError(
                f"Zlewnia zbyt duza: ~{estimated:,} komorek "
                f"(limit: {max_cells:,}). "
                f"Wybierz punkt blizej zrodla cieku."
            )

        # BFS via scipy (Cython, fast)
        node_order = breadth_first_order(
            self._upstream_adj,
            outlet_idx,
            directed=True,
            return_predecessors=False,
        )

        if len(node_order) > max_cells:
            raise ValueError(
                f"Zlewnia zbyt duza: {len(node_order):,} komorek (limit: {max_cells:,})"
            )

        # Cache result
        self._traverse_cache[outlet_id] = node_order
        return node_order

    def get_flow_cells(self, indices: np.ndarray):
        """
        Build FlowCell-compatible tuples for given internal indices.

        Returns a list of tuples matching the FlowCell constructor:
        (id, x, y, elevation, flow_accumulation, slope,
         downstream_id, cell_area, is_stream)
        """
        result = []
        for idx in indices:
            db_id = self._idx_to_id(idx)
            slope_val = float(self._slope[idx])
            slope_out = slope_val if not np.isnan(slope_val) else None

            result.append(
                (
                    db_id,
                    float(self._x[idx]),
                    float(self._y[idx]),
                    float(self._elevation[idx]),
                    int(self._flow_acc[idx]),
                    slope_out,
                    None,  # downstream_id not needed by callers
                    float(self._cell_area[idx]),
                    bool(self._is_stream[idx]),
                )
            )
        return result


# Global singleton
_flow_graph: FlowGraph | None = None


def get_flow_graph() -> FlowGraph:
    """Get or create the global FlowGraph instance."""
    global _flow_graph
    if _flow_graph is None:
        _flow_graph = FlowGraph()
    return _flow_graph
