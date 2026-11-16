"""Data acquisition for stormwater sewer networks.

Supports local files (SHP/GPKG/GeoJSON); the source types wfs, database and url are
refused until the topology model reads them.
One source per run. Reprojects to EPSG:2180.
"""

import logging
from pathlib import Path
from typing import Any

import fiona
import geopandas as gpd

logger = logging.getLogger(__name__)

TARGET_CRS = "EPSG:2180"


def _detect_geometry_type(gdf: gpd.GeoDataFrame) -> str:
    """Detect dominant geometry type: 'lines' or 'points'."""
    types = gdf.geometry.geom_type.unique()
    if any(t in ("LineString", "MultiLineString") for t in types):
        return "lines"
    if any(t in ("Point", "MultiPoint") for t in types):
        return "points"
    raise ValueError(f"Unsupported geometry types: {types}")


def _validate_crs(gdf: gpd.GeoDataFrame, assumed_crs: str | None) -> gpd.GeoDataFrame:
    """Validate and set CRS. Raises ValueError if no CRS and no assumed_crs."""
    if gdf.crs is None:
        if assumed_crs:
            logger.warning(f"No CRS in data — using assumed_crs={assumed_crs}")
            gdf = gdf.set_crs(assumed_crs)
        else:
            raise ValueError(
                "Input data has no CRS. Set 'sewer.source.assumed_crs' in config."
            )
    if gdf.crs.to_epsg() != 2180:
        logger.info(f"Reprojecting from {gdf.crs} to {TARGET_CRS}")
        gdf = gdf.to_crs(TARGET_CRS)
    return gdf


def _auto_detect_layer(path: str) -> str | None:
    """Auto-detect first LineString layer in multi-layer file."""
    try:
        layers = fiona.listlayers(path)
    except Exception:
        return None
    if len(layers) == 1:
        return str(layers[0])
    for layer_name in layers:
        with fiona.open(path, layer=layer_name) as src:
            if src.schema["geometry"] in ("LineString", "MultiLineString"):
                return str(layer_name)
    return layers[0] if layers else None


def load_from_file(
    path: str,
    lines_layer: str | None = None,
    points_layer: str | None = None,
    source_format: str = "auto",
) -> tuple[gpd.GeoDataFrame | None, gpd.GeoDataFrame | None]:
    """Load sewer data from local file (SHP/GPKG/GeoJSON).

    Returns (points_gdf, lines_gdf). Either may be None if not present.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Sewer data file not found: {path}")

    points_gdf: gpd.GeoDataFrame | None = None
    lines_gdf: gpd.GeoDataFrame | None = None

    # Determine available layers for GPKG; other formats have a single layer
    try:
        available_layers = fiona.listlayers(path)
    except Exception:
        available_layers = [None]

    # --- Load lines ---
    if source_format != "points_only":
        layer = lines_layer or _auto_detect_layer(path)
        if layer is not None:
            logger.info(f"Loading sewer lines from {path} (layer={layer})")
            lines_gdf = gpd.read_file(path, layer=layer)
            # If auto-detected layer turned out to be points, move it
            if not lines_gdf.empty and _detect_geometry_type(lines_gdf) == "points":
                if points_gdf is None:
                    points_gdf = lines_gdf
                lines_gdf = None

    # --- Load points ---
    if points_layer:
        logger.info(f"Loading sewer points from {path} (layer={points_layer})")
        points_gdf = gpd.read_file(path, layer=points_layer)
    elif source_format == "points_only":
        # Auto-detect a point layer
        for layer_name in available_layers:
            gdf = (
                gpd.read_file(path, layer=layer_name)
                if layer_name
                else gpd.read_file(path)
            )
            if not gdf.empty and _detect_geometry_type(gdf) == "points":
                points_gdf = gdf
                break
        if points_gdf is None:
            # Fallback: read first layer regardless of geometry
            first = available_layers[0]
            points_gdf = (
                gpd.read_file(path, layer=first) if first else gpd.read_file(path)
            )

    if lines_gdf is not None:
        logger.info(f"Loaded {len(lines_gdf)} sewer lines")
    if points_gdf is not None:
        logger.info(f"Loaded {len(points_gdf)} sewer points")

    return points_gdf, lines_gdf


def load_sewer_data(
    config: dict[str, Any],
) -> tuple[gpd.GeoDataFrame | None, gpd.GeoDataFrame | None]:
    """Load sewer data based on config source type.

    Dispatches to appropriate loader, validates CRS, reprojects to EPSG:2180.
    Returns (points_gdf, lines_gdf). Either may be None if not present.
    """
    sewer_cfg = config.get("sewer", config)
    source = sewer_cfg.get("source", sewer_cfg)
    source_type = source.get("type", "file")
    source_format = source.get("format", "auto")
    assumed_crs = source.get("assumed_crs")

    if source_type == "file":
        points_gdf, lines_gdf = load_from_file(
            source["path"],
            lines_layer=source.get("lines_layer"),
            points_layer=source.get("points_layer"),
            source_format=source_format,
        )
    elif source_type in ("wfs", "database", "url"):
        raise ValueError(
            f"Source type '{source_type}' is not yet supported with the new topology "
            "model. Please use type='file' with a GPKG/SHP containing point data with "
            "id, role, and downstream_id columns."
        )
    else:
        raise ValueError(f"Unknown sewer source type: {source_type}")

    if points_gdf is not None:
        points_gdf = _validate_crs(points_gdf, assumed_crs)
    if lines_gdf is not None:
        lines_gdf = _validate_crs(lines_gdf, assumed_crs)

    if points_gdf is None and lines_gdf is None:
        raise ValueError("Sewer data is empty — no features loaded")

    if points_gdf is not None:
        logger.info(
            f"Loaded {len(points_gdf)} sewer point features (crs={points_gdf.crs})"
        )
    if lines_gdf is not None:
        logger.info(
            f"Loaded {len(lines_gdf)} sewer line features (crs={lines_gdf.crs})"
        )

    return points_gdf, lines_gdf
