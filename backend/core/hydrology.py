"""
Hydrological processing: depression filling, flow direction, flow accumulation.

Core D8 flow direction constants, internal nodata hole filling,
stream burning, endorheic lake classification, pyflwdir-based hydrology,
sink fixing, and flow accumulation recomputation.
"""

import logging
from pathlib import Path

import numpy as np

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


def fill_internal_nodata_holes(
    dem: np.ndarray,
    nodata: float,
    min_valid_neighbors: int = 5,
    max_iterations: int = 3,
) -> tuple[np.ndarray, int]:
    """
    Wypelnia wewnetrzne dziury nodata w DEM.

    Iteracyjnie wypelnia komorki nodata otoczone wystarczajaca liczba
    validnych sasiadow (okno 3x3). Komorki brzegowe i duze bloki nodata
    nie sa wypelniane.

    Parameters
    ----------
    dem : np.ndarray
        Input DEM array
    nodata : float
        NoData value
    min_valid_neighbors : int
        Minimalna liczba validnych sasiadow (z 8) aby uznac za dziure wewnetrzna
    max_iterations : int
        Maksymalna liczba iteracji wypelniania

    Returns
    -------
    tuple
        (patched_dem, total_filled) — naprawiony DEM i liczba wypelnionych komorek
    """
    from scipy.ndimage import generic_filter

    patched = dem.copy()
    total_filled = 0

    for iteration in range(max_iterations):
        nodata_mask = patched == nodata
        if not np.any(nodata_mask):
            break

        # Count valid neighbors for each cell (3x3 window)
        valid_map = (patched != nodata).astype(np.float64)

        def count_valid_neighbors(window):
            # window is 3x3 flattened (9 elements), center is index 4
            return np.sum(window) - window[4]

        neighbor_count = generic_filter(
            valid_map, count_valid_neighbors, size=3, mode="constant", cval=0.0
        )

        # Internal holes: nodata cells with enough valid neighbors
        fillable = nodata_mask & (neighbor_count >= min_valid_neighbors)

        if not np.any(fillable):
            break

        # Compute mean of valid neighbors for each cell
        def mean_valid_neighbors(window):
            center = window[4]
            neighbors = np.concatenate([window[:4], window[5:]])
            valid = neighbors[neighbors != nodata]
            if len(valid) == 0:
                return center
            return np.mean(valid)

        neighbor_mean = generic_filter(
            patched, mean_valid_neighbors, size=3, mode="constant", cval=nodata
        )

        filled_count = int(np.sum(fillable))
        patched[fillable] = neighbor_mean[fillable]
        total_filled += filled_count

        logger.debug(
            f"  fill_internal_nodata_holes iteration {iteration + 1}: "
            f"filled {filled_count} cells"
        )

        if filled_count == 0:
            break

    return patched, total_filled


def burn_streams_into_dem(
    dem: np.ndarray,
    transform,
    streams_path,
    burn_depth_m: float = 10.0,
    nodata: float = -9999.0,
) -> tuple[np.ndarray, dict]:
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
        Depth to burn streams (meters), default 5.0
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
    import geopandas as gpd
    from rasterio.features import rasterize
    from shapely.geometry import box

    diagnostics = {"cells_burned": 0, "streams_loaded": 0, "streams_in_extent": 0}
    burned = dem.copy()

    # 1. Load streams (multi-layer GeoPackage support)
    streams_path = Path(streams_path)
    try:
        import fiona

        layers = fiona.listlayers(str(streams_path))
        if len(layers) > 1:
            # Multi-layer GeoPackage: load stream lines + lake polygons
            import pandas as pd

            target_prefixes = ["SWRS", "SWKN", "SWRM", "PTWP"]
            loaded_gdfs = []
            loaded_layer_names = []
            for layer in layers:
                for prefix in target_prefixes:
                    if prefix in layer.upper():
                        try:
                            gdf = gpd.read_file(streams_path, layer=layer)
                            if not gdf.empty:
                                loaded_gdfs.append(gdf)
                                loaded_layer_names.append(layer)
                        except Exception:
                            logger.debug(f"Could not read layer {layer}")
                        break

            if loaded_gdfs:
                streams = gpd.GeoDataFrame(pd.concat(loaded_gdfs, ignore_index=True))
                if hasattr(loaded_gdfs[0], "crs") and loaded_gdfs[0].crs is not None:
                    streams = streams.set_crs(loaded_gdfs[0].crs)
                logger.info(
                    f"Multi-layer GeoPackage: loaded {len(loaded_gdfs)} layers "
                    f"({', '.join(loaded_layer_names)}), "
                    f"{len(streams)} features total"
                )
            else:
                streams = gpd.GeoDataFrame(geometry=[], crs="EPSG:2180")
        else:
            # Single-layer file
            streams = gpd.read_file(streams_path)
    except Exception:
        # Fallback: fiona not available or file not readable as multi-layer
        streams = gpd.read_file(streams_path)

    diagnostics["streams_loaded"] = len(streams)

    if streams.empty:
        logger.info("Stream burning: empty GeoDataFrame, skipping")
        return burned, diagnostics

    # 2. Validate/reproject CRS to EPSG:2180
    if streams.crs is not None and streams.crs.to_epsg() != 2180:
        logger.info(f"  Reprojecting streams from {streams.crs} to EPSG:2180")
        streams = streams.to_crs(epsg=2180)

    # 3. Clip to DEM extent
    nrows, ncols = dem.shape
    xmin = transform.c
    ymax = transform.f
    xmax = xmin + ncols * transform.a
    ymin = ymax + nrows * transform.e  # transform.e is negative

    dem_box = box(xmin, ymin, xmax, ymax)
    streams = streams[streams.intersects(dem_box)]
    streams = streams.clip(dem_box)
    diagnostics["streams_in_extent"] = len(streams)

    if streams.empty:
        logger.info("Stream burning: no streams within DEM extent, skipping")
        return burned, diagnostics

    # 4. Rasterize streams onto DEM grid
    geometries = [(geom, 1) for geom in streams.geometry if geom is not None]
    stream_mask = rasterize(
        geometries,
        out_shape=dem.shape,
        transform=transform,
        fill=0,
        dtype=np.uint8,
        all_touched=True,
    )

    # 5. Burn: lower DEM at stream cells (skip nodata)
    burn_cells = (stream_mask == 1) & (dem != nodata)
    burned[burn_cells] -= burn_depth_m
    diagnostics["cells_burned"] = int(np.sum(burn_cells))

    logger.info(
        f"Stream burning: {diagnostics['cells_burned']} cells burned "
        f"(depth={burn_depth_m}m, streams={diagnostics['streams_in_extent']})"
    )

    return burned, diagnostics


def _sample_dem_at_point(
    dem: np.ndarray,
    transform,
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
    transform,
    gpkg_path: str | Path,
    nodata: float,
) -> tuple[list[tuple[int, int]], dict]:
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
    }
    drain_points: list[tuple[int, int]] = []

    # Build DEM extent box
    nrows, ncols = dem.shape
    xmin = transform.c
    ymax = transform.f
    xmax = xmin + ncols * transform.a
    ymin = ymax + nrows * transform.e  # transform.e is negative
    dem_box = box(xmin, ymin, xmax, ymax)

    # 1. Load water body polygons (OT_PTWP_A)
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

    diagnostics["total_lakes"] = len(lakes)

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
    cluster_lakes: dict[int, list] = {}
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
    transform,
    lake_geom,
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
    Rekompozycja flow accumulation z algorytmem Kahna (BFS topological sort).

    W odroznieniu od legacy compute_flow_accumulation():
    - Pomija komorki nodata (acc=0)
    - Brak deprecation warning
    - Obsluguje komorki z fdir=0 (brzeg/outlet) jako terminale

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
    from collections import deque

    nrows, ncols = fdir.shape
    acc = np.zeros((nrows, ncols), dtype=np.int32)
    inflow_count = np.zeros((nrows, ncols), dtype=np.int32)

    # Set acc=1 for valid cells, 0 for nodata
    valid = dem != nodata
    acc[valid] = 1

    # Count inflows for each cell
    for i in range(nrows):
        for j in range(ncols):
            if not valid[i, j]:
                continue
            d = fdir[i, j]
            if d in D8_DIRECTIONS:
                di, dj = D8_DIRECTIONS[d]
                ni, nj = i + di, j + dj
                if 0 <= ni < nrows and 0 <= nj < ncols and valid[ni, nj]:
                    inflow_count[ni, nj] += 1

    # BFS from headwaters (valid cells with no inflows and valid fdir)
    queue = deque()
    for i in range(nrows):
        for j in range(ncols):
            if valid[i, j] and inflow_count[i, j] == 0:
                queue.append((i, j))

    while queue:
        i, j = queue.popleft()
        d = fdir[i, j]
        if d in D8_DIRECTIONS:
            di, dj = D8_DIRECTIONS[d]
            ni, nj = i + di, j + dj
            if 0 <= ni < nrows and 0 <= nj < ncols and valid[ni, nj]:
                acc[ni, nj] += acc[i, j]
                inflow_count[ni, nj] -= 1
                if inflow_count[ni, nj] == 0:
                    queue.append((ni, nj))

    return acc


def fix_internal_sinks(
    fdir: np.ndarray,
    acc: np.ndarray,
    filled_dem: np.ndarray,
    dem: np.ndarray,
    nodata: float,
    max_iterations: int = 3,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """
    Naprawia wewnetrzne zlewy po pyflwdir.

    Dla kazdej wewnetrznej komorki z fdir=0 (nie na brzegu, nie nodata):
    1. Steepest descent — najstromiszy spadek do sasiada (z filled_dem)
    2. Max accumulation — sasiad z najwyzsza akumulacja
    3. Any valid — dowolny validny sasiad

    Po naprawie rekompozycja flow accumulation.

    Parameters
    ----------
    fdir : np.ndarray
        Flow direction array (D8 encoding)
    acc : np.ndarray
        Flow accumulation array
    filled_dem : np.ndarray
        DEM po depression filling
    dem : np.ndarray
        Oryginalny filled DEM (for nodata detection)
    nodata : float
        NoData value
    max_iterations : int
        Maksymalna liczba iteracji naprawy

    Returns
    -------
    tuple
        (fixed_fdir, recomputed_acc, diagnostics)
        diagnostics: dict with 'total_fixed', 'by_strategy', 'iterations'
    """
    nrows, ncols = fdir.shape
    fdir_fixed = fdir.copy()

    directions = [1, 2, 4, 8, 16, 32, 64, 128]
    offsets = [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)]
    distances = [1.0, 1.414, 1.0, 1.414, 1.0, 1.414, 1.0, 1.414]

    valid = dem != nodata
    edge_mask = np.zeros((nrows, ncols), dtype=bool)
    edge_mask[0, :] = True
    edge_mask[-1, :] = True
    edge_mask[:, 0] = True
    edge_mask[:, -1] = True

    diag = {
        "total_fixed": 0,
        "by_strategy": {"steepest": 0, "max_acc": 0, "any_valid": 0},
        "iterations": 0,
    }

    for iteration in range(max_iterations):
        # Find internal sinks: fdir not a valid D8 direction, valid, not on edge
        # pysheds returns 0 (nodata), -1 (pit/outlet), -2 (unresolved flat)
        is_valid_d8 = np.isin(fdir_fixed, list(VALID_D8_SET))
        internal_sinks = ~is_valid_d8 & valid & ~edge_mask
        sink_rows, sink_cols = np.where(internal_sinks)
        sink_indices = list(zip(sink_rows, sink_cols, strict=True))

        if not sink_indices:
            break

        diag["iterations"] = iteration + 1
        fixed_this_iter = 0

        for i, j in sink_indices:
            best_dir = None
            strategy = None

            # Strategy 1: steepest descent using filled_dem
            max_slope = 0.0
            for d, (di, dj), dist in zip(directions, offsets, distances, strict=True):
                ni, nj = i + di, j + dj
                if 0 <= ni < nrows and 0 <= nj < ncols and valid[ni, nj]:
                    slope = (filled_dem[i, j] - filled_dem[ni, nj]) / dist
                    if slope > max_slope:
                        max_slope = slope
                        best_dir = d
                        strategy = "steepest"

            # Strategy 2: max accumulation neighbor
            if best_dir is None:
                max_acc_val = -1
                for d, (di, dj), _dist in zip(
                    directions, offsets, distances, strict=True
                ):
                    ni, nj = i + di, j + dj
                    if (
                        0 <= ni < nrows
                        and 0 <= nj < ncols
                        and valid[ni, nj]
                        and acc[ni, nj] > max_acc_val
                    ):
                        max_acc_val = acc[ni, nj]
                        best_dir = d
                        strategy = "max_acc"

            # Strategy 3: any valid neighbor
            if best_dir is None:
                for d, (di, dj), _dist in zip(
                    directions, offsets, distances, strict=True
                ):
                    ni, nj = i + di, j + dj
                    if 0 <= ni < nrows and 0 <= nj < ncols and valid[ni, nj]:
                        best_dir = d
                        strategy = "any_valid"
                        break

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
    metadata: dict,
    drain_points: list[tuple[int, int]] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
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
        (filled_dem, flow_direction, flow_accumulation, d8_fdir) arrays
        - filled_dem: DEM po wypelnieniu zaglebie (rzeczywiste wysokosci)
        - flow_direction: kierunki splywy D8 (int16, nodata=0)
        - flow_accumulation: akumulacja przeplywu (po fix_internal_sinks)
        - d8_fdir: oryginalny pyflwdir D8 (uint8) do budowy FlwdirRaster
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

    # Flow accumulation via FlwdirRaster
    logger.info("  Computing flow accumulation...")
    flw = pyflwdir.from_array(d8_fdir, ftype="d8", transform=transform, latlon=False)
    acc_float = flw.upstream_area(unit="cell")
    acc_arr = np.where(acc_float == -9999, 0, acc_float).astype(np.int32)

    # Restore nodata in filled_dem (original nodata + drain points)
    restore_mask = dem == nodata
    if drain_points:
        for row, col in drain_points:
            restore_mask[row, col] = True
    filled_dem[restore_mask] = nodata

    # Safety net: fix internal sinks (if pyflwdir left any)
    valid = filled_dem != nodata
    edge_mask = np.zeros_like(valid)
    edge_mask[0, :] = True
    edge_mask[-1, :] = True
    edge_mask[:, 0] = True
    edge_mask[:, -1] = True

    is_valid_d8 = np.isin(fdir_arr, list(VALID_D8_SET))
    internal_sinks = ~is_valid_d8 & valid & ~edge_mask
    sink_count = int(np.sum(internal_sinks))

    if sink_count > 0:
        # Log breakdown of invalid fdir values
        invalid_fdir = fdir_arr[internal_sinks]
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
        logger.info("  All internal cells have valid flow direction")

    logger.info("Hydrology processing complete")
    return filled_dem, fdir_arr, acc_arr, d8_fdir
