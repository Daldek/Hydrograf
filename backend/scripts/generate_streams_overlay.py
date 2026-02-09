"""
Generate a colored PNG overlay from stream order raster for Leaflet display.

Reads a Strahler stream order raster (uint8, 0=no stream, 1-8=order),
applies a discrete blue color palette, saves as transparent PNG
with WGS84 bounds metadata.

Usage:
    python -m scripts.generate_streams_overlay \
        --input ../data/e2e_test/intermediates/N-33-131-C-b-2-3_07_stream_order.tif \
        --output ../frontend/data/streams.png \
        --meta ../frontend/data/streams.json
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from scipy.ndimage import maximum_filter

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


def generate_overlay(
    input_path: str, output_png: str, output_meta: str, max_size: int = 1024
) -> None:
    """Generate colored PNG and metadata JSON from stream order raster."""
    with rasterio.open(input_path) as src:
        data = src.read(1)
        crs = src.crs
        bounds = src.bounds
        height, width = data.shape

    # Find max order present in data
    max_order = int(np.max(data))
    stream_pixels = int(np.count_nonzero(data))
    print(f"Stream order: {width}x{height}, max order={max_order}, "
          f"stream pixels={stream_pixels}")

    # Dilate streams to make them visible after downsampling.
    # Line width grows with Strahler order (order 1 → 3px, order 5 → 7px).
    # Process low→high so higher orders paint over lower ones.
    dilated = np.zeros_like(data)
    for order in range(1, max_order + 1):
        mask = data == order
        if not np.any(mask):
            continue
        kernel_size = 2 * order + 1  # 3, 5, 7, 9, 11, 13, 15, 17
        order_arr = np.where(mask, order, 0).astype(data.dtype)
        expanded = maximum_filter(order_arr, size=kernel_size)
        dilated = np.where(expanded > 0, expanded, dilated)

    dilated_pixels = int(np.count_nonzero(dilated))
    print(f"After dilation: {dilated_pixels} visible pixels "
          f"({100 * dilated_pixels / (width * height):.1f}%)")

    # Build RGBA image
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    for order, (r, g, b) in STRAHLER_COLORS.items():
        mask = dilated == order
        rgba[mask, 0] = r
        rgba[mask, 1] = g
        rgba[mask, 2] = b
        rgba[mask, 3] = 255
    # order 0 stays (0,0,0,0) = fully transparent

    # Save PNG (with optional downsampling)
    img = Image.fromarray(rgba, mode="RGBA")
    if max_size and (width > max_size or height > max_size):
        img.thumbnail((max_size, max_size), Image.NEAREST)
        print(f"Downsampled: {width}x{height} → {img.width}x{img.height}")
        width, height = img.width, img.height
    img.save(output_png, optimize=True)
    file_size = Path(output_png).stat().st_size
    print(f"PNG saved: {output_png} ({file_size / 1024:.0f} KB)")

    # Transform bounds to WGS84
    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    lon_min, lat_min = transformer.transform(bounds.left, bounds.bottom)
    lon_max, lat_max = transformer.transform(bounds.right, bounds.top)

    meta = {
        "bounds": [[lat_min, lon_min], [lat_max, lon_max]],
        "max_order": max_order,
        "width": width,
        "height": height,
        "crs_source": str(crs),
    }

    with open(output_meta, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata: {output_meta}")
    print(f"WGS84 bounds: [{lat_min:.6f}, {lon_min:.6f}] → "
          f"[{lat_max:.6f}, {lon_max:.6f}]")


def main() -> None:
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
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    generate_overlay(args.input, args.output, args.meta, args.max_size)


if __name__ == "__main__":
    main()
