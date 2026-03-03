"""
Morphometric calculations for watershed analysis.

Provides functions to calculate watershed morphometric parameters
from flow network cells, compatible with Hydrolog's WatershedParameters.
"""

import logging

import numpy as np
from shapely.geometry import Polygon

from core.watershed import FlowCell

logger = logging.getLogger(__name__)


def calculate_perimeter_km(boundary: Polygon) -> float:
    """
    Calculate watershed perimeter from boundary polygon.

    Parameters
    ----------
    boundary : Polygon
        Watershed boundary polygon in EPSG:2180 (meters)

    Returns
    -------
    float
        Perimeter in kilometers

    Examples
    --------
    >>> perimeter = calculate_perimeter_km(boundary)
    >>> print(f"Perimeter: {perimeter:.2f} km")
    """
    return boundary.length / 1000.0


def calculate_watershed_length_km(
    cells: list[FlowCell],
    outlet: FlowCell,
) -> float:
    """
    Calculate watershed length as max distance from outlet.

    The watershed length is the longest straight-line distance
    from the outlet to any point in the watershed.

    Parameters
    ----------
    cells : list[FlowCell]
        All cells in the watershed
    outlet : FlowCell
        Outlet cell (pour point)

    Returns
    -------
    float
        Watershed length in kilometers

    Examples
    --------
    >>> length = calculate_watershed_length_km(cells, outlet)
    >>> print(f"Length: {length:.2f} km")
    """
    if not cells:
        return 0.0

    distances = [((c.x - outlet.x) ** 2 + (c.y - outlet.y) ** 2) ** 0.5 for c in cells]
    max_distance_m = max(distances)

    return max_distance_m / 1000.0


def calculate_elevation_stats(cells: list[FlowCell]) -> dict:
    """
    Calculate elevation statistics from watershed cells.

    Parameters
    ----------
    cells : list[FlowCell]
        All cells in the watershed

    Returns
    -------
    dict
        Dictionary with keys:
        - elevation_min_m: minimum elevation [m]
        - elevation_max_m: maximum elevation [m]
        - elevation_mean_m: area-weighted mean elevation [m]

    Examples
    --------
    >>> stats = calculate_elevation_stats(cells)
    >>> print(f"Relief: {stats['elevation_max_m'] - stats['elevation_min_m']:.0f} m")
    """
    if not cells:
        return {
            "elevation_min_m": 0.0,
            "elevation_max_m": 0.0,
            "elevation_mean_m": 0.0,
        }

    elevations = np.array([c.elevation for c in cells])
    areas = np.array([c.cell_area for c in cells])

    return {
        "elevation_min_m": float(np.min(elevations)),
        "elevation_max_m": float(np.max(elevations)),
        "elevation_mean_m": float(np.average(elevations, weights=areas)),
    }


def calculate_mean_slope(cells: list[FlowCell]) -> float:
    """
    Calculate area-weighted mean slope.

    Parameters
    ----------
    cells : list[FlowCell]
        All cells in the watershed (slope in percent)

    Returns
    -------
    float
        Mean slope in m/m (dimensionless)

    Notes
    -----
    Converts from percent (stored in DB) to m/m for Hydrolog compatibility.
    Cells with None slope are excluded from calculation.

    Examples
    --------
    >>> slope = calculate_mean_slope(cells)
    >>> print(f"Mean slope: {slope:.4f} m/m ({slope*100:.2f}%)")
    """
    valid = [(c.slope, c.cell_area) for c in cells if c.slope is not None]
    if not valid:
        logger.warning("No cells with valid slope data")
        return 0.0

    slopes, areas = zip(*valid, strict=False)
    slopes_array = np.array(slopes)
    areas_array = np.array(areas)

    mean_slope_percent = float(np.average(slopes_array, weights=areas_array))
    return mean_slope_percent / 100.0


def find_main_stream(
    cells: list[FlowCell],
    outlet: FlowCell,
    return_coords: bool = False,
) -> tuple[float, float] | tuple[float, float, list[tuple[float, float]]]:
    """
    Find main stream parameters using reverse trace algorithm.

    Traces upstream from outlet, always following the cell with highest
    flow accumulation. This identifies the main channel efficiently
    without iterating through all head cells.

    Parameters
    ----------
    cells : list[FlowCell]
        All cells in the watershed
    outlet : FlowCell
        Outlet cell (pour point)
    return_coords : bool, optional
        If True, also return list of (x, y) coordinates for the stream path

    Returns
    -------
    tuple[float, float] or tuple[float, float, list]
        (channel_length_km, channel_slope_m_per_m)
        or (channel_length_km, channel_slope_m_per_m, coords) if return_coords=True

    Notes
    -----
    Optimized algorithm (257x faster than original):
    1. Build upstream graph (cell -> upstream cells)
    2. Start at outlet, trace upstream following max accumulation
    3. Calculate length and slope of this single path

    The main stream is defined as the path with highest accumulated flow,
    which corresponds to the largest contributing area at each junction.

    Examples
    --------
    >>> length_km, slope = find_main_stream(cells, outlet)
    >>> print(f"Main stream: {length_km:.2f} km, slope {slope:.4f} m/m")

    >>> length_km, slope, coords = find_main_stream(cells, outlet, return_coords=True)
    >>> # coords can be used to create LineString for GIS export
    """
    if not cells:
        if return_coords:
            return (0.0, 0.0, [])
        return (0.0, 0.0)

    cell_by_id: dict[int, FlowCell] = {c.id: c for c in cells}

    # Build upstream graph: cell_id -> list of upstream cell_ids
    upstream_graph: dict[int, list[int]] = {}
    for c in cells:
        if c.downstream_id is not None:
            if c.downstream_id not in upstream_graph:
                upstream_graph[c.downstream_id] = []
            upstream_graph[c.downstream_id].append(c.id)

    # Trace upstream from outlet, always picking highest accumulation
    path_length_m = 0.0
    path_elevations: list[float] = [outlet.elevation]
    path_coords: list[tuple[float, float]] = [(outlet.x, outlet.y)]
    current_cell = outlet

    while True:
        upstream_ids = upstream_graph.get(current_cell.id, [])
        if not upstream_ids:
            break

        # Pick upstream cell with highest flow accumulation
        best_upstream = None
        best_acc = -1
        for uid in upstream_ids:
            ucell = cell_by_id.get(uid)
            if ucell and ucell.flow_accumulation > best_acc:
                best_acc = ucell.flow_accumulation
                best_upstream = ucell

        if best_upstream is None:
            break

        # Calculate distance between cells
        dist = (
            (current_cell.x - best_upstream.x) ** 2
            + (current_cell.y - best_upstream.y) ** 2
        ) ** 0.5
        path_length_m += dist
        path_elevations.append(best_upstream.elevation)
        path_coords.append((best_upstream.x, best_upstream.y))
        current_cell = best_upstream

    # Calculate slope (elevation difference / length)
    if len(path_elevations) >= 2 and path_length_m > 0:
        # Elevation diff: highest point (end of trace) - outlet (start)
        elev_diff = path_elevations[-1] - path_elevations[0]
        channel_slope = elev_diff / path_length_m
    else:
        channel_slope = 0.0

    channel_length_km = path_length_m / 1000.0

    logger.debug(
        f"Main stream found: {channel_length_km:.2f} km, "
        f"slope {channel_slope:.4f} m/m, {len(path_coords)} points"
    )

    if return_coords:
        return (channel_length_km, max(0.0, channel_slope), path_coords)
    return (channel_length_km, max(0.0, channel_slope))


def calculate_shape_indices(
    area_km2: float,
    perimeter_km: float,
    length_km: float,
) -> dict:
    """
    Calculate watershed shape indices.

    Parameters
    ----------
    area_km2 : float
        Watershed area [km2]
    perimeter_km : float
        Watershed perimeter [km]
    length_km : float
        Watershed length (max distance from outlet) [km]

    Returns
    -------
    dict
        Dictionary with keys:
        - compactness_coefficient: Gravelius compactness Kc = P / (2*sqrt(pi*A))
        - circularity_ratio: Miller circularity Rc = 4*pi*A / P^2
        - elongation_ratio: Schumm elongation Re = (2/L)*sqrt(A/pi)
        - form_factor: Horton form factor Ff = A / L^2
        - mean_width_km: mean width W = A / L [km]
    """
    result = {}

    if area_km2 <= 0 or perimeter_km <= 0 or length_km <= 0:
        return {
            "compactness_coefficient": None,
            "circularity_ratio": None,
            "elongation_ratio": None,
            "form_factor": None,
            "mean_width_km": None,
        }

    # Kc — Gravelius compactness coefficient
    # Kc = P / (2 * sqrt(pi * A)), Kc=1 for circle
    result["compactness_coefficient"] = round(
        perimeter_km / (2 * np.sqrt(np.pi * area_km2)), 4
    )

    # Rc — Miller circularity ratio
    # Rc = 4 * pi * A / P^2, Rc=1 for circle
    result["circularity_ratio"] = round(4 * np.pi * area_km2 / (perimeter_km**2), 4)

    # Re — Schumm elongation ratio
    # Re = (2/L) * sqrt(A/pi), Re=1 for circle
    result["elongation_ratio"] = round((2 / length_km) * np.sqrt(area_km2 / np.pi), 4)

    # Ff — Horton form factor
    # Ff = A / L^2
    result["form_factor"] = round(area_km2 / (length_km**2), 4)

    # W — mean width
    # W = A / L [km]
    result["mean_width_km"] = round(area_km2 / length_km, 4)

    return result


def calculate_relief_indices(
    elev_stats: dict,
    length_km: float,
) -> dict:
    """
    Calculate watershed relief indices.

    Parameters
    ----------
    elev_stats : dict
        Dictionary with elevation_min_m, elevation_max_m, elevation_mean_m
    length_km : float
        Watershed length [km]

    Returns
    -------
    dict
        Dictionary with keys:
        - relief_ratio: Rh = (Hmax - Hmin) / (L * 1000)
        - hypsometric_integral: HI = (Hmean - Hmin) / (Hmax - Hmin)
    """
    h_min = elev_stats.get("elevation_min_m", 0)
    h_max = elev_stats.get("elevation_max_m", 0)
    h_mean = elev_stats.get("elevation_mean_m", 0)
    relief = h_max - h_min

    result = {}

    # Rh — relief ratio
    if length_km > 0 and relief > 0:
        result["relief_ratio"] = round(relief / (length_km * 1000), 6)
    else:
        result["relief_ratio"] = None

    # HI — hypsometric integral
    if relief > 0:
        result["hypsometric_integral"] = round((h_mean - h_min) / relief, 4)
    else:
        result["hypsometric_integral"] = None

    return result


def calculate_hypsometric_curve(
    cells: list[FlowCell],
    n_bins: int = 20,
) -> list[dict]:
    """
    Calculate hypsometric curve (relative area vs relative height).

    Parameters
    ----------
    cells : list[FlowCell]
        All cells in the watershed
    n_bins : int
        Number of equal height bins (default: 20)

    Returns
    -------
    list[dict]
        List of {relative_height: float, relative_area: float} dicts,
        sorted from highest to lowest relative_height.
        relative_height and relative_area are both in [0, 1].
    """
    if not cells or n_bins <= 0:
        return []

    elevations = np.array([c.elevation for c in cells])
    areas = np.array([c.cell_area for c in cells])

    h_min = float(np.min(elevations))
    h_max = float(np.max(elevations))
    relief = h_max - h_min

    if relief <= 0:
        # Flat watershed — all area at relative height 0.5
        return [
            {"relative_height": 1.0, "relative_area": 0.0},
            {"relative_height": 0.0, "relative_area": 1.0},
        ]

    total_area = float(np.sum(areas))

    # Create bins from top (1.0) to bottom (0.0)
    bin_edges = np.linspace(0, 1, n_bins + 1)  # 0 to 1
    curve = []

    for i in range(len(bin_edges)):
        # relative_height threshold
        rh = 1.0 - bin_edges[i]
        # Absolute height threshold
        h_threshold = h_min + rh * relief
        # Area above this threshold
        area_above = float(np.sum(areas[elevations >= h_threshold]))
        relative_area = area_above / total_area

        curve.append(
            {
                "relative_height": round(rh, 4),
                "relative_area": round(relative_area, 4),
            }
        )

    return curve


def get_stream_stats_in_watershed(
    boundary_wkt: str,
    db_session,
) -> dict | None:
    """
    Get stream network statistics within a watershed boundary.

    Queries stream_network for BDOT10k (non-DEM-derived) segments that
    intersect the watershed boundary polygon. Uses ST_Intersection for
    accurate stream length calculation within the boundary.

    Parameters
    ----------
    boundary_wkt : str
        Watershed boundary as WKT polygon (EPSG:2180)
    db_session : Session
        SQLAlchemy database session

    Returns
    -------
    dict or None
        Dictionary with keys:
        - total_stream_length_km: total length of streams within boundary [km]
        - n_segments: number of stream segments
        - max_strahler_order: maximum Strahler stream order
        Returns None if no BDOT10k stream data exists in the area.
    """
    from sqlalchemy import text

    result = db_session.execute(
        text("""
            SELECT
                COALESCE(SUM(ST_Length(ST_Intersection(
                    geom,
                    ST_SetSRID(ST_GeomFromText(:wkt), 2180)
                ))), 0) AS total_length_m,
                COUNT(*) AS n_segments,
                COALESCE(MAX(strahler_order), 0) AS max_order
            FROM stream_network
            WHERE source != 'DEM_DERIVED'
              AND ST_Intersects(
                  geom,
                  ST_SetSRID(ST_GeomFromText(:wkt), 2180)
              )
        """),
        {"wkt": boundary_wkt},
    ).fetchone()

    if result is None or result[1] == 0:
        return None

    return {
        "total_stream_length_km": round(result[0] / 1000.0, 4),
        "n_segments": result[1],
        "max_strahler_order": result[2],
    }


def calculate_drainage_indices(
    stream_stats: dict,
    area_km2: float,
    relief_m: float,
) -> dict:
    """
    Calculate drainage network indices from stream statistics.

    Parameters
    ----------
    stream_stats : dict
        From get_stream_stats_in_watershed(), with keys:
        total_stream_length_km, n_segments, max_strahler_order
    area_km2 : float
        Watershed area [km2]
    relief_m : float
        Relief (Hmax - Hmin) [m]

    Returns
    -------
    dict
        Dictionary with keys:
        - drainage_density_km_per_km2: Dd = total_length / area
        - stream_frequency_per_km2: Fs = n_segments / area
        - ruggedness_number: Rn = (relief/1000) * Dd
        - max_strahler_order: max stream order
    """
    if area_km2 <= 0:
        return {
            "drainage_density_km_per_km2": None,
            "stream_frequency_per_km2": None,
            "ruggedness_number": None,
            "max_strahler_order": None,
        }

    total_length = stream_stats["total_stream_length_km"]
    n_segments = stream_stats["n_segments"]
    max_order = stream_stats["max_strahler_order"]

    dd = round(total_length / area_km2, 4)
    fs = round(n_segments / area_km2, 4)
    rn = round((relief_m / 1000.0) * dd, 4) if relief_m > 0 else None

    return {
        "drainage_density_km_per_km2": dd,
        "stream_frequency_per_km2": fs,
        "ruggedness_number": rn,
        "max_strahler_order": max_order,
    }


def build_morphometric_params(
    cells: list[FlowCell],
    boundary: Polygon,
    outlet: FlowCell,
    cn: int | None = None,
    include_stream_coords: bool = False,
    db=None,
    include_hypsometric_curve: bool = False,
) -> dict:
    """
    Build complete morphometric parameters dictionary.

    Creates a dictionary compatible with Hydrolog's WatershedParameters.from_dict().
    Optionally includes shape/relief/drainage indices and hypsometric curve.

    Parameters
    ----------
    cells : list[FlowCell]
        All cells in the watershed
    boundary : Polygon
        Watershed boundary polygon in EPSG:2180
    outlet : FlowCell
        Outlet cell (pour point)
    cn : int, optional
        SCS Curve Number (will be calculated separately if None)
    include_stream_coords : bool, optional
        If True, include main_stream_coords in output for GIS export
    db : Session, optional
        Database session for drainage network indices query
    include_hypsometric_curve : bool, optional
        If True, include hypsometric curve data (default: False)

    Returns
    -------
    dict
        Dictionary with all morphometric parameters, ready for
        WatershedParameters.from_dict()

    Examples
    --------
    >>> params = build_morphometric_params(cells, boundary, outlet, cn=72)
    >>> from hydrolog.morphometry import WatershedParameters
    >>> wp = WatershedParameters.from_dict(params)
    """
    elev_stats = calculate_elevation_stats(cells)

    # Get main stream with coordinates if requested
    if include_stream_coords:
        channel_length_km, channel_slope, stream_coords = find_main_stream(
            cells, outlet, return_coords=True
        )
    else:
        channel_length_km, channel_slope = find_main_stream(cells, outlet)
        stream_coords = None

    area_km2 = sum(c.cell_area for c in cells) / 1_000_000
    perimeter_km = calculate_perimeter_km(boundary)
    length_km = calculate_watershed_length_km(cells, outlet)

    params = {
        "area_km2": area_km2,
        "perimeter_km": perimeter_km,
        "length_km": length_km,
        "elevation_min_m": elev_stats["elevation_min_m"],
        "elevation_max_m": elev_stats["elevation_max_m"],
        "elevation_mean_m": elev_stats["elevation_mean_m"],
        "mean_slope_m_per_m": calculate_mean_slope(cells),
        "channel_length_km": (channel_length_km if channel_length_km > 0 else None),
        "channel_slope_m_per_m": (channel_slope if channel_slope > 0 else None),
        "cn": cn,
        "source": "Hydrograf",
        "crs": "EPSG:2180",
    }

    if include_stream_coords and stream_coords:
        params["main_stream_coords"] = stream_coords

    # Shape indices
    shape = calculate_shape_indices(area_km2, perimeter_km, length_km)
    params.update(shape)

    # Relief indices
    relief = calculate_relief_indices(elev_stats, length_km)
    params.update(relief)

    # Hypsometric curve (optional — can be large)
    if include_hypsometric_curve:
        params["hypsometric_curve"] = calculate_hypsometric_curve(cells)

    # Drainage network indices (requires DB with stream_network data)
    if db is not None:
        try:
            boundary_wkt = boundary.wkt
            stream_stats = get_stream_stats_in_watershed(boundary_wkt, db)
            if stream_stats is not None:
                relief_m = elev_stats["elevation_max_m"] - elev_stats["elevation_min_m"]
                drainage = calculate_drainage_indices(stream_stats, area_km2, relief_m)
                params.update(drainage)
        except Exception as e:
            logger.warning(f"Failed to get drainage indices: {e}")

    logger.info(
        f"Built morphometric params: "
        f"area={params['area_km2']:.2f} km2, "
        f"length={params['length_km']:.2f} km, "
        f"relief="
        f"{params['elevation_max_m'] - params['elevation_min_m']:.0f} m"
    )

    return params
