"""Unit tests for core.sewer_topology module."""

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString as ShapelyLineString
from shapely.geometry import Point

from core.sewer_topology import (
    ParsedTopology,
    TopologyValidationError,
    parse_sewer_topology,
    validate_against_fdir,
)
from rasterio.transform import from_bounds


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


@pytest.fixture
def points_and_lines_format_b():
    """Format B: separate point + line layers."""
    points = gpd.GeoDataFrame(
        {
            "id": ["n1", "n2", "n3"],
            "role": ["inlet", "junction", "outlet"],
            "geometry": [
                Point(500_000, 200_000),
                Point(500_100, 200_100),
                Point(500_200, 200_200),
            ],
        },
        crs="EPSG:2180",
    )
    lines = gpd.GeoDataFrame(
        {
            "from_node": ["n1", "n2"],
            "to_node": ["n2", "n3"],
            "diameter_mm": [300, 400],
            "geometry": [
                ShapelyLineString([(500_000, 200_000), (500_050, 200_050),
                                   (500_100, 200_100)]),
                ShapelyLineString([(500_100, 200_100), (500_150, 200_150),
                                   (500_200, 200_200)]),
            ],
        },
        crs="EPSG:2180",
    )
    return points, lines


class TestParseFormatB:
    def test_basic_parse(self, points_and_lines_format_b, default_field_mapping,
                         default_role_mapping):
        points, lines = points_and_lines_format_b
        topo = parse_sewer_topology(
            points, lines, default_field_mapping, default_role_mapping,
        )
        assert isinstance(topo, ParsedTopology)
        assert topo.source_format == "points_and_lines"

    def test_node_count(self, points_and_lines_format_b, default_field_mapping,
                        default_role_mapping):
        points, lines = points_and_lines_format_b
        topo = parse_sewer_topology(
            points, lines, default_field_mapping, default_role_mapping,
        )
        assert len(topo.nodes) == 3

    def test_edge_count(self, points_and_lines_format_b, default_field_mapping,
                        default_role_mapping):
        points, lines = points_and_lines_format_b
        topo = parse_sewer_topology(
            points, lines, default_field_mapping, default_role_mapping,
        )
        assert len(topo.edges) == 2

    def test_edges_preserve_geometry(self, points_and_lines_format_b,
                                      default_field_mapping, default_role_mapping):
        """Format B edges keep original line geometry (not straight line)."""
        points, lines = points_and_lines_format_b
        topo = parse_sewer_topology(
            points, lines, default_field_mapping, default_role_mapping,
        )
        for edge in topo.edges:
            assert len(edge["geometry"].coords) == 3

    def test_edges_have_attributes(self, points_and_lines_format_b,
                                    default_field_mapping, default_role_mapping):
        default_field_mapping["diameter"] = "diameter_mm"
        points, lines = points_and_lines_format_b
        topo = parse_sewer_topology(
            points, lines, default_field_mapping, default_role_mapping,
        )
        diameters = [e.get("diameter") for e in topo.edges]
        assert diameters == [300, 400]


class TestValidationDuplicateId:
    def test_duplicate_node_id(self, default_field_mapping, default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["n1", "n1", "n2"],
                "role": ["inlet", "junction", "outlet"],
                "downstream_id": ["n1", "n2", None],
                "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(gdf, None, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "duplicate_id" for e in exc_info.value.errors)


class TestValidationInvalidRole:
    def test_unknown_role(self, default_field_mapping, default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2"],
                "role": ["pump", "outlet"],
                "downstream_id": ["n2", None],
                "geometry": [Point(0, 0), Point(1, 1)],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(gdf, None, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "invalid_role" for e in exc_info.value.errors)


class TestValidationMissingTarget:
    def test_downstream_id_not_found(self, default_field_mapping,
                                      default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2"],
                "role": ["inlet", "outlet"],
                "downstream_id": ["n99", None],
                "geometry": [Point(0, 0), Point(1, 1)],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(gdf, None, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "missing_target" for e in exc_info.value.errors)


class TestValidationOutletHasDownstream:
    def test_outlet_with_downstream(self, default_field_mapping,
                                     default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2", "n3"],
                "role": ["inlet", "outlet", "junction"],
                "downstream_id": ["n2", "n3", None],
                "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(gdf, None, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "outlet_has_downstream"
                   for e in exc_info.value.errors)


class TestValidationMissingDownstream:
    def test_inlet_without_downstream(self, default_field_mapping,
                                       default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2"],
                "role": ["inlet", "outlet"],
                "downstream_id": [None, None],
                "geometry": [Point(0, 0), Point(1, 1)],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(gdf, None, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "missing_downstream"
                   for e in exc_info.value.errors)


class TestValidationCycleDetected:
    def test_cycle(self, default_field_mapping, default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2", "n3"],
                "role": ["inlet", "junction", "junction"],
                "downstream_id": ["n2", "n3", "n1"],
                "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(gdf, None, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "cycle_detected" for e in exc_info.value.errors)


class TestValidationNoOutlet:
    def test_component_without_outlet(self, default_field_mapping,
                                       default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2"],
                "role": ["inlet", "junction"],
                "downstream_id": ["n2", None],
                "geometry": [Point(0, 0), Point(1, 1)],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(gdf, None, default_field_mapping,
                                 default_role_mapping)
        errors = exc_info.value.errors
        error_types = [e["type"] for e in errors]
        assert "missing_downstream" in error_types or "no_outlet" in error_types


class TestValidationNoInlet:
    def test_component_without_inlet(self, default_field_mapping,
                                      default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2"],
                "role": ["junction", "outlet"],
                "downstream_id": ["n2", None],
                "geometry": [Point(0, 0), Point(1, 1)],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(gdf, None, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "no_inlet" for e in exc_info.value.errors)


class TestValidationDirectionMismatch:
    def test_edge_to_inlet(self, default_field_mapping, default_role_mapping):
        """Format B: edge pointing TO an inlet is invalid."""
        points = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2", "n3"],
                "role": ["junction", "inlet", "outlet"],
                "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
            },
            crs="EPSG:2180",
        )
        lines = gpd.GeoDataFrame(
            {
                "from_node": ["n1", "n1"],
                "to_node": ["n2", "n3"],
                "geometry": [
                    ShapelyLineString([(0, 0), (1, 1)]),
                    ShapelyLineString([(0, 0), (2, 2)]),
                ],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(points, lines, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "direction_mismatch" for e in exc_info.value.errors)

    def test_edge_from_outlet(self, default_field_mapping, default_role_mapping):
        """Format B: edge FROM an outlet is invalid."""
        points = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2", "n3"],
                "role": ["inlet", "outlet", "junction"],
                "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
            },
            crs="EPSG:2180",
        )
        lines = gpd.GeoDataFrame(
            {
                "from_node": ["n1", "n2"],
                "to_node": ["n2", "n3"],
                "geometry": [
                    ShapelyLineString([(0, 0), (1, 1)]),
                    ShapelyLineString([(1, 1), (2, 2)]),
                ],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(points, lines, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "direction_mismatch" for e in exc_info.value.errors)


class TestValidationOrphanEdge:
    def test_edge_references_missing_node(self, default_field_mapping,
                                           default_role_mapping):
        points = gpd.GeoDataFrame(
            {
                "id": ["n1", "n2"],
                "role": ["inlet", "outlet"],
                "geometry": [Point(0, 0), Point(1, 1)],
            },
            crs="EPSG:2180",
        )
        lines = gpd.GeoDataFrame(
            {
                "from_node": ["n1", "n99"],
                "to_node": ["n2", "n2"],
                "geometry": [
                    ShapelyLineString([(0, 0), (1, 1)]),
                    ShapelyLineString([(5, 5), (1, 1)]),
                ],
            },
            crs="EPSG:2180",
        )
        with pytest.raises(TopologyValidationError) as exc_info:
            parse_sewer_topology(points, lines, default_field_mapping,
                                 default_role_mapping)
        assert any(e["type"] == "orphan_edge" for e in exc_info.value.errors)


class TestValidationValidData:
    def test_valid_y_junction(self, default_field_mapping, default_role_mapping):
        """Y-junction: 2 inlets → junction → outlet. Must pass."""
        gdf = gpd.GeoDataFrame(
            {
                "id": ["i1", "i2", "j1", "o1"],
                "role": ["inlet", "inlet", "junction", "outlet"],
                "downstream_id": ["j1", "j1", "o1", None],
                "geometry": [
                    Point(0, 0), Point(0, 2),
                    Point(1, 1), Point(2, 1),
                ],
            },
            crs="EPSG:2180",
        )
        topo = parse_sewer_topology(gdf, None, default_field_mapping,
                                     default_role_mapping)
        assert len(topo.nodes) == 4
        assert len(topo.edges) == 3

    def test_storage_node_passes(self, default_field_mapping,
                                  default_role_mapping):
        gdf = gpd.GeoDataFrame(
            {
                "id": ["i1", "s1", "o1"],
                "role": ["inlet", "storage", "outlet"],
                "downstream_id": ["s1", "o1", None],
                "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
            },
            crs="EPSG:2180",
        )
        topo = parse_sewer_topology(gdf, None, default_field_mapping,
                                     default_role_mapping)
        assert len(topo.nodes) == 3
        roles = {n["id"]: n["role"] for n in topo.nodes}
        assert roles["s1"] == "storage"


class TestValidateAgainstFdir:
    @pytest.fixture
    def small_fdir_se(self):
        """10x10 fdir grid, all flowing SE (D8 value=2). Pit at SE corner."""
        fdir = np.full((10, 10), 2, dtype=np.uint8)
        fdir[9, 9] = 0  # pit at SE corner
        # Transform: cols map to x (0-50), rows map to y (50-0) — top-left origin
        transform = from_bounds(0, 0, 50, 50, 10, 10)
        return fdir, transform

    def test_no_loop_outlet_upstream_of_inlet(self, small_fdir_se,
                                               default_field_mapping,
                                               default_role_mapping):
        """Outlet at NW (upstream in fdir), inlet at SE (downstream).
        Sewer pipes water from SE inlet back to NW outlet.
        Outlet's fdir path goes SE toward inlet → LOOP expected."""
        fdir, transform = small_fdir_se
        # Outlet at NW corner (row=1, col=1), fdir goes SE → path hits SE
        # Inlet at SE area (row=7, col=7)
        # Sewer: inlet(SE) → outlet(NW) — physically pipes water uphill
        # Outlet's fdir downstream path: (1,1)→(2,2)→...→(7,7) = inlet cell → LOOP
        gdf = gpd.GeoDataFrame(
            {
                "id": ["inlet1", "outlet1"],
                "role": ["inlet", "outlet"],
                "downstream_id": ["outlet1", None],
                "geometry": [
                    Point(37.5, 12.5),  # col=7, row=7 in 10x10 grid (SE area)
                    Point(7.5, 42.5),   # col=1, row=1 in 10x10 grid (NW area)
                ],
            },
            crs="EPSG:2180",
        )
        topo = parse_sewer_topology(gdf, None, default_field_mapping,
                                     default_role_mapping)
        errors = validate_against_fdir(topo, fdir, transform)
        assert len(errors) > 0
        assert errors[0]["type"] == "feedback_loop"

    def test_no_loop_safe_config(self, small_fdir_se, default_field_mapping,
                                  default_role_mapping):
        """Outlet at SE (downstream in fdir), inlet at NW (upstream).
        Sewer pipes water from NW inlet to SE outlet — same as natural flow.
        Outlet's fdir path goes further SE, never back to NW inlet → no loop."""
        fdir, transform = small_fdir_se
        gdf = gpd.GeoDataFrame(
            {
                "id": ["inlet1", "outlet1"],
                "role": ["inlet", "outlet"],
                "downstream_id": ["outlet1", None],
                "geometry": [
                    Point(7.5, 42.5),   # col=1, row=1 (NW = upstream in fdir)
                    Point(37.5, 12.5),  # col=7, row=7 (SE = downstream in fdir)
                ],
            },
            crs="EPSG:2180",
        )
        topo = parse_sewer_topology(gdf, None, default_field_mapping,
                                     default_role_mapping)
        errors = validate_against_fdir(topo, fdir, transform)
        assert errors == []
