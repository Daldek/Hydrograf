"""
Utilities for raster operations including VRT mosaic creation.

This module provides functions for working with multiple DEM tiles,
creating virtual rasters (VRT), and reading mosaicked data.

VRT (Virtual Raster) is preferred over physical merge because:
- No data duplication on disk
- Instant creation (~1s vs minutes for large areas)
- Transparent to GDAL/rasterio/pyflwdir
- Original tiles can be updated independently
"""

import logging
import math
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# PUWG 2000 zones: easting prefix -> EPSG code
_PUWG2000_ZONES = {
    5: 2176,
    6: 2177,
    7: 2178,
    8: 2179,
}
TARGET_CRS = "EPSG:2180"  # PUWG 1992
TARGET_RES_M = 5.0  # Default hydro resolution (matches Kartograf download)


def _read_asc_header(path: Path) -> dict[str, Any]:
    """Read ASC grid header (first 6 lines) to get origin and cellsize."""
    header = {}
    with open(path) as f:
        for _ in range(6):
            line = f.readline().strip()
            if not line:
                break
            parts = re.split(r"\s+", line, maxsplit=1)
            if len(parts) == 2:
                header[parts[0].lower()] = float(parts[1])
    return header


def _detect_crs_from_coords(xll: float, yll: float) -> str | None:
    """Detect CRS from ASC corner coordinates.

    Returns EPSG code string or None if coordinates look like EPSG:2180.
    """
    if xll > 1_000_000:
        zone = int(xll // 1_000_000)
        epsg = _PUWG2000_ZONES.get(zone)
        if epsg:
            return f"EPSG:{epsg}"
        logger.warning(f"Unknown PUWG 2000 zone for easting={xll}")
    return None  # EPSG:2180 or unknown


def normalize_crs(
    input_files: list[Path],
    output_dir: Path,
) -> list[Path]:
    """Detect and reproject ASC files not in EPSG:2180 (PUWG 1992).

    GUGiK serves NMT 1m data in PUWG 1992 (EPSG:2180) or PUWG 2000
    (EPSG:2176-2179) depending on the region.  Files in PUWG 2000 are
    reprojected to EPSG:2180 using gdalwarp so that all tiles can be
    mosaicked into a single VRT.  Files already in EPSG:2180 pass through
    unchanged and nothing is written next to any input: the inputs may live
    in a store that Hydrograf must not modify.

    Parameters
    ----------
    input_files : list[Path]
        ASC files to check.
    output_dir : Path
        Hydrograf's directory for the reprojected copies (gdalwarp writes
        each ``.asc`` with its ``.prj`` there).  Never the directory of the
        inputs.

    Returns
    -------
    list[Path]
        Paths ready for mosaicking, in input order: original files for
        EPSG:2180, reprojected ASC grids for the others.  Missing inputs
        are skipped.
    """
    if not input_files:
        return []

    result: list[Path] = []
    n_reprojected = 0

    for f in input_files:
        if not f.exists():
            continue

        hdr = _read_asc_header(f)
        xll = hdr.get("xllcorner", hdr.get("xllcenter", 0.0))
        yll = hdr.get("yllcorner", hdr.get("yllcenter", 0.0))

        source_crs = _detect_crs_from_coords(xll, yll)

        if source_crs is None:
            # Already in EPSG:2180: used as it is, nothing written beside it.
            result.append(f)
            continue

        # Needs reprojection
        output_dir.mkdir(parents=True, exist_ok=True)

        # Use source cellsize (preserve native resolution)
        src_cellsize = hdr.get("cellsize", TARGET_RES_M)
        target_res = max(src_cellsize, TARGET_RES_M)

        logger.info(
            f"Reprojecting {f.name}: {source_crs} → {TARGET_CRS} "
            f"(resample to {target_res}m)"
        )

        # Reproject to ASC format (matching original tiles) so that
        # gdalbuildvrt sees uniform band color interpretation ("Undefined").
        # GeoTIFF has "Gray" which causes gdalbuildvrt to skip them.
        out_asc = output_dir / f"{f.stem}.asc"

        if out_asc.exists():
            logger.debug(f"Reprojected file exists, reusing: {out_asc.name}")
            result.append(out_asc)
            n_reprojected += 1
            continue

        cmd = [
            "gdalwarp",
            "-s_srs",
            source_crs,
            "-t_srs",
            TARGET_CRS,
            "-tr",
            str(target_res),
            str(target_res),
            "-r",
            "bilinear",
            "-of",
            "AAIGrid",
            "-overwrite",
            str(f),
            str(out_asc),
        ]

        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            result.append(out_asc)
            n_reprojected += 1
        except subprocess.CalledProcessError as e:
            logger.error(f"gdalwarp failed for {f.name}: {e.stderr}")
            raise RuntimeError(f"Reprojection failed for {f.name}: {e.stderr}") from e

    if n_reprojected:
        logger.info(
            f"CRS normalization: {n_reprojected}/{len(input_files)} files "
            f"reprojected from PUWG 2000 to {TARGET_CRS}"
        )
    else:
        logger.info("CRS normalization: all files already in EPSG:2180")

    return result


def _sheet_frame(path: Path) -> tuple[float, float, float, float, float]:
    """Return ``(left, bottom, right, top, cellsize)`` of a sheet in its own CRS."""
    if path.suffix.lower() == ".asc":
        header = _read_asc_header(path)
        cellsize = header["cellsize"]
        left = header.get("xllcorner", header.get("xllcenter", 0.0) - cellsize / 2)
        bottom = header.get("yllcorner", header.get("yllcenter", 0.0) - cellsize / 2)
        return (
            left,
            bottom,
            left + header["ncols"] * cellsize,
            bottom + header["nrows"] * cellsize,
            cellsize,
        )
    import rasterio

    with rasterio.open(path) as src:
        if abs(src.res[0] - src.res[1]) > 1e-9 * src.res[0]:
            raise ValueError(f"{path} has cells that are not square: {src.res}")
        return (*src.bounds, src.res[0])


def align_to_cellsize(
    input_files: list[Path],
    output_dir: Path,
    cellsize_m: float = TARGET_RES_M,
) -> list[Path]:
    """Put every sheet on the grid of the sheets of ``cellsize_m``, without a VRT.

    A set of one resolution can hold sheets of a finer one: GUGiK delivers some of
    the 5 m NMT sheets of 2021 as 1 m grids. ``gdalbuildvrt -resolution highest``
    then makes the whole mosaic 1 m, and a VRT of any other resolution resamples the
    odd sheets on every read, where two windows can read one cell differently. So
    each finer sheet is averaged (``gdalwarp -r average``) to ``cellsize_m`` on the
    lattice of the sheets that already have it (their corners agree modulo
    ``cellsize_m``), as an ASC grid in ``output_dir``; the mosaic of the result has
    the cells of those sheets and reads every source cell for cell.

    Parameters
    ----------
    input_files : list[Path]
        Sheets in EPSG:2180 (after ``normalize_crs``).
    output_dir : Path
        Hydrograf's directory for the averaged copies (never the store of the
        inputs); a copy that exists is used again.
    cellsize_m : float
        Cell size of the run [m].

    Returns
    -------
    list[Path]
        The paths for the mosaic, in input order.

    Raises
    ------
    ValueError
        The sheets of ``cellsize_m`` lie on different lattices, or a sheet is
        coarser than ``cellsize_m``.
    """
    tolerance = 1e-6 * cellsize_m
    frames = {path: _sheet_frame(path) for path in input_files}
    offsets = {
        (round(left % cellsize_m, 6), round(top % cellsize_m, 6))
        for left, _, _, top, cellsize in frames.values()
        if abs(cellsize - cellsize_m) <= tolerance
    }
    if len(offsets) > 1:
        raise ValueError(
            f"The {cellsize_m:g} m sheets lie on {len(offsets)} different grids "
            f"(corner offsets {sorted(offsets)}): no mosaic reads them cell for cell"
        )
    offset_x, offset_y = offsets.pop() if offsets else (0.0, 0.0)
    result: list[Path] = []
    averaged = 0
    for path in input_files:
        left, bottom, right, top, cellsize = frames[path]
        if abs(cellsize - cellsize_m) <= tolerance:
            result.append(path)
            continue
        if cellsize > cellsize_m:
            raise ValueError(
                f"{path.name} has {cellsize:g} m cells, coarser than the "
                f"{cellsize_m:g} m of the run"
            )
        target = output_dir / f"{path.stem}_{cellsize_m:g}m.asc"
        result.append(target)
        averaged += 1
        if target.exists():
            continue
        output_dir.mkdir(parents=True, exist_ok=True)
        # The frame grows outward to whole cells of the lattice.
        x0 = math.floor((left - offset_x) / cellsize_m) * cellsize_m + offset_x
        y0 = math.floor((bottom - offset_y) / cellsize_m) * cellsize_m + offset_y
        x1 = math.ceil((right - offset_x) / cellsize_m) * cellsize_m + offset_x
        y1 = math.ceil((top - offset_y) / cellsize_m) * cellsize_m + offset_y
        partial = target.with_name(f".{target.name}.partial")
        cmd = [
            "gdalwarp",
            "-q",
            "-overwrite",
            "-s_srs",
            TARGET_CRS,
            "-t_srs",
            TARGET_CRS,
            "-r",
            "average",
            "-tr",
            repr(cellsize_m),
            repr(cellsize_m),
            "-te",
            *(repr(value) for value in (x0, y0, x1, y1)),
            "-srcnodata",
            "-9999",
            "-dstnodata",
            "-9999",
            "-of",
            "AAIGrid",
            str(path),
            str(partial),
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Averaging {path.name} failed: {e.stderr}") from e
        partial.replace(target)
        for sidecar in output_dir.glob(f"{partial.name}.*"):
            sidecar.unlink()
        partial.with_suffix(".prj").unlink(missing_ok=True)
    if averaged:
        logger.info(
            "Grid alignment: %d of %d sheets averaged to %g m on the grid of the "
            "others",
            averaged,
            len(input_files),
            cellsize_m,
        )
    return result


def create_vrt_mosaic(
    input_files: list[Path],
    output_vrt: Path | None = None,
    resolution: str = "highest",
    nodata: float = -9999.0,
    target_crs: str | None = None,
) -> Path:
    """
    Create a mosaic from multiple DEM tiles.

    Tries to use GDAL's gdalbuildvrt for true VRT (virtual raster).
    Falls back to rasterio.merge for physical merge if GDAL is unavailable.

    Parameters
    ----------
    input_files : List[Path]
        List of paths to input raster files (ASC, TIF, etc.)
    output_vrt : Path, optional
        Output file path. Extension determines format:
        - .vrt: Virtual raster (requires GDAL)
        - .tif: GeoTIFF (fallback with rasterio.merge)
        If None, creates temp file.
    resolution : str
        Resolution strategy: 'highest', 'lowest', 'average', 'user'
        Default 'highest' uses the finest resolution among inputs.
    nodata : float
        NoData value for the mosaic (default: -9999.0)
    target_crs : str, optional
        CRS of every input (e.g. ``"EPSG:2180"``), assigned to the mosaic;
        the CRS an input declares itself, or the lack of one (ASC sheets of
        the Kartograf store have no ``.prj``), is ignored.  If None, the
        mosaic takes the CRS of the inputs.

    Returns
    -------
    Path
        Path to created mosaic file (VRT or GeoTIFF)

    Raises
    ------
    ValueError
        If no input files provided

    Examples
    --------
    >>> tiles = [Path("tile1.asc"), Path("tile2.asc")]
    >>> mosaic_path = create_vrt_mosaic(tiles, Path("mosaic.vrt"))
    >>> print(mosaic_path)
    mosaic.vrt  # or mosaic.tif if GDAL unavailable
    """
    if not input_files:
        raise ValueError("No input files provided for mosaic")

    # Filter existing files
    existing_files = [f for f in input_files if f.exists()]
    if not existing_files:
        raise ValueError(f"None of the input files exist: {input_files}")

    if len(existing_files) != len(input_files):
        missing = set(input_files) - set(existing_files)
        logger.warning(f"Missing files (will be skipped): {missing}")

    logger.info(f"Creating mosaic from {len(existing_files)} files...")

    # Create output path if not specified
    if output_vrt is None:
        output_vrt = Path(tempfile.mktemp(suffix=".vrt", prefix="dem_mosaic_"))

    # Try GDAL's gdalbuildvrt first (preferred - true VRT, no data duplication)
    try:
        return _create_vrt_gdal(
            existing_files, output_vrt, resolution, nodata, target_crs
        )
    except RuntimeError as e:
        if "not found" in str(e).lower():
            logger.warning("GDAL not available, falling back to rasterio.merge")
            # Change extension to .tif for physical merge
            output_tif = output_vrt.with_suffix(".tif")
            return _create_mosaic_rasterio(
                existing_files, output_tif, nodata, target_crs
            )
        raise


def _create_vrt_gdal(
    input_files: list[Path],
    output_vrt: Path,
    resolution: str,
    nodata: float,
    target_crs: str | None = None,
) -> Path:
    """Create VRT using GDAL's gdalbuildvrt command.

    With ``target_crs`` the VRT gets that CRS (``-a_srs``) and inputs whose
    own projection differs or is missing are kept
    (``-allow_projection_difference``); without the flag gdalbuildvrt
    silently drops them.
    """
    cmd = [
        "gdalbuildvrt",
        "-resolution",
        resolution,
        "-srcnodata",
        str(nodata),
        "-vrtnodata",
        str(nodata),
        "-overwrite",
    ]
    if target_crs:
        cmd.extend(["-a_srs", target_crs, "-allow_projection_difference"])
    cmd.append(str(output_vrt))
    cmd.extend(str(f) for f in input_files)

    logger.debug(f"Running: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        if result.stdout:
            logger.debug(f"gdalbuildvrt stdout: {result.stdout}")

    except subprocess.CalledProcessError as e:
        logger.error(f"gdalbuildvrt failed: {e.stderr}")
        raise RuntimeError(f"Failed to create VRT: {e.stderr}") from e

    except FileNotFoundError:
        raise RuntimeError(
            "gdalbuildvrt not found. Install GDAL: "
            "apt-get install gdal-bin (Linux) or brew install gdal (macOS)"
        ) from None

    logger.info(f"VRT created: {output_vrt}")
    logger.info(f"VRT file size: {output_vrt.stat().st_size / 1024:.1f} KB")

    return output_vrt


def _create_mosaic_rasterio(
    input_files: list[Path],
    output_path: Path,
    nodata: float,
    target_crs: str | None = None,
) -> Path:
    """
    Create physical mosaic using rasterio.merge.

    This is a fallback when GDAL is not available. Creates a GeoTIFF
    file with LZW compression.  The mosaic gets ``target_crs`` when given,
    otherwise the CRS of the first input.
    """
    import rasterio
    from rasterio.merge import merge

    logger.info(f"Creating mosaic with rasterio.merge ({len(input_files)} files)...")

    # Open all input files
    src_files = [rasterio.open(f) for f in input_files]

    try:
        # Merge all files
        mosaic, out_transform = merge(
            src_files,
            nodata=nodata,
            method="first",  # Use first non-nodata value
        )

        # Get metadata from first file
        out_meta = src_files[0].meta.copy()
        out_meta.update(
            {
                "driver": "GTiff",
                "height": mosaic.shape[1],
                "width": mosaic.shape[2],
                "transform": out_transform,
                "nodata": nodata,
                "compress": "lzw",
            }
        )
        if target_crs:
            out_meta["crs"] = target_crs

        # Write output
        with rasterio.open(output_path, "w", **out_meta) as dest:
            dest.write(mosaic)

    finally:
        # Close all source files
        for src in src_files:
            src.close()

    logger.info(f"Mosaic created: {output_path}")
    logger.info(
        f"Mosaic file size: {output_path.stat().st_size / (1024 * 1024):.1f} MB"
    )

    return output_path


def read_vrt_as_array(
    vrt_path: Path,
) -> tuple[np.ndarray, dict[str, Any]]:
    """
    Read VRT mosaic as numpy array with metadata.

    Parameters
    ----------
    vrt_path : Path
        Path to VRT file

    Returns
    -------
    tuple
        (data array, metadata dict with transform, crs, nodata, shape)

    Examples
    --------
    >>> data, meta = read_vrt_as_array(Path("mosaic.vrt"))
    >>> print(data.shape, meta['nodata'])
    (5000, 6000) -9999.0
    """
    import rasterio

    with rasterio.open(vrt_path) as src:
        data = src.read(1)
        metadata = {
            "transform": src.transform,
            "crs": src.crs,
            "nodata": src.nodata,
            "width": src.width,
            "height": src.height,
            "bounds": src.bounds,
            "dtype": src.dtypes[0],
            # Extract corner and cellsize for compatibility with ASCII grid format
            "xllcorner": src.bounds.left,
            "yllcorner": src.bounds.bottom,
            "cellsize": src.transform.a,  # Pixel width (assumes square pixels)
            "ncols": src.width,
            "nrows": src.height,
            "nodata_value": src.nodata if src.nodata is not None else -9999.0,
        }

    logger.info(f"Read VRT: {metadata['nrows']}x{metadata['ncols']} cells")
    logger.info(f"Bounds: {metadata['bounds']}")
    logger.info(f"Cell size: {metadata['cellsize']} m")

    return data, metadata


def get_mosaic_info(vrt_path: Path) -> dict[str, Any]:
    """
    Get information about VRT mosaic without loading data.

    Parameters
    ----------
    vrt_path : Path
        Path to VRT file

    Returns
    -------
    dict
        Mosaic information including dimensions, bounds, cell size
    """
    import rasterio

    with rasterio.open(vrt_path) as src:
        info = {
            "width": src.width,
            "height": src.height,
            "total_cells": src.width * src.height,
            "bounds": src.bounds,
            "crs": str(src.crs),
            "cell_size_m": src.transform.a,
            "nodata": src.nodata,
            "dtype": src.dtypes[0],
            "estimated_memory_mb": (src.width * src.height * 4)
            / (1024 * 1024),  # float32
        }

    return info


def validate_tiles_compatibility(input_files: list[Path]) -> dict[str, Any]:
    """
    Validate that all tiles are compatible for mosaicking.

    Checks CRS, cell size, and data type consistency.

    Parameters
    ----------
    input_files : List[Path]
        List of raster files to validate

    Returns
    -------
    dict
        Validation results with 'valid', 'issues', and 'summary'
    """
    import rasterio

    results: dict[str, Any] = {
        "valid": True,
        "issues": [],
        "summary": {},
    }

    if not input_files:
        results["valid"] = False
        results["issues"].append("No input files provided")
        return results

    # Collect metadata from all files
    metadata_list = []
    for f in input_files:
        if not f.exists():
            results["issues"].append(f"File not found: {f}")
            continue

        try:
            with rasterio.open(f) as src:
                metadata_list.append(
                    {
                        "file": f.name,
                        "crs": str(src.crs),
                        "cell_size": round(src.transform.a, 6),
                        "dtype": src.dtypes[0],
                        "nodata": src.nodata,
                    }
                )
        except Exception as e:
            results["issues"].append(f"Cannot read {f}: {e}")

    if not metadata_list:
        results["valid"] = False
        results["issues"].append("No readable files found")
        return results

    # Check consistency
    reference = metadata_list[0]
    results["summary"]["reference_crs"] = reference["crs"]
    results["summary"]["reference_cell_size"] = reference["cell_size"]
    results["summary"]["total_files"] = len(metadata_list)

    for meta in metadata_list[1:]:
        if meta["crs"] != reference["crs"]:
            results["valid"] = False
            results["issues"].append(
                f"CRS mismatch: {meta['file']} has {meta['crs']}, "
                f"expected {reference['crs']}"
            )

        if abs(meta["cell_size"] - reference["cell_size"]) > 0.0001:
            results["valid"] = False
            results["issues"].append(
                f"Cell size mismatch: {meta['file']} has {meta['cell_size']}, "
                f"expected {reference['cell_size']}"
            )

    if results["valid"]:
        logger.info(f"All {len(metadata_list)} tiles are compatible")
    else:
        logger.warning(f"Tile validation failed: {results['issues']}")

    return results


def resample_raster(
    input_path: Path,
    output_path: Path,
    target_resolution: float,
    method: str = "bilinear",
) -> Path:
    """
    Resample raster to target resolution.

    Parameters
    ----------
    input_path : Path
        Input raster file
    output_path : Path
        Output resampled raster file
    target_resolution : float
        Target cell size in meters
    method : str
        Resampling method: 'nearest', 'bilinear', 'cubic', 'average'
        Default 'bilinear' for continuous data like elevation.

    Returns
    -------
    Path
        Path to resampled raster
    """
    import rasterio
    from rasterio.enums import Resampling

    resampling_methods = {
        "nearest": Resampling.nearest,
        "bilinear": Resampling.bilinear,
        "cubic": Resampling.cubic,
        "average": Resampling.average,
    }

    resample_method = resampling_methods.get(method, Resampling.bilinear)

    with rasterio.open(input_path) as src:
        from rasterio.transform import from_bounds

        # Calculate new dimensions (zachowaj proporcje)
        src_resolution = abs(src.transform.a)
        scale_factor = src_resolution / target_resolution

        new_width = int(src.width * scale_factor)
        new_height = int(src.height * scale_factor)

        # Oblicz rzeczywistą rozdzielczość zachowując dokładne bounds
        bounds = src.bounds
        actual_res_x = (bounds.right - bounds.left) / new_width
        _ = (bounds.top - bounds.bottom) / new_height  # actual_res_y not used

        logger.info(
            f"Resampling {input_path.name}: "
            f"{src.width}x{src.height} ({src_resolution:.6f}m) "
            f"-> {new_width}x{new_height} ({actual_res_x:.6f}m)"
        )

        # Transform zachowujący dokładne bounds (extent) - EPSG:2180
        new_transform = from_bounds(
            bounds.left, bounds.bottom, bounds.right, bounds.top, new_width, new_height
        )

        # Read and resample data
        data = src.read(
            out_shape=(src.count, new_height, new_width),
            resampling=resample_method,
        )

        # Update metadata
        out_meta = src.meta.copy()
        out_meta.update(
            {
                "width": new_width,
                "height": new_height,
                "transform": new_transform,
                "compress": "lzw",
            }
        )

        # Write output
        with rasterio.open(output_path, "w", **out_meta) as dst:
            dst.write(data)

    logger.info(f"Resampled raster saved: {output_path}")
    logger.info(f"File size: {output_path.stat().st_size / (1024 * 1024):.1f} MB")

    return output_path


def convert_asc_to_geotiff(
    input_asc: Path,
    output_tif: Path | None = None,
    compress: str = "LZW",
) -> Path:
    """
    Convert ASCII Grid to GeoTIFF with compression.

    Useful for reducing disk space - LZW-compressed GeoTIFF is typically
    50-70% smaller than ASCII Grid.

    Parameters
    ----------
    input_asc : Path
        Input ASCII Grid file
    output_tif : Path, optional
        Output GeoTIFF path. If None, uses same name with .tif extension.
    compress : str
        Compression algorithm: 'LZW', 'DEFLATE', 'ZSTD', 'NONE'

    Returns
    -------
    Path
        Path to created GeoTIFF
    """
    if output_tif is None:
        output_tif = input_asc.with_suffix(".tif")

    cmd = [
        "gdal_translate",
        "-of",
        "GTiff",
        "-co",
        f"COMPRESS={compress}",
        "-co",
        "TILED=YES",
        str(input_asc),
        str(output_tif),
    ]

    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"gdal_translate failed: {e.stderr}") from e

    logger.info(f"Converted {input_asc.name} -> {output_tif.name}")
    logger.info(
        f"Size reduction: {input_asc.stat().st_size / 1024:.0f} KB -> "
        f"{output_tif.stat().st_size / 1024:.0f} KB"
    )

    return output_tif
