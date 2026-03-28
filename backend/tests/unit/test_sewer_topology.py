"""Unit tests for core.sewer_topology module."""

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point

from core.sewer_topology import (
    ParsedTopology,
    TopologyValidationError,
    parse_sewer_topology,
)


@pytest.fixture
def simple_points_format_a():
    """Format A: 3 points with downstream_id (inlet→junction→outlet)."""
    return gpd.GeoDataFrame(
        {
            "id": ["n1", "n2", "n3"],
            "role": ["inlet", "junction", "outlet"],
            "downstream_id": ["n2", "n3", None],
            "geometry": [
                Point(500_000, 200_000),
                Point(500_100, 200_100),
                Point(500_200, 200_200),
            ],
        },
        crs="EPSG:2180",
    )


@pytest.fixture
def default_field_mapping():
    return {
        "node_id": "id",
        "node_role": "role",
        "downstream_id": "downstream_id",
        "edge_from": "from_node",
        "edge_to": "to_node",
        "invert_elev": None,
        "depth": None,
        "diameter": None,
    }


@pytest.fixture
def default_role_mapping():
    return {
        "inlet": "inlet",
        "outlet": "outlet",
        "junction": "junction",
        "storage": "storage",
    }


class TestParseFormatA:
    def test_basic_parse(self, simple_points_format_a, default_field_mapping,
                         default_role_mapping):
        topo = parse_sewer_topology(
            simple_points_format_a, None,
            default_field_mapping, default_role_mapping,
        )
        assert isinstance(topo, ParsedTopology)
        assert topo.source_format == "points_only"

    def test_node_count(self, simple_points_format_a, default_field_mapping,
                        default_role_mapping):
        topo = parse_sewer_topology(
            simple_points_format_a, None,
            default_field_mapping, default_role_mapping,
        )
        assert len(topo.nodes) == 3

    def test_edge_count_auto_generated(self, simple_points_format_a,
                                        default_field_mapping,
                                        default_role_mapping):
        topo = parse_sewer_topology(
            simple_points_format_a, None,
            default_field_mapping, default_role_mapping,
        )
        assert len(topo.edges) == 2

    def test_node_roles(self, simple_points_format_a, default_field_mapping,
                        default_role_mapping):
        topo = parse_sewer_topology(
            simple_points_format_a, None,
            default_field_mapping, default_role_mapping,
        )
        roles = {n["id"]: n["role"] for n in topo.nodes}
        assert roles == {"n1": "inlet", "n2": "junction", "n3": "outlet"}

    def test_edges_have_geometry(self, simple_points_format_a,
                                  default_field_mapping, default_role_mapping):
        topo = parse_sewer_topology(
            simple_points_format_a, None,
            default_field_mapping, default_role_mapping,
        )
        for edge in topo.edges:
            assert edge["geometry"] is not None
            assert edge["geometry"].geom_type == "LineString"

    def test_edge_direction(self, simple_points_format_a,
                            default_field_mapping, default_role_mapping):
        topo = parse_sewer_topology(
            simple_points_format_a, None,
            default_field_mapping, default_role_mapping,
        )
        from_to = [(e["from_id"], e["to_id"]) for e in topo.edges]
        assert ("n1", "n2") in from_to
        assert ("n2", "n3") in from_to


class TestParseFormatAWithRoleMapping:
    def test_custom_role_values(self, default_field_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["a", "b"],
                "role": ["wpust", "wylot"],
                "downstream_id": ["b", None],
                "geometry": [Point(500_000, 200_000), Point(500_100, 200_100)],
            },
            crs="EPSG:2180",
        )
        role_mapping = {
            "inlet": "wpust",
            "outlet": "wylot",
            "junction": "studzienka",
            "storage": "zbiornik",
        }
        topo = parse_sewer_topology(gdf, None, default_field_mapping, role_mapping)
        roles = {n["id"]: n["role"] for n in topo.nodes}
        assert roles == {"a": "inlet", "b": "outlet"}
