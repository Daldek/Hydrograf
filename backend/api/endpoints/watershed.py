"""
Watershed delineation endpoint.

Provides API endpoint for delineating watershed boundaries
based on a clicked point location. Uses CatchmentGraph (~11k nodes,
~0.5 MB) for BFS traversal and pre-computed stat aggregation.
Zero raster operations in runtime.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from core.catchment_graph import get_catchment_graph
from core.constants import (
    DEFAULT_THRESHOLD_M2,
    DELINEATION_MAX_AREA_M2,
    HYDROGRAPH_AREA_LIMIT_KM2,
    M2_PER_KM2,
)
from core.database import get_db
from core.land_cover import get_land_cover_for_boundary
from core.watershed_service import (
    boundary_to_polygon,
    build_morph_dict_from_graph,
    ensure_outlet_within_boundary,
    get_main_stream_geojson,
    get_segment_outlet,
    get_stream_info_by_segment_idx,
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

        # 3. Find catchment at click point (direct ST_Contains)
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

        # 4. Get segment info for outlet
        segment_idx = cg.get_segment_idx(clicked_idx)
        segment = get_stream_info_by_segment_idx(segment_idx, DEFAULT_THRESHOLD_M2, db)

        # 5. Traverse upstream via catchment graph BFS
        upstream_indices = cg.traverse_upstream(clicked_idx)
        segment_idxs = cg.get_segment_indices(
            upstream_indices,
            DEFAULT_THRESHOLD_M2,
        )

        # 6. Aggregate pre-computed stats (zero raster ops)
        # upstream_indices_for_stats tracks which indices to use for stats;
        # updated together with merge_idxs during cascade escalation (CR9).
        upstream_indices_for_stats = upstream_indices
        stats = cg.aggregate_stats(upstream_indices_for_stats)
        area_km2 = stats["area_km2"]
        logger.debug(f"Watershed area: {area_km2:.2f} km2")

        # 6a. Auto-selection check: area > limit → selection display
        auto_selected = area_km2 > DELINEATION_MAX_AREA_M2 / M2_PER_KM2

        # 7. Check if hydrograph generation is available (SCS-CN limit)
        hydrograph_available = area_km2 <= HYDROGRAPH_AREA_LIMIT_KM2

        # 8. Build boundary from ST_Union of catchment polygons.
        # For large catchments (500+ segments), cascade to coarser
        # thresholds to avoid ST_UnaryUnion timeout (30s DB limit).
        _MAX_MERGE = 500
        merge_idxs = segment_idxs
        merge_threshold = DEFAULT_THRESHOLD_M2

        if len(segment_idxs) > _MAX_MERGE:
            for t in [1000, 10000, 100000]:
                if t <= DEFAULT_THRESHOLD_M2:
                    continue
                try:
                    t_node = cg.find_catchment_at_point(
                        point_2180.x, point_2180.y, t, db
                    )
                except ValueError:
                    continue
                t_up = cg.traverse_upstream(t_node)
                t_segs = cg.get_segment_indices(t_up, t)
                if len(t_segs) <= _MAX_MERGE or t == 100000:
                    merge_idxs = t_segs
                    merge_threshold = t
                    # CR9: re-aggregate stats from escalated threshold
                    # so stats match the boundary polygon
                    upstream_indices_for_stats = t_up
                    stats = cg.aggregate_stats(upstream_indices_for_stats)
                    area_km2 = stats["area_km2"]
                    logger.info(
                        "Cascade: threshold escalated from %d to %d "
                        "(%d -> %d segments)",
                        DEFAULT_THRESHOLD_M2,
                        merge_threshold,
                        len(segment_idxs),
                        len(merge_idxs),
                    )
                    break

        boundary_2180 = merge_catchment_boundaries(
            merge_idxs,
            merge_threshold,
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
            segment_idx,
            DEFAULT_THRESHOLD_M2,
            db,
        )
        if outlet_info is None:
            if segment:
                outlet_x, outlet_y = segment["downstream_x"], segment["downstream_y"]
            else:
                outlet_x, outlet_y = point_2180.x, point_2180.y
        else:
            outlet_x, outlet_y = outlet_info["x"], outlet_info["y"]

        # E4: Snap outlet to boundary if it fell outside (cascade threshold mismatch)
        outlet_x, outlet_y = ensure_outlet_within_boundary(
            outlet_x, outlet_y, boundary_2180
        )

        # 12. Outlet elevation from CatchmentGraph stats (elevation_min_m of outlet)
        outlet_elevation = stats.get("elevation_min_m") or 0.0

        # 13. Transform outlet coords to WGS84
        outlet_lon, outlet_lat = transform_pl1992_to_wgs84(outlet_x, outlet_y)

        # 14. Build morphometric parameters from graph
        morph_dict = build_morph_dict_from_graph(
            cg,
            upstream_indices_for_stats,
            boundary_2180,
            outlet_x,
            outlet_y,
            segment_idx,
            DEFAULT_THRESHOLD_M2,
            db=db,
        )

        # 15. Hypsometric curve
        hypso_curve = None
        if include_hypsometric_curve:
            hypso_data = cg.aggregate_hypsometric(upstream_indices_for_stats)
            if hypso_data:
                hypso_curve = [HypsometricPoint(**p) for p in hypso_data]

        # 16. Main stream GeoJSON
        main_stream_geojson = get_main_stream_geojson(
            segment_idx,
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

        # 17b. Inject weighted CN and imperviousness into morphometry for hydrograph fast path
        if lc_stats is not None:
            morph_dict["cn"] = lc_stats.weighted_cn
            morph_dict["imperviousness"] = round(
                lc_stats.weighted_imperviousness, 3
            )

        # 17a. HSG soil statistics
        hsg_stats_data = None
        try:
            from core.soil_hsg import get_hsg_for_boundary
            from models.schemas import HsgCategory, HsgStats

            hsg_data = get_hsg_for_boundary(boundary_2180.wkb_hex, db)
            if hsg_data:
                hsg_stats_data = HsgStats(
                    categories=[
                        HsgCategory(
                            group=cat["group"],
                            percentage=cat["percentage"],
                            area_m2=cat["area_m2"],
                        )
                        for cat in hsg_data["categories"]
                    ],
                    dominant_group=hsg_data["dominant_group"],
                )
        except Exception as e:
            logger.debug(f"HSG stats not available: {e}")

        # 18. Build response
        result = DelineateResponse(
            watershed=WatershedResponse(
                boundary_geojson=boundary_geojson,
                outlet=OutletInfo(
                    latitude=outlet_lat,
                    longitude=outlet_lon,
                    elevation_m=outlet_elevation,
                ),
                area_km2=round(area_km2, 2),
                hydrograph_available=hydrograph_available,
                morphometry=MorphometricParameters(**morph_dict),
                hypsometric_curve=hypso_curve,
                land_cover_stats=lc_stats,
                hsg_stats=hsg_stats_data,
                main_stream_geojson=main_stream_geojson,
            ),
            auto_selected=auto_selected,
            upstream_segment_indices=segment_idxs if auto_selected else None,
            display_threshold_m2=DEFAULT_THRESHOLD_M2 if auto_selected else None,
            info_message=(
                "Zlewnia przekracza 10 000 m² — wyświetlono "
                "pre-obliczone zlewnie cząstkowe."
                if auto_selected
                else None
            ),
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
