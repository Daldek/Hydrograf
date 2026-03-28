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
        to_node = node_by_id[to_id]
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
    """Format B: parse edges from lines GeoDataFrame. (Stub — Task 4.)"""
    raise NotImplementedError("Format B parsing — see Task 4")


def _validate_topology(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Validate topology consistency. Returns list of error dicts. (Stub — Task 5.)"""
    return []


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
