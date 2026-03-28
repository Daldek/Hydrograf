"""Data acquisition for stormwater sewer networks.

Supports: local file (SHP/GPKG/GeoJSON), WFS, external database, URL.
One source per run. Reprojects to EPSG:2180.
"""

import ipaddress
import logging
import re
import urllib.parse
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


def _validate_url(url: str) -> None:
    """Validate URL to prevent SSRF. Only allows http(s):// to external hosts."""
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme not in ("https", "http"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}. Use https://")

    hostname = parsed.hostname or ""

    # Block internal/private addresses
    blocked_hosts = {
        "localhost", "127.0.0.1", "0.0.0.0", "::1",
        "metadata.google.internal",
    }
    if hostname in blocked_hosts:
        raise ValueError(f"Blocked host: {hostname}")

    # Block private IP ranges (incl. cloud metadata 169.254.x.x)
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError(f"Blocked private/reserved IP: {hostname}")
    except ValueError:
        pass  # hostname is not an IP — OK (could be a domain)

    # Block AWS/cloud metadata endpoints by prefix
    if hostname.startswith("169.254."):
        raise ValueError(f"Blocked metadata endpoint: {hostname}")


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
    suffix = p.suffix.lower()
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
            gdf = gpd.read_file(path, layer=layer_name) if layer_name else gpd.read_file(path)
            if not gdf.empty and _detect_geometry_type(gdf) == "points":
                points_gdf = gdf
                break
        if points_gdf is None:
            # Fallback: read first layer regardless of geometry
            first = available_layers[0]
            points_gdf = gpd.read_file(path, layer=first) if first else gpd.read_file(path)

    if lines_gdf is not None:
        logger.info(f"Loaded {len(lines_gdf)} sewer lines")
    if points_gdf is not None:
        logger.info(f"Loaded {len(points_gdf)} sewer points")

    return points_gdf, lines_gdf


def load_from_wfs(url: str, layer: str) -> gpd.GeoDataFrame:
    """Load sewer data from WFS service."""
    _validate_url(url)
    encoded_layer = urllib.parse.quote(layer, safe='')
    wfs_url = f"{url}?service=WFS&request=GetFeature&typeName={encoded_layer}&outputFormat=json"
    logger.info(f"Loading sewer data from WFS: {url} (layer={layer})")
    return gpd.read_file(wfs_url)


def load_from_database(connection: str, table: str) -> gpd.GeoDataFrame:
    """Load sewer data from external PostGIS database."""
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', table):
        raise ValueError(f"Invalid table name: {table}")

    # Validate connection string — block SSRF via database hostname
    parsed = urllib.parse.urlparse(connection)
    if parsed.hostname:
        _validate_url(f"https://{parsed.hostname}")

    from sqlalchemy import create_engine

    logger.info(f"Loading sewer data from database: {table}")
    engine = create_engine(connection)
    return gpd.read_postgis(f"SELECT * FROM {table}", engine, geom_col="geom")


def load_from_url(url: str) -> gpd.GeoDataFrame:
    """Load sewer data from remote file URL (GDAL vsicurl)."""
    _validate_url(url)
    logger.info(f"Loading sewer data from URL: {url}")
    return gpd.read_file(url)


def load_sewer_data(
    config: dict,
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
        logger.info(f"Loaded {len(points_gdf)} sewer point features (crs={points_gdf.crs})")
    if lines_gdf is not None:
        logger.info(f"Loaded {len(lines_gdf)} sewer line features (crs={lines_gdf.crs})")

    return points_gdf, lines_gdf
