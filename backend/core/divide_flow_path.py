"""Longest flow path from the boundary of a watershed to its outlet.

The watershed is the union of its sub-catchments: the cells of the label raster
of their threshold (``<stem>_10_subcatchments_<threshold>.tif``) whose label is
one of their ``segment_idx``. Its boundary cells are the cells of the watershed
with a 4-neighbour outside it (another label, no label or beyond the raster).
The path starts at the boundary cell farthest from the outlet along the flow
(``<stem>_04b_stream_distance.tif``) and follows the D8 flow directions
(``<stem>_03_flowdir.tif``) to the first cell outside the watershed, where the
longest flow path of the outlet sub-catchment ends too.

Its length is the flow distance of that cell minus the flow distance at the
outlet of the watershed, the baseline of the longest flow path. The pipeline
took the ``max_flow_dist_m`` of every sub-catchment from the same distance grid
the raster stores (float32 in both), so a boundary cell is never farther than
the longest flow path.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import rasterio
from rasterio.windows import Window, from_bounds
from rasterio.windows import transform as window_transform
from shapely.geometry import LineString

from core.hydrology import D8_DIRECTIONS

logger = logging.getLogger(__name__)

# Cells added to a side of the reading window while the watershed reaches it.
_MIN_GROWTH_CELLS = 64


@dataclass(frozen=True)
class DivideFlowPath:
    """The flow path from the farthest boundary cell of a watershed.

    Attributes
    ----------
    length_km : float
        Flow distance from the boundary cell to the outlet [km].
    coords_2180 : list[tuple[float, float]]
        Cell centres in EPSG:2180, from the boundary cell to the outlet,
        simplified with the tolerance of the pipeline's flow paths.
    """

    length_km: float
    coords_2180: list[tuple[float, float]]


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
    with a flow distance of 0, the internal sinks that the saved directions
    drain but pyflwdir's grid of the distances does not (as
    ``process_dem.d8_from_saved_flowdir``).

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


def compute_divide_flow_path(
    segment_idxs: Sequence[int],
    bounds_2180: tuple[float, float, float, float],
    baseline_m: float,
    labels_path: str,
    flow_dist_path: str,
    flowdir_path: str,
) -> DivideFlowPath | None:
    """Flow path from the farthest boundary cell of a watershed to its outlet.

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
    DivideFlowPath | None
        None when the watershed has no cell in ``labels_path`` or its
        farthest boundary cell is not upstream of the outlet.
    """
    labels = np.asarray(segment_idxs, dtype=np.int64)
    if labels.size == 0 or np.isnan(baseline_m):
        return None
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
                "Divide flow path: %s, %s and %s are not on one grid",
                labels_path,
                flow_dist_path,
                flowdir_path,
            )
            return None
        win, member = _read_members(labels_src, labels, bounds_2180)
        if not member.any():
            return None
        flow_dist = dist_src.read(1, window=win)
        candidates = boundary_mask(member)
        if dist_src.nodata is not None:
            candidates &= flow_dist != dist_src.nodata
        if not candidates.any():
            return None
        head = np.unravel_index(
            int(np.argmax(np.where(candidates, flow_dist, -np.inf))), member.shape
        )
        length_m = float(flow_dist[head]) - baseline_m
        if length_m <= 0:
            return None
        fdir = fdir_src.read(1, window=win)
        cells = trace_flow_path((int(head[0]), int(head[1])), member, fdir, flow_dist)
        transform = window_transform(win, labels_src.transform)
        cellsize = abs(labels_src.transform.a)

    coords = [transform * (col + 0.5, row + 0.5) for row, col in cells]
    if len(coords) > 3:
        line = LineString(coords).simplify(2 * cellsize, preserve_topology=True)
        coords = list(line.coords)
    return DivideFlowPath(
        length_km=round(length_m / 1000.0, 4),
        coords_2180=[(float(x), float(y)) for x, y in coords],
    )
