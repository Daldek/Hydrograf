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
OUTLET = (219, 85)  # A: the outlet cell of the grid, on the main river
# The last cell of each tributary above its confluence with the main river, (row,
# column): a click there moves to the mouth (D3)
T3_MOUTH, T2_MOUTH, T1_MOUTH = (75, 86), (123, 86), (159, 84)
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


@pytest.fixture
def mouths(client, run):
    response = client.post(URL, json=at_the_mouths(run))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


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

        assert set(origins) == {n["id"] for n in nodes} - {"OUT"}
        for node in nodes:
            if node["type"] == "subcatchment":
                origin = origins[node["id"]]["watershed"]
                assert origin["element"] in {"headwater", "tributary", "intermediate"}
            elif node["type"] in {"reach", "junction"}:
                origin = origins[node["id"]]["node"]
            else:
                continue
            assert origin["source"] == "hydrograf"
        # A's snapped place is the origin of the whole network
        a = mouths["points"][0]
        assert handoff["provenance"]["watershed"] == {
            "source": "hydrograf",
            "point": "A",
            "latitude": a["latitude"],
            "longitude": a["longitude"],
            "threshold_m2": NETWORK_SNAP_THRESHOLD_M2,
        }

    def test_the_origins_name_the_points_mouths_and_measures(self, mouths):
        origins = mouths["handoff"]["node_provenance"]
        by_id = {s["id"]: s for s in mouths["subcatchments"]}
        tributaries = {
            s["point"]: origins[s["id"]]["watershed"]
            for s in mouths["subcatchments"]
            if s["kind"] == "tributary"
        }

        assert set(tributaries) == {"P1", "P2", "P3"}
        for point_id, origin in tributaries.items():
            assert origin["at_mouth"] is True
            assert origin["point"] == point_id
        for reach in mouths["reaches"]:
            origin = origins[reach["id"]]["node"]
            assert origin["length"] == "flow_distance"
            assert origin["slope"] == reach["slope_method"]
            assert origin["upstream_elevation_m"] == reach["upstream_elevation_m"]
            przyrzecze = next(s for s in by_id.values() if s["reach"] == reach["id"])
            assert origins[przyrzecze["id"]]["watershed"]["reach"] == reach["id"]
        outlet = next(j for j in mouths["junctions"] if j["kind"] == "outlet")
        assert origins[outlet["id"]]["node"]["element"] == "outlet"
        assert origins[outlet["id"]]["node"]["point"] == "A"

    def test_each_node_follows_the_nodes_it_receives(self, mouths):
        nodes = mouths["handoff"]["payload"]["nodes"]

        # The order of D15 for three tributaries at their mouths
        assert [n["id"] for n in nodes] == [
            *("Z1", "Z2", "J1", "R1", "Z3", "Z4", "J2", "R2", "Z5", "Z6", "J3"),
            *("R3", "Z7", "J4", "OUT"),
        ]
        seen: set[str] = set()
        for node in nodes:
            assert set(node.get("from", [])) <= seen, node["id"]
            seen.add(node["id"])
        for node in nodes:
            if node["type"] in {"reach", "outlet"}:
                assert len(node["from"]) == 1, node["id"]
        assert nodes[-1] == {"id": "OUT", "type": "outlet", "from": ["J4"]}

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
        # A's name names the network; each confluence names the point of the
        # tributary joining it, by its name when it has one
        assert mouths["handoff"]["subject"].startswith("Rzeka, ")
        descriptions = {n["id"]: n["description"] for n in payload["nodes"][:-1]}
        names = {p["id"]: p["name"] for p in mouths["points"]}
        for item in mouths["subcatchments"]:
            if item["kind"] == "tributary":
                junction = descriptions[item["to"]]
                assert item["point"] in junction
                assert names[item["point"]] is None or names[item["point"]] in junction
                others = {"P1", "P2", "P3"} - {item["point"]}
                assert not [other for other in others if other in junction]

    def test_the_subcatchments_add_up_to_a_in_hydrolog(self, mouths):
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

        network = read_network(completed, prepare=section)

        assert {node.id for node in network.nodes} == {
            n["id"] for n in payload["nodes"]
        }

    def test_hydrolog_lays_it_out_as_handed_off(self, mouths):
        payload = mouths["handoff"]["payload"]

        drawn = route_schematic(network=payload, structure_only=True).result.to_dict()

        assert drawn["structure_only"] is True
        assert drawn["outlet"] == "OUT"
        assert {n["id"] for n in drawn["nodes"]} == {n["id"] for n in payload["nodes"]}


class TestTheResponse:
    def test_the_elements_add_up_to_a_and_name_their_points(self, mouths):
        assert mouths["area_check"] == {
            "watershed_km2": mouths["area_km2"],
            "elements_km2": mouths["area_km2"],
        }
        assert mouths["boundary_geojson"]["geometry"]["type"] == "MultiPolygon"
        assert [(p["id"], p["name"], p["at_mouth"]) for p in mouths["points"]] == [
            ("A", "Rzeka", False),
            ("P1", "Pierwszy", True),
            ("P2", None, True),
            ("P3", "Trzeci", True),
        ]
        reach = mouths["reaches"][0]
        assert reach["from"] == "J1" and reach["to"] == "J2"
        assert reach["geojson"]["geometry"]["type"] == "LineString"
        assert mouths["notices"] == []


# A gauge on the main river above T3's confluence, on A's trunk with no point above
# it, so its subcatchment is the headwater: 20 m above, the mouth rule moves it to the
# confluence (D3); 100 m above, it keeps its place and a reach runs to the confluence
GAUGE_AT_T3, GAUGE_ABOVE_T3 = (73, 85), (65, 85)


class TestTheHeadwaterIsHandedOffAsATributary:
    """The author's decision of 2026-11-11: two kinds for the person, the contract kept.

    Which branch of a confluence goes on as the main river follows the larger upstream
    area, so the hand-off names a headwater as a tributary; its kind stays `headwater`.
    """

    def test_the_headwater_above_the_uppermost_junction_is_a_tributary_above_it(
        self, mouths
    ):
        nodes = {n["id"]: n for n in mouths["handoff"]["payload"]["nodes"]}
        (headwater,) = [s for s in mouths["subcatchments"] if s["kind"] == "headwater"]

        assert headwater["point"] is None
        name = f"Dopływ powyżej {headwater['to']}"
        assert nodes[headwater["id"]]["watershed"]["name"] == name
        assert nodes[headwater["id"]]["description"].startswith(f"{name}: ")

    @pytest.mark.parametrize(
        ("cell", "name"),
        [
            (GAUGE_AT_T3, "Dopływ do ujścia przy G (Wodowskaz)"),
            (GAUGE_ABOVE_T3, "Dopływ do punktu G (Wodowskaz)"),
        ],
        ids=["at-the-confluence", "a-reach-above-it"],
    )
    def test_a_headwater_and_a_tributary_at_one_confluence_are_both_tributaries(
        self, client, run, cell, name
    ):
        body = {
            "outlet": point(run, "A", OUTLET, "Rzeka"),
            "points": [
                point(run, "G", cell, "Wodowskaz"),
                point(run, "P3", T3_MOUTH, "Trzeci"),
            ],
            "threshold_m2": NETWORK_SNAP_THRESHOLD_M2,
        }

        response = client.post(URL, json=body)

        assert response.status_code == 200, response.text
        network = response.json()
        by_point = {s["point"]: s for s in network["subcatchments"] if s["point"]}
        gauge, tributary = by_point["G"], by_point["P3"]
        assert (gauge["kind"], tributary["kind"]) == ("headwater", "tributary")
        handoff = network["handoff"]
        nodes = {n["id"]: n for n in handoff["payload"]["nodes"]}
        assert nodes[gauge["id"]]["watershed"]["name"] == name
        assert nodes[tributary["id"]]["watershed"]["name"] == (
            "Dopływ do ujścia przy P3 (Trzeci)"
        )
        assert nodes[tributary["to"]]["description"] == (
            "Zbieg: dopływ G (Wodowskaz), dopływ P3 (Trzeci)"
        )
        origins = handoff["node_provenance"]
        assert origins[gauge["id"]]["watershed"]["element"] == "headwater"
        assert origins[tributary["id"]]["watershed"]["element"] == "tributary"


# A point on T2 ten cells (100 m) above its mouth: beyond the mouth rule's 50 m, so
# its subcatchment reaches the confluence by a reach of some 100 m
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

    def test_a_point_100_m_above_a_confluence_gets_its_move_to_the_mouth(
        self, client, run
    ):
        response = client.post(URL, json=above_a_confluence(run))

        assert response.status_code == 200, response.text
        body = response.json()
        p2 = next(p for p in body["points"] if p["id"] == "P2")
        assert p2["at_mouth"] is False
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
        # The cell above the confluence on T2, one cell from the junction's
        assert notice["move_to"] is not None
        assert run_cell(notice["move_to"]) == T2_MOUTH

    def test_the_point_moved_there_enters_the_confluence_without_a_reach(
        self, client, run
    ):
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
        assert p2["at_mouth"] is True
        assert not [r for r in moved["reaches"] if r["from"] == p2["node"]]
        assert reach_notices(moved) == {}

    def test_a_flat_reach_is_a_notice_and_a_lag_in_the_handoff(
        self, client, run, monkeypatch
    ):
        monkeypatch.setattr(core.network_delineation, "_measure_reach", flat("R1"))

        response = client.post(URL, json=at_the_mouths(run))

        assert response.status_code == 200, response.text
        body = response.json()
        r1 = next(r for r in body["reaches"] if r["id"] == "R1")
        lag_min = max(1, round(r1["length_km"] * 1000 / 0.5 / 60))
        # R1 runs from confluence J1 to confluence J2: no point to move
        assert reach_notices(body) == {
            "R1": {
                "length_m": pytest.approx(r1["length_km"] * 1000),
                "slope_minimum": True,
                "upper_point": None,
                "lower": "J2",
                "move_to": None,
                "lag_min": lag_min,
            }
        }
        handoff = body["handoff"]
        node = next(n for n in handoff["payload"]["nodes"] if n["id"] == "R1")
        assert node["method"] == "lag"
        assert node["lag_min"] == lag_min
        assert node["from"] == ["J1"]
        assert "Opóźnienie" in node["description"]
        origin = handoff["node_provenance"]["R1"]["node"]
        assert origin["slope"] == "minimum"
        assert origin["method"] == "lag"
        assert origin["method_reason"] == "flat"
        assert origin["length_km"] == r1["length_km"]
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
        assert peaks["OUT"] > 0
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

    def test_a_point_that_does_not_drain_to_a_is_named(self, client, run):
        body = {
            "outlet": point(run, "A", T2_MOUTH),
            "points": [point(run, "P1", T3_MOUTH)],
            "threshold_m2": NETWORK_SNAP_THRESHOLD_M2,
        }

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
            (lambda b: b["points"].clear(), "/body/points"),
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
            "no point",
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

    def test_the_outlet_id_defaults_to_a_and_counts_among_the_ids(self, client, run):
        body = at_the_mouths(run)
        del body["outlet"]["id"]
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
