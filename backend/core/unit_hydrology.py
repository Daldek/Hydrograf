"""Hydrology of the whole grid filled once, read by owner, routed on disk.

The depression fill and the D8 directions run once on the whole prepared DEM, with
the code of ``process_hydrology_pyflwdir`` (``fill_whole_grid``), and every owner
takes its cells from those rasters: the seams of two owners agree by construction,
and the result is that of the whole raster. A cycle in the owner graph is not a D8
cycle: the latter is detected explicitly. Global counts and outlet distances are
propagated on a disk-backed D8 topology, so no entire-area pyflwdir object is
created.

The cells of each owner can be saved as they are read (``UnitStage``, through a
``UnitCheckpoints``) and restored by a later call: the resumption of an interrupted
run, which fills the grid again only when an owner has no intact stage.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Protocol

import numba
import numpy as np
import rasterio
from pyflwdir.gis_utils import distance as _cell_distance
from rasterio.windows import Window
from scipy.ndimage import binary_dilation, find_objects

from core.hydrology import (
    D8_COL_OFFSET,
    D8_ROW_OFFSET,
    D8_VALID,
    HOLE_FILL_PASSES,
    fill_depressions_d8,
    fix_sinks_of_fill,
    recompute_flow_accumulation,
)
from core.morphometry_raster import compute_slope_from_gradients, gradient_strips
from core.raster_io import read_raster, save_raster_geotiff
from core.stream_extraction import compute_downstream_links, vectorize_streams

logger = logging.getLogger(__name__)

_STAGE_ARRAYS = ("cells", "filled", "fdir", "raw_fdir", "active")
# pyflwdir's D8 code of a cell it routes no flow through
_NO_FLOW = 247
# Rows of a strip of the slope
_STRIP_ROWS = 512


@dataclass(frozen=True)
class UnitStage:
    """The fill and D8 one owner wrote: its own cells and the repaired holes it took.

    Attributes
    ----------
    row, col : int
        Grid position of ``cells[0, 0]``.
    cells : np.ndarray
        bool, the cells the owner wrote, in the box of them.
    filled, fdir, raw_fdir, active : np.ndarray
        The values of those cells in row-major order: filled DEM (float32), D8 with
        the hole cells as routing cells (int16), pyflwdir D8 (int16) and whether
        the cell routes flow (bool).
    """

    row: int
    col: int
    cells: np.ndarray
    filled: np.ndarray
    fdir: np.ndarray
    raw_fdir: np.ndarray
    active: np.ndarray

    def save(self, path: Path) -> None:
        """Write the stage as an uncompressed ``.npz``, replacing ``path`` at once."""
        partial = path.with_name(f".{path.name}.partial")
        with partial.open("wb") as sink:
            np.savez(
                sink,
                origin=np.array([self.row, self.col], dtype=np.int64),
                **{name: getattr(self, name) for name in _STAGE_ARRAYS},
            )
            sink.flush()
            os.fsync(sink.fileno())
        os.replace(partial, path)

    @classmethod
    def load(cls, path: Path) -> UnitStage:
        """Read a stage written by :meth:`save`."""
        with np.load(path) as stored:
            row, col = (int(value) for value in stored["origin"])
            arrays = {name: stored[name] for name in _STAGE_ARRAYS}
        cells = int(np.count_nonzero(arrays["cells"]))
        if (
            arrays["cells"].ndim != 2
            or row < 0
            or col < 0
            or any(arrays[name].shape != (cells,) for name in _STAGE_ARRAYS[1:])
        ):
            raise ValueError(f"{path} is not a consistent unit stage")
        return cls(row, col, **arrays)


class UnitCheckpoints(Protocol):
    """Where the stages of the owners are saved and restored from.

    ``restore`` returns the saved stage of an owner (1-based index on the owner
    raster) read with the halo ``halo_m``, or None; ``save`` keeps a stage just
    read, with the bounds of the owner's cells
    ``(row_start, row_stop, col_start, col_stop)``.
    """

    def restore(self, owner: int, halo_m: float) -> UnitStage | None:
        """Return the saved stage of the owner at this halo, or None."""
        ...

    def save(
        self,
        owner: int,
        halo_m: float,
        bbox: tuple[int, int, int, int],
        stage: UnitStage,
    ) -> None:
        """Keep the stage of the owner read at this halo."""
        ...


@dataclass(frozen=True)
class FilledGrid:
    """The fill and D8 of the whole grid (``fill_whole_grid``), tiled GeoTIFFs.

    Attributes
    ----------
    filled : Path
        float32 filled DEM, nodata where the DEM has none, at the drain points
        and on the repaired holes.
    fdir : Path
        int16 D8 after the sink fix of ``process_hydrology_pyflwdir``, 0 without
        a direction.
    d8 : Path
        uint8 D8 of pyflwdir: 247 on the cells it routes no flow through, 0 at its
        pits; a repaired hole has a direction.
    """

    filled: Path
    fdir: Path
    d8: Path


@dataclass
class UnitHydrology:
    """Completed owned-cell rasters on the common grid, backed by local files."""

    filled_dem: np.memmap
    fdir: np.memmap
    acc: np.memmap
    flow_dist_m: np.memmap
    strahler: dict[int, np.memmap]
    labels: dict[int, np.memmap]
    slope: np.memmap
    segments: dict[int, list[dict[str, Any]]]
    raw_fdir: np.memmap
    valid: np.memmap


def _raster(path: Path, dtype: str, shape: tuple[int, int]) -> np.memmap:
    """Create a disk-backed raster without filling it twice."""
    return np.lib.format.open_memmap(path, mode="w+", dtype=dtype, shape=shape)


def _untimed(name: str) -> AbstractContextManager[object]:
    """Give a step that the caller of ``process_unit_hydrology`` does not time."""
    return nullcontext()


def fill_whole_grid(
    dem_path: Path,
    output_dir: Path,
    drain_points: list[tuple[int, int]] | None = None,
) -> FilledGrid:
    """Fill the depressions of the whole DEM and derive its D8, once.

    The fill, the D8 and the sink fix of ``process_hydrology_pyflwdir``
    (``fill_depressions_d8``, ``fix_sinks_of_fill``) on the whole grid, without its
    FlwdirRaster and accumulation, which the routing computes on disk. The holes of
    the DEM are repaired in the array read, which pyflwdir then fills: the memory is
    the DEM and the arrays of the fill, all float32 or smaller. The results are
    written to ``output_dir`` as tiled GeoTIFFs and freed.

    Parameters
    ----------
    dem_path : Path
        The DEM as ``process_hydrology_pyflwdir`` is to see it (streams burnt,
        buildings raised).
    output_dir : Path
        Where ``filled.tif``, ``fdir.tif`` and ``d8.tif`` are written.
    drain_points : list of (row, col), optional
        The drain points of endorheic lakes on the grid.

    Returns
    -------
    FilledGrid
        The paths of the three rasters.
    """
    dem, metadata = read_raster(dem_path)
    nodata = metadata["nodata_value"]
    logger.info("Filling the whole grid: %s cells", f"{dem.size:,}")
    filled, d8 = fill_depressions_d8(dem, nodata, drain_points, overwrite_dem=True)
    del dem
    fdir = d8.astype(np.int16)
    fdir[d8 == _NO_FLOW] = 0
    # The accumulation a sink fix needs is that of pyflwdir's D8 (its upstream
    # area): every cell pyflwdir routes counts, the repaired holes too
    fdir, _ = fix_sinks_of_fill(
        fdir, filled, nodata, partial(recompute_flow_accumulation, fdir, d8, _NO_FLOW)
    )
    grid = FilledGrid(
        output_dir / "filled.tif", output_dir / "fdir.tif", output_dir / "d8.tif"
    )
    save_raster_geotiff(filled, metadata, grid.filled, nodata=nodata, dtype="float32")
    del filled
    save_raster_geotiff(fdir, metadata, grid.fdir, nodata=0, dtype="int16")
    del fdir
    save_raster_geotiff(d8, metadata, grid.d8, nodata=_NO_FLOW, dtype="uint8")
    return grid


@numba.njit(cache=True)
def _receiver(
    i: int, fdir: np.ndarray, valid: np.ndarray, nrows: int, ncols: int
) -> int:
    """Resolve a D8 receiver using the common grid, never wrapping at a row edge."""
    code = fdir[i]
    if code < 0 or code > 255 or not D8_VALID[code]:
        return -1
    row, col = divmod(i, ncols)
    down_row = row + D8_ROW_OFFSET[code]
    down_col = col + D8_COL_OFFSET[code]
    if 0 <= down_row < nrows and 0 <= down_col < ncols:
        down = down_row * ncols + down_col
        if valid[down]:
            return int(down)
    return -1


@numba.njit(cache=True)
def _route_cells(
    fdir: np.ndarray,
    valid: np.ndarray,
    indegree: np.ndarray,
    acc: np.ndarray,
    queue: np.ndarray,
    nrows: int,
    ncols: int,
) -> int:
    """Kahn flow: every sending cell adds its complete area to its receiver once."""
    n = fdir.size
    nvalid = 0
    for i in range(n):
        if not valid[i]:
            continue
        nvalid += 1
        acc[i] = 1
        down = _receiver(i, fdir, valid, nrows, ncols)
        if down >= 0:
            indegree[down] += 1
    end = 0
    for i in range(n):
        if valid[i] and indegree[i] == 0:
            queue[end] = i
            end += 1
    at = 0
    while at < end:
        i = queue[at]
        at += 1
        down = _receiver(i, fdir, valid, nrows, ncols)
        if down >= 0:
            acc[down] += acc[i]
            indegree[down] -= 1
            if indegree[down] == 0:
                queue[end] = down
                end += 1
    return end if end == nvalid else -1


@numba.njit(cache=True)
def _outlet_distance(
    fdir: np.ndarray,
    valid: np.ndarray,
    queue: np.ndarray,
    nvalid: int,
    result: np.ndarray,
    nrows: int,
    ncols: int,
    transform: Any,
) -> None:
    """Reverse D8 order, including one step at every cross-owner boundary."""
    result[:] = -9999.0
    for k in range(nvalid - 1, -1, -1):
        i = queue[k]
        down = _receiver(i, fdir, valid, nrows, ncols)
        if down < 0:
            result[i] = 0.0
        else:
            # pyflwdir adds in float32 (NumPy 2 keeps a Python float weak), so the
            # step is rounded to float32 first: the same bits as stream_distance.
            result[i] = result[down] + np.float32(
                _cell_distance(i, down, ncols, latlon=False, transform=transform)
            )


@numba.njit(cache=True)
def _strahler(
    fdir: np.ndarray,
    valid: np.ndarray,
    acc: np.ndarray,
    queue: np.ndarray,
    nvalid: int,
    result: np.ndarray,
    maximum_upstream: np.ndarray,
    nrows: int,
    ncols: int,
    threshold_cells: int,
) -> None:
    """Use pyflwdir.streams.strahler_order's same headwater/confluence rule."""
    for k in range(nvalid):
        i = queue[k]
        if acc[i] < threshold_cells:
            continue
        if result[i] == 0:
            result[i] = 1
        down = _receiver(i, fdir, valid, nrows, ncols)
        if down < 0:
            continue
        current, existing = result[i], result[down]
        earlier = maximum_upstream[down]
        if existing < current:
            result[down] = current
        elif current == existing and earlier == current:
            result[down] += 1
        if earlier < current:
            maximum_upstream[down] = current


@numba.njit(cache=True)
def _propagate_labels(
    fdir: np.ndarray,
    valid: np.ndarray,
    queue: np.ndarray,
    nvalid: int,
    labels: np.ndarray,
    nrows: int,
    ncols: int,
) -> None:
    """Trace every unlabeled cell to the first downstream stream seed."""
    for k in range(nvalid - 1, -1, -1):
        i = queue[k]
        if labels[i] == 0:
            down = _receiver(i, fdir, valid, nrows, ncols)
            if down >= 0:
                labels[i] = labels[down]


def _unit_stage(
    row: int,
    col: int,
    fresh: np.ndarray,
    filled: np.ndarray,
    fdir: np.ndarray,
    raw_fdir: np.ndarray,
    active: np.ndarray,
) -> UnitStage:
    """Crop the cells an owner writes (``fresh`` of its window at ``row, col``)."""
    rows = np.flatnonzero(fresh.any(axis=1))
    cols = np.flatnonzero(fresh.any(axis=0))
    top, left = int(rows[0]), int(cols[0])
    cells = fresh[top : int(rows[-1]) + 1, left : int(cols[-1]) + 1].copy()
    # Row-major order over the window is row-major order over the crop.
    return UnitStage(row + top, col + left, cells, filled, fdir, raw_fdir, active)


def _apply_stage(
    stage: UnitStage,
    filled: np.ndarray,
    fdir: np.ndarray,
    raw_fdir: np.ndarray,
    seen: np.ndarray,
    valid: np.ndarray,
) -> None:
    """Write an owner's cells into the whole-grid rasters."""
    rows = slice(stage.row, stage.row + stage.cells.shape[0])
    cols = slice(stage.col, stage.col + stage.cells.shape[1])
    if rows.stop > filled.shape[0] or cols.stop > filled.shape[1]:
        raise ValueError("A unit stage reaches beyond the grid")
    cells = stage.cells
    filled[rows, cols][cells] = stage.filled
    fdir[rows, cols][cells] = stage.fdir
    raw_fdir[rows, cols][cells] = stage.raw_fdir
    seen[rows, cols][cells] = 1
    valid[rows, cols][cells] = stage.active


def _read_stage(
    grid: dict[str, Any],
    owners: np.ndarray,
    owner: int,
    bounds: tuple[int, int, int, int],
    seen: np.ndarray,
    nodata: float,
) -> UnitStage:
    """Take an owner's cells, and the repaired holes next to them, from the fill.

    ``grid`` holds the open datasets of the ``FilledGrid``. The window is the box
    of the owner's cells widened by ``HOLE_FILL_PASSES`` cells: a repaired hole lies
    that close to DEM data. The holes no owner took yet within that distance of the
    owner's cells are the owner's to write: they carry flow but belong to no unit.
    """
    min_row, max_row, min_col, max_col = bounds
    nrows, ncols = owners.shape
    r0 = max(0, min_row - HOLE_FILL_PASSES)
    r1 = min(nrows, max_row + HOLE_FILL_PASSES)
    c0 = max(0, min_col - HOLE_FILL_PASSES)
    c1 = min(ncols, max_col + HOLE_FILL_PASSES)
    window = Window(c0, r0, c1 - c0, r1 - r0)
    filled = grid["filled"].read(1, window=window)
    d8 = grid["d8"].read(1, window=window)
    owned = owners[r0:r1, c0:c1] == owner
    # A repaired hole: nodata in the filled DEM, yet pyflwdir routes flow through it
    patched = (filled == nodata) & (d8 != _NO_FLOW)
    if np.any(patched):
        patched &= binary_dilation(
            owned, structure=np.ones((3, 3), dtype=bool), iterations=HOLE_FILL_PASSES
        )
    fresh = owned | (patched & (seen[r0:r1, c0:c1] == 0))
    del owned, patched
    raw_fdir = d8[fresh].astype(np.int16)
    active = raw_fdir != _NO_FLOW
    raw_fdir[~active] = 0
    fdir = grid["fdir"].read(1, window=window)[fresh]
    return _unit_stage(r0, c0, fresh, filled[fresh], fdir, raw_fdir, active)


def process_unit_hydrology(
    dem_path: Path,
    owners: np.ndarray,
    output_dir: Path,
    thresholds_m2: tuple[int, ...],
    *,
    drain_points: list[tuple[int, int]] | None = None,
    checkpoints: UnitCheckpoints | None = None,
    stage: Callable[[str], AbstractContextManager[object]] = _untimed,
) -> UnitHydrology:
    """Fill the whole grid once, take its cells owner by owner, then route on disk.

    ``owners`` must assign every DEM-data cell a positive owner; repaired holes and
    cells without data are no owner's. An actual cell-level cycle fails rather
    than publishing a numerically incorrect mosaic. No PGW owner-graph topological
    sort is used.

    ``dem_path`` is the DEM exactly as ``process_hydrology_pyflwdir`` is to see it:
    streams burnt, buildings raised; ``drain_points`` are the lake drain points of
    the whole grid. Burning, smoothing and the classification of lakes look at a
    whole stream or lake, and the fill at a whole closed basin and its flats, so
    none of them runs in a window: the caller prepares the DEM on the whole grid,
    ``fill_whole_grid`` fills it, and every owner takes its cells from that fill.
    ``output_dir`` holds the fill and the disk-backed rasters.

    With ``checkpoints`` every owner's stage is saved once taken, and an owner
    whose stage was saved is restored instead; the grid is filled only when an
    owner is not restored. ``stage`` gives a context for each step:
    ``restore_units``, ``global_fill``, ``unit_stages``, ``routing`` and
    ``vectorize_streams``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dem_path) as source:
        if owners.shape != source.shape or owners.dtype.kind not in "iu":
            raise ValueError("owner raster must be an integer array on the DEM grid")
        if source.nodata is None:
            raise ValueError("DEM nodata is required")
        if source.transform.a != -source.transform.e or source.transform.a <= 0:
            raise ValueError("DEM must have square, north-up cells")
        shape = source.shape
        nodata = source.nodata
        transform = source.transform
        bounds = source.bounds
    nrows, ncols = shape
    cellsize_m = transform.a
    # The margin of an owner's window, recorded with its stage
    halo_m = HOLE_FILL_PASSES * cellsize_m
    filled = _raster(output_dir / "filled.npy", "float32", shape)
    fdir = _raster(output_dir / "fdir.npy", "int16", shape)
    raw_fdir = _raster(output_dir / "raw_fdir.npy", "int16", shape)
    seen = _raster(output_dir / "seen.npy", "uint8", shape)
    valid = _raster(output_dir / "valid.npy", "bool", shape)
    # One scan of the owner raster, not one full-grid np.nonzero per PGW.
    unit_bounds = [
        (owner, (bbox[0].start, bbox[0].stop, bbox[1].start, bbox[1].stop))
        for owner, bbox in enumerate(find_objects(owners), start=1)
        if bbox is not None
    ]
    pending = unit_bounds
    if checkpoints is not None:
        with stage("restore_units"):
            pending = []
            for owner, owner_bounds in unit_bounds:
                restored = checkpoints.restore(owner, halo_m)
                if restored is None:
                    pending.append((owner, owner_bounds))
                else:
                    _apply_stage(restored, filled, fdir, raw_fdir, seen, valid)
                    del restored
    if pending:
        with stage("global_fill"):
            grid = fill_whole_grid(dem_path, output_dir, drain_points)
        with (
            stage("unit_stages"),
            rasterio.open(grid.filled) as grid_filled,
            rasterio.open(grid.fdir) as grid_fdir,
            rasterio.open(grid.d8) as grid_d8,
        ):
            datasets = {"filled": grid_filled, "fdir": grid_fdir, "d8": grid_d8}
            for owner, owner_bounds in pending:
                unit = _read_stage(datasets, owners, owner, owner_bounds, seen, nodata)
                _apply_stage(unit, filled, fdir, raw_fdir, seen, valid)
                if checkpoints is not None:
                    checkpoints.save(owner, halo_m, owner_bounds, unit)
                del unit
    with stage("routing"):
        unseen = seen == 0
        if np.any(unseen):
            # Unowned nodata is permitted, but valid exterior cells cannot be
            # dropped because their upstream flow might enter an owner.
            with rasterio.open(dem_path) as source:
                for _, window in source.block_windows(1):
                    block = source.read(1, window=window)
                    row = int(window.row_off)
                    col = int(window.col_off)
                    unowned = unseen[
                        row : row + block.shape[0], col : col + block.shape[1]
                    ]
                    if np.any(unowned & (block != nodata)):
                        raise ValueError("Valid DEM cells without a processing owner")
            filled[unseen] = nodata
        del unseen, seen
        # As process_dem: the slope of the whole filled DEM, strip by strip
        slope = _raster(output_dir / "slope.npy", "float64", shape)
        for rows, dx, dy in gradient_strips(filled, cellsize_m, nodata, _STRIP_ROWS):
            slope[rows] = compute_slope_from_gradients(dx, dy)
            del dx, dy
        indegree = _raster(output_dir / "indegree.npy", "uint8", shape)
        acc = _raster(output_dir / "acc.npy", "int32", shape)
        queue = np.memmap(
            output_dir / "topology.bin",
            mode="w+",
            dtype="int32",
            shape=(nrows * ncols,),
        )
        nvalid = _route_cells(
            fdir.ravel(),
            valid.ravel(),
            indegree.ravel(),
            acc.ravel(),
            queue,
            nrows,
            ncols,
        )
        del indegree
        if nvalid < 0:
            raise ValueError("D8 cycle in global owned-cell flow graph")
        distance = _raster(output_dir / "flow_dist_m.npy", "float32", shape)
        _outlet_distance(
            raw_fdir.ravel(),
            valid.ravel(),
            queue,
            nvalid,
            distance.ravel(),
            nrows,
            ncols,
            transform,
        )
    grid_metadata: dict[str, Any] = {
        "cellsize": cellsize_m,
        "xllcorner": bounds.left,
        "yllcorner": bounds.bottom,
        "nodata_value": nodata,
        "transform": transform,
    }
    results: dict[int, np.memmap] = {}
    segments_by_threshold: dict[int, list[dict[str, Any]]] = {}
    labels: dict[int, np.memmap] = {}
    with stage("vectorize_streams"):
        for threshold_m2 in sorted(set(thresholds_m2), reverse=True):
            threshold_cells = max(1, int(threshold_m2 / cellsize_m**2))
            order = _raster(output_dir / f"order_{threshold_m2}.npy", "uint8", shape)
            maximum = _raster(output_dir / "max_order.npy", "uint8", shape)
            _strahler(
                raw_fdir.ravel(),
                valid.ravel(),
                acc.ravel(),
                queue,
                nvalid,
                order.ravel(),
                maximum.ravel(),
                nrows,
                ncols,
                threshold_cells,
            )
            del maximum
            label = _raster(output_dir / f"labels_{threshold_m2}.npy", "int32", shape)
            segments = vectorize_streams(
                filled,
                fdir,
                acc,
                slope,
                order,
                metadata=grid_metadata,
                stream_threshold=threshold_cells,
                label_raster_out=label,
            )
            _propagate_labels(
                raw_fdir.ravel(),
                valid.ravel(),
                queue,
                nvalid,
                label.ravel(),
                nrows,
                ncols,
            )
            compute_downstream_links(segments, label, fdir, grid_metadata)
            segments_by_threshold[threshold_m2] = segments
            results[threshold_m2] = order
            labels[threshold_m2] = label
    del queue
    return UnitHydrology(
        filled,
        fdir,
        acc,
        distance,
        results,
        labels,
        slope,
        segments_by_threshold,
        raw_fdir,
        valid,
    )
