"""
Point identification endpoint.

Everything Hydrograf knows at one point of the map, for the mode „Identyfikuj”
of the interface: the coordinates in WGS84, PL-1992 and PL-2000, the terrain of
the DEM, the maximum water of the requested analysis results, the nearest BDOT10k
stream and the water body, land cover with its CN for the three AMC classes, soil
group, depression, sub-catchment, main channel and distance to the outlet of the
network at the point (``core/point_info.py``).

A point off the DEM is outside the area of the data: 404 ``no_data``. Inside it
the answer is partial, each source that has nothing at the point gives null.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from core.analysis_results import sample_water_levels
from core.config import get_settings
from core.constants import DEFAULT_THRESHOLD_M2
from core.database import get_db
from core.errors import (
    HydrografError,
    InternalError,
    NoDataError,
    StoreUnavailableError,
)
from core.point_info import (
    depression_at,
    land_cover_at,
    main_channel_at,
    nearest_stream,
    sample_raster,
    soil_group_at,
    subcatchment_at,
    water_body_at,
)
from models.schemas import (
    IdentifyPointRequest,
    IdentifyPointResponse,
    PointCoordinates,
    PointDepression,
    PointLandCover,
    PointPl2000,
    PointStream,
    PointSubcatchment,
    PointWater,
    PointWaterBody,
)
from utils.geometry import (
    PL2000_EPSG_BY_ZONE,
    transform_wgs84_to_pl1992,
    transform_wgs84_to_pl2000,
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/identify-point", response_model=IdentifyPointResponse)
def identify_point(
    request: Annotated[IdentifyPointRequest, Query()],
    db: Session = Depends(get_db),
) -> IdentifyPointResponse:
    """
    Read what Hydrograf knows at one point of the map.

    Parameters
    ----------
    request : IdentifyPointRequest
        Query parameters: the point (WGS84), the threshold of the sub-catchment
        network and the analysis results whose water is read (``result_ids``
        repeated, ``?result_ids=a&result_ids=b``)
    db : Session
        Database session (injected by FastAPI)

    Returns
    -------
    IdentifyPointResponse
        Coordinates, terrain elevation and slope, water of the results, stream,
        water body, land cover, soil group, depression, sub-catchment with its
        main channel; null where a source has nothing at the point

    Raises
    ------
    NoDataError
        ``no_data`` (404) when the point is off the DEM, outside the data
    StoreUnavailableError
        ``store_unavailable`` (503) when the DEM raster is missing
    InternalError
        ``internal_error`` (500) on an unexpected failure
    """
    try:
        settings = get_settings()
        point = transform_wgs84_to_pl1992(request.latitude, request.longitude)
        x, y = point.x, point.y

        dem_path = settings.resolve_dem_path()
        if dem_path is None:
            logger.error("No DEM raster found in %s", settings.dem_dir)
            raise StoreUnavailableError("dem_unavailable", reason="dem_unavailable")
        elevation = sample_raster(dem_path, x, y)
        if elevation is None:
            raise NoDataError("no_data_at_point", reason="outside_data_area")

        slope_path = settings.resolve_slope_path()
        slope = sample_raster(slope_path, x, y) if slope_path else None

        water = []
        for result_id, levels in sample_water_levels(
            settings.frontend_data_dir, request.result_ids, [(x, y)]
        ):
            level = levels[0]
            depth = None if level is None else round(level - elevation, 2)
            water.append(
                PointWater(
                    result_id=result_id,
                    water_level_m=None if level is None else round(level, 2),
                    depth_m=depth if depth is not None and depth > 0 else None,
                )
            )

        threshold = max(request.threshold_m2 or 0, DEFAULT_THRESHOLD_M2)
        stream = nearest_stream(db, x, y)
        water_body = water_body_at(
            settings.frontend_data_dir, request.longitude, request.latitude
        )
        soil_hsg = soil_group_at(db, x, y)
        land_cover = land_cover_at(db, x, y, soil_hsg)
        depression = depression_at(db, x, y)
        subcatchment = subcatchment_at(db, x, y, threshold)
        if subcatchment is not None:
            segment_idx = subcatchment["segment_idx"]
            subcatchment = {
                **subcatchment,
                **main_channel_at(db, threshold, segment_idx),
            }
        zone, easting_2000, northing_2000 = transform_wgs84_to_pl2000(
            request.latitude, request.longitude
        )

        return IdentifyPointResponse(
            coordinates=PointCoordinates(
                latitude=request.latitude,
                longitude=request.longitude,
                easting_m=round(x, 2),
                northing_m=round(y, 2),
                pl2000=PointPl2000(
                    zone=zone,
                    epsg=PL2000_EPSG_BY_ZONE[zone],
                    easting_m=round(easting_2000, 2),
                    northing_m=round(northing_2000, 2),
                ),
            ),
            elevation_m=round(elevation, 2),
            slope_percent=None if slope is None else round(slope, 1),
            water=water,
            stream=None if stream is None else PointStream(**stream),
            water_body=None if water_body is None else PointWaterBody(**water_body),
            land_cover=None if land_cover is None else PointLandCover(**land_cover),
            soil_hsg=soil_hsg,
            depression=None if depression is None else PointDepression(**depression),
            subcatchment=(
                None
                if subcatchment is None
                else PointSubcatchment(threshold_m2=threshold, **subcatchment)
            ),
        )

    except HydrografError:
        raise
    except Exception as e:
        logger.error("Error identifying point: %s", e, exc_info=True)
        raise InternalError("identify_failed", reason="identify_failed") from e
