"""Longest flow paths of a watershed: from its farthest cell and its boundary.

The watershed is the union of its sub-catchments: the cells of the label raster
of their threshold (``<stem>_10_subcatchments_<threshold>.tif``) whose label is
one of their ``segment_idx``. Its boundary cells are the cells of the watershed
with a 4-neighbour outside it (another label, no label or beyond the raster).
The longest flow path starts at the cell of the watershed farthest from the
outlet along the flow (``<stem>_04b_stream_distance.tif``), the divide flow
path at its farthest boundary cell. Both follow the D8 flow directions
(``<stem>_03_flowdir.tif``) to the first cell outside the watershed, where the
longest flow path of the outlet sub-catchment ends too. D8 paths coincide
downstream of their first common cell, so the line of the divide flow path
ends there, and there is none when both start at the same cell.

The length of a path is the flow distance of its first cell minus the flow
distance at the outlet of the watershed, the baseline of the longest flow path.
The pipeline took the ``max_flow_dist_m`` of every sub-catchment from the same
distance grid the raster stores (float32 in both), so the longest flow path has
the length of ``hydraulic_length_km`` and a boundary cell is never farther.

The line of a path joins the centres of its cells, as the lines of
``stream_network`` (``core.stream_extraction``), without the cells inside its
straight runs, so it lies on the streams where it follows them.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.windows import Window, from_bounds
from rasterio.windows import transform as window_transform

from core.hydrology import D8_DIRECTIONS

logger = logging.getLogger(__name__)

# Cells added to a side of the reading window while the watershed reaches it.
_MIN_GROWTH_CELLS = 64


@dataclass(frozen=True)
class FlowPath:
    """A flow path from a cell of a watershed to its outlet.

    Attributes
    ----------
    length_km : float
        Flow distance from the first cell to the outlet [km].
    own_length_km : float
        Flow distance from the first cell to the last cell of the line [km];
        less than ``length_km`` when the line stops where it joins the
        longest flow path.
    coords_2180 : list[tuple[float, float]]
        Cell centres in EPSG:2180, from the first cell to the end of the line,
        where the flow direction changes (and both ends).
    """

    length_km: float
    own_length_km: float
    coords_2180: list[tuple[float, float]]


@dataclass(frozen=True)
class WatershedFlowPaths:
    """The longest flow path of a watershed and the one from its boundary.

    Attributes
    ----------
    longest : FlowPath | None
        From the cell of the watershed farthest from the outlet.
    divide : FlowPath | None
        From the boundary cell of the watershed farthest from the outlet to
        its first cell on the longest path; None when it is the longest path.
    divide_is_longest : bool
        The farthest boundary cell is the head of the longest path.
    """

    longest: FlowPath | None
    divide: FlowPath | None
    divide_is_longest: bool = False


NO_FLOW_PATHS = WatershedFlowPaths(longest=None, divide=None)


def boundary_mask(member: np.ndarray) -> np.ndarray:
    """Cells of ``member`` with a 4-neighbour outside it or beyond the array.

    Parameters
    ----------
    member : np.ndarray
        Cells of the watershed (bool, 2-D).

    Returns
    -------
    np.ndarray
        Boundary cells of the watershed (bool, same shape).
    """
    padded = np.pad(member, 1, constant_values=False)
    interior: np.ndarray = (
        padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    )
    boundary: np.ndarray = member & ~interior
    return boundary


def trace_flow_path(
    start: tuple[int, int],
    member: np.ndarray,
    fdir: np.ndarray,
    flow_dist: np.ndarray,
) -> list[tuple[int, int]]:
    """Follow the D8 flow directions from ``start`` out of the watershed.

    The path ends at the first cell outside ``member``, at a pit or where the
    flow leaves the array. Pits are cells without a D8 direction and the cells
    with a flow distance of 0, the pits that the directions saved by earlier runs
    drain but pyflwdir's grid of the distances does not (as
    ``core.cell_parameters.d8_from_saved_flowdir``).

    Parameters
    ----------
    start : tuple[int, int]
        Row and column of the first cell.
    member : np.ndarray
        Cells of the watershed (bool, 2-D).
    fdir : np.ndarray
        D8 flow directions (1 = E ... 128 = NE, 0 = none).
    flow_dist : np.ndarray
        Flow distance to the outlet of the grid [m].

    Returns
    -------
    list[tuple[int, int]]
        Rows and columns of the path, ``start`` first.
    """
    nrows, ncols = member.shape
    row, col = start
    path = [(row, col)]
    for _ in range(member.size):
        offset = D8_DIRECTIONS.get(int(fdir[row, col]))
        if offset is None or flow_dist[row, col] == 0:
            break
        row, col = row + offset[0], col + offset[1]
        if not (0 <= row < nrows and 0 <= col < ncols):
            break
        path.append((row, col))
        if not member[row, col]:
            break
    return path


def _window(
    src: rasterio.DatasetReader,
    bounds: tuple[float, float, float, float],
) -> Window:
    """Window of whole cells covering ``bounds`` plus one cell, within the raster."""
    win = from_bounds(*bounds, transform=src.transform)
    col0 = int(np.floor(win.col_off)) - 1
    row0 = int(np.floor(win.row_off)) - 1
    col1 = int(np.ceil(win.col_off + win.width)) + 1
    row1 = int(np.ceil(win.row_off + win.height)) + 1
    return _clamped(src, row0, col0, row1, col1)


def _clamped(
    src: rasterio.DatasetReader, row0: int, col0: int, row1: int, col1: int
) -> Window:
    row0, col0 = max(row0, 0), max(col0, 0)
    row1, col1 = min(row1, src.height), min(col1, src.width)
    return Window(col0, row0, max(col1 - col0, 0), max(row1 - row0, 0))


def _read_members(
    src: rasterio.DatasetReader,
    labels: np.ndarray,
    bounds: tuple[float, float, float, float],
) -> tuple[Window, np.ndarray]:
    """Read the cells of ``labels``, growing the window until it holds them all.

    The watershed is D8-connected, so it lies inside the window once no
    side of it within the raster has a cell of the watershed.
    """
    win = _window(src, bounds)
    while True:
        member = np.isin(src.read(1, window=win), labels)
        row0, col0 = int(win.row_off), int(win.col_off)
        row1, col1 = row0 + int(win.height), col0 + int(win.width)
        grow = (
            max(_MIN_GROWTH_CELLS, int(win.height) // 2),
            max(_MIN_GROWTH_CELLS, int(win.width) // 2),
        )
        new = (
            row0 - grow[0] if row0 > 0 and member[0, :].any() else row0,
            col0 - grow[1] if col0 > 0 and member[:, 0].any() else col0,
            row1 + grow[0] if row1 < src.height and member[-1, :].any() else row1,
            col1 + grow[1] if col1 < src.width and member[:, -1].any() else col1,
        )
        if new == (row0, col0, row1, col1):
            return win, member
        win = _clamped(src, *new)


def path_coords(
    cells: Sequence[tuple[int, int]], transform: Affine
) -> list[tuple[float, float]]:
    """Centres of the cells of a path where its direction changes, and its ends.

    The dropped cells lie on the straight line between their neighbours, so
    the line is the one through all the centres (as ``stream_network``).

    Parameters
    ----------
    cells : Sequence[tuple[int, int]]
        Rows and columns of the path in the grid of ``transform``.
    transform : Affine
        Transform of the grid of ``cells`` (EPSG:2180).

    Returns
    -------
    list[tuple[float, float]]
        Coordinates in EPSG:2180, from the first cell to the last.
    """
    kept = list(cells[:1])
    for prev, cell, nxt in zip(cells, cells[1:], cells[2:], strict=False):
        step_in = (cell[0] - prev[0], cell[1] - prev[1])
        if step_in != (nxt[0] - cell[0], nxt[1] - cell[1]):
            kept.append(cell)
    kept.extend(cells[1:][-1:])
    coords = []
    for row, col in kept:
        x, y = transform * (col + 0.5, row + 0.5)
        coords.append((float(x), float(y)))
    return coords


def _farthest(starts: np.ndarray, flow_dist: np.ndarray) -> tuple[int, int] | None:
    """Cell of ``starts`` farthest from the outlet, None without one."""
    if not starts.any():
        return None
    row, col = np.unravel_index(
        int(np.argmax(np.where(starts, flow_dist, -np.inf))), starts.shape
    )
    return int(row), int(col)


def _flow_path(
    cells: Sequence[tuple[int, int]],
    flow_dist: np.ndarray,
    baseline_m: float,
    transform: Affine,
    own_end_m: float | None = None,
) -> FlowPath | None:
    """Flow path of ``cells``; None when its head is not upstream of the outlet.

    ``own_end_m`` is the flow distance of the last cell when ``cells`` is only
    the part of a path from its head (the default: ``baseline_m``).
    """
    head_m = float(flow_dist[cells[0]])
    length_m = head_m - baseline_m
    if length_m <= 0:
        return None
    own_m = length_m if own_end_m is None else head_m - own_end_m
    return FlowPath(
        length_km=round(length_m / 1000.0, 4),
        own_length_km=round(own_m / 1000.0, 4),
        coords_2180=path_coords(cells, transform),
    )


def compute_flow_paths(
    segment_idxs: Sequence[int],
    bounds_2180: tuple[float, float, float, float],
    baseline_m: float,
    labels_path: str,
    flow_dist_path: str,
    flowdir_path: str,
) -> WatershedFlowPaths:
    """Longest flow path of a watershed and the one from its boundary.

    Parameters
    ----------
    segment_idxs : Sequence[int]
        Labels of the sub-catchments of the watershed in ``labels_path``.
    bounds_2180 : tuple[float, float, float, float]
        Approximate extent of the watershed (minx, miny, maxx, maxy), EPSG:2180;
        the window grows until it covers all the cells of the watershed.
    baseline_m : float
        Flow distance at the outlet of the watershed [m], the baseline of its
        longest flow path.
    labels_path : str
        Label raster of the threshold of ``segment_idxs``.
    flow_dist_path : str
        Flow distance raster [m].
    flowdir_path : str
        Saved D8 flow directions of the pipeline (int16, 0 = none).

    Returns
    -------
    WatershedFlowPaths
        A path is None when the watershed has no cell in ``labels_path`` or
        the first cell of the path is not upstream of the outlet. The divide
        path is also None when it starts at the head of the longest path
        (``divide_is_longest``); otherwise its line ends at its first cell on
        the longest path, downstream of which D8 paths coincide.
    """
    labels = np.asarray(segment_idxs, dtype=np.int64)
    if labels.size == 0 or np.isnan(baseline_m):
        return NO_FLOW_PATHS
    with (
        rasterio.open(labels_path) as labels_src,
        rasterio.open(flow_dist_path) as dist_src,
        rasterio.open(flowdir_path) as fdir_src,
    ):
        grid = (labels_src.shape, labels_src.transform)
        if (dist_src.shape, dist_src.transform) != grid or (
            fdir_src.shape,
            fdir_src.transform,
        ) != grid:
            logger.warning(
                "Flow paths: %s, %s and %s are not on one grid",
                labels_path,
                flow_dist_path,
                flowdir_path,
            )
            return NO_FLOW_PATHS
        win, member = _read_members(labels_src, labels, bounds_2180)
        if not member.any():
            return NO_FLOW_PATHS
        flow_dist = dist_src.read(1, window=win)
        fdir = fdir_src.read(1, window=win)
        nodata = dist_src.nodata
        transform = window_transform(win, labels_src.transform)
    return watershed_flow_paths(member, flow_dist, fdir, nodata, baseline_m, transform)


def watershed_flow_paths(
    member: np.ndarray,
    flow_dist: np.ndarray,
    fdir: np.ndarray,
    nodata: float | None,
    baseline_m: float,
    transform: Affine,
) -> WatershedFlowPaths:
    """Longest flow path and the one from the boundary of the cells of a watershed.

    Parameters
    ----------
    member : np.ndarray
        Cells of the watershed (bool, 2-D), all upstream of its outlet.
    flow_dist : np.ndarray
        Flow distance to the outlet of the grid [m], on the grid of ``member``.
    fdir : np.ndarray
        Saved D8 flow directions of the pipeline (1 = E ... 128 = NE, 0 = none).
    nodata : float | None
        Nodata value of ``flow_dist``.
    baseline_m : float
        Flow distance at the outlet of the watershed [m].
    transform : Affine
        Transform of the grid of ``member`` (EPSG:2180).

    Returns
    -------
    WatershedFlowPaths
        As ``compute_flow_paths``.
    """
    starts = member if nodata is None else member & (flow_dist != nodata)
    longest_head = _farthest(starts, flow_dist)
    if longest_head is None:
        return NO_FLOW_PATHS
    longest_cells = trace_flow_path(longest_head, member, fdir, flow_dist)
    longest = _flow_path(longest_cells, flow_dist, baseline_m, transform)
    divide_head = _farthest(starts & boundary_mask(member), flow_dist)
    if divide_head is None:
        return WatershedFlowPaths(longest=longest, divide=None)
    if divide_head == longest_head:
        return WatershedFlowPaths(
            longest=longest, divide=None, divide_is_longest=longest is not None
        )
    divide_cells = trace_flow_path(divide_head, member, fdir, flow_dist)
    on_longest = set(longest_cells)
    meet = next((i for i, cell in enumerate(divide_cells) if cell in on_longest), None)
    if meet is None:
        divide = _flow_path(divide_cells, flow_dist, baseline_m, transform)
    else:
        divide = _flow_path(
            divide_cells[: meet + 1],
            flow_dist,
            baseline_m,
            transform,
            own_end_m=float(flow_dist[divide_cells[meet]]),
        )
    return WatershedFlowPaths(longest=longest, divide=divide)
