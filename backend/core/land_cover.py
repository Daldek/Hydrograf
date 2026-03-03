"""
Land cover analysis for CN (Curve Number) calculation.

Provides functions to calculate area-weighted CN from the land_cover table
using spatial intersection with watershed boundary.

The CN (Curve Number) is used in the SCS-CN method for estimating
direct runoff from rainfall.
"""

import logging
from pathlib import Path
from typing import Any

from shapely.geometry import Polygon
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.constants import DEFAULT_CN  # re-exported for backwards compat

logger = logging.getLogger(__name__)

# Valid land cover categories (from database constraint)
VALID_CATEGORIES = frozenset(
    [
        "las",
        "łąka",
        "grunt_orny",
        "zabudowa_mieszkaniowa",
        "zabudowa_przemysłowa",
        "droga",
        "woda",
        "inny",
    ]
)


def calculate_weighted_cn(
    boundary: Polygon,
    db: Session,
) -> tuple[int, dict[str, float]]:
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
    land_cover_stats: dict[str, float] = {}
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
        f"(total area: {total_area / 1e6:.2f} km²)"
    )

    return (weighted_cn, land_cover_stats)


def get_land_cover_for_boundary(
    boundary: Polygon,
    db: Session,
) -> dict | None:
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
        categories.append(
            {
                "category": row.category,
                "cn_value": row.cn_value,
                "imperviousness": row.imperviousness,
                "area_m2": round(row.total_area_m2, 1),
                "percentage": round((row.total_area_m2 / total_area) * 100, 1),
            }
        )

    return {
        "categories": categories,
        "total_area_m2": round(total_area, 1),
        "weighted_cn": weighted_cn,
        "weighted_imperviousness": round(weighted_imperviousness, 3),
    }


def determine_cn(
    boundary: Polygon,
    db: Session,
    config_cn: int | None = None,
    default_cn: int = DEFAULT_CN,
    use_kartograf: bool = True,
    boundary_wgs84: list[list[float]] | None = None,
    data_dir: Path | None = None,
    teryt: str | None = None,
) -> tuple[int, str, dict[str, Any] | None]:
    """
    Okresl wartosc CN wedlug hierarchii zrodel.

    Hierarchia:
    1. Jawnie podana wartosc w konfiguracji (config_cn)
    2. Z tabeli land_cover w bazie danych
    3. Z Kartografa (HSG + land cover) - jesli use_kartograf=True
    4. Wartosc domyslna (default_cn)

    Parameters
    ----------
    boundary : Polygon
        Granica zlewni w EPSG:2180
    db : Session
        Sesja bazy danych
    config_cn : int, optional
        Wartosc CN z konfiguracji (najwyzszy priorytet)
    default_cn : int, optional
        Domyslna wartosc CN, domyslnie 75
    use_kartograf : bool, optional
        Czy uzywac Kartografa, domyslnie True
    boundary_wgs84 : List[List[float]], optional
        Granica w WGS84 (wymagana dla Kartografa)
    data_dir : Path, optional
        Katalog danych (wymagany dla Kartografa)

    Returns
    -------
    Tuple[int, str, Optional[Dict[str, Any]]]
        (cn_value, source, details)
        - cn_value: wartosc CN (0-100)
        - source: zrodlo ('config', 'database_land_cover', 'kartograf_hsg', 'default')
        - details: dodatkowe informacje (dla kartograf)

    Examples
    --------
    >>> cn, source, details = determine_cn(boundary, db, config_cn=80)
    >>> print(f"CN={cn} (zrodlo: {source})")
    CN=80 (zrodlo: config)

    >>> cn, source, details = determine_cn(boundary, db)
    >>> print(f"CN={cn} (zrodlo: {source})")
    CN=72 (zrodlo: database_land_cover)
    """
    # 1. Jawnie podana wartosc
    if config_cn is not None:
        logger.info(f"CN z konfiguracji: {config_cn}")
        return (config_cn, "config", None)

    # 2. Z tabeli land_cover w DB
    try:
        cn_value, land_cover_stats = calculate_weighted_cn(boundary, db)

        if land_cover_stats:  # Prawdziwe dane (nie DEFAULT_CN z braku danych)
            logger.info(f"CN z bazy danych (land_cover): {cn_value}")
            return (cn_value, "database_land_cover", {"stats": land_cover_stats})

    except Exception as e:
        logger.debug(f"Blad pobierania land_cover z bazy: {e}")

    # 3. Z Kartografa
    if use_kartograf and boundary_wgs84 and data_dir:
        from core.cn_calculator import calculate_cn_from_kartograf

        result = calculate_cn_from_kartograf(boundary_wgs84, data_dir, teryt=teryt)

        if result and result.cn:
            logger.info(f"CN z Kartografa (HSG={result.dominant_hsg}): {result.cn}")
            return (
                result.cn,
                "kartograf_hsg",
                {
                    "dominant_hsg": result.dominant_hsg,
                    "hsg_stats": result.hsg_stats,
                    "land_cover_stats": result.land_cover_stats,
                    "cn_details": result.cn_details,
                },
            )

    # 4. Wartosc domyslna
    logger.warning(f"Brak danych CN, uzyto wartosci domyslnej: {default_cn}")
    return (default_cn, "default", None)
