"""Soil hydrological group (HSG) queries."""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_hsg_for_boundary(boundary_wkb_hex: str, db: Session) -> dict | None:
    """Get HSG statistics for a watershed boundary.

    Args:
        boundary_wkb_hex: Watershed boundary as WKB hex string (EPSG:2180).
        db: Database session.

    Returns:
        Dict with categories and dominant_group, or None if no data.
    """
    sql = text("""
        WITH watershed AS (
            SELECT ST_SetSRID(
                ST_GeomFromWKB(decode(:boundary_wkb, 'hex')),
                2180
            ) AS geom
        ),
        intersections AS (
            SELECT
                sh.hsg_group,
                ST_Area(ST_Intersection(sh.geom, w.geom)) AS intersection_area_m2
            FROM soil_hsg sh
            CROSS JOIN watershed w
            WHERE ST_Intersects(sh.geom, w.geom)
        ),
        grouped AS (
            SELECT
                hsg_group,
                SUM(intersection_area_m2) AS total_area_m2
            FROM intersections
            GROUP BY hsg_group
        )
        SELECT
            hsg_group,
            total_area_m2,
            total_area_m2 / NULLIF(SUM(total_area_m2) OVER (), 0) * 100 AS percentage
        FROM grouped
        ORDER BY total_area_m2 DESC
    """)

    result = db.execute(sql, {"boundary_wkb": boundary_wkb_hex}).fetchall()

    if not result:
        return None

    categories = []
    for row in result:
        categories.append(
            {
                "group": row.hsg_group,
                "area_m2": float(row.total_area_m2),
                "percentage": float(row.percentage),
            }
        )

    return {
        "categories": categories,
        "dominant_group": categories[0]["group"],
    }
