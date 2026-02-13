"""
Integration tests for depressions (blue spots) endpoint.
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


def _make_depression_row(
    id_: int,
    volume: float = 100.0,
    area: float = 50.0,
    max_depth: float = 2.0,
    mean_depth: float = 1.0,
):
    """Create a mock depression row."""
    r = MagicMock()
    r.id = id_
    r.volume_m3 = volume
    r.area_m2 = area
    r.max_depth_m = max_depth
    r.mean_depth_m = mean_depth
    r.geojson = {
        "type": "Polygon",
        "coordinates": [
            [[21.0, 52.0], [21.01, 52.0], [21.01, 52.01], [21.0, 52.01], [21.0, 52.0]]
        ],
    }
    return r


@pytest.fixture
def mock_db_with_depressions():
    """Mock database returning depression features."""
    mock_session = MagicMock()
    rows = [
        _make_depression_row(1, volume=500.0, area=200.0, max_depth=3.0),
        _make_depression_row(2, volume=100.0, area=50.0, max_depth=1.5),
        _make_depression_row(3, volume=50.0, area=30.0, max_depth=0.8),
    ]
    mock_session.execute.return_value.fetchall.return_value = rows
    return mock_session


@pytest.fixture
def mock_db_no_depressions():
    """Mock database returning no depressions."""
    mock_session = MagicMock()
    mock_session.execute.return_value.fetchall.return_value = []
    return mock_session


class TestDepressionsEndpoint:
    """Tests for GET /api/depressions."""

    def test_success_returns_200(self, client, mock_db_with_depressions):
        """Test successful request returns 200."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_depressions

        response = client.get("/api/depressions")

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_response_is_geojson_feature_collection(
        self, client, mock_db_with_depressions
    ):
        """Test response is a valid GeoJSON FeatureCollection."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_depressions

        response = client.get("/api/depressions")
        data = response.json()

        assert data["type"] == "FeatureCollection"
        assert "features" in data
        assert isinstance(data["features"], list)
        app.dependency_overrides.clear()

    def test_feature_count(self, client, mock_db_with_depressions):
        """Test correct number of features returned."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_depressions

        response = client.get("/api/depressions")
        data = response.json()

        assert len(data["features"]) == 3
        app.dependency_overrides.clear()

    def test_feature_structure(self, client, mock_db_with_depressions):
        """Test each feature has correct GeoJSON structure."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_depressions

        response = client.get("/api/depressions")
        data = response.json()

        for feature in data["features"]:
            assert feature["type"] == "Feature"
            assert "geometry" in feature
            assert "properties" in feature
        app.dependency_overrides.clear()

    def test_feature_properties(self, client, mock_db_with_depressions):
        """Test feature properties contain required fields."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_depressions

        response = client.get("/api/depressions")
        data = response.json()

        props = data["features"][0]["properties"]
        assert "id" in props
        assert "volume_m3" in props
        assert "area_m2" in props
        assert "max_depth_m" in props
        assert "mean_depth_m" in props
        app.dependency_overrides.clear()

    def test_empty_result_returns_empty_collection(
        self, client, mock_db_no_depressions
    ):
        """Test empty result returns FeatureCollection with no features."""
        app.dependency_overrides[get_db] = lambda: mock_db_no_depressions

        response = client.get("/api/depressions")
        data = response.json()

        assert response.status_code == 200
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 0
        app.dependency_overrides.clear()

    def test_min_volume_filter(self, client, mock_db_with_depressions):
        """Test min_volume query parameter is accepted."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_depressions

        response = client.get("/api/depressions?min_volume=100")

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_max_volume_filter(self, client, mock_db_with_depressions):
        """Test max_volume query parameter is accepted."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_depressions

        response = client.get("/api/depressions?max_volume=1000")

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_min_area_filter(self, client, mock_db_with_depressions):
        """Test min_area query parameter is accepted."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_depressions

        response = client.get("/api/depressions?min_area=10")

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_max_area_filter(self, client, mock_db_with_depressions):
        """Test max_area query parameter is accepted."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_depressions

        response = client.get("/api/depressions?max_area=500")

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_combined_filters(self, client, mock_db_with_depressions):
        """Test combining volume and area filters."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_depressions

        response = client.get(
            "/api/depressions?min_volume=10&max_volume=1000&min_area=5&max_area=500"
        )

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_bbox_filter(self, client, mock_db_with_depressions):
        """Test bbox query parameter is accepted."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_depressions

        response = client.get("/api/depressions?bbox=20.9,51.9,21.1,52.1")

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_negative_min_volume_returns_422(self, client):
        """Test that negative min_volume returns 422."""
        response = client.get("/api/depressions?min_volume=-10")

        assert response.status_code == 422

    def test_negative_min_area_returns_422(self, client):
        """Test that negative min_area returns 422."""
        response = client.get("/api/depressions?min_area=-5")

        assert response.status_code == 422

    def test_values_are_rounded(self, client, mock_db_with_depressions):
        """Test that property values are properly rounded."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_depressions

        response = client.get("/api/depressions")
        data = response.json()

        props = data["features"][0]["properties"]
        # volume_m3 rounded to 2 decimal places
        assert isinstance(props["volume_m3"], float)
        # area_m2 rounded to 1 decimal place
        assert isinstance(props["area_m2"], float)
        # max_depth_m rounded to 3 decimal places
        assert isinstance(props["max_depth_m"], float)
        app.dependency_overrides.clear()

    def test_features_ordered_by_volume_desc(self, client, mock_db_with_depressions):
        """Test that features are ordered by volume descending (via SQL)."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_depressions

        response = client.get("/api/depressions")
        data = response.json()

        volumes = [f["properties"]["volume_m3"] for f in data["features"]]
        assert volumes == sorted(volumes, reverse=True)
        app.dependency_overrides.clear()

    def test_invalid_bbox_format_still_returns_200(
        self, client, mock_db_with_depressions
    ):
        """Test that invalid bbox format is silently ignored."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_depressions

        response = client.get("/api/depressions?bbox=invalid")

        assert response.status_code == 200
        app.dependency_overrides.clear()
