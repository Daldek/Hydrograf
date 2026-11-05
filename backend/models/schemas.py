"""
Pydantic models for API request/response schemas.

Defines data structures for watershed delineation and hydrograph
generation API endpoints.
"""

import json
import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DelineateRequest(BaseModel):
    """Request for watershed delineation.

    When threshold_m2 is provided, uses pre-computed catchments (fast).
    When omitted, performs precise on-the-fly delineation.
    """

    latitude: float = Field(
        ...,
        ge=-90,
        le=90,
        description="Latitude in WGS84 (decimal degrees)",
        examples=[52.23],
    )
    longitude: float = Field(
        ...,
        ge=-180,
        le=180,
        description="Longitude in WGS84 (decimal degrees)",
        examples=[21.01],
    )
    threshold_m2: int | None = Field(
        None,
        gt=0,
        description=(
            "Flow accumulation threshold [m2]. If provided, uses pre-computed "
            "catchments (fast). If omitted, performs precise on-the-fly delineation."
        ),
        examples=[10000],
    )


class OutletInfo(BaseModel):
    """
    Information about watershed outlet point.

    Attributes
    ----------
    latitude : float
        Outlet latitude in WGS84
    longitude : float
        Outlet longitude in WGS84
    elevation_m : float
        Outlet elevation in meters above sea level
    """

    latitude: float = Field(..., description="Outlet latitude in WGS84")
    longitude: float = Field(..., description="Outlet longitude in WGS84")
    elevation_m: float = Field(..., description="Outlet elevation [m n.p.m.]")


class MorphometricParameters(BaseModel):
    """
    Morphometric parameters compatible with Hydrolog's WatershedParameters.

    This schema matches the Hydrolog library's WatershedParameters dataclass,
    enabling seamless integration between Hydrograf (GIS) and Hydrolog (hydrology).

    Attributes
    ----------
    area_km2 : float
        Watershed area [km2]
    perimeter_km : float
        Watershed perimeter [km]
    length_km : float
        Watershed length (max distance from outlet) [km]
    elevation_min_m : float
        Minimum elevation at outlet [m a.s.l.]
    elevation_max_m : float
        Maximum elevation in watershed [m a.s.l.]
    elevation_mean_m : float, optional
        Area-weighted mean elevation [m a.s.l.]
    mean_slope_m_per_m : float, optional
        Area-weighted mean slope [m/m]
    channel_length_km : float, optional
        Main channel length along the DEM stream network, from the outlet to the
        channel head at the accumulation threshold [km]
    channel_slope_m_per_m : float, optional
        Main channel slope from its source (the channel head) to the outlet [m/m]
    real_channel_length_km : float, optional
        Length of the main channel along BDOT10k streams, from the outlet [km]
    flow_path_length_km : float, optional
        Longest flow path from the hydraulically most distant point of the
        watershed (usually on the divide, possibly on an internal ridge) to the
        outlet [km]
    flow_path_slope_m_per_m : float, optional
        (Elevation of its head − outlet elevation) / its length [m/m]
    overland_length_km, overland_slope_m_per_m : float, optional
        Length [km] and slope [m/m] of the overland segment of the longest flow
        path, from its head to the DEM stream network of the delineation threshold
    cn : float, optional
        SCS Curve Number (0-100); area-weighted values carry one decimal
    forest_pct, urban_pct : float, optional
        Shares of forest and of urbanised land [%] in the land cover, Lutz's W and U
    source : str, optional
        Data source identifier
    crs : str, optional
        Coordinate reference system
    """

    area_km2: float = Field(..., ge=0, description="Watershed area [km2]")
    perimeter_km: float = Field(..., ge=0, description="Watershed perimeter [km]")
    length_km: float = Field(..., ge=0, description="Watershed length [km]")
    elevation_min_m: float = Field(..., description="Minimum elevation [m a.s.l.]")
    elevation_max_m: float = Field(..., description="Maximum elevation [m a.s.l.]")
    elevation_mean_m: float | None = Field(
        None, description="Area-weighted mean elevation [m a.s.l.]"
    )
    mean_slope_m_per_m: float | None = Field(
        None, ge=0, description="Area-weighted mean slope [m/m]"
    )
    channel_length_km: float | None = Field(
        None,
        ge=0,
        description=(
            "Main channel length along the DEM stream network, from the outlet to "
            "the channel head at the accumulation threshold [km]"
        ),
    )
    channel_slope_m_per_m: float | None = Field(
        None,
        ge=0,
        description=(
            "Main channel slope: (elevation of its source, the channel head, - "
            "outlet elevation) / channel_length_km [m/m]"
        ),
    )
    real_channel_length_km: float | None = Field(
        None,
        ge=0,
        description=(
            "Length of the main channel along BDOT10k streams, counted from the "
            "outlet upstream [km]"
        ),
    )
    cn: float | None = Field(None, ge=0, le=100, description="SCS Curve Number")
    imperviousness: float | None = Field(
        None, ge=0, le=1, description="Weighted imperviousness fraction [0-1]"
    )
    forest_pct: float | None = Field(
        None, ge=0, le=100, description="Share of forest [%] (Lutz's W)"
    )
    urban_pct: float | None = Field(
        None,
        ge=0,
        le=100,
        description="Share of urbanised (built-up and transport) land [%] (Lutz's U)",
    )
    source: str | None = Field("Hydrograf", description="Data source")
    crs: str | None = Field("EPSG:2180", description="Coordinate reference system")

    # Shape indices
    compactness_coefficient: float | None = Field(
        None, description="Gravelius compactness coefficient Kc"
    )
    circularity_ratio: float | None = Field(
        None, description="Miller circularity ratio Rc"
    )
    elongation_ratio: float | None = Field(
        None, description="Schumm elongation ratio Re"
    )
    form_factor: float | None = Field(None, description="Horton form factor Ff")
    lemniscate_ratio: float | None = Field(
        None, description="Chorley lemniscate ratio Cl = 0.5*L/A"
    )
    mean_width_km: float | None = Field(None, ge=0, description="Mean width A/L [km]")

    # Relief indices
    relief_ratio: float | None = Field(None, description="Relief ratio R = ΔH/√A [‰]")
    divide_slope: float | None = Field(None, description="Divide slope Rp = ΔH/P [‰]")
    asymmetry_coefficient: float | None = Field(
        None, description="Asymmetry coefficient α = 2*(AL-AP)/A"
    )
    hypsometric_integral: float | None = Field(
        None, ge=0, le=1, description="Hypsometric integral HI"
    )

    # Drainage network indices
    drainage_density_km_per_km2: float | None = Field(
        None, ge=0, description="Drainage density Dd [km/km2]"
    )
    stream_frequency_per_km2: float | None = Field(
        None, ge=0, description="Stream frequency Fs [1/km2]"
    )
    ruggedness_number: float | None = Field(
        None, ge=0, description="Ruggedness number Rn"
    )
    max_strahler_order: int | None = Field(
        None, ge=1, description="Maximum Strahler stream order"
    )
    length_to_centroid_km: float | None = Field(
        None, ge=0, description="Distance from outlet to boundary centroid [km]"
    )
    hydraulic_length_km: float | None = Field(
        None,
        ge=0,
        description=(
            "Longest flow path from the hydraulically most distant point of the "
            "watershed to the outlet [km] "
            "(the value of flow_path_length_km)"
        ),
    )

    # Flow path parameters
    longest_flow_path_km: float | None = Field(
        None,
        ge=0,
        description="Longest flow path from most remote cell to outlet [km]",
    )
    divide_flow_path_km: float | None = Field(
        None,
        ge=0,
        description="Longest flow path from watershed divide (boundary) to outlet [km]",
    )
    centroid_flow_path_km: float | None = Field(
        None,
        ge=0,
        description="Flow path from watershed centroid to outlet [km]",
    )
    flow_path_length_km: float | None = Field(
        None,
        gt=0,
        description=(
            "Longest flow path from the hydraulically most distant point of the "
            "watershed (usually on the divide, possibly on a ridge inside the "
            "watershed) to the outlet, along the "
            "flow directions of the DEM [km]"
        ),
    )
    flow_path_slope_m_per_m: float | None = Field(
        None,
        gt=0,
        description=(
            "(Elevation of the head of the longest flow path, the hydraulically "
            "most distant point of the watershed - "
            "outlet elevation) / flow_path_length_km [m/m]"
        ),
    )
    overland_length_km: float | None = Field(
        None,
        gt=0,
        description=(
            "Overland segment of the longest flow path, from its head (the "
            "hydraulically most distant point) to the first cell of the DEM "
            "stream network at the delineation threshold [km]"
        ),
    )
    overland_slope_m_per_m: float | None = Field(
        None,
        gt=0,
        description="Drop along the overland segment / its length [m/m]",
    )


class HypsometricPoint(BaseModel):
    """Single point on hypsometric curve."""

    relative_height: float = Field(..., ge=0, le=1, description="Relative height h/H")
    relative_area: float = Field(..., ge=0, le=1, description="Relative area a/A")


class LandCoverCategory(BaseModel):
    """Single land cover category with statistics."""

    category: str = Field(..., description="Land cover category name")
    percentage: float = Field(..., ge=0, le=100, description="Area percentage [%]")
    area_m2: float = Field(..., ge=0, description="Area [m2]")
    cn_value: int = Field(..., ge=0, le=100, description="CN value for category")


class LandCoverStats(BaseModel):
    """Land cover statistics for a watershed."""

    categories: list[LandCoverCategory] = Field(
        ..., description="Per-category statistics"
    )
    weighted_cn: float = Field(
        ..., ge=0, le=100, description="Area-weighted CN (rounded to 0.1)"
    )
    weighted_imperviousness: float = Field(
        ..., ge=0, le=1, description="Area-weighted imperviousness fraction"
    )
    forest_pct: float = Field(
        ..., ge=0, le=100, description="Share of forest [%] (Lutz's W)"
    )
    urban_pct: float = Field(
        ...,
        ge=0,
        le=100,
        description="Share of urbanised (built-up and transport) land [%] (Lutz's U)",
    )


class HsgCategory(BaseModel):
    """Single HSG category."""

    group: str = Field(..., description="HSG group (A/B/C/D)")
    percentage: float = Field(..., ge=0, le=100, description="Area percentage [%]")
    area_m2: float = Field(..., ge=0, description="Area [m²]")


class HsgStats(BaseModel):
    """Soil hydrological group statistics."""

    categories: list[HsgCategory] = Field(..., description="Per-group statistics")
    dominant_group: str = Field(..., description="Dominant HSG group")


class PmaxtpGridCell(BaseModel):
    """A PMAXTP grid point and the area of its Thiessen polygon in a watershed."""

    model_config = ConfigDict(allow_inf_nan=False)

    easting_m: float = Field(..., description="Grid point easting, EPSG:2180 [m]")
    northing_m: float = Field(..., description="Grid point northing, EPSG:2180 [m]")
    area_km2: float = Field(
        ..., gt=0, description="Area of its Thiessen polygon inside the watershed [km2]"
    )


# Grid points one watershed may weigh: a 250 km2 watershed on the default 2 km grid
# has about 90, a 0.5 km grid would give about 1100
PMAXTP_GRID_MAX_CELLS = 2000


class WatershedResponse(BaseModel):
    """Watershed delineation result."""

    boundary_geojson: dict[str, Any] = Field(
        ..., description="Watershed boundary as GeoJSON Feature"
    )
    outlet: OutletInfo = Field(..., description="Outlet point information")
    area_km2: float = Field(..., ge=0, description="Watershed area [km2]")
    hydrograph_available: bool = Field(
        ...,
        description="Whether hydrograph generation is available (area <= 250 km2)",
    )
    morphometry: MorphometricParameters | None = Field(
        None,
        description="Full morphometric parameters for hydrological calculations",
    )
    hypsometric_curve: list[HypsometricPoint] | None = Field(
        None, description="Hypsometric curve (if requested)"
    )
    land_cover_stats: LandCoverStats | None = Field(
        None, description="Land cover statistics"
    )
    hsg_stats: HsgStats | None = None
    main_stream_geojson: dict[str, Any] | None = Field(
        None, description="Main stream as GeoJSON LineString (WGS84)"
    )
    longest_flow_path_geojson: dict[str, Any] | None = Field(
        None, description="Longest flow path as GeoJSON Feature (WGS84)"
    )
    divide_flow_path_geojson: dict[str, Any] | None = Field(
        None, description="Divide flow path (from boundary) as GeoJSON Feature (WGS84)"
    )
    pmaxtp_grid: list[PmaxtpGridCell] | None = Field(
        None,
        description="PMAXTP grid points weighing the watershed's design depth: the "
        "areas of their Thiessen polygons inside it (ADR-069); send them back as "
        "`pmaxtp_grid` of POST /api/generate-hydrograph with `morphometry`; null "
        "without grid data around the watershed",
    )


class StreamInfo(BaseModel):
    """Information about the selected stream segment."""

    segment_idx: int = Field(..., description="Stream segment index")
    strahler_order: int | None = Field(None, description="Strahler stream order")
    length_m: float | None = Field(None, ge=0, description="Segment length [m]")
    upstream_area_km2: float | None = Field(
        None, ge=0, description="Upstream catchment area [km2]"
    )


class DelineateResponse(BaseModel):
    """Full response for watershed delineation endpoint."""

    mode: str = Field(
        ...,
        description=(
            "Delineation mode: 'precomputed' (with threshold) or 'precise' (without)"
        ),
    )
    watershed: WatershedResponse = Field(
        ...,
        description="Watershed delineation results",
    )
    stream: StreamInfo | None = Field(
        None,
        description="Selected stream segment info (precomputed mode only)",
    )
    upstream_segment_indices: list[int] | None = Field(
        None,
        description="Segment indices for MVT stream highlighting",
    )
    display_threshold_m2: int | None = Field(
        None,
        description="Threshold used for upstream_segment_indices (for MVT matching)",
    )
    info_message: str | None = Field(
        None,
        description="User-facing info about parameter changes",
    )
    handoff: dict[str, Any] | None = Field(
        None,
        description=(
            "The watershed as a hand-off to Hydrolog's GUI: nogat-handoff/1 "
            "(schemas/nogat/handoff-1.schema.json) carrying hydrolog-network/1, "
            "without rainfall and result (ADR-068)"
        ),
    )


class DelineatePreviewRequest(DelineateRequest):
    """Request for the delineation preview.

    Same input as precomputed mode of POST /api/delineate-watershed, so
    threshold_m2 is required: precise mode has no preview.
    """

    threshold_m2: int = Field(
        ...,
        gt=0,
        description="Flow accumulation threshold [m2], as in precomputed delineation",
        examples=[10000],
    )


class DelineatePreviewResponse(BaseModel):
    """Sub-catchments a precomputed delineation merges, by depth for animation."""

    threshold_m2: int = Field(
        ...,
        description="Threshold of the sub-catchments (after the floor and cascade)",
    )
    segment_count: int = Field(
        ...,
        ge=1,
        description="Number of sub-catchments the delineation merges",
    )
    catchments: dict[str, Any] = Field(
        ...,
        description=(
            "GeoJSON FeatureCollection (WGS84) with one MultiPolygon per depth "
            "(property depth: drainage links up from the outlet sub-catchment, "
            "0 = outlet), by increasing depth; simplified to about a screen pixel "
            "at the watershed's extent; at most 5000 sub-catchments nearest the outlet"
        ),
    )


# ===================== HYDROGRAPH MODELS =====================


CUSTOM_PRECIPITATION_MAX_STEPS = 2000


class CustomPrecipitation(BaseModel):
    """
    User-supplied rainfall series replacing the PMAXTP design storm.

    Attributes
    ----------
    timestep_min : float
        Length of every interval of the series [min], > 0
    depths_mm : list[float]
        Rainfall depth in each interval [mm], >= 0, 1-2000 values
    """

    timestep_min: float = Field(
        ..., description="Interval length of the series [min]", examples=[10]
    )
    depths_mm: list[float] = Field(
        ...,
        description="Rainfall depth per interval [mm]",
        examples=[[0.5, 2.0, 6.5, 3.0, 1.0]],
    )

    @field_validator("timestep_min")
    @classmethod
    def timestep_positive(cls, v: float) -> float:
        """Accept an interval length above 0 and up to one day [min]."""
        if not v > 0:
            raise ValueError("Krok czasowy szeregu opadu musi być większy od 0 min.")
        if v > 1440:
            raise ValueError(
                "Krok czasowy szeregu opadu nie może przekraczać 1440 min (1 doba)."
            )
        return v

    @field_validator("depths_mm")
    @classmethod
    def depths_valid(cls, v: list[float]) -> list[float]:
        """Accept 1 to the maximum number of finite depths >= 0 with a positive sum."""
        if not v:
            raise ValueError("Szereg opadu musi zawierać co najmniej jedną wartość.")
        if len(v) > CUSTOM_PRECIPITATION_MAX_STEPS:
            raise ValueError(
                f"Szereg opadu może mieć najwyżej {CUSTOM_PRECIPITATION_MAX_STEPS} "
                f"wartości (podano {len(v)})."
            )
        for i, depth in enumerate(v, start=1):
            if not math.isfinite(depth) or depth < 0:
                raise ValueError(
                    f"Wysokość opadu musi być liczbą nieujemną (krok {i}: {depth})."
                )
        if sum(v) <= 0:
            raise ValueError("Suma opadu w szeregu musi być większa od 0 mm.")
        return v


class MorphometryOrigin(BaseModel):
    """
    Where the pre-computed morphometry of a hydrograph request came from.

    The interface sends the morphometry of a delineation; it names the outlet of the
    watershed and the fields the person changed since (the advanced mode), which the
    hand-off of the response gives as the provenance of the watershed.

    Attributes
    ----------
    latitude : float
        Outlet latitude of the delineated watershed in WGS84
    longitude : float
        Outlet longitude of the delineated watershed in WGS84
    changed : list[str]
        Fields of the morphometry the person changed after the delineation
    """

    latitude: float = Field(
        ..., ge=-90, le=90, description="Outlet latitude of the delineated watershed"
    )
    longitude: float = Field(
        ..., ge=-180, le=180, description="Outlet longitude of the delineated watershed"
    )
    changed: list[str] = Field(
        default_factory=list,
        description="Fields of `morphometry` the person changed after the delineation",
        examples=[["cn"]],
    )

    @field_validator("changed")
    @classmethod
    def morphometry_fields(cls, v: list[str]) -> list[str]:
        """Accept the names of fields of the morphometry, each once."""
        for name in v:
            if name not in MorphometricParameters.model_fields:
                raise ValueError(f"Nieznane pole morfometrii: {name}.")
        if len(set(v)) != len(v):
            raise ValueError("Pole morfometrii podano więcej niż raz.")
        return v


class HydrographRequest(BaseModel):
    """
    Request model for hydrograph generation.

    Attributes
    ----------
    latitude : float
        Latitude in WGS84 (decimal degrees)
    longitude : float
        Longitude in WGS84 (decimal degrees)
    duration : str, optional
        Rainfall duration (full PMAXTP range: '5min'...'72h');
        required unless custom_precipitation is given
    probability : float, optional
        Exceedance probability [%]; required unless custom_precipitation is given
    timestep_min : float, optional
        Time step for calculations [min], default 5.0 (ignored for a custom series)
    tc_method : str, optional
        Time of concentration method ('kirpich', 'nrcs', 'giandotti', 'faa', 'kerby',
        'kerby_kirpich'), default 'nrcs'; Hydrolog computes it from the inputs the
        method's source defines
    tc_runoff_coeff : float, optional
        FAA's runoff coefficient C, required by the 'faa' method; never derived
    tc_retardance : float, optional
        Kerby's retardance N, required by 'kerby' and 'kerby_kirpich'; never derived
    hietogram_type : str, optional
        Hietogram type ('beta', 'block', 'euler_ii'), default 'beta'
    uh_model : str, optional
        Unit hydrograph model ('scs', 'snyder', 'nash'), default 'scs'
    snyder_ct : float, optional
        Snyder time coefficient Ct (used when uh_model='snyder')
    snyder_cp : float, optional
        Snyder peak coefficient Cp (used when uh_model='snyder')
    nash_estimation : str, optional
        Nash parameter estimation method ('from_lutz', 'from_urban_regression'),
        default 'from_lutz'
    amc : {'I', 'II', 'III'}, optional
        Antecedent moisture condition applied to CN, default 'II'
    custom_precipitation : CustomPrecipitation, optional
        Own rainfall series; replaces PMAXTP and the hietogram
    morphometry_origin : MorphometryOrigin, optional
        Outlet and changed fields of the delineation `morphometry` came from
    pmaxtp_grid : list[PmaxtpGridCell], optional
        With `morphometry`: the delineation's Thiessen weights of the PMAXTP grid
    areal_reduction_factor : float, optional
        The user's own areal reduction factor of the PMAXTP depth (0, 1]; none
    """

    latitude: float = Field(
        ...,
        ge=-90,
        le=90,
        description="Latitude in WGS84 (decimal degrees)",
        examples=[52.23],
    )
    longitude: float = Field(
        ...,
        ge=-180,
        le=180,
        description="Longitude in WGS84 (decimal degrees)",
        examples=[21.01],
    )
    duration: str | None = Field(
        None,
        pattern=r"^(5min|10min|15min|30min|45min|1h|1\.5h|2h|3h|6h|12h|18h|24h|36h|48h|72h)$",
        description="Rainfall duration (required unless custom_precipitation is given)",
        examples=["1h"],
    )
    probability: float | None = Field(
        None,
        description="Exceedance probability [%] "
        "(required unless custom_precipitation is given)",
        examples=[10],
    )
    timestep_min: float = Field(
        5.0, ge=1, le=60, description="Time step for calculations [min]"
    )
    tc_method: str = Field(
        "nrcs",
        pattern=r"^(kirpich|nrcs|giandotti|faa|kerby|kerby_kirpich)$",
        description="Time of concentration method",
    )
    hietogram_type: str = Field(
        "beta",
        pattern=r"^(beta|block|euler_ii)$",
        description="Hietogram distribution type",
    )
    hietogram_alpha: float = Field(
        2.0, gt=0, le=20, description="Beta hietogram alpha parameter"
    )
    hietogram_beta: float = Field(
        5.0, gt=0, le=20, description="Beta hietogram beta parameter"
    )
    uh_model: Literal["scs", "snyder", "nash"] = Field(
        "scs",
        description="Unit hydrograph model ('scs', 'snyder', or 'nash')",
    )
    snyder_ct: float | None = Field(
        None,
        gt=0,
        description="Snyder time coefficient Ct (default 1.5 if not provided)",
    )
    snyder_cp: float | None = Field(
        None,
        gt=0,
        le=1,
        description="Snyder peak coefficient Cp (default 0.6 if not provided)",
    )
    nash_estimation: Literal["from_lutz", "from_urban_regression"] = Field(
        "from_lutz",
        description="Nash parameter estimation method",
    )
    tc_runoff_coeff: float | None = Field(
        None,
        gt=0.0,
        le=1.0,
        description="Runoff coefficient C of the FAA method (0 < C <= 1; FAA 1970, "
        "AC 150/5320-5B, table I). Required by tc_method 'faa', never derived; "
        "without it the request gets 400 tc_inputs_missing.",
    )
    tc_retardance: float | None = Field(
        None,
        ge=0.02,
        le=0.8,
        description="Kerby retardance coefficient N (0.02 smooth impervious - 0.8 "
        "dense grass, forest; Kerby 1959, TxDOT Hydraulic Design Manual). Required "
        "by tc_method 'kerby' and 'kerby_kirpich', never derived; without it the "
        "request gets 400 tc_inputs_missing.",
    )
    morphometry: MorphometricParameters | None = Field(
        None,
        description="Pre-computed morphometry (skips watershed delineation); its "
        "area_km2 has the limit of a delineated catchment (area_limit_km2 of "
        "GET /api/scenarios, 422 above it)",
    )
    amc: Literal["I", "II", "III"] = Field(
        "II",
        description="Antecedent moisture condition: I dry, II average, III wet",
    )
    custom_precipitation: CustomPrecipitation | None = Field(
        None,
        description="Own rainfall series; replaces PMAXTP and the hietogram "
        "(duration, probability, hietogram_* and timestep_min are then ignored)",
    )
    morphometry_origin: MorphometryOrigin | None = Field(
        None,
        description="Where `morphometry` came from: the outlet of the delineated "
        "watershed and the fields the person changed since; the hand-off of the "
        "response names them (without it, it gives the morphometry as the user's)",
    )
    pmaxtp_grid: list[PmaxtpGridCell] | None = Field(
        None,
        max_length=PMAXTP_GRID_MAX_CELLS,
        description="With `morphometry`: the `pmaxtp_grid` of the delineation, so "
        "the PMAXTP depth is the watershed mean over these Thiessen polygons; "
        "without it the depth is interpolated at the point (IDW of the 4 nearest "
        "grid points). Ignored without `morphometry` (the watershed is delineated "
        "and weighed again) and with `custom_precipitation`",
    )
    areal_reduction_factor: float | None = Field(
        None,
        gt=0,
        le=1,
        description="The user's own areal reduction factor of the PMAXTP depth "
        "(0 < ARF <= 1): the depth used is the PMAXTP depth (watershed mean or IDW "
        "at the point) times ARF. Null (default): no reduction; Hydrograf never "
        "estimates the factor itself (ADR-069). Ignored with `custom_precipitation`",
        examples=[0.95],
    )

    @model_validator(mode="after")
    def design_storm_or_custom(self) -> "HydrographRequest":
        """Require a PMAXTP design storm (duration and probability) or own series."""
        if self.custom_precipitation is None and (
            self.duration is None or self.probability is None
        ):
            raise ValueError(
                "Podaj czas trwania (duration) i prawdopodobieństwo (probability) "
                "opadu albo własny szereg opadu (custom_precipitation)."
            )
        return self


class PmaxtpPoint(BaseModel):
    """A PMAXTP grid point used for the design depth."""

    easting_m: float = Field(..., description="Easting, EPSG:2180 [m]")
    northing_m: float = Field(..., description="Northing, EPSG:2180 [m]")
    latitude: float = Field(..., description="Latitude, WGS84 [deg]")
    longitude: float = Field(..., description="Longitude, WGS84 [deg]")
    precipitation_mm: float = Field(
        ..., ge=0, description="PMAXTP depth of the scenario at the point [mm]"
    )
    weight: float = Field(
        ..., ge=0, le=1, description="Share of the point in the depth [-]"
    )
    area_km2: float | None = Field(
        None,
        description="Thiessen: area of its polygon inside the watershed [km2]",
    )
    distance_m: float | None = Field(
        None, description="IDW: distance from the point of the request [m]"
    )


class PrecipitationInfo(BaseModel):
    """Precipitation event information."""

    source: Literal["pmaxtp", "custom"] = Field(
        ..., description="Rainfall origin: PMAXTP design storm or own series"
    )
    total_mm: float = Field(
        ...,
        ge=0,
        description="Total precipitation used [mm]: for PMAXTP `pmaxtp_depth_mm` "
        "times `areal_reduction_factor` when one was given",
    )
    pmaxtp_depth_mm: float | None = Field(
        None,
        ge=0,
        description="PMAXTP depth before any areal reduction [mm] (the watershed "
        "mean or IDW at the point; null for a custom series)",
    )
    areal_reduction_factor: float | None = Field(
        None,
        description="The user's areal reduction factor applied to the PMAXTP "
        "depth (null: no reduction, and for a custom series)",
    )
    duration_min: float = Field(..., ge=0, description="Duration [min]")
    probability_percent: float | None = Field(
        ..., description="Exceedance probability [%] (null for a custom series)"
    )
    timestep_min: float = Field(..., ge=0, description="Time step [min]")
    times_min: list[float] = Field(..., description="Time values [min]")
    intensities_mm: list[float] = Field(..., description="Precipitation depths [mm]")
    effective_mm: list[float] = Field(
        default_factory=list,
        description="Effective precipitation depths per timestep [mm]",
    )
    interpolation: Literal["thiessen", "idw"] | None = Field(
        None,
        description="How the PMAXTP depth came from the grid: 'thiessen', the "
        "watershed mean over Thiessen polygons, or 'idw' at the point of the "
        "request (null for a custom series)",
    )
    pmaxtp_points: list[PmaxtpPoint] = Field(
        default_factory=list,
        description="The grid points of the PMAXTP depth with their depths and "
        "weights (empty for a custom series)",
    )


class HydrographInfo(BaseModel):
    """Hydrograph results."""

    times_min: list[float] = Field(..., description="Time values [min]")
    discharge_m3s: list[float] = Field(..., description="Discharge values [m3/s]")
    peak_discharge_m3s: float = Field(..., ge=0, description="Peak discharge [m3/s]")
    time_to_peak_min: float = Field(..., ge=0, description="Time to peak [min]")
    total_volume_m3: float = Field(..., ge=0, description="Total runoff volume [m3]")


class WaterBalance(BaseModel):
    """Water balance information from SCS-CN calculation."""

    total_precip_mm: float = Field(..., ge=0, description="Total precipitation [mm]")
    total_effective_mm: float = Field(
        ..., ge=0, description="Effective precipitation [mm]"
    )
    runoff_coefficient: float = Field(
        ..., ge=0, le=1, description="Runoff coefficient [-]"
    )
    cn_used: float = Field(
        ..., ge=0, le=100, description="Curve Number used (adjusted for AMC)"
    )
    retention_mm: float = Field(..., ge=0, description="Maximum retention S [mm]")
    initial_abstraction_mm: float = Field(
        ..., ge=0, description="Initial abstraction Ia [mm]"
    )


class HydrographMetadata(BaseModel):
    """Metadata for hydrograph generation."""

    tc_min: float | None = Field(None, ge=0, description="Time of concentration [min]")
    tc_method: str | None = Field(None, description="TC calculation method used")
    hietogram_type: str | None = Field(
        ..., description="Hietogram type used (null for a custom series)"
    )
    amc: Literal["I", "II", "III"] = Field(
        "II", description="Antecedent moisture condition applied to CN"
    )
    uh_model: str = Field("scs", description="Unit hydrograph model")
    nash_estimation: str | None = Field(None, description="Nash estimation method")
    nash_n: float | None = Field(None, description="Nash N parameter")
    nash_k_min: float | None = Field(None, description="Nash K parameter [min]")
    nash_forest_pct: float | None = Field(
        None, description="Share of forest W in Lutz's estimation [%]"
    )
    nash_urban_pct: float | None = Field(
        None, description="Share of urbanised land U in Lutz's estimation [%]"
    )
    nash_urban_fraction: float | None = Field(
        None, description="Urbanization index used [0-1]"
    )
    nash_effective_precip_mm: float | None = Field(
        None, description="Effective precip used for Nash urban regression [mm]"
    )
    nash_duration_h: float | None = Field(
        None, description="Duration used for Nash urban regression [h]"
    )


class HydrographResponse(BaseModel):
    """
    Full response for hydrograph generation endpoint.

    Attributes
    ----------
    watershed : WatershedResponse
        Watershed information with morphometry
    precipitation : PrecipitationInfo
        Precipitation event details
    hydrograph : HydrographInfo
        Generated hydrograph data
    water_balance : WaterBalance
        Water balance from SCS-CN
    metadata : HydrographMetadata
        Calculation metadata
    handoff : dict
        The watershed, its rainfall, runoff and result as a hand-off to Hydrolog
    """

    watershed: WatershedResponse | None = Field(
        None, description="Watershed information (omitted in fast mode)"
    )
    precipitation: PrecipitationInfo = Field(..., description="Precipitation event")
    hydrograph: HydrographInfo = Field(..., description="Generated hydrograph")
    water_balance: WaterBalance = Field(..., description="Water balance")
    metadata: HydrographMetadata = Field(..., description="Calculation metadata")
    handoff: dict[str, Any] = Field(
        ...,
        description=(
            "The watershed with the rainfall, runoff and unrounded result of this "
            "computation as a hand-off to Hydrolog's GUI: nogat-handoff/1 "
            "(schemas/nogat/handoff-1.schema.json) carrying hydrolog-network/1 "
            "(ADR-068)"
        ),
    )


# ===================== TERRAIN PROFILE MODELS =====================


class TerrainProfileRequest(BaseModel):
    """Request model for terrain profile extraction."""

    geometry: dict[str, Any] = Field(..., description="GeoJSON LineString geometry")
    n_samples: int = Field(100, ge=2, le=1000, description="Number of sample points")
    result_ids: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Ids of analysis results (manifest /data/results/index.json) whose "
            "maximum water level is sampled along the line"
        ),
    )


class ProfileWaterLevel(BaseModel):
    """Maximum water level of one analysis result along the profile."""

    result_id: str = Field(..., description="Analysis result id (results manifest)")
    levels_m: list[float | None] = Field(
        ...,
        description=(
            "Water level [m a.s.l.] at each sample; null where dry, off the "
            "result or without DEM data"
        ),
    )


class TerrainProfileResponse(BaseModel):
    """Response model for terrain profile."""

    distances_m: list[float] = Field(..., description="Cumulative distances [m]")
    elevations_m: list[float] = Field(
        ...,
        description="Elevations [m a.s.l.]; 0.0 at the samples that dem_gaps marks",
    )
    dem_gaps: list[bool] = Field(
        ...,
        description="True at each sample where the DEM has no data (off its extent): "
        "a gap of the profile, not an elevation",
    )
    total_length_m: float = Field(..., ge=0, description="Total line length [m]")
    water_levels: list[ProfileWaterLevel] = Field(
        default_factory=list,
        description="Requested results whose water level raster the line crosses",
    )


# ===================== POINT IDENTIFICATION MODELS =====================


class IdentifyPointRequest(BaseModel):
    """Query parameters of the identification of one map point (GET)."""

    latitude: float = Field(
        ...,
        ge=-90,
        le=90,
        description="Latitude in WGS84 (decimal degrees)",
        examples=[51.0376],
    )
    longitude: float = Field(
        ...,
        ge=-180,
        le=180,
        description="Longitude in WGS84 (decimal degrees)",
        examples=[16.1723],
    )
    threshold_m2: int | None = Field(
        None,
        gt=0,
        description=(
            "Flow accumulation threshold [m2] of the sub-catchment network to read "
            "(the flow lines on the map); raised to 10000, the default, if lower"
        ),
        examples=[100000],
    )
    result_ids: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Ids of analysis results (manifest /data/results/index.json) whose "
            "maximum water level is read at the point"
        ),
    )


class PointPl2000(BaseModel):
    """The point in PL-2000, in the zone of its longitude."""

    zone: int = Field(
        ...,
        ge=5,
        le=8,
        description="Zone: 5 west of 16.5°E, 6 to 19.5°E, 7 to 22.5°E, 8 east of it",
    )
    epsg: int = Field(..., description="EPSG code of the zone, 2176 to 2179")
    easting_m: float = Field(
        ...,
        description="Easting [m], Y of Polish surveying; starts with the zone number",
    )
    northing_m: float = Field(..., description="Northing [m], X of Polish surveying")


class PointCoordinates(BaseModel):
    """The point in WGS84, PL-1992 and PL-2000 (Polish grids only)."""

    latitude: float = Field(..., description="Latitude in WGS84 [°]")
    longitude: float = Field(..., description="Longitude in WGS84 [°]")
    easting_m: float = Field(
        ..., description="PL-1992 (EPSG:2180) easting [m], Y of Polish surveying"
    )
    northing_m: float = Field(
        ..., description="PL-1992 (EPSG:2180) northing [m], X of Polish surveying"
    )
    pl2000: PointPl2000 = Field(..., description="PL-2000 (EPSG:2176 to 2179)")


class PointWater(BaseModel):
    """Maximum water of one analysis result at the point."""

    result_id: str = Field(..., description="Analysis result id (results manifest)")
    water_level_m: float | None = Field(
        ..., description="Maximum water level [m a.s.l.]; null where the result is dry"
    )
    depth_m: float | None = Field(
        ...,
        description=(
            "Water level minus the terrain elevation [m]; null where the water "
            "does not lie above the terrain"
        ),
    )


class PointStream(BaseModel):
    """Nearest BDOT10k stream line to the point, at most 5 km away."""

    name: str | None = Field(None, description="Name (BDOT10k), null if unnamed")
    layer_type: str = Field(
        ..., description="BDOT10k layer: SWRS river, SWKN canal, SWRM ditch"
    )
    distance_m: float = Field(..., ge=0, description="Distance from the point [m]")


class PointWaterBody(BaseModel):
    """BDOT10k water body polygon (lake, pond, wide river) containing the point."""

    name: str | None = Field(None, description="Name (BDOT10k NAZWA), null if unnamed")
    kind: str | None = Field(
        None, description="Kind of water (BDOT10k RODZAJ), e.g. 'woda stojąca'"
    )


class PointLandCover(BaseModel):
    """Land cover at the point."""

    category: str = Field(
        ..., description="Land cover category, as in land_cover_stats"
    )
    bdot_class: str | None = Field(None, description="BDOT10k layer, e.g. PTLZ")
    cn: int = Field(
        ...,
        description="CN of the category for AMC II (average), as in the catchment CN",
    )
    cn_amc_i: int = Field(
        ..., description="CN for AMC I (dry), converted from cn by Hydrolog"
    )
    cn_amc_iii: int = Field(
        ..., description="CN for AMC III (wet), converted from cn by Hydrolog"
    )
    imperviousness: float | None = Field(
        None, description="Impervious fraction of the category (0-1)"
    )


class PointDepression(BaseModel):
    """Terrain depression (blue spot) containing the point."""

    max_depth_m: float = Field(..., description="Maximum depth of the depression [m]")
    mean_depth_m: float | None = Field(None, description="Mean depth [m]")
    area_m2: float = Field(..., description="Area of the depression [m2]")
    volume_m3: float = Field(..., description="Volume of the depression [m3]")


class PointSubcatchment(BaseModel):
    """Precomputed sub-catchment containing the point and its stream segment."""

    threshold_m2: int = Field(
        ..., description="Flow accumulation threshold of the network [m2]"
    )
    segment_idx: int = Field(..., description="Stream segment index")
    area_km2: float = Field(..., description="Area of the sub-catchment [km2]")
    upstream_area_km2: float | None = Field(
        None,
        description=(
            "Catchment area at the segment's downstream end [km2], as a "
            "precomputed delineation from this sub-catchment"
        ),
    )
    strahler_order: int | None = Field(None, description="Strahler order")
    segment_length_m: float | None = Field(None, description="Segment length [m]")
    is_real_stream: bool | None = Field(
        None,
        description="Segment matched to a BDOT10k stream; null if not matched",
    )
    channel_length_km: float | None = Field(
        None,
        description=(
            "Main channel length [km] of the catchment at the segment's downstream "
            "end, as channel_length_km of a delineated watershed; null without the "
            "in-memory catchment graph"
        ),
    )
    distance_to_outlet_km: float | None = Field(
        None,
        description=(
            "Flow distance [km] from the segment's downstream end to the outlet of "
            "the network, where the water leaves the data area (not necessarily a "
            "river mouth); null without the in-memory catchment graph"
        ),
    )


class IdentifyPointResponse(BaseModel):
    """What Hydrograf knows at a point; a member is null where its source is empty."""

    coordinates: PointCoordinates = Field(..., description="The point")
    elevation_m: float = Field(
        ..., description="Terrain elevation of the DEM [m a.s.l.]"
    )
    slope_percent: float | None = Field(
        None, description="Terrain slope of the DEM [%]"
    )
    water: list[PointWater] = Field(
        default_factory=list,
        description="Requested results whose water level raster holds the point",
    )
    stream: PointStream | None = Field(
        None, description="Nearest BDOT10k stream, at most 5 km away"
    )
    water_body: PointWaterBody | None = Field(
        None, description="BDOT10k water body containing the point"
    )
    land_cover: PointLandCover | None = Field(None, description="Land cover")
    soil_hsg: str | None = Field(
        None, description="Hydrologic soil group (A, B, C or D)"
    )
    depression: PointDepression | None = Field(
        None, description="Terrain depression containing the point"
    )
    subcatchment: PointSubcatchment | None = Field(
        None, description="Sub-catchment of the precomputed network at the point"
    )


# ===================== FEEDBACK MODELS =====================


class FeedbackRequest(BaseModel):
    """Request model for tester feedback submission."""

    message: str = Field(
        ..., min_length=1, max_length=5000, description="Feedback text"
    )
    contact: str | None = Field(
        None, max_length=200, description="Optional name or email"
    )
    page_url: str | None = Field(
        None, max_length=500, description="Page URL at submission time"
    )
    diagnostics: dict[str, Any] | None = Field(
        None, description="Session diagnostics (events, workspace, env)"
    )

    @field_validator("diagnostics")
    @classmethod
    def diagnostics_size_limit(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """Reject a diagnostics payload larger than 100 KB."""
        if v is not None and len(json.dumps(v)) > 100_000:
            raise ValueError("diagnostics payload exceeds 100 KB limit")
        return v


class FeedbackResponse(BaseModel):
    """Response model for feedback submission."""

    id: int = Field(..., description="Created feedback record id")
    status: str = Field("ok", description="Submission status")


class FeedbackUpdate(BaseModel):
    """Request model for changing the read flag of a feedback submission."""

    is_read: bool = Field(
        ..., strict=True, description="Whether the submission is read"
    )
