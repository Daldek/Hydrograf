"""Flow-path operations on disk-backed, globally routed PGW D8 cells.

The catchment enrichment stage needs downstream indices (the flow paths and the
overland segments of core.cell_parameters walk them) and raster-cell centres. A
whole-area pyflwdir object would duplicate the full grid's flow topology in RAM, so
the same operations use an int32 memmap.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numba
import numpy as np
from affine import Affine

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


@dataclass
class UnitFlowPaths:
    """The subset of pyflwdir's FlwdirRaster used by catchment enrichment."""

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
