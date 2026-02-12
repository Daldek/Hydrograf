"""
Script to process DEM (Digital Elevation Model) and populate flow_network table.

Reads ASCII GRID DEM file or VRT mosaic, computes hydrological parameters
(flow direction, flow accumulation, slope), and loads data into PostgreSQL/PostGIS.

Supports:
- Single ASCII GRID (.asc) files
- VRT mosaics (.vrt) created from multiple tiles
- GeoTIFF (.tif) files

For multi-tile processing, use VRT mosaic to ensure hydrological continuity
across tile boundaries. See utils/raster_utils.py for VRT creation.

Usage
-----
    cd backend
    python -m scripts.process_dem --help
    python -m scripts.process_dem --input ../data/nmt/N-33-131-D-a-3-2.asc

Examples
--------
    # Process single DEM tile
    python -m scripts.process_dem \\
        --input ../data/nmt/N-33-131-D-a-3-2.asc \\
        --stream-threshold 100

    # Process VRT mosaic (multiple tiles)
    python -m scripts.process_dem \\
        --input ../data/nmt/mosaic.vrt \\
        --stream-threshold 100

    # Dry run (only show statistics)
    python -m scripts.process_dem \\
        --input ../data/nmt/N-33-131-D-a-3-2.asc \\
        --dry-run

    # Process with custom batch size
    python -m scripts.process_dem \\
        --input ../data/nmt/N-33-131-D-a-3-2.asc \\
        --batch-size 50000
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
from sqlalchemy import text

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
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


def save_raster_geotiff(
    data: np.ndarray,
    metadata: dict,
    output_path: Path,
    nodata: float = -9999.0,
    dtype: str = "float32",
) -> None:
    """
    Save numpy array as GeoTIFF with PL-1992 (EPSG:2180) CRS.

    Uses the original transform from input raster if available to ensure
    perfect alignment with source DEM.

    Parameters
    ----------
    data : np.ndarray
        Raster data array
    metadata : dict
        Grid metadata with transform (preferred) or xllcorner, yllcorner, cellsize
    output_path : Path
        Output GeoTIFF path
    nodata : float
        NoData value
    dtype : str
        Output data type ('float32', 'int32', 'int16')
    """
    import rasterio
    from rasterio.transform import from_bounds

    nrows, ncols = data.shape

    # Preferuj oryginalną transformację z pliku wejściowego (idealne wyrównanie)
    if "transform" in metadata:
        transform = metadata["transform"]
    else:
        # Fallback: oblicz z bounds (może być niedokładne)
        cellsize = metadata["cellsize"]
        xll = metadata["xllcorner"]
        yll = metadata["yllcorner"]
        xmin = xll
        ymin = yll
        xmax = xll + ncols * cellsize
        ymax = yll + nrows * cellsize
        transform = from_bounds(xmin, ymin, xmax, ymax, ncols, nrows)

    # Map dtype string to numpy/rasterio dtype
    dtype_map = {
        "float32": (np.float32, rasterio.float32),
        "float64": (np.float64, rasterio.float64),
        "int32": (np.int32, rasterio.int32),
        "int16": (np.int16, rasterio.int16),
        "uint8": (np.uint8, rasterio.uint8),
    }

    np_dtype, rio_dtype = dtype_map.get(dtype, (np.float32, rasterio.float32))

    # Prepare data (flip vertically because ASCII GRID is top-down)
    out_data = data.astype(np_dtype)

    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=nrows,
        width=ncols,
        count=1,
        dtype=rio_dtype,
        crs="EPSG:2180",
        transform=transform,
        nodata=nodata,
        compress="lzw",
    ) as dst:
        dst.write(out_data, 1)

    logger.info(f"Saved: {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")


def read_raster(filepath: Path) -> tuple[np.ndarray, dict]:
    """
    Read raster file (ASC, VRT, or GeoTIFF) using rasterio.

    This is the preferred method as it handles all formats uniformly
    and works with VRT mosaics for multi-tile processing.

    Parameters
    ----------
    filepath : Path
        Path to raster file (.asc, .vrt, .tif)

    Returns
    -------
    tuple
        (data array, metadata dict with ncols, nrows, xllcorner, yllcorner, cellsize, nodata)

    Raises
    ------
    FileNotFoundError
        If file does not exist
    """
    import rasterio

    if not filepath.exists():
        raise FileNotFoundError(f"Raster file not found: {filepath}")

    logger.info(f"Reading raster: {filepath}")

    with rasterio.open(filepath) as src:
        data = src.read(1)

        # Build metadata compatible with ASCII grid format
        metadata = {
            "ncols": src.width,
            "nrows": src.height,
            "xllcorner": src.bounds.left,
            "yllcorner": src.bounds.bottom,
            "cellsize": abs(src.transform.a),  # Pixel width
            "nodata_value": src.nodata if src.nodata is not None else -9999.0,
            # Additional info
            "crs": str(src.crs),
            "bounds": src.bounds,
            "transform": src.transform,
        }

    logger.info(f"Read raster: {metadata['nrows']}x{metadata['ncols']} cells")
    logger.info(f"Origin: ({metadata['xllcorner']:.1f}, {metadata['yllcorner']:.1f})")
    logger.info(f"Cell size: {metadata['cellsize']} m")
    logger.info(f"Total cells: {metadata['nrows'] * metadata['ncols']:,}")

    return data, metadata


def read_ascii_grid(filepath: Path) -> tuple[np.ndarray, dict]:
    """
    Read ARC/INFO ASCII GRID file.

    Supports both corner (xllcorner/yllcorner) and center (xllcenter/yllcenter)
    coordinate formats. Center coordinates are converted to corner.

    Note: For VRT mosaics or GeoTIFF files, use read_raster() instead.

    Parameters
    ----------
    filepath : Path
        Path to .asc file

    Returns
    -------
    tuple
        (data array, metadata dict with ncols, nrows, xllcorner, yllcorner, cellsize, nodata)

    Raises
    ------
    FileNotFoundError
        If file does not exist
    ValueError
        If file format is invalid
    """
    if not filepath.exists():
        raise FileNotFoundError(f"DEM file not found: {filepath}")

    metadata = {}
    header_lines = 6

    with open(filepath) as f:
        # Read header
        for _i in range(header_lines):
            line = f.readline().strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].lower()
                value = parts[1]
                if key in ("ncols", "nrows"):
                    metadata[key] = int(value)
                elif key in (
                    "xllcorner",
                    "yllcorner",
                    "xllcenter",
                    "yllcenter",
                    "cellsize",
                    "nodata_value",
                ):
                    metadata[key] = float(value)

    # Handle center vs corner coordinates
    # If center is provided, convert to corner
    if "xllcenter" in metadata and "xllcorner" not in metadata:
        metadata["xllcorner"] = metadata["xllcenter"] - metadata.get("cellsize", 0) / 2
        logger.info("Converted xllcenter to xllcorner")
    if "yllcenter" in metadata and "yllcorner" not in metadata:
        metadata["yllcorner"] = metadata["yllcenter"] - metadata.get("cellsize", 0) / 2
        logger.info("Converted yllcenter to yllcorner")

    # Validate required fields
    required = ["ncols", "nrows", "xllcorner", "yllcorner", "cellsize"]
    for field in required:
        if field not in metadata:
            raise ValueError(f"Missing required header field: {field}")

    # Set default nodata if not present
    if "nodata_value" not in metadata:
        metadata["nodata_value"] = -9999.0

    # Read data
    data = np.loadtxt(filepath, skiprows=header_lines)

    if data.shape != (metadata["nrows"], metadata["ncols"]):
        raise ValueError(
            f"Data shape {data.shape} doesn't match header "
            f"({metadata['nrows']}, {metadata['ncols']})"
        )

    logger.info(f"Read DEM: {metadata['nrows']}x{metadata['ncols']} cells")
    logger.info(f"Origin: ({metadata['xllcorner']:.1f}, {metadata['yllcorner']:.1f})")
    logger.info(f"Cell size: {metadata['cellsize']} m")

    return data, metadata


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
    streams_path: Path,
    burn_depth_m: float = 5.0,
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

    # 1. Load streams
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

    # Restore nodata in filled_dem
    filled_dem[dem == nodata] = nodata

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


def process_hydrology_whitebox(
    dem: np.ndarray,
    metadata: dict,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Process DEM using WhiteboxTools for hydrological analysis.

    WhiteboxTools uses more robust algorithms for depression filling
    and flat area resolution than pysheds, especially for large flat areas.

    Parameters
    ----------
    dem : np.ndarray
        Input DEM array
    metadata : dict
        Grid metadata with xllcorner, yllcorner, cellsize, nodata_value

    Returns
    -------
    tuple
        (filled_dem, flow_direction, flow_accumulation) arrays
    """
    import tempfile

    import rasterio
    from rasterio.transform import from_bounds
    from whitebox import WhiteboxTools

    logger.info("Processing hydrology with WhiteboxTools...")

    wbt = WhiteboxTools()
    wbt.set_verbose_mode(False)

    nodata = metadata["nodata_value"]
    nrows, ncols = dem.shape
    cellsize = metadata["cellsize"]
    xll = metadata["xllcorner"]
    yll = metadata["yllcorner"]

    # Calculate bounds
    xmin = xll
    ymin = yll
    xmax = xll + ncols * cellsize
    ymax = yll + nrows * cellsize

    transform = from_bounds(xmin, ymin, xmax, ymax, ncols, nrows)

    # Create temp directory for intermediate files
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dem = f"{tmpdir}/dem.tif"
        filled_dem_path = f"{tmpdir}/filled.tif"
        flowdir_path = f"{tmpdir}/flowdir.tif"
        flowacc_path = f"{tmpdir}/flowacc.tif"

        # Write input DEM
        with rasterio.open(
            input_dem,
            "w",
            driver="GTiff",
            height=nrows,
            width=ncols,
            count=1,
            dtype=rasterio.float32,
            crs="EPSG:2180",
            transform=transform,
            nodata=nodata,
        ) as dst:
            dst.write(dem.astype(np.float32), 1)

        # Step 1: Fill depressions (breach preferred for realistic results)
        logger.info("  Step 1/3: Filling depressions (breach algorithm)...")
        try:
            wbt.breach_depressions_least_cost(
                input_dem,
                filled_dem_path,
                dist=10,  # max breach distance
                fill=True,  # fill remaining depressions
            )
        except Exception as e:
            logger.warning(f"  Breach failed ({e}), trying fill_depressions...")
            wbt.fill_depressions(input_dem, filled_dem_path)

        # Step 2: Compute flow direction (D8)
        logger.info("  Step 2/3: Computing flow direction (D8)...")
        wbt.d8_pointer(filled_dem_path, flowdir_path)

        # Step 3: Compute flow accumulation (using the D8 pointer for consistency)
        logger.info("  Step 3/3: Computing flow accumulation...")
        wbt.d8_flow_accumulation(flowdir_path, flowacc_path, pntr=True)

        # Read results
        with rasterio.open(filled_dem_path) as src:
            filled_dem = src.read(1)

        with rasterio.open(flowdir_path) as src:
            fdir_wbt = src.read(1)

        with rasterio.open(flowacc_path) as src:
            acc = src.read(1)

    # Convert WhiteboxTools flow direction to pysheds/standard D8 encoding
    # WBT uses: 1=E, 2=NE, 4=N, 8=NW, 16=W, 32=SW, 64=S, 128=SE
    # Standard: 1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE
    # Need to remap: WBT -> Standard
    wbt_to_d8 = {
        1: 1,  # E -> E
        2: 128,  # NE -> NE
        4: 64,  # N -> N
        8: 32,  # NW -> NW
        16: 16,  # W -> W
        32: 8,  # SW -> SW
        64: 4,  # S -> S
        128: 2,  # SE -> SE
        0: 0,  # nodata/outlet
    }

    fdir_arr = np.zeros_like(fdir_wbt, dtype=np.int16)
    for wbt_val, d8_val in wbt_to_d8.items():
        fdir_arr[fdir_wbt == wbt_val] = d8_val

    acc_arr = acc.astype(np.int32)

    # Handle nodata
    filled_dem[filled_dem == nodata] = nodata
    fdir_arr[dem == nodata] = 0
    acc_arr[dem == nodata] = 0

    # Verify no internal sinks
    valid = filled_dem != nodata
    edge_mask = np.zeros_like(valid)
    edge_mask[0, :] = True
    edge_mask[-1, :] = True
    edge_mask[:, 0] = True
    edge_mask[:, -1] = True

    is_valid_d8 = np.isin(fdir_arr, list(VALID_D8_SET))
    internal_no_flow = ~is_valid_d8 & valid & ~edge_mask

    if np.sum(internal_no_flow) > 0:
        logger.warning(
            f"  {np.sum(internal_no_flow)} internal cells without valid flow direction"
        )
    else:
        logger.info("  All internal cells have valid flow direction")

    logger.info("Hydrology processing complete (WhiteboxTools)")
    return filled_dem, fdir_arr, acc_arr


def fill_depressions(dem: np.ndarray, nodata: float) -> np.ndarray:
    """
    Fill depressions (sinks) in DEM.

    Note: This is a legacy wrapper. The main processing now uses
    process_hydrology_pyflwdir() which handles fill, resolve flats,
    and flow direction together for correct results.

    Parameters
    ----------
    dem : np.ndarray
        Input DEM array
    nodata : float
        NoData value

    Returns
    -------
    np.ndarray
        Filled DEM
    """
    logger.warning(
        "Using legacy fill_depressions - consider using process_hydrology_pyflwdir()"
    )
    # Return unchanged - actual filling happens in process_hydrology_pyflwdir
    return dem.copy()


def compute_flow_direction(dem: np.ndarray, nodata: float) -> np.ndarray:
    """
    Compute D8 flow direction.

    Note: This is a legacy wrapper. The main processing now uses
    process_hydrology_pyflwdir() which handles fill, resolve flats,
    and flow direction together for correct results.

    Parameters
    ----------
    dem : np.ndarray
        Filled DEM array
    nodata : float
        NoData value

    Returns
    -------
    np.ndarray
        Flow direction array (D8 encoding)
    """
    logger.warning(
        "Using legacy compute_flow_direction"
        " - consider using process_hydrology_pyflwdir()"
    )

    nrows, ncols = dem.shape
    fdir = np.zeros((nrows, ncols), dtype=np.int16)

    directions = [1, 2, 4, 8, 16, 32, 64, 128]
    offsets = [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)]
    distances = [1, 1.414, 1, 1.414, 1, 1.414, 1, 1.414]

    for i in range(nrows):
        for j in range(ncols):
            if dem[i, j] == nodata:
                fdir[i, j] = 0
                continue

            max_slope = 0
            flow_dir = 0

            for d, (di, dj), dist in zip(directions, offsets, distances):
                ni, nj = i + di, j + dj
                if 0 <= ni < nrows and 0 <= nj < ncols:
                    if dem[ni, nj] != nodata:
                        slope = (dem[i, j] - dem[ni, nj]) / dist
                        if slope > max_slope:
                            max_slope = slope
                            flow_dir = d

            fdir[i, j] = flow_dir

    return fdir


def compute_flow_accumulation(fdir: np.ndarray) -> np.ndarray:
    """
    Compute flow accumulation from flow direction.

    Note: This is a legacy wrapper. The main processing now uses
    process_hydrology_pyflwdir() which computes accumulation correctly.

    Parameters
    ----------
    fdir : np.ndarray
        Flow direction array (D8 encoding)

    Returns
    -------
    np.ndarray
        Flow accumulation array (number of upstream cells)
    """
    logger.warning(
        "Using legacy compute_flow_accumulation"
        " - consider using process_hydrology_pyflwdir()"
    )

    from collections import deque

    nrows, ncols = fdir.shape
    acc = np.ones((nrows, ncols), dtype=np.int32)
    inflow_count = np.zeros((nrows, ncols), dtype=np.int32)

    for i in range(nrows):
        for j in range(ncols):
            d = fdir[i, j]
            if d in D8_DIRECTIONS:
                di, dj = D8_DIRECTIONS[d]
                ni, nj = i + di, j + dj
                if 0 <= ni < nrows and 0 <= nj < ncols:
                    inflow_count[ni, nj] += 1

    queue = deque()
    for i in range(nrows):
        for j in range(ncols):
            if inflow_count[i, j] == 0 and fdir[i, j] != 0:
                queue.append((i, j))

    while queue:
        i, j = queue.popleft()
        d = fdir[i, j]
        if d in D8_DIRECTIONS:
            di, dj = D8_DIRECTIONS[d]
            ni, nj = i + di, j + dj
            if 0 <= ni < nrows and 0 <= nj < ncols:
                acc[ni, nj] += acc[i, j]
                inflow_count[ni, nj] -= 1
                if inflow_count[ni, nj] == 0:
                    queue.append((ni, nj))

    return acc


def compute_slope(dem: np.ndarray, cellsize: float, nodata: float) -> np.ndarray:
    """
    Compute slope in percent.

    Parameters
    ----------
    dem : np.ndarray
        DEM array
    cellsize : float
        Cell size in meters
    nodata : float
        NoData value

    Returns
    -------
    np.ndarray
        Slope array in percent
    """
    logger.info("Computing slope...")

    # Use Sobel operator for gradient
    from scipy import ndimage

    # Replace nodata with nan for calculations
    dem_calc = dem.astype(np.float64)
    dem_calc[dem == nodata] = np.nan

    # Compute gradients
    dy = ndimage.sobel(dem_calc, axis=0, mode="constant", cval=np.nan) / (8 * cellsize)
    dx = ndimage.sobel(dem_calc, axis=1, mode="constant", cval=np.nan) / (8 * cellsize)

    # Slope in percent
    slope = np.sqrt(dx**2 + dy**2) * 100

    # Replace nan with 0
    slope = np.nan_to_num(slope, nan=0.0)

    logger.info(f"Slope computed (range: {slope.min():.1f}% - {slope.max():.1f}%)")
    return slope


def compute_aspect(dem: np.ndarray, cellsize: float, nodata: float) -> np.ndarray:
    """
    Compute aspect (slope direction) in degrees.

    Uses Sobel operator for gradient computation (same as compute_slope).
    Convention: 0=North, 90=East, 180=South, 270=West (clockwise from North).
    Flat areas (no gradient) get value -1.

    Parameters
    ----------
    dem : np.ndarray
        DEM array
    cellsize : float
        Cell size in meters
    nodata : float
        NoData value

    Returns
    -------
    np.ndarray
        Aspect array in degrees (0-360, -1 for flat areas)
    """
    logger.info("Computing aspect...")

    from scipy import ndimage

    dem_calc = dem.astype(np.float64)
    dem_calc[dem == nodata] = np.nan

    # Compute gradients (same Sobel as slope)
    dy = ndimage.sobel(dem_calc, axis=0, mode="constant", cval=np.nan) / (8 * cellsize)
    dx = ndimage.sobel(dem_calc, axis=1, mode="constant", cval=np.nan) / (8 * cellsize)

    # Aspect: atan2(-dy, dx) gives angle from East, counter-clockwise
    # Convert to geographic convention: 0=N, clockwise
    # Geographic aspect = 90 - degrees(atan2(-dy, dx))
    # Equivalently: atan2(-dx, dy) gives 0=N clockwise directly
    aspect_rad = np.arctan2(-dx, dy)
    aspect_deg = np.degrees(aspect_rad)

    # Convert to 0-360 range
    aspect_deg = np.where(aspect_deg < 0, aspect_deg + 360.0, aspect_deg)

    # Mark flat areas (no gradient) as -1
    flat_mask = (dx == 0) & (dy == 0)
    aspect_deg[flat_mask] = -1.0

    # Mark nodata areas as -1
    aspect_deg = np.nan_to_num(aspect_deg, nan=-1.0)

    valid = aspect_deg[aspect_deg >= 0]
    if len(valid) > 0:
        logger.info(
            f"Aspect computed (range: {valid.min():.1f}° - {valid.max():.1f}°)"
        )
    else:
        logger.info("Aspect computed (all flat)")

    return aspect_deg


def compute_strahler_order(
    dem: np.ndarray,
    metadata: dict,
    stream_threshold: int = 100,
) -> np.ndarray:
    """
    Compute Strahler stream order using pyflwdir.

    .. deprecated::
        Use ``compute_strahler_from_fdir()`` instead — it reuses
        pre-computed fdir/acc from the main pipeline, avoiding
        inconsistency between Strahler and vectorized streams.

    Uses pyflwdir's FlwdirRaster.stream_order() method.
    Only stream cells (flow_accumulation >= threshold) get an order.
    Non-stream cells have order 0 (nodata).

    Parameters
    ----------
    dem : np.ndarray
        Filled DEM array
    metadata : dict
        Grid metadata with transform or xllcorner/yllcorner/cellsize, nodata_value
    stream_threshold : int
        Flow accumulation threshold for stream identification

    Returns
    -------
    np.ndarray
        Strahler stream order array (uint8, nodata=0)
    """
    import pyflwdir
    from pyflwdir.dem import fill_depressions as pyflwdir_fill_depressions

    logger.info("Computing Strahler stream order via pyflwdir...")

    nodata = metadata["nodata_value"]

    # Patch internal nodata holes (same as main pipeline)
    dem_patched, _ = fill_internal_nodata_holes(dem, nodata)

    # Depression filling + D8 flow direction
    _filled, d8_fdir = pyflwdir_fill_depressions(
        dem_patched, nodata=nodata, max_depth=-1.0, outlets="edge"
    )

    # Build transform
    transform = metadata.get("transform")
    if transform is None:
        from rasterio.transform import from_bounds

        xll, yll = metadata["xllcorner"], metadata["yllcorner"]
        nrows, ncols = dem.shape
        cs = metadata["cellsize"]
        transform = from_bounds(
            xll, yll, xll + ncols * cs, yll + nrows * cs, ncols, nrows
        )

    # Build FlwdirRaster
    flw = pyflwdir.from_array(d8_fdir, ftype="d8", transform=transform, latlon=False)

    # Compute upstream area for mask
    acc_float = flw.upstream_area(unit="cell")
    acc = np.where(acc_float == -9999, 0, acc_float).astype(np.int32)

    # Stream mask
    stream_mask = acc >= stream_threshold

    # Compute Strahler order
    strahler = flw.stream_order(type="strahler", mask=stream_mask)
    strahler = strahler.astype(np.uint8)

    # Non-stream cells → 0 (nodata)
    strahler[~stream_mask] = 0

    max_order = int(strahler.max()) if np.any(strahler > 0) else 0
    stream_count = int(np.sum(strahler > 0))
    logger.info(
        f"Strahler order computed (max order: {max_order}, "
        f"stream cells: {stream_count:,})"
    )

    return strahler


def compute_strahler_from_fdir(
    d8_fdir: np.ndarray,
    acc: np.ndarray,
    metadata: dict,
    stream_threshold: int,
) -> np.ndarray:
    """
    Compute Strahler stream order using pre-computed fdir and acc.

    Unlike ``compute_strahler_order()``, this function does NOT recompute
    hydrology from scratch. It reuses the same ``d8_fdir`` and ``acc``
    produced by ``process_hydrology_pyflwdir()``, ensuring that Strahler
    orders are consistent with the vectorized stream network.

    Parameters
    ----------
    d8_fdir : np.ndarray
        Original pyflwdir D8 flow direction (uint8, nodata=247, pit=0)
    acc : np.ndarray
        Flow accumulation from the main pipeline (after fix_internal_sinks)
    metadata : dict
        Grid metadata with transform or xllcorner/yllcorner/cellsize
    stream_threshold : int
        Flow accumulation threshold (in cells) for stream identification

    Returns
    -------
    np.ndarray
        Strahler stream order array (uint8, nodata=0)
    """
    import pyflwdir

    logger.info("Computing Strahler stream order (from pre-computed fdir)...")

    transform = metadata.get("transform")
    if transform is None:
        from rasterio.transform import from_bounds

        xll, yll = metadata["xllcorner"], metadata["yllcorner"]
        nrows, ncols = d8_fdir.shape
        cs = metadata["cellsize"]
        transform = from_bounds(
            xll, yll, xll + ncols * cs, yll + nrows * cs, ncols, nrows
        )

    flw = pyflwdir.from_array(d8_fdir, ftype="d8", transform=transform, latlon=False)

    stream_mask = acc >= stream_threshold
    strahler = flw.stream_order(type="strahler", mask=stream_mask).astype(np.uint8)
    strahler[~stream_mask] = 0

    max_order = int(strahler.max()) if np.any(strahler > 0) else 0
    stream_count = int(np.sum(strahler > 0))
    logger.info(
        f"Strahler order computed (max order: {max_order}, "
        f"stream cells: {stream_count:,})"
    )

    return strahler


def compute_twi(
    acc: np.ndarray,
    slope: np.ndarray,
    cellsize: float,
    nodata_acc: int = 0,
    min_slope_percent: float = 0.1,
) -> np.ndarray:
    """
    Compute Topographic Wetness Index (TWI).

    TWI = ln(SCA / tan(slope_rad)) where:
    - SCA = specific catchment area = upstream_area_m2 / cellsize
    - slope_rad = arctan(slope_percent / 100)
    - Minimum slope is clamped to avoid division by zero

    Parameters
    ----------
    acc : np.ndarray
        Flow accumulation array (number of upstream cells including self)
    slope : np.ndarray
        Slope array in percent
    cellsize : float
        Cell size in meters
    nodata_acc : int
        NoData value for accumulation (cells with this value are excluded)
    min_slope_percent : float
        Minimum slope in percent to avoid division by zero (default: 0.1%)

    Returns
    -------
    np.ndarray
        TWI array (float32, nodata=-9999)
    """
    logger.info("Computing TWI (Topographic Wetness Index)...")

    cell_area = cellsize * cellsize

    # Upstream area in m2 and specific catchment area (SCA)
    upstream_area_m2 = acc.astype(np.float64) * cell_area
    sca = upstream_area_m2 / cellsize

    # Clamp slope to minimum to avoid division by zero
    slope_clamped = np.maximum(slope, min_slope_percent)
    slope_rad = np.arctan(slope_clamped / 100.0)

    # TWI = ln(SCA / tan(slope_rad)), only for valid cells
    valid_mask = acc != nodata_acc
    tan_slope = np.tan(slope_rad)

    twi_result = np.full(acc.shape, -9999.0, dtype=np.float32)
    twi_result[valid_mask] = np.log(sca[valid_mask] / tan_slope[valid_mask]).astype(
        np.float32
    )

    valid = twi_result[twi_result > -9999]
    if len(valid) > 0:
        logger.info(
            f"TWI computed (range: {valid.min():.1f} - {valid.max():.1f})"
        )

    return twi_result


def vectorize_streams(
    dem: np.ndarray,
    fdir: np.ndarray,
    acc: np.ndarray,
    slope: np.ndarray,
    strahler: np.ndarray,
    metadata: dict,
    stream_threshold: int = 100,
    label_raster_out: np.ndarray | None = None,
) -> list[dict]:
    """
    Vectorize stream network from raster data as LineString segments.

    Traces connected stream cells from headwaters downstream to junctions
    or outlets. Each segment becomes a LineString with attributes.

    Parameters
    ----------
    dem : np.ndarray
        Filled DEM array
    fdir : np.ndarray
        Flow direction array (D8 encoding)
    acc : np.ndarray
        Flow accumulation array
    slope : np.ndarray
        Slope array (percent)
    strahler : np.ndarray
        Strahler stream order array (0 = non-stream)
    metadata : dict
        Grid metadata (xllcorner, yllcorner, cellsize, nodata_value)
    stream_threshold : int
        Flow accumulation threshold for stream identification
    label_raster_out : np.ndarray, optional
        Pre-allocated int32 array (same shape as dem). When provided,
        stream cells are painted with their 1-based segment index.
        Used by delineate_subcatchments() to seed downstream tracing.

    Returns
    -------
    list[dict]
        List of stream segment dicts with keys:
        - coords: list of (x, y) tuples
        - strahler_order: int
        - length_m: float
        - upstream_area_km2: float (at segment end)
        - mean_slope_percent: float
    """
    logger.info("Vectorizing stream network...")

    nrows, ncols = dem.shape
    cellsize = metadata["cellsize"]
    xll = metadata["xllcorner"]
    yll = metadata["yllcorner"]
    nodata = metadata["nodata_value"]
    cell_area = cellsize * cellsize

    stream_mask = (acc >= stream_threshold) & (dem != nodata)

    def cell_xy(row, col):
        """Get cell center coordinates in PL-1992."""
        x = xll + (col + 0.5) * cellsize
        y = yll + (nrows - row - 0.5) * cellsize
        return (x, y)

    def downstream_cell(row, col):
        """Get downstream cell (row, col) or None."""
        d = fdir[row, col]
        if d not in D8_DIRECTIONS:
            return None
        di, dj = D8_DIRECTIONS[d]
        ni, nj = row + di, col + dj
        if 0 <= ni < nrows and 0 <= nj < ncols and dem[ni, nj] != nodata:
            return (ni, nj)
        return None

    # Count upstream stream neighbors for each cell
    upstream_count = np.zeros((nrows, ncols), dtype=np.int32)
    for i in range(nrows):
        for j in range(ncols):
            if not stream_mask[i, j]:
                continue
            ds = downstream_cell(i, j)
            if ds is not None and stream_mask[ds[0], ds[1]]:
                upstream_count[ds[0], ds[1]] += 1

    # Headwaters: stream cells with no upstream stream neighbors
    headwaters = []
    for i in range(nrows):
        for j in range(ncols):
            if stream_mask[i, j] and upstream_count[i, j] == 0:
                headwaters.append((i, j))

    logger.info(f"  Found {len(headwaters)} headwater cells")

    # Trace segments from headwaters
    visited = np.zeros((nrows, ncols), dtype=bool)
    segments = []

    for hw_row, hw_col in headwaters:
        row, col = hw_row, hw_col

        while True:
            if visited[row, col]:
                break

            # Start new segment
            coords = [cell_xy(row, col)]
            slopes = [float(slope[row, col])]
            seg_order = max(int(strahler[row, col]), 1)
            length_m = 0.0
            visited[row, col] = True
            seg_rc_path = [(row, col)]

            # Trace downstream while same order
            while True:
                ds = downstream_cell(row, col)
                if ds is None:
                    break
                nr, nc = ds
                if not stream_mask[nr, nc]:
                    break
                if visited[nr, nc]:
                    # Add final point for connection
                    coords.append(cell_xy(nr, nc))
                    dist = (
                        (coords[-1][0] - coords[-2][0]) ** 2
                        + (coords[-1][1] - coords[-2][1]) ** 2
                    ) ** 0.5
                    length_m += dist
                    break

                next_order = max(int(strahler[nr, nc]), 1)
                if next_order != seg_order:
                    # Order changes: end segment, add junction pt
                    coords.append(cell_xy(nr, nc))
                    dist = (
                        (coords[-1][0] - coords[-2][0]) ** 2
                        + (coords[-1][1] - coords[-2][1]) ** 2
                    ) ** 0.5
                    length_m += dist
                    break

                visited[nr, nc] = True
                seg_rc_path.append((nr, nc))
                new_pt = cell_xy(nr, nc)
                dist = (
                    (new_pt[0] - coords[-1][0]) ** 2
                    + (new_pt[1] - coords[-1][1]) ** 2
                ) ** 0.5
                length_m += dist
                coords.append(new_pt)
                slopes.append(float(slope[nr, nc]))
                row, col = nr, nc

            # Only create segment if >= 2 points
            if len(coords) >= 2:
                upstream_area_km2 = (
                    float(acc[row, col]) * cell_area / 1_000_000
                )
                segments.append(
                    {
                        "coords": coords,
                        "strahler_order": seg_order,
                        "length_m": round(length_m, 1),
                        "upstream_area_km2": round(
                            upstream_area_km2, 4
                        ),
                        "mean_slope_percent": round(
                            float(np.mean(slopes)), 2
                        ),
                    }
                )

                # Paint label raster with 1-based segment index
                if label_raster_out is not None:
                    seg_id = len(segments)  # 1-based
                    for r, c in seg_rc_path:
                        label_raster_out[r, c] = seg_id

            # Continue from junction point if order changed
            ds = downstream_cell(row, col)
            if ds is None or not stream_mask[ds[0], ds[1]]:
                break
            if visited[ds[0], ds[1]]:
                break
            row, col = ds

    logger.info(
        f"Vectorized {len(segments)} stream segments "
        f"(total length: "
        f"{sum(s['length_m'] for s in segments) / 1000:.1f} km)"
    )

    return segments


def insert_stream_segments(
    db_session,
    segments: list[dict],
    threshold_m2: int = 100,
) -> int:
    """
    Insert vectorized stream segments into stream_network table.

    Uses COPY for bulk loading via temporary table.

    Parameters
    ----------
    db_session : Session
        SQLAlchemy database session
    segments : list[dict]
        List of segment dicts from vectorize_streams()
    threshold_m2 : int
        Flow accumulation threshold in m² used to generate these segments

    Returns
    -------
    int
        Number of segments inserted
    """
    import io

    if not segments:
        logger.info("No stream segments to insert")
        return 0

    logger.info(
        f"Inserting {len(segments)} stream segments "
        f"(threshold={threshold_m2} m²) into stream_network..."
    )

    raw_conn = db_session.connection().connection
    cursor = raw_conn.cursor()

    # Create temp table
    cursor.execute("""
        CREATE TEMP TABLE temp_stream_import (
            wkt TEXT,
            strahler_order INT,
            length_m FLOAT,
            upstream_area_km2 FLOAT,
            mean_slope_percent FLOAT,
            source TEXT,
            threshold_m2 INT
        )
    """)

    # Build TSV
    tsv_buffer = io.StringIO()
    for seg in segments:
        coords_wkt = ", ".join(
            f"{x} {y}" for x, y in seg["coords"]
        )
        wkt = f"LINESTRING({coords_wkt})"
        tsv_buffer.write(
            f"{wkt}\t{seg['strahler_order']}\t"
            f"{seg['length_m']}\t{seg['upstream_area_km2']}\t"
            f"{seg['mean_slope_percent']}\tDEM_DERIVED\t"
            f"{threshold_m2}\n"
        )

    tsv_buffer.seek(0)

    cursor.copy_expert(
        "COPY temp_stream_import FROM STDIN"
        " WITH (FORMAT text, DELIMITER E'\\t', NULL '')",
        tsv_buffer,
    )

    # Insert with geometry construction (skip geohash duplicates)
    cursor.execute("""
        INSERT INTO stream_network (
            geom, strahler_order, length_m,
            upstream_area_km2, mean_slope_percent, source,
            threshold_m2
        )
        SELECT
            ST_SetSRID(ST_GeomFromText(wkt), 2180),
            strahler_order, length_m,
            upstream_area_km2, mean_slope_percent, source,
            threshold_m2
        FROM temp_stream_import
        ON CONFLICT DO NOTHING
    """)

    total = cursor.rowcount
    raw_conn.commit()
    logger.info(f"  Inserted {total} stream segments")

    return total


def delineate_subcatchments(
    fdir: np.ndarray,
    label_raster: np.ndarray,
    dem: np.ndarray,
    nodata: float,
) -> np.ndarray:
    """
    Assign every non-stream cell to the stream segment it drains to.

    Traces downstream via D8 flow direction until hitting a cell that
    already has a label (stream cell). Memoized: once a cell is labeled,
    future traces through it terminate immediately.

    Parameters
    ----------
    fdir : np.ndarray
        D8 flow direction array (int16)
    label_raster : np.ndarray
        int32 array, pre-painted with stream segment labels (1-based).
        Modified in-place: non-stream cells get the label of the
        downstream segment they drain to.
    dem : np.ndarray
        DEM array (for nodata detection)
    nodata : float
        NoData value

    Returns
    -------
    np.ndarray
        The label_raster (modified in-place)
    """
    logger.info("Delineating sub-catchments...")

    nrows, ncols = fdir.shape
    labeled_count = 0
    unlabeled_count = 0

    for i in range(nrows):
        for j in range(ncols):
            if dem[i, j] == nodata:
                continue
            if label_raster[i, j] != 0:
                continue

            # Trace downstream, collecting path
            path = []
            r, c = i, j
            found_label = 0

            while True:
                if label_raster[r, c] != 0:
                    found_label = label_raster[r, c]
                    break

                path.append((r, c))
                d = fdir[r, c]
                if d not in D8_DIRECTIONS:
                    break

                dr, dc = D8_DIRECTIONS[d]
                nr, nc = r + dr, c + dc
                if not (0 <= nr < nrows and 0 <= nc < ncols):
                    break
                if dem[nr, nc] == nodata:
                    break

                r, c = nr, nc

            # Assign label to entire path
            if found_label != 0:
                for pr, pc in path:
                    label_raster[pr, pc] = found_label
                labeled_count += len(path)
            else:
                unlabeled_count += len(path)

    total_valid = int(np.sum(dem != nodata))
    total_labeled = int(np.sum(label_raster != 0))
    logger.info(
        f"  Sub-catchments: {total_labeled:,}/{total_valid:,} cells labeled "
        f"({unlabeled_count:,} drain outside area)"
    )

    return label_raster


def polygonize_subcatchments(
    label_raster: np.ndarray,
    dem: np.ndarray,
    slope: np.ndarray,
    metadata: dict,
    segments: list[dict],
) -> list[dict]:
    """
    Convert label raster to sub-catchment polygons.

    Groups rasterio shapes by segment index, computes union geometry
    and zonal statistics (area, mean elevation, mean slope).

    Parameters
    ----------
    label_raster : np.ndarray
        int32 array with segment labels (1-based, 0=unassigned)
    dem : np.ndarray
        DEM array
    slope : np.ndarray
        Slope array (percent)
    metadata : dict
        Grid metadata (cellsize, nodata_value, transform)
    segments : list[dict]
        Stream segments from vectorize_streams()

    Returns
    -------
    list[dict]
        List of catchment dicts with keys: wkt, segment_idx,
        area_km2, mean_elevation_m, mean_slope_percent, strahler_order
    """
    from collections import defaultdict

    from rasterio.features import shapes
    from shapely.geometry import MultiPolygon, shape
    from shapely.ops import unary_union

    logger.info("Polygonizing sub-catchments...")

    nodata = metadata["nodata_value"]
    cellsize = metadata["cellsize"]
    cell_area_km2 = (cellsize * cellsize) / 1_000_000

    # Build transform
    transform = metadata.get("transform")
    if transform is None:
        from rasterio.transform import from_bounds

        nrows, ncols = label_raster.shape
        xll, yll = metadata["xllcorner"], metadata["yllcorner"]
        transform = from_bounds(
            xll, yll,
            xll + ncols * cellsize,
            yll + nrows * cellsize,
            ncols, nrows,
        )

    # Mask: only labeled cells
    mask = label_raster > 0

    # Polygonize
    geom_groups = defaultdict(list)
    for geom_dict, value in shapes(label_raster, mask=mask, transform=transform):
        seg_idx = int(value)
        if seg_idx > 0:
            geom_groups[seg_idx].append(shape(geom_dict))

    logger.info(f"  Found {len(geom_groups)} unique sub-catchment labels")

    # Build catchment records
    catchments = []
    simplify_tol = cellsize / 2

    for seg_idx in sorted(geom_groups.keys()):
        geom_list = geom_groups[seg_idx]
        merged = unary_union(geom_list)

        # Ensure MULTIPOLYGON
        if merged.geom_type == "Polygon":
            merged = MultiPolygon([merged])

        # Simplify to reduce staircase vertices
        merged = merged.simplify(simplify_tol, preserve_topology=True)
        if merged.geom_type == "Polygon":
            merged = MultiPolygon([merged])

        # Zonal statistics from raster mask
        cell_mask = label_raster == seg_idx
        n_cells = int(np.sum(cell_mask))
        area_km2 = n_cells * cell_area_km2

        # Mean elevation (exclude nodata)
        elev_mask = cell_mask & (dem != nodata)
        mean_elev = float(np.mean(dem[elev_mask])) if np.any(elev_mask) else None

        # Mean slope
        mean_slp = float(np.mean(slope[cell_mask])) if n_cells > 0 else None

        # Strahler order from segment
        strahler_order = None
        if 1 <= seg_idx <= len(segments):
            strahler_order = segments[seg_idx - 1].get("strahler_order")

        catchments.append({
            "wkt": merged.wkt,
            "segment_idx": seg_idx,
            "area_km2": round(area_km2, 6),
            "mean_elevation_m": round(mean_elev, 2) if mean_elev is not None else None,
            "mean_slope_percent": round(mean_slp, 2) if mean_slp is not None else None,
            "strahler_order": strahler_order,
        })

    logger.info(
        f"  Polygonized {len(catchments)} sub-catchments "
        f"(total area: {sum(c['area_km2'] for c in catchments):.2f} km²)"
    )

    return catchments


def insert_catchments(
    db_session,
    catchments: list[dict],
    threshold_m2: int,
) -> int:
    """
    Insert sub-catchment polygons into stream_catchments table.

    Uses COPY pattern (temp table + bulk insert) for performance.

    Parameters
    ----------
    db_session : Session
        SQLAlchemy database session
    catchments : list[dict]
        List of catchment dicts from polygonize_subcatchments()
    threshold_m2 : int
        Flow accumulation threshold in m²

    Returns
    -------
    int
        Number of catchments inserted
    """
    import io

    if not catchments:
        logger.info("No sub-catchments to insert")
        return 0

    logger.info(
        f"Inserting {len(catchments)} sub-catchments "
        f"(threshold={threshold_m2} m²) into stream_catchments..."
    )

    raw_conn = db_session.connection().connection
    cursor = raw_conn.cursor()

    # Create temp table
    cursor.execute("""
        CREATE TEMP TABLE temp_catchments_import (
            wkt TEXT,
            segment_idx INT,
            threshold_m2 INT,
            area_km2 FLOAT,
            mean_elevation_m FLOAT,
            mean_slope_percent FLOAT,
            strahler_order INT
        )
    """)

    # Build TSV
    tsv_buffer = io.StringIO()
    for cat in catchments:
        elev = cat["mean_elevation_m"]
        slp = cat["mean_slope_percent"]
        mean_elev = "" if elev is None else str(elev)
        mean_slp = "" if slp is None else str(slp)
        strahler = "" if cat["strahler_order"] is None else str(cat["strahler_order"])
        tsv_buffer.write(
            f"{cat['wkt']}\t{cat['segment_idx']}\t"
            f"{threshold_m2}\t{cat['area_km2']}\t"
            f"{mean_elev}\t{mean_slp}\t{strahler}\n"
        )

    tsv_buffer.seek(0)

    cursor.copy_expert(
        "COPY temp_catchments_import FROM STDIN"
        " WITH (FORMAT text, DELIMITER E'\\t', NULL '')",
        tsv_buffer,
    )

    # Insert with geometry construction
    cursor.execute("""
        INSERT INTO stream_catchments (
            geom, segment_idx, threshold_m2,
            area_km2, mean_elevation_m, mean_slope_percent,
            strahler_order
        )
        SELECT
            ST_SetSRID(ST_GeomFromText(wkt), 2180),
            segment_idx, threshold_m2,
            area_km2, mean_elevation_m, mean_slope_percent,
            strahler_order
        FROM temp_catchments_import
    """)

    total = cursor.rowcount
    raw_conn.commit()
    logger.info(f"  Inserted {total} sub-catchments")

    return total


def create_flow_network_records(
    dem: np.ndarray,
    fdir: np.ndarray,
    acc: np.ndarray,
    slope: np.ndarray,
    metadata: dict,
    stream_threshold: int = 100,
    strahler: np.ndarray | None = None,
) -> list:
    """
    Create flow_network records from raster data.

    Cell IDs are computed as: row * ncols + col + 1 (1-based).
    This ensures unique IDs across the entire raster, including VRT mosaics.

    Note: For very large areas (>40,000 x 40,000 cells), IDs may exceed
    PostgreSQL INTEGER range (2^31). Consider using BIGINT for such cases.

    Parameters
    ----------
    dem : np.ndarray
        DEM array
    fdir : np.ndarray
        Flow direction array
    acc : np.ndarray
        Flow accumulation array
    slope : np.ndarray
        Slope array (percent)
    metadata : dict
        Grid metadata (xllcorner, yllcorner, cellsize, nodata_value)
    stream_threshold : int
        Flow accumulation threshold for stream identification
    strahler : np.ndarray, optional
        Strahler stream order array (0 = non-stream)

    Returns
    -------
    list
        List of dicts with flow_network fields
    """
    logger.info("Creating flow_network records...")

    nrows, ncols = dem.shape
    cellsize = metadata["cellsize"]
    xll = metadata["xllcorner"]
    yll = metadata["yllcorner"]
    nodata = metadata["nodata_value"]
    cell_area = cellsize * cellsize

    # Check for potential ID overflow (INT max = 2^31 - 1 = 2,147,483,647)
    max_id = nrows * ncols
    if max_id > 2_000_000_000:
        logger.warning(
            f"Large raster ({nrows}x{ncols} = {max_id:,} cells) may cause "
            f"ID overflow. Consider using BIGINT for flow_network.id"
        )

    records = []

    # Create index map for downstream_id lookup
    # Index = row * ncols + col + 1 (1-based for DB)
    # This ensures unique IDs across the entire VRT mosaic
    def get_cell_index(row, col):
        return row * ncols + col + 1

    for i in range(nrows):
        for j in range(ncols):
            if dem[i, j] == nodata:
                continue

            # Cell center coordinates (PL-1992)
            # Note: ASCII GRID has origin at lower-left, row 0 is top
            x = xll + (j + 0.5) * cellsize
            y = yll + (nrows - i - 0.5) * cellsize

            cell_id = get_cell_index(i, j)

            # Find downstream cell
            downstream_id = None
            d = fdir[i, j]
            if d in D8_DIRECTIONS:
                di, dj = D8_DIRECTIONS[d]
                ni, nj = i + di, j + dj
                if (
                    0 <= ni < nrows
                    and 0 <= nj < ncols
                    and dem[ni, nj] != nodata
                ):
                    downstream_id = get_cell_index(ni, nj)

            # Strahler order (None for non-stream cells)
            strahler_val = None
            if strahler is not None and strahler[i, j] > 0:
                strahler_val = int(strahler[i, j])

            records.append(
                {
                    "id": cell_id,
                    "x": x,
                    "y": y,
                    "elevation": float(dem[i, j]),
                    "flow_accumulation": int(acc[i, j]),
                    "slope": float(slope[i, j]),
                    "downstream_id": downstream_id,
                    "cell_area": cell_area,
                    "is_stream": bool(acc[i, j] >= stream_threshold),
                    "strahler_order": strahler_val,
                }
            )

    logger.info(f"Created {len(records)} records")
    stream_count = sum(1 for r in records if r["is_stream"])
    logger.info(f"Stream cells (acc >= {stream_threshold}): {stream_count}")

    return records


def insert_records_batch(
    db_session,
    records: list,
    batch_size: int = 10000,
    table_empty: bool = True,
) -> int:
    """
    Insert records into flow_network table using PostgreSQL COPY.

    Uses COPY FROM for bulk loading (20x faster than individual INSERTs).
    Temporarily disables indexes for faster insert, then rebuilds them.

    Parameters
    ----------
    db_session : Session
        SQLAlchemy database session
    records : list
        List of record dicts
    batch_size : int
        Number of records per batch (unused, kept for API compatibility)
    table_empty : bool
        If True, skip ON CONFLICT check (much faster for empty tables)
        If False, use ON CONFLICT DO UPDATE for upsert behavior

    Returns
    -------
    int
        Total records inserted
    """
    import io

    logger.info(f"Inserting {len(records):,} records using COPY (optimized)...")

    # Get raw connection for COPY operation
    raw_conn = db_session.connection().connection
    cursor = raw_conn.cursor()

    # Phase 1: Disable indexes and FK for faster bulk insert
    logger.info("Phase 1: Preparing for bulk insert...")

    cursor.execute("DROP INDEX IF EXISTS idx_flow_geom")
    cursor.execute("DROP INDEX IF EXISTS idx_downstream")
    cursor.execute("DROP INDEX IF EXISTS idx_is_stream")
    cursor.execute("DROP INDEX IF EXISTS idx_flow_accumulation")
    cursor.execute("DROP INDEX IF EXISTS idx_strahler")
    cursor.execute(
        "ALTER TABLE flow_network"
        " DROP CONSTRAINT IF EXISTS"
        " flow_network_downstream_id_fkey"
    )
    raw_conn.commit()
    logger.info("  Indexes and FK constraint dropped")

    # Phase 2: Bulk insert using COPY
    logger.info("Phase 2: Bulk inserting records with COPY...")

    # Create temporary table for COPY
    cursor.execute("""
        CREATE TEMP TABLE temp_flow_import (
            id INT,
            x FLOAT,
            y FLOAT,
            elevation FLOAT,
            flow_accumulation INT,
            slope FLOAT,
            downstream_id INT,
            cell_area FLOAT,
            is_stream BOOLEAN,
            strahler_order SMALLINT
        )
    """)

    # Create TSV buffer
    tsv_buffer = io.StringIO()
    for r in records:
        downstream = (
            "" if r["downstream_id"] is None
            else str(r["downstream_id"])
        )
        is_stream = "t" if r["is_stream"] else "f"
        strahler = (
            "" if r.get("strahler_order") is None
            else str(r["strahler_order"])
        )
        tsv_buffer.write(
            f"{r['id']}\t{r['x']}\t{r['y']}\t"
            f"{r['elevation']}\t{r['flow_accumulation']}\t"
            f"{r['slope']}\t{downstream}\t{r['cell_area']}\t"
            f"{is_stream}\t{strahler}\n"
        )

    tsv_buffer.seek(0)

    # COPY to temp table
    cursor.copy_expert(
        "COPY temp_flow_import FROM STDIN"
        " WITH (FORMAT text, DELIMITER E'\\t', NULL '')",
        tsv_buffer,
    )
    logger.info(f"  COPY to temp table: {len(records):,} records")

    # Insert from temp table with geometry construction
    # When table is empty, skip ON CONFLICT for faster insert
    if table_empty:
        cursor.execute("""
            INSERT INTO flow_network (
                id, geom, elevation, flow_accumulation, slope,
                downstream_id, cell_area, is_stream,
                strahler_order
            )
            SELECT
                id, ST_SetSRID(ST_Point(x, y), 2180),
                elevation, flow_accumulation, slope,
                downstream_id, cell_area, is_stream,
                strahler_order
            FROM temp_flow_import
        """)
    else:
        cursor.execute("""
            INSERT INTO flow_network (
                id, geom, elevation, flow_accumulation, slope,
                downstream_id, cell_area, is_stream,
                strahler_order
            )
            SELECT
                id, ST_SetSRID(ST_Point(x, y), 2180),
                elevation, flow_accumulation, slope,
                downstream_id, cell_area, is_stream,
                strahler_order
            FROM temp_flow_import
            ON CONFLICT (id) DO UPDATE SET
                geom = EXCLUDED.geom,
                elevation = EXCLUDED.elevation,
                flow_accumulation = EXCLUDED.flow_accumulation,
                slope = EXCLUDED.slope,
                downstream_id = EXCLUDED.downstream_id,
                cell_area = EXCLUDED.cell_area,
                is_stream = EXCLUDED.is_stream,
                strahler_order = EXCLUDED.strahler_order
        """)

    total_inserted = cursor.rowcount
    raw_conn.commit()
    logger.info(f"  Inserted {total_inserted:,} records into flow_network")

    # Phase 3: Restore FK constraint and indexes
    logger.info("Phase 3: Restoring indexes and constraints...")

    cursor.execute("""
        ALTER TABLE flow_network
        ADD CONSTRAINT flow_network_downstream_id_fkey
        FOREIGN KEY (downstream_id) REFERENCES flow_network(id) ON DELETE SET NULL
    """)
    logger.info("  FK constraint restored")

    cursor.execute("CREATE INDEX idx_flow_geom ON flow_network USING GIST (geom)")
    logger.info("  Index idx_flow_geom created")

    cursor.execute("CREATE INDEX idx_downstream ON flow_network (downstream_id)")
    logger.info("  Index idx_downstream created")

    cursor.execute(
        "CREATE INDEX idx_is_stream ON flow_network (is_stream) WHERE is_stream = TRUE"
    )
    logger.info("  Index idx_is_stream created")

    cursor.execute(
        "CREATE INDEX idx_flow_accumulation"
        " ON flow_network (flow_accumulation)"
    )
    logger.info("  Index idx_flow_accumulation created")

    cursor.execute(
        "CREATE INDEX idx_strahler"
        " ON flow_network (strahler_order)"
        " WHERE strahler_order IS NOT NULL"
    )
    logger.info("  Index idx_strahler created")

    cursor.execute("ANALYZE flow_network")
    raw_conn.commit()
    logger.info("  ANALYZE completed")

    return total_inserted


def process_dem(
    input_path: Path,
    stream_threshold: int = 100,
    batch_size: int = 10000,
    dry_run: bool = False,
    save_intermediates: bool = False,
    output_dir: Path | None = None,
    clear_existing: bool = False,
    burn_streams_path: Path | None = None,
    burn_depth_m: float = 5.0,
    skip_streams_vectorize: bool = False,
    thresholds: list[int] | None = None,
    skip_catchments: bool = False,
) -> dict:
    """
    Process DEM file (ASC, VRT, or GeoTIFF) and load into flow_network table.

    Supports VRT mosaics for multi-tile processing with hydrological continuity
    across tile boundaries.

    Parameters
    ----------
    input_path : Path
        Path to input raster file (.asc, .vrt, or .tif)
    stream_threshold : int
        Flow accumulation threshold for stream identification (used for
        flow_network.is_stream and single-threshold mode)
    batch_size : int
        Database insert batch size (unused with COPY, kept for API compatibility)
    dry_run : bool
        If True, only compute statistics without inserting
    save_intermediates : bool
        If True, save intermediate rasters as GeoTIFF
    output_dir : Path, optional
        Output directory for intermediate files (default: same as input)
    clear_existing : bool
        If True, clear existing data before insert (TRUNCATE).
        Default False to support incremental processing.
    burn_streams_path : Path, optional
        Path to GeoPackage/Shapefile with stream lines for DEM burning
    burn_depth_m : float
        Burn depth in meters (default: 5.0)
    skip_streams_vectorize : bool
        If True, skip stream vectorization (default: False)
    skip_catchments : bool
        If True, skip sub-catchment delineation (default: False)
    thresholds : list[int], optional
        List of FA thresholds in m² for multi-density stream networks.
        If provided, generates separate stream networks per threshold.
        The lowest threshold is used for flow_network.is_stream and strahler_order.

    Returns
    -------
    dict
        Processing statistics including:
        - ncols, nrows, cellsize, total_cells
        - valid_cells, max_accumulation, mean_slope
        - stream_cells, records, inserted
        - burn_cells (if burn_streams_path provided)
    """
    stats = {}

    # Setup output directory for intermediates
    if output_dir is None:
        output_dir = input_path.parent
    output_dir = Path(output_dir)
    base_name = input_path.stem

    # 1. Read DEM (supports ASC, VRT, GeoTIFF)
    suffix = input_path.suffix.lower()
    if suffix in (".vrt", ".tif", ".tiff"):
        dem, metadata = read_raster(input_path)
    else:
        # Fallback to ASCII grid parser for .asc files
        dem, metadata = read_ascii_grid(input_path)

    stats["ncols"] = metadata["ncols"]
    stats["nrows"] = metadata["nrows"]
    stats["cellsize"] = metadata["cellsize"]
    stats["total_cells"] = metadata["ncols"] * metadata["nrows"]

    nodata = metadata["nodata_value"]
    valid_cells = np.sum(dem != nodata)
    stats["valid_cells"] = int(valid_cells)

    # Save original DEM as GeoTIFF
    if save_intermediates:
        save_raster_geotiff(
            dem,
            metadata,
            output_dir / f"{base_name}_01_dem.tif",
            nodata=nodata,
            dtype="float32",
        )

    # 2. Burn streams (optional) — before depression filling
    if burn_streams_path is not None:
        transform = metadata.get("transform")
        if transform is None:
            from rasterio.transform import from_bounds

            xll, yll = metadata["xllcorner"], metadata["yllcorner"]
            nrows, ncols = dem.shape
            cs = metadata["cellsize"]
            transform = from_bounds(
                xll, yll, xll + ncols * cs, yll + nrows * cs, ncols, nrows
            )
        dem, burn_diag = burn_streams_into_dem(
            dem, transform, burn_streams_path, burn_depth_m, nodata
        )
        stats["burn_cells"] = burn_diag["cells_burned"]
        if save_intermediates:
            save_raster_geotiff(
                dem,
                metadata,
                output_dir / f"{base_name}_02a_burned.tif",
                nodata=nodata,
                dtype="float32",
            )

    # 3-5. Process hydrology using pyflwdir (fill depressions, flow dir, accumulation)
    # Note: Migrated from pysheds to pyflwdir (Deltares) — fewer deps, no temp files
    filled_dem, fdir, acc, d8_fdir = process_hydrology_pyflwdir(dem, metadata)
    stats["max_accumulation"] = int(acc.max())

    if save_intermediates:
        save_raster_geotiff(
            filled_dem,
            metadata,
            output_dir / f"{base_name}_02_filled.tif",
            nodata=nodata,
            dtype="float32",
        )
        save_raster_geotiff(
            fdir,
            metadata,
            output_dir / f"{base_name}_03_flowdir.tif",
            nodata=0,
            dtype="int16",
        )
        save_raster_geotiff(
            acc,
            metadata,
            output_dir / f"{base_name}_04_flowacc.tif",
            nodata=0,
            dtype="int32",
        )

    # 5. Compute slope
    slope = compute_slope(filled_dem, metadata["cellsize"], nodata)
    stats["mean_slope"] = float(np.mean(slope[dem != nodata]))

    if save_intermediates:
        save_raster_geotiff(
            slope,
            metadata,
            output_dir / f"{base_name}_05_slope.tif",
            nodata=-1,
            dtype="float32",
        )

    # 5b. Compute aspect
    aspect = compute_aspect(filled_dem, metadata["cellsize"], nodata)

    if save_intermediates:
        save_raster_geotiff(
            aspect,
            metadata,
            output_dir / f"{base_name}_09_aspect.tif",
            nodata=-1,
            dtype="float32",
        )

    # Determine thresholds for multi-density stream networks
    cell_area = metadata["cellsize"] * metadata["cellsize"]
    DEFAULT_THRESHOLDS_M2 = [100, 1000, 10000, 100000]

    if thresholds:
        threshold_list_m2 = sorted(thresholds)
    else:
        threshold_list_m2 = sorted(DEFAULT_THRESHOLDS_M2)

    logger.info(
        f"Cell size: {metadata['cellsize']}m, cell area: {cell_area} m²"
    )
    for t_m2 in threshold_list_m2:
        t_cells = max(1, int(t_m2 / cell_area))
        logger.info(f"  Threshold {t_m2} m² = {t_cells} cells")

    # Use lowest threshold for flow_network (most detailed network)
    lowest_threshold_cells = max(
        1, int(threshold_list_m2[0] / cell_area)
    )

    # 5c. Compute Strahler stream order via pyflwdir (lowest threshold)
    strahler = compute_strahler_from_fdir(
        d8_fdir, acc, metadata, lowest_threshold_cells
    )

    if save_intermediates:
        save_raster_geotiff(
            strahler,
            metadata,
            output_dir / f"{base_name}_07_stream_order.tif",
            nodata=0,
            dtype="uint8",
        )

    # 5d. Compute TWI
    twi = compute_twi(acc, slope, metadata["cellsize"], nodata_acc=0)

    if save_intermediates:
        save_raster_geotiff(
            twi,
            metadata,
            output_dir / f"{base_name}_08_twi.tif",
            nodata=-9999,
            dtype="float32",
        )

    # 6. Create stream mask (lowest threshold)
    stream_mask = (acc >= lowest_threshold_cells).astype(np.uint8)
    if save_intermediates:
        save_raster_geotiff(
            stream_mask,
            metadata,
            output_dir / f"{base_name}_06_streams.tif",
            nodata=255,
            dtype="uint8",
        )

    # 7. Create records (with strahler_order from lowest threshold)
    records = create_flow_network_records(
        filled_dem, fdir, acc, slope, metadata, lowest_threshold_cells,
        strahler=strahler,
    )
    stats["records"] = len(records)
    stats["stream_cells"] = sum(1 for r in records if r["is_stream"])

    # 7b. Vectorize streams per threshold
    all_stream_segments = {}  # threshold_m2 → segments
    all_catchment_data = {}  # threshold_m2 → catchments
    if not skip_streams_vectorize:
        for threshold_m2 in threshold_list_m2:
            threshold_cells = max(1, int(threshold_m2 / cell_area))
            logger.info(
                f"--- Vectorizing streams for threshold "
                f"{threshold_m2} m² ({threshold_cells} cells) ---"
            )

            # Compute Strahler for this threshold
            if threshold_cells == lowest_threshold_cells:
                strahler_t = strahler
            else:
                strahler_t = compute_strahler_from_fdir(
                    d8_fdir, acc, metadata, threshold_cells
                )

            if save_intermediates and threshold_cells != lowest_threshold_cells:
                save_raster_geotiff(
                    strahler_t,
                    metadata,
                    output_dir / f"{base_name}_07_stream_order_{threshold_m2}.tif",
                    nodata=0,
                    dtype="uint8",
                )

            # Allocate label raster for sub-catchment delineation
            label_raster = None
            if not skip_catchments:
                label_raster = np.zeros_like(filled_dem, dtype=np.int32)

            segments = vectorize_streams(
                filled_dem, fdir, acc, slope, strahler_t,
                metadata, threshold_cells,
                label_raster_out=label_raster,
            )
            all_stream_segments[threshold_m2] = segments

            # Delineate and polygonize sub-catchments
            if not skip_catchments and label_raster is not None:
                delineate_subcatchments(fdir, label_raster, filled_dem, nodata)

                if save_intermediates:
                    save_raster_geotiff(
                        label_raster, metadata,
                        output_dir / f"{base_name}_10_subcatchments_{threshold_m2}.tif",
                        nodata=0, dtype="int32",
                    )

                catchments = polygonize_subcatchments(
                    label_raster, filled_dem, slope, metadata, segments,
                )
                all_catchment_data[threshold_m2] = catchments

            logger.info(
                f"  Threshold {threshold_m2} m²: "
                f"{len(segments)} segments"
            )

        total_segments = sum(
            len(s) for s in all_stream_segments.values()
        )
        stats["stream_segments"] = total_segments
        stats["stream_thresholds"] = {
            t: len(s) for t, s in all_stream_segments.items()
        }
        if all_catchment_data:
            stats["catchment_thresholds"] = {
                t: len(c) for t, c in all_catchment_data.items()
            }

    # 8. Insert into database
    if not dry_run:
        from core.database import get_db_session

        with get_db_session() as db:
            # Bulk import can take minutes — override statement_timeout
            db.execute(text("SET LOCAL statement_timeout = '600s'"))

            if clear_existing:
                logger.info("Clearing existing flow_network data...")
                db.execute(text("TRUNCATE TABLE flow_network CASCADE"))
                db.execute(
                    text(
                        "DELETE FROM stream_network"
                        " WHERE source = 'DEM_DERIVED'"
                    )
                )
                db.execute(text("DELETE FROM stream_catchments"))
                db.commit()

            # table_empty=True when we just truncated
            inserted = insert_records_batch(
                db, records, batch_size, table_empty=clear_existing
            )
            stats["inserted"] = inserted

            # Insert stream segments per threshold
            total_seg_inserted = 0
            for threshold_m2, segments in all_stream_segments.items():
                if segments:
                    seg_inserted = insert_stream_segments(
                        db, segments, threshold_m2=threshold_m2,
                    )
                    total_seg_inserted += seg_inserted
            if total_seg_inserted > 0:
                stats["stream_segments_inserted"] = total_seg_inserted

            # Insert sub-catchments per threshold
            total_catch_inserted = 0
            for threshold_m2, catchments in all_catchment_data.items():
                if catchments:
                    catch_inserted = insert_catchments(
                        db, catchments, threshold_m2=threshold_m2,
                    )
                    total_catch_inserted += catch_inserted
            if total_catch_inserted > 0:
                stats["catchments_inserted"] = total_catch_inserted
    else:
        logger.info("Dry run - skipping database insert")
        stats["inserted"] = 0

    return stats


def main():
    """Main entry point for DEM processing script."""
    parser = argparse.ArgumentParser(
        description="Process DEM and populate flow_network table",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        required=True,
        help="Path to input ASCII GRID (.asc) file",
    )
    parser.add_argument(
        "--stream-threshold",
        type=int,
        default=100,
        help=(
            "Flow accumulation threshold in cells (default: 100). "
            "Ignored when --thresholds is specified."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10000,
        help="Database insert batch size (default: 10000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only compute statistics without database insert",
    )
    parser.add_argument(
        "--save-intermediates",
        "-s",
        action="store_true",
        help="Save intermediate rasters as GeoTIFF (for QGIS verification)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Output directory for intermediate files (default: same as input)",
    )
    parser.add_argument(
        "--clear-existing",
        action="store_true",
        help="Clear existing flow_network data before insert (TRUNCATE)",
    )
    parser.add_argument(
        "--burn-streams",
        type=str,
        default=None,
        help="Path to GeoPackage/Shapefile with stream lines for DEM burning",
    )
    parser.add_argument(
        "--burn-depth",
        type=float,
        default=5.0,
        help="Burn depth in meters (default: 5.0)",
    )
    parser.add_argument(
        "--skip-streams-vectorize",
        action="store_true",
        help="Skip stream vectorization (useful without DB)",
    )
    parser.add_argument(
        "--skip-catchments",
        action="store_true",
        help="Skip sub-catchment delineation (default: generate catchments)",
    )
    parser.add_argument(
        "--thresholds",
        type=str,
        default=None,
        help=(
            "Comma-separated FA thresholds in m² for multi-density "
            "stream networks (e.g. 100,1000,10000,100000). "
            "Overrides --stream-threshold for vectorization."
        ),
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir) if args.output_dir else None
    burn_streams_path = Path(args.burn_streams) if args.burn_streams else None

    # Parse thresholds
    threshold_list = None
    if args.thresholds:
        threshold_list = [int(t.strip()) for t in args.thresholds.split(",")]

    logger.info("=" * 60)
    logger.info("DEM Processing Script")
    logger.info("=" * 60)
    logger.info(f"Input: {input_path}")
    logger.info(f"Stream threshold: {args.stream_threshold}")
    if threshold_list:
        logger.info(f"Multi-threshold FA: {threshold_list} m²")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Save intermediates: {args.save_intermediates}")
    logger.info(f"Clear existing: {args.clear_existing}")
    if burn_streams_path:
        logger.info(f"Burn streams: {burn_streams_path} (depth={args.burn_depth}m)")
    if output_dir:
        logger.info(f"Output dir: {output_dir}")
    logger.info("=" * 60)

    start_time = time.time()

    try:
        stats = process_dem(
            input_path,
            stream_threshold=args.stream_threshold,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            save_intermediates=args.save_intermediates,
            output_dir=output_dir,
            clear_existing=args.clear_existing,
            burn_streams_path=burn_streams_path,
            burn_depth_m=args.burn_depth,
            skip_streams_vectorize=args.skip_streams_vectorize,
            thresholds=threshold_list,
            skip_catchments=args.skip_catchments,
        )
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        raise

    elapsed = time.time() - start_time

    logger.info("=" * 60)
    logger.info("Processing complete!")
    logger.info(f"  Grid size: {stats['ncols']} x {stats['nrows']}")
    logger.info(f"  Cell size: {stats['cellsize']} m")
    logger.info(f"  Total cells: {stats['total_cells']:,}")
    logger.info(f"  Valid cells: {stats['valid_cells']:,}")
    logger.info(f"  Max accumulation: {stats['max_accumulation']:,}")
    logger.info(f"  Mean slope: {stats['mean_slope']:.1f}%")
    if "burn_cells" in stats:
        logger.info(f"  Burned cells: {stats['burn_cells']:,}")
    logger.info(f"  Stream cells: {stats['stream_cells']:,}")
    if "stream_segments" in stats:
        logger.info(
            f"  Stream segments: {stats['stream_segments']:,}"
        )
    if "stream_thresholds" in stats:
        for t, count in stats["stream_thresholds"].items():
            logger.info(f"    Threshold {t} m²: {count} segments")
    logger.info(f"  Records created: {stats['records']:,}")
    logger.info(f"  Records inserted: {stats['inserted']:,}")
    if "stream_segments_inserted" in stats:
        logger.info(
            f"  Stream segments inserted: "
            f"{stats['stream_segments_inserted']:,}"
        )
    if "catchment_thresholds" in stats:
        for t, count in stats["catchment_thresholds"].items():
            logger.info(f"    Sub-catchments {t} m²: {count}")
    if "catchments_inserted" in stats:
        logger.info(
            f"  Sub-catchments inserted: "
            f"{stats['catchments_inserted']:,}"
        )
    logger.info(f"  Time elapsed: {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
