"""
The command ``depressions list`` (ADR-091).

Terrain depressions (blue spots), filtered by volume and area.
"""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from api.envelope import Outcome
from core.errors import InternalError
from models.schemas import DepressionsQuery, DepressionsResponse

logger = logging.getLogger(__name__)


def list_depressions(options: DepressionsQuery, db: Session) -> Outcome:
    """
    Get terrain depressions as a GeoJSON FeatureCollection: ``depressions list``.

    Returns depressions filtered by volume and area ranges, optionally within a
    bounding box (a malformed one is ignored), at most 500, the largest first.

    Parameters
    ----------
    options : DepressionsQuery
        The ranges of volume [m3] and area [m2] and the bounding box (WGS84).
    db : Session
        Database session

    Returns
    -------
    Outcome
        ``DepressionsResponse`` and ``Cache-Control: public, max-age=3600``.
    """
    try:
        # SECURITY: All conditions use parameterized values (:param_name).
        # Never add user-controlled column/table names to this list.
        conditions = [
            "d.volume_m3 >= :min_volume",
            "d.volume_m3 <= :max_volume",
            "d.area_m2 >= :min_area",
            "d.area_m2 <= :max_area",
        ]
        params: dict[str, Any] = {
            "min_volume": options.min_volume,
            "max_volume": options.max_volume,
            "min_area": options.min_area,
            "max_area": options.max_area,
        }

        if options.bbox:
            parts = options.bbox.split(",")
            if len(parts) == 4:
                try:
                    minlon, minlat, maxlon, maxlat = [float(p) for p in parts]
                    conditions.append(
                        "ST_Intersects(d.geom, ST_Transform("
                        "ST_MakeEnvelope(:minlon, :minlat,"
                        " :maxlon, :maxlat, 4326), 2180))"
                    )
                    params.update(
                        {
                            "minlon": minlon,
                            "minlat": minlat,
                            "maxlon": maxlon,
                            "maxlat": maxlat,
                        }
                    )
                except ValueError:
                    pass

        where_clause = " AND ".join(conditions)

        query = text(f"""
            SELECT
                d.id,
                d.volume_m3,
                d.area_m2,
                d.max_depth_m,
                d.mean_depth_m,
                ST_AsGeoJSON(ST_Transform(d.geom, 4326))::json AS geojson
            FROM depressions d
            WHERE {where_clause}
            ORDER BY d.volume_m3 DESC
            LIMIT 500
        """)

        result = db.execute(query, params).fetchall()

        features = []
        for row in result:
            features.append(
                {
                    "type": "Feature",
                    "geometry": row.geojson,
                    "properties": {
                        "id": row.id,
                        "volume_m3": round(row.volume_m3, 2),
                        "area_m2": round(row.area_m2, 1),
                        "max_depth_m": round(row.max_depth_m, 3),
                        "mean_depth_m": (
                            round(row.mean_depth_m, 3) if row.mean_depth_m else None
                        ),
                    },
                }
            )

        return Outcome(
            DepressionsResponse(type="FeatureCollection", features=features),
            cache_control="public, max-age=3600",
        )

    except Exception as e:
        logger.error(f"Error fetching depressions: {e}", exc_info=True)
        raise InternalError(
            "depressions_failed", reason="depressions_query_failed"
        ) from e
