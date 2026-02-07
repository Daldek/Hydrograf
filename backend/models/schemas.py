"""
Pydantic models for API request/response schemas.

Defines data structures for watershed delineation and hydrograph generation API endpoints.
"""

from typing import Any

from pydantic import BaseModel, Field


class DelineateRequest(BaseModel):
    """
    Request model for watershed delineation.

    Attributes
    ----------
    latitude : float
        Latitude in WGS84 (decimal degrees), range -90 to 90
    longitude : float
        Longitude in WGS84 (decimal degrees), range -180 to 180
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
    cn: int | None = Field(None, ge=0, le=100, description="SCS Curve Number")
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
    form_factor: float | None = Field(
        None, description="Horton form factor Ff"
    )
    mean_width_km: float | None = Field(
        None, ge=0, description="Mean width A/L [km]"
    )

    # Relief indices
    relief_ratio: float | None = Field(
        None, description="Relief ratio Rh"
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


class HypsometricPoint(BaseModel):
    """Single point on hypsometric curve."""

    relative_height: float = Field(
        ..., ge=0, le=1, description="Relative height h/H"
    )
    relative_area: float = Field(
        ..., ge=0, le=1, description="Relative area a/A"
    )


class WatershedResponse(BaseModel):
    """
    Watershed delineation result.

    Attributes
    ----------
    boundary_geojson : dict
        Watershed boundary as GeoJSON Feature (Polygon)
    outlet : OutletInfo
        Information about outlet point
    cell_count : int
        Number of cells in the watershed
    area_km2 : float
        Watershed area in square kilometers
    hydrograph_available : bool
        Whether SCS-CN hydrograph can be generated (area <= 250 km2)
    morphometry : MorphometricParameters, optional
        Full morphometric parameters for hydrological calculations
    hypsometric_curve : list of HypsometricPoint, optional
        Hypsometric curve data (only if requested)
    """

    boundary_geojson: dict[str, Any] = Field(
        ..., description="Watershed boundary as GeoJSON Feature"
    )
    outlet: OutletInfo = Field(..., description="Outlet point information")
    cell_count: int = Field(
        ..., ge=0, description="Number of cells in watershed"
    )
    area_km2: float = Field(
        ..., ge=0, description="Watershed area [km2]"
    )
    hydrograph_available: bool = Field(
        ...,
        description="Whether hydrograph generation is available"
        " (area <= 250 km2)",
    )
    morphometry: MorphometricParameters | None = Field(
        None,
        description="Full morphometric parameters"
        " for hydrological calculations",
    )
    hypsometric_curve: list[HypsometricPoint] | None = Field(
        None, description="Hypsometric curve (if requested)"
    )


class DelineateResponse(BaseModel):
    """
    Full response for watershed delineation endpoint.

    Attributes
    ----------
    watershed : WatershedResponse
        Watershed delineation results
    """

    watershed: WatershedResponse = Field(
        ..., description="Watershed delineation results"
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
        Rainfall duration ('15min', '30min', '1h', '2h', '6h', '12h', '24h')
    probability : int
        Exceedance probability [%] (1, 2, 5, 10, 20, 50)
    timestep_min : float, optional
        Time step for calculations [min], default 5.0
    tc_method : str, optional
        Time of concentration method ('kirpich', 'scs_lag', 'giandotti')
    hietogram_type : str, optional
        Hietogram type ('beta', 'block', 'euler_ii'), default 'beta'
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
        pattern=r"^(15min|30min|1h|2h|6h|12h|24h)$",
        description="Rainfall duration",
        examples=["1h"],
    )
    probability: int = Field(
        ...,
        description="Exceedance probability [%]",
        examples=[10],
    )
    timestep_min: float = Field(
        5.0, ge=1, le=60, description="Time step for calculations [min]"
    )
    tc_method: str = Field(
        "kirpich",
        pattern=r"^(kirpich|scs_lag|giandotti)$",
        description="Time of concentration method",
    )
    hietogram_type: str = Field(
        "beta",
        pattern=r"^(beta|block|euler_ii)$",
        description="Hietogram distribution type",
    )


class PrecipitationInfo(BaseModel):
    """Precipitation event information."""

    total_mm: float = Field(..., ge=0, description="Total precipitation [mm]")
    duration_min: float = Field(..., ge=0, description="Duration [min]")
    probability_percent: int = Field(..., description="Exceedance probability [%]")
    timestep_min: float = Field(..., ge=0, description="Time step [min]")
    times_min: list[float] = Field(..., description="Time values [min]")
    intensities_mm: list[float] = Field(..., description="Precipitation depths [mm]")


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

    tc_min: float = Field(..., ge=0, description="Time of concentration [min]")
    tc_method: str = Field(..., description="TC calculation method used")
    hietogram_type: str = Field(..., description="Hietogram type used")
    uh_model: str = Field("scs", description="Unit hydrograph model")


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

    watershed: WatershedResponse = Field(..., description="Watershed information")
    precipitation: PrecipitationInfo = Field(..., description="Precipitation event")
    hydrograph: HydrographInfo = Field(..., description="Generated hydrograph")
    water_balance: WaterBalance = Field(..., description="Water balance")
    metadata: HydrographMetadata = Field(..., description="Calculation metadata")
