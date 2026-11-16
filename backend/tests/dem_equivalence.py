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
from pathlib import Path
from typing import Any

import fiona
import numpy as np
import numpy.typing as npt
import rasterio
from rasterio.coords import BoundingBox
from rasterio.features import shapes
from rasterio.transform import from_origin
from scipy import ndimage
from shapely.geometry import MultiPolygon, shape

from core.hydrology import D8_DIRECTIONS, process_hydrology_pyflwdir
from core.morphometry_raster import (
    _compute_gradients,
    compute_slope_from_gradients,
    compute_strahler_from_fdir,
)
from core.stream_extraction import (
    compute_downstream_links,
    delineate_subcatchments,
    vectorize_streams,
)

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
    # pyflwdir.FlwdirRaster of the run (process_hydrology_pyflwdir)
    flw: Any
    flow_dist_m: np.ndarray
    slope_percent: np.ndarray
    metadata: dict[str, Any]


def derive_hydrology(dem: np.ndarray, metadata: dict[str, Any]) -> Hydrology:
    """Run the steps of process_dem from the DEM to the slope.

    Every call computes new arrays. A function that changes its inputs in place needs
    copies when the old and the new code run on one Hydrology.
    """
    filled_dem, fdir, acc, flw = process_hydrology_pyflwdir(dem, metadata)
    flow_dist_m = flw.stream_distance(unit="m").reshape(filled_dem.shape)
    dx, dy = _compute_gradients(
        filled_dem, metadata["cellsize"], metadata["nodata_value"]
    )
    slope_percent = compute_slope_from_gradients(dx, dy)
    return Hydrology(
        filled_dem=filled_dem,
        fdir=fdir,
        acc=acc,
        flw=flw,
        flow_dist_m=flow_dist_m,
        slope_percent=slope_percent,
        metadata=metadata,
    )


def subcatchments(
    hydrology: Hydrology, threshold_m2: int
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    """Delineate the sub-catchments of a threshold as process_dem does.

    Returns
    -------
    tuple[np.ndarray, np.ndarray, list[dict]]
        The label raster (int32 segment indices, 0 = none), the stream mask of the
        threshold and the stream segments with their downstream links.
    """
    metadata = hydrology.metadata
    nodata = metadata["nodata_value"]
    threshold_cells = max(1, int(threshold_m2 / metadata["cellsize"] ** 2))
    strahler = compute_strahler_from_fdir(hydrology.flw, hydrology.acc, threshold_cells)
    labels = np.zeros_like(hydrology.filled_dem, dtype=np.int32)
    segments = vectorize_streams(
        hydrology.filled_dem,
        hydrology.fdir,
        hydrology.acc,
        hydrology.slope_percent,
        strahler,
        metadata,
        threshold_cells,
        label_raster_out=labels,
    )
    delineate_subcatchments(hydrology.flw, labels, hydrology.filled_dem, nodata)
    compute_downstream_links(segments, labels, hydrology.fdir, metadata)
    stream_mask = (hydrology.acc >= threshold_cells) & (hydrology.filled_dem != nodata)
    return labels, stream_mask, segments


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


@dataclass
class SplitScene:
    """A synthetic DEM cut into PGW-like owners, and the run of the whole raster."""

    dem: np.ndarray
    metadata: dict[str, Any]
    whole: Hydrology
    # Owner (1-based) of every cell with DEM data, 0 elsewhere
    owners: np.ndarray
    # Cells on or beside a border between owners
    border: np.ndarray
    # The DEM as a GeoTIFF
    dem_path: Path


def write_dem_geotiff(path: Path, dem: np.ndarray, metadata: dict[str, Any]) -> Path:
    """Write a DEM of the tests as a float32 GeoTIFF in EPSG:2180."""
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=dem.shape[0],
        width=dem.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=metadata["transform"],
        nodata=NODATA,
    ) as dst:
        dst.write(dem, 1)
    return path


def split_scene(tmp_path: Path, units: int, holes: bool) -> SplitScene:
    """Cut the synthetic DEM into 2 or 3 owners that straddle its hard features.

    The owners 1 and 2 meet on a wavy seam through the closed basin and the plateau of
    the DEM; owner 3 (``units == 3``) lies south of row 82. The scene asserts what it
    exists for: with ``holes``, repaired nodata holes that carry the flow across the
    seam; a basin that the fill raises on both sides of the seam; hillslope leakage;
    and D8 crossings in both directions between owners 1 and 2, a cycle of the owner
    graph in an acyclic flow.
    """
    dem, metadata = synthetic_dem(
        nrows=121, ncols=131, seed=12, nodata_border=False, holes=holes
    )
    if holes:
        seam_col = 72 + round(6 * np.sin(23 / 7))
        dem[23, seam_col] = NODATA
    whole = derive_hydrology(dem, metadata)
    # The baseline fills internal holes for routing and restores DEM nodata afterward;
    # D8 and accumulation must still traverse those temporarily patched cells.
    if holes:
        assert np.any((dem == NODATA) & (whole.fdir > 0))
        assert whole.fdir[23, seam_col] > 0  # patched routing at the seam
    owners = np.empty(dem.shape, dtype=np.uint8)
    for row in range(dem.shape[0]):
        split = 72 + round(6 * np.sin(row / 7))
        owners[row, :split] = 1
        owners[row, split:] = 2
    if units == 3:
        owners[82:, :] = 3
    owners[dem == NODATA] = 0
    # The closed basin and plateau both straddle owner 1/2, rather than
    # testing only unrelated slopes away from the shared boundary.
    assert owners[59, 71] != owners[59, 78]
    assert owners[48, 69] != owners[48, 75]
    border = np.zeros(dem.shape, dtype=bool)
    vertical = owners[:, 1:] != owners[:, :-1]
    border[:, 1:] |= vertical
    border[:, :-1] |= vertical
    horizontal = owners[1:, :] != owners[:-1, :]
    border[1:, :] |= horizontal
    border[:-1, :] |= horizontal
    basin_border = border[55:65, 68:82]
    filled_basin = whole.filled_dem[55:65, 68:82] > dem[55:65, 68:82]
    assert np.any(basin_border & filled_basin)
    assert np.any(border[48:52, 68:76])
    first, second = np.nonzero(whole.fdir > 0)
    crosses = []
    for found_row, found_col in zip(first, second, strict=True):
        row, col = int(found_row), int(found_col)
        # Count actual D8 crossings to prove both directions of the quotient cycle.
        if int(whole.fdir[row, col]) not in D8_DIRECTIONS:
            continue
        dr, dc = D8_DIRECTIONS[int(whole.fdir[row, col])]
        tr, tc = row + dr, col + dc
        if (
            0 <= tr < dem.shape[0]
            and 0 <= tc < dem.shape[1]
            and owners[row, col] != owners[tr, tc]
        ):
            crosses.append(
                (int(owners[row, col]), int(owners[tr, tc]), int(whole.acc[row, col]))
            )
    assert any(area < 40 for _a, _b, area in crosses), "hillslope leakage is exercised"
    assert (1, 2) in {(a, b) for a, b, _ in crosses}
    assert (2, 1) in {(a, b) for a, b, _ in crosses}, "unit-graph cycle is exercised"
    path = write_dem_geotiff(tmp_path / "dem.tif", dem, metadata)
    return SplitScene(dem, metadata, whole, owners, border, path)


def write_pgw_geopackage(
    path: Path, scene: SplitScene, codes: tuple[str, ...]
) -> tuple[str, ...]:
    """Write the owners of a scene as a Kartograf-like PGW GeoPackage.

    The polygons are the cells of each owner, so rasterizing them on the grid of the
    DEM gives the owners of the scene. The owners but the last are river catchments,
    the last one is a remaining area (the layers of ``core.unit_ownership``). Returns
    the codes of the owners.
    """
    transform = scene.metadata["transform"]
    count = int(scene.owners.max())
    assert len(codes) == count
    layers: dict[str, list[tuple[str, MultiPolygon]]] = {
        "zlewnie_jcwp_rzecznych": [],
        "pozostale_obszary_jcwp": [],
    }
    for owner, code in enumerate(codes, start=1):
        cells = (scene.owners == owner).astype(np.uint8)
        parts = [
            shape(geometry)
            for geometry, value in shapes(cells, mask=cells > 0, transform=transform)
        ]
        layer = "pozostale_obszary_jcwp" if owner == count else "zlewnie_jcwp_rzecznych"
        layers[layer].append((code, MultiPolygon(parts)))
    for name, items in layers.items():
        with fiona.open(
            path,
            "w",
            driver="GPKG",
            layer=name,
            crs="EPSG:2180",
            schema={"geometry": "MultiPolygon", "properties": {"MS_KOD": "str"}},
        ) as sink:
            for code, geometry in items:
                sink.write(
                    {
                        "geometry": geometry.__geo_interface__,
                        "properties": {"MS_KOD": code},
                    }
                )
    return codes


Network = tuple[dict[int, list[dict[str, Any]]], dict[int, list[dict[str, Any]]]]


def assert_same_network(actual: Network, expected: Network) -> None:
    """Assert two runs gave the same stream network and catchment graph.

    Each network is the stream segments and the sub-catchments (``vectorize_streams``
    and ``polygonize_subcatchments`` rows) by threshold, as handed to the database.

    The runs agree up to the renumbering of ``segment_idx`` per threshold: a segment
    is told by its geometry (the coordinates of its cells, unique in a network), the
    numbering of the actual run must be a one-to-one map of the expected one and dense
    from 1, and every other column, the sub-catchment of each segment and the
    downstream link (``downstream_segment_idx``) of each of them must be equal under
    that map.
    """
    actual_segments, actual_catchments = actual
    expected_segments, expected_catchments = expected
    assert list(actual_segments) == list(expected_segments)
    assert list(actual_catchments) == list(expected_catchments)
    for threshold, wanted in expected_segments.items():
        found_segments = actual_segments[threshold]
        where = f"threshold {threshold} m2"
        assert len(found_segments) == len(wanted), where
        by_geometry = {
            tuple(segment["coords"]): i for i, segment in enumerate(found_segments, 1)
        }
        assert len(by_geometry) == len(found_segments), f"{where}: a duplicate"
        renumber: dict[int, int] = {}
        for old, segment in enumerate(wanted, 1):
            renumber[old] = by_geometry[tuple(segment["coords"])]
        assert sorted(renumber.values()) == list(range(1, len(wanted) + 1)), where

        def mapped(index: int | None, renumber: dict[int, int] = renumber) -> Any:
            """The new number of a segment; None, which drains out of the area."""
            return None if index is None else renumber[index]

        for old, segment in enumerate(wanted, 1):
            found = found_segments[renumber[old] - 1]
            keys = set(segment) - {"downstream_segment_idx", "_outlet_rc"}
            assert set(found) - {"downstream_segment_idx", "_outlet_rc"} == keys
            for key in sorted(keys):
                assert_identical(
                    found[key], segment[key], f"{where} segment {old} {key}"
                )
            assert found["_outlet_rc"] == segment["_outlet_rc"]
            # Only the thresholds with sub-catchments get links in process_dem
            if "downstream_segment_idx" in segment:
                assert found["downstream_segment_idx"] == mapped(
                    segment["downstream_segment_idx"]
                ), f"{where} segment {old}: downstream link"
        expected_sheds = expected_catchments.get(threshold, [])
        actual_sheds = {
            c["segment_idx"]: c for c in actual_catchments.get(threshold, [])
        }
        assert len(actual_sheds) == len(expected_sheds), where
        for shed in expected_sheds:
            old = shed["segment_idx"]
            found = actual_sheds[renumber[old]]
            keys = set(shed) - {"segment_idx", "downstream_segment_idx"}
            assert set(found) - {"segment_idx", "downstream_segment_idx"} == keys
            for key in sorted(keys):
                assert_identical(
                    found[key], shed[key], f"{where} catchment {old} {key}"
                )
            assert found["downstream_segment_idx"] == mapped(
                shed["downstream_segment_idx"]
            ), f"{where} catchment {old}: downstream link"
