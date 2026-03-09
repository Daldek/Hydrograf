"""Boundary file loading, validation and transformation for analysis area definition."""

import logging
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from pyproj import CRS
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_MB = 50
MAX_ZIP_FILES = 20
MAX_ZIP_EXTRACTED_MB = 100


def load_boundary(file_path: Path, layer: str | None = None) -> BaseGeometry:
    """Load vector file, validate, union features -> single WGS84 polygon.

    Accepts: SHP, GPKG, GeoJSON. SHP as .zip containing .shp+.shx+.dbf+.prj.
    Multi-feature files are unioned into a single polygon.
    CRS is auto-detected; if missing, WGS84 is assumed with a warning.

    Args:
        file_path: Path to vector file (.gpkg, .geojson, .json, .zip with .shp)
        layer: Layer name for multi-layer files (GPKG). Default: first layer.

    Returns:
        Single Polygon or MultiPolygon geometry in WGS84.

    Raises:
        FileNotFoundError: If file doesn't exist.
        ValueError: If file is too large, contains non-polygon geometries,
                     or has no valid features.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Boundary file not found: {file_path}")

    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        raise ValueError(
            f"File too large: {file_size_mb:.1f} MB (max {MAX_FILE_SIZE_MB} MB)"
        )

    # Handle ZIP (SHP archive)
    if file_path.suffix.lower() == ".zip":
        return _load_from_zip(file_path, layer)

    return _load_and_process(file_path, layer)


def _validate_zip_entries(zf: zipfile.ZipFile) -> None:
    """Validate ZIP entries for security.

    Checks file count, total size, path traversal, symlinks.

    Raises:
        ValueError: If any security check fails.
    """
    entries = zf.infolist()
    if len(entries) > MAX_ZIP_FILES:
        raise ValueError(
            f"ZIP has too many files: {len(entries)} (max {MAX_ZIP_FILES})"
        )

    total_size = sum(e.file_size for e in entries)
    if total_size / (1024 * 1024) > MAX_ZIP_EXTRACTED_MB:
        raise ValueError(
            f"ZIP extracted size too large: {total_size / (1024 * 1024):.1f} MB "
            f"(max {MAX_ZIP_EXTRACTED_MB} MB)"
        )

    for entry in entries:
        if entry.is_dir():
            continue
        # Check for path traversal
        if ".." in entry.filename or entry.filename.startswith("/"):
            raise ValueError(f"Suspicious path in ZIP: {entry.filename}")
        # Check for symlinks (external_attr upper 16 bits)
        if (entry.external_attr >> 16) & 0o120000 == 0o120000:
            raise ValueError(f"Symlink in ZIP not allowed: {entry.filename}")


def _load_from_zip(zip_path: Path, layer: str | None = None) -> BaseGeometry:
    """Extract ZIP containing SHP and load it."""
    with zipfile.ZipFile(zip_path, "r") as zf:
        _validate_zip_entries(zf)

        with tempfile.TemporaryDirectory() as tmpdir:
            zf.extractall(tmpdir)
            # Find .shp file
            shp_files = list(Path(tmpdir).rglob("*.shp"))
            if not shp_files:
                raise ValueError("No .shp file found in ZIP archive")
            if len(shp_files) > 1:
                logger.warning(
                    "Multiple .shp files in ZIP, using first: %s", shp_files[0].name
                )
            return _load_and_process(shp_files[0], layer)


def _load_and_process(file_path: Path, layer: str | None = None) -> BaseGeometry:
    """Load file with geopandas, filter to polygons, union, reproject to WGS84."""
    read_kwargs = {}
    if layer is not None:
        read_kwargs["layer"] = layer

    gdf = gpd.read_file(file_path, **read_kwargs)

    if gdf.empty:
        raise ValueError(f"No features found in: {file_path}")

    # CRS handling
    if gdf.crs is None:
        logger.warning(
            "No CRS detected in %s, assuming WGS84 (EPSG:4326)", file_path.name
        )
        gdf = gdf.set_crs("EPSG:4326")

    # Filter to polygon geometries only
    polygon_mask = gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"])
    if not polygon_mask.any():
        geom_types = gdf.geometry.geom_type.unique().tolist()
        raise ValueError(
            f"No polygon geometries found. File contains: {geom_types}"
        )

    if not polygon_mask.all():
        n_dropped = (~polygon_mask).sum()
        logger.warning(
            "Dropped %d non-polygon features from %s", n_dropped, file_path.name
        )
        gdf = gdf[polygon_mask]

    # Reproject to WGS84 if needed
    if gdf.crs and not CRS(gdf.crs).equals(CRS("EPSG:4326")):
        logger.info("Reprojecting from %s to EPSG:4326", gdf.crs)
        gdf = gdf.to_crs("EPSG:4326")

    # Union all features
    geom = unary_union(gdf.geometry)

    # Validate and fix
    if not geom.is_valid:
        logger.warning("Invalid geometry detected, applying buffer(0) fix")
        geom = make_valid(geom)

    if geom.is_empty:
        raise ValueError("Resulting geometry is empty after union")

    return geom


def boundary_to_bbox_wgs84(
    geom: BaseGeometry,
) -> tuple[float, float, float, float]:
    """Return (min_lon, min_lat, max_lon, max_lat) from geometry bounds.

    Geometry must be in WGS84 (EPSG:4326).
    """
    return geom.bounds  # (minx, miny, maxx, maxy)


def boundary_to_bbox_2180(
    geom: BaseGeometry,
) -> tuple[float, float, float, float]:
    """Reproject geometry to EPSG:2180 and return bbox.

    Args:
        geom: Geometry in WGS84 (EPSG:4326).

    Returns:
        (minx, miny, maxx, maxy) in EPSG:2180.
    """
    gdf = gpd.GeoDataFrame(geometry=[geom], crs="EPSG:4326")
    gdf_2180 = gdf.to_crs("EPSG:2180")
    return tuple(gdf_2180.total_bounds)


def validate_boundary_file(file_path: Path) -> dict:
    """Validate boundary file and return metadata.

    Args:
        file_path: Path to vector file.

    Returns:
        Dict with keys: crs, n_features, n_layers, area_km2, bbox_wgs84.

    Raises:
        FileNotFoundError: If file doesn't exist.
        ValueError: If file is invalid or unreadable.
    """
    import shutil as _shutil

    import fiona

    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Boundary file not found: {file_path}")

    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    if file_size_mb > MAX_FILE_SIZE_MB:
        raise ValueError(
            f"File too large: {file_size_mb:.1f} MB (max {MAX_FILE_SIZE_MB} MB)"
        )

    # Detect layers
    actual_path = file_path
    temp_dir = None

    try:
        if file_path.suffix.lower() == ".zip":
            temp_dir = tempfile.mkdtemp()
            with zipfile.ZipFile(file_path, "r") as zf:
                _validate_zip_entries(zf)
                zf.extractall(temp_dir)
            shp_files = list(Path(temp_dir).rglob("*.shp"))
            if not shp_files:
                raise ValueError("No .shp file found in ZIP")
            actual_path = shp_files[0]

        layers = fiona.listlayers(actual_path)
        n_layers = len(layers)

        # Load and get stats
        geom = load_boundary(file_path)
        bbox_wgs84 = boundary_to_bbox_wgs84(geom)

        # Calculate area in km2 using EPSG:2180
        gdf = gpd.GeoDataFrame(geometry=[geom], crs="EPSG:4326")
        gdf_2180 = gdf.to_crs("EPSG:2180")
        area_km2 = gdf_2180.geometry.area.iloc[0] / 1_000_000

        # Read original CRS and feature count
        gdf_orig = gpd.read_file(actual_path)
        crs_str = str(gdf_orig.crs) if gdf_orig.crs else "unknown"
        n_features = len(gdf_orig)

        return {
            "crs": crs_str,
            "n_features": n_features,
            "n_layers": n_layers,
            "area_km2": round(area_km2, 2),
            "bbox_wgs84": bbox_wgs84,
        }
    finally:
        if temp_dir:
            _shutil.rmtree(temp_dir, ignore_errors=True)
