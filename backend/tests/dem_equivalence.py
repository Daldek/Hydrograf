"""Small synthetic rasters and an exact comparison for old-versus-new tests.

The memory plan of the DEM processing (docs/TECHNICAL_DEBT.md, F1 to F7) changes how
process_dem computes, never what it computes. A step rewritten for memory is tested
against the old one on the rasters of this module, and the two results must agree bit
for bit (assert_identical).

synthetic_dem builds a deterministic DEM with what makes the processing branch:

- single-cell pits and a closed basin, which the depression filling turns into flats,
  and flats of the input: a plateau and a strip on the north edge;
- an irregular nodata border: ragged corners and a missing sheet on the east side.
  The valid cells touch the frame of the raster between them, so outlets lie both on
  the frame and next to nodata inside it;
- internal nodata holes that fill_internal_nodata_holes fills in one pass (1 x 1,
  2 x 2, a cell on the north edge), in three passes (3 x 3) or in part (2 x 8, which
  needs a fourth pass, and 4 x 4, of which only the corners fill);
- pits next to the nodata that stays (the 4 x 4 hole, the missing sheet): internal
  sinks, which fix_internal_sinks turns into pairs of cells draining into each other.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pyflwdir
from rasterio.coords import BoundingBox
from rasterio.transform import from_origin
from scipy import ndimage

from core.hydrology import process_hydrology_pyflwdir
from core.morphometry_raster import _compute_gradients, compute_slope_from_gradients

NODATA = -9999.0
CELLSIZE_M = 5.0
# South-west corner of the grids (PL-1992)
XLL_M = 500_000.0
YLL_M = 300_000.0
# Flow accumulation thresholds for grids of CELLSIZE_M (10, 40 and 200 cells): the
# first is below MIN_CATCHMENT_THRESHOLD_M2 (streams only), the others have
# sub-catchments
THRESHOLDS_M2 = (250, 1_000, 5_000)
# The smallest grid that holds the features of synthetic_dem
MIN_ROWS = 40
MIN_COLS = 48

# Variants for parametrized tests, by test id: keyword arguments of synthetic_dem.
# The sizes divide by no common strip height.
DEM_CASES: dict[str, dict[str, Any]] = {
    "float32": {},
    "float64": {"dtype": np.float64, "seed": 1},
    "no-border": {"nodata_border": False, "seed": 2},
    "no-holes": {"holes": False, "seed": 3},
    "large": {"nrows": 83, "ncols": 101, "seed": 4},
}


def grid_metadata(
    nrows: int,
    ncols: int,
    *,
    cellsize_m: float = CELLSIZE_M,
    nodata: float = NODATA,
) -> dict[str, Any]:
    """Return the metadata that read_raster gives for a grid of the tests."""
    xmax_m = XLL_M + ncols * cellsize_m
    ymax_m = YLL_M + nrows * cellsize_m
    return {
        "ncols": ncols,
        "nrows": nrows,
        "xllcorner": XLL_M,
        "yllcorner": YLL_M,
        "cellsize": cellsize_m,
        "nodata_value": nodata,
        "crs": "EPSG:2180",
        "bounds": BoundingBox(XLL_M, YLL_M, xmax_m, ymax_m),
        "transform": from_origin(XLL_M, ymax_m, cellsize_m, cellsize_m),
    }


def synthetic_dem(
    nrows: int = 47,
    ncols: int = 61,
    *,
    seed: int = 0,
    dtype: npt.DTypeLike = np.float32,
    nodata_border: bool = True,
    holes: bool = True,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Build a DEM of a valley network with pits, flats and nodata (module docstring).

    The same arguments give the same DEM. The land falls to the south along a
    meandering main valley; ridges across its sides make the tributaries and ``seed``
    drives the roughness. The pits, flats and holes sit at fixed offsets from the
    centre of the grid, which has at least MIN_ROWS x MIN_COLS cells.

    Returns
    -------
    tuple[np.ndarray, dict]
        The DEM (``dtype``, NODATA outside the area) and its grid_metadata.
    """
    if nrows < MIN_ROWS or ncols < MIN_COLS:
        raise ValueError(f"synthetic_dem needs at least {MIN_ROWS} x {MIN_COLS} cells")
    rng = np.random.default_rng(seed)
    rows, cols = np.indices((nrows, ncols), dtype=np.float64)
    valley = ncols / 2 + 0.1 * ncols * np.sin(2 * np.pi * rows / nrows)
    across = np.abs(cols - valley)
    elevation = (
        100.0
        + 0.3 * (nrows - 1 - rows)
        + 0.6 * across
        + 1.5 * np.abs(np.sin(rows / 6.0)) * np.minimum(across, 12.0) / 12.0
        + 3.0 * ndimage.gaussian_filter(rng.normal(size=(nrows, ncols)), sigma=2.0)
    )

    centre_row, centre_col = nrows // 2, ncols // 2
    # Single-cell pits deeper than the relief around them: one on the valley floor,
    # one next to each nodata area that stays (internal sinks)
    floor_row = centre_row - 3
    pits = [
        (centre_row - 8, centre_col - 9),
        (centre_row + 6, centre_col + 9),
        (centre_row + 10, centre_col - 5),
        (floor_row, round(float(valley[floor_row, 0]))),
    ]
    if holes:
        pits.append((centre_row - 4, centre_col - 15))
    if nodata_border:
        pits.append((centre_row + 6, ncols - 8))
    for row, col in pits:
        elevation[row, col] -= 3.0
    # A closed basin, 6 m deep at its centre and 4 cells in radius
    distance = np.hypot(rows - (centre_row - 1), cols - (centre_col + 10))
    elevation -= np.clip(6.0 * (1.0 - distance / 4.0), 0.0, None)
    # Flats: a plateau at the elevation of its lowest cell, a strip on the north edge
    for flat in (
        np.s_[centre_row - 12 : centre_row - 8, centre_col + 3 : centre_col + 10],
        np.s_[0:2, centre_col - 3 : centre_col + 4],
    ):
        elevation[flat] = elevation[flat].min()

    dem = elevation.astype(dtype)
    if nodata_border:
        # Ragged corners: Manhattan distance to the nearest corner under a wavy limit
        to_corner = np.minimum(rows, nrows - 1 - rows) + np.minimum(
            cols, ncols - 1 - cols
        )
        dem[to_corner < 9.0 + 2.0 * np.sin(0.9 * rows) + 2.0 * np.cos(0.7 * cols)] = (
            NODATA
        )
        # A missing sheet on the east side
        dem[centre_row + 2 : centre_row + 12, ncols - 7 :] = NODATA
    if holes:
        for hole in (
            # Filled in one pass: 1 x 1, 2 x 2, a cell of the north edge
            np.s_[centre_row + 3, centre_col - 11],
            np.s_[centre_row - 5 : centre_row - 3, centre_col - 4 : centre_col - 2],
            np.s_[0, centre_col + 7],
            # In three passes: 3 x 3
            np.s_[centre_row + 8 : centre_row + 11, centre_col + 3 : centre_col + 6],
            # In part: 2 x 8 (four passes), 4 x 4 (its corners only)
            np.s_[centre_row + 13 : centre_row + 15, centre_col - 11 : centre_col - 3],
            np.s_[centre_row - 3 : centre_row + 1, centre_col - 16 : centre_col - 12],
        ):
            dem[hole] = NODATA
    return dem, grid_metadata(nrows, ncols)


@dataclass
class Hydrology:
    """The rasters that process_dem derives from a DEM before its thresholds."""

    filled_dem: np.ndarray
    # D8 flow directions after fix_internal_sinks (int16, 0 = none)
    fdir: np.ndarray
    # Flow accumulation [cells] (int32)
    acc: np.ndarray
    # pyflwdir D8 flow directions of flw (uint8)
    d8_fdir: np.ndarray
    flw: Any
    flow_dist_m: np.ndarray
    slope_percent: np.ndarray
    metadata: dict[str, Any]


def derive_hydrology(dem: np.ndarray, metadata: dict[str, Any]) -> Hydrology:
    """Run the steps of process_dem from the DEM to the slope.

    Every call computes new arrays. A function that changes its inputs in place needs
    copies when the old and the new code run on one Hydrology.
    """
    filled_dem, fdir, acc, d8_fdir = process_hydrology_pyflwdir(dem, metadata)
    flw = pyflwdir.from_array(
        d8_fdir, ftype="d8", transform=metadata["transform"], latlon=False
    )
    flow_dist_m = flw.stream_distance(unit="m").reshape(d8_fdir.shape)
    dx, dy = _compute_gradients(
        filled_dem, metadata["cellsize"], metadata["nodata_value"]
    )
    slope_percent = compute_slope_from_gradients(dx, dy)
    return Hydrology(
        filled_dem=filled_dem,
        fdir=fdir,
        acc=acc,
        d8_fdir=d8_fdir,
        flw=flw,
        flow_dist_m=flow_dist_m,
        slope_percent=slope_percent,
        metadata=metadata,
    )


def assert_identical(actual: Any, expected: Any, where: str = "result") -> None:
    """Assert that ``actual`` (the new code) equals ``expected`` (the old) bit for bit.

    Both have the same type at every level. Arrays agree in dtype, shape and the bits
    of every value (NaN equals NaN of the same bits, 0.0 differs from -0.0), floats
    and NumPy scalars in their bits, dicts in their keys, the order of the keys and
    the values, lists and tuples item by item; anything else by ``==``. The message
    names the first place that differs, e.g. ``result[3]['coords'][0]``.

    Raises
    ------
    AssertionError
        At the first difference.
    """
    if type(actual) is not type(expected):
        raise AssertionError(
            f"{where}: {type(actual).__name__} != {type(expected).__name__}"
        )
    if isinstance(expected, np.ndarray):
        _assert_identical_arrays(actual, expected, where)
    elif isinstance(expected, float | np.generic):
        if np.asarray(actual).tobytes() != np.asarray(expected).tobytes():
            raise AssertionError(f"{where}: {actual!r} != {expected!r}")
    elif isinstance(expected, dict):
        if list(actual) != list(expected):
            raise AssertionError(f"{where}: keys {list(actual)} != {list(expected)}")
        for key, value in expected.items():
            assert_identical(actual[key], value, f"{where}[{key!r}]")
    elif isinstance(expected, list | tuple):
        if len(actual) != len(expected):
            raise AssertionError(
                f"{where}: {len(actual)} items != {len(expected)} items"
            )
        for index, (new, old) in enumerate(zip(actual, expected, strict=True)):
            assert_identical(new, old, f"{where}[{index}]")
    elif actual != expected:
        raise AssertionError(f"{where}: {actual!r} != {expected!r}")


def _assert_identical_arrays(
    actual: np.ndarray, expected: np.ndarray, where: str
) -> None:
    """Assert the identity of two arrays (assert_identical)."""
    if actual.dtype != expected.dtype or actual.shape != expected.shape:
        raise AssertionError(
            f"{where}: {actual.dtype} {actual.shape} != {expected.dtype} "
            f"{expected.shape}"
        )
    if expected.dtype.hasobject:
        assert_identical(actual.tolist(), expected.tolist(), where)
        return
    if actual.tobytes() == expected.tobytes():
        return
    new = np.ascontiguousarray(actual).reshape(-1)
    old = np.ascontiguousarray(expected).reshape(-1)
    size = expected.dtype.itemsize
    if expected.dtype.kind in "biufc" and size in (1, 2, 4, 8):
        differ = new.view(f"u{size}") != old.view(f"u{size}")
    else:
        differ = new != old
    first = np.unravel_index(int(np.argmax(differ)), expected.shape)
    raise AssertionError(
        f"{where}: {int(np.count_nonzero(differ))} of {expected.size} values differ, "
        f"the first at {tuple(int(i) for i in first)}: "
        f"{actual[first]!r} != {expected[first]!r}"
    )
