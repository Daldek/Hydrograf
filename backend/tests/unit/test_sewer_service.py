"""Unit tests for core.sewer_service module."""

import geopandas as gpd
import numpy as np
import pytest
from scipy import sparse
from shapely.geometry import LineString, Point

from core.sewer_service import (
    SewerGraph,
    _snap_endpoints,
    build_sewer_graph,
    burn_inlets,
    propagate_fa_downstream,
    reconstruct_inlet_fa,
    route_fa_through_sewer,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_tree_lines():
    """3 lines forming tree: 2 inlets -> 1 junction -> 1 outlet.

    Topology (PL-1992 coords):
        A (500000, 600100) ---> B (500050, 600100) ---> D (500100, 600100)
        C (500050, 600150) -/

    D has the lowest y when B is a junction, but B and D share y=600100.
    D is the outlet because it is the degree-1 node with lowest y
    among the two degree-1 leaf nodes (A, C, D). D.y == A.y == 600100,
    but D.x > A.x — python min() picks A first. So we force D to have
    the lowest y:
    """
    return gpd.GeoDataFrame(
        {"geometry": [
            LineString([(500000, 600100), (500050, 600100)]),   # A -> B
            LineString([(500050, 600150), (500050, 600100)]),   # C -> B
            LineString([(500050, 600100), (500100, 600050)]),   # B -> D (D at y=600050)
        ]},
        crs="EPSG:2180",
    )


@pytest.fixture
def tree_with_elevations():
    """Lines with invert elevation attributes for direction detection.

    Connected chain: A (500000,600200) -> B (500050,600200) -> C (500100,600200)
    Elevations: A=110, B=105, C=100 (flow A->B->C by invert_start > invert_end).
    """
    return gpd.GeoDataFrame(
        {
            "geometry": [
                LineString([(500000, 600200), (500050, 600200)]),  # A -> B
                LineString([(500050, 600200), (500100, 600200)]),  # B -> C
            ],
            "inv_start": [110.0, 105.0],
            "inv_end": [105.0, 100.0],
        },
        crs="EPSG:2180",
    )


@pytest.fixture
def disconnected_lines():
    """Two separate line segments forming 2 disconnected components."""
    return gpd.GeoDataFrame(
        {"geometry": [
            LineString([(500000, 600100), (500050, 600050)]),
            LineString([(501000, 601100), (501050, 601050)]),
        ]},
        crs="EPSG:2180",
    )


# ---------------------------------------------------------------------------
# Tests: build_sewer_graph basics
# ---------------------------------------------------------------------------


class TestBuildSewerGraph:
    def test_simple_tree_node_count(self, simple_tree_lines):
        g = build_sewer_graph(simple_tree_lines)
        assert g.n_nodes == 4  # A, B, C, D

    def test_simple_tree_edge_count(self, simple_tree_lines):
        g = build_sewer_graph(simple_tree_lines)
        assert g.n_edges == 3

    def test_simple_tree_inlets(self, simple_tree_lines):
        g = build_sewer_graph(simple_tree_lines)
        inlets = g.get_nodes_by_type("inlet")
        assert len(inlets) == 2  # A and C

    def test_simple_tree_outlets(self, simple_tree_lines):
        g = build_sewer_graph(simple_tree_lines)
        outlets = g.get_nodes_by_type("outlet")
        assert len(outlets) == 1  # D

    def test_simple_tree_junctions(self, simple_tree_lines):
        g = build_sewer_graph(simple_tree_lines)
        junctions = g.get_nodes_by_type("junction")
        assert len(junctions) == 1  # B

    def test_simple_tree_single_component(self, simple_tree_lines):
        g = build_sewer_graph(simple_tree_lines)
        assert g.n_components == 1

    def test_simple_tree_no_warnings(self, simple_tree_lines):
        g = build_sewer_graph(simple_tree_lines)
        # Single connected component with outlet => no warnings
        assert len(g.warnings) == 0

    def test_simple_tree_root_outlet_assigned(self, simple_tree_lines):
        g = build_sewer_graph(simple_tree_lines)
        outlets = g.get_nodes_by_type("outlet")
        outlet_id = outlets[0]["id"]
        # All nodes should have root_outlet_id == outlet's id
        for node in g.nodes:
            assert node["root_outlet_id"] == outlet_id

    def test_adjacency_shape(self, simple_tree_lines):
        g = build_sewer_graph(simple_tree_lines)
        assert g.adj.shape == (4, 4)

    def test_adjacency_nnz(self, simple_tree_lines):
        """3 edges => 3 non-zero entries in directed adjacency."""
        g = build_sewer_graph(simple_tree_lines)
        assert g.adj.nnz == 3

    def test_direction_from_elevations(self, tree_with_elevations):
        g = build_sewer_graph(
            tree_with_elevations,
            attr_mapping={
                "invert_start": "inv_start",
                "invert_end": "inv_end",
            },
        )
        # 3 nodes, 2 edges, flow from high to low
        assert g.n_nodes == 3
        assert g.n_edges == 2

        # The outlet should be the node with the lowest invert elevation
        outlets = g.get_nodes_by_type("outlet")
        assert len(outlets) == 1

        # All edges should have from_node at higher elevation than to_node
        # (confirmed by having exactly 1 outlet and correct topology)
        inlets = g.get_nodes_by_type("inlet")
        assert len(inlets) == 1

        junctions = g.get_nodes_by_type("junction")
        assert len(junctions) == 1

    def test_disconnected_components(self, disconnected_lines):
        g = build_sewer_graph(disconnected_lines)
        assert g.n_components == 2
        assert g.n_nodes == 4
        assert g.n_edges == 2
        assert any("disconnected" in w.lower() for w in g.warnings)

    def test_empty_input(self):
        gdf = gpd.GeoDataFrame({"geometry": []}, crs="EPSG:2180")
        g = build_sewer_graph(gdf)
        assert g.n_nodes == 0
        assert g.n_edges == 0
        assert any("empty" in w.lower() for w in g.warnings)


# ---------------------------------------------------------------------------
# Tests: snapping
# ---------------------------------------------------------------------------


class TestSnapEndpoints:
    def test_snap_merges_close_endpoints(self):
        """2 lines with endpoints 0.5m apart should be snapped to one node."""
        lines = gpd.GeoDataFrame(
            {"geometry": [
                LineString([(500000, 600000), (500050, 600000)]),
                LineString([(500050.3, 600000.4), (500100, 600000)]),
            ]},
            crs="EPSG:2180",
        )
        g = build_sewer_graph(lines, snap_tolerance_m=2.0)
        # Without snapping: 4 nodes. With snapping: 3 (middle two merge)
        assert g.n_nodes == 3

    def test_no_snap_beyond_tolerance(self):
        """Endpoints 5m apart should NOT snap with tolerance=2."""
        lines = gpd.GeoDataFrame(
            {"geometry": [
                LineString([(500000, 600000), (500050, 600000)]),
                LineString([(500055, 600000), (500100, 600000)]),
            ]},
            crs="EPSG:2180",
        )
        g = build_sewer_graph(lines, snap_tolerance_m=2.0)
        assert g.n_nodes == 4  # No snapping

    def test_exact_match_snaps(self):
        """Endpoints at exact same location should always snap."""
        lines = gpd.GeoDataFrame(
            {"geometry": [
                LineString([(500000, 600000), (500050, 600000)]),
                LineString([(500050, 600000), (500100, 600000)]),
            ]},
            crs="EPSG:2180",
        )
        g = build_sewer_graph(lines, snap_tolerance_m=2.0)
        assert g.n_nodes == 3

    def test_snap_endpoints_returns_coords_and_map(self):
        """Verify the raw _snap_endpoints function output."""
        lines = gpd.GeoDataFrame(
            {"geometry": [
                LineString([(0, 0), (10, 0)]),
                LineString([(10, 0), (20, 0)]),
            ]},
            crs="EPSG:2180",
        )
        coords, mapping = _snap_endpoints(lines, tolerance_m=2.0)

        # 3 unique endpoints: (0,0), (10,0), (20,0)
        assert len(coords) == 3
        assert len(mapping) == 2  # 2 lines

        # Line 0 and Line 1 share middle node
        assert mapping[0][1] == mapping[1][0]


# ---------------------------------------------------------------------------
# Tests: BFS upstream inlets
# ---------------------------------------------------------------------------


class TestUpstreamInlets:
    def test_upstream_inlets_for_outlet(self, simple_tree_lines):
        g = build_sewer_graph(simple_tree_lines)
        outlets = g.get_nodes_by_type("outlet")
        assert len(outlets) == 1
        outlet_id = outlets[0]["id"]

        inlet_ids = g.get_upstream_inlets(outlet_id)
        assert len(inlet_ids) == 2

    def test_upstream_inlets_returns_only_inlets(self, simple_tree_lines):
        g = build_sewer_graph(simple_tree_lines)
        outlets = g.get_nodes_by_type("outlet")
        outlet_id = outlets[0]["id"]
        inlet_ids = g.get_upstream_inlets(outlet_id)

        # All returned IDs should be inlets
        inlet_node_ids = {n["id"] for n in g.get_nodes_by_type("inlet")}
        assert set(inlet_ids) == inlet_node_ids

    def test_upstream_inlets_nonexistent_node(self):
        gdf = gpd.GeoDataFrame(
            {"geometry": [LineString([(0, 0), (10, 0)])]},
            crs="EPSG:2180",
        )
        g = build_sewer_graph(gdf)
        assert g.get_upstream_inlets(999) == []


# ---------------------------------------------------------------------------
# Tests: user-specified outlets
# ---------------------------------------------------------------------------


class TestUserOutlets:
    def test_user_outlet_overrides_auto_detection(self):
        """User-specified outlet point near node D forces it as outlet."""
        lines = gpd.GeoDataFrame(
            {"geometry": [
                LineString([(500000, 600100), (500050, 600100)]),
                LineString([(500050, 600100), (500100, 600100)]),
            ]},
            crs="EPSG:2180",
        )
        # Place user outlet near (500000, 600100) — the left node
        user_pts = gpd.GeoDataFrame(
            {"geometry": [Point(500001, 600101)]},
            crs="EPSG:2180",
        )
        g = build_sewer_graph(lines, user_outlets=user_pts)
        outlets = g.get_nodes_by_type("outlet")
        assert len(outlets) == 1
        # The outlet should be near (500000, 600100)
        assert abs(outlets[0]["x"] - 500000) < 5
        assert abs(outlets[0]["y"] - 600100) < 5


# ---------------------------------------------------------------------------
# Tests: node properties
# ---------------------------------------------------------------------------


class TestNodeProperties:
    def test_node_has_all_required_fields(self, simple_tree_lines):
        g = build_sewer_graph(simple_tree_lines)
        required_fields = {
            "id", "x", "y", "node_type", "component_id",
            "depth_m", "invert_elev_m", "dem_elev_m", "burn_elev_m",
            "fa_value", "total_upstream_fa", "root_outlet_id", "source_type",
        }
        for node in g.nodes:
            assert required_fields <= set(node.keys())

    def test_edge_has_all_required_fields(self, simple_tree_lines):
        g = build_sewer_graph(simple_tree_lines)
        required_fields = {"id", "from_node", "to_node", "geom", "length_m"}
        for edge in g.edges:
            assert required_fields <= set(edge.keys())

    def test_edge_length_positive(self, simple_tree_lines):
        g = build_sewer_graph(simple_tree_lines)
        for edge in g.edges:
            assert edge["length_m"] > 0


# ---------------------------------------------------------------------------
# Tests: SewerGraph class
# ---------------------------------------------------------------------------


class TestSewerGraphClass:
    def test_empty_graph_properties(self):
        g = SewerGraph()
        assert g.n_nodes == 0
        assert g.n_edges == 0
        assert g.n_components == 0
        assert g.warnings == []

    def test_get_nodes_by_type_empty(self):
        g = SewerGraph()
        assert g.get_nodes_by_type("inlet") == []

    def test_get_upstream_inlets_empty(self):
        g = SewerGraph()
        assert g.get_upstream_inlets(0) == []


# ---------------------------------------------------------------------------
# Tests: direction from attributes
# ---------------------------------------------------------------------------


class TestDirectionFromAttributes:
    def test_attribute_direction_positive(self):
        """flow_direction > 0 means start->end direction."""
        lines = gpd.GeoDataFrame(
            {
                "geometry": [
                    LineString([(500000, 600100), (500050, 600050)]),
                    LineString([(500050, 600050), (500100, 600000)]),
                ],
                "flow_dir": [1.0, 1.0],
            },
            crs="EPSG:2180",
        )
        g = build_sewer_graph(
            lines,
            attr_mapping={"flow_direction": "flow_dir"},
        )
        outlets = g.get_nodes_by_type("outlet")
        assert len(outlets) == 1
        # Outlet should be the end of the chain (lowest y)
        assert outlets[0]["y"] == pytest.approx(600000, abs=5)

    def test_attribute_direction_negative(self):
        """flow_direction < 0 means end->start direction."""
        lines = gpd.GeoDataFrame(
            {
                "geometry": [
                    # Geometrically A->B, but flow_dir=-1 reverses to B->A
                    LineString([(500050, 600050), (500000, 600100)]),
                ],
                "flow_dir": [-1.0],
            },
            crs="EPSG:2180",
        )
        g = build_sewer_graph(
            lines,
            attr_mapping={"flow_direction": "flow_dir"},
        )
        # With reversal, flow goes from (500000,600100) to (500050,600050)
        outlets = g.get_nodes_by_type("outlet")
        assert len(outlets) == 1
        inlets = g.get_nodes_by_type("inlet")
        assert len(inlets) == 1


# ---------------------------------------------------------------------------
# Fixtures for raster operation tests
# ---------------------------------------------------------------------------


@pytest.fixture
def small_dem():
    """5x5 DEM with gentle slope."""
    return np.array([
        [110, 109, 108, 109, 110],
        [109, 108, 107, 108, 109],
        [108, 107, 106, 107, 108],
        [107, 106, 105, 106, 107],
        [106, 105, 104, 105, 106],
    ], dtype=np.float64)


@pytest.fixture
def small_fdir():
    """D8 fdir: all flowing toward center-bottom (4,2)."""
    return np.array([
        [2,   4,   4,   4,   8],
        [2,   2,   4,   8,   8],
        [1,   2,   4,   8,  16],
        [1,   2,   4,   8,  16],
        [1,   1,   0,  16,  16],
    ], dtype=np.int16)


@pytest.fixture
def small_fa():
    """Simple FA raster."""
    return np.array([
        [1, 1, 1, 1, 1],
        [2, 2, 3, 2, 2],
        [1, 3, 7, 3, 1],
        [1, 4, 12, 4, 1],
        [1, 5, 25, 5, 1],
    ], dtype=np.int32)


# ---------------------------------------------------------------------------
# Tests: burn_inlets
# ---------------------------------------------------------------------------


class TestBurnInlets:
    def test_burns_dem_at_inlet(self, small_dem):
        inlets = [{"id": 0, "row": 1, "col": 1, "depth_m": None, "invert_elev_m": None}]
        dem_copy = small_dem.copy()
        dem_mod, drain_pts = burn_inlets(dem_copy, inlets, default_depth_m=0.5)
        assert dem_mod[1, 1] == pytest.approx(108.0 - 0.5)
        assert (1, 1) in drain_pts

    def test_uses_invert_elevation(self, small_dem):
        inlets = [{"id": 0, "row": 1, "col": 1, "depth_m": None, "invert_elev_m": 106.0}]
        dem_copy = small_dem.copy()
        dem_mod, drain_pts = burn_inlets(dem_copy, inlets, default_depth_m=0.5)
        # DEM is 108 at (1,1), invert is 106, so depth = 2.0
        assert dem_mod[1, 1] == pytest.approx(108.0 - 2.0)

    def test_skips_negative_depth(self, small_dem):
        inlets = [{"id": 0, "row": 1, "col": 1, "depth_m": None, "invert_elev_m": 999.0}]
        dem_copy = small_dem.copy()
        dem_mod, drain_pts = burn_inlets(dem_copy, inlets, default_depth_m=0.5)
        assert dem_mod[1, 1] == 108.0
        assert len(drain_pts) == 0

    def test_skips_out_of_bounds(self, small_dem):
        inlets = [{"id": 0, "row": 99, "col": 99, "depth_m": 0.5, "invert_elev_m": None}]
        dem_copy = small_dem.copy()
        _, drain_pts = burn_inlets(dem_copy, inlets, default_depth_m=0.5)
        assert len(drain_pts) == 0

    def test_deduplicates_same_cell(self, small_dem):
        inlets = [
            {"id": 0, "row": 1, "col": 1, "depth_m": 0.3, "invert_elev_m": None},
            {"id": 1, "row": 1, "col": 1, "depth_m": 0.8, "invert_elev_m": None},
        ]
        dem_copy = small_dem.copy()
        dem_mod, drain_pts = burn_inlets(dem_copy, inlets, default_depth_m=0.5)
        assert dem_mod[1, 1] == pytest.approx(108.0 - 0.8)  # max depth
        assert drain_pts.count((1, 1)) == 1


# ---------------------------------------------------------------------------
# Tests: reconstruct_inlet_fa
# ---------------------------------------------------------------------------


class TestReconstructInletFa:
    def test_reconstructs_from_neighbors(self, small_fa, small_fdir):
        # Cell (2,2) has fdir=4 (south). Neighbors pointing TO (2,2):
        # (1,1) fdir=2 (SE) → points to (2,2) ✓
        # (1,2) fdir=4 (S) → points to (2,2) ✓
        # (1,3) fdir=8 (SW) → points to (2,2) ✓
        inlets = [{"id": 0, "row": 2, "col": 2}]
        reconstruct_inlet_fa(small_fa, small_fdir, inlets)
        assert inlets[0]["fa_value"] > 0

    def test_boundary_inlet_no_crash(self, small_fa, small_fdir):
        inlets = [{"id": 0, "row": 0, "col": 0}]
        reconstruct_inlet_fa(small_fa, small_fdir, inlets)
        assert inlets[0]["fa_value"] >= 0


# ---------------------------------------------------------------------------
# Tests: route_fa_through_sewer
# ---------------------------------------------------------------------------


class TestRouteFA:
    def test_simple_routing(self):
        graph = SewerGraph()
        graph.nodes = [
            {"id": 0, "node_type": "inlet", "fa_value": 100, "total_upstream_fa": None, "component_id": 0},
            {"id": 1, "node_type": "inlet", "fa_value": 200, "total_upstream_fa": None, "component_id": 0},
            {"id": 2, "node_type": "junction", "fa_value": None, "total_upstream_fa": None, "component_id": 0},
            {"id": 3, "node_type": "outlet", "fa_value": None, "total_upstream_fa": None, "component_id": 0},
        ]
        graph._node_lookup = {0: 0, 1: 1, 2: 2, 3: 3}
        row = np.array([2, 2, 3], dtype=np.int32)
        col = np.array([0, 1, 2], dtype=np.int32)
        graph.adj = sparse.csr_matrix(
            (np.ones(3, dtype=np.int8), (row, col)), shape=(4, 4)
        )
        route_fa_through_sewer(graph)
        assert graph.nodes[3]["total_upstream_fa"] == 300


# ---------------------------------------------------------------------------
# Tests: propagate_fa_downstream
# ---------------------------------------------------------------------------


class TestPropagateFa:
    def test_adds_surplus_downstream(self, small_fa, small_fdir):
        fa = small_fa.copy()
        outlets = [{"id": 0, "row": 2, "col": 2, "total_upstream_fa": 50}]
        original_at_outlet = small_fa[2, 2]
        original_below = small_fa[3, 2]
        propagate_fa_downstream(fa, small_fdir, outlets)
        assert fa[2, 2] == original_at_outlet + 50
        assert fa[3, 2] >= original_below + 50

    def test_zero_surplus_no_change(self, small_fa, small_fdir):
        fa = small_fa.copy()
        outlets = [{"id": 0, "row": 2, "col": 2, "total_upstream_fa": 0}]
        propagate_fa_downstream(fa, small_fdir, outlets)
        np.testing.assert_array_equal(fa, small_fa)
