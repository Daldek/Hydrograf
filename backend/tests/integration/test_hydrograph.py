"""
Integration tests for hydrograph generation endpoint.

Tests the CatchmentGraph-based hydrograph endpoint by mocking:
- get_catchment_graph() -> CatchmentGraph with traverse/aggregate
- find_nearest_stream_segment() -> stream segment dict
- merge_catchment_boundaries() -> MultiPolygon boundary
- get_segment_outlet() -> outlet coordinates
- build_morph_dict_from_graph() -> morphometric dict for Hydrolog
- get_land_cover_for_boundary() -> None (default CN=75)
- DB session for precipitation query (IDW interpolation)
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import MultiPolygon, Polygon

from api.main import app
from core.database import get_db

# Module path for patching
_HG = "api.endpoints.hydrograph"


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_boundary() -> MultiPolygon:
    """Create a small MultiPolygon boundary (~10 km2) in PL-1992 coords."""
    # Approx 3.16 km x 3.16 km square -> ~10 km2
    poly = Polygon(
        [
            (639000, 486000),
            (642160, 486000),
            (642160, 489160),
            (639000, 489160),
            (639000, 486000),
        ]
    )
    return MultiPolygon([poly])


def _make_morph_dict(cn: int = 75) -> dict:
    """
    Build a morph dict compatible with WatershedParameters.from_dict()
    and MorphometricParameters schema.
    """
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
        "cn": cn,
        "source": "Hydrograf",
        "crs": "EPSG:2180",
        # Shape indices
        "compactness_coefficient": None,
        "circularity_ratio": None,
        "elongation_ratio": None,
        "form_factor": None,
        "mean_width_km": None,
        # Relief indices
        "relief_ratio": None,
        "hypsometric_integral": None,
        # Drainage network indices
        "drainage_density_km_per_km2": None,
        "stream_frequency_per_km2": None,
        "ruggedness_number": None,
        "max_strahler_order": None,
    }


def _make_mock_cg():
    """Create a mock CatchmentGraph with valid traversal results."""
    cg = MagicMock()
    cg.loaded = True
    cg.find_catchment_at_point.return_value = 0
    cg.traverse_upstream.return_value = np.array([0, 1, 2])
    cg.get_segment_indices.return_value = [10, 11, 12]
    cg.aggregate_stats.return_value = {
        "area_km2": 10.0,
        "elevation_min_m": 120.0,
        "elevation_max_m": 190.0,
        "elevation_mean_m": 155.0,
        "mean_slope_m_per_m": 0.04,
        "stream_length_km": 6.5,
        "drainage_density_km_per_km2": 0.65,
        "stream_frequency_per_km2": 0.3,
        "max_strahler_order": 3,
    }
    return cg


def _make_segment_dict() -> dict:
    """Return a segment dict as from find_nearest_stream_segment."""
    return {
        "segment_idx": 10,
        "strahler_order": 3,
        "length_m": 1200.0,
        "upstream_area_km2": 10.0,
        "downstream_x": 639139.0,
        "downstream_y": 486706.0,
    }


def _make_precip_db_mock():
    """
    Create a mock DB session that returns precipitation = 45.0 mm
    for any precipitation_data query.
    """
    mock_session = MagicMock()

    def execute_side_effect(query, params=None):
        result = MagicMock()
        query_str = str(query)
        if "precipitation_data" in query_str:
            precip = MagicMock()
            precip.precipitation_interpolated = 45.0
            result.fetchone.return_value = precip
        else:
            result.fetchone.return_value = None
            result.fetchall.return_value = []
        return result

    mock_session.execute.side_effect = execute_side_effect
    return mock_session


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Patch context manager for the "happy path" (successful generation)
# ---------------------------------------------------------------------------


def _patch_happy_path(cn: int = 75):
    """
    Return a stack of patches for a successful hydrograph generation.

    Patches all 6 external functions the endpoint calls, plus the
    DB override for precipitation.
    """
    boundary = _make_boundary()
    morph = _make_morph_dict(cn)
    mock_cg = _make_mock_cg()
    segment = _make_segment_dict()

    patches = {
        "cg": patch(f"{_HG}.get_catchment_graph", return_value=mock_cg),
        "seg": patch(f"{_HG}.find_nearest_stream_segment", return_value=segment),
        "merge": patch(f"{_HG}.merge_catchment_boundaries", return_value=boundary),
        "outlet": patch(
            f"{_HG}.get_segment_outlet",
            return_value={"x": 639139.0, "y": 486706.0},
        ),
        "morph": patch(f"{_HG}.build_morph_dict_from_graph", return_value=morph),
        "lc": patch(f"{_HG}.get_land_cover_for_boundary", return_value=None),
    }
    return patches


class _HappyPathContext:
    """Context manager that activates all happy-path patches at once."""

    def __init__(self, cn: int = 75):
        self._patches = _patch_happy_path(cn)
        self._mocks: dict[str, MagicMock] = {}

    def __enter__(self):
        for key, p in self._patches.items():
            self._mocks[key] = p.start()
        return self._mocks

    def __exit__(self, *args):
        for p in self._patches.values():
            p.stop()


# ---------------------------------------------------------------------------
# TestGenerateHydrographEndpoint
# ---------------------------------------------------------------------------


class TestGenerateHydrographEndpoint:
    """Tests for POST /api/generate-hydrograph."""

    # Default request payload used across most tests
    _DEFAULT_PAYLOAD = {
        "latitude": 52.23,
        "longitude": 21.01,
        "duration": "1h",
        "probability": 10,
    }

    def _post(self, client, payload=None):
        return client.post(
            "/api/generate-hydrograph",
            json=payload or self._DEFAULT_PAYLOAD,
        )

    # ---- 1. test_success_returns_200 ----

    def test_success_returns_200(self, client):
        """Test successful hydrograph generation returns 200."""
        mock_db = _make_precip_db_mock()
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with _HappyPathContext():
                response = self._post(client)
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()

    # ---- 2. test_response_structure ----

    def test_response_structure(self, client):
        """Test response has correct top-level keys."""
        mock_db = _make_precip_db_mock()
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with _HappyPathContext():
                response = self._post(client)

            data = response.json()
            assert "watershed" in data
            assert "precipitation" in data
            assert "hydrograph" in data
            assert "water_balance" in data
            assert "metadata" in data
        finally:
            app.dependency_overrides.clear()

    # ---- 3. test_hydrograph_data_structure ----

    def test_hydrograph_data_structure(self, client):
        """Test hydrograph data has correct structure."""
        mock_db = _make_precip_db_mock()
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with _HappyPathContext():
                response = self._post(client)

            data = response.json()
            hydro = data["hydrograph"]

            assert "times_min" in hydro
            assert "discharge_m3s" in hydro
            assert "peak_discharge_m3s" in hydro
            assert "time_to_peak_min" in hydro
            assert "total_volume_m3" in hydro

            assert len(hydro["times_min"]) > 0
            assert len(hydro["discharge_m3s"]) > 0
            assert hydro["peak_discharge_m3s"] > 0
            assert hydro["time_to_peak_min"] > 0
            assert hydro["total_volume_m3"] > 0
        finally:
            app.dependency_overrides.clear()

    # ---- 4. test_water_balance_structure ----

    def test_water_balance_structure(self, client):
        """Test water balance data has correct structure (CN=75 default)."""
        mock_db = _make_precip_db_mock()
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with _HappyPathContext():
                response = self._post(client)

            data = response.json()
            wb = data["water_balance"]

            assert "total_precip_mm" in wb
            assert "total_effective_mm" in wb
            assert "runoff_coefficient" in wb
            assert "cn_used" in wb
            assert "retention_mm" in wb
            assert "initial_abstraction_mm" in wb

            assert wb["cn_used"] == 75  # DEFAULT_CN
            assert 0 <= wb["runoff_coefficient"] <= 1
        finally:
            app.dependency_overrides.clear()

    # ---- 5. test_metadata_structure ----

    def test_metadata_structure(self, client):
        """Test metadata has correct structure and defaults."""
        mock_db = _make_precip_db_mock()
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with _HappyPathContext():
                response = self._post(client)

            data = response.json()
            meta = data["metadata"]

            assert "tc_min" in meta
            assert "tc_method" in meta
            assert "hietogram_type" in meta
            assert "uh_model" in meta

            assert meta["tc_min"] > 0
            assert meta["tc_method"] == "kirpich"
            assert meta["hietogram_type"] == "beta"
            assert meta["uh_model"] == "scs"
        finally:
            app.dependency_overrides.clear()

    # ---- 6. test_morphometry_in_response ----

    def test_morphometry_in_response(self, client):
        """Test that morphometry is included in watershed response."""
        mock_db = _make_precip_db_mock()
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with _HappyPathContext():
                response = self._post(client)

            data = response.json()
            morph = data["watershed"]["morphometry"]

            assert morph is not None
            assert morph["area_km2"] > 0
            assert morph["perimeter_km"] > 0
            assert morph["length_km"] > 0
            assert morph["elevation_min_m"] < morph["elevation_max_m"]
            assert morph["source"] == "Hydrograf"
            assert morph["crs"] == "EPSG:2180"
        finally:
            app.dependency_overrides.clear()

    # ---- 7. test_no_stream_returns_404 ----

    def test_no_stream_returns_404(self, client):
        """Test that missing stream returns 404."""
        mock_db = MagicMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_cg = MagicMock()
        mock_cg.loaded = True

        try:
            with (
                patch(f"{_HG}.get_catchment_graph", return_value=mock_cg),
                patch(f"{_HG}.find_nearest_stream_segment", return_value=None),
            ):
                response = self._post(
                    client,
                    {
                        "latitude": 52.0,
                        "longitude": 21.0,
                        "duration": "1h",
                        "probability": 10,
                    },
                )

            assert response.status_code == 404
            assert "ciek" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.clear()

    # ---- 8. test_area_too_large_returns_400 ----

    def test_area_too_large_returns_400(self, client):
        """Test that watershed > 250 km2 returns 400."""
        mock_db = MagicMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        # CatchmentGraph that reports 300 km2
        mock_cg = _make_mock_cg()
        mock_cg.aggregate_stats.return_value = {
            "area_km2": 300.0,
            "elevation_min_m": 100.0,
            "elevation_max_m": 250.0,
            "elevation_mean_m": 175.0,
            "mean_slope_m_per_m": 0.03,
            "stream_length_km": 20.0,
        }
        segment = _make_segment_dict()

        try:
            with (
                patch(f"{_HG}.get_catchment_graph", return_value=mock_cg),
                patch(f"{_HG}.find_nearest_stream_segment", return_value=segment),
            ):
                response = self._post(client)

            assert response.status_code == 400
            assert "250" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    # ---- 9. test_invalid_duration_returns_422 ----

    def test_invalid_duration_returns_422(self, client):
        """Test that invalid duration returns 422 (Pydantic validation)."""
        response = self._post(
            client,
            {
                "latitude": 52.23,
                "longitude": 21.01,
                "duration": "45min",  # Invalid
                "probability": 10,
            },
        )

        assert response.status_code == 422

    # ---- 10. test_invalid_probability_returns_400 ----

    def test_invalid_probability_returns_400(self, client):
        """Test that invalid probability returns 400."""
        mock_db = _make_precip_db_mock()
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with _HappyPathContext():
                response = self._post(
                    client,
                    {
                        "latitude": 52.23,
                        "longitude": 21.01,
                        "duration": "1h",
                        "probability": 15,  # Invalid (not in 1,2,5,10,20,50)
                    },
                )

            assert response.status_code == 400
        finally:
            app.dependency_overrides.clear()

    # ---- 11. test_valid_durations ----

    def test_valid_durations(self, client):
        """Test all valid duration values produce 200."""
        mock_db = _make_precip_db_mock()
        app.dependency_overrides[get_db] = lambda: mock_db

        valid_durations = ["15min", "30min", "1h", "2h", "6h", "12h", "24h"]

        try:
            with _HappyPathContext():
                for duration in valid_durations:
                    response = self._post(
                        client,
                        {
                            "latitude": 52.23,
                            "longitude": 21.01,
                            "duration": duration,
                            "probability": 10,
                        },
                    )
                    assert response.status_code == 200, (
                        f"Failed for duration={duration}"
                    )
        finally:
            app.dependency_overrides.clear()

    # ---- 12. test_valid_probabilities ----

    def test_valid_probabilities(self, client):
        """Test all valid probability values produce 200."""
        mock_db = _make_precip_db_mock()
        app.dependency_overrides[get_db] = lambda: mock_db

        valid_probabilities = [1, 2, 5, 10, 20, 50]

        try:
            with _HappyPathContext():
                for prob in valid_probabilities:
                    response = self._post(
                        client,
                        {
                            "latitude": 52.23,
                            "longitude": 21.01,
                            "duration": "1h",
                            "probability": prob,
                        },
                    )
                    assert response.status_code == 200, f"Failed for probability={prob}"
        finally:
            app.dependency_overrides.clear()

    # ---- 13. test_different_tc_methods ----

    def test_different_tc_methods(self, client):
        """Test different time of concentration methods."""
        mock_db = _make_precip_db_mock()
        app.dependency_overrides[get_db] = lambda: mock_db

        methods = ["kirpich", "scs_lag", "giandotti"]

        try:
            with _HappyPathContext():
                for method in methods:
                    response = self._post(
                        client,
                        {
                            "latitude": 52.23,
                            "longitude": 21.01,
                            "duration": "1h",
                            "probability": 10,
                            "tc_method": method,
                        },
                    )
                    assert response.status_code == 200, f"Failed for tc_method={method}"
                    assert response.json()["metadata"]["tc_method"] == method
        finally:
            app.dependency_overrides.clear()

    # ---- 14. test_different_hietogram_types ----

    def test_different_hietogram_types(self, client):
        """Test different hietogram types."""
        mock_db = _make_precip_db_mock()
        app.dependency_overrides[get_db] = lambda: mock_db

        types = ["beta", "block", "euler_ii"]

        try:
            with _HappyPathContext():
                for htype in types:
                    response = self._post(
                        client,
                        {
                            "latitude": 52.23,
                            "longitude": 21.01,
                            "duration": "1h",
                            "probability": 10,
                            "hietogram_type": htype,
                        },
                    )
                    assert response.status_code == 200, (
                        f"Failed for hietogram_type={htype}"
                    )
                    assert response.json()["metadata"]["hietogram_type"] == htype
        finally:
            app.dependency_overrides.clear()

    # ---- 15. test_custom_timestep ----

    def test_custom_timestep(self, client):
        """Test custom timestep parameter."""
        mock_db = _make_precip_db_mock()
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with _HappyPathContext():
                response = self._post(
                    client,
                    {
                        "latitude": 52.23,
                        "longitude": 21.01,
                        "duration": "1h",
                        "probability": 10,
                        "timestep_min": 10.0,
                    },
                )

            assert response.status_code == 200
            data = response.json()
            assert data["precipitation"]["timestep_min"] == 10.0
        finally:
            app.dependency_overrides.clear()

    # ---- 16. test_precipitation_info_structure ----

    def test_precipitation_info_structure(self, client):
        """Test precipitation info has correct structure and values."""
        mock_db = _make_precip_db_mock()
        app.dependency_overrides[get_db] = lambda: mock_db

        try:
            with _HappyPathContext():
                response = self._post(client)

            data = response.json()
            precip = data["precipitation"]

            assert precip["total_mm"] == 45.0  # Mocked value
            assert precip["duration_min"] == 60.0
            assert precip["probability_percent"] == 10
            assert precip["timestep_min"] == 5.0
            assert len(precip["times_min"]) > 0
            assert len(precip["intensities_mm"]) > 0
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# TestScenariosEndpoint (unchanged -- no DB or watershed dependency)
# ---------------------------------------------------------------------------


class TestScenariosEndpoint:
    """Tests for GET /api/scenarios endpoint."""

    def test_scenarios_returns_200(self, client):
        """Test scenarios endpoint returns 200."""
        response = client.get("/api/scenarios")
        assert response.status_code == 200

    def test_scenarios_response_structure(self, client):
        """Test scenarios response has correct structure."""
        response = client.get("/api/scenarios")
        data = response.json()

        assert "durations" in data
        assert "probabilities" in data
        assert "tc_methods" in data
        assert "hietogram_types" in data
        assert "area_limit_km2" in data

    def test_scenarios_valid_durations(self, client):
        """Test scenarios returns valid durations."""
        response = client.get("/api/scenarios")
        data = response.json()

        expected = ["12h", "15min", "1h", "24h", "2h", "30min", "6h"]
        assert data["durations"] == expected

    def test_scenarios_valid_probabilities(self, client):
        """Test scenarios returns valid probabilities."""
        response = client.get("/api/scenarios")
        data = response.json()

        expected = [1, 2, 5, 10, 20, 50]
        assert data["probabilities"] == expected

    def test_scenarios_area_limit(self, client):
        """Test scenarios returns area limit."""
        response = client.get("/api/scenarios")
        data = response.json()

        assert data["area_limit_km2"] == 250.0
