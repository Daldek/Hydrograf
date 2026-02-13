"""
Stream selection endpoint.

Selects a stream segment, traverses upstream, and returns the upstream
catchment boundary and segment indices for frontend highlighting,
along with full watershed statistics (morphometry, land cover, etc.).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
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


def _find_stream_segment(
    x: float, y: float, threshold_m2: int, db: Session
) -> dict | None:
    """Find the nearest stream_network segment to a point."""
    query = text("""
        SELECT
            segment_idx,
            strahler_order,
            ST_Length(geom) as length_m,
            upstream_area_km2
        FROM stream_network
        WHERE threshold_m2 = :threshold
          AND ST_DWithin(geom, ST_SetSRID(ST_Point(:x, :y), 2180), 1000)
        ORDER BY ST_Distance(geom, ST_SetSRID(ST_Point(:x, :y), 2180))
        LIMIT 1
    """)
    result = db.execute(query, {"x": x, "y": y, "threshold": threshold_m2}).fetchone()
    if result is None:
        return None
    return {
        "segment_idx": result.segment_idx,
        "strahler_order": result.strahler_order,
        "length_m": result.length_m,
        "upstream_area_km2": result.upstream_area_km2,
    }


def _find_upstream_segments(
    boundary_wkt: str, threshold_m2: int, db: Session
) -> list[int]:
    """Find all stream_catchments segments that intersect the boundary."""
    query = text("""
        SELECT segment_idx
        FROM stream_catchments
        WHERE threshold_m2 = :threshold
          AND ST_Intersects(geom, ST_GeomFromText(:wkt, 2180))
    """)
    results = db.execute(
        query, {"threshold": threshold_m2, "wkt": boundary_wkt}
    ).fetchall()
    return [r.segment_idx for r in results]


@router.post("/select-stream", response_model=SelectStreamResponse)
def select_stream(
    request: SelectStreamRequest,
    db: Session = Depends(get_db),
):
    """
    Select a stream segment and compute upstream catchment.

    Finds the nearest stream, traverses upstream, builds a boundary,
    and returns upstream segment indices for frontend highlighting.
    """
    try:
        point_2180 = transform_wgs84_to_pl1992(request.latitude, request.longitude)
        logger.info(
            f"select-stream: ({request.latitude:.4f}, {request.longitude:.4f}) "
            f"threshold={request.threshold_m2}"
        )

        # 1. Find nearest stream cell
        outlet = find_nearest_stream(point_2180, db)
        if outlet is None:
            raise HTTPException(
                status_code=404,
                detail="Nie znaleziono cieku w pobliżu. Kliknij bliżej linii cieku.",
            )

        # 2. Find stream segment in stream_network (use snapped outlet coords)
        segment = _find_stream_segment(outlet.x, outlet.y, request.threshold_m2, db)
        if segment is None:
            raise HTTPException(
                status_code=404,
                detail="Nie znaleziono segmentu cieku dla wybranego progu.",
            )

        # 3. Traverse upstream
        cells = traverse_upstream(outlet.id, db)

        # 4. Build boundary
        boundary_2180 = build_boundary(cells)
        boundary_wgs84 = transform_polygon_pl1992_to_wgs84(boundary_2180)
        boundary_geojson = polygon_to_geojson_feature(boundary_wgs84)

        # 5. Find upstream segment indices
        upstream_indices = _find_upstream_segments(
            boundary_2180.wkt, request.threshold_m2, db
        )

        # 6. Compute full watershed statistics
        HYDROGRAPH_AREA_LIMIT_KM2 = 250.0
        area_km2 = calculate_watershed_area_km2(cells)
        hydrograph_available = area_km2 <= HYDROGRAPH_AREA_LIMIT_KM2

        morph_dict = build_morphometric_params(
            cells,
            boundary_2180,
            outlet,
            db=db,
            include_hypsometric_curve=True,
            include_stream_coords=True,
        )

        # Transform outlet to WGS84
        outlet_lon, outlet_lat = transform_pl1992_to_wgs84(outlet.x, outlet.y)

        # Extract hypsometric curve
        hypso_data = morph_dict.pop("hypsometric_curve", None)
        hypso_curve = None
        if hypso_data:
            hypso_curve = [HypsometricPoint(**p) for p in hypso_data]

        # Extract and transform main stream coords to WGS84 GeoJSON
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

        # Get land cover statistics
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

        watershed_response = WatershedResponse(
            boundary_geojson=boundary_geojson,
            outlet=OutletInfo(
                latitude=outlet_lat,
                longitude=outlet_lon,
                elevation_m=outlet.elevation,
            ),
            cell_count=len(cells),
            area_km2=round(area_km2, 2),
            hydrograph_available=hydrograph_available,
            morphometry=MorphometricParameters(**morph_dict),
            hypsometric_curve=hypso_curve,
            land_cover_stats=lc_stats,
            main_stream_geojson=main_stream_geojson,
        )

        return SelectStreamResponse(
            stream=StreamInfo(
                segment_idx=segment["segment_idx"],
                strahler_order=segment["strahler_order"],
                length_m=segment["length_m"],
                upstream_area_km2=segment["upstream_area_km2"],
            ),
            upstream_segment_indices=upstream_indices,
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
