"""
Find where the flow of the NMT leaves given catchment polygons.

A polygon that is the NMT watershed of its outlet drains through that one cell; the
export of the catchment parameters then has ``polygon_to_upstream_area_ratio`` of about
1. A ratio above 1 means that part of the polygon drains elsewhere. For every polygon
this script takes the cells whose D8 flow leaves it (to a cell of another polygon or
of none, to a cell without NMT data, or nowhere: a pit), groups the connected ones
with the same destination into exits and accumulates the flow within the polygon, so
each exit gets the area of the polygon that leaves through it. Every cell of the
polygon leaves through exactly one exit. The exit that holds the outlet of the export
(the cell of the largest flow accumulation) is marked.

The rasters are those of export_catchment_parameters (open_rasters: the VRT mosaics
of an active unit run, otherwise the GeoTIFFs of DEM_DIR), read in the window of each
polygon only. The GeoPackage (the exits as points, the part of the polygon that
drains to each exit of at least ``--min-exit-km2`` as polygons, the summary of each
polygon as a table) is written to a local temporary directory and copied to the
output, so the output may be on a network share; the CSV holds the summary.

Usage
-----
    cd backend
    python -m scripts.diagnose_catchment_exits --input zlewnie.gpkg \
        --layer zlew_h_07 --key ID_HYD_10 --ids 1863141,1883617 \
        --output wyjscia_zlewni.gpkg
"""

import argparse
import logging
import shutil
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyflwdir
from rasterio.features import rasterize, shapes
from rasterio.transform import Affine, array_bounds
from scipy import ndimage
from shapely.geometry import Point, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from core.cell_parameters import PipelineRasters, d8_from_saved_flowdir, outlet_cell
from core.config import get_settings
from core.constants import CRS_PL1992, M2_PER_KM2
from core.hydrology import D8_COL_OFFSET, D8_ROW_OFFSET, D8_VALID
from core.version import get_version
from scripts.export_catchment_parameters import (
    PANEL_THRESHOLD_M2,
    open_rasters,
    read_polygon_cells,
    read_polygons,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Where the flow of an exit goes: a cell with NMT data outside the polygon, a cell
# without NMT data (or beyond the raster), nowhere (a pit of the flow directions)
OUTFLOW, NODATA, PIT = "outflow", "nodata", "pit"
# The destination of an outflow into a cell of no polygon of the layer
OUTSIDE_LAYER = "outside_layer"
# An exit draining less than this gets no area and is not counted in
# exit_count_over_min and the receivers of the summary [km²]
DEFAULT_MIN_EXIT_KM2 = 0.01
EXITS_LAYER = "catchment_exits"
AREAS_LAYER = "catchment_exit_areas"
SUMMARY_LAYER = "catchment_exit_summary"


@dataclass(frozen=True)
class Exit:
    """Connected cells of a polygon whose flow leaves it to the same destination.

    Attributes
    ----------
    kind : str
        OUTFLOW, NODATA or PIT.
    receiver : int
        Index + 1 of the polygon that holds the cells the flow goes to (OUTFLOW);
        0 for none of the polygons, a cell without data or a pit.
    cell : tuple[int, int]
        Row and column of the cell of the exit with the largest flow accumulation
        within the polygon.
    boundary_cells : int
        Cells of the exit.
    upstream_cells : int
        Cells of the polygon whose flow leaves it through this exit.
    is_outlet : bool
        Whether the exit holds the outlet of the export.
    """

    kind: str
    receiver: int
    cell: tuple[int, int]
    boundary_cells: int
    upstream_cells: int
    is_outlet: bool


def polygon_exits(
    d8: np.ndarray,
    member: np.ndarray,
    receivers: np.ndarray,
    outlet: tuple[int, int],
) -> tuple[list[Exit], np.ndarray]:
    """Group the cells where the flow leaves a polygon into exits.

    The flow accumulates within the polygon only: flow from outside is not counted
    and a cell whose flow leaves the polygon ends its path there, so the
    ``upstream_cells`` of the exits add up to the cells of the polygon.

    Parameters
    ----------
    d8 : np.ndarray
        pyflwdir D8 flow directions of a window around the polygon (uint8; 0 is a
        pit, 247 a cell without data).
    member : np.ndarray
        Cells of the polygon (bool), all with data.
    receivers : np.ndarray
        Index + 1 of the polygon that holds each cell, 0 for none (int).
    outlet : tuple[int, int]
        Cell of the polygon that the export takes as its outlet.

    Returns
    -------
    list[Exit]
        The exits, the largest ``upstream_cells`` first.
    np.ndarray
        For each cell of the polygon the number of the exit it leaves through (its
        position in the list + 1); 0 outside the polygon (int64).
    """
    nrows, ncols = d8.shape
    rows, cols = np.indices(d8.shape)
    has_dir = D8_VALID[d8] & member
    down_row = rows + D8_ROW_OFFSET[d8]
    down_col = cols + D8_COL_OFFSET[d8]
    in_window = (
        (down_row >= 0) & (down_row < nrows) & (down_col >= 0) & (down_col < ncols)
    )
    down_row = np.clip(down_row, 0, nrows - 1)
    down_col = np.clip(down_col, 0, ncols - 1)
    leads = has_dir & in_window
    down_member = leads & member[down_row, down_col]
    terminal = member & ~down_member

    # Destination of each terminal cell: the receiving polygon (>= 1), 0 outside
    # every polygon, -1 without data, -2 a pit
    down_valid = leads & (d8[down_row, down_col] != 247)
    destination = np.where(down_valid, receivers[down_row, down_col], -1)
    destination = np.where(has_dir, destination, -2)

    # Accumulation within the polygon: the terminal cells are pits, the rest of the
    # window is outside the grid
    inner = np.where(down_member, d8, np.where(member, 0, 247)).astype(np.uint8)
    flw = pyflwdir.from_array(inner, ftype="d8", check_ftype=False, latlon=False)
    upstream = flw.accuflux(member.astype(np.int64), nodata=-1)

    groups = np.zeros(d8.shape, dtype=np.int64)
    group_dest: list[int] = []
    eight = np.ones((3, 3), dtype=bool)
    for dest in np.unique(destination[terminal]):
        labels, count = ndimage.label(terminal & (destination == dest), structure=eight)
        groups[labels > 0] = labels[labels > 0] + len(group_dest)
        group_dest.extend([int(dest)] * count)

    idx = np.flatnonzero(terminal)
    gid = groups.ravel()[idx] - 1
    acc = upstream.ravel()[idx]
    n_groups = len(group_dest)
    upstream_cells = np.bincount(gid, weights=acc, minlength=n_groups)
    boundary_cells = np.bincount(gid, minlength=n_groups)
    # The cell of the largest accumulation of each group: the last of its sort
    order = np.lexsort((acc, gid))
    last = np.flatnonzero(np.r_[gid[order][1:] != gid[order][:-1], True])
    best = idx[order[last]]
    outlet_group = int(groups[outlet]) - 1

    exits = []
    for g, dest in enumerate(group_dest):
        row, col = np.unravel_index(int(best[g]), d8.shape)
        exits.append(
            Exit(
                kind=OUTFLOW if dest >= 0 else NODATA if dest == -1 else PIT,
                receiver=max(dest, 0),
                cell=(int(row), int(col)),
                boundary_cells=int(boundary_cells[g]),
                upstream_cells=round(float(upstream_cells[g])),
                is_outlet=g == outlet_group,
            )
        )
    ranking = sorted(
        range(n_groups),
        key=lambda g: (-exits[g].upstream_cells, not exits[g].is_outlet),
    )
    # The number of each group's exit in the sorted list, 0 for no group
    number = np.zeros(n_groups + 1, dtype=np.int64)
    number[np.array(ranking, dtype=np.int64) + 1] = np.arange(1, n_groups + 1)
    drained = flw.basins(idxs=idx, ids=(gid + 1).astype(np.uint32))
    return [exits[g] for g in ranking], number[drained]


def reenters(d8: np.ndarray, member: np.ndarray, cell: tuple[int, int]) -> bool:
    """Whether the flow from an exit cell comes back into the polygon in the window."""
    nrows, ncols = d8.shape
    row, col = cell
    for _ in range(d8.size):
        code = int(d8[row, col])
        if not D8_VALID[code]:
            return False
        row, col = row + int(D8_ROW_OFFSET[code]), col + int(D8_COL_OFFSET[code])
        if not (0 <= row < nrows and 0 <= col < ncols):
            return False
        if member[row, col]:
            return True
    return False


def _receivers(
    polygons: gpd.GeoDataFrame, shape: tuple[int, int], transform: Affine
) -> np.ndarray:
    """Index + 1 of the polygon whose geometry holds the centre of each cell."""
    bounds = array_bounds(shape[0], shape[1], transform)
    hits = polygons.sindex.query(box(*bounds))
    if not len(hits):
        return np.zeros(shape, dtype=np.int32)
    return np.asarray(
        rasterize(
            [(polygons.geometry.iloc[i], int(i) + 1) for i in hits],
            out_shape=shape,
            transform=transform,
            fill=0,
            dtype="int32",
        )
    )


def diagnose_polygon(
    geometry: BaseGeometry,
    rasters: PipelineRasters,
    polygons: gpd.GeoDataFrame,
    key: str,
    min_exit_km2: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Find the exits of a polygon and summarise them.

    Parameters
    ----------
    geometry : BaseGeometry
        The polygon, in EPSG:2180.
    rasters : PipelineRasters
        Open rasters of the pipeline.
    polygons : gpd.GeoDataFrame
        Every polygon of the layer (the receivers), with ``key``.
    key : str
        Key field of ``polygons``.
    min_exit_km2 : float
        Exits draining less get no area and are left out of the counts and the
        receivers of the summary.

    Returns
    -------
    tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]
        A row per exit (with its point), a row per exit of at least
        ``min_exit_km2`` (with the part of the polygon that drains to it), and the
        summary of the polygon.
    """
    cells = read_polygon_cells(geometry, rasters)
    cell_km2 = rasters.cellsize_m**2 / M2_PER_KM2
    member_cells = int(np.count_nonzero(cells.member))
    summary: dict[str, Any] = {
        "polygon_area_km2": round(geometry.area / M2_PER_KM2, 4),
        "cell_area_km2": round(member_cells * cell_km2, 4),
    }
    if not member_cells:
        return [], [], summary
    outlet = outlet_cell(cells)
    d8 = d8_from_saved_flowdir(cells.fdir, cells.flow_dist, cells.valid)
    receivers = _receivers(polygons, d8.shape, cells.transform)
    exits, drained = polygon_exits(d8, cells.member, receivers, outlet)
    # Mean slope of the cells that leave through each exit (the slope raster's
    # nodata is negative)
    slope = cells.slope
    if slope is None:
        raise ValueError("The window holds no slope")
    sloped = cells.member & (slope >= 0)
    slope_sum = np.bincount(
        drained[sloped], weights=slope[sloped], minlength=len(exits) + 1
    )
    slope_count = np.bincount(drained[sloped], minlength=len(exits) + 1)

    def destination(e: Exit) -> str:
        if e.receiver:
            return str(polygons[key].iloc[e.receiver - 1])
        return OUTSIDE_LAYER if e.kind == OUTFLOW else e.kind

    rows = []
    for number, e in enumerate(exits, start=1):
        x, y = cells.transform * (e.cell[1] + 0.5, e.cell[0] + 0.5)
        rows.append(
            {
                "exit_id": number,
                "kind": e.kind,
                "destination": destination(e),
                "is_export_outlet": e.is_outlet,
                "reenters_polygon": e.kind == OUTFLOW
                and reenters(d8, cells.member, e.cell),
                "area_km2": round(e.upstream_cells * cell_km2, 4),
                "share_of_polygon": round(e.upstream_cells / member_cells, 4),
                "boundary_cells": e.boundary_cells,
                "mean_slope_percent": (
                    round(float(slope_sum[number] / slope_count[number]), 3)
                    if slope_count[number]
                    else None
                ),
                "nmt_upstream_area_km2": round(float(cells.acc[e.cell]) * cell_km2, 4),
                "elevation_m": round(float(cells.dem[e.cell]), 2),
                "geometry": Point(x, y),
            }
        )
    significant = [r for r in rows if r["area_km2"] >= min_exit_km2]
    areas = _exit_areas(drained, cells.transform, significant)
    outlet_row = next(r for r in rows if r["is_export_outlet"])
    others = [r for r in rows if not r["is_export_outlet"]]
    received: dict[str, float] = {}
    for r in significant:
        received[r["destination"]] = received.get(r["destination"], 0.0) + r["area_km2"]
    largest = max(others, key=lambda r: r["area_km2"], default=None)
    upstream_km2 = float(cells.acc[outlet]) * cell_km2
    summary.update(
        {
            "outlet_upstream_area_km2": round(upstream_km2, 4),
            "polygon_to_upstream_area_ratio": (
                round(summary["polygon_area_km2"] / upstream_km2, 4)
                if upstream_km2 > 0
                else None
            ),
            "exit_count": len(rows),
            "exit_count_over_min": len(significant),
            "outlet_exit_km2": outlet_row["area_km2"],
            "outlet_destination": outlet_row["destination"],
            "other_exits_km2": round(sum(r["area_km2"] for r in others), 4),
            "reentering_km2": round(
                sum(r["area_km2"] for r in others if r["reenters_polygon"]), 4
            ),
            "pit_km2": round(sum(r["area_km2"] for r in rows if r["kind"] == PIT), 4),
            "nodata_km2": round(
                sum(r["area_km2"] for r in rows if r["kind"] == NODATA), 4
            ),
            "largest_other_exit_km2": largest["area_km2"] if largest else None,
            "largest_other_exit_to": largest["destination"] if largest else None,
            "receivers": "; ".join(
                f"{name}: {km2:.4f}"
                for name, km2 in sorted(received.items(), key=lambda kv: -kv[1])
            ),
        }
    )
    return rows, areas, summary


def _exit_areas(
    drained: np.ndarray, transform: Affine, exits: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Polygons of the cells that leave through the given exits."""
    numbers = [r["exit_id"] for r in exits]
    parts: dict[int, list[BaseGeometry]] = {n: [] for n in numbers}
    for geom, value in shapes(
        drained.astype(np.int32),
        mask=np.isin(drained, numbers),
        transform=transform,
    ):
        parts[int(value)].append(shape(geom))
    return [
        {
            "exit_id": r["exit_id"],
            "destination": r["destination"],
            "is_export_outlet": r["is_export_outlet"],
            "area_km2": r["area_km2"],
            "geometry": unary_union(parts[r["exit_id"]]),
        }
        for r in exits
    ]


def diagnose(
    input_path: Path,
    layer: str | None,
    key: str,
    ids: Sequence[str],
    output: Path,
    csv_path: Path,
    dem_dir: Path,
    min_exit_km2: float,
) -> int:
    """Write the exits of the polygons and their summary.

    Parameters
    ----------
    input_path, layer, key
        The polygons (read_polygons); every polygon of the layer can receive.
    ids : Sequence[str]
        Keys of the polygons to diagnose; empty for all.
    output : Path
        New GeoPackage: the layers EXITS_LAYER (points), AREAS_LAYER (polygons) and
        SUMMARY_LAYER (a table).
    csv_path : Path
        New CSV of the summary.
    dem_dir : Path
        Directory of the rasters of the pipeline.
    min_exit_km2 : float
        Smallest exit of the areas, the counts and the receivers of the summary
        [km²].

    Returns
    -------
    int
        Number of polygons diagnosed.

    Raises
    ------
    FileNotFoundError
        When a raster is missing.
    ValueError
        When an output exists, the input is refused, a key is not in the layer, or
        the rasters are not on one grid in PL-1992.
    """
    for path in (output, csv_path):
        if path.exists():
            raise ValueError(f"{path} exists; remove it or choose another path")
    polygons = read_polygons(input_path, layer, key, []).reset_index(drop=True)
    polygons[key] = polygons[key].astype(str)
    if ids:
        unknown = sorted(set(ids) - set(polygons[key]))
        if unknown:
            raise ValueError(f"{key} not in {input_path}: {', '.join(unknown)}")
        chosen = polygons[polygons[key].isin(set(ids))]
    else:
        chosen = polygons

    exit_rows: list[dict[str, Any]] = []
    area_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    with open_rasters(dem_dir, PANEL_THRESHOLD_M2) as rasters:
        for i, (value, geometry) in enumerate(
            zip(chosen[key], chosen.geometry, strict=True), start=1
        ):
            t0 = time.perf_counter()
            rows, areas, summary = diagnose_polygon(
                geometry, rasters, polygons, key, min_exit_km2
            )
            exit_rows.extend({key: value, **row} for row in rows)
            area_rows.extend({key: value, **row} for row in areas)
            summaries.append({key: value, **summary})
            logger.info(
                "%d/%d %s=%s: %d exits, %s of %s km2 through the outlet (%.1f s)",
                i,
                len(chosen),
                key,
                value,
                summary.get("exit_count", 0),
                summary.get("outlet_exit_km2"),
                summary["cell_area_km2"],
                time.perf_counter() - t0,
            )

    metadata = {
        "hydrograf_version": get_version(),
        "source": f"{input_path} ({layer or 'only layer'})",
        "dem_dir": str(dem_dir),
        "min_exit_km2": str(min_exit_km2),
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    exits = gpd.GeoDataFrame(exit_rows, geometry="geometry", crs=CRS_PL1992)
    exit_areas = gpd.GeoDataFrame(area_rows, geometry="geometry", crs=CRS_PL1992)
    table = pd.DataFrame(summaries)
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / output.name
        exits.to_file(local, layer=EXITS_LAYER, driver="GPKG", metadata=metadata)
        exit_areas.to_file(local, layer=AREAS_LAYER, driver="GPKG")
        gpd.GeoDataFrame(table).to_file(local, layer=SUMMARY_LAYER, driver="GPKG")
        shutil.copyfile(local, output)
    table.to_csv(csv_path, index=False)
    return len(summaries)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the diagnosis."""
    parser = argparse.ArgumentParser(
        description="Find where the NMT flow leaves given catchment polygons"
    )
    parser.add_argument("--input", required=True, help="GeoPackage of the polygons")
    parser.add_argument(
        "--layer", default=None, help="Layer of the polygons (default: the only one)"
    )
    parser.add_argument(
        "--key", required=True, help="Field with a unique value per polygon"
    )
    parser.add_argument(
        "--ids", default="", help="Comma-separated keys to diagnose (default: all)"
    )
    parser.add_argument("--output", required=True, help="New GeoPackage")
    parser.add_argument(
        "--csv", default=None, help="New CSV of the summary (default: OUTPUT.csv)"
    )
    parser.add_argument(
        "--min-exit-km2",
        type=float,
        default=DEFAULT_MIN_EXIT_KM2,
        help=(
            "Smallest exit counted in exit_count_over_min and the receivers of the "
            f"summary [km²] (default: {DEFAULT_MIN_EXIT_KM2})"
        ),
    )
    parser.add_argument(
        "--dem-dir",
        default=None,
        help="Directory of the rasters of the pipeline (default: DEM_DIR)",
    )
    args = parser.parse_args(argv)

    output = Path(args.output)
    t0 = time.time()
    try:
        count = diagnose(
            Path(args.input),
            args.layer,
            args.key,
            [value for value in args.ids.split(",") if value],
            output,
            Path(args.csv) if args.csv else output.with_suffix(".csv"),
            Path(args.dem_dir or get_settings().dem_dir),
            args.min_exit_km2,
        )
    except (FileNotFoundError, ValueError) as e:
        logger.error("%s", e)
        sys.exit(1)
    logger.info("%d polygons written to %s in %.1f s", count, output, time.time() - t0)


if __name__ == "__main__":
    main()
