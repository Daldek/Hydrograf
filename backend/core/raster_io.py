"""
Raster I/O utilities for reading and writing DEM files.

Supports ASCII GRID (.asc), VRT mosaics (.vrt), and GeoTIFF (.tif) formats.
All outputs use PL-1992 (EPSG:2180) CRS. ``read_raster`` reads a whole raster
(the preprocessing); ``read_raster_window`` reads only a window around a query
(the API).
"""

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.windows import Window, from_bounds

logger = logging.getLogger(__name__)


def save_raster_geotiff(
    data: np.ndarray,
    metadata: dict[str, Any],
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


def read_raster(filepath: Path) -> tuple[np.ndarray, dict[str, Any]]:
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


@dataclass(frozen=True, eq=False)
class RasterWindow:
    """Cells of the first band of a raster in a window, with their grid.

    Attributes
    ----------
    data : np.ndarray
        Values of the window in the dtype of the raster; the cells beyond the
        raster hold ``nodata`` (0 for a raster without one)
    transform : Affine
        Transform of ``data``: ``transform * (col, row)`` is the upper left
        corner of the cell ``data[row, col]``
    nodata : float | None
        Nodata value of the raster
    """

    data: np.ndarray
    transform: Affine
    nodata: float | None


def read_raster_window(
    filepath: str | Path,
    bounds: tuple[float, float, float, float],
    margin_m: float = 0.0,
) -> RasterWindow:
    """Read the first band of a raster in a window around a bounding box.

    The window holds the whole cells covering ``bounds`` widened by
    ``margin_m``, plus one cell on every side, so a point on the edge of
    ``bounds`` lies inside it whatever the rounding. Only the part of the
    raster in the window is read (of a VRT mosaic, only the tiles it touches).
    The window may reach beyond the raster: those cells are filled with the
    nodata value. The whole window is allocated, so the caller keeps it small.

    Parameters
    ----------
    filepath : str | Path
        Raster file (GeoTIFF or VRT)
    bounds : tuple[float, float, float, float]
        (minx, miny, maxx, maxy) in the CRS of the raster
    margin_m : float
        Margin around ``bounds`` in the units of the CRS (metres in EPSG:2180)

    Returns
    -------
    RasterWindow
        The values of the window, its transform and the nodata of the raster
    """
    minx, miny, maxx, maxy = bounds
    with rasterio.open(filepath) as src:
        span = from_bounds(
            minx - margin_m,
            miny - margin_m,
            maxx + margin_m,
            maxy + margin_m,
            transform=src.transform,
        )
        row0 = math.floor(span.row_off) - 1
        col0 = math.floor(span.col_off) - 1
        row1 = math.ceil(span.row_off + span.height) + 1
        col1 = math.ceil(span.col_off + span.width) + 1
        fill = src.nodata if src.nodata is not None else 0
        data = np.full((row1 - row0, col1 - col0), fill, dtype=src.dtypes[0])
        # The rows and columns of the window on the raster, read in place
        top, bottom = max(row0, 0), min(row1, src.height)
        left, right = max(col0, 0), min(col1, src.width)
        if top < bottom and left < right:
            part = data[top - row0 : bottom - row0, left - col0 : right - col0]
            src.read(1, window=Window(left, top, right - left, bottom - top), out=part)
        transform = src.window_transform(Window(col0, row0, col1 - col0, row1 - row0))
        nodata = src.nodata
    return RasterWindow(data=data, transform=transform, nodata=nodata)


def downsample_raster(input_path: Path, output_path: Path, target_res_m: float) -> Path:
    """
    Downsample raster to target resolution using GDAL (bilinear).

    Used to reduce memory for pyflwdir on large rasters.
    Returns output_path.
    """
    import subprocess

    logger.info(f"Downsampling {input_path.name}: target {target_res_m}m resolution")

    cmd = [
        "gdalwarp",
        "-tr",
        str(target_res_m),
        str(target_res_m),
        "-r",
        "bilinear",
        "-of",
        "GTiff",
        "-co",
        "COMPRESS=DEFLATE",
        "-overwrite",
        str(input_path),
        str(output_path),
    ]

    subprocess.run(cmd, capture_output=True, text=True, check=True)

    logger.info(f"Downsampled to: {output_path}")
    return output_path


def read_ascii_grid(filepath: Path) -> tuple[np.ndarray, dict[str, Any]]:
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

    metadata: dict[str, float] = {}
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
