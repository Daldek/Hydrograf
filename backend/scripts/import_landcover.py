"""
Script to import land cover data from GeoPackage into PostgreSQL/PostGIS.

Reads BDOT10k or CORINE land cover data from GeoPackage files and imports
them into the land_cover table with appropriate CN (Curve Number) values
for hydrological calculations.

BDOT10k layer mapping to Hydrograf categories:
    PTLZ -> las (forest)
    PTTR -> grunt_orny (arable land)
    PTUT -> grunt_orny (permanent crops)
    PTWP -> woda (water)
    PTWZ -> łąka (wetlands)
    PTRK -> łąka (shrubs)
    PTZB -> zabudowa_mieszkaniowa (buildings)
    PTKM -> droga (roads)
    PTPL -> droga (squares)
    PTGN -> inny (unused land)
    PTNZ -> inny (undeveloped)
    PTSO -> inny (dumps)

Usage
-----
    cd backend
    python -m scripts.import_landcover --help
    python -m scripts.import_landcover --input ../data/landcover/bdot10k_teryt_1465.gpkg

Examples
--------
    # Import BDOT10k data
    python -m scripts.import_landcover \\
        --input ../data/landcover/bdot10k_teryt_1465.gpkg

    # Dry run (show what would be imported)
    python -m scripts.import_landcover \\
        --input ../data/landcover/bdot10k_teryt_1465.gpkg \\
        --dry-run

    # Clear existing data before import
    python -m scripts.import_landcover \\
        --input ../data/landcover/bdot10k_teryt_1465.gpkg \\
        --clear-existing
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import geopandas

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# BDOT10k layer codes (PT* = Pokrycie Terenu)
BDOT10K_LAYERS = [
    "PTGN",  # Grunty nieużytkowe (unused land)
    "PTKM",  # Tereny komunikacyjne (roads, transport)
    "PTLZ",  # Tereny leśne (forests)
    "PTNZ",  # Tereny niezabudowane (undeveloped)
    "PTPL",  # Place (squares)
    "PTRK",  # Roślinność krzewiasta (shrubs)
    "PTSO",  # Składowiska (dumps)
    "PTTR",  # Tereny rolne (arable land)
    "PTUT",  # Uprawy trwałe (permanent crops)
    "PTWP",  # Wody powierzchniowe (surface water)
    "PTWZ",  # Tereny zabagnione (wetlands)
    "PTZB",  # Tereny zabudowane (buildings)
]

# Mapping BDOT10k classes to Hydrograf categories with CN values
# CN values for AMC-II (average antecedent moisture condition)
BDOT10K_MAPPING: dict[str, tuple[str, int, float]] = {
    # bdot_class: (category, cn_value, imperviousness)
    "PTLZ": ("las", 60, 0.0),
    "PTTR": ("grunt_orny", 78, 0.1),
    "PTUT": ("grunt_orny", 78, 0.1),
    "PTWP": ("woda", 100, 1.0),
    "PTWZ": ("łąka", 70, 0.0),
    "PTRK": ("łąka", 70, 0.0),
    "PTZB": ("zabudowa_mieszkaniowa", 85, 0.5),
    "PTKM": ("droga", 98, 0.95),
    "PTPL": ("droga", 98, 0.95),
    "PTGN": ("inny", 75, 0.2),
    "PTNZ": ("inny", 75, 0.2),
    "PTSO": ("inny", 75, 0.2),
}

# Default values for unknown classes
DEFAULT_MAPPING = ("inny", 75, 0.2)


def get_database_url() -> str:
    """Get database URL from environment or config."""
    # Try environment variable first
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return db_url

    # Try config file
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from core.config import settings

        return settings.database_url
    except ImportError:
        pass

    # Default for local development
    return "postgresql://hydro_user:hydro_pass@localhost:5432/hydro_db"


def read_gpkg_layers(gpkg_path: Path) -> dict[str, "geopandas.GeoDataFrame"]:
    """
    Read all land cover layers from a GeoPackage file.

    Parameters
    ----------
    gpkg_path : Path
        Path to the GeoPackage file

    Returns
    -------
    Dict[str, GeoDataFrame]
        Dictionary mapping layer names to GeoDataFrames
    """
    import fiona
    import geopandas as gpd

    layers = {}

    # List available layers
    available_layers = fiona.listlayers(gpkg_path)
    logger.info(f"Available layers in GeoPackage: {available_layers}")

    # Read each PT* layer
    for layer_name in available_layers:
        # Check if it's a BDOT10k land cover layer
        layer_code = layer_name.upper()
        if layer_code in BDOT10K_LAYERS or layer_name.startswith("PT"):
            try:
                gdf = gpd.read_file(gpkg_path, layer=layer_name)
                if len(gdf) > 0:
                    layers[layer_code] = gdf
                    logger.info(f"  {layer_code}: {len(gdf)} features")
            except Exception as e:
                logger.warning(f"  {layer_code}: failed to read - {e}")

    return layers


def transform_to_2180(gdf: "geopandas.GeoDataFrame") -> "geopandas.GeoDataFrame":
    """
    Transform GeoDataFrame to EPSG:2180 (PL-1992) if needed.

    Parameters
    ----------
    gdf : GeoDataFrame
        Input GeoDataFrame

    Returns
    -------
    GeoDataFrame
        GeoDataFrame in EPSG:2180
    """
    if gdf.crs is None:
        logger.warning("No CRS defined, assuming EPSG:2180")
        gdf = gdf.set_crs("EPSG:2180")
    elif gdf.crs.to_epsg() != 2180:
        logger.info(f"Transforming from {gdf.crs} to EPSG:2180")
        gdf = gdf.to_crs("EPSG:2180")
    return gdf


def prepare_records(
    layers: dict[str, "geopandas.GeoDataFrame"],
) -> list[dict]:
    """
    Prepare database records from GeoDataFrames.

    Parameters
    ----------
    layers : Dict[str, GeoDataFrame]
        Dictionary mapping layer codes to GeoDataFrames

    Returns
    -------
    List[Dict]
        List of records ready for database insertion
    """
    from shapely import wkb

    records = []

    for layer_code, gdf in layers.items():
        # Get mapping for this layer
        category, cn_value, imperviousness = BDOT10K_MAPPING.get(
            layer_code, DEFAULT_MAPPING
        )

        # Transform to EPSG:2180
        gdf = transform_to_2180(gdf)

        for _idx, row in gdf.iterrows():
            geom = row.geometry

            # Skip invalid geometries
            if geom is None or geom.is_empty:
                continue

            # Ensure MultiPolygon type
            if geom.geom_type == "Polygon":
                from shapely.geometry import MultiPolygon

                geom = MultiPolygon([geom])
            elif geom.geom_type != "MultiPolygon":
                logger.warning(f"Skipping non-polygon geometry: {geom.geom_type}")
                continue

            # Validate geometry
            if not geom.is_valid:
                geom = geom.buffer(0)  # Fix invalid geometry
                if not geom.is_valid:
                    logger.warning(f"Skipping invalid geometry in {layer_code}")
                    continue

            records.append(
                {
                    "geom_wkb": wkb.dumps(geom, include_srid=False),
                    "category": category,
                    "cn_value": cn_value,
                    "imperviousness": imperviousness,
                    "bdot_class": layer_code,
                }
            )

    return records


def import_to_database(
    records: list[dict],
    database_url: str,
    batch_size: int = 1000,
    clear_existing: bool = False,
) -> int:
    """
    Import records into the land_cover table.

    Parameters
    ----------
    records : List[Dict]
        Records to import
    database_url : str
        Database connection URL
    batch_size : int
        Number of records per batch
    clear_existing : bool
        If True, clear existing data before import

    Returns
    -------
    int
        Number of records inserted
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(database_url)

    with engine.connect() as conn:
        # Clear existing data if requested
        if clear_existing:
            logger.info("Clearing existing land_cover data...")
            conn.execute(text("TRUNCATE TABLE land_cover RESTART IDENTITY CASCADE"))
            conn.commit()

        # Insert records in batches
        inserted = 0

        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]

            # Build INSERT statement
            values = []
            params = {}

            for j, rec in enumerate(batch):
                param_prefix = f"p{j}_"
                values.append(
                    f"(ST_SetSRID(ST_GeomFromWKB(:{param_prefix}geom), 2180), "
                    f":{param_prefix}category, :{param_prefix}cn_value, "
                    f":{param_prefix}imperviousness, :{param_prefix}bdot_class)"
                )
                params[f"{param_prefix}geom"] = rec["geom_wkb"]
                params[f"{param_prefix}category"] = rec["category"]
                params[f"{param_prefix}cn_value"] = rec["cn_value"]
                params[f"{param_prefix}imperviousness"] = rec["imperviousness"]
                params[f"{param_prefix}bdot_class"] = rec["bdot_class"]

            sql = f"""
                INSERT INTO land_cover (geom, category, cn_value, imperviousness, bdot_class)
                VALUES {", ".join(values)}
            """

            conn.execute(text(sql), params)
            conn.commit()

            inserted += len(batch)
            logger.info(f"  Inserted {inserted}/{len(records)} records")

    return inserted


def import_landcover(
    input_path: Path,
    database_url: str | None = None,
    batch_size: int = 1000,
    dry_run: bool = False,
    clear_existing: bool = False,
) -> dict:
    """
    Import land cover data from GeoPackage to database.

    Parameters
    ----------
    input_path : Path
        Path to GeoPackage file
    database_url : str, optional
        Database connection URL (default: from config)
    batch_size : int
        Records per batch
    dry_run : bool
        If True, only show what would be done
    clear_existing : bool
        If True, clear existing data before import

    Returns
    -------
    Dict
        Import statistics
    """
    stats = {
        "layers_read": 0,
        "features_total": 0,
        "records_prepared": 0,
        "records_inserted": 0,
    }

    # Read GeoPackage layers
    logger.info(f"Reading GeoPackage: {input_path}")
    layers = read_gpkg_layers(input_path)

    stats["layers_read"] = len(layers)
    stats["features_total"] = sum(len(gdf) for gdf in layers.values())

    logger.info(
        f"Read {stats['layers_read']} layers, {stats['features_total']} features"
    )

    if stats["features_total"] == 0:
        logger.warning("No features found to import!")
        return stats

    # Prepare records
    logger.info("Preparing records for database...")
    records = prepare_records(layers)
    stats["records_prepared"] = len(records)

    logger.info(f"Prepared {len(records)} records")

    # Show category distribution
    from collections import Counter

    categories = Counter(r["category"] for r in records)
    logger.info("Category distribution:")
    for cat, count in sorted(categories.items()):
        logger.info(f"  {cat}: {count}")

    if dry_run:
        logger.info("DRY RUN - no data will be imported")
        return stats

    # Import to database
    if database_url is None:
        database_url = get_database_url()

    logger.info("Importing to database...")
    stats["records_inserted"] = import_to_database(
        records=records,
        database_url=database_url,
        batch_size=batch_size,
        clear_existing=clear_existing,
    )

    return stats


def main():
    """Main entry point for land cover import script."""
    parser = argparse.ArgumentParser(
        description="Import land cover data from GeoPackage to PostgreSQL/PostGIS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Input
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        required=True,
        help="Path to GeoPackage file (.gpkg)",
    )

    # Options
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Records per database batch (default: 1000)",
    )
    parser.add_argument(
        "--clear-existing",
        action="store_true",
        help="Clear existing land_cover data before import",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show what would be imported",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    # Log configuration
    logger.info("=" * 60)
    logger.info("Land Cover Import Script")
    logger.info("=" * 60)
    logger.info(f"Input: {input_path}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Clear existing: {args.clear_existing}")
    logger.info("=" * 60)

    # Run import
    start_time = time.time()

    try:
        stats = import_landcover(
            input_path=input_path,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            clear_existing=args.clear_existing,
        )
    except ImportError as e:
        logger.error(f"Missing dependency: {e}")
        logger.error("Install with: pip install geopandas fiona")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Import failed: {e}")
        sys.exit(1)

    elapsed = time.time() - start_time

    # Summary
    logger.info("=" * 60)
    logger.info("Import complete!")
    logger.info("=" * 60)
    logger.info(f"  Layers read: {stats['layers_read']}")
    logger.info(f"  Features total: {stats['features_total']}")
    logger.info(f"  Records prepared: {stats['records_prepared']}")
    logger.info(f"  Records inserted: {stats['records_inserted']}")
    logger.info(f"  Time elapsed: {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
