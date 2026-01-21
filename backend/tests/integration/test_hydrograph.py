"""
Integration tests for hydrograph generation endpoint.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from api.main import app
from core.database import get_db


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_db_with_stream_and_precipitation():
    """Mock database with stream and precipitation data."""
    mock_session = MagicMock()

    # Mock find_nearest_stream query
    stream_result = MagicMock()
    stream_result.id = 1
    stream_result.x = 639139.0  # Warsaw area PL-1992
    stream_result.y = 486706.0
    stream_result.elevation = 150.0
    stream_result.flow_accumulation = 1000
    stream_result.slope = 2.5
    stream_result.downstream_id = None
    stream_result.cell_area = 1_000_000.0  # 1 km² per cell
    stream_result.is_stream = True
    stream_result.distance = 50.0

    # Mock traverse_upstream results (10 cells = 10 km² < 250 km² limit)
    upstream_results = []
    for i in range(10):
        r = MagicMock()
        r.id = i + 1
        r.x = 639139.0 + i * 500
        r.y = 486706.0 + (i % 3) * 500
        r.elevation = 150.0 + i * 10
        r.flow_accumulation = 1000 - i * 90
        r.slope = 2.5 + i * 0.5
        r.downstream_id = i if i > 0 else None
        r.cell_area = 1_000_000.0  # 1 km² per cell
        r.is_stream = i < 3
        upstream_results.append(r)

    # Mock precipitation query result (IDW interpolation)
    precip_result = MagicMock()
    precip_result.precipitation_interpolated = 45.0  # mm

    def execute_side_effect(query, params=None):
        result = MagicMock()
        query_str = str(query)

        if "is_stream = TRUE" in query_str:
            result.fetchone.return_value = stream_result
        elif "RECURSIVE upstream" in query_str:
            result.fetchall.return_value = upstream_results
        elif "precipitation_data" in query_str:
            result.fetchone.return_value = precip_result
        else:
            result.fetchone.return_value = None
            result.fetchall.return_value = []

        return result

    mock_session.execute.side_effect = execute_side_effect
    return mock_session


@pytest.fixture
def mock_db_large_watershed():
    """Mock database with large watershed (> 250 km²)."""
    mock_session = MagicMock()

    # Mock find_nearest_stream query
    stream_result = MagicMock()
    stream_result.id = 1
    stream_result.x = 639139.0
    stream_result.y = 486706.0
    stream_result.elevation = 150.0
    stream_result.flow_accumulation = 1000
    stream_result.slope = 2.5
    stream_result.downstream_id = None
    stream_result.cell_area = 1_000_000.0
    stream_result.is_stream = True
    stream_result.distance = 50.0

    # Create 300 cells = 300 km² > 250 km² limit
    upstream_results = []
    for i in range(300):
        r = MagicMock()
        r.id = i + 1
        r.x = 639139.0 + (i % 30) * 100
        r.y = 486706.0 + (i // 30) * 100
        r.elevation = 150.0 + i
        r.flow_accumulation = 1000 - i * 3
        r.slope = 2.5
        r.downstream_id = i if i > 0 else None
        r.cell_area = 1_000_000.0
        r.is_stream = i == 0
        upstream_results.append(r)

    def execute_side_effect(query, params=None):
        result = MagicMock()
        query_str = str(query)
        if "is_stream = TRUE" in query_str:
            result.fetchone.return_value = stream_result
        elif "RECURSIVE upstream" in query_str:
            result.fetchall.return_value = upstream_results
        return result

    mock_session.execute.side_effect = execute_side_effect
    return mock_session


class TestGenerateHydrographEndpoint:
    """Tests for POST /api/generate-hydrograph."""

    def test_success_returns_200(self, client, mock_db_with_stream_and_precipitation):
        """Test successful hydrograph generation returns 200."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream_and_precipitation

        response = client.post(
            "/api/generate-hydrograph",
            json={
                "latitude": 52.23,
                "longitude": 21.01,
                "duration": "1h",
                "probability": 10,
            },
        )

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_response_structure(self, client, mock_db_with_stream_and_precipitation):
        """Test response has correct structure."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream_and_precipitation

        response = client.post(
            "/api/generate-hydrograph",
            json={
                "latitude": 52.23,
                "longitude": 21.01,
                "duration": "1h",
                "probability": 10,
            },
        )

        data = response.json()
        assert "watershed" in data
        assert "precipitation" in data
        assert "hydrograph" in data
        assert "water_balance" in data
        assert "metadata" in data

        app.dependency_overrides.clear()

    def test_hydrograph_data_structure(
        self, client, mock_db_with_stream_and_precipitation
    ):
        """Test hydrograph data has correct structure."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream_and_precipitation

        response = client.post(
            "/api/generate-hydrograph",
            json={
                "latitude": 52.23,
                "longitude": 21.01,
                "duration": "1h",
                "probability": 10,
            },
        )

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

        app.dependency_overrides.clear()

    def test_water_balance_structure(
        self, client, mock_db_with_stream_and_precipitation
    ):
        """Test water balance data has correct structure."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream_and_precipitation

        response = client.post(
            "/api/generate-hydrograph",
            json={
                "latitude": 52.23,
                "longitude": 21.01,
                "duration": "1h",
                "probability": 10,
            },
        )

        data = response.json()
        wb = data["water_balance"]

        assert "total_precip_mm" in wb
        assert "total_effective_mm" in wb
        assert "runoff_coefficient" in wb
        assert "cn_used" in wb
        assert "retention_mm" in wb
        assert "initial_abstraction_mm" in wb

        assert wb["cn_used"] == 75  # Default CN
        assert 0 <= wb["runoff_coefficient"] <= 1

        app.dependency_overrides.clear()

    def test_metadata_structure(self, client, mock_db_with_stream_and_precipitation):
        """Test metadata has correct structure."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream_and_precipitation

        response = client.post(
            "/api/generate-hydrograph",
            json={
                "latitude": 52.23,
                "longitude": 21.01,
                "duration": "1h",
                "probability": 10,
            },
        )

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

        app.dependency_overrides.clear()

    def test_morphometry_in_response(
        self, client, mock_db_with_stream_and_precipitation
    ):
        """Test that morphometry is included in watershed response."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream_and_precipitation

        response = client.post(
            "/api/generate-hydrograph",
            json={
                "latitude": 52.23,
                "longitude": 21.01,
                "duration": "1h",
                "probability": 10,
            },
        )

        data = response.json()
        morph = data["watershed"]["morphometry"]

        assert morph is not None
        assert morph["area_km2"] > 0
        assert morph["perimeter_km"] > 0
        assert morph["length_km"] > 0
        assert morph["elevation_min_m"] < morph["elevation_max_m"]
        assert morph["source"] == "Hydrograf"
        assert morph["crs"] == "EPSG:2180"

        app.dependency_overrides.clear()

    def test_no_stream_returns_404(self, client):
        """Test that missing stream returns 404."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None
        app.dependency_overrides[get_db] = lambda: mock_session

        response = client.post(
            "/api/generate-hydrograph",
            json={
                "latitude": 52.0,
                "longitude": 21.0,
                "duration": "1h",
                "probability": 10,
            },
        )

        assert response.status_code == 404
        assert "ciek" in response.json()["detail"].lower()

        app.dependency_overrides.clear()

    def test_area_too_large_returns_400(self, client, mock_db_large_watershed):
        """Test that watershed > 250 km² returns 400."""
        app.dependency_overrides[get_db] = lambda: mock_db_large_watershed

        response = client.post(
            "/api/generate-hydrograph",
            json={
                "latitude": 52.23,
                "longitude": 21.01,
                "duration": "1h",
                "probability": 10,
            },
        )

        assert response.status_code == 400
        assert "250" in response.json()["detail"]

        app.dependency_overrides.clear()

    def test_invalid_duration_returns_422(self, client):
        """Test that invalid duration returns 422."""
        response = client.post(
            "/api/generate-hydrograph",
            json={
                "latitude": 52.23,
                "longitude": 21.01,
                "duration": "45min",  # Invalid
                "probability": 10,
            },
        )

        assert response.status_code == 422

    def test_invalid_probability_returns_400(
        self, client, mock_db_with_stream_and_precipitation
    ):
        """Test that invalid probability returns 400."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream_and_precipitation

        response = client.post(
            "/api/generate-hydrograph",
            json={
                "latitude": 52.23,
                "longitude": 21.01,
                "duration": "1h",
                "probability": 15,  # Invalid (not in 1,2,5,10,20,50)
            },
        )

        assert response.status_code == 400

        app.dependency_overrides.clear()

    def test_valid_durations(self, client, mock_db_with_stream_and_precipitation):
        """Test all valid duration values."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream_and_precipitation

        valid_durations = ["15min", "30min", "1h", "2h", "6h", "12h", "24h"]

        for duration in valid_durations:
            response = client.post(
                "/api/generate-hydrograph",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "duration": duration,
                    "probability": 10,
                },
            )

            assert response.status_code == 200, f"Failed for duration={duration}"

        app.dependency_overrides.clear()

    def test_valid_probabilities(self, client, mock_db_with_stream_and_precipitation):
        """Test all valid probability values."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream_and_precipitation

        valid_probabilities = [1, 2, 5, 10, 20, 50]

        for prob in valid_probabilities:
            response = client.post(
                "/api/generate-hydrograph",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "duration": "1h",
                    "probability": prob,
                },
            )

            assert response.status_code == 200, f"Failed for probability={prob}"

        app.dependency_overrides.clear()

    def test_different_tc_methods(self, client, mock_db_with_stream_and_precipitation):
        """Test different time of concentration methods."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream_and_precipitation

        methods = ["kirpich", "scs_lag", "giandotti"]

        for method in methods:
            response = client.post(
                "/api/generate-hydrograph",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "duration": "1h",
                    "probability": 10,
                    "tc_method": method,
                },
            )

            assert response.status_code == 200, f"Failed for tc_method={method}"
            assert response.json()["metadata"]["tc_method"] == method

        app.dependency_overrides.clear()

    def test_different_hietogram_types(
        self, client, mock_db_with_stream_and_precipitation
    ):
        """Test different hietogram types."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream_and_precipitation

        types = ["beta", "block", "euler_ii"]

        for htype in types:
            response = client.post(
                "/api/generate-hydrograph",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "duration": "1h",
                    "probability": 10,
                    "hietogram_type": htype,
                },
            )

            assert response.status_code == 200, f"Failed for hietogram_type={htype}"
            assert response.json()["metadata"]["hietogram_type"] == htype

        app.dependency_overrides.clear()

    def test_custom_timestep(self, client, mock_db_with_stream_and_precipitation):
        """Test custom timestep parameter."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream_and_precipitation

        response = client.post(
            "/api/generate-hydrograph",
            json={
                "latitude": 52.23,
                "longitude": 21.01,
                "duration": "1h",
                "probability": 10,
                "timestep_min": 10.0,
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Check that timestep is used in precipitation
        assert data["precipitation"]["timestep_min"] == 10.0

        app.dependency_overrides.clear()

    def test_precipitation_info_structure(
        self, client, mock_db_with_stream_and_precipitation
    ):
        """Test precipitation info has correct structure."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream_and_precipitation

        response = client.post(
            "/api/generate-hydrograph",
            json={
                "latitude": 52.23,
                "longitude": 21.01,
                "duration": "1h",
                "probability": 10,
            },
        )

        data = response.json()
        precip = data["precipitation"]

        assert precip["total_mm"] == 45.0  # Mocked value
        assert precip["duration_min"] == 60.0
        assert precip["probability_percent"] == 10
        assert precip["timestep_min"] == 5.0
        assert len(precip["times_min"]) > 0
        assert len(precip["intensities_mm"]) > 0

        app.dependency_overrides.clear()


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
