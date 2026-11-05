"""
What Hydrograf knows at one point of the map (``GET /api/identify-point``).

Every function takes the point in PL-1992 (EPSG:2180) and answers None where its
source has nothing there. The terrain comes from the rasters of the preprocessing
(the DEM and its slope), the land cover with its CN, the hydrologic soil group, the
depressions, the BDOT10k streams and the precomputed sub-catchments from PostGIS;
the main channel at the sub-catchment's segment and the distance to the outlet of
the network from the in-memory ``CatchmentGraph``. The CN of the land cover is the
AMC II value of the catchment CN, converted to AMC I and III by Hydrolog as for
the hydrograph.

The BDOT10k water bodies (``OT_PTWP_A``: lakes, ponds and wide rivers drawn as
polygons) are not in the database: the bootstrap writes them only to
``<frontend_data_dir>/bdot_lakes.geojson`` (WGS84), the file the map draws. That
file is read here, indexed once and kept in memory until it changes.
"""

import json
import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import rasterio
from hydrolog.runoff import AMC, SCSCN
from shapely import STRtree, make_valid
from shapely.errors import ShapelyError
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.catchment_graph import CatchmentGraph

logger = logging.getLogger(__name__)

# Farthest stream reported as the nearest one: beyond a few kilometres a stream
# says nothing about the point, and near the edge of the data, where the BDOT10k
# layer is cut, the true nearest stream may lie outside it. In the data area
# (790 km², 1550 km of BDOT10k streams) a 250 m grid of 12 652 points found a
# stream within 163 m at the median, 1.0 km at the 99th percentile and 2.07 km
# at most (2026-11-05), so 5 km leaves room for sparser areas. The search walks
# the GiST index nearest first and stops at the first line, whatever the limit.
STREAM_SEARCH_MAX_DISTANCE_M = 5000.0
# The water bodies of the map, relative to the directory served under /data/
WATER_BODIES_FILE = "bdot_lakes.geojson"


def sample_raster(path: str, x: float, y: float) -> float | None:
    """Value of the first band of a raster in EPSG:2180 at a point.

    Parameters
    ----------
    path : str
        Raster file (GeoTIFF or VRT) in EPSG:2180
    x, y : float
        Point in EPSG:2180

    Returns
    -------
    float | None
        The value, or None off the raster, on nodata or on a non-finite value
    """
    with rasterio.open(path) as dataset:
        left, bottom, right, top = dataset.bounds
        if not (left <= x < right and bottom < y <= top):
            return None
        value = float(next(dataset.sample([(x, y)]))[0])
        nodata = dataset.nodata
    if not math.isfinite(value):
        return None
    if nodata is not None and math.isclose(value, float(nodata), rel_tol=1e-6):
        return None
    return value


def land_cover_at(db: Session, x: float, y: float) -> dict[str, Any] | None:
    """Land cover polygon containing the point (the smallest where they overlap).

    The CN of the category is the AMC II value the catchment CN averages
    (``core/land_cover.py``), independent of the soil group; Hydrolog converts it
    to AMC I and III with the conversion the hydrograph uses.

    Returns
    -------
    dict | None
        ``category``, ``cn`` (AMC II), ``cn_amc_i`` and ``cn_amc_iii``,
        ``imperviousness`` (0–1 or None) and ``bdot_class`` (BDOT10k layer code
        or None)
    """
    row = db.execute(
        text("""
            SELECT category, cn_value, imperviousness, bdot_class
            FROM land_cover
            WHERE ST_Contains(geom, ST_SetSRID(ST_Point(:x, :y), 2180))
            ORDER BY ST_Area(geom)
            LIMIT 1
        """),
        {"x": x, "y": y},
    ).fetchone()
    if row is None:
        return None
    cn = int(row.cn_value)
    scs = SCSCN(cn=cn)
    return {
        "category": row.category,
        "cn": cn,
        "cn_amc_i": scs.adjust_cn_for_amc(AMC.I),
        "cn_amc_iii": scs.adjust_cn_for_amc(AMC.III),
        "imperviousness": row.imperviousness,
        "bdot_class": row.bdot_class,
    }


def soil_group_at(db: Session, x: float, y: float) -> str | None:
    """Hydrologic soil group (A, B, C or D) of the polygon containing the point."""
    row = db.execute(
        text("""
            SELECT hsg_group
            FROM soil_hsg
            WHERE ST_Contains(geom, ST_SetSRID(ST_Point(:x, :y), 2180))
            LIMIT 1
        """),
        {"x": x, "y": y},
    ).fetchone()
    return None if row is None else str(row.hsg_group)


def depression_at(db: Session, x: float, y: float) -> dict[str, Any] | None:
    """Terrain depression (blue spot) containing the point, the smallest if nested.

    Returns
    -------
    dict | None
        ``max_depth_m``, ``mean_depth_m`` (or None), ``area_m2``, ``volume_m3``
    """
    row = db.execute(
        text("""
            SELECT max_depth_m, mean_depth_m, area_m2, volume_m3
            FROM depressions
            WHERE ST_Contains(geom, ST_SetSRID(ST_Point(:x, :y), 2180))
            ORDER BY area_m2
            LIMIT 1
        """),
        {"x": x, "y": y},
    ).fetchone()
    if row is None:
        return None
    return {
        "max_depth_m": row.max_depth_m,
        "mean_depth_m": row.mean_depth_m,
        "area_m2": row.area_m2,
        "volume_m3": row.volume_m3,
    }


def nearest_stream(
    db: Session,
    x: float,
    y: float,
    max_distance_m: float = STREAM_SEARCH_MAX_DISTANCE_M,
) -> dict[str, Any] | None:
    """Nearest BDOT10k stream line to the point, at most ``max_distance_m`` away.

    A nearest-neighbour (KNN, ``<->``) search over the GiST index of the lines.

    Returns
    -------
    dict | None
        ``name`` (or None), ``layer_type`` (SWRS river, SWKN canal, SWRM ditch)
        and ``distance_m``; None when no stream is within ``max_distance_m``
    """
    row = db.execute(
        text("""
            SELECT name, layer_type,
                   ST_Distance(geom, ST_SetSRID(ST_Point(:x, :y), 2180)) AS distance_m
            FROM bdot_streams
            WHERE ST_DWithin(geom, ST_SetSRID(ST_Point(:x, :y), 2180), :max_distance)
            ORDER BY geom <-> ST_SetSRID(ST_Point(:x, :y), 2180)
            LIMIT 1
        """),
        {"x": x, "y": y, "max_distance": max_distance_m},
    ).fetchone()
    if row is None:
        return None
    return {
        "name": row.name or None,
        "layer_type": row.layer_type,
        "distance_m": round(float(row.distance_m), 1),
    }


def subcatchment_at(
    db: Session, x: float, y: float, threshold_m2: int
) -> dict[str, Any] | None:
    """Precomputed sub-catchment containing the point and the segment it drains.

    Parameters
    ----------
    threshold_m2 : int
        Flow accumulation threshold of the network (stream_catchments)

    Returns
    -------
    dict | None
        ``segment_idx``, ``area_km2`` (the sub-catchment), ``upstream_area_km2``
        (the whole catchment at the segment's downstream end, as a precomputed
        delineation from this sub-catchment), ``strahler_order``,
        ``segment_length_m`` and ``is_real_stream`` (segment matched to BDOT10k);
        the segment values are None without a stream_network row
    """
    row = db.execute(
        text("""
            SELECT sc.segment_idx, sc.area_km2,
                   COALESCE(sn.strahler_order, sc.strahler_order) AS strahler_order,
                   sn.upstream_area_km2,
                   ST_Length(sn.geom) AS segment_length_m,
                   sn.is_real_stream
            FROM stream_catchments sc
            LEFT JOIN stream_network sn
              ON sn.threshold_m2 = sc.threshold_m2
             AND sn.segment_idx = sc.segment_idx
            WHERE sc.threshold_m2 = :threshold
              AND ST_Contains(sc.geom, ST_SetSRID(ST_Point(:x, :y), 2180))
            LIMIT 1
        """),
        {"x": x, "y": y, "threshold": threshold_m2},
    ).fetchone()
    if row is None:
        return None
    return {
        "segment_idx": int(row.segment_idx),
        "area_km2": float(row.area_km2),
        "upstream_area_km2": row.upstream_area_km2,
        "strahler_order": row.strahler_order,
        "segment_length_m": row.segment_length_m,
        "is_real_stream": row.is_real_stream,
    }


def main_channel_at(
    cg: CatchmentGraph, db: Session, threshold_m2: int, segment_idx: int
) -> dict[str, float | None]:
    """Read the main channel at a segment's end and the distance to the outlet.

    Both come from the in-memory graph. The main channel is traced up from the
    segment's sub-catchment as for a watershed delineated there (its
    ``channel_length_km``). The distance to the outlet is the difference of the
    D8 flow distances at the outlet points of the sub-catchment and of the last
    node below it: the outlet of the network, where the water leaves the data
    area, which need not be the mouth of the river. The flow distances run on
    from there to where the D8 flow leaves the DEM, hence the difference. Tracing
    up from the outlet of the 790 km² network at 10 000 m² takes about 20 ms.

    Parameters
    ----------
    cg : CatchmentGraph
        The graph (``get_catchment_graph()``); loaded here if it is not yet
    db : Session
        Database session the graph is loaded from
    threshold_m2, segment_idx : int
        Network and segment of the sub-catchment (``subcatchment_at``)

    Returns
    -------
    dict
        ``channel_length_km`` and ``distance_to_outlet_km``, None when the graph
        cannot be loaded or lacks the segment (and the distance without the flow
        distances)
    """
    if not cg.ensure_loaded(db):
        return {"channel_length_km": None, "distance_to_outlet_km": None}
    idx = cg.lookup_by_segment_idx(threshold_m2, segment_idx)
    if idx is None:
        return {"channel_length_km": None, "distance_to_outlet_km": None}
    main = cg.trace_main_channel(idx, cg.traverse_upstream(idx))
    outlet = int(cg.trace_downstream(idx)[-1])
    distance_m = cg.get_outlet_flow_dist_m(idx) - cg.get_outlet_flow_dist_m(outlet)
    return {
        "channel_length_km": main["main_channel_length_km"],
        "distance_to_outlet_km": (
            round(distance_m / 1000, 3) if math.isfinite(distance_m) else None
        ),
    }


@dataclass(frozen=True)
class _WaterBodies:
    """Polygons of the water bodies file (WGS84) with an index and attributes."""

    tree: STRtree
    geometries: list[BaseGeometry]
    attributes: list[dict[str, str | None]]


def _attribute(properties: dict[str, Any], name: str) -> str | None:
    """BDOT10k attribute as text, whichever the case of its key; None if empty."""
    value = properties.get(name.upper(), properties.get(name.lower()))
    if value is None:
        return None
    return str(value).strip() or None


@lru_cache(maxsize=1)
def _load_water_bodies(path: str, mtime_ns: int) -> _WaterBodies:
    """Read and index the water bodies file; cached per path and modification."""
    collection = json.loads(Path(path).read_text("utf-8"))
    geometries: list[BaseGeometry] = []
    attributes: list[dict[str, str | None]] = []
    for feature in collection.get("features", []):
        if not isinstance(feature, dict) or not feature.get("geometry"):
            continue
        geometry = shape(feature["geometry"])
        if geometry.is_empty:
            continue
        if not geometry.is_valid:
            geometry = make_valid(geometry)
        properties = feature.get("properties") or {}
        geometries.append(geometry)
        attributes.append(
            {
                "name": _attribute(properties, "NAZWA"),
                "kind": _attribute(properties, "RODZAJ"),
            }
        )
    logger.info("Water bodies indexed: %d polygons from %s", len(geometries), path)
    return _WaterBodies(STRtree(geometries), geometries, attributes)


def water_body_at(
    frontend_data_dir: str, longitude: float, latitude: float
) -> dict[str, str | None] | None:
    """BDOT10k water body (lake, pond, river polygon) containing a WGS84 point.

    Parameters
    ----------
    frontend_data_dir : str
        Directory served under ``/data/`` (holds ``bdot_lakes.geojson``)
    longitude, latitude : float
        Point in WGS84

    Returns
    -------
    dict | None
        ``name`` (BDOT10k NAZWA, often None) and ``kind`` (RODZAJ, e.g. „woda
        stojąca”) of the smallest polygon containing the point; None outside every
        polygon or without a readable file
    """
    path = Path(frontend_data_dir) / WATER_BODIES_FILE
    try:
        bodies = _load_water_bodies(str(path), path.stat().st_mtime_ns)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, AttributeError, ShapelyError) as e:
        logger.warning("Water bodies %s not readable: %s", path, e)
        return None
    hits = bodies.tree.query(Point(longitude, latitude), predicate="intersects")
    if len(hits) == 0:
        return None
    best = min((int(i) for i in hits), key=lambda i: bodies.geometries[i].area)
    return bodies.attributes[best]
