"""POST /api/delineate-network on the rasters of a synthetic process_dem run (ADR-080).

process_dem runs over a main river with three tributaries (tests.fixtures.pipeline_run,
river_network_dem); DEM_DIR points at its saved rasters, the catchment graph of its
units of 1 ha is built from the rows it would insert, and a fake database answers the
queries of the measures. The hand-off of the response validates against the copied
envelope and the pinned Hydrolog's network schema, and Hydrolog reads its payload: its
`read_network` once the person adds what the hand-off leaves to Sieć (the rainfall and
the section of each reach), `route schematic --structure-only` as it is handed off.
"""

import json
import re
import threading
import time
from dataclasses import replace
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hydrolog.operations import route_network, route_schematic
from hydrolog.routing.document import read_network
from jsonschema import Draft202012Validator

import api.endpoints.network
import core.network_delineation
from api.main import app
from core.config import get_settings
from core.database import get_db
from core.messages import MESSAGES, render
from core.network_delineation import MIN_REACH_SLOPE_M_PER_M
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

_ROOT = Path(__file__).resolve().parents[3]
ENVELOPE = Draft202012Validator(
    json.loads(
        (_ROOT / "schemas" / "nogat" / "handoff-1.schema.json").read_text(
            encoding="utf-8"
        )
    )
)
NETWORK = Draft202012Validator(
    json.loads(
        files("hydrolog")
        .joinpath("schemas/hydrolog-network-1.schema.json")
        .read_text(encoding="utf-8")
    )
)
URL = "/api/delineate-network"
OUTLET = (219, 85)  # the outlet cell of the grid, on the main river
# The last cell of each tributary above its confluence with the main river, (row,
# column): a click there moves to the confluence, a node of the network (N3)
T3_MOUTH, T2_MOUTH, T1_MOUTH = (75, 86), (123, 86), (159, 84)
# The confluence of T1 and the main river, the cell below their last cells
AT_T1 = (160, 85)
# Points away from the nodes: up T2, on the main river between T1 and T2
UP_T2, MAIN_ABOVE_T1 = (123, 110), (140, 85)
# What a description of Hydrolog refuses: a control character but line feed
CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]")


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_pipeline(
        tmp_path_factory.mktemp("network"),
        river_network_dem(),
        cell_m=NETWORK_CELL_M,
        x0=NETWORK_X0,
        y1=NETWORK_Y1,
        thresholds=[NETWORK_UNIT_THRESHOLD_M2],
    )


@pytest.fixture(scope="module")
def graph(run):
    return catchment_graph(run, NETWORK_UNIT_THRESHOLD_M2)


@pytest.fixture
def client(run, graph, monkeypatch):
    """The API on the run's rasters (DEM_DIR), its graph and the fake database."""
    height_m, width_m = (n * NETWORK_CELL_M for n in NETWORK_SHAPE)
    db = FakeDatabase(
        run,
        NETWORK_UNIT_THRESHOLD_M2,
        land_cover=land_cover_layout(NETWORK_X0, NETWORK_Y1, width_m, height_m),
        soils=soil_layout(NETWORK_X0, NETWORK_Y1, width_m, height_m),
    )
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


def text(message_id, lang, problem):
    """The catalogue's text of a message with the details of a problem."""
    return render(MESSAGES[message_id].text(lang), problem["details"])


def at_the_mouths(run):
    """A at the outlet, P1 to P3 at the mouths of T1 to T3 (P2 without a name)."""
    return {
        "outlet": point(run, "A", OUTLET, "Rzeka"),
        "points": [
            point(run, "P1", T1_MOUTH, "Pierwszy"),
            point(run, "P2", T2_MOUTH),
            point(run, "P3", T3_MOUTH, "Trzeci"),
        ],
        "threshold_m2": NETWORK_SNAP_THRESHOLD_M2,
    }


def network_of(run, outlet, *points):
    """A request of the closing section and points given as (id, cell, name)."""
    return {
        "outlet": point(run, *outlet),
        "points": [point(run, *item) for item in points],
        "threshold_m2": NETWORK_SNAP_THRESHOLD_M2,
    }


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
            (j["id"], j["kind"], j["point"], j["inflows"]) for j in body["junctions"]
        ],
    }


@pytest.fixture
def mouths(client, run):
    response = client.post(URL, json=at_the_mouths(run))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def read_with_rainfall_and_sections(payload):
    """Hydrolog's network once the person gives its rainfall and reach sections."""
    completed = {
        **payload,
        "rainfall": {
            "kind": "design",
            "hietogram_type": "beta",
            "total_mm": 50.0,
            "duration_min": 120.0,
            "alpha": 2.0,
            "beta": 5.0,
        },
    }

    def section(node_id, kind, entry):
        if kind == "reach":
            return {**entry, "manning_n": 0.035, "bottom_width_m": 4.0}
        return entry

    return read_network(completed, prepare=section)


class TestTheHandoff:
    """Plan test 15: the hand-off of a network."""

    def test_it_validates_against_the_envelope_and_hydrologs_network(self, mouths):
        handoff = mouths["handoff"]

        assert [e.message for e in ENVELOPE.iter_errors(handoff)] == []
        assert [e.message for e in NETWORK.iter_errors(handoff["payload"])] == []

    def test_every_node_but_the_outlet_has_its_origin(self, mouths):
        handoff = mouths["handoff"]
        nodes = handoff["payload"]["nodes"]
        origins = handoff["node_provenance"]

        assert set(origins) == {n["id"] for n in nodes} - {"O"}
        for node in nodes:
            if node["type"] == "subcatchment":
                origin = origins[node["id"]]["watershed"]
                assert origin["element"] in {"headwater", "intermediate"}
            elif node["type"] in {"reach", "junction"}:
                origin = origins[node["id"]]["node"]
            else:
                continue
            assert origin["source"] == "hydrograf"
        # The closing section's node and place are the origin of the whole network
        closing = mouths["points"][0]
        assert handoff["provenance"]["watershed"] == {
            "source": "hydrograf",
            "point": "P1",
            "latitude": closing["latitude"],
            "longitude": closing["longitude"],
            "threshold_m2": NETWORK_SNAP_THRESHOLD_M2,
        }

    def test_the_origins_name_the_nodes_and_the_measures(self, mouths):
        handoff = mouths["handoff"]
        origins = handoff["node_provenance"]
        junctions = {j["id"]: j for j in mouths["junctions"]}

        # N7: no tributary, no mouth; the ids of the request stay out (N1)
        assert '"tributary"' not in json.dumps(handoff)
        assert "at_mouth" not in json.dumps(handoff)
        for item in mouths["subcatchments"]:
            origin = origins[item["id"]]["watershed"]
            assert origin["element"] == item["kind"]
            assert origin.get("reach") == item["reach"]
            # The node of a point of the request it enters, which Hydrolog shows as
            # „dopływ do punktu J3”; a przyrzecze names its reach
            entered = junctions[item["to"]]
            assert origin.get("point") == (item["to"] if entered["point"] else None)
        node_origins = {node: origins[node]["node"] for node in junctions}
        assert node_origins == {
            "P1": {
                "source": "hydrograf",
                "element": "outlet",
                "name": "Rzeka",
                "latitude": junctions["P1"]["latitude"],
                "longitude": junctions["P1"]["longitude"],
            },
            **{
                node: {
                    "source": "hydrograf",
                    "element": "point",
                    **({"name": name} if name else {}),
                    "at_node": True,
                    "latitude": junctions[node]["latitude"],
                    "longitude": junctions[node]["longitude"],
                }
                for node, name in (("J1", "Pierwszy"), ("J2", None), ("J3", "Trzeci"))
            },
        }
        for reach in mouths["reaches"]:
            origin = origins[reach["id"]]["node"]
            assert origin["length"] == "flow_distance"
            assert origin["slope"] == reach["slope_method"]
            assert origin["upstream_elevation_m"] == reach["upstream_elevation_m"]

    def test_each_node_follows_the_nodes_it_receives(self, mouths):
        nodes = mouths["handoff"]["payload"]["nodes"]

        # The order of D15 with the ids of N8 for three tributaries at their mouths
        assert [n["id"] for n in nodes] == [
            *("Z4", "Z5", "J3", "R3", "Z3", "Z6", "J2", "R2", "Z2", "Z7", "J1"),
            *("R1", "Z1", "P1", "O"),
        ]
        seen: set[str] = set()
        for node in nodes:
            assert set(node.get("from", [])) <= seen, node["id"]
            seen.add(node["id"])
        for node in nodes:
            if node["type"] in {"reach", "outlet"}:
                assert len(node["from"]) == 1, node["id"]
        assert nodes[-1] == {"id": "O", "type": "outlet", "from": ["P1"]}

    def test_it_carries_no_rainfall_time_step_result_or_section(self, mouths):
        handoff = mouths["handoff"]
        payload = handoff["payload"]

        assert "result" not in handoff
        assert not {"rainfall", "timestep_min"} & set(payload)
        for node in payload["nodes"]:
            assert "rainfall" not in node
            if node["type"] == "reach":
                assert node["method"] == "muskingum-cunge"
                assert not {"manning_n", "bottom_width_m", "top_width_m"} & set(node)

    def test_the_descriptions_are_texts_hydrolog_takes(self, mouths):
        payload = mouths["handoff"]["payload"]
        texts = [payload["description"]] + [
            n["description"] for n in payload["nodes"] if n["type"] != "outlet"
        ]

        assert all(0 < len(text) <= 500 for text in texts)
        assert not [text for text in texts if CONTROL.search(text)]
        # The closing section's name names the network, its node the description
        assert mouths["handoff"]["subject"] == "Rzeka, sieć (7 zlewni)"
        assert payload["description"].startswith(
            "Sieć zlewni do przekroju zamykającego P1 (Rzeka), wyznaczona w "
            "Hydrografie: 7 zlewni, 3 odcinki, 4 węzły."
        )

    def test_the_subcatchments_add_up_to_the_closing_section_in_hydrolog(self, mouths):
        nodes = mouths["handoff"]["payload"]["nodes"]
        areas = [
            n["watershed"]["area_km2"] for n in nodes if n["type"] == "subcatchment"
        ]

        assert sum(areas) == pytest.approx(mouths["area_km2"], abs=1e-9)
        for node in nodes:
            if node["type"] == "subcatchment":
                watershed = node["watershed"]
                assert watershed["cn"] > 0
                assert watershed["flow_path_length_km"] > 0
                assert watershed["flow_path_slope_m_per_m"] > 0

    def test_hydrolog_reads_it_once_the_person_gives_rainfall_and_sections(
        self, mouths
    ):
        payload = mouths["handoff"]["payload"]

        network = read_with_rainfall_and_sections(payload)

        assert {node.id for node in network.nodes} == {
            n["id"] for n in payload["nodes"]
        }

    def test_hydrolog_lays_it_out_as_handed_off(self, mouths):
        payload = mouths["handoff"]["payload"]

        drawn = route_schematic(network=payload, structure_only=True).result.to_dict()

        assert drawn["structure_only"] is True
        assert drawn["outlet"] == "O"
        assert {n["id"] for n in drawn["nodes"]} == {n["id"] for n in payload["nodes"]}

    @pytest.mark.parametrize(
        ("cell", "nodes"),
        [(OUTLET, ["Z1", "P1", "O"]), (AT_T1, ["Z1", "Z2", "J1", "O"])],
        ids=["away from a node", "at a confluence"],
    )
    def test_the_closing_section_alone_is_a_network_hydrolog_reads(
        self, client, run, cell, nodes
    ):
        # The plan's cases 1 and 2: a node of one inflow or of two
        response = client.post(URL, json=network_of(run, ("A", cell, "Rzeka")))

        assert response.status_code == 200, response.text
        handoff = response.json()["handoff"]
        payload = handoff["payload"]
        assert [e.message for e in ENVELOPE.iter_errors(handoff)] == []
        assert [e.message for e in NETWORK.iter_errors(payload)] == []
        assert [n["id"] for n in payload["nodes"]] == nodes
        network = read_with_rainfall_and_sections(payload)
        assert {node.id for node in network.nodes} == set(nodes)
        drawn = route_schematic(network=payload, structure_only=True).result.to_dict()
        assert drawn["outlet"] == "O"


class TestTheResponse:
    def test_the_elements_add_up_and_the_points_carry_their_nodes(self, mouths):
        assert mouths["area_check"] == {
            "watershed_km2": mouths["area_km2"],
            "elements_km2": mouths["area_km2"],
        }
        assert mouths["boundary_geojson"]["geometry"]["type"] == "MultiPolygon"
        assert [
            (p["id"], p["name"], p["at_node"], p["node"]) for p in mouths["points"]
        ] == [
            ("A", "Rzeka", False, "P1"),
            ("P1", "Pierwszy", True, "J1"),
            ("P2", None, True, "J2"),
            ("P3", "Trzeci", True, "J3"),
        ]
        assert [
            (j["id"], j["kind"], j["point"], j["name"]) for j in mouths["junctions"]
        ] == [
            ("P1", "outlet", "A", "Rzeka"),
            ("J1", "point", "P1", "Pierwszy"),
            ("J2", "point", "P2", None),
            ("J3", "point", "P3", "Trzeci"),
        ]
        reach = mouths["reaches"][0]
        assert reach["from"] == "J1" and reach["to"] == "P1"
        assert reach["geojson"]["geometry"]["type"] == "LineString"
        assert mouths["notices"] == []


# The names of the elements and nodes (N7): every subcatchment's and node's, by id
NAMES = {
    "at the mouths": (
        at_the_mouths,
        {
            "Z1": "Przyrzecze odcinka R1",
            "Z2": "Przyrzecze odcinka R2",
            "Z3": "Przyrzecze odcinka R3",
            "Z4": "Dopływ do J3 (ciek główny)",
            "Z5": "Dopływ do J3",
            "Z6": "Dopływ do J2",
            "Z7": "Dopływ do J1",
            "P1": "Przekrój zamykający: Rzeka",
            "J1": "Zbieg: Pierwszy",
            "J2": "Zbieg",
            "J3": "Zbieg: Trzeci",
        },
    ),
    # The plan's case 4 with a name: a P above a J the network makes
    "a point up a tributary": (
        lambda run: network_of(run, ("A", OUTLET, "Rzeka"), ("P1", UP_T2, "Nysa Mała")),
        {
            "Z1": "Przyrzecze odcinka R1",
            "Z2": "Dopływ do J1 (ciek główny)",
            "Z3": "Przyrzecze odcinka R2",
            "Z4": "Dopływ do P2",
            "P1": "Przekrój zamykający: Rzeka",
            "J1": "Zbieg",
            "P2": "Punkt: Nysa Mała",
        },
    ),
    # The closing section alone at a confluence, without a name
    "the closing section at a confluence": (
        lambda run: network_of(run, ("A", AT_T1)),
        {
            "Z1": "Dopływ do J1 (ciek główny)",
            "Z2": "Dopływ do J1",
            "J1": "Przekrój zamykający",
        },
    ),
}


class TestTheNames:
    """N7: a dopływ of the node it enters and a przyrzecze; nodes by what they are."""

    @pytest.mark.parametrize(("body", "names"), NAMES.values(), ids=NAMES.keys())
    def test_each_element_and_node_says_what_it_is(self, client, run, body, names):
        response = client.post(URL, json=body(run))

        assert response.status_code == 200, response.text
        nodes = {n["id"]: n for n in response.json()["handoff"]["payload"]["nodes"]}
        found = {}
        for node_id, node in nodes.items():
            if node["type"] == "subcatchment":
                found[node_id] = node["watershed"]["name"]
                assert node["description"].startswith(f"{node['watershed']['name']}: ")
            elif node["type"] == "junction":
                found[node_id] = node["description"]
        assert found == names

    def test_a_closing_section_without_a_name_names_the_network_by_its_place(
        self, client, run
    ):
        response = client.post(URL, json=network_of(run, ("A", AT_T1)))

        handoff = response.json()["handoff"]
        assert re.fullmatch(
            r"Zlewnia \d+,\d{5}° N, \d+,\d{5}° E, sieć \(2 zlewnie\)",
            handoff["subject"],
        )
        assert handoff["payload"]["description"].startswith(
            "Sieć zlewni do przekroju zamykającego J1, wyznaczona w Hydrografie: "
            "2 zlewnie, 0 odcinków, 1 węzeł."
        )

    def test_a_river_joining_at_a_gauge_is_a_headwater_of_its_node(self, client, run):
        # G at the confluence of T1 and the main river, Q 200 m above it on the main
        # river: T1, with no point, enters G's node as a headwater of its own
        body = network_of(
            run,
            ("A", OUTLET, "Rzeka"),
            ("G", AT_T1, "Wodowskaz"),
            ("Q", MAIN_ABOVE_T1),
        )

        response = client.post(URL, json=body)

        assert response.status_code == 200, response.text
        network = response.json()
        (gauge,) = [j for j in network["junctions"] if j["point"] == "G"]
        (river,) = [
            s
            for s in network["subcatchments"]
            if s["to"] == gauge["id"] and s["kind"] == "headwater"
        ]
        assert gauge["inflows"][-1] == river["id"]
        nodes = {n["id"]: n for n in network["handoff"]["payload"]["nodes"]}
        assert nodes[river["id"]]["watershed"]["name"] == f"Dopływ do {gauge['id']}"
        assert nodes[gauge["id"]]["description"] == "Zbieg: Wodowskaz"


# A point on T2 ten cells (100 m) above its mouth: beyond 50 m, so it reaches the
# confluence by a reach of some 100 m
T2_ABOVE_THE_MOUTH = (123, 96)


def above_a_confluence(run):
    """P1 and P3 at their mouths, P2 100 m up T2."""
    body = at_the_mouths(run)
    body["points"][1] = point(run, "P2", T2_ABOVE_THE_MOUTH)
    return body


def flat(reach_id):
    """A _measure_reach that gives the reach the minimum slope, as a flat NMT does."""
    real = core.network_delineation._measure_reach

    def measure(grid, cg, db, nmt, reach):
        measured = real(grid, cg, db, nmt, reach)
        if reach.id != reach_id:
            return measured
        return replace(
            measured, slope_m_per_m=MIN_REACH_SLOPE_M_PER_M, slope_method="minimum"
        )

    return measure


def reach_notices(body):
    return {
        n["ids"][0]: n["reach"]
        for n in body["notices"]
        if n["code"] == "reach_short_or_flat"
    }


class TestShortAndFlatReaches:
    """D10a: a reach shorter than 200 m or of the minimum slope is a notice."""

    def test_a_point_100_m_above_a_confluence_gets_its_move_to_the_node(
        self, client, run
    ):
        response = client.post(URL, json=above_a_confluence(run))

        assert response.status_code == 200, response.text
        body = response.json()
        p2 = next(p for p in body["points"] if p["id"] == "P2")
        assert (p2["at_node"], p2["node"]) == (False, "P2")
        reach = next(r for r in body["reaches"] if r["from"] == p2["node"])
        junction = next(j for j in body["junctions"] if j["id"] == reach["to"])
        assert junction["kind"] == "confluence"
        notice = reach_notices(body)[reach["id"]]
        assert notice["length_m"] == pytest.approx(reach["length_km"] * 1000)
        assert 50 < notice["length_m"] < 200
        assert notice["upper_point"] == "P2"
        assert notice["lower"] == junction["id"]
        assert notice["slope_minimum"] is False
        assert notice["lag_min"] is None
        # The cell above the confluence on T2, one cell from the node's
        assert notice["move_to"] is not None
        assert run_cell(notice["move_to"]) == T2_MOUTH

    def test_the_point_moved_there_is_the_confluence(self, client, run):
        first = client.post(URL, json=above_a_confluence(run)).json()
        reach_id = next(
            r for r in first["reaches"] if r["from"] == first["points"][2]["node"]
        )["id"]
        move_to = reach_notices(first)[reach_id]["move_to"]
        body = above_a_confluence(run)
        body["points"][1].update(move_to)

        response = client.post(URL, json=body)

        assert response.status_code == 200, response.text
        moved = response.json()
        p2 = next(p for p in moved["points"] if p["id"] == "P2")
        assert p2["at_node"] is True
        assert reach_notices(moved) == {}
        # T2 enters P2's node with no reach: the network of the points at the mouths
        mouths = client.post(URL, json=at_the_mouths(run)).json()
        assert structure(moved) == structure(mouths)

    def test_a_flat_reach_is_a_notice_and_a_lag_in_the_handoff(
        self, client, run, monkeypatch
    ):
        monkeypatch.setattr(core.network_delineation, "_measure_reach", flat("R2"))

        response = client.post(URL, json=at_the_mouths(run))

        assert response.status_code == 200, response.text
        body = response.json()
        r2 = next(r for r in body["reaches"] if r["id"] == "R2")
        lag_min = max(1, round(r2["length_km"] * 1000 / 0.5 / 60))
        # R2 runs from P2's node down to P1's: no confluence the network makes to
        # move P2 to
        assert reach_notices(body) == {
            "R2": {
                "length_m": pytest.approx(r2["length_km"] * 1000),
                "slope_minimum": True,
                "upper_point": "P2",
                "lower": "J1",
                "move_to": None,
                "lag_min": lag_min,
            }
        }
        handoff = body["handoff"]
        node = next(n for n in handoff["payload"]["nodes"] if n["id"] == "R2")
        assert node["method"] == "lag"
        assert node["lag_min"] == lag_min
        assert node["from"] == ["J2"]
        assert "Opóźnienie" in node["description"]
        origin = handoff["node_provenance"]["R2"]["node"]
        assert origin["slope"] == "minimum"
        assert origin["method"] == "lag"
        assert origin["method_reason"] == "flat"
        assert origin["length_km"] == r2["length_km"]
        assert [e.message for e in ENVELOPE.iter_errors(handoff)] == []
        assert [e.message for e in NETWORK.iter_errors(handoff["payload"])] == []

    def test_hydrolog_routes_a_handoff_with_a_lag_once_given_rainfall_and_sections(
        self, client, run, monkeypatch
    ):
        monkeypatch.setattr(core.network_delineation, "_measure_reach", flat("R1"))
        payload = client.post(URL, json=at_the_mouths(run)).json()["handoff"]["payload"]
        completed = {
            **payload,
            "timestep_min": 5,
            "rainfall": {
                "kind": "design",
                "hietogram_type": "block",
                "total_mm": 60.0,
                "duration_min": 120.0,
            },
            "nodes": [
                {**n, "manning_n": 0.04, "bottom_width_m": 5.0}
                if n.get("method") == "muskingum-cunge"
                else n
                for n in payload["nodes"]
            ],
        }

        routed = route_network(network=completed).result.to_dict()

        peaks = {n["id"]: n["peak_m3s"] for n in routed["nodes"]}
        assert peaks["O"] > 0
        assert peaks["R1"] == pytest.approx(peaks["J1"], rel=0.05)


def run_cell(place):
    """The cell of the grid that a place of a response lies in, (row, column)."""
    xy = transform_wgs84_to_pl1992(place["latitude"], place["longitude"])
    return (
        int((NETWORK_Y1 - xy.y) // NETWORK_CELL_M),
        int((xy.x - NETWORK_X0) // NETWORK_CELL_M),
    )


class TestProblems:
    """Plan test 16: the problem documents of D12."""

    def test_a_point_off_the_streams_is_named_in_both_languages(self, client, run):
        body = at_the_mouths(run)
        body["points"].append(point(run, "P7", (30, 5)))

        english = client.post(URL, json=body)
        polish = client.post(URL, json=body, headers={"Accept-Language": "pl"})

        assert english.status_code == polish.status_code == 404
        problem = english.json()
        assert problem["code"] == "not_found"
        assert problem["details"]["reason"] == "network_point_off_stream"
        assert problem["details"]["point_id"] == "P7"
        assert problem["detail"] == text("network_point_off_stream", "en", problem)
        assert polish.json()["detail"] == text(
            "network_point_off_stream", "pl", problem
        )

    def test_a_point_that_does_not_drain_to_the_closing_section_is_named(
        self, client, run
    ):
        body = network_of(run, ("A", UP_T2), ("P1", T3_MOUTH))

        response = client.post(URL, json=body, headers={"Accept-Language": "pl"})

        assert response.status_code == 400
        problem = response.json()
        assert (problem["code"], problem["details"]["point_id"]) == (
            "validation_error",
            "P1",
        )
        assert problem["detail"] == text("network_point_outside", "pl", problem)

    def test_points_on_one_cell_are_named(self, client, run):
        body = at_the_mouths(run)
        body["points"].append(point(run, "P4", (100, 85)))
        body["points"].append(point(run, "P5", (100, 85)))

        response = client.post(URL, json=body)

        assert response.status_code == 400
        assert response.json()["details"]["reason"] == "network_points_coincide"
        assert response.json()["details"]["point_ids"] == ["P4", "P5"]

    def test_a_point_beside_a_closing_section_at_a_confluence_is_refused(
        self, client, run
    ):
        # The plan's case 9 (N6): the point 10 m above A moves to A's node, which
        # already divides the catchment into the rivers that join there
        body = network_of(run, ("A", AT_T1), ("P1", (159, 85)))

        english = client.post(URL, json=body)
        polish = client.post(URL, json=body, headers={"Accept-Language": "pl"})

        assert english.status_code == polish.status_code == 400
        problem = polish.json()
        assert problem["details"] == {
            "reason": "network_points_coincide",
            "point_ids": ["A", "P1"],
        }
        assert f"{problem['detail']} {problem['hint']}" == (
            "Punkty A, P1 trafiają w ten sam węzeł sieci: jeden punkt w węźle już "
            "dzieli zlewnię na cieki, które się w nim łączą. Usuń jeden z nich albo "
            "przesuń go dalej niż 50 m od węzła."
        )
        assert english.json()["detail"] == text(
            "network_points_coincide", "en", problem
        )

    def test_a_window_above_the_cap_is_unsupported(self, client, run, monkeypatch):
        monkeypatch.setattr(core.network_delineation, "NETWORK_MAX_WINDOW_CELLS", 1000)

        response = client.post(URL, json=at_the_mouths(run))

        assert response.status_code == 422
        assert response.json()["code"] == "unsupported"
        assert response.json()["details"]["reason"] == "network_window_too_large"

    def test_without_the_graph_or_the_rasters_the_store_is_unavailable(
        self, client, run, graph, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(
            api.endpoints.network, "loaded_catchment_graph", lambda _: None
        )
        no_graph = client.post(URL, json=at_the_mouths(run))
        monkeypatch.setattr(
            api.endpoints.network, "loaded_catchment_graph", lambda _: graph
        )
        monkeypatch.setenv("DEM_DIR", str(tmp_path))
        get_settings.cache_clear()
        no_rasters = client.post(URL, json=at_the_mouths(run))

        assert (no_graph.status_code, no_rasters.status_code) == (503, 503)
        assert no_graph.json()["details"]["reason"] == "catchment_graph_unavailable"
        assert no_rasters.json()["details"]["reason"] == "network_rasters_missing"

    @pytest.mark.parametrize(
        ("change", "pointer"),
        [
            (lambda b: b["points"][0].update(id="a"), "/body/points"),
            (lambda b: b["outlet"].pop("id"), "/body/outlet/id"),
            (lambda b: b.update(points=b["points"] * 11), "/body/points"),
            (lambda b: b["points"][0].update(id="P 1"), "/body/points/0/id"),
            (lambda b: b["points"][0].update(id="P" * 17), "/body/points/0/id"),
            (
                lambda b: b["points"][0].update(name="Kamiennik\n"),
                "/body/points/0/name",
            ),
            (lambda b: b["points"][0].update(name="  "), "/body/points/0/name"),
            (lambda b: b["outlet"].update(latitude=91), "/body/outlet/latitude"),
            (lambda b: b.update(threshold_m2=9999), "/body/threshold_m2"),
        ],
        ids=[
            "ids equal without regard to case",
            "the closing section without an id",
            "more than 30 points",
            "an id with a space",
            "an id of 17 characters",
            "a name with a control character",
            "a blank name",
            "a latitude off the globe",
            "a threshold below 1 ha",
        ],
    )
    def test_an_invalid_request_is_refused_before_the_rasters(
        self, client, run, change, pointer
    ):
        body = at_the_mouths(run)
        change(body)

        response = client.post(URL, json=body)

        assert response.status_code == 400
        assert response.json()["details"]["reason"] == "invalid_request"
        assert pointer in response.json()["details"]["fields"]

    def test_the_id_of_the_closing_section_counts_among_the_ids(self, client, run):
        body = at_the_mouths(run)
        body["points"][0]["id"] = "a"

        response = client.post(URL, json=body)

        assert response.status_code == 400
        assert response.json()["details"]["fields"] == ["/body/points"]

    def test_any_other_failure_is_a_failed_network_and_frees_the_worker(
        self, client, run, monkeypatch
    ):
        real = api.endpoints.network.build_network_handoff

        def broken(*_args, **_kwargs):
            raise RuntimeError("the hand-off")

        monkeypatch.setattr(api.endpoints.network, "build_network_handoff", broken)
        failed = client.post(URL, json=at_the_mouths(run))
        monkeypatch.setattr(api.endpoints.network, "build_network_handoff", real)
        next_one = client.post(URL, json=at_the_mouths(run))

        assert failed.status_code == 500
        assert failed.json()["details"]["reason"] == "network_delineation_failed"
        assert next_one.status_code == 200, next_one.text


class TestOneNetworkAtATime:
    """Plan test 17: the lock of the worker (D13)."""

    def test_a_request_waits_for_the_running_network_then_gets_503(
        self, client, run, monkeypatch
    ):
        monkeypatch.setattr(api.endpoints.network, "NETWORK_LOCK_WAIT_S", 0.3)
        lock = api.endpoints.network._network_lock
        assert lock.acquire(timeout=1)
        try:
            started = time.monotonic()
            response = client.post(
                URL, json=at_the_mouths(run), headers={"Accept-Language": "pl"}
            )
            waited = time.monotonic() - started
        finally:
            lock.release()

        assert response.status_code == 503
        problem = response.json()
        assert problem["code"] == "store_unavailable"
        assert problem["details"] == {
            "reason": "network_delineation_busy",
            "wait_s": 0.3,
        }
        assert problem["detail"] == text("network_delineation_busy", "pl", problem)
        assert waited >= 0.3

    def test_a_request_runs_when_the_network_before_it_ends_in_time(self, client, run):
        lock = api.endpoints.network._network_lock
        assert lock.acquire(timeout=1)
        threading.Timer(0.2, lock.release).start()

        response = client.post(URL, json=at_the_mouths(run))

        assert response.status_code == 200, response.text
