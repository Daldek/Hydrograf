"""
Generate a colored PNG overlay from stream order raster for Leaflet display.

Reads a Strahler stream order raster (uint8, 0=no stream, 1-8=order),
applies a discrete blue color palette, saves as transparent PNG
with WGS84 bounds metadata.

The raster is read in strips of whole rows, never as a whole. The streams are dilated
at full resolution, so their lines widen with the order; when the PNG is smaller than
the raster, square blocks of cells, about twice as fine as the PNG, keep the highest
order they hold and the PNG pixels the highest order of their blocks, so no line
breaks up.

Usage:
    python -m scripts.generate_streams_overlay \
        --input ../data/e2e_test/intermediates/N-33-131-C-b-2-3_07_stream_order.tif \
        --output ../frontend/data/streams.png \
        --meta ../frontend/data/streams.json
"""

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from PIL import Image
from rasterio.warp import Resampling, reproject
from scipy.ndimage import maximum_filter

from utils.dem_color import (
    overlay_grid,
    read_strips,
    reduce_into,
    reduction_factor,
    strip_rows,
)

# Discrete color palette for Strahler orders 1–8 (blue gradient)
STRAHLER_COLORS = {
    1: (0xB3, 0xE5, 0xFC),  # #B3E5FC — light blue
    2: (0x81, 0xD4, 0xFA),  # #81D4FA
    3: (0x4F, 0xC3, 0xF7),  # #4FC3F7
    4: (0x29, 0xB6, 0xF6),  # #29B6F6
    5: (0x03, 0x9B, 0xE5),  # #039BE5
    6: (0x02, 0x77, 0xBD),  # #0277BD
    7: (0x01, 0x57, 0x9B),  # #01579B
    8: (0x00, 0x2F, 0x6C),  # #002F6C — dark blue
}

OVERSAMPLING = 2
"""Blocks of the reduced raster per PNG pixel and side, before the reprojection."""


def generate_overlay(
    input_path: str,
    output_png: str,
    output_meta: str,
    max_size: int = 1024,
    source_crs: str | None = None,
) -> None:
    """Generate colored PNG and metadata JSON from stream order raster."""
    dst_crs = "EPSG:4326"

    with rasterio.open(input_path) as src:
        src_crs = src.crs or source_crs
        if src_crs is None:
            print("Error: raster has no CRS. Use --source-crs.", file=sys.stderr)
            sys.exit(1)

        grid = overlay_grid(
            src_crs, src.transform, src.width, src.height, max_size, dst_crs
        )
        rows = strip_rows(src.width)

        # Find max order present in data
        max_order = 0
        stream_pixels = 0
        for strip in read_strips(src, rows):
            max_order = max(max_order, int(strip.data.max()))
            stream_pixels += int(np.count_nonzero(strip.data))
        print(
            f"Stream order: {src.width}x{src.height}, max order={max_order}, "
            f"stream pixels={stream_pixels}"
        )

        factor = 1
        if grid.downsampled:
            factor = reduction_factor(
                src.height, src.width, OVERSAMPLING * max(grid.width, grid.height)
            )
        blocks = np.zeros(
            (math.ceil(src.height / factor), math.ceil(src.width / factor)),
            dtype=src.dtypes[0],
        )
        dilated_pixels = 0
        # The dilation of order k reaches k rows: a halo of max_order rows makes the
        # rows of a strip equal those of the whole raster.
        for strip in read_strips(src, rows, halo=max_order):
            dilated = _dilate(strip.data, max_order)[
                strip.offset : strip.offset + strip.rows
            ]
            dilated_pixels += int(np.count_nonzero(dilated))
            reduce_into(blocks, dilated, strip.row0, 0, factor, np.maximum)
        print(
            f"After dilation: {dilated_pixels} visible pixels "
            f"({100 * dilated_pixels / (src.width * src.height):.1f}%)"
        )
        block_transform = src.transform * Affine.scale(factor)

    # Reproject the blocks onto the PNG pixels; when shrinking, a pixel keeps the
    # highest order of its blocks.
    reprojected = np.zeros((grid.height, grid.width), dtype=blocks.dtype)
    reproject(
        source=blocks,
        destination=reprojected,
        src_transform=block_transform,
        src_crs=src_crs,
        dst_transform=grid.transform,
        dst_crs=dst_crs,
        resampling=Resampling.max if grid.downsampled else Resampling.nearest,
        src_nodata=0,
        dst_nodata=0,
    )

    height, width = reprojected.shape
    print(f"Reprojected to {dst_crs}: {width}x{height}")

    # Build RGBA image
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    for order, (r, g, b) in STRAHLER_COLORS.items():
        mask = reprojected == order
        rgba[mask, 0] = r
        rgba[mask, 1] = g
        rgba[mask, 2] = b
        rgba[mask, 3] = 255
    # order 0 stays (0,0,0,0) = fully transparent

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
        "max_order": max_order,
        "width": img.width,
        "height": img.height,
        "crs_source": str(src_crs),
    }

    with open(output_meta, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata: {output_meta}")
    print(
        f"WGS84 bounds: [{lat_min:.6f}, {lon_min:.6f}] → [{lat_max:.6f}, {lon_max:.6f}]"
    )


def _dilate(data: np.ndarray, max_order: int) -> np.ndarray:
    """
    Widen the streams of a stream order raster by their order.

    Order k grows to a square of ``2k + 1`` cells (order 1 → 3, order 8 → 17); the
    orders are painted from low to high, so a higher order covers a lower one.

    Parameters
    ----------
    data : np.ndarray
        Stream orders (0 = no stream).
    max_order : int
        Highest order to paint.

    Returns
    -------
    np.ndarray
        The dilated orders, of the type of ``data``.
    """
    dilated = np.zeros_like(data)
    for order in range(1, max_order + 1):
        mask = data == order
        if not np.any(mask):
            continue
        kernel_size = 2 * order + 1
        order_arr = np.where(mask, order, 0).astype(data.dtype)
        expanded = maximum_filter(order_arr, size=kernel_size)
        dilated = np.where(expanded > 0, expanded, dilated)
    return dilated


def main() -> None:
    """Run the stream order overlay generator."""
    parser = argparse.ArgumentParser(
        description="Generate stream order overlay PNG for Leaflet"
    )
    parser.add_argument(
        "--input", required=True, help="Input stream order raster (GeoTIFF)"
    )
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
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    generate_overlay(args.input, args.output, args.meta, args.max_size, args.source_crs)


if __name__ == "__main__":
    main()
