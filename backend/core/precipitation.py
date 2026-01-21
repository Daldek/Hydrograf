"""
Precipitation data retrieval module.

Provides functions to query precipitation data from the local database
with spatial interpolation for points not directly on the grid.
"""

import logging
from typing import Optional

from shapely.geometry import Point
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Valid duration values
VALID_DURATIONS_MIN = {15, 30, 60, 120, 360, 720, 1440}
VALID_DURATIONS_STR = {"15min", "30min", "1h", "2h", "6h", "12h", "24h"}

# Valid probability values
VALID_PROBABILITIES = {1, 2, 5, 10, 20, 50}

# Duration mapping: minutes -> database string
DURATION_MIN_TO_STR = {
    15: "15min",
    30: "30min",
    60: "1h",
    120: "2h",
    360: "6h",
    720: "12h",
    1440: "24h",
}

# Duration mapping: string -> minutes
DURATION_STR_TO_MIN = {v: k for k, v in DURATION_MIN_TO_STR.items()}


def validate_duration(duration: int | str) -> str:
    """
    Validate and normalize duration parameter.

    Parameters
    ----------
    duration : int | str
        Duration in minutes (15, 30, 60, 120, 360, 720, 1440)
        or as string ('15min', '30min', '1h', '2h', '6h', '12h', '24h')

    Returns
    -------
    str
        Normalized duration string for database query

    Raises
    ------
    ValueError
        If duration is invalid
    """
    if isinstance(duration, int):
        if duration not in VALID_DURATIONS_MIN:
            raise ValueError(
                f"Invalid duration: {duration}. " f"Must be one of {sorted(VALID_DURATIONS_MIN)}"
            )
        return DURATION_MIN_TO_STR[duration]

    if isinstance(duration, str):
        if duration not in VALID_DURATIONS_STR:
            raise ValueError(
                f"Invalid duration: {duration}. " f"Must be one of {sorted(VALID_DURATIONS_STR)}"
            )
        return duration

    raise ValueError(f"Duration must be int or str, got {type(duration)}")


def validate_probability(probability: int) -> int:
    """
    Validate probability parameter.

    Parameters
    ----------
    probability : int
        Exceedance probability [%]: 1, 2, 5, 10, 20, 50

    Returns
    -------
    int
        Validated probability

    Raises
    ------
    ValueError
        If probability is invalid
    """
    if probability not in VALID_PROBABILITIES:
        raise ValueError(
            f"Invalid probability: {probability}. " f"Must be one of {sorted(VALID_PROBABILITIES)}"
        )
    return probability


def get_precipitation(
    centroid: Point,
    duration: int | str,
    probability: int,
    db: Session,
) -> Optional[float]:
    """
    Get interpolated precipitation value for a point.

    Uses Inverse Distance Weighting (IDW) interpolation from
    the 4 nearest grid points in the database.

    Parameters
    ----------
    centroid : Point
        Query point in EPSG:2180 (PL-1992)
    duration : int | str
        Rainfall duration in minutes (15, 30, 60, 120, 360, 720, 1440)
        or as string ('15min', '30min', '1h', '2h', '6h', '12h', '24h')
    probability : int
        Exceedance probability [%]: 1, 2, 5, 10, 20, 50
    db : Session
        SQLAlchemy database session

    Returns
    -------
    float | None
        Interpolated precipitation [mm], or None if no data found

    Raises
    ------
    ValueError
        If duration or probability is invalid

    Examples
    --------
    >>> from shapely.geometry import Point
    >>> centroid = Point(500000, 600000)  # PL-1992
    >>> precip = get_precipitation(centroid, 60, 10, db)
    >>> print(f"P(1h, 10%) = {precip:.1f} mm")
    P(1h, 10%) = 38.5 mm
    """
    duration_str = validate_duration(duration)
    probability = validate_probability(probability)

    # IDW interpolation query
    # Uses 4 nearest points to interpolate value
    # Adding small epsilon (0.001) to avoid division by zero
    query = text(
        """
        WITH nearest AS (
            SELECT
                precipitation_mm,
                ST_Distance(geom, ST_SetSRID(ST_Point(:x, :y), 2180)) as dist
            FROM precipitation_data
            WHERE duration = :duration
              AND probability = :probability
            ORDER BY geom <-> ST_SetSRID(ST_Point(:x, :y), 2180)
            LIMIT 4
        )
        SELECT
            CASE
                WHEN MIN(dist) < 0.001 THEN
                    (SELECT precipitation_mm FROM nearest WHERE dist < 0.001 LIMIT 1)
                ELSE
                    SUM(precipitation_mm / POWER(dist + 0.001, 2)) /
                    SUM(1 / POWER(dist + 0.001, 2))
            END as precipitation_interpolated
        FROM nearest
        WHERE dist IS NOT NULL
    """
    )

    result = db.execute(
        query,
        {
            "x": centroid.x,
            "y": centroid.y,
            "duration": duration_str,
            "probability": probability,
        },
    ).fetchone()

    if result is None or result.precipitation_interpolated is None:
        logger.warning(
            f"No precipitation data found for point ({centroid.x}, {centroid.y}), "
            f"duration={duration_str}, probability={probability}%"
        )
        return None

    return float(result.precipitation_interpolated)


def get_precipitation_wgs84(
    latitude: float,
    longitude: float,
    duration: int | str,
    probability: int,
    db: Session,
) -> Optional[float]:
    """
    Get interpolated precipitation value for WGS84 coordinates.

    Convenience function that handles coordinate transformation.

    Parameters
    ----------
    latitude : float
        Latitude in WGS84 (decimal degrees)
    longitude : float
        Longitude in WGS84 (decimal degrees)
    duration : int | str
        Rainfall duration (see get_precipitation)
    probability : int
        Exceedance probability [%]
    db : Session
        SQLAlchemy database session

    Returns
    -------
    float | None
        Interpolated precipitation [mm], or None if no data found

    Examples
    --------
    >>> precip = get_precipitation_wgs84(52.23, 21.01, "1h", 10, db)
    >>> print(f"P = {precip:.1f} mm")
    """
    from pyproj import Transformer

    # Transform WGS84 -> PL-1992
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True)
    x, y = transformer.transform(longitude, latitude)

    centroid = Point(x, y)
    return get_precipitation(centroid, duration, probability, db)


def get_all_scenarios(
    centroid: Point,
    db: Session,
) -> dict:
    """
    Get precipitation values for all 42 scenarios.

    Parameters
    ----------
    centroid : Point
        Query point in EPSG:2180 (PL-1992)
    db : Session
        SQLAlchemy database session

    Returns
    -------
    dict
        Nested dict: {duration_str: {probability: precipitation_mm}}

    Examples
    --------
    >>> scenarios = get_all_scenarios(centroid, db)
    >>> print(scenarios["1h"][10])  # P(1h, 10%)
    38.5
    """
    result = {}

    for duration_str in VALID_DURATIONS_STR:
        result[duration_str] = {}
        for probability in VALID_PROBABILITIES:
            precip = get_precipitation(centroid, duration_str, probability, db)
            result[duration_str][probability] = precip

    return result


def check_data_coverage(
    bbox: tuple,
    db: Session,
) -> dict:
    """
    Check precipitation data coverage for a bounding box.

    Parameters
    ----------
    bbox : tuple
        (min_x, min_y, max_x, max_y) in EPSG:2180
    db : Session
        SQLAlchemy database session

    Returns
    -------
    dict
        Coverage statistics
    """
    min_x, min_y, max_x, max_y = bbox

    query = text(
        """
        SELECT
            COUNT(DISTINCT geom) as point_count,
            COUNT(*) as total_records,
            COUNT(*) / NULLIF(COUNT(DISTINCT geom), 0) as scenarios_per_point
        FROM precipitation_data
        WHERE ST_Within(
            geom,
            ST_MakeEnvelope(:min_x, :min_y, :max_x, :max_y, 2180)
        )
    """
    )

    result = db.execute(
        query,
        {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y},
    ).fetchone()

    return {
        "point_count": result.point_count or 0,
        "total_records": result.total_records or 0,
        "scenarios_per_point": result.scenarios_per_point or 0,
        "expected_scenarios": 42,
        "coverage_complete": (result.scenarios_per_point or 0) == 42,
    }
