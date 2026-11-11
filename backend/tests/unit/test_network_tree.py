"""core.network_tree builds the tree of a network on a synthetic catchment graph.

A main river of eight units (M0 at the outlet of the graph up to M7) with three
tributaries: T1 (T1a, T1b) joins it at the head of M2, T2 (T2a, T2b, T2c) at the head
of M4 and T3 (T3a) at the head of M6; T2 has a tributary of its own, S (Sa, Sb), at
the head of T2b. The main river carries the larger upstream area at every confluence,
and T2c the larger one at the head of T2b. Every unit drains at least THRESHOLD_M2, so
the four confluences are the nodes of the network (N2). Flow distances are those of
cells of 5 m along the segments; a point's paths run down and up them.
"""

import random
from itertools import pairwise

import numpy as np
import pytest
from scipy import sparse

from core.catchment_graph import CatchmentGraph
from core.errors import InvalidRequestError
from core.network_tree import (
    MOUTH_TOLERANCE_M,
    ControlPoint,
    Place,
    UnitHead,
    UnitOutlet,
    build_network_tree,
)

STEP_M = 5.0
# The network the points snapped to: its confluences are the nodes, and a river of at
# least 1 km² joining at a node without a point is a subcatchment of its own
THRESHOLD_M2 = 1_000_000
# name: (unit below, local area [km²], segment length [m])
UNITS = {
    "M0": (None, 3.0, 1000.0),
    "M1": ("M0", 3.0, 1000.0),
    "M2": ("M1", 3.0, 1000.0),
    "M3": ("M2", 3.0, 1000.0),
    "M4": ("M3", 3.0, 1000.0),
    "M5": ("M4", 3.0, 1000.0),
    "M6": ("M5", 3.0, 1000.0),
    "M7": ("M6", 3.0, 1000.0),
    "T1a": ("M2", 1.0, 600.0),
    "T1b": ("T1a", 1.0, 600.0),
    "T2a": ("M4", 1.0, 500.0),
    "T2b": ("T2a", 1.0, 500.0),
    "T2c": ("T2b", 3.0, 800.0),
    "Sa": ("T2b", 1.0, 400.0),
    "Sb": ("Sa", 1.0, 600.0),
    "T3a": ("M6", 1.0, 700.0),
}


class River:
    """The synthetic graph and the cells of its segments."""

    def __init__(self, lengths_m=None, extra_units=None):
        units = {**UNITS, **(extra_units or {})}
        lengths = {name: length for name, (_, _, length) in units.items()}
        lengths.update(lengths_m or {})
        self.names = list(units)
        self.index = {name: i for i, name in enumerate(self.names)}
        self.below = {name: below for name, (below, _, _) in units.items()}
        # Flow distance at the cell below the outlet of each unit, and at its head
        self.outlet_fd = {}
        self.head_fd = {}
        for name in self.names:  # every unit after the one below it
            below = self.below[name]
            self.outlet_fd[name] = 0.0 if below is None else self.head_fd[below]
            self.head_fd[name] = self.outlet_fd[name] + lengths[name]
        self.upstream = {
            name: [n for n in self.names if self.below[n] == name]
            for name in self.names
        }
        area = {}
        for name in reversed(self.names):  # every unit before the one below it
            area[name] = units[name][1] + sum(area[n] for n in self.upstream[name])
        self.graph = self._graph(units, area, lengths)

    def _graph(self, units, upstream_area, lengths):
        n = len(self.names)
        cg = CatchmentGraph()
        cg._n = n
        cg._loaded = True
        cg._segment_idx = np.arange(1, n + 1, dtype=np.int32)
        cg._threshold_m2 = np.full(n, 10_000, dtype=np.int32)
        cg._area_km2 = np.array([units[m][1] for m in self.names], dtype=np.float32)
        cg._upstream_area_km2 = np.array([upstream_area[m] for m in self.names])
        cg._outlet_flow_dist_m = np.array([self.outlet_fd[m] for m in self.names])
        cg._stream_length_km = np.array(
            [lengths[m] / 1000 for m in self.names], dtype=np.float32
        )
        cg._strahler = np.ones(n, dtype=np.int8)
        cg._lookup = {(10_000, i + 1): i for i in range(n)}
        links = [
            (self.index[self.below[m]], self.index[m])
            for m in self.names
            if self.below[m] is not None
        ]
        rows, cols = zip(*links, strict=True)
        cg._upstream_adj = sparse.csr_matrix(
            (np.ones(len(links), dtype=np.int8), (rows, cols)), shape=(n, n)
        )
        return cg

    def place(self, name, fd):
        """The cell of unit ``name`` at flow distance ``fd``."""
        assert self.outlet_fd[name] < fd <= self.head_fd[name], (name, fd)
        return Place(
            cell=(self.index[name], int(round(fd))),
            unit=self.index[name],
            flow_dist_m=float(fd),
            at_head=fd == self.head_fd[name] and bool(self.upstream[name]),
            at_outlet=fd == self.outlet_fd[name] + STEP_M,
        )

    def point(self, point_id, name, fd):
        """A control point at a cell, with its paths as snapping records them.

        Down the flow as far as MOUTH_TOLERANCE_M, up its unit's segment as far as
        its head cell within MOUTH_TOLERANCE_M.
        """
        path = []
        unit, cell_fd = name, fd
        while True:
            cell_fd -= STEP_M
            if cell_fd <= self.outlet_fd[unit]:
                unit = self.below[unit]
                if unit is None:
                    break
            if fd - cell_fd > MOUTH_TOLERANCE_M:
                break
            path.append(self.place(unit, cell_fd))
        upstream = []
        cell_fd = fd + STEP_M
        while cell_fd <= min(self.head_fd[name], fd + MOUTH_TOLERANCE_M):
            upstream.append(self.place(name, cell_fd))
            cell_fd += STEP_M
        place = self.place(name, fd)
        return ControlPoint(point_id, place, tuple(path), tuple(upstream))

    def name(self, unit):
        return self.names[unit]


@pytest.fixture
def river():
    return River()


def build(river, outlet, *points):
    """Build the tree of the points and check the invariants of every network."""
    tree = build_network_tree(river.graph, outlet, list(points), THRESHOLD_M2)
    assert_no_przyrzecze_holds_a_larger_river(river, tree)
    assert_each_river_at_a_node_enters_it_alone(river, tree)
    assert_no_element_ends_at_a_point_at_a_node(tree)
    assert_the_ids_follow_the_network(tree)
    return tree


def assert_no_przyrzecze_holds_a_larger_river(river, tree):
    """No przyrzecze holds a river larger than the one its reach brings (D4).

    A unit that joins a reach from the side at a confluence inside it, below its
    upper end and above its lower end, lies in the reach's przyrzecze with all above
    it (it carries no point, else its point would have a node there): it drains no
    more than the unit the reach comes down to that confluence.
    """
    area = river.graph.get_upstream_area_km2
    for reach in tree.reaches:
        path = [river.name(reach.upper.unit)]
        while path[-1] != river.name(reach.lower.unit):
            path.append(river.below[path[-1]])
        if isinstance(reach.lower, UnitHead) or reach.lower.at_head:
            path.pop()  # its lower end is that unit's head cell
        for above, unit in pairwise(path):
            for side in river.upstream[unit]:
                assert side == above or area(river.index[side]) <= area(
                    river.index[above]
                ), f"{reach.id} holds {side}, larger than {above} at the head of {unit}"


def assert_each_river_at_a_node_enters_it_alone(river, tree):
    """A river without a point that joins at a node's cell is a dopływ of its own (N4).

    Every unit of at least THRESHOLD_M2 that drains into the cell of a node at a
    confluence beside the trunk, with no control point in it or above it, ends in a
    headwater that enters the node and holds no other unit of THRESHOLD_M2 joining
    there: no przyrzecze holds it.
    """
    area = river.graph.get_upstream_area_km2
    elements = unit_elements(river, tree)
    z = by_id(tree.subcatchments)
    pointed = {river.name(p.place.unit) for p in tree.points}

    def at_outlet(name):
        element = elements[name]
        return element[-1][1] if isinstance(element, list) else element

    def carries_a_point(name):
        return name in pointed or any(map(carries_a_point, river.upstream[name]))

    for junction in tree.junctions:
        place = junction.place
        if isinstance(place, Place) and not place.at_head:
            continue
        joining = river.upstream[river.name(place.unit)]
        trunk = (
            river.name(place.above)
            if isinstance(place, UnitHead)
            else max(joining, key=lambda name: area(river.index[name]))
        )
        rivers = [n for n in joining if area(river.index[n]) * 1e6 >= THRESHOLD_M2]
        for name in rivers:
            if name == trunk or carries_a_point(name):
                continue
            element = z[at_outlet(name)]
            assert (element.kind, element.point, element.to) == (
                "headwater",
                junction.point,
                junction.id,
            ), f"{name}, joining at {junction.id}, is in {element.id}"
            assert element.id not in {at_outlet(n) for n in rivers if n != name}, (
                f"{element.id} holds {name} and another river at {junction.id}"
            )


def assert_no_element_ends_at_a_point_at_a_node(tree):
    """A point at a node splits no unit: its branches end above it (N5)."""
    at_nodes = {p.place for p in tree.points if p.at_node}
    assert not {s.outlet for s in tree.subcatchments} & at_nodes
    assert not {where for s in tree.splits for where, _ in s.outlets} & at_nodes


def assert_the_ids_follow_the_network(tree):
    """J at a confluence, P elsewhere, each kind numbered from the closing section up.

    N1 and N8: the closing section's node is J1 or P1 and comes first; every node
    comes after the node it flows into, each kind numbered without gaps; the order of
    D15 lists every node after every node it receives, the outlet O last.
    """
    points = {p.point_id: p for p in tree.points}
    for junction in tree.junctions:
        at_confluence = isinstance(junction.place, UnitHead) or (
            points[junction.point].at_node
        )
        assert junction.id[0] == ("J" if at_confluence else "P"), junction
    for prefix in "JP":
        numbers = [int(j.id[1:]) for j in tree.junctions if j.id[0] == prefix]
        assert numbers == list(range(1, len(numbers) + 1))
    (closing,) = [j for j in tree.junctions if j.kind == "outlet"]
    assert tree.junctions[0] == closing and closing.id in ("J1", "P1")
    assert {p.point_id: p.node for p in tree.points}[closing.point] == closing.id
    position = {j.id: i for i, j in enumerate(tree.junctions)}
    for reach in tree.reaches:
        assert position[reach.from_node] > position[reach.to], reach
    assert [s.id for s in tree.subcatchments] == [
        f"Z{i}" for i in range(1, len(tree.subcatchments) + 1)
    ]
    assert [r.id for r in tree.reaches] == [
        f"R{i}" for i in range(1, len(tree.reaches) + 1)
    ]
    receives = {j.id: set(j.inflows) for j in tree.junctions}
    receives |= {r.id: {r.from_node} for r in tree.reaches}
    seen: set[str] = set()
    for node in tree.order[:-1]:
        assert receives.get(node, set()) <= seen, node
        seen.add(node)
    assert tree.order[-1] == "O"
    assert seen == set(receives) | {s.id for s in tree.subcatchments}


def unit_elements(river, tree):
    """Element id of each whole unit by name; a split unit maps to its outlets."""
    ids = {s.number: s.id for s in tree.subcatchments}
    result = {}
    for unit, number in zip(tree.units.tolist(), tree.unit_elements, strict=True):
        if number:
            result[river.name(unit)] = ids[int(number)]
    for split in tree.splits:
        result[river.name(split.unit)] = [
            (
                "outlet" if isinstance(where, UnitOutlet) else where.flow_dist_m,
                ids.get(number),
            )
            for where, number in split.outlets
        ]
    return result


def by_id(items):
    return {item.id: item for item in items}


def node_of(tree, point_id):
    return next(p.node for p in tree.points if p.point_id == point_id)


def test_a_point_at_a_tributary_mouth_is_the_confluence(river):
    # P1 lies 20 m above the confluence of T1 and the main river: it moves to the
    # node and receives both rivers, with no reach; its reach runs down to A
    tree = build(river, river.point("A", "M0", 500), river.point("P1", "T1a", 3020))

    assert tree.order == ("Z2", "Z3", "J1", "R1", "Z1", "P1", "O")
    points = {p.point_id: p for p in tree.points}
    assert (points["A"].node, points["A"].at_node) == ("P1", False)
    assert (points["P1"].node, points["P1"].at_node) == ("J1", True)
    assert points["P1"].place == river.place("M2", 3000)
    j = by_id(tree.junctions)
    assert (j["P1"].kind, j["P1"].point, j["P1"].inflows) == (
        "outlet",
        "A",
        ("R1", "Z1"),
    )
    assert (j["J1"].kind, j["J1"].point, j["J1"].inflows) == (
        "point",
        "P1",
        ("Z2", "Z3"),
    )
    z = by_id(tree.subcatchments)
    assert [(s.kind, s.to, s.point, s.reach) for s in tree.subcatchments] == [
        ("intermediate", "P1", "A", "R1"),
        ("headwater", "J1", "P1", None),
        ("headwater", "J1", "P1", None),
    ]
    # Each branch ends at the outlet cell of its unit above the node (N5)
    assert (z["Z2"].outlet, z["Z3"].outlet) == (
        UnitOutlet(river.index["M3"]),
        UnitOutlet(river.index["T1a"]),
    )
    (reach,) = tree.reaches
    assert (reach.from_node, reach.to, reach.intermediate) == ("J1", "P1", "Z1")
    assert (reach.upper, reach.lower) == (
        river.place("M2", 3000),
        river.place("M0", 500),
    )

    elements = unit_elements(river, tree)
    assert elements.pop("M0") == [(500.0, "Z1"), ("outlet", None)]
    assert elements == {
        # The node's own unit below it is in the przyrzecze of its reach down
        "M1": "Z1",
        "M2": "Z1",
        "T1a": "Z3",
        "T1b": "Z3",
        **dict.fromkeys(("M3", "M4", "M5", "M6", "M7", "T2a", "T2b", "T2c"), "Z2"),
        **dict.fromkeys(("Sa", "Sb", "T3a"), "Z2"),
    }


def test_points_at_three_mouths_are_the_three_confluences(river):
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P1", "T1a", 3020),
        river.point("P2", "T2a", 5030),
        river.point("P3", "T3a", 7010),
    )

    assert tree.order == (
        *("Z4", "Z5", "J3", "R3", "Z3", "Z6", "J2", "R2", "Z2", "Z7", "J1", "R1"),
        *("Z1", "P1", "O"),
    )
    assert {p.point_id: p.node for p in tree.points} == {
        "A": "P1",
        "P1": "J1",
        "P2": "J2",
        "P3": "J3",
    }
    j = by_id(tree.junctions)
    assert [river.name(j[i].place.unit) for i in ("J1", "J2", "J3")] == [
        "M2",
        "M4",
        "M6",
    ]
    assert [j[i].inflows for i in ("P1", "J1", "J2", "J3")] == [
        ("R1", "Z1"),
        ("R2", "Z2", "Z7"),
        ("R3", "Z3", "Z6"),
        ("Z4", "Z5"),
    ]
    assert [(r.from_node, r.to) for r in tree.reaches] == [
        ("J1", "P1"),
        ("J2", "J1"),
        ("J3", "J2"),
    ]
    assert [(s.kind, s.point) for s in tree.subcatchments] == [
        ("intermediate", "A"),
        ("intermediate", "P1"),
        ("intermediate", "P2"),
        ("headwater", "P3"),
        ("headwater", "P3"),
        ("headwater", "P2"),
        ("headwater", "P1"),
    ]

    elements = unit_elements(river, tree)
    assert elements.pop("M0") == [(500.0, "Z1"), ("outlet", None)]
    assert elements == {
        "M1": "Z1",
        "M2": "Z1",
        "M3": "Z2",
        "M4": "Z2",
        "M5": "Z3",
        "M6": "Z3",
        "M7": "Z4",
        "T3a": "Z5",
        **dict.fromkeys(("T2a", "T2b", "T2c", "Sa", "Sb"), "Z6"),
        "T1a": "Z7",
        "T1b": "Z7",
    }


def test_every_unit_of_the_catchment_is_in_exactly_one_element(river):
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P1", "T1a", 3300),
        river.point("P2", "Sb", 6700),
        river.point("P3", "M5", 5500),
    )

    assert sorted(river.name(u) for u in tree.units.tolist()) == sorted(UNITS)
    split = {s.unit for s in tree.splits}
    numbers = {s.number for s in tree.subcatchments}
    for unit, number in zip(tree.units.tolist(), tree.unit_elements, strict=True):
        assert (unit in split) == (number == 0), river.name(unit)
        assert number == 0 or number in numbers
    used = set(tree.unit_elements.tolist()) | {
        number for s in tree.splits for _, number in s.outlets
    }
    assert numbers <= used


def test_a_point_200_m_up_a_tributary_has_a_reach_to_a_node_at_its_mouth(river):
    # The plan's case 4: the network makes a J where the point's path enters the main
    # river, whose part above it is a headwater
    tree = build(river, river.point("A", "M0", 500), river.point("P1", "T1a", 3200))

    assert tree.order == ("Z2", "Z4", "P2", "R2", "Z3", "J1", "R1", "Z1", "P1", "O")
    j = by_id(tree.junctions)
    assert (j["J1"].kind, j["J1"].point, j["J1"].inflows) == (
        "confluence",
        None,
        ("Z2", "R2", "Z3"),
    )
    assert j["J1"].place == UnitHead(river.index["M2"], river.index["M3"])
    assert (j["P2"].kind, j["P2"].point, j["P2"].inflows) == ("point", "P1", ("Z4",))
    z = by_id(tree.subcatchments)
    assert (z["Z2"].kind, z["Z2"].point, z["Z2"].outlet) == (
        "headwater",
        None,
        UnitOutlet(river.index["M3"]),
    )
    assert (z["Z3"].kind, z["Z3"].reach, z["Z3"].outlet) == (
        "intermediate",
        "R2",
        UnitOutlet(river.index["T1a"]),
    )
    assert (z["Z4"].kind, z["Z4"].point, z["Z4"].outlet) == (
        "headwater",
        "P1",
        river.place("T1a", 3200),
    )
    reaches = by_id(tree.reaches)
    assert (reaches["R2"].from_node, reaches["R2"].to) == ("P2", "J1")
    assert reaches["R2"].upper == river.place("T1a", 3200)
    elements = unit_elements(river, tree)
    assert elements["T1a"] == [(3200.0, "Z4"), ("outlet", "Z3")]
    assert elements["T1b"] == "Z4"


@pytest.mark.parametrize(
    ("lengths", "extra_units", "where", "drawn"),
    [
        ({}, {}, ("T1a", 3040), ("M2", 3000)),
        ({}, {}, ("M2", 2970), ("M2", 3000)),
        ({}, {}, ("T1a", 3060), None),
        ({}, {}, ("M2", 2940), None),
        # M3 is 40 m long and X joins it at its head: a node 20 m below and 20 m
        # above the point, the lower one taken; 15 m above and 25 m below, the upper
        ({"M3": 40.0}, {"X": ("M3", 1.0, 300.0)}, ("M3", 3020), ("M2", 3000)),
        ({"M3": 40.0}, {"X": ("M3", 1.0, 300.0)}, ("M3", 3025), ("M3", 3040)),
        # W, below the threshold, joins M3 at its head: no node there (N2)
        ({}, {"W": ("M3", 0.5, 300.0)}, ("M3", 3980), None),
        ({}, {"W": ("M3", 0.5, 300.0)}, ("M4", 4020), None),
    ],
    ids=[
        "40 m above a node",
        "30 m below a node",
        "60 m above a node",
        "60 m below a node",
        "between two nodes, on a tie",
        "nearer the node above",
        "below a stream under the threshold",
        "above a stream under the threshold",
    ],
)
def test_a_point_moves_to_the_nearest_node_within_50_m(
    lengths, extra_units, where, drawn
):
    river = River(lengths, extra_units)
    tree = build(river, river.point("A", "M0", 500), river.point("P", *where))

    (point,) = [p for p in tree.points if p.point_id == "P"]
    if drawn is None:
        assert (point.place, point.at_node, point.node[0]) == (
            river.place(*where),
            False,
            "P",
        )
    else:
        assert (point.place, point.at_node, point.node[0]) == (
            river.place(*drawn),
            True,
            "J",
        )


@pytest.mark.parametrize(
    ("where", "order", "branches"),
    [
        (("M2", 3000), ("Z1", "Z2", "J1", "O"), ("M3", "T1a")),
        (("M3", 3030), ("Z1", "Z2", "J1", "O"), ("M3", "T1a")),
        (("M2", 2970), ("Z1", "Z2", "J1", "O"), ("M3", "T1a")),
        (("M0", 500), ("Z1", "P1", "O"), ()),
    ],
    ids=["at a node", "30 m above a node", "30 m below a node", "away from nodes"],
)
def test_the_closing_section_alone_is_a_network(river, where, order, branches):
    # The plan's cases 1, 2 and 7: at a node (or moved to one) each branch is a
    # headwater into its J, elsewhere one headwater enters its P
    tree = build(river, river.point("A", *where))

    assert tree.order == order
    assert tree.reaches == ()
    (closing,) = tree.junctions
    (point,) = tree.points
    assert (closing.kind, closing.point, point.node) == ("outlet", "A", closing.id)
    assert all(s.kind == "headwater" and s.to == closing.id for s in tree.subcatchments)
    if branches:
        assert point.at_node and point.place == river.place("M2", 3000)
        assert [s.outlet for s in tree.subcatchments] == [
            UnitOutlet(river.index[name]) for name in branches
        ]
        # The node's own unit lies outside the network, whole (N5)
        assert river.name(int(tree.units[0])) == "M2"
        assert (tree.unit_elements[0], tree.splits) == (0, ())
    else:
        assert not point.at_node
        (headwater,) = tree.subcatchments
        assert headwater.outlet == river.place(*where)
        assert unit_elements(river, tree)["M0"] == [(500.0, "Z1"), ("outlet", None)]


def test_a_small_stream_at_the_node_of_the_closing_section_lies_outside():
    # W (0.5 km²) joins M3 and T1 at the head of M2, below the threshold: no branch
    # of A's node, it drains into A's own cell and lies outside with A's unit (N5)
    river = River(extra_units={"W": ("M2", 0.5, 300.0)})
    tree = build(river, river.point("A", "M2", 3000))

    elements = dict(
        zip(map(river.name, tree.units.tolist()), tree.unit_elements, strict=True)
    )
    assert (elements["M2"], elements["W"], tree.splits) == (0, 0, ())
    assert [s.outlet for s in tree.subcatchments] == [
        UnitOutlet(river.index["M3"]),
        UnitOutlet(river.index["T1a"]),
    ]


def test_a_gauge_between_two_nodes_splits_the_reach(river):
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P1", "T1a", 3020),
        river.point("P2", "T2a", 5020),
        river.point("G", "M3", 3500),
    )

    gauge = by_id(tree.junctions)[node_of(tree, "G")]
    assert (gauge.id, gauge.kind, gauge.point) == ("P2", "point", "G")
    reaches = by_id(tree.reaches)
    # J(P1) <- G <- J(P2): the gauge's node lies between the two confluences
    (into_gauge,) = [r for r in tree.reaches if r.to == gauge.id]
    (out_of_gauge,) = [r for r in tree.reaches if r.from_node == gauge.id]
    assert into_gauge.from_node == node_of(tree, "P2")
    assert out_of_gauge.to == node_of(tree, "P1")
    assert river.name(into_gauge.upper.unit) == "M4"
    assert river.name(reaches[out_of_gauge.id].lower.unit) == "M2"
    assert gauge.inflows == (into_gauge.id, into_gauge.intermediate)
    elements = unit_elements(river, tree)
    assert elements["M3"] == [
        (3500.0, into_gauge.intermediate),
        ("outlet", out_of_gauge.intermediate),
    ]


def test_a_gauge_above_every_node_has_a_headwater_of_its_own(river):
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P1", "T1a", 3020),
        river.point("P2", "T2a", 5020),
        river.point("P3", "T3a", 7020),
        river.point("G", "M7", 7600),
    )

    gauge = by_id(tree.junctions)[node_of(tree, "G")]
    (headwater_id,) = gauge.inflows
    headwater = by_id(tree.subcatchments)[headwater_id]
    assert (headwater.kind, headwater.point, headwater.outlet) == (
        "headwater",
        "G",
        river.place("M7", 7600),
    )
    (into_top,) = [r for r in tree.reaches if r.from_node == gauge.id]
    assert into_top.to == node_of(tree, "P3")
    assert river.name(into_top.lower.unit) == "M6"
    assert unit_elements(river, tree)["M7"] == [
        (7600.0, headwater.id),
        ("outlet", into_top.intermediate),
    ]


def test_points_on_a_tributary_and_its_tributary_make_its_own_trunk(river):
    # The plan's case 8 by cascade: P2 at the mouth of T2 is a node; Q on S joins the
    # main river of T2 at the fork, a node the network makes, above which T2c is a
    # headwater
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P2", "T2a", 5020),
        river.point("Q", "Sb", 6700),
    )

    j = by_id(tree.junctions)
    p2 = j[node_of(tree, "P2")]
    assert (p2.id, p2.kind) == ("J1", "point")
    assert p2.place == river.place("M4", 5000)
    z = by_id(tree.subcatchments)
    reaches = by_id(tree.reaches)
    # The main river above P2 first, then T2 by the reach from its fork
    trunk, into_p2, przyrzecze = p2.inflows
    assert (z[trunk].kind, z[trunk].outlet) == (
        "headwater",
        UnitOutlet(river.index["M5"]),
    )
    fork = j[reaches[into_p2].from_node]
    assert (fork.id, fork.kind) == ("J2", "confluence")
    assert fork.place == UnitHead(river.index["T2b"], river.index["T2c"])
    headwater, from_q, _ = fork.inflows
    assert (z[headwater].kind, z[headwater].point, z[headwater].outlet) == (
        "headwater",
        None,
        UnitOutlet(river.index["T2c"]),
    )
    assert reaches[from_q].from_node == node_of(tree, "Q") == "P2"
    elements = unit_elements(river, tree)
    assert elements["T2c"] == headwater
    assert elements["Sa"] == reaches[from_q].intermediate
    assert elements["T2a"] == elements["T2b"] == przyrzecze
    assert elements["Sb"] == [(6700.0, "Z6"), ("outlet", reaches[from_q].intermediate)]


@pytest.mark.parametrize(
    ("unit", "kind"), [("T2c", "point"), ("Sa", "confluence")], ids=["T2c", "S"]
)
def test_the_trunk_takes_the_branch_of_the_larger_upstream_area(river, unit, kind):
    # On T2c, the main river of T2, Q's reach runs to P2's node; on S, to the fork
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P2", "T2a", 5020),
        river.point("Q", unit, 6300),
    )

    j = by_id(tree.junctions)
    (reach,) = [r for r in tree.reaches if r.from_node == node_of(tree, "Q")]
    assert j[reach.to].kind == kind


def test_two_points_in_one_unit_and_a_point_in_the_unit_of_a_split_them(river):
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("G1", "M5", 5700),
        river.point("G2", "M5", 5300),
        river.point("P", "M0", 800),
    )

    numbers = {s.point: s.number for s in tree.subcatchments}
    by_unit = {river.name(s.unit): s for s in tree.splits}
    assert set(by_unit) == {"M5", "M0"}
    m5 = by_unit["M5"].outlets
    assert [(where.flow_dist_m, number) for where, number in m5[:2]] == [
        (5700.0, numbers["G1"]),
        (5300.0, numbers["G2"]),
    ]
    assert m5[2] == (UnitOutlet(river.index["M5"]), numbers["P"])
    m0 = by_unit["M0"].outlets
    assert [(where.flow_dist_m, number) for where, number in m0[:2]] == [
        (800.0, numbers["P"]),
        (500.0, numbers["A"]),
    ]
    assert m0[2] == (UnitOutlet(river.index["M0"]), 0)


@pytest.mark.parametrize(
    ("outlet", "point"),
    [(("M3", 3500), ("T1a", 3300)), (("M0", 500), ("M0", 300))],
    ids=["another branch", "below A in its unit"],
)
def test_a_point_that_does_not_drain_to_a_is_refused(river, outlet, point):
    with pytest.raises(InvalidRequestError) as raised:
        build(river, river.point("A", *outlet), river.point("P1", *point))

    assert raised.value.message_id == "network_point_outside"
    assert raised.value.details["point_id"] == "P1"


def test_points_on_one_cell_are_refused(river):
    with pytest.raises(InvalidRequestError) as raised:
        build(
            river,
            river.point("A", "M0", 500),
            river.point("P1", "M3", 3500),
            river.point("P2", "M3", 3500),
        )

    assert raised.value.message_id == "network_points_coincide"
    assert raised.value.details["point_ids"] == ["P1", "P2"]


def test_two_points_moved_to_one_node_are_refused():
    # P1 on T2c and P2 on S, 15 and 20 m above the fork of T2, both move to it (N6)
    river = River({"T2a": 10.0, "T2b": 10.0})
    with pytest.raises(InvalidRequestError) as raised:
        build(
            river,
            river.point("A", "M0", 500),
            river.point("P1", "T2c", 5035),
            river.point("P2", "Sa", 5040),
        )

    assert raised.value.message_id == "network_points_coincide"
    assert raised.value.details["point_ids"] == ["P1", "P2"]


@pytest.mark.parametrize("where", [("M3", 3010), ("T1a", 3030), ("M2", 2990)])
def test_a_point_moved_to_the_node_of_the_closing_section_is_refused(river, where):
    # The plan's case 9: A at a confluence already divides its catchment
    with pytest.raises(InvalidRequestError) as raised:
        build(river, river.point("A", "M2", 3000), river.point("P1", *where))

    assert raised.value.message_id == "network_points_coincide"
    assert raised.value.details["point_ids"] == ["A", "P1"]


def test_points_on_two_branches_of_a_tributary_meet_on_its_main_river(river):
    # No point at T2's mouth: P1 lies on its main river (T2c), P2 on S, which joins
    # it at the fork
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P1", "T2c", 6500),
        river.point("P2", "Sb", 6700),
    )

    j = by_id(tree.junctions)
    reaches = by_id(tree.reaches)
    merge = [x for x in tree.junctions if river.name(x.place.unit) == "T2b"]
    assert len(merge) == 1 and merge[0].kind == "confluence"
    (down,) = [r for r in tree.reaches if r.from_node == merge[0].id]
    assert river.name(j[down.to].place.unit) == "M4"
    # Into the fork: P1's reach down the main river first, then P2's from the side
    first, _, second, _ = merge[0].inflows
    assert j[reaches[first].from_node].point == "P1"
    assert j[reaches[second].from_node].point == "P2"
    elements = unit_elements(river, tree)
    assert elements["T2b"] == elements["T2a"] == reaches[down.id].intermediate
    assert elements["Sa"] == reaches[second].intermediate
    p1 = j[reaches[first].from_node]
    assert elements["T2c"] == [
        (6500.0, p1.inflows[0]),
        ("outlet", reaches[first].intermediate),
    ]


def test_a_point_30_m_above_the_fork_of_its_path_is_the_fork(river):
    # P2 lies 30 m above the fork of T2 on S: it moves to the fork, and P1 on T2's
    # main river comes down to it by its reach; S above P2 enters it as a headwater
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P1", "T2c", 6500),
        river.point("P2", "Sa", 6030),
    )

    (p2,) = [p for p in tree.points if p.point_id == "P2"]
    assert (p2.at_node, p2.place) == (True, river.place("T2b", 6000))
    fork = by_id(tree.junctions)[p2.node]
    assert fork.kind == "point"
    reach, przyrzecze, headwater = fork.inflows
    assert by_id(tree.reaches)[reach].from_node == node_of(tree, "P1")
    z = by_id(tree.subcatchments)
    assert z[przyrzecze].outlet == UnitOutlet(river.index["T2c"])
    assert (z[headwater].kind, z[headwater].point, z[headwater].outlet) == (
        "headwater",
        "P2",
        UnitOutlet(river.index["Sa"]),
    )
    elements = unit_elements(river, tree)
    assert elements["Sa"] == elements["Sb"] == headwater


def test_a_tributary_without_a_point_at_its_mouth_has_a_headwater_on_its_main_river():
    # The Kaczawa of the author's network (2026-11-11): T2 enters A's trunk with no
    # point at its mouth; P1 lies on S 10 m above its mouth into T2's main river, whose
    # part above the fork (T2c) is larger than S and carries no point; Q lies 10 m
    # above the mouth of U, lower on T2. Both move to their forks: T2c is the
    # headwater of P1's node, and the reach from it runs down T2
    river = River(extra_units={"U": ("T2a", 1.0, 500.0)})
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P1", "Sa", 6010),
        river.point("Q", "U", 5510),
    )

    assert tree.order == (
        *("Z2", "Z5", "Z6", "J3", "R3", "Z4", "Z7", "J2", "R2", "Z3", "J1", "R1"),
        *("Z1", "P1", "O"),
    )
    assert {p.point_id: (p.node, p.at_node) for p in tree.points} == {
        "A": ("P1", False),
        "P1": ("J3", True),
        "Q": ("J2", True),
    }
    j = by_id(tree.junctions)
    assert [(j[i].kind, river.name(j[i].place.unit)) for i in ("J1", "J2", "J3")] == [
        ("confluence", "M4"),
        ("point", "T2a"),
        ("point", "T2b"),
    ]
    assert [j[i].inflows for i in ("P1", "J1", "J2", "J3")] == [
        ("R1", "Z1"),
        ("Z2", "R2", "Z3"),
        ("R3", "Z4", "Z7"),
        ("Z5", "Z6"),
    ]
    assert [(r.from_node, r.to) for r in tree.reaches] == [
        ("J1", "P1"),
        ("J2", "J1"),
        ("J3", "J2"),
    ]
    elements = unit_elements(river, tree)
    assert elements.pop("M0") == [(500.0, "Z1"), ("outlet", None)]
    assert elements == {
        **dict.fromkeys(("M5", "M6", "M7", "T3a"), "Z2"),
        "T2a": "Z3",
        "T2b": "Z4",
        "T2c": "Z5",
        "Sa": "Z6",
        "Sb": "Z6",
        "U": "Z7",
        **dict.fromkeys(("M4", "M3", "M2", "M1", "T1a", "T1b"), "Z1"),
    }


def test_a_closing_section_at_a_confluence_receives_both_branches(river):
    # A at the confluence of T1 and the main river: the main river enters it as a
    # headwater, T1 by the reach from P1; A's own unit lies outside (N5)
    outlet = river.point("A", "M2", 3000)
    tree = build(river, outlet, river.point("P1", "T1a", 3300))

    assert tree.order == ("Z1", "Z3", "P1", "R1", "Z2", "J1", "O")
    a = by_id(tree.junctions)["J1"]
    assert (a.kind, a.point, a.inflows) == ("outlet", "A", ("Z1", "R1", "Z2"))
    z = by_id(tree.subcatchments)
    assert z["Z1"].outlet == UnitOutlet(river.index["M3"])
    assert z["Z2"].outlet == UnitOutlet(river.index["T1a"])
    assert by_id(tree.reaches)["R1"].lower == outlet.place
    assert river.name(int(tree.units[0])) == "M2"
    assert tree.unit_elements[0] == 0
    elements = unit_elements(river, tree)
    assert "M2" not in elements
    assert elements["T1a"] == [(3300.0, "Z3"), ("outlet", "Z2")]


@pytest.mark.parametrize("fd", [3005, 3040, 3060])
def test_a_gauge_at_most_50_m_above_a_confluence_is_the_confluence(river, fd):
    # P1's path enters A's trunk at the head of M2 (3000 m); the gauge on M3 above it
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P1", "T1a", 3200),
        river.point("G", "M3", fd),
    )

    (g,) = [p for p in tree.points if p.point_id == "G"]
    j = by_id(tree.junctions)
    (from_p1,) = [r for r in tree.reaches if r.from_node == node_of(tree, "P1")]
    if fd - 3000 <= MOUTH_TOLERANCE_M:
        # G moves to the confluence and is it: the main river above is its headwater
        assert (g.at_node, g.place) == (True, river.place("M2", 3000))
        node = j[g.node]
        assert (node.kind, node.inflows[1]) == ("point", from_p1.id)
        assert by_id(tree.subcatchments)[node.inflows[0]].kind == "headwater"
        assert [x.kind for x in tree.junctions].count("confluence") == 0
    else:
        assert (g.at_node, g.place) == (False, river.place("M3", fd))
        (confluence,) = [x for x in tree.junctions if x.kind == "confluence"]
        (from_g,) = [r for r in tree.reaches if r.from_node == g.node]
        assert confluence.inflows[0] == from_g.id
        assert from_p1.to == confluence.id


def test_a_point_30_m_above_the_point_below_it_on_one_river_keeps_its_place(river):
    # No node lies between them: the reach from G carries P's own cells (D5)
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P", "M3", 3500),
        river.point("G", "M3", 3530),
    )

    (g,) = [p for p in tree.points if p.point_id == "G"]
    assert not g.at_node
    (reach,) = [r for r in tree.reaches if r.from_node == g.node]
    assert reach.to == node_of(tree, "P")
    assert (reach.upper, reach.lower) == (
        river.place("M3", 3530),
        river.place("M3", 3500),
    )


def test_a_river_without_a_point_at_a_node_enters_it_on_its_own():
    # V (2.5 km²) and W (0.5 km²) join M3 and T1 at the head of M2, where P1 lies: V,
    # a river of the network, enters the node as a dopływ of its own; W, below the
    # threshold, stays in the element below the node
    river = River(extra_units={"V": ("M2", 2.5, 400.0), "W": ("M2", 0.5, 300.0)})
    tree = build(river, river.point("A", "M0", 500), river.point("P1", "T1a", 3020))

    assert tree.order == ("Z2", "Z3", "Z4", "J1", "R1", "Z1", "P1", "O")
    j = by_id(tree.junctions)
    assert j["J1"].inflows == ("Z2", "Z3", "Z4")
    assert [s.outlet for s in tree.subcatchments[1:]] == [
        UnitOutlet(river.index["M3"]),
        UnitOutlet(river.index["V"]),
        UnitOutlet(river.index["T1a"]),
    ]
    elements = unit_elements(river, tree)
    assert elements["V"] == "Z3"
    assert elements["W"] == elements["M2"] == elements["M1"] == "Z1"


def test_a_river_at_the_cell_of_a_gauge_enters_its_node(river):
    # G lies at the head of M4, where T2 (7 km², no point) joins M5; Q lies on M6
    gauge = river.point("G", "M4", 5000)
    assert gauge.place.at_head
    tree = build(
        river, river.point("A", "M0", 500), gauge, river.point("Q", "M6", 6500)
    )

    (g,) = [j for j in tree.junctions if j.point == "G"]
    assert g.id.startswith("J")
    z = by_id(tree.subcatchments)
    reach, przyrzecze, t2 = g.inflows
    assert by_id(tree.reaches)[reach].intermediate == przyrzecze
    # The reach's przyrzecze ends above the node, at the outlet cell of M5 (N5)
    assert z[przyrzecze].outlet == UnitOutlet(river.index["M5"])
    assert (z[t2].kind, z[t2].point, z[t2].outlet) == (
        "headwater",
        "G",
        UnitOutlet(river.index["T2a"]),
    )
    elements = unit_elements(river, tree)
    assert {elements[name] for name in ("T2a", "T2b", "T2c", "Sa", "Sb")} == {t2}
    assert elements["M5"] == przyrzecze


def test_a_tributary_that_joins_a_reach_stays_in_its_przyrzecze(river):
    # The plan's case 11: T1 and T2 join the main river between G and A
    tree = build(river, river.point("A", "M0", 500), river.point("G", "M5", 5500))

    assert [j.id for j in tree.junctions] == ["P1", "P2"]
    (reach,) = tree.reaches
    elements = unit_elements(river, tree)
    for name in ("T1a", "T1b", "T2a", "T2b", "T2c", "Sa", "Sb", "M4", "M1"):
        assert elements[name] == reach.intermediate, name


@pytest.mark.parametrize(
    ("extra_units", "points"),
    [
        (
            {},
            [
                ("P1", "T1a", 3020),
                ("P2", "Sb", 6700),
                ("P3", "M5", 5500),
                ("P4", "T2c", 6500),
                ("P5", "T3a", 7300),
            ],
        ),
        # Branches of a branch: T2 without a point at its mouth, P2 at the fork of S
        # and T2's main river with R above it on S, Q on U lower on T2
        (
            {"U": ("T2a", 1.0, 500.0)},
            [
                ("P1", "T1a", 3020),
                ("P2", "Sa", 6010),
                ("P3", "M5", 5500),
                ("P5", "T3a", 7300),
                ("Q", "U", 5700),
                ("R", "Sb", 6700),
            ],
        ),
        # Rivers at nodes: V joins at the head of M2, where P1 moves, and W at the
        # head of M4, where P2 moves; Q lies 100 m above P2's node on M5, P6 on S
        (
            {"V": ("M2", 2.5, 400.0), "W": ("M4", 1.5, 300.0)},
            [
                ("P1", "T1a", 3020),
                ("P2", "T2a", 5030),
                ("P5", "T3a", 7300),
                ("P6", "Sb", 6700),
                ("Q", "M5", 5100),
            ],
        ),
    ],
    ids=["a gauge on a tributary", "branches of a branch", "rivers at nodes"],
)
def test_the_same_points_in_another_order_give_the_same_network(extra_units, points):
    # The plan's case 12
    river = River(extra_units=extra_units)
    controls = [river.point(*point) for point in points]

    def network(order):
        tree = build(river, river.point("A", "M0", 500), *order)
        return (
            tree.order,
            tree.subcatchments,
            tree.reaches,
            tree.junctions,
            tree.unit_elements.tolist(),
            tree.splits,
            sorted(tree.points, key=lambda p: p.point_id),
        )

    first = network(controls)
    rng = random.Random(7)
    orders = [rng.sample(controls, len(controls)) for _ in range(10)]
    orders.append(controls[::-1])
    assert all(order != controls for order in orders)
    for order in orders:
        assert network(order) == first, [c.point_id for c in order]
    assert first[0][-1] == "O"


def test_the_ids_of_the_request_name_no_node(river):
    # The plan's case 10: handles that look like the network's ids change nothing
    def network(names):
        a, p1, p2, p3 = names
        tree = build(
            river,
            river.point(a, "M0", 500),
            river.point(p1, "T1a", 3020),
            river.point(p2, "T2c", 6500),
            river.point(p3, "M5", 5500),
        )
        handle = dict(zip(names, ("A", "P1", "P2", "P3"), strict=True))
        handle[None] = None
        return (
            tree.order,
            [
                (s.id, s.kind, s.to, handle[s.point], s.reach)
                for s in tree.subcatchments
            ],
            tree.reaches,
            [(j.id, j.kind, handle[j.point], j.inflows) for j in tree.junctions],
            [(handle[p.point_id], p.node, p.at_node) for p in tree.points],
        )

    assert network(("x", "J1", "Z3", "O")) == network(("A", "P1", "P2", "P3"))
