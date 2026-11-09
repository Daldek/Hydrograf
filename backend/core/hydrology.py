"""
Hydrological processing: depression filling, flow direction, flow accumulation.

Core D8 flow direction constants, internal nodata hole filling, the interpolation
of the nodata the data encloses, stream burning, endorheic lake classification,
pyflwdir-based hydrology, sink fixing, and flow accumulation recomputation.
"""

import heapq
import logging
import math
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Sequence
from itertools import groupby
from pathlib import Path
from typing import Any

import numba
import numpy as np
from affine import Affine
from shapely.geometry.base import BaseGeometry

logger = logging.getLogger(__name__)

# D8 flow direction encoding (standard D8, compatible with pyflwdir/pysheds/ArcGIS)
# Direction values and their (row_offset, col_offset) for downstream cell
D8_DIRECTIONS = {
    1: (0, 1),  # E
    2: (1, 1),  # SE
    4: (1, 0),  # S
    8: (1, -1),  # SW
    16: (0, -1),  # W
    32: (-1, -1),  # NW
    64: (-1, 0),  # N
    128: (-1, 1),  # NE
}
VALID_D8_SET = frozenset(D8_DIRECTIONS.keys())

# D8 lookup tables for numba (no dicts in njit), indexed by code 0-255: whether
# the code is a D8 direction, and the row and column offsets of its downstream cell
D8_VALID = np.zeros(256, dtype=np.bool_)
D8_ROW_OFFSET = np.zeros(256, dtype=np.int32)
D8_COL_OFFSET = np.zeros(256, dtype=np.int32)
for _code, (_drow, _dcol) in D8_DIRECTIONS.items():
    D8_VALID[_code] = True
    D8_ROW_OFFSET[_code] = _drow
    D8_COL_OFFSET[_code] = _dcol

# What the stream burning takes from a BDOT10k GeoPackage (``dem.stream_burning``):
# "all" burns every line of OT_SWRS_L, OT_SWKN_L and OT_SWRM_L; "main" only the main
# watercourses (see _select_burned_features). OT_PTWP_A is burned in both.
STREAM_BURNING_MODES = ("all", "main")
_MAIN_COURSE = "ciek główny"
_RIVER = "rzeka"
# The attributes of a burned feature that the direction of a line reads (ADR-077)
STREAM_ATTRIBUTES = ("IDENTYFIKATORMPHP", "NAZWA", "CECHAGEOMETRII")

# Passes of fill_internal_nodata_holes: a repaired cell lies at most this many cells
# from a cell of the original DEM data
HOLE_FILL_PASSES = 3
# Cells of data read around an enclosed nodata area (interpolate_enclosed_nodata)
_ENCLOSED_RIM_CELLS = 2


def fill_internal_nodata_holes(
    dem: np.ndarray,
    nodata: float,
    min_valid_neighbors: int = 5,
    max_iterations: int = HOLE_FILL_PASSES,
    *,
    overwrite: bool = False,
) -> tuple[np.ndarray, int]:
    """
    Fill internal nodata holes of a DEM.

    In each pass a nodata cell with at least ``min_valid_neighbors`` valid cells
    among its 8 neighbours (cells outside the raster are not valid) gets the mean
    of those neighbours, all from the DEM before the pass; the passes stop when
    no cell is filled. Cells at the edge of large nodata areas and the inside of
    large holes stay nodata. A numba pass per iteration with memory per filled
    cell; the results equal bit for bit those of the scipy generic_filter
    version it replaced (the mean added up as np.mean does).

    Parameters
    ----------
    dem : np.ndarray
        Input DEM array
    nodata : float
        NoData value
    min_valid_neighbors : int
        Valid neighbours (of 8) for a nodata cell to be filled
    max_iterations : int
        Maximum number of passes
    overwrite : bool
        Repair the holes in ``dem`` itself instead of a copy (the memory of a
        whole DEM less); the returned DEM is then ``dem``.

    Returns
    -------
    tuple
        (patched_dem, total_filled): the filled DEM and the number of cells filled
    """
    patched = dem if overwrite else dem.copy()
    total_filled = 0
    # NumPy compares the DEM with nodata in this type; the neighbour means
    # compare in float64, the values of scipy's generic_filter
    nodata_value = np.result_type(dem.dtype, nodata).type(nodata)

    for iteration in range(max_iterations):
        cells, means = _fillable_holes(
            patched, nodata_value, float(nodata), min_valid_neighbors
        )
        if cells.size == 0:
            break
        patched.ravel()[cells] = means
        total_filled += cells.size

        logger.debug(
            f"  fill_internal_nodata_holes iteration {iteration + 1}: "
            f"filled {cells.size} cells"
        )

    return patched, total_filled


@numba.njit(cache=True)
def _fillable_holes(
    dem: np.ndarray,
    nodata: Any,
    nodata_f64: float,
    min_valid_neighbors: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return the flat indices of the fillable nodata cells and their means."""
    nrows, ncols = dem.shape
    values = np.empty(8, dtype=np.float64)
    count = 0
    for row in range(nrows):
        for col in range(ncols):
            if dem[row, col] == nodata:
                n_valid, _ = _valid_neighbours(
                    dem, row, col, nodata, nodata_f64, values
                )
                if n_valid >= min_valid_neighbors:
                    count += 1
    cells = np.empty(count, dtype=np.int64)
    means = np.empty(count, dtype=np.float64)
    count = 0
    for row in range(nrows):
        for col in range(ncols):
            if dem[row, col] != nodata:
                continue
            n_valid, n_values = _valid_neighbours(
                dem, row, col, nodata, nodata_f64, values
            )
            if n_valid < min_valid_neighbors:
                continue
            cells[count] = row * ncols + col
            # Without valid neighbours (min_valid_neighbors 0) a cell keeps nodata
            means[count] = (
                _mean_as_numpy(values, n_values)
                if n_values > 0
                else np.float64(dem[row, col])
            )
            count += 1
    return cells, means


@numba.njit(cache=True)
def _valid_neighbours(
    dem: np.ndarray,
    row: int,
    col: int,
    nodata: Any,
    nodata_f64: float,
    values: np.ndarray,
) -> tuple[int, int]:
    """Count the valid neighbours of a cell; put their values in ``values``.

    The count compares with ``nodata`` in the type of NumPy's ``dem != nodata``;
    the values (row by row through the 3 x 3 window, as generic_filter gives
    them) are compared in float64. Returns the count and the number of values.
    """
    nrows, ncols = dem.shape
    n_valid = 0
    n_values = 0
    for drow in range(-1, 2):
        for dcol in range(-1, 2):
            r, c = row + drow, col + dcol
            if (drow == 0 and dcol == 0) or not (0 <= r < nrows and 0 <= c < ncols):
                continue
            if dem[r, c] != nodata:
                n_valid += 1
            value = np.float64(dem[r, c])
            if value != nodata_f64:
                values[n_values] = value
                n_values += 1
    return n_valid, n_values


@numba.njit(cache=True)
def _mean_as_numpy(values: np.ndarray, n: int) -> float:
    """Return np.mean(values[:n]) for n <= 8, added up in the same order.

    NumPy starts its sum at 0.0 and adds fewer than 8 values one by one, and 8
    values in pairs.
    """
    if n == 8:
        total = ((values[0] + values[1]) + (values[2] + values[3])) + (
            (values[4] + values[5]) + (values[6] + values[7])
        )
    else:
        total = 0.0
        for k in range(n):
            total += values[k]
    return float((0.0 + total) / n)


def interpolate_enclosed_nodata(
    dem: np.ndarray, nodata: float, *, overwrite: bool = False
) -> tuple[np.ndarray, int]:
    """Fill every nodata area that the data of a DEM encloses, from the data around it.

    The depression fill takes every cell next to nodata for an outlet (pyflwdir's
    ``outlets="edge"``, ``fill_depressions_d8``), so a nodata area inside the data,
    such as a sheet missing from a mosaic, drains the land around it: an endorheic
    area. ``fill_internal_nodata_holes`` repairs small holes only. Here every nodata
    area that does not reach the frame of the raster (8-connected, as pyflwdir's
    neighbours) takes values interpolated from the data around it (GDAL's inverse
    distance weighting, ``rasterio.fill.fillnodata``); the depression fill then fills
    it like any ground, and the outlets left lie on the outer edge of the data. The
    nodata that reaches the frame stays.

    Parameters
    ----------
    dem : np.ndarray
        The DEM.
    nodata : float
        Its nodata value (NaN too).
    overwrite : bool
        Fill ``dem`` itself instead of a copy (the memory of a whole DEM less); the
        returned DEM is then ``dem``.

    Returns
    -------
    tuple
        (filled_dem, cells_filled): the DEM and the number of nodata cells filled.
    """
    from rasterio.fill import fillnodata
    from scipy import ndimage

    patched = dem if overwrite else dem.copy()
    valid = ~np.isnan(dem) if np.isnan(nodata) else dem != nodata
    eight = np.ones((3, 3), dtype=bool)
    enclosed = ndimage.binary_fill_holes(valid, structure=eight)
    enclosed &= ~valid
    rows = np.flatnonzero(enclosed.any(axis=1))
    if rows.size == 0:
        return patched, 0
    cols = np.flatnonzero(enclosed.any(axis=0))
    # The box of every enclosed area and its rim: labelled there, not on the grid
    nrows, ncols = dem.shape
    rim = _ENCLOSED_RIM_CELLS
    box = np.s_[
        max(int(rows[0]) - rim, 0) : min(int(rows[-1]) + 1 + rim, nrows),
        max(int(cols[0]) - rim, 0) : min(int(cols[-1]) + 1 + rim, ncols),
    ]
    labels, _ = ndimage.label(enclosed[box], structure=eight)
    del enclosed
    patched_box, valid_box = patched[box], valid[box]
    height, width = labels.shape
    filled = 0
    for label, (area_rows, area_cols) in enumerate(
        ndimage.find_objects(labels), start=1
    ):
        window = np.s_[
            max(area_rows.start - rim, 0) : min(area_rows.stop + rim, height),
            max(area_cols.start - rim, 0) : min(area_cols.stop + rim, width),
        ]
        area = labels[window] == label
        values = fillnodata(
            patched_box[window].copy(),
            mask=valid_box[window].astype(np.uint8),
            max_search_distance=float(sum(area.shape)),
            smoothing_iterations=0,
        )
        patched_box[window][area] = values[area]
        filled += int(np.count_nonzero(area))
    return patched, filled


def raise_buildings_in_dem(
    dem: np.ndarray,
    transform: Affine,
    crs_epsg: int,
    building_gpkg: str | None,
    building_raise_m: float = 5.0,
    *,
    nodata: float,
) -> np.ndarray:
    """Raise DEM elevation under building footprints.

    Prevents unrealistic flow paths through buildings. Only cells with data are
    raised: a cell equal to ``nodata`` under a building keeps it.
    """
    if building_gpkg is None:
        return dem

    import fiona
    from rasterio.features import rasterize
    from shapely.geometry import shape

    geometries = []
    with fiona.open(building_gpkg) as src:
        for feat in src:
            geom = shape(feat["geometry"])
            if geom.is_valid and not geom.is_empty:
                geometries.append(geom)

    if not geometries:
        return dem

    mask = rasterize(
        [(g, 1) for g in geometries],
        out_shape=dem.shape,
        transform=transform,
        fill=0,
        dtype=np.uint8,
    )

    # rasterize burns 1 into a background of 0: the mask is a valid boolean view
    raised = mask.view(np.bool_)
    np.logical_and(raised, dem != nodata, out=raised)
    dem[raised] += building_raise_m
    cells_raised = int(np.count_nonzero(raised))
    logger.info(
        f"Building raising: {cells_raised} cells raised "
        f"by {building_raise_m}m ({len(geometries)} buildings)"
    )
    return dem


def _non_empty(gdf: Any, column: str) -> Any:
    """Boolean Series: the column holds a non-blank text (False if it is missing)."""
    import pandas as pd

    if column not in gdf.columns:
        return pd.Series(False, index=gdf.index)
    values = gdf[column]
    return values.notna() & (values.astype(str).str.strip() != "")


def _equals(gdf: Any, column: str, value: str) -> Any:
    """Boolean Series: the column, stripped, equals ``value`` (False if missing)."""
    import pandas as pd

    if column not in gdf.columns:
        return pd.Series(False, index=gdf.index)
    return gdf[column].astype("string").str.strip().eq(value).fillna(False)


def _stripped(gdf: Any, column: str) -> list[str]:
    """Return the column as stripped text, '' where the value or column is missing."""
    if column not in gdf.columns:
        return [""] * len(gdf)
    return list(gdf[column].fillna("").astype(str).str.strip())


def _select_burned_features(gdf: Any, layer: str | None, stream_burning: str) -> Any:
    """Keep the features of one layer that ``stream_burning`` burns.

    ``"all"`` keeps everything. ``"main"`` keeps, of the BDOT10k line layers,
    OT_SWRS_L with ``PRZEBIEG = 'ciek główny'`` that is a river (``RODZAJ =
    'rzeka'``) or carries an MPHP identifier (``IDENTYFIKATORMPHP``), OT_SWKN_L
    with an MPHP identifier, and no OT_SWRM_L. Water polygons (PTWP) and layers
    that are not BDOT10k streams are kept whole.
    """
    if stream_burning == "all":
        return gdf
    code = (layer or "").upper()
    if "SWRM" in code:
        return gdf.iloc[0:0]
    if "SWRS" in code:
        keep = _equals(gdf, "PRZEBIEG", _MAIN_COURSE) & (
            _equals(gdf, "RODZAJ", _RIVER) | _non_empty(gdf, "IDENTYFIKATORMPHP")
        )
        return gdf[keep]
    if "SWKN" in code:
        return gdf[_non_empty(gdf, "IDENTYFIKATORMPHP")]
    return gdf


def _load_stream_features(
    streams_path: str | Path,
    transform: Affine,
    dem_shape: tuple[int, int],
    stream_burning: str = "all",
) -> Any:
    """Load the burned features of a BDOT10k GeoPackage/Shapefile with their attributes.

    Reads the SWRS/SWKN/SWRM/PTWP layers (the first layer when none is), keeps what
    ``stream_burning`` selects (``_select_burned_features``), reprojects to EPSG:2180
    and keeps the features that reach into the DEM extent: layer by layer, feature by
    feature, part by part. A (Multi)LineString gives a row per part of two or more
    points, a polygon or any other geometry one row as it is.

    Parameters
    ----------
    streams_path : str or Path
        Path to GeoPackage/Shapefile with stream line geometries
    transform : Affine
        Rasterio Affine transform for the DEM grid
    dem_shape : tuple[int, int]
        (nrows, ncols) of the DEM array
    stream_burning : str
        ``"all"`` (every line layer) or ``"main"`` (the main watercourses)

    Returns
    -------
    gpd.GeoDataFrame
        ``geometry`` and the ``STREAM_ATTRIBUTES`` of each row's feature as stripped
        text ('' where the value or the column is missing; OT_SWRM_L has neither
        ``IDENTYFIKATORMPHP`` nor ``CECHAGEOMETRII``), in EPSG:2180; empty with these
        columns when nothing is selected.
    """
    import fiona
    import geopandas as gpd
    from shapely.geometry import LineString, MultiLineString, box

    if stream_burning not in STREAM_BURNING_MODES:
        raise ValueError(
            f"stream_burning must be one of {STREAM_BURNING_MODES}, "
            f"not {stream_burning!r}"
        )

    streams_path = str(streams_path)
    nrows, ncols = dem_shape
    left, top = transform * (0, 0)
    right, bottom = transform * (ncols, nrows)
    dem_bounds = box(
        min(left, right),
        min(top, bottom),
        max(left, right),
        max(top, bottom),
    )

    try:
        layers = fiona.listlayers(streams_path)
    except Exception:
        layers = [None]

    stream_prefixes = ("SWRS", "SWKN", "SWRM", "PTWP")
    target_layers = [
        lyr for lyr in layers if lyr and any(p in lyr.upper() for p in stream_prefixes)
    ]
    if not target_layers:
        target_layers = layers[:1] if layers else []

    geoms: list[Any] = []
    attributes: dict[str, list[str]] = {column: [] for column in STREAM_ATTRIBUTES}
    for layer in target_layers:
        try:
            kwargs = {"layer": layer} if layer else {}
            gdf = gpd.read_file(streams_path, **kwargs)
        except Exception:
            continue
        gdf = _select_burned_features(gdf, layer, stream_burning)
        if gdf.empty:
            continue
        if gdf.crs and gdf.crs.to_epsg() != 2180:
            gdf = gdf.to_crs(epsg=2180)
        gdf = gdf[gdf.geometry.intersects(dem_bounds)]
        texts = [_stripped(gdf, column) for column in STREAM_ATTRIBUTES]
        for geom, *values in zip(gdf.geometry, *texts, strict=True):
            if geom is None or geom.is_empty:
                continue
            if isinstance(geom, MultiLineString):
                parts = [
                    part
                    for part in geom.geoms
                    if not part.is_empty and len(part.coords) >= 2
                ]
            elif isinstance(geom, LineString):
                parts = [geom] if len(geom.coords) >= 2 else []
            else:
                # Polygons (burned as areas) and any other geometry, as they are
                parts = [geom]
            for part in parts:
                geoms.append(part)
                for column, value in zip(STREAM_ATTRIBUTES, values, strict=True):
                    attributes[column].append(value)

    return gpd.GeoDataFrame(attributes, geometry=geoms, crs="EPSG:2180")


def _load_stream_geometries(
    streams_path: str | Path,
    transform: Affine,
    dem_shape: tuple[int, int],
    stream_burning: str = "all",
) -> list[Any]:
    """Return the geometries of ``_load_stream_features``, in their order."""
    return list(
        _load_stream_features(
            streams_path, transform, dem_shape, stream_burning
        ).geometry
    )


def burn_streams_into_dem(
    dem: np.ndarray,
    transform: Affine,
    streams_path: str | Path,
    burn_depth_m: float = 2.0,
    nodata: float = -9999.0,
    stream_burning: str = "all",
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    Wypalanie ciekow w DEM — obniza DEM wzdluz znanych ciekow.

    Wymusza zgodnosc modelu hydrologicznego z rzeczywista siecia rzeczna
    (np. BDOT10k) przed analiza hydrologiczna pyflwdir.

    Parameters
    ----------
    dem : np.ndarray
        Input DEM array
    transform : Affine
        Rasterio Affine transform for the DEM grid
    streams_path : Path
        Path to GeoPackage/Shapefile with stream line geometries
    burn_depth_m : float
        Depth to burn streams (meters), default 2.0
    nodata : float
        NoData value in DEM
    stream_burning : str
        ``"all"`` burns every BDOT10k line layer (SWRS, SWKN, SWRM); ``"main"``
        only the main watercourses (``_select_burned_features``). PTWP in both.

    Returns
    -------
    tuple
        (burned_dem, diagnostics) where diagnostics is a dict with:
        - cells_burned: number of DEM cells lowered
        - streams_loaded: number of stream features loaded
        - streams_in_extent: number of stream features intersecting DEM extent
    """
    from rasterio.features import rasterize

    diagnostics = {"cells_burned": 0, "streams_loaded": 0, "streams_in_extent": 0}
    burned = dem.copy()

    # 1. Load streams via shared helper
    geoms = _load_stream_geometries(streams_path, transform, dem.shape, stream_burning)
    diagnostics["streams_loaded"] = len(geoms)
    diagnostics["streams_in_extent"] = len(geoms)

    if not geoms:
        logger.info("Stream burning: no stream geometries loaded, skipping")
        return burned, diagnostics

    # 2. Rasterize streams onto DEM grid
    stream_mask = rasterize(
        [(geom, 1) for geom in geoms],
        out_shape=dem.shape,
        transform=transform,
        fill=0,
        dtype=np.uint8,
        all_touched=True,
    )

    # 3. Burn: lower DEM at stream cells (skip nodata)
    burn_cells = (stream_mask == 1) & (dem != nodata)
    burned[burn_cells] -= burn_depth_m
    diagnostics["cells_burned"] = int(np.sum(burn_cells))

    logger.info(
        "Stream burning (%s): %d cells burned (depth=%sm, streams=%d)",
        stream_burning,
        diagnostics["cells_burned"],
        burn_depth_m,
        diagnostics["streams_in_extent"],
    )

    return burned, diagnostics


def _bresenham(r0: int, c0: int, r1: int, c1: int) -> list[tuple[int, int]]:
    """Bresenham line rasterization between two pixel coordinates.

    Returns ordered list of (row, col) cells from (r0, c0) to (r1, c1).
    """
    dr = abs(r1 - r0)
    dc = abs(c1 - c0)
    sr = 1 if r1 > r0 else -1
    sc = 1 if c1 > c0 else -1
    err = dr - dc
    cells = []
    r, c = r0, c0
    while True:
        cells.append((r, c))
        if r == r1 and c == c1:
            break
        e2 = 2 * err
        if e2 > -dc:
            err -= dc
            r += sr
        if e2 < dr:
            err += dr
            c += sc
    return cells


def _cell_of(transform: Affine, x: float, y: float) -> tuple[int, int]:
    """Return the (row, col) of the raster cell that contains a point."""
    col, row = ~transform * (x, y)
    return math.floor(row), math.floor(col)


def _rasterize_line_ordered(
    line: BaseGeometry,
    transform: Affine,
    shape: tuple[int, int] | None = None,
) -> list[tuple[int, int]]:
    """Rasterize a LineString to an ordered sequence of (row, col) cells.

    Uses Bresenham between the cells that contain consecutive vertices, the cells
    the stream burning lowers (ADR-072). Deduplicates cells at segment junctions.
    Optionally clips to raster shape.

    Extension vs spec: added optional ``shape`` for bounds clipping.
    """
    coords = list(line.coords)
    if len(coords) < 2:
        return []

    cells: list[tuple[int, int]] = []
    for i in range(len(coords) - 1):
        r0, c0 = _cell_of(transform, *coords[i][:2])
        r1, c1 = _cell_of(transform, *coords[i + 1][:2])
        segment = _bresenham(r0, c0, r1, c1)
        if cells and segment and segment[0] == cells[-1]:
            segment = segment[1:]
        cells.extend(segment)

    if shape is not None:
        nrows, ncols = shape
        cells = [(r, c) for r, c in cells if 0 <= r < nrows and 0 <= c < ncols]

    return cells


# The direction of a burned line is the first that these rules give (ADR-077): towards
# the mouth of its MPHP watercourse; down the DEM of its whole watercourse where that
# watercourse is digitized both ways, when the DEM along it rises or falls by more
# than WATERCOURSE_RISE_M between the lowest cells of its first and last quarter;
# against its digitizing when the DEM along the line itself rises that way by more
# than REVERSED_LINE_RISE_M (ADR-072); else the way it is digitized (BDOT10k
# digitizes a watercourse downstream). A profile shorter than
# REVERSED_LINE_MIN_LENGTH_M, whose quarters are no longer than an embankment, rises
# by nothing
REVERSED_LINE_RISE_M = 2.0
REVERSED_LINE_MIN_LENGTH_M = 200.0
WATERCOURSE_RISE_M = 0.5
# CECHAGEOMETRII of an artificial connector, a line drawn through a lake: the DEM
# along it is a water surface and never gives its direction
CONNECTOR = "sztuczny łącznik"
# A line that ends inside the data where no line goes on continues into the nearest
# line that begins where no line ends, within LINE_GAP_M: two features of one
# watercourse digitized apart (ADR-072)
LINE_GAP_M = 50.0


def _line_nodes(
    geometries: list[Any],
    transform: Affine,
    snap_tolerance_px: int = 1,
) -> tuple[dict[int, tuple[int, int]], dict[int, tuple[int, int]]]:
    """Give the ends of the stream lines the nodes of their network.

    Each end is snapped to the raster cell that contains it, the first or last cell of
    the line (``_rasterize_line_ordered``); an end within ``snap_tolerance_px`` cells
    (in rows and in columns) of a node already made joins that node, the first one
    made; the ends are taken line by line, the first point of a line before its last.

    Returns
    -------
    tuple
        ({line index: (node of its first point, node of its last point)}, the first
        point being where the line begins as digitized; {node: (row, col) of its cell})
    """
    node_of_cell: dict[tuple[int, int], int] = {}

    def node(x: float, y: float) -> int:
        cell = _cell_of(transform, x, y)
        for (node_row, node_col), node_id in node_of_cell.items():
            if (
                abs(node_row - cell[0]) <= snap_tolerance_px
                and abs(node_col - cell[1]) <= snap_tolerance_px
            ):
                return node_id
        node_of_cell[cell] = len(node_of_cell)
        return node_of_cell[cell]

    ends: dict[int, tuple[int, int]] = {}
    for idx, geom in enumerate(geometries):
        coords = list(geom.coords)
        if len(coords) < 2:
            continue
        first = node(*coords[0][:2])
        ends[idx] = (first, node(*coords[-1][:2]))
    return ends, {node_id: cell for cell, node_id in node_of_cell.items()}


def _gap_joins(
    ends: dict[int, tuple[int, int]],
    node_cells: dict[int, tuple[int, int]],
    dem: np.ndarray,
    nodata: float,
    cellsize_m: float,
) -> list[tuple[int, int]]:
    """Find the gaps between the features of a watercourse that the smoothing bridges.

    A dead end is a node where lines end and none begins, on a cell with data: the
    line stops inside the data, and its descent would end in a pit that the fill
    raises until it spills, maybe out at the upstream crossing of the river. An open
    start is a node where lines begin and none ends. Each dead end is joined to the
    nearest open start within LINE_GAP_M (between their cells) whose lines do not lead
    back to it, the joins made before included; a stream that ends in the data without
    one stays a dead end.

    Returns
    -------
    list
        (dead end, open start) pairs, by dead end.
    """
    downstream: dict[int, list[int]] = defaultdict(list)
    incoming: Counter[int] = Counter()
    for first, last in ends.values():
        if first != last:
            downstream[first].append(last)
            incoming[last] += 1
    starts = sorted(node for node in downstream if not incoming[node])
    if not starts:
        return []
    start_cells = np.array([node_cells[node] for node in starts], dtype=np.float64)

    def leads_to(source: int, target: int) -> bool:
        seen = {source}
        queue = deque([source])
        while queue:
            node = queue.popleft()
            if node == target:
                return True
            for below in downstream[node]:
                if below not in seen:
                    seen.add(below)
                    queue.append(below)
        return False

    nrows, ncols = dem.shape
    joins = []
    for node in sorted(node for node in incoming if not downstream[node]):
        row, col = node_cells[node]
        if not (0 <= row < nrows and 0 <= col < ncols) or dem[row, col] == nodata:
            continue
        gaps_m = np.hypot(start_cells[:, 0] - row, start_cells[:, 1] - col) * cellsize_m
        for nearest in np.argsort(gaps_m, kind="stable"):
            if gaps_m[nearest] > LINE_GAP_M:
                break
            start = starts[nearest]
            if not leads_to(start, node):
                joins.append((node, start))
                downstream[node].append(start)
                break
    return joins


def _quarter_rise(values: np.ndarray, spacing_m: float) -> float | None:
    """Return how much a DEM profile rises from its first to its last quarter.

    ``values`` are DEM values ``spacing_m`` apart. The rise is the lowest value of the
    last quarter less the lowest of the first (a quarter has at least one value), so
    a bridge or an embankment inside a quarter does not count. None for fewer than
    two values or a profile shorter than REVERSED_LINE_MIN_LENGTH_M.
    """
    if values.size < 2 or values.size * spacing_m < REVERSED_LINE_MIN_LENGTH_M:
        return None
    quarter = max(values.size // 4, 1)
    return float(values[-quarter:].min()) - float(values[:quarter].min())


def _rises_downstream(values: np.ndarray, cellsize_m: float) -> bool:
    """Say whether the DEM along a stream line rises the way it is digitized.

    ``values`` are the DEM values of the line's cells with data, in the order the line
    is digitized; they rise by more than REVERSED_LINE_RISE_M between the quarters
    (``_quarter_rise``), which a water surface on a flat valley does not (ADR-072).
    """
    rise_m = _quarter_rise(values, cellsize_m)
    return rise_m is not None and rise_m > REVERSED_LINE_RISE_M


def _mouth_directions(
    lines: Sequence[int],
    ends: dict[int, tuple[int, int]],
    mphp: Sequence[str],
    lengths_m: dict[int, float],
) -> dict[int, bool]:
    """Orient the lines of each MPHP watercourse towards its mouth (ADR-077, rule 1).

    The watercourse of the MPHP identifier K meets its receiver at a node of K's lines
    where a line of ``ends`` whose identifier is a proper prefix of K begins or ends
    (a tributary, whose identifier K is a prefix of, is no receiver). Along K's lines,
    by their lengths, a line flows from its node farther from such a node, the
    nearest one, to its nearer node.

    Parameters
    ----------
    lines : sequence of int
        The lines to orient: those of ``ends`` whose two nodes differ.
    ends : dict
        {line: (node of its first point, node of its last point)} of every line, as
        digitized.
    mphp : sequence of str
        The MPHP identifier of each line, '' without one.
    lengths_m : dict
        The length of each line.

    Returns
    -------
    dict
        {line: whether it is digitized away from the mouth} for each line of an MPHP
        watercourse whose two nodes are reached from its mouth at different distances.
    """
    codes_at: dict[int, set[str]] = defaultdict(set)
    for line, (first, last) in ends.items():
        if mphp[line]:
            codes_at[first].add(mphp[line])
            codes_at[last].add(mphp[line])
    members: dict[str, list[int]] = defaultdict(list)
    for line in lines:
        if mphp[line]:
            members[mphp[line]].append(line)
    decided: dict[int, bool] = {}
    for code, own in members.items():
        neighbours: dict[int, list[tuple[int, float]]] = defaultdict(list)
        for line in own:
            first, last = ends[line]
            neighbours[first].append((last, lengths_m[line]))
            neighbours[last].append((first, lengths_m[line]))
        mouths = [
            node
            for node in neighbours
            if any(other != code and code.startswith(other) for other in codes_at[node])
        ]
        # Dijkstra from all the mouths at once
        distance = dict.fromkeys(mouths, 0.0)
        heap = [(0.0, node) for node in mouths]
        heapq.heapify(heap)
        while heap:
            reached, node = heapq.heappop(heap)
            if reached > distance[node]:
                continue
            for other, length in neighbours[node]:
                if reached + length < distance.get(other, math.inf):
                    distance[other] = reached + length
                    heapq.heappush(heap, (reached + length, other))
        for line in own:
            first, last = ends[line]
            if (
                first in distance
                and last in distance
                and distance[first] != distance[last]
            ):
                decided[line] = distance[first] < distance[last]
    return decided


def _watercourse_chains(
    lines: Sequence[int],
    ends: dict[int, tuple[int, int]],
    keys: dict[int, str],
) -> list[list[tuple[int, bool]]]:
    """Join the lines of each watercourse end to end.

    A node joins two lines of one key (their watercourse) when exactly two lines of
    that key have an end at it. Each chain is walked once, from its first line in the
    order of ``lines``: back through the joins to a free end (or round a loop until a
    line repeats), then forward to the other free end.

    Returns
    -------
    list
        The chains, each as (line, whether it is digitized the way of the walk) in the
        order of the walk. A line with the key '' is in none.
    """
    at_node: dict[tuple[int, str], list[int]] = defaultdict(list)
    for line in lines:
        if keys[line]:
            first, last = ends[line]
            at_node[(first, keys[line])].append(line)
            at_node[(last, keys[line])].append(line)
    goes_on: dict[int, dict[int, int]] = defaultdict(dict)
    for (node, _), members in at_node.items():
        if len(members) == 2:
            one, other = members
            goes_on[one][node] = other
            goes_on[other][node] = one

    def far_node(line: int, node: int) -> int:
        first, last = ends[line]
        return last if first == node else first

    walked: set[int] = set()
    chains = []
    for start in lines:
        if start in walked or not keys[start]:
            continue
        line, entry, seen = start, ends[start][0], {start}
        while entry in goes_on[line] and goes_on[line][entry] not in seen:
            line = goes_on[line][entry]
            seen.add(line)
            entry = far_node(line, entry)
        chain = []
        node = entry
        while True:
            walked.add(line)
            chain.append((line, ends[line][0] == node))
            node = far_node(line, node)
            following = goes_on[line].get(node)
            if following is None or following in walked:
                break
            line = following
        chains.append(chain)
    return chains


def _profile_of_walk(
    run: Sequence[tuple[int, bool]],
    values: dict[int, np.ndarray],
    connector: Sequence[bool],
) -> np.ndarray:
    """Return the DEM along lines in the order of a walk, without the connectors.

    ``run`` holds (line, whether it is digitized the way of the walk).
    """
    parts = [
        values[line] if forward else values[line][::-1]
        for line, forward in run
        if not connector[line]
    ]
    return np.concatenate(parts) if parts else np.empty(0)


def _watercourse_directions(
    lines: Sequence[int],
    ends: dict[int, tuple[int, int]],
    mphp: Sequence[str],
    names: Sequence[str],
    values: dict[int, np.ndarray],
    connector: Sequence[bool],
    spacing_m: float,
) -> tuple[dict[int, bool], list[list[int]]]:
    """Orient the lines of watercourses digitized both ways (ADR-077, rule 2).

    A watercourse is the lines of one MPHP identifier, else of one name, joined end to
    end (``_watercourse_chains``); one whose lines are all digitized the same way is
    not decided. The DEM along the whole chain, in the order of the walk and without
    its artificial connectors, decides when it rises or falls by more than
    WATERCOURSE_RISE_M between the quarters (``_quarter_rise``): its lower end is
    downstream. A block, a run of lines of the walk digitized the same way, digitized
    downstream keeps its direction; one digitized upstream is reversed, unless the DEM
    along its own lines (without connectors, the way they are digitized) falls by more
    than REVERSED_LINE_RISE_M: then the block is not decided (the guard), as the DEM
    along a line overrides its digitizing by that much (ADR-072). A connector takes the
    decision of its block.

    Returns
    -------
    tuple
        ({line: whether it is reversed} of the lines decided; the blocks kept by the
        guard, each as its lines)
    """
    keys: dict[int, str] = {}
    for line in lines:
        if mphp[line]:
            keys[line] = f"M:{mphp[line]}"
        elif names[line]:
            keys[line] = f"N:{names[line]}"
        else:
            keys[line] = ""
    decided: dict[int, bool] = {}
    kept: list[list[int]] = []
    for chain in _watercourse_chains(lines, ends, keys):
        if len({forward for _, forward in chain}) < 2:
            continue
        rise_m = _quarter_rise(_profile_of_walk(chain, values, connector), spacing_m)
        if rise_m is None or abs(rise_m) <= WATERCOURSE_RISE_M:
            continue
        walk_downstream = rise_m < 0
        for forward, run in groupby(chain, key=lambda item: item[1]):
            block = list(run)
            if forward == walk_downstream:
                decided.update((line, False) for line, _ in block)
                continue
            walked = _profile_of_walk(block, values, connector)
            fall_m = _quarter_rise(walked if forward else walked[::-1], spacing_m)
            if fall_m is not None and fall_m < -REVERSED_LINE_RISE_M:
                kept.append([line for line, _ in block])
                continue
            decided.update((line, True) for line, _ in block)
    return decided, kept


def _line_directions(
    ends: dict[int, tuple[int, int]],
    values: dict[int, np.ndarray],
    lengths_m: dict[int, float],
    mphp: Sequence[str],
    names: Sequence[str],
    connector: Sequence[bool],
    spacing_m: float,
) -> tuple[dict[int, tuple[bool, str]], list[list[int]]]:
    """Decide the direction of each stream line by the rules of ADR-077.

    The first rule that decides a line gives its direction: ``"mouth"``, towards the
    mouth of its MPHP watercourse (``_mouth_directions``); ``"watercourse"``, down the
    DEM of its whole watercourse (``_watercourse_directions``); ``"rise"``, reversed
    when the DEM along it rises the way it is digitized by more than
    REVERSED_LINE_RISE_M (``_rises_downstream``, ADR-072), which never reverses an
    artificial connector; ``"digitized"``, the way it is digitized. Pure: the
    network, the attributes and the DEM values come in.

    Parameters
    ----------
    ends : dict
        {line: (node of its first point, node of its last point)}, as digitized.
    values : dict
        The DEM values of the cells of each line with data, in the digitized order.
    lengths_m : dict
        The length of each line.
    mphp, names : sequence of str
        The MPHP identifier and the name of each line, '' without one.
    connector : sequence of bool
        Whether each line is an artificial connector (``CONNECTOR``).
    spacing_m : float
        The distance between two values of a line (the cell size).

    Returns
    -------
    tuple
        ({line: (whether it is reversed, the rule)} for every line of ``ends`` whose
        two nodes differ; the blocks kept by the guard of rule 2, each as its lines)
    """
    lines = sorted(line for line, (first, last) in ends.items() if first != last)
    by_mouth = _mouth_directions(lines, ends, mphp, lengths_m)
    by_watercourse, kept = _watercourse_directions(
        lines, ends, mphp, names, values, connector, spacing_m
    )
    directions: dict[int, tuple[bool, str]] = {}
    for line in lines:
        if line in by_mouth:
            directions[line] = (by_mouth[line], "mouth")
        elif line in by_watercourse:
            directions[line] = (by_watercourse[line], "watercourse")
        elif not connector[line] and _rises_downstream(values[line], spacing_m):
            directions[line] = (True, "rise")
        else:
            directions[line] = (False, "digitized")
    return directions, kept


def _flow_order(ends: dict[int, tuple[int, int]]) -> tuple[list[int], int]:
    """Order the stream lines so each comes after every line ending at its first node.

    Kahn's algorithm over the nodes: a node is taken once every line ending at it is
    ordered, then the lines beginning at it, by index. A directed cycle has no such
    order: when no node can be taken, the first node of the lowest-numbered line left
    is taken as it is. A line that ends where it begins is left out.

    Returns
    -------
    tuple
        (the indices of the lines in that order, the number of lines ordered before a
        line ending at their first node because of a cycle)
    """
    lines = sorted(line for line, (first, last) in ends.items() if first != last)
    outgoing: dict[int, list[int]] = defaultdict(list)
    waiting: dict[int, int] = defaultdict(int)
    for line in lines:
        first, last = ends[line]
        outgoing[first].append(line)
        waiting[last] += 1
    order: list[int] = []
    ordered: set[int] = set()
    ready = deque(node for node in sorted(outgoing) if waiting[node] == 0)

    def take(node: int) -> int:
        taken = 0
        for line in outgoing[node]:
            if line in ordered:
                continue
            ordered.add(line)
            order.append(line)
            taken += 1
            last = ends[line][1]
            waiting[last] -= 1
            if waiting[last] == 0:
                ready.append(last)
        return taken

    out_of_order = 0
    next_line = 0
    while len(order) < len(lines):
        if ready:
            take(ready.popleft())
            continue
        while lines[next_line] in ordered:
            next_line += 1
        out_of_order += take(ends[lines[next_line]][0])
    return order, out_of_order


@numba.njit(cache=True)
def _descend_strictly(
    dem: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
    nodata: float,
    start: float,
) -> tuple[float, int, int, float, float]:
    """Lower the cells of a stream line so each lies strictly below the one before it.

    The cells are in the order of the flow and ``start`` is the value the line must
    begin below (+inf at a source). A cell higher than the lowest value before it (an
    obstruction: a bridge, an embankment) is cut to just below the cell before it;
    any other cell not below the cell before it is lowered by one float32 step, the
    resolution at which pyflwdir's depression fill orders the cells, so the profile
    has no flat. Cells without data are passed over.

    Returns
    -------
    tuple
        (the value of the last cell with data, or ``start`` without one; the cells
        cut; the cells lowered by a step; the largest cut [m]; the sum of the cuts [m])
    """
    running = start
    lowest = start
    cut = 0
    stepped = 0
    largest = 0.0
    total = 0.0
    for i in range(rows.size):
        value = dem[rows[i], cols[i]]
        if value == nodata:
            continue
        below = np.nextafter(np.float32(running), np.float32(-np.inf))
        if value > below:
            if value > lowest:
                cut += 1
                correction = value - below
                total += correction
                if correction > largest:
                    largest = correction
            else:
                stepped += 1
            dem[rows[i], cols[i]] = below
        if value < lowest:
            lowest = value
        running = dem[rows[i], cols[i]]
    return running, cut, stepped, largest, total


def smooth_streams_monotonic(
    dem: np.ndarray,
    transform: Affine,
    streams_path: str | Path,
    nodata: float = -9999.0,
    stream_burning: str = "all",
) -> tuple[np.ndarray, list[BaseGeometry], dict[str, Any]]:
    """Make every burned stream line descend strictly in the direction of its flow.

    The direction of a line is the first that the rules of ADR-077 give
    (``_line_directions``), on the DEM as it comes in: towards the mouth of its MPHP
    watercourse; down the DEM of its whole watercourse where the watercourse is
    digitized both ways; against its digitizing where the DEM along the line rises
    that way by more than REVERSED_LINE_RISE_M (ADR-072); else the way it is digitized
    (BDOT10k digitizes a watercourse downstream). An artificial connector through a
    lake never takes its direction from the DEM along it. No outlet is chosen from the
    DEM: a river that crosses the edge of the data leaves it at its downstream
    crossing, whichever of its two crossings is lower (ADR-072).

    The lines are taken in the order of the flow (``_flow_order``). A line begins
    below the lowest value the lines ending at its first node reached, and every cell
    of it with data ends strictly below the cell before it: a cell above is cut (a
    bridge, an embankment), a cell as high is lowered by one float32 step. A flat
    valley thus falls towards the downstream end by steps of micrometres, and the
    depression fill, which drains a flat towards whichever of its outlets it reaches
    first, cannot send it out of the data at the upstream crossing. A gap of up to
    LINE_GAP_M between two features of a watercourse is bridged by a straight run of
    cells that descends the same way (``_gap_joins``), so the descent does not end in
    a pit.

    Parameters
    ----------
    dem : np.ndarray
        Input DEM array (modified copy is returned)
    transform : Affine
        Rasterio Affine transform for the DEM grid
    streams_path : str or Path
        Path to GeoPackage/Shapefile with stream line geometries
    nodata : float
        NoData value in DEM
    stream_burning : str
        The selection of the burned streams (``burn_streams_into_dem``): the
        smoothing follows the same lines.

    Returns
    -------
    tuple
        (smoothed_dem, flow_lines, diagnostics): ``flow_lines`` are the burned
        LineStrings in their order, each in the direction of its flow (reversed where
        a rule reverses it), the directions the classification of the lakes takes
        (``classify_endorheic_lakes``). The diagnostics:
        - segments_processed: lines with at least two cells in the DEM
        - segments_skipped: lines with fewer, or ending where they begin
        - segments_reversed: lines taken against their digitized direction
        - segments_by_mouth, segments_by_watercourse: lines whose direction rules 1
          (the mouth) and 2 (the DEM of the watercourse) decide, reversed or not
        - segments_reversed_by_mouth, segments_reversed_by_watercourse,
          segments_reversed_by_rise: the reversed lines by rule (rule 3 is the rise
          along the line); their sum is segments_reversed
        - blocks_kept_by_fall: blocks digitized against their watercourse that rule 2
          leaves, as their own DEM falls by more than REVERSED_LINE_RISE_M the way
          they are digitized
        - connectors: artificial connectors among the lines
        - segments_out_of_order: lines of a directed cycle, taken before a line
          ending at their first node
        - gaps_bridged: gaps between features bridged
        - cells_smoothed: cells cut to below the cell before them
        - cells_stepped: cells as high as the cell before them, lowered by a step
        - cells_unchanged: the other cells of the lines with data
        - max_correction_m, mean_correction_m: of the cut cells
    """
    from shapely import reverse

    smoothed = dem.copy()
    diag: dict[str, Any] = {
        "segments_processed": 0,
        "segments_skipped": 0,
        "segments_reversed": 0,
        "segments_by_mouth": 0,
        "segments_by_watercourse": 0,
        "segments_reversed_by_mouth": 0,
        "segments_reversed_by_watercourse": 0,
        "segments_reversed_by_rise": 0,
        "blocks_kept_by_fall": 0,
        "connectors": 0,
        "segments_out_of_order": 0,
        "gaps_bridged": 0,
        "cells_smoothed": 0,
        "cells_stepped": 0,
        "cells_unchanged": 0,
        "max_correction_m": 0.0,
        "mean_correction_m": 0.0,
    }
    features = _load_stream_features(streams_path, transform, dem.shape, stream_burning)
    features = features[features.geom_type == "LineString"]
    geoms = list(features.geometry)
    if not geoms:
        return smoothed, [], diag
    mphp = list(features["IDENTYFIKATORMPHP"])
    names = list(features["NAZWA"])
    connector = [value == CONNECTOR for value in features["CECHAGEOMETRII"]]
    diag["connectors"] = sum(connector)

    # The cells of each line as digitized, the nodes it joins, the DEM along it
    ends, node_cells = _line_nodes(geoms, transform)
    cellsize_m = abs(transform.a)
    cells_of: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    values: dict[int, np.ndarray] = {}
    for line, (first, last) in ends.items():
        cells = _rasterize_line_ordered(geoms[line], transform, shape=dem.shape)
        if len(cells) < 2 or first == last:
            diag["segments_skipped"] += 1
            cells = []
        else:
            diag["segments_processed"] += 1
        rows = np.array([row for row, _ in cells], dtype=np.intp)
        cols = np.array([col for _, col in cells], dtype=np.intp)
        line_values = dem[rows, cols]
        values[line] = line_values[line_values != nodata]
        cells_of[line] = (rows, cols)
    # The direction of each line: a reversed one is taken the other way
    directions, kept = _line_directions(
        ends,
        values,
        {line: geoms[line].length for line in ends},
        mphp,
        names,
        connector,
        cellsize_m,
    )
    diag["blocks_kept_by_fall"] = len(kept)
    flow_lines = list(geoms)
    for line, (reversed_line, rule) in directions.items():
        if rule in ("mouth", "watercourse"):
            diag[f"segments_by_{rule}"] += 1
        if not reversed_line:
            continue
        rows, cols = cells_of[line]
        cells_of[line] = (rows[::-1].copy(), cols[::-1].copy())
        first, last = ends[line]
        ends[line] = (last, first)
        flow_lines[line] = reverse(geoms[line])
        diag["segments_reversed"] += 1
        diag[f"segments_reversed_by_{rule}"] += 1
    # The bridges of the gaps, as lines numbered after the real ones
    nrows, ncols = dem.shape
    for bridge, (dead_end, start) in enumerate(
        _gap_joins(ends, node_cells, dem, nodata, cellsize_m), start=len(geoms)
    ):
        cells = [
            (row, col)
            for row, col in _bresenham(*node_cells[dead_end], *node_cells[start])
            if 0 <= row < nrows and 0 <= col < ncols
        ]
        ends[bridge] = (dead_end, start)
        cells_of[bridge] = (
            np.array([row for row, _ in cells], dtype=np.intp),
            np.array([col for _, col in cells], dtype=np.intp),
        )
        diag["gaps_bridged"] += 1

    order, diag["segments_out_of_order"] = _flow_order(ends)
    node_value: dict[int, float] = {}
    corrections_m = 0.0
    valid_cells = 0
    for line in order:
        first, last = ends[line]
        rows, cols = cells_of[line]
        if rows.size:
            valid_cells += int(np.count_nonzero(smoothed[rows, cols] != nodata))
        end_value, cut, stepped, largest, total = _descend_strictly(
            smoothed, rows, cols, nodata, node_value.get(first, np.inf)
        )
        if end_value < node_value.get(last, np.inf):
            node_value[last] = end_value
        diag["cells_smoothed"] += cut
        diag["cells_stepped"] += stepped
        diag["max_correction_m"] = max(diag["max_correction_m"], largest)
        corrections_m += total
    diag["cells_unchanged"] = (
        valid_cells - diag["cells_smoothed"] - diag["cells_stepped"]
    )
    if diag["cells_smoothed"]:
        diag["mean_correction_m"] = corrections_m / diag["cells_smoothed"]

    logger.info(
        "Monotonic smoothing: %d segments (%d against their digitized direction: %d "
        "to the mouth, %d down their watercourse, %d by their own rise; %d blocks kept "
        "by their fall; %d out of the flow order, %d gaps bridged), %d cells cut, %d "
        "lowered by a step, max=%.2fm, mean=%.2fm",
        diag["segments_processed"],
        diag["segments_reversed"],
        diag["segments_reversed_by_mouth"],
        diag["segments_reversed_by_watercourse"],
        diag["segments_reversed_by_rise"],
        diag["blocks_kept_by_fall"],
        diag["segments_out_of_order"],
        diag["gaps_bridged"],
        diag["cells_smoothed"],
        diag["cells_stepped"],
        diag["max_correction_m"],
        diag["mean_correction_m"],
    )
    return smoothed, flow_lines, diag


# A watercourse line within LAKE_SNAP_M of a water body belongs to it: BDOT10k lines
# often stop short of the shore (on the Hydroni area the median gap of the lines near a
# lake is 9 m, the 90th percentile 17 m), and water bodies within LAKE_SNAP_M of each
# other (reeds, marshes) are classified as one
LAKE_SNAP_M = 20.0
# Floating-point slack of the length of a line beyond its contact with a lake [m]
_LAKE_CONTACT_EPS_M = 1e-6


def _flow_leaves_lake(line: BaseGeometry, lake: BaseGeometry) -> bool:
    """Say whether the flow of a line, in the order of its vertices, leaves a lake.

    The flow of the line starts at the lake where the two meet: after the last point
    they have in common (a line that crosses the lake passes through it), or at the
    first vertex of a line that does not reach the lake but begins within
    ``LAKE_SNAP_M`` of it. The flow leaves the lake when the line has a part beyond that
    point. A line that ends in the lake, at its shore or within ``LAKE_SNAP_M`` short
    of it brings water in; so does a line that merely passes within ``LAKE_SNAP_M``
    without touching and without beginning there.
    """
    import shapely
    from shapely.geometry import Point

    hit = line.intersection(lake)
    if not hit.is_empty:
        points = shapely.points(shapely.get_coordinates(hit))
        reach_m = float(shapely.line_locate_point(line, points).max())
    elif lake.distance(Point(line.coords[0])) <= LAKE_SNAP_M:
        reach_m = 0.0
    else:
        return False
    return bool(line.length - reach_m > _LAKE_CONTACT_EPS_M)


def _in_flow_order(
    line: BaseGeometry, dem: np.ndarray, transform: Affine, nodata: float
) -> tuple[BaseGeometry, bool]:
    """Return a stream line in the order of its flow, and whether it was reversed.

    BDOT10k digitizes a watercourse downstream, so a line keeps its vertex order unless
    the DEM along it rises that way (``_rises_downstream``): the rule of a line on its
    own (ADR-072, rule 3 of ADR-077), for a line whose direction the smoothing did not
    decide.
    """
    from shapely.geometry import LineString

    cells = _rasterize_line_ordered(line, transform, shape=dem.shape)
    if len(cells) < 2:
        return line, False
    rows = np.array([row for row, _ in cells], dtype=np.intp)
    cols = np.array([col for _, col in cells], dtype=np.intp)
    values = dem[rows, cols]
    if _rises_downstream(values[values != nodata], abs(transform.a)):
        return LineString(list(line.coords)[::-1]), True
    return line, False


def classify_endorheic_lakes(
    dem: np.ndarray,
    transform: Affine,
    gpkg_path: str | Path,
    nodata: float,
    min_area_m2: float | None = None,
    waterbody_path: str | Path | None = None,
    flow_lines: Sequence[BaseGeometry] | None = None,
) -> tuple[list[tuple[int, int]], dict[str, Any]]:
    """
    Classify water bodies and return drain points for endorheic lakes.

    Reads water body polygons (OT_PTWP_A) and stream lines (OT_SWRS_L,
    OT_SWKN_L, OT_SWRM_L) from a BDOT10k GeoPackage. A water body is exorheic
    (przepływowy) when any watercourse line leaves it, and endorheic (bezodpływowy)
    otherwise: every line of the three layers counts, whatever its kind or name.

    A line leaves a water body when its flow starts at it and goes on outside it
    (``_flow_leaves_lake``): the line has a part beyond its last contact with the
    water body, so a line that starts at the shore, begins within ``LAKE_SNAP_M`` of
    it, or crosses it leaves it; a line that ends at it or in it is an inflow. A
    burned line flows the way the smoothing takes it (``flow_lines``, the rules of
    ADR-077), so the lakes and the smoothed DEM agree on its direction. Any other line
    flows the way BDOT10k digitizes it (a watercourse is digitized downstream) unless
    the DEM along it rises that way by more than 2 m on at least 200 m, a line
    digitized upstream (``_in_flow_order``, the rule of a line on its own, ADR-072):
    the DEM is read along those lines near water bodies only. The DEM never decides
    anything else, and a line's elevations at its ends are not compared.

    Water bodies within ``LAKE_SNAP_M`` of each other form one cluster that is
    classified as a whole: an outflow of any of them makes all of them exorheic.

    Parameters
    ----------
    dem : np.ndarray
        Input DEM array
    transform : Affine
        Rasterio Affine transform for the DEM grid
    gpkg_path : str or Path
        Path to BDOT10k GeoPackage with water body and stream layers
    nodata : float
        NoData value in DEM
    min_area_m2 : float, optional
        Minimum water body area in m². Bodies smaller than this are ignored.
    waterbody_path : str or Path, optional
        Custom path to water body file (.gpkg/.shp). All bodies from this
        file are treated as endorheic (no stream-based classification).
    flow_lines : sequence of LineString, optional
        The burned lines in the direction of their flow, as
        ``smooth_streams_monotonic`` returns them: a line of the three layers with
        the geometry of one of them, either way, flows that way.

    Returns
    -------
    tuple
        (drain_points, diagnostics) where:
        - drain_points: list of (row, col) for each endorheic lake
        - diagnostics: dict with classification stats (``streams_analyzed``: the lines
          near water bodies that were examined, ``streams_burned``: those of them that
          take the direction of ``flow_lines``, ``streams_reversed``: those taken
          against their digitized direction)
    """
    import geopandas as gpd
    import shapely
    from shapely.geometry import box

    gpkg_path = Path(gpkg_path)
    diagnostics = {
        "total_lakes": 0,
        "endorheic": 0,
        "exorheic": 0,
        "clusters": 0,
        "streams_analyzed": 0,
        "streams_burned": 0,
        "streams_reversed": 0,
        "filtered_by_area": 0,
    }
    drain_points: list[tuple[int, int]] = []

    # Build DEM extent box
    nrows, ncols = dem.shape
    xmin = transform.c
    ymax = transform.f
    xmax = xmin + ncols * transform.a
    ymin = ymax + nrows * transform.e  # transform.e is negative
    dem_box = box(xmin, ymin, xmax, ymax)

    # 1. Load water body polygons
    if waterbody_path is not None:
        # Custom waterbody file — load and treat all as endorheic
        waterbody_path = Path(waterbody_path)
        try:
            import fiona

            wb_layers = fiona.listlayers(str(waterbody_path))
            # Auto-detect: prefer PTWP layer, fallback to first
            wb_layer = None
            for layer in wb_layers:
                if "PTWP" in layer.upper():
                    wb_layer = layer
                    break
            if wb_layer is None:
                wb_layer = wb_layers[0]
            lakes = gpd.read_file(waterbody_path, layer=wb_layer)
        except Exception:
            lakes = gpd.read_file(waterbody_path)
    else:
        # Default: load OT_PTWP_A from BDOT10k gpkg_path
        try:
            import fiona

            layers = fiona.listlayers(str(gpkg_path))
        except Exception:
            logger.warning(
                f"Cannot read layers from {gpkg_path}, skipping lake classification"
            )
            return drain_points, diagnostics

        water_layer = None
        for layer in layers:
            if "PTWP" in layer.upper():
                water_layer = layer
                break

        if water_layer is None:
            logger.info("No OT_PTWP_A layer in GeoPackage, skipping")
            return drain_points, diagnostics

        lakes = gpd.read_file(gpkg_path, layer=water_layer)

    if lakes.crs is not None and lakes.crs.to_epsg() != 2180:
        lakes = lakes.to_crs(epsg=2180)
    lakes = lakes[lakes.intersects(dem_box)]
    lakes = lakes.clip(dem_box)

    if lakes.empty:
        logger.info("No water bodies within DEM extent")
        return drain_points, diagnostics

    # Filter by minimum area
    if min_area_m2 is not None and min_area_m2 > 0:
        before_count = len(lakes)
        lakes = lakes[lakes.geometry.area >= min_area_m2]
        diagnostics["filtered_by_area"] = before_count - len(lakes)
        if diagnostics["filtered_by_area"] > 0:
            logger.info(
                f"  Filtered {diagnostics['filtered_by_area']} water bodies "
                f"< {min_area_m2} m² ({len(lakes)} remaining)"
            )
        if lakes.empty:
            logger.info("No water bodies remaining after area filter")
            return drain_points, diagnostics

    diagnostics["total_lakes"] = len(lakes)

    # Custom waterbody path → all endorheic, skip stream classification
    if waterbody_path is not None:
        lake_geoms = [g for g in lakes.geometry if g is not None and not g.is_empty]
        diagnostics["endorheic"] = len(lake_geoms)
        diagnostics["clusters"] = len(lake_geoms)
        for lake_geom in lake_geoms:
            _add_drain_point(dem, transform, lake_geom, nodata, drain_points)
        logger.info(
            f"Custom waterbody: {len(lake_geoms)} bodies, "
            f"all treated as endorheic, {len(drain_points)} drain points"
        )
        return drain_points, diagnostics

    # 2. Load stream lines (OT_SWRS_L, OT_SWKN_L, OT_SWRM_L)
    stream_layer_prefixes = ["SWRS", "SWKN", "SWRM"]
    stream_gdfs = []
    for layer in layers:
        for prefix in stream_layer_prefixes:
            if prefix in layer.upper():
                try:
                    gdf = gpd.read_file(gpkg_path, layer=layer)
                    if gdf.crs is not None and gdf.crs.to_epsg() != 2180:
                        gdf = gdf.to_crs(epsg=2180)
                    gdf = gdf[gdf.intersects(dem_box)]
                    if not gdf.empty:
                        stream_gdfs.append(gdf)
                except Exception:
                    logger.debug(f"Could not read layer {layer}")
                break

    if stream_gdfs:
        import pandas as pd

        streams = gpd.GeoDataFrame(pd.concat(stream_gdfs, ignore_index=True))
        if hasattr(stream_gdfs[0], "crs"):
            streams = streams.set_crs(stream_gdfs[0].crs)
    else:
        streams = gpd.GeoDataFrame(geometry=[], crs="EPSG:2180")
    # One row per LineString, with the vertex order of BDOT10k
    streams = streams[streams.geometry.notna() & ~streams.geometry.is_empty]
    streams = streams.explode(index_parts=False, ignore_index=True)
    streams = streams[streams.geom_type == "LineString"].reset_index(drop=True)

    # 3. Cluster touching lakes (buffer → merge → explode)
    #    Bridges gaps through reeds/marshes so connected water bodies
    #    are classified as a single unit.
    from shapely.ops import unary_union

    lake_geoms = [g for g in lakes.geometry if g is not None and not g.is_empty]
    buffered = unary_union([g.buffer(LAKE_SNAP_M) for g in lake_geoms])

    # Explode multipolygon into individual clusters
    if buffered.geom_type == "MultiPolygon":
        cluster_hulls = list(buffered.geoms)
    else:
        cluster_hulls = [buffered]

    # Map each original lake to its cluster index
    lake_to_cluster: dict[int, int] = {}
    for i, geom in enumerate(lake_geoms):
        for ci, hull in enumerate(cluster_hulls):
            if hull.intersects(geom):
                lake_to_cluster[i] = ci
                break

    # Build cluster → original geometries mapping
    cluster_lakes: dict[int, list[Any]] = {}
    for i, ci in lake_to_cluster.items():
        cluster_lakes.setdefault(ci, []).append(lake_geoms[i])

    diagnostics["clusters"] = len(cluster_lakes)
    logger.info(
        f"  {len(lake_geoms)} lakes grouped into "
        f"{len(cluster_lakes)} clusters (buffer={LAKE_SNAP_M}m)"
    )

    # 4. Classify each cluster: exorheic when the flow of any line near it leaves it.
    #    A burned line flows as the smoothing took it, found by its geometry
    line_geoms = streams.geometry.values
    flow_of = {shapely.normalize(line).wkb: line for line in (flow_lines or [])}
    in_flow_order: dict[int, BaseGeometry] = {}
    for _ci, members in cluster_lakes.items():
        # Union of all lake geometries in this cluster
        cluster_geom = unary_union(members) if len(members) > 1 else members[0]

        near = (
            streams.sindex.query(
                cluster_geom.buffer(LAKE_SNAP_M), predicate="intersects"
            )
            if len(line_geoms)
            else []
        )

        has_outflow = False
        for line_idx in near:
            line_idx = int(line_idx)
            if line_idx not in in_flow_order:
                diagnostics["streams_analyzed"] += 1
                line = line_geoms[line_idx]
                flow = flow_of.get(shapely.normalize(line).wkb)
                if flow is None:
                    flow, was_reversed = _in_flow_order(line, dem, transform, nodata)
                else:
                    diagnostics["streams_burned"] += 1
                    was_reversed = not flow.equals_exact(line, 0.0)
                in_flow_order[line_idx] = flow
                diagnostics["streams_reversed"] += was_reversed
            if _flow_leaves_lake(in_flow_order[line_idx], cluster_geom):
                has_outflow = True
                break

        if has_outflow:
            diagnostics["exorheic"] += len(members)
        else:
            diagnostics["endorheic"] += len(members)
            for lake_geom in members:
                _add_drain_point(dem, transform, lake_geom, nodata, drain_points)

    logger.info(
        f"Lake classification: {diagnostics['total_lakes']} total, "
        f"{diagnostics['endorheic']} endorheic, "
        f"{diagnostics['exorheic']} exorheic, "
        f"{diagnostics['clusters']} clusters, "
        f"{diagnostics['streams_analyzed']} streams analyzed "
        f"({diagnostics['streams_burned']} burned)"
    )

    return drain_points, diagnostics


def _add_drain_point(
    dem: np.ndarray,
    transform: Affine,
    lake_geom: BaseGeometry,
    nodata: float,
    drain_points: list[tuple[int, int]],
) -> None:
    """Add drain point (row, col) for an endorheic lake."""
    rep_pt = lake_geom.representative_point()
    inv_transform = ~transform
    col_f, row_f = inv_transform * (rep_pt.x, rep_pt.y)
    row, col = int(row_f), int(col_f)
    nrows, ncols = dem.shape
    if 0 <= row < nrows and 0 <= col < ncols:
        drain_points.append((row, col))


def recompute_flow_accumulation(
    fdir: np.ndarray,
    dem: np.ndarray,
    nodata: float,
) -> np.ndarray:
    """
    Recompute the flow accumulation with Kahn's topological order.

    Unlike the legacy compute_flow_accumulation():
    - nodata cells are skipped (acc=0)
    - cells without a D8 direction (0, a pit, any other code) are terminals

    A cell passes its accumulation on once all the cells draining into it have
    passed theirs; the cells of a cycle never do, and keep what reached them
    from outside the cycle. In numba, following each chain downstream as far as
    it is complete, without a queue.

    Parameters
    ----------
    fdir : np.ndarray
        Flow direction array (D8 encoding)
    dem : np.ndarray
        DEM array (for nodata detection)
    nodata : float
        NoData value

    Returns
    -------
    np.ndarray
        Flow accumulation array (number of upstream cells including self)
    """
    nodata_value = np.result_type(dem.dtype, nodata).type(nodata)
    return _kahn_accumulation(
        fdir, dem, nodata_value, D8_VALID, D8_ROW_OFFSET, D8_COL_OFFSET
    )


@numba.njit(cache=True)
def _kahn_accumulation(
    fdir: np.ndarray,
    dem: np.ndarray,
    nodata: Any,
    d8_valid: np.ndarray,
    d8_row: np.ndarray,
    d8_col: np.ndarray,
) -> np.ndarray:
    """Accumulate along the flow directions (recompute_flow_accumulation)."""
    nrows, ncols = fdir.shape
    acc = np.zeros((nrows, ncols), dtype=np.int32)
    # Valid cells draining into each cell (at most 8); 255 once the cell has
    # passed its accumulation on
    inflow = np.zeros((nrows, ncols), dtype=np.uint8)
    done = np.uint8(255)
    for row in range(nrows):
        for col in range(ncols):
            if dem[row, col] == nodata:
                continue
            acc[row, col] = 1
            code = fdir[row, col]
            if code < 0 or code > 255 or not d8_valid[code]:
                continue
            r, c = row + d8_row[code], col + d8_col[code]
            if 0 <= r < nrows and 0 <= c < ncols and dem[r, c] != nodata:
                inflow[r, c] += 1
    for row in range(nrows):
        for col in range(ncols):
            if inflow[row, col] != 0 or dem[row, col] == nodata:
                continue
            r, c = row, col
            while True:
                inflow[r, c] = done
                code = fdir[r, c]
                if code < 0 or code > 255 or not d8_valid[code]:
                    break
                down_r, down_c = r + d8_row[code], c + d8_col[code]
                if not (
                    0 <= down_r < nrows
                    and 0 <= down_c < ncols
                    and dem[down_r, down_c] != nodata
                ):
                    break
                acc[down_r, down_c] += acc[r, c]
                inflow[down_r, down_c] -= 1
                if inflow[down_r, down_c] != 0:
                    break
                r, c = down_r, down_c
    return acc


@numba.njit(cache=True)
def _internal_sinks(
    fdir: np.ndarray,
    dem: np.ndarray,
    nodata: Any,
    d8_valid: np.ndarray,
) -> np.ndarray:
    """Return the flat indices of the internal sinks, row by row.

    An internal sink is a cell without a D8 flow direction (0, -1, any other
    value) whose 3 x 3 window lies in the raster and has data. A pit at the edge
    of the data, on the frame of the raster or next to nodata, is an outlet:
    pyflwdir's depression filling (outlets="edge") drains the area through such
    cells and leaves no other pits.
    """
    nrows, ncols = fdir.shape
    count = 0
    for row in range(1, nrows - 1):
        for col in range(1, ncols - 1):
            if _is_sink(fdir, dem, row, col, nodata, d8_valid):
                count += 1
    sinks = np.empty(count, dtype=np.int64)
    count = 0
    for row in range(1, nrows - 1):
        for col in range(1, ncols - 1):
            if _is_sink(fdir, dem, row, col, nodata, d8_valid):
                sinks[count] = row * ncols + col
                count += 1
    return sinks


@numba.njit(cache=True)
def _is_sink(
    fdir: np.ndarray,
    dem: np.ndarray,
    row: int,
    col: int,
    nodata: Any,
    d8_valid: np.ndarray,
) -> bool:
    """Say whether a cell off the frame is an internal sink (_internal_sinks)."""
    code = fdir[row, col]
    if 0 <= code <= 255 and d8_valid[code]:
        return False
    for r in range(row - 1, row + 2):
        for c in range(col - 1, col + 2):
            if dem[r, c] == nodata:
                return False
    return True


@numba.njit(cache=True)
def _drains_into(
    fdir: np.ndarray,
    dem: np.ndarray,
    nodata: Any,
    row: int,
    col: int,
    target: int,
    d8_valid: np.ndarray,
    d8_row: np.ndarray,
    d8_col: np.ndarray,
) -> bool:
    """Say whether the flow from a cell reaches the cell of flat index ``target``.

    The flow stops at a cell without a D8 direction and where it leaves the
    raster or its data, as the accumulation does; a path with more steps than
    the raster has cells runs round a cycle without the target.
    """
    nrows, ncols = fdir.shape
    for _ in range(nrows * ncols):
        if row * ncols + col == target:
            return True
        code = fdir[row, col]
        if dem[row, col] == nodata or code < 0 or code > 255 or not d8_valid[code]:
            return False
        row += d8_row[code]
        col += d8_col[code]
        if not (0 <= row < nrows and 0 <= col < ncols):
            return False
    return False


def fix_internal_sinks(
    fdir: np.ndarray,
    acc: np.ndarray,
    filled_dem: np.ndarray,
    dem: np.ndarray,
    nodata: float,
    max_iterations: int = 3,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """
    Give the internal sinks of a flow direction grid a direction.

    An internal sink (_internal_sinks) is a cell without a D8 direction whose
    8 neighbours have data; a pit at the edge of the data is an outlet and is
    left as it is. A sink drains to one of the neighbours whose flow does not
    come back to it, so no direction closes a cycle, chosen by, in turn:
    1. steepest descent: the steepest drop to it (filled_dem)
    2. max accumulation: the largest accumulation
    3. any valid: the first one
    A sink without such a neighbour stays. The accumulation is recomputed after
    the fixes.

    Parameters
    ----------
    fdir : np.ndarray
        Flow direction array (D8 encoding)
    acc : np.ndarray
        Flow accumulation array
    filled_dem : np.ndarray
        DEM after the depression filling (the slopes of strategy 1)
    dem : np.ndarray
        DEM whose cells equal to ``nodata`` have no data
    nodata : float
        NoData value
    max_iterations : int
        Maximum number of passes

    Returns
    -------
    tuple
        (fixed_fdir, recomputed_acc, diagnostics)
        diagnostics: dict with 'total_fixed', 'by_strategy', 'iterations'
    """
    ncols = fdir.shape[1]
    fdir_fixed = fdir.copy()

    directions = [1, 2, 4, 8, 16, 32, 64, 128]
    offsets = [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)]
    distances = [1.0, 1.414, 1.0, 1.414, 1.0, 1.414, 1.0, 1.414]

    # NumPy compares the DEM with nodata in this type
    nodata_value = np.result_type(dem.dtype, nodata).type(nodata)

    diag: dict[str, Any] = {
        "total_fixed": 0,
        "by_strategy": {"steepest": 0, "max_acc": 0, "any_valid": 0},
        "iterations": 0,
    }

    for iteration in range(max_iterations):
        # Cells without a D8 direction away from the edge of the data (pysheds
        # returned 0 (nodata), -1 (pit/outlet), -2 (unresolved flat))
        sinks = _internal_sinks(fdir_fixed, dem, nodata_value, D8_VALID)

        if sinks.size == 0:
            break

        diag["iterations"] = iteration + 1
        fixed_this_iter = 0

        for sink in sinks:
            i, j = divmod(int(sink), ncols)
            # The neighbours (all with data) whose flow does not come back to
            # the sink, with the fixes made so far
            candidates = [
                (d, i + di, j + dj, dist)
                for d, (di, dj), dist in zip(
                    directions, offsets, distances, strict=True
                )
                if not _drains_into(
                    fdir_fixed,
                    dem,
                    nodata_value,
                    i + di,
                    j + dj,
                    sink,
                    D8_VALID,
                    D8_ROW_OFFSET,
                    D8_COL_OFFSET,
                )
            ]
            best_dir = None
            strategy = None

            # Strategy 1: steepest descent using filled_dem
            max_slope = 0.0
            for d, ni, nj, dist in candidates:
                slope = (filled_dem[i, j] - filled_dem[ni, nj]) / dist
                if slope > max_slope:
                    max_slope = slope
                    best_dir = d
                    strategy = "steepest"

            # Strategy 2: max accumulation neighbor
            if best_dir is None:
                max_acc_val = -1
                for d, ni, nj, _dist in candidates:
                    if acc[ni, nj] > max_acc_val:
                        max_acc_val = acc[ni, nj]
                        best_dir = d
                        strategy = "max_acc"

            # Strategy 3: any valid neighbor
            if best_dir is None and candidates:
                best_dir = candidates[0][0]
                strategy = "any_valid"

            if best_dir is not None:
                fdir_fixed[i, j] = best_dir
                diag["total_fixed"] += 1
                diag["by_strategy"][strategy] += 1
                fixed_this_iter += 1

        logger.debug(
            f"  fix_internal_sinks iteration {iteration + 1}: "
            f"fixed {fixed_this_iter} sinks"
        )

        if fixed_this_iter == 0:
            break

    # Recompute flow accumulation after fixes
    if diag["total_fixed"] > 0:
        acc_fixed = recompute_flow_accumulation(fdir_fixed, dem, nodata)
    else:
        acc_fixed = acc.copy()

    return fdir_fixed, acc_fixed, diag


def fill_depressions_d8(
    dem: np.ndarray,
    nodata: float,
    drain_points: list[tuple[int, int]] | None = None,
    *,
    overwrite_dem: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Fill the depressions of a DEM and derive pyflwdir's D8 directions.

    The internal nodata holes are repaired first (fill_internal_nodata_holes); the
    drain points of endorheic lakes then become nodata, which pyflwdir treats as
    local outlets; pyflwdir fills the depressions (Wang & Liu 2006, outlets at the
    edge of the data) and gives every cell it routes a D8 direction. The filled DEM
    gets back the nodata of the DEM and of the drain points; a repaired hole keeps
    its direction, so it carries flow.

    Parameters
    ----------
    dem : np.ndarray
        Input DEM array.
    nodata : float
        NoData value.
    drain_points : list of (row, col), optional
        Drain points for endorheic lakes, injected as NoData after the hole
        filling and before pyflwdir.
    overwrite_dem : bool
        Repair the holes in ``dem`` itself, which pyflwdir then fills: no copy of
        the DEM is made, and ``dem`` must not be used afterwards.

    Returns
    -------
    tuple
        (filled_dem, d8_fdir): the filled DEM (the dtype of ``dem``) and pyflwdir's
        D8 grid (uint8: 247 where it routes no flow, 0 at its pits, the outlets).
    """
    from pyflwdir.dem import fill_depressions as pyflwdir_fill_depressions

    # Original nodata and drain points: nodata again in the filled DEM
    restore_mask = dem == nodata
    if drain_points:
        for row, col in drain_points:
            restore_mask[row, col] = True

    # Level 1: Fill internal nodata holes before depression filling
    dem_patched, holes_filled = fill_internal_nodata_holes(
        dem, nodata, overwrite=overwrite_dem
    )
    if holes_filled > 0:
        logger.info(f"  Filled {holes_filled} internal nodata holes")

    # Inject drain points AFTER hole filling, BEFORE pyflwdir
    # pyflwdir treats NoData as local outlets → water routes to drain point
    if drain_points:
        for row, col in drain_points:
            dem_patched[row, col] = nodata
        logger.info(f"  Injected {len(drain_points)} endorheic drain points")

    # Core: depression filling + D8 flow direction (Wang & Liu 2006)
    # Replaces pysheds fill_pits + fill_depressions + resolve_flats + flowdir
    logger.info("  Filling depressions and computing D8 flow direction...")
    filled_dem, d8_fdir = pyflwdir_fill_depressions(
        dem_patched, nodata=nodata, max_depth=-1.0, outlets="edge"
    )
    del dem_patched
    filled_dem[restore_mask] = nodata
    return filled_dem, d8_fdir


def fix_sinks_of_fill(
    fdir: np.ndarray,
    filled_dem: np.ndarray,
    nodata: float,
    accumulation: Callable[[], np.ndarray],
) -> tuple[np.ndarray, np.ndarray | None]:
    """Give the internal sinks of a filled grid a direction (fix_internal_sinks).

    A safety net: pyflwdir's fill leaves no internal sink, its pits are the
    outlets of the area, on the frame of the raster and next to nodata or a drain
    point.

    Parameters
    ----------
    fdir : np.ndarray
        D8 flow directions of fill_depressions_d8 (int16, 0 without a direction).
    filled_dem : np.ndarray
        Its filled DEM, with nodata restored.
    nodata : float
        NoData value.
    accumulation : callable
        Gives the accumulation of pyflwdir's D8 grid [cells]; called only when a
        sink is found.

    Returns
    -------
    tuple
        (fdir, acc): the fixed directions and their recomputed accumulation, or
        ``fdir`` itself and None when there is no sink.
    """
    sinks = _internal_sinks(
        fdir,
        filled_dem,
        np.result_type(filled_dem.dtype, nodata).type(nodata),
        D8_VALID,
    )
    if sinks.size == 0:
        logger.info("  No internal sinks: the pits are outlets at the edge of the data")
        return fdir, None
    # Log breakdown of invalid fdir values
    unique_vals, counts = np.unique(fdir.ravel()[sinks], return_counts=True)
    breakdown = ", ".join(
        f"fdir={v}: {c}" for v, c in zip(unique_vals, counts, strict=True)
    )
    logger.info(f"  Invalid fdir breakdown: {breakdown}")
    logger.info(f"  Found {sinks.size} internal sinks, fixing...")
    fixed, acc, diag = fix_internal_sinks(
        fdir, accumulation(), filled_dem, filled_dem, nodata
    )
    logger.info(
        f"  Fixed {diag['total_fixed']} sinks "
        f"(steepest: {diag['by_strategy']['steepest']}, "
        f"max_acc: {diag['by_strategy']['max_acc']}, "
        f"any_valid: {diag['by_strategy']['any_valid']})"
    )
    return fixed, acc


def process_hydrology_pyflwdir(
    dem: np.ndarray,
    metadata: dict[str, Any],
    drain_points: list[tuple[int, int]] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, Any]:
    """
    Process DEM using pyflwdir (Deltares) for hydrological analysis.

    Uses pyflwdir for depression filling (Wang & Liu 2006), D8 flow direction,
    and flow accumulation. Replaces pysheds — fewer dependencies, no temp files,
    works directly on numpy arrays.

    Parameters
    ----------
    dem : np.ndarray
        Input DEM array
    metadata : dict
        Grid metadata with xllcorner, yllcorner, cellsize, nodata_value,
        and optionally transform (rasterio Affine)
    drain_points : list of (row, col), optional
        Drain points for endorheic lakes. Each point is injected as NoData
        after hole filling but before pyflwdir, so pyflwdir treats them
        as local outlets (sinks).

    Returns
    -------
    tuple
        (filled_dem, flow_direction, flow_accumulation, flw)
        - filled_dem: DEM after depression filling (real elevations)
        - flow_direction: D8 flow directions (int16, nodata=0)
        - flow_accumulation: flow accumulation [cells], pyflwdir's upstream
          area unless fix_internal_sinks recomputed it
        - flw: pyflwdir.FlwdirRaster of pyflwdir's D8 grid, with its cells
          ordered; the one FlwdirRaster of the run. It is the grid of
          flow_direction: fix_internal_sinks finds no sink in it (its pits are
          outlets at the edge of the data)
    """
    import pyflwdir

    logger.info("Processing hydrology with pyflwdir (Deltares)...")

    nodata = metadata["nodata_value"]
    filled_dem, d8_fdir = fill_depressions_d8(dem, nodata, drain_points)

    # Convert fdir types:
    # pyflwdir d8_fdir: uint8, nodata=247, pit=0
    # Our convention: int16, nodata=0
    fdir_arr = d8_fdir.astype(np.int16)
    fdir_arr[d8_fdir == 247] = 0  # pyflwdir nodata → 0

    # Build transform for FlwdirRaster
    transform = metadata.get("transform")
    if transform is None:
        from rasterio.transform import from_bounds

        xll, yll = metadata["xllcorner"], metadata["yllcorner"]
        nrows, ncols = dem.shape
        cs = metadata["cellsize"]
        transform = from_bounds(
            xll, yll, xll + ncols * cs, yll + nrows * cs, ncols, nrows
        )

    # Flow accumulation via the FlwdirRaster of the whole run. Its cells are
    # ordered by sorting: pyflwdir's default walk builds a matrix of the
    # upstream cells of every cell (7-8 per cell)
    logger.info("  Computing flow accumulation...")
    flw = pyflwdir.from_array(d8_fdir, ftype="d8", transform=transform, latlon=False)
    flw.order_cells(method="sort")
    acc_float = flw.upstream_area(unit="cell")
    acc_arr = np.where(acc_float == -9999, 0, acc_float).astype(np.int32)

    fdir_arr, fixed_acc = fix_sinks_of_fill(
        fdir_arr, filled_dem, nodata, lambda: acc_arr
    )
    if fixed_acc is not None:
        acc_arr = fixed_acc

    logger.info("Hydrology processing complete")
    return filled_dem, fdir_arr, acc_arr, flw
