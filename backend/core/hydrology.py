"""
Hydrological processing: depression filling, flow direction, flow accumulation.

Core D8 flow direction constants, internal nodata hole filling,
stream burning, endorheic lake classification, pyflwdir-based hydrology,
sink fixing, and flow accumulation recomputation.
"""

import logging
from collections import defaultdict, deque
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


def fill_internal_nodata_holes(
    dem: np.ndarray,
    nodata: float,
    min_valid_neighbors: int = 5,
    max_iterations: int = 3,
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

    Returns
    -------
    tuple
        (patched_dem, total_filled): the filled DEM and the number of cells filled
    """
    patched = dem.copy()
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


def raise_buildings_in_dem(
    dem: np.ndarray,
    transform: Affine,
    crs_epsg: int,
    building_gpkg: str | None,
    building_raise_m: float = 5.0,
) -> np.ndarray:
    """Raise DEM elevation under building footprints.

    Prevents unrealistic flow paths through buildings.
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

    dem[mask == 1] += building_raise_m
    cells_raised = int(np.sum(mask == 1))
    logger.info(
        f"Building raising: {cells_raised} cells raised "
        f"by {building_raise_m}m ({len(geometries)} buildings)"
    )
    return dem


def _load_stream_geometries(
    streams_path: str | Path, transform: Affine, dem_shape: tuple[int, int]
) -> list[Any]:
    """Load stream geometries from BDOT10k GeoPackage/Shapefile.

    Reads SWRS/SWKN/SWRM/PTWP layers, reprojects to EPSG:2180,
    clips to DEM extent, decomposes MultiLineString to LineString.

    Parameters
    ----------
    streams_path : str or Path
        Path to GeoPackage/Shapefile with stream line geometries
    transform : Affine
        Rasterio Affine transform for the DEM grid
    dem_shape : tuple[int, int]
        (nrows, ncols) of the DEM array

    Returns
    -------
    list[LineString]
        List of LineString geometries within DEM extent
    """
    import fiona
    import geopandas as gpd
    from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon, box

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

    all_geoms = []
    for layer in target_layers:
        try:
            kwargs = {"layer": layer} if layer else {}
            gdf = gpd.read_file(streams_path, **kwargs)
        except Exception:
            continue
        if gdf.empty:
            continue
        if gdf.crs and gdf.crs.to_epsg() != 2180:
            gdf = gdf.to_crs(epsg=2180)
        gdf = gdf[gdf.geometry.intersects(dem_bounds)]
        for geom in gdf.geometry:
            if geom is None or geom.is_empty:
                continue
            if isinstance(geom, MultiLineString):
                for part in geom.geoms:
                    if not part.is_empty and len(list(part.coords)) >= 2:
                        all_geoms.append(part)
            elif isinstance(geom, (Polygon, MultiPolygon)):
                # Include polygon geometries as-is (for burn rasterization)
                all_geoms.append(geom)
            elif isinstance(geom, LineString):
                if len(list(geom.coords)) >= 2:
                    all_geoms.append(geom)
            else:
                # Other geometry types — include if valid
                all_geoms.append(geom)

    return all_geoms


def burn_streams_into_dem(
    dem: np.ndarray,
    transform: Affine,
    streams_path: str | Path,
    burn_depth_m: float = 2.0,
    nodata: float = -9999.0,
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
    geoms = _load_stream_geometries(streams_path, transform, dem.shape)
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
        f"Stream burning: {diagnostics['cells_burned']} cells burned "
        f"(depth={burn_depth_m}m, streams={diagnostics['streams_in_extent']})"
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


def _rasterize_line_ordered(
    line: BaseGeometry,
    transform: Affine,
    shape: tuple[int, int] | None = None,
) -> list[tuple[int, int]]:
    """Rasterize a LineString to an ordered sequence of (row, col) cells.

    Uses Bresenham between consecutive vertices. Deduplicates cells
    at segment junctions. Optionally clips to raster shape.

    Extension vs spec: added optional ``shape`` for bounds clipping.
    """
    coords = list(line.coords)
    if len(coords) < 2:
        return []

    cells: list[tuple[int, int]] = []
    for i in range(len(coords) - 1):
        x0, y0 = coords[i][:2]
        x1, y1 = coords[i + 1][:2]
        col0, row0 = ~transform * (x0, y0)
        col1, row1 = ~transform * (x1, y1)
        r0, c0 = int(round(row0)), int(round(col0))
        r1, c1 = int(round(row1)), int(round(col1))
        segment = _bresenham(r0, c0, r1, c1)
        if cells and segment and segment[0] == cells[-1]:
            segment = segment[1:]
        cells.extend(segment)

    if shape is not None:
        nrows, ncols = shape
        cells = [(r, c) for r, c in cells if 0 <= r < nrows and 0 <= c < ncols]

    return cells


def _build_stream_network_graph(
    geometries: list[Any],
    dem: np.ndarray,
    transform: Affine,
    snap_tolerance_px: int = 1,
) -> tuple[dict[int, list[tuple[int, int]]], dict[int, tuple[int, int]], list[int]]:
    """Build a topology graph from stream LineString geometries.

    Endpoints are snapped to raster pixels. Nodes within snap_tolerance_px
    of each other are merged.

    Returns
    -------
    graph : dict
        {node_id: [(neighbor_node_id, segment_index), ...]}
    seg_nodes : dict
        {segment_index: (start_node, end_node)}; start corresponds to
        geometry coords[0], end to coords[-1].
    outlets : list
        Outlet node IDs (one per connected component).
    """
    nrows, ncols = dem.shape

    endpoints = []
    for idx, geom in enumerate(geometries):
        coords = list(geom.coords)
        if len(coords) < 2:
            continue
        for pt, is_start in [(coords[0], True), (coords[-1], False)]:
            x, y = pt[:2]
            col, row = ~transform * (x, y)
            r, c = int(round(row)), int(round(col))
            endpoints.append((r, c, idx, is_start))

    node_for_point: dict[tuple[int, int], int] = {}
    next_node_id = 0

    def get_or_create_node(r: int, c: int) -> int:
        nonlocal next_node_id
        for (nr, nc), nid in node_for_point.items():
            if abs(nr - r) <= snap_tolerance_px and abs(nc - c) <= snap_tolerance_px:
                return nid
        node_for_point[(r, c)] = next_node_id
        next_node_id += 1
        return next_node_id - 1

    seg_nodes: dict[int, tuple[int | None, int | None]] = {}
    for r, c, idx, is_start in endpoints:
        nid = get_or_create_node(r, c)
        if idx not in seg_nodes:
            seg_nodes[idx] = (None, None)
        if is_start:
            seg_nodes[idx] = (nid, seg_nodes[idx][1])
        else:
            seg_nodes[idx] = (seg_nodes[idx][0], nid)

    graph: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for idx, (n_start, n_end) in seg_nodes.items():
        if n_start is None or n_end is None or n_start == n_end:
            continue
        graph[n_start].append((n_end, idx))
        graph[n_end].append((n_start, idx))

    for nid in range(next_node_id):
        if nid not in graph:
            graph[nid] = []

    node_coords = {nid: (r, c) for (r, c), nid in node_for_point.items()}
    outlets = []
    visited: set[int] = set()

    def _clamp_elev(n: int) -> float:
        if n not in node_coords:
            return float("inf")
        r, c = node_coords[n]
        r = max(0, min(r, nrows - 1))
        c = max(0, min(c, ncols - 1))
        return float(dem[r, c])

    for start_nid in range(next_node_id):
        if start_nid in visited:
            continue
        component: list[int] = []
        queue = deque([start_nid])
        visited.add(start_nid)
        while queue:
            nid = queue.popleft()
            component.append(nid)
            for neighbor, _ in graph[nid]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        degree_one = [n for n in component if len(graph[n]) == 1]
        if not degree_one:
            degree_one = component

        edge_nodes = [
            n
            for n in degree_one
            if n in node_coords
            and (
                node_coords[n][0] <= 0
                or node_coords[n][0] >= nrows - 1
                or node_coords[n][1] <= 0
                or node_coords[n][1] >= ncols - 1
            )
        ]

        candidates = edge_nodes if edge_nodes else degree_one
        outlets.append(min(candidates, key=_clamp_elev))

    # Filter out incomplete segment mappings
    seg_nodes_clean: dict[int, tuple[int, int]] = {
        idx: (s, e)
        for idx, (s, e) in seg_nodes.items()
        if s is not None and e is not None
    }

    return dict(graph), seg_nodes_clean, outlets


def smooth_streams_monotonic(
    dem: np.ndarray,
    transform: Affine,
    streams_path: str | Path,
    nodata: float = -9999.0,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Enforce monotonically decreasing elevation along stream channels.

    Loads stream geometries, builds a topology graph, and applies a
    running-minimum downstream pass from sources to outlets. At
    confluences the minimum of all tributary last-elevations is used
    as the running value for the downstream segment.

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

    Returns
    -------
    tuple
        (smoothed_dem, diagnostics) where diagnostics contains:
        - segments_processed: int
        - segments_skipped: int
        - cells_smoothed: int
        - cells_unchanged: int
        - max_correction_m: float
        - mean_correction_m: float
        - disconnected_components: int
    """
    smoothed = dem.copy()
    diag = {
        "segments_processed": 0,
        "segments_skipped": 0,
        "cells_smoothed": 0,
        "cells_unchanged": 0,
        "max_correction_m": 0.0,
        "mean_correction_m": 0.0,
        "disconnected_components": 0,
    }

    # 1. Load geometries (filter to LineStrings only for smoothing)
    from shapely.geometry import LineString as _LS

    all_geoms = _load_stream_geometries(streams_path, transform, dem.shape)
    geoms = [g for g in all_geoms if isinstance(g, _LS)]
    if not geoms:
        return smoothed, diag

    # 2. Rasterize each segment
    seg_cells: dict[int, list[tuple[int, int]]] = {}
    valid_geoms = []
    for idx, geom in enumerate(geoms):
        cells = _rasterize_line_ordered(geom, transform, shape=dem.shape)
        if len(cells) < 2:
            diag["segments_skipped"] += 1
            continue
        seg_cells[idx] = cells
        valid_geoms.append((idx, geom))

    if not valid_geoms:
        diag["segments_skipped"] = len(geoms)
        return smoothed, diag

    # Build geometry list preserving original indices for graph building
    geom_list_for_graph = [None] * len(geoms)
    for idx, geom in valid_geoms:
        geom_list_for_graph[idx] = geom

    # 3. Build topology graph
    graph, seg_nodes, outlets = _build_stream_network_graph(geoms, smoothed, transform)
    diag["disconnected_components"] = len(outlets)

    # 4. Process each connected component
    corrections: list[float] = []
    processed_segs: set[int] = set()

    for outlet in outlets:
        # BFS from outlet to build traversal order + position lookup
        bfs_order: list[int] = []
        bfs_pos: dict[int, int] = {}
        bfs_queue = deque([outlet])
        bfs_pos[outlet] = 0
        pos_counter = 0
        while bfs_queue:
            nid = bfs_queue.popleft()
            bfs_order.append(nid)
            for neighbor, _seg_idx in graph.get(nid, []):
                if neighbor not in bfs_pos:
                    pos_counter += 1
                    bfs_pos[neighbor] = pos_counter
                    bfs_queue.append(neighbor)

        # node_last_elev: track last elevation written at each node
        # (minimum across all incoming tributaries)
        node_last_elev: dict[int, float] = {}

        # Process in reverse BFS order (sources first → outlet last)
        for nid in reversed(bfs_order):
            nid_pos = bfs_pos[nid]
            for neighbor, seg_idx in graph.get(nid, []):
                if seg_idx not in seg_cells:
                    continue
                if seg_idx in processed_segs:
                    continue
                neighbor_pos = bfs_pos.get(neighbor)
                if neighbor_pos is None:
                    continue
                # Only process when nid is upstream (farther from outlet)
                if neighbor_pos >= nid_pos:
                    continue

                processed_segs.add(seg_idx)
                diag["segments_processed"] += 1

                cells = list(seg_cells[seg_idx])

                # Direction: seg_nodes[seg_idx][0] corresponds to
                # geometry coords[0]. If that node is not nid, reverse.
                if seg_idx in seg_nodes:
                    geom_start_node, _geom_end_node = seg_nodes[seg_idx]
                    if geom_start_node != nid:
                        cells = list(reversed(cells))

                # Initialize running minimum
                running_val = float("inf")
                # At confluence: use min of tributary last-elevations
                if nid in node_last_elev:
                    running_val = min(running_val, node_last_elev[nid])

                # Running-minimum downstream pass
                for r, c in cells:
                    val = float(smoothed[r, c])
                    if nodata != -9999.0 and val == nodata:
                        # Skip nodata cells
                        continue
                    if val == nodata:
                        continue
                    new_val = min(val, running_val)
                    if new_val < val:
                        correction = val - new_val
                        corrections.append(correction)
                        smoothed[r, c] = new_val
                        diag["cells_smoothed"] += 1
                    else:
                        diag["cells_unchanged"] += 1
                    running_val = new_val

                # Store last elevation at downstream node
                last_cell = cells[-1] if cells else None
                if last_cell is not None:
                    last_r, last_c = last_cell
                    last_val = float(smoothed[last_r, last_c])
                    if last_val != nodata:
                        if neighbor in node_last_elev:
                            node_last_elev[neighbor] = min(
                                node_last_elev[neighbor], last_val
                            )
                        else:
                            node_last_elev[neighbor] = last_val

    # Count segments that were in seg_cells but not processed
    unprocessed = set(seg_cells.keys()) - processed_segs
    diag["segments_skipped"] += len(unprocessed)

    # Compute correction statistics
    if corrections:
        diag["max_correction_m"] = max(corrections)
        diag["mean_correction_m"] = sum(corrections) / len(corrections)

    logger.info(
        f"Monotonic smoothing: {diag['segments_processed']} segments, "
        f"{diag['cells_smoothed']} cells corrected, "
        f"max={diag['max_correction_m']:.2f}m, "
        f"mean={diag['mean_correction_m']:.2f}m"
    )

    return smoothed, diag


def _sample_dem_at_point(
    dem: np.ndarray,
    transform: Affine,
    x: float,
    y: float,
    nodata: float,
    search_radius: int = 3,
) -> float | None:
    """
    Sample DEM elevation at a geographic point.

    Parameters
    ----------
    dem : np.ndarray
        DEM array
    transform : Affine
        Rasterio Affine transform
    x, y : float
        Coordinates in DEM CRS (e.g. EPSG:2180)
    nodata : float
        NoData value
    search_radius : int
        Search radius (in cells) when the exact cell is NoData

    Returns
    -------
    float or None
        Elevation value, or None if no valid cell found within search radius.
    """
    inv_transform = ~transform
    col_f, row_f = inv_transform * (x, y)
    row, col = int(row_f), int(col_f)
    nrows, ncols = dem.shape

    if 0 <= row < nrows and 0 <= col < ncols and dem[row, col] != nodata:
        return float(dem[row, col])

    # Search neighbors in expanding square
    best_val = None
    best_dist_sq = float("inf")
    for dr in range(-search_radius, search_radius + 1):
        for dc in range(-search_radius, search_radius + 1):
            nr, nc = row + dr, col + dc
            if 0 <= nr < nrows and 0 <= nc < ncols and dem[nr, nc] != nodata:
                dist_sq = dr * dr + dc * dc
                if dist_sq < best_dist_sq:
                    best_dist_sq = dist_sq
                    best_val = float(dem[nr, nc])
    return best_val


def classify_endorheic_lakes(
    dem: np.ndarray,
    transform: Affine,
    gpkg_path: str | Path,
    nodata: float,
    min_area_m2: float | None = None,
    waterbody_path: str | Path | None = None,
) -> tuple[list[tuple[int, int]], dict[str, Any]]:
    """
    Classify water bodies and return drain points for endorheic lakes.

    Reads water body polygons (OT_PTWP_A) and stream lines (OT_SWRS_L,
    OT_SWKN_L, OT_SWRM_L) from a BDOT10k GeoPackage. For each water body,
    determines if it is endorheic (no outflow) or exorheic (has outflow)
    based on touching streams and DEM elevation analysis.

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

    Returns
    -------
    tuple
        (drain_points, diagnostics) where:
        - drain_points: list of (row, col) for each endorheic lake
        - diagnostics: dict with classification stats
    """
    import geopandas as gpd
    from shapely.geometry import Point, box

    gpkg_path = Path(gpkg_path)
    diagnostics = {
        "total_lakes": 0,
        "endorheic": 0,
        "exorheic": 0,
        "clusters": 0,
        "streams_analyzed": 0,
        "undetermined": 0,
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

    # 3. Cluster touching lakes (buffer → merge → explode)
    #    Bridges gaps through reeds/marshes so connected water bodies
    #    are classified as a single unit.
    from shapely.ops import unary_union

    CLUSTER_BUFFER_M = 20
    lake_geoms = [g for g in lakes.geometry if g is not None and not g.is_empty]
    buffered = unary_union([g.buffer(CLUSTER_BUFFER_M) for g in lake_geoms])

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
        f"{len(cluster_lakes)} clusters (buffer={CLUSTER_BUFFER_M}m)"
    )

    # 4. Classify each cluster
    for _ci, members in cluster_lakes.items():
        # Union of all lake geometries in this cluster
        cluster_geom = unary_union(members) if len(members) > 1 else members[0]

        # Find touching streams (20m buffer for snapping tolerance)
        if streams.empty:
            touching = streams.iloc[0:0]
        else:
            touching = streams[
                streams.intersects(cluster_geom.buffer(CLUSTER_BUFFER_M))
            ]

        if touching.empty:
            # No streams at all → endorheic
            diagnostics["endorheic"] += len(members)
            for lake_geom in members:
                _add_drain_point(dem, transform, lake_geom, nodata, drain_points)
            continue

        # Analyze each touching stream for inflow/outflow
        has_outflow = False
        diagnostics["streams_analyzed"] += len(touching)

        for _s_idx, stream_row in touching.iterrows():
            stream_geom = stream_row.geometry
            if stream_geom is None or stream_geom.is_empty:
                continue

            coords = list(stream_geom.coords)
            if len(coords) < 2:
                continue

            start_pt = Point(coords[0])
            end_pt = Point(coords[-1])

            start_dist = cluster_geom.distance(start_pt)
            end_dist = cluster_geom.distance(end_pt)

            if start_dist <= end_dist:
                near_pt = start_pt
                far_pt = end_pt
            else:
                near_pt = end_pt
                far_pt = start_pt

            near_elev = _sample_dem_at_point(
                dem, transform, near_pt.x, near_pt.y, nodata
            )
            far_elev = _sample_dem_at_point(dem, transform, far_pt.x, far_pt.y, nodata)

            if near_elev is None or far_elev is None:
                diagnostics["undetermined"] += 1
                continue  # treat as inflow (conservative)

            if far_elev < near_elev - 0.1:
                # Far end is lower → outflow (water flows away)
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
        f"{diagnostics['streams_analyzed']} streams analyzed"
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
    from pyflwdir.dem import fill_depressions as pyflwdir_fill_depressions

    logger.info("Processing hydrology with pyflwdir (Deltares)...")

    nodata = metadata["nodata_value"]

    # Level 1: Fill internal nodata holes before depression filling
    dem_patched, holes_filled = fill_internal_nodata_holes(dem, nodata)
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

    # Restore nodata in filled_dem (original nodata + drain points)
    restore_mask = dem == nodata
    if drain_points:
        for row, col in drain_points:
            restore_mask[row, col] = True
    filled_dem[restore_mask] = nodata

    # Safety net: internal sinks, cells without a direction away from the edge
    # of the data. pyflwdir leaves none: its pits are the outlets of the area,
    # on the frame of the raster and next to nodata or a drain point
    sinks = _internal_sinks(
        fdir_arr,
        filled_dem,
        np.result_type(filled_dem.dtype, nodata).type(nodata),
        D8_VALID,
    )
    sink_count = sinks.size

    if sink_count > 0:
        # Log breakdown of invalid fdir values
        invalid_fdir = fdir_arr.ravel()[sinks]
        unique_vals, counts = np.unique(invalid_fdir, return_counts=True)
        breakdown = ", ".join(
            f"fdir={v}: {c}" for v, c in zip(unique_vals, counts, strict=True)
        )
        logger.info(f"  Invalid fdir breakdown: {breakdown}")
        logger.info(f"  Found {sink_count} internal sinks, fixing...")
        fdir_arr, acc_arr, diag = fix_internal_sinks(
            fdir_arr, acc_arr, filled_dem, filled_dem, nodata
        )
        logger.info(
            f"  Fixed {diag['total_fixed']} sinks "
            f"(steepest: {diag['by_strategy']['steepest']}, "
            f"max_acc: {diag['by_strategy']['max_acc']}, "
            f"any_valid: {diag['by_strategy']['any_valid']})"
        )
    else:
        logger.info("  No internal sinks: the pits are outlets at the edge of the data")

    logger.info("Hydrology processing complete")
    return filled_dem, fdir_arr, acc_arr, flw
