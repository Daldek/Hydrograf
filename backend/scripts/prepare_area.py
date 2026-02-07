"""
Pipeline script to download and process spatial data for a specified area.

This script combines:
1. Downloading NMT data from GUGiK using Kartograf (multiple tiles)
2. Creating VRT mosaic from downloaded tiles (ensures hydrological continuity)
3. Processing mosaic with pyflwdir (fill depressions, flow direction, accumulation)
4. Loading data into PostgreSQL/PostGIS flow_network table
5. (Optional) Downloading land cover data from BDOT10k/CORINE
6. (Optional) Loading land cover into land_cover table

IMPORTANT: Multiple tiles are merged into a VRT (Virtual Raster) before
hydrological analysis. This ensures correct flow routing across tile
boundaries - water can flow from one tile to another without artifacts.

Requires:
- Kartograf 0.3.0+ for data download
- GDAL for VRT creation (gdalbuildvrt)

Usage
-----
    cd backend
    python -m scripts.prepare_area --help
    python -m scripts.prepare_area --lat 52.23 --lon 21.01 --buffer 5

Examples
--------
    # Full pipeline for area (NMT only)
    python -m scripts.prepare_area \\
        --lat 52.23 --lon 21.01 \\
        --buffer 5

    # With land cover data (BDOT10k)
    python -m scripts.prepare_area \\
        --lat 52.23 --lon 21.01 \\
        --buffer 5 \\
        --with-landcover

    # With custom stream threshold
    python -m scripts.prepare_area \\
        --lat 52.23 --lon 21.01 \\
        --buffer 10 \\
        --stream-threshold 50

    # Keep downloaded files and save intermediates
    python -m scripts.prepare_area \\
        --lat 52.23 --lon 21.01 \\
        --keep-downloads \\
        --save-intermediates
"""

import argparse
import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def prepare_area(
    lat: float,
    lon: float,
    buffer_km: float = 5.0,
    scale: str = "1:10000",
    stream_threshold: int = 100,
    batch_size: int = 10000,
    keep_downloads: bool = True,
    save_intermediates: bool = False,
    output_dir: Path | None = None,
    with_landcover: bool = False,
    landcover_provider: str = "bdot10k",
) -> dict:
    """
    Download and process NMT data for an area around a point.

    Parameters
    ----------
    lat : float
        Latitude (WGS84)
    lon : float
        Longitude (WGS84)
    buffer_km : float
        Buffer radius in kilometers
    scale : str
        Map scale for sheet selection
    stream_threshold : int
        Flow accumulation threshold for stream identification
    batch_size : int
        Database insert batch size
    keep_downloads : bool
        If True, keep downloaded .asc files
    save_intermediates : bool
        If True, save intermediate GeoTIFF files
    output_dir : Path, optional
        Output directory for downloads (default: temp directory)
    with_landcover : bool
        If True, also download and import land cover data
    landcover_provider : str
        Land cover provider: 'bdot10k' or 'corine'

    Returns
    -------
    dict
        Processing statistics including:
        - sheets_found: number of sheets identified
        - sheets_downloaded: number of sheets successfully downloaded
        - sheets_processed: number of sheets processed
        - total_cells: total cells imported
        - stream_cells: number of stream cells
        - landcover_features: number of land cover features (if with_landcover)
    """
    # Add parent to path for imports
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from scripts.download_dem import download_for_point
    from scripts.process_dem import process_dem
    from utils.sheet_finder import get_sheets_for_point_with_buffer

    stats = {
        "sheets_found": 0,
        "sheets_downloaded": 0,
        "sheets_processed": 0,
        "total_cells": 0,
        "stream_cells": 0,
        "errors": [],
    }

    # Step 1: Find sheets for the area
    logger.info("=" * 60)
    logger.info("Step 1: Finding sheets for area")
    logger.info("=" * 60)

    sheets = get_sheets_for_point_with_buffer(lat, lon, buffer_km, scale)
    stats["sheets_found"] = len(sheets)

    logger.info(f"Point: ({lat}, {lon})")
    logger.info(f"Buffer: {buffer_km} km")
    logger.info(f"Scale: {scale}")
    logger.info(f"Sheets found: {len(sheets)}")

    for sheet in sheets:
        logger.info(f"  {sheet}")

    if not sheets:
        logger.warning("No sheets found for the specified area!")
        return stats

    # Step 2: Download sheets
    logger.info("=" * 60)
    logger.info("Step 2: Downloading NMT data from GUGiK")
    logger.info("=" * 60)

    # Use temp directory or specified output
    if output_dir is None:
        if keep_downloads:
            output_dir = Path(__file__).parent.parent.parent / "data" / "nmt"
        else:
            output_dir = Path(tempfile.mkdtemp(prefix="hydrolog_nmt_"))
            logger.info(f"Using temp directory: {output_dir}")
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    downloaded_files = download_for_point(
        lat=lat,
        lon=lon,
        buffer_km=buffer_km,
        output_dir=output_dir,
        scale=scale,
    )

    stats["sheets_downloaded"] = len(downloaded_files)
    logger.info(f"Downloaded {len(downloaded_files)} files")

    if not downloaded_files:
        logger.error(
            "No files downloaded! Check network connection and GUGiK availability."
        )
        return stats

    # Step 3: Create mosaic from all tiles (VRT or GeoTIFF)
    logger.info("=" * 60)
    logger.info("Step 3: Creating DEM mosaic")
    logger.info("=" * 60)

    from utils.raster_utils import create_vrt_mosaic, get_mosaic_info

    # Try VRT first, fallback to GeoTIFF if GDAL unavailable
    mosaic_path = output_dir / "dem_mosaic.vrt"

    try:
        mosaic_path = create_vrt_mosaic(
            input_files=downloaded_files,
            output_vrt=mosaic_path,
            resolution="highest",
            nodata=-9999.0,
        )

        # Log mosaic info
        mosaic_info = get_mosaic_info(mosaic_path)
        logger.info(
            f"Mosaic dimensions: {mosaic_info['width']} x {mosaic_info['height']}"
        )
        logger.info(f"Total cells: {mosaic_info['total_cells']:,}")
        logger.info(f"Cell size: {mosaic_info['cell_size_m']} m")
        logger.info(f"Estimated memory: {mosaic_info['estimated_memory_mb']:.1f} MB")

        stats["mosaic_path"] = str(mosaic_path)
        stats["mosaic_cells"] = mosaic_info["total_cells"]

    except Exception as e:
        logger.error(f"Mosaic creation failed: {e}")
        stats["errors"].append(f"Mosaic creation: {e}")
        return stats

    # Step 4: Process the mosaic as single continuous DEM
    logger.info("=" * 60)
    logger.info("Step 4: Processing DEM mosaic (hydrological analysis)")
    logger.info("=" * 60)

    try:
        dem_stats = process_dem(
            input_path=mosaic_path,
            stream_threshold=stream_threshold,
            batch_size=batch_size,
            dry_run=False,
            save_intermediates=save_intermediates,
            output_dir=output_dir if save_intermediates else None,
            clear_existing=True,  # Clear before processing
        )

        stats["sheets_processed"] = len(downloaded_files)
        stats["total_cells"] = dem_stats.get("valid_cells", 0)
        stats["stream_cells"] = dem_stats.get("stream_cells", 0)

        logger.info(f"Processed: {dem_stats.get('valid_cells', 0):,} cells")
        logger.info(f"Stream cells: {dem_stats.get('stream_cells', 0):,}")
        logger.info(f"Max accumulation: {dem_stats.get('max_accumulation', 0):,}")

    except Exception as e:
        logger.error(f"DEM processing failed: {e}")
        stats["errors"].append(f"DEM processing: {e}")
        import traceback

        logger.error(traceback.format_exc())

    # Step 5: Download and import land cover (optional)
    if with_landcover:
        logger.info("=" * 60)
        logger.info("Step 5: Downloading land cover data")
        logger.info("=" * 60)

        try:
            from scripts.download_landcover import download_landcover
            from scripts.import_landcover import import_landcover

            # Create landcover output directory
            landcover_dir = (
                output_dir.parent / "landcover"
                if output_dir
                else Path("../data/landcover")
            )
            landcover_dir.mkdir(parents=True, exist_ok=True)

            # Download land cover
            gpkg_file = download_landcover(
                output_dir=landcover_dir,
                provider=landcover_provider,
                lat=lat,
                lon=lon,
                buffer_km=buffer_km,
            )

            if gpkg_file and gpkg_file.exists():
                logger.info(f"Downloaded: {gpkg_file}")

                # Import to database
                logger.info("=" * 60)
                logger.info("Step 6: Importing land cover to database")
                logger.info("=" * 60)

                lc_stats = import_landcover(
                    input_path=gpkg_file,
                    batch_size=batch_size,
                    dry_run=False,
                    clear_existing=False,
                )

                stats["landcover_features"] = lc_stats.get("records_inserted", 0)
                logger.info(
                    f"Imported {stats['landcover_features']} land cover features"
                )
            else:
                logger.warning("Land cover download failed!")
                stats["errors"].append("Land cover download failed")

        except ImportError as e:
            logger.warning(f"Land cover support not available: {e}")
            stats["errors"].append(f"Land cover import error: {e}")
        except Exception as e:
            logger.error(f"Land cover processing failed: {e}")
            stats["errors"].append(f"Land cover error: {e}")

    # Cleanup temp directory if not keeping downloads
    if not keep_downloads and output_dir.name.startswith("hydrolog_nmt_"):
        logger.info(f"Cleaning up temp directory: {output_dir}")
        shutil.rmtree(output_dir, ignore_errors=True)

    return stats


def main():
    """Main entry point for prepare_area script."""
    parser = argparse.ArgumentParser(
        description="Download and process NMT data for a specified area",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Location (required)
    location_group = parser.add_argument_group("Location (required)")
    location_group.add_argument(
        "--lat",
        type=float,
        required=True,
        help="Latitude (WGS84)",
    )
    location_group.add_argument(
        "--lon",
        type=float,
        required=True,
        help="Longitude (WGS84)",
    )
    location_group.add_argument(
        "--buffer",
        type=float,
        default=5.0,
        help="Buffer radius in kilometers (default: 5)",
    )

    # Processing options
    process_group = parser.add_argument_group("Processing options")
    process_group.add_argument(
        "--stream-threshold",
        type=int,
        default=100,
        help="Flow accumulation threshold for streams (default: 100)",
    )
    process_group.add_argument(
        "--batch-size",
        type=int,
        default=10000,
        help="Database insert batch size (default: 10000)",
    )
    process_group.add_argument(
        "--scale",
        type=str,
        default="1:10000",
        choices=["1:10000", "1:25000", "1:50000", "1:100000"],
        help="Map scale (default: 1:10000)",
    )

    # Land cover options
    landcover_group = parser.add_argument_group(
        "Land cover options (requires Kartograf 0.3.0+)"
    )
    landcover_group.add_argument(
        "--with-landcover",
        action="store_true",
        help="Also download and import land cover data (BDOT10k)",
    )
    landcover_group.add_argument(
        "--landcover-provider",
        type=str,
        default="bdot10k",
        choices=["bdot10k", "corine"],
        help="Land cover provider (default: bdot10k)",
    )

    # Output options
    output_group = parser.add_argument_group("Output options")
    output_group.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output directory for downloads (default: ../data/nmt/)",
    )
    output_group.add_argument(
        "--keep-downloads",
        action="store_true",
        default=True,
        help="Keep downloaded .asc files (default: True)",
    )
    output_group.add_argument(
        "--no-keep-downloads",
        action="store_false",
        dest="keep_downloads",
        help="Delete downloaded .asc files after processing",
    )
    output_group.add_argument(
        "--save-intermediates",
        "-s",
        action="store_true",
        help="Save intermediate GeoTIFF files",
    )

    # Dry run
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show what would be done",
    )

    args = parser.parse_args()

    # Log configuration
    logger.info("=" * 60)
    logger.info("Hydrograf - Prepare Area Pipeline")
    logger.info("=" * 60)
    logger.info(f"Point: ({args.lat}, {args.lon})")
    logger.info(f"Buffer: {args.buffer} km")
    logger.info(f"Scale: {args.scale}")
    logger.info(f"Stream threshold: {args.stream_threshold}")
    logger.info(f"Keep downloads: {args.keep_downloads}")
    logger.info(f"Save intermediates: {args.save_intermediates}")
    logger.info(f"With land cover: {args.with_landcover}")
    if args.with_landcover:
        logger.info(f"Land cover provider: {args.landcover_provider}")
    logger.info("=" * 60)

    if args.dry_run:
        # Dry run - just show what would be downloaded
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from utils.sheet_finder import get_sheets_for_point_with_buffer

        sheets = get_sheets_for_point_with_buffer(
            args.lat, args.lon, args.buffer, args.scale
        )

        logger.info("DRY RUN - would download and process:")
        logger.info("NMT sheets:")
        for sheet in sheets:
            logger.info(f"  {sheet}")
        logger.info(f"Total: {len(sheets)} sheets")
        if args.with_landcover:
            logger.info(f"Would also download land cover ({args.landcover_provider})")
        return

    # Run pipeline
    start_time = time.time()

    try:
        stats = prepare_area(
            lat=args.lat,
            lon=args.lon,
            buffer_km=args.buffer,
            scale=args.scale,
            stream_threshold=args.stream_threshold,
            batch_size=args.batch_size,
            keep_downloads=args.keep_downloads,
            save_intermediates=args.save_intermediates,
            output_dir=Path(args.output) if args.output else None,
            with_landcover=args.with_landcover,
            landcover_provider=args.landcover_provider,
        )
    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        sys.exit(1)

    elapsed = time.time() - start_time

    # Summary
    logger.info("=" * 60)
    logger.info("Pipeline complete!")
    logger.info("=" * 60)
    logger.info(f"  Sheets found: {stats['sheets_found']}")
    logger.info(f"  Sheets downloaded: {stats['sheets_downloaded']}")
    logger.info(f"  Sheets processed: {stats['sheets_processed']}")
    logger.info(f"  Total cells: {stats['total_cells']:,}")
    logger.info(f"  Stream cells: {stats['stream_cells']:,}")
    if "landcover_features" in stats:
        logger.info(f"  Land cover features: {stats['landcover_features']:,}")
    logger.info(f"  Time elapsed: {elapsed:.1f}s")

    if stats["errors"]:
        logger.warning("Errors:")
        for error in stats["errors"]:
            logger.warning(f"  {error}")

    logger.info("=" * 60)

    if stats["sheets_processed"] == 0:
        logger.error("No sheets were processed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
