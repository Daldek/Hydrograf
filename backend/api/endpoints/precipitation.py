"""
The command ``precipitation depth``: a catchment's design depth (ADR-069, ADR-091).

The design depth of a catchment for a PMAXTP duration and probability is the mean of
the depths of the local PMAXTP grid over the catchment, each grid point weighted by
the area of its Thiessen polygon inside the boundary (``core.precipitation``): the
depth ``hydrograph generate`` takes for the same watershed and scenario, so that a
hydrograph made from it elsewhere (Hydrolog's ``hydrograph generate`` with
``total_mm``) equals Hydrograf's own. No areal reduction factor is applied: Hydrograf
never estimates one (ADR-069).
"""

import logging
from typing import Any

import shapely
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy.orm import Session

from api.endpoints.hydrograph import pmaxtp_points
from api.envelope import Outcome
from core.attribution import PMAXTP
from core.errors import (
    HydrografError,
    InternalError,
    InvalidRequestError,
    NoDataError,
    UnsupportedError,
)
from core.precipitation import UnknownGridPointError, areal_depth, thiessen_cells
from models.schemas import DesignDepthRequest, DesignDepthResponse
from utils.geometry import transform_geometry_wgs84_to_pl1992

logger = logging.getLogger(__name__)

# The largest boundary weighed: a catchment, not a region; about 2500 points of the
# default 2 km grid [km2]
DESIGN_DEPTH_MAX_AREA_KM2 = 10_000.0


def _boundary(geojson: dict[str, Any]) -> BaseGeometry:
    """Return the boundary of the request as a valid polygon in EPSG:2180.

    Parameters
    ----------
    geojson : dict[str, Any]
        A GeoJSON Polygon or MultiPolygon, or a Feature of one, in WGS84.

    Returns
    -------
    BaseGeometry
        The Polygon or MultiPolygon in EPSG:2180.

    Raises
    ------
    InvalidRequestError
        ``validation_error`` (400, ``boundary_invalid``) for another geometry, an
        empty or invalid one, or coordinates outside WGS84.
    """

    def invalid(cause: str) -> InvalidRequestError:
        return InvalidRequestError(
            "boundary_invalid",
            reason="boundary_invalid",
            option="boundary",
            cause=cause,
        )

    geometry = geojson.get("geometry") if geojson.get("type") == "Feature" else geojson
    if not isinstance(geometry, dict):
        raise invalid("no geometry")
    try:
        polygon = shape(geometry)
    except (AttributeError, KeyError, TypeError, ValueError, IndexError) as e:
        raise invalid(str(e) or type(e).__name__) from e
    except shapely.errors.ShapelyError as e:
        # GEOS's own failures and an unknown geometry type
        raise invalid(str(e)) from e
    if not isinstance(polygon, Polygon | MultiPolygon):
        raise invalid(f"a {polygon.geom_type}, not a polygon")
    if polygon.is_empty or not polygon.is_valid:
        raise invalid(shapely.is_valid_reason(polygon))
    west, south, east, north = polygon.bounds
    if west < -180 or east > 180 or south < -90 or north > 90:
        raise invalid("coordinates outside WGS84 longitude and latitude")
    return transform_geometry_wgs84_to_pl1992(polygon)


def design_depth(request: DesignDepthRequest, db: Session) -> Outcome:
    """Compute a catchment's PMAXTP design depth: ``precipitation depth``.

    Parameters
    ----------
    request : DesignDepthRequest
        The boundary (WGS84), the duration [min] and the probability [%].
    db : Session
        Database session.

    Returns
    -------
    Outcome
        ``DesignDepthResponse``: the unrounded Thiessen mean, the grid points with
        their depths and weights, the area of the boundary and PMAXTP's lines.

    Raises
    ------
    InvalidRequestError
        ``validation_error`` (400, ``boundary_invalid``) for a boundary that is no
        valid polygon.
    UnsupportedError
        ``unsupported`` (422, ``boundary_too_large``) above
        ``DESIGN_DEPTH_MAX_AREA_KM2``.
    NoDataError
        ``no_data`` (404, ``no_design_depth_data``) when the grid has no data of
        the scenario around the boundary.
    InternalError
        ``internal_error`` (500) on an unexpected failure.
    """
    boundary = _boundary(request.boundary)
    area_km2 = boundary.area / 1e6
    if area_km2 > DESIGN_DEPTH_MAX_AREA_KM2:
        raise UnsupportedError(
            "boundary_too_large",
            reason="boundary_too_large",
            area_km2=area_km2,
            limit_km2=DESIGN_DEPTH_MAX_AREA_KM2,
        )
    no_data = NoDataError(
        "no_design_depth_data",
        reason="no_design_depth_data",
        duration_min=request.duration_min,
        probability_percent=request.probability_percent,
    )
    try:
        depth = areal_depth(
            thiessen_cells(boundary, db),
            request.duration_min,
            request.probability_percent,
            db,
        )
    except UnknownGridPointError as e:
        # The cells came from the table: the scenario has no data there
        raise no_data from e
    except HydrografError:
        raise
    except Exception as e:
        logger.error("Error computing a design depth: %s", e, exc_info=True)
        raise InternalError("design_depth_failed", reason="design_depth_failed") from e
    if depth is None:
        raise no_data
    return Outcome(
        DesignDepthResponse(
            pmaxtp_depth_mm=depth.precipitation_mm,
            duration_min=request.duration_min,
            probability_percent=request.probability_percent,
            interpolation="thiessen",
            area_km2=round(area_km2, 4),
            pmaxtp_points=pmaxtp_points(depth),
            attribution=list(PMAXTP.attribution),
            terms_notice=list(PMAXTP.terms_notice),
        )
    )
