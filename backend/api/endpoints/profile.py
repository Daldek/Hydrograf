"""
Terrain profile endpoint.

Extracts elevation profile along a GeoJSON LineString by reading the DEM in
windows along the line, and on request the maximum water level of analysis
results along the same samples.
"""

import logging
import math

from fastapi import APIRouter, Response
from pyproj import Transformer
from rasterio.transform import rowcol
from shapely.geometry import LineString

from core.analysis_results import sample_water_levels
from core.config import get_settings
from core.errors import (
    HydrografError,
    InternalError,
    InvalidRequestError,
    NoDataError,
    StoreUnavailableError,
)
from core.raster_io import read_raster_window
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

# Largest extent [m] of a window of the DEM: a line up to this long is read in
# one window, a longer one in windows of consecutive samples along it, so a
# profile never holds more of the DEM than one window (400 x 400 cells at 5 m).
PROFILE_WINDOW_SIDE_M = 2000.0


def _dem_samples(
    dem_path: str, points: list[tuple[float, float]], spacing_m: float
) -> tuple[list[float], list[bool]]:
    """Elevation and DEM gap at each sample, read in windows along the line.

    Consecutive samples are ``spacing_m`` apart along the line, so the bounding
    box of ``per_window`` of them is at most PROFILE_WINDOW_SIDE_M across; each
    is read with the cell around it (``read_raster_window``). A sample where
    the DEM has no data, also off its extent, is a gap with elevation 0.0.
    """
    per_window = (
        len(points) if spacing_m == 0 else int(PROFILE_WINDOW_SIDE_M // spacing_m) + 1
    )
    elevations: list[float] = []
    gaps: list[bool] = []
    for start in range(0, len(points), per_window):
        run = points[start : start + per_window]
        xs = [p[0] for p in run]
        ys = [p[1] for p in run]
        window = read_raster_window(dem_path, (min(xs), min(ys), max(xs), max(ys)))
        rows, cols = rowcol(window.transform, xs, ys)
        for value in window.data[rows, cols]:
            elev = float(value)
            gap = window.nodata is not None and math.isclose(
                elev, float(window.nodata), rel_tol=1e-6
            )
            elevations.append(0.0 if gap else elev)
            gaps.append(gap)
    return elevations, gaps


@router.post("/terrain-profile", response_model=TerrainProfileResponse)
def terrain_profile(
    request: TerrainProfileRequest,
    response: Response,
) -> TerrainProfileResponse:
    """
    Extract terrain elevation profile along a line.

    Samples N equally spaced points along the input LineString and reads
    their elevations from windows of the DEM along the line. A sample where
    the DEM has no data is a gap: ``dem_gaps`` marks it and ``elevations_m``
    holds 0.0 there. For each requested analysis result with a water level
    raster crossed by the line, the water level at the same samples (null
    where dry or in a gap).

    Parameters
    ----------
    request : TerrainProfileRequest
        GeoJSON LineString geometry, number of samples, analysis result ids

    Returns
    -------
    TerrainProfileResponse
        Arrays of distances, elevations and gaps along the profile, water levels

    Raises
    ------
    InvalidRequestError
        ``validation_error`` (400) for a geometry other than a LineString of at
        least two points
    NoDataError
        ``no_data`` (404, ``no_elevation_data``) when the DEM has no data at any
        sample of the line
    StoreUnavailableError
        ``store_unavailable`` (503) when there is no DEM raster
    InternalError
        ``internal_error`` (500) on an unexpected failure
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

        # Read elevations from windows of the DEM along the line
        settings = get_settings()
        dem_path = settings.resolve_dem_path()

        if dem_path is None:
            logger.error("No DEM raster found in %s", settings.dem_dir)
            raise StoreUnavailableError("dem_unavailable", reason="dem_unavailable")

        elevations, dem_gaps = _dem_samples(
            dem_path, sample_points, total_length_m / max(n_samples - 1, 1)
        )

        if not elevations or all(dem_gaps):
            raise NoDataError("no_elevation_data", reason="no_elevation_data")

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
            dem_gaps=dem_gaps,
            total_length_m=total_length_m,
            water_levels=water_levels,
        )

    except HydrografError:
        raise
    except Exception as e:
        logger.error(f"Error extracting terrain profile: {e}", exc_info=True)
        raise InternalError("profile_failed", reason="profile_failed") from e
