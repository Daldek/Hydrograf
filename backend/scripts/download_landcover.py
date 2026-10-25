r"""
Script to download land cover data from GUGiK (BDOT10k) or Copernicus (CORINE).

Downloads land cover data for a specified area into the Kartograf store of the pipeline
(ADR-061) with ``kartograf.download_landcover``. Supports downloading by:
- Point + buffer (every county the area intersects)
- Sheet code (godlo)
- TERYT code (4-digit county code)

Available data sources:
- BDOT10k: Polish topographic database (all layers downloaded, hydro filtered on merge)
- CORINE: European land cover classification (44 classes), a raster

A file is a version of the store: the GeoPackage of a county is
``<root>/landcover/pl_bdot10k_gpkg/teryt/<teryt>.gpkg``. A version that is already local
is used again without a request (``--no-skip-existing`` fetches it again).

Usage
-----
    cd backend
    python -m scripts.download_landcover --help
    python -m scripts.download_landcover --lat 52.23 --lon 21.01 --buffer 5

Examples
--------
    # Download BDOT10k land cover for area around point
    python -m scripts.download_landcover \
        --lat 52.23 --lon 21.01 \
        --buffer 5 \
        --root ../cache/kartograf/

    # Download BDOT10k for specific TERYT code (powiat)
    python -m scripts.download_landcover \
        --teryt 1465 \
        --root ../cache/kartograf/

    # Download CORINE land cover
    python -m scripts.download_landcover \
        --lat 52.23 --lon 21.01 \
        --provider corine \
        --year 2018
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from utils.kartograf_store import describe_error, store_dir

if TYPE_CHECKING:
    from kartograf import LandCoverReport

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

HYDRO_LAYER_PREFIXES = ("SWRS", "SWKN", "SWRM", "PTWP")


def merge_hydro_gpkgs(gpkg_paths: list[Path], output_path: Path) -> Path | None:
    """
    Merge multiple per-TERYT hydro GeoPackages into one multi-layer GeoPackage.

    Preserves layer structure (SWRS, SWKN, SWRM, PTWP) as required by
    ``burn_streams_into_dem()`` in ``core/hydrology.py``.

    Parameters
    ----------
    gpkg_paths : list[Path]
        Paths to per-TERYT hydro GeoPackage files
    output_path : Path
        Path for the merged output GeoPackage

    Returns
    -------
    Path or None
        Path to merged file, or None if no data available
    """
    if not gpkg_paths:
        return None

    if len(gpkg_paths) == 1:
        return gpkg_paths[0]

    try:
        import fiona
        import geopandas as gpd
        import pandas as pd
    except ImportError as e:
        logger.error(f"Missing dependency for merge: {e}")
        return None

    # Collect GeoDataFrames per layer name across all files
    layers_data: dict[str, list[gpd.GeoDataFrame]] = {}
    layers_crs: dict[str, object] = {}

    for gpkg in gpkg_paths:
        try:
            layer_names = fiona.listlayers(str(gpkg))
        except Exception as e:
            logger.warning(f"Cannot read layers from {gpkg}: {e}")
            continue

        for layer_name in layer_names:
            # Filter: keep only hydro-relevant layers
            # Extract BDOT10k code: "OT_SWRS_L" → "SWRS"
            parts = layer_name.split("_")
            is_ot = len(parts) >= 3 and parts[0] == "OT"
            layer_code = parts[1] if is_ot else layer_name
            if not layer_code.startswith(HYDRO_LAYER_PREFIXES):
                logger.debug(f"Skipping non-hydro layer: {layer_name}")
                continue
            try:
                gdf = gpd.read_file(gpkg, layer=layer_name)
                if gdf.empty:
                    continue
                layers_data.setdefault(layer_name, []).append(gdf)
                if layer_name not in layers_crs and gdf.crs is not None:
                    layers_crs[layer_name] = gdf.crs
            except Exception as e:
                logger.debug(f"Cannot read layer {layer_name} from {gpkg}: {e}")

    if not layers_data:
        logger.warning("No hydro data found in any input files")
        return None

    # Write merged layers to output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    for layer_name, gdfs in layers_data.items():
        merged = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True))
        crs = layers_crs.get(layer_name)
        if crs is not None:
            merged = merged.set_crs(crs)
        merged.to_file(output_path, layer=layer_name, driver="GPKG")

    total_features = sum(len(gdf) for gdfs in layers_data.values() for gdf in gdfs)
    logger.info(
        f"Merged {len(gpkg_paths)} hydro files → {output_path.name}: "
        f"{len(layers_data)} layers, {total_features} features"
    )
    return output_path


def fetch_landcover(
    root: Path,
    provider: str = "bdot10k",
    teryt: str | None = None,
    godlo: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    buffer_km: float = 5.0,
    year: int = 2018,
    skip_existing: bool = True,
    metadata_cache_path: Path | None = None,
) -> "LandCoverReport":
    """
    Download land cover data into the Kartograf store ``root``.

    Parameters
    ----------
    root : Path
        Kartograf store (``<cache>/kartograf``); a new or empty directory becomes one.
    provider : str
        Data provider: 'bdot10k' or 'corine' (default: 'bdot10k')
    teryt : str, optional
        4-digit TERYT code (county/powiat); BDOT10k only
    godlo : str, optional
        Sheet code (e.g., 'N-34-131-C-c-2-1')
    lat : float, optional
        Latitude (WGS84) - requires lon
    lon : float, optional
        Longitude (WGS84) - requires lat
    buffer_km : float
        Buffer radius in kilometers when using lat/lon; the area is the square around
        the point and BDOT10k covers every county it intersects
    year : int
        Reference year for CORINE data (default: 2018); not used for BDOT10k, whose
        ``year`` of Kartograf is the yearly archive
    skip_existing : bool
        Use a local version without a request (default: True); False fetches the
        files again (a new version, or the same one)
    metadata_cache_path : Path, optional
        SQLite file of the Kartograf metadata cache; none by default

    Returns
    -------
    kartograf.LandCoverReport
        ``files`` (one per county, sheet or area), ``failed`` and ``ok``

    Raises
    ------
    ValueError
        No area given.
    kartograf.KartografError
        A request that Kartograf refuses or a store that refuses the write; see
        ``utils.kartograf_store.describe_error``.
    """
    from kartograf import MetadataCache, download_landcover

    from utils.sheet_lookup import point_buffer_bbox

    request: dict[str, Any]
    if teryt:
        request = {"teryt": teryt}
    elif godlo:
        request = {"sheet": godlo}
    elif lat is not None and lon is not None:
        logger.info(f"Finding area for point ({lat}, {lon}) with {buffer_km} km buffer")
        request = {"bbox": point_buffer_bbox(lat, lon, buffer_km)}
    else:
        raise ValueError(
            "Either --teryt, --godlo, or both --lat and --lon are required"
        )
    if provider == "corine":
        request["year"] = year

    return download_landcover(
        product=provider,
        root=root,
        update=None if skip_existing else "force",
        cache=MetadataCache(metadata_cache_path) if metadata_cache_path else False,
        **request,
    )


def main():
    """Run the land cover download script."""
    parser = argparse.ArgumentParser(
        description="Download land cover data from GUGiK/Copernicus",
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
        "--root",
        type=str,
        default=str(store_dir(Path("../cache"))),
        help=(
            "Kartograf store (default: ../cache/kartograf); a new or empty "
            "directory becomes a store, one that holds other files is refused"
        ),
    )
    output_group.add_argument(
        "--metadata-cache",
        type=Path,
        default=None,
        help=(
            "SQLite file of the Kartograf metadata cache (default: none; "
            "local disk, outside --root)"
        ),
    )
    output_group.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Fetch the files again even if a version is local",
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

    root = Path(args.root)
    skip_existing = not args.no_skip_existing

    # Log configuration
    logger.info("=" * 60)
    logger.info("Land Cover Download Script (Kartograf)")
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

    logger.info(f"Store: {root}")
    logger.info(f"Skip existing: {skip_existing}")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("DRY RUN - no files will be downloaded")
        return

    # Download
    start_time = time.time()

    try:
        report = fetch_landcover(
            root=root,
            provider=args.provider,
            teryt=args.teryt,
            godlo=args.godlo,
            lat=args.lat,
            lon=args.lon,
            buffer_km=args.buffer,
            year=args.year,
            skip_existing=skip_existing,
            metadata_cache_path=args.metadata_cache,
        )
    except Exception as e:
        logger.error(f"Download failed: {describe_error(e)}")
        sys.exit(1)

    elapsed = time.time() - start_time

    # Summary
    logger.info("=" * 60)
    if report.ok:
        logger.info("Download complete!")
    else:
        logger.warning("Download incomplete!")
    for item in report.files:
        size_mb = item.file.size_bytes / 1024 / 1024
        logger.info(f"  {item.unit}: {item.file.path} ({size_mb:.1f} MB)")
    for failure in report.failed:
        logger.warning(f"  {failure.unit}: {failure.error}")
    logger.info(f"  Time elapsed: {elapsed:.1f}s")
    logger.info("=" * 60)
    if not report.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
