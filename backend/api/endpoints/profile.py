"""
Terrain profile endpoint.

Extracts elevation profile along a GeoJSON LineString
by sampling the DEM raster file via rasterio.
"""

import logging
import math

import rasterio
from fastapi import APIRouter, Response
from pyproj import Transformer
from shapely.geometry import LineString

from core.config import get_settings
from core.errors import (
    HydrografError,
    InternalError,
    InvalidRequestError,
    NoDataError,
    StoreUnavailableError,
)
from models.schemas import TerrainProfileRequest, TerrainProfileResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# Reusable CRS transformer (WGS84 lon,lat -> PL-1992 x,y)
_transformer_4326_to_2180 = Transformer.from_crs(
    "EPSG:4326", "EPSG:2180", always_xy=True
)


@router.post("/terrain-profile", response_model=TerrainProfileResponse)
def terrain_profile(
    request: TerrainProfileRequest,
    response: Response,
) -> TerrainProfileResponse:
    """
    Extract terrain elevation profile along a line.

    Samples N equally spaced points along the input LineString and
    reads elevation values directly from the DEM raster file.

    Parameters
    ----------
    request : TerrainProfileRequest
        GeoJSON LineString geometry and number of samples

    Returns
    -------
    TerrainProfileResponse
        Arrays of distances and elevations along the profile
    """
    try:
        geom = request.geometry
        if geom.get("type") != "LineString":
            raise InvalidRequestError(
                "profile_geometry_type",
                reason="invalid_geometry_type",
                geometry_type=geom.get("type"),
            )

        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            raise InvalidRequestError(
                "profile_too_few_coordinates",
                reason="too_few_coordinates",
                coordinates=len(coords),
            )

        n_samples = request.n_samples

        # Transform GeoJSON coords (lon, lat) to PL-1992 (x, y)
        coords_2180 = [_transformer_4326_to_2180.transform(c[0], c[1]) for c in coords]
        line = LineString(coords_2180)
        total_length_m = line.length

        # Generate sample points along the line
        sample_points = []
        distances = []
        for i in range(n_samples):
            frac = i / max(n_samples - 1, 1)
            point = line.interpolate(frac, normalized=True)
            sample_points.append((point.x, point.y))
            distances.append(frac * total_length_m)

        # Read elevations from DEM file
        settings = get_settings()
        dem_path = settings.resolve_dem_path()

        if dem_path is None:
            logger.error("No DEM raster found in %s", settings.dem_dir)
            raise StoreUnavailableError("dem_unavailable", reason="dem_unavailable")

        elevations: list[float] = []
        nodata_count = 0
        with rasterio.open(dem_path) as dataset:
            for val in dataset.sample(sample_points):
                elev = float(val[0])
                if dataset.nodata is not None and math.isclose(
                    elev, float(dataset.nodata), rel_tol=1e-6
                ):
                    elevations.append(0.0)
                    nodata_count += 1
                else:
                    elevations.append(elev)

        if not elevations or nodata_count == len(elevations):
            raise NoDataError("no_elevation_data", reason="no_elevation_data")

        response.headers["Cache-Control"] = "public, max-age=3600"
        return TerrainProfileResponse(
            distances_m=distances,
            elevations_m=elevations,
            total_length_m=total_length_m,
        )

    except HydrografError:
        raise
    except Exception as e:
        logger.error(f"Error extracting terrain profile: {e}", exc_info=True)
        raise InternalError("profile_failed", reason="profile_failed") from e
