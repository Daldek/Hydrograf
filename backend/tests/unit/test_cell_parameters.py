"""core.cell_parameters.overland_segments measures what pyflwdir's path measured.

The walk along the flow directions replaced ``FlwdirRaster.path`` with the stream
mask. On the synthetic DEMs of tests.dem_equivalence (pits, flats, nodata holes and a
nodata border) every cell, taken as a head, gets the length and drop of the overland
segment that the path on the same directions gave (the code before, the reference):
along the downstream indices of the run (pyflwdir's, and in the int32 of
UnitFlowPaths), along the D8 grid rebuilt from its saved rasters, and along that grid
with a pit on the hillside, as the export makes its outlet one.
"""

import numpy as np
import pyflwdir
import pytest

from core.cell_parameters import d8_from_saved_flowdir, overland_segments
from tests.dem_equivalence import (
    DEM_CASES,
    assert_identical,
    derive_hydrology,
    synthetic_dem,
)


@pytest.fixture(scope="module", params=list(DEM_CASES.values()), ids=list(DEM_CASES))
def hydrology(request):
    return derive_hydrology(*synthetic_dem(**request.param))


def _segments_by_pyflwdir(head_idxs, flw, stream_mask, flat_dem):
    """overland_segments as it was, on pyflwdir's path: the reference."""
    paths, dists = flw.path(idxs=head_idxs, mask=stream_mask, unit="m")
    stream_flat = stream_mask.ravel()
    lengths, drops = [], []
    for head, path, dist in zip(head_idxs, paths, dists, strict=True):
        end = path[-1]
        if len(path) < 2 or not stream_flat[end]:
            lengths.append(None)
            drops.append(None)
            continue
        lengths.append(round(float(dist), 1))
        drops.append(round(float(flat_dem[head]) - float(flat_dem[end]), 2))
    return lengths, drops


@pytest.mark.parametrize("threshold_cells", [10, 200])
def test_the_walk_measures_what_pyflwdirs_path_measured(hydrology, threshold_cells):
    nodata = hydrology.metadata["nodata_value"]
    valid = hydrology.filled_dem != nodata
    stream = (hydrology.acc >= threshold_cells) & valid
    flat_dem = hydrology.filled_dem.ravel()
    heads = np.arange(flat_dem.size, dtype=np.intp)
    transform = hydrology.flw.transform
    run = _segments_by_pyflwdir(heads, hydrology.flw, stream, flat_dem)
    # Not only unmeasured segments: many heads reach a stream
    assert sum(length is not None for length in run[0]) > heads.size // 4

    idxs_ds = hydrology.flw.idxs_ds
    for downstream in (idxs_ds, idxs_ds.astype(np.int32)):
        assert_identical(
            overland_segments(heads, stream, flat_dem, transform, idxs_ds=downstream),
            run,
        )
    saved = d8_from_saved_flowdir(hydrology.fdir, hydrology.flow_dist_m, valid)
    with_pit = saved.copy()
    with_pit.ravel()[np.argmax(np.where(stream, -1, hydrology.acc))] = 0
    for d8 in (saved, with_pit):
        flw = pyflwdir.from_array(d8, ftype="d8", transform=transform, latlon=False)
        assert_identical(
            overland_segments(heads, stream, flat_dem, transform, d8=d8),
            _segments_by_pyflwdir(heads, flw, stream, flat_dem),
        )
