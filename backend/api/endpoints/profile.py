"""
Terrain profile endpoint.

Extracts elevation profile along a GeoJSON LineString
by sampling the DEM raster file via rasterio.
"""

import logging
import os

import rasterio
from fastapi import APIRouter, HTTPException, Response
from pyproj import Transformer
from shapely.geometry import LineString

from core.config import get_settings
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
            raise HTTPException(
                status_code=400,
                detail="Geometry must be a LineString",
            )

        coords = geom.get("coordinates", [])
        if len(coords) < 2:
            raise HTTPException(
                status_code=400,
                detail="LineString must have at least 2 coordinates",
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
        dem_path = settings.dem_path

        if not os.path.exists(dem_path):
            raise HTTPException(
                status_code=503,
                detail=f"Plik DEM nie jest dostepny: {dem_path}. Skonfiguruj DEM_PATH.",
            )

        elevations: list[float] = []
        with rasterio.open(dem_path) as dataset:
            for val in dataset.sample(sample_points):
                elev = float(val[0])
                # Handle nodata
                if dataset.nodata is not None and elev == dataset.nodata:
                    elevations.append(0.0)
                else:
                    elevations.append(elev)

        if not elevations or all(e == 0.0 for e in elevations):
            raise HTTPException(
                status_code=404,
                detail="Brak danych wysokosciowych dla podanej linii",
            )

        response.headers["Cache-Control"] = "public, max-age=3600"
        return TerrainProfileResponse(
            distances_m=distances,
            elevations_m=elevations,
            total_length_m=total_length_m,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error extracting terrain profile: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error during profile extraction",
        ) from e
