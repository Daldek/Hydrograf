"""
Script to download land cover data from GUGiK (BDOT10k) or Copernicus (CORINE).

Downloads land cover data for a specified area using Kartograf 0.3.0+ library.
Supports downloading by:
- Point + buffer (finds TERYT code for the area)
- Sheet code (godło)
- TERYT code (4-digit county code)
- Bounding box (EPSG:2180)

Available data sources:
- BDOT10k: Polish topographic database (12 land cover layers, 1:10000 scale)
- CORINE: European land cover classification (44 classes)

Usage
-----
    cd backend
    python -m scripts.download_landcover --help
    python -m scripts.download_landcover --lat 52.23 --lon 21.01 --buffer 5

Examples
--------
    # Download BDOT10k for area around point
    python -m scripts.download_landcover \\
        --lat 52.23 --lon 21.01 \\
        --buffer 5 \\
        --output ../data/landcover/

    # Download BDOT10k for specific TERYT code (powiat)
    python -m scripts.download_landcover \\
        --teryt 1465 \\
        --output ../data/landcover/

    # Download CORINE land cover
    python -m scripts.download_landcover \\
        --lat 52.23 --lon 21.01 \\
        --provider corine \\
        --year 2018
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def download_landcover(
    output_dir: Path,
    provider: str = "bdot10k",
    teryt: Optional[str] = None,
    godlo: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    buffer_km: float = 5.0,
    year: int = 2018,
    skip_existing: bool = True,
) -> Optional[Path]:
    """
    Download land cover data using Kartograf.

    Parameters
    ----------
    output_dir : Path
        Output directory for downloaded files
    provider : str
        Data provider: 'bdot10k' or 'corine' (default: 'bdot10k')
    teryt : str, optional
        4-digit TERYT code (county/powiat)
    godlo : str, optional
        Sheet code (e.g., 'N-34-131-C-c-2-1')
    lat : float, optional
        Latitude (WGS84) - requires lon
    lon : float, optional
        Longitude (WGS84) - requires lat
    buffer_km : float
        Buffer radius in kilometers when using lat/lon
    year : int
        Reference year for CORINE data (default: 2018)
    skip_existing : bool
        Skip download if file already exists

    Returns
    -------
    Path or None
        Path to downloaded file, or None if download failed

    Raises
    ------
    ImportError
        If Kartograf is not installed
    ValueError
        If invalid parameters provided
    """
    try:
        from kartograf.landcover import LandCoverManager
    except ImportError as e:
        logger.error(
            "Kartograf 0.3.0+ not installed. Install with: "
            "pip install git+https://github.com/Daldek/Kartograf.git@main"
        )
        raise ImportError("Kartograf library not found or version too old") from e

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize LandCoverManager
    manager = LandCoverManager(output_dir=str(output_dir), provider=provider)

    logger.info(f"Provider: {provider.upper()}")
    logger.info(f"Output directory: {output_dir}")

    # Determine download method
    if teryt:
        logger.info(f"Downloading by TERYT: {teryt}")
        output_path = output_dir / f"{provider}_teryt_{teryt}.gpkg"

        if skip_existing and output_path.exists():
            logger.info(f"File already exists, skipping: {output_path}")
            return output_path

        try:
            result = manager.download_by_teryt(teryt, output_path=output_path)
            return Path(result)
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return None

    elif godlo:
        logger.info(f"Downloading by sheet code: {godlo}")
        output_path = output_dir / f"{provider}_godlo_{godlo.replace('-', '_')}.gpkg"

        if skip_existing and output_path.exists():
            logger.info(f"File already exists, skipping: {output_path}")
            return output_path

        try:
            kwargs = {"year": year} if provider == "corine" else {}
            result = manager.download_by_godlo(godlo, output_path=output_path, **kwargs)
            return Path(result)
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return None

    elif lat is not None and lon is not None:
        # Convert point to TERYT or bbox
        logger.info(f"Finding area for point ({lat}, {lon}) with {buffer_km} km buffer")

        try:
            # Transform to PL-1992 for bbox
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from utils.geometry import transform_wgs84_to_pl1992

            x, y = transform_wgs84_to_pl1992(lat, lon)

            # Create bbox with buffer
            buffer_m = buffer_km * 1000
            from kartograf import BBox

            bbox = BBox(x - buffer_m, y - buffer_m, x + buffer_m, y + buffer_m, "EPSG:2180")

            output_path = output_dir / f"{provider}_bbox_{int(x)}_{int(y)}.gpkg"

            if skip_existing and output_path.exists():
                logger.info(f"File already exists, skipping: {output_path}")
                return output_path

            logger.info(f"Downloading by bbox: {bbox}")
            kwargs = {"year": year} if provider == "corine" else {}
            result = manager.download_by_bbox(bbox, output_path=output_path, **kwargs)
            return Path(result)

        except Exception as e:
            logger.error(f"Download failed: {e}")
            return None

    else:
        raise ValueError("Either --teryt, --godlo, or both --lat and --lon are required")


def main():
    """Main entry point for land cover download script."""
    parser = argparse.ArgumentParser(
        description="Download land cover data from GUGiK (BDOT10k) or Copernicus (CORINE)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Location options
    location_group = parser.add_argument_group("Location (choose one)")
    location_group.add_argument(
        "--teryt",
        type=str,
        help="4-digit TERYT code (powiat), e.g., 1465",
    )
    location_group.add_argument(
        "--godlo",
        type=str,
        help="Sheet code, e.g., N-34-131-C-c-2-1",
    )
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

    # Provider options
    provider_group = parser.add_argument_group("Data source")
    provider_group.add_argument(
        "--provider",
        "-p",
        type=str,
        default="bdot10k",
        choices=["bdot10k", "corine"],
        help="Data provider (default: bdot10k)",
    )
    provider_group.add_argument(
        "--year",
        type=int,
        default=2018,
        choices=[1990, 2000, 2006, 2012, 2018],
        help="Reference year for CORINE data (default: 2018)",
    )

    # Output options
    output_group = parser.add_argument_group("Output")
    output_group.add_argument(
        "--output",
        "-o",
        type=str,
        default="../data/landcover/",
        help="Output directory (default: ../data/landcover/)",
    )
    output_group.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Re-download files even if they exist",
    )

    # Dry run
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show what would be downloaded",
    )

    args = parser.parse_args()

    # Validate arguments
    if not any([args.teryt, args.godlo, args.lat]):
        parser.error("Either --teryt, --godlo, or --lat/--lon are required")

    if args.lat is not None and args.lon is None:
        parser.error("--lat requires --lon")
    if args.lon is not None and args.lat is None:
        parser.error("--lon requires --lat")

    output_dir = Path(args.output)
    skip_existing = not args.no_skip_existing

    # Log configuration
    logger.info("=" * 60)
    logger.info("Land Cover Download Script (Kartograf 0.3.0)")
    logger.info("=" * 60)
    logger.info(f"Provider: {args.provider.upper()}")

    if args.teryt:
        logger.info(f"TERYT: {args.teryt}")
    elif args.godlo:
        logger.info(f"Sheet code: {args.godlo}")
    elif args.lat:
        logger.info(f"Point: ({args.lat}, {args.lon})")
        logger.info(f"Buffer: {args.buffer} km")

    if args.provider == "corine":
        logger.info(f"Year: {args.year}")

    logger.info(f"Output: {output_dir}")
    logger.info(f"Skip existing: {skip_existing}")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("DRY RUN - no files will be downloaded")
        return

    # Download
    start_time = time.time()

    try:
        result = download_landcover(
            output_dir=output_dir,
            provider=args.provider,
            teryt=args.teryt,
            godlo=args.godlo,
            lat=args.lat,
            lon=args.lon,
            buffer_km=args.buffer,
            year=args.year,
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
    if result:
        logger.info("Download complete!")
        logger.info(f"  File: {result}")
        logger.info(f"  Size: {result.stat().st_size / 1024 / 1024:.1f} MB")
    else:
        logger.warning("Download failed!")
    logger.info(f"  Time elapsed: {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
