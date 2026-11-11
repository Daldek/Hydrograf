"""The preview of a network against its full run, on a synthetic run (ADR-081).

process_dem runs over the main river with three tributaries of the network tests
(tests.fixtures.pipeline_run, river_network_dem) with sub-catchments of 1 ha and of
the 20 ha the points snap to; the catchment graph holds both, and a fake database
answers the queries of the measures and of the preview (the polygons of the
sub-catchments united by element, their stream lines). The preview must name every
element, reach and node as the full run does, give the same areas and reach lengths,
and draw outlines that follow the elements of the full run. The cases of the plan
``2026-11-11-network-nodes.md`` run as networks of both.
"""

from typing import Any

import numpy as np
import pytest
import shapely
from fastapi.testclient import TestClient
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

import api.endpoints.network
import core.network_preview
from api.main import app
from core.config import get_settings
from core.database import get_db
from tests.fixtures.pipeline_run import (
    NETWORK_CELL_M,
    NETWORK_SHAPE,
    NETWORK_SNAP_THRESHOLD_M2,
    NETWORK_UNIT_THRESHOLD_M2,
    NETWORK_X0,
    NETWORK_Y1,
    FakeDatabase,
    catchment_graph,
    land_cover_layout,
    river_network_dem,
    run_pipeline,
    soil_layout,
)
from utils.geometry import transform_pl1992_to_wgs84, transform_wgs84_to_pl1992

FULL = "/api/delineate-network"
PREVIEW = "/api/delineate-network/preview"
OUTLET = (219, 85)  # the outlet cell of the grid, on the main river
# The last cell of each tributary above its confluence with the main river (row,
# column): a click there moves to the confluence, a node of the network (N3)
T3_MOUTH, T2_MOUTH, T1_MOUTH = (75, 86), (123, 86), (159, 84)
# The confluence of T1 and the main river, the cell below their last cells, and the
# main river 30 m above and 30 m below it
AT_T1, ABOVE_T1, BELOW_T1 = (160, 85), (157, 85), (163, 85)
# Points away from the nodes: on the main river below T1 and between T1 and T2, up T2,
# up T1a (the tributary of T1)
MAIN_BELOW_T1, MAIN_ABOVE_T1 = (190, 85), (140, 85)
UP_T2, UP_T1A = (123, 110), (159, 20)
_TO_2180 = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_pipeline(
        tmp_path_factory.mktemp("network_preview"),
        river_network_dem(),
        cell_m=NETWORK_CELL_M,
        x0=NETWORK_X0,
        y1=NETWORK_Y1,
        thresholds=[NETWORK_UNIT_THRESHOLD_M2, NETWORK_SNAP_THRESHOLD_M2],
    )


@pytest.fixture(scope="module")
def graph(run):
    return catchment_graph(run, NETWORK_UNIT_THRESHOLD_M2, NETWORK_SNAP_THRESHOLD_M2)


class RecordingDatabase(FakeDatabase):
    """The fake database, keeping the parameters of the preview's outline query."""

    outlines: list[dict[str, Any]]

    def execute(self, statement, params=None):
        if "AS p(threshold_m2, segment_idx, element)" in str(statement):
            self.outlines.append(params)
        return super().execute(statement, params)


@pytest.fixture
def db(run):
    height_m, width_m = (n * NETWORK_CELL_M for n in NETWORK_SHAPE)
    database = RecordingDatabase(
        run,
        NETWORK_UNIT_THRESHOLD_M2,
        land_cover=land_cover_layout(NETWORK_X0, NETWORK_Y1, width_m, height_m),
        soils=soil_layout(NETWORK_X0, NETWORK_Y1, width_m, height_m),
    )
    database.outlines = []
    return database


@pytest.fixture
def client(run, graph, db, monkeypatch):
    """The API on the run's rasters (DEM_DIR), its graph and the fake database."""
    monkeypatch.setenv("DEM_DIR", str(run.directory))
    get_settings.cache_clear()
    monkeypatch.setattr(
        api.endpoints.network, "loaded_catchment_graph", lambda _db: graph
    )
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def point(run, point_id, cell, name=None):
    """A point of the request at the centre of a cell of the grid."""
    longitude, latitude = transform_pl1992_to_wgs84(*run.cell_centre_xy(*cell))
    body: dict[str, Any] = {
        "id": point_id,
        "latitude": latitude,
        "longitude": longitude,
    }
    if name is not None:
        body["name"] = name
    return body


def request(run, outlet, **points):
    """A request of the closing section A at a cell and the points at theirs."""
    return {
        "outlet": point(run, "A", outlet, "Rzeka"),
        "points": [point(run, point_id, cell) for point_id, cell in points.items()],
        "threshold_m2": NETWORK_SNAP_THRESHOLD_M2,
    }


# The plan's cases (by their numbers) and the networks of the outlines and notices
NETWORKS = {
    "1 the closing section alone at a confluence": (AT_T1, {}),
    "2 the closing section alone": (OUTLET, {}),
    "3 a point on the main river": (OUTLET, {"P1": MAIN_BELOW_T1}),
    "4 a point up a tributary": (OUTLET, {"P1": UP_T2}),
    "5 a point 30 m above a confluence": (OUTLET, {"P1": ABOVE_T1}),
    "6 a point 30 m below a confluence": (OUTLET, {"P1": BELOW_T1}),
    "7 the closing section 30 m above a confluence": (ABOVE_T1, {}),
    "7 the closing section 30 m below a confluence": (BELOW_T1, {}),
    "8 a point on a tributary of a tributary": (OUTLET, {"P1": UP_T1A}),
    "11 a tributary that joins a reach": (OUTLET, {"P1": MAIN_ABOVE_T1}),
    # Every point at a confluence: whole units only
    "at the mouths": (OUTLET, {"P1": T1_MOUTH, "P2": T2_MOUTH, "P3": T3_MOUTH}),
    # A gauge between two nodes, and two points in one unit of the main river, which
    # the full run splits into three parts
    "a gauge and two points in one unit": (
        OUTLET,
        {"P1": T1_MOUTH, "G": MAIN_ABOVE_T1, "P2": (99, 85), "P3": (102, 85)},
    ),
    # The closing section inside its unit (its part below lies outside the network)
    "the closing section inside its unit": (
        MAIN_BELOW_T1,
        {"P1": UP_T2, "P2": T3_MOUTH},
    ),
    # A point 100 m up a tributary, beyond 50 m: a short reach to the confluence, with
    # the move of the point there
    "a point 100 m above its confluence": (
        OUTLET,
        {"P1": T1_MOUTH, "P2": (123, 96), "P3": T3_MOUTH},
    ),
    # P1 30 m above the mouth of T1a into T1's main river, as at the Bukowica of the
    # author's network of 2026-11-11: P1 is that confluence, whose main river, the arm
    # from the north, is a headwater
    "a point at the mouth of a tributary's tributary": (
        OUTLET,
        {"P1": (159, 47), "P2": T2_MOUTH, "P3": T3_MOUTH},
    ),
    # The closing section at a confluence, the author's A of 2026-11-11: T1 by the
    # reach from a point up it, the main river a headwater
    "the closing section at a confluence and a point up a branch": (
        AT_T1,
        {"P1": (159, 70)},
    ),
}


def full_and_preview(client, body):
    full = client.post(FULL, json=body)
    preview = client.post(PREVIEW, json=body)
    assert full.status_code == 200, full.text
    assert preview.status_code == 200, preview.text
    return full.json(), preview.json()


def structure(body):
    """The tree of a response: what the ids name and how the nodes join."""
    return {
        "points": [(p["id"], p["node"], p["at_node"]) for p in body["points"]],
        "subcatchments": [
            (s["id"], s["kind"], s["to"], s["point"], s["reach"])
            for s in body["subcatchments"]
        ],
        "reaches": [(r["id"], r["from"], r["to"]) for r in body["reaches"]],
        "junctions": [
            (j["id"], j["kind"], j["point"], j["name"], j["inflows"])
            for j in body["junctions"]
        ],
    }


def handed_off_areas(full):
    """The area of each subcatchment of the full run, exact to the cell (6 decimals)."""
    return {
        node["id"]: node["watershed"]["area_km2"]
        for node in full["handoff"]["payload"]["nodes"]
        if "watershed" in node
    }


def to_2180(geometry: dict[str, Any]) -> BaseGeometry:
    """A GeoJSON geometry of a response (WGS84) in EPSG:2180."""

    def project(coords: np.ndarray) -> np.ndarray:
        x, y = _TO_2180.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(shape(geometry), project)


def run_cell(place):
    """The cell of the grid that a place of a response lies in, (row, column)."""
    xy = transform_wgs84_to_pl1992(place["latitude"], place["longitude"])
    return (
        int((NETWORK_Y1 - xy.y) // NETWORK_CELL_M),
        int((xy.x - NETWORK_X0) // NETWORK_CELL_M),
    )


@pytest.mark.parametrize("network", NETWORKS.values(), ids=NETWORKS.keys())
class TestThePreviewIsTheNetworkOfTheFullRun:
    def test_it_names_the_elements_reaches_and_nodes_as_the_full_run(
        self, client, run, network
    ):
        full, preview = full_and_preview(client, request(run, network[0], **network[1]))

        assert structure(preview) == structure(full)

    def test_its_points_and_nodes_lie_where_the_full_run_puts_them(
        self, client, run, network
    ):
        full, preview = full_and_preview(client, request(run, network[0], **network[1]))

        for ours, theirs in zip(
            preview["points"] + preview["junctions"],
            full["points"] + full["junctions"],
            strict=True,
        ):
            assert ours["latitude"] == pytest.approx(theirs["latitude"], abs=1e-9)
            assert ours["longitude"] == pytest.approx(theirs["longitude"], abs=1e-9)
        assert [p["snap_distance_m"] for p in preview["points"]] == [
            p["snap_distance_m"] for p in full["points"]
        ]

    def test_its_areas_and_reach_lengths_are_those_of_the_full_run(
        self, client, run, network
    ):
        full, preview = full_and_preview(client, request(run, network[0], **network[1]))

        assert {s["id"]: s["area_km2"] for s in preview["subcatchments"]} == (
            handed_off_areas(full)
        )
        assert preview["area_km2"] == full["area_km2"]
        assert {r["id"]: r["length_km"] for r in preview["reaches"]} == {
            r["id"]: r["length_km"] for r in full["reaches"]
        }

    def test_its_notices_are_those_of_the_full_run(self, client, run, network):
        full, preview = full_and_preview(client, request(run, network[0], **network[1]))

        assert preview["notices"] == full["notices"]


# The networks of the cases: the closing section A (named Rzeka) and P1 without a name
CS_ALONE_AT_A_NODE = {
    "points": [("A", "J1", True)],
    "subcatchments": [
        ("Z1", "headwater", "J1", "A", None),
        ("Z2", "headwater", "J1", "A", None),
    ],
    "reaches": [],
    "junctions": [("J1", "outlet", "A", "Rzeka", ["Z1", "Z2"])],
}
A_POINT_AT_A_NODE = {
    "points": [("A", "P1", False), ("P1", "J1", True)],
    "subcatchments": [
        ("Z1", "intermediate", "P1", "A", "R1"),
        ("Z2", "headwater", "J1", "P1", None),
        ("Z3", "headwater", "J1", "P1", None),
    ],
    "reaches": [("R1", "J1", "P1")],
    "junctions": [
        ("P1", "outlet", "A", "Rzeka", ["R1", "Z1"]),
        ("J1", "point", "P1", None, ["Z2", "Z3"]),
    ],
}
A_POINT_ON_THE_RIVER = {
    "points": [("A", "P1", False), ("P1", "P2", False)],
    "subcatchments": [
        ("Z1", "intermediate", "P1", "A", "R1"),
        ("Z2", "headwater", "P2", "P1", None),
    ],
    "reaches": [("R1", "P2", "P1")],
    "junctions": [
        ("P1", "outlet", "A", "Rzeka", ["R1", "Z1"]),
        ("P2", "point", "P1", None, ["Z2"]),
    ],
}
CASES = {
    "1": (AT_T1, {}, CS_ALONE_AT_A_NODE),
    "2": (
        OUTLET,
        {},
        {
            "points": [("A", "P1", False)],
            "subcatchments": [("Z1", "headwater", "P1", "A", None)],
            "reaches": [],
            "junctions": [("P1", "outlet", "A", "Rzeka", ["Z1"])],
        },
    ),
    "3": (OUTLET, {"P1": MAIN_BELOW_T1}, A_POINT_ON_THE_RIVER),
    # The plan's case 4: headwater -> P2 -> R2 -> J1 at the tributary's mouth, the
    # main river above J1 a headwater, J1 -> R1 -> P1
    "4": (
        OUTLET,
        {"P1": UP_T2},
        {
            "points": [("A", "P1", False), ("P1", "P2", False)],
            "subcatchments": [
                ("Z1", "intermediate", "P1", "A", "R1"),
                ("Z2", "headwater", "J1", None, None),
                ("Z3", "intermediate", "J1", None, "R2"),
                ("Z4", "headwater", "P2", "P1", None),
            ],
            "reaches": [("R1", "J1", "P1"), ("R2", "P2", "J1")],
            "junctions": [
                ("P1", "outlet", "A", "Rzeka", ["R1", "Z1"]),
                ("J1", "confluence", None, None, ["Z2", "R2", "Z3"]),
                ("P2", "point", "P1", None, ["Z4"]),
            ],
        },
    ),
    "5": (OUTLET, {"P1": ABOVE_T1}, A_POINT_AT_A_NODE),
    "6": (OUTLET, {"P1": BELOW_T1}, A_POINT_AT_A_NODE),
    "7 above": (ABOVE_T1, {}, CS_ALONE_AT_A_NODE),
    "7 below": (BELOW_T1, {}, CS_ALONE_AT_A_NODE),
    # The cascade of 4: P1 on T1a joins T1's main river at a node the network makes,
    # and T1 joins the main river at another
    "8": (
        OUTLET,
        {"P1": UP_T1A},
        {
            "points": [("A", "P1", False), ("P1", "P2", False)],
            "subcatchments": [
                ("Z1", "intermediate", "P1", "A", "R1"),
                ("Z2", "headwater", "J1", None, None),
                ("Z3", "intermediate", "J1", None, "R2"),
                ("Z4", "headwater", "J2", None, None),
                ("Z5", "intermediate", "J2", None, "R3"),
                ("Z6", "headwater", "P2", "P1", None),
            ],
            "reaches": [("R1", "J1", "P1"), ("R2", "J2", "J1"), ("R3", "P2", "J2")],
            "junctions": [
                ("P1", "outlet", "A", "Rzeka", ["R1", "Z1"]),
                ("J1", "confluence", None, None, ["Z2", "R2", "Z3"]),
                ("J2", "confluence", None, None, ["Z4", "R3", "Z5"]),
                ("P2", "point", "P1", None, ["Z6"]),
            ],
        },
    ),
    "11": (OUTLET, {"P1": MAIN_ABOVE_T1}, A_POINT_ON_THE_RIVER),
}


class TestTheCasesOfThePlan:
    @pytest.mark.parametrize("case", CASES.values(), ids=CASES.keys())
    def test_each_gives_its_network(self, client, run, case):
        outlet, points, network = case

        preview = client.post(PREVIEW, json=request(run, outlet, **points))

        assert preview.status_code == 200, preview.text
        assert structure(preview.json()) == network

    @pytest.mark.parametrize(
        ("outlet", "points"),
        [
            (AT_T1, {}),
            (ABOVE_T1, {}),
            (BELOW_T1, {}),
            (OUTLET, {"P1": ABOVE_T1}),
            (OUTLET, {"P1": BELOW_T1}),
        ],
        ids=["at", "30 m above", "30 m below", "a point above", "a point below"],
    )
    def test_a_point_within_50_m_of_a_confluence_lies_at_it(
        self, client, run, outlet, points
    ):
        preview = client.post(PREVIEW, json=request(run, outlet, **points)).json()

        (at_node,) = [p for p in preview["points"] if p["at_node"]]
        assert run_cell(at_node) == AT_T1
        node = next(j for j in preview["junctions"] if j["id"] == at_node["node"])
        assert run_cell(node) == AT_T1

    def test_a_closing_section_at_a_node_holds_the_branches_alone(self, client, run):
        # N5: its own cell and the rest of its unit lie outside; the branches are
        # the headwaters that enter the point at that node above the closing section
        full, preview = full_and_preview(client, request(run, AT_T1))
        _, above = full_and_preview(client, request(run, OUTLET, P1=ABOVE_T1))

        areas = {s["id"]: s["area_km2"] for s in above["subcatchments"]}
        assert preview["area_km2"] == pytest.approx(areas["Z2"] + areas["Z3"])
        assert full["area_check"] == {
            "watershed_km2": preview["area_km2"],
            "elements_km2": preview["area_km2"],
        }

    def test_a_tributary_that_joins_a_reach_stays_in_its_przyrzecze(self, client, run):
        full, preview = full_and_preview(client, request(run, OUTLET, P1=MAIN_ABOVE_T1))

        przyrzecze = next(s for s in full["subcatchments"] if s["id"] == "Z1")
        outline = to_2180(przyrzecze["watershed"]["boundary_geojson"]["geometry"])
        # T1 and T1a, which join the reach between its ends
        for cell in ((100, 49), (159, 30), (159, 70)):
            assert outline.contains(Point(run.cell_centre_xy(*cell))), cell
        assert [j["id"] for j in preview["junctions"]] == ["P1", "P2"]

    def test_the_ids_of_the_request_name_no_node(self, client, run):
        # The plan's case 10
        cells = (OUTLET, T1_MOUTH, UP_T2, UP_T1A)

        def network(handles):
            body = {
                "outlet": point(run, handles[0], cells[0]),
                "points": [
                    point(run, handle, cell)
                    for handle, cell in zip(handles[1:], cells[1:], strict=True)
                ],
                "threshold_m2": NETWORK_SNAP_THRESHOLD_M2,
            }
            response = client.post(PREVIEW, json=body)
            assert response.status_code == 200, response.text
            canonical = dict(zip(handles, ("A", "P1", "P2", "P3"), strict=True))
            canonical[None] = None
            tree = structure(response.json())
            return {
                "points": [(canonical[h], *rest) for h, *rest in tree["points"]],
                "subcatchments": [
                    (z, kind, to, canonical[p], reach)
                    for z, kind, to, p, reach in tree["subcatchments"]
                ],
                "reaches": tree["reaches"],
                "junctions": [
                    (j, kind, canonical[p], name, inflows)
                    for j, kind, p, name, inflows in tree["junctions"]
                ],
            }

        assert network(("x", "J1", "Z3", "O")) == network(("A", "P1", "P2", "P3"))

    def test_the_same_points_in_another_order_give_the_same_ids(self, client, run):
        # The plan's case 12
        points = {"P1": UP_T2, "P2": UP_T1A, "P3": MAIN_BELOW_T1, "P4": T3_MOUTH}

        def network(order):
            body = request(run, OUTLET, **{key: points[key] for key in order})
            tree = structure(client.post(PREVIEW, json=body).json())
            tree["points"].sort()
            return tree

        first = network(["P1", "P2", "P3", "P4"])
        assert network(["P4", "P3", "P2", "P1"]) == first
        assert network(["P3", "P1", "P4", "P2"]) == first


class TestTheOutlines:
    def test_they_follow_the_elements_of_the_full_run_from_coarser_units(
        self, client, run, db
    ):
        outlet, points = NETWORKS["at the mouths"]
        full, preview = full_and_preview(client, request(run, outlet, **points))
        theirs = {
            s["id"]: to_2180(s["watershed"]["boundary_geojson"]["geometry"])
            for s in full["subcatchments"]
        }

        for element in preview["subcatchments"]:
            ours = to_2180(element["boundary_geojson"]["geometry"])
            overlap = ours.intersection(theirs[element["id"]]).area
            assert overlap / ours.union(theirs[element["id"]]).area > 0.95, element[
                "id"
            ]
        # The elements of whole units are drawn with sub-catchments of 20 ha
        (outlines,) = db.outlines
        assert NETWORK_SNAP_THRESHOLD_M2 in outlines["thresholds"]
        assert len(outlines["segments"]) < len(
            run.catchments[NETWORK_UNIT_THRESHOLD_M2]
        )

    @pytest.mark.parametrize(
        "name",
        [
            "a gauge and two points in one unit",
            # The closing section's cell heads its unit: P1's reach comes down T1
            # into it
            "the closing section at a confluence and a point up a branch",
        ],
    )
    def test_reaches_follow_the_streams_between_their_ends(self, client, run, name):
        outlet, points = NETWORKS[name]
        full, preview = full_and_preview(client, request(run, outlet, **points))
        theirs = {r["id"]: to_2180(r["geojson"]["geometry"]) for r in full["reaches"]}

        for reach in preview["reaches"]:
            line = to_2180(reach["geojson"]["geometry"])
            assert line.hausdorff_distance(theirs[reach["id"]]) < NETWORK_CELL_M, reach[
                "id"
            ]


class TestPointsInsideUnits:
    def test_at_the_mouths_no_point_is_inside_a_unit_and_every_outline_is_exact(
        self, client, run
    ):
        outlet, points = NETWORKS["at the mouths"]
        preview = client.post(PREVIEW, json=request(run, outlet, **points)).json()

        assert not any(p["inside_unit"] for p in preview["points"])
        assert not any(s["outline_approximate"] for s in preview["subcatchments"])

    def test_the_elements_at_a_point_inside_a_unit_have_approximate_outlines(
        self, client, run
    ):
        outlet, points = NETWORKS["a gauge and two points in one unit"]
        preview = client.post(PREVIEW, json=request(run, outlet, **points)).json()

        assert {p["id"]: p["inside_unit"] for p in preview["points"]} == {
            "A": False,
            "P1": False,
            "G": True,
            "P2": True,
            "P3": True,
        }
        nodes = {p["id"]: p["node"] for p in preview["points"]}
        approximate = {
            s["to"] for s in preview["subcatchments"] if s["outline_approximate"]
        }
        assert {nodes["G"], nodes["P2"], nodes["P3"]} <= approximate
        # T1, entering P1's node at its confluence, is whole units
        (t1,) = [
            s
            for s in preview["subcatchments"]
            if s["to"] == nodes["P1"] and s["kind"] == "headwater"
        ]
        assert not t1["outline_approximate"]


class TestComposition:
    @pytest.mark.parametrize(
        ("outlet", "points"),
        [
            (OUTLET, {"P1": T1_MOUTH, "P7": (30, 5)}),
            (UP_T2, {"P1": T3_MOUTH}),
            (OUTLET, {"P1": T1_MOUTH, "P4": (100, 85), "P5": (100, 85)}),
            (AT_T1, {"P1": (159, 85)}),
        ],
        ids=[
            "a point off the streams",
            "a point that does not drain to A",
            "points on one cell",
            "a point beside the closing section at a confluence",
        ],
    )
    def test_its_errors_are_those_of_the_full_run(self, client, run, outlet, points):
        body = request(run, outlet, **points)

        full = client.post(FULL, json=body, headers={"Accept-Language": "pl"})
        preview = client.post(PREVIEW, json=body, headers={"Accept-Language": "pl"})

        assert preview.status_code == full.status_code
        assert full.status_code in (400, 404)
        ours, theirs = preview.json(), full.json()
        assert (ours["code"], ours["details"], ours["detail"]) == (
            theirs["code"],
            theirs["details"],
            theirs["detail"],
        )

    def test_a_point_beside_a_closing_section_at_a_confluence_is_refused(
        self, client, run
    ):
        # The plan's case 9: the point 10 m above the closing section moves to its
        # node, which already divides the catchment (N6)
        body = request(run, AT_T1, P1=(159, 85))

        response = client.post(PREVIEW, json=body, headers={"Accept-Language": "pl"})

        assert response.status_code == 400
        problem = response.json()
        assert problem["details"] == {
            "reason": "network_points_coincide",
            "point_ids": ["A", "P1"],
        }
        assert f"{problem['detail']} {problem['hint']}" == (
            "Punkty A, P1 trafiają w ten sam węzeł sieci: jeden punkt w węźle już "
            "dzieli zlewnię na cieki, które się w nim łączą. Usuń jeden z nich albo "
            "przesuń go dalej niż 50 m od węzła."
        )

    def test_an_element_above_the_limit_of_scs_cn_is_a_notice(
        self, client, run, monkeypatch
    ):
        outlet, points = NETWORKS["at the mouths"]
        monkeypatch.setattr(api.endpoints.network, "HYDROGRAPH_AREA_LIMIT_KM2", 0.5)

        preview = client.post(PREVIEW, json=request(run, outlet, **points)).json()

        large = [s["id"] for s in preview["subcatchments"] if s["area_km2"] > 0.5]
        assert large
        assert preview["notices"] == [
            {"code": "over_scs_cn_limit", "ids": large, "reach": None}
        ]

    def test_a_flat_reach_is_a_notice_with_the_lag_of_the_handoff(
        self, client, run, monkeypatch
    ):
        outlet, points = NETWORKS["at the mouths"]
        monkeypatch.setattr(
            core.network_preview,
            "reach_slope",
            lambda *_args: (0.0001, "minimum", None, None),
        )

        preview = client.post(PREVIEW, json=request(run, outlet, **points)).json()

        notices = {n["ids"][0]: n["reach"] for n in preview["notices"]}
        assert set(notices) == {r["id"] for r in preview["reaches"]}
        for reach in preview["reaches"]:
            notice = notices[reach["id"]]
            assert notice["slope_minimum"] is True
            assert notice["lag_min"] == max(
                1, round(reach["length_km"] * 1000 / 0.5 / 60)
            )

    def test_any_other_failure_is_a_failed_preview(self, client, run, monkeypatch):
        def broken(*_args, **_kwargs):
            raise RuntimeError("the outlines")

        monkeypatch.setattr(core.network_preview, "element_outlines", broken)
        outlet, points = NETWORKS["at the mouths"]

        response = client.post(PREVIEW, json=request(run, outlet, **points))

        assert response.status_code == 500
        assert response.json()["details"]["reason"] == "network_preview_failed"
