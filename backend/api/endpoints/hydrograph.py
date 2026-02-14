"""
Hydrograph generation endpoint.

Provides API endpoint for generating SCS-CN based direct runoff hydrographs
using the Hydrolog library.

Uses CatchmentGraph (~87k nodes) for watershed delineation instead of
FlowGraph (19.7M cells), eliminating runtime dependency on the large
flow_network table.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

# Hydrolog imports
from hydrolog.morphometry import WatershedParameters
from hydrolog.precipitation import BetaHietogram, BlockHietogram, EulerIIHietogram
from hydrolog.runoff import HydrographGenerator
from sqlalchemy.orm import Session

from core.catchment_graph import get_catchment_graph
from core.constants import DEFAULT_CN, DEFAULT_THRESHOLD_M2, HYDROGRAPH_AREA_LIMIT_KM2
from core.database import get_db
from core.land_cover import get_land_cover_for_boundary
from core.precipitation import (
    DURATION_STR_TO_MIN,
    VALID_DURATIONS_STR,
    VALID_PROBABILITIES,
    get_precipitation,
    validate_duration,
    validate_probability,
)
from core.watershed_service import (
    boundary_to_polygon,
    build_morph_dict_from_graph,
    find_nearest_stream_segment,
    get_segment_outlet,
    merge_catchment_boundaries,
)
from models.schemas import (
    HydrographInfo,
    HydrographMetadata,
    HydrographRequest,
    HydrographResponse,
    MorphometricParameters,
    OutletInfo,
    PrecipitationInfo,
    WaterBalance,
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

# Hietogram factory
HIETOGRAM_CLASSES = {
    "beta": lambda: BetaHietogram(alpha=2.0, beta=5.0),
    "block": lambda: BlockHietogram(),
    "euler_ii": lambda: EulerIIHietogram(peak_position=0.33),
}


@router.post("/generate-hydrograph", response_model=HydrographResponse)
def generate_hydrograph(
    request: HydrographRequest,
    db: Session = Depends(get_db),
) -> HydrographResponse:
    """
    Generate direct runoff hydrograph for a given point.

    Uses SCS-CN method with configurable hietogram distribution and
    time of concentration calculation. Watershed delineation via
    CatchmentGraph (~87k nodes, ~5-50ms BFS).

    Parameters
    ----------
    request : HydrographRequest
        Request with coordinates, duration, probability, and options
    db : Session
        Database session (injected by FastAPI)

    Returns
    -------
    HydrographResponse
        Complete hydrograph with watershed info, precipitation, and results

    Raises
    ------
    HTTPException 404
        When no stream found near the point
    HTTPException 400
        When watershed is too large (> 250 km2) or invalid parameters
    HTTPException 503
        When catchment graph is not loaded
    HTTPException 500
        On internal server error
    """
    try:
        logger.info(
            "Generating hydrograph for "
            f"({request.latitude:.6f}, {request.longitude:.6f}), "
            f"duration={request.duration}, p={request.probability}%"
        )

        # ===== STEP 1: Validate parameters =====
        duration_str = validate_duration(request.duration)
        probability = validate_probability(request.probability)
        duration_min = DURATION_STR_TO_MIN[duration_str]

        # ===== STEP 2: Transform coordinates =====
        point_2180 = transform_wgs84_to_pl1992(request.latitude, request.longitude)

        # ===== STEP 3: Get CatchmentGraph =====
        cg = get_catchment_graph()
        if not cg.loaded:
            raise HTTPException(
                status_code=503,
                detail="Graf zlewni nie został załadowany. Spróbuj ponownie.",
            )

        # ===== STEP 4: Find nearest stream segment =====
        segment = find_nearest_stream_segment(
            point_2180.x, point_2180.y, DEFAULT_THRESHOLD_M2, db
        )
        if segment is None:
            raise HTTPException(
                status_code=404,
                detail="Nie znaleziono cieku w tym miejscu",
            )

        segment_idx = segment["segment_idx"]

        # ===== STEP 5: Find catchment at point and traverse upstream =====
        try:
            clicked_idx = cg.find_catchment_at_point(
                point_2180.x, point_2180.y, DEFAULT_THRESHOLD_M2, db
            )
        except ValueError as e:
            raise HTTPException(
                status_code=404,
                detail="Nie znaleziono zlewni cząstkowej. Kliknij w obszarze zlewni.",
            ) from e

        upstream_indices = cg.traverse_upstream(clicked_idx)
        segment_idxs = cg.get_segment_indices(upstream_indices, DEFAULT_THRESHOLD_M2)

        # ===== STEP 6: Aggregate stats and check area limit =====
        stats = cg.aggregate_stats(upstream_indices)
        area_km2 = stats["area_km2"]

        if area_km2 > HYDROGRAPH_AREA_LIMIT_KM2:
            raise HTTPException(
                status_code=400,
                detail=f"Zlewnia ({area_km2:.1f} km2) przekracza limit SCS-CN "
                f"({HYDROGRAPH_AREA_LIMIT_KM2} km2)",
            )

        # ===== STEP 7: Build boundary =====
        boundary_2180 = merge_catchment_boundaries(
            segment_idxs, DEFAULT_THRESHOLD_M2, db
        )
        if boundary_2180 is None:
            raise HTTPException(
                status_code=500,
                detail="Nie udało się zbudować granicy zlewni.",
            )

        boundary_poly = boundary_to_polygon(boundary_2180)

        # ===== STEP 8: Calculate CN from land cover =====
        try:
            lc_data = get_land_cover_for_boundary(boundary_2180, db)
            if lc_data:
                cn = lc_data["weighted_cn"]
                logger.info(f"CN={cn} calculated from land cover")
            else:
                cn = DEFAULT_CN
                logger.info(f"CN={cn} (default, no land cover data)")
        except Exception as e:
            logger.warning(
                f"Failed to calculate CN from land cover: {e}, using default"
            )
            cn = DEFAULT_CN

        # ===== STEP 9: Build morphometric dict =====
        # Get outlet coordinates
        outlet_info = get_segment_outlet(segment_idx, DEFAULT_THRESHOLD_M2, db)
        if outlet_info is not None:
            outlet_x, outlet_y = outlet_info["x"], outlet_info["y"]
        else:
            outlet_x, outlet_y = segment["downstream_x"], segment["downstream_y"]

        morph_dict = build_morph_dict_from_graph(
            cg,
            upstream_indices,
            boundary_2180,
            outlet_x,
            outlet_y,
            segment_idx,
            DEFAULT_THRESHOLD_M2,
            cn=cn,
        )

        # Outlet elevation from aggregated stats
        outlet_elevation = stats.get("elevation_min_m") or 0.0

        # ===== STEP 10: Get precipitation =====
        centroid_2180 = boundary_2180.centroid
        precip_mm = get_precipitation(centroid_2180, duration_str, probability, db)

        if precip_mm is None:
            raise HTTPException(
                status_code=400,
                detail=f"Brak danych opadowych dla ({request.latitude:.4f}, "
                f"{request.longitude:.4f})",
            )

        logger.debug(
            f"Precipitation: {precip_mm:.1f} mm for {duration_str}, p={probability}%"
        )

        # ===== STEP 11: Create Hydrolog objects =====
        watershed_params = WatershedParameters.from_dict(morph_dict)
        tc_min = watershed_params.calculate_tc(method=request.tc_method)

        logger.debug(f"Time of concentration: {tc_min:.1f} min ({request.tc_method})")

        # Create hietogram
        hietogram_factory = HIETOGRAM_CLASSES.get(request.hietogram_type)
        if hietogram_factory is None:
            raise HTTPException(
                status_code=400,
                detail=f"Nieznany typ hietogramu: {request.hietogram_type}",
            )

        hietogram = hietogram_factory()
        precip_result = hietogram.generate(
            total_mm=precip_mm,
            duration_min=float(duration_min),
            timestep_min=request.timestep_min,
        )

        # ===== STEP 12: Generate hydrograph =====
        generator = HydrographGenerator(
            area_km2=morph_dict["area_km2"],
            cn=cn,
            tc_min=tc_min,
            uh_model="scs",
        )

        hydro_result = generator.generate(
            precipitation=precip_result,
            timestep_min=request.timestep_min,
        )

        # ===== STEP 13: Build response =====
        boundary_wgs84 = transform_polygon_pl1992_to_wgs84(boundary_poly)
        boundary_geojson = polygon_to_geojson_feature(
            boundary_wgs84,
            properties={"area_km2": round(area_km2, 2)},
        )

        outlet_lon, outlet_lat = transform_pl1992_to_wgs84(outlet_x, outlet_y)

        response = HydrographResponse(
            watershed=WatershedResponse(
                boundary_geojson=boundary_geojson,
                outlet=OutletInfo(
                    latitude=outlet_lat,
                    longitude=outlet_lon,
                    elevation_m=outlet_elevation,
                ),
                cell_count=0,  # Not applicable for graph-based approach
                area_km2=round(area_km2, 2),
                hydrograph_available=True,
                morphometry=MorphometricParameters(**morph_dict),
            ),
            precipitation=PrecipitationInfo(
                total_mm=round(precip_mm, 2),
                duration_min=float(duration_min),
                probability_percent=probability,
                timestep_min=request.timestep_min,
                times_min=precip_result.times_min.tolist(),
                intensities_mm=[
                    round(x, 3) for x in precip_result.intensities_mm.tolist()
                ],
            ),
            hydrograph=HydrographInfo(
                times_min=hydro_result.hydrograph.times_min.tolist(),
                discharge_m3s=[
                    round(x, 4) for x in hydro_result.hydrograph.discharge_m3s.tolist()
                ],
                peak_discharge_m3s=round(hydro_result.peak_discharge_m3s, 3),
                time_to_peak_min=round(hydro_result.time_to_peak_min, 1),
                total_volume_m3=round(hydro_result.total_volume_m3, 0),
            ),
            water_balance=WaterBalance(
                total_precip_mm=round(hydro_result.total_precip_mm, 2),
                total_effective_mm=round(hydro_result.total_effective_mm, 2),
                runoff_coefficient=round(hydro_result.runoff_coefficient, 3),
                cn_used=hydro_result.cn_used,
                retention_mm=round(hydro_result.retention_mm, 2),
                initial_abstraction_mm=round(hydro_result.initial_abstraction_mm, 2),
            ),
            metadata=HydrographMetadata(
                tc_min=round(tc_min, 1),
                tc_method=request.tc_method,
                hietogram_type=request.hietogram_type,
                uh_model="scs",
            ),
        )

        logger.info(
            f"Hydrograph generated: Qmax={hydro_result.peak_discharge_m3s:.2f} m3/s, "
            f"tp={hydro_result.time_to_peak_min:.0f} min, "
            f"V={hydro_result.total_volume_m3:.0f} m3"
        )

        return response

    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error in hydrograph generation: {e}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Error generating hydrograph: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error during hydrograph generation",
        ) from e


@router.get("/scenarios")
def list_scenarios() -> dict:
    """
    List available hydrograph generation scenarios.

    Returns the valid combinations of duration and probability values
    that can be used for hydrograph generation.

    Returns
    -------
    dict
        Available durations, probabilities, tc_methods, and hietogram_types
    """
    return {
        "durations": sorted(VALID_DURATIONS_STR),
        "probabilities": sorted(VALID_PROBABILITIES),
        "tc_methods": ["kirpich", "scs_lag", "giandotti"],
        "hietogram_types": ["beta", "block", "euler_ii"],
        "area_limit_km2": HYDROGRAPH_AREA_LIMIT_KM2,
    }
