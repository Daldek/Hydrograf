"""
In-memory graph of sub-catchments for fast upstream traversal.

Loads the sub-catchment nodes from PostGIS into numpy arrays and a scipy
sparse matrix at API startup, and again when the network in the database
changes (loaded_catchment_graph, network_version). Enables BFS traversal +
stat aggregation in ~5-50ms.

Memory usage: ~0.5 MB RAM.
"""

import logging
import threading
import time
from collections.abc import Iterable
from typing import Any

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import breadth_first_order
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_FETCH_SIZE = 50_000

# Placeholder of an unloaded graph; never mutated, replaced by load().
_EMPTY: np.ndarray = np.empty(0)


def _measured(values: np.ndarray, idx: int) -> float | None:
    """Value of a node, None when it was not measured (NaN or not loaded)."""
    if idx >= values.size:
        return None
    value = float(values[idx])
    return None if np.isnan(value) else value


# Consecutive segments without a BDOT10k stream that the main channel along BDOT10k
# streams bridges: the flow path of the DEM can leave the BDOT10k channel for a
# segment or two at bends and meanders, or run between two parallel channels whose
# buffers alternate.
MAX_REAL_CHANNEL_GAP = 2


def contiguous_real_length_km(
    is_real: Iterable[bool], lengths_km: Iterable[float]
) -> float:
    """Length of a main channel along BDOT10k streams, counted from its outlet.

    The segments come from the outlet upstream. The length adds up the segments
    matched to BDOT10k streams from the outlet, with the gaps of at most
    MAX_REAL_CHANNEL_GAP consecutive unmatched segments between two matched ones;
    it stops at the first unmatched segment before any matched one and at a longer
    gap: everything above is overland flow, even where later segments are matched.

    Parameters
    ----------
    is_real : Iterable[bool]
        Whether each segment matches a BDOT10k stream, from the outlet upstream.
    lengths_km : Iterable[float]
        Length of each segment [km], in the same order.

    Returns
    -------
    float
        The length [km], 0 when the segment of the outlet is unmatched.
    """
    contiguous_real_km = 0.0
    gap_count = 0
    pending_gap_km = 0.0
    started = False  # gap tolerance only after the first real segment
    for real, length_km in zip(is_real, lengths_km, strict=True):
        if real:
            started = True
            contiguous_real_km += pending_gap_km + length_km
            pending_gap_km = 0.0
            gap_count = 0
        else:
            if not started:
                break  # not real before any real one: no real channel
            gap_count += 1
            if gap_count > MAX_REAL_CHANNEL_GAP:
                break
            pending_gap_km += length_km
    return contiguous_real_km


# Column indices for stream_catchments SELECT in load()
(
    _COL_SEG_IDX,
    _COL_THRESHOLD,
    _COL_AREA,
    _COL_ELEV_MEAN,
    _COL_SLOPE,
    _COL_STRAHLER,
    _COL_DS_SEG_IDX,
    _COL_ELEV_MIN,
    _COL_ELEV_MAX,
    _COL_PERIMETER,
    _COL_STREAM_LEN,
    _COL_HISTOGRAM,
    _COL_HYDRAULIC_LEN,
    _COL_FLOW_DIST,
    _COL_OUTLET_DIST,
    _COL_HEAD_ELEV,
    _COL_OVERLAND_LEN,
    _COL_OVERLAND_DROP,
    _COL_STREAM_HEAD_ELEV,
) = range(19)


class CatchmentGraph:
    """
    In-memory graph of sub-catchments (~87k nodes).

    Each node represents a sub-catchment (one per stream segment per threshold).
    Upstream adjacency is stored as a scipy CSR sparse matrix for BFS.
    Per-node stats are stored in numpy arrays for fast aggregation.
    """

    def __init__(self) -> None:
        self._loaded = False
        # network_version() of the database when the graph was loaded
        # (set by loaded_catchment_graph)
        self.network_version: tuple[int | None, ...] | None = None
        self._n = 0

        # Per-node numpy arrays (indexed 0..n-1); empty until load()
        self._segment_idx: np.ndarray = _EMPTY
        self._threshold_m2: np.ndarray = _EMPTY
        self._area_km2: np.ndarray = _EMPTY
        self._elev_min: np.ndarray = _EMPTY
        self._elev_max: np.ndarray = _EMPTY
        self._elev_mean: np.ndarray = _EMPTY
        self._slope_mean: np.ndarray = _EMPTY
        self._stream_length_km: np.ndarray = _EMPTY
        # Legacy per-subcatchment absolute distance (== max_flow_dist_m/1000).
        # Loaded for DB compatibility; NOT used by aggregate_stats — hydraulic
        # length is computed from max_flow_dist_m and outlet_flow_dist_m (see
        # aggregate_stats). Do not reintroduce as a fallback: absolute values
        # caused the feedback-#11 bug.
        self._hydraulic_length_km: np.ndarray = _EMPTY
        self._strahler: np.ndarray = _EMPTY
        self._max_flow_dist_m: np.ndarray = _EMPTY
        self._outlet_flow_dist_m: np.ndarray | None = None
        # Head of each node's longest flow path: its elevation and the
        # overland segment down to the node's stream (NaN: not measured)
        self._flow_path_head_elev_m: np.ndarray = _EMPTY
        self._overland_length_m: np.ndarray = _EMPTY
        self._overland_drop_m: np.ndarray = _EMPTY
        # Elevation of the upstream end of each node's stream segment
        self._stream_head_elev_m: np.ndarray = _EMPTY

        # Per-segment data from stream_network (loaded separately)
        self._is_real_stream: np.ndarray | None = None
        self._segment_length_km: np.ndarray | None = None
        self._upstream_area_km2: np.ndarray | None = None

        # Adjacency: adj[i, j] = 1 means node j drains into node i
        self._upstream_adj: sparse.csr_matrix = sparse.csr_matrix((0, 0))

        # Index lookup: (threshold_m2, segment_idx) → internal idx
        self._lookup: dict[tuple[int, int], int] = {}

        # Elevation histograms: list of dicts per node (variable size)
        self._histograms: list[dict[str, Any] | None] = []

    @property
    def loaded(self) -> bool:
        """Whether the graph has been loaded from the database."""
        return self._loaded

    def load(self, db: Session) -> None:
        """
        Load sub-catchment graph from database into memory.

        Reads all rows from stream_catchments, builds numpy arrays
        and sparse upstream adjacency matrix. A graph is loaded once:
        loaded_catchment_graph loads a new one when the network changes.
        """
        if self._loaded:
            return

        t0 = time.time()
        logger.info("Loading catchment graph into memory...")

        # Count
        count_result = db.execute(
            text("SELECT COUNT(*) FROM stream_catchments")
        ).fetchone()
        n = count_result[0] if count_result is not None else 0
        if n == 0:
            logger.warning("stream_catchments is empty, graph not loaded")
            return

        logger.info(f"stream_catchments: {n:,} rows")

        self._n = n

        # Pre-allocate arrays
        self._segment_idx = np.empty(n, dtype=np.int32)
        self._threshold_m2 = np.empty(n, dtype=np.int32)
        self._area_km2 = np.empty(n, dtype=np.float32)
        self._elev_min = np.full(n, np.nan, dtype=np.float32)
        self._elev_max = np.full(n, np.nan, dtype=np.float32)
        self._elev_mean = np.full(n, np.nan, dtype=np.float32)
        self._slope_mean = np.full(n, np.nan, dtype=np.float32)
        self._stream_length_km = np.full(n, np.nan, dtype=np.float32)
        self._hydraulic_length_km = np.full(n, np.nan, dtype=np.float32)
        self._strahler = np.zeros(n, dtype=np.int8)
        self._max_flow_dist_m = np.full(n, 0.0, dtype=np.float64)
        self._outlet_flow_dist_m = np.full(n, np.nan, dtype=np.float64)
        self._flow_path_head_elev_m = np.full(n, np.nan, dtype=np.float32)
        self._overland_length_m = np.full(n, np.nan, dtype=np.float32)
        self._overland_drop_m = np.full(n, np.nan, dtype=np.float32)
        self._stream_head_elev_m = np.full(n, np.nan, dtype=np.float32)
        self._histograms = [None] * n

        # Edge lists for sparse matrix
        edge_from = []  # upstream node
        edge_to = []  # downstream node

        # Stream via server-side cursor
        raw_conn = db.connection().connection
        cursor: Any = raw_conn.cursor(name="catchment_graph_load")
        try:
            cursor.itersize = _FETCH_SIZE
            cursor.execute(
                "SELECT segment_idx, threshold_m2, area_km2, "
                "mean_elevation_m, mean_slope_percent, strahler_order, "
                "downstream_segment_idx, elevation_min_m, elevation_max_m, "
                "perimeter_km, stream_length_km, elev_histogram, "
                "hydraulic_length_km, "
                "COALESCE(max_flow_dist_m, 0), "
                "outlet_flow_dist_m, "
                "flow_path_head_elev_m, overland_length_m, overland_drop_m, "
                "stream_head_elev_m "
                "FROM stream_catchments ORDER BY threshold_m2, segment_idx"
            )

            i = 0
            while True:
                rows = cursor.fetchmany(_FETCH_SIZE)
                if not rows:
                    break
                for r in rows:
                    seg_idx = r[_COL_SEG_IDX]
                    threshold = r[_COL_THRESHOLD]

                    self._segment_idx[i] = seg_idx
                    self._threshold_m2[i] = threshold
                    self._area_km2[i] = (
                        r[_COL_AREA] if r[_COL_AREA] is not None else 0.0
                    )

                    if r[_COL_ELEV_MEAN] is not None:
                        self._elev_mean[i] = r[_COL_ELEV_MEAN]
                    if r[_COL_SLOPE] is not None:
                        self._slope_mean[i] = r[_COL_SLOPE]
                    if r[_COL_STRAHLER] is not None:
                        self._strahler[i] = r[_COL_STRAHLER]
                    if r[_COL_ELEV_MIN] is not None:
                        self._elev_min[i] = r[_COL_ELEV_MIN]
                    if r[_COL_ELEV_MAX] is not None:
                        self._elev_max[i] = r[_COL_ELEV_MAX]
                    if r[_COL_STREAM_LEN] is not None:
                        self._stream_length_km[i] = r[_COL_STREAM_LEN]

                    # Histogram (JSONB → dict)
                    self._histograms[i] = r[_COL_HISTOGRAM]

                    # Hydraulic length (flow path distance to outlet)
                    if r[_COL_HYDRAULIC_LEN] is not None:
                        self._hydraulic_length_km[i] = r[_COL_HYDRAULIC_LEN]

                    # max_flow_dist_m (COALESCE ensures 0 for NULL)
                    self._max_flow_dist_m[i] = r[_COL_FLOW_DIST]

                    if r[_COL_OUTLET_DIST] is not None:
                        self._outlet_flow_dist_m[i] = r[_COL_OUTLET_DIST]
                    if r[_COL_HEAD_ELEV] is not None:
                        self._flow_path_head_elev_m[i] = r[_COL_HEAD_ELEV]
                    if r[_COL_OVERLAND_LEN] is not None:
                        self._overland_length_m[i] = r[_COL_OVERLAND_LEN]
                    if r[_COL_OVERLAND_DROP] is not None:
                        self._overland_drop_m[i] = r[_COL_OVERLAND_DROP]
                    if r[_COL_STREAM_HEAD_ELEV] is not None:
                        self._stream_head_elev_m[i] = r[_COL_STREAM_HEAD_ELEV]

                    # Register in lookup
                    self._lookup[(threshold, seg_idx)] = i

                    # Downstream link → edge
                    ds_seg_idx = r[_COL_DS_SEG_IDX]
                    if ds_seg_idx is not None:
                        ds_key = (threshold, ds_seg_idx)
                        # Defer edge — downstream node may not be seen yet
                        edge_from.append(i)
                        edge_to.append(ds_key)

                    i += 1
        finally:
            cursor.close()
        if i != n:
            # A publication committed between the count and the read
            raise RuntimeError(
                f"stream_catchments changed during the load: {n:,} rows counted, "
                f"{i:,} read"
            )

        # Load is_real_stream, per-segment length and upstream_area from stream_network
        self._is_real_stream = np.zeros(n, dtype=np.bool_)
        self._segment_length_km = np.zeros(n, dtype=np.float64)
        self._upstream_area_km2 = np.zeros(n, dtype=np.float64)

        sn_cursor: Any = raw_conn.cursor(name="catchment_graph_stream_network")
        try:
            sn_cursor.itersize = _FETCH_SIZE
            sn_cursor.execute(
                "SELECT segment_idx, threshold_m2, "
                "COALESCE(is_real_stream, false) AS is_real, "
                "COALESCE(length_m, 0) / 1000.0 AS segment_length_km, "
                "COALESCE(upstream_area_km2, 0) AS upstream_area_km2 "
                "FROM stream_network "
                "ORDER BY threshold_m2, segment_idx"
            )

            while True:
                sn_rows = sn_cursor.fetchmany(_FETCH_SIZE)
                if not sn_rows:
                    break
                for sr in sn_rows:
                    sn_key = (sr[1], sr[0])  # (threshold_m2, segment_idx)
                    sn_idx = self._lookup.get(sn_key)
                    if sn_idx is not None:
                        self._is_real_stream[sn_idx] = sr[2]
                        self._segment_length_km[sn_idx] = sr[3]
                        self._upstream_area_km2[sn_idx] = sr[4]
        except Exception as e:
            logger.warning(
                f"Failed to load is_real_stream from stream_network: {e}. "
                "Defaulting to all false / 0.0."
            )
            self._is_real_stream = np.zeros(n, dtype=np.bool_)
            self._segment_length_km = np.zeros(n, dtype=np.float64)
            self._upstream_area_km2 = np.zeros(n, dtype=np.float64)
        finally:
            sn_cursor.close()

        # Resolve deferred edges
        resolved_from = []
        resolved_to = []
        for src_idx, ds_key in zip(edge_from, edge_to, strict=True):
            ds_idx = self._lookup.get(ds_key)
            if ds_idx is not None:
                resolved_from.append(src_idx)
                resolved_to.append(ds_idx)

        n_edges = len(resolved_from)

        # Build sparse upstream adjacency: adj[downstream, upstream] = 1
        if n_edges > 0:
            from_arr = np.array(resolved_from, dtype=np.int32)
            to_arr = np.array(resolved_to, dtype=np.int32)
            self._upstream_adj = sparse.csr_matrix(
                (
                    np.ones(n_edges, dtype=np.int8),
                    (to_arr, from_arr),
                ),
                shape=(n, n),
                dtype=np.int8,
            )
        else:
            self._upstream_adj = sparse.csr_matrix((n, n), dtype=np.int8)

        # Memory report
        mem_arrays = sum(
            arr.nbytes
            for arr in [
                self._segment_idx,
                self._threshold_m2,
                self._area_km2,
                self._elev_min,
                self._elev_max,
                self._elev_mean,
                self._slope_mean,
                self._stream_length_km,
                self._hydraulic_length_km,
                self._strahler,
                self._max_flow_dist_m,
                self._outlet_flow_dist_m,
                self._flow_path_head_elev_m,
                self._overland_length_m,
                self._overland_drop_m,
                self._stream_head_elev_m,
                self._is_real_stream,
                self._segment_length_km,
                self._upstream_area_km2,
            ]
        )
        mem_sparse = (
            self._upstream_adj.data.nbytes
            + self._upstream_adj.indices.nbytes
            + self._upstream_adj.indptr.nbytes
        )
        total_mb = (mem_arrays + mem_sparse) / 1024 / 1024
        elapsed = time.time() - t0

        logger.info(
            f"Catchment graph loaded: {n:,} nodes, {n_edges:,} edges "
            f"in {elapsed:.1f}s ({total_mb:.1f} MB RAM)"
        )

        n_missing_outlet = int(np.isnan(self._outlet_flow_dist_m).sum())
        if n_missing_outlet > 0:
            logger.warning(
                "%d/%d catchments missing outlet_flow_dist_m — "
                "hydraulic_length_km will use understating fallback; "
                "run scripts/backfill_outlet_flow_dist.py",
                n_missing_outlet,
                self._n,
            )
        n_missing_head = int(np.isnan(self._flow_path_head_elev_m).sum())
        if n_missing_head > 0:
            logger.warning(
                "%d/%d catchments missing flow_path_head_elev_m — the flow path "
                "slope, overland segment and channel slope stay empty; "
                "run scripts/backfill_flow_path_heads.py",
                n_missing_head,
                self._n,
            )

        # Quick integrity check (set _loaded temporarily for verify_graph)
        self._loaded = True
        try:
            report = self.verify_graph()
            for t, info in report["thresholds"].items():
                if not info["segment_idx_ok"]:
                    logger.error(
                        f"Threshold {t}: duplicate segment_idx! "
                        f"{info['unique_segment_idx']}/{info['nodes']}"
                    )
                logger.info(
                    f"Threshold {t}: {info['nodes']} nodes, "
                    f"{info['outlets']} outlets, "
                    f"{info['with_upstream']} with upstream"
                )
        except Exception:
            logger.exception("Graph verification failed")

    def find_catchment_at_point(
        self,
        x: float,
        y: float,
        threshold_m2: int,
        db: Session,
    ) -> int:
        """
        Find the sub-catchment containing a point via ST_Contains.

        Parameters
        ----------
        x, y : float
            Point coordinates in PL-1992 (EPSG:2180)
        threshold_m2 : int
            Flow accumulation threshold
        db : Session
            Database session for spatial query

        Returns
        -------
        int
            Internal index of the catchment node

        Raises
        ------
        ValueError
            If no catchment found at point
        """
        if not self._loaded:
            raise RuntimeError("Catchment graph not loaded")

        result = db.execute(
            text(
                "SELECT segment_idx FROM stream_catchments "
                "WHERE threshold_m2 = :threshold "
                "AND ST_Contains(geom, ST_SetSRID(ST_Point(:x, :y), 2180)) "
                "LIMIT 1"
            ),
            {"threshold": threshold_m2, "x": x, "y": y},
        ).fetchone()

        if result is None:
            raise ValueError(
                "Nie znaleziono zlewni cząstkowej w tym punkcie. "
                "Kliknij w obszarze pokrytym liniami spływu."
            )

        key = (threshold_m2, result.segment_idx)
        idx = self._lookup.get(key)
        if idx is None:
            raise ValueError(
                f"Segment {result.segment_idx} (threshold={threshold_m2}) "
                f"not found in catchment graph"
            )
        return idx

    def lookup_by_segment_idx(
        self,
        threshold_m2: int,
        segment_idx: int,
    ) -> int | None:
        """Look up internal graph index by (threshold_m2, segment_idx)."""
        if not self._loaded:
            raise RuntimeError("Catchment graph not loaded")
        return self._lookup.get((threshold_m2, segment_idx))

    def get_segment_idx(self, internal_idx: int) -> int:
        """Get segment_idx for a node by its internal graph index."""
        if not self._loaded:
            raise RuntimeError("Catchment graph not loaded")
        return int(self._segment_idx[internal_idx])

    def get_max_flow_dist_m(self, internal_idx: int) -> float:
        """Get max_flow_dist_m for a node by its internal graph index."""
        if not self._loaded:
            raise RuntimeError("Catchment graph not loaded")
        return float(self._max_flow_dist_m[internal_idx])

    def get_outlet_flow_dist_m(self, internal_idx: int) -> float:
        """Flow distance [m] at the node's outlet point (NaN if not loaded)."""
        if not self._loaded:
            raise RuntimeError("Catchment graph not loaded")
        if self._outlet_flow_dist_m is None:
            return float("nan")
        return float(self._outlet_flow_dist_m[internal_idx])

    def thresholds_m2(self) -> list[int]:
        """Flow accumulation thresholds [m²] of the graph's nodes, ascending."""
        if not self._loaded:
            raise RuntimeError("Catchment graph not loaded")
        return [int(t) for t in np.unique(self._threshold_m2)]

    def verify_graph(self, db: Session | None = None) -> dict[str, Any]:
        """Verify graph integrity. Returns diagnostic dict."""
        if not self._loaded:
            raise RuntimeError("Catchment graph not loaded")

        thresholds = np.unique(self._threshold_m2)
        report: dict[str, Any] = {"thresholds": {}, "total_nodes": self._n}
        # Upstream neighbours of each node: the stored entries of its CSR row
        upstream_counts = np.diff(self._upstream_adj.indptr)

        for t in thresholds:
            t = int(t)
            mask = self._threshold_m2 == t
            indices = np.where(mask)[0]
            n_nodes = len(indices)

            # Count edges (nodes with at least one upstream neighbor)
            n_with_upstream = int(np.count_nonzero(upstream_counts[indices]))
            # Count outlets (nodes with no downstream = no node points to them)
            col_sums = self._upstream_adj[:, indices].sum(axis=0).A1
            n_outlets = int(np.sum(col_sums == 0))

            # Check segment_idx consistency
            seg_idxs = self._segment_idx[indices]
            n_unique = len(np.unique(seg_idxs))

            report["thresholds"][t] = {
                "nodes": n_nodes,
                "with_upstream": n_with_upstream,
                "outlets": n_outlets,
                "unique_segment_idx": n_unique,
                "segment_idx_ok": n_unique == n_nodes,
            }

        if db is not None:
            result = db.execute(
                text("""
                SELECT sn.threshold_m2, COUNT(*) as mismatches
                FROM stream_network sn
                LEFT JOIN stream_catchments sc
                  ON sn.threshold_m2 = sc.threshold_m2
                  AND sn.segment_idx = sc.segment_idx
                WHERE sc.segment_idx IS NULL AND sn.segment_idx IS NOT NULL
                GROUP BY sn.threshold_m2
            """)
            ).fetchall()
            report["segment_idx_mismatches"] = {
                r.threshold_m2: r.mismatches for r in result
            }
            if report["segment_idx_mismatches"]:
                logger.warning(
                    f"segment_idx mismatches: {report['segment_idx_mismatches']}"
                )

        return report

    def traverse_upstream(self, start_idx: int) -> np.ndarray:
        """
        BFS upstream traversal from a catchment node.

        Parameters
        ----------
        start_idx : int
            Internal index of the starting node

        Returns
        -------
        np.ndarray
            Array of internal indices (including start_idx)
        """
        if not self._loaded:
            raise RuntimeError("Catchment graph not loaded")

        order: np.ndarray = breadth_first_order(
            self._upstream_adj,
            start_idx,
            directed=True,
            return_predecessors=False,
        )
        return order

    def upstream_segments_by_depth(
        self,
        start_idx: int,
    ) -> tuple[list[int], list[int]]:
        """
        Sub-catchments upstream of a node in BFS order, with their depth.

        Parameters
        ----------
        start_idx : int
            Internal index of the starting node

        Returns
        -------
        tuple[list[int], list[int]]
            segment_idx of every node reached by traverse_upstream(start_idx),
            in its BFS order (edges link nodes of one threshold, so all share
            the threshold of start_idx), and for each of them the number of
            drainage links up from start_idx: 0 for start_idx itself,
            non-decreasing along the order.
        """
        if not self._loaded:
            raise RuntimeError("Catchment graph not loaded")

        order, predecessors = breadth_first_order(
            self._upstream_adj,
            start_idx,
            directed=True,
            return_predecessors=True,
        )
        nodes = order.tolist()
        depth_of = {nodes[0]: 0}
        for node, downstream in zip(
            nodes[1:],
            predecessors[order[1:]].tolist(),
            strict=True,
        ):
            depth_of[node] = depth_of[downstream] + 1
        depths = [depth_of[node] for node in nodes]
        return self._segment_idx[order].tolist(), depths

    def trace_downstream(self, start_idx: int) -> np.ndarray:
        """
        Nodes from a catchment node down to the outlet of its network.

        Parameters
        ----------
        start_idx : int
            Internal index of the starting node

        Returns
        -------
        np.ndarray
            Internal indices in the order of the flow: start_idx first, the
            outlet of the network (the node that drains into no other) last
        """
        if not self._loaded:
            raise RuntimeError("Catchment graph not loaded")

        # Every node drains into one node at most, so the search over the
        # reversed edges walks the single path downstream
        order: np.ndarray = breadth_first_order(
            self._upstream_adj.T,
            start_idx,
            directed=True,
            return_predecessors=False,
        )
        return order

    def get_segment_indices(
        self,
        indices: np.ndarray,
        threshold_m2: int,
    ) -> list[int]:
        """
        Get segment_idx values for given internal indices, filtered by threshold.

        Parameters
        ----------
        indices : np.ndarray
            Internal indices from traverse_upstream()
        threshold_m2 : int
            Only return segments matching this threshold

        Returns
        -------
        list[int]
            List of segment_idx values
        """
        mask = self._threshold_m2[indices] == threshold_m2
        segment_idxs: list[int] = self._segment_idx[indices[mask]].tolist()
        return segment_idxs

    def aggregate_stats(
        self, indices: np.ndarray, outlet_idx: int | None = None
    ) -> dict[str, Any]:
        """
        Aggregate pre-computed stats across multiple catchment nodes.

        Parameters
        ----------
        indices : np.ndarray
            Internal indices from traverse_upstream()
        outlet_idx : int | None
            Internal index of the watershed outlet node. Required to compute
            hydraulic_length_km — without it the length cannot be anchored
            to the selected watershed's outlet and is returned as None.

        Returns
        -------
        dict
            Aggregated statistics:
            - area_km2: sum
            - elevation_min_m: min
            - elevation_max_m: max
            - elevation_mean_m: area-weighted mean
            - mean_slope_percent: area-weighted mean
            - perimeter_km: sum (individual sub-catchment perimeters)
            - stream_length_km: sum
            - drainage_density_km_per_km2: total_stream_length / total_area
            - max_strahler_order: max
            - stream_frequency_per_km2: n_segments / total_area
            - hydraulic_length_km: (max(max_flow_dist_m) -
              outlet_flow_dist_m[outlet]) / 1000; None bez outlet_idx
            - flow_path_head_elevation_m, overland_length_km,
              overland_slope_m_per_m: the head of the longest flow path (the
              farthest cell of the node with the largest max_flow_dist_m) and
              its overland segment down to that node's stream; None when not
              measured, a slope also when it is not positive
        """
        areas = self._area_km2[indices]
        total_area = float(np.nansum(areas))

        # Elevation min/max
        elev_mins = self._elev_min[indices]
        elev_maxs = self._elev_max[indices]
        valid_min = elev_mins[~np.isnan(elev_mins)]
        valid_max = elev_maxs[~np.isnan(elev_maxs)]
        elev_min = float(np.min(valid_min)) if len(valid_min) > 0 else None
        elev_max = float(np.max(valid_max)) if len(valid_max) > 0 else None

        # Area-weighted mean elevation
        elev_means = self._elev_mean[indices]
        valid_elev = ~np.isnan(elev_means) & (areas > 0)
        if np.any(valid_elev):
            elev_mean = float(
                np.nansum(elev_means[valid_elev] * areas[valid_elev])
                / np.nansum(areas[valid_elev])
            )
        else:
            elev_mean = None

        # Area-weighted mean slope (percent → m/m for output)
        slope_means = self._slope_mean[indices]
        valid_slope = ~np.isnan(slope_means) & (areas > 0)
        if np.any(valid_slope):
            slope_pct = float(
                np.nansum(slope_means[valid_slope] * areas[valid_slope])
                / np.nansum(areas[valid_slope])
            )
            slope_m_per_m = slope_pct / 100.0
        else:
            slope_pct = None
            slope_m_per_m = None

        # Stream length (sum)
        stream_lengths = self._stream_length_km[indices]
        total_stream_km = float(np.nansum(stream_lengths))

        # Pre-compute real stream mask (used for Strahler + BDOT metrics)
        real_mask = (
            self._is_real_stream[indices] if self._is_real_stream is not None else None
        )

        # Max Strahler from BDOT real streams only
        if real_mask is not None:
            real_strahlers = self._strahler[indices][real_mask]
            max_strahler = (
                int(np.max(real_strahlers)) if len(real_strahlers) > 0 else None
            )
        else:
            strahlers = self._strahler[indices]
            max_strahler = int(np.max(strahlers)) if len(strahlers) > 0 else None

        # BDOT-based drainage metrics (real streams only)
        if real_mask is not None and self._segment_length_km is not None:
            real_lengths = self._segment_length_km[indices]
            bdot_stream_km = float(np.nansum(real_lengths[real_mask]))
            bdot_n_segments = int(np.sum(real_mask))
            bdot_drainage_density = (
                bdot_stream_km / total_area if total_area > 0 else None
            )
            bdot_stream_frequency = (
                bdot_n_segments / total_area if total_area > 0 else None
            )
        else:
            bdot_stream_km = 0.0
            bdot_n_segments = 0
            bdot_drainage_density = None
            bdot_stream_frequency = None

        # Hydraulic length: max_flow_dist_m stores the cumulative distance
        # from each subcatchment's farthest cell to the GLOBAL basin outlet
        # (from pyflwdir.stream_distance). The flow path length within the
        # SELECTED watershed is that maximum minus the flow distance at the
        # outlet POINT (outlet_flow_dist_m). Without outlet_idx the length
        # cannot be computed correctly, so it is None.
        hydraulic_length_km = None
        if self._max_flow_dist_m is not None and outlet_idx is not None:
            flow_dists = self._max_flow_dist_m[indices]
            max_flow_dist = float(np.max(flow_dists)) if len(flow_dists) > 0 else 0.0
            if max_flow_dist > 0:
                baseline = float("nan")
                if self._outlet_flow_dist_m is not None:
                    baseline = float(self._outlet_flow_dist_m[outlet_idx])
                if np.isnan(baseline):
                    # Un-backfilled data: understate (never inflate).
                    baseline = float(self._max_flow_dist_m[outlet_idx])
                hydraulic_length_km = max(0.0, max_flow_dist - baseline) / 1000.0

        # Head of the longest flow path and its overland segment
        head_elev = None
        overland_length_km = None
        overland_slope = None
        far = self._farthest_node(indices)
        if far is not None:
            head_elev = _measured(self._flow_path_head_elev_m, far)
            length_m = _measured(self._overland_length_m, far)
            drop_m = _measured(self._overland_drop_m, far)
            if length_m is not None and length_m > 0:
                overland_length_km = length_m / 1000.0
                if drop_m is not None and drop_m > 0:
                    overland_slope = drop_m / length_m

        return {
            "area_km2": round(total_area, 6),
            "elevation_min_m": round(elev_min, 2) if elev_min is not None else None,
            "elevation_max_m": round(elev_max, 2) if elev_max is not None else None,
            "elevation_mean_m": round(elev_mean, 2) if elev_mean is not None else None,
            "mean_slope_m_per_m": (
                round(slope_m_per_m, 6) if slope_m_per_m is not None else None
            ),
            "mean_slope_percent": (
                round(slope_pct, 2) if slope_pct is not None else None
            ),
            "stream_length_km": round(total_stream_km, 4),
            "drainage_density_km_per_km2": (
                round(bdot_drainage_density, 4)
                if bdot_drainage_density is not None
                else None
            ),
            "max_strahler_order": max_strahler,
            "stream_frequency_per_km2": (
                round(bdot_stream_frequency, 4)
                if bdot_stream_frequency is not None
                else None
            ),
            "bdot_stream_length_km": round(bdot_stream_km, 4),
            "bdot_stream_count": bdot_n_segments,
            "hydraulic_length_km": (
                round(hydraulic_length_km, 4)
                if hydraulic_length_km is not None
                else None
            ),
            "flow_path_head_elevation_m": (
                round(head_elev, 2) if head_elev is not None else None
            ),
            "overland_length_km": (
                round(overland_length_km, 4) if overland_length_km is not None else None
            ),
            "overland_slope_m_per_m": (
                round(overland_slope, 6) if overland_slope is not None else None
            ),
        }

    def _farthest_node(self, indices: np.ndarray) -> int | None:
        """Node of ``indices`` with the largest max_flow_dist_m, None when unknown.

        Its farthest cell is the head of the longest flow path of the nodes.
        """
        if len(indices) == 0 or self._max_flow_dist_m.size == 0:
            return None
        dists = self._max_flow_dist_m[indices]
        k = int(np.argmax(dists))
        return int(indices[k]) if dists[k] > 0 else None

    def trace_main_channel(
        self,
        outlet_idx: int,
        upstream_indices: np.ndarray,
    ) -> dict[str, Any]:
        """
        Trace the main channel upstream from outlet following highest Strahler order.

        At each confluence, selects the upstream branch with:
        1. Highest Strahler order
        2. Longest stream segment (tie-breaker)
        3. Largest catchment area (second tie-breaker)

        Parameters
        ----------
        outlet_idx : int
            Internal index of the outlet node
        upstream_indices : np.ndarray
            Internal indices from traverse_upstream() (defines watershed boundary)

        Returns
        -------
        dict
            - main_channel_length_km: float — sum of stream lengths
            - main_channel_slope_m_per_m: float | None — (elevation of the
              channel's source, the upstream end of the head node's stream
              segment, − elevation of the outlet) / length; None when an
              elevation is missing or the slope is not positive
            - main_channel_nodes: list[int] — path indices
            - real_channel_length_km: float | None — BDOT10k part from the outlet
        """
        if not self._loaded:
            raise RuntimeError("Catchment graph not loaded")

        upstream_set = set(upstream_indices.tolist())
        path = [outlet_idx]
        current = outlet_idx

        while True:
            neighbors = self._upstream_adj[current].indices
            # Filter to nodes within this watershed
            candidates = [n for n in neighbors if n in upstream_set]
            if not candidates:
                break

            # Select best upstream: max upstream_area_km2 (cumulative drainage
            # area from stream_network — true flow accumulation), then prefer
            # BDOT real stream, then Strahler, then local subcatchment area.
            # upstream_area_km2 is threshold-independent → consistent path.
            # Falls back to local area_km2 if upstream_area not loaded.
            _ua = self._upstream_area_km2
            best = max(
                candidates,
                key=lambda n: (
                    _ua[n] if _ua is not None else self._area_km2[n],
                    int(self._is_real_stream[n])
                    if self._is_real_stream is not None
                    else 0,
                    self._strahler[n],
                    self._area_km2[n],
                ),
            )
            path.append(best)
            current = best

        # Sum stream lengths along path
        path_arr = np.array(path, dtype=np.int32)
        lengths = self._stream_length_km[path_arr]
        main_length_km = float(np.nansum(lengths))

        # Slope from the source of the main channel (the upstream end of the
        # head node's stream segment), not from the highest point of the head
        # sub-catchment: feedback #13
        head_idx = path[-1]  # furthest upstream node
        source_elev = _measured(self._stream_head_elev_m, head_idx)
        outlet_elev = _measured(self._elev_min, outlet_idx)

        main_slope = None
        if main_length_km > 0 and source_elev is not None and outlet_elev is not None:
            slope = (source_elev - outlet_elev) / (main_length_km * 1000)
            if slope > 0:
                main_slope = round(slope, 6)

        # Real channel length: contiguous BDOT-matched segments from the outlet
        # (path_arr[0]) upstream
        real_length_km = None
        if self._is_real_stream is not None and self._segment_length_km is not None:
            real_length_km = contiguous_real_length_km(
                self._is_real_stream[path_arr], self._segment_length_km[path_arr]
            )

        return {
            "main_channel_length_km": round(main_length_km, 4),
            "main_channel_slope_m_per_m": main_slope,
            "main_channel_nodes": path,
            "real_channel_length_km": (
                round(real_length_km, 4) if real_length_km is not None else None
            ),
        }

    def aggregate_hypsometric(
        self,
        indices: np.ndarray,
        n_points: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Merge elevation histograms and produce a normalized hypsometric curve.

        Parameters
        ----------
        indices : np.ndarray
            Internal indices of catchment nodes
        n_points : int
            Number of points on the output curve (default: 20)

        Returns
        -------
        list[dict]
            List of {"relative_height": float, "relative_area": float} dicts.
            Empty list if no histograms available.
        """
        # Collect valid histograms
        histograms = []
        for idx in indices:
            h = self._histograms[idx]
            if h is not None and "counts" in h and len(h["counts"]) > 0:
                histograms.append(h)

        if not histograms:
            return []

        # Merge histograms on absolute elevation axis
        interval_m = histograms[0].get("interval_m", 1)
        global_min = min(h["base_m"] for h in histograms)
        global_max = max(
            h["base_m"] + len(h["counts"]) * interval_m for h in histograms
        )
        n_bins = max(1, (global_max - global_min) // interval_m)
        merged = np.zeros(n_bins, dtype=np.int64)

        for h in histograms:
            offset = (h["base_m"] - global_min) // interval_m
            counts = h["counts"]
            end = offset + len(counts)
            if end <= n_bins:
                merged[offset:end] += counts
            else:
                merged[offset:n_bins] += counts[: n_bins - offset]

        total_cells = int(merged.sum())
        if total_cells == 0:
            return []

        # Normalize to hypsometric curve
        cumulative = np.cumsum(merged[::-1])[::-1]  # area above each elevation
        elevations = np.arange(n_bins) * interval_m + global_min

        h_range = float(elevations[-1] - elevations[0])
        if h_range <= 0:
            return [
                {"relative_height": 0.0, "relative_area": 1.0},
                {"relative_height": 1.0, "relative_area": 0.0},
            ]

        # Sample at n_points evenly spaced relative heights
        curve = []
        for i in range(n_points + 1):
            rh = i / n_points  # relative height 0..1
            elev_threshold = elevations[0] + rh * h_range
            # Find cumulative area above this elevation
            bin_idx = int((elev_threshold - global_min) / interval_m)
            bin_idx = max(0, min(bin_idx, n_bins - 1))
            ra = float(cumulative[bin_idx]) / total_cells
            curve.append(
                {
                    "relative_height": round(rh, 4),
                    "relative_area": round(ra, 4),
                }
            )

        return curve


# Global singleton: the graph requests use. loaded_catchment_graph replaces it
# with a newly loaded graph when the network in the database changes.
_catchment_graph: CatchmentGraph | None = None
_catchment_graph_lock = threading.Lock()
# One load at a time: the requests that find the network changed wait for it
_reload_lock = threading.Lock()

# (file node, writes) of the two tables the graph is loaded from; NULLs for a
# table that does not exist
_NETWORK_VERSION_SQL = text("""
    SELECT pg_relation_filenode(t.oid) AS filenode,
           pg_stat_get_tuples_inserted(t.oid) + pg_stat_get_tuples_updated(t.oid)
               + pg_stat_get_tuples_deleted(t.oid) AS writes
    FROM (VALUES (1, to_regclass('stream_catchments')),
                 (2, to_regclass('stream_network'))) AS t(n, oid)
    ORDER BY t.n
""")


def get_catchment_graph() -> CatchmentGraph:
    """Get or create the global CatchmentGraph instance (thread-safe).

    The graph of the last load, which may not be loaded; requests take theirs
    from :func:`loaded_catchment_graph`.
    """
    global _catchment_graph
    if _catchment_graph is None:
        with _catchment_graph_lock:
            if _catchment_graph is None:
                _catchment_graph = CatchmentGraph()
    return _catchment_graph


def network_version(db: Session) -> tuple[int | None, ...]:
    """Return the version of the stream network in the database, cheap to read.

    The file nodes and the write counters of ``stream_catchments`` and
    ``stream_network`` in PostgreSQL's cumulative statistics. Every row that a
    publication of a run, the BDOT10k stream matching after it, a backfill or a
    manual change inserts, updates or deletes adds to the counters, and TRUNCATE
    gives a table a new file node. The writer's backend adds a transaction's
    counts after the transaction ends: when it goes idle, but at most once a
    second (otherwise ten seconds later), or when it disconnects. So a new
    version never comes before the rows it counts are committed, and comes
    seconds after. A reset of the statistics or a write that is rolled back
    changes the version without changing the network: one needless reload.

    Parameters
    ----------
    db : Session
        Database session. PostgreSQL keeps the statistics a transaction read first
        until it ends, so a session reads a new version in a new transaction.

    Returns
    -------
    tuple[int | None, ...]
        File node and writes of ``stream_catchments``, then of ``stream_network``;
        None for a table that does not exist.
    """
    rows = db.execute(_NETWORK_VERSION_SQL).fetchall()
    return tuple(value for row in rows for value in (row.filenode, row.writes))


def loaded_catchment_graph(db: Session) -> CatchmentGraph | None:
    """Return the graph of the network that the database holds now, or None.

    Reads :func:`network_version` and, when it differs from the version the
    current graph was loaded at (a run was published, the whole raster processed
    again, the tables cleaned), loads a new graph and makes it the current one.
    Each API worker does so at its first request after the change. A request
    keeps the graph it got until it ends, so a reload never changes the graph
    under it; the requests that find the network changed wait for one load.

    Parameters
    ----------
    db : Session
        Database session the version is read and the graph loaded from.

    Returns
    -------
    CatchmentGraph | None
        The loaded graph; None when ``stream_catchments`` is empty or the load
        failed (logged; the next call loads again).
    """
    global _catchment_graph
    version = network_version(db)
    graph = get_catchment_graph()
    if graph.loaded and graph.network_version == version:
        return graph
    with _reload_lock:
        graph = get_catchment_graph()
        if graph.loaded and graph.network_version == version:
            return graph
        if graph.loaded:
            logger.info(
                "Network in the database changed (version %s, was %s): "
                "reloading the catchment graph",
                version,
                graph.network_version,
            )
        fresh = CatchmentGraph()
        try:
            fresh.load(db)
        except Exception:
            logger.exception("Catchment graph load failed")
            fresh = CatchmentGraph()
        fresh.network_version = version
        _catchment_graph = fresh
    return fresh if fresh.loaded else None
