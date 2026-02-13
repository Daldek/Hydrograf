"""
Tile endpoints for stream and catchment vector layers (MVT).

Serves stream network and sub-catchment tiles as Mapbox Vector Tiles
(MVT/protobuf) from PostGIS tables.
"""

import logging

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

# Simplification tolerance per zoom level (in EPSG:2180 metres)
_MVT_SIMPLIFY_TOLERANCE = {
    0: 5000,
    1: 2500,
    2: 1250,
    3: 600,
    4: 300,
    5: 150,
    6: 80,
    7: 40,
    8: 20,
    9: 10,
    10: 5,
    11: 2.5,
    12: 1.2,
    13: 0.6,
    14: 0.3,
    15: 0.15,
    16: 0.08,
    17: 0.04,
    18: 0.02,
}

_EMPTY_MVT = b""


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
    threshold: int = Query(default=10000, ge=1, description="FA threshold in m²"),
    db: Session = Depends(get_db),
) -> Response:
    """
    Serve stream network as Mapbox Vector Tiles (MVT/protobuf).

    Streams are filtered by flow accumulation threshold and styled
    by Strahler order on the client side.
    """
    xmin, ymin, xmax, ymax = _tile_to_bbox_3857(z, x, y)

    # Geometry simplification tolerance based on zoom
    tolerance = _MVT_SIMPLIFY_TOLERANCE.get(z, 0.01)

    row = db.execute(
        text("""
        WITH mvt_data AS (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(
                        ST_Simplify(s.geom, :tolerance),
                        3857
                    ),
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
            "tolerance": tolerance,
        },
    ).fetchone()

    tile_data = row[0] if row and row[0] else _EMPTY_MVT

    return Response(
        content=bytes(tile_data),
        media_type="application/x-protobuf",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/tiles/catchments/{z}/{x}/{y}.pbf")
def get_catchments_mvt(
    z: int,
    x: int,
    y: int,
    threshold: int = Query(default=10000, ge=1, description="FA threshold in m²"),
    db: Session = Depends(get_db),
) -> Response:
    """
    Serve sub-catchment polygons as Mapbox Vector Tiles (MVT/protobuf).

    Each sub-catchment is the drainage area of a single stream segment.
    Filtered by flow accumulation threshold, styled by Strahler order
    on the client side.
    """
    xmin, ymin, xmax, ymax = _tile_to_bbox_3857(z, x, y)

    # Geometry simplification tolerance based on zoom
    tolerance = _MVT_SIMPLIFY_TOLERANCE.get(z, 0.01)

    row = db.execute(
        text("""
        WITH mvt_data AS (
            SELECT
                ST_AsMVTGeom(
                    ST_Transform(
                        ST_Simplify(c.geom, :tolerance),
                        3857
                    ),
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
            "tolerance": tolerance,
        },
    ).fetchone()

    tile_data = row[0] if row and row[0] else _EMPTY_MVT

    return Response(
        content=bytes(tile_data),
        media_type="application/x-protobuf",
        headers={"Cache-Control": "public, max-age=86400"},
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
