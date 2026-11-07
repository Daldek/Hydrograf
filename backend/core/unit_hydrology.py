"""Hydrology on buffered raster owners with disk-backed cell-level routing.

A cycle in the owner graph is not a D8 cycle: the latter is detected explicitly.
Each owner's filling runs through the same hydrology code as process_dem; only its
owned cells survive the halo. Global counts and outlet distances are propagated
on a disk-backed D8 topology, so no entire-area pyflwdir object is created.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    process_hydrology_pyflwdir,
)
from core.morphometry_raster import _compute_gradients, compute_slope_from_gradients
from core.stream_extraction import vectorize_streams


class _SeamMismatch(ValueError):
    """A local halo has a different fill or D8 from the preceding owner."""


@dataclass
class UnitHydrology:
    """Completed owned-cell rasters on the common grid, backed by local files."""

    filled_dem: np.memmap
    fdir: np.memmap
    acc: np.memmap
    flow_dist_m: np.memmap
    strahler: dict[int, np.memmap]
    labels: dict[int, np.memmap]


def _raster(path: Path, dtype: str, shape: tuple[int, int]) -> np.memmap:
    """Create a disk-backed raster without filling it twice."""
    return np.lib.format.open_memmap(path, mode="w+", dtype=dtype, shape=shape)


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
            result[i] = result[down] + _cell_distance(
                i, down, ncols, latlon=False, transform=transform
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


def process_unit_hydrology(
    dem_path: Path,
    owners: np.ndarray,
    output_dir: Path,
    thresholds_m2: tuple[int, ...],
    *,
    buffer_m: float = 500.0,
    max_window_cells: int = 80_000_000,
) -> UnitHydrology:
    """Run the fill/D8, routing, distance and threshold masks by owner.

    ``owners`` must assign every DEM-data cell a positive owner. Buffer cells
    are input only, and the caller must partition exterior inflows too. A seam
    mismatch or an actual cell-level cycle fails rather than publishing a
    numerically incorrect mosaic. No PGW owner-graph topological sort is used.
    """
    if max_window_cells < 1:
        raise ValueError("max_window_cells must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dem_path) as source:
        nrows, ncols = source.shape
        if owners.shape != source.shape or owners.dtype.kind not in "iu":
            raise ValueError("owner raster must be an integer array on the DEM grid")
        if source.nodata is None:
            raise ValueError("DEM nodata is required")
        if source.transform.a != -source.transform.e or source.transform.a <= 0:
            raise ValueError("DEM must have square, north-up cells")
        shape = source.shape
        nodata = source.nodata
        cellsize_m = source.transform.a
        halo = math.ceil(buffer_m / cellsize_m)
        filled = _raster(output_dir / "filled.npy", "float32", shape)
        fdir = _raster(output_dir / "fdir.npy", "int16", shape)
        raw_fdir = _raster(output_dir / "raw_fdir.npy", "int16", shape)
        slope = _raster(output_dir / "slope.npy", "float32", shape)
        seen = _raster(output_dir / "seen.npy", "uint8", shape)
        # One scan of the owner raster, not one full-grid np.nonzero per PGW.
        unit_bounds = []
        for owner, bbox in enumerate(find_objects(owners), start=1):
            if bbox is not None:
                row, col = bbox
                unit_bounds.append(
                    (owner, row.start, row.stop, col.start, col.stop)
                )
        # An edge outlet of a local halo can change flat tie-breaking even
        # where the filled elevations agree. Redo *all* units on a larger halo,
        # so previously written neighbours are checked under identical rules.
        while True:
            seen[:] = 0
            try:
                for owner, min_row, max_row, min_col, max_col in unit_bounds:
                    r0 = max(0, min_row - halo)
                    r1 = min(nrows, max_row + halo)
                    c0 = max(0, min_col - halo)
                    c1 = min(ncols, max_col + halo)
                    window_cells = (r1 - r0) * (c1 - c0)
                    if window_cells > max_window_cells:
                        raise MemoryError(
                            f"PGW owner {owner} requires {window_cells:,} DEM cells "
                            f"with {halo * cellsize_m:g} m halo, exceeding configured "
                            f"max_window_cells={max_window_cells:,}; no seam result "
                            "will be published"
                        )
                    window = Window(c0, r0, c1 - c0, r1 - r0)
                    dem = source.read(1, window=window)
                    transform = source.window_transform(window)
                    metadata: dict[str, Any] = {
                        "ncols": c1 - c0,
                        "nrows": r1 - r0,
                        "xllcorner": transform.c,
                        "yllcorner": transform.f + (r1 - r0) * transform.e,
                        "cellsize": cellsize_m,
                        "nodata_value": nodata,
                        "transform": transform,
                    }
                    local_filled, local_fdir, _local_acc, flw = (
                        process_hydrology_pyflwdir(dem, metadata)
                    )
                    local_raw = flw.to_array(ftype="d8")
                    # The common hole filler temporarily repairs original
                    # nodata cells for flow, then restores their DEM nodata.
                    # Keep their D8 as scratch routing cells, not PGW owners.
                    patched = (dem == nodata) & (local_raw != 247)
                    local_raw[local_raw == 247] = 0
                    del flw, _local_acc
                    dx, dy = _compute_gradients(local_filled, cellsize_m, nodata)
                    local_slope = compute_slope_from_gradients(dx, dy)
                    del dx, dy
                    owned = owners[r0:r1, c0:c1] == owner
                    adjacent = binary_dilation(owned, structure=np.ones((3, 3)))
                    if np.any(patched):
                        # Hole filling makes at most three passes; every repaired
                        # cell is within three pixels of original valid DEM data.
                        patched &= binary_dilation(
                            adjacent, structure=np.ones((3, 3)), iterations=2
                        )
                    seen_window = seen[r0:r1, c0:c1]
                    old = (seen_window != 0) & (adjacent | patched)
                    different = old & (
                        (filled[r0:r1, c0:c1] != local_filled)
                        | (fdir[r0:r1, c0:c1] != local_fdir)
                    )
                    if np.any(different):
                        raise _SeamMismatch(
                            f"Owner {owner} has {np.count_nonzero(different)} "
                            f"fill/D8 disagreements at {halo * cellsize_m:g} m halo"
                        )
                    fresh = owned | (patched & (seen_window == 0))
                    filled[r0:r1, c0:c1][fresh] = local_filled[fresh]
                    fdir[r0:r1, c0:c1][fresh] = local_fdir[fresh]
                    raw_fdir[r0:r1, c0:c1][fresh] = local_raw[fresh]
                    slope[r0:r1, c0:c1][fresh] = local_slope[fresh]
                    seen_window[fresh] = 1
                    del dem, local_filled, local_fdir, local_raw, local_slope
                    del owned, adjacent, patched, old, different, fresh, seen_window
            except _SeamMismatch as error:
                if halo >= max(nrows, ncols):
                    raise ValueError("No consistent D8 at full DEM extent") from error
                halo *= 2
                continue
            break
        if np.any(seen == 0):
            # Unowned nodata is permitted, but valid exterior cells cannot be
            # dropped because their upstream flow might enter an owner.
            for _, window in source.block_windows(1):
                block = source.read(1, window=window)
                row = int(window.row_off)
                col = int(window.col_off)
                unowned = (
                    seen[row : row + block.shape[0], col : col + block.shape[1]] == 0
                )
                if np.any(unowned & (block != nodata)):
                    raise ValueError("Valid DEM cells without a processing owner")
            filled[seen == 0] = nodata
            fdir[seen == 0] = 0
            raw_fdir[seen == 0] = 0
        valid = _raster(output_dir / "valid.npy", "bool", shape)
        valid[:] = seen != 0
        indegree = _raster(output_dir / "indegree.npy", "uint8", shape)
        indegree[:] = 0
        acc = _raster(output_dir / "acc.npy", "int32", shape)
        acc[:] = 0
        queue = np.memmap(
            output_dir / "topology.bin",
            mode="w+",
            dtype="int32",
            shape=(nrows * ncols,),
        )
        nvalid = _route_cells(
            fdir.ravel(), valid.ravel(), indegree.ravel(), acc.ravel(),
            queue, nrows, ncols,
        )
        if nvalid < 0:
            raise ValueError("D8 cycle in global owned-cell flow graph")
        distance = _raster(output_dir / "flow_dist_m.npy", "float32", shape)
        _outlet_distance(
            raw_fdir.ravel(), valid.ravel(), queue, nvalid,
            distance.ravel(), nrows, ncols, source.transform,
        )
        results: dict[int, np.memmap] = {}
        labels: dict[int, np.memmap] = {}
        for threshold_m2 in sorted(set(thresholds_m2), reverse=True):
            threshold_cells = max(1, int(threshold_m2 / cellsize_m**2))
            order = _raster(output_dir / f"order_{threshold_m2}.npy", "uint8", shape)
            order[:] = 0
            maximum = _raster(output_dir / "max_order.npy", "uint8", shape)
            maximum[:] = 0
            _strahler(
                raw_fdir.ravel(), valid.ravel(), acc.ravel(), queue, nvalid,
                order.ravel(), maximum.ravel(), nrows, ncols, threshold_cells,
            )
            del maximum
            label = _raster(output_dir / f"labels_{threshold_m2}.npy", "int32", shape)
            label[:] = 0
            vectorize_streams(
                filled,
                fdir,
                acc,
                slope,
                order,
                metadata={
                    "cellsize": cellsize_m,
                    "xllcorner": source.bounds.left,
                    "yllcorner": source.bounds.bottom,
                    "nodata_value": nodata,
                },
                stream_threshold=threshold_cells,
                label_raster_out=label,
            )
            _propagate_labels(
                raw_fdir.ravel(), valid.ravel(), queue, nvalid,
                label.ravel(), nrows, ncols,
            )
            results[threshold_m2] = order
            labels[threshold_m2] = label
        del queue, indegree, raw_fdir, slope, seen, valid
        return UnitHydrology(filled, fdir, acc, distance, results, labels)
