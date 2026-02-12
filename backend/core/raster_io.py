"""
Raster I/O utilities for reading and writing DEM files.

Supports ASCII GRID (.asc), VRT mosaics (.vrt), and GeoTIFF (.tif) formats.
All outputs use PL-1992 (EPSG:2180) CRS.
"""

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


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
        (data array, metadata dict with ncols, nrows, xllcorner,
        yllcorner, cellsize, nodata)

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
        (data array, metadata dict with ncols, nrows, xllcorner,
        yllcorner, cellsize, nodata)

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
