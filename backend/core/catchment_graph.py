"""
In-memory graph of sub-catchments for fast upstream traversal.

Loads ~11k sub-catchment nodes from PostGIS into numpy arrays and a
scipy sparse matrix at API startup. Enables BFS traversal + stat
aggregation in ~5-50ms.

Memory usage: ~0.5 MB RAM.
"""

import logging
import threading
import time
from collections import deque

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import breadth_first_order
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_FETCH_SIZE = 50_000


class CatchmentGraph:
    """
    In-memory graph of sub-catchments (~87k nodes).

    Each node represents a sub-catchment (one per stream segment per threshold).
    Upstream adjacency is stored as a scipy CSR sparse matrix for BFS.
    Per-node stats are stored in numpy arrays for fast aggregation.
    """

    def __init__(self):
        self._loaded = False
        self._n = 0

        # Per-node numpy arrays (indexed 0..n-1)
        self._segment_idx: np.ndarray | None = None
        self._threshold_m2: np.ndarray | None = None
        self._area_km2: np.ndarray | None = None
        self._elev_min: np.ndarray | None = None
        self._elev_max: np.ndarray | None = None
        self._elev_mean: np.ndarray | None = None
        self._slope_mean: np.ndarray | None = None
        self._perimeter_km: np.ndarray | None = None
        self._stream_length_km: np.ndarray | None = None
        self._hydraulic_length_km: np.ndarray | None = None
        self._strahler: np.ndarray | None = None
        self._max_flow_dist_m: np.ndarray | None = None

        # Per-segment data from stream_network (loaded separately)
        self._is_real_stream: np.ndarray | None = None
        self._segment_length_km: np.ndarray | None = None

        # Adjacency: adj[i, j] = 1 means node j drains into node i
        self._upstream_adj: sparse.csr_matrix | None = None

        # Index lookup: (threshold_m2, segment_idx) → internal idx
        self._lookup: dict[tuple[int, int], int] = {}

        # Elevation histograms: list of dicts per node (variable size)
        self._histograms: list[dict | None] = []

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self, db: Session) -> None:
        """
        Load sub-catchment graph from database into memory.

        Reads all rows from stream_catchments, builds numpy arrays
        and sparse upstream adjacency matrix.
        """
        if self._loaded:
            return

        t0 = time.time()
        logger.info("Loading catchment graph into memory...")

        # Count
        count_result = db.execute(
            text("SELECT COUNT(*) FROM stream_catchments")
        ).fetchone()
        n = count_result[0]
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
        self._perimeter_km = np.full(n, np.nan, dtype=np.float32)
        self._stream_length_km = np.full(n, np.nan, dtype=np.float32)
        self._hydraulic_length_km = np.full(n, np.nan, dtype=np.float32)
        self._strahler = np.zeros(n, dtype=np.int8)
        self._max_flow_dist_m = np.full(n, 0.0, dtype=np.float64)
        self._histograms = [None] * n

        # Edge lists for sparse matrix
        edge_from = []  # upstream node
        edge_to = []  # downstream node

        # Stream via server-side cursor
        raw_conn = db.connection().connection
        cursor = raw_conn.cursor(name="catchment_graph_load")
        try:
            cursor.itersize = _FETCH_SIZE
            cursor.execute(
                "SELECT segment_idx, threshold_m2, area_km2, "
                "mean_elevation_m, mean_slope_percent, strahler_order, "
                "downstream_segment_idx, elevation_min_m, elevation_max_m, "
                "perimeter_km, stream_length_km, elev_histogram, "
                "hydraulic_length_km, "
                "COALESCE(max_flow_dist_m, 0) "
                "FROM stream_catchments ORDER BY threshold_m2, segment_idx"
            )

            i = 0
            while True:
                rows = cursor.fetchmany(_FETCH_SIZE)
                if not rows:
                    break
                for r in rows:
                    seg_idx = r[0]
                    threshold = r[1]

                    self._segment_idx[i] = seg_idx
                    self._threshold_m2[i] = threshold
                    self._area_km2[i] = r[2] if r[2] is not None else 0.0

                    if r[3] is not None:
                        self._elev_mean[i] = r[3]
                    if r[4] is not None:
                        self._slope_mean[i] = r[4]
                    if r[5] is not None:
                        self._strahler[i] = r[5]
                    if r[7] is not None:
                        self._elev_min[i] = r[7]
                    if r[8] is not None:
                        self._elev_max[i] = r[8]
                    if r[9] is not None:
                        self._perimeter_km[i] = r[9]
                    if r[10] is not None:
                        self._stream_length_km[i] = r[10]

                    # Histogram (JSONB → dict)
                    self._histograms[i] = r[11]

                    # Hydraulic length (flow path distance to outlet)
                    if r[12] is not None:
                        self._hydraulic_length_km[i] = r[12]

                    # max_flow_dist_m (COALESCE ensures 0 for NULL)
                    self._max_flow_dist_m[i] = r[13]

                    # Register in lookup
                    self._lookup[(threshold, seg_idx)] = i

                    # Downstream link → edge
                    ds_seg_idx = r[6]
                    if ds_seg_idx is not None:
                        ds_key = (threshold, ds_seg_idx)
                        # Defer edge — downstream node may not be seen yet
                        edge_from.append(i)
                        edge_to.append(ds_key)

                    i += 1
        finally:
            cursor.close()

        # Load is_real_stream and per-segment length from stream_network
        self._is_real_stream = np.zeros(n, dtype=np.bool_)
        self._segment_length_km = np.zeros(n, dtype=np.float64)

        sn_cursor = raw_conn.cursor(name="catchment_graph_stream_network")
        try:
            sn_cursor.itersize = _FETCH_SIZE
            sn_cursor.execute(
                "SELECT segment_idx, threshold_m2, "
                "COALESCE(is_real_stream, false) AS is_real, "
                "COALESCE(length_m, 0) / 1000.0 AS segment_length_km "
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
        except Exception as e:
            logger.warning(
                f"Failed to load is_real_stream from stream_network: {e}. "
                "Defaulting to all false / 0.0."
            )
            self._is_real_stream = np.zeros(n, dtype=np.bool_)
            self._segment_length_km = np.zeros(n, dtype=np.float64)
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
                self._perimeter_km,
                self._stream_length_km,
                self._hydraulic_length_km,
                self._strahler,
                self._max_flow_dist_m,
                self._is_real_stream,
                self._segment_length_km,
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
                "Kliknij w obszarze pokrytym siecią rzeczną."
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

    def verify_graph(self, db: Session | None = None) -> dict:
        """Verify graph integrity. Returns diagnostic dict."""
        if not self._loaded:
            raise RuntimeError("Catchment graph not loaded")

        thresholds = np.unique(self._threshold_m2)
        report = {"thresholds": {}, "total_nodes": self._n}

        for t in thresholds:
            t = int(t)
            mask = self._threshold_m2 == t
            indices = np.where(mask)[0]
            n_nodes = len(indices)

            # Count edges (nodes with at least one upstream neighbor)
            n_with_upstream = sum(
                1 for idx in indices if self._upstream_adj[idx].nnz > 0
            )
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

        return breadth_first_order(
            self._upstream_adj,
            start_idx,
            directed=True,
            return_predecessors=False,
        )

    def traverse_to_confluence(self, start_idx: int) -> np.ndarray:
        """
        BFS upstream, stop at confluence nodes (>1 upstream neighbor).

        Includes confluence nodes in the result but does not continue
        BFS past them. A confluence is any node with more than one
        upstream neighbor in the adjacency matrix.

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

        visited: set[int] = set()
        queue = deque([start_idx])
        visited.add(start_idx)
        result = [start_idx]

        while queue:
            current = queue.popleft()
            upstream = self._upstream_adj[current].indices
            for up_idx in upstream:
                if up_idx not in visited:
                    visited.add(up_idx)
                    result.append(up_idx)
                    # Only continue BFS through non-confluence nodes
                    if self._upstream_adj[up_idx].nnz <= 1:
                        queue.append(up_idx)

        return np.array(result, dtype=np.int32)

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
        return self._segment_idx[indices[mask]].tolist()

    def aggregate_stats(self, indices: np.ndarray, outlet_idx: int | None = None) -> dict:
        """
        Aggregate pre-computed stats across multiple catchment nodes.

        Parameters
        ----------
        indices : np.ndarray
            Internal indices from traverse_upstream()

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

        # Drainage density
        drainage_density = total_stream_km / total_area if total_area > 0 else None

        # Max Strahler from BDOT real streams only
        if self._is_real_stream is not None:
            real_mask = self._is_real_stream[indices]
            real_strahlers = self._strahler[indices][real_mask]
            max_strahler = int(np.max(real_strahlers)) if len(real_strahlers) > 0 else None
        else:
            strahlers = self._strahler[indices]
            max_strahler = int(np.max(strahlers)) if len(strahlers) > 0 else None

        # Stream frequency (all segments — kept for backward compatibility)
        n_segments = len(indices)
        stream_frequency_all = n_segments / total_area if total_area > 0 else None

        # BDOT-based drainage metrics (real streams only)
        if self._is_real_stream is not None and self._segment_length_km is not None:
            real_mask = self._is_real_stream[indices]
            real_lengths = self._segment_length_km[indices]
            bdot_stream_km = float(np.nansum(real_lengths[real_mask]))
            bdot_n_segments = int(np.sum(real_mask))
            bdot_drainage_density = bdot_stream_km / total_area if total_area > 0 else None
            bdot_stream_frequency = bdot_n_segments / total_area if total_area > 0 else None
        else:
            bdot_stream_km = 0.0
            bdot_n_segments = 0
            bdot_drainage_density = None
            bdot_stream_frequency = None

        # Hydraulic length: max_flow_dist_m stores the cumulative distance
        # from each subcatchment's farthest cell to the GLOBAL basin outlet
        # (from pyflwdir.stream_distance).  To get the flow path length
        # within the SELECTED watershed, subtract the outlet's distance:
        #   hydraulic_length = max(all_subcatchments) - outlet_flow_dist
        hydraulic_length_km = None
        if self._max_flow_dist_m is not None:
            flow_dists = self._max_flow_dist_m[indices]
            max_flow_dist = float(np.max(flow_dists)) if len(flow_dists) > 0 else 0.0
            if outlet_idx is not None and max_flow_dist > 0:
                outlet_flow_dist = float(self._max_flow_dist_m[outlet_idx])
                relative_dist = max_flow_dist - outlet_flow_dist
                if relative_dist > 0:
                    hydraulic_length_km = relative_dist / 1000.0
            elif max_flow_dist > 0:
                # No outlet_idx — fall back to raw value (legacy callers)
                hydraulic_length_km = max_flow_dist / 1000.0
        if hydraulic_length_km is None:
            hydraulic_lengths = self._hydraulic_length_km[indices]
            valid_hl = hydraulic_lengths[~np.isnan(hydraulic_lengths)]
            hydraulic_length_km = float(np.max(valid_hl)) if len(valid_hl) > 0 else None

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
                round(bdot_drainage_density, 4) if bdot_drainage_density is not None else None
            ),
            "max_strahler_order": max_strahler,
            "stream_frequency_per_km2": (
                round(bdot_stream_frequency, 4) if bdot_stream_frequency is not None else None
            ),
            "bdot_stream_length_km": round(bdot_stream_km, 4),
            "bdot_stream_count": bdot_n_segments,
            "hydraulic_length_km": (
                round(hydraulic_length_km, 4) if hydraulic_length_km is not None else None
            ),
        }

    def trace_main_channel(
        self,
        outlet_idx: int,
        upstream_indices: np.ndarray,
    ) -> dict:
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
            - main_channel_slope_m_per_m: float | None — relief/length
            - main_channel_nodes: list[int] — path indices
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

            # Select best upstream: max upstream area (= flow accumulation),
            # then prefer BDOT real stream, then Strahler, then stream length.
            # Upstream area is the primary criterion because it is a physical
            # property independent of the threshold — this harmonizes the main
            # channel path across threshold levels (1k, 10k, 100k m²).
            best = max(
                candidates,
                key=lambda n: (
                    self._area_km2[n],
                    int(self._is_real_stream[n]) if hasattr(self, '_is_real_stream') and self._is_real_stream is not None else 0,
                    self._strahler[n],
                    self._stream_length_km[n]
                    if not np.isnan(self._stream_length_km[n])
                    else 0.0,
                ),
            )
            path.append(best)
            current = best

        # Sum stream lengths along path
        path_arr = np.array(path, dtype=np.int32)
        lengths = self._stream_length_km[path_arr]
        main_length_km = float(np.nansum(lengths))

        # Slope: head elev_max - outlet elev_min
        head_idx = path[-1]  # furthest upstream node
        head_elev_max = self._elev_max[head_idx]
        outlet_elev_min = self._elev_min[outlet_idx]

        main_slope = None
        if (
            main_length_km > 0
            and not np.isnan(head_elev_max)
            and not np.isnan(outlet_elev_min)
        ):
            main_slope = round(
                (float(head_elev_max) - float(outlet_elev_min))
                / (main_length_km * 1000),
                6,
            )

        # Real channel length: contiguous BDOT-matched segments from outlet upstream.
        # Walk from outlet (path_arr[0]) upstream, sum segment lengths while
        # is_real_stream is True.  Stop at the FIRST non-real segment — everything
        # above is overland flow, even if later segments are flagged real (can
        # happen when the DEM flow-path runs between two parallel BDOT channels
        # whose buffers alternate coverage).
        real_length_km = None
        if self._is_real_stream is not None and self._segment_length_km is not None:
            contiguous_real_km = 0.0
            gap_count = 0
            MAX_GAP = 2  # allow up to 2 consecutive non-real segments
            pending_gap_km = 0.0
            started = False  # gap tolerance only after first real segment
            for node in path_arr:
                if self._is_real_stream[node]:
                    started = True
                    contiguous_real_km += pending_gap_km + self._segment_length_km[node]
                    pending_gap_km = 0.0
                    gap_count = 0
                else:
                    if not started:
                        break  # not-real before any real → no real channel
                    gap_count += 1
                    if gap_count > MAX_GAP:
                        break
                    pending_gap_km += self._segment_length_km[node]
            real_length_km = contiguous_real_km

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
    ) -> list[dict]:
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


# Global singleton
_catchment_graph: CatchmentGraph | None = None
_catchment_graph_lock = threading.Lock()


def get_catchment_graph() -> CatchmentGraph:
    """Get or create the global CatchmentGraph instance (thread-safe)."""
    global _catchment_graph
    if _catchment_graph is None:
        with _catchment_graph_lock:
            if _catchment_graph is None:
                _catchment_graph = CatchmentGraph()
    return _catchment_graph
