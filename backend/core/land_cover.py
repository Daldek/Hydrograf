"""
Land cover analysis for CN (Curve Number) calculation.

Provides functions to calculate area-weighted CN from the land_cover table
using spatial intersection with watershed boundary.

The CN (Curve Number) is used in the SCS-CN method for estimating
direct runoff from rainfall.
"""

import logging
from typing import Dict, Optional, Tuple

from shapely.geometry import Polygon
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Default CN if land cover data unavailable (average condition)
DEFAULT_CN = 75

# Valid land cover categories (from database constraint)
VALID_CATEGORIES = frozenset([
    "las",
    "łąka",
    "grunt_orny",
    "zabudowa_mieszkaniowa",
    "zabudowa_przemysłowa",
    "droga",
    "woda",
    "inny",
])


def calculate_weighted_cn(
    boundary: Polygon,
    db: Session,
) -> Tuple[int, Dict[str, float]]:
    """
    Calculate area-weighted CN from land cover data.

    Performs spatial intersection between watershed boundary and land_cover
    table, then calculates area-weighted average CN.

    Parameters
    ----------
    boundary : Polygon
        Watershed boundary polygon in EPSG:2180
    db : Session
        Database session

    Returns
    -------
    Tuple[int, Dict[str, float]]
        - weighted_cn: Area-weighted CN value (0-100)
        - land_cover_stats: Dictionary with category percentages

    Examples
    --------
    >>> cn, stats = calculate_weighted_cn(boundary, db)
    >>> print(f"CN = {cn}, Forest: {stats.get('las', 0):.1f}%")
    CN = 72, Forest: 45.2%

    Notes
    -----
    If no land cover data is found for the watershed area, returns
    (DEFAULT_CN, {}) and logs a warning.

    The CN calculation uses the formula:
        weighted_cn = sum(cn_i * area_i) / total_area
    where cn_i is the CN value for category i and area_i is the
    intersection area of that category with the watershed.
    """
    if not boundary.is_valid:
        logger.warning("Invalid boundary polygon, using default CN")
        return (DEFAULT_CN, {})

    # Convert boundary to WKB hex for SQL
    boundary_wkb = boundary.wkb_hex

    query = text("""
        WITH watershed AS (
            SELECT ST_SetSRID(
                ST_GeomFromWKB(decode(:boundary_wkb, 'hex')),
                2180
            ) AS geom
        ),
        intersections AS (
            SELECT
                lc.category,
                lc.cn_value,
                ST_Area(ST_Intersection(lc.geom, w.geom)) AS intersection_area_m2
            FROM land_cover lc
            CROSS JOIN watershed w
            WHERE ST_Intersects(lc.geom, w.geom)
        )
        SELECT
            category,
            cn_value,
            SUM(intersection_area_m2) AS total_area_m2
        FROM intersections
        GROUP BY category, cn_value
        ORDER BY total_area_m2 DESC
    """)

    try:
        result = db.execute(query, {"boundary_wkb": boundary_wkb}).fetchall()
    except Exception as e:
        logger.error(f"Database error calculating CN: {e}")
        return (DEFAULT_CN, {})

    if not result:
        logger.warning("No land cover data found for watershed, using default CN")
        return (DEFAULT_CN, {})

    # Calculate weighted CN
    total_area = sum(row.total_area_m2 for row in result)

    if total_area <= 0:
        logger.warning("Zero total area from land cover intersection, using default CN")
        return (DEFAULT_CN, {})

    weighted_cn_sum = sum(row.cn_value * row.total_area_m2 for row in result)
    weighted_cn = round(weighted_cn_sum / total_area)

    # Clamp to valid range 0-100
    weighted_cn = max(0, min(100, weighted_cn))

    # Build stats dictionary with category percentages
    land_cover_stats: Dict[str, float] = {}
    for row in result:
        category = row.category
        percentage = (row.total_area_m2 / total_area) * 100
        if category in land_cover_stats:
            land_cover_stats[category] += percentage
        else:
            land_cover_stats[category] = percentage

    # Round percentages
    land_cover_stats = {k: round(v, 1) for k, v in land_cover_stats.items()}

    logger.info(
        f"Calculated CN={weighted_cn} from {len(result)} land cover categories "
        f"(total area: {total_area/1e6:.2f} km²)"
    )

    return (weighted_cn, land_cover_stats)


def get_land_cover_for_boundary(
    boundary: Polygon,
    db: Session,
) -> Optional[Dict]:
    """
    Get detailed land cover information for a watershed boundary.

    Parameters
    ----------
    boundary : Polygon
        Watershed boundary polygon in EPSG:2180
    db : Session
        Database session

    Returns
    -------
    Optional[Dict]
        Dictionary with land cover details:
        - categories: List of category stats
        - total_area_m2: Total intersection area
        - weighted_cn: Calculated CN
        - weighted_imperviousness: Weighted imperviousness fraction

        Returns None if no land cover data is found.
    """
    if not boundary.is_valid:
        return None

    boundary_wkb = boundary.wkb_hex

    query = text("""
        WITH watershed AS (
            SELECT ST_SetSRID(
                ST_GeomFromWKB(decode(:boundary_wkb, 'hex')),
                2180
            ) AS geom
        ),
        intersections AS (
            SELECT
                lc.category,
                lc.cn_value,
                lc.imperviousness,
                lc.bdot_class,
                ST_Area(ST_Intersection(lc.geom, w.geom)) AS intersection_area_m2
            FROM land_cover lc
            CROSS JOIN watershed w
            WHERE ST_Intersects(lc.geom, w.geom)
        )
        SELECT
            category,
            cn_value,
            imperviousness,
            SUM(intersection_area_m2) AS total_area_m2
        FROM intersections
        GROUP BY category, cn_value, imperviousness
        ORDER BY total_area_m2 DESC
    """)

    try:
        result = db.execute(query, {"boundary_wkb": boundary_wkb}).fetchall()
    except Exception as e:
        logger.error(f"Database error getting land cover: {e}")
        return None

    if not result:
        return None

    total_area = sum(row.total_area_m2 for row in result)

    if total_area <= 0:
        return None

    # Calculate weighted values
    weighted_cn_sum = sum(row.cn_value * row.total_area_m2 for row in result)
    weighted_imperv_sum = sum(
        (row.imperviousness or 0) * row.total_area_m2 for row in result
    )

    weighted_cn = round(weighted_cn_sum / total_area)
    weighted_imperviousness = weighted_imperv_sum / total_area

    # Build category details
    categories = []
    for row in result:
        categories.append({
            "category": row.category,
            "cn_value": row.cn_value,
            "imperviousness": row.imperviousness,
            "area_m2": round(row.total_area_m2, 1),
            "percentage": round((row.total_area_m2 / total_area) * 100, 1),
        })

    return {
        "categories": categories,
        "total_area_m2": round(total_area, 1),
        "weighted_cn": weighted_cn,
        "weighted_imperviousness": round(weighted_imperviousness, 3),
    }
