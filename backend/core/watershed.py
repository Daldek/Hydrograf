"""
Watershed delineation core logic.

Provides functions for finding stream outlet, traversing flow network upstream,
and constructing watershed boundary polygon.
"""

import logging
from dataclasses import dataclass

import numpy as np
import shapely
from affine import Affine
from rasterio.features import shapes
from shapely.geometry import MultiPoint, Point, Polygon, shape
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Maximum cells for safety limit
MAX_CELLS_DEFAULT = 10_000_000

# Maximum distance to search for stream [m]
MAX_STREAM_DISTANCE_M = 1000.0

# Maximum recursion depth for upstream traversal
MAX_RECURSION_DEPTH = 10000


@dataclass
class FlowCell:
    """
    Represents a cell in flow_network table.

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


def find_nearest_stream(
    point: Point,
    db: Session,
    max_distance_m: float = MAX_STREAM_DISTANCE_M,
) -> FlowCell | None:
    """
    Find the nearest stream cell to a given point.

    Uses spatial index (GIST) for efficient search within maximum distance.

    Parameters
    ----------
    point : Point
        Query point in EPSG:2180 (PL-1992)
    db : Session
        SQLAlchemy database session
    max_distance_m : float, optional
        Maximum search distance in meters, default 1000

    Returns
    -------
    FlowCell | None
        Nearest stream cell, or None if not found within distance

    Examples
    --------
    >>> from shapely.geometry import Point
    >>> point = Point(500000, 600000)
    >>> cell = find_nearest_stream(point, db)
    >>> if cell:
    ...     print(f"Found stream at elevation {cell.elevation} m")
    """
    query = text("""
        SELECT
            id,
            ST_X(geom) as x,
            ST_Y(geom) as y,
            elevation,
            flow_accumulation,
            slope,
            downstream_id,
            cell_area,
            is_stream,
            ST_Distance(geom, ST_SetSRID(ST_Point(:x, :y), 2180)) as distance
        FROM flow_network
        WHERE is_stream = TRUE
          AND ST_DWithin(geom, ST_SetSRID(ST_Point(:x, :y), 2180), :max_dist)
        ORDER BY distance
        LIMIT 1
    """)

    result = db.execute(
        query,
        {"x": point.x, "y": point.y, "max_dist": max_distance_m},
    ).fetchone()

    if result is None:
        logger.warning(
            f"No stream found within {max_distance_m}m of "
            f"({point.x:.1f}, {point.y:.1f})"
        )
        return None

    logger.debug(f"Found stream cell {result.id} at distance {result.distance:.1f}m")

    return FlowCell(
        id=result.id,
        x=result.x,
        y=result.y,
        elevation=result.elevation,
        flow_accumulation=result.flow_accumulation,
        slope=result.slope,
        downstream_id=result.downstream_id,
        cell_area=result.cell_area,
        is_stream=result.is_stream,
    )


def traverse_upstream(
    outlet_id: int,
    db: Session,
    max_cells: int = MAX_CELLS_DEFAULT,
) -> list[FlowCell]:
    """
    Traverse flow network upstream from outlet using recursive CTE.

    Finds all cells that drain to the outlet cell, effectively
    delineating the watershed boundary.

    Parameters
    ----------
    outlet_id : int
        ID of outlet cell (starting point)
    db : Session
        SQLAlchemy database session
    max_cells : int, optional
        Safety limit for maximum cells, default 10,000,000

    Returns
    -------
    list[FlowCell]
        All cells in the watershed (including outlet)

    Raises
    ------
    ValueError
        If watershed exceeds max_cells limit

    Examples
    --------
    >>> cells = traverse_upstream(outlet_id=123, db=db)
    >>> print(f"Watershed has {len(cells)} cells")
    """
    # Recursive CTE for upstream traversal
    # Follows the downstream_id links in reverse direction
    query = text("""
        WITH RECURSIVE upstream AS (
            -- Base case: outlet cell
            SELECT
                id,
                ST_X(geom) as x,
                ST_Y(geom) as y,
                elevation,
                flow_accumulation,
                slope,
                downstream_id,
                cell_area,
                is_stream,
                1 as depth
            FROM flow_network
            WHERE id = :outlet_id

            UNION ALL

            -- Recursive case: find cells where downstream_id = current cell id
            SELECT
                f.id,
                ST_X(f.geom) as x,
                ST_Y(f.geom) as y,
                f.elevation,
                f.flow_accumulation,
                f.slope,
                f.downstream_id,
                f.cell_area,
                f.is_stream,
                u.depth + 1
            FROM flow_network f
            INNER JOIN upstream u ON f.downstream_id = u.id
            WHERE u.depth < :max_depth
        )
        SELECT id, x, y, elevation, flow_accumulation, slope,
               downstream_id, cell_area, is_stream
        FROM upstream
    """)

    results = db.execute(
        query,
        {"outlet_id": outlet_id, "max_depth": MAX_RECURSION_DEPTH},
    ).fetchall()

    if len(results) > max_cells:
        logger.error(
            f"Watershed too large: {len(results):,} cells > {max_cells:,} limit"
        )
        raise ValueError(
            f"Watershed too large: {len(results):,} cells exceeds limit of {max_cells:,}"
        )

    logger.info(f"Traversed {len(results):,} cells upstream from outlet {outlet_id}")

    return [
        FlowCell(
            id=r.id,
            x=r.x,
            y=r.y,
            elevation=r.elevation,
            flow_accumulation=r.flow_accumulation,
            slope=r.slope,
            downstream_id=r.downstream_id,
            cell_area=r.cell_area,
            is_stream=r.is_stream,
        )
        for r in results
    ]


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
