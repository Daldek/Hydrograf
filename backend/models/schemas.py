"""
Pydantic models for API request/response schemas.

Defines data structures for watershed delineation API endpoints.
"""

from pydantic import BaseModel, Field
from typing import Any


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
    """

    boundary_geojson: dict[str, Any] = Field(
        ..., description="Watershed boundary as GeoJSON Feature"
    )
    outlet: OutletInfo = Field(..., description="Outlet point information")
    cell_count: int = Field(..., ge=0, description="Number of cells in watershed")
    area_km2: float = Field(..., ge=0, description="Watershed area [km2]")
    hydrograph_available: bool = Field(
        ..., description="Whether hydrograph generation is available (area <= 250 km2)"
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
