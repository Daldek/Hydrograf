"""
Integration tests for select-stream endpoint.

Tests the graph-based select-stream endpoint that uses CatchmentGraph
instead of flow_network BFS + raster operations.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy import sparse

from api.main import app
from core.catchment_graph import CatchmentGraph
from core.database import get_db


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


def _make_mock_catchment_graph():
    """Create a mock CatchmentGraph with 3 nodes for testing."""
    cg = CatchmentGraph()
    n = 3
    cg._n = n
    cg._loaded = True

    cg._segment_idx = np.array([10, 11, 12], dtype=np.int32)
    cg._threshold_m2 = np.array([10000, 10000, 10000], dtype=np.int32)
    cg._area_km2 = np.array([2.0, 3.0, 5.0], dtype=np.float32)
    cg._elev_min = np.array([140.0, 150.0, 120.0], dtype=np.float32)
    cg._elev_max = np.array([180.0, 190.0, 160.0], dtype=np.float32)
    cg._elev_mean = np.array([160.0, 170.0, 140.0], dtype=np.float32)
    cg._slope_mean = np.array([4.0, 5.0, 3.0], dtype=np.float32)
    cg._perimeter_km = np.array([8.0, 10.0, 15.0], dtype=np.float32)
    cg._stream_length_km = np.array([1.5, 2.0, 3.0], dtype=np.float32)
    cg._strahler = np.array([1, 1, 2], dtype=np.int8)
    cg._histograms = [
        {"base_m": 140, "interval_m": 1, "counts": [10, 20, 30, 20, 10]},
        {"base_m": 150, "interval_m": 1, "counts": [15, 25, 15]},
        {"base_m": 120, "interval_m": 1, "counts": [5, 10, 15, 20, 15, 10, 5]},
    ]

    cg._lookup = {
        (10000, 10): 0,
        (10000, 11): 1,
        (10000, 12): 2,
    }

    # 10→12, 11→12 (12 is outlet)
    row = np.array([2, 2], dtype=np.int32)
    col = np.array([0, 1], dtype=np.int32)
    data = np.ones(2, dtype=np.int8)
    cg._upstream_adj = sparse.csr_matrix(
        (data, (row, col)),
        shape=(n, n),
        dtype=np.int8,
    )

    return cg


@pytest.fixture
def mock_db_select_stream():
    """Mock database for graph-based stream selection."""
    mock_session = MagicMock()

    # Mock stream_network segment result
    segment_result = MagicMock()
    segment_result.id = 12
    segment_result.strahler_order = 2
    segment_result.length_m = 3000.0
    segment_result.upstream_area_km2 = 10.0
    segment_result.downstream_x = 639139.0
    segment_result.downstream_y = 486706.0

    # Mock catchment point lookup
    catchment_result = MagicMock()
    catchment_result.segment_idx = 12

    # Mock ST_Union boundary (WKB for a simple polygon)
    from shapely.geometry import MultiPolygon, Polygon

    poly = Polygon(
        [
            (639100, 486650),
            (639200, 486650),
            (639200, 486750),
            (639100, 486750),
            (639100, 486650),
        ]
    )
    multi = MultiPolygon([poly])
    boundary_wkb = multi.wkb

    boundary_result = MagicMock()
    boundary_result.geom = boundary_wkb

    # Mock outlet endpoint
    outlet_result = MagicMock()
    outlet_result.x = 639139.0
    outlet_result.y = 486706.0

    # Mock outlet elevation
    elev_result = MagicMock()
    elev_result.elevation = 120.0

    # Mock main stream GeoJSON
    stream_geojson_result = MagicMock()
    stream_geojson_result.geojson = (
        '{"type":"LineString","coordinates":[[21.01,52.23],[21.02,52.24]]}'
    )

    def execute_side_effect(query, params=None):
        result = MagicMock()
        query_str = str(query)

        if "stream_network" in query_str and "ST_DWithin" in query_str:
            result.fetchone.return_value = segment_result
        elif "ST_Contains" in query_str and "stream_catchments" in query_str:
            result.fetchone.return_value = catchment_result
        elif "ST_Union" in query_str:
            result.fetchone.return_value = boundary_result
        elif "ST_EndPoint" in query_str:
            result.fetchone.return_value = outlet_result
        elif "elevation" in query_str and "is_stream" in query_str:
            result.fetchone.return_value = elev_result
        elif "ST_AsGeoJSON" in query_str:
            result.fetchone.return_value = stream_geojson_result
        elif "land_cover" in query_str:
            result.fetchall.return_value = []
            result.fetchone.return_value = None
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
        cg = _make_mock_catchment_graph()

        with patch(
            "api.endpoints.select_stream.get_catchment_graph",
            return_value=cg,
        ):
            app.dependency_overrides[get_db] = lambda: mock_db_select_stream

            response = client.post(
                "/api/select-stream",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "threshold_m2": 10000,
                },
            )

            assert response.status_code == 200
            app.dependency_overrides.clear()

    def test_response_has_watershed(self, client, mock_db_select_stream):
        """Test response contains watershed field with full stats."""
        cg = _make_mock_catchment_graph()

        with patch(
            "api.endpoints.select_stream.get_catchment_graph",
            return_value=cg,
        ):
            app.dependency_overrides[get_db] = lambda: mock_db_select_stream

            response = client.post(
                "/api/select-stream",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "threshold_m2": 10000,
                },
            )

            data = response.json()
            assert "watershed" in data
            assert data["watershed"] is not None
            assert "boundary_geojson" in data["watershed"]
            assert "outlet" in data["watershed"]
            assert "area_km2" in data["watershed"]
            assert "hydrograph_available" in data["watershed"]

            app.dependency_overrides.clear()

    def test_morphometric_parameters_present(self, client, mock_db_select_stream):
        """Test watershed.morphometry has key parameters."""
        cg = _make_mock_catchment_graph()

        with patch(
            "api.endpoints.select_stream.get_catchment_graph",
            return_value=cg,
        ):
            app.dependency_overrides[get_db] = lambda: mock_db_select_stream

            response = client.post(
                "/api/select-stream",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "threshold_m2": 10000,
                },
            )

            data = response.json()
            morph = data["watershed"]["morphometry"]
            assert morph is not None
            assert "area_km2" in morph
            assert "perimeter_km" in morph
            assert "elevation_min_m" in morph
            assert "elevation_max_m" in morph
            assert "elevation_mean_m" in morph
            assert morph["area_km2"] > 0
            assert morph["drainage_density_km_per_km2"] is not None

            app.dependency_overrides.clear()

    def test_upstream_segments_present(self, client, mock_db_select_stream):
        """Test upstream_segment_indices is returned."""
        cg = _make_mock_catchment_graph()

        with patch(
            "api.endpoints.select_stream.get_catchment_graph",
            return_value=cg,
        ):
            app.dependency_overrides[get_db] = lambda: mock_db_select_stream

            response = client.post(
                "/api/select-stream",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "threshold_m2": 10000,
                },
            )

            data = response.json()
            assert "upstream_segment_indices" in data
            assert isinstance(data["upstream_segment_indices"], list)
            assert len(data["upstream_segment_indices"]) > 0
            # Should contain all 3 segments (10, 11, 12) since we start from 12
            assert sorted(data["upstream_segment_indices"]) == [10, 11, 12]

            app.dependency_overrides.clear()

    def test_no_stream_returns_404(self, client):
        """Test that missing stream returns 404."""
        cg = _make_mock_catchment_graph()
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None

        with patch(
            "api.endpoints.select_stream.get_catchment_graph",
            return_value=cg,
        ):
            app.dependency_overrides[get_db] = lambda: mock_session

            response = client.post(
                "/api/select-stream",
                json={
                    "latitude": 52.0,
                    "longitude": 21.0,
                    "threshold_m2": 10000,
                },
            )

            assert response.status_code == 404
            assert "Nie znaleziono cieku" in response.json()["detail"]

            app.dependency_overrides.clear()

    def test_graph_not_loaded_returns_503(self, client):
        """Test that unloaded graph returns 503."""
        cg = CatchmentGraph()  # Not loaded
        mock_session = MagicMock()

        # Need stream to be found first
        segment_result = MagicMock()
        segment_result.id = 12
        segment_result.strahler_order = 2
        segment_result.length_m = 3000.0
        segment_result.upstream_area_km2 = 10.0
        segment_result.downstream_x = 639139.0
        segment_result.downstream_y = 486706.0
        mock_session.execute.return_value.fetchone.return_value = segment_result

        with patch(
            "api.endpoints.select_stream.get_catchment_graph",
            return_value=cg,
        ):
            app.dependency_overrides[get_db] = lambda: mock_session

            response = client.post(
                "/api/select-stream",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "threshold_m2": 10000,
                },
            )

            assert response.status_code == 503

            app.dependency_overrides.clear()

    def test_invalid_coordinates_returns_422(self, client):
        """Test that latitude=200 returns 422."""
        response = client.post(
            "/api/select-stream",
            json={
                "latitude": 200.0,
                "longitude": 21.0,
                "threshold_m2": 10000,
            },
        )

        assert response.status_code == 422

    def test_missing_threshold_returns_422(self, client):
        """Test that missing threshold_m2 returns 422."""
        response = client.post(
            "/api/select-stream",
            json={"latitude": 52.23, "longitude": 21.01},
        )

        assert response.status_code == 422
