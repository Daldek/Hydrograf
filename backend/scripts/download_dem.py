"""
Script to download DEM (Digital Elevation Model) data from GUGiK using Kartograf.

Downloads NMT data for a specified area (point + buffer), list of sheet codes,
or geometry file (SHP/GPKG).
Uses Kartograf 0.7.0 (OpenData ASC, GUGiK campaigns "newest", MetadataCache).

Kartograf 0.7.0 API used here:
- DownloadManager.download_sheets(godla) -> list[Path] (standard paths;
  coarse PL-1992 codes expanded to 1:10000); per-sheet result in
  DownloadManager.last_result (failed / no_coverage / hard_failures / unverified)
- find_sheets_for_geometry(filepath, target_scale) -> tile selection
  from SHP/GPKG

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
        --output ../cache/ --metadata-cache ../cache/kartograf_meta.db

    # Download specific sheets
    python -m scripts.download_dem \\
        --sheets N-34-131-C-c-2-1 N-34-131-C-c-2-2 \\
        --output ../cache/ --metadata-cache ../cache/kartograf_meta.db

    # Download tiles covering a geometry file
    python -m scripts.download_dem \\
        --geometry ../data/boundary.gpkg \\
        --output ../cache/ --metadata-cache ../cache/kartograf_meta.db
"""

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# Kartograf MetadataCache (SQLite) file name inside the cache/data root.
METADATA_CACHE_NAME = "kartograf_meta.db"


class NmtDownloadError(RuntimeError):
    """Pobranie NMT niekompletne albo niewiarygodne — bootstrap nie moze kontynuowac."""


@dataclass(frozen=True)
class NmtDownloadReport:
    """Wynik pobrania arkuszy NMT przez Kartograf 0.7.0.

    paths — sciezki standardowe (dowiazania do najnowszej kampanii), pobrane
    teraz albo juz lokalne; no_coverage — godla bez danych w GUGiK (np. poza
    Polska, morze); unverified — godlo -> blad skorowidza, przy ktorym uzyto
    lokalnej kampanii bez sprawdzenia nowszej.
    """

    paths: list[Path]
    no_coverage: list[str] = field(default_factory=list)
    unverified: dict[str, str] = field(default_factory=dict)


def download_sheets(
    sheets: list[str],
    output_dir: Path,
    metadata_cache_path: Path,
    skip_existing: bool = True,
    resolution: str = "5m",
) -> NmtDownloadReport:
    """
    Download NMT sheets via Kartograf 0.7.0 (campaigns="newest").

    Parameters
    ----------
    sheets : list[str]
        Sheet codes; PL-1992 codes coarser than 1:10000 are expanded by Kartograf.
    output_dir : Path
        Kartograf data root — files land in
        ``<output_dir>/nmt/pl_<uklad>_<res>_evrf2007/...``.
    metadata_cache_path : Path
        SQLite file of Kartograf's MetadataCache. Keep it on a local disk
        (SQLite WAL is unreliable on network shares); its directory must exist.
    skip_existing : bool
        Reuse local campaign files (default: True).
    resolution : str
        "1m" or "5m" (default: "5m").

    Returns
    -------
    NmtDownloadReport

    Raises
    ------
    NmtDownloadError
        Transport/service failures (full list of sheets), no coverage for
        every sheet, missing cache directory or a cache disabled by SQLite.
    kartograf.ParseError
        Invalid sheet code (raised before any download).
    """
    from kartograf import DownloadManager, GugikProvider, MetadataCache

    if not sheets:
        raise NmtDownloadError("Pusta lista arkuszy NMT — nic do pobrania")

    if not metadata_cache_path.parent.is_dir():
        raise NmtDownloadError(
            f"Katalog cache metadanych Kartografa nie istnieje: "
            f"{metadata_cache_path.parent}"
        )

    cache_errors: list[str] = []
    cache = MetadataCache(metadata_cache_path, on_disabled=cache_errors.append)
    provider = GugikProvider(resolution=resolution, cache=cache)
    manager = DownloadManager(
        output_dir=str(output_dir),
        provider=provider,
        resolution=resolution,
        campaigns="newest",
    )

    logger.info(f"Downloading {len(sheets)} sheets to {output_dir} (ASC, OpenData)")
    paths = manager.download_sheets(sheets, skip_existing=skip_existing)
    result = manager.last_result

    errors = list(cache_errors)

    hard_failures = result.hard_failures
    if hard_failures:
        requested = len(paths) + len(result.failed)
        errors.append(
            f"{len(hard_failures)} z {requested} arkuszy NMT nie pobrano "
            f"(blad pobrania, nie brak danych) — ponow pobranie: "
            f"{', '.join(hard_failures)}"
        )

    if not paths:
        errors.append(
            f"brak pokrycia GUGiK dla wszystkich arkuszy: "
            f"{', '.join(result.no_coverage)}"
        )

    if errors:
        raise NmtDownloadError("; ".join(errors))

    if result.no_coverage:
        logger.warning(
            f"Brak pokrycia GUGiK dla {len(result.no_coverage)} arkuszy "
            f"(pominiete): {', '.join(result.no_coverage)}"
        )
    for godlo, error in result.unverified.items():
        logger.warning(
            f"{godlo}: uzyto lokalnej kampanii bez sprawdzenia nowszej "
            f"(skorowidz niedostepny: {error})"
        )

    logger.info(f"NMT: {len(paths)} arkuszy gotowych")
    return NmtDownloadReport(
        paths=list(paths),
        no_coverage=list(result.no_coverage),
        unverified=dict(result.unverified),
    )


def download_for_point(
    lat: float,
    lon: float,
    buffer_km: float,
    output_dir: Path,
    metadata_cache_path: Path,
    scale: str = "1:10000",
    skip_existing: bool = True,
) -> NmtDownloadReport:
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
    NmtDownloadReport
        See download_sheets()
    """
    # Import sheet lookup (local module)
    try:
        from utils.sheet_lookup import sheets_for_point_buffer
    except ImportError:
        # Try relative import for script execution
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from utils.sheet_lookup import sheets_for_point_buffer

    logger.info(f"Finding sheets for point ({lat}, {lon}) with {buffer_km} km buffer")

    # Get list of sheets
    sheets = sheets_for_point_buffer(lat, lon, buffer_km, scale)

    logger.info(f"Found {len(sheets)} sheets to download:")
    for sheet in sheets:
        logger.info(f"  {sheet}")

    if not sheets:
        raise NmtDownloadError(f"Brak arkuszy dla punktu ({lat}, {lon})")

    return download_sheets(
        sheets, output_dir, metadata_cache_path, skip_existing=skip_existing
    )


def download_for_geometry(
    geometry_path: Path,
    output_dir: Path,
    metadata_cache_path: Path,
    scale: str = "1:10000",
    layer: str | None = None,
    skip_existing: bool = True,
) -> NmtDownloadReport:
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
    NmtDownloadReport
        See download_sheets()
    """
    from kartograf import find_sheets_for_geometry

    logger.info(f"Finding sheets for geometry: {geometry_path}")
    if layer:
        logger.info(f"Layer: {layer}")

    sheets = find_sheets_for_geometry(
        geometry_path, target_scale=scale, layer=layer
    )

    logger.info(f"Found {len(sheets)} sheets for geometry:")
    for sheet in sheets:
        logger.info(f"  {sheet}")

    if not sheets:
        raise NmtDownloadError(f"Brak arkuszy dla geometrii: {geometry_path}")

    return download_sheets(
        sheets, output_dir, metadata_cache_path, skip_existing=skip_existing
    )


def main():
    """Main entry point for DEM download script."""
    parser = argparse.ArgumentParser(
        description="Download NMT data from GUGiK using Kartograf 0.7.0",
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
        default="../cache/",
        help=(
            "Katalog danych Kartografa (default: ../cache/); "
            "pliki w <output>/nmt/pl_<uklad>_<res>_evrf2007/"
        ),
    )
    output_group.add_argument(
        "--metadata-cache",
        type=Path,
        default=None,
        help="Plik SQLite cache metadanych Kartografa (wymagany; dysk lokalny)",
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
            from utils.sheet_lookup import sheets_for_point_buffer
        except ImportError:
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from utils.sheet_lookup import sheets_for_point_buffer

        sheets = sheets_for_point_buffer(
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
    logger.info("NMT Download Script (using Kartograf 0.7.0)")
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
                Path(args.geometry), target_scale=args.scale, layer=args.layer
            )
            logger.info(f"DRY RUN - would download {len(sheets)} sheets:")
            for sheet in sheets:
                logger.info(f"  {sheet}")
        else:
            logger.info("DRY RUN - no files will be downloaded")
        return

    if args.metadata_cache is None:
        parser.error("--metadata-cache jest wymagany do pobierania")

    # Download
    start_time = time.time()

    try:
        if args.geometry:
            downloaded = download_for_geometry(
                geometry_path=Path(args.geometry),
                output_dir=output_dir,
                metadata_cache_path=args.metadata_cache,
                scale=args.scale,
                layer=args.layer,
                skip_existing=skip_existing,
            )
        else:
            downloaded = download_sheets(
                sheets, output_dir, args.metadata_cache, skip_existing=skip_existing
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
    logger.info(f"  Sheets ready: {len(downloaded.paths)}")
    logger.info(f"  No coverage: {len(downloaded.no_coverage)}")
    logger.info(f"  Unverified (local campaign reused): {len(downloaded.unverified)}")
    logger.info(f"  Output directory: {output_dir}")
    logger.info(f"  Time elapsed: {elapsed:.1f}s")
    logger.info("=" * 60)

    for f in downloaded.paths:
        logger.info(f"  {f}")


if __name__ == "__main__":
    main()
