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
from core.land_cover import get_land_cover_for_boundary
from core.morphometry import calculate_shape_indices
from core.watershed_service import (
    boundary_to_polygon,
    compute_watershed_length,
    ensure_outlet_within_boundary,
    get_main_stream_geojson,
    get_segment_outlet,
    get_stream_info_by_segment_idx,
    merge_catchment_boundaries,
)
from models.schemas import (
    HypsometricPoint,
    LandCoverCategory,
    LandCoverStats,
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
        if request.to_confluence:
            upstream_indices = cg.traverse_to_confluence(clicked_idx)
        else:
            upstream_indices = cg.traverse_upstream(clicked_idx)
        bfs_segment_idxs = cg.get_segment_indices(upstream_indices, threshold)

        # 5. Aggregate pre-computed stats (zero raster ops)
        # upstream_indices_for_stats tracks which indices to use for stats;
        # updated together with merge_idxs during cascade escalation (CR9).
        upstream_indices_for_stats = upstream_indices
        stats = cg.aggregate_stats(upstream_indices_for_stats)
        area_km2 = stats["area_km2"]

        # 6. Build boundary from ST_Union of catchment polygons.
        # For large catchments (500+ segments), cascade to coarser
        # thresholds to avoid ST_UnaryUnion timeout (30s DB limit).
        _MAX_MERGE = 300
        merge_idxs = bfs_segment_idxs
        merge_threshold = threshold

        if len(bfs_segment_idxs) > _MAX_MERGE:
            for t in [1000, 10000, 100000]:
                if t <= threshold:
                    continue
                try:
                    t_node = cg.find_catchment_at_point(
                        point_2180.x, point_2180.y, t, db
                    )
                except ValueError:
                    continue
                if request.to_confluence:
                    t_up = cg.traverse_to_confluence(t_node)
                else:
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
                        threshold,
                        merge_threshold,
                        len(bfs_segment_idxs),
                        len(merge_idxs),
                    )
                    break

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

        # 8. Derived metrics requiring boundary geometry
        perimeter_km = round(boundary_2180.length / 1000, 4)
        length_km = round(
            compute_watershed_length(boundary_2180, outlet_x, outlet_y),
            4,
        )
        shape_indices = calculate_shape_indices(area_km2, perimeter_km, length_km)

        # Relief indices
        relief_ratio = None
        elev_min = stats.get("elevation_min_m")
        elev_max = stats.get("elevation_max_m")
        if elev_min is not None and elev_max is not None and length_km > 0:
            relief_m = elev_max - elev_min
            relief_ratio = round(relief_m / (length_km * 1000), 6)

        # Ruggedness number
        ruggedness = None
        dd = stats.get("drainage_density_km_per_km2")
        if elev_min is not None and elev_max is not None and dd is not None:
            relief_km = (elev_max - elev_min) / 1000
            ruggedness = round(dd * relief_km, 4)

        # Channel length and slope from main channel trace (not total network)
        main_ch = cg.trace_main_channel(clicked_idx, upstream_indices_for_stats)
        channel_length_km = main_ch.get("main_channel_length_km")
        channel_slope = main_ch.get("main_channel_slope_m_per_m")

        # 9. Hypsometric curve
        hypso_data = cg.aggregate_hypsometric(upstream_indices_for_stats)
        hypso_curve = None
        hypsometric_integral = None
        if hypso_data:
            hypso_curve = [HypsometricPoint(**p) for p in hypso_data]
            # HI ~ trapezoidal integration of relative_area over relative_height
            areas = [p["relative_area"] for p in hypso_data]
            heights = [p["relative_height"] for p in hypso_data]
            if len(areas) >= 2:
                hi = sum(
                    (areas[i] + areas[i + 1]) / 2 * (heights[i + 1] - heights[i])
                    for i in range(len(areas) - 1)
                )
                hypsometric_integral = round(max(0, min(1, hi)), 4)

        # 10. Main stream GeoJSON
        main_stream_geojson = get_main_stream_geojson(segment_idx, threshold, db)

        # 11. Land cover statistics
        hydrograph_available = area_km2 <= HYDROGRAPH_AREA_LIMIT_KM2

        # Simplify boundary for land cover/HSG queries — exact shape
        # is not needed for area-weighted statistics, and complex
        # boundaries with thousands of vertices make ST_Intersection
        # very slow (~20s for 95 km² watershed).
        lc_boundary = boundary_poly
        if area_km2 > 5:
            lc_boundary = boundary_poly.simplify(20.0)  # 20m tolerance

        lc_stats = None
        try:
            lc_data = get_land_cover_for_boundary(lc_boundary, db)
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

        # 11a. HSG soil statistics
        hsg_stats_data = None
        try:
            from core.soil_hsg import get_hsg_for_boundary
            from models.schemas import HsgCategory, HsgStats

            hsg_data = get_hsg_for_boundary(lc_boundary.wkb_hex, db)
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

        # 12. Build morphometric parameters
        cn_value = lc_stats.weighted_cn if lc_stats is not None else None
        imperviousness = round(lc_stats.weighted_imperviousness, 3) if lc_stats is not None else None

        # Distance from outlet to boundary centroid
        from shapely.geometry import Point as ShapelyPoint

        outlet_point = ShapelyPoint(outlet_x, outlet_y)
        centroid = boundary_poly.centroid
        length_to_centroid_km = round(centroid.distance(outlet_point) / 1000, 4)

        morphometry = MorphometricParameters(
            area_km2=round(area_km2, 2),
            perimeter_km=perimeter_km,
            length_km=length_km,
            elevation_min_m=elev_min if elev_min is not None else 0.0,
            elevation_max_m=elev_max if elev_max is not None else 0.0,
            elevation_mean_m=stats.get("elevation_mean_m"),
            mean_slope_m_per_m=stats.get("mean_slope_m_per_m"),
            channel_length_km=channel_length_km,
            channel_slope_m_per_m=channel_slope,
            length_to_centroid_km=length_to_centroid_km,
            compactness_coefficient=shape_indices.get("compactness_coefficient"),
            circularity_ratio=shape_indices.get("circularity_ratio"),
            elongation_ratio=shape_indices.get("elongation_ratio"),
            form_factor=shape_indices.get("form_factor"),
            mean_width_km=shape_indices.get("mean_width_km"),
            relief_ratio=relief_ratio,
            hypsometric_integral=hypsometric_integral,
            drainage_density_km_per_km2=dd,
            stream_frequency_per_km2=stats.get("stream_frequency_per_km2"),
            ruggedness_number=ruggedness,
            max_strahler_order=stats.get("max_strahler_order"),
            cn=cn_value,
            imperviousness=imperviousness,
        )

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
