"""
XYZ tile endpoint for DEM raster layer.

Serves colored DEM tiles from PostGIS raster data.
"""

import logging
import math
from io import BytesIO

import numpy as np
from fastapi import APIRouter, Depends, Response
from PIL import Image
from pyproj import Transformer
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

TILE_SIZE = 256

# Hypsometric color ramp (elevation-normalized 0–1 → RGB)
_COLOR_STOPS = [
    (0.00, 56, 128, 60),
    (0.15, 76, 175, 80),
    (0.30, 139, 195, 74),
    (0.45, 205, 220, 57),
    (0.60, 255, 193, 7),
    (0.75, 161, 110, 60),
    (0.90, 120, 100, 90),
    (1.00, 245, 245, 240),
]

# Pre-built colormap (256 entries)
_COLORMAP = None


def _build_colormap() -> np.ndarray:
    global _COLORMAP
    if _COLORMAP is not None:
        return _COLORMAP
    cmap = np.zeros((256, 3), dtype=np.uint8)
    positions = [s[0] for s in _COLOR_STOPS]
    colors = np.array([[s[1], s[2], s[3]] for s in _COLOR_STOPS], dtype=np.float64)
    for i in range(256):
        t = i / 255.0
        for k in range(len(positions) - 1):
            if positions[k] <= t <= positions[k + 1]:
                lt = (t - positions[k]) / (positions[k + 1] - positions[k])
                rgb = colors[k] * (1 - lt) + colors[k + 1] * lt
                cmap[i] = np.clip(rgb, 0, 255).astype(np.uint8)
                break
    _COLORMAP = cmap
    return cmap


# WGS84 ↔ EPSG:2180 transformer (cached)
_transformer_to_2180 = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True)


def _tile_to_bbox_2180(z: int, x: int, y: int):
    """Convert XYZ tile coordinates to EPSG:2180 bounding box."""
    n = 2 ** z
    # Tile bounds in WGS84
    lon_min = x / n * 360.0 - 180.0
    lon_max = (x + 1) / n * 360.0 - 180.0
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    # Transform corners to EPSG:2180
    x_min, y_min = _transformer_to_2180.transform(lon_min, lat_min)
    x_max, y_max = _transformer_to_2180.transform(lon_max, lat_max)
    return x_min, y_min, x_max, y_max


# DEM elevation range (cached on first request)
_elev_range = None


def _get_elev_range(db: Session):
    global _elev_range
    if _elev_range is not None:
        return _elev_range
    row = db.execute(text("""
        SELECT
            ST_MinPossibleValue(ST_BandPixelType(rast, 1)),
            (ST_SummaryStats(rast)).min,
            (ST_SummaryStats(rast)).max
        FROM dem_raster LIMIT 1
    """)).fetchone()
    if row:
        # Get actual min/max across all tiles
        result = db.execute(text("""
            SELECT MIN((ST_SummaryStats(rast)).min),
                   MAX((ST_SummaryStats(rast)).max)
            FROM dem_raster
        """)).fetchone()
        _elev_range = (result[0], result[1])
    else:
        _elev_range = (0, 100)
    return _elev_range


@router.get("/tiles/dem/{z}/{x}/{y}.png")
def get_dem_tile(
    z: int, x: int, y: int,
    db: Session = Depends(get_db),
) -> Response:
    """
    Serve a colored DEM tile as PNG.

    Uses PostGIS raster: clips + resamples dem_raster to 256x256,
    applies hypsometric color ramp, returns transparent PNG.
    """
    x_min, y_min, x_max, y_max = _tile_to_bbox_2180(z, x, y)

    # Query PostGIS: clip raster to tile bbox, resample to 256x256
    row = db.execute(text("""
        WITH clipped AS (
            SELECT ST_Union(
                ST_Clip(rast, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 2180))
            ) AS rast
            FROM dem_raster
            WHERE ST_Intersects(rast, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 2180))
        )
        SELECT ST_AsGDALRaster(
            ST_Resize(rast, :tile_size, :tile_size),
            'GTiff'
        ) AS data
        FROM clipped
        WHERE rast IS NOT NULL
    """), {
        "xmin": x_min, "ymin": y_min, "xmax": x_max, "ymax": y_max,
        "tile_size": TILE_SIZE,
    }).fetchone()

    if not row or not row[0]:
        # Empty tile — transparent PNG
        return Response(
            content=_empty_tile_png(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # Read raster data from GeoTIFF bytes
    import rasterio
    from io import BytesIO as RasterIO
    with rasterio.open(RasterIO(bytes(row[0]))) as src:
        data = src.read(1)
        nodata = src.nodata

    # Create valid mask
    if nodata is not None:
        valid = data != nodata
    else:
        valid = np.isfinite(data)

    if not np.any(valid):
        return Response(
            content=_empty_tile_png(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # Normalize elevation to 0–255
    elev_min, elev_max = _get_elev_range(db)
    elev_range = elev_max - elev_min
    if elev_range <= 0:
        elev_range = 1.0

    normalized = np.zeros_like(data, dtype=np.float64)
    normalized[valid] = np.clip((data[valid] - elev_min) / elev_range, 0, 1)
    indices = (normalized * 255).astype(np.int32)
    indices = np.clip(indices, 0, 255)

    # Apply colormap → RGBA
    cmap = _build_colormap()
    h, w = data.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 0] = cmap[indices, 0]
    rgba[..., 1] = cmap[indices, 1]
    rgba[..., 2] = cmap[indices, 2]
    rgba[..., 3] = np.where(valid, 180, 0).astype(np.uint8)

    # Encode PNG
    img = Image.fromarray(rgba, mode="RGBA")
    buf = BytesIO()
    img.save(buf, format="PNG")

    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _empty_tile_png() -> bytes:
    """Generate a 1x1 transparent PNG (minimal size)."""
    img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@router.get("/tiles/dem/metadata")
def get_dem_metadata(db: Session = Depends(get_db)) -> dict:
    """Return DEM layer metadata: bounds, elevation range."""
    result = db.execute(text("""
        SELECT
            ST_XMin(extent) AS xmin, ST_YMin(extent) AS ymin,
            ST_XMax(extent) AS xmax, ST_YMax(extent) AS ymax,
            elev_min, elev_max
        FROM (
            SELECT
                ST_Extent(ST_ConvexHull(rast)) AS extent,
                MIN((ST_SummaryStats(rast)).min) AS elev_min,
                MAX((ST_SummaryStats(rast)).max) AS elev_max
            FROM dem_raster
        ) sub
    """)).fetchone()

    if not result:
        return {"available": False}

    # Transform bounds to WGS84
    transformer = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)
    lon_min, lat_min = transformer.transform(result.xmin, result.ymin)
    lon_max, lat_max = transformer.transform(result.xmax, result.ymax)

    return {
        "available": True,
        "bounds": [[lat_min, lon_min], [lat_max, lon_max]],
        "elevation_min_m": round(result.elev_min, 1),
        "elevation_max_m": round(result.elev_max, 1),
    }
