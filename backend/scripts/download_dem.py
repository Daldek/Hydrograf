"""
Script to download DEM (Digital Elevation Model) data from GUGiK using Kartograf.

Downloads NMT data for a specified area (point + buffer) or list of sheet codes.
Uses Kartograf 0.2.0+ library for OpenData/WCS API communication with GUGiK servers.

Note: Kartograf 0.2.0 changed the download API:
- download_sheet(godło) -> always returns ASC format via OpenData
- download_bbox(bbox, filename, format) -> returns GeoTIFF/PNG/JPEG via WCS

Usage
-----
    cd backend
    python -m scripts.download_dem --help
    python -m scripts.download_dem --lat 52.23 --lon 21.01 --buffer 5

Examples
--------
    # Download for area around point (5 km buffer)
    python -m scripts.download_dem \\
        --lat 52.23 --lon 21.01 \\
        --buffer 5 \\
        --output ../data/nmt/

    # Download specific sheets
    python -m scripts.download_dem \\
        --sheets N-34-131-C-c-2-1 N-34-131-C-c-2-2 \\
        --output ../data/nmt/
"""

import argparse
import logging
import sys
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


def download_sheets(
    sheets: List[str],
    output_dir: Path,
    skip_existing: bool = True,
) -> List[Path]:
    """
    Download NMT data for specified sheet codes using Kartograf.

    In Kartograf 0.2.0+, download_sheet() always returns ASC format via OpenData.

    Parameters
    ----------
    sheets : List[str]
        List of sheet codes (godła) to download
    output_dir : Path
        Output directory for downloaded files
    skip_existing : bool
        Skip download if file already exists (default: True)

    Returns
    -------
    List[Path]
        List of paths to downloaded files

    Raises
    ------
    ImportError
        If Kartograf is not installed
    """
    try:
        from kartograf import DownloadManager, GugikProvider
    except ImportError as e:
        logger.error(
            "Kartograf not installed. Install with: "
            "pip install git+https://github.com/Daldek/Kartograf.git"
        )
        raise ImportError("Kartograf library not found") from e

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize Kartograf components (Kartograf 0.2.0 API)
    provider = GugikProvider()
    manager = DownloadManager(output_dir=str(output_dir), provider=provider)

    downloaded_files = []
    failed_sheets = []

    logger.info(f"Downloading {len(sheets)} sheets to {output_dir}")
    logger.info("Format: ASC (OpenData)")

    for i, sheet in enumerate(sheets, 1):
        logger.info(f"[{i}/{len(sheets)}] Downloading {sheet}...")

        try:
            # Download using Kartograf (always ASC in 0.2.0+)
            file_path = manager.download_sheet(sheet, skip_existing=skip_existing)
            if file_path:
                downloaded_files.append(Path(file_path))
                logger.info(f"  OK: {file_path}")
            else:
                logger.warning(f"  FAILED: {sheet} - no file returned")
                failed_sheets.append(sheet)

        except Exception as e:
            logger.warning(f"  FAILED: {sheet} - {e}")
            failed_sheets.append(sheet)

    # Summary
    logger.info("-" * 50)
    logger.info(f"Downloaded: {len(downloaded_files)}/{len(sheets)} sheets")

    if failed_sheets:
        logger.warning(f"Failed sheets: {', '.join(failed_sheets)}")

    return downloaded_files


def download_for_point(
    lat: float,
    lon: float,
    buffer_km: float,
    output_dir: Path,
    scale: str = "1:10000",
    skip_existing: bool = True,
) -> List[Path]:
    """
    Download NMT data for area around a point.

    Parameters
    ----------
    lat : float
        Latitude (WGS84)
    lon : float
        Longitude (WGS84)
    buffer_km : float
        Buffer radius in kilometers
    output_dir : Path
        Output directory
    scale : str
        Map scale (default "1:10000")
    skip_existing : bool
        Skip download if file already exists (default: True)

    Returns
    -------
    List[Path]
        List of downloaded file paths
    """
    # Import sheet finder (local module)
    try:
        from utils.sheet_finder import get_sheets_for_point_with_buffer
    except ImportError:
        # Try relative import for script execution
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from utils.sheet_finder import get_sheets_for_point_with_buffer

    logger.info(f"Finding sheets for point ({lat}, {lon}) with {buffer_km} km buffer")

    # Get list of sheets
    sheets = get_sheets_for_point_with_buffer(lat, lon, buffer_km, scale)

    logger.info(f"Found {len(sheets)} sheets to download:")
    for sheet in sheets:
        logger.info(f"  {sheet}")

    if not sheets:
        logger.warning("No sheets found for the specified area")
        return []

    return download_sheets(sheets, output_dir, skip_existing=skip_existing)


def main():
    """Main entry point for DEM download script."""
    parser = argparse.ArgumentParser(
        description="Download NMT data from GUGiK using Kartograf 0.2.0+",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Location options (mutually exclusive groups)
    location_group = parser.add_argument_group("Location (choose one)")
    location_group.add_argument(
        "--lat",
        type=float,
        help="Latitude (WGS84) - requires --lon",
    )
    location_group.add_argument(
        "--lon",
        type=float,
        help="Longitude (WGS84) - requires --lat",
    )
    location_group.add_argument(
        "--buffer",
        type=float,
        default=5.0,
        help="Buffer radius in kilometers (default: 5)",
    )
    location_group.add_argument(
        "--sheets",
        nargs="+",
        help="List of sheet codes to download (e.g., N-34-131-C-c-2-1)",
    )

    # Output options
    output_group = parser.add_argument_group("Output")
    output_group.add_argument(
        "--output",
        "-o",
        type=str,
        default="../data/nmt/",
        help="Output directory (default: ../data/nmt/)",
    )

    # Additional options
    parser.add_argument(
        "--scale",
        type=str,
        default="1:10000",
        choices=["1:10000", "1:25000", "1:50000", "1:100000"],
        help="Map scale (default: 1:10000)",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Re-download files even if they exist",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show what would be downloaded",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.sheets:
        # Download specific sheets
        sheets = args.sheets
    elif args.lat is not None and args.lon is not None:
        # Download for point
        # Import sheet finder
        try:
            from utils.sheet_finder import get_sheets_for_point_with_buffer
        except ImportError:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from utils.sheet_finder import get_sheets_for_point_with_buffer

        sheets = get_sheets_for_point_with_buffer(args.lat, args.lon, args.buffer, args.scale)
    else:
        parser.error("Either --sheets or both --lat and --lon are required")
        return

    output_dir = Path(args.output)
    skip_existing = not args.no_skip_existing

    # Log configuration
    logger.info("=" * 60)
    logger.info("NMT Download Script (using Kartograf 0.2.0)")
    logger.info("=" * 60)

    if args.lat is not None:
        logger.info(f"Point: ({args.lat}, {args.lon})")
        logger.info(f"Buffer: {args.buffer} km")
        logger.info(f"Scale: {args.scale}")

    logger.info(f"Sheets to download: {len(sheets)}")
    for sheet in sheets:
        logger.info(f"  {sheet}")

    logger.info(f"Output: {output_dir}")
    logger.info("Format: ASC (OpenData)")
    logger.info(f"Skip existing: {skip_existing}")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("DRY RUN - no files will be downloaded")
        return

    # Download
    start_time = time.time()

    try:
        downloaded = download_sheets(
            sheets,
            output_dir,
            skip_existing=skip_existing,
        )
    except ImportError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Download failed: {e}")
        sys.exit(1)

    elapsed = time.time() - start_time

    # Summary
    logger.info("=" * 60)
    logger.info("Download complete!")
    logger.info(f"  Files downloaded: {len(downloaded)}")
    logger.info(f"  Output directory: {output_dir}")
    logger.info(f"  Time elapsed: {elapsed:.1f}s")
    logger.info("=" * 60)

    # Print downloaded files
    if downloaded:
        logger.info("Downloaded files:")
        for f in downloaded:
            logger.info(f"  {f}")


if __name__ == "__main__":
    main()
