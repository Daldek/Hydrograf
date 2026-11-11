"""
Parameters of a watershed measured from its cells on the saved rasters of the pipeline.

The rasters that a run of process_dem saved (INTERMEDIATE_SUFFIXES and the labels of
the sub-catchments) are read in a window (read_cell_window, read_cells); the measures
take the window and the mask of the cells measured (CellWindow.member) and give what
the panel „Zlewnia” shows: the area, elevations and mean slope of process_dem's
sub-catchment statistics (terrain, terrain_of), the longest flow path, its slope and
overland segment and the flow path from the divide (flow_path_parameters), and the
main channel with its BDOT10k part and slope (main_channel, channel_measures,
channel_parameters). The export of catchment parameters
(scripts/export_catchment_parameters.py) measures a polygon with them and the network
delineation (core.network_delineation) each of its elements; process_dem and the
backfill of the flow path heads measure the overland segments of the sub-catchments
with overland_segments, a walk along the D8 directions that needs no pyflwdir object.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numba
import numpy as np
from rasterio.transform import Affine
from rasterio.windows import Window
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.catchment_graph import contiguous_real_length_km
from core.constants import M2_PER_KM2, M_PER_KM
from core.divide_flow_path import (
    WatershedFlowPaths,
    trace_flow_path,
    watershed_flow_paths,
)
from core.hydrology import D8_COL_OFFSET, D8_DIRECTIONS, D8_ROW_OFFSET, D8_VALID
from core.raster_io import cells_window, read_window
from core.zonal_stats import ZonalSummary, zonal_summary

# Hydrology rasters saved with save_intermediates that later runs read again
# (process_dem.load_hydrology_intermediates): name -> file suffix after the DEM's stem
INTERMEDIATE_SUFFIXES = {
    "filled_dem": "02_filled",
    "fdir": "03_flowdir",
    "acc": "04_flowacc",
    "flow_dist_m": "04b_stream_distance",
    "slope": "05_slope",
}

# pyflwdir's D8 code of a cell that routes no flow (its nodata)
D8_NO_FLOW = 247

# The flag and the lengths of segments that the catchment graph loads: the smoothed
# line of stream_network (_segment_length_km) and the cells (_stream_length_km)
_STREAM_SEGMENTS = text(
    "SELECT sn.segment_idx, COALESCE(sn.is_real_stream, false) AS is_real, "
    "COALESCE(sn.length_m, 0) AS line_length_m, sc.stream_length_km "
    "FROM stream_network sn LEFT JOIN stream_catchments sc "
    "ON sc.threshold_m2 = sn.threshold_m2 AND sc.segment_idx = sn.segment_idx "
    "WHERE sn.threshold_m2 = :threshold AND sn.segment_idx = ANY(:idxs)"
)


def d8_from_saved_flowdir(
    fdir: np.ndarray,
    flow_dist_m: np.ndarray,
    valid: np.ndarray,
) -> np.ndarray:
    """Rebuild the pyflwdir D8 grid of a run from its saved rasters.

    The saved flow directions (``_03_flowdir``) are pyflwdir's D8 grid; in the
    rasters of runs before fix_internal_sinks stopped fixing the pits at the
    edge of the data, it had given those pits a direction. Those pits are the
    only cells with a flow distance of 0, so they become pits again (a no-op for
    newer runs); cells outside the DEM become pyflwdir's nodata (247).

    Parameters
    ----------
    fdir : np.ndarray
        Saved D8 flow directions (int16, 0 = none).
    flow_dist_m : np.ndarray
        Saved flow distance to the outlet [m].
    valid : np.ndarray
        Cells of the DEM (bool).

    Returns
    -------
    np.ndarray
        pyflwdir D8 flow directions (uint8).
    """
    d8 = fdir.astype(np.uint8)
    # One mask at a time beside the grid: these windows can hold tens of millions of
    # cells
    cells = flow_dist_m == 0
    cells &= valid
    d8[cells] = 0
    np.logical_not(valid, out=cells)
    d8[cells] = D8_NO_FLOW
    return d8


@dataclass(frozen=True)
class PipelineRasters:
    """Rasters that a run of process_dem saved, open on one grid.

    Attributes
    ----------
    filled_dem, slope, acc, fdir, flow_dist, labels : rasterio.DatasetReader
        ``dem_mosaic_02_filled``, ``_05_slope``, ``_04_flowacc``, ``_03_flowdir``,
        ``_04b_stream_distance`` and ``_10_subcatchments_<threshold_m2>``.
    threshold_m2 : int
        Flow accumulation threshold of the stream network [m²].
    """

    filled_dem: Any
    slope: Any
    acc: Any
    fdir: Any
    flow_dist: Any
    labels: Any
    threshold_m2: int

    @property
    def cellsize_m(self) -> float:
        """Side of a cell [m]."""
        return float(abs(self.filled_dem.transform.a))

    @property
    def threshold_cells(self) -> int:
        """The threshold in cells, as process_dem counts it."""
        return max(1, int(self.threshold_m2 / self.cellsize_m**2))


@dataclass(frozen=True)
class CellWindow:
    """The rasters of the pipeline in a window, and the cells measured in it.

    Attributes
    ----------
    dem, acc, fdir, flow_dist : np.ndarray
        The window of each raster; cells beyond a raster hold its nodata.
    slope, labels : np.ndarray or None
        The windows of the slope and of the labels, None where they are not kept:
        the network delineation reads the slope only for the statistics of all its
        elements at once and keeps the labels of the stream cells only, for the
        channels (core.network_delineation).
    dem_nodata, flow_dist_nodata : float | None
        Nodata of the filled DEM and of the flow distances.
    transform : Affine
        Transform of the window.
    valid : np.ndarray
        Cells with NMT data.
    member : np.ndarray
        The cells measured, a subset of ``valid``: those of a polygon, or those
        that drain to an outlet.
    """

    dem: np.ndarray
    slope: np.ndarray | None
    acc: np.ndarray
    fdir: np.ndarray
    flow_dist: np.ndarray
    labels: np.ndarray | None
    dem_nodata: float | None
    flow_dist_nodata: float | None
    transform: Affine
    valid: np.ndarray
    member: np.ndarray


def read_cell_window(
    rasters: PipelineRasters, bounds: tuple[float, float, float, float]
) -> CellWindow:
    """Read the rasters around a bounding box: its cells and one cell more.

    The cell below an outlet on the edge of ``bounds`` and the cells next to it
    are in the window, as the flow paths and the main channel need them.

    Parameters
    ----------
    rasters : PipelineRasters
        Open rasters.
    bounds : tuple[float, float, float, float]
        (minx, miny, maxx, maxy) in EPSG:2180.

    Returns
    -------
    CellWindow
        The windows; ``member`` holds every cell with NMT data.
    """
    return read_cells(rasters, cells_window(rasters.filled_dem.transform, bounds))


def read_cells(
    rasters: PipelineRasters, window: Window, *, slope: bool = True
) -> CellWindow:
    """Read the rasters in a window of whole cells (it may reach beyond them).

    Parameters
    ----------
    rasters : PipelineRasters
        Open rasters.
    window : Window
        Rows and columns of the rasters.
    slope : bool
        Read the slope too; without it ``CellWindow.slope`` is None.

    Returns
    -------
    CellWindow
        The windows; ``member`` holds every cell with NMT data.
    """
    dem = read_window(rasters.filled_dem, window)
    flow_dist = read_window(rasters.flow_dist, window)
    valid = (
        np.ones(dem.data.shape, dtype=bool)
        if dem.nodata is None
        else dem.data != dem.nodata
    )
    return CellWindow(
        dem=dem.data,
        slope=read_window(rasters.slope, window).data if slope else None,
        acc=read_window(rasters.acc, window).data,
        fdir=read_window(rasters.fdir, window).data,
        flow_dist=flow_dist.data,
        labels=read_window(rasters.labels, window).data,
        dem_nodata=dem.nodata,
        flow_dist_nodata=flow_dist.nodata,
        transform=dem.transform,
        valid=valid,
        member=valid,
    )


def terrain(cells: CellWindow, cellsize_m: float) -> tuple[dict[str, Any], float]:
    """Area, elevations and mean slope of the cells, and the area for the indices.

    The statistics of process_dem's sub-catchments (polygonize_subcatchments), with
    the cells measured as the only label.

    Raises
    ------
    ValueError
        When the window holds no slope.
    """
    if cells.slope is None:
        raise ValueError("The window holds no slope")
    summary = zonal_summary(
        cells.member.astype(np.int32),
        cells.dem,
        cells.slope,
        cells.dem_nodata if cells.dem_nodata is not None else np.nan,
    )
    return terrain_of(summary, 1, cellsize_m)


def terrain_of(
    summary: ZonalSummary, label: int, cellsize_m: float
) -> tuple[dict[str, Any], float]:
    """Area, elevations and mean slope of one label of a zonal summary.

    Parameters
    ----------
    summary : ZonalSummary
        Statistics of the labels of the cells measured (``zonal_summary`` of the
        filled DEM and the slope).
    label : int
        The label.
    cellsize_m : float
        Side of a cell [m].

    Returns
    -------
    tuple[dict[str, Any], float]
        ``area_km2`` (to 4 decimals), ``elevation_min_m``, ``elevation_max_m``,
        ``elevation_mean_m`` and ``mean_slope_m_per_m``; and the area exact to the
        cell [km², 6 decimals].
    """
    count = int(summary.count[label])
    elev_count = int(summary.elev_count[label])
    area_km2 = round(count * (cellsize_m * cellsize_m / M2_PER_KM2), 6)
    return {
        "area_km2": round(area_km2, 4),
        "elevation_min_m": round(float(summary.elev_min_m[label]), 2),
        "elevation_max_m": round(float(summary.elev_max_m[label]), 2),
        "elevation_mean_m": round(float(summary.elev_sum_m[label] / elev_count), 2),
        "mean_slope_m_per_m": round(
            float(summary.slope_sum_percent[label] / count) / 100.0, 6
        ),
    }, area_km2


def outlet_cell(cells: CellWindow) -> tuple[int, int]:
    """Cell measured with the largest flow accumulation (the first of equal)."""
    flat = int(np.argmax(np.where(cells.member, cells.acc, -1)))
    row, col = np.unravel_index(flat, cells.member.shape)
    return int(row), int(col)


def baseline_m(cells: CellWindow, outlet: tuple[int, int]) -> float:
    """Flow distance at the outlet of the cells measured [m].

    The catchment graph measures a watershed from the first cell below its
    outlet cell (the end of the outlet sub-catchment's longest flow path), from
    the outlet cell itself where the flow ends there (a pit, the edge of the data).
    """
    end = trace_flow_path(outlet, cells.member, cells.fdir, cells.flow_dist)[-1]
    if (
        end != outlet
        and cells.valid[end]
        and cells.flow_dist[end] != cells.flow_dist_nodata
    ):
        return float(cells.flow_dist[end])
    return float(cells.flow_dist[outlet])


def flow_path_parameters(
    cells: CellWindow, d8: np.ndarray, outlet: tuple[int, int], threshold_cells: int
) -> tuple[dict[str, Any], WatershedFlowPaths]:
    """Longest flow path, its slope and overland segment, and the divide path.

    Parameters
    ----------
    cells : CellWindow
        The window; ``member`` holds the cells that drain to ``outlet``, where the
        flow paths start.
    d8 : np.ndarray
        pyflwdir D8 grid of the window (d8_from_saved_flowdir) with ``outlet`` a
        pit, so the overland segment ends there.
    outlet : tuple[int, int]
        Outlet cell.
    threshold_cells : int
        Threshold of the stream network that ends the overland segment [cells].

    Returns
    -------
    tuple[dict[str, Any], WatershedFlowPaths]
        ``flow_path_length_km``, ``flow_path_slope_m_per_m``,
        ``overland_length_km``, ``overland_slope_m_per_m`` and
        ``divide_flow_path_km``, None where they cannot be measured; and the lines
        of the longest flow path and of the divide path.
    """
    paths = watershed_flow_paths(
        cells.member,
        cells.flow_dist,
        cells.fdir,
        cells.flow_dist_nodata,
        baseline_m(cells, outlet),
        cells.transform,
    )
    result: dict[str, Any] = {
        "flow_path_length_km": None,
        "flow_path_slope_m_per_m": None,
        "overland_length_km": None,
        "overland_slope_m_per_m": None,
        "divide_flow_path_km": (
            paths.divide.length_km if paths.divide is not None else None
        ),
    }
    if paths.longest is None:
        return result, paths
    length_km = paths.longest.length_km
    result["flow_path_length_km"] = length_km
    col, row = ~cells.transform * paths.longest.coords_2180[0]
    head = (math.floor(row), math.floor(col))
    slope = (_elevation(cells, head) - _elevation(cells, outlet)) / (length_km * 1000)
    if slope > 0:
        result["flow_path_slope_m_per_m"] = round(slope, 6)
    stream = cells.acc >= threshold_cells
    stream &= cells.valid
    lengths, drops = overland_segments(
        np.array([np.ravel_multi_index(head, d8.shape)], dtype=np.intp),
        stream,
        cells.dem,
        cells.transform,
        d8=d8,
    )
    overland_m, drop_m = lengths[0], drops[0]
    if overland_m is not None and overland_m > 0:
        result["overland_length_km"] = round(overland_m / M_PER_KM, 4)
        if drop_m is not None and drop_m > 0:
            result["overland_slope_m_per_m"] = round(drop_m / overland_m, 6)
    return result, paths


def overland_segments(
    head_idxs: np.ndarray,
    stream_mask: np.ndarray,
    dem: np.ndarray,
    transform: Affine,
    *,
    d8: np.ndarray | None = None,
    idxs_ds: np.ndarray | None = None,
) -> tuple[list[float | None], list[float | None]]:
    """Measure the overland segment of flow paths, from their heads to the streams.

    The segment runs along the flow directions from a head cell to the first
    cell of the stream mask, as pyflwdir's ``FlwdirRaster.path`` with that mask
    runs. It is not measurable (None) when the head is a stream cell or the path
    ends in a pit before it reaches a stream. The flow directions are a D8 grid
    (the saved rasters, d8_from_saved_flowdir) or the downstream indices of a
    run (``idxs_ds`` of its pyflwdir.FlwdirRaster or its UnitFlowPaths).

    Parameters
    ----------
    head_idxs : np.ndarray
        Flat indices of the head cells.
    stream_mask : np.ndarray
        2-D stream mask of the threshold (bool).
    dem : np.ndarray
        Filled DEM on the grid of ``stream_mask``, flattened or not: it is read at
        the flat indices of the cells, without a copy of a window.
    transform : Affine
        Transform of the grid, whose cell sides measure the steps.
    d8 : np.ndarray, optional
        pyflwdir D8 grid (uint8: 0 at a pit, 247 where no flow is routed); a cell
        that drains off the grid or into a cell of 247 is a pit.
    idxs_ds : np.ndarray, optional
        Flat index of the cell below each cell: the cell itself at a pit,
        negative where no flow is routed.

    Returns
    -------
    tuple[list[float | None], list[float | None]]
        Length [m] and drop [m] of the segment of each head.

    Raises
    ------
    ValueError
        Unless exactly one of ``d8`` and ``idxs_ds`` is given.
    """
    if (d8 is None) == (idxs_ds is None):
        raise ValueError("overland_segments takes either d8 or idxs_ds")
    stream = np.ascontiguousarray(stream_mask).ravel()
    dists, ends = _walk_to_stream(
        np.ascontiguousarray(head_idxs, dtype=np.int64),
        np.empty(0, np.uint8) if d8 is None else np.ascontiguousarray(d8).ravel(),
        np.empty(0, np.int64) if idxs_ds is None else idxs_ds,
        stream,
        stream_mask.shape[1],
        float(transform.a),
        float(transform.e),
        D8_VALID,
        D8_ROW_OFFSET,
        D8_COL_OFFSET,
    )
    lengths: list[float | None] = []
    drops: list[float | None] = []
    for head, dist, end in zip(head_idxs, dists, ends, strict=True):
        if end < 0:
            lengths.append(None)
            drops.append(None)
            continue
        lengths.append(round(float(dist), 1))
        drops.append(round(float(dem.flat[head]) - float(dem.flat[end]), 2))
    return lengths, drops


@numba.njit(cache=True)
def _walk_to_stream(
    heads: np.ndarray,
    d8: np.ndarray,
    idxs_ds: np.ndarray,
    stream: np.ndarray,
    ncols: int,
    xres: float,
    yres: float,
    d8_valid: np.ndarray,
    d8_row: np.ndarray,
    d8_col: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Walk down from each head to the first stream cell (overland_segments).

    Follows ``d8`` or, when it is empty, ``idxs_ds``. Returns the distance
    walked [m] and the stream cell reached, -1 where the head is a stream cell
    or the walk ends in a pit. A step measures as pyflwdir's
    ``gis_utils.distance`` does, so the distances are those of
    ``FlwdirRaster.path``.
    """
    size = stream.size
    nrows = size // ncols
    dists = np.zeros(heads.size, dtype=np.float64)
    ends = np.full(heads.size, -1, dtype=np.int64)
    for i in range(heads.size):
        idx = heads[i]
        dist = 0.0
        for _ in range(size):
            if stream[idx]:
                break
            if d8.size:
                down = _d8_receiver(idx, d8, nrows, ncols, d8_valid, d8_row, d8_col)
            else:
                down = idxs_ds[idx]
                if down == idx:
                    down = -1
            if down < 0:
                break
            drow = abs(down // ncols - idx // ncols)
            dcol = abs(down % ncols - idx % ncols)
            dist += math.hypot(xres * drow, yres * dcol)
            idx = down
        if idx != heads[i] and stream[idx]:
            dists[i] = dist
            ends[i] = idx
    return dists, ends


@numba.njit(cache=True)
def _d8_receiver(
    idx: int,
    d8: np.ndarray,
    nrows: int,
    ncols: int,
    d8_valid: np.ndarray,
    d8_row: np.ndarray,
    d8_col: np.ndarray,
) -> int:
    """Cell below ``idx`` on a pyflwdir D8 grid, -1 at a pit or without flow."""
    code = d8[idx]
    if not d8_valid[code]:
        return -1
    row = idx // ncols + d8_row[code]
    col = idx % ncols + d8_col[code]
    if row < 0 or row >= nrows or col < 0 or col >= ncols:
        return -1
    down = int(row * ncols + col)
    if d8[down] == D8_NO_FLOW:
        return -1
    return down


def _elevation(cells: CellWindow, cell: tuple[int, int]) -> float:
    """Return the filled DEM at a cell, to the 0.01 m of the sub-catchment stats."""
    return round(float(cells.dem[cell]), 2)


def _downstream(cells: CellWindow, cell: tuple[int, int]) -> tuple[int, int] | None:
    """Cell that a cell drains into, None at a pit or beyond the data."""
    offset = D8_DIRECTIONS.get(int(cells.fdir[cell]))
    if offset is None:
        return None
    row, col = cell[0] + offset[0], cell[1] + offset[1]
    nrows, ncols = cells.valid.shape
    if not (0 <= row < nrows and 0 <= col < ncols) or not cells.valid[row, col]:
        return None
    return row, col


def main_channel(
    cells: CellWindow, outlet: tuple[int, int], stream: np.ndarray
) -> list[tuple[int, int]]:
    """Cells of the main channel of the cells measured, from the outlet up.

    From each cell the channel goes up into the stream cell that drains into it
    with the largest flow accumulation: at a confluence the branch of the larger
    upstream area, as CatchmentGraph.trace_main_channel chooses among the
    sub-catchments. It follows the stream network out of the cells measured and
    back (a stream along a boundary that does not follow the NMT) and ends at its
    last cell among them: its source, or where it flows in from outside.

    Parameters
    ----------
    cells : CellWindow
        The window and the cells measured.
    outlet : tuple[int, int]
        Outlet cell.
    stream : np.ndarray
        Cells of the stream network of the threshold.

    Returns
    -------
    list[tuple[int, int]]
        The cells, outlet first; empty when the outlet is not a stream cell.
    """
    if not stream[outlet]:
        return []
    nrows, ncols = stream.shape
    path = [outlet]
    row, col = outlet
    for _ in range(int(np.count_nonzero(stream))):
        best: tuple[int, int] | None = None
        for code, (drow, dcol) in D8_DIRECTIONS.items():
            r, c = row - drow, col - dcol
            if (
                0 <= r < nrows
                and 0 <= c < ncols
                and cells.fdir[r, c] == code
                and stream[r, c]
                and (best is None or cells.acc[r, c] > cells.acc[best])
            ):
                best = (r, c)
        if best is None:
            break
        path.append(best)
        row, col = best
    last = max(i for i, cell in enumerate(path) if cells.member[cell])
    return path[: last + 1]


def channel_parameters(
    cells: CellWindow,
    outlet: tuple[int, int],
    rasters: PipelineRasters,
    db: Session,
) -> dict[str, Any]:
    """Length, BDOT10k length and slope of the main channel (main_channel).

    Returns
    -------
    dict[str, Any]
        As channel_measures.

    Raises
    ------
    ValueError
        When the window holds no labels.
    """
    if cells.labels is None:
        raise ValueError("The window holds no labels")
    stream = (cells.acc >= rasters.threshold_cells) & cells.valid
    path = main_channel(cells, outlet, stream)
    labels = [int(cells.labels[cell]) for cell in path]
    return channel_measures(cells, path, labels, rasters, db)


def channel_measures(
    cells: CellWindow,
    path: list[tuple[int, int]],
    labels: Sequence[int],
    rasters: PipelineRasters,
    db: Session,
) -> dict[str, Any]:
    """Length, BDOT10k length and slope of a main channel.

    A segment of the stream network has the length from each of its cells to the
    next one, the last to the first cell of the segment below it, rounded to
    0.1 m (stream_extraction.vectorize_streams) and kept in km to 4 decimals in
    stream_catchments; the segment of a cell is its label. A segment that the
    channel follows in part counts that part. The BDOT10k length takes each
    segment along its smoothed line of stream_network, as the catchment graph
    does, a part of a segment in proportion.

    Parameters
    ----------
    cells : CellWindow
        The window.
    path : list[tuple[int, int]]
        Cells of the channel, its outlet first (main_channel).
    labels : Sequence[int]
        The label of each cell of ``path``: its segment.
    rasters : PipelineRasters
        Open rasters: the threshold of the labels and the cell size.
    db : Session
        Database session (the BDOT10k flags of ``stream_network``).

    Returns
    -------
    dict[str, Any]
        ``channel_length_km``, ``real_channel_length_km`` and
        ``channel_slope_m_per_m``; None where they cannot be measured.
    """
    result: dict[str, Any] = {
        "channel_length_km": None,
        "real_channel_length_km": None,
        "channel_slope_m_per_m": None,
    }
    if not path:
        return result
    outlet = path[0]
    segment_idxs: list[int] = []  # from the outlet up
    raw_lengths_m: list[float] = []
    for i, (cell, label) in enumerate(zip(path, labels, strict=True)):
        below = path[i - 1] if i else _downstream(cells, outlet)
        step_m = 0.0
        if below is not None:
            diagonal = below[0] != cell[0] and below[1] != cell[1]
            step_m = rasters.cellsize_m * (math.sqrt(2.0) if diagonal else 1.0)
        if segment_idxs and segment_idxs[-1] == label:
            raw_lengths_m[-1] += step_m
        else:
            segment_idxs.append(label)
            raw_lengths_m.append(step_m)
    lengths_m = [round(length, 1) for length in raw_lengths_m]
    length_km = sum(round(length / M_PER_KM, 4) for length in lengths_m)
    if length_km <= 0:
        return result
    result["channel_length_km"] = round(length_km, 4)
    drop_m = _elevation(cells, path[-1]) - _elevation(cells, outlet)
    slope = drop_m / (length_km * 1000)
    if slope > 0:
        result["channel_slope_m_per_m"] = round(slope, 6)
    segments = {
        int(r.segment_idx): r
        for r in db.execute(
            _STREAM_SEGMENTS,
            {"threshold": rasters.threshold_m2, "idxs": segment_idxs},
        ).fetchall()
    }
    real: list[bool] = []
    line_lengths_km: list[float] = []
    for idx, length_m in zip(segment_idxs, lengths_m, strict=True):
        segment = segments.get(idx)
        real.append(segment is not None and bool(segment.is_real))
        line_km = length_m / M_PER_KM
        if segment is not None and segment.stream_length_km:
            line_km *= (segment.line_length_m or 0.0) / (
                segment.stream_length_km * M_PER_KM
            )
        line_lengths_km.append(line_km)
    result["real_channel_length_km"] = round(
        contiguous_real_length_km(real, line_lengths_km), 4
    )
    return result
