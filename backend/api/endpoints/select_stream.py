"""
Stream selection endpoint.

Selects a stream segment via catchment graph (~117k nodes), traverses
upstream, aggregates pre-computed stats, and returns the watershed
boundary with full morphometry. Zero raster operations in runtime.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from core.catchment_graph import get_catchment_graph
from core.constants import DEFAULT_THRESHOLD_M2, HYDROGRAPH_AREA_LIMIT_KM2
from core.database import get_db
from core.watershed_service import (
    boundary_to_polygon,
    build_hsg_stats,
    build_land_cover_stats,
    build_morph_dict_from_graph,
    cascade_escalate,
    ensure_outlet_within_boundary,
    get_divide_flow_path_geojson,
    get_longest_flow_path_geojson,
    get_main_channel_feature_collection,
    get_main_stream_geojson,
    get_segment_outlet,
    get_stream_info_by_segment_idx,
    merge_catchment_boundaries,
)
from models.schemas import (
    HypsometricPoint,
    MorphometricParameters,
    OutletInfo,
    SelectStreamRequest,
    SelectStreamResponse,
    StreamInfo,
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


@router.post("/select-stream", response_model=SelectStreamResponse)
def select_stream(
    request: SelectStreamRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    Select a stream segment and compute upstream catchment.

    Uses the in-memory catchment graph (~117k nodes) for BFS traversal
    and pre-computed stat aggregation. Zero raster operations.
    """
    try:
        point_2180 = transform_wgs84_to_pl1992(
            request.latitude,
            request.longitude,
        )
        logger.info(
            f"select-stream: ({request.latitude:.4f}, {request.longitude:.4f}) "
            f"threshold={request.threshold_m2}"
        )

        cg = get_catchment_graph()

        if not cg.loaded:
            raise HTTPException(
                status_code=503,
                detail="Graf zlewni nie został załadowany. Spróbuj ponownie.",
            )

        threshold = request.threshold_m2

        # ADR-026: catchments only for threshold >= 1000
        escalated = False
        if threshold < DEFAULT_THRESHOLD_M2:
            original_threshold = threshold
            threshold = DEFAULT_THRESHOLD_M2
            escalated = True
            logger.info(
                f"Threshold {original_threshold} escalated to {threshold} "
                f"(no catchments below {DEFAULT_THRESHOLD_M2})"
            )

        # 1. Find catchment at click point (ADR-039: pure ST_Contains)
        try:
            clicked_idx = cg.find_catchment_at_point(
                point_2180.x, point_2180.y, threshold, db
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        segment_idx = cg.get_segment_idx(clicked_idx)

        # 2. Get stream info for response
        segment = get_stream_info_by_segment_idx(segment_idx, threshold, db)

        # 4. Traverse upstream via catchment graph BFS
        upstream_indices = cg.traverse_upstream(clicked_idx)
        bfs_segment_idxs = cg.get_segment_indices(upstream_indices, threshold)

        # 5. Aggregate pre-computed stats (zero raster ops)
        # upstream_indices_for_stats and outlet_idx_for_stats track which
        # indices/outlet to use; updated during cascade escalation (CR9).
        upstream_indices_for_stats = upstream_indices
        outlet_idx_for_stats = clicked_idx
        stats = cg.aggregate_stats(upstream_indices_for_stats, outlet_idx=outlet_idx_for_stats)
        area_km2 = stats["area_km2"]

        # 6. Build boundary from ST_Union of catchment polygons.
        # For large catchments (300+ segments), cascade to coarser
        # thresholds to avoid ST_UnaryUnion timeout (30s DB limit).
        _MAX_MERGE = 300
        merge_idxs = bfs_segment_idxs
        merge_threshold = threshold

        escalation = cascade_escalate(
            cg, point_2180.x, point_2180.y, threshold,
            bfs_segment_idxs, _MAX_MERGE, db,
        )
        if escalation:
            merge_idxs, merge_threshold, upstream_indices_for_stats, outlet_idx_for_stats, stats, area_km2 = escalation
            logger.info(
                "Cascade: threshold escalated from %d to %d "
                "(%d -> %d segments)",
                threshold,
                merge_threshold,
                len(bfs_segment_idxs),
                len(merge_idxs),
            )

        boundary_2180 = merge_catchment_boundaries(
            merge_idxs,
            merge_threshold,
            db,
        )

        # Display indices = BFS indices (same threshold, no cross-threshold mapping)
        display_segment_idxs = bfs_segment_idxs

        if boundary_2180 is None:
            raise HTTPException(
                status_code=500,
                detail="Nie udało się zbudować granicy zlewni.",
            )

        # Convert MultiPolygon to Polygon (largest component)
        boundary_poly = boundary_to_polygon(boundary_2180)

        boundary_wgs84 = transform_polygon_pl1992_to_wgs84(boundary_poly)
        boundary_geojson = polygon_to_geojson_feature(boundary_wgs84)

        # 7. Outlet point (from clicked segment's downstream endpoint)
        outlet_info = get_segment_outlet(segment_idx, threshold, db)
        if outlet_info is None:
            if segment:
                outlet_x, outlet_y = segment["downstream_x"], segment["downstream_y"]
            else:
                # Fallback: use click point
                outlet_x, outlet_y = point_2180.x, point_2180.y
        else:
            outlet_x, outlet_y = outlet_info["x"], outlet_info["y"]

        # E4: Snap outlet to boundary if it fell outside (cascade threshold mismatch)
        outlet_x, outlet_y = ensure_outlet_within_boundary(
            outlet_x, outlet_y, boundary_2180
        )

        outlet_elevation = stats.get("elevation_min_m")
        outlet_lon, outlet_lat = transform_pl1992_to_wgs84(outlet_x, outlet_y)

        # 8. Build morphometric parameters from graph (unified with watershed.py)
        morph_dict = build_morph_dict_from_graph(
            cg,
            upstream_indices_for_stats,
            boundary_2180,
            outlet_x,
            outlet_y,
            segment_idx,
            merge_threshold,
            db=db,
            outlet_idx=outlet_idx_for_stats,
        )

        # 9. Hypsometric curve (needed for GUI — not part of morph dict)
        hypso_data = cg.aggregate_hypsometric(upstream_indices_for_stats)
        hypso_curve = None
        if hypso_data:
            hypso_curve = [HypsometricPoint(**p) for p in hypso_data]

        # 10. Main stream GeoJSON (FeatureCollection with is_real_stream per segment)
        main_channel_nodes = morph_dict.pop("_main_channel_nodes", [])
        main_stream_geojson = get_main_channel_feature_collection(
            cg, main_channel_nodes, merge_threshold, db,
        )
        if main_stream_geojson is None:
            main_stream_geojson = get_main_stream_geojson(segment_idx, merge_threshold, db)

        # 11. Land cover statistics
        hydrograph_available = area_km2 <= HYDROGRAPH_AREA_LIMIT_KM2

        # Simplify boundary for land cover/HSG queries — exact shape
        # is not needed for area-weighted statistics, and complex
        # boundaries with thousands of vertices make ST_Intersection
        # very slow (~20s for 95 km² watershed).
        lc_simplify = 20.0 if area_km2 > 5 else None
        lc_stats = build_land_cover_stats(boundary_poly, db, simplify_tolerance=lc_simplify)

        # 11a. HSG soil statistics
        lc_boundary = boundary_poly.simplify(20.0) if area_km2 > 5 else boundary_poly
        hsg_stats_data = build_hsg_stats(lc_boundary, db)

        # 12. Inject CN and imperviousness into morph dict
        if lc_stats is not None:
            morph_dict["cn"] = lc_stats.weighted_cn
            morph_dict["imperviousness"] = round(
                lc_stats.weighted_imperviousness, 3
            )

        morphometry = MorphometricParameters(**morph_dict)

        # 12b. Longest flow path GeoJSON
        flow_path_geojson = None
        try:
            flow_path_geojson = get_longest_flow_path_geojson(
                cg, upstream_indices_for_stats, clicked_idx,
                threshold, db,
            )
        except Exception as e:
            logger.debug(f"Longest flow path not available: {e}")

        # 12c. Divide flow path GeoJSON
        divide_path_geojson = None
        try:
            divide_path_geojson = get_divide_flow_path_geojson(
                cg, upstream_indices_for_stats, clicked_idx,
                threshold, db,
            )
        except Exception as e:
            logger.debug(f"Divide flow path not available: {e}")

        # 13. Build response
        watershed_response = WatershedResponse(
            boundary_geojson=boundary_geojson,
            outlet=OutletInfo(
                latitude=outlet_lat,
                longitude=outlet_lon,
                elevation_m=outlet_elevation or 0.0,
            ),
            area_km2=round(area_km2, 2),
            hydrograph_available=hydrograph_available,
            morphometry=morphometry,
            hypsometric_curve=hypso_curve,
            land_cover_stats=lc_stats,
            hsg_stats=hsg_stats_data,
            main_stream_geojson=main_stream_geojson,
            longest_flow_path_geojson=flow_path_geojson,
            divide_flow_path_geojson=divide_path_geojson,
        )

        info_message = (
            (
                f"Zlewnie cząstkowe niedostępne dla progu {original_threshold} m². "
                f"Zaznaczono z progu {threshold} m²."
            )
            if escalated
            else None
        )

        response.headers["Cache-Control"] = "public, max-age=3600"
        return SelectStreamResponse(
            stream=StreamInfo(
                segment_idx=segment_idx,
                strahler_order=segment["strahler_order"] if segment else None,
                length_m=segment["length_m"] if segment else None,
                upstream_area_km2=segment["upstream_area_km2"] if segment else None,
            ),
            upstream_segment_indices=display_segment_idxs,
            boundary_geojson=boundary_geojson,
            display_threshold_m2=threshold,
            watershed=watershed_response,
            info_message=info_message,
        )

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error in stream selection: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error in stream selection: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Błąd wewnętrzny podczas wyboru cieku",
        ) from e
