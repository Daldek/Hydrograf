"""
Tests of the hand-off of a watershed to Hydrolog's GUI (nogat-handoff/1, ADR-068).

The hand-offs of POST /api/generate-hydrograph (fast path, PMAXTP lookup patched) and
of a delineated watershed validate against the vendored envelope and against the
network schema of the pinned Hydrolog, and Hydrolog's `hydrograph generate`, which
Hydrogram zlewni runs on an opened hand-off, recomputes the payload to the hand-off's
result: the comparison Hydrolog shows agrees. Nash by Lutz reopens as Lutz: Hydrolog's
`uh nash` estimates n and K from the watershed handed over to Hydrograf's values.
"""

import json
from importlib.resources import files
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from hydrolog.operations import hydrograph_generate, uh_nash
from jsonschema import Draft202012Validator

from api.endpoints.watershed import _watershed_handoff
from api.main import app
from core.database import get_db
from core.precipitation import DesignDepth
from models.schemas import MorphometricParameters, OutletInfo, WatershedResponse

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

# A PMAXTP depth with more decimals than the response's `precipitation` keeps
PMAXTP_MM = 73.123456789
POINT = {"latitude": 51.01544, "longitude": 15.88984}
OUTLET = {"latitude": 51.016785552617904, "longitude": 15.889229228459445}


def _morphometry() -> dict[str, Any]:
    """The Kamiennik above its mouth into the Kaczawa, as the delineation gives it."""
    return {
        "area_km2": 134.9683,
        "perimeter_km": 84.4609,
        "length_km": 22.2789,
        "elevation_min_m": 256.77,
        "elevation_max_m": 722.68,
        "elevation_mean_m": 418.93,
        "mean_slope_m_per_m": 0.135824,
        "channel_length_km": 21.3978,
        "channel_slope_m_per_m": 0.016872,
        "real_channel_length_km": 20.724,
        "cn": 69.6,
        "imperviousness": 0.067,
        "forest_pct": 47.9,
        "urban_pct": 2.5,
        "compactness_coefficient": 2.0509,
        "length_to_centroid_km": 13.6173,
        "hydraulic_length_km": 22.2789,
    }


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _post(client: TestClient, **options: Any):
    body: dict[str, Any] = {
        **POINT,
        "duration": "6h",
        "probability": 1,
        "morphometry": _morphometry(),
        **options,
    }
    depth = DesignDepth(PMAXTP_MM, "idw", ())
    with patch("api.endpoints.hydrograph.point_depth", return_value=depth):
        return client.post("/api/generate-hydrograph", json=body)


def _handoff(client: TestClient, **options: Any) -> dict[str, Any]:
    response = _post(client, **options)
    assert response.status_code == 200, response.text
    handoff: dict[str, Any] = response.json()["handoff"]
    return handoff


def _schema_problems(doc: dict[str, Any]) -> list[str]:
    problems = [
        f"envelope {e.json_path}: {e.message}" for e in ENVELOPE.iter_errors(doc)
    ]
    problems += [
        f"payload {e.json_path}: {e.message}"
        for e in NETWORK.iter_errors(doc["payload"])
    ]
    return problems


def _recompute(doc: dict[str, Any]) -> tuple[float, float, float]:
    """Hydrolog's `hydrograph generate` of the payload's subcatchment."""
    payload = doc["payload"]
    (subcatchment,) = [n for n in payload["nodes"] if n["type"] == "subcatchment"]
    options = {k: v for k, v in subcatchment["runoff"].items() if k != "model"}
    rainfall = subcatchment["rainfall"]
    if rainfall["kind"] == "series":
        options["values"] = rainfall["depths_mm"]
    else:
        options.update({k: v for k, v in rainfall.items() if k != "kind"})
    run = hydrograph_generate(
        watershed=subcatchment["watershed"],
        timestep_min=payload["timestep_min"],
        **options,
    ).result
    return run.peak_discharge_m3s, run.time_to_peak_min, run.total_volume_m3


class TestHydrographHandoff:
    @pytest.mark.parametrize(
        "options",
        [
            {"uh_model": "scs", "tc_method": "nrcs"},
            {
                "uh_model": "scs",
                "tc_method": "kirpich",
                "hietogram_type": "euler_ii",
                "amc": "III",
            },
            {
                "uh_model": "scs",
                "tc_method": "giandotti",
                "hietogram_type": "block",
                "amc": "I",
            },
            {
                "uh_model": "scs",
                "tc_method": "kerby_kirpich",
                "tc_retardance": 0.3,
                "hietogram_alpha": 3.5,
                "hietogram_beta": 2.0,
            },
            {"uh_model": "snyder", "snyder_ct": 1.4, "snyder_cp": 0.65},
            {"uh_model": "nash", "nash_estimation": "from_lutz"},
            {"uh_model": "nash", "nash_estimation": "from_urban_regression"},
            {
                "custom_precipitation": {
                    "timestep_min": 10,
                    "depths_mm": [5.0, 20.123, 15.5, 5.0, 0.0, 1.25],
                },
            },
        ],
        ids=[
            "scs-nrcs-beta",
            "scs-kirpich-euler-amc3",
            "scs-giandotti-block-amc1",
            "scs-kerby-kirpich-beta-shape",
            "snyder",
            "nash-lutz",
            "nash-urban",
            "own-series",
        ],
    )
    def test_hydrolog_recomputes_the_result_of_a_valid_handoff(self, client, options):
        doc = _handoff(client, **options)

        assert _schema_problems(doc) == []
        result = doc["result"]
        assert _recompute(doc) == (
            result["peak_discharge_m3s"],
            result["time_to_peak_min"],
            result["total_volume_m3"],
        )

    def test_pmaxtp_depth_comes_with_the_point_hydrolog_keeps_it_for(self, client):
        doc = _handoff(client, duration="12h", probability=0.5)

        rainfall = doc["payload"]["nodes"][0]["rainfall"]
        origin = doc["provenance"]["rainfall"]
        assert rainfall["total_mm"] == PMAXTP_MM
        assert origin == {
            "source": "pmaxtp",
            "method": "POT",
            "probability_percent": 0.5,
            "duration_min": rainfall["duration_min"],
            **POINT,
            "interpolation": "idw",
        }

    def test_own_series_is_the_users_rainfall(self, client):
        doc = _handoff(
            client,
            custom_precipitation={"timestep_min": 15, "depths_mm": [2.0, 8.0, 4.0]},
        )

        assert doc["provenance"]["rainfall"] == {"source": "user"}
        assert doc["payload"]["timestep_min"] == 15


class TestLutzHandoff:
    @pytest.mark.parametrize(
        ("shares", "used"),
        [
            ({"forest_pct": 47.9, "urban_pct": 2.5}, (47.9, 2.5)),
            ({}, (0.0, 0.0)),
        ],
        ids=["land-cover", "without-land-cover"],
    )
    def test_hydrologs_lutz_gives_hydrografs_n_and_k(self, client, shares, used):
        morphometry = _morphometry()
        del morphometry["forest_pct"], morphometry["urban_pct"]
        response = _post(
            client,
            uh_model="nash",
            nash_estimation="from_lutz",
            morphometry={**morphometry, **shares},
        )

        assert response.status_code == 200, response.text
        metadata = response.json()["metadata"]
        doc = response.json()["handoff"]
        watershed = doc["payload"]["nodes"][0]["watershed"]
        runoff = doc["payload"]["nodes"][0]["runoff"]
        assert (metadata["nash_forest_pct"], metadata["nash_urban_pct"]) == used
        assert (watershed["forest_pct"], watershed["urban_pct"]) == used
        assert watershed["manning_n"] == 0.035
        assert doc["provenance"]["runoff"] == {"source": "hydrograf", "method": "lutz"}
        # What Hydrolog's GUI runs when it opens Nash by Lutz (`uh nash`, lutzOptions)
        lutz = uh_nash(
            area_km2=watershed["area_km2"],
            lutz_length_km=watershed["channel_length_km"],
            lutz_centroid_length_km=watershed["Lc_km"],
            lutz_slope_m_per_m=watershed["channel_slope_m_per_m"],
            lutz_manning_n=watershed["manning_n"],
            lutz_forest_pct=watershed["forest_pct"],
            lutz_urban_pct=watershed["urban_pct"],
        ).parameters
        assert (lutz["n"], lutz["k_min"]) == (runoff["nash_n"], runoff["nash_k_min"])


class TestWatershedOrigin:
    def test_delineated_morphometry_names_the_outlet_and_the_changed_fields(
        self, client
    ):
        doc = _handoff(
            client,
            morphometry_origin={**OUTLET, "changed": ["cn", "length_to_centroid_km"]},
        )

        assert doc["provenance"]["watershed"] == {
            "source": "hydrograf",
            **OUTLET,
            "changed": ["cn", "Lc_km"],
        }
        assert doc["subject"] == "Zlewnia 51,01679° N, 15,88923° E"

    def test_morphometry_without_its_origin_is_the_users(self, client):
        doc = _handoff(client)

        assert doc["provenance"]["watershed"] == {"source": "user"}
        assert doc["subject"] == "Zlewnia 51,01544° N, 15,88984° E"

    def test_unknown_changed_field_is_refused(self, client):
        response = _post(
            client, morphometry_origin={**OUTLET, "changed": ["volume_m3"]}
        )

        assert response.status_code == 400
        (error,) = response.json()["errors"]
        assert error["pointer"] == "/body/morphometry_origin/changed"


class TestDelineatedWatershedHandoff:
    def test_watershed_without_rainfall_and_result(self):
        watershed = WatershedResponse(
            boundary_geojson={"type": "Feature", "geometry": None, "properties": {}},
            outlet=OutletInfo(**OUTLET, elevation_m=256.77),
            area_km2=134.97,
            hydrograph_available=True,
            morphometry=MorphometricParameters(**_morphometry()),
        )

        doc = _watershed_handoff(watershed)

        assert doc is not None
        assert _schema_problems(doc) == []
        assert "result" not in doc
        assert doc["provenance"] == {"watershed": {"source": "hydrograf", **OUTLET}}
        (subcatchment, outlet) = doc["payload"]["nodes"]
        assert outlet == {"id": "OUT", "type": "outlet", "from": ["Z1"]}
        assert "rainfall" not in subcatchment
        assert subcatchment["watershed"] == {
            "name": "Zlewnia 51,01679° N, 15,88923° E",
            "area_km2": 134.9683,
            "perimeter_km": 84.4609,
            "length_km": 22.2789,
            "elevation_min_m": 256.77,
            "elevation_max_m": 722.68,
            "elevation_mean_m": 418.93,
            "mean_slope_m_per_m": 0.135824,
            "channel_length_km": 21.3978,
            "channel_slope_m_per_m": 0.016872,
            "cn": 69.6,
            "Lc_km": 13.6173,
            "urban_pct": 2.5,
            "forest_pct": 47.9,
        }
