"""
Script to download IMGW PMAXTP precipitation data and store in PostgreSQL.

Downloads maximum precipitation data for a grid of points within specified
bounding box and stores all 42 scenarios (7 durations x 6 probabilities)
in the precipitation_data table.

Usage
-----
    cd backend
    python -m scripts.preprocess_precipitation --help
    python -m scripts.preprocess_precipitation \\
        --bbox "19.5,51.5,20.5,52.5" \\
        --spacing 2.0

Examples
--------
    # Download data for Warsaw area (small test)
    python -m scripts.preprocess_precipitation \\
        --bbox "20.8,52.1,21.2,52.4" \\
        --spacing 5.0

    # Full municipality preprocessing
    python -m scripts.preprocess_precipitation \\
        --bbox "19.5,51.5,20.5,52.5" \\
        --spacing 2.0 \\
        --delay 0.5
"""

import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime

from pyproj import Transformer
from sqlalchemy import text

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Rainfall scenarios according to SCOPE.md
DURATIONS = ["15min", "30min", "1h", "2h", "6h", "12h", "24h"]
DURATION_MINUTES = [15, 30, 60, 120, 360, 720, 1440]
PROBABILITIES = [1, 2, 5, 10, 20, 50]

# Coordinate transformer: WGS84 -> PL-1992
WGS84_TO_PL1992 = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True)


def parse_bbox(bbox_str: str) -> tuple[float, float, float, float]:
    """
    Parse bounding box string.

    Parameters
    ----------
    bbox_str : str
        Bounding box as "min_lon,min_lat,max_lon,max_lat"

    Returns
    -------
    tuple
        (min_lon, min_lat, max_lon, max_lat)

    Raises
    ------
    ValueError
        If bbox format is invalid
    """
    try:
        parts = [float(x.strip()) for x in bbox_str.split(",")]
        if len(parts) != 4:
            raise ValueError("Expected 4 values")
        min_lon, min_lat, max_lon, max_lat = parts

        # Validate coordinates for Poland
        if not (14.0 <= min_lon <= 24.2 and 14.0 <= max_lon <= 24.2):
            raise ValueError("Longitude must be between 14.0 and 24.2 (Poland)")
        if not (49.0 <= min_lat <= 54.9 and 49.0 <= max_lat <= 54.9):
            raise ValueError("Latitude must be between 49.0 and 54.9 (Poland)")
        if min_lon >= max_lon or min_lat >= max_lat:
            raise ValueError("min values must be less than max values")

        return min_lon, min_lat, max_lon, max_lat
    except Exception as e:
        raise ValueError(f"Invalid bbox format: {e}") from e


def generate_grid_points(
    bbox: tuple[float, float, float, float],
    spacing_km: float,
) -> list[tuple[float, float]]:
    """
    Generate a grid of points within bounding box.

    Parameters
    ----------
    bbox : tuple
        (min_lon, min_lat, max_lon, max_lat) in WGS84
    spacing_km : float
        Distance between grid points [km]

    Returns
    -------
    list
        List of (lat, lon) tuples in WGS84
    """
    min_lon, min_lat, max_lon, max_lat = bbox

    # Approximate degrees per km at Poland's latitude (~52°N)
    # 1 degree latitude ≈ 111 km
    # 1 degree longitude ≈ 111 * cos(52°) ≈ 68 km
    lat_step = spacing_km / 111.0
    lon_step = spacing_km / 68.0

    points = []
    lat = min_lat
    while lat <= max_lat:
        lon = min_lon
        while lon <= max_lon:
            points.append((lat, lon))
            lon += lon_step
        lat += lat_step

    return points


async def fetch_pmaxtp_for_point(
    lat: float,
    lon: float,
    delay_s: float = 0.5,
) -> dict:
    """
    Fetch all 42 precipitation scenarios for a single point.

    Parameters
    ----------
    lat : float
        Latitude (WGS84)
    lon : float
        Longitude (WGS84)
    delay_s : float
        Delay after request to avoid rate limiting

    Returns
    -------
    dict
        {(duration_str, probability): precipitation_mm}
    """
    try:
        from imgwtools import fetch_pmaxtp
    except ImportError:
        logger.error("imgwtools not installed. Run: pip install imgwtools")
        raise

    try:
        result = fetch_pmaxtp(latitude=lat, longitude=lon)

        scenarios = {}
        for duration_str, duration_min in zip(
            DURATIONS, DURATION_MINUTES, strict=False
        ):
            for prob in PROBABILITIES:
                precip = result.data.get_precipitation(duration_min, prob)
                scenarios[(duration_str, prob)] = precip

        # Rate limiting delay
        await asyncio.sleep(delay_s)

        return scenarios

    except Exception as e:
        logger.warning(f"Failed to fetch data for ({lat}, {lon}): {e}")
        return {}


def insert_precipitation_data(
    db_session,
    lat: float,
    lon: float,
    scenarios: dict,
) -> int:
    """
    Insert precipitation data for a point into database.

    Parameters
    ----------
    db_session : Session
        SQLAlchemy database session
    lat : float
        Latitude (WGS84)
    lon : float
        Longitude (WGS84)
    scenarios : dict
        {(duration_str, probability): precipitation_mm}

    Returns
    -------
    int
        Number of records inserted
    """
    # Transform to PL-1992
    x, y = WGS84_TO_PL1992.transform(lon, lat)

    count = 0
    for (duration, probability), precipitation_mm in scenarios.items():
        if precipitation_mm is None:
            continue

        try:
            db_session.execute(
                text("""
                    INSERT INTO precipitation_data
                        (geom, duration, probability,
                         precipitation_mm, source, updated_at)
                    VALUES
                        (ST_SetSRID(ST_Point(:x, :y), 2180), :duration, :probability,
                         :precipitation_mm, 'IMGW_PMAXTP', :updated_at)
                    ON CONFLICT (geom, duration, probability)
                    DO UPDATE SET
                        precipitation_mm = EXCLUDED.precipitation_mm,
                        updated_at = EXCLUDED.updated_at
                """),
                {
                    "x": x,
                    "y": y,
                    "duration": duration,
                    "probability": probability,
                    "precipitation_mm": precipitation_mm,
                    "updated_at": datetime.utcnow(),
                },
            )
            count += 1
        except Exception as e:
            logger.error(
                f"Failed to insert ({lat}, {lon}, {duration}, {probability}): {e}"
            )

    return count


async def process_grid(
    bbox: tuple[float, float, float, float],
    spacing_km: float,
    delay_s: float,
) -> tuple[int, int, int]:
    """
    Process entire grid of points.

    Parameters
    ----------
    bbox : tuple
        Bounding box (min_lon, min_lat, max_lon, max_lat)
    spacing_km : float
        Grid spacing [km]
    delay_s : float
        Delay between API requests [s]

    Returns
    -------
    tuple
        (total_points, successful_points, total_records)
    """
    # Import here to avoid issues when imgwtools not installed
    from core.database import get_db_session

    points = generate_grid_points(bbox, spacing_km)
    total_points = len(points)

    logger.info(f"Generated {total_points} grid points with {spacing_km} km spacing")
    logger.info(f"Bounding box: {bbox}")
    logger.info(f"Expected records: {total_points * 42} (42 scenarios per point)")

    successful_points = 0
    total_records = 0

    with get_db_session() as db:
        for i, (lat, lon) in enumerate(points, 1):
            logger.info(f"Processing point {i}/{total_points}: ({lat:.4f}, {lon:.4f})")

            scenarios = await fetch_pmaxtp_for_point(lat, lon, delay_s)

            if scenarios:
                records = insert_precipitation_data(db, lat, lon, scenarios)
                total_records += records
                successful_points += 1

                if i % 10 == 0:
                    db.commit()
                    logger.info(f"Committed batch. Progress: {i}/{total_points}")

        # Final commit
        db.commit()

    return total_points, successful_points, total_records


def main():
    """Main entry point for preprocessing script."""
    parser = argparse.ArgumentParser(
        description="Download IMGW PMAXTP precipitation data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--bbox",
        type=str,
        required=True,
        help="Bounding box: min_lon,min_lat,max_lon,max_lat (WGS84)",
    )
    parser.add_argument(
        "--spacing",
        type=float,
        default=2.0,
        help="Grid spacing in km (default: 2.0)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Delay between API requests in seconds (default: 0.5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only show grid points without downloading",
    )

    args = parser.parse_args()

    try:
        bbox = parse_bbox(args.bbox)
    except ValueError as e:
        logger.error(f"Invalid bounding box: {e}")
        sys.exit(1)

    if args.dry_run:
        points = generate_grid_points(bbox, args.spacing)
        logger.info(f"Dry run: would process {len(points)} points")
        logger.info(f"Expected records: {len(points) * 42}")
        for i, (lat, lon) in enumerate(points[:10], 1):
            logger.info(f"  Point {i}: ({lat:.4f}, {lon:.4f})")
        if len(points) > 10:
            logger.info(f"  ... and {len(points) - 10} more points")
        return

    logger.info("=" * 60)
    logger.info("IMGW PMAXTP Precipitation Data Preprocessing")
    logger.info("=" * 60)

    start_time = time.time()

    try:
        total, successful, records = asyncio.run(
            process_grid(bbox, args.spacing, args.delay)
        )
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Preprocessing failed: {e}")
        sys.exit(1)

    elapsed = time.time() - start_time

    logger.info("=" * 60)
    logger.info("Preprocessing complete!")
    logger.info(f"  Total points: {total}")
    logger.info(f"  Successful: {successful}")
    logger.info(f"  Records inserted: {records}")
    logger.info(f"  Time elapsed: {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
