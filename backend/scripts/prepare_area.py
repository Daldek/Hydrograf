"""
Pipeline script to download and process NMT data for a specified area.

This script combines:
1. Downloading NMT data from GUGiK using Kartograf
2. Processing DEM files with pysheds
3. Loading data into PostgreSQL/PostGIS flow_network table

Usage
-----
    cd backend
    python -m scripts.prepare_area --help
    python -m scripts.prepare_area --lat 52.23 --lon 21.01 --buffer 5

Examples
--------
    # Full pipeline for area
    python -m scripts.prepare_area \\
        --lat 52.23 --lon 21.01 \\
        --buffer 5

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
from typing import List

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

    Returns
    -------
    dict
        Processing statistics including:
        - sheets_found: number of sheets identified
        - sheets_downloaded: number of sheets successfully downloaded
        - sheets_processed: number of sheets processed
        - total_cells: total cells imported
        - stream_cells: number of stream cells
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
        logger.error("No files downloaded! Check network connection and GUGiK availability.")
        return stats

    # Step 3: Process each downloaded file
    logger.info("=" * 60)
    logger.info("Step 3: Processing DEM files")
    logger.info("=" * 60)

    for i, dem_file in enumerate(downloaded_files, 1):
        logger.info(f"[{i}/{len(downloaded_files)}] Processing {dem_file.name}...")

        try:
            dem_stats = process_dem(
                input_path=dem_file,
                stream_threshold=stream_threshold,
                batch_size=batch_size,
                dry_run=False,
                save_intermediates=save_intermediates,
                output_dir=output_dir if save_intermediates else None,
            )

            stats["sheets_processed"] += 1
            stats["total_cells"] += dem_stats.get("valid_cells", 0)
            stats["stream_cells"] += dem_stats.get("stream_cells", 0)

            logger.info(f"  Processed: {dem_stats.get('valid_cells', 0):,} cells")

        except Exception as e:
            logger.error(f"  FAILED: {e}")
            stats["errors"].append(f"{dem_file.name}: {e}")

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

    # Output options
    output_group = parser.add_argument_group("Output options")
    output_group.add_argument(
        "--output", "-o",
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
        "--save-intermediates", "-s",
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
    logger.info("HydroLOG - Prepare Area Pipeline")
    logger.info("=" * 60)
    logger.info(f"Point: ({args.lat}, {args.lon})")
    logger.info(f"Buffer: {args.buffer} km")
    logger.info(f"Scale: {args.scale}")
    logger.info(f"Stream threshold: {args.stream_threshold}")
    logger.info(f"Keep downloads: {args.keep_downloads}")
    logger.info(f"Save intermediates: {args.save_intermediates}")
    logger.info("=" * 60)

    if args.dry_run:
        # Dry run - just show what would be downloaded
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from utils.sheet_finder import get_sheets_for_point_with_buffer

        sheets = get_sheets_for_point_with_buffer(
            args.lat, args.lon, args.buffer, args.scale
        )

        logger.info("DRY RUN - would download and process:")
        for sheet in sheets:
            logger.info(f"  {sheet}")
        logger.info(f"Total: {len(sheets)} sheets")
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
