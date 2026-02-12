"""
Integration tests for terrain profile endpoint.
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
def mock_db_with_profile():
    """Mock database returning elevation profile data."""
    mock_session = MagicMock()

    # Simulate 5 sample points along a line
    profile_rows = []
    for i in range(5):
        r = MagicMock()
        r.idx = i
        r.distance_m = i * 250.0
        r.elevation_m = 150.0 + i * 5.0
        profile_rows.append(r)

    mock_session.execute.return_value.fetchall.return_value = profile_rows
    return mock_session


@pytest.fixture
def mock_db_empty():
    """Mock database returning no profile data."""
    mock_session = MagicMock()
    mock_session.execute.return_value.fetchall.return_value = []
    return mock_session


class TestTerrainProfileEndpoint:
    """Tests for POST /api/terrain-profile."""

    def test_success_returns_200(self, client, mock_db_with_profile):
        """Test successful profile extraction returns 200."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_profile

        response = client.post(
            "/api/terrain-profile",
            json={
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[21.0, 52.0], [21.01, 52.01]],
                },
                "n_samples": 5,
            },
        )

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_response_structure(self, client, mock_db_with_profile):
        """Test response has correct structure."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_profile

        response = client.post(
            "/api/terrain-profile",
            json={
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[21.0, 52.0], [21.01, 52.01]],
                },
                "n_samples": 5,
            },
        )

        data = response.json()
        assert "distances_m" in data
        assert "elevations_m" in data
        assert "total_length_m" in data
        app.dependency_overrides.clear()

    def test_distances_and_elevations_lengths_match(self, client, mock_db_with_profile):
        """Test that distances and elevations arrays have same length."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_profile

        response = client.post(
            "/api/terrain-profile",
            json={
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[21.0, 52.0], [21.01, 52.01]],
                },
                "n_samples": 5,
            },
        )

        data = response.json()
        assert len(data["distances_m"]) == len(data["elevations_m"])
        assert len(data["distances_m"]) == 5
        app.dependency_overrides.clear()

    def test_total_length_equals_last_distance(self, client, mock_db_with_profile):
        """Test that total_length_m equals the last distance value."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_profile

        response = client.post(
            "/api/terrain-profile",
            json={
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[21.0, 52.0], [21.01, 52.01]],
                },
                "n_samples": 5,
            },
        )

        data = response.json()
        assert data["total_length_m"] == data["distances_m"][-1]
        app.dependency_overrides.clear()

    def test_elevations_are_floats(self, client, mock_db_with_profile):
        """Test that elevation values are numeric."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_profile

        response = client.post(
            "/api/terrain-profile",
            json={
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[21.0, 52.0], [21.01, 52.01]],
                },
                "n_samples": 5,
            },
        )

        data = response.json()
        for elev in data["elevations_m"]:
            assert isinstance(elev, float)
        app.dependency_overrides.clear()

    def test_non_linestring_returns_400(self, client, mock_db_with_profile):
        """Test that non-LineString geometry returns 400."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_profile

        response = client.post(
            "/api/terrain-profile",
            json={
                "geometry": {
                    "type": "Point",
                    "coordinates": [21.0, 52.0],
                },
                "n_samples": 5,
            },
        )

        assert response.status_code == 400
        assert "LineString" in response.json()["detail"]
        app.dependency_overrides.clear()

    def test_too_few_coordinates_returns_400(self, client, mock_db_with_profile):
        """Test that LineString with < 2 coordinates returns 400."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_profile

        response = client.post(
            "/api/terrain-profile",
            json={
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[21.0, 52.0]],
                },
                "n_samples": 5,
            },
        )

        assert response.status_code == 400
        assert "2 coordinates" in response.json()["detail"]
        app.dependency_overrides.clear()

    def test_empty_result_returns_404(self, client, mock_db_empty):
        """Test that empty profile result returns 404."""
        app.dependency_overrides[get_db] = lambda: mock_db_empty

        response = client.post(
            "/api/terrain-profile",
            json={
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[21.0, 52.0], [21.01, 52.01]],
                },
                "n_samples": 5,
            },
        )

        assert response.status_code == 404
        app.dependency_overrides.clear()

    def test_n_samples_too_low_returns_422(self, client):
        """Test that n_samples < 2 returns 422."""
        response = client.post(
            "/api/terrain-profile",
            json={
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[21.0, 52.0], [21.01, 52.01]],
                },
                "n_samples": 1,
            },
        )

        assert response.status_code == 422

    def test_n_samples_too_high_returns_422(self, client):
        """Test that n_samples > 1000 returns 422."""
        response = client.post(
            "/api/terrain-profile",
            json={
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[21.0, 52.0], [21.01, 52.01]],
                },
                "n_samples": 1001,
            },
        )

        assert response.status_code == 422

    def test_missing_geometry_returns_422(self, client):
        """Test that missing geometry returns 422."""
        response = client.post(
            "/api/terrain-profile",
            json={"n_samples": 5},
        )

        assert response.status_code == 422

    def test_default_n_samples(self, client, mock_db_with_profile):
        """Test that default n_samples is used when not specified."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_profile

        response = client.post(
            "/api/terrain-profile",
            json={
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[21.0, 52.0], [21.01, 52.01]],
                },
            },
        )

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_multi_point_linestring(self, client, mock_db_with_profile):
        """Test profile with multi-point LineString geometry."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_profile

        response = client.post(
            "/api/terrain-profile",
            json={
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [21.0, 52.0],
                        [21.005, 52.005],
                        [21.01, 52.01],
                        [21.015, 52.005],
                    ],
                },
                "n_samples": 5,
            },
        )

        assert response.status_code == 200
        app.dependency_overrides.clear()
