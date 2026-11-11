"""
Shared watershed delineation service using CatchmentGraph.

Provides reusable functions for stream lookup, boundary merging,
outlet extraction, and morphometric dict construction. Used by
watershed and hydrograph endpoints.

All spatial queries target stream_network / stream_catchments tables
(~87k rows each), using pre-computed catchment polygons for fast
boundary merging and morphometric parameter lookup.
"""

import json
import logging
import math
from typing import Any

import numpy as np
from shapely import wkb
from shapely.geometry import MultiPolygon, Point, Polygon
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.catchment_graph import CatchmentGraph
from core.divide_flow_path import (
    NO_FLOW_PATHS,
    FlowPath,
    WatershedFlowPaths,
    compute_flow_paths,
)
from core.morphometry import calculate_shape_indices
from models.schemas import HsgStats, LandCoverStats
from utils.geometry import transform_pl1992_to_wgs84

logger = logging.getLogger(__name__)

# Minimum area (m²) for interior holes to be preserved in watershed boundary.
# Holes smaller than this threshold (~32×32m) are removed as artifacts.
MIN_HOLE_AREA_M2 = 100


def get_stream_info_by_segment_idx(
    segment_idx: int,
    threshold_m2: int,
    db: Session,
) -> dict[str, Any] | None:
    """
    Get stream segment info by segment_idx and threshold.

    Uses the segment_idx column (1-based per threshold) for exact lookup
    instead of spatial proximity search.

    Parameters
    ----------
    segment_idx : int
        Segment index (1-based per threshold, matches stream_catchments)
    threshold_m2 : int
        Flow accumulation threshold
    db : Session
        Database session

    Returns
    -------
    dict | None
        Segment info with keys: segment_idx, strahler_order, length_m,
        upstream_area_km2, downstream_x, downstream_y.
        None if no segment found.
    """
    query = text("""
        SELECT
            segment_idx,
            strahler_order,
            ST_Length(geom) as length_m,
            upstream_area_km2,
            ST_X(ST_EndPoint(geom)) as downstream_x,
            ST_Y(ST_EndPoint(geom)) as downstream_y
        FROM stream_network
        WHERE threshold_m2 = :threshold
          AND segment_idx = :seg_idx
        LIMIT 1
    """)
    result = db.execute(
        query,
        {"threshold": threshold_m2, "seg_idx": segment_idx},
    ).fetchone()
    if result is None:
        return None
    return {
        "segment_idx": result.segment_idx,
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

    For large segment sets (>100), uses batched union with pre-simplification
    to avoid ST_UnaryUnion O(n²) timeout on 500+ polygons.

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

    n = len(segment_idxs)

    if n <= 100:
        return _merge_direct(segment_idxs, threshold_m2, db)

    # Large merges: batched union with pre-simplification
    logger.info(f"Large merge: {n} segments, using batched union")
    try:
        result = _merge_batched(segment_idxs, threshold_m2, db)
        if result is not None:
            return result
    except Exception as e:
        logger.warning(f"Batched merge failed ({e}), trying simplified fallback")

    # Fallback: aggressive simplification then direct union
    return _merge_simplified_fallback(segment_idxs, threshold_m2, db)


# Gap-closing buffer distance (meters, EPSG:2180). Buffer-debuffer cycle
# ST_Buffer(d) + ST_Buffer(-d) closes gaps up to 2*d between
# independently simplified adjacent catchment polygons.
# Preprocessing simplifies each polygon with 2*cellsize (~10m) tolerance,
# which can create gaps of 1-5m between neighbours.
_GAP_CLOSE_M = 2.0

# Smoothing pipeline applied to final merged geometry:
#   1. ST_Buffer(d) + ST_Buffer(-d)    — close gaps from preprocessing
#   2. ST_SimplifyPreserveTopology(5.0) — reduce staircase vertices
#   3. ST_ChaikinSmoothing(3)           — smooth corners (3 iterations)
#   4. ST_Buffer(0)                     — fix self-intersections,
#                                         preserve connectivity
#      (ST_MakeValid would SPLIT self-intersecting polygons into
#       separate parts, causing discontinuities)
#   5. ST_Multi()                       — wrap as MultiPolygon
#
# Template: {union_expr} is replaced with the ST_UnaryUnion(ST_Collect(..)) call.
_SMOOTH_SQL = """ST_Multi(ST_Buffer(
    ST_ChaikinSmoothing(
        ST_SimplifyPreserveTopology(
            ST_Buffer(ST_Buffer(
                {union_expr},
            :gap_close), -:gap_close),
        5.0),
    3),
0))"""

# Batch size for grid-batched union: each batch unions ~50 polygons
# (fast), then the final union merges ~n/50 pre-merged results.
_BATCH_SIZE = 50

# Snap-to-grid size for pre-union vertex reduction (meters, EPSG:2180).
# Unlike ST_SimplifyPreserveTopology, ST_SnapToGrid preserves shared
# edges between adjacent polygons (both sides snap to the same grid
# points), preventing gaps after union.
_SNAP_SIZE_M = 10.0

# Aggressive snap size for simplified fallback (meters, EPSG:2180).
_SNAP_SIZE_FALLBACK_M = 50.0


def _merge_direct(
    segment_idxs: list[int],
    threshold_m2: int,
    db: Session,
) -> MultiPolygon | None:
    """Direct ST_UnaryUnion for small segment sets (≤100)."""
    smooth = _SMOOTH_SQL.format(union_expr="ST_UnaryUnion(ST_Collect(geom))")
    query = text(f"""
        SELECT ST_AsBinary(
            {smooth}
        ) as geom
        FROM stream_catchments
        WHERE threshold_m2 = :threshold
          AND segment_idx = ANY(:idxs)
    """)
    result = db.execute(
        query,
        {
            "threshold": threshold_m2,
            "idxs": segment_idxs,
            "gap_close": _GAP_CLOSE_M,
        },
    ).fetchone()

    if result is None or result.geom is None:
        return None

    return wkb.loads(bytes(result.geom))


def _merge_batched(
    segment_idxs: list[int],
    threshold_m2: int,
    db: Session,
) -> MultiPolygon | None:
    """
    Batched union with snap-to-grid for large segment sets.

    Groups polygons into batches (~50 each), snaps to grid (preserves
    shared edges unlike ST_SimplifyPreserveTopology), unions within
    each batch, then unions the batch results.
    Turns O(n²) into O(k × (n/k)²) ≈ O(n²/k).
    """
    from core.db_bulk import override_statement_timeout

    smooth = _SMOOTH_SQL.format(union_expr="ST_UnaryUnion(ST_Collect(geom))")
    query = text(f"""
        WITH numbered AS (
            SELECT
                ST_MakeValid(ST_SnapToGrid(geom, :snap_size)) AS geom,
                ROW_NUMBER() OVER (ORDER BY segment_idx) AS rn
            FROM stream_catchments
            WHERE threshold_m2 = :threshold AND segment_idx = ANY(:idxs)
        ),
        batched AS (
            SELECT ST_UnaryUnion(ST_Collect(geom)) AS geom
            FROM numbered
            GROUP BY (rn - 1) / :batch_size
        )
        SELECT ST_AsBinary(
            {smooth}
        ) AS geom
        FROM batched
    """)

    with override_statement_timeout(db, timeout_s=300):
        result = db.execute(
            query,
            {
                "threshold": threshold_m2,
                "idxs": segment_idxs,
                "snap_size": _SNAP_SIZE_M,
                "batch_size": _BATCH_SIZE,
                "gap_close": _GAP_CLOSE_M,
            },
        ).fetchone()

    if result is None or result.geom is None:
        return None

    return wkb.loads(bytes(result.geom))


def _merge_simplified_fallback(
    segment_idxs: list[int],
    threshold_m2: int,
    db: Session,
) -> MultiPolygon | None:
    """Fallback: aggressive snap-to-grid (50m) then direct union."""
    query = text("""
        SELECT ST_AsBinary(
            ST_Multi(ST_Buffer(
                ST_UnaryUnion(ST_Collect(
                    ST_MakeValid(ST_SnapToGrid(geom, :snap_size))
                )),
            0))
        ) AS geom
        FROM stream_catchments
        WHERE threshold_m2 = :threshold AND segment_idx = ANY(:idxs)
    """)
    result = db.execute(
        query,
        {
            "threshold": threshold_m2,
            "idxs": segment_idxs,
            "snap_size": _SNAP_SIZE_FALLBACK_M,
        },
    ).fetchone()

    if result is None or result.geom is None:
        return None

    return wkb.loads(bytes(result.geom))


def catchments_bounds(
    segment_idxs: list[int],
    threshold_m2: int,
    db: Session,
) -> tuple[float, float, float, float] | None:
    """
    Bounding box of sub-catchments of one threshold.

    Parameters
    ----------
    segment_idxs : list[int]
        Segment indices of the sub-catchments
    threshold_m2 : int
        Flow accumulation threshold
    db : Session
        Database session

    Returns
    -------
    tuple[float, float, float, float] | None
        (minx, miny, maxx, maxy) in EPSG:2180, or None when none of the
        sub-catchments has a geometry
    """
    if not segment_idxs:
        return None
    query = text("""
        SELECT ST_XMin(extent) AS minx, ST_YMin(extent) AS miny,
               ST_XMax(extent) AS maxx, ST_YMax(extent) AS maxy
        FROM (
            SELECT ST_Extent(geom) AS extent
            FROM stream_catchments
            WHERE threshold_m2 = :threshold AND segment_idx = ANY(:idxs)
        ) AS selected
    """)
    result = db.execute(
        query,
        {"threshold": threshold_m2, "idxs": segment_idxs},
    ).fetchone()
    if result is None or result.minx is None:
        return None
    return (result.minx, result.miny, result.maxx, result.maxy)


def get_segment_outlet(
    segment_idx: int,
    threshold_m2: int,
    db: Session,
) -> dict[str, Any] | None:
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
        WHERE segment_idx = :seg_idx
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
    boundary: Polygon | MultiPolygon,
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
) -> dict[str, Any] | None:
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
        WHERE segment_idx = :seg_idx
          AND threshold_m2 = :threshold
        LIMIT 1
    """)
    result = db.execute(
        query,
        {"seg_idx": segment_idx, "threshold": threshold_m2},
    ).fetchone()
    if result is None or result.geojson is None:
        return None

    geojson: dict[str, Any] = json.loads(result.geojson)
    return geojson


def get_main_channel_feature_collection(
    cg: CatchmentGraph,
    main_channel_nodes: list[int],
    threshold_m2: int,
    db: Session,
) -> dict[str, Any] | None:
    """
    Build GeoJSON FeatureCollection for the full main channel.

    Each segment is a separate Feature with ``is_real_stream`` property
    indicating whether the segment matches a BDOT10k real stream.

    Parameters
    ----------
    cg : CatchmentGraph
        Loaded catchment graph (for segment_idx and is_real_stream lookup)
    main_channel_nodes : list[int]
        Internal graph indices from trace_main_channel()
    threshold_m2 : int
        Flow accumulation threshold
    db : Session
        Database session

    Returns
    -------
    dict | None
        GeoJSON FeatureCollection or None if no segments found
    """
    if not main_channel_nodes:
        return None

    seg_idxs = [cg.get_segment_idx(n) for n in main_channel_nodes]
    if not seg_idxs:
        return None

    # Build is_real_stream lookup using "contiguous from outlet" logic
    # with tolerance for up to MAX_GAP consecutive non-real segments
    # (the DEM flow-path can briefly deviate from the BDOT channel at
    # bends/meanders, producing short false-negative gaps).
    real_flags = {}
    if cg._is_real_stream is not None:
        MAX_GAP = 2  # allow up to 2 consecutive non-real segments
        gap_count = 0
        started = False  # gap tolerance only after first real segment
        pending_gap_nodes: list[int] = []
        for node_idx, node in enumerate(main_channel_nodes):
            si = cg.get_segment_idx(node)
            if cg._is_real_stream[node]:
                started = True
                # Flush pending gap nodes as real (they were within tolerance)
                for gap_si in pending_gap_nodes:
                    real_flags[gap_si] = True
                pending_gap_nodes = []
                gap_count = 0
                real_flags[si] = True
            else:
                if not started:
                    # Not-real before any real → mark all remaining as not-real
                    real_flags[si] = False
                    for rem_node in main_channel_nodes[node_idx + 1 :]:
                        real_flags[cg.get_segment_idx(rem_node)] = False
                    break
                gap_count += 1
                if gap_count > MAX_GAP:
                    # Mark pending gap nodes as not-real and stop
                    for gap_si in pending_gap_nodes:
                        real_flags[gap_si] = False
                    real_flags[si] = False
                    # Mark all remaining nodes as not-real
                    for rem_node in main_channel_nodes[node_idx + 1 :]:
                        real_flags[cg.get_segment_idx(rem_node)] = False
                    break
                pending_gap_nodes.append(si)
        else:
            # Loop completed without breaking — mark any trailing gap as not-real
            for gap_si in pending_gap_nodes:
                real_flags[gap_si] = False

    query = text("""
        SELECT
            segment_idx,
            ST_AsGeoJSON(ST_Transform(geom, 4326)) as geojson
        FROM stream_network
        WHERE threshold_m2 = :threshold
          AND segment_idx = ANY(:idxs)
    """)
    results = db.execute(
        query,
        {"threshold": threshold_m2, "idxs": seg_idxs},
    ).fetchall()

    if not results:
        return None

    features = []
    for row in results:
        geom = json.loads(row.geojson)
        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "segment_idx": row.segment_idx,
                    "is_real_stream": real_flags.get(row.segment_idx, False),
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def get_catchment_levels_feature_collection(
    segment_idxs: list[int],
    depths: list[int],
    threshold_m2: int,
    tolerance_m: float,
    db: Session,
) -> dict[str, Any]:
    """
    Simplified sub-catchments grouped by depth as a WGS84 FeatureCollection.

    Light geometry for the delineation preview: one MultiPolygon per depth,
    collecting (not merging) its sub-catchments, each simplified with
    ``tolerance_m`` (ST_Simplify keeping collapsed ones); coordinates
    rounded to 5 decimals (~1 m).

    Parameters
    ----------
    segment_idxs : list[int]
        Segment indices of the sub-catchments
    depths : list[int]
        Depth of each segment, parallel to ``segment_idxs``
    threshold_m2 : int
        Flow accumulation threshold of the segments
    tolerance_m : float
        Simplification tolerance [m, EPSG:2180]
    db : Session
        Database session

    Returns
    -------
    dict
        FeatureCollection with one feature per depth (property ``depth``),
        by increasing depth; depths without a polygon are left out.
    """
    query = text("""
        SELECT
            sel.depth,
            ST_AsGeoJSON(
                ST_Transform(
                    ST_CollectionExtract(
                        ST_Collect(ST_Simplify(c.geom, :tolerance, true)), 3
                    ),
                    4326
                ),
                5
            ) AS geojson
        FROM stream_catchments c
        JOIN unnest(CAST(:idxs AS integer[]), CAST(:depths AS integer[]))
            AS sel(segment_idx, depth) ON sel.segment_idx = c.segment_idx
        WHERE c.threshold_m2 = :threshold
          AND c.segment_idx = ANY(:idxs)
          AND c.geom IS NOT NULL
        GROUP BY sel.depth
        ORDER BY sel.depth
    """)
    rows = db.execute(
        query,
        {
            "threshold": threshold_m2,
            "idxs": segment_idxs,
            "depths": depths,
            "tolerance": tolerance_m,
        },
    ).fetchall()

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": json.loads(row.geojson),
                "properties": {"depth": row.depth},
            }
            for row in rows
        ],
    }


def boundary_to_polygon(boundary_2180: MultiPolygon | Polygon) -> Polygon:
    """
    Extract largest Polygon from a MultiPolygon or pass through Polygon.

    Removes interior holes smaller than MIN_HOLE_AREA_M2 to eliminate
    micro-gap artifacts from ST_Union and small endorheic depressions.

    Parameters
    ----------
    boundary_2180 : MultiPolygon | Polygon
        Input boundary geometry

    Returns
    -------
    Polygon
        Largest polygon component with small holes removed
    """
    if hasattr(boundary_2180, "geoms"):
        polys = list(boundary_2180.geoms)
        poly = polys[0] if len(polys) == 1 else max(polys, key=lambda p: p.area)
    else:
        poly = boundary_2180

    # Filter out small interior holes (artifacts)
    if poly.interiors:
        kept = [r for r in poly.interiors if Polygon(r).area >= MIN_HOLE_AREA_M2]
        if len(kept) < len(poly.interiors):
            poly = Polygon(poly.exterior, kept)

    return poly


def _compute_lc_along_channel(
    db: Session,
    cg: CatchmentGraph,
    main_ch: dict[str, Any],
    threshold_m2: int,
    centroid: Point,
    outlet_x: float,
    outlet_y: float,
) -> float | None:
    """Compute Lc along the main channel (Snyder method).

    Queries stream geometries from DB, merges into a LineString, and
    projects the watershed centroid onto it to get the distance along the
    channel from the outlet. The stored stream lines run from their upstream
    end, so the distance is measured from the end of the merged line that
    lies nearer the outlet.

    Returns Lc in km, or None on failure.
    """
    from shapely.ops import linemerge

    nodes = main_ch.get("main_channel_nodes", [])
    if not nodes:
        return None

    # Get segment_idx for each main channel node
    seg_idxs = [cg.get_segment_idx(n) for n in nodes]

    try:
        # Query stream geometries for main channel segments
        rows = db.execute(
            text(
                "SELECT segment_idx, ST_AsBinary(geom) AS geom "
                "FROM stream_network "
                "WHERE threshold_m2 = :threshold "
                "  AND segment_idx = ANY(:idxs)"
            ),
            {"threshold": threshold_m2, "idxs": seg_idxs},
        ).fetchall()

        if not rows:
            return None

        # Parse geometries and merge into continuous line
        lines = [wkb.loads(bytes(r.geom)) for r in rows]
        merged = linemerge(lines)

        # Ensure single LineString
        if merged.geom_type == "MultiLineString":
            # Pick the longest component
            merged = max(merged.geoms, key=lambda g: g.length)

        if merged.geom_type != "LineString" or merged.is_empty:
            return None

        # Project centroid onto the merged channel, from its outlet end
        lc_m = merged.project(centroid)
        outlet = Point(outlet_x, outlet_y)
        if Point(merged.coords[-1]).distance(outlet) < Point(merged.coords[0]).distance(
            outlet
        ):
            lc_m = merged.length - lc_m
        return float(round(lc_m / 1000, 4))

    except Exception as e:
        logger.warning(f"Failed to compute Lc along channel: {e}")
        return None


def sample_stream_distance(
    points_2180: list[tuple[float, float]],
    tif_path: str,
) -> list[float]:
    """Sample stream_distance raster at given points (EPSG:2180).

    Returns list of distances [m] from each point to the global outlet.
    Points outside raster extent get NaN.

    Parameters
    ----------
    points_2180 : list[tuple[float, float]]
        List of (x, y) tuples in EPSG:2180
    tif_path : str
        Path to stream_distance GeoTIFF

    Returns
    -------
    list[float]
        Distance values in meters
    """
    import rasterio

    with rasterio.open(tif_path) as src:
        values = list(src.sample(points_2180))
        return [float(v[0]) if v[0] != src.nodata else float("nan") for v in values]


def _outlet_baseline_m(cg: CatchmentGraph, outlet_idx: int) -> float:
    """Flow distance [m] at the outlet of a watershed, the baseline of its paths.

    outlet_flow_dist_m of the outlet node, max_flow_dist_m of it for data
    without it (understates, never inflates), as CatchmentGraph.aggregate_stats.
    """
    baseline = cg.get_outlet_flow_dist_m(outlet_idx)
    if math.isnan(baseline):
        baseline = cg.get_max_flow_dist_m(outlet_idx)
    return baseline


def get_flow_paths(
    cg: CatchmentGraph,
    upstream_indices: np.ndarray,
    outlet_idx: int,
    threshold_m2: int,
    boundary_2180: MultiPolygon | Polygon,
) -> WatershedFlowPaths:
    """Longest flow path of the watershed and the one from its boundary.

    The watershed is the union of the sub-catchments of ``upstream_indices``
    in the label raster of ``threshold_m2``; both paths follow the D8 flow
    directions to the outlet and their lengths have the baseline of the
    longest flow path (core.divide_flow_path).

    Parameters
    ----------
    cg : CatchmentGraph
        Loaded catchment graph
    upstream_indices : np.ndarray
        Internal indices from cg.traverse_upstream()
    outlet_idx : int
        Internal index of the outlet node
    threshold_m2 : int
        Flow accumulation threshold of ``upstream_indices``
    boundary_2180 : MultiPolygon | Polygon
        Boundary of the watershed in EPSG:2180 (the first reading window)

    Returns
    -------
    WatershedFlowPaths
        No paths without the label, distance or flow direction raster.
    """
    from core.config import get_settings

    settings = get_settings()
    labels_path = settings.resolve_subcatchment_labels_path(threshold_m2)
    flow_dist_path = settings.resolve_stream_distance_path()
    flowdir_path = settings.resolve_flowdir_path()
    if labels_path is None or flow_dist_path is None or flowdir_path is None:
        logger.debug(
            "Flow paths: no label (%s), distance (%s) or flow direction "
            "(%s) raster for threshold %d",
            labels_path,
            flow_dist_path,
            flowdir_path,
            threshold_m2,
        )
        return NO_FLOW_PATHS
    return compute_flow_paths(
        cg.get_segment_indices(upstream_indices, threshold_m2),
        boundary_2180.bounds,
        _outlet_baseline_m(cg, outlet_idx),
        labels_path,
        flow_dist_path,
        flowdir_path,
    )


def flow_path_geojson(path: FlowPath | None, kind: str) -> dict[str, Any] | None:
    """GeoJSON Feature (WGS84) of a flow path, None without one or for one cell.

    ``kind`` is its ``type`` property (``longest_flow_path``, ``divide_flow_path``).
    """
    if path is None or len(path.coords_2180) < 2:
        return None
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [
                list(transform_pl1992_to_wgs84(x, y)) for x, y in path.coords_2180
            ],
        },
        "properties": {
            "type": kind,
            "length_km": path.length_km,
            "own_length_km": path.own_length_km,
        },
    }


def build_morph_dict_from_graph(
    cg: CatchmentGraph,
    upstream_indices: np.ndarray,
    boundary_2180: MultiPolygon | Polygon,
    outlet_x: float,
    outlet_y: float,
    segment_idx: int,
    threshold_m2: int,
    cn: float | None = None,
    imperviousness: float | None = None,
    db: "Session | None" = None,
    outlet_idx: int | None = None,
) -> dict[str, Any]:
    """Build the morphometric parameter dict for Hydrolog.

    Compatible with Hydrolog's WatershedParameters.from_dict() and
    MorphometricParameters schema.

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
    cn : float | None
        SCS Curve Number (optional)
    imperviousness : float | None
        Weighted imperviousness fraction (optional)

    Returns
    -------
    dict
        Dictionary with all morphometric parameters
    """
    stats = cg.aggregate_stats(upstream_indices, outlet_idx=outlet_idx)
    area_km2 = stats["area_km2"]

    perimeter_km = round(boundary_2180.length / 1000, 4)

    # Watershed length = longest flow path (main channel valley from outlet
    # to divide).  Fallback to straight-line max distance from outlet.
    hydraulic_len = stats.get("hydraulic_length_km")
    if hydraulic_len is not None and hydraulic_len > 0:
        length_km = round(hydraulic_len, 4)
    else:
        length_km = round(
            compute_watershed_length(boundary_2180, outlet_x, outlet_y),
            4,
        )

    elev_min = stats.get("elevation_min_m")
    elev_max = stats.get("elevation_max_m")

    # Channel length and slope from main channel trace (not total network), from
    # the outlet node of ``upstream_indices``: after an escalation to a coarser
    # threshold (cascade_escalate) ``segment_idx`` is the clicked segment of the
    # request's threshold, which is no node of ``threshold_m2``
    main_channel_nodes = []
    outlet_internal_idx = (
        outlet_idx
        if outlet_idx is not None
        else cg.lookup_by_segment_idx(threshold_m2, segment_idx)
    )
    if outlet_internal_idx is not None:
        main_ch = cg.trace_main_channel(outlet_internal_idx, upstream_indices)
        channel_length_km = main_ch.get("main_channel_length_km")
        channel_slope = main_ch.get("main_channel_slope_m_per_m")
        real_channel_length_km = main_ch.get("real_channel_length_km")
        main_channel_nodes = main_ch.get("main_channel_nodes", [])
    else:
        main_ch = None
        channel_length_km = None
        channel_slope = None
        real_channel_length_km = None

    # Lc: distance along main channel from outlet to nearest point to centroid
    centroid = boundary_2180.centroid
    length_to_centroid_km = (
        _compute_lc_along_channel(
            db,
            cg,
            main_ch,
            threshold_m2,
            centroid,
            outlet_x,
            outlet_y,
        )
        if db is not None and main_ch is not None
        else None
    )
    # Fallback: straight-line distance
    if length_to_centroid_km is None:
        outlet_point = Point(outlet_x, outlet_y)
        length_to_centroid_km = round(centroid.distance(outlet_point) / 1000, 4)

    # Shape indices
    shape_indices = calculate_shape_indices(area_km2, perimeter_km, length_km)

    # Relief indices
    # R = ΔH / sqrt(A) [‰], where ΔH in m, A in km²
    relief_ratio = None
    if elev_min is not None and elev_max is not None and area_km2 > 0:
        relief_m = elev_max - elev_min
        relief_ratio = round(relief_m / math.sqrt(area_km2), 4)

    # Rp = ΔH / P [‰], where ΔH in m, P in km (watershed boundary length)
    divide_slope = None
    if elev_min is not None and elev_max is not None and perimeter_km > 0:
        relief_m = elev_max - elev_min
        divide_slope = round(relief_m / perimeter_km, 4)

    # α — asymmetry coefficient: 2*(AL - AP) / A
    # where AL = left bank area, AP = right bank area (split along main channel)
    # TODO: compute AL and AP from main channel geometry
    asymmetry_coefficient = None

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

    # Flow path parameters
    longest_flow_path_km = stats.get("hydraulic_length_km")

    # The longest flow path from the hydraulically most distant point to the
    # outlet and its slope from the elevation of its head (Kirpich's L and S;
    # the flow length of NEH 630 ch. 15), with the overland segment of its head
    flow_path_length_km = (
        hydraulic_len if hydraulic_len is not None and hydraulic_len > 0 else None
    )
    flow_path_slope = None
    head_elev = stats.get("flow_path_head_elevation_m")
    if (
        flow_path_length_km is not None
        and head_elev is not None
        and elev_min is not None
    ):
        slope = (head_elev - elev_min) / (flow_path_length_km * 1000)
        if slope > 0:
            flow_path_slope = round(slope, 6)

    # The lines of the longest flow path and of the one from the boundary of
    # the watershed (the boundary cells of its sub-catchments in the label
    # raster), with the baseline of flow_path_length
    flow_paths = NO_FLOW_PATHS
    if outlet_idx is not None:
        try:
            flow_paths = get_flow_paths(
                cg, upstream_indices, outlet_idx, threshold_m2, boundary_2180
            )
        except Exception as e:
            logger.warning("Failed to compute the flow paths: %s", e)
    divide_flow_path_km = (
        flow_paths.divide.length_km if flow_paths.divide is not None else None
    )

    # Point sampling stream_distance.tif for the centroid flow path
    centroid_flow_path_km = None
    try:
        from core.config import get_settings

        sd_path = get_settings().resolve_stream_distance_path()
        if sd_path is not None:
            outlet_dist, centroid_dist = sample_stream_distance(
                [(outlet_x, outlet_y), (centroid.x, centroid.y)], sd_path
            )
            if not np.isnan(outlet_dist) and not np.isnan(centroid_dist):
                cfp = (centroid_dist - outlet_dist) / 1000.0
                if cfp > 0:
                    centroid_flow_path_km = round(cfp, 4)
        else:
            logger.debug("stream_distance.tif not found, skipping centroid flow path")
    except Exception as e:
        logger.debug("Failed to compute the centroid flow path: %s", e)

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
        "real_channel_length_km": real_channel_length_km,
        "length_to_centroid_km": length_to_centroid_km,
        "cn": cn,
        "imperviousness": imperviousness,
        "source": "Hydrograf",
        "crs": "EPSG:2180",
        # Shape indices
        "compactness_coefficient": shape_indices.get("compactness_coefficient"),
        "circularity_ratio": shape_indices.get("circularity_ratio"),
        "elongation_ratio": shape_indices.get("elongation_ratio"),
        "form_factor": shape_indices.get("form_factor"),
        "lemniscate_ratio": shape_indices.get("lemniscate_ratio"),
        "mean_width_km": shape_indices.get("mean_width_km"),
        # Relief indices
        "relief_ratio": relief_ratio,
        "divide_slope": divide_slope,
        "asymmetry_coefficient": asymmetry_coefficient,
        "hypsometric_integral": hypsometric_integral,
        # Drainage indices (BDOT-based: real streams only)
        "drainage_density_km_per_km2": dd,
        "stream_frequency_per_km2": stats.get("stream_frequency_per_km2"),
        "ruggedness_number": ruggedness,
        "max_strahler_order": stats.get("max_strahler_order"),
        "bdot_stream_length_km": stats.get("bdot_stream_length_km"),
        "bdot_stream_count": stats.get("bdot_stream_count"),
        "hydraulic_length_km": stats.get("hydraulic_length_km"),
        # Flow path parameters
        "longest_flow_path_km": longest_flow_path_km,
        "divide_flow_path_km": divide_flow_path_km,
        "centroid_flow_path_km": centroid_flow_path_km,
        "flow_path_length_km": flow_path_length_km,
        "flow_path_slope_m_per_m": flow_path_slope,
        "overland_length_km": stats.get("overland_length_km"),
        "overland_slope_m_per_m": stats.get("overland_slope_m_per_m"),
    }

    # Private keys (not part of Pydantic schema): internal node indices of the
    # main channel and the flow paths for the map
    params["_main_channel_nodes"] = main_channel_nodes
    params["_flow_paths"] = flow_paths

    logger.info(
        f"Built morph dict from graph: area={area_km2:.2f} km2, "
        f"length={length_km:.2f} km"
    )

    return params


def ensure_outlet_within_boundary(
    outlet_x: float,
    outlet_y: float,
    boundary_geom: Polygon | MultiPolygon,
) -> tuple[float, float]:
    """Snap outlet to boundary if it falls outside.

    Returns (outlet_x, outlet_y) unchanged if already inside or within 1m of boundary.
    Otherwise snaps to nearest point on boundary.

    Parameters
    ----------
    outlet_x, outlet_y : float
        Outlet coordinates in EPSG:2180
    boundary_geom : Polygon | MultiPolygon
        Boundary geometry (Shapely object)

    Returns
    -------
    tuple[float, float]
        (outlet_x, outlet_y) — original or snapped
    """
    from shapely.geometry import Point

    outlet_point = Point(outlet_x, outlet_y)

    # Already inside boundary
    if boundary_geom.contains(outlet_point):
        return outlet_x, outlet_y

    # Within 1m tolerance — treat as on boundary
    if boundary_geom.distance(outlet_point) <= 1.0:
        return outlet_x, outlet_y

    # Snap to nearest point on boundary
    nearest = (
        boundary_geom.exterior
        if hasattr(boundary_geom, "exterior")
        else boundary_geom.boundary
    )
    projected = nearest.interpolate(nearest.project(outlet_point))
    return projected.x, projected.y


def cascade_escalate(
    cg: CatchmentGraph,
    point_x: float,
    point_y: float,
    base_threshold: int,
    base_segment_idxs: list[int],
    max_merge: int,
    db: Session,
) -> tuple[list[int], int, np.ndarray, int, dict[str, Any], float] | None:
    """Escalate to a coarser threshold if the segment count exceeds max_merge.

    Tries the thresholds of the graph above ``base_threshold`` from the finest
    and re-runs the BFS from the sub-catchment at the point at the first one
    whose BFS selects at most ``max_merge`` segments. When none does, the
    coarsest threshold with a sub-catchment at the point is taken: it merges
    the fewest segments.

    Parameters
    ----------
    cg : CatchmentGraph
        Loaded catchment graph
    point_x, point_y : float
        Click point in EPSG:2180
    base_threshold : int
        Original threshold that produced too many segments
    base_segment_idxs : list[int]
        Segment indices from BFS at base_threshold
    max_merge : int
        Maximum allowed segment count before escalation
    db : Session
        Database session

    Returns
    -------
    tuple | None
        (merge_idxs, merge_threshold, upstream_indices, outlet_idx, stats, area_km2)
        or None if no escalation is needed (segment count <= max_merge) or no
        coarser threshold has a sub-catchment at the point.
    """
    if len(base_segment_idxs) <= max_merge:
        return None

    selected: tuple[list[int], int, np.ndarray, int] | None = None
    for t in cg.thresholds_m2():
        if t <= base_threshold:
            continue
        try:
            t_node = cg.find_catchment_at_point(point_x, point_y, t, db)
        except ValueError:
            continue
        t_up = cg.traverse_upstream(t_node)
        t_segs = cg.get_segment_indices(t_up, t)
        selected = (t_segs, t, t_up, t_node)
        if len(t_segs) <= max_merge:
            break

    if selected is None:
        return None
    t_segs, t, t_up, t_node = selected
    stats = cg.aggregate_stats(t_up, outlet_idx=t_node)
    return (t_segs, t, t_up, t_node, stats, stats["area_km2"])


def build_land_cover_stats(
    boundary: Polygon | MultiPolygon,
    db: Session,
    simplify_tolerance: float | None = None,
) -> LandCoverStats | None:
    """Build LandCoverStats from boundary polygon.

    The CN is that of the soil-cover complexes, land cover x soil group
    (core.land_cover.get_land_cover_for_boundary, ADR-075).

    Parameters
    ----------
    boundary : Polygon | MultiPolygon
        Watershed boundary in EPSG:2180
    db : Session
        Database session
    simplify_tolerance : float | None
        If set, simplify boundary before query (meters)

    Returns
    -------
    LandCoverStats | None
        Land cover statistics or None if no data
    """
    from core.land_cover import get_land_cover_for_boundary
    from models.schemas import LandCoverCategory, LandCoverStats

    query_boundary = boundary
    if simplify_tolerance is not None:
        query_boundary = boundary.simplify(simplify_tolerance)

    try:
        lc_data = get_land_cover_for_boundary(query_boundary, db)
        if not lc_data:
            return None
        return LandCoverStats(
            categories=[
                LandCoverCategory(
                    category=cat["category"],
                    percentage=cat["percentage"],
                    area_m2=cat["area_m2"],
                    cn_value=cat["cn_value"],
                )
                for cat in lc_data["categories"]
            ],
            weighted_cn=lc_data["weighted_cn"],
            weighted_imperviousness=lc_data["weighted_imperviousness"],
            forest_pct=lc_data["forest_pct"],
            urban_pct=lc_data["urban_pct"],
            hsg_assumed_pct=lc_data["hsg_assumed_pct"],
        )
    except Exception as e:
        logger.debug(f"Land cover stats not available: {e}")
        return None


def build_hsg_stats(
    boundary: Polygon | MultiPolygon,
    db: Session,
) -> HsgStats | None:
    """Build HsgStats from boundary polygon.

    Parameters
    ----------
    boundary : Polygon | MultiPolygon
        Watershed boundary in EPSG:2180. Uses wkb_hex for DB query.
    db : Session
        Database session

    Returns
    -------
    HsgStats | None
        HSG statistics or None if no data
    """
    from core.soil_hsg import get_hsg_for_boundary
    from models.schemas import HsgCategory, HsgStats

    try:
        hsg_data = get_hsg_for_boundary(boundary.wkb_hex, db)
        if not hsg_data:
            return None
        return HsgStats(
            categories=[
                HsgCategory(
                    group=cat["group"],
                    percentage=cat["percentage"],
                    area_m2=cat["area_m2"],
                )
                for cat in hsg_data["categories"]
            ],
            dominant_group=hsg_data["dominant_group"],
        )
    except Exception as e:
        logger.debug(f"HSG stats not available: {e}")
        return None
