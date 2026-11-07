"""
Generate a colored PNG overlay from DEM raster for Leaflet display.

Reads a DEM (GeoTIFF/VRT), applies a hypsometric color ramp blended with a hillshade,
saves as transparent PNG of at most ``--max-size`` px with WGS84 bounds metadata.

The DEM is read in strips of whole rows, never as a whole: two reads (of a float32
DEM) give the extremes and the exact 5th-95th percentile colour range of all valid
cells, one more averages the elevation and the hillshade (computed at full
resolution) over square blocks of cells, about twice as fine as the PNG. The blocks
are reprojected to EPSG:4326 onto the pixels of the PNG and coloured there; the share
of valid cells sets the alpha.

Usage:
    python -m scripts.generate_dem_overlay --input ../data/e2e_test/dem_mosaic.vrt \
        --output ../frontend/data/dem.png --meta ../frontend/data/dem.json
"""

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from PIL import Image
from rasterio.io import DatasetReader
from rasterio.warp import Resampling, reproject

from utils.dem_color import (
    HILLSHADE_HALO_ROWS,
    OverlayGrid,
    colorize_elevation,
    overlay_grid,
    read_strips,
    reduce_into,
    reduction_factor,
    shade_strip,
    strip_rows,
    summarize_elevation,
    valid_elevation,
)

OVERSAMPLING = 2
"""Blocks of the reduced DEM per PNG pixel and side, before the reprojection."""


def generate_overlay(
    input_path: str,
    output_png: str,
    output_meta: str,
    max_size: int = 1024,
    source_crs: str | None = None,
    no_hillshade: bool = False,
) -> None:
    """Generate colored PNG and metadata JSON from DEM raster."""
    dst_crs = "EPSG:4326"

    with rasterio.open(input_path) as src:
        src_crs = src.crs or source_crs
        if src_crs is None:
            print("Error: raster has no CRS. Use --source-crs.", file=sys.stderr)
            sys.exit(1)

        grid = overlay_grid(
            src_crs, src.transform, src.width, src.height, max_size, dst_crs
        )
        summary = summarize_elevation(src)
        factor = 1
        if grid.downsampled:
            factor = reduction_factor(
                src.height, src.width, OVERSAMPLING * max(grid.width, grid.height)
            )
        elevation, hillshade, coverage = _block_means(src, factor, not no_hillshade)
        if not no_hillshade:
            print(f"Hillshade computed (cellsize={abs(src.transform.a):.2f} m)")
        block_transform = src.transform * Affine.scale(factor)

    # Average blocks into the PNG pixels; without shrinking, interpolate as before.
    resampling = Resampling.average if grid.downsampled else Resampling.bilinear

    def warp(values: np.ndarray) -> np.ndarray:
        return _warp(values, src_crs, block_transform, grid, dst_crs, resampling)

    dem = warp(elevation)
    share = np.clip(np.nan_to_num(warp(coverage)), 0.0, 1.0)
    valid = np.isfinite(dem) & (share > 0)
    shade = None if hillshade is None else np.nan_to_num(warp(hillshade))

    print(
        f"DEM averaged over blocks of {factor}x{factor} cells and reprojected to "
        f"{dst_crs}: {grid.width}x{grid.height}, elevation "
        f"{summary.elevation_min_m:.1f}–{summary.elevation_max_m:.1f} m "
        f"(color range p5–p95: {summary.color_min_m:.1f}–{summary.color_max_m:.1f} m)"
    )

    rgba = colorize_elevation(
        dem, valid, summary.color_min_m, summary.color_max_m, shade
    )
    # The alpha is the share of valid cells, as shrinking the full image gave it.
    rgba[..., 3] = np.where(valid, np.rint(share * 255), 0).astype(np.uint8)
    if shade is not None:
        print("Hillshade blended with hypsometric ramp")

    img = Image.fromarray(rgba, mode="RGBA")
    if grid.downsampled:
        print(
            f"Downsampled: {grid.full_width}x{grid.full_height} → "
            f"{img.width}x{img.height}"
        )
    img.save(output_png, optimize=True)
    file_size = Path(output_png).stat().st_size
    print(f"PNG saved: {output_png} ({file_size / 1024:.0f} KB)")

    bounds = grid.bounds
    (lat_min, lon_min), (lat_max, lon_max) = bounds
    meta = {
        "bounds": bounds,
        "elevation_min_m": round(summary.elevation_min_m, 1),
        "elevation_max_m": round(summary.elevation_max_m, 1),
        "color_min_m": round(summary.color_min_m, 1),
        "color_max_m": round(summary.color_max_m, 1),
        "width": img.width,
        "height": img.height,
        "crs_source": str(src_crs),
        "generated_at": int(time.time()),
    }

    with open(output_meta, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata: {output_meta}")
    print(
        f"WGS84 bounds: [{lat_min:.6f}, {lon_min:.6f}] → [{lat_max:.6f}, {lon_max:.6f}]"
    )


def _block_means(
    src: DatasetReader, factor: int, hillshade: bool
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray]:
    """
    Average the valid cells of a DEM over blocks of ``factor`` x ``factor`` cells.

    Parameters
    ----------
    src : DatasetReader
        Open DEM, read strip by strip.
    factor : int
        Side of a block (cells).
    hillshade : bool
        Whether to average the hillshade too.

    Returns
    -------
    tuple[np.ndarray, np.ndarray | None, np.ndarray]
        Per block (``ceil(height / factor)`` x ``ceil(width / factor)``, float64):
        the mean elevation and the mean hillshade of its valid cells (NaN without
        one; no hillshade array without ``hillshade``), and the share of the block
        that is valid.
    """
    shape = (math.ceil(src.height / factor), math.ceil(src.width / factor))
    elevation_sum = np.zeros(shape)
    hillshade_sum = np.zeros(shape) if hillshade else None
    valid_cells = np.zeros(shape)
    cellsize_m = abs(src.transform.a)
    halo = HILLSHADE_HALO_ROWS if hillshade else 0
    for strip in read_strips(src, strip_rows(src.width), halo):
        valid = valid_elevation(strip.core, src.nodata)
        elevation = np.where(valid, strip.core, 0).astype(np.float64)
        reduce_into(elevation_sum, elevation, strip.row0, 0, factor, np.add)
        reduce_into(
            valid_cells, valid.astype(np.float64), strip.row0, 0, factor, np.add
        )
        if hillshade_sum is not None:
            shade = shade_strip(strip, src.nodata, cellsize_m)
            reduce_into(hillshade_sum, shade, strip.row0, 0, factor, np.add)

    covered = valid_cells > 0
    divisor = np.where(covered, valid_cells, 1.0)
    mean_elevation = np.where(covered, elevation_sum / divisor, np.nan)
    mean_hillshade = None
    if hillshade_sum is not None:
        mean_hillshade = np.where(covered, hillshade_sum / divisor, np.nan)
    return mean_elevation, mean_hillshade, valid_cells / factor**2


def _warp(
    values: np.ndarray,
    src_crs: Any,
    src_transform: Affine,
    grid: OverlayGrid,
    dst_crs: str,
    resampling: Resampling,
) -> np.ndarray:
    """Reproject float blocks (NaN = no data) onto the pixels of the PNG."""
    warped = np.full((grid.height, grid.width), np.nan)
    reproject(
        source=values,
        destination=warped,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=grid.transform,
        dst_crs=dst_crs,
        resampling=resampling,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    return warped


def main() -> None:
    """Run the DEM overlay generator."""
    parser = argparse.ArgumentParser(description="Generate DEM overlay PNG for Leaflet")
    parser.add_argument("--input", required=True, help="Input DEM raster (GeoTIFF/VRT)")
    parser.add_argument("--output", required=True, help="Output PNG path")
    parser.add_argument("--meta", required=True, help="Output metadata JSON path")
    parser.add_argument(
        "--max-size",
        type=int,
        default=1024,
        help="Max image dimension in pixels (default: 1024)",
    )
    parser.add_argument(
        "--source-crs",
        default=None,
        help="Source CRS override (e.g. EPSG:2180) if raster has no CRS metadata",
    )
    parser.add_argument(
        "--no-hillshade",
        action="store_true",
        help="Disable hillshade blending (default: hillshade enabled)",
    )
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    generate_overlay(
        args.input,
        args.output,
        args.meta,
        args.max_size,
        args.source_crs,
        no_hillshade=args.no_hillshade,
    )


if __name__ == "__main__":
    main()
