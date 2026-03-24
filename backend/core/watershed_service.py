"""
Shared watershed delineation service using CatchmentGraph.

Provides reusable functions for stream lookup, boundary merging,
outlet extraction, and morphometric dict construction. Used by
watershed, hydrograph, and select_stream endpoints.

All spatial queries target stream_network / stream_catchments tables
(~87k rows each), using pre-computed catchment polygons for fast
boundary merging and morphometric parameter lookup.
"""

import json
import logging
import math

import numpy as np
from shapely import wkb
from shapely.geometry import MultiPolygon, Point, Polygon
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.catchment_graph import CatchmentGraph

logger = logging.getLogger(__name__)

# Minimum area (m²) for interior holes to be preserved in watershed boundary.
# Holes smaller than this threshold (~32×32m) are removed as artifacts.
MIN_HOLE_AREA_M2 = 100


def get_stream_info_by_segment_idx(
    segment_idx: int,
    threshold_m2: int,
    db: Session,
) -> dict | None:
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


def map_boundary_to_display_segments(
    boundary_2180: MultiPolygon | Polygon,
    display_threshold_m2: int,
    db: Session,
) -> list[int]:
    """
    Map a computed boundary to segment_idxs at the display threshold.

    Used when the boundary was computed at a fine threshold but the
    frontend needs segment indices at the display threshold for MVT
    highlighting.

    Parameters
    ----------
    boundary_2180 : MultiPolygon | Polygon
        Boundary geometry in EPSG:2180
    display_threshold_m2 : int
        Display threshold for MVT tiles
    db : Session
        Database session

    Returns
    -------
    list[int]
        segment_idx values at the display threshold that intersect the boundary
    """
    query = text("""
        SELECT segment_idx FROM stream_catchments
        WHERE threshold_m2 = :threshold
          AND ST_Intersects(geom, ST_GeomFromWKB(:boundary, 2180))
    """)
    results = db.execute(
        query,
        {
            "threshold": display_threshold_m2,
            "boundary": boundary_2180.wkb,
        },
    ).fetchall()

    return [r.segment_idx for r in results]


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
    query = text("""
        SELECT ST_AsBinary(
            ST_Multi(ST_Buffer(
                ST_ChaikinSmoothing(
                    ST_SimplifyPreserveTopology(
                        ST_Buffer(ST_Buffer(
                            ST_UnaryUnion(ST_Collect(geom)),
                        :gap_close), -:gap_close),
                    5.0),
                3),
            0))
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

    query = text("""
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
            ST_Multi(ST_Buffer(
                ST_ChaikinSmoothing(
                    ST_SimplifyPreserveTopology(
                        ST_Buffer(ST_Buffer(
                            ST_UnaryUnion(ST_Collect(geom)),
                        :gap_close), -:gap_close),
                    5.0),
                3),
            0))
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

    return json.loads(result.geojson)


def get_main_channel_feature_collection(
    cg: CatchmentGraph,
    main_channel_nodes: list[int],
    threshold_m2: int,
    db: Session,
) -> dict | None:
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

    # Build is_real_stream lookup from graph arrays
    real_flags = {}
    if cg._is_real_stream is not None:
        for node in main_channel_nodes:
            si = cg.get_segment_idx(node)
            real_flags[si] = bool(cg._is_real_stream[node])

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
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "segment_idx": row.segment_idx,
                "is_real_stream": real_flags.get(row.segment_idx, False),
            },
        })

    return {
        "type": "FeatureCollection",
        "features": features,
    }


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
        WHERE segment_idx = :seg_idx
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
    db,
    cg: CatchmentGraph,
    main_ch: dict,
    threshold_m2: int,
    centroid: Point,
    outlet_x: float,
    outlet_y: float,
) -> float | None:
    """Compute Lc along the main channel (Snyder method).

    Queries stream geometries from DB, merges into a LineString, and
    projects the watershed centroid onto it to get along-channel distance.

    Returns Lc in km, or None on failure.
    """
    from shapely.geometry import LineString
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

        # Project centroid onto the merged channel
        lc_m = merged.project(centroid)
        return round(lc_m / 1000, 4)

    except Exception as e:
        logger.warning(f"Failed to compute Lc along channel: {e}")
        return None


def build_morph_dict_from_graph(
    cg: CatchmentGraph,
    upstream_indices: np.ndarray,
    boundary_2180: MultiPolygon | Polygon,
    outlet_x: float,
    outlet_y: float,
    segment_idx: int,
    threshold_m2: int,
    cn: int | None = None,
    imperviousness: float | None = None,
    db: "Session | None" = None,
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
    imperviousness : float | None
        Weighted imperviousness fraction (optional)

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

    # Channel length and slope from main channel trace (not total network)
    main_channel_nodes = []
    outlet_internal_idx = cg.lookup_by_segment_idx(threshold_m2, segment_idx)
    if outlet_internal_idx is not None:
        main_ch = cg.trace_main_channel(outlet_internal_idx, upstream_indices)
        channel_length_km = main_ch.get("main_channel_length_km")
        channel_slope = main_ch.get("main_channel_slope_m_per_m")
        real_channel_length_km = main_ch.get("real_channel_length_km")
        main_channel_nodes = main_ch.get("main_channel_nodes", [])
    else:
        channel_length_km = None
        channel_slope = None
        real_channel_length_km = None

    # Lc: distance along main channel from outlet to nearest point to centroid
    centroid = boundary_2180.centroid
    length_to_centroid_km = _compute_lc_along_channel(
        db, cg, main_ch, threshold_m2, centroid, outlet_x, outlet_y,
    ) if db is not None and main_ch is not None else None
    # Fallback: straight-line distance
    if length_to_centroid_km is None:
        outlet_point = Point(outlet_x, outlet_y)
        length_to_centroid_km = round(centroid.distance(outlet_point) / 1000, 4)

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
        "mean_width_km": shape_indices.get("mean_width_km"),
        # Relief indices
        "relief_ratio": relief_ratio,
        "hypsometric_integral": hypsometric_integral,
        # Drainage indices
        "drainage_density_km_per_km2": dd,
        "stream_frequency_per_km2": stats.get("stream_frequency_per_km2"),
        "ruggedness_number": ruggedness,
        "max_strahler_order": stats.get("max_strahler_order"),
        "hydraulic_length_km": stats.get("hydraulic_length_km"),
    }

    # Private key: internal node indices for main channel (not part of Pydantic schema)
    params["_main_channel_nodes"] = main_channel_nodes

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


def ensure_outlet_within_boundary(
    outlet_x: float,
    outlet_y: float,
    boundary_geom,
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


