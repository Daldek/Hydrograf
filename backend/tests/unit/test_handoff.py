"""
Tests of the hand-off of a watershed to Hydrolog's GUI (nogat-handoff/1, ADR-068).

The hand-offs of POST /api/generate-hydrograph (fast path, PMAXTP lookup patched) and
of a delineated watershed validate against the vendored envelope and against the
network schema of the pinned Hydrolog, and Hydrolog's `hydrograph generate`, which
Hydrogram zlewni runs on an opened hand-off, recomputes the payload to the hand-off's
result: the comparison Hydrolog shows agrees. Nash by Lutz reopens as Lutz: Hydrolog's
`uh nash` estimates n and K from the watershed handed over to Hydrograf's values.
"""

import csv
import json
from importlib.resources import files
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from hydrolog.morphometry import WatershedParameters
from hydrolog.operations import hydrograph_generate, uh_nash
from jsonschema import Draft202012Validator

from api.endpoints.watershed import _watershed_handoff
from api.main import app
from core.attribution import (
    CHMU,
    CHMU_PROCESSED,
    CHMU_SOURCE,
    IMGW,
    IMGW_SOURCE,
    NO_PROVIDER,
    PMAXTP,
    ProviderLines,
)
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

# Files of `obserwator series export` of the pinned Obserwator 3.2.1, byte for byte
# (`--variables P --start 2024-09-10 --end 2024-09-20 --format csv`, 2026-11-25, from a
# data root of Obserwator 3.1.0): Kamienna Góra, IMGW-PIB station 250160150 of
# `pl.imgw.meteo_precip_daily`, and Žacléř, ČHMÚ 0-203-0-10102027001 of
# `cz.chmu.meteo_daily`, the rain of the flood of September 2024
EXPORTS = Path(__file__).resolve().parents[1] / "fixtures" / "obserwator"

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
        "flow_path_length_km": 22.2789,
        "flow_path_slope_m_per_m": 0.016038,
        "flow_path_equal_area_slope_m_per_m": 0.0084766,
        "overland_length_km": 0.2563,
        "overland_slope_m_per_m": 0.163324,
    }


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _post(client: TestClient, headers: dict[str, str] | None = None, **options: Any):
    body: dict[str, Any] = {
        **POINT,
        "duration": "6h",
        "probability": 1,
        "morphometry": _morphometry(),
        **options,
    }
    depth = DesignDepth(PMAXTP_MM, "idw", ())
    with patch("api.endpoints.hydrograph.point_depth", return_value=depth):
        return client.post("/api/generate-hydrograph", json=body, headers=headers)


def _series_of_export(name: str) -> dict[str, Any]:
    """An own series of a file of `EXPORTS` as the interface sends it.

    The column `P [mm]` day by day and the file's lines unchanged: one per cell of the
    columns `attribution` and `terms_notice`, a cell holding several joined by „\\n”.
    """
    with (EXPORTS / name).open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    return {
        "timestep_min": 1440,
        "depths_mm": [float(row["P [mm]"]) for row in rows],
        **{
            key: [line for row in rows for line in row[key].split("\n") if line]
            for key in ("attribution", "terms_notice")
        },
    }


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
            {"uh_model": "scs", "tc_method": "faa", "tc_runoff_coeff": 0.3},
            {"uh_model": "scs", "tc_method": "kerby", "tc_retardance": 0.4},
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
            "scs-faa",
            "scs-kerby",
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

    @pytest.mark.parametrize(
        ("options", "coefficients"),
        [
            ({"tc_method": "nrcs", "tc_runoff_coeff": 0.3}, {}),
            ({"tc_method": "faa", "tc_runoff_coeff": 0.3}, {"runoff_coeff": 0.3}),
            ({"tc_method": "kerby", "tc_retardance": 0.4}, {"retardance": 0.4}),
            (
                {"tc_method": "kerby_kirpich", "tc_retardance": 0.6},
                {"retardance": 0.6},
            ),
        ],
        ids=["nrcs", "faa", "kerby", "kerby-kirpich"],
    )
    def test_hydrolog_computes_tc_from_the_inputs_handed_off(
        self, client, options, coefficients
    ):
        doc = _handoff(client, uh_model="scs", **options)

        (subcatchment, _) = doc["payload"]["nodes"]
        watershed = subcatchment["watershed"]
        morphometry = _morphometry()
        for key in (
            "flow_path_length_km",
            "flow_path_slope_m_per_m",
            "overland_length_km",
            "overland_slope_m_per_m",
        ):
            assert watershed[key] == morphometry[key]
        # C or N only with the method that used it
        assert {
            key: watershed[key]
            for key in ("runoff_coeff", "retardance")
            if key in watershed
        } == coefficients
        # Hydrolog computes tc again by the method; Hydrograf's tc is the provenance's
        assert subcatchment["runoff"] == {
            "model": "curve-number",
            "tc_method": options["tc_method"],
            "amc": "II",
            "uh_model": "scs",
        }
        origin = doc["provenance"]["runoff"]
        assert origin["tc_method"] == options["tc_method"]
        assert origin["tc_min"] == WatershedParameters.from_dict(
            watershed
        ).calculate_tc(options["tc_method"])


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
            lutz_length_km=watershed["flow_path_length_km"],
            lutz_centroid_length_km=watershed["Lc_km"],
            lutz_slope_m_per_m=watershed["flow_path_equal_area_slope_m_per_m"],
            lutz_manning_n=watershed["manning_n"],
            lutz_forest_pct=watershed["forest_pct"],
            lutz_urban_pct=watershed["urban_pct"],
        ).result.parameters
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


class TestProviderLines:
    @pytest.mark.parametrize(
        ("options", "lines"),
        [
            ({}, PMAXTP),
            (
                {"custom_precipitation": {"timestep_min": 10, "depths_mm": [5.0, 2.0]}},
                NO_PROVIDER,
            ),
            (
                {
                    "custom_precipitation": {
                        "timestep_min": 10,
                        "depths_mm": [5.0, 2.0],
                        "derived_from": "pmaxtp",
                    }
                },
                PMAXTP,
            ),
        ],
        ids=["pmaxtp", "own-series", "own-series-copied-from-pmaxtp"],
    )
    def test_response_and_handoff_carry_the_lines_of_the_rainfall(
        self, client, options, lines
    ):
        response = _post(client, **options)

        assert response.status_code == 200, response.text
        data = response.json()
        assert (data["attribution"], data["terms_notice"]) == (
            list(lines.attribution),
            list(lines.terms_notice),
        )
        # The hand-off has the lines of the response; an envelope without any has no
        # field, as the copy of Nogat's schema wants at least one line
        doc = data["handoff"]
        assert (doc.get("attribution", []), doc.get("terms_notice", [])) == (
            list(lines.attribution),
            list(lines.terms_notice),
        )
        assert _schema_problems(doc) == []

    @pytest.mark.parametrize(
        ("export", "derived_from", "lines"),
        [
            ("kamienna-gora-P-2024-09.csv", "imgw", IMGW),
            ("zacler-P-2024-09.csv", "chmu", CHMU),
        ],
    )
    def test_a_series_of_obserwators_export_carries_its_providers_lines(
        self, client, export, derived_from, lines
    ):
        series = _series_of_export(export)
        response = _post(
            client, custom_precipitation={**series, "derived_from": derived_from}
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["precipitation"]["timestep_min"] == 1440
        # Every line of the file reaches the products (DEV-20.6), the processed
        # data's lines among them, from core/attribution.py
        assert set(series["attribution"]) <= set(data["attribution"])
        assert set(series["terms_notice"]) <= set(data["terms_notice"])
        assert (data["attribution"], data["terms_notice"]) == (
            list(lines.attribution),
            list(lines.terms_notice),
        )
        doc = data["handoff"]
        assert (doc.get("attribution", []), doc.get("terms_notice", [])) == (
            list(lines.attribution),
            list(lines.terms_notice),
        )
        assert _schema_problems(doc) == []

    def test_series_named_by_its_provider_alone_carries_its_lines(self, client):
        """A client without the file's lines names the data: the API adds theirs."""
        series = {
            "timestep_min": 1440,
            "depths_mm": [9.5, 70.0],
            "derived_from": "imgw",
        }
        data = _post(client, custom_precipitation=series).json()

        assert (data["attribution"], data["terms_notice"]) == (
            list(IMGW.attribution),
            list(IMGW.terms_notice),
        )

    def test_cp_as_written_before_eco_071_is_cp(self, client):
        old_cp = "Dane ČHMÚ zostały przetworzone (agregacja do sum dobowych)"
        series = {
            "timestep_min": 1440,
            "depths_mm": [18.2, 34.6],
            "derived_from": "chmu",
            "attribution": [CHMU_SOURCE, old_cp],
        }
        data = _post(client, custom_precipitation=series).json()

        assert data["attribution"] == [CHMU_SOURCE, CHMU_PROCESSED]

    @pytest.mark.parametrize(
        ("export", "derived_from", "line", "message"),
        [
            # ČHMÚ's export said to be of IMGW-PIB's archives
            ("zacler-P-2024-09.csv", "imgw", CHMU_SOURCE, "IMGW-PIB"),
            # The file's lines without the data they belong to
            ("kamienna-gora-P-2024-09.csv", None, IMGW_SOURCE, "bez derived_from"),
            # IMGW-PIB's archives are no PMAXTP data
            ("kamienna-gora-P-2024-09.csv", "pmaxtp", IMGW_SOURCE, "PMAXTP"),
        ],
    )
    def test_a_line_the_named_data_do_not_have_is_refused(
        self, client, export, derived_from, line, message
    ):
        series = {**_series_of_export(export), "derived_from": derived_from}
        response = _post(
            client, custom_precipitation=series, headers={"Accept-Language": "pl"}
        )

        assert response.status_code == 400
        problem = response.json()
        assert problem["code"] == "validation_error"
        assert problem["details"]["reason"] == "unknown_attribution_line"
        assert problem["details"]["line"] == line
        assert message in problem["detail"]

    @pytest.mark.parametrize(
        "changed",
        [
            # A line the standard retired (ECO-065): the terms are linked as RD
            {"terms_notice": ["Regulamin: https://danepubliczne.imgw.pl/regulations"]},
            # S written otherwise than byte for byte
            {"attribution": [IMGW_SOURCE.replace(" – ", " - ")]},
            # A text that is no line of any provider
            {"attribution": ["<b>Źródło: ktokolwiek</b>"]},
        ],
        ids=["retired-terms-line", "altered-source", "foreign-text"],
    )
    def test_a_line_altered_or_retired_is_refused(self, client, changed):
        series = {
            **_series_of_export("kamienna-gora-P-2024-09.csv"),
            "derived_from": "imgw",
            **changed,
        }
        response = _post(client, custom_precipitation=series)

        assert response.status_code == 400
        assert response.json()["details"]["reason"] == "unknown_attribution_line"


class TestDelineatedWatershedHandoff:
    def test_watershed_without_rainfall_and_result(self):
        watershed = WatershedResponse(
            boundary_geojson={"type": "Feature", "geometry": None, "properties": {}},
            outlet=OutletInfo(**OUTLET, elevation_m=256.77),
            area_km2=134.97,
            hydrograph_available=True,
            morphometry=MorphometricParameters(**_morphometry()),
        )

        lines = ProviderLines(attribution=("Źródło: GUGiK (test)",))
        doc = _watershed_handoff(watershed, lines)

        assert doc is not None
        assert _schema_problems(doc) == []
        assert "result" not in doc
        # The hand-off carries the lines of its response (DEV-20.6)
        assert doc["attribution"] == ["Źródło: GUGiK (test)"]
        assert "terms_notice" not in doc
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
            "overland_length_km": 0.2563,
            "overland_slope_m_per_m": 0.163324,
            "Lc_km": 13.6173,
            "urban_pct": 2.5,
            "forest_pct": 47.9,
            "flow_path_length_km": 22.2789,
            "flow_path_slope_m_per_m": 0.016038,
            "flow_path_equal_area_slope_m_per_m": 0.0084766,
        }


class TestHydrolog090Storms:
    """The design storms of Hydrolog 0.9.0: whole steps and Euler II from its curve."""

    def test_a_duration_that_is_not_a_whole_number_of_steps_is_refused(self, client):
        response = _post(client, duration="45min", timestep_min=10)

        assert response.status_code == 400
        problem = response.json()
        assert problem["code"] == "validation_error"
        assert problem["details"] == {
            "reason": "not_multiple",
            "duration_min": 45.0,
            "timestep_min": 10.0,
        }

    def test_euler_ii_needs_a_step_the_pmaxtp_curve_reaches(self, client):
        response = _post(
            client, duration="1h", timestep_min=2, hietogram_type="euler_ii"
        )

        assert response.status_code == 400
        assert response.json()["details"]["reason"] == "not_covered"

    def test_euler_ii_is_built_from_the_pmaxtp_curve_of_the_probability(self, client):
        doc = _handoff(client, hietogram_type="euler_ii", areal_reduction_factor=0.9)

        rainfall = doc["payload"]["nodes"][0]["rainfall"]
        curve = rainfall["depth_duration_mm"]
        # Every PMAXTP duration, reduced by the factor like the total h(D)
        assert list(curve) == [str(m) for m in sorted(map(int, curve))]
        assert len(curve) == 16
        assert curve["360"] == pytest.approx(PMAXTP_MM * 0.9)
        assert rainfall["total_mm"] == pytest.approx(curve["360"])
        assert "peak_position" not in rainfall

    def test_the_result_carries_the_versions_of_hydrologs_formulas(self, client):
        response = _post(
            client,
            uh_model="scs",
            tc_method="kirpich",
            hietogram_type="euler_ii",
            amc="III",
        )

        body = response.json()
        versions = body["formula_versions"]
        assert set(versions) == {
            "euler_ii_hyetograph",
            "idw_precipitation",
            "kirpich",
            "scs",
            "scs_cn_amc",
            "scs_cn_retention",
            "scs_cn_runoff",
            "uh_convolution",
        }
        computed_with = body["handoff"]["result"]["computed_with"]
        assert computed_with["formula_versions"] == versions
        assert computed_with["version"] == body["hydrolog_version"]
