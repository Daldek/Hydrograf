"""
A preview of a network on the catchment graph (ADR-081).

``POST /api/delineate-network/preview`` composes the network of a closing section and
its points while the person places them, in a fraction of a second. The points snap as
for the full run (``core.network_delineation.snap_point``: the windows of the rasters
within some 160 m of each click) and ``core.network_tree`` builds the same tree, so the
ids, kinds and inflows of the elements and the places of the points and junctions are
those ``delineate_network`` gives. No window over A's catchment is read:

- the area of an element is the cells of its units (the graph's ``area_km2``), the
  parts of a unit that a point splits counted from the accumulation at the points
  (``Place.accumulation_cells``): exact to the cell, as the full run's;
- a reach's length is the difference of the flow distances of its ends, as the full
  run's; its line joins the stream lines of its units (``stream_network``) between
  its ends;
- an element's outline is the union of the polygons of its units
  (``stream_catchments``) on a grid of PREVIEW_GRID_M, drawn wherever possible with the
  largest unit of a coarser threshold that the element holds whole: a few hundred
  polygons instead of the tens of thousands of units of 1 ha. A unit that a point
  splits goes whole to the element with most of its cells, so the outlines of the
  elements at such a point are approximate until the full run splits the unit by the
  raster.
"""

import logging
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numba
import numpy as np
import shapely
from rasterio.transform import Affine
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.catchment_graph import CatchmentGraph
from core.cell_parameters import PipelineRasters
from core.config import Settings, get_settings
from core.constants import DEFAULT_THRESHOLD_M2, M2_PER_KM2, M_PER_KM
from core.network_delineation import (
    Click,
    NetworkJunction,
    NetworkPoint,
    ReachNotice,
    is_short_or_flat,
    open_network_rasters,
    reach_notice,
    reach_slope,
    snap_point,
    unit_outlet_near,
)
from core.network_tree import (
    NetworkTree,
    Place,
    PointNode,
    Reach,
    Subcatchment,
    UnitHead,
    build_network_tree,
)
from utils.geometry import transform_pl1992_to_wgs84

logger = logging.getLogger(__name__)

# The outlines of the elements are simplified to this grid and united on it [m]: the
# polygons of the units, which the preprocessing simplified at twice the cell size,
# lose their pixel steps, and the elements of the whole Kaczawa (792 km²) are united
# in under 0.2 s
PREVIEW_GRID_M = 10.0
# Holes and parts of an outline narrower than this (twice their area over their
# perimeter) are the gaps between neighbouring units simplified apart, not the land of
# another element [m]
_SLIVER_WIDTH_M = 3 * PREVIEW_GRID_M
# The lines of the reaches are simplified at this tolerance [m]: the stored stream
# lines carry eight vertices a cell (three Chaikin iterations), so a reach of 23 km
# would carry some 37,000
REACH_LINE_TOLERANCE_M = 1.0

_OUTLINES = text(
    "SELECT p.element, ST_AsBinary(ST_Union(ST_ReducePrecision(ST_CollectionExtract("
    "ST_MakeValid(ST_Simplify(c.geom, :grid_m, true)), 3), :grid_m), :grid_m)) AS geom "
    "FROM unnest(CAST(:thresholds AS integer[]), CAST(:segments AS integer[]), "
    "CAST(:elements AS integer[])) AS p(threshold_m2, segment_idx, element) "
    "JOIN stream_catchments c "
    "ON c.threshold_m2 = p.threshold_m2 AND c.segment_idx = p.segment_idx "
    "GROUP BY p.element"
)
_STREAM_LINES = text(
    "SELECT segment_idx, ST_AsBinary(geom) AS geom FROM stream_network "
    "WHERE threshold_m2 = :threshold AND segment_idx = ANY(:idxs)"
)


@dataclass(frozen=True)
class PreviewPoint:
    """A control point where it snapped, and whether a raster splits its unit.

    Attributes
    ----------
    point : NetworkPoint
        Its place and node, as ``delineate_network`` gives them.
    inside_unit : bool
        It lies inside its unit, not at the unit's outlet cell: the full run splits
        the unit by the raster, and the preview's outlines of the elements on both
        sides follow the whole unit.
    """

    point: NetworkPoint
    inside_unit: bool


@dataclass(frozen=True)
class PreviewSubcatchment:
    """An element of the previewed network.

    Attributes
    ----------
    subcatchment : Subcatchment
        Its place in the tree.
    area_km2 : float
        Its area exact to the cell [km², 6 decimals], as the full run gives it.
    outline_approximate : bool
        It holds a part of a unit that a point splits: its outline follows the whole
        unit or leaves it out.
    boundary_2180 : BaseGeometry or None
        Its outline from the polygons of the units, EPSG:2180; None when it holds no
        polygon (only a part of a split unit that another element took).
    """

    subcatchment: Subcatchment
    area_km2: float
    outline_approximate: bool
    boundary_2180: BaseGeometry | None


@dataclass(frozen=True)
class PreviewReach:
    """A reach of the previewed network.

    Attributes
    ----------
    reach : Reach
        Its place in the tree.
    length_km : float or None
        Flow distance of its upper end less that of its lower end [km], as the full
        run gives it; None where the graph holds no flow distance of a junction.
    line_2180 : LineString or None
        The stream lines of its units between its ends, EPSG:2180; None where one of
        them is missing.
    """

    reach: Reach
    length_km: float | None
    line_2180: LineString | None


@dataclass(frozen=True)
class NetworkPreview:
    """A network composed on the catchment graph (ADR-081).

    Attributes
    ----------
    threshold_m2 : int
        The network the points snapped to [m²].
    area_km2 : float
        A's catchment, the sum of the elements [km², 6 decimals].
    points : tuple[PreviewPoint, ...]
        A, then the points in the order of the request.
    subcatchments : tuple[PreviewSubcatchment, ...]
        ``Z1``, ``Z2``, …
    reaches : tuple[PreviewReach, ...]
        ``R1``, ``R2``, …
    junctions : tuple[NetworkJunction, ...]
        ``J1``, ``J2``, …
    order : tuple[str, ...]
        The nodes in the order of the full run's hand-off, ``OUT`` last.
    reach_notices : tuple[ReachNotice, ...]
        The reaches shorter than SHORT_REACH_M or of the minimum slope, as the full
        run gives them: the slope from the NMT at the same end cells.
    """

    threshold_m2: int
    area_km2: float
    points: tuple[PreviewPoint, ...]
    subcatchments: tuple[PreviewSubcatchment, ...]
    reaches: tuple[PreviewReach, ...]
    junctions: tuple[NetworkJunction, ...]
    order: tuple[str, ...]
    reach_notices: tuple[ReachNotice, ...]


class UnitIndex:
    """The positions of the units of A's catchment in ``tree.units``.

    Attributes
    ----------
    tree : NetworkTree
        The tree whose units are indexed.
    below_pos : np.ndarray
        For each unit, the position of the unit it drains into; -1 for A's.
    """

    def __init__(self, tree: NetworkTree):
        self.tree = tree
        self._order = np.argsort(tree.units)
        self._sorted = tree.units[self._order]
        at = np.searchsorted(self._sorted, np.maximum(tree.below, 0))
        self.below_pos = np.where(
            tree.below >= 0, self._order[np.minimum(at, self._order.size - 1)], -1
        ).astype(np.int64)

    def position(self, unit: int) -> int:
        """Return the position of a unit of A's catchment in ``tree.units``."""
        return int(self._order[np.searchsorted(self._sorted, unit)])


def preview_network(
    cg: CatchmentGraph,
    db: Session,
    outlet: Click,
    points: Sequence[Click],
    threshold_m2: int,
    settings: Settings | None = None,
) -> NetworkPreview:
    """Compose the network of a closing section and its points on the graph.

    Parameters
    ----------
    cg : CatchmentGraph
        The loaded catchment graph; its units are ``DEFAULT_THRESHOLD_M2``'s.
    db : Session
        Database session: the polygons of the units and their stream lines.
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
    NetworkPreview
        The tree of the full run with the areas, lengths and outlines of the graph.

    Raises
    ------
    NotFoundError
        ``network_point_off_stream`` (``snap_point``).
    InvalidRequestError
        ``network_point_outside``, ``network_points_coincide`` (core.network_tree).
    StoreUnavailableError
        ``network_rasters_missing``, ``raster_grids_differ``.
    """
    started = time.perf_counter()
    with open_network_rasters(settings or get_settings()) as (rasters, nmt):
        snapped = [
            snap_point(rasters, cg, click, threshold_m2) for click in (outlet, *points)
        ]
        transform = rasters.filled_dem.transform
        cellsize_m = rasters.cellsize_m
        tree = build_network_tree(cg, snapped[0], snapped[1:])
        index = UnitIndex(tree)
        reach_units = {reach.id: _reach_units(index, reach) for reach in tree.reaches}
        vertices = _stream_lines(
            cg,
            db,
            {unit for units in reach_units.values() for unit in units}
            | {j.place.above for j in tree.junctions if isinstance(j.place, UnitHead)},
        )
        lengths = {reach.id: _length_km(cg, reach) for reach in tree.reaches}
        notices = _reach_notices(tree, lengths, rasters, nmt, cg, vertices, transform)
    built = time.perf_counter()

    cell_km2 = cellsize_m * cellsize_m / M2_PER_KM2
    unit_cells = np.rint(
        cg.get_area_km2(tree.units).astype(np.float64) / cell_km2
    ).astype(np.int64)
    parts = split_parts(tree, index, unit_cells)
    whole = tree.unit_elements.astype(np.int64)
    element_cells = np.bincount(
        whole, weights=unit_cells, minlength=len(tree.subcatchments) + 1
    ).astype(np.int64)
    # The split units have element 0 in the table: their parts count instead, and the
    # part of A's unit below A (0) stays outside
    element_cells[0] = 0
    outline_element = whole.copy()
    for unit, counts in parts.items():
        for number, cells in counts.items():
            if number > 0:
                element_cells[number] += cells
        position = index.position(unit)
        outline_element[position] = _largest_part(counts)
        whole[position] = -1
    nodes, elements = outline_cover(
        cg, tree, index, unit_cells, whole, outline_element, cell_km2
    )
    outlines = element_outlines(cg, db, nodes, elements)
    outlined = time.perf_counter()

    approximate = {
        number for split in tree.splits for _, number in split.outlets if number > 0
    }
    clicks = {click.point_id: click for click in (outlet, *points)}
    preview = NetworkPreview(
        threshold_m2=threshold_m2,
        area_km2=round(int(element_cells.sum()) * cell_km2, 6),
        points=tuple(
            PreviewPoint(
                point=_network_point(transform, point, clicks[point.point_id]),
                inside_unit=not point.place.at_outlet,
            )
            for point in tree.points
        ),
        subcatchments=tuple(
            PreviewSubcatchment(
                subcatchment=item,
                area_km2=round(int(element_cells[item.number]) * cell_km2, 6),
                outline_approximate=item.number in approximate,
                boundary_2180=outlines.get(item.number),
            )
            for item in tree.subcatchments
        ),
        reaches=tuple(
            PreviewReach(
                reach=reach,
                length_km=lengths[reach.id],
                line_2180=_reach_line(
                    reach, reach_units[reach.id], vertices, transform
                ),
            )
            for reach in tree.reaches
        ),
        junctions=tuple(
            NetworkJunction(
                junction, *_lat_lon(_junction_xy(junction.place, vertices, transform))
            )
            for junction in tree.junctions
        ),
        order=tree.order,
        reach_notices=notices,
    )
    logger.info(
        "Network preview: %d points, %d units and %d elements in %.3f s (the tree "
        "and its reaches %.3f s, the outlines of %d polygons %.3f s)",
        len(tree.points),
        tree.units.size,
        len(tree.subcatchments),
        time.perf_counter() - started,
        built - started,
        nodes.size,
        outlined - built,
    )
    return preview


def split_parts(
    tree: NetworkTree, index: UnitIndex, unit_cells: np.ndarray
) -> dict[int, dict[int, int]]:
    """Count the cells of each element in each unit that a point splits.

    A unit receives every unit above it at its head, so the cells of the unit that
    drain to its uppermost point are the accumulation there less the cells of the
    units above; each point below adds its accumulation less that of the point above
    it, and the last outlet (the unit's outlet cell, or a point at it) takes the rest
    of the unit. The element number 0 counts the part of A's unit below A, outside
    the network.

    Parameters
    ----------
    tree : NetworkTree
        The tree and its split units.
    index : UnitIndex
        The positions of the units of ``tree``.
    unit_cells : np.ndarray
        Cells of each unit of ``tree.units``.

    Returns
    -------
    dict[int, dict[int, int]]
        By split unit, the cells of each element number in it, in the order of the
        flow; they add up to the unit's cells.
    """
    upstream = _upstream_sums(unit_cells, index.below_pos)
    parts: dict[int, dict[int, int]] = {}
    for split in tree.splits:
        position = index.position(split.unit)
        remaining = int(unit_cells[position])
        above = int(upstream[position]) - remaining
        counts: dict[int, int] = defaultdict(int)
        for k, (where, number) in enumerate(split.outlets):
            if k == len(split.outlets) - 1:
                part = remaining
            else:
                accumulation = (
                    where.accumulation_cells
                    if isinstance(where, Place)
                    else int(upstream[position])
                )
                part = min(max(accumulation - above, 0), remaining)
                above = max(above, accumulation)
            counts[number] += part
            remaining -= part
        parts[split.unit] = dict(counts)
    return parts


def outline_cover(
    cg: CatchmentGraph,
    tree: NetworkTree,
    index: UnitIndex,
    unit_cells: np.ndarray,
    whole_element: np.ndarray,
    outline_element: np.ndarray,
    cell_km2: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Choose the polygons that draw the elements, and the element of each.

    Every unit of A's catchment is drawn by the largest unit of a coarser threshold
    that holds it and that one element holds whole, else by itself. A unit of a
    coarser threshold is made of the units of 1 ha above its outlet cell
    (``CatchmentGraph.coarser_at_outlets``) down to the next such outlet below; it is
    taken when all of them lie in A's catchment (their cells add up to its own) and
    belong to one element whole.

    Parameters
    ----------
    cg : CatchmentGraph
        The loaded graph.
    tree : NetworkTree
        The tree: A's units.
    index : UnitIndex
        The positions of the units of ``tree``.
    unit_cells : np.ndarray
        Cells of each unit of ``tree.units``.
    whole_element : np.ndarray
        The element of each unit, -1 for a unit that a point splits.
    outline_element : np.ndarray
        The element whose outline takes each unit: a split unit goes to the element
        with most of its cells, or to none (0).
    cell_km2 : float
        Area of a cell [km²].

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        The internal indices of the chosen units, of any threshold, and the element
        number of each.
    """
    chosen = tree.units.astype(np.int64)
    for _, at_outlet in sorted(cg.coarser_at_outlets(DEFAULT_THRESHOLD_M2).items()):
        coarse = _inherit(at_outlet[tree.units], index.below_pos)
        held = coarse >= 0
        nodes, group = np.unique(coarse[held], return_inverse=True)
        lowest = np.full(nodes.size, np.iinfo(np.int64).max, dtype=np.int64)
        highest = np.full(nodes.size, np.iinfo(np.int64).min, dtype=np.int64)
        np.minimum.at(lowest, group, whole_element[held])
        np.maximum.at(highest, group, whole_element[held])
        cells = np.bincount(group, weights=unit_cells[held], minlength=nodes.size)
        own_cells = np.rint(cg.get_area_km2(nodes).astype(np.float64) / cell_km2)
        taken = (lowest == highest) & (lowest > 0) & (np.rint(cells) == own_cells)
        take = np.zeros(chosen.size, dtype=bool)
        take[held] = taken[group]
        chosen[take] = coarse[take]
    nodes, first = np.unique(chosen, return_index=True)
    elements = outline_element[first]
    drawn = elements > 0
    return nodes[drawn], elements[drawn]


def element_outlines(
    cg: CatchmentGraph, db: Session, nodes: np.ndarray, elements: np.ndarray
) -> dict[int, BaseGeometry]:
    """Unite the polygons of the chosen units by element, on PREVIEW_GRID_M.

    Parameters
    ----------
    cg : CatchmentGraph
        The loaded graph: the threshold and segment of each node.
    db : Session
        Database session (``stream_catchments``).
    nodes, elements : np.ndarray
        The chosen units and their element numbers (``outline_cover``).

    Returns
    -------
    dict[int, BaseGeometry]
        The outline of each element number that has polygons, EPSG:2180, without
        the slivers between its units.
    """
    if nodes.size == 0:
        return {}
    rows = db.execute(
        _OUTLINES,
        {
            "thresholds": [cg.get_threshold_m2(node) for node in nodes.tolist()],
            "segments": [cg.get_segment_idx(node) for node in nodes.tolist()],
            "elements": elements.tolist(),
            "grid_m": PREVIEW_GRID_M,
        },
    ).fetchall()
    outlines = {}
    for row in rows:
        if row.geom is None:
            continue
        outline = _without_slivers(shapely.from_wkb(bytes(row.geom)))
        if outline is not None:
            outlines[int(row.element)] = outline
    return outlines


def _without_slivers(geometry: BaseGeometry) -> MultiPolygon | None:
    """Drop the holes and parts narrower than _SLIVER_WIDTH_M; None if none is left."""

    def wide(ring: Polygon) -> bool:
        length = float(ring.length)
        return length > 0 and 2 * float(ring.area) / length >= _SLIVER_WIDTH_M

    polygons = []
    for part in shapely.get_parts(geometry).tolist():
        if not isinstance(part, Polygon) or part.is_empty:
            continue
        if not wide(Polygon(part.exterior)):
            continue
        holes = [ring for ring in part.interiors if wide(Polygon(ring))]
        polygons.append(Polygon(part.exterior, holes))
    return MultiPolygon(polygons) if polygons else None


def _stream_lines(
    cg: CatchmentGraph, db: Session, units: set[int]
) -> dict[int, np.ndarray]:
    """Return the vertices of the stream lines of units, upstream end first."""
    if not units:
        return {}
    unit_of = {cg.get_segment_idx(unit): unit for unit in units}
    rows = db.execute(
        _STREAM_LINES, {"threshold": DEFAULT_THRESHOLD_M2, "idxs": sorted(unit_of)}
    ).fetchall()
    if not rows:
        return {}
    lines = shapely.from_wkb([bytes(row.geom) for row in rows])
    coords, which = shapely.get_coordinates(lines, return_index=True)
    numbers = np.arange(len(rows))
    starts = np.searchsorted(which, numbers, side="left")
    ends = np.searchsorted(which, numbers, side="right")
    return {
        unit_of[int(row.segment_idx)]: coords[start:end]
        for row, start, end in zip(rows, starts.tolist(), ends.tolist(), strict=True)
        if end - start >= 2
    }


def _reach_units(index: UnitIndex, reach: Reach) -> list[int]:
    """Return the units a reach runs through, from its upper end down.

    Down to the unit of its lower end when that is a control point, else (a
    junction at the head of a unit) to the unit above it on the reach's branch.
    """
    units = index.tree.units
    last = reach.lower.unit
    position = index.position(reach.upper.unit)
    found = []
    while True:
        unit = int(units[position])
        if unit == last and isinstance(reach.lower, UnitHead):
            break
        found.append(unit)
        if unit == last:
            break
        position = int(index.below_pos[position])
        if position < 0:
            raise ValueError(f"Reach {reach.id} does not reach its lower end")
    return found


def _reach_line(
    reach: Reach,
    units: list[int],
    vertices: dict[int, np.ndarray],
    transform: Affine,
) -> LineString | None:
    """Return the stream lines of a reach's units cut at its ends, None without one.

    Only the lines of its end units are cut, at the projections of the cells of its
    control points; the line is simplified at REACH_LINE_TOLERANCE_M (the stored
    lines carry three Chaikin iterations: eight vertices a cell).
    """
    parts: list[np.ndarray] = []
    for k, unit in enumerate(units):
        coords = vertices.get(unit)
        if coords is not None and k == 0 and isinstance(reach.upper, Place):
            coords = _cut(coords, _centre(transform, reach.upper.cell), upper=True)
        if (
            coords is not None
            and k == len(units) - 1
            and isinstance(reach.lower, Place)
        ):
            coords = _cut(coords, _centre(transform, reach.lower.cell), upper=False)
        if coords is None:
            return None
        parts.append(coords if not parts else coords[1:])
    if not parts:
        return None
    line = np.concatenate(parts)
    if len(line) < 2:
        return None
    simplified = shapely.simplify(LineString(line), REACH_LINE_TOLERANCE_M)
    return simplified if isinstance(simplified, LineString) else None


def _cut(
    coords: np.ndarray, at: tuple[float, float], *, upper: bool
) -> np.ndarray | None:
    """Return the vertices of a line below (``upper``) or above a point on it."""
    line = LineString(coords)
    distance = float(line.project(Point(at)))
    start, end = (distance, float(line.length)) if upper else (0.0, distance)
    if end <= start:
        return None
    cut = substring(line, start, end)
    return shapely.get_coordinates(cut) if isinstance(cut, LineString) else None


def _length_km(cg: CatchmentGraph, reach: Reach) -> float | None:
    """Flow distance of a reach's upper end less its lower end's [km] (D10)."""
    upper = _flow_dist_m(cg, reach.upper)
    lower = _flow_dist_m(cg, reach.lower)
    if upper is None or lower is None:
        return None
    return round((upper - lower) / M_PER_KM, 4)


def _flow_dist_m(cg: CatchmentGraph, where: Place | UnitHead) -> float | None:
    """Flow distance at an end of a reach [m]: the graph's at a junction."""
    if isinstance(where, Place):
        return where.flow_dist_m
    distance = cg.get_outlet_flow_dist_m(where.above)
    return None if np.isnan(distance) else distance


def _junction_xy(
    place: Place | UnitHead, vertices: dict[int, np.ndarray], transform: Affine
) -> tuple[float, float]:
    """Return the centre of a junction's cell: a point's, or the end of a line."""
    if isinstance(place, Place):
        return _centre(transform, place.cell)
    coords = vertices.get(place.above)
    if coords is None:
        raise ValueError(f"The stream line of unit {place.above} is missing")
    return float(coords[-1, 0]), float(coords[-1, 1])


def _centre(transform: Affine, cell: tuple[int, int]) -> tuple[float, float]:
    """Centre of a cell of the rasters, EPSG:2180."""
    x, y = transform * (cell[1] + 0.5, cell[0] + 0.5)
    return float(x), float(y)


def _lat_lon(xy: tuple[float, float]) -> tuple[float, float]:
    """Latitude and longitude of a place given in EPSG:2180."""
    lon, lat = transform_pl1992_to_wgs84(*xy)
    return lat, lon


def _reach_notices(
    tree: NetworkTree,
    lengths: dict[str, float | None],
    rasters: PipelineRasters,
    nmt: Any,
    cg: CatchmentGraph,
    vertices: dict[int, np.ndarray],
    transform: Affine,
) -> tuple[ReachNotice, ...]:
    """Return the reaches shorter than SHORT_REACH_M or of the minimum slope (D10a).

    The slope is the full run's: the NMT at the centres of the end cells (a
    junction's at the end of the stream line of the unit above it) over the length.
    """
    junctions = {j.id: j for j in tree.junctions}
    found = []
    for reach in tree.reaches:
        length_km = lengths[reach.id]
        if length_km is None:
            continue
        _, method, _, _ = reach_slope(
            nmt,
            _junction_xy(reach.upper, vertices, transform),
            _junction_xy(reach.lower, vertices, transform),
            length_km,
        )
        if not is_short_or_flat(length_km, method):
            continue
        near = _junction_xy(junctions[reach.to].place, vertices, transform)

        def outlet_lat_lon(
            unit: int, near: tuple[float, float] = near
        ) -> tuple[float, float] | None:
            cell = unit_outlet_near(rasters, cg, unit, near)
            return None if cell is None else _lat_lon(_centre(transform, cell))

        found.append(reach_notice(tree, reach, length_km, method, outlet_lat_lon))
    return tuple(found)


def _network_point(transform: Affine, point: PointNode, click: Click) -> NetworkPoint:
    """Place a control point where it lies, with its distance from its click."""
    x, y = _centre(transform, point.place.cell)
    latitude, longitude = _lat_lon((x, y))
    return NetworkPoint(
        point_id=point.point_id,
        latitude=latitude,
        longitude=longitude,
        snap_distance_m=round(float(np.hypot(x - click.x, y - click.y)), 1),
        at_mouth=point.at_mouth,
        node=point.node,
    )


def _largest_part(counts: dict[int, int]) -> int:
    """Return the element with most cells of a split unit, the upper one on a tie."""
    best: int | None = None
    for number, cells in counts.items():
        if best is None or cells > counts[best]:
            best = number
    return 0 if best is None else best


@numba.njit(cache=True)
def _upstream_sums(cells: np.ndarray, below_pos: np.ndarray) -> np.ndarray:
    """Cells of each unit and of every unit above it.

    The units are in the order of ``upstream_tree``, each after the unit below it.
    """
    upstream = cells.copy()
    for i in range(cells.size - 1, 0, -1):
        if below_pos[i] >= 0:
            upstream[below_pos[i]] += upstream[i]
    return upstream


@numba.njit(cache=True)
def _inherit(own: np.ndarray, below_pos: np.ndarray) -> np.ndarray:
    """Give every unit without a value of its own the value of the unit below it.

    The units are in the order of ``upstream_tree``, each after the unit below it.
    """
    value = own.copy()
    for i in range(value.size):
        if value[i] < 0 and below_pos[i] >= 0:
            value[i] = value[below_pos[i]]
    return value
