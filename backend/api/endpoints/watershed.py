"""
Watershed delineation endpoint.

Provides API endpoint for delineating watershed boundaries
based on a clicked point location.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.database import get_db
from core.land_cover import get_land_cover_for_boundary
from core.morphometry import build_morphometric_params
from core.watershed import (
    build_boundary,
    calculate_watershed_area_km2,
    find_nearest_stream,
    traverse_upstream,
)
from models.schemas import (
    DelineateRequest,
    DelineateResponse,
    HypsometricPoint,
    LandCoverCategory,
    LandCoverStats,
    MorphometricParameters,
    OutletInfo,
    WatershedResponse,
)
from utils.geometry import (
    polygon_to_geojson_feature,
    transform_pl1992_to_wgs84,
    transform_polygon_pl1992_to_wgs84,
    transform_wgs84_to_pl1992,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# SCS-CN method limit for hydrograph generation [km²]
HYDROGRAPH_AREA_LIMIT_KM2 = 250.0


@router.post("/delineate-watershed", response_model=DelineateResponse)
def delineate_watershed(
    request: DelineateRequest,
    include_hypsometric_curve: bool = False,
    db: Session = Depends(get_db),
) -> DelineateResponse:
    """
    Delineate watershed boundary for a given point.

    Finds the nearest stream to the clicked point and traces
    all upstream cells to determine the watershed boundary.

    Parameters
    ----------
    request : DelineateRequest
        Point coordinates in WGS84 (latitude, longitude)
    db : Session
        Database session (injected by FastAPI)

    Returns
    -------
    DelineateResponse
        Watershed boundary as GeoJSON with metadata

    Raises
    ------
    HTTPException 404
        When no stream found near the point
    HTTPException 400
        When watershed is too large or invalid
    HTTPException 500
        On internal server error
    """
    try:
        logger.info(
            f"Delineating watershed for ({request.latitude:.6f}, {request.longitude:.6f})"
        )

        # 1. Transform WGS84 -> PL-1992
        point_2180 = transform_wgs84_to_pl1992(request.latitude, request.longitude)
        logger.debug(
            f"Transformed to PL-1992: ({point_2180.x:.1f}, {point_2180.y:.1f})"
        )

        # 2. Find nearest stream cell
        outlet_cell = find_nearest_stream(point_2180, db)
        if outlet_cell is None:
            raise HTTPException(
                status_code=404,
                detail="Nie znaleziono cieku w tym miejscu",
            )

        # 3. Traverse upstream to find all watershed cells
        cells = traverse_upstream(outlet_cell.id, db)

        # 4. Calculate watershed area
        area_km2 = calculate_watershed_area_km2(cells)
        logger.debug(f"Watershed area: {area_km2:.2f} km²")

        # 5. Check if hydrograph generation is available (SCS-CN limit)
        hydrograph_available = area_km2 <= HYDROGRAPH_AREA_LIMIT_KM2

        # 6. Build boundary polygon
        boundary_2180 = build_boundary(cells, method="convex")

        # 7. Calculate morphometric parameters (with stream coords for profile)
        morph_dict = build_morphometric_params(
            cells,
            boundary_2180,
            outlet_cell,
            db=db,
            include_hypsometric_curve=include_hypsometric_curve,
            include_stream_coords=True,
        )

        # 8. Transform boundary to WGS84
        boundary_wgs84 = transform_polygon_pl1992_to_wgs84(boundary_2180)

        # 9. Create GeoJSON Feature
        boundary_geojson = polygon_to_geojson_feature(
            boundary_wgs84,
            properties={"area_km2": round(area_km2, 2)},
        )

        # 10. Transform outlet coords back to WGS84
        outlet_lon, outlet_lat = transform_pl1992_to_wgs84(outlet_cell.x, outlet_cell.y)

        # 11. Extract hypsometric curve if present
        hypso_data = morph_dict.pop("hypsometric_curve", None)
        hypso_curve = None
        if hypso_data:
            hypso_curve = [HypsometricPoint(**p) for p in hypso_data]

        # 12. Extract and transform main stream coords to WGS84 GeoJSON
        stream_coords_2180 = morph_dict.pop("main_stream_coords", None)
        main_stream_geojson = None
        if stream_coords_2180 and len(stream_coords_2180) >= 2:
            wgs84_coords = [
                list(transform_pl1992_to_wgs84(x, y)) for x, y in stream_coords_2180
            ]
            main_stream_geojson = {
                "type": "LineString",
                "coordinates": wgs84_coords,
            }

        # 13. Get land cover statistics
        lc_stats = None
        try:
            lc_data = get_land_cover_for_boundary(boundary_2180, db)
            if lc_data:
                lc_stats = LandCoverStats(
                    categories=[
                        LandCoverCategory(
                            category=cat["category"],
                            percentage=cat["percentage"],
                            area_m2=cat["area_m2"],
                            cn_value=cat["cn_value"],
                        )
                        for cat in lc_data["categories"]
                    ],
                    weighted_cn=lc_data["weighted_cn"],
                    weighted_imperviousness=lc_data["weighted_imperviousness"],
                )
        except Exception as e:
            logger.debug(f"Land cover stats not available: {e}")

        # 14. Build response
        response = DelineateResponse(
            watershed=WatershedResponse(
                boundary_geojson=boundary_geojson,
                outlet=OutletInfo(
                    latitude=outlet_lat,
                    longitude=outlet_lon,
                    elevation_m=outlet_cell.elevation,
                ),
                cell_count=len(cells),
                area_km2=round(area_km2, 2),
                hydrograph_available=hydrograph_available,
                morphometry=MorphometricParameters(**morph_dict),
                hypsometric_curve=hypso_curve,
                land_cover_stats=lc_stats,
                main_stream_geojson=main_stream_geojson,
            )
        )

        logger.info(
            f"Watershed delineated: {area_km2:.2f} km², "
            f"{len(cells):,} cells, "
            f"hydrograph={'available' if hydrograph_available else 'unavailable'}"
        )

        return response

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except ValueError as e:
        # Handle validation errors (e.g., watershed too large)
        logger.error(f"Validation error in watershed delineation: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        # Handle unexpected errors
        logger.error(f"Error delineating watershed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error during watershed delineation",
        ) from e
