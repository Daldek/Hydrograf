"""Integration test: full sewer pipeline on 100x100 synthetic DEM with DB."""

import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import Affine
from shapely.geometry import Point
from sqlalchemy import text  # noqa: F401 — used in Task 3 (DB tests)

# Register DB fixtures from conftest_db
pytest_plugins = ["tests.conftest_db"]

from tests.conftest_db import requires_db

from core.sewer_service import (
    burn_inlets,
    insert_sewer_data,  # noqa: F401 — used in Task 3 (DB tests)
    propagate_fa_downstream,
    reconstruct_inlet_fa,
    route_fa_through_sewer,
)
from core.sewer_service import build_sewer_graph
from core.sewer_topology import parse_sewer_topology, validate_against_fdir

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
    # Format A: points with downstream_id
    coords = {name: _rc_to_xy(r, c) for name, (r, c) in SEWER_NODES.items()}

    points_gdf = gpd.GeoDataFrame(
        {
            "id": ["inlet_a", "inlet_b", "junction", "outlet"],
            "role": ["inlet", "inlet", "junction", "outlet"],
            "downstream_id": ["junction", "junction", "outlet", None],
            "geometry": [
                Point(coords["inlet_a"]),
                Point(coords["inlet_b"]),
                Point(coords["junction"]),
                Point(coords["outlet"]),
            ],
        },
        crs="EPSG:2180",
    )

    # --- 3. Parse topology and build sewer graph ---
    field_mapping = {
        "node_id": "id",
        "node_role": "role",
        "downstream_id": "downstream_id",
    }
    role_mapping = {
        "inlet": "inlet",
        "outlet": "outlet",
        "junction": "junction",
    }

    topology = parse_sewer_topology(points_gdf, None, field_mapping, role_mapping)
    graph = build_sewer_graph(topology)

    # --- 4. Map nodes to raster cells ---
    for n in graph.nodes:
        col_f, row_f = ~TRANSFORM * (n["x"], n["y"])
        n["row"] = int(row_f)
        n["col"] = int(col_f)

    # --- 5. Hydrology via pyflwdir (before burn, for fdir used in validation) ---
    filled_pre, d8_fdir_pre = fill_depressions(
        dem_before_burn.copy(), nodata=NODATA, max_depth=-1.0, outlets="edge"
    )
    fdir_pre = d8_fdir_pre.astype(np.int16)
    fdir_pre[d8_fdir_pre == 247] = 0

    # --- 6. Phase 1 validation: check for feedback loops ---
    fdir_errors = validate_against_fdir(topology, fdir_pre, TRANSFORM)
    # For a clean synthetic network there should be no feedback loops

    # --- 7. Burn inlets ---
    inlets = [n for n in graph.nodes if n["node_type"] == "inlet"]
    dem, drain_points = burn_inlets(dem, inlets, default_depth_m=BURN_DEPTH_M)

    # --- 8. Hydrology via pyflwdir (on burned DEM) ---
    filled, d8_fdir = fill_depressions(
        dem, nodata=NODATA, max_depth=-1.0, outlets="edge"
    )

    fdir = d8_fdir.astype(np.int16)
    fdir[d8_fdir == 247] = 0  # pyflwdir nodata → 0

    flw = pyflwdir.from_array(d8_fdir, ftype="d8", transform=TRANSFORM, latlon=False)
    acc = flw.upstream_area(unit="cell").astype(np.int32)
    acc[acc < 0] = 0

    acc_before_sewer = acc.copy()

    # --- 9. Sewer FA pipeline ---
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
        "fdir_errors": fdir_errors,
        "acc": acc,
        "acc_before_sewer": acc_before_sewer,
        "acc_before_propagation": acc_before_propagation,
        "graph": graph,
        "topology": topology,
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

    def test_validate_against_fdir(self, pipeline_state):
        """No feedback loops in clean synthetic sewer network."""
        fdir_errors = pipeline_state["fdir_errors"]
        assert fdir_errors == [], f"Unexpected fdir errors: {fdir_errors}"

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


@requires_db
@pytest.mark.db
class TestSewerDatabase:
    """DB tests for sewer pipeline: insert + augmented flag."""

    @pytest.fixture(autouse=True)
    def _db_cleanup(self, db_session):
        """Cleanup sewer data and synthetic stream after each test."""
        yield
        # Rollback any failed transaction before cleanup
        db_session.rollback()
        db_session.execute(
            text("TRUNCATE TABLE sewer_network RESTART IDENTITY CASCADE")
        )
        db_session.execute(
            text("TRUNCATE TABLE sewer_nodes RESTART IDENTITY CASCADE")
        )
        db_session.execute(
            text("DELETE FROM stream_network WHERE segment_idx = 9999")
        )
        db_session.execute(
            text(
                "UPDATE stream_network SET is_sewer_augmented = FALSE "
                "WHERE is_sewer_augmented = TRUE"
            )
        )
        db_session.commit()

    def test_insert_sewer_data(self, db_session, pipeline_state):
        """Sewer graph persisted to PostGIS correctly."""
        graph = pipeline_state["graph"]

        count = insert_sewer_data(graph, db_session, source_file="synthetic_test")
        assert count == 4 + 3  # 4 nodes + 3 edges

        # Verify node counts
        result = db_session.execute(
            text("SELECT COUNT(*) FROM sewer_nodes")
        )
        assert result.scalar() == 4

        result = db_session.execute(
            text("SELECT COUNT(*) FROM sewer_network")
        )
        assert result.scalar() == 3

        # Verify outlet has total_upstream_fa > 0
        result = db_session.execute(
            text(
                "SELECT total_upstream_fa FROM sewer_nodes "
                "WHERE node_type = 'outlet'"
            )
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] > 0

        # Verify inlets have fa_value > 0
        result = db_session.execute(
            text(
                "SELECT fa_value FROM sewer_nodes "
                "WHERE node_type = 'inlet'"
            )
        )
        rows = result.fetchall()
        assert len(rows) == 2
        for row in rows:
            assert row[0] > 0

        # Verify edges have positive length and correct source
        result = db_session.execute(
            text(
                "SELECT length_m, source FROM sewer_network"
            )
        )
        for length_m, source in result.fetchall():
            assert length_m > 0
            assert source == "synthetic_test"

        # Verify geometries are SRID 2180
        result = db_session.execute(
            text("SELECT ST_SRID(geom) FROM sewer_nodes LIMIT 1")
        )
        assert result.scalar() == 2180

    def test_sewer_augmented_flag(self, db_session, pipeline_state):
        """Stream segments near outlet marked is_sewer_augmented=TRUE."""
        graph = pipeline_state["graph"]
        outlet = pipeline_state["outlets"][0]

        # Insert synthetic stream segment within 50m of outlet
        db_session.execute(
            text(
                "INSERT INTO stream_network "
                "(geom, threshold_m2, segment_idx, is_sewer_augmented) "
                "VALUES ("
                "  ST_SetSRID("
                "    ST_MakeLine(ST_MakePoint(:x1, :y), ST_MakePoint(:x2, :y)),"
                "    2180"
                "  ), 1000, 9999, FALSE"
                ")"
            ),
            {
                "x1": outlet["x"] - 20.0,
                "x2": outlet["x"] + 20.0,
                "y": outlet["y"],
            },
        )
        db_session.commit()

        # Run insert_sewer_data (which updates is_sewer_augmented)
        insert_sewer_data(graph, db_session, source_file="synthetic_test")

        # Verify flag was set
        result = db_session.execute(
            text(
                "SELECT is_sewer_augmented FROM stream_network "
                "WHERE segment_idx = 9999"
            )
        )
        assert result.scalar() is True
