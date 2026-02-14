"""
Shared watershed delineation service using CatchmentGraph.

Provides reusable functions for stream lookup, boundary merging,
outlet extraction, and morphometric dict construction. Used by
watershed, hydrograph, and select_stream endpoints.

All spatial queries target stream_network / stream_catchments tables
(~87k rows each) instead of flow_network (19.7M rows), eliminating
runtime dependency on the large table.
"""

import json
import logging
import math

import numpy as np
from shapely import wkb
from shapely.geometry import MultiPolygon, Polygon
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.catchment_graph import CatchmentGraph

logger = logging.getLogger(__name__)


def find_nearest_stream_segment(
    x: float,
    y: float,
    threshold_m2: int,
    db: Session,
) -> dict | None:
    """
    Find the nearest stream_network segment to a point.

    Parameters
    ----------
    x, y : float
        Point coordinates in EPSG:2180 (PL-1992)
    threshold_m2 : int
        Flow accumulation threshold
    db : Session
        Database session

    Returns
    -------
    dict | None
        Segment info with keys: segment_idx, strahler_order, length_m,
        upstream_area_km2, downstream_x, downstream_y.
        None if no segment found within 1000m.
    """
    query = text("""
        SELECT
            id,
            strahler_order,
            ST_Length(geom) as length_m,
            upstream_area_km2,
            ST_X(ST_EndPoint(geom)) as downstream_x,
            ST_Y(ST_EndPoint(geom)) as downstream_y
        FROM stream_network
        WHERE threshold_m2 = :threshold
          AND ST_DWithin(geom, ST_SetSRID(ST_Point(:x, :y), 2180), 1000)
        ORDER BY ST_Distance(geom, ST_SetSRID(ST_Point(:x, :y), 2180))
        LIMIT 1
    """)
    result = db.execute(
        query,
        {"x": x, "y": y, "threshold": threshold_m2},
    ).fetchone()
    if result is None:
        return None
    return {
        "segment_idx": result.id,
        "strahler_order": result.strahler_order,
        "length_m": result.length_m,
        "upstream_area_km2": result.upstream_area_km2,
        "downstream_x": result.downstream_x,
        "downstream_y": result.downstream_y,
    }


def merge_catchment_boundaries(
    segment_idxs: list[int],
    threshold_m2: int,
    db: Session,
) -> MultiPolygon | None:
    """
    Merge sub-catchment polygons via ST_Union in PostGIS.

    Parameters
    ----------
    segment_idxs : list[int]
        Segment indices to merge
    threshold_m2 : int
        Flow accumulation threshold
    db : Session
        Database session

    Returns
    -------
    MultiPolygon | None
        Merged boundary or None if no geometries found
    """
    if not segment_idxs:
        return None

    query = text("""
        SELECT ST_AsBinary(
            ST_Multi(ST_Union(geom))
        ) as geom
        FROM stream_catchments
        WHERE threshold_m2 = :threshold
          AND segment_idx = ANY(:idxs)
    """)
    result = db.execute(
        query,
        {"threshold": threshold_m2, "idxs": segment_idxs},
    ).fetchone()

    if result is None or result.geom is None:
        return None

    return wkb.loads(bytes(result.geom))


def get_segment_outlet(
    segment_idx: int,
    threshold_m2: int,
    db: Session,
) -> dict | None:
    """
    Get outlet point (downstream endpoint) of a stream segment.

    Parameters
    ----------
    segment_idx : int
        Stream segment ID
    threshold_m2 : int
        Flow accumulation threshold
    db : Session
        Database session

    Returns
    -------
    dict | None
        {"x": float, "y": float} or None
    """
    query = text("""
        SELECT
            ST_X(ST_EndPoint(geom)) as x,
            ST_Y(ST_EndPoint(geom)) as y
        FROM stream_network
        WHERE id = :seg_idx
          AND threshold_m2 = :threshold
        LIMIT 1
    """)
    result = db.execute(
        query,
        {"seg_idx": segment_idx, "threshold": threshold_m2},
    ).fetchone()
    if result is None:
        return None
    return {"x": result.x, "y": result.y}


def compute_watershed_length(
    boundary,
    outlet_x: float,
    outlet_y: float,
) -> float:
    """
    Estimate watershed length as max distance from outlet to boundary.

    Parameters
    ----------
    boundary : Polygon | MultiPolygon
        Watershed boundary in EPSG:2180
    outlet_x, outlet_y : float
        Outlet coordinates in EPSG:2180

    Returns
    -------
    float
        Watershed length in km
    """
    if hasattr(boundary, "geoms"):
        coords = []
        for poly in boundary.geoms:
            coords.extend(poly.exterior.coords)
    else:
        coords = list(boundary.exterior.coords)

    if not coords:
        return 0.0

    max_dist = max(
        math.sqrt((x - outlet_x) ** 2 + (y - outlet_y) ** 2) for x, y in coords
    )
    return max_dist / 1000  # m -> km


def get_main_stream_geojson(
    segment_idx: int,
    threshold_m2: int,
    db: Session,
) -> dict | None:
    """
    Get the main stream line as WGS84 GeoJSON from stream_network.

    Parameters
    ----------
    segment_idx : int
        Stream segment ID
    threshold_m2 : int
        Flow accumulation threshold
    db : Session
        Database session

    Returns
    -------
    dict | None
        GeoJSON geometry dict or None
    """
    query = text("""
        SELECT ST_AsGeoJSON(
            ST_Transform(geom, 4326)
        ) as geojson
        FROM stream_network
        WHERE id = :seg_idx
          AND threshold_m2 = :threshold
        LIMIT 1
    """)
    result = db.execute(
        query,
        {"seg_idx": segment_idx, "threshold": threshold_m2},
    ).fetchone()
    if result is None or result.geojson is None:
        return None

    return json.loads(result.geojson)


def get_main_stream_coords_2180(
    segment_idx: int,
    threshold_m2: int,
    db: Session,
) -> list[tuple[float, float]] | None:
    """
    Get main stream coordinates in PL-1992 (EPSG:2180).

    Parameters
    ----------
    segment_idx : int
        Stream segment ID
    threshold_m2 : int
        Flow accumulation threshold
    db : Session
        Database session

    Returns
    -------
    list[tuple[float, float]] | None
        List of (x, y) tuples in EPSG:2180, or None
    """
    query = text("""
        SELECT ST_AsText(geom) as wkt
        FROM stream_network
        WHERE id = :seg_idx
          AND threshold_m2 = :threshold
        LIMIT 1
    """)
    result = db.execute(
        query,
        {"seg_idx": segment_idx, "threshold": threshold_m2},
    ).fetchone()
    if result is None or result.wkt is None:
        return None

    from shapely import wkt as shapely_wkt

    line = shapely_wkt.loads(result.wkt)
    return list(line.coords)


def boundary_to_polygon(boundary_2180: MultiPolygon | Polygon) -> Polygon:
    """
    Extract largest Polygon from a MultiPolygon or pass through Polygon.

    Parameters
    ----------
    boundary_2180 : MultiPolygon | Polygon
        Input boundary geometry

    Returns
    -------
    Polygon
        Largest polygon component
    """
    if hasattr(boundary_2180, "geoms"):
        polys = list(boundary_2180.geoms)
        if len(polys) == 1:
            return polys[0]
        return max(polys, key=lambda p: p.area)
    return boundary_2180


def build_morph_dict_from_graph(
    cg: CatchmentGraph,
    upstream_indices: np.ndarray,
    boundary_2180: MultiPolygon | Polygon,
    outlet_x: float,
    outlet_y: float,
    segment_idx: int,
    threshold_m2: int,
    cn: int | None = None,
) -> dict:
    """
    Build morphometric parameter dict compatible with Hydrolog's
    WatershedParameters.from_dict() and MorphometricParameters schema.

    Uses pre-computed stats from CatchmentGraph (zero raster operations).

    Parameters
    ----------
    cg : CatchmentGraph
        Loaded catchment graph
    upstream_indices : np.ndarray
        Internal indices from cg.traverse_upstream()
    boundary_2180 : MultiPolygon | Polygon
        Merged boundary in EPSG:2180
    outlet_x, outlet_y : float
        Outlet point in EPSG:2180
    segment_idx : int
        Outlet stream segment ID
    threshold_m2 : int
        Flow accumulation threshold
    cn : int | None
        SCS Curve Number (optional)

    Returns
    -------
    dict
        Dictionary with all morphometric parameters
    """
    stats = cg.aggregate_stats(upstream_indices)
    area_km2 = stats["area_km2"]

    perimeter_km = round(boundary_2180.length / 1000, 4)
    length_km = round(
        compute_watershed_length(boundary_2180, outlet_x, outlet_y),
        4,
    )

    elev_min = stats.get("elevation_min_m")
    elev_max = stats.get("elevation_max_m")

    # Channel length and slope from aggregated stream stats
    channel_length_km = stats.get("stream_length_km")
    channel_slope = None
    if (
        channel_length_km
        and channel_length_km > 0
        and elev_min is not None
        and elev_max is not None
    ):
        channel_slope = round(
            (elev_max - elev_min) / (channel_length_km * 1000),
            6,
        )

    # Shape indices
    shape_indices = _compute_shape_indices(area_km2, perimeter_km, length_km)

    # Relief indices
    relief_ratio = None
    if elev_min is not None and elev_max is not None and length_km > 0:
        relief_m = elev_max - elev_min
        relief_ratio = round(relief_m / (length_km * 1000), 6)

    hypsometric_integral = None
    elev_mean = stats.get("elevation_mean_m")
    if (
        elev_min is not None
        and elev_max is not None
        and elev_mean is not None
        and (elev_max - elev_min) > 0
    ):
        hypsometric_integral = round((elev_mean - elev_min) / (elev_max - elev_min), 4)

    # Ruggedness number
    dd = stats.get("drainage_density_km_per_km2")
    ruggedness = None
    if elev_min is not None and elev_max is not None and dd is not None:
        relief_km = (elev_max - elev_min) / 1000
        ruggedness = round(dd * relief_km, 4)

    params = {
        "area_km2": round(area_km2, 2),
        "perimeter_km": perimeter_km,
        "length_km": length_km,
        "elevation_min_m": elev_min if elev_min is not None else 0.0,
        "elevation_max_m": elev_max if elev_max is not None else 0.0,
        "elevation_mean_m": elev_mean,
        "mean_slope_m_per_m": stats.get("mean_slope_m_per_m"),
        "channel_length_km": channel_length_km if channel_length_km else None,
        "channel_slope_m_per_m": channel_slope,
        "cn": cn,
        "source": "Hydrograf",
        "crs": "EPSG:2180",
        # Shape indices
        "compactness_coefficient": shape_indices.get("compactness_coefficient"),
        "circularity_ratio": shape_indices.get("circularity_ratio"),
        "elongation_ratio": shape_indices.get("elongation_ratio"),
        "form_factor": shape_indices.get("form_factor"),
        "mean_width_km": shape_indices.get("mean_width_km"),
        # Relief indices
        "relief_ratio": relief_ratio,
        "hypsometric_integral": hypsometric_integral,
        # Drainage indices
        "drainage_density_km_per_km2": dd,
        "stream_frequency_per_km2": stats.get("stream_frequency_per_km2"),
        "ruggedness_number": ruggedness,
        "max_strahler_order": stats.get("max_strahler_order"),
    }

    logger.info(
        f"Built morph dict from graph: area={area_km2:.2f} km2, "
        f"length={length_km:.2f} km"
    )

    return params


def _compute_shape_indices(
    area_km2: float,
    perimeter_km: float,
    length_km: float,
) -> dict:
    """Compute watershed shape indices (Kc, Rc, Re, Ff, W)."""
    if area_km2 <= 0 or perimeter_km <= 0 or length_km <= 0:
        return {
            "compactness_coefficient": None,
            "circularity_ratio": None,
            "elongation_ratio": None,
            "form_factor": None,
            "mean_width_km": None,
        }

    return {
        "compactness_coefficient": round(
            perimeter_km / (2 * math.sqrt(math.pi * area_km2)), 4
        ),
        "circularity_ratio": round(4 * math.pi * area_km2 / (perimeter_km**2), 4),
        "elongation_ratio": round((2 / length_km) * math.sqrt(area_km2 / math.pi), 4),
        "form_factor": round(area_km2 / (length_km**2), 4),
        "mean_width_km": round(area_km2 / length_km, 4),
    }
