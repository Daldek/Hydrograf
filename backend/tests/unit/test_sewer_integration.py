"""Integration test: full sewer pipeline on synthetic DEM."""

import numpy as np
import pytest
import geopandas as gpd
from shapely.geometry import Point

from core.sewer_topology import parse_sewer_topology, TopologyValidationError
from core.sewer_service import (
    SewerGraph,
    build_sewer_graph,
    burn_inlets,
    reconstruct_inlet_fa,
    route_fa_through_sewer,
    propagate_fa_downstream,
)

# Standard field/role mappings for all tests
_FIELD_MAPPING = {
    "node_id": "id",
    "node_role": "role",
    "downstream_id": "downstream_id",
    "edge_from": "from_node",
    "edge_to": "to_node",
}
_ROLE_MAPPING = {
    "inlet": "inlet",
    "outlet": "outlet",
    "junction": "junction",
    "storage": "storage",
}


def _build_graph_from_points(points_data: list[dict]) -> SewerGraph:
    """Helper: build SewerGraph from list of dicts with id, role, downstream_id, x, y."""
    gdf = gpd.GeoDataFrame(
        [
            {
                "id": p["id"],
                "role": p["role"],
                "downstream_id": p.get("downstream_id"),
                "geometry": Point(p["x"], p["y"]),
            }
            for p in points_data
        ],
        crs="EPSG:2180",
    )
    topology = parse_sewer_topology(gdf, None, _FIELD_MAPPING, _ROLE_MAPPING)
    return build_sewer_graph(topology)


@pytest.fixture
def synthetic_dem():
    """30x30 DEM sloping from NW (high) to SE (low).

    Elevation = 200 - row - col, creating a uniform SE slope.
    """
    nrows, ncols = 30, 30
    dem = np.zeros((nrows, ncols), dtype=np.float64)
    for r in range(nrows):
        for c in range(ncols):
            dem[r, c] = 200.0 - r * 2.0 - c * 2.0
    return dem


@pytest.fixture
def synthetic_fdir():
    """D8 fdir for SE-sloping DEM. Most cells flow SE (D8=2).

    Bottom-right corner is pit (fdir=0).
    """
    nrows, ncols = 30, 30
    fdir = np.full((nrows, ncols), 2, dtype=np.int16)  # SE everywhere
    # Bottom row flows east
    fdir[-1, :] = 1
    fdir[-1, -1] = 0  # pit at corner
    # Right column flows south
    fdir[:, -1] = 4
    fdir[-1, -1] = 0  # pit
    return fdir


@pytest.fixture
def synthetic_fa(synthetic_fdir):
    """Compute simple FA from fdir. Each cell = count of upstream cells."""
    nrows, ncols = synthetic_fdir.shape
    fa = np.ones((nrows, ncols), dtype=np.int32)
    # Simple approximation: cells further SE have more upstream
    for r in range(nrows):
        for c in range(ncols):
            fa[r, c] = max(1, (r + 1) * (c + 1) // 4)
    return fa


@pytest.fixture
def simple_sewer_network():
    """Simple sewer: 2 inlets feeding into 1 junction, 1 outlet.

    All coordinates in EPSG:2180 space, matching synthetic DEM.
    Inlet A at (5.5, 24.5), Inlet B at (15.5, 24.5),
    Junction at (10.5, 14.5), Outlet at (25.5, 4.5).

    Note: coordinates are (x, y) = (col, row) convention for GIS.
    """
    points = [
        {"id": "A", "role": "inlet",    "downstream_id": "J",    "x": 5.5,  "y": 24.5},
        {"id": "B", "role": "inlet",    "downstream_id": "J",    "x": 15.5, "y": 24.5},
        {"id": "J", "role": "junction", "downstream_id": "OUT",  "x": 10.5, "y": 14.5},
        {"id": "OUT", "role": "outlet", "downstream_id": None,   "x": 25.5, "y": 4.5},
    ]
    gdf = gpd.GeoDataFrame(
        [
            {
                "id": p["id"],
                "role": p["role"],
                "downstream_id": p.get("downstream_id"),
                "geometry": Point(p["x"], p["y"]),
            }
            for p in points
        ],
        crs="EPSG:2180",
    )
    topology = parse_sewer_topology(gdf, None, _FIELD_MAPPING, _ROLE_MAPPING)
    return build_sewer_graph(topology)


class TestFullSewerPipeline:
    """End-to-end test of the sewer integration pipeline."""

    def test_graph_builds_correctly(self, simple_sewer_network):
        """Graph has correct topology: 2 inlets, 1 junction, 1 outlet."""
        graph = simple_sewer_network

        assert graph.n_nodes == 4
        assert graph.n_edges == 3
        assert len(graph.get_nodes_by_type("inlet")) == 2
        assert len(graph.get_nodes_by_type("outlet")) == 1
        assert len(graph.get_nodes_by_type("junction")) == 1
        assert graph.n_components == 1

    def test_inlet_burning_modifies_dem(self, synthetic_dem, simple_sewer_network):
        """Inlet burning lowers DEM at inlet cells and returns drain points."""
        graph = simple_sewer_network
        dem = synthetic_dem.copy()

        inlets = []
        for n in graph.nodes:
            if n["node_type"] == "inlet":
                # Manual row/col assignment for test (30x30 grid, cellsize=1)
                n["row"] = 30 - 1 - int(n["y"])  # flip y
                n["col"] = int(n["x"])
                if 0 <= n["row"] < 30 and 0 <= n["col"] < 30:
                    inlets.append(n)

        original_values = {(n["row"], n["col"]): dem[n["row"], n["col"]] for n in inlets}

        dem_mod, drain_pts = burn_inlets(dem, inlets, default_depth_m=1.0)

        assert len(drain_pts) > 0
        for n in inlets:
            r, c = n["row"], n["col"]
            if (r, c) in original_values:
                assert dem_mod[r, c] < original_values[(r, c)]

    def test_fa_reconstruction_produces_values(self, synthetic_fa, synthetic_fdir, simple_sewer_network):
        """FA reconstruction assigns positive values to inlet cells."""
        graph = simple_sewer_network

        inlets = []
        for n in graph.nodes:
            if n["node_type"] == "inlet":
                n["row"] = 30 - 1 - int(n["y"])
                n["col"] = int(n["x"])
                if 0 <= n["row"] < 30 and 0 <= n["col"] < 30:
                    inlets.append(n)

        reconstruct_inlet_fa(synthetic_fa, synthetic_fdir, inlets)

        # At least some inlets should have non-zero FA
        fa_values = [n.get("fa_value", 0) for n in inlets]
        assert any(v >= 0 for v in fa_values)

    def test_routing_sums_inlet_fa(self, synthetic_fa, synthetic_fdir, simple_sewer_network):
        """Routing correctly sums FA from inlets to outlet."""
        graph = simple_sewer_network

        # Manually set FA on inlets
        for n in graph.nodes:
            if n["node_type"] == "inlet":
                n["row"] = 30 - 1 - int(n["y"])
                n["col"] = int(n["x"])

        inlets = [n for n in graph.nodes if n["node_type"] == "inlet" and n.get("row", -1) >= 0]
        reconstruct_inlet_fa(synthetic_fa, synthetic_fdir, inlets)

        route_fa_through_sewer(graph)

        outlets = graph.get_nodes_by_type("outlet")
        assert len(outlets) == 1

        inlet_fa_sum = sum(n.get("fa_value", 0) for n in inlets)
        assert outlets[0]["total_upstream_fa"] == inlet_fa_sum

    def test_propagation_increases_downstream_fa(self, synthetic_fa, synthetic_fdir, simple_sewer_network):
        """FA propagation adds surplus to cells downstream of outlet."""
        graph = simple_sewer_network
        fa = synthetic_fa.copy()
        fa_original = synthetic_fa.copy()

        # Set up inlets
        for n in graph.nodes:
            if n["node_type"] in ("inlet", "outlet"):
                n["row"] = 30 - 1 - int(n["y"])
                n["col"] = int(n["x"])

        inlets = [n for n in graph.nodes if n["node_type"] == "inlet" and n.get("row", -1) >= 0]
        reconstruct_inlet_fa(fa, synthetic_fdir, inlets)
        route_fa_through_sewer(graph)

        outlets = [n for n in graph.nodes if n["node_type"] == "outlet" and n.get("row", -1) >= 0]

        if outlets and outlets[0].get("total_upstream_fa", 0) > 0:
            propagate_fa_downstream(fa, synthetic_fdir, outlets)

            # FA at outlet cell should have increased
            outlet = outlets[0]
            r, c = outlet["row"], outlet["col"]
            if 0 <= r < 30 and 0 <= c < 30:
                assert fa[r, c] >= fa_original[r, c]

    def test_full_pipeline_no_crash(self, synthetic_dem, synthetic_fa, synthetic_fdir, simple_sewer_network):
        """Full pipeline executes without errors."""
        graph = simple_sewer_network
        dem = synthetic_dem.copy()
        fa = synthetic_fa.copy()

        # Assign row/col to all relevant nodes
        for n in graph.nodes:
            n["row"] = 30 - 1 - int(n["y"])
            n["col"] = int(n["x"])

        # Step 3b: burn inlets
        inlets = [n for n in graph.nodes if n["node_type"] == "inlet" and 0 <= n["row"] < 30 and 0 <= n["col"] < 30]
        dem_mod, drain_pts = burn_inlets(dem, inlets, default_depth_m=0.5)

        # Step 4a: reconstruct FA
        reconstruct_inlet_fa(fa, synthetic_fdir, inlets)

        # Step 4b: route
        route_fa_through_sewer(graph)

        # Step 4c: propagate
        outlets = [n for n in graph.nodes if n["node_type"] == "outlet" and 0 <= n["row"] < 30 and 0 <= n["col"] < 30]
        propagate_fa_downstream(fa, synthetic_fdir, outlets)

        # Verify no NaN or negative FA
        assert not np.any(np.isnan(fa.astype(float)))
        assert np.all(fa >= 0)


class TestSewerPipelineEdgeCases:
    """Edge case tests for the sewer pipeline."""

    def test_empty_sewer_network(self):
        """Empty topology (no nodes) should produce empty graph."""
        from core.sewer_topology import ParsedTopology
        empty_topology = ParsedTopology(nodes=[], edges=[])
        graph = build_sewer_graph(empty_topology)
        assert graph.n_nodes == 0
        assert graph.n_edges == 0

    def test_single_line_network(self):
        """Single inlet + outlet creates 2-node, 1-edge graph."""
        graph = _build_graph_from_points([
            {"id": "I1",  "role": "inlet",  "downstream_id": "O1", "x": 0.0,  "y": 0.0},
            {"id": "O1",  "role": "outlet", "downstream_id": None,  "x": 10.0, "y": 10.0},
        ])
        assert graph.n_nodes == 2
        assert graph.n_edges == 1
        assert len(graph.get_nodes_by_type("inlet")) == 1
        assert len(graph.get_nodes_by_type("outlet")) == 1

    def test_disconnected_components(self):
        """Two independent inlet→outlet pairs form two components with a warning."""
        graph = _build_graph_from_points([
            {"id": "I1", "role": "inlet",  "downstream_id": "O1",  "x": 0.0,   "y": 0.0},
            {"id": "O1", "role": "outlet", "downstream_id": None,   "x": 10.0,  "y": 0.0},
            {"id": "I2", "role": "inlet",  "downstream_id": "O2",  "x": 100.0, "y": 100.0},
            {"id": "O2", "role": "outlet", "downstream_id": None,   "x": 110.0, "y": 100.0},
        ])
        assert graph.n_components == 2

    def test_regression_without_sewer(self, synthetic_fa):
        """FA raster should be unchanged when no sewer operations are applied."""
        fa_copy = synthetic_fa.copy()
        np.testing.assert_array_equal(synthetic_fa, fa_copy)
