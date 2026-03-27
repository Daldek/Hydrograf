"""
Graph building for stormwater sewer networks.

Parses GIS line geometries into a directed graph with snapped endpoints,
direction cascade (attribute -> elevations -> tree topology), outlet
detection, node classification, and validation.

Memory usage: negligible for typical urban networks (hundreds of edges).
"""

import logging
from collections import deque

import geopandas as gpd
import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import connected_components

logger = logging.getLogger(__name__)


class SewerGraph:
    """Directed graph of a stormwater sewer network."""

    def __init__(self) -> None:
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.adj: sparse.csr_matrix = sparse.csr_matrix((0, 0), dtype=np.int8)
        self.warnings: list[str] = []
        self.n_components: int = 0
        self._node_lookup: dict[int, int] = {}  # node_id -> index

    @property
    def n_nodes(self) -> int:
        return len(self.nodes)

    @property
    def n_edges(self) -> int:
        return len(self.edges)

    def get_nodes_by_type(self, node_type: str) -> list[dict]:
        """Return all nodes with the given node_type."""
        return [n for n in self.nodes if n["node_type"] == node_type]

    def get_upstream_inlets(self, outlet_id: int) -> list[int]:
        """BFS upstream from outlet, return IDs of inlet nodes found."""
        idx = self._node_lookup.get(outlet_id)
        if idx is None:
            return []

        visited: set[int] = set()
        queue: deque[int] = deque([idx])
        visited.add(idx)
        inlet_ids: list[int] = []

        while queue:
            current = queue.popleft()
            node = self.nodes[current]
            if node["node_type"] == "inlet":
                inlet_ids.append(node["id"])

            # adj[downstream, upstream] = 1 -> row `current` has upstream neighbors
            upstream_indices = self.adj[current].indices
            for u_idx in upstream_indices:
                if u_idx not in visited:
                    visited.add(u_idx)
                    queue.append(u_idx)

        return inlet_ids


def _snap_endpoints(
    lines: gpd.GeoDataFrame,
    tolerance_m: float,
) -> tuple[list[tuple[float, float]], dict[int, tuple[int, int]]]:
    """
    Snap line endpoints within tolerance using greedy clustering.

    Parameters
    ----------
    lines : gpd.GeoDataFrame
        Line geometries.
    tolerance_m : float
        Maximum distance for snapping endpoints together.

    Returns
    -------
    unique_coords : list[tuple[float, float]]
        Unique snapped node coordinates (cluster centroids).
    line_node_map : dict[int, tuple[int, int]]
        Maps line index -> (start_node_idx, end_node_idx).
    """
    # Collect all endpoints: (line_idx, is_end, x, y)
    endpoints: list[tuple[int, int, float, float]] = []
    for i, geom in enumerate(lines.geometry):
        coords = list(geom.coords)
        sx, sy = coords[0][0], coords[0][1]
        ex, ey = coords[-1][0], coords[-1][1]
        endpoints.append((i, 0, sx, sy))  # start
        endpoints.append((i, 1, ex, ey))  # end

    n_pts = len(endpoints)
    cluster_id = [-1] * n_pts
    clusters: list[list[int]] = []  # cluster -> list of endpoint indices

    # Greedy clustering: assign each point to nearest existing cluster
    # or create new one
    tol_sq = tolerance_m * tolerance_m
    cluster_cx: list[float] = []
    cluster_cy: list[float] = []

    for pt_idx in range(n_pts):
        _, _, px, py = endpoints[pt_idx]

        best_cluster = -1
        best_dist_sq = tol_sq  # only consider clusters within tolerance

        for c_idx in range(len(clusters)):
            dx = px - cluster_cx[c_idx]
            dy = py - cluster_cy[c_idx]
            d_sq = dx * dx + dy * dy
            if d_sq < best_dist_sq:
                best_dist_sq = d_sq
                best_cluster = c_idx

        if best_cluster >= 0:
            cluster_id[pt_idx] = best_cluster
            clusters[best_cluster].append(pt_idx)
            # Update centroid
            n_members = len(clusters[best_cluster])
            cluster_cx[best_cluster] = (
                cluster_cx[best_cluster] * (n_members - 1) + px
            ) / n_members
            cluster_cy[best_cluster] = (
                cluster_cy[best_cluster] * (n_members - 1) + py
            ) / n_members
        else:
            new_idx = len(clusters)
            cluster_id[pt_idx] = new_idx
            clusters.append([pt_idx])
            cluster_cx.append(px)
            cluster_cy.append(py)

    # Build outputs
    unique_coords = list(zip(cluster_cx, cluster_cy))

    line_node_map: dict[int, tuple[int, int]] = {}
    # Group by line_idx: each line has exactly 2 endpoints (start=0, end=1)
    line_endpoints: dict[int, dict[int, int]] = {}
    for pt_idx in range(n_pts):
        line_idx, is_end, _, _ = endpoints[pt_idx]
        if line_idx not in line_endpoints:
            line_endpoints[line_idx] = {}
        line_endpoints[line_idx][is_end] = cluster_id[pt_idx]

    for line_idx, ep_map in line_endpoints.items():
        line_node_map[line_idx] = (ep_map[0], ep_map[1])

    return unique_coords, line_node_map


def _assign_directions_by_topology(
    n_nodes: int,
    undirected_edges: list[tuple[int, int, int]],
    node_degrees: np.ndarray,
    outlet_indices: list[int],
) -> list[tuple[int, int]]:
    """
    Direct edges by BFS from outlets upward.

    For each component, BFS starts at the outlet and traverses upward.
    Edge direction: from visited node (upstream) to the node that
    discovered it (downstream). This means edges point downstream
    (from_node -> to_node = upstream -> downstream).

    Parameters
    ----------
    n_nodes : int
        Total number of nodes.
    undirected_edges : list[tuple[int, int, int]]
        Each tuple: (edge_idx, node_a, node_b).
    node_degrees : np.ndarray
        Degree of each node in undirected graph.
    outlet_indices : list[int]
        Node indices identified as outlets.

    Returns
    -------
    directed_pairs : list[tuple[int, int]]
        List of (from_node, to_node) where from is upstream, to is downstream.
        Indexed by edge_idx position matching undirected_edges order.
    """
    # Build undirected adjacency lists
    adj_list: dict[int, list[tuple[int, int]]] = {i: [] for i in range(n_nodes)}
    for edge_idx, na, nb in undirected_edges:
        adj_list[na].append((nb, edge_idx))
        adj_list[nb].append((na, edge_idx))

    directed: dict[int, tuple[int, int]] = {}  # edge_idx -> (from, to)
    visited = set()

    for outlet_idx in outlet_indices:
        if outlet_idx in visited:
            continue
        queue: deque[int] = deque([outlet_idx])
        visited.add(outlet_idx)

        while queue:
            current = queue.popleft()
            for neighbor, edge_idx in adj_list[current]:
                if neighbor not in visited and edge_idx not in directed:
                    visited.add(neighbor)
                    # neighbor is upstream of current
                    directed[edge_idx] = (neighbor, current)
                    queue.append(neighbor)

    # Build result in original edge order
    result: list[tuple[int, int]] = []
    for edge_idx, na, nb in undirected_edges:
        if edge_idx in directed:
            result.append(directed[edge_idx])
        else:
            # Fallback: use original order (should not happen if all components have outlets)
            result.append((na, nb))

    return result


def build_sewer_graph(
    gdf: gpd.GeoDataFrame,
    snap_tolerance_m: float = 2.0,
    attr_mapping: dict | None = None,
    user_outlets: gpd.GeoDataFrame | None = None,
) -> SewerGraph:
    """
    Build a directed sewer graph from line geometries.

    Algorithm:
    1. Snap endpoints within tolerance
    2. Create nodes (one per unique snapped endpoint)
    3. Create undirected edges (one per input line)
    4. Detect connected components
    5. Direction cascade: attribute -> elevations -> tree topology
    6. Build directed adjacency (CSR matrix)
    7. Classify node types (outlet/inlet/junction)
    8. Assign root_outlet_id via BFS
    9. Validate

    Parameters
    ----------
    gdf : gpd.GeoDataFrame
        Line geometries representing sewer pipes.
    snap_tolerance_m : float
        Maximum distance to snap endpoints together (default: 2.0m).
    attr_mapping : dict | None
        Column name mapping: {flow_direction, invert_start, invert_end, ...}.
    user_outlets : gpd.GeoDataFrame | None
        User-specified outlet points. If provided, nearest nodes are used
        as outlets instead of auto-detection.

    Returns
    -------
    SewerGraph
        Directed graph with nodes, edges, adjacency, and warnings.
    """
    if attr_mapping is None:
        attr_mapping = {}

    graph = SewerGraph()

    if len(gdf) == 0:
        graph.warnings.append("Empty input GeoDataFrame")
        return graph

    # --- Step 1: Snap endpoints ---
    unique_coords, line_node_map = _snap_endpoints(gdf, snap_tolerance_m)
    n_nodes = len(unique_coords)

    # --- Step 2: Create nodes ---
    for node_idx, (x, y) in enumerate(unique_coords):
        graph.nodes.append({
            "id": node_idx,
            "x": x,
            "y": y,
            "node_type": "unknown",  # classified later
            "component_id": -1,
            "depth_m": None,
            "invert_elev_m": None,
            "dem_elev_m": None,
            "burn_elev_m": None,
            "fa_value": None,
            "total_upstream_fa": None,
            "root_outlet_id": None,
            "source_type": None,
        })
    graph._node_lookup = {i: i for i in range(n_nodes)}

    # --- Step 3: Create undirected edges ---
    undirected_edges: list[tuple[int, int, int]] = []  # (edge_idx, node_a, node_b)
    for line_idx in range(len(gdf)):
        start_node, end_node = line_node_map[line_idx]
        geom = gdf.geometry.iloc[line_idx]
        length_m = geom.length

        edge = {
            "id": line_idx,
            "from_node": start_node,
            "to_node": end_node,
            "geom": geom,
            "length_m": length_m,
        }
        graph.edges.append(edge)
        undirected_edges.append((line_idx, start_node, end_node))

    # --- Step 4: Connected components ---
    if n_nodes > 0:
        row_indices = []
        col_indices = []
        for _, na, nb in undirected_edges:
            row_indices.extend([na, nb])
            col_indices.extend([nb, na])

        if row_indices:
            undirected_adj = sparse.csr_matrix(
                (
                    np.ones(len(row_indices), dtype=np.int8),
                    (np.array(row_indices), np.array(col_indices)),
                ),
                shape=(n_nodes, n_nodes),
                dtype=np.int8,
            )
        else:
            undirected_adj = sparse.csr_matrix((n_nodes, n_nodes), dtype=np.int8)

        n_comp, labels = connected_components(
            undirected_adj, directed=False, return_labels=True
        )
        graph.n_components = n_comp

        for node_idx in range(n_nodes):
            graph.nodes[node_idx]["component_id"] = int(labels[node_idx])

        if n_comp > 1:
            graph.warnings.append(
                f"Network has {n_comp} disconnected components"
            )
    else:
        graph.n_components = 0

    # --- Step 5: Direction cascade ---
    # Compute node degrees for topology fallback
    node_degrees = np.zeros(n_nodes, dtype=np.int32)
    for _, na, nb in undirected_edges:
        node_degrees[na] += 1
        node_degrees[nb] += 1

    # Track which edges have been directed
    directed_pairs: dict[int, tuple[int, int]] = {}  # edge_idx -> (from, to)

    # 5a: ATTRIBUTE direction
    flow_dir_col = attr_mapping.get("flow_direction")
    if flow_dir_col and flow_dir_col in gdf.columns:
        for edge_idx, na, nb in undirected_edges:
            val = gdf.iloc[edge_idx][flow_dir_col]
            if val is not None and val != "":
                # Assume value indicates direction: positive/forward = start->end
                try:
                    val_num = float(val)
                    if val_num > 0:
                        directed_pairs[edge_idx] = (na, nb)
                    elif val_num < 0:
                        directed_pairs[edge_idx] = (nb, na)
                except (ValueError, TypeError):
                    pass

    # 5b: ELEVATION direction (for edges not yet directed)
    invert_start_col = attr_mapping.get("invert_start")
    invert_end_col = attr_mapping.get("invert_end")
    if (
        invert_start_col
        and invert_end_col
        and invert_start_col in gdf.columns
        and invert_end_col in gdf.columns
    ):
        for edge_idx, na, nb in undirected_edges:
            if edge_idx in directed_pairs:
                continue
            row = gdf.iloc[edge_idx]
            start_elev = row[invert_start_col]
            end_elev = row[invert_end_col]
            if (
                start_elev is not None
                and end_elev is not None
                and not (isinstance(start_elev, float) and np.isnan(start_elev))
                and not (isinstance(end_elev, float) and np.isnan(end_elev))
            ):
                start_elev = float(start_elev)
                end_elev = float(end_elev)
                if start_elev > end_elev:
                    # Water flows from high to low: start -> end
                    directed_pairs[edge_idx] = (na, nb)
                elif end_elev > start_elev:
                    directed_pairs[edge_idx] = (nb, na)
                # If equal, leave undirected for topology step

    # 5c: TREE TOPOLOGY for remaining undirected edges
    remaining = [
        (edge_idx, na, nb)
        for edge_idx, na, nb in undirected_edges
        if edge_idx not in directed_pairs
    ]

    if remaining:
        # Detect outlets: user-specified or auto-detect
        outlet_indices = _detect_outlets(
            graph.nodes, node_degrees, labels if n_nodes > 0 else np.array([]),
            user_outlets, n_nodes,
        )

        topo_pairs = _assign_directions_by_topology(
            n_nodes, remaining, node_degrees, outlet_indices,
        )
        for (edge_idx, _, _), (from_node, to_node) in zip(remaining, topo_pairs):
            directed_pairs[edge_idx] = (from_node, to_node)

    # Apply directions to edges
    for edge_idx in range(len(graph.edges)):
        if edge_idx in directed_pairs:
            from_node, to_node = directed_pairs[edge_idx]
            graph.edges[edge_idx]["from_node"] = from_node
            graph.edges[edge_idx]["to_node"] = to_node

    # --- Step 6: Build directed adjacency (CSR) ---
    # Convention: adj[downstream, upstream] = 1
    if n_nodes > 0 and graph.edges:
        from_arr = np.array(
            [e["from_node"] for e in graph.edges], dtype=np.int32
        )
        to_arr = np.array(
            [e["to_node"] for e in graph.edges], dtype=np.int32
        )
        graph.adj = sparse.csr_matrix(
            (
                np.ones(len(graph.edges), dtype=np.int8),
                (to_arr, from_arr),
            ),
            shape=(n_nodes, n_nodes),
            dtype=np.int8,
        )
    else:
        graph.adj = sparse.csr_matrix(
            (max(n_nodes, 1), max(n_nodes, 1)), dtype=np.int8
        )

    # --- Step 7: Classify node types ---
    for node_idx in range(n_nodes):
        has_incoming = graph.adj[:, node_idx].nnz > 0  # something drains TO here
        has_outgoing = graph.adj[node_idx, :].nnz > 0  # this drains TO something else (upstream)

        # In our convention adj[downstream, upstream] = 1:
        # - adj[node_idx, :].nnz > 0 means node_idx has upstream neighbors
        # - adj[:, node_idx].nnz > 0 means node_idx IS upstream of something (has downstream)

        # So:
        # has_downstream: this node appears as upstream in some edge -> adj[:, node_idx].nnz > 0
        # has_upstream: this node has upstream neighbors -> adj[node_idx, :].nnz > 0
        has_upstream = graph.adj[node_idx, :].nnz > 0
        has_downstream = graph.adj[:, node_idx].nnz > 0

        if has_upstream and has_downstream:
            graph.nodes[node_idx]["node_type"] = "junction"
        elif has_upstream and not has_downstream:
            # Has upstream but nothing downstream -> this is an outlet (terminal node)
            graph.nodes[node_idx]["node_type"] = "outlet"
        elif not has_upstream and has_downstream:
            # No upstream but has downstream -> this is an inlet (source node)
            graph.nodes[node_idx]["node_type"] = "inlet"
        else:
            # Isolated node (no connections at all)
            graph.nodes[node_idx]["node_type"] = "isolated"

    # --- Step 8: Assign root_outlet_id ---
    outlets = graph.get_nodes_by_type("outlet")
    for outlet in outlets:
        outlet_idx = graph._node_lookup[outlet["id"]]
        # BFS upstream from outlet
        visited: set[int] = set()
        queue: deque[int] = deque([outlet_idx])
        visited.add(outlet_idx)

        while queue:
            current = queue.popleft()
            graph.nodes[current]["root_outlet_id"] = outlet["id"]
            upstream_indices = graph.adj[current].indices
            for u_idx in upstream_indices:
                if u_idx not in visited:
                    visited.add(u_idx)
                    queue.append(u_idx)

    # --- Step 9: Validate ---
    if n_nodes > 0:
        # Check for components without outlets
        components_with_outlets: set[int] = set()
        for outlet in outlets:
            components_with_outlets.add(outlet["component_id"])

        for comp_id in range(graph.n_components):
            if comp_id not in components_with_outlets:
                graph.warnings.append(
                    f"Component {comp_id} has no outlet node"
                )

    n_inlets = len(graph.get_nodes_by_type("inlet"))
    n_outlets = len(outlets)
    n_junctions = len(graph.get_nodes_by_type("junction"))
    logger.info(
        f"Sewer graph built: {n_nodes} nodes ({n_inlets} inlets, "
        f"{n_junctions} junctions, {n_outlets} outlets), "
        f"{len(graph.edges)} edges, {graph.n_components} components"
    )
    if graph.warnings:
        for w in graph.warnings:
            logger.warning(f"SewerGraph: {w}")

    return graph


def _detect_outlets(
    nodes: list[dict],
    node_degrees: np.ndarray,
    component_labels: np.ndarray,
    user_outlets: gpd.GeoDataFrame | None,
    n_nodes: int,
) -> list[int]:
    """
    Detect outlet nodes for tree topology direction assignment.

    If user_outlets is provided, find nearest node to each point.
    Otherwise, for each component pick the degree-1 node with
    the lowest y-coordinate.
    """
    if user_outlets is not None and len(user_outlets) > 0:
        outlet_indices = []
        for _, pt in user_outlets.iterrows():
            px, py = pt.geometry.x, pt.geometry.y
            best_idx = -1
            best_dist_sq = float("inf")
            for node_idx, node in enumerate(nodes):
                dx = node["x"] - px
                dy = node["y"] - py
                d_sq = dx * dx + dy * dy
                if d_sq < best_dist_sq:
                    best_dist_sq = d_sq
                    best_idx = node_idx
            if best_idx >= 0:
                outlet_indices.append(best_idx)
        return outlet_indices

    # Auto-detect: for each component, degree-1 node with lowest y
    outlets: list[int] = []
    if n_nodes == 0:
        return outlets

    n_components = int(component_labels.max()) + 1 if len(component_labels) > 0 else 0

    for comp_id in range(n_components):
        comp_nodes = [
            i for i in range(n_nodes) if component_labels[i] == comp_id
        ]
        if not comp_nodes:
            continue

        # Prefer degree-1 nodes (leaf nodes)
        degree1_nodes = [i for i in comp_nodes if node_degrees[i] == 1]
        candidates = degree1_nodes if degree1_nodes else comp_nodes

        # Pick the one with lowest y-coordinate (most downstream in typical maps)
        best = min(candidates, key=lambda i: nodes[i]["y"])
        outlets.append(best)

    return outlets
