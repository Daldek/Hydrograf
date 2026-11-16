"""core.cell_parameters: the overland walk and the memory of the flow paths.

The walk along the flow directions replaced ``FlwdirRaster.path`` with the stream
mask. On the synthetic DEMs of tests.dem_equivalence (pits, flats, nodata holes and a
nodata border) every cell, taken as a head, gets the length and drop of the overland
segment that the path on the same directions gave (the code before, the reference):
along the downstream indices of the run (pyflwdir's, and in the int32 of
UnitFlowPaths), along the D8 grid rebuilt from its saved rasters, and along that grid
with a pit on the hillside, as the export makes its outlet one.

The network measures each element in a frame of a window of up to 60 M cells, so the
flow paths of a frame take no copy of it and no mask of its candidate cells.
"""

import tracemalloc

import numpy as np
import pyflwdir
import pytest
from rasterio.transform import from_origin

from core.cell_parameters import (
    CellWindow,
    d8_from_saved_flowdir,
    flow_path_parameters,
    overland_segments,
)
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


def test_the_flow_paths_of_a_frame_take_less_than_two_bytes_a_cell():
    # A frame of size x size cells inside a window: every column flows south, the
    # last row east to the outlet in its corner, whose flow leaves the frame
    size, cell_m = 1000, 5.0
    row, col = np.indices((size + 2, size + 2)) - 1
    frame = (slice(1, -1), slice(1, -1))
    flow_dist = ((2 * size - 1 - row - col) * cell_m).astype(np.float32)
    fdir = np.where(row == size - 1, 1, 4).astype(np.int16)
    acc = np.where(row == size - 1, size * (col + 1), row + 1).astype(np.int32)
    everywhere = np.ones((size, size), dtype=bool)
    cells = CellWindow(
        dem=(flow_dist / 100)[frame],
        slope=None,
        acc=acc[frame],
        fdir=fdir[frame],
        flow_dist=flow_dist[frame],
        labels=None,
        dem_nodata=-9999.0,
        flow_dist_nodata=-1.0,
        transform=from_origin(0.0, size * cell_m, cell_m, cell_m),
        valid=everywhere,
        member=everywhere,
    )
    outlet = (size - 1, size - 1)
    d8 = d8_from_saved_flowdir(cells.fdir, cells.flow_dist, cells.valid)
    d8[outlet] = 0
    flow_path_parameters(cells, d8, outlet, 100)  # numba's code, outside the count

    tracemalloc.start()
    try:
        values, paths = flow_path_parameters(cells, d8, outlet, 100)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    # From the far corner down its column and along the last row
    assert values["flow_path_length_km"] == pytest.approx((2 * size - 2) * cell_m / 1e3)
    assert values["overland_length_km"] == pytest.approx(99 * cell_m / 1e3)
    assert paths.divide_is_longest
    # The mask of the stream cells and the cells of the path: no float copy of the
    # frame (4 bytes a cell), no mask per candidate or boundary cell
    assert peak < 2 * size * size
