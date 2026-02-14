"""
In-memory graph of sub-catchments for fast upstream traversal.

Loads ~87k sub-catchment nodes (vs 19.7M cells in flow_graph) from
PostGIS into numpy arrays and a scipy sparse matrix at API startup.
Enables BFS traversal + stat aggregation in ~5-50ms.

Memory usage: ~8 MB (vs ~1 GB for flow graph).
"""

import logging
import time

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
        self._strahler: np.ndarray | None = None

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
        self._strahler = np.zeros(n, dtype=np.int8)
        self._histograms = [None] * n

        # Edge lists for sparse matrix
        edge_from = []  # upstream node
        edge_to = []  # downstream node

        # Stream via server-side cursor
        raw_conn = db.connection().connection
        cursor = raw_conn.cursor(name="catchment_graph_load")
        cursor.itersize = _FETCH_SIZE
        cursor.execute(
            "SELECT segment_idx, threshold_m2, area_km2, "
            "mean_elevation_m, mean_slope_percent, strahler_order, "
            "downstream_segment_idx, elevation_min_m, elevation_max_m, "
            "perimeter_km, stream_length_km, elev_histogram "
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

        cursor.close()

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
                self._strahler,
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

        self._loaded = True

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
        queue = [start_idx]
        visited.add(start_idx)
        result = [start_idx]

        while queue:
            current = queue.pop(0)
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

    def aggregate_stats(self, indices: np.ndarray) -> dict:
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

        # Max Strahler
        strahlers = self._strahler[indices]
        max_strahler = int(np.max(strahlers)) if len(strahlers) > 0 else None

        # Stream frequency
        n_segments = len(indices)
        stream_frequency = n_segments / total_area if total_area > 0 else None

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
                round(drainage_density, 4) if drainage_density is not None else None
            ),
            "max_strahler_order": max_strahler,
            "stream_frequency_per_km2": (
                round(stream_frequency, 4) if stream_frequency is not None else None
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


def get_catchment_graph() -> CatchmentGraph:
    """Get or create the global CatchmentGraph instance."""
    global _catchment_graph
    if _catchment_graph is None:
        _catchment_graph = CatchmentGraph()
    return _catchment_graph
