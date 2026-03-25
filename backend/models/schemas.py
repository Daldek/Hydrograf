"""
Pydantic models for API request/response schemas.

Defines data structures for watershed delineation and hydrograph
generation API endpoints.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


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
        description="Flow accumulation threshold [m2]. If provided, uses pre-computed catchments (fast). If omitted, performs precise on-the-fly delineation.",
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
        Main channel length [km]
    channel_slope_m_per_m : float, optional
        Main channel slope [m/m]
    cn : int, optional
        SCS Curve Number (0-100)
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
        None, ge=0, description="Main channel length [km]"
    )
    channel_slope_m_per_m: float | None = Field(
        None, ge=0, description="Main channel slope [m/m]"
    )
    real_channel_length_km: float | None = Field(
        None, ge=0,
        description="Main channel length covered by BDOT10k real streams [km]",
    )
    cn: int | None = Field(None, ge=0, le=100, description="SCS Curve Number")
    imperviousness: float | None = Field(
        None, ge=0, le=1, description="Weighted imperviousness fraction [0-1]"
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
    mean_width_km: float | None = Field(None, ge=0, description="Mean width A/L [km]")

    # Relief indices
    relief_ratio: float | None = Field(None, description="Relief ratio Rh")
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
        None, ge=0,
        description="Longest flow path from most remote point to outlet [km]",
    )

    # Flow path parameters
    longest_flow_path_km: float | None = Field(
        None, ge=0,
        description="Longest flow path from most remote cell to outlet [km]",
    )
    divide_flow_path_km: float | None = Field(
        None, ge=0,
        description="Longest flow path from watershed divide (boundary) to outlet [km]",
    )
    centroid_flow_path_km: float | None = Field(
        None, ge=0,
        description="Flow path from watershed centroid to outlet [km]",
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
    weighted_cn: int = Field(..., ge=0, le=100, description="Area-weighted CN")
    weighted_imperviousness: float = Field(
        ..., ge=0, le=1, description="Area-weighted imperviousness fraction"
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
        description="Delineation mode: 'precomputed' (with threshold) or 'precise' (without)",
    )
    watershed: WatershedResponse = Field(
        ..., description="Watershed delineation results",
    )
    stream: StreamInfo | None = Field(
        None, description="Selected stream segment info (precomputed mode only)",
    )
    upstream_segment_indices: list[int] | None = Field(
        None, description="Segment indices for MVT stream highlighting",
    )
    display_threshold_m2: int | None = Field(
        None, description="Threshold used for upstream_segment_indices (for MVT matching)",
    )
    info_message: str | None = Field(
        None, description="User-facing info about parameter changes",
    )


# ===================== HYDROGRAPH MODELS =====================


class HydrographRequest(BaseModel):
    """
    Request model for hydrograph generation.

    Attributes
    ----------
    latitude : float
        Latitude in WGS84 (decimal degrees)
    longitude : float
        Longitude in WGS84 (decimal degrees)
    duration : str
        Rainfall duration (full PMAXTP range: '5min'...'72h')
    probability : int
        Exceedance probability [%] (1, 2, 5, 10, 20, 50)
    timestep_min : float, optional
        Time step for calculations [min], default 5.0
    tc_method : str, optional
        Time of concentration method ('kirpich', 'nrcs', 'giandotti')
    hietogram_type : str, optional
        Hietogram type ('beta', 'block', 'euler_ii'), default 'beta'
    uh_model : str, optional
        Unit hydrograph model ('scs', 'snyder', 'nash'), default 'scs'
    snyder_ct : float, optional
        Snyder time coefficient Ct (used when uh_model='snyder')
    snyder_cp : float, optional
        Snyder peak coefficient Cp (used when uh_model='snyder')
    nash_estimation : str, optional
        Nash parameter estimation method ('from_tc', 'from_lutz')
    nash_n : float, optional
        Nash N parameter — number of reservoirs (used with from_tc)
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
    duration: str = Field(
        ...,
        pattern=r"^(5min|10min|15min|30min|45min|1h|1\.5h|2h|3h|6h|12h|18h|24h|36h|48h|72h)$",
        description="Rainfall duration",
        examples=["1h"],
    )
    probability: float = Field(
        ...,
        description="Exceedance probability [%]",
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
    nash_estimation: Literal["from_tc", "from_lutz", "from_urban_regression"] = Field(
        "from_lutz",
        description="Nash parameter estimation method (from_tc deprecated since Hydrolog v0.6.2)",
    )
    nash_n: float = Field(
        3.0,
        gt=0,
        le=20,
        description="Nash N parameter (number of reservoirs, used with from_tc)",
    )
    tc_runoff_coeff: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Runoff coefficient C for FAA method [0-1]. "
        "If not provided, estimated from CN.",
    )
    tc_retardance: float | None = Field(
        None,
        ge=0.02,
        le=0.8,
        description="Kerby retardance coefficient N (0.02=smooth, 0.8=dense forest). "
        "Default 0.4 (grass/crops).",
    )
    tc_overland_length_km: float | None = Field(
        None,
        gt=0,
        le=5.0,
        description="Overland flow length for FAA/Kerby methods [km]. "
        "Required for FAA (typ. 0.015-3 km) and Kerby (max 0.366 km).",
    )
    morphometry: MorphometricParameters | None = Field(
        None,
        description="Pre-computed morphometry (skips watershed delineation)",
    )


class PrecipitationInfo(BaseModel):
    """Precipitation event information."""

    total_mm: float = Field(..., ge=0, description="Total precipitation [mm]")
    duration_min: float = Field(..., ge=0, description="Duration [min]")
    probability_percent: float = Field(..., description="Exceedance probability [%]")
    timestep_min: float = Field(..., ge=0, description="Time step [min]")
    times_min: list[float] = Field(..., description="Time values [min]")
    intensities_mm: list[float] = Field(..., description="Precipitation depths [mm]")
    effective_mm: list[float] = Field(
        default_factory=list,
        description="Effective precipitation depths per timestep [mm]",
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
    cn_used: int = Field(..., ge=0, le=100, description="Curve Number used")
    retention_mm: float = Field(..., ge=0, description="Maximum retention S [mm]")
    initial_abstraction_mm: float = Field(
        ..., ge=0, description="Initial abstraction Ia [mm]"
    )


class HydrographMetadata(BaseModel):
    """Metadata for hydrograph generation."""

    tc_min: float | None = Field(None, ge=0, description="Time of concentration [min]")
    tc_method: str | None = Field(None, description="TC calculation method used")
    hietogram_type: str = Field(..., description="Hietogram type used")
    uh_model: str = Field("scs", description="Unit hydrograph model")
    nash_estimation: str | None = Field(None, description="Nash estimation method")
    nash_n: float | None = Field(None, description="Nash N parameter")
    nash_k_min: float | None = Field(None, description="Nash K parameter [min]")
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
    """

    watershed: WatershedResponse | None = Field(
        None, description="Watershed information (omitted in fast mode)"
    )
    precipitation: PrecipitationInfo = Field(..., description="Precipitation event")
    hydrograph: HydrographInfo = Field(..., description="Generated hydrograph")
    water_balance: WaterBalance = Field(..., description="Water balance")
    metadata: HydrographMetadata = Field(..., description="Calculation metadata")


# ===================== TERRAIN PROFILE MODELS =====================


class TerrainProfileRequest(BaseModel):
    """Request model for terrain profile extraction."""

    geometry: dict[str, Any] = Field(..., description="GeoJSON LineString geometry")
    n_samples: int = Field(100, ge=2, le=1000, description="Number of sample points")


class TerrainProfileResponse(BaseModel):
    """Response model for terrain profile."""

    distances_m: list[float] = Field(..., description="Cumulative distances [m]")
    elevations_m: list[float] = Field(..., description="Elevations [m a.s.l.]")
    total_length_m: float = Field(..., ge=0, description="Total line length [m]")
