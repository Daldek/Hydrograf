"""
Terrain profile endpoint.

Extracts elevation profile along a GeoJSON LineString
by sampling the DEM raster file via rasterio, and on request the maximum
water level of analysis results along the same samples.
"""

import logging
import math
import os

import rasterio
from fastapi import APIRouter, HTTPException, Response
from pyproj import Transformer
from shapely.geometry import LineString

from core.analysis_results import sample_water_levels
from core.config import get_settings
from models.schemas import (
    ProfileWaterLevel,
    TerrainProfileRequest,
    TerrainProfileResponse,
)

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
    reads elevation values directly from the DEM raster file. For each
    requested analysis result with a water level raster crossed by the line,
    the water level at the same samples (null where dry).

    Parameters
    ----------
    request : TerrainProfileRequest
        GeoJSON LineString geometry, number of samples, analysis result ids

    Returns
    -------
    TerrainProfileResponse
        Arrays of distances and elevations along the profile, water levels
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
        dem_path = settings.resolve_dem_path()

        if dem_path is None:
            logger.error("No DEM raster found in %s", settings.dem_dir)
            raise HTTPException(
                status_code=503,
                detail="Plik DEM nie jest dostepny. Skontaktuj sie z administratorem.",
            )

        elevations: list[float] = []
        dem_gaps: list[bool] = []
        with rasterio.open(dem_path) as dataset:
            for val in dataset.sample(sample_points):
                elev = float(val[0])
                gap = dataset.nodata is not None and math.isclose(
                    elev, float(dataset.nodata), rel_tol=1e-6
                )
                elevations.append(0.0 if gap else elev)
                dem_gaps.append(gap)

        if not elevations or all(dem_gaps):
            raise HTTPException(
                status_code=404,
                detail="Brak danych wysokosciowych dla podanej linii",
            )

        # Water levels only where the terrain is known (a gap reads as 0 m)
        water_levels = [
            ProfileWaterLevel(
                result_id=result_id,
                levels_m=[
                    None if gap else level
                    for level, gap in zip(levels, dem_gaps, strict=True)
                ],
            )
            for result_id, levels in sample_water_levels(
                settings.frontend_data_dir, request.result_ids, sample_points
            )
        ]

        response.headers["Cache-Control"] = "public, max-age=3600"
        return TerrainProfileResponse(
            distances_m=distances,
            elevations_m=elevations,
            total_length_m=total_length_m,
            water_levels=water_levels,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error extracting terrain profile: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error during profile extraction",
        ) from e
