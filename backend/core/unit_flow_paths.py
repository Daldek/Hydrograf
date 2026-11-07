"""Flow-path operations on disk-backed, globally routed PGW D8 cells.

The catchment enrichment stage needs downstream indices, raster-cell centres and
paths to the first stream cell. A whole-area pyflwdir object would duplicate the
full grid's flow topology in RAM, so the same operations use an int32 memmap.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numba
import numpy as np
from affine import Affine
from pyflwdir.gis_utils import distance as _cell_distance

from core.unit_hydrology import UnitHydrology, _receiver


@numba.njit(cache=True)
def _downstream_indices(
    fdir: np.ndarray,
    valid: np.ndarray,
    downstream: np.ndarray,
    nrows: int,
    ncols: int,
) -> None:
    for i in range(fdir.size):
        if not valid[i]:
            downstream[i] = -1
        else:
            target = _receiver(i, fdir, valid, nrows, ncols)
            downstream[i] = target if target >= 0 else i


@numba.njit(cache=True)
def _path_to_mask(
    start: int,
    downstream: np.ndarray,
    stop: np.ndarray,
    ncols: int,
    transform: Any,
) -> tuple[np.ndarray, float]:
    """Include the first marked cell; an outlet itself makes a one-cell path."""
    index = start
    count = 1
    while not stop[index]:
        target = downstream[index]
        if target < 0 or target == index:
            break
        index = target
        count += 1
        if count > downstream.size:
            raise ValueError("Cycle while tracing a PGW flow path")
    path = np.empty(count, dtype=np.int32)
    index = start
    path[0] = index
    length_m = 0.0
    for k in range(1, count):
        target = downstream[index]
        length_m += _cell_distance(
            index, target, ncols, latlon=False, transform=transform
        )
        index = target
        path[k] = index
    return path, length_m


@dataclass
class UnitFlowPaths:
    """The subset of pyflwdir path APIs used by catchment enrichment."""

    idxs_ds: np.memmap
    shape: tuple[int, int]
    transform: Affine

    @classmethod
    def from_hydrology(
        cls, result: UnitHydrology, transform: Affine, path: Path
    ) -> UnitFlowPaths:
        """Persist the D8 receiver of every active cell once for path tracing."""
        nrows, ncols = result.fdir.shape
        indices = np.lib.format.open_memmap(
            path, mode="w+", dtype="int32", shape=(nrows * ncols,)
        )
        _downstream_indices(
            result.raw_fdir.ravel(),
            result.valid.ravel(),
            indices,
            nrows,
            ncols,
        )
        return cls(indices, (nrows, ncols), transform)

    def xy(self, indices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return the EPSG:2180 centres of flat raster indices."""
        cols = indices % self.shape[1]
        rows = indices // self.shape[1]
        xs, ys = self.transform * (cols + 0.5, rows + 0.5)
        return xs, ys

    def path(
        self, *, idxs: np.ndarray, mask: np.ndarray, unit: str
    ) -> tuple[list[np.ndarray], list[float]]:
        """Trace each upstream head to the first marked stream cell or outlet."""
        if mask.shape != self.shape or unit != "m":
            raise ValueError("PGW flow paths require a same-grid mask and metre units")
        marked = mask.ravel()
        paths: list[np.ndarray] = []
        lengths: list[float] = []
        for start in idxs:
            path, length = _path_to_mask(
                int(start),
                self.idxs_ds,
                marked,
                self.shape[1],
                self.transform,
            )
            paths.append(path)
            lengths.append(length)
        return paths, lengths
