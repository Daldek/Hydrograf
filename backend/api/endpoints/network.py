"""
Network delineation endpoints (ADR-080, ADR-081).

POST /api/delineate-network delineates the network of subcatchments, reaches and
nodes of a closing section and the control points above it
(``core.network_delineation``) and hands it to Hydrolog as one ``nogat-handoff/1``
(``core.handoff.build_network_handoff``). A network reads the saved rasters of the
closing section's whole catchment, so each worker delineates one network at a time: a
request waits for the one before it at most NETWORK_LOCK_WAIT_S, then gets 503 (D13).

POST /api/delineate-network/preview composes the same network on the catchment graph
while the person places the points (``core.network_preview``): the same ids, the areas
and the reach lengths of the full run, the outlines of the sub-catchment polygons. It
reads no window of the closing section's catchment and takes no lock.
"""

import logging
import threading
from typing import Any

from fastapi import APIRouter, Depends
from shapely.geometry import LineString, MultiPolygon, mapping
from sqlalchemy.orm import Session

from api.errors import problem_responses
from core import network_delineation, network_preview
from core.catchment_graph import loaded_catchment_graph
from core.constants import DEFAULT_THRESHOLD_M2, HYDROGRAPH_AREA_LIMIT_KM2, M_PER_KM
from core.database import get_db
from core.errors import HydrografError, InternalError, StoreUnavailableError
from core.handoff import build_network_handoff, flat_reach_lag_min
from core.network_tree import Junction
from models.schemas import (
    DelineateNetworkPreviewResponse,
    DelineateNetworkRequest,
    DelineateNetworkResponse,
    NetworkAreaCheck,
    NetworkJunctionInfo,
    NetworkNotice,
    NetworkPlace,
    NetworkPoint,
    NetworkPointInfo,
    NetworkPreviewPointInfo,
    NetworkPreviewReachInfo,
    NetworkPreviewSubcatchmentInfo,
    NetworkReachInfo,
    NetworkReachNotice,
    NetworkSubcatchmentInfo,
)
from utils.geometry import transform_geometry_pl1992_to_wgs84, transform_wgs84_to_pl1992

logger = logging.getLogger(__name__)
router = APIRouter()

# How long a request waits for the network another request of this worker delineates
# (D13) [s]
NETWORK_LOCK_WAIT_S = 15.0
_network_lock = threading.Lock()


@router.post(
    "/delineate-network",
    response_model=DelineateNetworkResponse,
    responses=problem_responses(422),
)
def delineate_network(
    request: DelineateNetworkRequest, db: Session = Depends(get_db)
) -> DelineateNetworkResponse:
    """Delineate the network of a closing section and the points above it.

    Every point, the closing section included, snaps to the nearest stream cell of
    `threshold_m2` within 100 m, and a point at most 50 m from a node of that network
    along the stream (a confluence of its streams) moves to the node. Every point is
    a node of the network, J at a confluence and P elsewhere: a point at a confluence
    receives every stream that joins there, a point elsewhere splits its river. The
    subcatchments (the rivers that enter a node with no reach, and the przyrzecze of
    each reach) are made of the 1 ha sub-catchments, split where a point lies inside
    one away from a node, and add up to the closing section's catchment; each gets the
    parameters of a delineated watershed, each reach the difference of the flow
    distances of its ends as its length and the NMT at its ends for its slope. One
    network at a time per worker: a request waits 15 s for the one before it.
    """
    if not _network_lock.acquire(timeout=NETWORK_LOCK_WAIT_S):
        raise StoreUnavailableError(
            "network_delineation_busy",
            reason="network_delineation_busy",
            wait_s=NETWORK_LOCK_WAIT_S,
        )
    try:
        cg = loaded_catchment_graph(db)
        if cg is None:
            raise StoreUnavailableError(
                "catchment_graph_unavailable", reason="catchment_graph_unavailable"
            )
        network = network_delineation.delineate_network(
            cg,
            db,
            _click(request.outlet),
            [_click(point) for point in request.points],
            request.threshold_m2,
        )
        names = {
            point.id: point.name
            for point in (request.outlet, *request.points)
            if point.name is not None
        }
        return _response(network, names, build_network_handoff(network, names))
    except HydrografError:
        raise
    except Exception as e:
        logger.error("Error delineating a network: %s", e, exc_info=True)
        raise InternalError(
            "network_delineation_failed", reason="network_delineation_failed"
        ) from e
    finally:
        _network_lock.release()


@router.post(
    "/delineate-network/preview", response_model=DelineateNetworkPreviewResponse
)
def delineate_network_preview(
    request: DelineateNetworkRequest, db: Session = Depends(get_db)
) -> DelineateNetworkPreviewResponse:
    """Compose the network of a closing section and its points, without measuring it.

    The points snap and move to the nodes, and the tree is built, as for
    `POST /api/delineate-network`, so the ids of the nodes, subcatchments and reaches,
    the places of the points and the errors of the composition are the same; each
    subcatchment gets its area (exact to the cell) and an outline from the 1 ha
    sub-catchments (approximate where a point away from a node splits one: the
    characteristics split it by the raster), each reach the difference of the flow
    distances of its ends. No window of the closing section's catchment is read and
    no lock taken: a fraction of a second for any network of the data.
    """
    try:
        cg = loaded_catchment_graph(db)
        if cg is None:
            raise StoreUnavailableError(
                "catchment_graph_unavailable", reason="catchment_graph_unavailable"
            )
        preview = network_preview.preview_network(
            cg,
            db,
            _click(request.outlet),
            [_click(point) for point in request.points],
            request.threshold_m2,
        )
    except HydrografError:
        raise
    except Exception as e:
        logger.error("Error previewing a network: %s", e, exc_info=True)
        raise InternalError(
            "network_preview_failed", reason="network_preview_failed"
        ) from e
    names = {
        point.id: point.name
        for point in (request.outlet, *request.points)
        if point.name is not None
    }
    return _preview_response(preview, names)


def _click(point: NetworkPoint) -> network_delineation.Click:
    """Return a point of the request in EPSG:2180."""
    place = transform_wgs84_to_pl1992(point.latitude, point.longitude)
    return network_delineation.Click(point.id, place.x, place.y)


def _response(
    network: network_delineation.Network,
    names: dict[str, str],
    handoff: dict[str, Any],
) -> DelineateNetworkResponse:
    """Build the response of a delineated network."""
    boundary = transform_geometry_pl1992_to_wgs84(network.boundary_2180)
    if boundary.geom_type == "Polygon":
        boundary = MultiPolygon([boundary])
    over_limit = [
        e.subcatchment.id
        for e in network.subcatchments
        if not e.watershed.hydrograph_available
    ]
    notices = (
        [NetworkNotice(code="over_scs_cn_limit", ids=over_limit)] if over_limit else []
    )
    notices += _reach_notices(network.reach_notices)
    return DelineateNetworkResponse(
        threshold_m2=network.threshold_m2,
        unit_threshold_m2=DEFAULT_THRESHOLD_M2,
        area_km2=network.area_km2,
        area_check=NetworkAreaCheck(
            watershed_km2=network.area_km2, elements_km2=network.elements_km2
        ),
        boundary_geojson={
            "type": "Feature",
            "geometry": mapping(boundary),
            "properties": {"area_km2": network.area_km2},
        },
        points=[
            NetworkPointInfo(
                id=point.point_id,
                name=names.get(point.point_id),
                latitude=point.latitude,
                longitude=point.longitude,
                snap_distance_m=point.snap_distance_m,
                at_node=point.at_node,
                node=point.node,
            )
            for point in network.points
        ],
        subcatchments=[
            NetworkSubcatchmentInfo(
                id=item.subcatchment.id,
                kind=item.subcatchment.kind,
                to=item.subcatchment.to,
                point=item.subcatchment.point,
                reach=item.subcatchment.reach,
                watershed=item.watershed,
            )
            for item in network.subcatchments
        ],
        reaches=[
            NetworkReachInfo(
                id=item.reach.id,
                from_node=item.reach.from_node,
                to=item.reach.to,
                length_km=item.length_km,
                slope_m_per_m=item.slope_m_per_m,
                slope_method=item.slope_method,
                upstream_elevation_m=item.upstream_elevation_m,
                downstream_elevation_m=item.downstream_elevation_m,
                vector_length_km=item.vector_length_km,
                geojson={
                    "type": "Feature",
                    "geometry": mapping(
                        transform_geometry_pl1992_to_wgs84(LineString(item.line_2180))
                    ),
                    "properties": {"id": item.reach.id},
                },
            )
            for item in network.reaches
        ],
        junctions=[
            _junction_info(item.junction, item.latitude, item.longitude, names)
            for item in network.junctions
        ],
        notices=notices,
        handoff=handoff,
    )


def _preview_response(
    preview: network_preview.NetworkPreview, names: dict[str, str]
) -> DelineateNetworkPreviewResponse:
    """Build the response of a previewed network."""
    over_limit = [
        item.subcatchment.id
        for item in preview.subcatchments
        if item.area_km2 > HYDROGRAPH_AREA_LIMIT_KM2
    ]
    return DelineateNetworkPreviewResponse(
        threshold_m2=preview.threshold_m2,
        unit_threshold_m2=DEFAULT_THRESHOLD_M2,
        area_km2=preview.area_km2,
        points=[
            NetworkPreviewPointInfo(
                id=item.point.point_id,
                name=names.get(item.point.point_id),
                latitude=item.point.latitude,
                longitude=item.point.longitude,
                snap_distance_m=item.point.snap_distance_m,
                at_node=item.point.at_node,
                node=item.point.node,
                inside_unit=item.inside_unit,
            )
            for item in preview.points
        ],
        subcatchments=[
            NetworkPreviewSubcatchmentInfo(
                id=item.subcatchment.id,
                kind=item.subcatchment.kind,
                to=item.subcatchment.to,
                point=item.subcatchment.point,
                reach=item.subcatchment.reach,
                area_km2=item.area_km2,
                outline_approximate=item.outline_approximate,
                boundary_geojson=None
                if item.boundary_2180 is None
                else {
                    "type": "Feature",
                    "geometry": mapping(
                        transform_geometry_pl1992_to_wgs84(item.boundary_2180)
                    ),
                    "properties": {"id": item.subcatchment.id},
                },
            )
            for item in preview.subcatchments
        ],
        reaches=[
            NetworkPreviewReachInfo(
                id=item.reach.id,
                from_node=item.reach.from_node,
                to=item.reach.to,
                length_km=item.length_km,
                geojson=None
                if item.line_2180 is None
                else {
                    "type": "Feature",
                    "geometry": mapping(
                        transform_geometry_pl1992_to_wgs84(item.line_2180)
                    ),
                    "properties": {"id": item.reach.id},
                },
            )
            for item in preview.reaches
        ],
        junctions=[
            _junction_info(item.junction, item.latitude, item.longitude, names)
            for item in preview.junctions
        ],
        notices=(
            [NetworkNotice(code="over_scs_cn_limit", ids=over_limit)]
            if over_limit
            else []
        )
        + _reach_notices(preview.reach_notices),
    )


def _junction_info(
    junction: Junction, latitude: float, longitude: float, names: dict[str, str]
) -> NetworkJunctionInfo:
    """Describe a node of a network, with the name of its point."""
    return NetworkJunctionInfo(
        id=junction.id,
        kind=junction.kind,
        point=junction.point,
        name=names.get(junction.point) if junction.point is not None else None,
        latitude=latitude,
        longitude=longitude,
        inflows=list(junction.inflows),
    )


def _reach_notices(
    items: tuple[network_delineation.ReachNotice, ...],
) -> list[NetworkNotice]:
    """One notice per reach shorter than 200 m or of the minimum slope (D10a)."""
    return [
        NetworkNotice(
            code="reach_short_or_flat",
            ids=[item.reach],
            reach=NetworkReachNotice(
                length_m=item.length_m,
                slope_minimum=item.slope_minimum,
                upper_point=item.upper_point,
                lower=item.lower,
                move_to=None
                if item.move_to is None
                else NetworkPlace(latitude=item.move_to[0], longitude=item.move_to[1]),
                lag_min=flat_reach_lag_min(item.length_m / M_PER_KM)
                if item.slope_minimum
                else None,
            ),
        )
        for item in items
    ]
