"""
Tile endpoints for stream and catchment vector layers (MVT).

Serves stream network and sub-catchment tiles as Mapbox Vector Tiles
(MVT/protobuf) from PostGIS tables.

Geometry is pre-simplified at 1m (cellsize) during pipeline processing.
No additional simplification is applied at query time — ST_AsMVTGeom
handles coordinate quantization to the 4096-unit tile grid, which
provides zoom-appropriate detail reduction without discrete visual
jumps between zoom levels.
"""

import logging

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

_EMPTY_MVT = b""

# Cache headers: non-empty tiles are cached for 24h; empty tiles must
# never be cached — during bootstrap, tables are temporarily empty
# and caching empty responses blocks tiles for up to 24 hours.
_CACHE_HIT = {"Cache-Control": "public, max-age=86400"}
_CACHE_MISS = {"Cache-Control": "no-store"}


def _tile_to_bbox_3857(z: int, x: int, y: int):
    """Convert XYZ tile coordinates to EPSG:3857 bounding box."""
    n = 2**z
    # Web Mercator bounds
    world = 20037508.3427892
    tile_size = 2 * world / n
    xmin = -world + x * tile_size
    xmax = xmin + tile_size
    ymax = world - y * tile_size
    ymin = ymax - tile_size
    return xmin, ymin, xmax, ymax


@router.get("/tiles/streams/{z}/{x}/{y}.pbf")
def get_streams_mvt(
    z: int,
    x: int,
    y: int,
    threshold: int = Query(default=100000, ge=1, description="FA threshold in m²"),
    db: Session = Depends(get_db),
) -> Response:
    """
    Serve stream network as Mapbox Vector Tiles (MVT/protobuf).

    Streams are filtered by flow accumulation threshold and styled
    by Strahler order on the client side.
    """
    xmin, ymin, xmax, ymax = _tile_to_bbox_3857(z, x, y)

    row = db.execute(
        text("""
        WITH mvt_data AS (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(s.geom, 3857),
                    ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 3857),
                    4096, 64, true
                ) AS geom,
                s.strahler_order,
                s.length_m,
                s.upstream_area_km2
            FROM stream_network s
            WHERE s.threshold_m2 = :threshold
              AND s.geom IS NOT NULL
              AND ST_Intersects(
                  s.geom,
                  ST_Transform(
                      ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 3857),
                      2180
                  )
              )
        )
        SELECT ST_AsMVT(mvt_data, 'streams', 4096, 'geom') AS tile
        FROM mvt_data
        """),
        {
            "xmin": xmin,
            "ymin": ymin,
            "xmax": xmax,
            "ymax": ymax,
            "threshold": threshold,
        },
    ).fetchone()

    tile_data = row[0] if row and row[0] else _EMPTY_MVT
    has_data = tile_data != _EMPTY_MVT

    return Response(
        content=bytes(tile_data),
        media_type="application/x-protobuf",
        headers=_CACHE_HIT if has_data else _CACHE_MISS,
    )


@router.get("/tiles/catchments/{z}/{x}/{y}.pbf")
def get_catchments_mvt(
    z: int,
    x: int,
    y: int,
    threshold: int = Query(default=100000, ge=1, description="FA threshold in m²"),
    db: Session = Depends(get_db),
) -> Response:
    """
    Serve sub-catchment polygons as Mapbox Vector Tiles (MVT/protobuf).

    Each sub-catchment is the drainage area of a single stream segment.
    Filtered by flow accumulation threshold, styled by Strahler order
    on the client side.
    """
    xmin, ymin, xmax, ymax = _tile_to_bbox_3857(z, x, y)

    # Min polygon area to include in tiles (filters raster micro-fragments)
    min_geom_area = 50  # m² in EPSG:2180

    row = db.execute(
        text("""
        WITH mvt_data AS (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(c.geom, 3857),
                    ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 3857),
                    4096, 64, true
                ) AS geom,
                c.strahler_order,
                c.area_km2,
                c.mean_elevation_m,
                c.segment_idx
            FROM stream_catchments c
            WHERE c.threshold_m2 = :threshold
              AND c.geom IS NOT NULL
              AND ST_Area(c.geom) > :min_geom_area
              AND ST_Intersects(
                  c.geom,
                  ST_Transform(
                      ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 3857),
                      2180
                  )
              )
        )
        SELECT ST_AsMVT(mvt_data, 'catchments', 4096, 'geom') AS tile
        FROM mvt_data
        """),
        {
            "xmin": xmin,
            "ymin": ymin,
            "xmax": xmax,
            "ymax": ymax,
            "threshold": threshold,
            "min_geom_area": min_geom_area,
        },
    ).fetchone()

    tile_data = row[0] if row and row[0] else _EMPTY_MVT
    has_data = tile_data != _EMPTY_MVT

    return Response(
        content=bytes(tile_data),
        media_type="application/x-protobuf",
        headers=_CACHE_HIT if has_data else _CACHE_MISS,
    )


@router.get("/tiles/landcover/{z}/{x}/{y}.pbf")
def get_landcover_tile(
    z: int,
    x: int,
    y: int,
    db: Session = Depends(get_db),
) -> Response:
    """
    Serve land cover data as Mapbox Vector Tiles (MVT/protobuf).

    Land cover polygons from BDOT10k classification are styled by
    category on the client side.
    """
    xmin, ymin, xmax, ymax = _tile_to_bbox_3857(z, x, y)

    row = db.execute(
        text("""
        WITH mvt_data AS (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(lc.geom, 3857),
                    ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 3857),
                    4096, 64, true
                ) AS geom,
                lc.category,
                lc.cn_value,
                lc.bdot_class
            FROM land_cover lc
            WHERE lc.geom IS NOT NULL
              AND ST_Intersects(
                  lc.geom,
                  ST_Transform(
                      ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 3857),
                      2180
                  )
              )
        )
        SELECT ST_AsMVT(mvt_data, 'landcover', 4096, 'geom') AS tile
        FROM mvt_data
        """),
        {
            "xmin": xmin,
            "ymin": ymin,
            "xmax": xmax,
            "ymax": ymax,
        },
    ).fetchone()

    tile_data = row[0] if row and row[0] else _EMPTY_MVT
    has_data = tile_data != _EMPTY_MVT

    return Response(
        content=bytes(tile_data),
        media_type="application/x-protobuf",
        headers=_CACHE_HIT if has_data else _CACHE_MISS,
    )


@router.get("/tiles/sewer/{z}/{x}/{y}.pbf")
def get_sewer_mvt(
    z: int,
    x: int,
    y: int,
    db: Session = Depends(get_db),
) -> Response:
    """Sewer network MVT tiles (lines + nodes in separate layers)."""
    xmin, ymin, xmax, ymax = _tile_to_bbox_3857(z, x, y)

    row = db.execute(
        text("""
        WITH
        sewer_lines AS (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(n.geom, 3857),
                    ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 3857),
                    4096, 64, true
                ) AS geom,
                n.diameter_mm,
                n.length_m,
                n.slope_percent
            FROM sewer_network n
            WHERE n.geom IS NOT NULL
              AND ST_Intersects(
                  n.geom,
                  ST_Transform(
                      ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 3857),
                      2180
                  )
              )
        ),
        sewer_pts AS (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(p.geom, 3857),
                    ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 3857),
                    4096, 64, true
                ) AS geom,
                p.node_type,
                p.fa_value,
                p.total_upstream_fa
            FROM sewer_nodes p
            WHERE p.geom IS NOT NULL
              AND ST_Intersects(
                  p.geom,
                  ST_Transform(
                      ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 3857),
                      2180
                  )
              )
        )
        SELECT
            COALESCE(
                (SELECT ST_AsMVT(d, 'sewer_lines', 4096, 'geom')
                 FROM sewer_lines d WHERE d.geom IS NOT NULL),
                ''::bytea
            )
            ||
            COALESCE(
                (SELECT ST_AsMVT(d, 'sewer_nodes', 4096, 'geom')
                 FROM sewer_pts d WHERE d.geom IS NOT NULL),
                ''::bytea
            ) AS tile
        """),
        {
            "xmin": xmin,
            "ymin": ymin,
            "xmax": xmax,
            "ymax": ymax,
        },
    ).fetchone()

    tile_data = row[0] if row and row[0] else _EMPTY_MVT
    has_data = tile_data != _EMPTY_MVT

    return Response(
        content=bytes(tile_data),
        media_type="application/x-protobuf",
        headers=_CACHE_HIT if has_data else _CACHE_MISS,
    )


@router.get("/tiles/thresholds")
def get_available_thresholds(db: Session = Depends(get_db)) -> dict:
    """
    Return available FA threshold values from the database.

    Queries distinct threshold_m2 from stream_network and stream_catchments
    so the frontend can build dropdown options dynamically.
    """
    streams_rows = db.execute(
        text("SELECT DISTINCT threshold_m2 FROM stream_network ORDER BY threshold_m2")
    ).fetchall()
    streams = [row[0] for row in streams_rows]

    # stream_catchments may not exist yet
    try:
        catchments_rows = db.execute(
            text(
                "SELECT DISTINCT threshold_m2"
                " FROM stream_catchments ORDER BY threshold_m2"
            )
        ).fetchall()
        catchments = [row[0] for row in catchments_rows]
    except Exception:
        catchments = []

    return {"streams": streams, "catchments": catchments}
