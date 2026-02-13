"""
Generate depression (blue spot) data from DEM difference and insert into PostGIS.

Computes terrain depressions as the difference between filled and original DEM,
vectorizes connected components, inserts geometry + metrics into depressions table,
and optionally generates a PNG overlay for Leaflet display.

Usage:
    python -m scripts.generate_depressions \
        --dem ../data/nmt/dem.tif --filled ../data/nmt/dem_filled.tif

    python -m scripts.generate_depressions \
        --dem ../data/nmt/dem.tif --filled ../data/nmt/dem_filled.tif \
        --output-png ../frontend/data/depressions.png \
        --output-meta ../frontend/data/depressions.json
"""

import argparse
import io
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.features import shapes
from rasterio.warp import Resampling, calculate_default_transform, reproject
from scipy.ndimage import label
from shapely.geometry import shape

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Depth color ramp: light blue (shallow) → dark blue (deep)
DEPTH_COLORS = [
    (0.0, 0xBB, 0xDE, 0xFB),  # #BBDEFB — very shallow
    (0.2, 0x64, 0xB5, 0xF6),  # #64B5F6
    (0.5, 0x21, 0x96, 0xF3),  # #2196F3
    (0.8, 0x0D, 0x47, 0xA1),  # #0D47A1
    (1.0, 0x01, 0x27, 0x64),  # #012764 — deepest
]


def build_depth_colormap(n_steps: int = 256) -> np.ndarray:
    """Build a 256x3 uint8 colormap for depth values."""
    cmap = np.zeros((n_steps, 3), dtype=np.uint8)
    positions = [s[0] for s in DEPTH_COLORS]
    colors = np.array([[s[1], s[2], s[3]] for s in DEPTH_COLORS], dtype=np.float64)

    for i in range(n_steps):
        t = i / (n_steps - 1) if n_steps > 1 else 0
        for k in range(len(positions) - 1):
            if positions[k] <= t <= positions[k + 1]:
                local_t = (t - positions[k]) / (positions[k + 1] - positions[k])
                rgb = colors[k] * (1 - local_t) + colors[k + 1] * local_t
                cmap[i] = np.clip(rgb, 0, 255).astype(np.uint8)
                break
    return cmap


def compute_depressions(
    dem_path: str,
    filled_path: str,
    min_depth_m: float = 0.001,
) -> tuple[list[dict], np.ndarray, dict]:
    """
    Compute terrain depressions from DEM difference.

    Parameters
    ----------
    dem_path : str
        Path to original DEM raster
    filled_path : str
        Path to filled DEM raster
    min_depth_m : float
        Minimum depth to consider as depression (default: 1mm)

    Returns
    -------
    tuple[list[dict], np.ndarray, dict]
        - List of depression dicts (wkt, volume_m3, area_m2, max_depth_m, mean_depth_m)
        - Depth array (for overlay generation)
        - Raster metadata (transform, crs, shape)
    """
    with rasterio.open(dem_path) as src_dem:
        dem = src_dem.read(1).astype(np.float64)
        nodata_dem = src_dem.nodata
        transform = src_dem.transform
        crs = src_dem.crs
        cellsize = abs(transform.a)

    with rasterio.open(filled_path) as src_filled:
        filled = src_filled.read(1).astype(np.float64)
        nodata_filled = src_filled.nodata

    # Compute depth = filled - original
    depth = filled - dem

    # Mask nodata and noise
    if nodata_dem is not None:
        depth[dem == nodata_dem] = 0
    if nodata_filled is not None:
        depth[filled == nodata_filled] = 0
    depth[depth < min_depth_m] = 0

    depression_mask = depth > 0
    cell_area = cellsize * cellsize

    total_depression_pixels = int(np.sum(depression_mask))
    logger.info(
        f"Depression pixels: {total_depression_pixels:,} "
        f"(depth range: {depth[depression_mask].min():.3f}–"
        f"{depth[depression_mask].max():.3f} m)"
        if total_depression_pixels > 0
        else "No depressions found"
    )

    if total_depression_pixels == 0:
        return [], depth, {"transform": transform, "crs": crs, "shape": dem.shape}

    # Label connected components
    labeled, n_features = label(depression_mask)
    logger.info(f"Found {n_features} connected depression regions")

    # Pre-compute zonal statistics in one pass using bincount (O(M) not O(n*M))
    from core.zonal_stats import zonal_bincount, zonal_max

    counts = zonal_bincount(labeled, max_label=n_features)
    depth_sum = zonal_bincount(
        labeled,
        weights=depth,
        max_label=n_features,
    )
    max_depths = zonal_max(labeled, depth, n_features)

    logger.info("  Zonal statistics computed (single-pass bincount)")

    # Vectorize and compute metrics per depression
    depressions = []
    for geom_dict, value in shapes(labeled.astype(np.int32), transform=transform):
        if value == 0:
            continue
        depression_id = int(value)

        n_cells = int(counts[depression_id])
        area_m2 = n_cells * cell_area
        volume_m3 = float(depth_sum[depression_id]) * cell_area
        max_depth_m = float(max_depths[depression_id - 1])
        mean_depth_m = volume_m3 / area_m2 if area_m2 > 0 else 0

        polygon = shape(geom_dict)
        wkt = polygon.wkt

        depressions.append(
            {
                "wkt": wkt,
                "volume_m3": round(volume_m3, 4),
                "area_m2": round(area_m2, 4),
                "max_depth_m": round(max_depth_m, 4),
                "mean_depth_m": round(mean_depth_m, 4),
            }
        )

    logger.info(
        f"Vectorized {len(depressions)} depressions "
        f"(total volume: {sum(d['volume_m3'] for d in depressions):.1f} m³, "
        f"max depth: {max(d['max_depth_m'] for d in depressions):.3f} m)"
    )

    return depressions, depth, {"transform": transform, "crs": crs, "shape": dem.shape}


def insert_depressions(db_session, depressions: list[dict], srid: int = 2180) -> int:
    """
    Insert depressions into PostGIS using COPY bulk loading.

    Parameters
    ----------
    db_session : Session
        SQLAlchemy database session
    depressions : list[dict]
        List of depression dicts from compute_depressions()
    srid : int
        SRID of the geometry (default: 2180)

    Returns
    -------
    int
        Number of depressions inserted
    """
    if not depressions:
        logger.info("No depressions to insert")
        return 0

    logger.info(f"Inserting {len(depressions)} depressions into database...")

    raw_conn = db_session.connection().connection
    cursor = raw_conn.cursor()

    # Bulk import can take minutes — disable statement_timeout
    cursor.execute("SET statement_timeout = 0")
    raw_conn.commit()

    # Create temp table (drop first for safety)
    cursor.execute("DROP TABLE IF EXISTS temp_depressions_import")
    cursor.execute("""
        CREATE TEMP TABLE temp_depressions_import (
            wkt TEXT,
            volume_m3 FLOAT,
            area_m2 FLOAT,
            max_depth_m FLOAT,
            mean_depth_m FLOAT
        )
    """)

    # Build TSV
    tsv_buffer = io.StringIO()
    for dep in depressions:
        tsv_buffer.write(
            f"{dep['wkt']}\t{dep['volume_m3']}\t{dep['area_m2']}\t"
            f"{dep['max_depth_m']}\t{dep['mean_depth_m']}\n"
        )

    tsv_buffer.seek(0)

    cursor.copy_expert(
        "COPY temp_depressions_import FROM STDIN"
        " WITH (FORMAT text, DELIMITER E'\\t', NULL '')",
        tsv_buffer,
    )

    # Insert with geometry construction
    cursor.execute(f"""
        INSERT INTO depressions (geom, volume_m3, area_m2, max_depth_m, mean_depth_m)
        SELECT
            ST_SetSRID(ST_GeomFromText(wkt), {srid}),
            volume_m3, area_m2, max_depth_m, mean_depth_m
        FROM temp_depressions_import
    """)

    total = cursor.rowcount
    raw_conn.commit()
    logger.info(f"  Inserted {total} depressions")

    return total


def generate_overlay(
    depth: np.ndarray,
    raster_meta: dict,
    output_png: str,
    output_meta: str,
    max_size: int = 1024,
) -> None:
    """
    Generate depression depth overlay as PNG + JSON metadata.

    Parameters
    ----------
    depth : np.ndarray
        Depth array from compute_depressions()
    raster_meta : dict
        Raster metadata with transform, crs, shape
    output_png : str
        Output PNG file path
    output_meta : str
        Output JSON metadata file path
    max_size : int
        Max image dimension in pixels
    """
    src_transform = raster_meta["transform"]
    src_crs = raster_meta["crs"]
    dst_crs = "EPSG:4326"

    src_height, src_width = raster_meta["shape"]

    # Reproject to EPSG:4326
    dst_transform, dst_width, dst_height = calculate_default_transform(
        src_crs,
        dst_crs,
        src_width,
        src_height,
        left=src_transform.c,
        bottom=src_transform.f + src_height * src_transform.e,
        right=src_transform.c + src_width * src_transform.a,
        top=src_transform.f,
    )

    depth_reproj = np.zeros((dst_height, dst_width), dtype=np.float64)
    reproject(
        source=depth.astype(np.float64),
        destination=depth_reproj,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        resampling=Resampling.nearest,
        src_nodata=0.0,
        dst_nodata=0.0,
    )

    height, width = depth_reproj.shape
    has_depression = depth_reproj > 0

    if not np.any(has_depression):
        logger.info("No depression pixels for overlay — skipping PNG generation")
        return

    # Normalize depth to 0–255
    max_depth = float(np.max(depth_reproj[has_depression]))
    normalized = np.zeros_like(depth_reproj)
    normalized[has_depression] = depth_reproj[has_depression] / max_depth
    indices = np.clip((normalized * 255).astype(np.int32), 0, 255)

    # Apply colormap
    cmap = build_depth_colormap()
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[..., 0] = cmap[indices, 0]
    rgba[..., 1] = cmap[indices, 1]
    rgba[..., 2] = cmap[indices, 2]
    rgba[..., 3] = np.where(has_depression, 255, 0).astype(np.uint8)

    # Save PNG
    img = Image.fromarray(rgba, mode="RGBA")
    if max_size and (width > max_size or height > max_size):
        img.thumbnail((max_size, max_size), Image.NEAREST)
        logger.info(f"Downsampled: {width}x{height} → {img.width}x{img.height}")
    img.save(output_png, optimize=True)
    file_size = Path(output_png).stat().st_size
    logger.info(f"PNG saved: {output_png} ({file_size / 1024:.0f} KB)")

    # Bounds from reprojected transform
    lon_min = dst_transform.c
    lat_max = dst_transform.f
    lon_max = lon_min + dst_width * dst_transform.a
    lat_min = lat_max + dst_height * dst_transform.e

    meta = {
        "bounds": [[lat_min, lon_min], [lat_max, lon_max]],
        "max_depth_m": round(max_depth, 3),
        "width": img.width,
        "height": img.height,
        "crs_source": str(src_crs),
    }

    with open(output_meta, "w") as f:
        json.dump(meta, f, indent=2)
    logger.info(f"Metadata: {output_meta}")
    logger.info(
        f"WGS84 bounds: [{lat_min:.6f}, {lon_min:.6f}] → [{lat_max:.6f}, {lon_max:.6f}]"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate depressions from DEM and insert into PostGIS"
    )
    parser.add_argument("--dem", required=True, help="Path to original DEM raster")
    parser.add_argument("--filled", required=True, help="Path to filled DEM raster")
    parser.add_argument(
        "--min-depth",
        type=float,
        default=0.001,
        help="Minimum depth in meters (default: 0.001 = 1mm)",
    )
    parser.add_argument(
        "--output-png",
        default=None,
        help="Output PNG path for depression overlay",
    )
    parser.add_argument(
        "--output-meta",
        default=None,
        help="Output JSON metadata path for depression overlay",
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=1024,
        help="Max overlay image dimension in pixels (default: 1024)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute depressions but skip database insert",
    )
    parser.add_argument(
        "--clear-existing",
        action="store_true",
        help="Clear existing depressions before insert (TRUNCATE)",
    )
    args = parser.parse_args()

    for path in [args.dem, args.filled]:
        if not Path(path).exists():
            print(f"Error: file not found: {path}", file=sys.stderr)
            sys.exit(1)

    start_time = time.time()

    # Compute depressions
    depressions, depth, raster_meta = compute_depressions(
        args.dem, args.filled, args.min_depth
    )

    # Insert into database
    if not args.dry_run and depressions:
        from sqlalchemy import text

        from core.database import get_db_session
        from core.db_bulk import override_statement_timeout

        with (
            get_db_session() as db,
            override_statement_timeout(
                db,
                timeout_s=600,
            ),
        ):
            if args.clear_existing:
                logger.info("Clearing existing depressions...")
                db.execute(text("TRUNCATE TABLE depressions"))
                db.commit()

            insert_depressions(db, depressions)
    elif args.dry_run:
        logger.info("Dry run — skipping database insert")

    # Generate overlay if requested
    if args.output_png and args.output_meta:
        generate_overlay(
            depth,
            raster_meta,
            args.output_png,
            args.output_meta,
            args.max_size,
        )

    elapsed = time.time() - start_time
    logger.info(f"Done in {elapsed:.1f}s — {len(depressions)} depressions processed")


if __name__ == "__main__":
    main()
