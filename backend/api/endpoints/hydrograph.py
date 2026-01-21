"""
Hydrograph generation endpoint.

Provides API endpoint for generating SCS-CN based direct runoff hydrographs
using the Hydrolog library.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.database import get_db
from core.morphometry import build_morphometric_params
from core.precipitation import (
    DURATION_STR_TO_MIN,
    VALID_DURATIONS_STR,
    VALID_PROBABILITIES,
    get_precipitation,
    validate_duration,
    validate_probability,
)
from core.watershed import (
    build_boundary,
    calculate_watershed_area_km2,
    find_nearest_stream,
    traverse_upstream,
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

# Hydrolog imports
from hydrolog.morphometry import WatershedParameters
from hydrolog.precipitation import BetaHietogram, BlockHietogram, EulerIIHietogram
from hydrolog.runoff import HydrographGenerator

logger = logging.getLogger(__name__)
router = APIRouter()

# SCS-CN method limit [km2]
HYDROGRAPH_AREA_LIMIT_KM2 = 250.0

# Default CN if land cover data unavailable
DEFAULT_CN = 75

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
    time of concentration calculation.

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
    HTTPException 500
        On internal server error
    """
    try:
        logger.info(
            f"Generating hydrograph for ({request.latitude:.6f}, {request.longitude:.6f}), "
            f"duration={request.duration}, p={request.probability}%"
        )

        # ===== STEP 1: Validate parameters =====
        duration_str = validate_duration(request.duration)
        probability = validate_probability(request.probability)
        duration_min = DURATION_STR_TO_MIN[duration_str]

        # ===== STEP 2: Delineate watershed =====
        point_2180 = transform_wgs84_to_pl1992(request.latitude, request.longitude)

        outlet_cell = find_nearest_stream(point_2180, db)
        if outlet_cell is None:
            raise HTTPException(
                status_code=404,
                detail="Nie znaleziono cieku w tym miejscu",
            )

        cells = traverse_upstream(outlet_cell.id, db)
        area_km2 = calculate_watershed_area_km2(cells)

        # ===== STEP 3: Check area limit =====
        if area_km2 > HYDROGRAPH_AREA_LIMIT_KM2:
            raise HTTPException(
                status_code=400,
                detail=f"Zlewnia ({area_km2:.1f} km2) przekracza limit SCS-CN "
                f"({HYDROGRAPH_AREA_LIMIT_KM2} km2)",
            )

        # ===== STEP 4: Build boundary and morphometry =====
        boundary_2180 = build_boundary(cells, method="convex")

        # TODO: Calculate CN from land cover when available
        cn = DEFAULT_CN

        morph_dict = build_morphometric_params(cells, boundary_2180, outlet_cell, cn)

        # ===== STEP 5: Get precipitation =====
        centroid_2180 = boundary_2180.centroid
        precip_mm = get_precipitation(centroid_2180, duration_str, probability, db)

        if precip_mm is None:
            raise HTTPException(
                status_code=400,
                detail=f"Brak danych opadowych dla ({request.latitude:.4f}, "
                f"{request.longitude:.4f})",
            )

        logger.debug(f"Precipitation: {precip_mm:.1f} mm for {duration_str}, p={probability}%")

        # ===== STEP 6: Create Hydrolog objects =====
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

        # ===== STEP 7: Generate hydrograph =====
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

        # ===== STEP 8: Build response =====
        boundary_wgs84 = transform_polygon_pl1992_to_wgs84(boundary_2180)
        boundary_geojson = polygon_to_geojson_feature(
            boundary_wgs84,
            properties={"area_km2": round(area_km2, 2)},
        )

        outlet_lon, outlet_lat = transform_pl1992_to_wgs84(outlet_cell.x, outlet_cell.y)

        response = HydrographResponse(
            watershed=WatershedResponse(
                boundary_geojson=boundary_geojson,
                outlet=OutletInfo(
                    latitude=outlet_lat,
                    longitude=outlet_lon,
                    elevation_m=outlet_cell.elevation,
                ),
                cell_count=len(cells),
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
                intensities_mm=[round(x, 3) for x in precip_result.intensities_mm.tolist()],
            ),
            hydrograph=HydrographInfo(
                times_min=hydro_result.hydrograph.times_min.tolist(),
                discharge_m3s=[round(x, 4) for x in hydro_result.hydrograph.discharge_m3s.tolist()],
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
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating hydrograph: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error during hydrograph generation",
        )


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
