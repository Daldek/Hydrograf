"""Sewer topology parser and validator.

Parses user-provided sewer data (Format A: points with downstream_id,
Format B: points + lines) into a unified ParsedTopology structure.
Validates topology consistency with structured error reporting.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString

logger = logging.getLogger(__name__)

VALID_ROLES = {"inlet", "outlet", "junction", "storage"}


@dataclass
class ParsedTopology:
    """Unified result of parsing both input formats."""

    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_format: str = "points_only"


class TopologyValidationError(Exception):
    """Raised when topology data fails validation."""

    def __init__(self, errors: list[dict]) -> None:
        self.errors = errors
        messages = [e["message"] for e in errors]
        super().__init__(
            f"Topology validation failed ({len(errors)} errors):\n"
            + "\n".join(f"  - {m}" for m in messages)
        )


def _invert_role_mapping(role_mapping: dict) -> dict:
    """Invert {canonical: user_value} -> {user_value: canonical}."""
    return {v: k for k, v in role_mapping.items()}


def _parse_nodes(
    points_gdf: gpd.GeoDataFrame,
    field_mapping: dict,
    role_lookup: dict,
) -> list[dict]:
    """Extract nodes from points GeoDataFrame."""
    id_col = field_mapping["node_id"]
    role_col = field_mapping["node_role"]

    nodes = []
    for _, row in points_gdf.iterrows():
        geom = row.geometry
        raw_role = str(row[role_col]).strip()
        canonical_role = role_lookup.get(raw_role, raw_role)

        node = {
            "id": str(row[id_col]),
            "role": canonical_role,
            "x": geom.x,
            "y": geom.y,
        }

        # Core attributes
        for attr in ("invert_elev", "depth", "diameter"):
            col = field_mapping.get(attr)
            if col and col in points_gdf.columns:
                val = row[col]
                node[attr] = None if (val is None or val != val) else val

        # Extended attributes
        for attr in ("rim_elevation", "max_depth", "ponded_area",
                      "outfall_type", "manning", "material",
                      "cross_section", "width", "height"):
            col = field_mapping.get(attr)
            if col and col in points_gdf.columns:
                val = row[col]
                node[attr] = None if (val is None or val != val) else val

        nodes.append(node)

    return nodes


def _generate_edges_from_downstream(
    nodes: list[dict],
    points_gdf: gpd.GeoDataFrame,
    field_mapping: dict,
) -> list[dict]:
    """Format A: generate LineString edges from downstream_id column."""
    ds_col = field_mapping["downstream_id"]
    id_col = field_mapping["node_id"]

    node_by_id = {n["id"]: n for n in nodes}
    edges = []

    for _, row in points_gdf.iterrows():
        from_id = str(row[id_col])
        ds_val = row.get(ds_col)
        if ds_val is None or (isinstance(ds_val, float) and ds_val != ds_val):
            continue  # outlet — no downstream
        to_id = str(ds_val)

        from_node = node_by_id[from_id]
        to_node = node_by_id.get(to_id)
        if to_node is None:
            # Unknown target — record edge stub; validation will catch it
            geom = LineString([(from_node["x"], from_node["y"]),
                               (from_node["x"], from_node["y"])])
        else:
            geom = LineString([(from_node["x"], from_node["y"]),
                               (to_node["x"], to_node["y"])])

        edges.append({
            "from_id": from_id,
            "to_id": to_id,
            "geometry": geom,
            "source": "auto_generated",
        })

    return edges


def _parse_edges_from_lines(
    nodes: list[dict],
    lines_gdf: gpd.GeoDataFrame,
    field_mapping: dict,
) -> list[dict]:
    """Format B: parse edges from lines GeoDataFrame with from_node/to_node."""
    from_col = field_mapping["edge_from"]
    to_col = field_mapping["edge_to"]

    edges = []
    for _, row in lines_gdf.iterrows():
        edge = {
            "from_id": str(row[from_col]),
            "to_id": str(row[to_col]),
            "geometry": row.geometry,
            "source": "user_data",
        }

        # Pipe attributes from line layer
        for attr in ("diameter", "width", "height", "cross_section",
                      "manning", "material", "invert_elev"):
            col = field_mapping.get(attr)
            if col and col in lines_gdf.columns:
                val = row[col]
                edge[attr] = None if (val is None or val != val) else val

        edges.append(edge)

    return edges


def _validate_topology(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Validate topology consistency. Returns list of error dicts (empty=OK)."""
    errors: list[dict] = []

    # 1. Duplicate IDs
    seen_ids: dict[str, int] = defaultdict(int)
    for node in nodes:
        seen_ids[node["id"]] += 1
    for nid, count in seen_ids.items():
        if count > 1:
            errors.append({
                "type": "duplicate_id",
                "node_id": nid,
                "message": f"Node id={nid} appears {count} times",
            })
    if errors:
        return errors  # can't continue with duplicate IDs

    node_ids = {n["id"] for n in nodes}
    node_by_id = {n["id"]: n for n in nodes}

    # 2. Invalid roles
    for node in nodes:
        if node["role"] not in VALID_ROLES:
            errors.append({
                "type": "invalid_role",
                "node_id": node["id"],
                "message": (
                    f"Node id={node['id']}: role '{node['role']}' "
                    f"not in {VALID_ROLES}"
                ),
            })

    # 3. Direction mismatch: inlet should not be to_node, outlet should not be from_node
    node_role_by_id = {n["id"]: n["role"] for n in nodes}
    for edge in edges:
        to_role = node_role_by_id.get(edge["to_id"])
        from_role = node_role_by_id.get(edge["from_id"])
        if to_role == "inlet":
            errors.append({
                "type": "direction_mismatch",
                "node_id": edge["to_id"],
                "message": (
                    f"Edge {edge['from_id']}→{edge['to_id']}: "
                    f"node {edge['to_id']} is inlet (should not be downstream target)"
                ),
            })
        if from_role == "outlet":
            errors.append({
                "type": "direction_mismatch",
                "node_id": edge["from_id"],
                "message": (
                    f"Edge {edge['from_id']}→{edge['to_id']}: "
                    f"node {edge['from_id']} is outlet (should not be upstream source)"
                ),
            })

    # 4. Downstream map + outlet/missing_downstream checks
    downstream_map: dict[str, str] = {}
    for edge in edges:
        downstream_map[edge["from_id"]] = edge["to_id"]

    for node in nodes:
        nid = node["id"]
        has_downstream = nid in downstream_map

        if node["role"] == "outlet" and has_downstream:
            errors.append({
                "type": "outlet_has_downstream",
                "node_id": nid,
                "message": (
                    f"Outlet id={nid} has downstream_id="
                    f"{downstream_map[nid]} — outlets must be terminal"
                ),
            })

        if node["role"] != "outlet" and not has_downstream:
            errors.append({
                "type": "missing_downstream",
                "node_id": nid,
                "message": f"{node['role'].capitalize()} id={nid} has no downstream_id",
            })

    # 5. Edge targets exist (orphan edges + missing_target)
    has_broken_refs = False
    for edge in edges:
        if edge["from_id"] not in node_ids:
            errors.append({
                "type": "orphan_edge",
                "node_id": edge["from_id"],
                "message": f"Edge from_node={edge['from_id']}: no matching point",
            })
            has_broken_refs = True
        if edge["to_id"] not in node_ids:
            errors.append({
                "type": "orphan_edge",
                "node_id": edge["to_id"],
                "message": f"Edge to_node={edge['to_id']}: no matching point",
            })
            errors.append({
                "type": "missing_target",
                "node_id": edge["from_id"],
                "message": (
                    f"Node id={edge['from_id']}: downstream_id="
                    f"{edge['to_id']} not found"
                ),
            })
            has_broken_refs = True

    if has_broken_refs:
        return errors  # can't check topology with broken references

    # 6. Cycle detection (DFS)
    visited: set[str] = set()
    in_stack: set[str] = set()

    def _dfs_cycle(nid: str) -> str | None:
        visited.add(nid)
        in_stack.add(nid)
        ds = downstream_map.get(nid)
        if ds:
            if ds in in_stack:
                cycle = [nid, ds]
                cur = ds
                while downstream_map.get(cur) and downstream_map[cur] != ds:
                    cur = downstream_map[cur]
                    cycle.append(cur)
                return " → ".join(cycle)
            if ds not in visited:
                result = _dfs_cycle(ds)
                if result:
                    return result
        in_stack.discard(nid)
        return None

    for node in nodes:
        if node["id"] not in visited:
            cycle_str = _dfs_cycle(node["id"])
            if cycle_str:
                errors.append({
                    "type": "cycle_detected",
                    "node_id": node["id"],
                    "message": f"Cycle: {cycle_str}",
                })
                break

    if errors:
        return errors

    # 7. Component analysis (undirected BFS)
    adj: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adj[edge["from_id"]].add(edge["to_id"])
        adj[edge["to_id"]].add(edge["from_id"])

    component_map: dict[str, int] = {}
    comp_id = 0
    for node in nodes:
        nid = node["id"]
        if nid in component_map:
            continue
        queue: deque[str] = deque([nid])
        component_map[nid] = comp_id
        while queue:
            cur = queue.popleft()
            for neighbor in adj.get(cur, set()):
                if neighbor not in component_map:
                    component_map[neighbor] = comp_id
                    queue.append(neighbor)
        comp_id += 1

    components: dict[int, list[dict]] = defaultdict(list)
    for node in nodes:
        cid = component_map.get(node["id"], -1)
        components[cid].append(node)

    for cid, comp_nodes in components.items():
        roles_in_comp = {n["role"] for n in comp_nodes}
        ids_in_comp = {n["id"] for n in comp_nodes}

        if "outlet" not in roles_in_comp:
            errors.append({
                "type": "no_outlet",
                "node_id": None,
                "message": f"Component {ids_in_comp} has no outlet",
            })
        if "inlet" not in roles_in_comp:
            errors.append({
                "type": "no_inlet",
                "node_id": None,
                "message": f"Component {ids_in_comp} has no inlet",
            })

    return errors


def parse_sewer_topology(
    points_gdf: gpd.GeoDataFrame,
    lines_gdf: gpd.GeoDataFrame | None,
    field_mapping: dict,
    role_mapping: dict,
) -> ParsedTopology:
    """Parse and validate sewer topology from user data.

    Format A (lines_gdf=None): points with downstream_id, auto-generate lines.
    Format B (lines_gdf given): points + lines with from_node/to_node.

    Raises TopologyValidationError with structured report on invalid data.
    """
    role_lookup = _invert_role_mapping(role_mapping)
    nodes = _parse_nodes(points_gdf, field_mapping, role_lookup)

    if lines_gdf is None:
        edges = _generate_edges_from_downstream(nodes, points_gdf, field_mapping)
        source_format = "points_only"
    else:
        edges = _parse_edges_from_lines(nodes, lines_gdf, field_mapping)
        source_format = "points_and_lines"

    errors = _validate_topology(nodes, edges)
    if errors:
        raise TopologyValidationError(errors)

    return ParsedTopology(
        nodes=nodes,
        edges=edges,
        source_format=source_format,
    )
