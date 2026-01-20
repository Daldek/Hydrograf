"""
Morphometric calculations for watershed analysis.

Provides functions to calculate watershed morphometric parameters
from flow network cells, compatible with Hydrolog's WatershedParameters.
"""

import logging
from typing import Optional

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

    distances = [
        ((c.x - outlet.x) ** 2 + (c.y - outlet.y) ** 2) ** 0.5
        for c in cells
    ]
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

    slopes, areas = zip(*valid)
    slopes_array = np.array(slopes)
    areas_array = np.array(areas)

    mean_slope_percent = float(np.average(slopes_array, weights=areas_array))
    return mean_slope_percent / 100.0


def find_main_stream(
    cells: list[FlowCell],
    outlet: FlowCell,
) -> tuple[float, float]:
    """
    Find main stream parameters using longest path algorithm.

    Traces the longest flow path from watershed divide to outlet
    following the flow network graph.

    Parameters
    ----------
    cells : list[FlowCell]
        All cells in the watershed
    outlet : FlowCell
        Outlet cell (pour point)

    Returns
    -------
    tuple[float, float]
        (channel_length_km, channel_slope_m_per_m)

    Notes
    -----
    Uses a graph traversal approach:
    1. Build upstream graph (cell -> upstream cells)
    2. Find all head cells (no upstream neighbors)
    3. For each head, trace path to outlet, calculating length
    4. Return parameters of longest path

    Examples
    --------
    >>> length_km, slope = find_main_stream(cells, outlet)
    >>> print(f"Main stream: {length_km:.2f} km, slope {slope:.4f} m/m")
    """
    if not cells:
        return (0.0, 0.0)

    cell_by_id: dict[int, FlowCell] = {c.id: c for c in cells}

    upstream_graph: dict[int, list[int]] = {}
    for c in cells:
        if c.downstream_id is not None:
            if c.downstream_id not in upstream_graph:
                upstream_graph[c.downstream_id] = []
            upstream_graph[c.downstream_id].append(c.id)

    cells_with_upstream = set(upstream_graph.keys())
    all_cell_ids = set(cell_by_id.keys())
    head_cells = all_cell_ids - cells_with_upstream

    if not head_cells:
        max_elev = max(c.elevation for c in cells)
        head_cells = {c.id for c in cells if c.elevation == max_elev}

    longest_length_m = 0.0
    longest_path_elevations: list[float] = []

    for head_id in head_cells:
        path_length_m = 0.0
        path_elevations = []
        current_id = head_id

        while current_id is not None:
            current_cell = cell_by_id.get(current_id)
            if current_cell is None:
                break

            path_elevations.append(current_cell.elevation)

            if current_cell.downstream_id is not None:
                downstream = cell_by_id.get(current_cell.downstream_id)
                if downstream is not None:
                    dist = (
                        (current_cell.x - downstream.x) ** 2
                        + (current_cell.y - downstream.y) ** 2
                    ) ** 0.5
                    path_length_m += dist
                    current_id = current_cell.downstream_id
                else:
                    break
            else:
                break

        if path_length_m > longest_length_m:
            longest_length_m = path_length_m
            longest_path_elevations = path_elevations

    if len(longest_path_elevations) >= 2 and longest_length_m > 0:
        elev_diff = longest_path_elevations[0] - longest_path_elevations[-1]
        channel_slope = elev_diff / longest_length_m
    else:
        channel_slope = 0.0

    channel_length_km = longest_length_m / 1000.0

    logger.debug(
        f"Main stream found: {channel_length_km:.2f} km, "
        f"slope {channel_slope:.4f} m/m"
    )

    return (channel_length_km, max(0.0, channel_slope))


def build_morphometric_params(
    cells: list[FlowCell],
    boundary: Polygon,
    outlet: FlowCell,
    cn: Optional[int] = None,
) -> dict:
    """
    Build complete morphometric parameters dictionary.

    Creates a dictionary compatible with Hydrolog's WatershedParameters.from_dict().

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
    channel_length_km, channel_slope = find_main_stream(cells, outlet)

    params = {
        "area_km2": sum(c.cell_area for c in cells) / 1_000_000,
        "perimeter_km": calculate_perimeter_km(boundary),
        "length_km": calculate_watershed_length_km(cells, outlet),
        "elevation_min_m": elev_stats["elevation_min_m"],
        "elevation_max_m": elev_stats["elevation_max_m"],
        "elevation_mean_m": elev_stats["elevation_mean_m"],
        "mean_slope_m_per_m": calculate_mean_slope(cells),
        "channel_length_km": channel_length_km if channel_length_km > 0 else None,
        "channel_slope_m_per_m": channel_slope if channel_slope > 0 else None,
        "cn": cn,
        "source": "Hydrograf",
        "crs": "EPSG:2180",
    }

    logger.info(
        f"Built morphometric params: area={params['area_km2']:.2f} km2, "
        f"length={params['length_km']:.2f} km, "
        f"relief={params['elevation_max_m'] - params['elevation_min_m']:.0f} m"
    )

    return params
