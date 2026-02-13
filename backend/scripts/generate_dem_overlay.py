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
from rasterio.warp import Resampling, calculate_default_transform, reproject

from utils.dem_color import build_colormap, compute_hillshade


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

        dem_raw = src.read(1)
        nodata = src.nodata
        src_transform = src.transform

        # Compute hillshade in source CRS (metric) before reprojection
        hillshade_src = None
        if not no_hillshade:
            # Estimate cellsize from transform (metres)
            cellsize = abs(src_transform.a)
            # Mask nodata for gradient computation
            dem_for_hs = dem_raw.astype(np.float64)
            if nodata is not None:
                dem_for_hs[dem_raw == nodata] = np.nan
            hillshade_src = compute_hillshade(dem_for_hs, cellsize)
            print(f"Hillshade computed (cellsize={cellsize:.2f} m)")

        # Reproject DEM to EPSG:4326 so pixels align with geographic grid
        dst_transform, dst_width, dst_height = calculate_default_transform(
            src_crs, dst_crs, src.width, src.height, *src.bounds
        )

        dem = np.empty((dst_height, dst_width), dtype=dem_raw.dtype)
        reproject(
            source=dem_raw,
            destination=dem,
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
            src_nodata=nodata,
            dst_nodata=nodata,
        )

        # Reproject hillshade to EPSG:4326 too
        hillshade = None
        if hillshade_src is not None:
            hillshade = np.zeros((dst_height, dst_width), dtype=np.float64)
            reproject(
                source=hillshade_src,
                destination=hillshade,
                src_transform=src_transform,
                src_crs=src_crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=Resampling.bilinear,
                src_nodata=np.nan,
                dst_nodata=0.0,
            )

    height, width = dem.shape

    # Create mask for valid data
    valid = dem != nodata if nodata is not None else np.isfinite(dem)

    # Elevation range
    valid_data = dem[valid]
    elev_min = float(np.min(valid_data))
    elev_max = float(np.max(valid_data))
    elev_range = elev_max - elev_min

    print(
        f"DEM reprojected to {dst_crs}: {width}x{height}, "
        f"elevation {elev_min:.1f}–{elev_max:.1f} m"
    )

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

    # Apply hillshade as multiply blend: rgb = rgb * (0.3 + 0.7 * hillshade)
    if hillshade is not None:
        blend_factor = (0.3 + 0.7 * hillshade).astype(np.float64)
        for ch in range(3):
            rgba[..., ch] = np.clip(
                rgba[..., ch].astype(np.float64) * blend_factor, 0, 255
            ).astype(np.uint8)
        print("Hillshade blended with hypsometric ramp")

    # Save PNG (with optional downsampling)
    img = Image.fromarray(rgba, mode="RGBA")
    if max_size and (width > max_size or height > max_size):
        img.thumbnail((max_size, max_size), Image.LANCZOS)
        print(f"Downsampled: {width}x{height} → {img.width}x{img.height}")
    img.save(output_png, optimize=True)
    file_size = Path(output_png).stat().st_size
    print(f"PNG saved: {output_png} ({file_size / 1024:.0f} KB)")

    # Bounds from reprojected transform (already in EPSG:4326)
    lon_min = dst_transform.c
    lat_max = dst_transform.f
    lon_max = lon_min + dst_width * dst_transform.a
    lat_min = lat_max + dst_height * dst_transform.e

    meta = {
        "bounds": [[lat_min, lon_min], [lat_max, lon_max]],
        "elevation_min_m": round(elev_min, 1),
        "elevation_max_m": round(elev_max, 1),
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
