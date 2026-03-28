"""Unit tests for core.sewer_service module (new topology interface)."""

import geopandas as gpd
import numpy as np
import pytest
from scipy import sparse
from shapely.geometry import LineString, Point

from core.sewer_topology import ParsedTopology, parse_sewer_topology
from core.sewer_service import (
    SewerGraph,
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
def default_field_mapping():
    return {
        "node_id": "id", "node_role": "role",
        "downstream_id": "downstream_id",
        "edge_from": "from_node", "edge_to": "to_node",
    }


@pytest.fixture
def default_role_mapping():
    return {"inlet": "inlet", "outlet": "outlet",
            "junction": "junction", "storage": "storage"}


@pytest.fixture
def y_junction_topology(default_field_mapping, default_role_mapping):
    """Y-junction: 2 inlets → junction → outlet, pre-parsed."""
    gdf = gpd.GeoDataFrame(
        {
            "id": ["i1", "i2", "j1", "o1"],
            "role": ["inlet", "inlet", "junction", "outlet"],
            "downstream_id": ["j1", "j1", "o1", None],
            "geometry": [
                Point(500_000, 200_000),
                Point(500_000, 200_200),
                Point(500_100, 200_100),
                Point(500_200, 200_100),
            ],
        },
        crs="EPSG:2180",
    )
    return parse_sewer_topology(gdf, None, default_field_mapping, default_role_mapping)


# ---------------------------------------------------------------------------
# Tests: build_sewer_graph (new topology interface)
# ---------------------------------------------------------------------------


class TestBuildSewerGraphNew:
    def test_accepts_parsed_topology(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        assert isinstance(graph, SewerGraph)

    def test_node_count(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        assert graph.n_nodes == 4

    def test_edge_count(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        assert graph.n_edges == 3

    def test_node_types(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        inlets = graph.get_nodes_by_type("inlet")
        outlets = graph.get_nodes_by_type("outlet")
        junctions = graph.get_nodes_by_type("junction")
        assert len(inlets) == 2
        assert len(outlets) == 1
        assert len(junctions) == 1

    def test_upstream_inlets_from_outlet(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        outlets = graph.get_nodes_by_type("outlet")
        inlet_ids = graph.get_upstream_inlets(outlets[0]["id"])
        assert len(inlet_ids) == 2

    def test_adjacency_matrix(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        assert graph.adj.nnz == 3

    def test_component_assignment(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        assert graph.n_components == 1
        for node in graph.nodes:
            assert "component_id" in node

    def test_root_outlet_id(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        outlet = graph.get_nodes_by_type("outlet")[0]
        assert outlet.get("root_outlet_id") is None
        for node in graph.nodes:
            if node["node_type"] != "outlet":
                assert node["root_outlet_id"] == outlet["id"]

    def test_node_lookup_populated(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        assert len(graph._node_lookup) == 4
        for node in graph.nodes:
            assert node["id"] in graph._node_lookup

    def test_edge_has_from_to_ids(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        for edge in graph.edges:
            assert "from_id" in edge
            assert "to_id" in edge
            assert "from_idx" in edge
            assert "to_idx" in edge

    def test_edge_length_m_present(self, y_junction_topology):
        graph = build_sewer_graph(y_junction_topology)
        for edge in graph.edges:
            assert "length_m" in edge
            assert edge["length_m"] >= 0.0

    def test_empty_topology_returns_empty_graph(self, default_field_mapping, default_role_mapping):
        """Topology with no nodes returns an empty SewerGraph."""
        # Manually construct an empty ParsedTopology
        topology = ParsedTopology(nodes=[], edges=[])
        graph = build_sewer_graph(topology)
        assert graph.n_nodes == 0
        assert graph.n_edges == 0
        assert graph.n_components == 0


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
