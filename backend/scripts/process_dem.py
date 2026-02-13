"""
Script to process DEM (Digital Elevation Model) and populate flow_network table.

Reads ASCII GRID DEM file or VRT mosaic, computes hydrological parameters
(flow direction, flow accumulation, slope), and loads data into PostgreSQL/PostGIS.

Supports:
- Single ASCII GRID (.asc) files
- VRT mosaics (.vrt) created from multiple tiles
- GeoTIFF (.tif) files

For multi-tile processing, use VRT mosaic to ensure hydrological continuity
across tile boundaries. See utils/raster_utils.py for VRT creation.

Usage
-----
    cd backend
    python -m scripts.process_dem --help
    python -m scripts.process_dem --input ../data/nmt/N-33-131-D-a-3-2.asc

Examples
--------
    # Process single DEM tile
    python -m scripts.process_dem \\
        --input ../data/nmt/N-33-131-D-a-3-2.asc \\
        --stream-threshold 100

    # Process VRT mosaic (multiple tiles)
    python -m scripts.process_dem \\
        --input ../data/nmt/mosaic.vrt \\
        --stream-threshold 100

    # Dry run (only show statistics)
    python -m scripts.process_dem \\
        --input ../data/nmt/N-33-131-D-a-3-2.asc \\
        --dry-run

    # Process with custom batch size
    python -m scripts.process_dem \\
        --input ../data/nmt/N-33-131-D-a-3-2.asc \\
        --batch-size 50000
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
from sqlalchemy import text

# ---- Core module imports ----
from core.db_bulk import (
    create_flow_network_records,
    create_flow_network_tsv,
    insert_catchments,
    insert_records_batch,
    insert_records_batch_tsv,
    insert_stream_segments,
)
from core.hydrology import (
    D8_DIRECTIONS,
    VALID_D8_SET,
    burn_streams_into_dem,
    classify_endorheic_lakes,
    fill_internal_nodata_holes,
    fix_internal_sinks,
    process_hydrology_pyflwdir,
    recompute_flow_accumulation,
)
from core.morphometry_raster import (
    _compute_gradients,
    compute_aspect,
    compute_aspect_from_gradients,
    compute_slope,
    compute_slope_from_gradients,
    compute_strahler_from_fdir,
    compute_strahler_order,
    compute_twi,
)
from core.raster_io import read_ascii_grid, read_raster, save_raster_geotiff
from core.stream_extraction import (
    compute_downstream_links,
    delineate_subcatchments,
    polygonize_subcatchments,
    vectorize_streams,
)

# Re-export all public names for backward compatibility
__all__ = [
    "D8_DIRECTIONS",
    "VALID_D8_SET",
    "burn_streams_into_dem",
    "classify_endorheic_lakes",
    "compute_aspect",
    "compute_downstream_links",
    "compute_slope",
    "compute_strahler_from_fdir",
    "compute_strahler_order",
    "compute_twi",
    "create_flow_network_records",
    "create_flow_network_tsv",
    "delineate_subcatchments",
    "fill_internal_nodata_holes",
    "fix_internal_sinks",
    "insert_catchments",
    "insert_records_batch",
    "insert_records_batch_tsv",
    "insert_stream_segments",
    "main",
    "polygonize_subcatchments",
    "process_dem",
    "process_hydrology_pyflwdir",
    "read_ascii_grid",
    "read_raster",
    "recompute_flow_accumulation",
    "save_raster_geotiff",
    "vectorize_streams",
]

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def process_dem(
    input_path: Path,
    stream_threshold: int = 100,
    batch_size: int = 10000,
    dry_run: bool = False,
    save_intermediates: bool = False,
    output_dir: Path | None = None,
    clear_existing: bool = False,
    burn_streams_path: Path | None = None,
    burn_depth_m: float = 5.0,
    skip_streams_vectorize: bool = False,
    thresholds: list[int] | None = None,
    skip_catchments: bool = False,
) -> dict:
    """
    Process DEM file (ASC, VRT, or GeoTIFF) and load into flow_network table.

    Supports VRT mosaics for multi-tile processing with hydrological continuity
    across tile boundaries.

    Parameters
    ----------
    input_path : Path
        Path to input raster file (.asc, .vrt, or .tif)
    stream_threshold : int
        Flow accumulation threshold for stream identification (used for
        flow_network.is_stream and single-threshold mode)
    batch_size : int
        Database insert batch size (unused with COPY, kept for API compatibility)
    dry_run : bool
        If True, only compute statistics without inserting
    save_intermediates : bool
        If True, save intermediate rasters as GeoTIFF
    output_dir : Path, optional
        Output directory for intermediate files (default: same as input)
    clear_existing : bool
        If True, clear existing data before insert (TRUNCATE).
        Default False to support incremental processing.
    burn_streams_path : Path, optional
        Path to GeoPackage/Shapefile with stream lines for DEM burning
    burn_depth_m : float
        Burn depth in meters (default: 5.0)
    skip_streams_vectorize : bool
        If True, skip stream vectorization (default: False)
    skip_catchments : bool
        If True, skip sub-catchment delineation (default: False)
    thresholds : list[int], optional
        List of FA thresholds in m² for multi-density stream networks.
        If provided, generates separate stream networks per threshold.
        The lowest threshold is used for flow_network.is_stream and strahler_order.

    Returns
    -------
    dict
        Processing statistics including:
        - ncols, nrows, cellsize, total_cells
        - valid_cells, max_accumulation, mean_slope
        - stream_cells, records, inserted
        - burn_cells (if burn_streams_path provided)
    """
    stats = {}

    # Setup output directory for intermediates
    if output_dir is None:
        output_dir = input_path.parent
    output_dir = Path(output_dir)
    base_name = input_path.stem

    # 1. Read DEM (supports ASC, VRT, GeoTIFF)
    suffix = input_path.suffix.lower()
    if suffix in (".vrt", ".tif", ".tiff"):
        dem, metadata = read_raster(input_path)
    else:
        # Fallback to ASCII grid parser for .asc files
        dem, metadata = read_ascii_grid(input_path)

    stats["ncols"] = metadata["ncols"]
    stats["nrows"] = metadata["nrows"]
    stats["cellsize"] = metadata["cellsize"]
    stats["total_cells"] = metadata["ncols"] * metadata["nrows"]

    nodata = metadata["nodata_value"]
    valid_cells = np.sum(dem != nodata)
    stats["valid_cells"] = int(valid_cells)

    # Save original DEM as GeoTIFF
    if save_intermediates:
        save_raster_geotiff(
            dem,
            metadata,
            output_dir / f"{base_name}_01_dem.tif",
            nodata=nodata,
            dtype="float32",
        )

    # 2. Burn streams (optional) — before depression filling
    if burn_streams_path is not None:
        transform = metadata.get("transform")
        if transform is None:
            from rasterio.transform import from_bounds

            xll, yll = metadata["xllcorner"], metadata["yllcorner"]
            nrows, ncols = dem.shape
            cs = metadata["cellsize"]
            transform = from_bounds(
                xll, yll, xll + ncols * cs, yll + nrows * cs, ncols, nrows
            )
        dem, burn_diag = burn_streams_into_dem(
            dem, transform, burn_streams_path, burn_depth_m, nodata
        )
        stats["burn_cells"] = burn_diag["cells_burned"]
        if save_intermediates:
            save_raster_geotiff(
                dem,
                metadata,
                output_dir / f"{base_name}_02a_burned.tif",
                nodata=nodata,
                dtype="float32",
            )

    # 2b. Classify endorheic lakes and compute drain points (optional)
    drain_points = None
    if burn_streams_path is not None:
        transform_for_lakes = metadata.get("transform")
        if transform_for_lakes is None:
            from rasterio.transform import from_bounds as _from_bounds

            _xll, _yll = metadata["xllcorner"], metadata["yllcorner"]
            _nr, _nc = dem.shape
            _cs = metadata["cellsize"]
            transform_for_lakes = _from_bounds(
                _xll, _yll, _xll + _nc * _cs, _yll + _nr * _cs, _nc, _nr
            )
        drain_points, drain_diag = classify_endorheic_lakes(
            dem, transform_for_lakes, burn_streams_path, nodata
        )
        stats["endorheic_lakes"] = drain_diag["endorheic"]
        stats["drain_points"] = len(drain_points)

    # 3-5. Process hydrology using pyflwdir (fill depressions, flow dir, accumulation)
    # Note: Migrated from pysheds to pyflwdir (Deltares) — fewer deps, no temp files
    filled_dem, fdir, acc, d8_fdir = process_hydrology_pyflwdir(
        dem, metadata, drain_points=drain_points
    )
    stats["max_accumulation"] = int(acc.max())

    # Build FlwdirRaster once for reuse (subcatchments, potentially strahler)
    import pyflwdir

    transform = metadata.get("transform")
    if transform is None:
        from rasterio.transform import from_bounds

        xll, yll = metadata["xllcorner"], metadata["yllcorner"]
        nrows, ncols = dem.shape
        cs = metadata["cellsize"]
        transform = from_bounds(
            xll, yll, xll + ncols * cs, yll + nrows * cs, ncols, nrows
        )
    flw = pyflwdir.from_array(d8_fdir, ftype="d8", transform=transform, latlon=False)

    if save_intermediates:
        save_raster_geotiff(
            filled_dem,
            metadata,
            output_dir / f"{base_name}_02_filled.tif",
            nodata=nodata,
            dtype="float32",
        )
        save_raster_geotiff(
            fdir,
            metadata,
            output_dir / f"{base_name}_03_flowdir.tif",
            nodata=0,
            dtype="int16",
        )
        save_raster_geotiff(
            acc,
            metadata,
            output_dir / f"{base_name}_04_flowacc.tif",
            nodata=0,
            dtype="int32",
        )

    # 5. Compute slope and aspect (shared Sobel gradients)
    logger.info("Computing slope and aspect (shared gradients)...")
    dx, dy = _compute_gradients(filled_dem, metadata["cellsize"], nodata)
    slope = compute_slope_from_gradients(dx, dy)
    logger.info(f"Slope computed (range: {slope.min():.1f}% - {slope.max():.1f}%)")
    stats["mean_slope"] = float(np.mean(slope[dem != nodata]))

    if save_intermediates:
        save_raster_geotiff(
            slope,
            metadata,
            output_dir / f"{base_name}_05_slope.tif",
            nodata=-1,
            dtype="float32",
        )

    aspect = compute_aspect_from_gradients(dx, dy)
    valid_aspect = aspect[aspect >= 0]
    if len(valid_aspect) > 0:
        logger.info(
            f"Aspect computed "
            f"(range: {valid_aspect.min():.1f}° - "
            f"{valid_aspect.max():.1f}°)"
        )
    del dx, dy  # Free gradient memory

    if save_intermediates:
        save_raster_geotiff(
            aspect,
            metadata,
            output_dir / f"{base_name}_09_aspect.tif",
            nodata=-1,
            dtype="float32",
        )

    # Determine thresholds for multi-density stream networks
    cell_area = metadata["cellsize"] * metadata["cellsize"]
    DEFAULT_THRESHOLDS_M2 = [100, 1000, 10000, 100000]

    if thresholds:
        threshold_list_m2 = sorted(thresholds)
    else:
        threshold_list_m2 = sorted(DEFAULT_THRESHOLDS_M2)

    logger.info(f"Cell size: {metadata['cellsize']}m, cell area: {cell_area} m²")
    for t_m2 in threshold_list_m2:
        t_cells = max(1, int(t_m2 / cell_area))
        logger.info(f"  Threshold {t_m2} m² = {t_cells} cells")

    # Use lowest threshold for flow_network (most detailed network)
    lowest_threshold_cells = max(1, int(threshold_list_m2[0] / cell_area))

    # 5c. Compute Strahler stream order via pyflwdir (lowest threshold)
    strahler = compute_strahler_from_fdir(
        d8_fdir, acc, metadata, lowest_threshold_cells
    )

    if save_intermediates:
        save_raster_geotiff(
            strahler,
            metadata,
            output_dir / f"{base_name}_07_stream_order.tif",
            nodata=0,
            dtype="uint8",
        )

    # 5d. Compute TWI
    twi = compute_twi(acc, slope, metadata["cellsize"], nodata_acc=0)

    if save_intermediates:
        save_raster_geotiff(
            twi,
            metadata,
            output_dir / f"{base_name}_08_twi.tif",
            nodata=-9999,
            dtype="float32",
        )

    # 6. Create stream mask (lowest threshold)
    stream_mask = (acc >= lowest_threshold_cells).astype(np.uint8)
    if save_intermediates:
        save_raster_geotiff(
            stream_mask,
            metadata,
            output_dir / f"{base_name}_06_streams.tif",
            nodata=255,
            dtype="uint8",
        )

    # 7. Create flow_network TSV (vectorized numpy — ~5s vs ~120s)
    tsv_buffer, n_records, n_stream = create_flow_network_tsv(
        filled_dem,
        fdir,
        acc,
        slope,
        metadata,
        lowest_threshold_cells,
        strahler=strahler,
    )
    stats["records"] = n_records
    stats["stream_cells"] = n_stream

    # 7b. Vectorize streams per threshold
    all_stream_segments = {}  # threshold_m2 → segments
    all_catchment_data = {}  # threshold_m2 → catchments
    if not skip_streams_vectorize:
        for threshold_m2 in threshold_list_m2:
            threshold_cells = max(1, int(threshold_m2 / cell_area))
            logger.info(
                f"--- Vectorizing streams for threshold "
                f"{threshold_m2} m² ({threshold_cells} cells) ---"
            )

            # Compute Strahler for this threshold
            if threshold_cells == lowest_threshold_cells:
                strahler_t = strahler
            else:
                strahler_t = compute_strahler_from_fdir(
                    d8_fdir, acc, metadata, threshold_cells
                )

            if save_intermediates and threshold_cells != lowest_threshold_cells:
                save_raster_geotiff(
                    strahler_t,
                    metadata,
                    output_dir / f"{base_name}_07_stream_order_{threshold_m2}.tif",
                    nodata=0,
                    dtype="uint8",
                )

            # Allocate label raster for sub-catchment delineation
            label_raster = None
            if not skip_catchments:
                label_raster = np.zeros_like(filled_dem, dtype=np.int32)

            segments = vectorize_streams(
                filled_dem,
                fdir,
                acc,
                slope,
                strahler_t,
                metadata,
                threshold_cells,
                label_raster_out=label_raster,
            )
            all_stream_segments[threshold_m2] = segments

            # Delineate and polygonize sub-catchments
            if not skip_catchments and label_raster is not None:
                delineate_subcatchments(flw, label_raster, filled_dem, nodata)

                # Compute downstream links for catchment graph
                compute_downstream_links(
                    segments,
                    label_raster,
                    fdir,
                    metadata,
                )

                if save_intermediates:
                    save_raster_geotiff(
                        label_raster,
                        metadata,
                        output_dir / f"{base_name}_10_subcatchments_{threshold_m2}.tif",
                        nodata=0,
                        dtype="int32",
                    )

                catchments = polygonize_subcatchments(
                    label_raster,
                    filled_dem,
                    slope,
                    metadata,
                    segments,
                )
                all_catchment_data[threshold_m2] = catchments

            logger.info(f"  Threshold {threshold_m2} m²: {len(segments)} segments")

        total_segments = sum(len(s) for s in all_stream_segments.values())
        stats["stream_segments"] = total_segments
        stats["stream_thresholds"] = {t: len(s) for t, s in all_stream_segments.items()}
        if all_catchment_data:
            stats["catchment_thresholds"] = {
                t: len(c) for t, c in all_catchment_data.items()
            }

    # 8. Insert into database
    if not dry_run:
        from core.database import get_db_session

        with get_db_session() as db:
            if clear_existing:
                logger.info("Clearing existing flow_network data...")
                db.execute(text("TRUNCATE TABLE flow_network CASCADE"))
                db.execute(
                    text("DELETE FROM stream_network WHERE source = 'DEM_DERIVED'")
                )
                db.execute(text("DELETE FROM stream_catchments"))
                db.commit()

            # TSV fast path — COPY directly from buffer
            inserted = insert_records_batch_tsv(
                db,
                tsv_buffer,
                n_records,
                table_empty=clear_existing,
            )
            stats["inserted"] = inserted

            # Insert stream segments per threshold
            total_seg_inserted = 0
            for threshold_m2, segments in all_stream_segments.items():
                if segments:
                    seg_inserted = insert_stream_segments(
                        db,
                        segments,
                        threshold_m2=threshold_m2,
                    )
                    total_seg_inserted += seg_inserted
            if total_seg_inserted > 0:
                stats["stream_segments_inserted"] = total_seg_inserted

            # Insert sub-catchments per threshold
            total_catch_inserted = 0
            for threshold_m2, catchments in all_catchment_data.items():
                if catchments:
                    catch_inserted = insert_catchments(
                        db,
                        catchments,
                        threshold_m2=threshold_m2,
                    )
                    total_catch_inserted += catch_inserted
            if total_catch_inserted > 0:
                stats["catchments_inserted"] = total_catch_inserted

            # Validate stream vs catchment counts per threshold
            for threshold_m2 in all_stream_segments:
                stream_count = len(all_stream_segments.get(threshold_m2, []))
                catchment_count = len(all_catchment_data.get(threshold_m2, []))
                if stream_count != catchment_count:
                    logger.warning(
                        f"Stream/catchment mismatch for threshold={threshold_m2} m²: "
                        f"{stream_count} streams vs {catchment_count} catchments"
                    )
    else:
        logger.info("Dry run - skipping database insert")
        stats["inserted"] = 0

    return stats


def main():
    """Main entry point for DEM processing script."""
    parser = argparse.ArgumentParser(
        description="Process DEM and populate flow_network table",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        required=True,
        help="Path to input ASCII GRID (.asc) file",
    )
    parser.add_argument(
        "--stream-threshold",
        type=int,
        default=100,
        help=(
            "Flow accumulation threshold in cells (default: 100). "
            "Ignored when --thresholds is specified."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10000,
        help="Database insert batch size (default: 10000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only compute statistics without database insert",
    )
    parser.add_argument(
        "--save-intermediates",
        "-s",
        action="store_true",
        help="Save intermediate rasters as GeoTIFF (for QGIS verification)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Output directory for intermediate files (default: same as input)",
    )
    parser.add_argument(
        "--clear-existing",
        action="store_true",
        help="Clear existing flow_network data before insert (TRUNCATE)",
    )
    parser.add_argument(
        "--burn-streams",
        type=str,
        default=None,
        help="Path to GeoPackage/Shapefile with stream lines for DEM burning",
    )
    parser.add_argument(
        "--burn-depth",
        type=float,
        default=5.0,
        help="Burn depth in meters (default: 5.0)",
    )
    parser.add_argument(
        "--skip-streams-vectorize",
        action="store_true",
        help="Skip stream vectorization (useful without DB)",
    )
    parser.add_argument(
        "--skip-catchments",
        action="store_true",
        help="Skip sub-catchment delineation (default: generate catchments)",
    )
    parser.add_argument(
        "--thresholds",
        type=str,
        default=None,
        help=(
            "Comma-separated FA thresholds in m² for multi-density "
            "stream networks (e.g. 100,1000,10000,100000). "
            "Overrides --stream-threshold for vectorization."
        ),
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir) if args.output_dir else None
    burn_streams_path = Path(args.burn_streams) if args.burn_streams else None

    # Parse thresholds
    threshold_list = None
    if args.thresholds:
        threshold_list = [int(t.strip()) for t in args.thresholds.split(",")]

    logger.info("=" * 60)
    logger.info("DEM Processing Script")
    logger.info("=" * 60)
    logger.info(f"Input: {input_path}")
    logger.info(f"Stream threshold: {args.stream_threshold}")
    if threshold_list:
        logger.info(f"Multi-threshold FA: {threshold_list} m²")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Save intermediates: {args.save_intermediates}")
    logger.info(f"Clear existing: {args.clear_existing}")
    if burn_streams_path:
        logger.info(f"Burn streams: {burn_streams_path} (depth={args.burn_depth}m)")
    if output_dir:
        logger.info(f"Output dir: {output_dir}")
    logger.info("=" * 60)

    start_time = time.time()

    try:
        stats = process_dem(
            input_path,
            stream_threshold=args.stream_threshold,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            save_intermediates=args.save_intermediates,
            output_dir=output_dir,
            clear_existing=args.clear_existing,
            burn_streams_path=burn_streams_path,
            burn_depth_m=args.burn_depth,
            skip_streams_vectorize=args.skip_streams_vectorize,
            thresholds=threshold_list,
            skip_catchments=args.skip_catchments,
        )
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        raise

    elapsed = time.time() - start_time

    logger.info("=" * 60)
    logger.info("Processing complete!")
    logger.info(f"  Grid size: {stats['ncols']} x {stats['nrows']}")
    logger.info(f"  Cell size: {stats['cellsize']} m")
    logger.info(f"  Total cells: {stats['total_cells']:,}")
    logger.info(f"  Valid cells: {stats['valid_cells']:,}")
    logger.info(f"  Max accumulation: {stats['max_accumulation']:,}")
    logger.info(f"  Mean slope: {stats['mean_slope']:.1f}%")
    if "burn_cells" in stats:
        logger.info(f"  Burned cells: {stats['burn_cells']:,}")
    if "endorheic_lakes" in stats:
        logger.info(
            f"  Endorheic lakes: {stats['endorheic_lakes']}, "
            f"drain points: {stats.get('drain_points', 0)}"
        )
    logger.info(f"  Stream cells: {stats['stream_cells']:,}")
    if "stream_segments" in stats:
        logger.info(f"  Stream segments: {stats['stream_segments']:,}")
    if "stream_thresholds" in stats:
        for t, count in stats["stream_thresholds"].items():
            logger.info(f"    Threshold {t} m²: {count} segments")
    logger.info(f"  Records created: {stats['records']:,}")
    logger.info(f"  Records inserted: {stats['inserted']:,}")
    if "stream_segments_inserted" in stats:
        logger.info(
            f"  Stream segments inserted: {stats['stream_segments_inserted']:,}"
        )
    if "catchment_thresholds" in stats:
        for t, count in stats["catchment_thresholds"].items():
            logger.info(f"    Sub-catchments {t} m²: {count}")
    if "catchments_inserted" in stats:
        logger.info(f"  Sub-catchments inserted: {stats['catchments_inserted']:,}")
    logger.info(f"  Time elapsed: {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
