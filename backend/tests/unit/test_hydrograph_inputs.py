"""
Tests for hydrograph request options: AMC, fractional CN, own rainfall
series, and the public layer availability endpoint.

The fast path (pre-computed morphometry in the request) is used so no
watershed delineation is needed; PMAXTP lookup is patched.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.endpoints.hydrograph import _custom_hietogram
from api.main import app
from core.database import get_db
from models.schemas import (
    CUSTOM_PRECIPITATION_MAX_STEPS,
    CustomPrecipitation,
    HydrographRequest,
)

_HG = "api.endpoints.hydrograph"


def _morphometry(cn: float = 72.0) -> dict[str, Any]:
    return {
        "area_km2": 10.0,
        "perimeter_km": 20.0,
        "length_km": 5.0,
        "elevation_min_m": 120.0,
        "elevation_max_m": 190.0,
        "elevation_mean_m": 155.0,
        "mean_slope_m_per_m": 0.04,
        "channel_length_km": 6.5,
        "channel_slope_m_per_m": 0.0108,
        "length_to_centroid_km": 3.5,
        "imperviousness": 0.1,
        "cn": cn,
    }


def _request(**overrides) -> dict[str, Any]:
    body = {
        "latitude": 51.0,
        "longitude": 16.05,
        "duration": "1h",
        "probability": 10,
        "morphometry": _morphometry(),
    }
    body.update(overrides)
    return body


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def pmaxtp_45mm():
    with patch(f"{_HG}.get_precipitation", return_value=45.0) as mocked:
        yield mocked


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------


class TestCustomPrecipitationSchema:
    @pytest.mark.parametrize(
        ("payload", "fragment"),
        [
            ({"timestep_min": 10, "depths_mm": []}, "co najmniej jedną"),
            ({"timestep_min": 10, "depths_mm": [1.0, -0.5]}, "krok 2"),
            ({"timestep_min": 0, "depths_mm": [1.0]}, "większy od 0"),
            ({"timestep_min": -5, "depths_mm": [1.0]}, "większy od 0"),
            ({"timestep_min": 1441, "depths_mm": [1.0]}, "1440"),
            ({"timestep_min": 10, "depths_mm": [0.0, 0.0]}, "Suma opadu"),
            (
                {
                    "timestep_min": 1,
                    "depths_mm": [1.0] * (CUSTOM_PRECIPITATION_MAX_STEPS + 1),
                },
                "najwyżej",
            ),
        ],
    )
    def test_invalid_series_rejected_with_polish_message(self, payload, fragment):
        with pytest.raises(ValidationError) as exc:
            CustomPrecipitation(**payload)
        assert fragment in str(exc.value)

    def test_series_at_limits_accepted(self):
        series = CustomPrecipitation(
            timestep_min=0.5,
            depths_mm=[0.0] * (CUSTOM_PRECIPITATION_MAX_STEPS - 1) + [0.1],
        )
        assert len(series.depths_mm) == CUSTOM_PRECIPITATION_MAX_STEPS


class TestHydrographRequestSchema:
    def test_duration_and_probability_required_without_custom_series(self):
        with pytest.raises(ValidationError) as exc:
            HydrographRequest(latitude=51.0, longitude=16.0, duration="1h")
        assert "custom_precipitation" in str(exc.value)

    def test_custom_series_replaces_duration_and_probability(self):
        req = HydrographRequest(
            latitude=51.0,
            longitude=16.0,
            custom_precipitation={"timestep_min": 10, "depths_mm": [2.0, 5.0]},
        )
        assert req.duration is None
        assert req.probability is None

    def test_amc_defaults_to_ii_and_rejects_unknown(self):
        assert HydrographRequest(**_request()).amc == "II"
        with pytest.raises(ValidationError):
            HydrographRequest(**_request(amc="IV"))

    def test_morphometry_accepts_fractional_cn(self):
        req = HydrographRequest(**_request(morphometry=_morphometry(cn=72.5)))
        assert req.morphometry.cn == 72.5


def test_custom_hietogram_uses_interval_end_times():
    result = _custom_hietogram([1.0, 4.0, 2.5], 10.0)
    assert result.times_min.tolist() == [10.0, 20.0, 30.0]
    assert result.total_mm == pytest.approx(7.5)
    assert result.duration_min == 30.0
    assert result.timestep_min == 10.0


# ---------------------------------------------------------------------------
# Endpoint behaviour
# ---------------------------------------------------------------------------


def _post(client, body) -> dict[str, Any]:
    response = client.post("/api/generate-hydrograph", json=body)
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


class TestAmc:
    def test_amc_changes_cn_and_effective_rainfall(self, client, pmaxtp_45mm):
        results = {amc: _post(client, _request(amc=amc)) for amc in ("I", "II", "III")}
        cn = {amc: r["water_balance"]["cn_used"] for amc, r in results.items()}
        pe = {
            amc: r["water_balance"]["total_effective_mm"] for amc, r in results.items()
        }

        assert cn["II"] == 72.0
        assert cn["I"] < cn["II"] < cn["III"]
        assert pe["I"] < pe["II"] < pe["III"]
        for amc, r in results.items():
            assert r["metadata"]["amc"] == amc

    def test_nash_urban_regression_uses_amc_adjusted_cn(self, client, pmaxtp_45mm):
        data = _post(
            client,
            _request(
                amc="III",
                uh_model="nash",
                nash_estimation="from_urban_regression",
            ),
        )
        # The regression input must be the event's effective rainfall
        assert data["metadata"]["nash_effective_precip_mm"] == pytest.approx(
            data["water_balance"]["total_effective_mm"], abs=0.01
        )


def test_fractional_cn_is_used_as_given(client, pmaxtp_45mm):
    data = _post(client, _request(morphometry=_morphometry(cn=72.5)))
    assert data["water_balance"]["cn_used"] == 72.5
    # S = 25400 / CN - 254
    assert data["water_balance"]["retention_mm"] == pytest.approx(
        25400 / 72.5 - 254, abs=0.01
    )


class TestAreaLimit:
    """The SCS-CN limit holds for a catchment given in ``morphometry`` too."""

    def _area(self, area_km2: float) -> dict[str, Any]:
        morphometry = _morphometry()
        morphometry["area_km2"] = area_km2
        return _request(morphometry=morphometry)

    def test_area_above_the_published_limit_is_unsupported(self, client, pmaxtp_45mm):
        limit = client.get("/api/scenarios").json()["area_limit_km2"]

        response = client.post(
            "/api/generate-hydrograph", json=self._area(limit + 0.01)
        )

        assert response.status_code == 422
        problem = response.json()
        assert problem["code"] == "unsupported"
        assert problem["details"]["reason"] == "area_exceeds_limit"
        assert problem["details"]["limit_km2"] == limit

    def test_area_at_the_limit_is_computed(self, client, pmaxtp_45mm):
        limit = client.get("/api/scenarios").json()["area_limit_km2"]

        data = _post(client, self._area(limit))

        assert data["hydrograph"]["peak_discharge_m3s"] > 0


class TestCustomPrecipitation:
    def test_series_replaces_pmaxtp(self, client, pmaxtp_45mm):
        depths = [1.5, 4.0, 12.5, 20.0, 8.0]
        data = _post(
            client,
            _request(
                duration=None,
                probability=None,
                custom_precipitation={"timestep_min": 10, "depths_mm": depths},
            ),
        )
        precip = data["precipitation"]

        pmaxtp_45mm.assert_not_called()
        assert precip["source"] == "custom"
        assert precip["probability_percent"] is None
        assert precip["total_mm"] == pytest.approx(sum(depths))
        assert precip["duration_min"] == 50.0
        assert precip["timestep_min"] == 10.0
        assert precip["times_min"] == [10.0, 20.0, 30.0, 40.0, 50.0]
        assert precip["intensities_mm"] == depths
        assert data["water_balance"]["total_precip_mm"] == pytest.approx(sum(depths))
        assert data["metadata"]["hietogram_type"] is None
        # The hydrograph runs on the series' own timestep
        times = data["hydrograph"]["times_min"]
        assert times[1] - times[0] == pytest.approx(10.0)

    def test_series_takes_precedence_over_duration(self, client, pmaxtp_45mm):
        data = _post(
            client,
            _request(
                custom_precipitation={"timestep_min": 5, "depths_mm": [10.0, 30.0]},
            ),
        )
        pmaxtp_45mm.assert_not_called()
        assert data["precipitation"]["source"] == "custom"
        assert data["precipitation"]["total_mm"] == 40.0

    def test_pmaxtp_response_reports_source_and_probability(self, client, pmaxtp_45mm):
        precip = _post(client, _request())["precipitation"]
        assert precip["source"] == "pmaxtp"
        assert precip["probability_percent"] == 10
        assert precip["total_mm"] == 45.0

    def test_invalid_series_returns_400_with_polish_message(self, client, pmaxtp_45mm):
        response = client.post(
            "/api/generate-hydrograph",
            json=_request(
                custom_precipitation={"timestep_min": 10, "depths_mm": [1.0, -2.0]}
            ),
        )
        assert response.status_code == 400
        problem = response.json()
        assert problem["code"] == "validation_error"
        assert problem["details"]["fields"] == ["/body/custom_precipitation/depths_mm"]
        assert "nieujemną" in problem["errors"][0]["message"]


class TestNashEstimation:
    def test_estimation_from_tc_is_refused_with_the_allowed_methods(self, client):
        response = client.post(
            "/api/generate-hydrograph",
            json=_request(uh_model="nash", nash_estimation="from_tc"),
        )
        assert response.status_code == 400
        problem = response.json()
        assert problem["code"] == "validation_error"
        assert problem["details"]["fields"] == ["/body/nash_estimation"]
        assert problem["errors"][0]["message"] == (
            "Input should be 'from_lutz' or 'from_urban_regression'"
        )


# ---------------------------------------------------------------------------
# Layer availability
# ---------------------------------------------------------------------------


class TestLayerAvailability:
    def _client_with_db(self, db):
        app.dependency_overrides[get_db] = lambda: db
        return TestClient(app)

    def teardown_method(self):
        app.dependency_overrides.clear()

    @pytest.mark.parametrize("exists", [True, False])
    def test_reports_sewer_presence(self, exists):
        db = MagicMock()
        db.execute.return_value.scalar.return_value = exists
        response = self._client_with_db(db).get("/api/layers")
        assert response.status_code == 200
        assert response.json() == {"sewer": exists}

    def test_query_failure_reports_no_sewer(self):
        db = MagicMock()
        db.execute.side_effect = RuntimeError("relation does not exist")
        response = self._client_with_db(db).get("/api/layers")
        assert response.status_code == 200
        assert response.json() == {"sewer": False}
        db.rollback.assert_called_once()
