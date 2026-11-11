"""core.network_tree builds the tree of a network on a synthetic catchment graph.

A main river of eight units (M0 at the outlet of the graph up to M7) with three
tributaries: T1 (T1a, T1b) joins it at the head of M2, T2 (T2a, T2b, T2c) at the head
of M4 and T3 (T3a) at the head of M6; T2 has a tributary of its own, S (Sa, Sb), at
the head of T2b. The main river carries the larger upstream area at every confluence,
and T2c the larger one at the head of T2b. Flow distances are those of cells of 5 m
along the segments; a point's path runs down them.
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
        """A control point at a cell, with its path down as snapping records it."""
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
        return ControlPoint(point_id, self.place(name, fd), tuple(path))

    def name(self, unit):
        return self.names[unit]


@pytest.fixture
def river():
    return River()


def build(river, outlet, *points):
    """Build the tree of the points; every reach must run down a main river."""
    tree = build_network_tree(river.graph, outlet, list(points))
    assert_no_przyrzecze_holds_a_larger_river(river, tree)
    return tree


def assert_no_przyrzecze_holds_a_larger_river(river, tree):
    """No przyrzecze holds a river larger than the one its reach brings (D4).

    A unit that joins a reach from the side at a confluence inside it, below its
    upper end and above its lower end, lies in the reach's przyrzecze with all above
    it (it carries no point, else its point would have a junction there): it drains
    no more than the unit the reach comes down to that confluence.
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


def test_one_tributary_at_its_mouth_gives_the_example_of_nogat(river):
    tree = build(river, river.point("A", "M0", 500), river.point("P1", "T1a", 3020))

    assert tree.order == ("Z1", "Z2", "J1", "R1", "Z3", "J2", "OUT")
    z = by_id(tree.subcatchments)
    assert (z["Z1"].kind, z["Z1"].to, z["Z1"].point) == ("headwater", "J1", None)
    assert (z["Z2"].kind, z["Z2"].to, z["Z2"].point) == ("tributary", "J1", "P1")
    assert z["Z2"].at_mouth
    assert (z["Z3"].kind, z["Z3"].to, z["Z3"].reach) == ("intermediate", "J2", "R1")
    assert z["Z3"].point == "A"
    (reach,) = tree.reaches
    assert (reach.id, reach.from_node, reach.to, reach.intermediate) == (
        "R1",
        "J1",
        "J2",
        "Z3",
    )
    j = by_id(tree.junctions)
    assert (j["J1"].kind, j["J1"].point, j["J1"].inflows) == (
        "confluence",
        None,
        ("Z1", "Z2"),
    )
    assert (j["J2"].kind, j["J2"].point, j["J2"].inflows) == (
        "outlet",
        "A",
        ("R1", "Z3"),
    )
    # The junction is the head of M2; the reach runs from it down to A
    assert j["J1"].place.unit == river.index["M2"]
    assert river.graph.get_outlet_flow_dist_m(j["J1"].place.above) == 3000.0
    assert reach.lower == river.place("M0", 500)
    points = {p.point_id: p for p in tree.points}
    assert points["P1"].place == river.place("T1a", 3005)
    assert (points["P1"].node, points["A"].node) == ("Z2", "J2")

    elements = unit_elements(river, tree)
    assert elements.pop("M0") == [(500.0, "Z3"), ("outlet", None)]
    assert elements == {
        "M1": "Z3",
        "M2": "Z3",
        "T1a": "Z2",
        "T1b": "Z2",
        **dict.fromkeys(("M3", "M4", "M5", "M6", "M7", "T2a", "T2b", "T2c"), "Z1"),
        **dict.fromkeys(("Sa", "Sb", "T3a"), "Z1"),
    }


def test_points_at_three_mouths_make_a_junction_at_each_confluence(river):
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P1", "T1a", 3020),
        river.point("P2", "T2a", 5030),
        river.point("P3", "T3a", 7010),
    )

    assert tree.order == (
        *("Z1", "Z2", "J1", "R1", "Z3", "Z4", "J2", "R2", "Z5", "Z6", "J3", "R3"),
        *("Z7", "J4", "OUT"),
    )
    z = by_id(tree.subcatchments)
    assert [z[f"Z{i}"].kind for i in range(1, 8)] == [
        "headwater",
        "tributary",
        "intermediate",
        "tributary",
        "intermediate",
        "tributary",
        "intermediate",
    ]
    assert [z[i].point for i in ("Z2", "Z4", "Z6")] == ["P3", "P2", "P1"]
    j = by_id(tree.junctions)
    assert j["J1"].inflows == ("Z1", "Z2")
    assert j["J2"].inflows == ("R1", "Z3", "Z4")
    assert j["J3"].inflows == ("R2", "Z5", "Z6")
    assert j["J4"].inflows == ("R3", "Z7")
    # Each confluence names the point of the tributary joining it; A's has none
    assert [j[i].tributaries for i in ("J1", "J2", "J3", "J4")] == [
        ("P3",),
        ("P2",),
        ("P1",),
        (),
    ]
    assert [(r.from_node, r.to) for r in tree.reaches] == [
        ("J1", "J2"),
        ("J2", "J3"),
        ("J3", "J4"),
    ]
    assert [river.name(j[i].place.unit) for i in ("J1", "J2", "J3")] == [
        "M6",
        "M4",
        "M2",
    ]

    elements = unit_elements(river, tree)
    assert elements.pop("M0") == [(500.0, "Z7"), ("outlet", None)]
    assert elements == {
        "M7": "Z1",
        "T3a": "Z2",
        "M6": "Z3",
        "M5": "Z3",
        **dict.fromkeys(("T2a", "T2b", "T2c", "Sa", "Sb"), "Z4"),
        "M4": "Z5",
        "M3": "Z5",
        "T1a": "Z6",
        "T1b": "Z6",
        "M2": "Z7",
        "M1": "Z7",
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


def test_a_point_200_m_up_a_tributary_has_a_reach_to_its_mouth(river):
    tree = build(river, river.point("A", "M0", 500), river.point("P1", "T1a", 3200))

    assert tree.order == ("Z1", "Z2", "R1", "Z3", "J1", "R2", "Z4", "J2", "OUT")
    z = by_id(tree.subcatchments)
    assert (z["Z2"].kind, z["Z2"].point, z["Z2"].to) == ("tributary", "P1", "R1")
    assert not z["Z2"].at_mouth
    assert (z["Z3"].kind, z["Z3"].reach, z["Z3"].to) == ("intermediate", "R1", "J1")
    assert z["Z3"].outlet == UnitOutlet(river.index["T1a"])
    reaches = by_id(tree.reaches)
    assert (reaches["R1"].from_node, reaches["R1"].to) == ("Z2", "J1")
    assert reaches["R1"].upper == river.place("T1a", 3200)
    assert by_id(tree.junctions)["J1"].inflows == ("Z1", "R1", "Z3")
    elements = unit_elements(river, tree)
    assert elements["T1a"] == [(3200.0, "Z2"), ("outlet", "Z3")]
    assert elements["T1b"] == "Z2"


def test_a_point_40_m_up_a_tributary_moves_to_its_mouth(river):
    tree = build(river, river.point("A", "M0", 500), river.point("P1", "T1a", 3040))

    assert tree.order == ("Z1", "Z2", "J1", "R1", "Z3", "J2", "OUT")
    (p1,) = [p for p in tree.points if p.point_id == "P1"]
    assert p1.at_mouth
    assert p1.place == river.place("T1a", 3005)
    # At the outlet cell of T1a: the unit is whole, only A's unit is split
    assert [s.unit for s in tree.splits] == [river.index["M0"]]


def test_a_gauge_between_two_junctions_splits_the_reach(river):
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P1", "T1a", 3020),
        river.point("P2", "T2a", 5020),
        river.point("G", "M3", 3500),
    )

    j = {junction.point: junction for junction in tree.junctions}
    gauge = j["G"]
    assert gauge.kind == "point"
    reaches = by_id(tree.reaches)
    # J(M2) <- G <- J(M4): the gauge's junction lies between the two confluences
    into_gauge = [r for r in tree.reaches if r.to == gauge.id]
    out_of_gauge = [r for r in tree.reaches if r.from_node == gauge.id]
    assert len(into_gauge) == len(out_of_gauge) == 1
    assert river.name(into_gauge[0].upper.unit) == "M4"
    assert river.name(reaches[out_of_gauge[0].id].lower.unit) == "M2"
    # The gauge comes along the trunk: only P1 joins the confluence below it
    assert by_id(tree.junctions)[out_of_gauge[0].to].tributaries == ("P1",)
    assert gauge.tributaries == ()
    elements = unit_elements(river, tree)
    assert [where for where, _ in elements["M3"]] == [3500.0, "outlet"]


def test_a_gauge_above_every_junction_ends_the_headwater(river):
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P1", "T1a", 3020),
        river.point("P2", "T2a", 5020),
        river.point("P3", "T3a", 7020),
        river.point("G", "M7", 7600),
    )

    z = {s.point: s for s in tree.subcatchments if s.point is not None}
    assert z["G"].kind == "headwater"
    assert [s.kind for s in tree.subcatchments].count("headwater") == 1
    (into_top,) = [r for r in tree.reaches if r.from_node == z["G"].id]
    assert river.name(into_top.lower.unit) == "M6"
    assert unit_elements(river, tree)["M7"] == [
        (7600.0, z["G"].id),
        ("outlet", by_id(tree.subcatchments)[into_top.intermediate].id),
    ]


def test_points_on_a_tributary_and_its_tributary_make_its_own_trunk(river):
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P2", "T2a", 5020),
        river.point("Q", "Sb", 6700),
    )

    j = {junction.point: junction for junction in tree.junctions}
    p2 = j["P2"]
    assert p2.kind == "point"
    (into_p2,) = [r for r in tree.reaches if r.to == p2.id]
    confluence = by_id(tree.junctions)[into_p2.from_node]
    assert confluence.kind == "confluence"
    assert river.name(confluence.place.unit) == "T2b"
    z = by_id(tree.subcatchments)
    headwater = z[confluence.inflows[0]]
    assert headwater.kind == "headwater"
    assert headwater.outlet == UnitOutlet(river.index["T2c"])
    reach_q = by_id(tree.reaches)[confluence.inflows[1]]
    q = z[reach_q.from_node]
    assert (q.kind, q.point) == ("tributary", "Q")
    elements = unit_elements(river, tree)
    assert elements["T2c"] == headwater.id
    assert elements["Sa"] == reach_q.intermediate
    # P2 moved to the outlet cell of T2a: the unit is whole, in the przyrzecze above P2
    assert into_p2.intermediate == p2.inflows[1]
    assert elements["T2a"] == elements["T2b"] == into_p2.intermediate


@pytest.mark.parametrize(
    ("unit", "fd", "kind"),
    [("T2c", 6300, "headwater"), ("Sa", 6300, "tributary")],
)
def test_the_trunk_takes_the_branch_of_the_larger_upstream_area(river, unit, fd, kind):
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P2", "T2a", 5020),
        river.point("Q", unit, fd),
    )

    (q,) = [s for s in tree.subcatchments if s.point == "Q"]
    assert q.kind == kind
    (p2,) = [j for j in tree.junctions if j.point == "P2"]
    kinds = {
        by_id(tree.junctions)[r.to].kind for r in tree.reaches if r.from_node == q.id
    }
    # On the trunk the gauge's reach runs to P2, off it to the confluence above P2
    assert kinds == {"point" if kind == "headwater" else "confluence"}


def test_two_points_in_one_unit_and_a_point_in_the_unit_of_a_split_it(river):
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("G1", "M5", 5700),
        river.point("G2", "M5", 5300),
        river.point("P", "M0", 800),
    )

    numbers = {s.point: s.number for s in tree.subcatchments if s.point}
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


def test_two_points_moved_to_one_mouth_are_refused():
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


def test_two_points_moved_to_one_merge_of_paths_are_refused():
    # A third branch, U, joins T2a 10 m below the fork of T2 (T2b): P1 and P2 lie at
    # most 50 m above that merge of their paths with Q's, so both move to the outlet
    # cell of T2b, past the fork
    river = River({"T2b": 10.0}, extra_units={"U": ("T2a", 1.0, 500.0)})
    with pytest.raises(InvalidRequestError) as raised:
        build(
            river,
            river.point("A", "M0", 500),
            river.point("P1", "T2c", 5535),
            river.point("P2", "Sa", 5540),
            river.point("Q", "U", 5900),
        )

    assert raised.value.message_id == "network_points_coincide"
    assert raised.value.details["point_ids"] == ["P1", "P2"]


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
    z = by_id(tree.subcatchments)
    assert z[reaches[first].from_node].point == "P1"
    assert z[reaches[second].from_node].point == "P2"
    # P2 joins the fork from the side, both points the trunk's confluence
    assert merge[0].tributaries == ("P2",)
    assert j[down.to].tributaries == ("P1", "P2")
    elements = unit_elements(river, tree)
    assert elements["T2b"] == elements["T2a"] == reaches[down.id].intermediate
    assert elements["Sa"] == reaches[second].intermediate
    assert elements["T2c"] == [
        (6500.0, z[reaches[first].from_node].id),
        ("outlet", reaches[first].intermediate),
    ]


def test_a_point_at_most_50_m_above_the_fork_of_its_path_enters_it(river):
    # P2 lies 30 m above the fork of T2 where its path enters T2's main river, on
    # which P1 lies, far above their junction on A's trunk: its tributary enters the
    # fork with no reach
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P1", "T2c", 6500),
        river.point("P2", "Sa", 6030),
    )

    (p2,) = [p for p in tree.points if p.point_id == "P2"]
    assert p2.at_mouth
    assert p2.place == river.place("Sa", 6005)
    (merge,) = [j for j in tree.junctions if river.name(j.place.unit) == "T2b"]
    z = {s.point: s for s in tree.subcatchments if s.point is not None}
    assert (z["P2"].kind, z["P2"].to) == ("tributary", merge.id)
    assert [r for r in tree.reaches if r.from_node == z["P2"].id] == []
    # P1's reach down the main river and its przyrzecze first, then P2's tributary
    reach, _, tributary = merge.inflows
    assert by_id(tree.reaches)[reach].from_node == z["P1"].id
    assert tributary == z["P2"].id
    assert merge.tributaries == ("P2",)
    elements = unit_elements(river, tree)
    assert elements["Sa"] == elements["Sb"] == z["P2"].id


def test_a_tributary_without_a_point_at_its_mouth_has_a_headwater_on_its_main_river():
    # The Kaczawa of the author's network (2026-11-11): T2 enters A's trunk with no
    # point at its mouth; P1 lies on S 10 m above its mouth into T2's main river, whose
    # part above the fork (T2c) is larger than S and carries no point; Q lies 10 m
    # above the mouth of U, lower on T2. T2c is the headwater of the fork, and the
    # reach from the fork runs down T2: no reach from P1 whose przyrzecze holds T2c
    river = River(extra_units={"U": ("T2a", 1.0, 500.0)})
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P1", "Sa", 6010),
        river.point("Q", "U", 5510),
    )

    assert tree.order == (
        *("Z1", "Z2", "Z3", "J1", "R1", "Z4", "Z5", "J2", "R2", "Z6", "J3", "R3"),
        *("Z7", "J4", "OUT"),
    )
    z = by_id(tree.subcatchments)
    assert [(z[f"Z{i}"].kind, z[f"Z{i}"].point) for i in range(1, 8)] == [
        ("headwater", None),
        ("headwater", None),
        ("tributary", "P1"),
        ("intermediate", None),
        ("tributary", "Q"),
        ("intermediate", None),
        ("intermediate", "A"),
    ]
    assert z["Z3"].at_mouth and z["Z5"].at_mouth
    j = by_id(tree.junctions)
    assert [river.name(j[i].place.unit) for i in ("J1", "J2", "J3")] == [
        "T2b",
        "T2a",
        "M4",
    ]
    assert [j[i].inflows for i in ("J1", "J2", "J3", "J4")] == [
        ("Z2", "Z3"),
        ("R1", "Z4", "Z5"),
        ("Z1", "R2", "Z6"),
        ("R3", "Z7"),
    ]
    assert [j[i].tributaries for i in ("J1", "J2", "J3")] == [
        ("P1",),
        ("Q",),
        ("P1", "Q"),
    ]
    assert [(r.from_node, r.to, r.intermediate) for r in tree.reaches] == [
        ("J1", "J2", "Z4"),
        ("J2", "J3", "Z6"),
        ("J3", "J4", "Z7"),
    ]
    elements = unit_elements(river, tree)
    assert elements.pop("M0") == [(500.0, "Z7"), ("outlet", None)]
    assert elements == {
        **dict.fromkeys(("M5", "M6", "M7", "T3a"), "Z1"),
        "T2c": "Z2",
        "Sa": "Z3",
        "Sb": "Z3",
        "T2b": "Z4",
        "U": "Z5",
        "T2a": "Z6",
        **dict.fromkeys(("M4", "M3", "M2", "M1", "T1a", "T1b"), "Z7"),
    }


def test_a_tributary_entering_at_the_cell_of_a_enters_its_junction(river):
    outlet = river.point("A", "M2", 3000)
    assert outlet.place.at_head
    tree = build(river, outlet, river.point("P1", "T1a", 3300))

    (a,) = [j for j in tree.junctions if j.point == "A"]
    z = by_id(tree.subcatchments)
    headwater = z[a.inflows[0]]
    assert (headwater.kind, headwater.point, headwater.outlet) == (
        "headwater",
        "A",
        outlet.place,
    )
    reaches = by_id(tree.reaches)
    assert reaches[a.inflows[1]].lower == outlet.place
    assert tree.order == ("Z1", "Z2", "R1", "Z3", "J1", "OUT")


@pytest.mark.parametrize("fd", [3005, 3040, 3060])
def test_a_gauge_at_most_50_m_above_a_confluence_enters_it(river, fd):
    # P1's path enters A's trunk at the head of M2 (3000 m); the gauge on M3 above it
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P1", "T1a", 3200),
        river.point("G", "M3", fd),
    )

    (g,) = [p for p in tree.points if p.point_id == "G"]
    (gauge,) = [s for s in tree.subcatchments if s.point == "G"]
    (confluence,) = [j for j in tree.junctions if j.kind == "confluence"]
    from_gauge = [r for r in tree.reaches if r.from_node == gauge.id]
    if fd - 3000 <= MOUTH_TOLERANCE_M:
        # At the outlet cell of M3, its headwater enters the confluence directly
        assert g.at_mouth
        assert g.place == river.place("M3", 3005)
        assert from_gauge == []
        assert (gauge.kind, gauge.to) == ("headwater", confluence.id)
        assert confluence.inflows[0] == gauge.id
        assert river.index["M3"] not in {s.unit for s in tree.splits}
    else:
        assert not g.at_mouth
        assert g.place == river.place("M3", fd)
        (reach,) = from_gauge
        assert confluence.inflows[0] == reach.id
    # The gauge comes along the trunk, P1 from the side
    assert confluence.tributaries == ("P1",)


def test_a_point_30_m_above_the_point_below_it_on_one_river_keeps_its_place(river):
    # No confluence lies between them: the reach from G carries P's own cells (D5)
    tree = build(
        river,
        river.point("A", "M0", 500),
        river.point("P", "M3", 3500),
        river.point("G", "M3", 3530),
    )

    (g,) = [p for p in tree.points if p.point_id == "G"]
    assert not g.at_mouth
    (gauge,) = [s for s in tree.subcatchments if s.point == "G"]
    (reach,) = [r for r in tree.reaches if r.from_node == gauge.id]
    (p,) = [j for j in tree.junctions if j.point == "P"]
    assert reach.to == p.id
    assert (reach.upper, reach.lower) == (
        river.place("M3", 3530),
        river.place("M3", 3500),
    )


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
        # Branches of a branch: T2 without a point at its mouth, P2 at the mouth of S
        # into its main river with R above it, Q on U lower on T2
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
    ],
    ids=["a gauge on a tributary", "branches of a branch"],
)
def test_the_same_points_in_another_order_give_the_same_network(extra_units, points):
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
    assert first[0][-1] == "OUT"
