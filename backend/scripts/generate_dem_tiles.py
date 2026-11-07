"""
Generate XYZ tile pyramid from DEM raster for Leaflet L.tileLayer display.

Pipeline (the DEM is read in strips of whole rows, never as a whole):
  1. Summarize the elevations: extremes and the exact 5th-95th percentile of all
     valid cells, the colour range (two reads of a float32 DEM)
  2. Colour the DEM strip by strip in its own CRS: hypsometric palette blended with
     the hillshade, computed at full resolution → RGBA GeoTIFF on disk
  3. Reproject it to EPSG:3857 (Web Mercator) with gdalwarp in bounded memory
  4. Tile: gdal2tiles.py --xyz → {z}/{x}/{y}.png
  5. Write metadata JSON (bounds, zoom range, elevation stats)

The temporary GeoTIFFs (compressed, a few hundred MB for 233 M cells) go to a
temporary directory in ``--work-dir`` (default: the system temporary directory).

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
import time
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from rasterio.io import DatasetReader
from rasterio.warp import calculate_default_transform
from rasterio.windows import Window

from utils.dem_color import (
    HILLSHADE_HALO_ROWS,
    ElevationSummary,
    colorize_elevation,
    read_strips,
    shade_strip,
    strip_rows,
    summarize_elevation,
    valid_elevation,
)

BLOCK_PX = 256
"""Block side of the temporary GeoTIFFs; the coloured strips are whole block rows."""

WARP_MEMORY_MB = 256
"""Working memory of gdalwarp (``-wm``)."""

GTIFF_OPTIONS = {
    "TILED": "YES",
    "COMPRESS": "DEFLATE",
    "PREDICTOR": "2",
    "BIGTIFF": "IF_SAFER",
}
"""Creation options of the temporary GeoTIFFs."""


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
    work_dir: str | None = None,
) -> None:
    """Generate XYZ tile pyramid from DEM raster."""
    dst_crs = "EPSG:3857"
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="dem_tiles_", dir=work_dir) as tmp:
        colored = Path(tmp) / "dem_rgba.tif"
        with rasterio.open(input_path) as src:
            src_crs = src.crs or source_crs
            if src_crs is None:
                print("Error: raster has no CRS. Use --source-crs.", file=sys.stderr)
                sys.exit(1)

            summary = summarize_elevation(src)
            print(
                f"DEM {src.width}x{src.height}, elevation "
                f"{summary.elevation_min_m:.1f}–{summary.elevation_max_m:.1f} m "
                f"(color range p5–p95: {summary.color_min_m:.1f}–"
                f"{summary.color_max_m:.1f} m)"
            )
            # Grid of the DEM in EPSG:3857 at its own resolution (required by
            # gdal2tiles).
            dst_transform, width, height = calculate_default_transform(
                src_crs, dst_crs, src.width, src.height, *src.bounds
            )
            _write_colored(src, src_crs, colored, summary, not no_hillshade)

        mercator = Path(tmp) / "dem_rgba_3857.tif"
        _warp(colored, mercator, dst_crs, dst_transform, width, height)
        colored.unlink()
        tif_size_mb = mercator.stat().st_size / 1024 / 1024
        print(
            f"RGBA GeoTIFF reprojected to {dst_crs}: {width}x{height} "
            f"({tif_size_mb:.1f} MB)"
        )

        cmd = [
            "gdal2tiles.py",
            "--xyz",
            f"--zoom={min_zoom}-{max_zoom}",
            "-r",
            resampling,
            f"--processes={processes}",
            "--exclude",
            str(mercator),
            str(output_path),
        ]
        print(f"Running: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"gdal2tiles.py failed:\n{result.stderr}", file=sys.stderr)
            sys.exit(1)

        if result.stdout:
            print(result.stdout)

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
        "elevation_min_m": round(summary.elevation_min_m, 1),
        "elevation_max_m": round(summary.elevation_max_m, 1),
        "color_min_m": round(summary.color_min_m, 1),
        "color_max_m": round(summary.color_max_m, 1),
        "tile_count": tile_count,
        "total_size_mb": round(total_size / 1024 / 1024, 1),
        "generated_at": int(time.time()),
    }

    Path(output_meta).parent.mkdir(parents=True, exist_ok=True)
    with open(output_meta, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Metadata: {output_meta}")
    print(
        f"WGS84 bounds: [{lat_min:.6f}, {lon_min:.6f}] → [{lat_max:.6f}, {lon_max:.6f}]"
    )


def _write_colored(
    src: DatasetReader,
    src_crs: Any,
    path: Path,
    summary: ElevationSummary,
    hillshade: bool,
) -> None:
    """
    Write the coloured DEM as an RGBA GeoTIFF on its own grid, strip by strip.

    Parameters
    ----------
    src : DatasetReader
        Open DEM.
    src_crs : CRS or str
        CRS of the DEM (its own or the override).
    path : Path
        GeoTIFF to write; band 4 is the alpha (opaque on the valid cells).
    summary : ElevationSummary
        Colour range of the elevations.
    hillshade : bool
        Whether to blend the hillshade into the colours.
    """
    cellsize_m = abs(src.transform.a)
    rows = max(BLOCK_PX, strip_rows(src.width) // BLOCK_PX * BLOCK_PX)
    halo = HILLSHADE_HALO_ROWS if hillshade else 0
    profile = {
        "driver": "GTiff",
        "width": src.width,
        "height": src.height,
        "count": 4,
        "dtype": "uint8",
        "crs": src_crs,
        "transform": src.transform,
        "photometric": "RGB",
        "alpha": "YES",
        "blockxsize": BLOCK_PX,
        "blockysize": BLOCK_PX,
        **GTIFF_OPTIONS,
    }
    with rasterio.open(path, "w", **profile) as dst:
        for strip in read_strips(src, rows, halo):
            valid = valid_elevation(strip.core, src.nodata)
            shade = shade_strip(strip, src.nodata, cellsize_m) if hillshade else None
            rgba = colorize_elevation(
                strip.core, valid, summary.color_min_m, summary.color_max_m, shade
            )
            dst.write(
                np.ascontiguousarray(np.moveaxis(rgba, 2, 0)),
                window=Window(0, strip.row0, src.width, strip.rows),
            )
    if hillshade:
        print(f"Hillshade computed (cellsize={cellsize_m:.2f} m)")
        print("Hillshade blended with hypsometric ramp")


def _warp(
    source: Path,
    target: Path,
    dst_crs: str,
    transform: Affine,
    width: int,
    height: int,
) -> None:
    """Reproject the RGBA GeoTIFF onto the given grid with gdalwarp (bilinear)."""
    west, north = transform.c, transform.f
    east = west + width * transform.a
    south = north + height * transform.e
    cmd = [
        "gdalwarp",
        "-q",
        "-overwrite",
        "-t_srs",
        dst_crs,
        "-te",
        *(repr(value) for value in (west, south, east, north)),
        "-ts",
        str(width),
        str(height),
        "-r",
        "bilinear",
        "-wm",
        str(WARP_MEMORY_MB),
        *(arg for item in GTIFF_OPTIONS.items() for arg in ("-co", "=".join(item))),
        str(source),
        str(target),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"gdalwarp failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    """Run the DEM tile generator."""
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
        "--max-zoom", type=int, default=16, help="Max zoom (default: 16)"
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
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Directory of the temporary GeoTIFFs (default: system temp directory)",
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
        work_dir=args.work_dir,
    )


if __name__ == "__main__":
    main()
