"""
Hydrograph generation endpoint.

Provides API endpoint for generating direct runoff hydrographs
using the Hydrolog library. Supports SCS, Snyder, and Nash unit hydrograph models.

Uses CatchmentGraph (~11k nodes, ~0.5 MB) for watershed delineation
via BFS on pre-computed sub-catchments.
"""

import logging
from collections.abc import Callable
from typing import Any

import numpy as np
import numpy.typing as npt
from fastapi import APIRouter, Depends

# Hydrolog imports
from hydrolog.exceptions import InvalidParameterError
from hydrolog.morphometry import WatershedParameters
from hydrolog.precipitation import (
    BetaHietogram,
    BlockHietogram,
    EulerIIHietogram,
    Hietogram,
    HietogramResult,
)
from hydrolog.runoff import AMC, SCSCN, HydrographGenerator, NashIUH
from hydrolog.time.concentration import ConcentrationTime
from shapely.geometry import Point
from sqlalchemy.orm import Session

from api.errors import problem_responses
from core.catchment_graph import get_catchment_graph
from core.constants import DEFAULT_CN, DEFAULT_THRESHOLD_M2, HYDROGRAPH_AREA_LIMIT_KM2
from core.database import get_db
from core.errors import (
    CalculationError,
    HydrografError,
    InternalError,
    InvalidRequestError,
    NoDataError,
    NotFoundError,
    StoreUnavailableError,
    UnsupportedError,
)
from core.handoff import (
    PRODUCER,
    DesignHydrograph,
    build_handoff,
    curve_number_runoff,
    delineated_origin,
    design_storm,
    given_origin,
    hydrograph_result,
    pmaxtp_origin,
    rainfall_series,
    watershed_name,
    watershed_parameters,
)
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
    CUSTOM_PRECIPITATION_MAX_STEPS,
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

# Manning's n of the channel in Lutz's estimation of Nash's n and K
LUTZ_MANNING_N = 0.035

# Relative position of the peak of the Euler II hyetograph
EULER_II_PEAK_POSITION = 0.33

# The options of each tc method the request gives (provenance of the hand-off)
_TC_OPTIONS = {
    "faa": ("tc_overland_length_km", "tc_runoff_coeff"),
    "kerby": ("tc_overland_length_km", "tc_retardance"),
    "kerby_kirpich": ("tc_overland_length_km", "tc_retardance"),
}


def _require_area_within_limit(area_km2: float) -> None:
    """Refuse a catchment above the SCS-CN limit, delineated or given in the request.

    Parameters
    ----------
    area_km2 : float
        Area of the catchment [km2].

    Raises
    ------
    UnsupportedError
        ``unsupported`` (422, ``catchment_too_large``) above
        ``HYDROGRAPH_AREA_LIMIT_KM2``, the ``area_limit_km2`` of ``GET /api/scenarios``.
    """
    if area_km2 > HYDROGRAPH_AREA_LIMIT_KM2:
        raise UnsupportedError(
            "catchment_too_large",
            reason="area_exceeds_limit",
            area_km2=float(area_km2),
            limit_km2=HYDROGRAPH_AREA_LIMIT_KM2,
        )


def _compute_watershed(
    point_2180: Point,
    request: HydrographRequest,
    db: Session,
) -> tuple[dict[str, Any], float, float, WatershedResponse]:
    """Full watershed computation path (steps 3-9).

    Returns (morph_dict, cn, area_km2, watershed_response).
    """
    cg = get_catchment_graph()
    if not cg.ensure_loaded(db):
        raise StoreUnavailableError(
            "catchment_graph_unavailable", reason="catchment_graph_unavailable"
        )

    try:
        clicked_idx = cg.find_catchment_at_point(
            point_2180.x, point_2180.y, DEFAULT_THRESHOLD_M2, db
        )
    except ValueError as e:
        raise NotFoundError(
            "no_catchment_at_point",
            reason="no_catchment_at_point",
            threshold_m2=DEFAULT_THRESHOLD_M2,
        ) from e

    segment_idx = cg.get_segment_idx(clicked_idx)
    segment = get_stream_info_by_segment_idx(segment_idx, DEFAULT_THRESHOLD_M2, db)

    upstream_indices = cg.traverse_upstream(clicked_idx)
    segment_idxs = cg.get_segment_indices(upstream_indices, DEFAULT_THRESHOLD_M2)

    stats = cg.aggregate_stats(upstream_indices, outlet_idx=clicked_idx)
    area_km2 = stats["area_km2"]

    _require_area_within_limit(area_km2)

    boundary_2180 = merge_catchment_boundaries(segment_idxs, DEFAULT_THRESHOLD_M2, db)
    if boundary_2180 is None:
        raise CalculationError("boundary_build_failed", reason="boundary_build_failed")

    imperviousness = None
    try:
        lc_data = get_land_cover_for_boundary(boundary_2180, db)
        if lc_data:
            cn = lc_data["weighted_cn"]
            imperviousness = lc_data.get("weighted_imperviousness")
            logger.info(f"CN={cn} calculated from land cover")
        else:
            cn = DEFAULT_CN
            logger.info(f"CN={cn} (default, no land cover data)")
    except Exception as e:
        logger.warning(f"Failed to calculate CN from land cover: {e}, using default")
        cn = DEFAULT_CN
        imperviousness = None

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
        imperviousness=imperviousness,
        db=db,
        outlet_idx=clicked_idx,
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
    # Remove private key before passing to Pydantic schema
    morph_dict.pop("_main_channel_nodes", None)

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
    intensities_mm: npt.ArrayLike,
    timestep_min: float,
    s_mm: float,
    ia_mm: float,
) -> float:
    """Compute effective precipitation duration from hietogram and SCS-CN losses.

    Walks through the hietogram step by step, applying cumulative SCS-CN.
    Returns the number of minutes during which Pe(t) > 0.
    """
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


def _calculate_tc(
    method: str,
    wp: WatershedParameters,
    morph_dict: dict[str, Any],
    request: HydrographRequest,
) -> float:
    """Calculate time of concentration using the specified method.

    For kirpich/nrcs/giandotti delegates to WatershedParameters.calculate_tc().
    For faa/kerby/kerby_kirpich uses ConcentrationTime static methods directly.
    """
    if method == "nrcs" and wp.channel_slope_m_per_m is not None:
        saved_slope = wp.channel_slope_m_per_m
        saved_length = wp.channel_length_km
        wp.channel_slope_m_per_m = None  # force mean_slope
        # Use hydraulic length (longest flow path) per TR-55
        hydraulic = morph_dict.get("hydraulic_length_km")
        if hydraulic:
            wp.channel_length_km = None  # force Hydrolog to use length_km
            # But length_km is Euclidean — override with hydraulic
            saved_wlength = wp.length_km
            wp.length_km = hydraulic
            tc = float(wp.calculate_tc(method=method))
            wp.length_km = saved_wlength
        else:
            tc = float(wp.calculate_tc(method=method))
        wp.channel_slope_m_per_m = saved_slope
        wp.channel_length_km = saved_length
        return tc

    if method == "kirpich":
        hydraulic = morph_dict.get("hydraulic_length_km")
        if hydraulic:
            saved = wp.channel_length_km
            saved_wl = wp.length_km
            wp.channel_length_km = None
            wp.length_km = hydraulic
            tc = float(wp.calculate_tc(method=method))
            wp.length_km = saved_wl
            wp.channel_length_km = saved
            return tc
        return float(wp.calculate_tc(method=method))

    if method == "giandotti":
        return float(wp.calculate_tc(method=method))

    if method == "faa":
        runoff_coeff = request.tc_runoff_coeff
        if runoff_coeff is None:
            cn = morph_dict.get("cn") or 75
            s_mm = (25400.0 / cn - 254.0) if cn < 100 else 0.0
            runoff_coeff = 1.0 - s_mm / (s_mm + 25.4) if s_mm > 0 else 0.95
        slope = morph_dict.get("mean_slope_m_per_m") or 0.01
        # FAA requires overland flow length (0.015-3 km), NOT watershed length
        length = request.tc_overland_length_km
        if length is None:
            raise ValueError(
                "Metoda FAA wymaga podania długości spływu powierzchniowego "
                "(tc_overland_length_km). Typowy zakres: 0.015-3 km."
            )
        return float(
            ConcentrationTime.faa(
                length_km=length,
                slope_m_per_m=slope,
                runoff_coeff=runoff_coeff,
            )
        )

    if method == "kerby":
        retardance = request.tc_retardance or 0.4
        slope = morph_dict.get("mean_slope_m_per_m") or 0.01
        # Kerby requires overland flow length (max ~0.366 km), NOT watershed length
        length = request.tc_overland_length_km
        if length is None:
            raise ValueError(
                "Metoda Kerby wymaga podania długości spływu powierzchniowego "
                "(tc_overland_length_km). Typowy zakres: 0.01-0.366 km."
            )
        return float(
            ConcentrationTime.kerby(
                length_km=length,
                slope_m_per_m=slope,
                retardance=retardance,
            )
        )

    if method == "kerby_kirpich":
        retardance = request.tc_retardance or 0.4
        # Prefer BDOT-based real channel length if available
        real_channel = morph_dict.get("real_channel_length_km")
        channel_length = real_channel or morph_dict.get("channel_length_km") or 1.0
        channel_slope = morph_dict.get("channel_slope_m_per_m") or 0.01
        # Prefer user-provided overland length, fallback to total - channel
        if request.tc_overland_length_km is not None:
            overland_length = request.tc_overland_length_km
        else:
            total_length = (
                morph_dict.get("hydraulic_length_km")
                or morph_dict.get("length_km")
                or channel_length
            )
            overland_length = max(total_length - channel_length, 0.1)
        overland_slope = morph_dict.get("mean_slope_m_per_m") or 0.01
        return float(
            ConcentrationTime.kerby_kirpich(
                overland_length_km=overland_length,
                overland_slope_m_per_m=overland_slope,
                retardance=retardance,
                channel_length_km=channel_length,
                channel_slope_m_per_m=channel_slope,
            )
        )

    raise ValueError(f"Unknown tc method: {method}")


def _estimate_nash_params(
    request: HydrographRequest,
    morph_dict: dict[str, Any],
    tc_min: float | None,
    precip_mm: float | None = None,
    cn: float | None = None,
    duration_min: float | None = None,
    precip_result: Any = None,
    timestep_min: float = 5.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Estimate Nash IUH parameters (n, k) using the requested method.

    Returns (uh_params, nash_meta) where nash_meta has extra info for response.
    """
    nash_meta: dict[str, Any] = {"estimation": request.nash_estimation}

    if request.nash_estimation == "from_lutz":
        channel_length = morph_dict.get("channel_length_km")
        length_to_centroid = morph_dict.get("length_to_centroid_km")
        channel_slope = morph_dict.get("channel_slope_m_per_m")
        if not channel_length or not length_to_centroid or not channel_slope:
            raise UnsupportedError(
                "lutz_parameters_missing",
                reason="missing_morphometry",
                method="from_lutz",
            )
        nash = NashIUH.from_lutz(
            L_km=channel_length,
            Lc_km=length_to_centroid,
            slope=channel_slope,
            manning_n=LUTZ_MANNING_N,
        )
        logger.info(f"Nash (Lutz): N={nash.n:.2f}, K={nash.k_min:.1f} min")
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
        # from_tc: deprecated in Hydrolog; generate_hydrograph computes tc_min for it
        if tc_min is None:
            raise ValueError("Nash from_tc needs the time of concentration")
        nash = NashIUH.from_tc(tc_min=tc_min, n=request.nash_n)
        logger.info(f"Nash (from_tc): N={nash.n:.2f}, K={nash.k_min:.1f} min")

    nash_meta["n"] = round(nash.n, 3)
    nash_meta["k_min"] = round(nash.k_min, 2)

    return {"n": nash.n, "k": nash.k_min, "k_unit": "min"}, nash_meta


# Hietogram factory
HIETOGRAM_CLASSES: dict[str, Callable[[], Hietogram]] = {
    "beta": lambda: BetaHietogram(alpha=2.0, beta=5.0),
    "block": lambda: BlockHietogram(),
    "euler_ii": lambda: EulerIIHietogram(peak_position=EULER_II_PEAK_POSITION),
}

# Request AMC code -> Hydrolog enum
AMC_BY_CODE = {"I": AMC.I, "II": AMC.II, "III": AMC.III}


def _custom_hietogram(depths_mm: list[float], timestep_min: float) -> HietogramResult:
    """Wrap a user rainfall series in Hydrolog's hietogram result.

    Parameters
    ----------
    depths_mm : list[float]
        Rainfall depth in each interval [mm].
    timestep_min : float
        Interval length [min].

    Returns
    -------
    HietogramResult
        Series with interval end times ``k * timestep_min`` (k = 1..n),
        the same convention as Hydrolog's hietogram classes.
    """
    depths = np.asarray(depths_mm, dtype=np.float64)
    n_steps = len(depths)
    return HietogramResult(
        times_min=np.arange(1, n_steps + 1, dtype=np.float64) * timestep_min,
        intensities_mm=depths,
        total_mm=float(depths.sum()),
        duration_min=n_steps * timestep_min,
        timestep_min=timestep_min,
    )


def _design_storm(request: HydrographRequest) -> tuple[str, float]:
    """Return the validated duration and probability of the PMAXTP design storm.

    Parameters
    ----------
    request : HydrographRequest
        Request without an own rainfall series.

    Returns
    -------
    tuple[str, float]
        Duration key (e.g. ``"1h"``) and probability [%].

    Raises
    ------
    InvalidRequestError
        ``validation_error`` (400) when the duration or the probability is missing
        (``HydrographRequest`` rejects such a request already).
    ValueError
        When the duration or the probability is not one of PMAXTP's values.
    """
    if request.duration is None or request.probability is None:
        raise InvalidRequestError(
            "invalid_parameters",
            reason="invalid_parameters",
            cause="duration and probability are required without custom_precipitation",
        )
    return validate_duration(request.duration), validate_probability(
        request.probability
    )


def _handoff_watershed(
    request: HydrographRequest, watershed_resp: WatershedResponse | None
) -> tuple[str, dict[str, Any]]:
    """Return the name and the provenance of the watershed of the hand-off.

    Parameters
    ----------
    request : HydrographRequest
        The request.
    watershed_resp : WatershedResponse or None
        The watershed the endpoint delineated, None for a given morphometry.

    Returns
    -------
    tuple[str, dict[str, Any]]
        A delineated watershed is named after its outlet. A given morphometry is
        named after the outlet of its ``morphometry_origin`` and comes from Hydrograf
        with the fields the person changed; without the origin it is named after the
        request point and is the user's.
    """
    if watershed_resp is not None:
        outlet = watershed_resp.outlet
        return (
            watershed_name(outlet.latitude, outlet.longitude),
            delineated_origin(outlet.latitude, outlet.longitude),
        )
    origin = request.morphometry_origin
    if origin is None:
        return watershed_name(request.latitude, request.longitude), given_origin()
    return (
        watershed_name(origin.latitude, origin.longitude),
        delineated_origin(origin.latitude, origin.longitude, origin.changed),
    )


def _storm_shape(request: HydrographRequest) -> dict[str, float]:
    """Return the shape parameters of the request's hyetograph in Hydrolog's names.

    Parameters
    ----------
    request : HydrographRequest
        Request of a PMAXTP design storm.

    Returns
    -------
    dict[str, float]
        ``alpha`` and ``beta`` of the Beta hyetograph, ``peak_position`` of Euler II,
        nothing for the block.
    """
    if request.hietogram_type == "beta":
        return {"alpha": request.hietogram_alpha, "beta": request.hietogram_beta}
    if request.hietogram_type == "euler_ii":
        return {"peak_position": EULER_II_PEAK_POSITION}
    return {}


def _tc_origin(request: HydrographRequest, tc_method: str) -> dict[str, Any]:
    """Return the method of tc and the options of it the request gave.

    Parameters
    ----------
    request : HydrographRequest
        The request.
    tc_method : str
        The method that computed tc.

    Returns
    -------
    dict[str, Any]
        ``tc_method`` and the given ``tc_*`` options the method reads.
    """
    origin: dict[str, Any] = {"tc_method": tc_method}
    for option in _TC_OPTIONS.get(tc_method, ()):
        value = getattr(request, option)
        if value is not None:
            origin[option] = value
    return origin


def _handoff_runoff(
    request: HydrographRequest,
    tc_min: float | None,
    tc_method: str | None,
    uh_params: dict[str, Any],
    nash_meta: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return the runoff of the hand-off and the provenance of its derived parameters.

    Parameters
    ----------
    request : HydrographRequest
        The request.
    tc_min : float or None
        The time of concentration the computation used [min].
    tc_method : str or None
        The method that computed it.
    uh_params : dict[str, Any]
        The ``uh_params`` of the Nash or Snyder generator.
    nash_meta : dict[str, Any]
        What the Nash estimation reports (``_estimate_nash_params``).

    Returns
    -------
    tuple[dict[str, Any], dict[str, Any] | None]
        The runoff with the values the generator used: tc for SCS, n and K for Nash,
        L, Lc, Ct and Cp for Snyder. The provenance of ``runoff`` names the method of
        tc (SCS) or of n and K (Nash) with its parameters; Snyder derives nothing.
    """
    if request.uh_model == "nash":
        runoff = curve_number_runoff(
            "nash", request.amc, nash_n=uh_params["n"], nash_k_min=uh_params["k"]
        )
        origin: dict[str, Any] = {
            "source": PRODUCER,
            "nash_estimation": request.nash_estimation,
        }
        if request.nash_estimation == "from_lutz":
            origin["manning_n"] = LUTZ_MANNING_N
        elif request.nash_estimation == "from_urban_regression":
            for key in ("urban_fraction", "effective_precip_mm", "duration_h"):
                origin[key] = nash_meta[key]
        elif tc_method is not None:
            origin.update(_tc_origin(request, tc_method))
            origin["tc_min"] = tc_min
        return runoff, origin
    if request.uh_model == "snyder":
        runoff = curve_number_runoff(
            "snyder",
            request.amc,
            snyder_length_km=uh_params["L_km"],
            snyder_centroid_length_km=uh_params["Lc_km"],
            snyder_ct=uh_params["ct"],
            snyder_cp=uh_params["cp"],
        )
        return runoff, None
    if tc_method is None:
        raise ValueError("The SCS unit hydrograph needs the time of concentration")
    runoff = curve_number_runoff("scs", request.amc, tc_min=tc_min)
    return runoff, {"source": PRODUCER, **_tc_origin(request, tc_method)}


@router.post(
    "/generate-hydrograph",
    response_model=HydrographResponse,
    responses=problem_responses(404, 422, 503),
)
def generate_hydrograph(
    request: HydrographRequest,
    db: Session = Depends(get_db),
) -> HydrographResponse:
    """
    Generate direct runoff hydrograph for a given point.

    Uses SCS-CN method (CN adjusted for the requested AMC) with either a
    PMAXTP design storm distributed by a hietogram or a user-supplied
    rainfall series, and a configurable time of concentration method.
    Watershed delineation via CatchmentGraph (~87k nodes, ~5-50ms BFS).

    Parameters
    ----------
    request : HydrographRequest
        Request with coordinates, rainfall (duration + probability or
        custom_precipitation), AMC and options
    db : Session
        Database session (injected by FastAPI)

    Returns
    -------
    HydrographResponse
        Complete hydrograph with watershed info, precipitation, and results

    Raises
    ------
    NotFoundError
        ``not_found`` (404) when no catchment lies at the point
    NoDataError
        ``no_data`` (404) when there is no precipitation for the point
    InvalidRequestError
        ``validation_error`` (400) for invalid parameters
    UnsupportedError
        ``unsupported`` (422) when the catchment, delineated or given in
        ``morphometry``, is larger than 250 km2 or lacks the parameters of the chosen
        model
    StoreUnavailableError
        ``store_unavailable`` (503) when the catchment graph is not loaded
    InternalError
        ``internal_error`` (500) on an unexpected failure
    """
    try:
        custom = request.custom_precipitation
        if custom is not None:
            rain_desc = (
                f"custom series ({len(custom.depths_mm)} x {custom.timestep_min} min)"
            )
        else:
            rain_desc = f"duration={request.duration}, p={request.probability}%"
        logger.info(
            "Generating hydrograph for "
            f"({request.latitude:.6f}, {request.longitude:.6f}), "
            f"{rain_desc}, AMC {request.amc}"
        )

        # ===== STEP 1: Validate parameters =====
        if custom is None:
            duration_str, design_probability = _design_storm(request)
            probability: float | None = design_probability
            duration_min = float(DURATION_STR_TO_MIN[duration_str])
            timestep_min = request.timestep_min
        else:
            probability = None
            duration_min = len(custom.depths_mm) * custom.timestep_min
            timestep_min = custom.timestep_min
        amc = AMC_BY_CODE[request.amc]

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
            _require_area_within_limit(area_km2)
        else:
            # ===== Full path: compute watershed from scratch =====
            morph_dict, cn, area_km2, watershed_resp = _compute_watershed(
                point_2180, request, db
            )

        # ===== Precipitation: own series or PMAXTP design storm =====
        if custom is not None:
            precip_result = _custom_hietogram(custom.depths_mm, timestep_min)
            hietogram_type = None
            handoff_rainfall = rainfall_series(custom.depths_mm, timestep_min)
            rainfall_origin = given_origin()
            logger.debug(
                f"Custom precipitation: {precip_result.total_mm:.1f} mm "
                f"in {duration_min:.0f} min"
            )
        else:
            # PMAXTP depth at the click point (IDW)
            precip_mm = get_precipitation(
                point_2180, duration_str, design_probability, db
            )

            if precip_mm is None:
                raise NoDataError(
                    "no_precipitation_data",
                    reason="no_precipitation_data",
                    latitude=request.latitude,
                    longitude=request.longitude,
                )

            logger.debug(
                f"Precipitation: {precip_mm:.1f} mm for {duration_str}, "
                f"p={probability}%"
            )

            hietogram_type = request.hietogram_type
            hietogram: Hietogram
            if hietogram_type == "beta":
                hietogram = BetaHietogram(
                    alpha=request.hietogram_alpha,
                    beta=request.hietogram_beta,
                )
            else:
                hietogram_factory = HIETOGRAM_CLASSES.get(hietogram_type)
                if hietogram_factory is None:
                    raise InvalidRequestError(
                        "unknown_hietogram_type",
                        reason="unknown_hietogram_type",
                        value=hietogram_type,
                        allowed=["beta", *sorted(HIETOGRAM_CLASSES)],
                    )
                hietogram = hietogram_factory()
            precip_result = hietogram.generate(
                total_mm=precip_mm,
                duration_min=duration_min,
                timestep_min=timestep_min,
            )
            handoff_rainfall = design_storm(
                request.hietogram_type,
                precip_mm,
                duration_min,
                **_storm_shape(request),
            )
            rainfall_origin = pmaxtp_origin(
                design_probability, duration_min, request.latitude, request.longitude
            )
        precip_total_mm = float(precip_result.total_mm)

        # ===== Create Hydrolog objects =====
        watershed_params = WatershedParameters.from_dict(morph_dict)
        # Nash from_lutz / from_urban_regression don't need tc
        nash_needs_tc = (
            request.uh_model == "nash" and request.nash_estimation == "from_tc"
        )
        if request.uh_model != "nash" or nash_needs_tc:
            tc_method = request.tc_method
            tc_min = _calculate_tc(tc_method, watershed_params, morph_dict, request)
            logger.debug(f"Time of concentration: {tc_min:.1f} min ({tc_method})")
        else:
            tc_method = None
            tc_min = None

        # ===== Generate hydrograph =====
        nash_meta: dict[str, Any] = {}
        uh_params: dict[str, Any] = {}
        if request.uh_model == "snyder":
            channel_length = morph_dict.get("channel_length_km")
            length_to_centroid = morph_dict.get("length_to_centroid_km")
            if not channel_length or not length_to_centroid:
                raise UnsupportedError(
                    "snyder_parameters_missing",
                    reason="missing_morphometry",
                    method="snyder",
                )
            uh_params = {
                "L_km": channel_length,
                "Lc_km": length_to_centroid,
                "ct": request.snyder_ct or 1.5,
                "cp": request.snyder_cp or 0.6,
            }
            generator = HydrographGenerator(
                area_km2=area_km2,
                cn=cn,
                tc_min=tc_min,
                uh_model="snyder",
                uh_params=uh_params,
            )
        elif request.uh_model == "nash":
            # The urban regression needs the event's effective rainfall, so it
            # uses the same AMC-adjusted CN as the runoff calculation below.
            cn_effective = SCSCN(cn=cn).adjust_cn_for_amc(amc)
            uh_params, nash_meta = _estimate_nash_params(
                request,
                morph_dict,
                tc_min,
                precip_mm=precip_total_mm,
                cn=cn_effective,
                duration_min=duration_min,
                precip_result=precip_result,
                timestep_min=timestep_min,
            )
            generator = HydrographGenerator(
                area_km2=area_km2,
                cn=cn,
                uh_model="nash",
                uh_params=uh_params,
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
            timestep_min=timestep_min,
            amc=amc,
        )

        # ===== Hand-off to Hydrolog: the values used, unrounded (ADR-068) =====
        name, watershed_origin = _handoff_watershed(request, watershed_resp)
        runoff, runoff_origin = _handoff_runoff(
            request, tc_min, tc_method, uh_params, nash_meta
        )
        provenance = {"rainfall": rainfall_origin}
        if runoff_origin is not None:
            provenance["runoff"] = runoff_origin
        handoff = build_handoff(
            name=name,
            watershed=watershed_parameters(morph_dict, name, cn=cn),
            watershed_origin=watershed_origin,
            hydrograph=DesignHydrograph(
                timestep_min=timestep_min,
                runoff=runoff,
                rainfall=handoff_rainfall,
                provenance=provenance,
                result=hydrograph_result(
                    hydro_result.peak_discharge_m3s,
                    hydro_result.time_to_peak_min,
                    hydro_result.total_volume_m3,
                ),
            ),
        )

        # ===== Build response =====
        response = HydrographResponse(
            watershed=watershed_resp,
            precipitation=PrecipitationInfo(
                source="custom" if custom is not None else "pmaxtp",
                total_mm=round(precip_total_mm, 2),
                duration_min=duration_min,
                probability_percent=probability,
                timestep_min=timestep_min,
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
                cn_used=float(hydro_result.cn_used),
                retention_mm=round(hydro_result.retention_mm, 2),
                initial_abstraction_mm=round(hydro_result.initial_abstraction_mm, 2),
            ),
            metadata=HydrographMetadata(
                tc_min=round(tc_min, 1) if tc_min is not None else None,
                tc_method=tc_method,
                hietogram_type=hietogram_type,
                amc=request.amc,
                uh_model=request.uh_model,
                nash_estimation=nash_meta.get("estimation"),
                nash_n=nash_meta.get("n"),
                nash_k_min=nash_meta.get("k_min"),
                nash_urban_fraction=nash_meta.get("urban_fraction"),
                nash_effective_precip_mm=nash_meta.get("effective_precip_mm"),
                nash_duration_h=nash_meta.get("duration_h"),
            ),
            handoff=handoff,
        )

        logger.info(
            f"Hydrograph generated: Qmax={hydro_result.peak_discharge_m3s:.2f} m3/s, "
            f"tp={hydro_result.time_to_peak_min:.0f} min, "
            f"V={hydro_result.total_volume_m3:.0f} m3"
        )

        return response

    except HydrografError:
        raise
    except (ValueError, InvalidParameterError) as e:
        logger.error(f"Validation error in hydrograph generation: {e}")
        raise InvalidRequestError(
            "invalid_parameters", reason="invalid_parameters", cause=str(e)
        ) from e
    except Exception as e:
        logger.error(f"Error generating hydrograph: {e}", exc_info=True)
        raise InternalError("hydrograph_failed", reason="hydrograph_failed") from e


@router.get("/scenarios")
def list_scenarios() -> dict[str, Any]:
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
        "tc_methods": ["nrcs", "kirpich", "giandotti", "faa", "kerby", "kerby_kirpich"],
        "hietogram_types": ["beta", "block", "euler_ii"],
        "uh_models": ["scs", "nash", "snyder"],
        "snyder_defaults": {"ct": 1.5, "cp": 0.6},
        "nash_estimation_methods": ["from_lutz", "from_urban_regression", "from_tc"],
        "nash_defaults": {"n": 3.0},
        "amc": list(AMC_BY_CODE),
        "custom_precipitation_max_steps": CUSTOM_PRECIPITATION_MAX_STEPS,
        "area_limit_km2": HYDROGRAPH_AREA_LIMIT_KM2,
    }
