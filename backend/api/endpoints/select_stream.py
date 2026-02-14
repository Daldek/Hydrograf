"""
Stream selection endpoint.

Selects a stream segment via catchment graph (~87k nodes), traverses
upstream, aggregates pre-computed stats, and returns the watershed
boundary with full morphometry. Zero raster operations in runtime.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from core.catchment_graph import get_catchment_graph
from core.constants import HYDROGRAPH_AREA_LIMIT_KM2
from core.database import get_db
from core.land_cover import get_land_cover_for_boundary
from core.morphometry import calculate_shape_indices
from core.watershed_service import (
    boundary_to_polygon,
    compute_watershed_length,
    find_nearest_stream_segment,
    get_main_stream_geojson,
    get_segment_outlet,
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

    Uses the in-memory catchment graph (~87k nodes) for BFS traversal
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

        # 1. Find stream segment nearest to click point
        segment = find_nearest_stream_segment(
            point_2180.x,
            point_2180.y,
            request.threshold_m2,
            db,
        )
        if segment is None:
            raise HTTPException(
                status_code=404,
                detail="Nie znaleziono cieku w pobliżu. Kliknij bliżej linii cieku.",
            )

        # 2. Find catchment at click point via catchment graph
        if not cg.loaded:
            raise HTTPException(
                status_code=503,
                detail="Graf zlewni nie został załadowany. Spróbuj ponownie.",
            )

        try:
            clicked_idx = cg.find_catchment_at_point(
                point_2180.x,
                point_2180.y,
                request.threshold_m2,
                db,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=404,
                detail="Nie znaleziono zlewni cząstkowej. Kliknij w obszarze zlewni.",
            ) from e

        # 3. Traverse upstream via catchment graph BFS
        if request.to_confluence:
            upstream_indices = cg.traverse_to_confluence(clicked_idx)
        else:
            upstream_indices = cg.traverse_upstream(clicked_idx)
        segment_idxs = cg.get_segment_indices(
            upstream_indices,
            request.threshold_m2,
        )

        # 4. Aggregate pre-computed stats (zero raster ops)
        stats = cg.aggregate_stats(upstream_indices)
        area_km2 = stats["area_km2"]

        # 5. Build boundary from ST_Union of catchment polygons
        boundary_2180 = merge_catchment_boundaries(
            segment_idxs,
            request.threshold_m2,
            db,
        )
        if boundary_2180 is None:
            raise HTTPException(
                status_code=500,
                detail="Nie udało się zbudować granicy zlewni.",
            )

        # Convert MultiPolygon to Polygon (largest component)
        boundary_poly = boundary_to_polygon(boundary_2180)

        boundary_wgs84 = transform_polygon_pl1992_to_wgs84(boundary_poly)
        boundary_geojson = polygon_to_geojson_feature(boundary_wgs84)

        # 6. Outlet point (from clicked segment's downstream endpoint)
        outlet_info = get_segment_outlet(
            segment["segment_idx"],
            request.threshold_m2,
            db,
        )
        if outlet_info is None:
            outlet_x, outlet_y = segment["downstream_x"], segment["downstream_y"]
        else:
            outlet_x, outlet_y = outlet_info["x"], outlet_info["y"]

        outlet_elevation = stats.get("elevation_min_m")
        outlet_lon, outlet_lat = transform_pl1992_to_wgs84(outlet_x, outlet_y)

        # 7. Derived metrics requiring boundary geometry
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

        # Channel length and slope from main stream
        channel_length_km = stats.get("stream_length_km")
        channel_slope = None
        if (
            channel_length_km
            and channel_length_km > 0
            and elev_min is not None
            and elev_max is not None
        ):
            channel_slope = round(
                (elev_max - elev_min) / (channel_length_km * 1000),
                6,
            )

        # 8. Hypsometric curve
        hypso_data = cg.aggregate_hypsometric(upstream_indices)
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

        # 9. Main stream GeoJSON
        main_stream_geojson = get_main_stream_geojson(
            segment["segment_idx"],
            request.threshold_m2,
            db,
        )

        # 10. Land cover statistics
        hydrograph_available = area_km2 <= HYDROGRAPH_AREA_LIMIT_KM2

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

        # 11. Build morphometric parameters
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
        )

        # 12. Build response
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
            main_stream_geojson=main_stream_geojson,
        )

        response.headers["Cache-Control"] = "public, max-age=3600"
        return SelectStreamResponse(
            stream=StreamInfo(
                segment_idx=segment["segment_idx"],
                strahler_order=segment["strahler_order"],
                length_m=segment["length_m"],
                upstream_area_km2=segment["upstream_area_km2"],
            ),
            upstream_segment_indices=segment_idxs,
            boundary_geojson=boundary_geojson,
            watershed=watershed_response,
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
