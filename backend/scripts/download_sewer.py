"""Data acquisition for stormwater sewer networks.

Supports: local file (SHP/GPKG/GeoJSON), WFS, external database, URL.
One source per run. Reprojects to EPSG:2180.
"""

import logging
import re
from pathlib import Path

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


def _validate_crs(
    gdf: gpd.GeoDataFrame, assumed_crs: str | None
) -> gpd.GeoDataFrame:
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
        return layers[0]
    for layer_name in layers:
        with fiona.open(path, layer=layer_name) as src:
            if src.schema["geometry"] in ("LineString", "MultiLineString"):
                return layer_name
    return layers[0] if layers else None


def load_from_file(
    path: str,
    lines_layer: str | None = None,
    points_layer: str | None = None,
) -> gpd.GeoDataFrame:
    """Load sewer data from local file (SHP/GPKG/GeoJSON)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Sewer data file not found: {path}")

    layer = lines_layer or _auto_detect_layer(path)
    logger.info(f"Loading sewer data from {path} (layer={layer})")
    gdf = gpd.read_file(path, layer=layer)

    if points_layer:
        pts = gpd.read_file(path, layer=points_layer)
        logger.info(f"Loaded {len(pts)} sewer points from layer={points_layer}")
        gdf.attrs["sewer_points"] = pts

    return gdf


def load_from_wfs(url: str, layer: str) -> gpd.GeoDataFrame:
    """Load sewer data from WFS service."""
    wfs_url = f"{url}?service=WFS&request=GetFeature&typeName={layer}&outputFormat=json"
    logger.info(f"Loading sewer data from WFS: {url} (layer={layer})")
    return gpd.read_file(wfs_url)


def load_from_database(connection: str, table: str) -> gpd.GeoDataFrame:
    """Load sewer data from external PostGIS database."""
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', table):
        raise ValueError(f"Invalid table name: {table}")

    from sqlalchemy import create_engine

    logger.info(f"Loading sewer data from database: {table}")
    engine = create_engine(connection)
    return gpd.read_postgis(f"SELECT * FROM {table}", engine, geom_col="geom")


def load_from_url(url: str) -> gpd.GeoDataFrame:
    """Load sewer data from remote file URL (GDAL vsicurl)."""
    logger.info(f"Loading sewer data from URL: {url}")
    return gpd.read_file(url)


def load_sewer_data(config: dict) -> gpd.GeoDataFrame:
    """Load sewer data based on config source type.

    Dispatches to appropriate loader, validates CRS, reprojects to EPSG:2180.
    """
    sewer_cfg = config["sewer"]
    source = sewer_cfg["source"]
    source_type = source["type"]

    if source_type == "file":
        gdf = load_from_file(
            source["path"],
            lines_layer=source.get("lines_layer"),
            points_layer=source.get("points_layer"),
        )
    elif source_type == "wfs":
        gdf = load_from_wfs(source["url"], source["layer"])
    elif source_type == "database":
        gdf = load_from_database(source["connection"], source["table"])
    elif source_type == "url":
        gdf = load_from_url(source["url"])
    else:
        raise ValueError(f"Unknown sewer source type: {source_type}")

    gdf = _validate_crs(gdf, source.get("assumed_crs"))

    if gdf.empty:
        raise ValueError("Sewer data is empty — no features loaded")

    logger.info(
        f"Loaded {len(gdf)} sewer features "
        f"(type={_detect_geometry_type(gdf)}, crs={gdf.crs})"
    )
    return gdf
