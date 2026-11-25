"""
Hydrograph generation endpoint.

Provides API endpoint for generating direct runoff hydrographs
using the Hydrolog library. Supports SCS, Snyder, and Nash unit hydrograph models.

Uses CatchmentGraph (~11k nodes, ~0.5 MB) for watershed delineation
via BFS on pre-computed sub-catchments.
"""

import logging
from collections.abc import Mapping
from dataclasses import asdict
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
from numba.core.compiler_lock import global_compiler_lock
from shapely.geometry import Point
from sqlalchemy.orm import Session

from api.endpoints.watershed import (
    _build_watershed_response,
    _loaded_catchment_graph,
    _select_precomputed,
)
from api.errors import problem_responses
from core import hydrolog_notices
from core.attribution import (
    CATCHMENT,
    NO_PROVIDER,
    PMAXTP,
    SERIES_ORIGINS,
    ProviderLines,
    instance_lines,
    merge,
    unknown_series_line,
)
from core.config import get_settings
from core.constants import DEFAULT_CN, DEFAULT_THRESHOLD_M2, HYDROGRAPH_AREA_LIMIT_KM2
from core.database import get_db
from core.errors import (
    CalculationError,
    HydrografError,
    InternalError,
    InvalidRequestError,
    NoDataError,
    UnsupportedError,
)
from core.formula_versions import (
    formula_versions,
    hydrograph_specs,
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
    hydrolog_version,
    pmaxtp_origin,
    rainfall_series,
    watershed_name,
    watershed_parameters,
)
from core.hydrolog_refusals import refusal
from core.precipitation import (
    DURATION_MIN_TO_STR,
    DURATION_STR_TO_MIN,
    VALID_DURATIONS_STR,
    VALID_PROBABILITIES,
    DesignDepth,
    ThiessenCell,
    UnknownGridPointError,
    areal_depth,
    point_depth,
    validate_duration,
    validate_probability,
)
from core.watershed_service import (
    boundary_to_polygon,
    merge_catchment_boundaries,
    watershed_lines,
)
from models.schemas import (
    CUSTOM_PRECIPITATION_MAX_STEPS,
    CustomPrecipitation,
    HydrographInfo,
    HydrographMetadata,
    HydrographRequest,
    HydrographResponse,
    MorphometricParameters,
    PmaxtpPoint,
    PrecipitationInfo,
    WaterBalance,
    WatershedResponse,
)
from utils.geometry import (
    transform_pl1992_to_wgs84,
    transform_wgs84_to_pl1992,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Manning's n of the channel in Lutz's estimation of Nash's n and K
LUTZ_MANNING_N = 0.035

# The shortest duration of the PMAXTP depth-duration curve, where Euler II's curve
# starts: its time step is at least this long (Hydrolog ADR-0042, `not_covered`)
EULER_II_SHORTEST_MIN = float(min(DURATION_MIN_TO_STR))

# A duration is a whole number of steps to this fraction of it, as Hydrolog counts
# the steps of a hyetograph (ADR-0046)
WHOLE_STEPS_TOLERANCE = 1e-9

# The coefficients of the tc methods that only the request gives, Hydrolog's field ->
# the request's option: FAA's C and Kerby's N are inputs, never derived (Nogat plan
# 2026-11-05-official-tc-inputs, D4)
_TC_COEFFICIENTS: dict[str, dict[str, str]] = {
    "faa": {"runoff_coeff": "tc_runoff_coeff"},
    "kerby": {"retardance": "tc_retardance"},
    "kerby_kirpich": {"retardance": "tc_retardance"},
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


def _series_lines(custom: CustomPrecipitation) -> ProviderLines:
    """Return the lines of the products made with an own rainfall series.

    Parameters
    ----------
    custom : CustomPrecipitation
        The series of the request.

    Returns
    -------
    ProviderLines
        Those of the data ``derived_from`` names (ADR-083, amended 2026-11-25), from
        ``core.attribution``; none for the user's own data.

    Raises
    ------
    InvalidRequestError
        ``validation_error`` (400, reason ``unknown_attribution_line``) for a line the
        series brings from its file that is not one of those data's, or that comes
        without ``derived_from``.
    """
    origin = custom.derived_from
    line = unknown_series_line(origin, custom.attribution, custom.terms_notice)
    if line is not None and origin is None:
        raise InvalidRequestError(
            "attribution_line_without_origin",
            reason="unknown_attribution_line",
            line=line,
        )
    if line is not None and origin is not None:
        raise InvalidRequestError(
            "unknown_attribution_line",
            reason="unknown_attribution_line",
            line=line,
            derived_from=origin,
            provider=SERIES_ORIGINS[origin][0],
        )
    return NO_PROVIDER if origin is None else SERIES_ORIGINS[origin][1]


def _compute_watershed(
    point_2180: Point, db: Session
) -> tuple[WatershedResponse, MorphometricParameters, float, ProviderLines]:
    """Delineate the watershed of the point as ``POST /api/delineate-watershed`` does.

    The precomputed delineation at the finest threshold: its sub-catchments
    (``_select_precomputed``), merged from a coarser threshold above 300 of them, which
    the merge of thousands of 1 ha sub-catchments needed minutes for (E5b-04); a
    catchment above the SCS-CN limit is refused before anything is merged. The
    morphometry with the CN of the land cover, the PMAXTP cells of the design depth
    (ADR-069) and the lines of the data are those of the watershed, as
    ``scripts/analyze_watershed.py`` takes them.

    Parameters
    ----------
    point_2180 : Point
        The point of the request in EPSG:2180.
    db : Session
        Database session.

    Returns
    -------
    tuple[WatershedResponse, MorphometricParameters, float, ProviderLines]
        The watershed (``_build_watershed_response``, without the hypsometric curve),
        its morphometry, its area from the catchment graph unrounded [km2], which the
        morphometry carries to 0.0001 km2, and the lines of its data
        (``watershed_lines``).

    Raises
    ------
    StoreUnavailableError
        ``store_unavailable`` (503) when the catchment graph is not loaded.
    NotFoundError
        ``not_found`` (404) when no sub-catchment lies at the point.
    UnsupportedError
        ``unsupported`` (422) above the SCS-CN limit.
    CalculationError
        ``calculation_error`` when the boundary cannot be merged.
    """
    cg = _loaded_catchment_graph(db)
    selection = _select_precomputed(DEFAULT_THRESHOLD_M2, point_2180, cg, db)
    _require_area_within_limit(selection.area_km2)

    boundary_2180 = merge_catchment_boundaries(
        selection.merge_idxs, selection.merge_threshold, db
    )
    if boundary_2180 is None:
        raise CalculationError("boundary_build_failed", reason="boundary_build_failed")
    watershed = _build_watershed_response(
        cg,
        point_2180,
        boundary_2180,
        boundary_to_polygon(boundary_2180),
        selection.upstream_indices,
        selection.outlet_idx,
        selection.merge_threshold,
        selection.area_km2,
        selection.stats,
        False,
        db,
    )
    # _build_watershed_response measures the morphometry of every watershed
    assert watershed.morphometry is not None
    logger.info(
        "Full path: %.2f km2, %d sub-catchments merged at %d m2, CN %s",
        selection.area_km2,
        len(selection.merge_idxs),
        selection.merge_threshold,
        watershed.morphometry.cn,
    )
    lines = watershed_lines(watershed, get_settings().frontend_data_dir)
    return watershed, watershed.morphometry, selection.area_km2, lines


def _design_depth(
    request: HydrographRequest,
    point_2180: Point,
    cells: list[ThiessenCell] | None,
    duration_str: str,
    probability: float,
    db: Session,
) -> DesignDepth:
    """PMAXTP depth of the design storm (ADR-069).

    The watershed mean over the Thiessen polygons ``cells``; without them (own
    morphometry without ``pmaxtp_grid``) the inverse distance weighting at the point.

    Raises
    ------
    InvalidRequestError
        ``validation_error`` (400) when a cell of the request's ``pmaxtp_grid`` is
        not a grid point
    NoDataError
        ``no_data`` (404) when the grid has no data there
    """
    no_data = NoDataError(
        "no_precipitation_data",
        reason="no_precipitation_data",
        latitude=request.latitude,
        longitude=request.longitude,
    )
    try:
        depth = (
            point_depth(point_2180, duration_str, probability, db)
            if cells is None
            else areal_depth(cells, duration_str, probability, db)
        )
    except UnknownGridPointError as e:
        if request.morphometry is None:
            # The cells came from the table: the scenario has no data there
            raise no_data from e
        raise InvalidRequestError(
            "pmaxtp_grid_point_unknown",
            reason="pmaxtp_grid_point_unknown",
            easting_m=round(e.easting_m, 2),
            northing_m=round(e.northing_m, 2),
        ) from e
    if depth is None:
        raise no_data
    return depth


def _depth_duration_mm(
    request: HydrographRequest,
    point_2180: Point,
    cells: list[ThiessenCell] | None,
    probability: float,
    factor: float,
    db: Session,
) -> dict[str, float]:
    """PMAXTP depth-duration curve of the probability, for Euler II (ADR-069).

    The depth of every PMAXTP duration at the probability, each weighed as the
    design depth (``_design_depth``: the Thiessen mean over the watershed, or the
    IDW at the point), times the user's areal reduction factor: the storm holds the
    depth of its duration (Hydrolog ADR-0042), so a reduced total needs the curve
    reduced alike.

    Parameters
    ----------
    request : HydrographRequest
        The request.
    point_2180 : Point
        The point of the request in EPSG:2180.
    cells : list[ThiessenCell] or None
        The Thiessen cells of the watershed, None for the IDW at the point.
    probability : float
        Exceedance probability [%].
    factor : float
        The areal reduction factor, 1 without one.
    db : Session
        Database session.

    Returns
    -------
    dict[str, float]
        The depth [mm] by duration [min] written as text, from 5 min to 72 h, as
        Hydrolog's ``precip pmaxtp`` gives the curve.
    """
    return {
        str(minutes): _design_depth(
            request, point_2180, cells, key, probability, db
        ).precipitation_mm
        * factor
        for minutes, key in DURATION_MIN_TO_STR.items()
    }


def _pmaxtp_points(depth: DesignDepth) -> list[PmaxtpPoint]:
    """Return the grid points of a design depth with their WGS84 coordinates."""
    points = []
    for point in depth.points:
        lon, lat = transform_pl1992_to_wgs84(point.easting_m, point.northing_m)
        points.append(PmaxtpPoint(latitude=lat, longitude=lon, **asdict(point)))
    return points


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


def _tc_coefficients(request: HydrographRequest, method: str) -> dict[str, float]:
    """Return the coefficients of a tc method the request gives, in Hydrolog's names.

    Parameters
    ----------
    request : HydrographRequest
        The request.
    method : str
        The method of tc.

    Returns
    -------
    dict[str, float]
        ``runoff_coeff`` (``tc_runoff_coeff``) for FAA, ``retardance``
        (``tc_retardance``) for Kerby and Kerby-Kirpich, when given; nothing for the
        other methods, which do not use them.
    """
    coefficients: dict[str, float] = {}
    for field, option in _TC_COEFFICIENTS.get(method, {}).items():
        value = getattr(request, option)
        if value is not None:
            coefficients[field] = value
    return coefficients


def _calculate_tc(
    method: str,
    morph_dict: dict[str, Any],
    cn: float,
    request: HydrographRequest,
) -> float:
    """Compute the time of concentration with Hydrolog from the method's own inputs.

    Hydrolog's ``WatershedParameters.calculate_tc`` takes for each method the
    watershed fields its source defines, with no substitute (Nogat plan
    2026-11-05-official-tc-inputs): Kirpich the longest flow path and its slope, NRCS
    the flow path, the mean slope and CN, Giandotti the main channel and the
    elevations, FAA and Kerby the overland segment with C or N, Kerby-Kirpich the
    overland segment, N and the flow path.

    Parameters
    ----------
    method : str
        The method of tc (``tc_method``).
    morph_dict : dict[str, Any]
        The morphometry of the computation.
    cn : float
        The CN the computation uses (the default CN of a watershed without land
        cover).
    request : HydrographRequest
        The request, with FAA's C and Kerby's N.

    Returns
    -------
    float
        The time of concentration [min].

    Raises
    ------
    InvalidRequestError
        ``tc_inputs_missing`` (400, reason ``missing_field``) when the method lacks
        an input; ``details.missing`` names the request option (``tc_runoff_coeff``,
        ``tc_retardance``) or the morphometry field of each.
    """
    fields = {**morph_dict, "cn": cn, **_tc_coefficients(request, method)}
    try:
        return float(WatershedParameters.from_dict(fields).calculate_tc(method))
    except InvalidParameterError as e:
        if e.details.get("reason") != "missing_field":
            raise
        options = _TC_COEFFICIENTS.get(method, {})
        raise InvalidRequestError(
            "tc_inputs_missing",
            reason="missing_field",
            method=method,
            missing=[options.get(name, name) for name in e.details["missing"]],
        ) from e


def _lutz_inputs(morph_dict: dict[str, Any]) -> dict[str, float]:
    """Return the inputs of Lutz's estimation besides the flow path and Lc.

    Parameters
    ----------
    morph_dict : dict[str, Any]
        The morphometry of the computation.

    Returns
    -------
    dict[str, float]
        ``manning_n`` (``LUTZ_MANNING_N``) and the shares of urbanised land and of
        forest of the land cover [%], 0 for a watershed without land cover (Hydrolog's
        default): the arguments of ``NashIUH.from_lutz`` and the fields of Hydrolog's
        ``WatershedParameters``.
    """
    return {
        "manning_n": LUTZ_MANNING_N,
        "urban_pct": morph_dict.get("urban_pct") or 0.0,
        "forest_pct": morph_dict.get("forest_pct") or 0.0,
    }


def _estimate_nash_params(
    request: HydrographRequest,
    morph_dict: dict[str, Any],
    precip_mm: float | None = None,
    cn: float | None = None,
    duration_min: float | None = None,
    precip_result: Any = None,
    timestep_min: float = 5.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Estimate Nash IUH parameters (n, k) using the requested method.

    Lutz's L is the longest flow path (``flow_path_length_km``) and Jg the
    equal-area slope of its profile (``flow_path_equal_area_slope_m_per_m``),
    Hydrolog ADR-0053; Lc runs along the main channel (``length_to_centroid_km``).

    Returns (uh_params, nash_meta) where nash_meta has extra info for response.
    """
    nash_meta: dict[str, Any] = {"estimation": request.nash_estimation}

    if request.nash_estimation == "from_lutz":
        flow_path_length = morph_dict.get("flow_path_length_km")
        length_to_centroid = morph_dict.get("length_to_centroid_km")
        equal_area_slope = morph_dict.get("flow_path_equal_area_slope_m_per_m")
        if not flow_path_length or not length_to_centroid or not equal_area_slope:
            raise UnsupportedError(
                "lutz_parameters_missing",
                reason="missing_morphometry",
                method="from_lutz",
            )
        lutz = _lutz_inputs(morph_dict)
        nash = NashIUH.from_lutz(
            L_km=flow_path_length,
            Lc_km=length_to_centroid,
            slope=equal_area_slope,
            manning_n=lutz["manning_n"],
            urban_pct=lutz["urban_pct"],
            forest_pct=lutz["forest_pct"],
            area_km2=morph_dict["area_km2"],
        )
        nash_meta["forest_pct"] = lutz["forest_pct"]
        nash_meta["urban_pct"] = lutz["urban_pct"]
        logger.info(
            "Nash (Lutz): N=%.2f, K=%.1f min, W=%.1f%%, U=%.1f%%",
            nash.n,
            nash.k_min,
            lutz["forest_pct"],
            lutz["urban_pct"],
        )
    else:  # from_urban_regression
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

    nash_meta["n"] = round(nash.n, 3)
    nash_meta["k_min"] = round(nash.k_min, 2)

    return {"n": nash.n, "k": nash.k_min, "k_unit": "min"}, nash_meta


# The design hyetographs of a PMAXTP storm (`allowed` of unknown_hietogram_type)
HIETOGRAM_TYPES = ("beta", "block", "euler_ii")

# Request AMC code -> Hydrolog enum
AMC_BY_CODE = {"I": AMC.I, "II": AMC.II, "III": AMC.III}


def _hietogram(
    request: HydrographRequest, depth_duration_mm: Mapping[str, float] | None
) -> Hietogram:
    """Return Hydrolog's design hyetograph of the request.

    Parameters
    ----------
    request : HydrographRequest
        Request of a PMAXTP design storm.
    depth_duration_mm : Mapping[str, float] or None
        The PMAXTP depth-duration curve of Euler II (``_depth_duration_mm``).

    Returns
    -------
    Hietogram
        Beta of the request's α and β, the block, or Euler II of the curve.

    Raises
    ------
    InvalidRequestError
        ``unknown_hietogram_type`` (400) for another type (the request's pattern
        admits none).
    """
    if request.hietogram_type == "beta":
        return BetaHietogram(alpha=request.hietogram_alpha, beta=request.hietogram_beta)
    if request.hietogram_type == "block":
        return BlockHietogram()
    if request.hietogram_type == "euler_ii" and depth_duration_mm is not None:
        return EulerIIHietogram(depth_duration_mm)
    raise InvalidRequestError(
        "unknown_hietogram_type",
        reason="unknown_hietogram_type",
        value=request.hietogram_type,
        allowed=list(HIETOGRAM_TYPES),
    )


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

    The storm is made of whole time steps (Hydrolog ADR-0046): its duration is a
    whole number of steps of ``timestep_min``, and Euler II, built from the PMAXTP
    depth-duration curve, has a step no shorter than the curve's first duration
    (Hydrolog ADR-0042). Both are refused here, before the watershed is delineated.

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
        (``HydrographRequest`` rejects such a request already), with reason
        ``not_multiple`` (``storm_not_whole_steps``) when the duration is not a whole
        number of steps, and with reason ``not_covered``
        (``euler_ii_step_below_curve``) when the step of Euler II is shorter than
        the curve's first duration.
    ValueError
        When the duration or the probability is not one of PMAXTP's values.
    """
    if request.duration is None or request.probability is None:
        raise InvalidRequestError(
            "invalid_parameters",
            reason="invalid_parameters",
            cause="duration and probability are required without custom_precipitation",
        )
    duration_str = validate_duration(request.duration)
    probability = validate_probability(request.probability)
    duration_min = float(DURATION_STR_TO_MIN[duration_str])
    step = request.timestep_min
    steps = max(round(duration_min / step), 1)
    if abs(steps * step - duration_min) > WHOLE_STEPS_TOLERANCE * duration_min:
        raise InvalidRequestError(
            "storm_not_whole_steps",
            reason="not_multiple",
            duration_min=duration_min,
            timestep_min=step,
        )
    if request.hietogram_type == "euler_ii" and step < EULER_II_SHORTEST_MIN:
        raise InvalidRequestError(
            "euler_ii_step_below_curve",
            reason="not_covered",
            shortest_min=EULER_II_SHORTEST_MIN,
            timestep_min=step,
        )
    return duration_str, probability


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


def _watershed_data_lines(
    request: HydrographRequest, delineated: ProviderLines | None
) -> ProviderLines:
    """Return the lines of the GUGiK and SoilGrids data of the hydrograph's watershed.

    Parameters
    ----------
    request : HydrographRequest
        The request.
    delineated : ProviderLines or None
        The lines of the watershed the endpoint delineated (``_compute_watershed``),
        None for a given morphometry.

    Returns
    -------
    ProviderLines
        Those of the watershed the endpoint delineated; for a given morphometry with
        its ``morphometry_origin``, a delineation of Hydrograf, those of a catchment
        (its morphometry and CN); none for the user's own watershed.
    """
    if delineated is not None:
        return delineated
    if request.morphometry_origin is not None:
        return instance_lines(CATCHMENT, get_settings().frontend_data_dir)
    return NO_PROVIDER


def _storm_shape(request: HydrographRequest) -> dict[str, float]:
    """Return the shape parameters of the request's hyetograph in Hydrolog's names.

    Parameters
    ----------
    request : HydrographRequest
        Request of a PMAXTP design storm.

    Returns
    -------
    dict[str, float]
        ``alpha`` and ``beta`` of the Beta hyetograph; nothing for the block and for
        Euler II, whose shape is its depth-duration curve.
    """
    if request.hietogram_type == "beta":
        return {"alpha": request.hietogram_alpha, "beta": request.hietogram_beta}
    return {}


def _tc_origin(request: HydrographRequest, tc_method: str) -> dict[str, Any]:
    """Return the method of tc and the coefficients of it the request gave.

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
    for option in _TC_COEFFICIENTS.get(tc_method, {}).values():
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
        The runoff with the values the generator used: the method of tc for SCS
        (``tc_method``, so that Hydrolog computes tc from the watershed again), n and
        K for Nash, L, Lc, Ct and Cp for Snyder. The provenance of ``runoff`` names
        the method of tc with Hydrograf's tc (``tc_min``, for the comparison) and its
        coefficients (SCS), or the method of n and K (Nash) with its parameters; for
        Lutz it is Hydrolog's own record (``method`` ``lutz``), whose inputs the
        watershed carries (``_lutz_inputs``), so that Hydrolog estimates n and K
        again. Snyder derives nothing.
    """
    if request.uh_model == "nash":
        runoff = curve_number_runoff(
            "nash", request.amc, nash_n=uh_params["n"], nash_k_min=uh_params["k"]
        )
        if request.nash_estimation == "from_lutz":
            return runoff, {"source": PRODUCER, "method": "lutz"}
        origin: dict[str, Any] = {
            "source": PRODUCER,
            "nash_estimation": request.nash_estimation,
        }
        for key in ("urban_fraction", "effective_precip_mm", "duration_h"):
            origin[key] = nash_meta[key]
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
    if tc_method is None or tc_min is None:
        raise ValueError("The SCS unit hydrograph needs the time of concentration")
    runoff = curve_number_runoff("scs", request.amc, tc_method=tc_method)
    return runoff, {
        "source": PRODUCER,
        **_tc_origin(request, tc_method),
        "tc_min": float(tc_min),
    }


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
        Complete hydrograph with watershed info, precipitation, and results;
        Hydrolog's warnings about the computation as Polish ``notices``

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
            rain_lines = PMAXTP
        else:
            probability = None
            duration_min = len(custom.depths_mm) * custom.timestep_min
            timestep_min = custom.timestep_min
            # The lines of the data the series came from, its file's checked first
            rain_lines = _series_lines(custom)
        amc = AMC_BY_CODE[request.amc]

        # ===== STEP 2: Transform coordinates =====
        point_2180 = transform_wgs84_to_pl1992(request.latitude, request.longitude)

        # ===== The watershed: the request's morphometry (fast path) or delineated =====
        watershed_resp = None
        delineated_lines: ProviderLines | None = None
        if request.morphometry is not None:
            morphometry = request.morphometry
            area_km2 = morphometry.area_km2
            logger.info(
                f"Fast path: using pre-computed morphometry "
                f"(area={area_km2:.2f} km2, CN={morphometry.cn})"
            )
            _require_area_within_limit(area_km2)
            pmaxtp_grid = request.pmaxtp_grid
        else:
            # Full path: the morphometry, CN and PMAXTP grid of the delineation, as
            # the interface sends them on the fast path
            watershed_resp, morphometry, area_km2, delineated_lines = (
                _compute_watershed(point_2180, db)
            )
            pmaxtp_grid = watershed_resp.pmaxtp_grid
        morph_dict = morphometry.model_dump(exclude_none=True)
        cn = morph_dict.get("cn") or DEFAULT_CN
        pmaxtp_cells = (
            None
            if pmaxtp_grid is None
            else [
                ThiessenCell(cell.easting_m, cell.northing_m, cell.area_km2)
                for cell in pmaxtp_grid
            ]
        )

        # ===== Precipitation: own series or PMAXTP design storm =====
        depth: DesignDepth | None = None
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
            # PMAXTP depth: the watershed mean, or at the point without the grid
            depth = _design_depth(
                request, point_2180, pmaxtp_cells, duration_str, design_probability, db
            )
            # The user's own areal reduction factor; none by default (ADR-069)
            arf = request.areal_reduction_factor
            factor = 1.0 if arf is None else arf
            precip_mm = depth.precipitation_mm * factor
            logger.debug(
                f"Precipitation: {precip_mm:.1f} mm for {duration_str}, "
                f"p={probability}% ({depth.interpolation}, "
                f"{len(depth.points)} grid points, ARF {arf})"
            )

            hietogram_type = request.hietogram_type
            # Euler II is built from the PMAXTP depth-duration curve of the
            # probability (Hydrolog ADR-0042), weighed as the design depth
            curve = (
                _depth_duration_mm(
                    request, point_2180, pmaxtp_cells, design_probability, factor, db
                )
                if hietogram_type == "euler_ii"
                else None
            )
            precip_result = _hietogram(request, curve).generate(
                total_mm=precip_mm,
                duration_min=duration_min,
                timestep_min=timestep_min,
            )
            handoff_rainfall = design_storm(
                request.hietogram_type,
                precip_mm,
                duration_min,
                depth_duration_mm=curve,
                **_storm_shape(request),
            )
            rainfall_origin = pmaxtp_origin(
                design_probability,
                duration_min,
                request.latitude,
                request.longitude,
                depth.interpolation,
                arf,
            )
        precip_total_mm = float(precip_result.total_mm)

        # ===== Time of concentration (Hydrolog, from the method's own inputs) =====
        # Hydrolog's warnings of the time of concentration and of the hydrograph are
        # the notices of the response (E5b-06): the process's warnings hook collects
        # those this request's context issues
        with hydrolog_notices.collect() as caught:
            # The area the generator used: the full path takes it from the catchment
            # graph unrounded, while the morphometry carries it to 0.01 km2
            watershed_fields = {**morph_dict, "area_km2": area_km2}
            # Nash (Lutz, urban regression) does not use tc
            if request.uh_model != "nash":
                tc_method = request.tc_method
                # Hydrolog's computations, which warn (OutsideTypicalRange), hold
                # numba's compiler lock (E5b-08): a numba compile in another thread
                # swaps the warning filters and handlers of the whole process while it
                # holds the lock, takes the warnings of other threads for its own and
                # emits them again from their text, from which no HydrologWarning can
                # be made, so the compiling request failed with a TypeError; under the
                # lock the warnings also reach the hook that collects them
                with global_compiler_lock:
                    tc_min = _calculate_tc(tc_method, watershed_fields, cn, request)
                if request.uh_model == "snyder":
                    # Snyder takes its lag from L and Lc, not from this tc: the
                    # warnings of the tc are no notices of its hydrograph
                    caught.clear()
                logger.debug(f"Time of concentration: {tc_min:.1f} min ({tc_method})")
                # FAA's C or Kerby's N, which the hand-off's watershed carries
                watershed_fields = {
                    **watershed_fields,
                    **_tc_coefficients(request, tc_method),
                }
            else:
                tc_method = None
                tc_min = None

            # ===== Generate hydrograph =====
            nash_meta: dict[str, Any] = {}
            uh_params: dict[str, Any] = {}
            # Under numba's compiler lock, as the time of concentration: the Nash
            # estimation, the unit hydrographs and the generation warn
            with global_compiler_lock:
                if request.uh_model == "snyder":
                    # Snyder's L runs to the divide: the longest flow path, not the
                    # main channel (Hydrolog ADR-0043)
                    flow_path_length = morph_dict.get("flow_path_length_km")
                    length_to_centroid = morph_dict.get("length_to_centroid_km")
                    if not flow_path_length or not length_to_centroid:
                        raise UnsupportedError(
                            "snyder_parameters_missing",
                            reason="missing_morphometry",
                            method="snyder",
                        )
                    uh_params = {
                        "L_km": flow_path_length,
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

        # ===== The versions of Hydrolog's formulas of the result (CMP-2.8) =====
        versions = formula_versions(
            hydrograph_specs(
                hietogram_type=hietogram_type,
                interpolation_method=None if depth is None else depth.interpolation,
                tc_method=tc_method if request.uh_model == "scs" else None,
                uh_model=request.uh_model,
                nash_estimation=nash_meta.get("estimation"),
                amc=request.amc,
            )
        )
        if watershed_resp is not None:
            versions = dict(
                sorted({**versions, **watershed_resp.formula_versions}.items())
            )

        # ===== Hand-off to Hydrolog: the values used, unrounded (ADR-068) =====
        name, watershed_origin = _handoff_watershed(request, watershed_resp)
        # The rainfall's lines, then those of a watershed of Hydrograf's data
        lines = merge([rain_lines, _watershed_data_lines(request, delineated_lines)])
        runoff, runoff_origin = _handoff_runoff(
            request, tc_min, tc_method, uh_params, nash_meta
        )
        provenance = {"rainfall": rainfall_origin}
        if runoff_origin is not None:
            provenance["runoff"] = runoff_origin
        if request.uh_model == "nash" and request.nash_estimation == "from_lutz":
            # Lutz's inputs, where Hydrolog's GUI reads them to estimate n and K again
            watershed_fields = {**watershed_fields, **_lutz_inputs(watershed_fields)}
        handoff = build_handoff(
            name=name,
            watershed=watershed_parameters(watershed_fields, name, cn=cn),
            watershed_origin=watershed_origin,
            lines=lines,
            hydrograph=DesignHydrograph(
                timestep_min=timestep_min,
                runoff=runoff,
                rainfall=handoff_rainfall,
                provenance=provenance,
                result=hydrograph_result(
                    hydro_result.peak_discharge_m3s,
                    hydro_result.time_to_peak_min,
                    hydro_result.total_volume_m3,
                    versions,
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
                pmaxtp_depth_mm=(
                    None if depth is None else round(depth.precipitation_mm, 2)
                ),
                areal_reduction_factor=(
                    None if custom is not None else request.areal_reduction_factor
                ),
                interpolation=None if depth is None else depth.interpolation,
                pmaxtp_points=[] if depth is None else _pmaxtp_points(depth),
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
                nash_forest_pct=nash_meta.get("forest_pct"),
                nash_urban_pct=nash_meta.get("urban_pct"),
                nash_urban_fraction=nash_meta.get("urban_fraction"),
                nash_effective_precip_mm=nash_meta.get("effective_precip_mm"),
                nash_duration_h=nash_meta.get("duration_h"),
            ),
            handoff=handoff,
            attribution=list(lines.attribution),
            terms_notice=list(lines.terms_notice),
            notices=hydrolog_notices.notices(caught),
            hydrolog_version=hydrolog_version(),
            formula_versions=versions,
        )

        logger.info(
            f"Hydrograph generated: Qmax={hydro_result.peak_discharge_m3s:.2f} m3/s, "
            f"tp={hydro_result.time_to_peak_min:.0f} min, "
            f"V={hydro_result.total_volume_m3:.0f} m3"
        )

        return response

    except HydrografError:
        raise
    except InvalidParameterError as e:
        logger.error(f"Hydrolog refused the hydrograph's inputs: {e}")
        raise refusal(e) from e
    except ValueError as e:
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
        "nash_estimation_methods": ["from_lutz", "from_urban_regression"],
        "amc": list(AMC_BY_CODE),
        "custom_precipitation_max_steps": CUSTOM_PRECIPITATION_MAX_STEPS,
        "area_limit_km2": HYDROGRAPH_AREA_LIMIT_KM2,
    }
