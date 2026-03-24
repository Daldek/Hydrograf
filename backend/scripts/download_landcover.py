"""
Script to download land cover data from GUGiK (BDOT10k) or Copernicus (CORINE).

Downloads land cover data for a specified area using Kartograf 0.6.1+ library.
Supports downloading by:
- Point + buffer (finds TERYT code for the area)
- Sheet code (godlo)
- TERYT code (4-digit county code)
- Bounding box (EPSG:2180)

Available data sources:
- BDOT10k: Polish topographic database (all layers downloaded, hydro filtered on merge)
- CORINE: European land cover classification (44 classes)

Usage
-----
    cd backend
    python -m scripts.download_landcover --help
    python -m scripts.download_landcover --lat 52.23 --lon 21.01 --buffer 5

Examples
--------
    # Download BDOT10k land cover for area around point
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
    teryt: str | None = None,
    godlo: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    buffer_km: float = 5.0,
    year: int = 2018,
    skip_existing: bool = True,
) -> Path | None:
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
            "Kartograf 0.6.1+ not installed. Install with: "
            "pip install git+https://github.com/Daldek/Kartograf.git@v0.6.1"
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
            result = manager.download_by_teryt(
                teryt, output_path=output_path
            )
            return Path(result)
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return None

    elif godlo:
        logger.info(f"Downloading by sheet code: {godlo}")
        output_path = (
            output_dir / f"{provider}_godlo_{godlo.replace('-', '_')}.gpkg"
        )

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

            bbox = BBox(
                x - buffer_m, y - buffer_m, x + buffer_m, y + buffer_m, "EPSG:2180"
            )

            output_path = (
                output_dir / f"{provider}_bbox_{int(x)}_{int(y)}.gpkg"
            )

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
        raise ValueError(
            "Either --teryt, --godlo, or both --lat and --lon are required"
        )


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


def _generate_sample_coords(start: float, end: float, spacing: float) -> list[float]:
    """
    Generate sample coordinates between start and end (inclusive).

    For ranges smaller than spacing, returns [start, midpoint, end].
    For start == end, returns [start].
    """
    if start == end:
        return [start]

    lo, hi = min(start, end), max(start, end)
    extent = hi - lo

    if extent < spacing:
        return [lo, lo + extent / 2.0, hi]

    n_steps = max(1, int(extent / spacing))
    step = extent / n_steps
    coords = [lo + i * step for i in range(n_steps)]
    coords.append(hi)
    return coords


def discover_teryts_for_bbox(
    bbox_2180: tuple[float, float, float, float],
    spacing_m: float = 2000.0,
) -> list[str]:
    """
    Discover all TERYT codes (powiaty) that cover a bounding box.

    Samples a grid of points within the bbox and queries WMS to find
    the TERYT code at each point. Returns a sorted list of unique codes.

    Parameters
    ----------
    bbox_2180 : tuple
        Bounding box in EPSG:2180: (min_x, min_y, max_x, max_y)
    spacing_m : float
        Grid spacing in meters (default: 5000)

    Returns
    -------
    list[str]
        Sorted list of unique 4-digit TERYT codes
    """
    from kartograf.providers.bdot10k import Bdot10kProvider

    min_x, min_y, max_x, max_y = bbox_2180
    xs = _generate_sample_coords(min_x, max_x, spacing_m)
    ys = _generate_sample_coords(min_y, max_y, spacing_m)

    provider = Bdot10kProvider()
    teryts: set[str] = set()

    for x in xs:
        for y in ys:
            try:
                teryt = provider._get_teryt_for_point(x, y)
                teryts.add(teryt)
                logger.info(f"Point ({x:.0f}, {y:.0f}) → TERYT {teryt}")
            except Exception as e:
                logger.debug(f"Point ({x:.0f}, {y:.0f}) — no TERYT: {e}")

    result = sorted(teryts)
    logger.info(f"Discovered {len(result)} TERYT(s) for bbox: {result}")
    return result


def main():
    """Main entry point for land cover download script."""
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
    logger.info("Land Cover Download Script (Kartograf 0.6.1)")
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
