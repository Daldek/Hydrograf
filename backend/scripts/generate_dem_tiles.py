"""
Generate XYZ tile pyramid from DEM raster for Leaflet L.tileLayer display.

Pipeline:
  1. Read DEM, compute hillshade in source CRS (metric)
  2. Reproject DEM + hillshade to EPSG:3857 (Web Mercator)
  3. Colorize: elevation → hypsometric palette + hillshade blend → RGBA GeoTIFF
  4. Tile: gdal2tiles.py --xyz → {z}/{x}/{y}.png
  5. Write metadata JSON (bounds, zoom range, elevation stats)

Usage:
    python -m scripts.generate_dem_tiles \
        --input ../data/e2e_test/dem_mosaic.vrt \
        --output-dir ../frontend/data/dem_tiles \
        --meta ../frontend/data/dem_tiles.json \
        --source-crs EPSG:2180
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, calculate_default_transform, reproject

from utils.dem_color import build_colormap, compute_hillshade


def generate_tiles(
    input_path: str,
    output_dir: str,
    output_meta: str,
    source_crs: str | None = None,
    min_zoom: int = 8,
    max_zoom: int = 18,
    resampling: str = "near",
    processes: int = 4,
    no_hillshade: bool = False,
) -> None:
    """Generate XYZ tile pyramid from DEM raster."""
    dst_crs = "EPSG:3857"

    with rasterio.open(input_path) as src:
        src_crs = src.crs or source_crs
        if src_crs is None:
            print("Error: raster has no CRS. Use --source-crs.", file=sys.stderr)
            sys.exit(1)

        dem_raw = src.read(1)
        nodata = src.nodata
        src_transform = src.transform
        src_bounds = src.bounds

        # Compute hillshade in source CRS (metric) before reprojection
        hillshade_src = None
        if not no_hillshade:
            cellsize = abs(src_transform.a)
            dem_for_hs = dem_raw.astype(np.float64)
            if nodata is not None:
                dem_for_hs[dem_raw == nodata] = np.nan
            hillshade_src = compute_hillshade(dem_for_hs, cellsize)
            print(f"Hillshade computed (cellsize={cellsize:.2f} m)")

        # Reproject DEM to EPSG:3857 (Web Mercator — required by gdal2tiles)
        dst_transform, dst_width, dst_height = calculate_default_transform(
            src_crs, dst_crs, src.width, src.height, *src_bounds
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

        # Reproject hillshade
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
    valid = dem != nodata if nodata is not None else np.isfinite(dem)

    valid_data = dem[valid]
    elev_min = float(np.min(valid_data))
    elev_max = float(np.max(valid_data))
    elev_range = elev_max - elev_min

    print(
        f"DEM reprojected to {dst_crs}: {width}x{height}, "
        f"elevation {elev_min:.1f}–{elev_max:.1f} m"
    )

    # Normalize to 0–255 and apply colormap
    normalized = np.zeros_like(dem, dtype=np.float64)
    if elev_range > 0:
        normalized[valid] = (dem[valid] - elev_min) / elev_range
    indices = np.clip((normalized * 255).astype(np.int32), 0, 255)

    cmap = build_colormap()
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[..., 0] = cmap[indices, 0]
    rgba[..., 1] = cmap[indices, 1]
    rgba[..., 2] = cmap[indices, 2]
    rgba[..., 3] = np.where(valid, 255, 0).astype(np.uint8)

    # Apply hillshade blend: rgb = rgb * (0.3 + 0.7 * hillshade)
    if hillshade is not None:
        blend_factor = (0.3 + 0.7 * hillshade).astype(np.float64)
        for ch in range(3):
            rgba[..., ch] = np.clip(
                rgba[..., ch].astype(np.float64) * blend_factor, 0, 255
            ).astype(np.uint8)
        print("Hillshade blended with hypsometric ramp")

    # Write RGBA GeoTIFF in EPSG:3857 (temp file for gdal2tiles)
    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
        tmp_tif = tmp.name

    # Bands: R, G, B, A (band-interleaved)
    with rasterio.open(
        tmp_tif,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=4,
        dtype="uint8",
        crs=dst_crs,
        transform=dst_transform,
    ) as dst:
        for band_idx in range(4):
            dst.write(rgba[..., band_idx], band_idx + 1)

    tif_size_mb = Path(tmp_tif).stat().st_size / 1024 / 1024
    print(f"RGBA GeoTIFF written: {tmp_tif} ({tif_size_mb:.1f} MB)")

    # Run gdal2tiles.py
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    cmd = [
        "gdal2tiles.py",
        "--xyz",
        f"--zoom={min_zoom}-{max_zoom}",
        "-r",
        resampling,
        f"--processes={processes}",
        "--exclude",
        tmp_tif,
        str(output_path),
    ]
    print(f"Running: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"gdal2tiles.py failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    if result.stdout:
        print(result.stdout)

    # Clean up temp file
    Path(tmp_tif).unlink(missing_ok=True)

    # Count generated tiles
    tile_count = sum(1 for _ in output_path.rglob("*.png"))
    total_size = sum(f.stat().st_size for f in output_path.rglob("*.png"))
    print(f"Tiles generated: {tile_count} files, {total_size / 1024 / 1024:.1f} MB")

    # Compute WGS84 bounds for metadata (Leaflet uses lat/lng)
    wgs84_transform, wgs84_w, wgs84_h = calculate_default_transform(
        dst_crs,
        "EPSG:4326",
        width,
        height,
        dst_transform.c,
        dst_transform.f + height * dst_transform.e,
        dst_transform.c + width * dst_transform.a,
        dst_transform.f,
    )
    lon_min = wgs84_transform.c
    lat_max = wgs84_transform.f
    lon_max = lon_min + wgs84_w * wgs84_transform.a
    lat_min = lat_max + wgs84_h * wgs84_transform.e

    meta = {
        "bounds": [
            [round(lat_min, 6), round(lon_min, 6)],
            [round(lat_max, 6), round(lon_max, 6)],
        ],
        "min_zoom": min_zoom,
        "max_zoom": max_zoom,
        "elevation_min_m": round(elev_min, 1),
        "elevation_max_m": round(elev_max, 1),
        "tile_count": tile_count,
        "total_size_mb": round(total_size / 1024 / 1024, 1),
    }

    Path(output_meta).parent.mkdir(parents=True, exist_ok=True)
    with open(output_meta, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata: {output_meta}")
    print(
        f"WGS84 bounds: [{lat_min:.6f}, {lon_min:.6f}] → [{lat_max:.6f}, {lon_max:.6f}]"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate XYZ tile pyramid from DEM raster"
    )
    parser.add_argument("--input", required=True, help="Input DEM raster (GeoTIFF/VRT)")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Output directory for tiles",
    )
    parser.add_argument("--meta", required=True, help="Output metadata JSON path")
    parser.add_argument(
        "--source-crs",
        default=None,
        help="Source CRS override (e.g. EPSG:2180) if raster has no CRS metadata",
    )
    parser.add_argument("--min-zoom", type=int, default=8, help="Min zoom (default: 8)")
    parser.add_argument(
        "--max-zoom", type=int, default=18, help="Max zoom (default: 18)"
    )
    parser.add_argument(
        "--resampling",
        default="near",
        help="Resampling method for gdal2tiles (default: near)",
    )
    parser.add_argument(
        "--processes",
        type=int,
        default=4,
        help="Parallel processes (default: 4)",
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

    generate_tiles(
        input_path=args.input,
        output_dir=args.output_dir,
        output_meta=args.meta,
        source_crs=args.source_crs,
        min_zoom=args.min_zoom,
        max_zoom=args.max_zoom,
        resampling=args.resampling,
        processes=args.processes,
        no_hillshade=args.no_hillshade,
    )


if __name__ == "__main__":
    main()
