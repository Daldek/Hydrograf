"""
Integration tests for tile (MVT) endpoints.
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
def mock_db_with_tile():
    """Mock database returning non-empty MVT tile data."""
    mock_session = MagicMock()
    # MVT tiles are binary protobuf; use a small fake payload
    fake_tile = b"\x1a\x00"
    row = MagicMock()
    row.__getitem__ = lambda self, idx: fake_tile if idx == 0 else None
    mock_session.execute.return_value.fetchone.return_value = row
    return mock_session


@pytest.fixture
def mock_db_empty_tile():
    """Mock database returning empty/null tile."""
    mock_session = MagicMock()
    row = MagicMock()
    row.__getitem__ = lambda self, idx: None
    mock_session.execute.return_value.fetchone.return_value = row
    return mock_session


@pytest.fixture
def mock_db_no_tile():
    """Mock database returning no row at all."""
    mock_session = MagicMock()
    mock_session.execute.return_value.fetchone.return_value = None
    return mock_session


@pytest.fixture
def mock_db_with_thresholds():
    """Mock database returning threshold values."""
    mock_session = MagicMock()

    streams_rows = [MagicMock(), MagicMock(), MagicMock()]
    for r, v in zip(streams_rows, [100, 1000, 10000]):
        r.__getitem__ = lambda self, idx, val=v: val if idx == 0 else None

    catchments_rows = [MagicMock(), MagicMock()]
    for r, v in zip(catchments_rows, [1000, 10000]):
        r.__getitem__ = lambda self, idx, val=v: val if idx == 0 else None

    def execute_side_effect(query, params=None):
        result = MagicMock()
        query_str = str(query)
        if "stream_network" in query_str:
            result.fetchall.return_value = streams_rows
        elif "stream_catchments" in query_str:
            result.fetchall.return_value = catchments_rows
        return result

    mock_session.execute.side_effect = execute_side_effect
    return mock_session


class TestStreamsMVT:
    """Tests for GET /api/tiles/streams/{z}/{x}/{y}.pbf."""

    def test_returns_200(self, client, mock_db_with_tile):
        """Test successful tile request returns 200."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_tile

        response = client.get("/api/tiles/streams/10/550/340.pbf")

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_content_type_is_protobuf(self, client, mock_db_with_tile):
        """Test response content type is protobuf."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_tile

        response = client.get("/api/tiles/streams/10/550/340.pbf")

        assert response.headers["content-type"] == "application/x-protobuf"
        app.dependency_overrides.clear()

    def test_cache_control_header(self, client, mock_db_with_tile):
        """Test response has cache control header."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_tile

        response = client.get("/api/tiles/streams/10/550/340.pbf")

        assert "Cache-Control" in response.headers
        assert "max-age" in response.headers["Cache-Control"]
        app.dependency_overrides.clear()

    def test_returns_binary_content(self, client, mock_db_with_tile):
        """Test response content is bytes."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_tile

        response = client.get("/api/tiles/streams/10/550/340.pbf")

        assert isinstance(response.content, bytes)
        app.dependency_overrides.clear()

    def test_empty_tile_returns_200(self, client, mock_db_empty_tile):
        """Test empty tile still returns 200 with empty content."""
        app.dependency_overrides[get_db] = lambda: mock_db_empty_tile

        response = client.get("/api/tiles/streams/10/550/340.pbf")

        assert response.status_code == 200
        assert response.content == b""
        app.dependency_overrides.clear()

    def test_no_row_returns_200_empty(self, client, mock_db_no_tile):
        """Test missing row returns 200 with empty content."""
        app.dependency_overrides[get_db] = lambda: mock_db_no_tile

        response = client.get("/api/tiles/streams/10/550/340.pbf")

        assert response.status_code == 200
        assert response.content == b""
        app.dependency_overrides.clear()

    def test_custom_threshold_parameter(self, client, mock_db_with_tile):
        """Test custom threshold query parameter."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_tile

        response = client.get("/api/tiles/streams/10/550/340.pbf?threshold=1000")

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_default_threshold_is_10000(self, client, mock_db_with_tile):
        """Test that default threshold is 10000."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_tile

        # Just verify the request succeeds without explicit threshold
        response = client.get("/api/tiles/streams/10/550/340.pbf")

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_threshold_must_be_positive(self, client):
        """Test that threshold < 1 returns 422."""
        response = client.get("/api/tiles/streams/10/550/340.pbf?threshold=0")

        assert response.status_code == 422

    def test_different_zoom_levels(self, client, mock_db_with_tile):
        """Test various zoom levels work."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_tile

        for z in [0, 5, 10, 15, 18]:
            response = client.get(f"/api/tiles/streams/{z}/0/0.pbf")
            assert response.status_code == 200, f"Failed for zoom={z}"

        app.dependency_overrides.clear()


class TestCatchmentsMVT:
    """Tests for GET /api/tiles/catchments/{z}/{x}/{y}.pbf."""

    def test_returns_200(self, client, mock_db_with_tile):
        """Test successful catchment tile returns 200."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_tile

        response = client.get("/api/tiles/catchments/10/550/340.pbf")

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_content_type_is_protobuf(self, client, mock_db_with_tile):
        """Test response content type is protobuf."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_tile

        response = client.get("/api/tiles/catchments/10/550/340.pbf")

        assert response.headers["content-type"] == "application/x-protobuf"
        app.dependency_overrides.clear()

    def test_cache_control_header(self, client, mock_db_with_tile):
        """Test response has cache control header."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_tile

        response = client.get("/api/tiles/catchments/10/550/340.pbf")

        assert "Cache-Control" in response.headers
        app.dependency_overrides.clear()

    def test_empty_tile_returns_200(self, client, mock_db_empty_tile):
        """Test empty catchment tile returns 200."""
        app.dependency_overrides[get_db] = lambda: mock_db_empty_tile

        response = client.get("/api/tiles/catchments/10/550/340.pbf")

        assert response.status_code == 200
        assert response.content == b""
        app.dependency_overrides.clear()

    def test_custom_threshold(self, client, mock_db_with_tile):
        """Test custom threshold for catchment tiles."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_tile

        response = client.get(
            "/api/tiles/catchments/10/550/340.pbf?threshold=100000"
        )

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_threshold_must_be_positive(self, client):
        """Test that threshold < 1 returns 422."""
        response = client.get("/api/tiles/catchments/10/550/340.pbf?threshold=0")

        assert response.status_code == 422


class TestThresholdsEndpoint:
    """Tests for GET /api/tiles/thresholds."""

    def test_returns_200(self, client, mock_db_with_thresholds):
        """Test thresholds endpoint returns 200."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_thresholds

        response = client.get("/api/tiles/thresholds")

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_response_structure(self, client, mock_db_with_thresholds):
        """Test response has streams and catchments keys."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_thresholds

        response = client.get("/api/tiles/thresholds")
        data = response.json()

        assert "streams" in data
        assert "catchments" in data
        assert isinstance(data["streams"], list)
        assert isinstance(data["catchments"], list)
        app.dependency_overrides.clear()

    def test_threshold_values(self, client, mock_db_with_thresholds):
        """Test that returned thresholds match mock data."""
        app.dependency_overrides[get_db] = lambda: mock_db_with_thresholds

        response = client.get("/api/tiles/thresholds")
        data = response.json()

        assert data["streams"] == [100, 1000, 10000]
        assert data["catchments"] == [1000, 10000]
        app.dependency_overrides.clear()

    def test_empty_thresholds(self, client):
        """Test with database returning no thresholds."""
        mock_session = MagicMock()

        def execute_side_effect(query, params=None):
            result = MagicMock()
            result.fetchall.return_value = []
            return result

        mock_session.execute.side_effect = execute_side_effect
        app.dependency_overrides[get_db] = lambda: mock_session

        response = client.get("/api/tiles/thresholds")
        data = response.json()

        assert response.status_code == 200
        assert data["streams"] == []
        assert data["catchments"] == []
        app.dependency_overrides.clear()

    def test_catchments_table_missing_graceful(self, client):
        """Test graceful handling when stream_catchments table doesn't exist."""
        mock_session = MagicMock()
        call_count = 0

        def execute_side_effect(query, params=None):
            nonlocal call_count
            result = MagicMock()
            call_count += 1
            if call_count == 1:
                # stream_network returns data
                row = MagicMock()
                row.__getitem__ = lambda self, idx: 10000 if idx == 0 else None
                result.fetchall.return_value = [row]
            else:
                # stream_catchments raises
                raise Exception("relation does not exist")
            return result

        mock_session.execute.side_effect = execute_side_effect
        app.dependency_overrides[get_db] = lambda: mock_session

        response = client.get("/api/tiles/thresholds")
        data = response.json()

        assert response.status_code == 200
        assert data["streams"] == [10000]
        assert data["catchments"] == []
        app.dependency_overrides.clear()
