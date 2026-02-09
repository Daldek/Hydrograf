"""
Terrain profile endpoint.

Extracts elevation profile along a GeoJSON LineString
by sampling the flow_network elevation data.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.database import get_db
from models.schemas import TerrainProfileRequest, TerrainProfileResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/terrain-profile", response_model=TerrainProfileResponse)
def terrain_profile(
    request: TerrainProfileRequest,
    db: Session = Depends(get_db),
) -> TerrainProfileResponse:
    """
    Extract terrain elevation profile along a line.

    Samples N equally spaced points along the input LineString and
    finds the nearest flow_network cell elevation for each.

    Parameters
    ----------
    request : TerrainProfileRequest
        GeoJSON LineString geometry and number of samples
    db : Session
        Database session

    Returns
    -------
    TerrainProfileResponse
        Arrays of distances and elevations along the profile
    """
    try:
        geom = request.geometry
        if geom.get("type") != "LineString":
            raise HTTPException(
                status_code=400,
                detail="Geometry must be a LineString",
            )

        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            raise HTTPException(
                status_code=400,
                detail="LineString must have at least 2 coordinates",
            )

        n_samples = request.n_samples

        # Build WKT from coordinates (lon, lat order in GeoJSON)
        coord_str = ", ".join(f"{c[0]} {c[1]}" for c in coords)
        wkt = f"LINESTRING({coord_str})"

        query = text("""
            WITH input_line AS (
                SELECT ST_Transform(
                    ST_SetSRID(ST_GeomFromText(:wkt), 4326),
                    2180
                ) AS geom
            ),
            line_length AS (
                SELECT ST_Length(geom) AS total_m FROM input_line
            ),
            sample_points AS (
                SELECT
                    generate_series(0, :n_samples - 1) AS idx,
                    generate_series(0, :n_samples - 1)::float
                        / GREATEST(:n_samples - 1, 1) AS frac
            ),
            points AS (
                SELECT
                    sp.idx,
                    sp.frac * ll.total_m AS distance_m,
                    ST_LineInterpolatePoint(il.geom, sp.frac) AS geom
                FROM sample_points sp
                CROSS JOIN input_line il
                CROSS JOIN line_length ll
            )
            SELECT
                p.idx,
                p.distance_m,
                (
                    SELECT fn.elevation
                    FROM flow_network fn
                    ORDER BY fn.geom <-> p.geom
                    LIMIT 1
                ) AS elevation_m
            FROM points p
            ORDER BY p.idx
        """)

        result = db.execute(query, {"wkt": wkt, "n_samples": n_samples}).fetchall()

        if not result:
            raise HTTPException(
                status_code=404,
                detail="Brak danych wysokościowych dla podanej linii",
            )

        distances = [float(r.distance_m) for r in result]
        elevations = [float(r.elevation_m) for r in result]
        total_length = distances[-1] if distances else 0.0

        return TerrainProfileResponse(
            distances_m=distances,
            elevations_m=elevations,
            total_length_m=total_length,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error extracting terrain profile: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error during profile extraction",
        ) from e
