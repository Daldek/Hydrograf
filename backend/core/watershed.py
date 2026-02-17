"""
Watershed boundary construction and FlowCell dataclass.

This module contains boundary-building functions (build_boundary,
build_boundary_polygonize) and the FlowCell dataclass. CatchmentGraph-based
watershed delineation logic is in ``core.watershed_service``.
"""

import logging
from dataclasses import dataclass

import numpy as np
import shapely
from affine import Affine
from rasterio.features import shapes
from shapely.geometry import MultiPoint, Point, Polygon, shape

logger = logging.getLogger(__name__)


@dataclass
class FlowCell:
    """
    Represents a cell with flow attributes (legacy dataclass).

    Attributes
    ----------
    id : int
        Unique cell identifier
    x : float
        X coordinate in EPSG:2180 (PL-1992)
    y : float
        Y coordinate in EPSG:2180 (PL-1992)
    elevation : float
        Elevation in meters above sea level
    flow_accumulation : int
        Number of cells flowing into this cell
    slope : float | None
        Terrain slope in percent
    downstream_id : int | None
        ID of downstream cell (None for outlets)
    cell_area : float
        Cell area in square meters
    is_stream : bool
        Whether cell is part of stream network
    """

    id: int
    x: float
    y: float
    elevation: float
    flow_accumulation: int
    slope: float | None
    downstream_id: int | None
    cell_area: float
    is_stream: bool


def build_boundary_polygonize(
    cells: list[FlowCell],
    cell_size: float = 1.0,
) -> Polygon:
    """
    Build watershed boundary by raster polygonization.

    Creates a binary raster mask from cell positions and converts it to
    a polygon using rasterio. This produces an accurate boundary that
    follows actual cell edges, similar to GIS software.

    Parameters
    ----------
    cells : list[FlowCell]
        List of cells in watershed
    cell_size : float, optional
        Cell size in meters, default 1.0 (matches NMT 1m resolution)

    Returns
    -------
    Polygon
        Watershed boundary polygon in EPSG:2180

    Raises
    ------
    ValueError
        If cells list is empty or has less than 3 cells

    Examples
    --------
    >>> boundary = build_boundary_polygonize(cells, cell_size=1.0)
    >>> print(f"Boundary area: {boundary.area / 1e6:.2f} km²")
    """
    if len(cells) < 3:
        raise ValueError(f"Need at least 3 cells to build boundary, got {len(cells)}")

    # 1. Determine extent from cell coordinates
    xs = [c.x for c in cells]
    ys = [c.y for c in cells]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    # 2. Add buffer of one cell around the extent
    min_x -= cell_size
    max_x += cell_size
    min_y -= cell_size
    max_y += cell_size

    # 3. Create binary raster
    cols = int(round((max_x - min_x) / cell_size)) + 1
    rows = int(round((max_y - min_y) / cell_size)) + 1
    raster = np.zeros((rows, cols), dtype=np.uint8)

    # 4. Mark watershed cells in raster
    for c in cells:
        col = int(round((c.x - min_x) / cell_size))
        row = int(round((max_y - c.y) / cell_size))
        # Bounds check
        if 0 <= row < rows and 0 <= col < cols:
            raster[row, col] = 1

    # 5. Define affine transform (top-left corner, cell size)
    transform = Affine.translation(
        min_x - cell_size / 2, max_y + cell_size / 2
    ) * Affine.scale(cell_size, -cell_size)

    # 6. Polygonize raster
    polygon_generator = shapes(raster, mask=raster == 1, transform=transform)

    # 7. Collect all polygons with value 1 (watershed)
    polygons = []
    for geom, value in polygon_generator:
        if value == 1:
            poly = shape(geom)
            if poly.is_valid and not poly.is_empty:
                polygons.append(poly)

    if not polygons:
        logger.warning(
            "Polygonization produced no polygons, falling back to convex hull"
        )
        points = MultiPoint([Point(c.x, c.y) for c in cells])
        return points.convex_hull

    # 8. Union all polygons (handles multipart watersheds)
    if len(polygons) == 1:
        boundary = polygons[0]
    else:
        from shapely.ops import unary_union

        boundary = unary_union(polygons)

    # 9. Extract largest polygon if result is MultiPolygon
    if boundary.geom_type == "MultiPolygon":
        boundary = max(boundary.geoms, key=lambda p: p.area)

    logger.debug(f"Built polygonized boundary with area {boundary.area / 1e6:.4f} km²")

    return boundary


def build_boundary(
    cells: list[FlowCell],
    method: str = "polygonize",
    cell_size: float = 1.0,
) -> Polygon:
    """
    Build watershed boundary polygon from cells.

    Creates a boundary polygon that encompasses all cells in the watershed.

    Parameters
    ----------
    cells : list[FlowCell]
        List of cells in watershed
    method : str, optional
        Boundary method:
        - 'polygonize' (default): raster polygonization, accurate boundary
        - 'convex': ConvexHull, fast but approximate
        - 'concave': ConcaveHull, tighter fit than convex
    cell_size : float, optional
        Cell size in meters for polygonize method, default 1.0

    Returns
    -------
    Polygon
        Watershed boundary polygon in EPSG:2180

    Raises
    ------
    ValueError
        If method is invalid or cells list has less than 3 cells

    Examples
    --------
    >>> boundary = build_boundary(cells, method='polygonize')
    >>> print(f"Boundary area: {boundary.area / 1e6:.2f} km²")
    """
    if len(cells) < 3:
        raise ValueError(f"Need at least 3 cells to build boundary, got {len(cells)}")

    if method == "polygonize":
        return build_boundary_polygonize(cells, cell_size=cell_size)

    # Create MultiPoint from cell centroids
    points = MultiPoint([Point(c.x, c.y) for c in cells])

    if method == "convex":
        boundary = points.convex_hull
    elif method == "concave":
        # ConcaveHull available in Shapely 2.0+
        # ratio parameter controls the "tightness" of the hull
        boundary = shapely.concave_hull(points, ratio=0.3)
    else:
        raise ValueError(
            f"Unknown method: '{method}'. Use 'polygonize', 'convex' or 'concave'"
        )

    # Handle edge case where hull degenerates to LineString
    if boundary.geom_type == "LineString":
        logger.warning("Boundary degenerated to LineString, buffering to Polygon")
        boundary = boundary.buffer(1.0)  # 1 meter buffer

    logger.debug(f"Built {method} boundary with area {boundary.area / 1e6:.4f} km²")

    return boundary


def calculate_watershed_area_km2(cells: list[FlowCell]) -> float:
    """
    Calculate total watershed area from cells.

    Sums the cell_area of all cells and converts to square kilometers.

    Parameters
    ----------
    cells : list[FlowCell]
        List of cells in watershed

    Returns
    -------
    float
        Total area in square kilometers

    Examples
    --------
    >>> area = calculate_watershed_area_km2(cells)
    >>> print(f"Watershed area: {area:.2f} km²")
    """
    if not cells:
        return 0.0

    total_area_m2 = sum(c.cell_area for c in cells)
    area_km2 = total_area_m2 / 1_000_000

    return area_km2
