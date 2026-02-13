"""
Integration tests for select-stream endpoint.
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
def mock_db_select_stream():
    """Mock database with stream data for successful stream selection."""
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

    # Mock traverse_upstream results (4 cells)
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

    # Mock pre-flight check result
    preflight_result = MagicMock()
    preflight_result.flow_accumulation = 3

    # Mock stream_network segment result
    segment_result = MagicMock()
    segment_result.segment_idx = 42
    segment_result.strahler_order = 3
    segment_result.length_m = 1250.0
    segment_result.upstream_area_km2 = 5.6

    # Mock upstream catchment segments
    catchment_results = [MagicMock(segment_idx=42), MagicMock(segment_idx=43)]

    def execute_side_effect(query, params=None):
        result = MagicMock()
        query_str = str(query)
        if "is_stream = TRUE" in query_str:
            result.fetchone.return_value = stream_result
        elif "flow_accumulation FROM flow_network WHERE id" in query_str:
            result.fetchone.return_value = preflight_result
        elif "RECURSIVE upstream" in query_str:
            result.fetchall.return_value = upstream_results
        elif "stream_network" in query_str and "ST_DWithin" in query_str:
            result.fetchone.return_value = segment_result
        elif "stream_catchments" in query_str:
            result.fetchall.return_value = catchment_results
        elif "stream_network" in query_str and "source" in query_str:
            # get_stream_stats_in_watershed
            stats_result = MagicMock()
            stats_result.__getitem__ = lambda self, idx: [500.0, 3, 2][idx]
            result.fetchone.return_value = stats_result
        else:
            result.fetchone.return_value = None
            result.fetchall.return_value = []
        return result

    mock_session.execute.side_effect = execute_side_effect
    return mock_session


class TestSelectStreamEndpoint:
    """Tests for POST /api/select-stream."""

    def test_success_returns_200(self, client, mock_db_select_stream):
        """Test successful stream selection returns 200."""
        app.dependency_overrides[get_db] = lambda: mock_db_select_stream

        response = client.post(
            "/api/select-stream",
            json={"latitude": 52.23, "longitude": 21.01, "threshold_m2": 10000},
        )

        assert response.status_code == 200
        app.dependency_overrides.clear()

    def test_response_has_watershed(self, client, mock_db_select_stream):
        """Test response contains watershed field with full stats."""
        app.dependency_overrides[get_db] = lambda: mock_db_select_stream

        response = client.post(
            "/api/select-stream",
            json={"latitude": 52.23, "longitude": 21.01, "threshold_m2": 10000},
        )

        data = response.json()
        assert "watershed" in data
        assert data["watershed"] is not None
        assert "boundary_geojson" in data["watershed"]
        assert "outlet" in data["watershed"]
        assert "cell_count" in data["watershed"]
        assert "area_km2" in data["watershed"]
        assert "hydrograph_available" in data["watershed"]

        app.dependency_overrides.clear()

    def test_morphometric_parameters_present(self, client, mock_db_select_stream):
        """Test watershed.morphometry has key parameters."""
        app.dependency_overrides[get_db] = lambda: mock_db_select_stream

        response = client.post(
            "/api/select-stream",
            json={"latitude": 52.23, "longitude": 21.01, "threshold_m2": 10000},
        )

        data = response.json()
        morph = data["watershed"]["morphometry"]
        assert morph is not None
        assert "area_km2" in morph
        assert "perimeter_km" in morph
        assert "elevation_min_m" in morph
        assert "elevation_max_m" in morph
        assert "elevation_mean_m" in morph

        app.dependency_overrides.clear()

    def test_upstream_segments_present(self, client, mock_db_select_stream):
        """Test upstream_segment_indices is returned."""
        app.dependency_overrides[get_db] = lambda: mock_db_select_stream

        response = client.post(
            "/api/select-stream",
            json={"latitude": 52.23, "longitude": 21.01, "threshold_m2": 10000},
        )

        data = response.json()
        assert "upstream_segment_indices" in data
        assert isinstance(data["upstream_segment_indices"], list)
        assert len(data["upstream_segment_indices"]) > 0

        app.dependency_overrides.clear()

    def test_no_stream_returns_404(self, client):
        """Test that missing stream returns 404."""
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None
        app.dependency_overrides[get_db] = lambda: mock_session

        response = client.post(
            "/api/select-stream",
            json={"latitude": 52.0, "longitude": 21.0, "threshold_m2": 10000},
        )

        assert response.status_code == 404
        assert "Nie znaleziono cieku" in response.json()["detail"]

        app.dependency_overrides.clear()

    def test_no_segment_for_threshold_returns_404(self, client):
        """Test that missing segment for threshold returns 404."""
        mock_session = MagicMock()

        # find_nearest_stream succeeds
        stream_result = MagicMock()
        stream_result.id = 1
        stream_result.x = 639139.0
        stream_result.y = 486706.0
        stream_result.elevation = 150.0
        stream_result.flow_accumulation = 1000
        stream_result.slope = 2.5
        stream_result.downstream_id = None
        stream_result.cell_area = 25.0
        stream_result.is_stream = True
        stream_result.distance = 50.0

        def execute_side_effect(query, params=None):
            result = MagicMock()
            query_str = str(query)
            if "is_stream = TRUE" in query_str:
                result.fetchone.return_value = stream_result
            elif "stream_network" in query_str and "ST_DWithin" in query_str:
                # No segment found for this threshold
                result.fetchone.return_value = None
            else:
                result.fetchone.return_value = None
                result.fetchall.return_value = []
            return result

        mock_session.execute.side_effect = execute_side_effect
        app.dependency_overrides[get_db] = lambda: mock_session

        response = client.post(
            "/api/select-stream",
            json={"latitude": 52.23, "longitude": 21.01, "threshold_m2": 100000},
        )

        assert response.status_code == 404
        assert "segmentu" in response.json()["detail"]

        app.dependency_overrides.clear()

    def test_invalid_coordinates_returns_422(self, client):
        """Test that latitude=200 returns 422."""
        response = client.post(
            "/api/select-stream",
            json={"latitude": 200.0, "longitude": 21.0, "threshold_m2": 10000},
        )

        assert response.status_code == 422

    def test_missing_threshold_returns_422(self, client):
        """Test that missing threshold_m2 returns 422."""
        response = client.post(
            "/api/select-stream",
            json={"latitude": 52.23, "longitude": 21.01},
        )

        assert response.status_code == 422
