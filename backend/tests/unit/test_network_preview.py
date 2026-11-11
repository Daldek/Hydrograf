"""The preview of a network against its full run, on a synthetic run (ADR-081).

process_dem runs over the main river with three tributaries of the network tests
(tests.fixtures.pipeline_run, river_network_dem) with sub-catchments of 1 ha and of
the 20 ha the points snap to; the catchment graph holds both, and a fake database
answers the queries of the measures and of the preview (the polygons of the
sub-catchments united by element, their stream lines). The preview must name every
element, reach and junction as the full run does, give the same areas and reach
lengths, and draw outlines that follow the elements of the full run.
"""

from typing import Any

import numpy as np
import pytest
import shapely
from fastapi.testclient import TestClient
from pyproj import Transformer
from shapely.geometry import shape
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
from utils.geometry import transform_pl1992_to_wgs84

FULL = "/api/delineate-network"
PREVIEW = "/api/delineate-network/preview"
OUTLET = (219, 85)  # A: the outlet cell of the grid, on the main river
# The last cell of each tributary above its confluence with the main river (row,
# column): a click there moves to the mouth
T3_MOUTH, T2_MOUTH, T1_MOUTH = (75, 86), (123, 86), (159, 84)
# A at the confluence of T1 and the main river, the cell below their last cells (T1's
# T1_MOUTH, the main river's 10 m above A), and a gauge 30 m above A on the main river
A_AT_T1, GAUGE_ABOVE_A = (160, 85), (157, 85)
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
    """A request of A at a cell and the points at theirs."""
    return {
        "outlet": point(run, "A", outlet, "Rzeka"),
        "points": [point(run, point_id, cell) for point_id, cell in points.items()],
        "threshold_m2": NETWORK_SNAP_THRESHOLD_M2,
    }


NETWORKS = {
    # Whole units only: every point moves to its mouth
    "at the mouths": (OUTLET, {"P1": T1_MOUTH, "P2": T2_MOUTH, "P3": T3_MOUTH}),
    # A gauge between two junctions, and two points in one unit of the main river,
    # which the full run splits into three parts
    "a gauge and two points in one unit": (
        OUTLET,
        {"P1": T1_MOUTH, "G": (140, 85), "P2": (99, 85), "P3": (102, 85)},
    ),
    # A inside its unit (its part below A lies outside the network), a point up a
    # tributary with a reach to its mouth
    "A inside its unit and a point up a tributary": (
        (190, 85),
        {"P1": (123, 110), "P2": T3_MOUTH},
    ),
    # A point 100 m up a tributary, beyond the mouth rule: a short reach to the
    # confluence, with the move of the point to its mouth
    "a point 100 m above its confluence": (
        OUTLET,
        {"P1": T1_MOUTH, "P2": (123, 96), "P3": T3_MOUTH},
    ),
    # No point at T1's mouth: P1 30 m above the mouth of T1a into T1's main river,
    # whose arm from the north is a headwater, as the upper Kaczawa of the author's
    # network of 2026-11-11
    "a point at the mouth of a tributary's tributary": (
        OUTLET,
        {"P1": (159, 47), "P2": T2_MOUTH, "P3": T3_MOUTH},
    ),
    # The author's network of 2026-11-11 (A at the confluence of the Nysa Szalona and
    # the Kaczawa, P1 7 m above it): the gauge moves to the mouth of the main river
    # and enters A with no reach, bringing P2's confluence; T1, with no point, enters
    # A as a dopływ of its own that holds A's own cells, which splits A's unit
    "A at a confluence and a gauge 30 m above it": (
        A_AT_T1,
        {"G": GAUGE_ABOVE_A, "P2": T2_MOUTH},
    ),
    # A point up T1 instead: its reach's przyrzecze ends at A's cell and holds A's
    # own cells
    "A at a confluence and a point up the other branch": (
        A_AT_T1,
        {"G": GAUGE_ABOVE_A, "P1": (159, 70)},
    ),
    # Both branches at their mouths: A's own cells are an element of their own
    "A at a confluence and both branches at their mouths": (
        A_AT_T1,
        {"G": GAUGE_ABOVE_A, "P1": T1_MOUTH},
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
        "points": [(p["id"], p["node"], p["at_mouth"]) for p in body["points"]],
        "subcatchments": [
            (s["id"], s["kind"], s["to"], s["point"], s["reach"])
            for s in body["subcatchments"]
        ],
        "reaches": [(r["id"], r["from"], r["to"]) for r in body["reaches"]],
        "junctions": [
            (j["id"], j["kind"], j["point"], j["inflows"]) for j in body["junctions"]
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


@pytest.mark.parametrize("network", NETWORKS.values(), ids=NETWORKS.keys())
class TestThePreviewIsTheNetworkOfTheFullRun:
    def test_it_names_the_elements_reaches_and_junctions_as_the_full_run(
        self, client, run, network
    ):
        full, preview = full_and_preview(client, request(run, network[0], **network[1]))

        assert structure(preview) == structure(full)

    def test_its_points_and_junctions_lie_where_the_full_run_puts_them(
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
            # A's cell heads its unit: P1's reach comes down T1 into it
            "A at a confluence and a point up the other branch",
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
        approximate = {
            s["point"] for s in preview["subcatchments"] if s["outline_approximate"]
        }
        assert {"G", "P2", "P3"} <= approximate
        assert "P1" not in approximate


class TestComposition:
    @pytest.mark.parametrize(
        ("outlet", "points"),
        [
            (OUTLET, {"P1": T1_MOUTH, "P7": (30, 5)}),
            (T2_MOUTH, {"P1": T3_MOUTH}),
            (OUTLET, {"P1": T1_MOUTH, "P4": (100, 85), "P5": (100, 85)}),
        ],
        ids=[
            "a point off the streams",
            "a point that does not drain to A",
            "points on one cell",
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
