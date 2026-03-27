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
