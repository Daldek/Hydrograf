"""
Time of concentration of POST /api/generate-hydrograph (Nogat plan
2026-11-05-official-tc-inputs, D5).

Hydrolog computes every method from the inputs its source defines: the endpoint's tc
is ``WatershedParameters.calculate_tc`` of the morphometry, the CN used and FAA's C or
Kerby's N of the request, and a missing input is a 400 that names it, never a
substitute.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from hydrolog.morphometry import WatershedParameters
from pydantic import ValidationError

from api.main import app
from core.database import get_db
from core.precipitation import DesignDepth
from models.schemas import HydrographRequest

POINT = {"latitude": 51.01544, "longitude": 15.88984}


def _morphometry() -> dict[str, Any]:
    """The Kamiennik above its mouth into the Kaczawa, with its flow path (ADR-070)."""
    return {
        "area_km2": 134.97,
        "perimeter_km": 84.4609,
        "length_km": 22.2789,
        "elevation_min_m": 256.77,
        "elevation_max_m": 722.68,
        "elevation_mean_m": 418.93,
        "mean_slope_m_per_m": 0.135822,
        "channel_length_km": 21.7949,
        "channel_slope_m_per_m": 0.014959,
        "real_channel_length_km": 20.686,
        "hydraulic_length_km": 22.2789,
        "flow_path_length_km": 22.2789,
        "flow_path_slope_m_per_m": 0.016038,
        "overland_length_km": 0.2563,
        "overland_slope_m_per_m": 0.163324,
        "length_to_centroid_km": 13.6173,
        "cn": 69.6,
    }


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _post(client: TestClient, morphometry: dict[str, Any], **options: Any):
    body = {
        **POINT,
        "duration": "6h",
        "probability": 1,
        "uh_model": "scs",
        "morphometry": morphometry,
        **options,
    }
    depth = DesignDepth(70.0, "idw", ())
    with patch("api.endpoints.hydrograph.point_depth", return_value=depth):
        return client.post(
            "/api/generate-hydrograph", json=body, headers={"Accept-Language": "pl"}
        )


class TestTcIsHydrologs:
    @pytest.mark.parametrize(
        ("options", "coefficients"),
        [
            ({"tc_method": "kirpich"}, {}),
            ({"tc_method": "nrcs"}, {}),
            ({"tc_method": "giandotti"}, {}),
            ({"tc_method": "faa", "tc_runoff_coeff": 0.3}, {"runoff_coeff": 0.3}),
            ({"tc_method": "kerby", "tc_retardance": 0.4}, {"retardance": 0.4}),
            (
                {"tc_method": "kerby_kirpich", "tc_retardance": 0.6},
                {"retardance": 0.6},
            ),
        ],
        ids=["kirpich", "nrcs", "giandotti", "faa", "kerby", "kerby-kirpich"],
    )
    def test_tc_is_calculate_tc_of_the_same_inputs(self, client, options, coefficients):
        response = _post(client, _morphometry(), **options)

        assert response.status_code == 200, response.text
        expected = WatershedParameters.from_dict(
            {**_morphometry(), **coefficients}
        ).calculate_tc(options["tc_method"])
        origin = response.json()["handoff"]["provenance"]["runoff"]
        assert origin["tc_min"] == expected
        assert response.json()["metadata"]["tc_min"] == round(expected, 1)

    def test_a_given_coefficient_another_method_does_not_read_is_ignored(self, client):
        response = _post(client, _morphometry(), tc_method="nrcs", tc_runoff_coeff=0.9)

        assert response.status_code == 200, response.text
        expected = WatershedParameters.from_dict(_morphometry()).calculate_tc("nrcs")
        assert response.json()["handoff"]["provenance"]["runoff"]["tc_min"] == expected


class TestMissingInput:
    @pytest.mark.parametrize(
        ("method", "options", "dropped", "missing"),
        [
            # C is not derived from CN
            ("faa", {}, (), ["tc_runoff_coeff"]),
            # N has no default
            ("kerby", {}, (), ["tc_retardance"]),
            # The overland slope is not the mean slope
            ("kerby", {"tc_retardance": 0.4}, ("overland_slope_m_per_m",), None),
            # Kirpich's slope is not the channel slope
            ("kirpich", {}, ("flow_path_slope_m_per_m",), None),
            # NRCS's length is not the hydraulic length under another name
            ("nrcs", {}, ("flow_path_length_km",), None),
            (
                "kerby_kirpich",
                {"tc_retardance": 0.4},
                ("overland_length_km", "flow_path_slope_m_per_m"),
                None,
            ),
        ],
        ids=[
            "faa-c",
            "kerby-n",
            "kerby-overland-slope",
            "kirpich-flow-path-slope",
            "nrcs-flow-path-length",
            "kerby-kirpich-overland-and-flow-path",
        ],
    )
    def test_missing_input_is_a_polish_400_naming_it(
        self, client, method, options, dropped, missing
    ):
        morphometry = _morphometry()
        for key in dropped:
            del morphometry[key]
        missing = missing or list(dropped)

        response = _post(client, morphometry, tc_method=method, **options)

        assert response.status_code == 400
        problem = response.json()
        assert problem["code"] == "validation_error"
        assert problem["details"] == {
            "reason": "missing_field",
            "method": method,
            "missing": missing,
        }
        assert problem["detail"] == (
            f"Czas koncentracji metodą {method} wymaga: {', '.join(missing)}."
        )

    def test_flow_path_not_longer_than_the_overland_segment_is_refused(self, client):
        morphometry = {**_morphometry(), "overland_length_km": 25.0}

        response = _post(
            client, morphometry, tc_method="kerby_kirpich", tc_retardance=0.4
        )

        assert response.status_code == 400
        assert response.json()["details"]["reason"] == "invalid_parameters"


class TestTcOptionsInSchema:
    @pytest.mark.parametrize("method", ["faa", "kerby", "kerby_kirpich"])
    def test_accepts_the_method(self, method):
        req = HydrographRequest(
            **POINT, duration="1h", probability=10, tc_method=method
        )
        assert req.tc_method == method
        assert (req.tc_runoff_coeff, req.tc_retardance) == (None, None)

    def test_rejects_invalid_tc_method(self):
        with pytest.raises(ValidationError):
            HydrographRequest(
                **POINT, duration="1h", probability=10, tc_method="invalid_method"
            )

    @pytest.mark.parametrize(
        ("value", "valid"), [(0.0, False), (0.01, True), (1.0, True), (1.01, False)]
    )
    def test_runoff_coeff_is_above_0_and_at_most_1(self, value, valid):
        if valid:
            req = HydrographRequest(
                **POINT, duration="1h", probability=10, tc_runoff_coeff=value
            )
            assert req.tc_runoff_coeff == value
        else:
            with pytest.raises(ValidationError):
                HydrographRequest(
                    **POINT, duration="1h", probability=10, tc_runoff_coeff=value
                )
