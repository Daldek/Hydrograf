"""
A network of subcatchments, reaches and junctions delineated at control points.

ADR-080 and the plan ``docs/plans/2026-11-10-network-delineation.md`` (D2, D6 to
D11); the tree of the network is ``core.network_tree``'s. The closing section A and
the points of the request snap to the nearest stream cell of the request's network
within NETWORK_SNAP_M (D2). Their tree names the elements, made of the units of the
catchment graph (``DEFAULT_THRESHOLD_M2``) and of the parts of the units that hold a
control point. One window of the saved rasters over A's catchment (D7, at most
NETWORK_MAX_WINDOW_CELLS cells) gives the element raster: the labels of the units
through a table unit -> element, the units of the control points split by pyflwdir
basins with an outlet at each control point and at the unit's outlet cell (D6). The
elements must add up to A's catchment counted from the graph (D11). Each element is
measured from its cells with ``core.cell_parameters``, giving the panel's parameters
(a ``WatershedResponse``, D8); the boundaries are one coverage of all elements
simplified together (D9); each reach gets the difference of the flow distances of its
ends as its length, the NMT at its ends for its slope and a check length along the
BDOT10k lines (D10). No flow directions are computed: the rasters are the pipeline's.
"""

import logging
import math
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal

import numba
import numpy as np
import pyflwdir
import rasterio
import shapely
from rasterio.features import shapes
from rasterio.transform import Affine
from rasterio.windows import Window
from shapely.geometry import LineString, MultiPolygon, Point, mapping
from shapely.geometry.base import BaseGeometry
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.catchment_graph import CatchmentGraph, hypsometric_curve
from core.cell_parameters import (
    INTERMEDIATE_SUFFIXES,
    CellWindow,
    PipelineRasters,
    baseline_m,
    channel_measures,
    d8_from_saved_flowdir,
    flow_path_parameters,
    main_channel,
    read_cells,
    terrain_of,
)
from core.config import Settings, get_settings
from core.constants import (
    DEFAULT_THRESHOLD_M2,
    HYDROGRAPH_AREA_LIMIT_KM2,
    M2_PER_KM2,
    M_PER_KM,
)
from core.db_bulk import BDOT_BUFFER_M
from core.divide_flow_path import path_coords
from core.errors import (
    InternalError,
    NotFoundError,
    StoreUnavailableError,
    UnsupportedError,
)
from core.hydrology import D8_DIRECTIONS
from core.morphometry import calculate_shape_indices
from core.network_tree import (
    MOUTH_TOLERANCE_M,
    ControlPoint,
    Junction,
    NetworkTree,
    Place,
    Reach,
    Subcatchment,
    UnitHead,
    UnitOutlet,
    build_network_tree,
)
from core.precipitation import thiessen_cells
from core.raster_io import cells_window, read_window
from core.raster_service import WINDOW_MARGIN_M
from core.watershed_service import (
    build_hsg_stats,
    build_land_cover_stats,
    catchments_bounds,
    compute_watershed_length,
    flow_path_geojson,
)
from core.zonal_stats import ZonalSummary, zonal_summary
from models.schemas import (
    HypsometricPoint,
    MorphometricParameters,
    OutletInfo,
    PmaxtpGridCell,
    WatershedResponse,
)
from utils.geometry import transform_geometry_pl1992_to_wgs84, transform_pl1992_to_wgs84

logger = logging.getLogger(__name__)

# A point snaps to the nearest stream cell of the request's network within this
# distance of the click (D2) [m]
NETWORK_SNAP_M = 100.0
# Largest window of the rasters over A's catchment [cells] (D7): 22 bytes a cell for
# the six rasters and 2 for the element raster, about 1.4 GB; production's whole grid
# has 58.6 M cells
NETWORK_MAX_WINDOW_CELLS = 60_000_000
# The slope of a reach whose NMT does not fall (D10): Hydrolog refuses a slope that
# is not positive [m/m]
MIN_REACH_SLOPE_M_PER_M = 0.0001
# A reach shorter than this is a notice (ADR-080, D10a): Muskingum-Cunge may find no
# division of it that keeps its weights non-negative at a usable time step [m]
SHORT_REACH_M = 200.0
# Tolerance of the simplification of the coverage of the elements (D9) [m]
COVERAGE_TOLERANCE_M = 5.0
# Spacing of the samples of a reach's line for its BDOT10k check length (D10) [m]
REACH_SAMPLE_M = 10.0
# The panel queries the land cover and the soils of a watershed larger than 5 km²
# with its boundary simplified by 20 m (api.endpoints.watershed)
_LAND_COVER_SIMPLIFY_ABOVE_KM2 = 5.0
_LAND_COVER_SIMPLIFY_M = 20.0
# A side of the window that A's catchment touches moves out by half the size of the
# window, by at least this many cells (as core.raster_service does)
_MIN_GROWTH_CELLS = 64
# The rasters of D7, by their name in PipelineRasters, and the NMT of the reaches
_RASTERS = {
    **INTERMEDIATE_SUFFIXES,
    "labels": f"10_subcatchments_{DEFAULT_THRESHOLD_M2}",
}
_NMT = "01_dem"

_BDOT_LINES = text(
    "SELECT ST_AsBinary(geom) AS geom FROM bdot_streams "
    "WHERE ST_DWithin(geom, ST_GeomFromWKB(:line, 2180), :buffer_m)"
)


@dataclass(frozen=True)
class Click:
    """A point of the request: its id and where it was clicked.

    Attributes
    ----------
    point_id : str
        Its id in the request.
    x, y : float
        Easting and northing, EPSG:2180 [m].
    """

    point_id: str
    x: float
    y: float


@dataclass(frozen=True)
class NetworkPoint:
    """A control point where it snapped (D2) and its node.

    Attributes
    ----------
    point_id : str
        Its id in the request.
    latitude, longitude : float
        Centre of its cell, after the mouth rule (WGS84).
    snap_distance_m : float
        Distance from the click to that centre [m].
    at_mouth : bool
        The mouth rule moved it (D3).
    node : str
        Its subcatchment when no point lies above it, else its junction.
    """

    point_id: str
    latitude: float
    longitude: float
    snap_distance_m: float
    at_mouth: bool
    node: str


@dataclass(frozen=True)
class NetworkSubcatchment:
    """An element of the network with its parameters (D8).

    Attributes
    ----------
    subcatchment : Subcatchment
        Its place in the tree.
    area_km2 : float
        Its area exact to the cell [km², 6 decimals].
    boundary_2180 : BaseGeometry
        Its part of the coverage (D9), EPSG:2180.
    watershed : WatershedResponse
        The panel's parameters, as for a delineated watershed.
    """

    subcatchment: Subcatchment
    area_km2: float
    boundary_2180: BaseGeometry
    watershed: WatershedResponse


@dataclass(frozen=True)
class NetworkReach:
    """A reach with its length, slope and check length (D10).

    Attributes
    ----------
    reach : Reach
        Its place in the tree.
    length_km : float
        Flow distance of its upper end less that of its lower end [km].
    slope_m_per_m : float
        Fall of the NMT between its ends over its length, MIN_REACH_SLOPE_M_PER_M
        where the NMT does not fall [m/m].
    slope_method : {"nmt", "minimum"}
        Where the slope comes from.
    upstream_elevation_m, downstream_elevation_m : float or None
        The NMT at its ends [m], None without NMT data.
    vector_length_km : float or None
        Its length along the BDOT10k lines, None where a sample of its line has no
        line within BDOT_BUFFER_M.
    line_2180 : list[tuple[float, float]]
        The centres of its D8 cells, upper end first (``path_coords``), EPSG:2180.
    """

    reach: Reach
    length_km: float
    slope_m_per_m: float
    slope_method: Literal["nmt", "minimum"]
    upstream_elevation_m: float | None
    downstream_elevation_m: float | None
    vector_length_km: float | None
    line_2180: list[tuple[float, float]]


@dataclass(frozen=True)
class NetworkJunction:
    """A junction and the centre of its cell (WGS84)."""

    junction: Junction
    latitude: float
    longitude: float


@dataclass(frozen=True)
class ReachNotice:
    """A reach shorter than SHORT_REACH_M or of the minimum slope (D10a).

    Attributes
    ----------
    reach : str
        Its id.
    length_m : float
        Its length [m].
    slope_minimum : bool
        Its NMT does not fall: its slope is MIN_REACH_SLOPE_M_PER_M.
    upper_point : str or None
        The control point at its upper end; None at a confluence.
    lower : str
        The junction it flows into.
    move_to : tuple[float, float] or None
        Latitude and longitude of the centre of the cell above that junction on the
        reach's branch (WGS84): the upper point placed there is at the mouth (D3) and
        enters the junction directly. None unless the upper end is a control point
        and the junction a confluence.
    """

    reach: str
    length_m: float
    slope_minimum: bool
    upper_point: str | None
    lower: str
    move_to: tuple[float, float] | None


@dataclass(frozen=True)
class Network:
    """A network of subcatchments, reaches and junctions (ADR-080).

    Attributes
    ----------
    threshold_m2 : int
        The network the points snapped to [m²].
    area_km2 : float
        A's catchment from the graph's units, less the part of A's unit below A
        (D11) [km², 6 decimals].
    elements_km2 : float
        The cells of the elements [km², 6 decimals]: equal to ``area_km2``.
    boundary_2180 : BaseGeometry
        A's boundary, the union of the elements (EPSG:2180).
    points : tuple[NetworkPoint, ...]
        A, then the points in the order of the request.
    subcatchments : tuple[NetworkSubcatchment, ...]
        ``Z1``, ``Z2``, …
    reaches : tuple[NetworkReach, ...]
        ``R1``, ``R2``, …
    junctions : tuple[NetworkJunction, ...]
        ``J1``, ``J2``, …
    order : tuple[str, ...]
        The nodes in the order of D15, the outlet ``OUT`` last.
    reach_notices : tuple[ReachNotice, ...]
        The reaches shorter than SHORT_REACH_M or of the minimum slope (D10a).
    """

    threshold_m2: int
    area_km2: float
    elements_km2: float
    boundary_2180: BaseGeometry
    points: tuple[NetworkPoint, ...]
    subcatchments: tuple[NetworkSubcatchment, ...]
    reaches: tuple[NetworkReach, ...]
    junctions: tuple[NetworkJunction, ...]
    order: tuple[str, ...]
    reach_notices: tuple[ReachNotice, ...]


def delineate_network(
    cg: CatchmentGraph,
    db: Session,
    outlet: Click,
    points: Sequence[Click],
    threshold_m2: int,
    settings: Settings | None = None,
) -> Network:
    """Delineate the network of a closing section and its points.

    Parameters
    ----------
    cg : CatchmentGraph
        The loaded catchment graph; its units are ``DEFAULT_THRESHOLD_M2``'s.
    db : Session
        Database session: the extent of the units, the BDOT10k flags and lines,
        the land cover, the soil groups and the PMAXTP grid.
    outlet : Click
        The closing section A.
    points : Sequence[Click]
        The points of the request, ids unique without regard to case.
    threshold_m2 : int
        The network the points snap to [m²], at least ``DEFAULT_THRESHOLD_M2``.
    settings : Settings, optional
        Where the rasters are; ``get_settings()`` by default.

    Returns
    -------
    Network
        The elements with their parameters, the reaches and the junctions.

    Raises
    ------
    NotFoundError
        ``network_point_off_stream``: a point with no stream cell within
        NETWORK_SNAP_M.
    InvalidRequestError
        ``network_point_outside``, ``network_points_coincide`` (core.network_tree).
    UnsupportedError
        ``network_window_too_large``: A's catchment needs a window of more than
        NETWORK_MAX_WINDOW_CELLS cells.
    StoreUnavailableError
        ``network_rasters_missing``, ``raster_grids_differ``.
    InternalError
        ``network_area_mismatch``: the elements do not add up to A's catchment.
    """
    started = time.perf_counter()
    with open_network_rasters(settings or get_settings()) as (rasters, nmt):
        snapped = [
            snap_point(rasters, cg, click, threshold_m2) for click in (outlet, *points)
        ]
        tree = build_network_tree(cg, snapped[0], snapped[1:])
        logger.info(
            "Network: %d points snapped, %d units, %d elements in %.2f s",
            len(snapped),
            tree.units.size,
            len(tree.subcatchments),
            time.perf_counter() - started,
        )
        window = catchment_window(rasters, cg, db, tree)
        # Each array of the window takes 1 to 4 bytes a cell: the slope is read for
        # the statistics of the elements only, the labels are dropped once the
        # element raster holds them (D7)
        grid = NetworkGrid(read_cells(rasters, window, slope=False), window, rasters)
        logger.info(
            "Network: window of %d x %d cells read in %.2f s",
            window.height,
            window.width,
            time.perf_counter() - started,
        )
        elements, streams, outside = element_raster(grid, cg, tree)
        grid.keep_stream_labels()
        check = area_check(cg, tree, elements, outside, rasters.cellsize_m)
        summary = element_summary(grid, elements)
        boundaries = element_coverage(
            elements, grid.cells.transform, COVERAGE_TOLERANCE_M
        )
        logger.info(
            "Network: elements and their coverage in %.2f s",
            time.perf_counter() - started,
        )
        subcatchments = _measure_elements(
            grid, cg, db, tree, elements, streams, summary, boundaries
        )
        reaches = tuple(
            _measure_reach(grid, cg, db, nmt, reach) for reach in tree.reaches
        )
        logger.info(
            "Network: %d elements and %d reaches measured in %.2f s",
            len(subcatchments),
            len(reaches),
            time.perf_counter() - started,
        )
        clicks = {click.point_id: click for click in (outlet, *points)}
        return Network(
            threshold_m2=threshold_m2,
            area_km2=check[0],
            elements_km2=check[1],
            boundary_2180=shapely.coverage_union_all(list(boundaries.values())),
            points=tuple(
                _network_point(grid, point, clicks[point.point_id])
                for point in tree.points
            ),
            subcatchments=subcatchments,
            reaches=reaches,
            junctions=tuple(
                NetworkJunction(junction, *_lat_lon(grid, grid.cell_of(junction.place)))
                for junction in tree.junctions
            ),
            order=tree.order,
            reach_notices=tuple(
                reach_notice(
                    tree,
                    item.reach,
                    item.length_km,
                    item.slope_method,
                    lambda unit: _lat_lon(grid, grid.cell_of(UnitOutlet(unit))),
                )
                for item in reaches
                if is_short_or_flat(item.length_km, item.slope_method)
            ),
        )


@contextmanager
def open_network_rasters(
    settings: Settings,
) -> Iterator[tuple[PipelineRasters, Any]]:
    """Open the rasters of a network: the pipeline's six on one grid and the NMT.

    Each is resolved through ``settings``: the active unit run's mosaic first, then
    the GeoTIFF of a run of the whole raster (D7); the NMT is ``resolve_dem_path``.

    Yields
    ------
    tuple[PipelineRasters, rasterio.DatasetReader]
        The rasters of the units (``DEFAULT_THRESHOLD_M2``) and the NMT.

    Raises
    ------
    StoreUnavailableError
        ``network_rasters_missing`` naming the missing rasters;
        ``raster_grids_differ`` when the six are not on one grid.
    """
    paths = {
        name: settings.resolve_pipeline_raster(suffix)
        for name, suffix in _RASTERS.items()
    }
    nmt_path = settings.resolve_dem_path()
    missing = [_RASTERS[name] for name, path in paths.items() if path is None]
    if nmt_path is None:
        missing.append(_NMT)
    if missing:
        logger.error("Network: rasters missing in %s: %s", settings.dem_dir, missing)
        raise StoreUnavailableError(
            "network_rasters_missing", reason="network_rasters_missing", rasters=missing
        )
    with ExitStack() as stack:
        sources = {
            name: stack.enter_context(rasterio.open(path))
            for name, path in paths.items()
        }
        dem = sources["filled_dem"]
        for name, source in sources.items():
            if (source.shape, source.transform) != (dem.shape, dem.transform):
                logger.error(
                    "Network: %s is not on the grid of %s",
                    paths[name],
                    paths["filled_dem"],
                )
                raise StoreUnavailableError(
                    "raster_grids_differ", reason="raster_grids_differ"
                )
        nmt = stack.enter_context(rasterio.open(nmt_path))
        yield (
            PipelineRasters(
                filled_dem=dem,
                slope=sources["slope"],
                acc=sources["acc"],
                fdir=sources["fdir"],
                flow_dist=sources["flow_dist_m"],
                labels=sources["labels"],
                threshold_m2=DEFAULT_THRESHOLD_M2,
            ),
            nmt,
        )


def snap_point(
    rasters: PipelineRasters, cg: CatchmentGraph, click: Click, threshold_m2: int
) -> ControlPoint:
    """Snap a click to the nearest stream cell of a network (D2).

    The cell is the nearest one within NETWORK_SNAP_M of the click, by its centre,
    whose accumulation reaches ``threshold_m2``, the larger accumulation on a tie.
    Such a cell is a stream cell of the units too, on its unit's segment. Its path
    runs down the flow as far as MOUTH_TOLERANCE_M below it, for the mouth rule.

    Parameters
    ----------
    rasters : PipelineRasters
        Open rasters of the units.
    cg : CatchmentGraph
        The loaded graph: the unit of each label.
    click : Click
        The point clicked.
    threshold_m2 : int
        The network [m²].

    Returns
    -------
    ControlPoint
        The point at its cell.

    Raises
    ------
    NotFoundError
        ``network_point_off_stream`` without such a cell (also off the rasters).
    """
    cellsize = rasters.cellsize_m
    margin = NETWORK_SNAP_M + MOUTH_TOLERANCE_M + 2 * cellsize
    window = cells_window(
        rasters.filled_dem.transform, (click.x, click.y, click.x, click.y), margin
    )
    acc = read_window(rasters.acc, window)
    dem = read_window(rasters.filled_dem, window)
    t = acc.transform
    rows, cols = np.indices(acc.data.shape)
    distance = np.hypot(
        t.c + (cols + 0.5) * t.a - click.x, t.f + (rows + 0.5) * t.e - click.y
    )
    threshold_cells = max(1, int(threshold_m2 / cellsize**2))
    candidate = (acc.data >= threshold_cells) & (distance <= NETWORK_SNAP_M)
    if dem.nodata is not None:
        candidate &= dem.data != dem.nodata
    flat = np.flatnonzero(candidate)
    if flat.size == 0:
        raise NotFoundError(
            "network_point_off_stream",
            reason="network_point_off_stream",
            point_id=click.point_id,
            threshold_m2=threshold_m2,
            snap_m=NETWORK_SNAP_M,
        )
    # The nearest, then the larger accumulation (lexsort: the last key first)
    best = int(
        flat[
            np.lexsort(
                (-acc.data.ravel()[flat].astype(np.float64), distance.ravel()[flat])
            )[0]
        ]
    )
    row, col = divmod(best, acc.data.shape[1])
    cells = _SnapCells(
        labels=read_window(rasters.labels, window).data,
        fdir=read_window(rasters.fdir, window).data,
        flow_dist=read_window(rasters.flow_dist, window).data,
        acc=acc.data,
        offset=(int(window.row_off), int(window.col_off)),
        cg=cg,
    )
    place = cells.place(row, col)
    if place is None:
        raise ValueError(
            f"The stream cell of {click.point_id} has no unit in the catchment graph"
        )
    path = []
    current = (row, col)
    while (below := cells.below(*current)) is not None:
        if place.flow_dist_m - float(cells.flow_dist[below]) > MOUTH_TOLERANCE_M:
            break
        below_place = cells.place(*below)
        if below_place is None:
            break
        path.append(below_place)
        current = below
    return ControlPoint(point_id=click.point_id, place=place, path=tuple(path))


@dataclass(frozen=True)
class _SnapCells:
    """The labels, flow directions, distances and accumulation around a click."""

    labels: np.ndarray
    fdir: np.ndarray
    flow_dist: np.ndarray
    acc: np.ndarray
    offset: tuple[int, int]
    cg: CatchmentGraph

    def below(self, row: int, col: int) -> tuple[int, int] | None:
        """Return the cell a cell drains into; None at a pit or out of the window."""
        step = D8_DIRECTIONS.get(int(self.fdir[row, col]))
        if step is None or self.flow_dist[row, col] == 0:
            return None
        r, c = row + step[0], col + step[1]
        nrows, ncols = self.labels.shape
        return (r, c) if 0 <= r < nrows and 0 <= c < ncols else None

    def place(self, row: int, col: int) -> Place | None:
        """Return the place of a cell of a unit; None without a unit of the graph."""
        label = int(self.labels[row, col])
        unit = (
            self.cg.lookup_by_segment_idx(DEFAULT_THRESHOLD_M2, label)
            if label > 0
            else None
        )
        if unit is None:
            return None
        nrows, ncols = self.labels.shape
        at_head = False
        for code, (drow, dcol) in D8_DIRECTIONS.items():
            r, c = row - drow, col - dcol
            if (
                0 <= r < nrows
                and 0 <= c < ncols
                and self.fdir[r, c] == code
                and 0 < self.labels[r, c] != label
            ):
                at_head = True
        below = self.below(row, col)
        return Place(
            cell=(self.offset[0] + row, self.offset[1] + col),
            unit=unit,
            flow_dist_m=float(self.flow_dist[row, col]),
            at_head=at_head,
            at_outlet=below is None or int(self.labels[below]) != label,
            accumulation_cells=int(self.acc[row, col]),
        )


def catchment_window(
    rasters: PipelineRasters, cg: CatchmentGraph, db: Session, tree: NetworkTree
) -> Window:
    """Find the window of the rasters over A's catchment (D7).

    The extent of the units (``catchments_bounds``) and of the control points with
    WINDOW_MARGIN_M, within the rasters, grown as the precise mode grows its window
    while a cell of the units lies on a side that is not the edge of the rasters.

    Raises
    ------
    UnsupportedError
        ``network_window_too_large`` before a window of more than
        NETWORK_MAX_WINDOW_CELLS cells is read.
    """
    transform = rasters.filled_dem.transform
    height, width = rasters.filled_dem.shape
    segment_idxs = cg.get_segment_indices(tree.units, DEFAULT_THRESHOLD_M2)
    xs, ys = zip(
        *(
            transform * (p.place.cell[1] + 0.5, p.place.cell[0] + 0.5)
            for p in tree.points
        ),
        strict=True,
    )
    bounds = catchments_bounds(segment_idxs, DEFAULT_THRESHOLD_M2, db)
    if bounds is not None:
        xs, ys = (*xs, bounds[0], bounds[2]), (*ys, bounds[1], bounds[3])
    window = cells_window(
        transform, (min(xs), min(ys), max(xs), max(ys)), WINDOW_MARGIN_M
    ).intersection(Window(0, 0, width, height))
    labels = np.sort(np.array(segment_idxs, dtype=np.int64))
    while True:
        size = int(window.height) * int(window.width)
        if size > NETWORK_MAX_WINDOW_CELLS:
            raise UnsupportedError(
                "network_window_too_large",
                reason="network_window_too_large",
                cells=size,
                max_cells=NETWORK_MAX_WINDOW_CELLS,
            )
        grown = _grown(rasters.labels, window, labels, height, width)
        if grown is None:
            return window
        window = grown


def _grown(
    labels_src: Any, window: Window, labels: np.ndarray, height: int, width: int
) -> Window | None:
    """Move out each side of the window with a cell of the units on it; None if none.

    A side at the edge of the rasters (``height`` x ``width`` cells) stays.
    """
    row0, col0 = int(window.row_off), int(window.col_off)
    row1, col1 = row0 + int(window.height), col0 + int(window.width)

    def touches(side: Window) -> bool:
        strip = read_window(labels_src, side).data
        return bool(np.isin(strip, labels).any())

    rows = max(_MIN_GROWTH_CELLS, int(window.height) // 2)
    cols = max(_MIN_GROWTH_CELLS, int(window.width) // 2)
    grown = (
        max(row0 - rows, 0)
        if row0 > 0 and touches(Window(col0, row0, col1 - col0, 1))
        else row0,
        max(col0 - cols, 0)
        if col0 > 0 and touches(Window(col0, row0, 1, row1 - row0))
        else col0,
        min(row1 + rows, height)
        if row1 < height and touches(Window(col0, row1 - 1, col1 - col0, 1))
        else row1,
        min(col1 + cols, width)
        if col1 < width and touches(Window(col1 - 1, row0, 1, row1 - row0))
        else col1,
    )
    if grown == (row0, col0, row1, col1):
        return None
    return Window(grown[1], grown[0], grown[3] - grown[1], grown[2] - grown[0])


class NetworkGrid:
    """The window of the rasters over A's catchment and the cells of the tree's places.

    Attributes
    ----------
    cells : CellWindow
        The rasters in the window; delineate_network reads it without the slope
        (element_summary reads that) and drops its labels after the element raster
        (keep_stream_labels).
    window : Window
        The window, in the rows and columns of the rasters.
    rasters : PipelineRasters
        The open rasters.
    unit_outlets : dict[int, tuple[int, int]]
        The outlet cell in the window of each unit a place of the tree names
        (element_raster).
    """

    def __init__(self, cells: CellWindow, window: Window, rasters: PipelineRasters):
        self.cells = cells
        self.window = window
        self.rasters = rasters
        self.row0, self.col0 = int(window.row_off), int(window.col_off)
        self.unit_outlets: dict[int, tuple[int, int]] = {}
        # The stream cells of the units (flat, ascending) and their labels
        self._stream_cells = np.empty(0, dtype=np.int64)
        self._stream_labels = np.empty(0, dtype=np.int64)

    def keep_stream_labels(self) -> None:
        """Keep the labels of the stream cells of the units only (D8).

        The window of the labels gives the element raster; after it the measures
        need the label of each cell of a main channel, which runs on the stream cells
        of the units (``main_channel``), so the window of the labels is dropped.
        """
        labels = self.cells.labels
        if labels is None:
            raise ValueError("The window holds no labels")
        self._stream_cells = _stream_cells(self.cells.acc, self.rasters.threshold_cells)
        self._stream_labels = labels.ravel()[self._stream_cells]
        self.cells = replace(self.cells, labels=None)

    def stream_labels(self, cells: Sequence[tuple[int, int]]) -> list[int]:
        """Return the labels of stream cells of the window (keep_stream_labels)."""
        ncols = self.cells.acc.shape[1]
        flat = np.array([row * ncols + col for row, col in cells], dtype=np.int64)
        at = np.searchsorted(self._stream_cells, flat)
        inside = at < self._stream_cells.size
        found = np.zeros(flat.size, dtype=bool)
        found[inside] = self._stream_cells[at[inside]] == flat[inside]
        if not found.all():
            raise ValueError("A cell of a channel is not a stream cell of the units")
        return [int(label) for label in self._stream_labels[at]]

    def local(self, cell: tuple[int, int]) -> tuple[int, int]:
        """Return a cell of the rasters in the window."""
        return cell[0] - self.row0, cell[1] - self.col0

    def below(self, cell: tuple[int, int]) -> tuple[int, int] | None:
        """Return the cell a cell drains into; None at a pit or at the edge."""
        step = D8_DIRECTIONS.get(int(self.cells.fdir[cell]))
        if step is None or self.cells.flow_dist[cell] == 0:
            return None
        row, col = cell[0] + step[0], cell[1] + step[1]
        nrows, ncols = self.cells.fdir.shape
        return (row, col) if 0 <= row < nrows and 0 <= col < ncols else None

    def cell_of(self, where: Place | UnitOutlet | UnitHead) -> tuple[int, int]:
        """Return the cell of the window of a place of the tree."""
        if isinstance(where, Place):
            return self.local(where.cell)
        if isinstance(where, UnitOutlet):
            return self.unit_outlets[where.unit]
        cell = self.below(self.unit_outlets[where.above])
        if cell is None:
            raise ValueError(f"The outlet of unit {where.above} drains nowhere")
        return cell

    def centre(self, cell: tuple[int, int]) -> tuple[float, float]:
        """Centre of a cell of the window, EPSG:2180."""
        x, y = self.cells.transform * (cell[1] + 0.5, cell[0] + 0.5)
        return float(x), float(y)


def element_raster(
    grid: NetworkGrid, cg: CatchmentGraph, tree: NetworkTree
) -> tuple[np.ndarray, dict[int, np.ndarray], int]:
    """Give every cell of the window its element (D5, D6).

    The labels of the units through the table unit -> element, then the units of
    the control points split by pyflwdir basins on the D8 of their extent plus one
    cell, with an outlet (a pit) at each control point in them and at their outlet
    cell: each of their cells takes the element of the first outlet below it.

    Returns
    -------
    tuple[np.ndarray, dict[int, np.ndarray], int]
        The element raster (int16, 0 outside the network); the count of the stream
        cells of the units of each split unit in each element (by unit, indexed by
        element); the cells of A's unit below A.
    """
    cells = grid.cells
    labels = cells.labels
    if labels is None:
        raise ValueError("The window holds no labels")
    segments = np.array(
        cg.get_segment_indices(tree.units, DEFAULT_THRESHOLD_M2), dtype=np.int64
    )
    if segments.size != tree.units.size:
        raise ValueError("The units of the catchment are not all of the unit threshold")
    segment_of = dict(zip(tree.units.tolist(), segments.tolist(), strict=True))
    table = np.zeros(max(int(labels.max()), int(segments.max())) + 1, np.int16)
    table[segments] = tree.unit_elements
    elements = table[labels]

    # The outlet cell of every unit a place of the tree names, and the extent of the
    # split units: one pass over the labels
    named = {
        s.outlet.unit for s in tree.subcatchments if isinstance(s.outlet, UnitOutlet)
    }
    named |= {j.place.above for j in tree.junctions if isinstance(j.place, UnitHead)}
    for reach in tree.reaches:
        named |= {
            e.above for e in (reach.upper, reach.lower) if isinstance(e, UnitHead)
        }
    for split in tree.splits:
        named.add(split.unit)
    named_units = sorted(named)
    slot = np.full(table.size, -1, dtype=np.int64)
    for k, unit in enumerate(named_units):
        slot[segment_of[unit]] = k
    flat, row_min, row_max, col_min, col_max = _extents(
        labels, slot, cells.acc, len(named_units)
    )
    ncols = labels.shape[1]
    for k, unit in enumerate(named_units):
        if flat[k] < 0:
            raise ValueError(f"Unit {unit} has no cells in the window")
        grid.unit_outlets[unit] = (int(flat[k] // ncols), int(flat[k] % ncols))

    threshold_cells = grid.rasters.threshold_cells
    n_elements = len(tree.subcatchments)
    streams: dict[int, np.ndarray] = {}
    outside = 0
    nrows = labels.shape[0]
    for split in tree.splits:
        k = named_units.index(split.unit)
        rows = slice(max(int(row_min[k]) - 1, 0), min(int(row_max[k]) + 2, nrows))
        cols = slice(max(int(col_min[k]) - 1, 0), min(int(col_max[k]) + 2, ncols))
        unit_cells = labels[rows, cols] == segment_of[split.unit]
        d8 = d8_from_saved_flowdir(
            cells.fdir[rows, cols], cells.flow_dist[rows, cols], cells.valid[rows, cols]
        )
        outlets = []
        for where, _ in split.outlets:
            row, col = grid.cell_of(where)
            outlets.append((row - rows.start, col - cols.start))
            d8[outlets[-1]] = 0
        flw = pyflwdir.from_array(d8, ftype="d8", latlon=False)
        basins = flw.basins(
            idxs=np.array([np.ravel_multi_index(o, d8.shape) for o in outlets]),
            ids=np.arange(1, len(outlets) + 1, dtype=np.uint32),
        )
        numbers = np.array([0] + [number for _, number in split.outlets], np.int16)
        part = elements[rows, cols]
        part[unit_cells] = numbers[basins[unit_cells]]
        stream = unit_cells & (cells.acc[rows, cols] >= threshold_cells)
        streams[split.unit] = np.bincount(part[stream], minlength=n_elements + 1)
        if split.unit == int(tree.units[0]):
            outside = int(np.count_nonzero(part[unit_cells] == 0))
    return elements, streams, outside


@numba.njit(cache=True)
def _extents(
    labels: np.ndarray, slot: np.ndarray, acc: np.ndarray, count: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """For each label with a slot: the cell of its largest accumulation, its extent.

    Returns the flat index of the first cell of the largest accumulation (-1
    without cells) and the first and last row and column of the cells.
    """
    nrows, ncols = labels.shape
    best = np.full(count, -np.inf)
    flat = np.full(count, -1, dtype=np.int64)
    row_min = np.full(count, nrows, dtype=np.int64)
    row_max = np.full(count, -1, dtype=np.int64)
    col_min = np.full(count, ncols, dtype=np.int64)
    col_max = np.full(count, -1, dtype=np.int64)
    for row in range(nrows):
        for col in range(ncols):
            label = labels[row, col]
            if label <= 0 or label >= slot.size:
                continue
            k = slot[label]
            if k < 0:
                continue
            row_min[k] = min(row_min[k], row)
            row_max[k] = max(row_max[k], row)
            col_min[k] = min(col_min[k], col)
            col_max[k] = max(col_max[k], col)
            if acc[row, col] > best[k]:
                best[k] = acc[row, col]
                flat[k] = row * ncols + col
    return flat, row_min, row_max, col_min, col_max


@numba.njit(cache=True)
def _stream_cells(acc: np.ndarray, threshold_cells: int) -> np.ndarray:
    """Flat indices of the cells of an accumulation of at least the threshold.

    In ascending order, as ``np.flatnonzero(acc >= threshold_cells)`` gives them,
    without a mask of the window.
    """
    nrows, ncols = acc.shape
    count = 0
    for row in range(nrows):
        for col in range(ncols):
            if acc[row, col] >= threshold_cells:
                count += 1
    cells = np.empty(count, dtype=np.int64)
    k = 0
    for row in range(nrows):
        for col in range(ncols):
            if acc[row, col] >= threshold_cells:
                cells[k] = row * ncols + col
                k += 1
    return cells


def area_check(
    cg: CatchmentGraph,
    tree: NetworkTree,
    elements: np.ndarray,
    outside: int,
    cellsize_m: float,
) -> tuple[float, float]:
    """Check that the elements add up to A's catchment (D11, B5).

    The cells of the element raster against the cells of A's catchment counted
    from the graph: the sum over its units of ``round(area_km2 / cell area)``, less
    the cells of A's unit below A.

    Returns
    -------
    tuple[float, float]
        A's catchment and the elements [km², 6 decimals], equal.

    Raises
    ------
    InternalError
        ``network_area_mismatch`` when they differ.
    """
    cell_km2 = cellsize_m * cellsize_m / M2_PER_KM2
    areas = cg.get_area_km2(tree.units).astype(np.float64)
    watershed_cells = int(np.rint(areas / cell_km2).sum()) - outside
    elements_cells = int(np.count_nonzero(elements))
    if elements_cells != watershed_cells:
        logger.error(
            "Network: the elements hold %d cells, A's catchment %d",
            elements_cells,
            watershed_cells,
        )
        raise InternalError(
            "network_area_mismatch",
            reason="network_area_mismatch",
            elements_cells=elements_cells,
            watershed_cells=watershed_cells,
        )
    return round(watershed_cells * cell_km2, 6), round(elements_cells * cell_km2, 6)


def element_summary(grid: NetworkGrid, elements: np.ndarray) -> ZonalSummary:
    """Give the terrain statistics of every element in one pass (D8).

    ``zonal_summary`` of the element raster over the filled DEM and the slope; the
    window of the slope is read for it alone.
    """
    cells = grid.cells
    return zonal_summary(
        elements,
        cells.dem,
        read_window(grid.rasters.slope, grid.window).data,
        cells.dem_nodata if cells.dem_nodata is not None else np.nan,
    )


def _measure_elements(
    grid: NetworkGrid,
    cg: CatchmentGraph,
    db: Session,
    tree: NetworkTree,
    elements: np.ndarray,
    streams: dict[int, np.ndarray],
    summary: ZonalSummary,
    boundaries: dict[int, BaseGeometry],
) -> tuple[NetworkSubcatchment, ...]:
    """Measure every element from its cells (D8)."""
    count = len(tree.subcatchments) + 1
    slot = np.arange(count, dtype=np.int64)
    flat, row_min, row_max, col_min, col_max = _extents(
        elements, slot, grid.cells.acc, count
    )
    nrows, ncols = elements.shape
    measured = []
    for item in tree.subcatchments:
        e = item.number
        if flat[e] < 0:
            raise ValueError(f"Element {item.id} has no cells")
        rows = slice(max(int(row_min[e]) - 1, 0), min(int(row_max[e]) + 2, nrows))
        cols = slice(max(int(col_min[e]) - 1, 0), min(int(col_max[e]) + 2, ncols))
        outlet = (int(flat[e] // ncols) - rows.start, int(flat[e] % ncols) - cols.start)
        terrain, area_km2 = terrain_of(summary, e, grid.rasters.cellsize_m)
        units = tree.units[tree.unit_elements == e]
        parts = {
            unit: float(counts[e] / counts.sum())
            for unit, counts in streams.items()
            if counts[e] > 0
        }
        measured.append(
            NetworkSubcatchment(
                subcatchment=item,
                area_km2=area_km2,
                boundary_2180=boundaries[e],
                watershed=_element_watershed(
                    grid,
                    (rows, cols),
                    elements[rows, cols] == e,
                    outlet,
                    terrain,
                    area_km2,
                    summary.histograms.get(e),
                    _drainage(cg, units, parts, area_km2),
                    boundaries[e],
                    db,
                ),
            )
        )
    return tuple(measured)


def _drainage(
    cg: CatchmentGraph, units: np.ndarray, parts: dict[int, float], area_km2: float
) -> dict[str, Any]:
    """Drainage indices of an element from the graph's values of its units (D8).

    A unit split among elements counts in each part that holds stream cells of its
    segment, its BDOT10k length in the share of those cells.
    """
    length_km = 0.0
    count = 0
    orders: list[int] = []
    for indices, share in [(units, 1.0)] + [
        (np.array([unit]), share) for unit, share in parts.items()
    ]:
        if indices.size == 0:
            continue
        stats = cg.aggregate_stats(indices)
        length_km += stats["bdot_stream_length_km"] * share
        count += stats["bdot_stream_count"]
        if stats["max_strahler_order"]:
            orders.append(stats["max_strahler_order"])
    return {
        "drainage_density_km_per_km2": (
            round(length_km / area_km2, 4) if area_km2 > 0 else None
        ),
        "stream_frequency_per_km2": round(count / area_km2, 4)
        if area_km2 > 0
        else None,
        "max_strahler_order": max(orders) if orders else None,
        "bdot_stream_length_km": round(length_km, 4),
        "bdot_stream_count": count,
    }


def _element_watershed(
    grid: NetworkGrid,
    frame: tuple[slice, slice],
    member: np.ndarray,
    outlet: tuple[int, int],
    terrain: dict[str, Any],
    area_km2: float,
    histogram: dict[str, Any] | None,
    drainage: dict[str, Any],
    boundary: BaseGeometry,
    db: Session,
) -> WatershedResponse:
    """Measure the panel's parameters of an element from its cells (D8).

    The terrain of its cells, the flow paths and the overland segment from its
    cells closed downstream, the main channel up its stream cells of the largest
    accumulation, the drainage indices of its units, and from its boundary the
    perimeter, the shape indices, the land cover, the soil groups and the PMAXTP
    weights, as ``build_morph_dict_from_graph`` and the response builder of
    ``POST /api/delineate-watershed`` put them together. The cells are measured in
    ``frame``, the rows and columns of the window around them, where ``member``
    holds them and ``outlet`` lies; the arrays of the frame are freed on return.
    """
    window, rasters = grid.cells, grid.rasters
    rows, cols = frame
    cells = CellWindow(
        dem=window.dem[rows, cols],
        slope=None,
        acc=window.acc[rows, cols],
        fdir=window.fdir[rows, cols],
        flow_dist=window.flow_dist[rows, cols],
        labels=None,
        dem_nodata=window.dem_nodata,
        flow_dist_nodata=window.flow_dist_nodata,
        transform=window.transform * Affine.translation(cols.start, rows.start),
        valid=window.valid[rows, cols],
        member=member,
    )
    d8 = d8_from_saved_flowdir(cells.fdir, cells.flow_dist, cells.valid)
    d8[outlet] = 0
    flow, paths = flow_path_parameters(cells, d8, outlet, rasters.threshold_cells)
    del d8
    stream = cells.acc >= rasters.threshold_cells
    stream &= member
    channel_cells = main_channel(cells, outlet, stream)
    del stream
    channel = channel_measures(
        cells,
        channel_cells,
        grid.stream_labels(
            [(row + rows.start, col + cols.start) for row, col in channel_cells]
        ),
        rasters,
        db,
    )
    outlet_x, outlet_y = cells.transform * (outlet[1] + 0.5, outlet[0] + 0.5)
    outlet_lon, outlet_lat = transform_pl1992_to_wgs84(outlet_x, outlet_y)
    elev_min, elev_max = terrain["elevation_min_m"], terrain["elevation_max_m"]
    elev_mean = terrain["elevation_mean_m"]
    perimeter_km = round(boundary.length / M_PER_KM, 4)
    flow_path_km = flow["flow_path_length_km"]
    length_km = (
        flow_path_km
        if flow_path_km
        else round(compute_watershed_length(boundary, outlet_x, outlet_y), 4)
    )
    centroid = boundary.centroid
    channel_line = (
        LineString(path_coords(channel_cells, cells.transform))
        if len(channel_cells) > 1
        else None
    )
    length_to_centroid_km = round(
        (
            channel_line.project(centroid)
            if channel_line is not None
            else centroid.distance(Point(outlet_x, outlet_y))
        )
        / M_PER_KM,
        4,
    )
    relief_m = elev_max - elev_min
    dd = drainage["drainage_density_km_per_km2"]
    shape_indices = calculate_shape_indices(area_km2, perimeter_km, length_km)
    lc_tolerance = (
        _LAND_COVER_SIMPLIFY_M if area_km2 > _LAND_COVER_SIMPLIFY_ABOVE_KM2 else None
    )
    land_cover = build_land_cover_stats(boundary, db, simplify_tolerance=lc_tolerance)
    soils = build_hsg_stats(
        boundary if lc_tolerance is None else boundary.simplify(lc_tolerance), db
    )
    morphometry = {
        "area_km2": terrain["area_km2"],
        "perimeter_km": perimeter_km,
        "length_km": length_km,
        "elevation_min_m": elev_min,
        "elevation_max_m": elev_max,
        "elevation_mean_m": elev_mean,
        "mean_slope_m_per_m": terrain["mean_slope_m_per_m"],
        **channel,
        "length_to_centroid_km": length_to_centroid_km,
        **{key: shape_indices.get(key) for key in _SHAPE_INDICES},
        "relief_ratio": (
            round(relief_m / math.sqrt(area_km2), 4) if area_km2 > 0 else None
        ),
        "divide_slope": round(relief_m / perimeter_km, 4) if perimeter_km > 0 else None,
        "hypsometric_integral": (
            round((elev_mean - elev_min) / relief_m, 4) if relief_m > 0 else None
        ),
        **drainage,
        "ruggedness_number": (
            round(dd * relief_m / M_PER_KM, 4) if dd is not None else None
        ),
        "hydraulic_length_km": flow_path_km,
        "longest_flow_path_km": flow_path_km,
        "centroid_flow_path_km": _centroid_flow_path_km(
            grid, centroid, baseline_m(cells, outlet)
        ),
        **flow,
    }
    if land_cover is not None:
        morphometry["cn"] = land_cover.weighted_cn
        morphometry["imperviousness"] = round(land_cover.weighted_imperviousness, 3)
        morphometry["forest_pct"] = land_cover.forest_pct
        morphometry["urban_pct"] = land_cover.urban_pct
    curve = hypsometric_curve([histogram]) if histogram is not None else []
    return WatershedResponse(
        boundary_geojson={
            "type": "Feature",
            "geometry": mapping(transform_geometry_pl1992_to_wgs84(boundary)),
            "properties": {"area_km2": round(area_km2, 2)},
        },
        outlet=OutletInfo(
            latitude=outlet_lat,
            longitude=outlet_lon,
            elevation_m=round(float(cells.dem[outlet]), 2),
        ),
        area_km2=round(area_km2, 2),
        hydrograph_available=area_km2 <= HYDROGRAPH_AREA_LIMIT_KM2,
        morphometry=MorphometricParameters(**morphometry),
        hypsometric_curve=[HypsometricPoint(**p) for p in curve] or None,
        land_cover_stats=land_cover,
        hsg_stats=soils,
        main_stream_geojson=(
            {
                "type": "LineString",
                "coordinates": [
                    list(transform_pl1992_to_wgs84(x, y))
                    for x, y in reversed(channel_line.coords)
                ],
            }
            if channel_line is not None
            else None
        ),
        longest_flow_path_geojson=flow_path_geojson(paths.longest, "longest_flow_path"),
        divide_flow_path_geojson=flow_path_geojson(paths.divide, "divide_flow_path"),
        pmaxtp_grid=[
            PmaxtpGridCell(**asdict(cell)) for cell in thiessen_cells(boundary, db)
        ]
        or None,
    )


_SHAPE_INDICES = (
    "compactness_coefficient",
    "circularity_ratio",
    "elongation_ratio",
    "form_factor",
    "lemniscate_ratio",
    "mean_width_km",
)


def _centroid_flow_path_km(
    grid: NetworkGrid, centroid: Point, baseline: float
) -> float | None:
    """Flow distance from the cell of the centroid down to the outlet [km]."""
    cells = grid.cells
    col, row = ~cells.transform * (centroid.x, centroid.y)
    cell = (math.floor(row), math.floor(col))
    nrows, ncols = cells.valid.shape
    if not (0 <= cell[0] < nrows and 0 <= cell[1] < ncols) or not cells.valid[cell]:
        return None
    distance = float(cells.flow_dist[cell])
    if distance == cells.flow_dist_nodata or distance - baseline <= 0:
        return None
    return round((distance - baseline) / M_PER_KM, 4)


def reach_slope(
    nmt: Any,
    upper_xy: tuple[float, float],
    lower_xy: tuple[float, float],
    length_km: float,
) -> tuple[float, Literal["nmt", "minimum"], float | None, float | None]:
    """Return the slope of a reach from the NMT at the centres of its end cells (D10).

    Returns
    -------
    tuple
        The slope [m/m], ``nmt`` or ``minimum`` (MIN_REACH_SLOPE_M_PER_M where the
        NMT does not fall or has no data), and the NMT at the upper and the lower
        end [m], None without data.
    """
    up, down = (
        None if value == nmt.nodata else round(float(value), 2)
        for (value,) in nmt.sample([upper_xy, lower_xy])
    )
    slope = (
        round((up - down) / (length_km * M_PER_KM), 6)
        if up is not None and down is not None
        else 0.0
    )
    if slope <= 0:
        return MIN_REACH_SLOPE_M_PER_M, "minimum", up, down
    return slope, "nmt", up, down


def is_short_or_flat(length_km: float | None, slope_method: str | None) -> bool:
    """Tell a reach shorter than SHORT_REACH_M or of the minimum slope (D10a)."""
    short = length_km is not None and length_km * M_PER_KM < SHORT_REACH_M
    return short or slope_method == "minimum"


def reach_notice(
    tree: NetworkTree,
    reach: Reach,
    length_km: float,
    slope_method: str | None,
    outlet_lat_lon: Callable[[int], tuple[float, float] | None],
) -> ReachNotice:
    """Return the notice of a reach shorter than SHORT_REACH_M or flat (D10a).

    Parameters
    ----------
    tree : NetworkTree
        The tree of the reach.
    reach : Reach
        The reach.
    length_km : float
        Its length [km].
    slope_method : {"nmt", "minimum"} or None
        Where its slope comes from; None when unknown.
    outlet_lat_lon : Callable
        The latitude and longitude of the outlet cell of a unit, None when not found.

    Returns
    -------
    ReachNotice
        The notice; ``move_to`` is the outlet cell of the last unit of the reach's
        branch above its junction, where its przyrzecze ends, when the reach runs
        from a control point into a confluence: the point placed there is at the
        mouth (D3), so the reach and its przyrzecze disappear.
    """
    lower = next(j for j in tree.junctions if j.id == reach.to)
    points = {s.id: s.point for s in tree.subcatchments}
    points.update({j.id: j.point for j in tree.junctions})
    upper_point = points.get(reach.from_node)
    end = next((s.outlet for s in tree.subcatchments if s.reach == reach.id), None)
    move_to = (
        outlet_lat_lon(end.unit)
        if upper_point is not None
        and lower.kind == "confluence"
        and isinstance(end, UnitOutlet)
        else None
    )
    return ReachNotice(
        reach=reach.id,
        length_m=round(length_km * M_PER_KM, 1),
        slope_minimum=slope_method == "minimum",
        upper_point=upper_point,
        lower=lower.id,
        move_to=move_to,
    )


def unit_outlet_near(
    rasters: PipelineRasters, cg: CatchmentGraph, unit: int, xy: tuple[float, float]
) -> tuple[int, int] | None:
    """Return the outlet cell of a unit within two cells of a place, None if none.

    The outlet cell of a unit is its cell of the largest accumulation, the cell
    next to the head cell of the unit below at a junction.
    """
    window = cells_window(
        rasters.filled_dem.transform, (*xy, *xy), 2 * rasters.cellsize_m
    )
    labels = read_window(rasters.labels, window).data
    acc = read_window(rasters.acc, window).data
    member = np.flatnonzero(labels.ravel() == cg.get_segment_idx(unit))
    if member.size == 0:
        return None
    row, col = divmod(int(member[np.argmax(acc.ravel()[member])]), labels.shape[1])
    return int(window.row_off) + row, int(window.col_off) + col


def _measure_reach(
    grid: NetworkGrid, cg: CatchmentGraph, db: Session, nmt: Any, reach: Reach
) -> NetworkReach:
    """Measure the length, slope, line and check length of a reach (D10)."""
    upper, lower = grid.cell_of(reach.upper), grid.cell_of(reach.lower)
    length_km = round(
        (
            _flow_dist(grid, cg, reach.upper, upper)
            - _flow_dist(grid, cg, reach.lower, lower)
        )
        / M_PER_KM,
        4,
    )
    if length_km <= 0:
        raise ValueError(f"Reach {reach.id} does not fall along the flow")
    cells = [upper]
    while cells[-1] != lower:
        below = grid.below(cells[-1])
        if below is None or len(cells) > grid.cells.fdir.size:
            raise ValueError(f"Reach {reach.id} does not reach its lower end")
        cells.append(below)
    line = path_coords(cells, grid.cells.transform)
    slope, method, up, down = reach_slope(
        nmt, grid.centre(upper), grid.centre(lower), length_km
    )
    streams = [
        shapely.from_wkb(bytes(row.geom))
        for row in db.execute(
            _BDOT_LINES,
            {"line": LineString(line).wkb, "buffer_m": BDOT_BUFFER_M},
        ).fetchall()
    ]
    return NetworkReach(
        reach=reach,
        length_km=length_km,
        slope_m_per_m=slope,
        slope_method=method,
        upstream_elevation_m=up,
        downstream_elevation_m=down,
        vector_length_km=vector_length_km(
            LineString(line), streams, REACH_SAMPLE_M, BDOT_BUFFER_M
        ),
        line_2180=line,
    )


def _flow_dist(
    grid: NetworkGrid,
    cg: CatchmentGraph,
    where: Place | UnitHead,
    cell: tuple[int, int],
) -> float:
    """Flow distance at an end of a reach [m] (D10).

    At a junction the graph's ``outlet_flow_dist_m`` of a unit draining into it, at
    a control point the raster at its cell.
    """
    if isinstance(where, UnitHead):
        distance = cg.get_outlet_flow_dist_m(where.above)
        if not math.isnan(distance):
            return distance
    return float(grid.cells.flow_dist[cell])


def _lat_lon(grid: NetworkGrid, cell: tuple[int, int]) -> tuple[float, float]:
    """Latitude and longitude of the centre of a cell of the window."""
    lon, lat = transform_pl1992_to_wgs84(*grid.centre(cell))
    return lat, lon


def _network_point(grid: NetworkGrid, point: Any, click: Click) -> NetworkPoint:
    """Place a control point where it lies, with its distance from its click."""
    cell = grid.local(point.place.cell)
    x, y = grid.centre(cell)
    latitude, longitude = _lat_lon(grid, cell)
    return NetworkPoint(
        point_id=point.point_id,
        latitude=latitude,
        longitude=longitude,
        snap_distance_m=round(math.hypot(x - click.x, y - click.y), 1),
        at_mouth=point.at_mouth,
        node=point.node,
    )


def element_coverage(
    elements: np.ndarray, transform: Affine, tolerance_m: float
) -> dict[int, BaseGeometry]:
    """Boundaries of the elements as one coverage, simplified together (D9).

    The element raster is vectorized once (4-connected cells of one number form a
    part); the rings are noded so that every point where three elements (or two and
    the outside) meet is a vertex of every ring through it, which makes the parts a
    valid coverage; ``shapely.coverage_simplify`` then simplifies all of them
    together, so shared edges stay shared (no gaps, no overlaps). No part or hole
    vanishes: the simplification reduces a ring at most to a triangle, so a part
    of a single cell keeps its place (with half its area at worst).

    Parameters
    ----------
    elements : np.ndarray
        2-D raster of element numbers 1..n (0 = no element).
    transform : Affine
        Affine transform of the raster (EPSG:2180).
    tolerance_m : float
        Tolerance of the coverage simplification [m].

    Returns
    -------
    dict[int, BaseGeometry]
        Element number -> its Polygon or MultiPolygon in the CRS of ``transform``.
    """
    rings: list[np.ndarray] = []
    rings_per_part: list[int] = []
    values: list[int] = []
    # Without a transform the rings are on the cell corners, (column, row)
    for geom, value in shapes(elements, mask=elements > 0, connectivity=4):
        part_rings = geom["coordinates"]
        rings.extend(np.asarray(ring, dtype=np.float64) for ring in part_rings)
        rings_per_part.append(len(part_rings))
        values.append(int(value))
    if not rings:
        return {}

    ring_offsets = np.zeros(len(rings) + 1, dtype=np.int64)
    np.cumsum([len(ring) for ring in rings], out=ring_offsets[1:])
    corners = np.rint(np.concatenate(rings)).astype(np.int64)
    stride = max(elements.shape) + 2
    corners, ring_offsets = _node_rings(corners, ring_offsets, stride)

    a, b, c, d, e, f = transform[:6]
    xy = np.column_stack(
        [
            a * corners[:, 0] + b * corners[:, 1] + c,
            d * corners[:, 0] + e * corners[:, 1] + f,
        ]
    )
    part_offsets = np.zeros(len(rings_per_part) + 1, dtype=np.int64)
    np.cumsum(rings_per_part, out=part_offsets[1:])
    parts = shapely.from_ragged_array(
        shapely.GeometryType.POLYGON, xy, (ring_offsets, part_offsets)
    )
    simplified = shapely.coverage_simplify(parts, tolerance_m)

    part_values = np.asarray(values)
    coverage: dict[int, BaseGeometry] = {}
    for value in np.unique(part_values):
        own = simplified[part_values == value]
        coverage[int(value)] = own[0] if len(own) == 1 else MultiPolygon(list(own))
    return coverage


def _node_rings(
    coords: np.ndarray, ring_offsets: np.ndarray, stride: int
) -> tuple[np.ndarray, np.ndarray]:
    """Insert every ring vertex into the edges of the other rings passing through it.

    The rings are axis-parallel on cell corners (integer cell units).
    ``rasterio.features.shapes`` drops the collinear vertices, so where a ring turns
    at a point on the straight edge of another ring (a T-junction of three elements,
    or of two elements and the outside) the straight ring lacks that vertex. Every
    vertex of every ring is inserted into the interior of each edge that contains it.

    Parameters
    ----------
    coords : np.ndarray
        Vertices of all rings, concatenated, shape (n, 2), int64 cell units
        (column, row); each ring is closed (its last vertex repeats its first).
    ring_offsets : np.ndarray
        Start of each ring in ``coords`` and the total, shape (n_rings + 1,).
    stride : int
        A number greater than every coordinate, to key a point by
        ``row * stride + column`` (or ``column * stride + row``).

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        The noded vertices and their ring offsets.
    """
    col = coords[:, 0]
    row = coords[:, 1]
    n = len(coords)
    # an edge starts at every vertex except the last (closing) one of a ring
    is_last = np.zeros(n, dtype=bool)
    is_last[ring_offsets[1:] - 1] = True
    nxt = np.minimum(np.arange(n) + 1, n - 1)
    col_end = np.where(is_last, col, col[nxt])
    row_end = np.where(is_last, row, row[nxt])
    horizontal = (row_end == row) & ~is_last
    vertical = (col_end == col) & ~is_last & ~horizontal
    forward = (col_end > col) | (row_end > row)

    # every vertex keyed along its row (for the horizontal edges) and its column;
    # the keys strictly between an edge's two ends are the vertices inside it
    # (sort and drop repeats: np.unique is ten times slower here)
    keys_h = np.sort(row * stride + col)
    keys_h = keys_h[np.append(True, keys_h[1:] != keys_h[:-1])]
    keys_v = np.sort(col * stride + row)
    keys_v = keys_v[np.append(True, keys_v[1:] != keys_v[:-1])]
    start = np.zeros(n, dtype=np.int64)
    end = np.zeros(n, dtype=np.int64)
    h = np.flatnonzero(horizontal)
    base_h = row[h] * stride
    lo_h = base_h + np.minimum(col[h], col_end[h])
    hi_h = base_h + np.maximum(col[h], col_end[h])
    start[h] = np.searchsorted(keys_h, lo_h, side="right")
    end[h] = np.searchsorted(keys_h, hi_h, side="left")
    v = np.flatnonzero(vertical)
    base_v = col[v] * stride
    lo_v = base_v + np.minimum(row[v], row_end[v])
    hi_v = base_v + np.maximum(row[v], row_end[v])
    start[v] = np.searchsorted(keys_v, lo_v, side="right")
    end[v] = np.searchsorted(keys_v, hi_v, side="left")
    n_insert = end - start
    if not n_insert.any():
        return coords, ring_offsets

    # each vertex is followed by the points inserted into its edge, in the
    # edge's direction
    out_start = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(1 + n_insert, out=out_start[1:])
    out = np.empty((int(out_start[-1]), 2), dtype=np.int64)
    out[out_start[:-1]] = coords
    edge = np.repeat(np.arange(n), n_insert)
    rank = np.arange(len(edge)) - np.repeat(np.cumsum(n_insert) - n_insert, n_insert)
    pick = np.where(forward[edge], start[edge] + rank, end[edge] - 1 - rank)
    is_h = horizontal[edge]
    inserted = np.empty((len(edge), 2), dtype=np.int64)
    row_h, col_h = np.divmod(keys_h[pick[is_h]], stride)
    inserted[is_h] = np.column_stack([col_h, row_h])
    col_v, row_v = np.divmod(keys_v[pick[~is_h]], stride)
    inserted[~is_h] = np.column_stack([col_v, row_v])
    out[out_start[edge] + 1 + rank] = inserted
    return out, out_start[ring_offsets]


def vector_length_km(
    line: LineString,
    streams: Sequence[BaseGeometry],
    step_m: float = REACH_SAMPLE_M,
    buffer_m: float = BDOT_BUFFER_M,
) -> float | None:
    """BDOT10k check length of a reach (D10).

    The reach's line is sampled every ``step_m`` from its start, plus its end; each
    sample takes the nearest line of ``streams`` within ``buffer_m``. The length is
    the sum over consecutive samples of the distance along their line when both took
    the same line, else the straight distance between their projections on their
    lines.

    Parameters
    ----------
    line : LineString
        The reach's D8 line from its upper end down (EPSG:2180).
    streams : Sequence[BaseGeometry]
        BDOT10k stream lines near the reach (EPSG:2180).
    step_m : float
        Distance between the samples [m].
    buffer_m : float
        Largest distance from a sample to its line [m] (ADR-044's matching buffer).

    Returns
    -------
    float | None
        The length [km], 4 decimals; None when there are no lines or a sample has
        no line within ``buffer_m``.
    """
    if len(streams) == 0:
        return None
    length_m = line.length
    distances_m = np.append(np.arange(0.0, length_m, step_m), length_m)
    samples = shapely.line_interpolate_point(line, distances_m)
    lines = np.asarray(streams, dtype=object)
    sample_idx, line_idx = shapely.STRtree(lines).query_nearest(
        samples, max_distance=buffer_m, all_matches=False
    )
    if len(sample_idx) < len(samples):
        return None
    nearest = np.empty(len(samples), dtype=np.int64)
    nearest[sample_idx] = line_idx
    on_line = lines[nearest]
    along_m = shapely.line_locate_point(on_line, samples)
    projected = shapely.line_interpolate_point(on_line, along_m)
    same_line = nearest[1:] == nearest[:-1]
    step_lengths_m = np.where(
        same_line,
        np.abs(np.diff(along_m)),
        shapely.distance(projected[:-1], projected[1:]),
    )
    return round(float(step_lengths_m.sum()) / M_PER_KM, 4)
