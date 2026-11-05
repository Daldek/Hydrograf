"""
Watershed delineation endpoint.

Unified endpoint with two modes:
- Precomputed (threshold_m2 given): BFS on pre-computed catchment graph,
  ST_Union boundary
- Precise (no threshold): BFS at 1000m² + on-the-fly raster boundary via pyflwdir

Preview endpoint: the sub-catchments precomputed mode will merge, without
the slow merge, for a progress animation in the GUI.
"""

import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, Response
from shapely import wkb
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.catchment_graph import CatchmentGraph, get_catchment_graph
from core.constants import DEFAULT_THRESHOLD_M2, HYDROGRAPH_AREA_LIMIT_KM2
from core.database import get_db
from core.errors import (
    CalculationError,
    HydrografError,
    InternalError,
    InvalidRequestError,
    NotFoundError,
    StoreUnavailableError,
)
from core.handoff import (
    build_handoff,
    delineated_origin,
    watershed_name,
    watershed_parameters,
)
from core.watershed_service import (
    boundary_to_polygon,
    build_hsg_stats,
    build_land_cover_stats,
    build_morph_dict_from_graph,
    cascade_escalate,
    ensure_outlet_within_boundary,
    get_catchment_levels_feature_collection,
    get_divide_flow_path_geojson,
    get_longest_flow_path_geojson,
    get_main_channel_feature_collection,
    get_main_stream_geojson,
    get_segment_outlet,
    get_stream_info_by_segment_idx,
    merge_catchment_boundaries,
)
from models.schemas import (
    DelineatePreviewRequest,
    DelineatePreviewResponse,
    DelineateRequest,
    DelineateResponse,
    HypsometricPoint,
    MorphometricParameters,
    OutletInfo,
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


def _smooth_polygon_sql(polygon: BaseGeometry, db: Session) -> BaseGeometry:
    """Apply PostGIS smoothing pipeline to a raw polygon.

    Same pipeline as merge_catchment_boundaries: SimplifyPreserveTopology(5.0) +
    ChaikinSmoothing(3).
    """
    query = text("""
        SELECT ST_AsBinary(
            ST_Multi(ST_Buffer(
                ST_ChaikinSmoothing(
                    ST_SimplifyPreserveTopology(
                        ST_GeomFromWKB(:wkb, 2180),
                    5.0),
                3),
            0))
        ) as geom
    """)
    result = db.execute(query, {"wkb": polygon.wkb}).fetchone()
    if result and result.geom:
        return wkb.loads(bytes(result.geom))
    return polygon


def _build_watershed_response(
    cg: CatchmentGraph,
    point_2180: Point,
    boundary_2180: BaseGeometry,
    boundary_poly: Polygon,
    upstream_indices_for_stats: np.ndarray,
    outlet_idx_for_stats: int,
    segment_idx: int,
    threshold: int,
    merge_threshold: int,
    area_km2: float,
    stats: dict[str, Any],
    include_hypsometric_curve: bool,
    db: Session,
) -> WatershedResponse:
    """Build WatershedResponse from computed data (shared by both modes)."""
    # Outlet
    outlet_info = get_segment_outlet(segment_idx, threshold, db)
    if outlet_info is None:
        segment = get_stream_info_by_segment_idx(segment_idx, threshold, db)
        if segment:
            outlet_x, outlet_y = segment["downstream_x"], segment["downstream_y"]
        else:
            outlet_x, outlet_y = point_2180.x, point_2180.y
    else:
        outlet_x, outlet_y = outlet_info["x"], outlet_info["y"]

    outlet_x, outlet_y = ensure_outlet_within_boundary(
        outlet_x, outlet_y, boundary_2180
    )
    outlet_elevation = stats.get("elevation_min_m") or 0.0
    outlet_lon, outlet_lat = transform_pl1992_to_wgs84(outlet_x, outlet_y)

    # Morphometry
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

    # Override area from precise raster stats if different
    morph_dict["area_km2"] = round(area_km2, 4)

    # Hypsometric curve
    hypso_curve = None
    if include_hypsometric_curve:
        hypso_data = cg.aggregate_hypsometric(upstream_indices_for_stats)
        if hypso_data:
            hypso_curve = [HypsometricPoint(**p) for p in hypso_data]

    # Main channel
    main_channel_nodes = morph_dict.pop("_main_channel_nodes", [])
    main_stream_geojson = get_main_channel_feature_collection(
        cg,
        main_channel_nodes,
        merge_threshold,
        db,
    )
    if main_stream_geojson is None:
        main_stream_geojson = get_main_stream_geojson(segment_idx, merge_threshold, db)

    # Hydrograph
    hydrograph_available = area_km2 <= HYDROGRAPH_AREA_LIMIT_KM2

    # Land cover (simplify boundary for large watersheds)
    lc_simplify = 20.0 if area_km2 > 5 else None
    lc_stats = build_land_cover_stats(boundary_poly, db, simplify_tolerance=lc_simplify)

    # HSG
    lc_boundary = boundary_poly.simplify(20.0) if area_km2 > 5 else boundary_poly
    hsg_stats_data = build_hsg_stats(lc_boundary, db)

    # Inject CN and Lutz's shares of forest and urbanised land
    if lc_stats is not None:
        morph_dict["cn"] = lc_stats.weighted_cn
        morph_dict["imperviousness"] = round(lc_stats.weighted_imperviousness, 3)
        morph_dict["forest_pct"] = lc_stats.forest_pct
        morph_dict["urban_pct"] = lc_stats.urban_pct

    # Flow paths
    flow_path_geojson = None
    try:
        flow_path_geojson = get_longest_flow_path_geojson(
            cg,
            upstream_indices_for_stats,
            outlet_idx_for_stats,
            threshold,
            db,
        )
    except Exception as e:
        logger.debug(f"Longest flow path not available: {e}")

    divide_path_geojson = None
    try:
        divide_path_geojson = get_divide_flow_path_geojson(
            cg,
            upstream_indices_for_stats,
            outlet_idx_for_stats,
            threshold,
            db,
        )
    except Exception as e:
        logger.debug(f"Divide flow path not available: {e}")

    # Build WGS84 boundary
    boundary_wgs84 = transform_polygon_pl1992_to_wgs84(boundary_poly)
    boundary_geojson = polygon_to_geojson_feature(
        boundary_wgs84,
        properties={"area_km2": round(area_km2, 2)},
    )

    return WatershedResponse(
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
        longest_flow_path_geojson=flow_path_geojson,
        divide_flow_path_geojson=divide_path_geojson,
    )


# Above this many sub-catchments the boundary is merged from a coarser
# threshold (cascade_escalate).
_MAX_MERGE = 300

# Preview polygons are simplified to about one screen pixel once the map is
# fitted to the watershed: its extent is ~sqrt(area), drawn ~500 px across.
_PREVIEW_PX_ACROSS = 500
_PREVIEW_MIN_TOLERANCE_M = 1.0

# The preview carries at most this many sub-catchments, the ones nearest the
# outlet in BFS order (the largest watershed of the current data has ~4400).
_PREVIEW_MAX_CATCHMENTS = 5000


@dataclass(frozen=True)
class _Selection:
    """Sub-catchments a precomputed delineation selects for a click."""

    threshold: int  # of the clicked sub-catchment, after the ADR-026 floor
    clicked_idx: int
    bfs_segment_idxs: list[int]  # BFS at `threshold` (MVT highlighting)
    merge_idxs: list[int]  # merged into the boundary
    merge_threshold: int  # coarser than `threshold` after a cascade
    upstream_indices: np.ndarray  # graph nodes of merge_idxs (stats)
    outlet_idx: int  # graph node of the outlet at merge_threshold
    stats: dict[str, Any]
    area_km2: float


def _loaded_catchment_graph(db: Session) -> CatchmentGraph:
    """Return the in-memory catchment graph, loading it on first use.

    Parameters
    ----------
    db : Session
        Database session the graph is loaded from.

    Returns
    -------
    CatchmentGraph
        The loaded graph.

    Raises
    ------
    StoreUnavailableError
        ``store_unavailable`` (503) when the graph cannot be loaded.
    """
    cg = get_catchment_graph()
    if not cg.ensure_loaded(db):
        raise StoreUnavailableError(
            "catchment_graph_unavailable", reason="catchment_graph_unavailable"
        )
    return cg


def _select_precomputed(
    threshold_m2: int,
    point_2180: Point,
    cg: CatchmentGraph,
    db: Session,
) -> _Selection:
    """Sub-catchments merged for a click in precomputed mode.

    Shared by the delineation and its preview, so both cover the same area:
    threshold floor, sub-catchment at the point (404 if none), BFS upstream
    and the cascade to a coarser threshold above _MAX_MERGE segments.
    """
    threshold = threshold_m2

    # ADR-026: catchments only for threshold >= DEFAULT_THRESHOLD_M2
    if threshold < DEFAULT_THRESHOLD_M2:
        threshold = DEFAULT_THRESHOLD_M2
        logger.info(
            f"Threshold {threshold_m2} escalated to {threshold} "
            f"(no catchments below {DEFAULT_THRESHOLD_M2})"
        )

    try:
        clicked_idx = cg.find_catchment_at_point(
            point_2180.x,
            point_2180.y,
            threshold,
            db,
        )
    except ValueError as e:
        raise NotFoundError(
            "no_catchment_at_point",
            reason="no_catchment_at_point",
            threshold_m2=threshold,
        ) from e

    upstream_indices = cg.traverse_upstream(clicked_idx)
    bfs_segment_idxs = cg.get_segment_indices(upstream_indices, threshold)
    stats = cg.aggregate_stats(upstream_indices, outlet_idx=clicked_idx)

    escalation = cascade_escalate(
        cg,
        point_2180.x,
        point_2180.y,
        threshold,
        bfs_segment_idxs,
        _MAX_MERGE,
        db,
    )
    if escalation is None:
        return _Selection(
            threshold=threshold,
            clicked_idx=clicked_idx,
            bfs_segment_idxs=bfs_segment_idxs,
            merge_idxs=bfs_segment_idxs,
            merge_threshold=threshold,
            upstream_indices=upstream_indices,
            outlet_idx=clicked_idx,
            stats=stats,
            area_km2=stats["area_km2"],
        )

    merge_idxs, merge_threshold, merge_upstream, outlet_idx, stats, area_km2 = (
        escalation
    )
    logger.info(
        "Cascade: %d -> %d (%d -> %d segments)",
        threshold,
        merge_threshold,
        len(bfs_segment_idxs),
        len(merge_idxs),
    )
    return _Selection(
        threshold=threshold,
        clicked_idx=clicked_idx,
        bfs_segment_idxs=bfs_segment_idxs,
        merge_idxs=merge_idxs,
        merge_threshold=merge_threshold,
        upstream_indices=merge_upstream,
        outlet_idx=outlet_idx,
        stats=stats,
        area_km2=area_km2,
    )


def _preview_tolerance_m(area_km2: float) -> float:
    """Simplification tolerance of preview polygons for a watershed area."""
    return max(
        math.sqrt(area_km2 * 1_000_000) / _PREVIEW_PX_ACROSS,
        _PREVIEW_MIN_TOLERANCE_M,
    )


def _delineate_precomputed(
    request: DelineateRequest,
    point_2180: Point,
    cg: CatchmentGraph,
    db: Session,
    include_hypsometric_curve: bool,
) -> dict[str, Any]:
    """Precomputed mode: BFS on graph + ST_Union boundary."""
    if request.threshold_m2 is None:
        raise ValueError("Precomputed mode needs threshold_m2")
    selection = _select_precomputed(request.threshold_m2, point_2180, cg, db)
    threshold = selection.threshold

    segment_idx = cg.get_segment_idx(selection.clicked_idx)
    segment = get_stream_info_by_segment_idx(segment_idx, threshold, db)

    # Boundary
    boundary_2180 = merge_catchment_boundaries(
        selection.merge_idxs,
        selection.merge_threshold,
        db,
    )
    if boundary_2180 is None:
        raise CalculationError("boundary_build_failed", reason="boundary_build_failed")

    boundary_poly = boundary_to_polygon(boundary_2180)

    # Build shared response
    watershed_response = _build_watershed_response(
        cg,
        point_2180,
        boundary_2180,
        boundary_poly,
        selection.upstream_indices,
        selection.outlet_idx,
        segment_idx,
        threshold,
        selection.merge_threshold,
        selection.area_km2,
        selection.stats,
        include_hypsometric_curve,
        db,
    )

    # Stream info
    stream_info = StreamInfo(
        segment_idx=segment_idx,
        strahler_order=segment["strahler_order"] if segment else None,
        length_m=segment["length_m"] if segment else None,
        upstream_area_km2=segment["upstream_area_km2"] if segment else None,
    )

    info_message = (
        (
            f"Zlewnie cząstkowe niedostępne dla progu {request.threshold_m2} m². "
            f"Zaznaczono z progu {threshold} m²."
        )
        if threshold != request.threshold_m2
        else None
    )

    logger.info(
        f"Precomputed delineation: {selection.area_km2:.2f} km2, "
        f"{len(selection.bfs_segment_idxs)} segments"
    )

    return {
        "watershed_response": watershed_response,
        "stream_info": stream_info,
        "upstream_segment_indices": selection.bfs_segment_idxs,
        "display_threshold_m2": threshold,
        "info_message": info_message,
    }


def _delineate_precise(
    request: DelineateRequest,
    point_2180: Point,
    cg: CatchmentGraph,
    db: Session,
    include_hypsometric_curve: bool,
) -> dict[str, Any]:
    """Precise mode: BFS at 1000 + raster boundary."""
    from core.raster_service import get_raster_cache

    threshold = DEFAULT_THRESHOLD_M2

    # Find catchment at finest threshold
    try:
        clicked_idx = cg.find_catchment_at_point(
            point_2180.x,
            point_2180.y,
            threshold,
            db,
        )
    except ValueError as e:
        raise NotFoundError(
            "no_catchment_at_point",
            reason="no_catchment_at_point",
            threshold_m2=threshold,
        ) from e

    segment_idx = cg.get_segment_idx(clicked_idx)

    # BFS at 1000 (for graph-based network stats)
    upstream_indices = cg.traverse_upstream(clicked_idx)
    upstream_indices_for_stats = upstream_indices
    outlet_idx_for_stats = clicked_idx
    stats = cg.aggregate_stats(
        upstream_indices_for_stats, outlet_idx=outlet_idx_for_stats
    )

    # Raster delineation for precise boundary
    rc = get_raster_cache()
    raster_result = rc.delineate_from_point(point_2180.x, point_2180.y)

    # Override area from raster (more precise)
    area_km2 = raster_result["stats"]["area_m2"] / 1_000_000

    # Boundary from raster + smoothing
    boundary_raw = raster_result["polygon"]
    boundary_2180 = _smooth_polygon_sql(boundary_raw, db)

    # Ensure it's a MultiPolygon for consistency
    if isinstance(boundary_2180, Polygon):
        boundary_2180 = MultiPolygon([boundary_2180])

    boundary_poly = boundary_to_polygon(boundary_2180)

    # Build shared response
    merge_threshold = threshold
    watershed_response = _build_watershed_response(
        cg,
        point_2180,
        boundary_2180,
        boundary_poly,
        upstream_indices_for_stats,
        outlet_idx_for_stats,
        segment_idx,
        threshold,
        merge_threshold,
        area_km2,
        stats,
        include_hypsometric_curve,
        db,
    )

    logger.info(f"Precise delineation: {area_km2:.2f} km2")

    # No cascade, no stream info, no upstream_segment_indices
    return {
        "watershed_response": watershed_response,
    }


def _watershed_handoff(watershed: WatershedResponse) -> dict[str, Any] | None:
    """Return the hand-off of a delineated watershed, without rainfall and result.

    Parameters
    ----------
    watershed : WatershedResponse
        The delineated watershed.

    Returns
    -------
    dict[str, Any] or None
        ``nogat-handoff/1`` of the watershed named after its outlet (ADR-068), None
        without morphometry.
    """
    if watershed.morphometry is None:
        return None
    outlet = watershed.outlet
    name = watershed_name(outlet.latitude, outlet.longitude)
    return build_handoff(
        name=name,
        watershed=watershed_parameters(
            watershed.morphometry.model_dump(exclude_none=True), name
        ),
        watershed_origin=delineated_origin(outlet.latitude, outlet.longitude),
    )


@router.post("/delineate-watershed", response_model=DelineateResponse)
def delineate_watershed(
    request: DelineateRequest,
    response: Response,
    include_hypsometric_curve: bool = False,
    db: Session = Depends(get_db),
) -> DelineateResponse:
    """Delineate watershed boundary for a given point.

    Two modes:
    - **Precomputed** (threshold_m2 provided): uses pre-computed catchment graph
      and ST_Union boundary. Fast (~0.5-2s).
    - **Precise** (no threshold): BFS at threshold=1000 + raster-based boundary
      via pyflwdir. Precise to the exact click point (~2-5s first call).
    """
    try:
        # ---- Shared: transform + graph ----
        point_2180 = transform_wgs84_to_pl1992(request.latitude, request.longitude)

        cg = _loaded_catchment_graph(db)

        # ---- Determine mode ----
        if request.threshold_m2 is not None:
            mode = "precomputed"
            # Precomputed mode always includes hypsometric curve
            # (needed for GUI — precomputed mode always includes hypsometric curve)
            result = _delineate_precomputed(
                request,
                point_2180,
                cg,
                db,
                True,
            )
        else:
            mode = "precise"
            result = _delineate_precise(
                request,
                point_2180,
                cg,
                db,
                include_hypsometric_curve,
            )

        response.headers["Cache-Control"] = "public, max-age=3600"

        return DelineateResponse(
            mode=mode,
            watershed=result["watershed_response"],
            stream=result.get("stream_info"),
            upstream_segment_indices=result.get("upstream_segment_indices"),
            display_threshold_m2=result.get("display_threshold_m2"),
            info_message=result.get("info_message"),
            handoff=_watershed_handoff(result["watershed_response"]),
        )

    except HydrografError:
        raise
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise InvalidRequestError(
            "invalid_parameters", reason="invalid_parameters", cause=str(e)
        ) from e
    except Exception as e:
        logger.error(f"Error delineating watershed: {e}", exc_info=True)
        raise InternalError("delineation_failed", reason="delineation_failed") from e


@router.post(
    "/delineate-watershed/preview",
    response_model=DelineatePreviewResponse,
)
def delineate_watershed_preview(
    request: DelineatePreviewRequest,
    db: Session = Depends(get_db),
) -> DelineatePreviewResponse:
    """Sub-catchments the precomputed delineation will merge, for animation.

    Same selection as POST /delineate-watershed in precomputed mode (threshold
    floor, sub-catchment at the point, BFS, cascade) without the merge and
    statistics: simplified polygons in BFS order from the outlet, each with
    its depth. Precise mode has no preview: its raster boundary starts at the
    exact click point, not at a sub-catchment.

    Parameters
    ----------
    request : DelineatePreviewRequest
        Click point (WGS84) and the threshold of the precomputed mode.
    db : Session
        Database session (injected by FastAPI).

    Returns
    -------
    DelineatePreviewResponse
        Merge threshold, number of sub-catchments and their polygons by BFS depth.

    Raises
    ------
    NotFoundError
        ``not_found`` (404) when no catchment lies at the point.
    InvalidRequestError
        ``validation_error`` (400) for invalid parameters.
    StoreUnavailableError
        ``store_unavailable`` (503) when the catchment graph is not loaded.
    InternalError
        ``internal_error`` (500) on an unexpected failure.
    """
    try:
        point_2180 = transform_wgs84_to_pl1992(request.latitude, request.longitude)
        cg = _loaded_catchment_graph(db)
        selection = _select_precomputed(request.threshold_m2, point_2180, cg, db)
        segment_idxs, depths = cg.upstream_segments_by_depth(selection.outlet_idx)
        catchments = get_catchment_levels_feature_collection(
            segment_idxs[:_PREVIEW_MAX_CATCHMENTS],
            depths[:_PREVIEW_MAX_CATCHMENTS],
            selection.merge_threshold,
            _preview_tolerance_m(selection.area_km2),
            db,
        )
        return DelineatePreviewResponse(
            threshold_m2=selection.merge_threshold,
            segment_count=len(segment_idxs),
            catchments=catchments,
        )

    except HydrografError:
        raise
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise InvalidRequestError(
            "invalid_parameters", reason="invalid_parameters", cause=str(e)
        ) from e
    except Exception as e:
        logger.error(f"Error previewing watershed: {e}", exc_info=True)
        raise InternalError(
            "delineation_preview_failed", reason="delineation_preview_failed"
        ) from e
