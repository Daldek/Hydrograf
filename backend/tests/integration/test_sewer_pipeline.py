"""Integration test: full sewer pipeline on 100x100 synthetic DEM with DB."""

import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import Affine
from shapely.geometry import LineString
from sqlalchemy import text  # noqa: F401 — used in Task 3 (DB tests)

from core.sewer_service import (
    build_sewer_graph,
    burn_inlets,
    insert_sewer_data,  # noqa: F401 — used in Task 3 (DB tests)
    propagate_fa_downstream,
    reconstruct_inlet_fa,
    route_fa_through_sewer,
)

# --- Constants ---
NROWS = NCOLS = 100
CELLSIZE = 5.0
XMIN = 500000.0
YMAX = 300500.0  # top of raster = yllcorner + nrows * cellsize
NODATA = -9999.0
BURN_DEPTH_M = 2.0

# Sewer node positions as (row, col) in raster space
SEWER_NODES = {
    "inlet_a": (20, 30),
    "inlet_b": (20, 70),
    "junction": (50, 50),
    "outlet": (70, 50),
}

TRANSFORM = Affine(CELLSIZE, 0.0, XMIN, 0.0, -CELLSIZE, YMAX)


def _rc_to_xy(row, col):
    """Convert raster (row, col) to geographic (x, y) at cell center."""
    x = XMIN + col * CELLSIZE + CELLSIZE / 2
    y = YMAX - row * CELLSIZE - CELLSIZE / 2
    return x, y


@pytest.fixture(scope="module")
def pipeline_state():
    """Run full sewer pipeline on synthetic DEM, return all artifacts."""
    import pyflwdir
    from pyflwdir.dem import fill_depressions

    # --- 1. Synthetic DEM: SE gradient + valley at col 48-52 ---
    dem = np.zeros((NROWS, NCOLS), dtype=np.float64)
    for r in range(NROWS):
        for c in range(NCOLS):
            dem[r, c] = 200.0 - r * 1.0 - c * 0.5
    dem[:, 48:53] -= 5.0  # valley
    dem[0, 0] = NODATA

    dem_before_burn = dem.copy()

    # --- 2. Sewer GeoDataFrame: Y-junction (2 inlets → junction → outlet) ---
    coords = {name: _rc_to_xy(r, c) for name, (r, c) in SEWER_NODES.items()}
    sewer_gdf = gpd.GeoDataFrame(
        {"geometry": [
            LineString([coords["inlet_a"], coords["junction"]]),
            LineString([coords["inlet_b"], coords["junction"]]),
            LineString([coords["junction"], coords["outlet"]]),
        ]},
        crs="EPSG:2180",
    )

    # --- 3. Build sewer graph ---
    graph = build_sewer_graph(sewer_gdf, snap_tolerance_m=2.0)

    # --- 4. Map nodes to raster cells ---
    for n in graph.nodes:
        col_f, row_f = ~TRANSFORM * (n["x"], n["y"])
        n["row"] = int(row_f)
        n["col"] = int(col_f)

    # --- 5. Burn inlets ---
    inlets = [n for n in graph.nodes if n["node_type"] == "inlet"]
    dem, drain_points = burn_inlets(dem, inlets, default_depth_m=BURN_DEPTH_M)

    # --- 6. Hydrology via pyflwdir ---
    filled, d8_fdir = fill_depressions(
        dem, nodata=NODATA, max_depth=-1.0, outlets="edge"
    )

    fdir = d8_fdir.astype(np.int16)
    fdir[d8_fdir == 247] = 0  # pyflwdir nodata → 0

    flw = pyflwdir.from_array(d8_fdir, ftype="d8", transform=TRANSFORM, latlon=False)
    acc = flw.upstream_area(unit="cell").astype(np.int32)
    acc[acc < 0] = 0

    acc_before_sewer = acc.copy()

    # --- 7. Sewer FA pipeline ---
    reconstruct_inlet_fa(acc, fdir, inlets)
    route_fa_through_sewer(graph)

    acc_before_propagation = acc.copy()
    outlets = [n for n in graph.nodes if n["node_type"] == "outlet"]
    propagate_fa_downstream(acc, fdir, outlets)

    return {
        "dem_before_burn": dem_before_burn,
        "dem_burned": dem,
        "dem_filled": filled,
        "fdir": fdir,
        "acc": acc,
        "acc_before_sewer": acc_before_sewer,
        "acc_before_propagation": acc_before_propagation,
        "graph": graph,
        "inlets": inlets,
        "outlets": outlets,
        "drain_points": drain_points,
    }


class TestSewerPipelineInMemory:
    """Validate each sewer pipeline stage on synthetic 100x100 DEM."""

    def test_build_sewer_graph(self, pipeline_state):
        """Graph has correct Y-junction topology."""
        g = pipeline_state["graph"]

        assert g.n_nodes == 4
        assert g.n_edges == 3
        assert g.n_components == 1
        assert g.adj.shape == (4, 4)
        assert len(g.warnings) == 0

        assert len(g.get_nodes_by_type("inlet")) == 2
        assert len(g.get_nodes_by_type("junction")) == 1
        assert len(g.get_nodes_by_type("outlet")) == 1

    def test_burn_inlets(self, pipeline_state):
        """DEM lowered at inlet cells, drain_points returned."""
        dem_before = pipeline_state["dem_before_burn"]
        dem_after = pipeline_state["dem_burned"]
        inlets = pipeline_state["inlets"]
        drain_points = pipeline_state["drain_points"]

        assert len(drain_points) == 2

        for inlet in inlets:
            r, c = inlet["row"], inlet["col"]
            assert dem_after[r, c] < dem_before[r, c], (
                f"Inlet at ({r},{c}) not burned"
            )
            assert inlet["dem_elev_m"] is not None
            assert inlet["burn_elev_m"] is not None
            assert inlet["burn_elev_m"] < inlet["dem_elev_m"]

    def test_hydrology_processing(self, pipeline_state):
        """pyflwdir produces valid fdir and acc rasters."""
        fdir = pipeline_state["fdir"]
        acc = pipeline_state["acc_before_sewer"]

        assert fdir.shape == (NROWS, NCOLS)
        assert acc.shape == (NROWS, NCOLS)

        # Most cells have valid flow direction
        valid_fdir = np.isin(fdir, [1, 2, 4, 8, 16, 32, 64, 128])
        assert valid_fdir.sum() > NROWS * NCOLS * 0.95

        # FA > 0 almost everywhere (except nodata corner)
        assert (acc > 0).sum() > NROWS * NCOLS * 0.95

        # FA max should be in the valley (col ~50) in southern rows
        max_pos = np.unravel_index(acc.argmax(), acc.shape)
        assert max_pos[0] > 50, "Max FA should be in southern half"

    def test_reconstruct_inlet_fa(self, pipeline_state):
        """Inlets have reconstructed FA > 0."""
        inlets = pipeline_state["inlets"]

        for inlet in inlets:
            assert inlet.get("fa_value") is not None, (
                f"Inlet {inlet['id']} has no fa_value"
            )
            assert inlet["fa_value"] > 0, (
                f"Inlet {inlet['id']} fa_value={inlet['fa_value']}, expected > 0"
            )

    def test_route_fa_through_sewer(self, pipeline_state):
        """Outlet total_upstream_fa == sum of inlet fa_values."""
        inlets = pipeline_state["inlets"]
        outlets = pipeline_state["outlets"]
        graph = pipeline_state["graph"]

        assert len(outlets) == 1
        outlet = outlets[0]

        inlet_fa_sum = sum(n["fa_value"] for n in inlets)
        assert outlet["total_upstream_fa"] == inlet_fa_sum
        assert outlet["total_upstream_fa"] > 0

        # Junction and inlets should not have total_upstream_fa
        for n in graph.nodes:
            if n["node_type"] != "outlet":
                assert n.get("total_upstream_fa") is None

    def test_propagate_fa_downstream(self, pipeline_state):
        """FA downstream of outlet increased by surplus."""
        acc_before = pipeline_state["acc_before_propagation"]
        acc_after = pipeline_state["acc"]
        outlets = pipeline_state["outlets"]

        outlet = outlets[0]
        r, c = outlet["row"], outlet["col"]
        surplus = outlet["total_upstream_fa"]

        # FA at outlet cell increased
        assert acc_after[r, c] > acc_before[r, c]
        assert acc_after[r, c] - acc_before[r, c] == surplus

        # FA downstream also increased (follow fdir one step)
        fdir = pipeline_state["fdir"]
        d8_dr = {1: 0, 2: 1, 4: 1, 8: 1, 16: 0, 32: -1, 64: -1, 128: -1}
        d8_dc = {1: 1, 2: 1, 4: 0, 8: -1, 16: -1, 32: -1, 64: 0, 128: 1}

        d8 = int(fdir[r, c])
        assert d8 in d8_dr, f"Outlet fdir={d8} is not a valid D8 direction"
        nr = r + d8_dr[d8]
        nc = c + d8_dc[d8]
        assert 0 <= nr < NROWS and 0 <= nc < NCOLS, (
            "Downstream cell out of bounds"
        )
        assert acc_after[nr, nc] > acc_before[nr, nc]
