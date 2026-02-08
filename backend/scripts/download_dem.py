"""
Script to download DEM (Digital Elevation Model) data from GUGiK using Kartograf.

Downloads NMT data for a specified area (point + buffer), list of sheet codes,
or geometry file (SHP/GPKG).
Uses Kartograf 0.4.1+ library for OpenData/WCS API communication with GUGiK servers.

Note: Kartograf 0.4.1 API:
- download_sheet(godlo) -> returns Path | list[Path] (auto-expansion for coarse scales)
- download_bbox(bbox, filename, format) -> returns GeoTIFF/PNG/JPEG via WCS
- find_sheets_for_geometry(filepath, target_scale) -> precise tile selection from SHP/GPKG

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

    # Download tiles covering a geometry file
    python -m scripts.download_dem \\
        --geometry ../data/boundary.gpkg \\
        --output ../data/nmt/
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def download_sheets(
    sheets: list[str],
    output_dir: Path,
    skip_existing: bool = True,
) -> list[Path]:
    """
    Download NMT data for specified sheet codes using Kartograf.

    In Kartograf 0.4.1+, download_sheet() returns ASC format via OpenData.
    Returns Path for 1:10000 sheets, or list[Path] for coarser scales (auto-expansion).

    Parameters
    ----------
    sheets : List[str]
        List of sheet codes (godla) to download
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
            "pip install git+https://github.com/Daldek/Kartograf.git@v0.4.1"
        )
        raise ImportError("Kartograf library not found") from e

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize Kartograf components (Kartograf 0.4.1 API)
    provider = GugikProvider()
    manager = DownloadManager(output_dir=str(output_dir), provider=provider)

    downloaded_files = []
    failed_sheets = []

    logger.info(f"Downloading {len(sheets)} sheets to {output_dir}")
    logger.info("Format: ASC (OpenData)")

    for i, sheet in enumerate(sheets, 1):
        logger.info(f"[{i}/{len(sheets)}] Downloading {sheet}...")

        try:
            # Download using Kartograf (returns Path | list[Path])
            result = manager.download_sheet(sheet, skip_existing=skip_existing)
            if result:
                if isinstance(result, list):
                    downloaded_files.extend(Path(p) for p in result)
                    logger.info(f"  OK: {sheet} → {len(result)} files (auto-expanded)")
                else:
                    downloaded_files.append(Path(result))
                    logger.info(f"  OK: {result}")
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
) -> list[Path]:
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


def download_for_geometry(
    geometry_path: Path,
    output_dir: Path,
    scale: str = "1:10000",
    layer: str | None = None,
    skip_existing: bool = True,
) -> list[Path]:
    """
    Download NMT data for area covered by a geometry file (SHP/GPKG).

    Uses Kartograf's find_sheets_for_geometry() for precise tile selection
    based on per-feature bounding boxes (more efficient than overall bbox).

    Parameters
    ----------
    geometry_path : Path
        Path to SHP or GPKG file with geometries
    output_dir : Path
        Output directory
    scale : str
        Map scale (default "1:10000")
    layer : str, optional
        Layer name in GPKG file (default: first layer)
    skip_existing : bool
        Skip download if file already exists (default: True)

    Returns
    -------
    List[Path]
        List of downloaded file paths
    """
    from kartograf import find_sheets_for_geometry

    logger.info(f"Finding sheets for geometry: {geometry_path}")
    if layer:
        logger.info(f"Layer: {layer}")

    sheets = find_sheets_for_geometry(
        str(geometry_path), target_scale=scale, layer=layer
    )

    logger.info(f"Found {len(sheets)} sheets for geometry:")
    for sheet in sheets:
        logger.info(f"  {sheet}")

    if not sheets:
        logger.warning("No sheets found for geometry")
        return []

    return download_sheets(sheets, output_dir, skip_existing=skip_existing)


def main():
    """Main entry point for DEM download script."""
    parser = argparse.ArgumentParser(
        description="Download NMT data from GUGiK using Kartograf 0.4.1+",
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
    location_group.add_argument(
        "--geometry",
        type=str,
        help="Path to SHP/GPKG file for tile selection (alternative to --lat/--lon)",
    )
    location_group.add_argument(
        "--layer",
        type=str,
        default=None,
        help="Layer name in GPKG file (default: first layer)",
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

    # Validate arguments and determine sheets
    sheets = None
    if args.sheets:
        sheets = args.sheets
    elif args.geometry:
        if not Path(args.geometry).exists():
            parser.error(f"Geometry file not found: {args.geometry}")
        # Sheets will be determined via find_sheets_for_geometry
    elif args.lat is not None and args.lon is not None:
        try:
            from utils.sheet_finder import get_sheets_for_point_with_buffer
        except ImportError:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from utils.sheet_finder import get_sheets_for_point_with_buffer

        sheets = get_sheets_for_point_with_buffer(
            args.lat, args.lon, args.buffer, args.scale
        )
    else:
        parser.error(
            "Either --sheets, --geometry, or both --lat and --lon are required"
        )
        return

    output_dir = Path(args.output)
    skip_existing = not args.no_skip_existing

    # Log configuration
    logger.info("=" * 60)
    logger.info("NMT Download Script (using Kartograf 0.4.1)")
    logger.info("=" * 60)

    if args.geometry:
        logger.info(f"Geometry: {args.geometry}")
        if args.layer:
            logger.info(f"Layer: {args.layer}")
    elif args.lat is not None:
        logger.info(f"Point: ({args.lat}, {args.lon})")
        logger.info(f"Buffer: {args.buffer} km")

    logger.info(f"Scale: {args.scale}")
    if sheets:
        logger.info(f"Sheets to download: {len(sheets)}")
        for sheet in sheets:
            logger.info(f"  {sheet}")

    logger.info(f"Output: {output_dir}")
    logger.info("Format: ASC (OpenData)")
    logger.info(f"Skip existing: {skip_existing}")
    logger.info("=" * 60)

    if args.dry_run:
        if args.geometry and sheets is None:
            # Need to resolve sheets for dry run display
            from kartograf import find_sheets_for_geometry

            sheets = find_sheets_for_geometry(
                args.geometry, target_scale=args.scale, layer=args.layer
            )
            logger.info(f"DRY RUN - would download {len(sheets)} sheets:")
            for sheet in sheets:
                logger.info(f"  {sheet}")
        else:
            logger.info("DRY RUN - no files will be downloaded")
        return

    # Download
    start_time = time.time()

    try:
        if args.geometry:
            downloaded = download_for_geometry(
                geometry_path=Path(args.geometry),
                output_dir=output_dir,
                scale=args.scale,
                layer=args.layer,
                skip_existing=skip_existing,
            )
        else:
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
