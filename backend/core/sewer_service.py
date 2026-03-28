"""
Graph building for stormwater sewer networks.

Builds a directed SewerGraph from pre-validated ParsedTopology.
No snapping, no direction heuristics — topology is explicit.

Memory usage: negligible for typical urban networks (hundreds of edges).
"""

from __future__ import annotations

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


def build_sewer_graph(topology) -> SewerGraph:
    """Build directed sewer graph from pre-validated ParsedTopology.

    Topology is explicit — nodes have roles, edges have from/to.
    No snapping, no direction heuristics, no auto-detect.
    """
    graph = SewerGraph()

    # 1. Create nodes with sequential indices
    node_id_to_idx: dict[str, int] = {}
    for i, node_data in enumerate(topology.nodes):
        node = {
            "id": node_data["id"],
            "idx": i,
            "node_type": node_data["role"],
            "x": node_data["x"],
            "y": node_data["y"],
        }
        # Copy optional attributes
        for attr in ("invert_elev", "depth", "diameter",
                      "rim_elevation", "max_depth", "ponded_area",
                      "outfall_type"):
            if attr in node_data:
                node[attr] = node_data[attr]

        graph.nodes.append(node)
        node_id_to_idx[node_data["id"]] = i

    # Populate _node_lookup so get_upstream_inlets() works
    graph._node_lookup = {node["id"]: node["idx"] for node in graph.nodes}

    # 2. Create edges
    n = len(graph.nodes)
    rows, cols = [], []

    for edge_data in topology.edges:
        from_idx = node_id_to_idx[edge_data["from_id"]]
        to_idx = node_id_to_idx[edge_data["to_id"]]

        edge = {
            "from_idx": from_idx,
            "to_idx": to_idx,
            "from_id": edge_data["from_id"],
            "to_id": edge_data["to_id"],
            "geometry": edge_data.get("geometry"),
            "source": edge_data.get("source", "user_data"),
            "length_m": (
                edge_data["geometry"].length if edge_data.get("geometry") else 0.0
            ),
        }
        # Copy pipe attributes
        for attr in ("diameter", "width", "height", "cross_section",
                      "manning", "material", "invert_elev"):
            if attr in edge_data:
                edge[attr] = edge_data[attr]

        graph.edges.append(edge)

        # adj[downstream, upstream] = 1 (convention from original code)
        rows.append(to_idx)
        cols.append(from_idx)

    # 3. Build adjacency matrix
    if n > 0:
        data = np.ones(len(rows), dtype=np.int8)
        graph.adj = sparse.csr_matrix(
            (data, (rows, cols)), shape=(n, n),
        )
    else:
        graph.adj = sparse.csr_matrix((0, 0), dtype=np.int8)

    # 4. Connected components
    if n > 0:
        n_comp, labels = connected_components(graph.adj, directed=False)
        graph.n_components = n_comp
        for i, node in enumerate(graph.nodes):
            node["component_id"] = int(labels[i])
    else:
        graph.n_components = 0

    # 5. Assign root_outlet_id via BFS from each outlet
    outlets = [nd for nd in graph.nodes if nd["node_type"] == "outlet"]
    for outlet in outlets:
        outlet["root_outlet_id"] = None
        visited = {outlet["idx"]}
        queue = deque([outlet["idx"]])
        while queue:
            cur = queue.popleft()
            upstream = graph.adj[cur, :].nonzero()[1]
            for up_idx in upstream:
                if up_idx not in visited:
                    visited.add(up_idx)
                    graph.nodes[up_idx]["root_outlet_id"] = outlet["id"]
                    queue.append(up_idx)

    logger.info(
        "Built sewer graph: %d nodes, %d edges, %d components",
        graph.n_nodes, graph.n_edges, graph.n_components,
    )

    return graph


# --- Raster operations ---

# D8 direction offsets
_D8_DR = {1: 0, 2: 1, 4: 1, 8: 1, 16: 0, 32: -1, 64: -1, 128: -1}
_D8_DC = {1: 1, 2: 1, 4: 0, 8: -1, 16: -1, 32: -1, 64: 0, 128: 1}


def burn_inlets(
    dem: np.ndarray,
    inlets: list[dict],
    default_depth_m: float = 0.5,
) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Lower DEM at inlet locations. Returns modified DEM and drain_points list.

    Each inlet dict must have: id, row, col. Optional: depth_m, invert_elev_m.
    Deduplicates: if multiple inlets map to same cell, uses max depth.
    Validates: skips inlets where computed depth <= 0.
    """
    drain_points: list[tuple[int, int]] = []
    cell_depths: dict[tuple[int, int], float] = {}
    nrows, ncols = dem.shape

    for inlet in inlets:
        row, col = inlet["row"], inlet["col"]
        if row < 0 or row >= nrows or col < 0 or col >= ncols:
            logger.warning(f"Inlet {inlet['id']} at ({row},{col}) outside DEM — skipping")
            continue

        dem_elev = float(dem[row, col])
        inlet["dem_elev_m"] = dem_elev

        # Determine depth (cascade: invert_elev → depth_m → default)
        if inlet.get("invert_elev_m") is not None:
            depth = dem_elev - inlet["invert_elev_m"]
        elif inlet.get("depth_m") is not None:
            depth = inlet["depth_m"]
        else:
            depth = default_depth_m

        if depth <= 0:
            logger.warning(
                f"Inlet {inlet['id']}: depth={depth:.2f}m <= 0 — skipping"
            )
            continue

        key = (row, col)
        if key in cell_depths:
            cell_depths[key] = max(cell_depths[key], depth)
        else:
            cell_depths[key] = depth

        inlet["burn_elev_m"] = dem_elev - depth

    for (row, col), depth in cell_depths.items():
        dem[row, col] -= depth
        drain_points.append((row, col))

    # Fix burn_elev_m for deduplicated cells (max depth may differ from per-inlet depth)
    for inlet in inlets:
        key = (inlet.get("row", -1), inlet.get("col", -1))
        if key in cell_depths:
            inlet["burn_elev_m"] = inlet.get("dem_elev_m", 0) - cell_depths[key]

    logger.info(f"Inlet burning: {len(cell_depths)} cells, {len(inlets)} inlets")
    return dem, drain_points


def reconstruct_inlet_fa(
    fa: np.ndarray,
    fdir: np.ndarray,
    inlets: list[dict],
) -> None:
    """Reconstruct FA for inlet cells (set to nodata by drain_points).

    For each inlet, sum FA from 8 neighbors whose D8 fdir points to inlet cell.
    Sets inlet["fa_value"] in-place.
    """
    nrows, ncols = fa.shape

    for inlet in inlets:
        row, col = inlet["row"], inlet["col"]
        reconstructed = 0

        for d8_code in _D8_DR:
            # Neighbor that flows TO (row, col) is at (row - dr, col - dc)
            # where (dr, dc) is the offset for d8_code
            nr = row - _D8_DR[d8_code]
            nc = col - _D8_DC[d8_code]
            if 0 <= nr < nrows and 0 <= nc < ncols:
                if int(fdir[nr, nc]) == d8_code:
                    reconstructed += int(fa[nr, nc])

        inlet["fa_value"] = reconstructed


def route_fa_through_sewer(graph) -> None:
    """Route FA through sewer graph: sum inlet FA per outlet.

    For each outlet, BFS upstream to find all inlets, sum their fa_value.
    Sets outlet["total_upstream_fa"] in-place.
    """
    for outlet in graph.get_nodes_by_type("outlet"):
        inlet_ids = graph.get_upstream_inlets(outlet["id"])
        total = 0
        for iid in inlet_ids:
            idx = graph._node_lookup[iid]
            node = graph.nodes[idx]
            fa_val = node.get("fa_value", 0) or 0
            total += fa_val
        outlet["total_upstream_fa"] = total
        logger.info(
            f"Outlet {outlet['id']}: {len(inlet_ids)} inlets, total_fa={total}"
        )


def propagate_fa_downstream(
    fa: np.ndarray,
    fdir: np.ndarray,
    outlets: list[dict],
) -> None:
    """Propagate FA surplus from sewer outlets downstream along fdir.

    Sorts outlets by total_upstream_fa ascending (smallest first).
    For each outlet: injects surplus at cell, walks downstream adding surplus.
    Anti-cycle protection via visited set.
    """
    nrows, ncols = fa.shape
    sorted_outlets = sorted(outlets, key=lambda o: o.get("total_upstream_fa", 0))

    for outlet in sorted_outlets:
        surplus = outlet.get("total_upstream_fa", 0)
        if surplus <= 0:
            continue

        row, col = outlet["row"], outlet["col"]
        fa[row, col] += surplus

        # Walk downstream
        visited = set()
        current_r, current_c = row, col
        while True:
            if (current_r, current_c) in visited:
                break
            visited.add((current_r, current_c))

            d8 = int(fdir[current_r, current_c])
            if d8 <= 0 or d8 not in _D8_DR:
                break

            nr = current_r + _D8_DR[d8]
            nc = current_c + _D8_DC[d8]

            if nr < 0 or nr >= nrows or nc < 0 or nc >= ncols:
                break

            fa[nr, nc] += surplus
            current_r, current_c = nr, nc

    logger.info(
        f"FA propagation: {len(sorted_outlets)} outlets, "
        f"max surplus={max((o.get('total_upstream_fa', 0) for o in sorted_outlets), default=0)}"
    )


def insert_sewer_data(
    graph,
    db_session,
    source_file: str = "unknown",
) -> int:
    """Insert sewer graph into PostGIS (sewer_nodes + sewer_network).

    Truncates existing data first, then inserts all nodes and edges.
    Returns total number of records inserted.
    """
    from sqlalchemy import text

    # Truncate existing data (order matters — FK constraints)
    # RESTART IDENTITY resets sequences so no manual setval needed.
    # No commit here — everything in a single transaction.
    db_session.execute(text("TRUNCATE TABLE sewer_network RESTART IDENTITY CASCADE"))
    db_session.execute(text("TRUNCATE TABLE sewer_nodes RESTART IDENTITY CASCADE"))

    # Insert nodes (two-pass: first without root_outlet_id to avoid FK order issues,
    # then UPDATE to set self-referencing root_outlet_id)
    for node in graph.nodes:
        db_session.execute(
            text("""
                INSERT INTO sewer_nodes (
                    id, geom, node_type, component_id, depth_m, invert_elev_m,
                    dem_elev_m, burn_elev_m, fa_value, total_upstream_fa,
                    root_outlet_id, source_type
                ) VALUES (
                    :id, ST_SetSRID(ST_MakePoint(:x, :y), 2180),
                    :node_type, :component_id, :depth_m, :invert_elev_m,
                    :dem_elev_m, :burn_elev_m, :fa_value, :total_upstream_fa,
                    NULL, :source_type
                )
            """),
            {
                "id": node["id"],
                "x": node["x"],
                "y": node["y"],
                "node_type": node["node_type"],
                "component_id": node.get("component_id"),
                "depth_m": node.get("depth_m"),
                "invert_elev_m": node.get("invert_elev_m"),
                "dem_elev_m": node.get("dem_elev_m"),
                "burn_elev_m": node.get("burn_elev_m"),
                "fa_value": node.get("fa_value"),
                "total_upstream_fa": node.get("total_upstream_fa"),
                "source_type": node.get("source_type") or "topology_generated",
            },
        )

    # Second pass: set root_outlet_id now that all nodes exist
    for node in graph.nodes:
        root_outlet_id = node.get("root_outlet_id")
        if root_outlet_id is not None:
            db_session.execute(
                text(
                    "UPDATE sewer_nodes SET root_outlet_id = :root_outlet_id "
                    "WHERE id = :id"
                ),
                {"id": node["id"], "root_outlet_id": root_outlet_id},
            )

    # Insert edges
    for edge in graph.edges:
        geom = edge.get("geometry")
        wkt = geom.wkt if geom is not None else None

        # Compute slope from endpoint elevations if available
        from_node = graph.nodes[edge["from_idx"]]
        to_node = graph.nodes[edge["to_idx"]]
        invert_start = from_node.get("invert_elev")
        invert_end = to_node.get("invert_elev")
        slope_pct = None
        if (
            invert_start is not None
            and invert_end is not None
            and edge["length_m"] > 0
        ):
            slope_pct = abs(invert_start - invert_end) / edge["length_m"] * 100

        db_session.execute(
            text("""
                INSERT INTO sewer_network (
                    geom, node_from_id, node_to_id, length_m, source,
                    diameter_mm, material, manning_n,
                    cross_section_shape, width_mm, height_mm,
                    invert_elev_start_m, invert_elev_end_m, slope_percent
                ) VALUES (
                    ST_SetSRID(ST_GeomFromText(:wkt), 2180),
                    :from_node, :to_node, :length_m, :source,
                    :diameter_mm, :material, :manning_n,
                    :cross_section_shape, :width_mm, :height_mm,
                    :invert_elev_start_m, :invert_elev_end_m, :slope_percent
                )
            """),
            {
                "wkt": wkt,
                "from_node": edge["from_id"],
                "to_node": edge["to_id"],
                "length_m": edge["length_m"],
                "source": source_file,
                "diameter_mm": edge.get("diameter"),
                "material": edge.get("material"),
                "manning_n": edge.get("manning"),
                "cross_section_shape": edge.get("cross_section"),
                "width_mm": edge.get("width"),
                "height_mm": edge.get("height"),
                "invert_elev_start_m": invert_start,
                "invert_elev_end_m": invert_end,
                "slope_percent": slope_pct,
            },
        )

    # Mark stream segments near sewer outlets as augmented (single batch query)
    db_session.execute(text("""
        UPDATE stream_network sn
        SET is_sewer_augmented = TRUE
        FROM sewer_nodes so
        WHERE so.node_type = 'outlet'
          AND ST_DWithin(sn.geom, so.geom, 50.0)
    """))

    db_session.commit()
    total = len(graph.nodes) + len(graph.edges)
    logger.info(f"Inserted sewer data: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    return total
