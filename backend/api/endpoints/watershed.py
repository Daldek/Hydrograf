"""
Watershed delineation endpoint.

Provides API endpoint for delineating watershed boundaries
based on a clicked point location. Uses CatchmentGraph (~87k nodes)
for BFS traversal and pre-computed stat aggregation instead of
FlowGraph (19.7M cells). Zero raster operations in runtime.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from core.catchment_graph import get_catchment_graph
from core.constants import DEFAULT_THRESHOLD_M2, HYDROGRAPH_AREA_LIMIT_KM2
from core.database import get_db
from core.land_cover import get_land_cover_for_boundary
from core.watershed_service import (
    boundary_to_polygon,
    build_morph_dict_from_graph,
    find_nearest_stream_segment,
    get_main_stream_geojson,
    get_segment_outlet,
    merge_catchment_boundaries,
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


@router.post("/delineate-watershed", response_model=DelineateResponse)
def delineate_watershed(
    request: DelineateRequest,
    response: Response,
    include_hypsometric_curve: bool = False,
    db: Session = Depends(get_db),
) -> DelineateResponse:
    """
    Delineate watershed boundary for a given point.

    Uses the in-memory catchment graph (~87k nodes) for BFS traversal
    and pre-computed stat aggregation. Zero raster operations.

    Parameters
    ----------
    request : DelineateRequest
        Point coordinates in WGS84 (latitude, longitude)
    response : Response
        FastAPI response for setting headers
    include_hypsometric_curve : bool
        Whether to include hypsometric curve data
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
    HTTPException 503
        When catchment graph is not loaded
    HTTPException 500
        On internal server error
    """
    try:
        logger.info(
            "Delineating watershed for "
            f"({request.latitude:.6f}, {request.longitude:.6f})"
        )

        # 1. Transform WGS84 -> PL-1992
        point_2180 = transform_wgs84_to_pl1992(request.latitude, request.longitude)
        logger.debug(
            f"Transformed to PL-1992: ({point_2180.x:.1f}, {point_2180.y:.1f})"
        )

        # 2. Get CatchmentGraph instance, check if loaded
        cg = get_catchment_graph()
        if not cg.loaded:
            raise HTTPException(
                status_code=503,
                detail="Graf zlewni nie został załadowany. Spróbuj ponownie.",
            )

        # 3. Find nearest stream segment
        segment = find_nearest_stream_segment(
            point_2180.x,
            point_2180.y,
            DEFAULT_THRESHOLD_M2,
            db,
        )
        if segment is None:
            raise HTTPException(
                status_code=404,
                detail="Nie znaleziono cieku w tym miejscu",
            )

        # 4. Find catchment at click point via catchment graph
        try:
            clicked_idx = cg.find_catchment_at_point(
                point_2180.x,
                point_2180.y,
                DEFAULT_THRESHOLD_M2,
                db,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=404,
                detail="Nie znaleziono zlewni cząstkowej. Kliknij w obszarze zlewni.",
            ) from e

        # 5. Traverse upstream via catchment graph BFS
        upstream_indices = cg.traverse_upstream(clicked_idx)
        segment_idxs = cg.get_segment_indices(
            upstream_indices,
            DEFAULT_THRESHOLD_M2,
        )

        # 6. Aggregate pre-computed stats (zero raster ops)
        stats = cg.aggregate_stats(upstream_indices)
        area_km2 = stats["area_km2"]
        logger.debug(f"Watershed area: {area_km2:.2f} km2")

        # 7. Check if hydrograph generation is available (SCS-CN limit)
        hydrograph_available = area_km2 <= HYDROGRAPH_AREA_LIMIT_KM2

        # 8. Build boundary from ST_Union of catchment polygons
        boundary_2180 = merge_catchment_boundaries(
            segment_idxs,
            DEFAULT_THRESHOLD_M2,
            db,
        )
        if boundary_2180 is None:
            raise HTTPException(
                status_code=500,
                detail="Nie udało się zbudować granicy zlewni.",
            )

        # 9. Extract largest polygon from MultiPolygon
        boundary_poly = boundary_to_polygon(boundary_2180)

        # 10. Transform boundary to WGS84 + GeoJSON
        boundary_wgs84 = transform_polygon_pl1992_to_wgs84(boundary_poly)
        boundary_geojson = polygon_to_geojson_feature(
            boundary_wgs84,
            properties={"area_km2": round(area_km2, 2)},
        )

        # 11. Get outlet from segment downstream endpoint
        outlet_info = get_segment_outlet(
            segment["segment_idx"],
            DEFAULT_THRESHOLD_M2,
            db,
        )
        if outlet_info is None:
            outlet_x, outlet_y = segment["downstream_x"], segment["downstream_y"]
        else:
            outlet_x, outlet_y = outlet_info["x"], outlet_info["y"]

        # 12. Outlet elevation from CatchmentGraph stats (elevation_min_m of outlet)
        outlet_elevation = stats.get("elevation_min_m") or 0.0

        # 13. Transform outlet coords to WGS84
        outlet_lon, outlet_lat = transform_pl1992_to_wgs84(outlet_x, outlet_y)

        # 14. Build morphometric parameters from graph
        morph_dict = build_morph_dict_from_graph(
            cg,
            upstream_indices,
            boundary_2180,
            outlet_x,
            outlet_y,
            segment["segment_idx"],
            DEFAULT_THRESHOLD_M2,
        )

        # 15. Hypsometric curve
        hypso_curve = None
        if include_hypsometric_curve:
            hypso_data = cg.aggregate_hypsometric(upstream_indices)
            if hypso_data:
                hypso_curve = [HypsometricPoint(**p) for p in hypso_data]

        # 16. Main stream GeoJSON
        main_stream_geojson = get_main_stream_geojson(
            segment["segment_idx"],
            DEFAULT_THRESHOLD_M2,
            db,
        )

        # 17. Land cover statistics
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

        # 18. Build response
        result = DelineateResponse(
            watershed=WatershedResponse(
                boundary_geojson=boundary_geojson,
                outlet=OutletInfo(
                    latitude=outlet_lat,
                    longitude=outlet_lon,
                    elevation_m=outlet_elevation,
                ),
                cell_count=0,  # Not applicable for graph-based approach
                area_km2=round(area_km2, 2),
                hydrograph_available=hydrograph_available,
                morphometry=MorphometricParameters(**morph_dict),
                hypsometric_curve=hypso_curve,
                land_cover_stats=lc_stats,
                main_stream_geojson=main_stream_geojson,
            )
        )

        logger.info(
            f"Watershed delineated: {area_km2:.2f} km2, "
            f"{len(segment_idxs)} segments, "
            f"hydrograph={'available' if hydrograph_available else 'unavailable'}"
        )

        response.headers["Cache-Control"] = "public, max-age=3600"
        return result

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
