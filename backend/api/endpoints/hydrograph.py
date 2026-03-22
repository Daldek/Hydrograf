"""
Hydrograph generation endpoint.

Provides API endpoint for generating direct runoff hydrographs
using the Hydrolog library. Supports SCS, Snyder, and Nash unit hydrograph models.

Uses CatchmentGraph (~11k nodes, ~0.5 MB) for watershed delineation
via BFS on pre-computed sub-catchments.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

# Hydrolog imports
from hydrolog.morphometry import WatershedParameters
from hydrolog.precipitation import BetaHietogram, BlockHietogram, EulerIIHietogram
from hydrolog.runoff import HydrographGenerator, NashIUH
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
    get_segment_outlet,
    get_stream_info_by_segment_idx,
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


def _compute_watershed(
    point_2180,
    request,
    db: Session,
) -> tuple[dict, int, float, WatershedResponse]:
    """Full watershed computation path (steps 3-9).

    Returns (morph_dict, cn, area_km2, watershed_response).
    """
    cg = get_catchment_graph()
    if not cg.loaded:
        raise HTTPException(
            status_code=503,
            detail="Graf zlewni nie został załadowany. Spróbuj ponownie.",
        )

    try:
        clicked_idx = cg.find_catchment_at_point(
            point_2180.x, point_2180.y, DEFAULT_THRESHOLD_M2, db
        )
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail="Nie znaleziono zlewni cząstkowej. Kliknij w obszarze zlewni.",
        ) from e

    segment_idx = cg.get_segment_idx(clicked_idx)
    segment = get_stream_info_by_segment_idx(segment_idx, DEFAULT_THRESHOLD_M2, db)

    upstream_indices = cg.traverse_upstream(clicked_idx)
    segment_idxs = cg.get_segment_indices(upstream_indices, DEFAULT_THRESHOLD_M2)

    stats = cg.aggregate_stats(upstream_indices)
    area_km2 = stats["area_km2"]

    if area_km2 > HYDROGRAPH_AREA_LIMIT_KM2:
        raise HTTPException(
            status_code=400,
            detail=f"Zlewnia ({area_km2:.1f} km2) przekracza limit SCS-CN "
            f"({HYDROGRAPH_AREA_LIMIT_KM2} km2)",
        )

    boundary_2180 = merge_catchment_boundaries(
        segment_idxs, DEFAULT_THRESHOLD_M2, db
    )
    if boundary_2180 is None:
        raise HTTPException(
            status_code=500,
            detail="Nie udało się zbudować granicy zlewni.",
        )

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

    outlet_info = get_segment_outlet(segment_idx, DEFAULT_THRESHOLD_M2, db)
    if outlet_info is not None:
        outlet_x, outlet_y = outlet_info["x"], outlet_info["y"]
    elif segment:
        outlet_x, outlet_y = segment["downstream_x"], segment["downstream_y"]
    else:
        outlet_x, outlet_y = point_2180.x, point_2180.y

    morph_dict = build_morph_dict_from_graph(
        cg,
        upstream_indices,
        boundary_2180,
        outlet_x,
        outlet_y,
        segment_idx,
        DEFAULT_THRESHOLD_M2,
        cn=cn,
        db=db,
    )

    # Build WatershedResponse for full-path callers
    outlet_elevation = stats.get("elevation_min_m") or 0.0
    outlet_lon, outlet_lat = transform_pl1992_to_wgs84(outlet_x, outlet_y)
    boundary_poly = boundary_to_polygon(boundary_2180)
    boundary_wgs84 = transform_polygon_pl1992_to_wgs84(boundary_poly)
    boundary_geojson = polygon_to_geojson_feature(
        boundary_wgs84,
        properties={"area_km2": round(area_km2, 2)},
    )
    watershed_resp = WatershedResponse(
        boundary_geojson=boundary_geojson,
        outlet=OutletInfo(
            latitude=outlet_lat,
            longitude=outlet_lon,
            elevation_m=outlet_elevation,
        ),
        area_km2=round(area_km2, 2),
        hydrograph_available=True,
        morphometry=MorphometricParameters(**morph_dict),
    )

    return morph_dict, cn, area_km2, watershed_resp


def _effective_duration_min(
    intensities_mm,
    timestep_min: float,
    s_mm: float,
    ia_mm: float,
) -> float:
    """Compute effective precipitation duration from hietogram and SCS-CN losses.

    Walks through the hietogram step by step, applying cumulative SCS-CN.
    Returns the number of minutes during which Pe(t) > 0.
    """
    import numpy as np

    intensities = np.asarray(intensities_mm)
    p_cum = np.cumsum(intensities)
    # Cumulative effective precip: Pe_cum = (P_cum - Ia)^2 / (P_cum - Ia + S)
    pe_cum = np.where(
        p_cum > ia_mm,
        (p_cum - ia_mm) ** 2 / (p_cum - ia_mm + s_mm),
        0.0,
    )
    # Per-step effective precip
    pe_step = np.diff(pe_cum, prepend=0.0)
    n_steps = int(np.count_nonzero(pe_step > 1e-6))
    return max(n_steps * timestep_min, timestep_min)


def _estimate_nash_params(
    request,
    morph_dict: dict,
    tc_min: float,
    precip_mm: float | None = None,
    cn: int | None = None,
    duration_min: float | None = None,
    precip_result=None,
    timestep_min: float = 5.0,
) -> tuple[dict, dict]:
    """Estimate Nash IUH parameters (n, k) using the requested method.

    Returns (uh_params, nash_meta) where nash_meta has extra info for response.
    """
    nash_meta = {"estimation": request.nash_estimation}

    if request.nash_estimation == "from_lutz":
        channel_length = morph_dict.get("channel_length_km")
        length_to_centroid = morph_dict.get("length_to_centroid_km")
        channel_slope = morph_dict.get("channel_slope_m_per_m")
        if not channel_length or not length_to_centroid or not channel_slope:
            raise HTTPException(
                status_code=400,
                detail="Metoda Lutza wymaga channel_length_km, "
                "length_to_centroid_km i channel_slope_m_per_m.",
            )
        nash = NashIUH.from_lutz(
            L_km=channel_length,
            Lc_km=length_to_centroid,
            slope=channel_slope,
            manning_n=0.035,
        )
        logger.info(
            f"Nash (Lutz): N={nash.n:.2f}, K={nash.k_min:.1f} min"
        )
    elif request.nash_estimation == "from_urban_regression":
        area_km2 = morph_dict["area_km2"]
        # Compute SCS-CN retention and initial abstraction
        s_mm = (25400.0 / cn - 254.0) if cn and cn < 100 else 0.0
        ia_mm = 0.2 * s_mm

        # Compute total effective precipitation
        if precip_mm and precip_mm > ia_mm:
            pe_mm = (precip_mm - ia_mm) ** 2 / (precip_mm - ia_mm + s_mm)
        else:
            pe_mm = 1.0  # fallback to avoid zero

        # Compute effective duration from hietogram (accounting for Ia)
        if precip_result is not None:
            eff_dur_min = _effective_duration_min(
                precip_result.intensities_mm, timestep_min, s_mm, ia_mm
            )
        else:
            eff_dur_min = duration_min or 60.0

        urban_fraction = morph_dict.get("imperviousness") or 0.0
        eff_dur_h = eff_dur_min / 60.0
        nash = NashIUH.from_urban_regression(
            area_km2=area_km2,
            effective_precip_mm=pe_mm,
            duration_h=eff_dur_h,
            urban_fraction=urban_fraction,
        )
        nash_meta["urban_fraction"] = urban_fraction
        nash_meta["effective_precip_mm"] = round(pe_mm, 2)
        nash_meta["duration_h"] = round(eff_dur_h, 4)
        logger.info(
            f"Nash (urban): N={nash.n:.2f}, K={nash.k_min:.1f} min, "
            f"Pe={pe_mm:.1f} mm, D_eff={eff_dur_min:.0f} min, "
            f"U={urban_fraction:.2f}"
        )
    else:
        # from_tc (default)
        nash = NashIUH.from_tc(tc_min=tc_min, n=request.nash_n)
        logger.info(
            f"Nash (from_tc): N={nash.n:.2f}, K={nash.k_min:.1f} min"
        )

    nash_meta["n"] = round(nash.n, 3)
    nash_meta["k_min"] = round(nash.k_min, 2)

    return {"n": nash.n, "k": nash.k_min, "k_unit": "min"}, nash_meta


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

        # ===== Fast path: use pre-computed morphometry =====
        watershed_resp = None
        if request.morphometry is not None:
            morph_dict = request.morphometry.model_dump(exclude_none=True)
            cn = morph_dict.get("cn") or DEFAULT_CN
            area_km2 = morph_dict["area_km2"]
            logger.info(
                f"Fast path: using pre-computed morphometry "
                f"(area={area_km2:.2f} km2, CN={cn})"
            )
        else:
            # ===== Full path: compute watershed from scratch =====
            morph_dict, cn, area_km2, watershed_resp = _compute_watershed(
                point_2180, request, db
            )

        # ===== Get precipitation (uses click point for IDW) =====
        precip_mm = get_precipitation(point_2180, duration_str, probability, db)

        if precip_mm is None:
            raise HTTPException(
                status_code=400,
                detail=f"Brak danych opadowych dla ({request.latitude:.4f}, "
                f"{request.longitude:.4f})",
            )

        logger.debug(
            f"Precipitation: {precip_mm:.1f} mm for {duration_str}, p={probability}%"
        )

        # ===== Create Hydrolog objects =====
        watershed_params = WatershedParameters.from_dict(morph_dict)
        # Nash from_lutz / from_urban_regression don't need tc
        nash_needs_tc = (
            request.uh_model == "nash" and request.nash_estimation == "from_tc"
        )
        if request.uh_model != "nash" or nash_needs_tc:
            tc_method = "kirpich" if nash_needs_tc else request.tc_method
            tc_min = watershed_params.calculate_tc(method=tc_method)
            logger.debug(f"Time of concentration: {tc_min:.1f} min ({tc_method})")
        else:
            tc_method = None
            tc_min = None

        # Create hietogram
        if request.hietogram_type == "beta":
            hietogram = BetaHietogram(
                alpha=request.hietogram_alpha,
                beta=request.hietogram_beta,
            )
        else:
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

        # ===== Generate hydrograph =====
        nash_meta = {}
        if request.uh_model == "snyder":
            channel_length = morph_dict.get("channel_length_km")
            length_to_centroid = morph_dict.get("length_to_centroid_km")
            if not channel_length or not length_to_centroid:
                raise HTTPException(
                    status_code=400,
                    detail="Model Snydera wymaga channel_length_km i "
                    "length_to_centroid_km w parametrach zlewni.",
                )
            generator = HydrographGenerator(
                area_km2=area_km2,
                cn=cn,
                tc_min=tc_min,
                uh_model="snyder",
                uh_params={
                    "L_km": channel_length,
                    "Lc_km": length_to_centroid,
                    "ct": request.snyder_ct or 1.5,
                    "cp": request.snyder_cp or 0.6,
                },
            )
        elif request.uh_model == "nash":
            nash_params, nash_meta = _estimate_nash_params(
                request, morph_dict, tc_min,
                precip_mm=precip_mm, cn=cn, duration_min=float(duration_min),
                precip_result=precip_result,
                timestep_min=request.timestep_min,
            )
            generator = HydrographGenerator(
                area_km2=area_km2,
                cn=cn,
                uh_model="nash",
                uh_params=nash_params,
            )
        else:
            generator = HydrographGenerator(
                area_km2=area_km2,
                cn=cn,
                tc_min=tc_min,
                uh_model="scs",
            )

        hydro_result = generator.generate(
            precipitation=precip_result,
            timestep_min=request.timestep_min,
        )

        # ===== Build response =====
        response = HydrographResponse(
            watershed=watershed_resp,
            precipitation=PrecipitationInfo(
                total_mm=round(precip_mm, 2),
                duration_min=float(duration_min),
                probability_percent=probability,
                timestep_min=request.timestep_min,
                times_min=precip_result.times_min.tolist(),
                intensities_mm=[
                    round(x, 3) for x in precip_result.intensities_mm.tolist()
                ],
                effective_mm=[
                    round(x, 3) for x in hydro_result.effective_precip_mm.tolist()
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
                tc_min=round(tc_min, 1) if tc_min is not None else None,
                tc_method=tc_method,
                hietogram_type=request.hietogram_type,
                uh_model=request.uh_model,
                nash_estimation=nash_meta.get("estimation"),
                nash_n=nash_meta.get("n"),
                nash_k_min=nash_meta.get("k_min"),
                nash_urban_fraction=nash_meta.get("urban_fraction"),
                nash_effective_precip_mm=nash_meta.get("effective_precip_mm"),
                nash_duration_h=nash_meta.get("duration_h"),
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
        "durations": sorted(VALID_DURATIONS_STR, key=lambda d: DURATION_STR_TO_MIN[d]),
        "probabilities": sorted(VALID_PROBABILITIES),
        "tc_methods": ["kirpich", "nrcs", "giandotti"],
        "hietogram_types": ["beta", "block", "euler_ii"],
        "uh_models": ["scs", "nash", "snyder"],
        "snyder_defaults": {"ct": 1.5, "cp": 0.6},
        "nash_estimation_methods": ["from_tc", "from_lutz", "from_urban_regression"],
        "nash_defaults": {"n": 3.0},
        "area_limit_km2": HYDROGRAPH_AREA_LIMIT_KM2,
    }
