"""
Raster I/O utilities for reading and writing DEM files.

Supports ASCII GRID (.asc), VRT mosaics (.vrt), and GeoTIFF (.tif) formats.
All outputs use PL-1992 (EPSG:2180) CRS.
"""

import logging
from pathlib import Path
from types import TracebackType
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class GeoTiffWriter:
    """A GeoTIFF in PL-1992 (EPSG:2180), LZW, written whole or strip by strip.

    Uses the original transform from the input raster if ``metadata`` has it, for a
    perfect alignment with the source DEM; else one from its corner and cell size.

    Parameters
    ----------
    output_path : Path
        Output GeoTIFF path.
    metadata : dict
        Grid metadata with transform (preferred) or xllcorner, yllcorner, cellsize.
    shape : tuple[int, ...]
        Rows and columns of the raster.
    nodata : float
        NoData value.
    dtype : str
        Data type of the file ('float32', 'float64', 'int32', 'int16', 'uint8';
        another name gives float32).
    """

    def __init__(
        self,
        output_path: Path,
        metadata: dict[str, Any],
        shape: tuple[int, ...],
        nodata: float = -9999.0,
        dtype: str = "float32",
    ) -> None:
        import rasterio
        from rasterio.transform import from_bounds

        nrows, ncols = shape
        if "transform" in metadata:
            transform = metadata["transform"]
        else:
            # From the corner and the cell size (may be inexact)
            cellsize = metadata["cellsize"]
            xll = metadata["xllcorner"]
            yll = metadata["yllcorner"]
            transform = from_bounds(
                xll, yll, xll + ncols * cellsize, yll + nrows * cellsize, ncols, nrows
            )
        dtype_map = {
            "float32": (np.float32, rasterio.float32),
            "float64": (np.float64, rasterio.float64),
            "int32": (np.int32, rasterio.int32),
            "int16": (np.int16, rasterio.int16),
            "uint8": (np.uint8, rasterio.uint8),
        }
        self._np_dtype, rio_dtype = dtype_map.get(dtype, (np.float32, rasterio.float32))
        self._ncols = ncols
        self.path = output_path
        self._dataset = rasterio.open(
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
        )

    def write_rows(self, row_start: int, data: np.ndarray) -> None:
        """Write ``data`` (2-D) into the rows from ``row_start`` on.

        The data is cast to the type of the file, without a copy when it has it.
        """
        from rasterio.windows import Window

        self._dataset.write(
            data.astype(self._np_dtype, copy=False),
            1,
            window=Window(0, row_start, self._ncols, data.shape[0]),
        )

    def __enter__(self) -> "GeoTiffWriter":
        """Return the writer."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the file, and log it when the writing did not fail."""
        self._dataset.close()
        if exc_type is None:
            size_kb = self.path.stat().st_size / 1024
            logger.info("Saved: %s (%.1f KB)", self.path, size_kb)


def save_raster_geotiff(
    data: np.ndarray,
    metadata: dict[str, Any],
    output_path: Path,
    nodata: float = -9999.0,
    dtype: str = "float32",
) -> None:
    """
    Save numpy array as GeoTIFF with PL-1992 (EPSG:2180) CRS (GeoTiffWriter).

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
        Output data type ('float32', 'float64', 'int32', 'int16', 'uint8')
    """
    with GeoTiffWriter(
        output_path, metadata, data.shape, nodata=nodata, dtype=dtype
    ) as writer:
        writer.write_rows(0, data)


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
