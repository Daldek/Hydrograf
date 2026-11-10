"""
The tree of a network delineated at control points, built on the catchment graph.

ADR-080 and the plan ``docs/plans/2026-11-10-network-delineation.md`` (D3 to D5, D15).
The control points, the closing section A and the points of the request, each snapped
to a stream cell (``core.network_delineation``), form a tree along their flow paths:

- the parent of a point is the first control point on its flow path downstream: the
  nearest below it in its own unit, else the uppermost in the first unit below that
  holds one, A at the latest;
- the trunk of a control point is its main river: from its cell up its unit's
  segment, then up the units ``CatchmentGraph.trace_main_channel`` chooses (ADR-046);
- a point joins its parent's trunk at itself when its unit is on the trunk (a gauge on
  the main river), else at the head cell of the trunk unit its path enters, a
  confluence: its junction. Points whose paths enter the trunk through the same unit
  first meet where their paths merge, a confluence that is a junction too (B1);
- the nodes of a trunk are the junctions and the point it carries; its edges run
  between consecutive nodes and from the lowest node to the control point, and a
  point off the trunk adds the edge from it to its junction, along its branch. Every
  edge is a reach with its intermediate catchment (przyrzecze); the trunk above its
  uppermost node, when that node is a junction, is a headwater subcatchment (ending at
  the control point when no node lies on its trunk); a point with no point above it is
  a subcatchment, a tributary when it lies off its parent's trunk, the headwater when
  on it;
- a point off its parent's trunk at most MOUTH_TOLERANCE_M above its junction along
  the flow moves to the outlet cell of the last unit above the junction on its
  branch (D3): its subcatchment, or its junction, enters the junction directly.

The elements are made of the units of the graph (``DEFAULT_THRESHOLD_M2``): every
element ends at one outlet cell, a control point's cell or the outlet cell of the unit
above a junction on its branch, and holds the cells whose first element outlet
downstream is its own (D5). A unit belongs to the element of the first element outlet
on its segment from its head, else to the element its unit below receives at its head;
a unit with a control point not at its outlet cell is split by the raster
(``core.network_delineation``, D6). Nothing here reads a raster: the cells of the
control points and of their paths come from their snapping.
"""

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from itertools import pairwise
from typing import Literal

import numpy as np

from core.catchment_graph import CatchmentGraph
from core.errors import InvalidRequestError

# A point off its parent's trunk at most this far above its junction along the flow
# is taken at the mouth of its tributary (D3) [m]
MOUTH_TOLERANCE_M = 50.0
# The id of the outlet of the network, into which A's junction flows
OUTLET_ID = "OUT"

type ElementKind = Literal["headwater", "tributary", "intermediate"]
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
    """

    cell: tuple[int, int]
    unit: int
    flow_dist_m: float
    at_head: bool = False
    at_outlet: bool = False


@dataclass(frozen=True)
class ControlPoint:
    """A control point snapped to a stream cell (D2).

    Attributes
    ----------
    point_id : str
        Its id in the request.
    place : Place
        Its cell.
    path : tuple[Place, ...]
        The cells below ``place`` along the flow, nearest first, at least as far as
        ``MOUTH_TOLERANCE_M`` below it (fewer where the flow ends): where the mouth
        rule (D3) may move the point.
    """

    point_id: str
    place: Place
    path: tuple[Place, ...] = ()


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
    """An element of the network: a headwater, a tributary or a przyrzecze.

    Attributes
    ----------
    id : str
        ``Z1``, ``Z2``, … in the order of D15.
    number : int
        Its value in the element raster: 1 for ``Z1``.
    kind : ElementKind
        ``headwater``, ``tributary`` or ``intermediate`` (the przyrzecze of a reach).
    to : str
        The node it flows into: a junction, or the reach below a point's subcatchment.
    point : str or None
        The id of the control point it ends at.
    reach : str or None
        The reach of a przyrzecze.
    at_mouth : bool
        It ends at a point that the mouth rule moved (D3).
    outlet : Place or UnitOutlet
        Its outlet cell.
    """

    id: str
    number: int
    kind: ElementKind
    to: str
    point: str | None
    reach: str | None
    at_mouth: bool
    outlet: Place | UnitOutlet


@dataclass(frozen=True)
class Reach:
    """An edge of the tree: a reach from its upper node down to its lower one.

    Attributes
    ----------
    id : str
        ``R1``, ``R2``, … in the order of D15.
    from_node : str
        The node it receives: the junction of its upper node, or the subcatchment of
        a point with no point above it.
    to : str
        The junction it flows into.
    upper, lower : Place or UnitHead
        The cells of its ends.
    intermediate : str or None
        Its przyrzecze; None when that has no cells (D5: an edge from a point at the
        outlet cell of the unit above its junction).
    """

    id: str
    from_node: str
    to: str
    upper: Place | UnitHead
    lower: Place | UnitHead
    intermediate: str | None


@dataclass(frozen=True)
class Junction:
    """A junction of the network.

    Attributes
    ----------
    id : str
        ``J1``, ``J2``, … in the order of D15.
    kind : JunctionKind
        ``confluence``, ``point`` (a point with points above it) or ``outlet`` (A's).
    point : str or None
        The id of its control point.
    place : Place or UnitHead
        Its cell.
    inflows : tuple[str, ...]
        The nodes it receives: the trunk's first, then the branches in descending
        order of the accumulation of their last cell.
    tributaries : tuple[str, ...]
        The control points of the branches that join it from the side, not along a
        trunk, in the order of ``inflows``: on each branch the nearest point above,
        or the points that meet below it on that branch (B1).
    """

    id: str
    kind: JunctionKind
    point: str | None
    place: Place | UnitHead
    inflows: tuple[str, ...]
    tributaries: tuple[str, ...]


@dataclass(frozen=True)
class PointNode:
    """A control point in the network.

    Attributes
    ----------
    point_id : str
        Its id in the request.
    place : Place
        Its cell, after the mouth rule.
    at_mouth : bool
        The mouth rule moved it (D3).
    node : str
        Its subcatchment when no point lies above it, else its junction.
    """

    point_id: str
    place: Place
    at_mouth: bool
    node: str


@dataclass(frozen=True)
class SplitUnit:
    """A unit with a control point inside: its outlets and their elements (D6).

    Attributes
    ----------
    unit : int
        Internal graph index of the unit.
    outlets : tuple[tuple[Place or UnitOutlet, int], ...]
        In the order of the flow: each control point in it and, unless one lies at
        its outlet cell, its outlet cell, with the element number each cell above
        it (and below the outlet above) takes; 0 outside the network (the part of
        A's unit below A).
    """

    unit: int
    outlets: tuple[tuple[Place | UnitOutlet, int], ...]


@dataclass(frozen=True)
class NetworkTree:
    """The network of a closing section and its points, on the graph.

    Attributes
    ----------
    points : tuple[PointNode, ...]
        A, then the points in the order of the request.
    subcatchments : tuple[Subcatchment, ...]
        ``Z1``, ``Z2``, …
    reaches : tuple[Reach, ...]
        ``R1``, ``R2``, …
    junctions : tuple[Junction, ...]
        ``J1``, ``J2``, …
    order : tuple[str, ...]
        Every node in the order of D15, each after every node it receives,
        ``OUTLET_ID`` last.
    units : np.ndarray
        A's catchment: the internal indices of the units (``upstream_tree``).
    unit_elements : np.ndarray
        The element number of each unit of ``units``; 0 for a split unit.
    splits : tuple[SplitUnit, ...]
        The units the raster splits.
    """

    points: tuple[PointNode, ...]
    subcatchments: tuple[Subcatchment, ...]
    reaches: tuple[Reach, ...]
    junctions: tuple[Junction, ...]
    order: tuple[str, ...]
    units: np.ndarray
    unit_elements: np.ndarray
    splits: tuple[SplitUnit, ...]


@dataclass(eq=False)
class _Element:
    """An element while the tree is built."""

    kind: ElementKind
    outlet: Place | UnitOutlet
    point: str | None = None
    at_mouth: bool = False
    reach: "_Edge | None" = None
    id: str = ""
    number: int = 0
    to: str = ""


@dataclass(eq=False)
class _Node:
    """A node that can receive branches: a control point or a confluence."""

    place: Place | UnitHead
    kind: JunctionKind
    point: str | None = None
    at_mouth: bool = False
    off_trunk: bool = False
    branches: list["_Branch"] = field(default_factory=list)
    # A control point's element, the one that ends at its cell
    element: _Element | None = None
    id: str = ""

    def node_id(self) -> str:
        """Its junction when it receives branches, else its subcatchment."""
        if self.branches:
            return self.id
        assert self.element is not None
        return self.element.id


@dataclass(eq=False)
class _Edge:
    """An edge while the tree is built."""

    upper: _Node
    lower: _Node
    intermediate: _Element | None
    id: str = ""


@dataclass(eq=False)
class _Branch:
    """What a node receives from one side: an edge, a headwater or a point at a mouth.

    ``unit`` is the last unit of the branch above the node, whose accumulation
    orders the branches after the trunk's.
    """

    trunk: bool
    unit: int
    accumulation_km2: float
    edge: _Edge | None = None
    headwater: _Element | None = None
    mouth: _Node | None = None


@dataclass(frozen=True)
class _Link:
    """How a point joins its parent's trunk.

    ``entry`` is None on the trunk, else the trunk unit its path enters and the unit
    of the path above it.
    """

    parent: str
    entry: tuple[int, int] | None


class _Catchment:
    """A's catchment on the graph: the unit below each unit and the trunks."""

    def __init__(self, cg: CatchmentGraph, units: np.ndarray, below: np.ndarray):
        self.cg = cg
        self.units = units
        self.below: dict[int, int] = dict(
            zip(units.tolist(), below.tolist(), strict=True)
        )
        self._trunks: dict[int, tuple[list[int], dict[int, int]]] = {}

    def trunk(self, unit: int) -> tuple[list[int], dict[int, int]]:
        """Units of the main river from ``unit`` up, and the position of each."""
        if unit not in self._trunks:
            nodes = self.cg.trace_main_channel(unit, self.units)["main_channel_nodes"]
            trunk = [int(n) for n in nodes]
            self._trunks[unit] = trunk, {u: i for i, u in enumerate(trunk)}
        return self._trunks[unit]

    def path_down(self, unit: int, last: int) -> list[int]:
        """Units from ``unit`` down to ``last``, both included."""
        path = [unit]
        while path[-1] != last:
            path.append(self.below[path[-1]])
        return path

    def accumulation_km2(self, unit: int) -> float:
        """Upstream area at the end of a unit's segment [km²]; 0 when not loaded."""
        area = self.cg.get_upstream_area_km2(unit)
        return 0.0 if math.isnan(area) else area


def build_network_tree(
    cg: CatchmentGraph, outlet: ControlPoint, points: Sequence[ControlPoint]
) -> NetworkTree:
    """Build the network of a closing section and its points (D3 to D5, D15).

    Parameters
    ----------
    cg : CatchmentGraph
        The loaded graph of the units (``DEFAULT_THRESHOLD_M2``).
    outlet : ControlPoint
        The closing section A.
    points : Sequence[ControlPoint]
        The points of the request, ids unique without regard to case.

    Returns
    -------
    NetworkTree
        The nodes, the elements of the units and the units to split.

    Raises
    ------
    InvalidRequestError
        ``validation_error``: ``network_point_outside`` for a point that does not
        drain to A; ``network_points_coincide`` for points, or a point and A, on one
        cell after the snapping or after the mouth rule.
    """
    units, below = cg.upstream_tree(outlet.place.unit)
    catchment = _Catchment(cg, units, below)
    _require_inside(catchment, outlet, points)
    controls = {c.point_id: c for c in (outlet, *points)}
    _require_apart(controls.values())

    # The mouth rule on the links of the snapped points, then the links again
    links = _links(catchment, controls, outlet.point_id)
    moved: dict[str, Place] = {}
    for point_id, link in links.items():
        mouth = _mouth(controls[point_id], link)
        if mouth is not None:
            moved[point_id] = mouth
    if moved:
        for point_id, place in moved.items():
            controls[point_id] = replace(controls[point_id], place=place, path=())
        _require_apart(controls.values())
        links = _links(catchment, controls, outlet.point_id)

    nodes = {
        point_id: _Node(
            place=control.place,
            kind="outlet" if point_id == outlet.point_id else "point",
            point=point_id,
            at_mouth=point_id in moved,
            off_trunk=point_id in links and links[point_id].entry is not None,
        )
        for point_id, control in controls.items()
    }
    children: dict[str, list[str]] = defaultdict(list)
    for point_id, link in links.items():
        children[link.parent].append(point_id)
    for parent_id, kids in children.items():
        _wire_trunk(catchment, nodes, links, nodes[parent_id], kids)
    for node in nodes.values():
        if node.element is None:
            assert isinstance(node.place, Place)
            node.element = _Element(
                kind="tributary" if node.off_trunk else "headwater",
                outlet=node.place,
                point=node.point,
                at_mouth=node.at_mouth,
            )

    elements, order = _number(nodes[outlet.point_id])
    junction_nodes = [n for n in _walk_nodes(nodes[outlet.point_id]) if n.branches]
    reaches, junctions = _connect(junction_nodes)
    unit_elements, splits = _unit_elements(catchment, elements)
    return NetworkTree(
        points=tuple(
            PointNode(
                point_id=point_id,
                place=controls[point_id].place,
                at_mouth=node.at_mouth,
                node=node.node_id(),
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
                at_mouth=el.at_mouth,
                outlet=el.outlet,
            )
            for el in elements
        ),
        reaches=tuple(sorted(reaches, key=lambda r: int(r.id[1:]))),
        junctions=tuple(sorted(junctions, key=lambda j: int(j.id[1:]))),
        order=tuple(order),
        units=units,
        unit_elements=unit_elements,
        splits=splits,
    )


def _require_inside(
    catchment: _Catchment, outlet: ControlPoint, points: Sequence[ControlPoint]
) -> None:
    """Refuse a point whose unit is not in A's catchment or that lies below A."""
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
    """Refuse control points on one cell, naming the first group of them."""
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
        unit = control.place.unit
        entry = None
        if unit not in position:
            above, unit = unit, catchment.below[unit]
            while unit not in position:
                above, unit = unit, catchment.below[unit]
            entry = (unit, above)
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


def _mouth(control: ControlPoint, link: _Link) -> Place | None:
    """Where the mouth rule moves a point off its parent's trunk, if it does (D3).

    The junction is the first cell of the path in the trunk unit it enters; the
    point moves to the cell above it, the outlet cell of the last unit above the
    junction on its branch, when the junction lies at most MOUTH_TOLERANCE_M below.
    """
    if link.entry is None:
        return None
    trunk_unit, _ = link.entry
    cells = (control.place, *control.path)
    for i in range(1, len(cells)):
        if control.place.flow_dist_m - cells[i].flow_dist_m > MOUTH_TOLERANCE_M:
            return None
        if cells[i].unit == trunk_unit:
            return cells[i - 1]
    return None


def _wire_trunk(
    catchment: _Catchment,
    nodes: dict[str, _Node],
    links: dict[str, _Link],
    parent: _Node,
    kids: list[str],
) -> None:
    """Give a control point with points above it its trunk, junctions and branches."""
    assert isinstance(parent.place, Place)
    trunk, position = catchment.trunk(parent.place.unit)
    gauges = [kid for kid in kids if links[kid].entry is None]
    assert len(gauges) <= 1, "two gauges cannot share a parent"
    # The children off the trunk by the junction they enter (None: the parent's own
    # cell, at the head of its unit) and the last unit of their path above it
    groups: dict[tuple[int | None, int], list[str]] = defaultdict(list)
    for kid in kids:
        entry = links[kid].entry
        if entry is None:
            continue
        trunk_unit, above = entry
        at_parent = trunk_unit == parent.place.unit and parent.place.at_head
        groups[(None if at_parent else trunk_unit, above)].append(kid)

    confluences = {
        unit: _Node(
            place=UnitHead(unit=unit, above=trunk[position[unit] + 1]),
            kind="confluence",
        )
        for unit in sorted(
            {unit for unit, _ in groups if unit is not None}, key=position.__getitem__
        )
    }
    trunk_nodes = list(confluences.values()) + [nodes[kid] for kid in gauges]
    if trunk_nodes:
        edge = _edge(trunk_nodes[0], parent, parent.place)
        parent.element = edge.intermediate
        parent.branches.append(
            _Branch(trunk=True, unit=parent.place.unit, accumulation_km2=0.0, edge=edge)
        )
        for lower, upper in pairwise(trunk_nodes):
            above = trunk[position[lower.place.unit] + 1]
            lower.branches.append(
                _Branch(
                    trunk=True,
                    unit=above,
                    accumulation_km2=catchment.accumulation_km2(above),
                    edge=_edge(upper, lower, UnitOutlet(above)),
                )
            )
        top = trunk_nodes[-1]
        if top.point is None:
            above = trunk[position[top.place.unit] + 1]
            top.branches.append(
                _Branch(
                    trunk=True,
                    unit=above,
                    accumulation_km2=catchment.accumulation_km2(above),
                    headwater=_Element(kind="headwater", outlet=UnitOutlet(above)),
                )
            )
    else:
        assert isinstance(parent.place, Place)
        parent.element = _Element(
            kind="headwater",
            outlet=parent.place,
            point=parent.point,
            at_mouth=parent.at_mouth,
        )
        parent.branches.append(
            _Branch(
                trunk=True,
                unit=parent.place.unit,
                accumulation_km2=0.0,
                headwater=parent.element,
            )
        )

    for (junction_unit, above), members in groups.items():
        target = parent if junction_unit is None else confluences[junction_unit]
        target.branches.append(
            _group_branch(catchment, [nodes[m] for m in members], above, target)
        )


def _edge(upper: _Node, lower: _Node, end: Place | UnitOutlet) -> _Edge:
    """Make an edge and its przyrzecze, which ends at ``end``.

    The przyrzecze has no cells when the upper node is a control point at the
    outlet cell it would end at (D5: an edge between two neighbouring cells).
    """
    empty = (
        isinstance(end, UnitOutlet)
        and isinstance(upper.place, Place)
        and upper.point is not None
        and upper.place.unit == end.unit
        and upper.place.at_outlet
    )
    point = lower.point if isinstance(end, Place) else None
    intermediate = (
        None
        if empty
        else _Element(
            kind="intermediate",
            outlet=end,
            point=point,
            at_mouth=lower.at_mouth if point is not None else False,
        )
    )
    edge = _Edge(upper=upper, lower=lower, intermediate=intermediate)
    if intermediate is not None:
        intermediate.reach = edge
    return edge


def _group_branch(
    catchment: _Catchment, members: list[_Node], above: int, target: _Node
) -> _Branch:
    """Make the branch of the points whose paths enter a junction through one unit.

    One point brings its edge, or itself at the mouth. Several points meet where
    their paths merge, at the head cells of the units their paths enter from two or
    more units: confluences joined by edges, the lowest one by the edge to the
    junction (B1).
    """
    accumulation = catchment.accumulation_km2(above)
    if len(members) == 1:
        (member,) = members
        if member.at_mouth:
            return _Branch(
                trunk=False, unit=above, accumulation_km2=accumulation, mouth=member
            )
        return _Branch(
            trunk=False,
            unit=above,
            accumulation_km2=accumulation,
            edge=_edge(member, target, UnitOutlet(above)),
        )

    paths = []
    for member in members:
        assert isinstance(member.place, Place)
        paths.append((member, catchment.path_down(member.place.unit, above)))
    entering: dict[int, set[int]] = defaultdict(set)
    for _, path in paths:
        for upper_unit, unit in pairwise(path):
            entering[unit].add(upper_unit)
    confluences = {
        unit: _Node(place=UnitHead(unit=unit, above=min(ups)), kind="confluence")
        for unit, ups in entering.items()
        if len(ups) > 1
    }
    wired: set[tuple[int, int]] = set()
    lowest: _Node | None = None
    for member, path in paths:
        upper = member
        for upper_unit, unit in pairwise(path):
            node = confluences.get(unit)
            if node is None:
                continue
            if (id(upper), unit) not in wired:
                wired.add((id(upper), unit))
                node.branches.append(
                    _Branch(
                        trunk=False,
                        unit=upper_unit,
                        accumulation_km2=catchment.accumulation_km2(upper_unit),
                        edge=_edge(upper, node, UnitOutlet(upper_unit)),
                    )
                )
            upper = node
        lowest = upper
    assert lowest is not None and lowest.point is None
    return _Branch(
        trunk=False,
        unit=above,
        accumulation_km2=accumulation,
        edge=_edge(lowest, target, UnitOutlet(above)),
    )


def _branch_key(branch: _Branch) -> tuple[bool, float, int]:
    """Sort the trunk first, then by descending accumulation of the last cell (D15)."""
    return (not branch.trunk, -branch.accumulation_km2, branch.unit)


def _number(root: _Node) -> tuple[list[_Element], list[str]]:
    """Walk the tree from A, each node after all it receives, and number it (D15)."""
    elements: list[_Element] = []
    order: list[str] = []
    counts = {"Z": 0, "R": 0, "J": 0}

    def name(prefix: str) -> str:
        counts[prefix] += 1
        order.append(f"{prefix}{counts[prefix]}")
        return order[-1]

    def element(item: _Element) -> None:
        item.id = name("Z")
        item.number = counts["Z"]
        elements.append(item)

    def upper(node: _Node) -> None:
        if node.branches:
            walk(node)
        else:
            assert node.element is not None
            element(node.element)

    def walk(node: _Node) -> None:
        for branch in sorted(node.branches, key=_branch_key):
            if branch.edge is not None:
                upper(branch.edge.upper)
                branch.edge.id = name("R")
                if branch.edge.intermediate is not None:
                    element(branch.edge.intermediate)
            elif branch.headwater is not None:
                element(branch.headwater)
            else:
                assert branch.mouth is not None
                upper(branch.mouth)
        node.id = name("J")

    walk(root)
    order.append(OUTLET_ID)
    return elements, order


def _walk_nodes(root: _Node) -> list[_Node]:
    """Every node of the tree, from A up."""
    found = [root]
    for node in found:
        for branch in node.branches:
            if branch.edge is not None:
                found.append(branch.edge.upper)
            elif branch.mouth is not None:
                found.append(branch.mouth)
    return found


def _connect(junction_nodes: list[_Node]) -> tuple[list[Reach], list[Junction]]:
    """Make the reaches and junctions, and set the node each element flows into."""
    reaches = []
    junctions = []
    for node in junction_nodes:
        inflows: list[str] = []
        tributaries: list[str] = []
        for branch in sorted(node.branches, key=_branch_key):
            if not branch.trunk:
                tributaries.extend(_points_up(_upper_node(branch)))
            if branch.edge is not None:
                edge = branch.edge
                if not edge.upper.branches:
                    assert edge.upper.element is not None
                    edge.upper.element.to = edge.id
                inflows.append(edge.id)
                intermediate_id = None
                if edge.intermediate is not None:
                    edge.intermediate.to = node.id
                    intermediate_id = edge.intermediate.id
                    inflows.append(intermediate_id)
                reaches.append(
                    Reach(
                        id=edge.id,
                        from_node=edge.upper.node_id(),
                        to=node.id,
                        upper=edge.upper.place,
                        lower=node.place,
                        intermediate=intermediate_id,
                    )
                )
            elif branch.headwater is not None:
                branch.headwater.to = node.id
                inflows.append(branch.headwater.id)
            else:
                assert branch.mouth is not None
                if not branch.mouth.branches:
                    assert branch.mouth.element is not None
                    branch.mouth.element.to = node.id
                inflows.append(branch.mouth.node_id())
        junctions.append(
            Junction(
                id=node.id,
                kind=node.kind,
                point=node.point,
                place=node.place,
                inflows=tuple(inflows),
                tributaries=tuple(tributaries),
            )
        )
    return reaches, junctions


def _upper_node(branch: _Branch) -> _Node:
    """Return the node a branch that is not a headwater comes from."""
    upper = branch.edge.upper if branch.edge is not None else branch.mouth
    assert upper is not None
    return upper


def _points_up(node: _Node) -> list[str]:
    """List the nearest control points from a node up: itself, or its branches'."""
    if node.point is not None:
        return [node.point]
    return [
        point
        for branch in sorted(node.branches, key=_branch_key)
        if branch.headwater is None
        for point in _points_up(_upper_node(branch))
    ]


def _unit_elements(
    catchment: _Catchment, elements: list[_Element]
) -> tuple[np.ndarray, tuple[SplitUnit, ...]]:
    """Give every unit its element, and list the units with a control point (D5, D6).

    One pass from A up: a unit takes the element of the first element outlet on its
    segment from its head, else the element its unit below receives at its head.
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
        if unit in at_points:
            at_head[unit] = max(at_points[unit], key=lambda p: p[0].flow_dist_m)[1]
        elif unit in at_outlets:
            at_head[unit] = at_outlets[unit]
        else:
            at_head[unit] = at_head[catchment.below[unit]]

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
