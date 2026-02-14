"""
Depressions (blue spots) endpoint.

Provides API endpoint for querying terrain depressions with
optional filtering by volume and area.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/depressions")
def get_depressions(
    response: Response,
    min_volume: float = Query(0, ge=0, description="Minimum volume [m3]"),
    max_volume: float = Query(1e9, ge=0, description="Maximum volume [m3]"),
    min_area: float = Query(100, ge=0, description="Minimum area [m2]"),
    max_area: float = Query(1e9, ge=0, description="Maximum area [m2]"),
    bbox: str | None = Query(
        None,
        description="Bounding box 'minlon,minlat,maxlon,maxlat' (WGS84)",
    ),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Get terrain depressions as GeoJSON FeatureCollection.

    Returns depressions filtered by volume and area ranges,
    optionally within a bounding box.

    Parameters
    ----------
    min_volume : float
        Minimum depression volume [m3]
    max_volume : float
        Maximum depression volume [m3]
    min_area : float
        Minimum depression area [m2]
    max_area : float
        Maximum depression area [m2]
    bbox : str, optional
        Bounding box in WGS84 (minlon,minlat,maxlon,maxlat)
    db : Session
        Database session

    Returns
    -------
    dict
        GeoJSON FeatureCollection with depression polygons
    """
    try:
        conditions = [
            "d.volume_m3 >= :min_volume",
            "d.volume_m3 <= :max_volume",
            "d.area_m2 >= :min_area",
            "d.area_m2 <= :max_area",
        ]
        params: dict[str, Any] = {
            "min_volume": min_volume,
            "max_volume": max_volume,
            "min_area": min_area,
            "max_area": max_area,
        }

        if bbox:
            parts = bbox.split(",")
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

        response.headers["Cache-Control"] = "public, max-age=3600"
        return {
            "type": "FeatureCollection",
            "features": features,
        }

    except Exception as e:
        logger.error(f"Error fetching depressions: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error fetching depressions",
        ) from e
