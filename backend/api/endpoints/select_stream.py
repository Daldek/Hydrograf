"""
Stream selection endpoint.

Selects a stream segment, traverses upstream, and returns the upstream
catchment boundary and segment indices for frontend highlighting.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.database import get_db
from core.watershed import (
    build_boundary,
    find_nearest_stream,
    traverse_upstream,
)
from models.schemas import (
    SelectStreamRequest,
    SelectStreamResponse,
    StreamInfo,
)
from utils.geometry import (
    polygon_to_geojson_feature,
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

        return SelectStreamResponse(
            stream=StreamInfo(
                segment_idx=segment["segment_idx"],
                strahler_order=segment["strahler_order"],
                length_m=segment["length_m"],
                upstream_area_km2=segment["upstream_area_km2"],
            ),
            upstream_segment_indices=upstream_indices,
            boundary_geojson=boundary_geojson,
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
