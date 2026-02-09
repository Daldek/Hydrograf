"""
Integration tests for watershed delineation endpoint.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.main import app
from core.database import get_db


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_db_with_stream():
    """Mock database with stream data for successful delineation."""
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
    stream_result.cell_area = 25.0
    stream_result.is_stream = True
    stream_result.distance = 50.0

    # Mock traverse_upstream results (4 cells = 100 m² = 0.0001 km²)
    upstream_results = []
    for i in range(4):
        r = MagicMock()
        r.id = i + 1
        r.x = 639139.0 + i * 5
        r.y = 486706.0 + (i % 2) * 5
        r.elevation = 150.0 + i * 2
        r.flow_accumulation = 1000 - i * 250
        r.slope = 2.5
        r.downstream_id = i if i > 0 else None
        r.cell_area = 25.0
        r.is_stream = i == 0
        upstream_results.append(r)

    # Mock pre-flight check result (check_watershed_size)
    preflight_result = MagicMock()
    preflight_result.flow_accumulation = 3  # small watershed

    def execute_side_effect(query, params=None):
        result = MagicMock()
        query_str = str(query)
        if "is_stream = TRUE" in query_str:
            result.fetchone.return_value = stream_result
        elif "flow_accumulation FROM flow_network WHERE id" in query_str:
            result.fetchone.return_value = preflight_result
        elif "RECURSIVE upstream" in query_str:
            result.fetchall.return_value = upstream_results
        return result

    mock_session.execute.side_effect = execute_side_effect
    return mock_session


class TestDelineateWatershedEndpoint:
    """Tests for POST /api/delineate-watershed."""

    def test_success_returns_200(self, client, mock_db_with_stream):
        """Test successful delineation returns 200."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream

        response = client.post(
            "/api/delineate-watershed",
            json={"latitude": 52.23, "longitude": 21.01},
        )

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_response_structure(self, client, mock_db_with_stream):
        """Test response has correct structure."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream

        response = client.post(
            "/api/delineate-watershed",
            json={"latitude": 52.23, "longitude": 21.01},
        )

        data = response.json()
        assert "watershed" in data
        assert "boundary_geojson" in data["watershed"]
        assert "outlet" in data["watershed"]
        assert "cell_count" in data["watershed"]
        assert "area_km2" in data["watershed"]
        assert "hydrograph_available" in data["watershed"]

        app.dependency_overrides.clear()

    def test_outlet_info_structure(self, client, mock_db_with_stream):
        """Test outlet info has correct structure."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream

        response = client.post(
            "/api/delineate-watershed",
            json={"latitude": 52.23, "longitude": 21.01},
        )

        data = response.json()
        outlet = data["watershed"]["outlet"]

        assert "latitude" in outlet
        assert "longitude" in outlet
        assert "elevation_m" in outlet

        app.dependency_overrides.clear()

    def test_boundary_is_valid_geojson(self, client, mock_db_with_stream):
        """Test that boundary is valid GeoJSON."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream

        response = client.post(
            "/api/delineate-watershed",
            json={"latitude": 52.23, "longitude": 21.01},
        )

        data = response.json()
        geojson = data["watershed"]["boundary_geojson"]

        assert geojson["type"] == "Feature"
        assert "geometry" in geojson
        assert geojson["geometry"]["type"] == "Polygon"
        assert "coordinates" in geojson["geometry"]
        assert "properties" in geojson

        app.dependency_overrides.clear()

    def test_boundary_has_area_property(self, client, mock_db_with_stream):
        """Test that boundary GeoJSON has area property."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream

        response = client.post(
            "/api/delineate-watershed",
            json={"latitude": 52.23, "longitude": 21.01},
        )

        data = response.json()
        geojson = data["watershed"]["boundary_geojson"]

        assert "area_km2" in geojson["properties"]

        app.dependency_overrides.clear()

    def test_no_stream_returns_404(self, client):
        """Test that missing stream returns 404."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None
        app.dependency_overrides[get_db] = lambda: mock_session

        response = client.post(
            "/api/delineate-watershed",
            json={"latitude": 52.0, "longitude": 21.0},
        )

        assert response.status_code == 404
        assert "Nie znaleziono cieku" in response.json()["detail"]

        app.dependency_overrides.clear()

    def test_invalid_latitude_too_high_returns_422(self, client):
        """Test that latitude > 90 returns 422."""
        response = client.post(
            "/api/delineate-watershed",
            json={"latitude": 100.0, "longitude": 21.0},
        )

        assert response.status_code == 422

    def test_invalid_latitude_too_low_returns_422(self, client):
        """Test that latitude < -90 returns 422."""
        response = client.post(
            "/api/delineate-watershed",
            json={"latitude": -100.0, "longitude": 21.0},
        )

        assert response.status_code == 422

    def test_invalid_longitude_too_high_returns_422(self, client):
        """Test that longitude > 180 returns 422."""
        response = client.post(
            "/api/delineate-watershed",
            json={"latitude": 52.0, "longitude": 200.0},
        )

        assert response.status_code == 422

    def test_invalid_longitude_too_low_returns_422(self, client):
        """Test that longitude < -180 returns 422."""
        response = client.post(
            "/api/delineate-watershed",
            json={"latitude": 52.0, "longitude": -200.0},
        )

        assert response.status_code == 422

    def test_missing_latitude_returns_422(self, client):
        """Test that missing latitude returns 422."""
        response = client.post(
            "/api/delineate-watershed",
            json={"longitude": 21.0},
        )

        assert response.status_code == 422

    def test_missing_longitude_returns_422(self, client):
        """Test that missing longitude returns 422."""
        response = client.post(
            "/api/delineate-watershed",
            json={"latitude": 52.0},
        )

        assert response.status_code == 422

    def test_empty_body_returns_422(self, client):
        """Test that empty request body returns 422."""
        response = client.post(
            "/api/delineate-watershed",
            json={},
        )

        assert response.status_code == 422

    def test_small_watershed_hydrograph_available(self, client, mock_db_with_stream):
        """Test that small watershed has hydrograph_available=True."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream

        response = client.post(
            "/api/delineate-watershed",
            json={"latitude": 52.23, "longitude": 21.01},
        )

        data = response.json()
        # 4 cells * 25 m² = 100 m² = 0.0001 km² < 250 km²
        assert data["watershed"]["hydrograph_available"] is True

        app.dependency_overrides.clear()

    def test_large_watershed_hydrograph_unavailable(self, client):
        """Test that large watershed has hydrograph_available=False."""
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
        stream_result.cell_area = 1_000_000.0  # 1 km² per cell
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
            r.cell_area = 1_000_000.0  # 1 km² per cell
            r.is_stream = i == 0
            upstream_results.append(r)

        # Mock pre-flight check result (check_watershed_size)
        preflight_result = MagicMock()
        preflight_result.flow_accumulation = 299  # small enough to pass pre-flight

        def execute_side_effect(query, params=None):
            result = MagicMock()
            query_str = str(query)
            if "is_stream = TRUE" in query_str:
                result.fetchone.return_value = stream_result
            elif "flow_accumulation FROM flow_network WHERE id" in query_str:
                result.fetchone.return_value = preflight_result
            elif "RECURSIVE upstream" in query_str:
                result.fetchall.return_value = upstream_results
            return result

        mock_session.execute.side_effect = execute_side_effect
        app.dependency_overrides[get_db] = lambda: mock_session

        response = client.post(
            "/api/delineate-watershed",
            json={"latitude": 52.23, "longitude": 21.01},
        )

        data = response.json()
        # 300 cells * 1 km² = 300 km² > 250 km²
        assert data["watershed"]["hydrograph_available"] is False
        assert data["watershed"]["area_km2"] == 300.0

        app.dependency_overrides.clear()

    def test_cell_count_matches(self, client, mock_db_with_stream):
        """Test that cell_count matches number of cells."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream

        response = client.post(
            "/api/delineate-watershed",
            json={"latitude": 52.23, "longitude": 21.01},
        )

        data = response.json()
        assert data["watershed"]["cell_count"] == 4

        app.dependency_overrides.clear()

    def test_area_calculation_correct(self, client, mock_db_with_stream):
        """Test that area is calculated correctly."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_stream

        response = client.post(
            "/api/delineate-watershed",
            json={"latitude": 52.23, "longitude": 21.01},
        )

        data = response.json()
        # 4 cells * 25 m² = 100 m² = 0.0001 km²
        assert data["watershed"]["area_km2"] == 0.0

        app.dependency_overrides.clear()
