"""
The tree of a network delineated at control points, built on the catchment graph.

ADR-080 and the plans ``docs/plans/2026-11-10-network-delineation.md`` (D4, D5, D15)
and ``docs/plans/2026-11-11-network-nodes.md`` (N1 to N8). The control points, the
closing section and the points of the request, each snapped to a stream cell
(``core.network_delineation``), form a tree along their flow paths:

- a node of the network is a confluence of its rivers: the head cell of a unit at
  which two or more units end whose upstream area reaches ``threshold_m2``, the
  network the points snapped to (N2);
- every control point, the closing section included, moves to the nearest node along
  the stream within MOUTH_TOLERANCE_M: the first node on its flow path below it, or
  the head cell of its own unit above it, the nearer by flow distance and the lower
  on a tie (N3). Every control point is a node of the tree, a ``J`` at a confluence
  and a ``P`` elsewhere (N1, N4);
- the parent of a point is the first control point on its flow path downstream: the
  nearest below it in its own unit, else the uppermost in the first unit below that
  holds one, the closing section at the latest;
- the trunk of a control point is its main river: from its cell up its unit's
  segment, then up the units ``CatchmentGraph.trace_main_channel`` chooses (ADR-046);
- a point joins its parent's trunk at itself when its unit is on the trunk (a gauge on
  the main river), else at the head cell of the trunk unit its path enters, a
  confluence: a ``J`` the network makes (D4);
- the points whose paths enter a trunk through the same unit form a branch, and a
  branch has a trunk of its own: the main river from that unit up, by the same rule.
  Each point of a branch joins the branch's trunk as a point joins its parent's trunk,
  and the points whose paths enter the branch's trunk through one unit form a branch
  of the branch (B1). So every reach runs down a main river, and the main river of a
  branch is a headwater above its uppermost node, not a part of a przyrzecze (B2);
- the nodes of a trunk are its confluences and the point it carries; its edges run
  between consecutive nodes and from the lowest node to the control point, or to the
  confluence the branch enters. Every edge is a reach with its intermediate catchment
  (przyrzecze); the trunk above its uppermost node is a headwater when that node is a
  confluence the network makes;
- a ``P`` receives its trunk alone: a headwater, or the reach from the lowest node
  above it; a ``J`` receives every branch that joins at its cell, the trunk first: a
  branch of points by the reach from its lowest node, a river without a point as a
  headwater of its own (N4). A river that joins a reach between its ends stays in its
  przyrzecze.

The elements are made of the units of the graph (``DEFAULT_THRESHOLD_M2``): every
element ends at one outlet cell and holds the cells whose first element outlet
downstream is its own (D5). An element that reaches a ``P`` ends at its cell; one that
reaches a ``J`` ends at the outlet cell of its unit above the node, so the node's own
cell and the cells that drain into it from the side belong to the element below it
(N5). The part of the closing section's unit below it lies outside the network; when
the closing section is a ``J``, all of its unit and the streams below the threshold
that join at its cell lie outside. A unit belongs to the element of the first element
outlet on its segment from its head, else to the element its unit below receives at
its head; a unit with a ``P`` inside, not at its outlet cell, is split by the raster
(``core.network_delineation``, D6). Nothing here reads a raster: the cells of the
control points and of their paths come from their snapping.
"""

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Literal

import numpy as np

from core.catchment_graph import CatchmentGraph
from core.constants import M2_PER_KM2
from core.errors import InvalidRequestError

# A control point moves to the nearest node of the network at most this far along the
# stream, below or above it (N3) [m]
MOUTH_TOLERANCE_M = 50.0
# The id of the outlet of the network, into which the closing section's node flows
OUTLET_ID = "O"

type ElementKind = Literal["headwater", "intermediate"]
type JunctionKind = Literal["confluence", "point", "outlet"]


@dataclass(frozen=True)
class Place:
    """A stream cell of a unit: where a control point lies.

    Attributes
    ----------
    cell : tuple[int, int]
        Row and column of the cell in the grid of the rasters.
    unit : int
        Internal graph index of its unit (its label at ``DEFAULT_THRESHOLD_M2``).
    flow_dist_m : float
        Flow distance to the outlet of the grid at the cell [m].
    at_head : bool
        Another unit drains into the cell: it is the head cell of its unit, at a
        confluence.
    at_outlet : bool
        The cell is the outlet cell of its unit: it drains out of the unit.
    accumulation_cells : int
        Cells that drain through the cell, itself included (``04_flowacc``): the
        preview counts the parts of a unit split by a point with it
        (``core.network_preview``).
    """

    cell: tuple[int, int]
    unit: int
    flow_dist_m: float
    at_head: bool = False
    at_outlet: bool = False
    accumulation_cells: int = 0


@dataclass(frozen=True)
class ControlPoint:
    """A control point snapped to a stream cell (D2).

    Attributes
    ----------
    point_id : str
        Its id in the request: the client's handle of the point, which no id of the
        network takes (N1).
    place : Place
        Its cell.
    path : tuple[Place, ...]
        The cells below ``place`` along the flow, nearest first, as far as
        MOUTH_TOLERANCE_M below it (fewer where the flow ends): where N3 may move
        the point down.
    upstream : tuple[Place, ...]
        The cells above ``place`` up its unit's stream, nearest first, as far as the
        unit's head cell and no farther than MOUTH_TOLERANCE_M above it (fewer where
        the stream of the request's network ends): where N3 may move the point up.
    """

    point_id: str
    place: Place
    path: tuple[Place, ...] = ()
    upstream: tuple[Place, ...] = ()


@dataclass(frozen=True)
class UnitOutlet:
    """The outlet cell of a unit: the cell of its largest flow accumulation."""

    unit: int


@dataclass(frozen=True)
class UnitHead:
    """The head cell of a unit at a confluence: the cell below the outlet of ``above``.

    Its flow distance is ``CatchmentGraph.get_outlet_flow_dist_m(above)``.
    """

    unit: int
    above: int


@dataclass(frozen=True)
class Subcatchment:
    """An element of the network: a headwater or a przyrzecze.

    Attributes
    ----------
    id : str
        ``Z1``, ``Z2``, … numbered from the closing section up (N8).
    number : int
        Its value in the element raster: 1 for ``Z1``.
    kind : ElementKind
        ``headwater`` (a river that enters its node with no reach) or
        ``intermediate`` (the przyrzecze of a reach).
    to : str
        The node it flows into.
    point : str or None
        The id in the request of the control point of that node; None at a
        confluence the network makes.
    reach : str or None
        The reach of a przyrzecze.
    outlet : Place or UnitOutlet
        Its outlet cell: the cell of a ``P``, or the outlet cell of its unit above a
        ``J`` (N5).
    """

    id: str
    number: int
    kind: ElementKind
    to: str
    point: str | None
    reach: str | None
    outlet: Place | UnitOutlet


@dataclass(frozen=True)
class Reach:
    """An edge of the tree: a reach from its upper node down to its lower one.

    Attributes
    ----------
    id : str
        ``R1``, ``R2``, … numbered from the closing section up (N8).
    from_node : str
        The node it receives.
    to : str
        The node it flows into.
    upper, lower : Place or UnitHead
        The cells of its ends.
    intermediate : str or None
        Its przyrzecze; None when that has no cells (D5: an edge from a ``P`` at the
        outlet cell of the unit above the node below it).
    """

    id: str
    from_node: str
    to: str
    upper: Place | UnitHead
    lower: Place | UnitHead
    intermediate: str | None


@dataclass(frozen=True)
class Junction:
    """A node of the network: a control point, or a confluence the network makes.

    Attributes
    ----------
    id : str
        ``J1``, ``J2``, … at a confluence, ``P1``, ``P2``, … elsewhere, each counted
        on its own from the closing section up (N1, N8).
    kind : JunctionKind
        ``confluence`` (made by the network), ``point`` (a point of the request) or
        ``outlet`` (the closing section's, which flows into ``OUTLET_ID``).
    point : str or None
        The id in the request of its control point.
    place : Place or UnitHead
        Its cell.
    inflows : tuple[str, ...]
        The nodes it receives: the trunk's first, then the branches in descending
        order of the accumulation of their last cell.
    """

    id: str
    kind: JunctionKind
    point: str | None
    place: Place | UnitHead
    inflows: tuple[str, ...]


@dataclass(frozen=True)
class PointNode:
    """A control point in the network.

    Attributes
    ----------
    point_id : str
        Its id in the request.
    place : Place
        Its cell, after N3.
    at_node : bool
        It lies at a node of the network (N2): N3 drew it there, also from the
        node's own cell, and its node is a ``J``.
    node : str
        Its node.
    """

    point_id: str
    place: Place
    at_node: bool
    node: str


@dataclass(frozen=True)
class SplitUnit:
    """A unit with a ``P`` inside: its outlets and their elements (D6).

    Attributes
    ----------
    unit : int
        Internal graph index of the unit.
    outlets : tuple[tuple[Place or UnitOutlet, int], ...]
        In the order of the flow: each ``P`` in it and, unless one lies at its
        outlet cell, its outlet cell, with the element number each cell above it
        (and below the outlet above) takes; 0 outside the network (the part of the
        closing section's unit below it).
    """

    unit: int
    outlets: tuple[tuple[Place | UnitOutlet, int], ...]


@dataclass(frozen=True)
class NetworkTree:
    """The network of a closing section and its points, on the graph.

    Attributes
    ----------
    points : tuple[PointNode, ...]
        The closing section, then the points in the order of the request.
    subcatchments : tuple[Subcatchment, ...]
        ``Z1``, ``Z2``, …
    reaches : tuple[Reach, ...]
        ``R1``, ``R2``, …
    junctions : tuple[Junction, ...]
        Every node in the order of their numbers (N8): the closing section's first,
        every node before the nodes above it.
    order : tuple[str, ...]
        Every node in the order of D15, each after every node it receives,
        ``OUTLET_ID`` last.
    units : np.ndarray
        The closing section's catchment: the internal indices of the units
        (``upstream_tree`` of its unit, which comes first).
    below : np.ndarray
        The internal index of the unit each unit of ``units`` drains into; -1 for
        the closing section's.
    unit_elements : np.ndarray
        The element number of each unit of ``units``; 0 for a split unit and for the
        units outside the network (the closing section's at a node, with the streams
        below the threshold that join at its cell).
    splits : tuple[SplitUnit, ...]
        The units the raster splits.
    """

    points: tuple[PointNode, ...]
    subcatchments: tuple[Subcatchment, ...]
    reaches: tuple[Reach, ...]
    junctions: tuple[Junction, ...]
    order: tuple[str, ...]
    units: np.ndarray
    below: np.ndarray
    unit_elements: np.ndarray
    splits: tuple[SplitUnit, ...]


@dataclass(eq=False)
class _Element:
    """An element while the tree is built."""

    kind: ElementKind
    outlet: Place | UnitOutlet
    reach: "_Edge | None" = None
    id: str = ""
    number: int = 0
    to: str = ""
    point: str | None = None


@dataclass(eq=False)
class _Node:
    """A node while the tree is built: a control point or a confluence."""

    place: Place | UnitHead
    kind: JunctionKind
    point: str | None = None
    # A control point at a node of the network (N3)
    at_node: bool = False
    branches: list["_Branch"] = field(default_factory=list)
    id: str = ""

    @property
    def at_confluence(self) -> bool:
        """Whether it lies at a node of the network: a ``J`` (N1)."""
        return isinstance(self.place, UnitHead) or self.at_node


@dataclass(eq=False)
class _Edge:
    """An edge while the tree is built."""

    upper: _Node
    lower: _Node
    intermediate: _Element | None
    id: str = ""


@dataclass(eq=False)
class _Branch:
    """What a node receives from one side: an edge or a headwater.

    ``unit`` is the last unit of the branch above the node, whose accumulation
    orders the branches after the trunk's.
    """

    trunk: bool
    unit: int
    accumulation_km2: float
    edge: _Edge | None = None
    headwater: _Element | None = None


@dataclass(frozen=True)
class _Link:
    """How a point joins its parent's trunk.

    ``entry`` is None on the trunk, else the trunk unit its path enters and the unit
    of the path above it.
    """

    parent: str
    entry: tuple[int, int] | None


class _Catchment:
    """The catchment of a unit on the graph: the units below and above each, the trunks.

    Parameters
    ----------
    cg : CatchmentGraph
        The loaded graph.
    unit : int
        Internal index of the unit at its outlet.
    threshold_m2 : int
        The network the points snapped to [m²]: its rivers.
    """

    def __init__(self, cg: CatchmentGraph, unit: int, threshold_m2: int):
        self.cg = cg
        self.units, below = cg.upstream_tree(unit)
        self.below_array = below
        self.threshold_m2 = threshold_m2
        self.below: dict[int, int] = dict(
            zip(self.units.tolist(), below.tolist(), strict=True)
        )
        # The units that drain into the head cell of each unit
        self.above: dict[int, list[int]] = defaultdict(list)
        for upper, down in self.below.items():
            if down >= 0:
                self.above[down].append(upper)
        self._trunks: dict[int, tuple[list[int], dict[int, int]]] = {}

    def trunk(self, unit: int) -> tuple[list[int], dict[int, int]]:
        """Units of the main river from ``unit`` up, and the position of each."""
        if unit not in self._trunks:
            nodes = self.cg.trace_main_channel(unit, self.units)["main_channel_nodes"]
            trunk = [int(n) for n in nodes]
            self._trunks[unit] = trunk, {u: i for i, u in enumerate(trunk)}
        return self._trunks[unit]

    def accumulation_km2(self, unit: int) -> float:
        """Upstream area at the end of a unit's segment [km²]; 0 when not loaded."""
        area = self.cg.get_upstream_area_km2(unit)
        return 0.0 if math.isnan(area) else area

    def rivers(self, unit: int, beside: Iterable[int]) -> list[int]:
        """Return the units of the rivers that join at the head cell of ``unit``.

        A river is a stream of the network the points snapped to: its upstream area
        reaches ``threshold_m2``. The units ``beside`` (the trunk's, the branches of
        points) are left out.
        """
        skip = set(beside)
        return [
            side
            for side in self.above.get(unit, [])
            if side not in skip
            and self.accumulation_km2(side) * M2_PER_KM2 >= self.threshold_m2
        ]

    def is_node(self, unit: int) -> bool:
        """Whether the head cell of a unit is a node of the network (N2).

        Two or more rivers end there; the units of 1 ha that join below the
        threshold do not count.
        """
        return len(self.rivers(unit, ())) >= 2


def build_network_tree(
    cg: CatchmentGraph,
    outlet: ControlPoint,
    points: Sequence[ControlPoint],
    threshold_m2: int,
) -> NetworkTree:
    """Build the network of a closing section and its points (N1 to N8, D4, D5, D15).

    Parameters
    ----------
    cg : CatchmentGraph
        The loaded graph of the units (``DEFAULT_THRESHOLD_M2``).
    outlet : ControlPoint
        The closing section.
    points : Sequence[ControlPoint]
        The points of the request, ids unique without regard to case; possibly none.
    threshold_m2 : int
        The network the points snapped to [m²]: its confluences are the nodes the
        control points move to (N2, N3), and a river of it that joins at a node
        without a point is a headwater of its own.

    Returns
    -------
    NetworkTree
        The nodes, the elements of the units and the units to split.

    Raises
    ------
    InvalidRequestError
        ``validation_error``: ``network_point_outside`` for a point that does not
        drain to the closing section; ``network_points_coincide`` for control points
        on one cell after N3, in practice on one node (N6).
    """
    # The units the closing section can move into, with all above them: a point that
    # drains to the closing section moves among these
    lowest = outlet.path[-1].unit if outlet.path else outlet.place.unit
    around = _Catchment(cg, lowest, threshold_m2)
    drawn = {c.point_id: _drawn(around, c) for c in (outlet, *points)}
    controls = {
        point_id: ControlPoint(point_id, place)
        for point_id, (place, _) in drawn.items()
    }
    closing = controls[outlet.point_id]
    catchment = (
        around
        if closing.place.unit == lowest
        else _Catchment(cg, closing.place.unit, threshold_m2)
    )
    _require_inside(catchment, closing, [controls[p.point_id] for p in points])
    _require_apart(controls.values())

    links = _links(catchment, controls, outlet.point_id)
    nodes = {
        point_id: _Node(
            place=control.place,
            kind="outlet" if point_id == outlet.point_id else "point",
            point=point_id,
            at_node=drawn[point_id][1],
        )
        for point_id, control in controls.items()
    }
    children: dict[str, list[str]] = defaultdict(list)
    for point_id, link in links.items():
        children[link.parent].append(point_id)
    for point_id, node in nodes.items():
        _wire_trunk(catchment, nodes, links, node, children[point_id])

    elements, numbered, order = _number(nodes[outlet.point_id])
    reaches, junctions = _connect(numbered)
    unit_elements, splits = _unit_elements(catchment, elements)
    return NetworkTree(
        points=tuple(
            PointNode(
                point_id=point_id,
                place=controls[point_id].place,
                at_node=node.at_node,
                node=node.id,
            )
            for point_id, node in nodes.items()
        ),
        subcatchments=tuple(
            Subcatchment(
                id=el.id,
                number=el.number,
                kind=el.kind,
                to=el.to,
                point=el.point,
                reach=el.reach.id if el.reach is not None else None,
                outlet=el.outlet,
            )
            for el in elements
        ),
        reaches=tuple(reaches),
        junctions=tuple(junctions),
        order=tuple(order),
        units=catchment.units,
        below=catchment.below_array,
        unit_elements=unit_elements,
        splits=splits,
    )


def _drawn(catchment: _Catchment, control: ControlPoint) -> tuple[Place, bool]:
    """Where N3 moves a control point, and whether that is a node of the network.

    The node is its own cell when that is one, else the first node on its flow path
    at most MOUTH_TOLERANCE_M below it or the head cell of its own unit at most
    MOUTH_TOLERANCE_M above it, the nearer by flow distance, the lower on a tie.
    Without one it keeps its cell.
    """
    place = control.place
    if place.at_head and catchment.is_node(place.unit):
        return place, True
    fd = place.flow_dist_m
    down = next(
        (
            cell
            for cell in control.path
            if fd - cell.flow_dist_m <= MOUTH_TOLERANCE_M
            and cell.at_head
            and catchment.is_node(cell.unit)
        ),
        None,
    )
    head = control.upstream[-1] if control.upstream else None
    up = (
        head
        if head is not None
        and head.at_head
        and head.flow_dist_m - fd <= MOUTH_TOLERANCE_M
        and catchment.is_node(head.unit)
        else None
    )
    if down is not None and (
        up is None or fd - down.flow_dist_m <= up.flow_dist_m - fd
    ):
        return down, True
    if up is not None:
        return up, True
    return place, False


def _require_inside(
    catchment: _Catchment, outlet: ControlPoint, points: Sequence[ControlPoint]
) -> None:
    """Refuse a point outside the catchment or below the closing section in its unit."""
    for point in points:
        place = point.place
        below_outlet = (
            place.unit == outlet.place.unit
            and place.flow_dist_m <= outlet.place.flow_dist_m
            and place.cell != outlet.place.cell
        )
        if place.unit not in catchment.below or below_outlet:
            raise InvalidRequestError(
                "network_point_outside",
                reason="network_point_outside",
                point_id=point.point_id,
                outlet_id=outlet.point_id,
            )


def _require_apart(controls: Iterable[ControlPoint]) -> None:
    """Refuse control points on one cell, naming the first group of them (N6)."""
    by_cell: dict[tuple[int, int], list[str]] = defaultdict(list)
    for control in controls:
        by_cell[control.place.cell].append(control.point_id)
    for point_ids in by_cell.values():
        if len(point_ids) > 1:
            raise InvalidRequestError(
                "network_points_coincide",
                reason="network_points_coincide",
                point_ids=point_ids,
            )


def _links(
    catchment: _Catchment, controls: dict[str, ControlPoint], outlet_id: str
) -> dict[str, _Link]:
    """Find the parent of every point and where its path joins its trunk (D4)."""
    by_unit: dict[int, list[ControlPoint]] = defaultdict(list)
    for control in controls.values():
        by_unit[control.place.unit].append(control)
    links = {}
    for point_id, control in controls.items():
        if point_id == outlet_id:
            continue
        parent = _parent(catchment, by_unit, control)
        _, position = catchment.trunk(parent.place.unit)
        entry = _entry(catchment, control.place.unit, position)
        links[point_id] = _Link(parent=parent.point_id, entry=entry)
    return links


def _parent(
    catchment: _Catchment,
    by_unit: dict[int, list[ControlPoint]],
    control: ControlPoint,
) -> ControlPoint:
    """Return the first control point on the flow path below a point."""
    fd = control.place.flow_dist_m
    below_in_unit = [
        other for other in by_unit[control.place.unit] if other.place.flow_dist_m < fd
    ]
    if below_in_unit:
        return max(below_in_unit, key=lambda other: other.place.flow_dist_m)
    unit = catchment.below[control.place.unit]
    while unit >= 0:
        if by_unit.get(unit):
            return max(by_unit[unit], key=lambda other: other.place.flow_dist_m)
        unit = catchment.below[unit]
    raise AssertionError(f"{control.point_id} has no control point below it")


def _entry(
    catchment: _Catchment, unit: int, position: dict[int, int]
) -> tuple[int, int] | None:
    """Where the path down from a unit enters a trunk, by the positions of its units.

    None when the unit lies on the trunk, else the trunk unit the path enters at its
    head cell, a confluence, and the unit of the path above it.
    """
    if unit in position:
        return None
    above, unit = unit, catchment.below[unit]
    while unit not in position:
        above, unit = unit, catchment.below[unit]
    return unit, above


def _branch_groups(
    catchment: _Catchment, units: Sequence[int], above: int
) -> tuple[list[int], dict[tuple[int, int], list[int]]]:
    """Split the units of points by where their paths enter the trunk of a branch (D4).

    The branch flows through the unit ``above``; its trunk is the main river from
    ``above`` up. Returns the positions in ``units`` of the units on the trunk, and
    those of the others by their entry (``_entry``).
    """
    _, position = catchment.trunk(above)
    on_trunk: list[int] = []
    groups: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, unit in enumerate(units):
        entry = _entry(catchment, unit, position)
        if entry is None:
            on_trunk.append(i)
        else:
            groups[entry].append(i)
    return on_trunk, groups


def _wire_trunk(
    catchment: _Catchment,
    nodes: dict[str, _Node],
    links: dict[str, _Link],
    parent: _Node,
    kids: list[str],
) -> None:
    """Give a control point its branches: its trunk and, at a node, all joining there.

    The points of ``kids`` join the trunk at the confluences where their paths enter
    it, or lie on it (D4). A ``P`` receives the trunk alone, whose element ends at its
    cell; a ``J`` receives the trunk, the branches of points that join at its cell
    and every river without a point that joins there, each ending at the outlet cell
    of its unit above the node (N4, N5).
    """
    place = parent.place
    assert isinstance(place, Place)
    trunk, position = catchment.trunk(place.unit)
    gauges = [nodes[kid] for kid in kids if links[kid].entry is None]
    assert len(gauges) <= 1, "two gauges cannot share a parent"
    # The children off the trunk by the confluence they enter (None: the parent's own
    # cell, at the head of its unit) and the last unit of their path above it
    groups: dict[tuple[int | None, int], list[str]] = defaultdict(list)
    for kid in kids:
        entry = links[kid].entry
        if entry is None:
            continue
        trunk_unit, above = entry
        at_parent = trunk_unit == place.unit and place.at_head
        groups[(None if at_parent else trunk_unit, above)].append(kid)

    confluences = _confluences(
        trunk, position, (unit for unit, _ in groups if unit is not None)
    )
    trunk_nodes = [*confluences.values(), *gauges]
    if parent.at_node:
        # The trunk enters the node at its head cell from the unit above it
        parent.branches.append(
            _branch(catchment, trunk_nodes[0], parent, trunk[1], trunk=True)
            if trunk_nodes
            else _headwater(catchment, trunk[1], trunk=True)
        )
    elif trunk_nodes:
        parent.branches.append(
            _Branch(
                trunk=True,
                unit=place.unit,
                accumulation_km2=0.0,
                edge=_edge(trunk_nodes[0], parent, place),
            )
        )
    else:
        parent.branches.append(
            _Branch(
                trunk=True,
                unit=place.unit,
                accumulation_km2=0.0,
                headwater=_Element(kind="headwater", outlet=place),
            )
        )
    if trunk_nodes:
        _wire_along(catchment, trunk, position, trunk_nodes)

    for (junction_unit, above), members in groups.items():
        target = parent if junction_unit is None else confluences[junction_unit]
        target.branches.append(
            _group_branch(catchment, [nodes[m] for m in members], above, target)
        )
    for unit, confluence in confluences.items():
        _add_rivers(catchment, confluence, [side for at, side in groups if at == unit])
    if parent.at_node:
        _add_rivers(catchment, parent, [side for at, side in groups if at is None])


def _add_rivers(catchment: _Catchment, node: _Node, branches: list[int]) -> None:
    """Let the rivers that join at a node's cell enter it, each a headwater (N4).

    ``branches`` are the units through which the branches of points enter the cell;
    the trunk's unit above the cell is left out too. A smaller stream stays in the
    element its cells drain to.
    """
    if isinstance(node.place, UnitHead):
        beside = [node.place.above, *branches]
    else:
        trunk, _ = catchment.trunk(node.place.unit)
        beside = [*trunk[1:2], *branches]
    for side in catchment.rivers(node.place.unit, beside):
        node.branches.append(_headwater(catchment, side, trunk=False))


def _confluences(
    trunk: list[int], position: dict[int, int], units: Iterable[int]
) -> dict[int, _Node]:
    """Make a confluence at the head cell of each trunk unit, from the bottom up."""
    return {
        unit: _Node(
            place=UnitHead(unit=unit, above=trunk[position[unit] + 1]),
            kind="confluence",
        )
        for unit in sorted(set(units), key=position.__getitem__)
    }


def _wire_along(
    catchment: _Catchment,
    trunk: list[int],
    position: dict[int, int],
    nodes: list[_Node],
) -> None:
    """Join the nodes of a trunk, from the bottom up, by the edges between them.

    The lower node of every edge is a confluence. The trunk above the top node is a
    headwater that enters it when the node is a confluence; a point there receives
    its own trunk (``_wire_trunk``).
    """
    for lower, upper in pairwise(nodes):
        above = trunk[position[lower.place.unit] + 1]
        lower.branches.append(_branch(catchment, upper, lower, above, trunk=True))
    top = nodes[-1]
    if top.point is None:
        above = trunk[position[top.place.unit] + 1]
        top.branches.append(_headwater(catchment, above, trunk=True))


def _edge(upper: _Node, lower: _Node, end: Place | UnitOutlet) -> _Edge:
    """Make an edge and its przyrzecze, which ends at ``end``.

    The przyrzecze has no cells when the upper node is a ``P`` at the outlet cell it
    would end at (D5: an edge between two neighbouring cells); a ``J`` there gives it
    its own cell (N5).
    """
    empty = (
        isinstance(end, UnitOutlet)
        and isinstance(upper.place, Place)
        and not upper.at_node
        and upper.place.unit == end.unit
        and upper.place.at_outlet
    )
    intermediate = None if empty else _Element(kind="intermediate", outlet=end)
    edge = _Edge(upper=upper, lower=lower, intermediate=intermediate)
    if intermediate is not None:
        intermediate.reach = edge
    return edge


def _branch(
    catchment: _Catchment, upper: _Node, lower: _Node, above: int, *, trunk: bool
) -> _Branch:
    """Make the branch from ``upper`` into the node ``lower`` through ``above``.

    An edge whose przyrzecze ends at the outlet cell of ``above``, the last unit of
    the branch above the node (N5).
    """
    return _Branch(
        trunk=trunk,
        unit=above,
        accumulation_km2=catchment.accumulation_km2(above),
        edge=_edge(upper, lower, UnitOutlet(above)),
    )


def _headwater(catchment: _Catchment, unit: int, *, trunk: bool) -> _Branch:
    """Make the branch of a river without a point that enters a node through ``unit``.

    A headwater that ends at the outlet cell of ``unit`` (N5).
    """
    return _Branch(
        trunk=trunk,
        unit=unit,
        accumulation_km2=catchment.accumulation_km2(unit),
        headwater=_Element(kind="headwater", outlet=UnitOutlet(unit)),
    )


def _group_branch(
    catchment: _Catchment, members: list[_Node], above: int, target: _Node
) -> _Branch:
    """Make the branch of the points whose paths enter a node through one unit.

    The branch has a trunk of its own, the main river from ``above`` up (B1, B2):
    the point on it, if any, is its uppermost node, and the others join it at the
    confluences where their paths enter it, each group of them a branch of the
    branch, the rivers beside them each a headwater. The lowest node enters the node
    ``target`` by an edge whose przyrzecze ends at the outlet cell of ``above``.
    """
    trunk, position = catchment.trunk(above)
    on_trunk, groups = _branch_groups(
        catchment, [member.place.unit for member in members], above
    )
    # A second point on the trunk would lie on the path of the first: its parent
    assert len(on_trunk) <= 1, "two points of a branch on its trunk"
    confluences = _confluences(trunk, position, (unit for unit, _ in groups))
    nodes = [*confluences.values(), *(members[i] for i in on_trunk)]
    _wire_along(catchment, trunk, position, nodes)
    for (unit, side), indices in groups.items():
        confluences[unit].branches.append(
            _group_branch(
                catchment, [members[i] for i in indices], side, confluences[unit]
            )
        )
    for unit, confluence in confluences.items():
        _add_rivers(catchment, confluence, [side for at, side in groups if at == unit])
    return _branch(catchment, nodes[0], target, above, trunk=False)


def _branch_key(branch: _Branch) -> tuple[bool, float, int]:
    """Sort the trunk first, then by descending accumulation of the last cell (D15)."""
    return (not branch.trunk, -branch.accumulation_km2, branch.unit)


def _number(root: _Node) -> tuple[list[_Element], list[_Node], list[str]]:
    """Give the nodes and elements their numbers from the closing section up (N8).

    A walk from the closing section, each node before the branches it receives, in
    the order of ``_branch_key``: a branch that is an edge brings its reach and its
    przyrzecze, then the node above it with everything that node receives. Each kind
    (``J``, ``P``, ``Z``, ``R``) is counted on its own, so the closing section is
    ``J1`` or ``P1`` and the numbers grow upstream. The order of the hand-off lists
    every node after every node it receives: at a node, each branch's nodes, its
    reach and its przyrzecze, then the node itself; ``OUTLET_ID`` last.

    Returns
    -------
    tuple[list[_Element], list[_Node], list[str]]
        The elements by their numbers, the nodes by their numbers (the closing
        section first) and the order of the hand-off.
    """
    counts: dict[str, int] = defaultdict(int)
    elements: list[_Element] = []
    nodes: list[_Node] = []
    order: list[str] = []

    def name(prefix: str) -> str:
        counts[prefix] += 1
        return f"{prefix}{counts[prefix]}"

    def element(item: _Element) -> None:
        item.id = name("Z")
        item.number = counts["Z"]
        elements.append(item)

    def number(node: _Node) -> None:
        node.id = name("J" if node.at_confluence else "P")
        nodes.append(node)
        node.branches.sort(key=_branch_key)
        for branch in node.branches:
            if branch.edge is not None:
                branch.edge.id = name("R")
                if branch.edge.intermediate is not None:
                    element(branch.edge.intermediate)
                number(branch.edge.upper)
            else:
                assert branch.headwater is not None
                element(branch.headwater)

    def walk(node: _Node) -> None:
        for branch in node.branches:
            if branch.edge is not None:
                walk(branch.edge.upper)
                order.append(branch.edge.id)
                if branch.edge.intermediate is not None:
                    order.append(branch.edge.intermediate.id)
            else:
                assert branch.headwater is not None
                order.append(branch.headwater.id)
        order.append(node.id)

    number(root)
    walk(root)
    order.append(OUTLET_ID)
    return elements, nodes, order


def _connect(nodes: list[_Node]) -> tuple[list[Reach], list[Junction]]:
    """Make the reaches and junctions, and set the node each element flows into."""
    reaches = []
    junctions = []
    for node in nodes:
        inflows: list[str] = []
        for branch in node.branches:
            if branch.edge is not None:
                edge = branch.edge
                inflows.append(edge.id)
                intermediate_id = None
                if edge.intermediate is not None:
                    edge.intermediate.to = node.id
                    edge.intermediate.point = node.point
                    intermediate_id = edge.intermediate.id
                    inflows.append(intermediate_id)
                reaches.append(
                    Reach(
                        id=edge.id,
                        from_node=edge.upper.id,
                        to=node.id,
                        upper=edge.upper.place,
                        lower=node.place,
                        intermediate=intermediate_id,
                    )
                )
            else:
                assert branch.headwater is not None
                branch.headwater.to = node.id
                branch.headwater.point = node.point
                inflows.append(branch.headwater.id)
        junctions.append(
            Junction(
                id=node.id,
                kind=node.kind,
                point=node.point,
                place=node.place,
                inflows=tuple(inflows),
            )
        )
    return sorted(reaches, key=lambda r: int(r.id[1:])), junctions


def _unit_elements(
    catchment: _Catchment, elements: list[_Element]
) -> tuple[np.ndarray, tuple[SplitUnit, ...]]:
    """Give every unit its element, and list the units split by a ``P`` (D5, D6).

    One pass from the closing section up: a unit takes the element of the first
    element outlet on its segment from its head, else the element its unit below
    receives at its head; the closing section's unit without one lies outside (0).
    """
    at_points: dict[int, list[tuple[Place, int]]] = defaultdict(list)
    at_outlets: dict[int, int] = {}
    for item in elements:
        if isinstance(item.outlet, Place):
            at_points[item.outlet.unit].append((item.outlet, item.number))
        else:
            assert item.outlet.unit not in at_outlets, "two elements on one outlet"
            at_outlets[item.outlet.unit] = item.number

    at_head: dict[int, int] = {}
    for unit in catchment.units.tolist():
        below = catchment.below[unit]
        if unit in at_points:
            at_head[unit] = max(at_points[unit], key=lambda p: p[0].flow_dist_m)[1]
        elif unit in at_outlets:
            at_head[unit] = at_outlets[unit]
        else:
            at_head[unit] = at_head[below] if below >= 0 else 0

    splits = []
    split_units = set()
    for unit, places in at_points.items():
        if all(place.at_outlet for place, _ in places):
            continue
        ordered = sorted(places, key=lambda p: -p[0].flow_dist_m)
        outlets: list[tuple[Place | UnitOutlet, int]] = list(ordered)
        if not any(place.at_outlet for place, _ in places):
            below = catchment.below[unit]
            rest = at_outlets.get(unit, at_head.get(below, 0) if below >= 0 else 0)
            outlets.append((UnitOutlet(unit), rest))
        splits.append(SplitUnit(unit=unit, outlets=tuple(outlets)))
        split_units.add(unit)

    unit_elements = np.array(
        [
            0 if unit in split_units else at_head[unit]
            for unit in catchment.units.tolist()
        ],
        dtype=np.int16,
    )
    return unit_elements, tuple(sorted(splits, key=lambda s: s.unit))
