"""
Import DEM GeoTIFF into PostGIS as tiled raster.

Creates `dem_raster` table with 256x256 raster tiles for XYZ tile serving.

Usage:
    cd backend
    .venv/bin/python -m scripts.import_dem_raster \
        --input ../data/e2e_test/intermediates/N-33-131-C-b-2-3_01_dem.tif
"""

import argparse
import sys
import time
from io import BytesIO
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.windows import Window
from sqlalchemy import text

from core.database import get_db_session

TILE_SIZE = 256


def create_table(db) -> None:
    """Create dem_raster table if not exists."""
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS dem_raster (
            rid SERIAL PRIMARY KEY,
            rast raster
        )
    """))
    db.execute(text("TRUNCATE dem_raster"))
    db.commit()


def create_indexes(db) -> None:
    """Create spatial index on dem_raster."""
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_dem_raster_st_convexhull
        ON dem_raster USING gist (ST_ConvexHull(rast))
    """))
    db.execute(text("SELECT AddRasterConstraints('dem_raster', 'rast')"))
    db.commit()


def tile_to_geotiff_bytes(data: np.ndarray, transform, crs, nodata: float) -> bytes:
    """Convert a 2D numpy array to in-memory GeoTIFF bytes."""
    buf = BytesIO()
    with rasterio.open(
        buf, "w", driver="GTiff",
        width=data.shape[1], height=data.shape[0],
        count=1, dtype=data.dtype,
        crs=crs, transform=transform,
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)
    return buf.getvalue()


def import_dem(input_path: str) -> None:
    """Import DEM raster into PostGIS as 256x256 tiles."""
    t0 = time.time()

    with rasterio.open(input_path) as src:
        full_data = src.read(1)
        full_transform = src.transform
        crs = src.crs
        nodata = src.nodata if src.nodata is not None else -9999
        height, width = full_data.shape

    print(f"DEM: {width}x{height}, CRS: {crs}")
    print(f"Elevation: {np.nanmin(full_data[full_data != nodata]):.1f}"
          f"–{np.nanmax(full_data[full_data != nodata]):.1f} m")

    # Calculate tile grid
    n_tiles_x = (width + TILE_SIZE - 1) // TILE_SIZE
    n_tiles_y = (height + TILE_SIZE - 1) // TILE_SIZE
    total_tiles = n_tiles_x * n_tiles_y
    print(f"Tiles: {n_tiles_x}x{n_tiles_y} = {total_tiles}")

    with get_db_session() as db:
        create_table(db)

        inserted = 0
        for ty in range(n_tiles_y):
            for tx in range(n_tiles_x):
                # Window in source raster
                col_off = tx * TILE_SIZE
                row_off = ty * TILE_SIZE
                win_width = min(TILE_SIZE, width - col_off)
                win_height = min(TILE_SIZE, height - row_off)

                window = Window(col_off, row_off, win_width, win_height)
                tile_data = full_data[row_off:row_off + win_height,
                                      col_off:col_off + win_width]

                # Skip tiles that are all nodata
                valid = tile_data != nodata
                if not np.any(valid):
                    continue

                # Pad to full tile size if needed
                if win_width < TILE_SIZE or win_height < TILE_SIZE:
                    padded = np.full((TILE_SIZE, TILE_SIZE), nodata,
                                    dtype=tile_data.dtype)
                    padded[:win_height, :win_width] = tile_data
                    tile_data = padded

                # Compute transform for this tile
                tile_transform = rasterio.transform.from_origin(
                    full_transform.c + col_off * full_transform.a,
                    full_transform.f + row_off * full_transform.e,
                    abs(full_transform.a),
                    abs(full_transform.e),
                )

                # Convert to GeoTIFF bytes
                tiff_bytes = tile_to_geotiff_bytes(
                    tile_data, tile_transform, crs, nodata
                )

                # Insert into PostGIS
                db.execute(
                    text("INSERT INTO dem_raster (rast) "
                         "VALUES (ST_FromGDALRaster(:data))"),
                    {"data": tiff_bytes},
                )
                inserted += 1

        create_indexes(db)

    elapsed = time.time() - t0
    print(f"Imported {inserted}/{total_tiles} tiles in {elapsed:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import DEM into PostGIS raster")
    parser.add_argument("--input", required=True, help="Input DEM raster path")
    args = parser.parse_args()

    if not Path(args.input).exists():
        print(f"Error: file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    import_dem(args.input)


if __name__ == "__main__":
    main()
