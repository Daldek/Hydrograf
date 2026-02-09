"""
Generate a colored PNG overlay from DEM raster for Leaflet display.

Reads a DEM (GeoTIFF/VRT), applies a hypsometric color ramp,
saves as transparent PNG with WGS84 bounds metadata.

Usage:
    python -m scripts.generate_dem_overlay --input ../data/e2e_test/dem_mosaic.vrt \
        --output ../frontend/data/dem.png --meta ../frontend/data/dem.json
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer


# Hypsometric color ramp: (position, R, G, B)
COLOR_STOPS = [
    (0.0, 56, 128, 60),     # dark green — valleys
    (0.15, 76, 175, 80),    # green
    (0.30, 139, 195, 74),   # light green
    (0.45, 205, 220, 57),   # lime
    (0.60, 255, 193, 7),    # amber
    (0.75, 161, 110, 60),   # brown
    (0.90, 120, 100, 90),   # dark brown/grey
    (1.0, 245, 245, 240),   # near white — peaks
]


def build_colormap(n_steps: int = 256) -> np.ndarray:
    """Build a 256x3 uint8 colormap from color stops."""
    cmap = np.zeros((n_steps, 3), dtype=np.uint8)
    positions = [s[0] for s in COLOR_STOPS]
    colors = np.array([[s[1], s[2], s[3]] for s in COLOR_STOPS], dtype=np.float64)

    for i in range(n_steps):
        t = i / (n_steps - 1)
        # Find interval
        for k in range(len(positions) - 1):
            if positions[k] <= t <= positions[k + 1]:
                local_t = (t - positions[k]) / (positions[k + 1] - positions[k])
                rgb = colors[k] * (1 - local_t) + colors[k + 1] * local_t
                cmap[i] = np.clip(rgb, 0, 255).astype(np.uint8)
                break
    return cmap


def generate_overlay(
    input_path: str, output_png: str, output_meta: str, max_size: int = 1024
) -> None:
    """Generate colored PNG and metadata JSON from DEM raster."""
    with rasterio.open(input_path) as src:
        dem = src.read(1)
        nodata = src.nodata
        transform = src.transform
        crs = src.crs
        height, width = dem.shape

        # Bounds in source CRS
        bounds = src.bounds

    # Create mask for valid data
    if nodata is not None:
        valid = dem != nodata
    else:
        valid = np.isfinite(dem)

    # Elevation range
    valid_data = dem[valid]
    elev_min = float(np.min(valid_data))
    elev_max = float(np.max(valid_data))
    elev_range = elev_max - elev_min

    print(f"DEM: {width}x{height}, elevation {elev_min:.1f}–{elev_max:.1f} m")

    # Normalize to 0–255
    normalized = np.zeros_like(dem, dtype=np.float64)
    if elev_range > 0:
        normalized[valid] = (dem[valid] - elev_min) / elev_range
    indices = np.clip((normalized * 255).astype(np.int32), 0, 255)

    # Apply colormap
    cmap = build_colormap()
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[..., 0] = cmap[indices, 0]
    rgba[..., 1] = cmap[indices, 1]
    rgba[..., 2] = cmap[indices, 2]
    rgba[..., 3] = np.where(valid, 255, 0).astype(np.uint8)

    # Save PNG (with optional downsampling)
    img = Image.fromarray(rgba, mode="RGBA")
    if max_size and (width > max_size or height > max_size):
        img.thumbnail((max_size, max_size), Image.LANCZOS)
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
        "elevation_min_m": round(elev_min, 1),
        "elevation_max_m": round(elev_max, 1),
        "width": width,
        "height": height,
        "crs_source": str(crs),
    }

    with open(output_meta, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata: {output_meta}")
    print(f"WGS84 bounds: [{lat_min:.6f}, {lon_min:.6f}] → [{lat_max:.6f}, {lon_max:.6f}]")


def main() -> None:
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
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    generate_overlay(args.input, args.output, args.meta, args.max_size)


if __name__ == "__main__":
    main()
