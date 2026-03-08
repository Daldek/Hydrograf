"""
Unit tests for CR9: cascade threshold boundary vs stats mismatch fix.

Verifies that when cascade escalation occurs (>500 segments triggers
coarser threshold), both boundary AND stats use the escalated threshold.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import MultiPolygon, Polygon

from api.main import app
from core.database import get_db


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


def _make_boundary_wkb():
    """Create a simple boundary WKB for mocking merge_catchment_boundaries."""
    poly = Polygon([
        (639100, 486650),
        (639200, 486650),
        (639200, 486750),
        (639100, 486750),
        (639100, 486650),
    ])
    return MultiPolygon([poly])


def _make_mock_cg_with_cascade():
    """
    Create a mock CatchmentGraph that triggers cascade escalation.

    Setup:
    - Fine threshold (1000): BFS returns 600 segments (>500 limit)
    - Coarse threshold (10000): BFS returns 50 segments (<=500 limit)
    - aggregate_stats returns different values for fine vs coarse indices
    """
    cg = MagicMock()
    cg.loaded = True

    # Fine threshold upstream indices (600 items -> triggers cascade)
    fine_upstream = np.arange(600, dtype=np.int32)
    fine_segment_idxs = list(range(1, 601))  # 600 segments

    # Coarse threshold upstream indices (50 items -> below limit)
    coarse_upstream = np.arange(50, dtype=np.int32)
    coarse_segment_idxs = list(range(1, 51))  # 50 segments

    # Fine stats (should NOT appear in final response after cascade)
    fine_stats = {
        "area_km2": 100.0,
        "elevation_min_m": 100.0,
        "elevation_max_m": 300.0,
        "elevation_mean_m": 200.0,
        "mean_slope_m_per_m": 0.05,
        "drainage_density_km_per_km2": 2.0,
        "stream_frequency_per_km2": 1.5,
        "max_strahler_order": 4,
    }

    # Coarse stats (should appear in final response after cascade)
    coarse_stats = {
        "area_km2": 105.0,
        "elevation_min_m": 95.0,
        "elevation_max_m": 310.0,
        "elevation_mean_m": 202.0,
        "mean_slope_m_per_m": 0.048,
        "drainage_density_km_per_km2": 1.8,
        "stream_frequency_per_km2": 1.3,
        "max_strahler_order": 4,
    }

    # lookup_by_segment_idx -> returns internal index
    cg.lookup_by_segment_idx.return_value = 0

    # get_segment_idx -> returns segment_idx for display
    cg.get_segment_idx.return_value = 1

    # traverse_upstream -> fine indices (600 items)
    cg.traverse_upstream.side_effect = [
        fine_upstream,       # First call: fine threshold BFS
        coarse_upstream,     # Second call: coarse threshold BFS (during cascade)
    ]

    # get_segment_indices: maps indices to segment_idxs
    cg.get_segment_indices.side_effect = [
        fine_segment_idxs,     # First call: fine -> 600 segments
        coarse_segment_idxs,   # Second call: coarse -> 50 segments
    ]

    # aggregate_stats: different results for fine vs coarse
    def _aggregate_stats(indices):
        if len(indices) == 600:
            return fine_stats.copy()
        elif len(indices) == 50:
            return coarse_stats.copy()
        return fine_stats.copy()

    cg.aggregate_stats.side_effect = _aggregate_stats

    # find_catchment_at_point: returns node index for coarse threshold
    cg.find_catchment_at_point.return_value = 0

    # trace_main_channel
    cg.trace_main_channel.return_value = {
        "main_channel_length_km": 15.0,
        "main_channel_slope_m_per_m": 0.003,
    }

    # aggregate_hypsometric
    cg.aggregate_hypsometric.return_value = []

    return cg, fine_stats, coarse_stats


def _make_mock_db():
    """Create a mock DB session for endpoint tests."""
    mock_session = MagicMock()

    segment_result = MagicMock()
    segment_result.segment_idx = 1
    segment_result.strahler_order = 3
    segment_result.length_m = 5000.0
    segment_result.upstream_area_km2 = 100.0
    segment_result.downstream_x = 639139.0
    segment_result.downstream_y = 486706.0

    catchment_result = MagicMock()
    catchment_result.segment_idx = 1

    boundary = _make_boundary_wkb()
    boundary_result = MagicMock()
    boundary_result.geom = boundary.wkb

    outlet_result = MagicMock()
    outlet_result.x = 639139.0
    outlet_result.y = 486706.0

    stream_geojson_result = MagicMock()
    stream_geojson_result.geojson = (
        '{"type":"LineString","coordinates":[[21.01,52.23],[21.02,52.24]]}'
    )

    def execute_side_effect(query, params=None):
        result = MagicMock()
        query_str = str(query)

        if "ST_ClosestPoint" in query_str:
            result.fetchone.return_value = None
        elif "stream_network" in query_str and "ST_DWithin" in query_str:
            result.fetchone.return_value = segment_result
        elif "ST_Contains" in query_str and "stream_catchments" in query_str:
            result.fetchone.return_value = catchment_result
        elif "ST_UnaryUnion" in query_str:
            result.fetchone.return_value = boundary_result
        elif "ST_EndPoint" in query_str:
            result.fetchone.return_value = outlet_result
        elif "ST_AsGeoJSON" in query_str:
            result.fetchone.return_value = stream_geojson_result
        elif "land_cover" in query_str or "soil_hsg" in query_str or "hsg" in query_str:
            result.fetchall.return_value = []
            result.fetchone.return_value = None
        else:
            result.fetchone.return_value = None
            result.fetchall.return_value = []
        return result

    mock_session.execute.side_effect = execute_side_effect
    return mock_session


class TestSelectStreamCascadeStats:
    """Tests for select_stream cascade stats consistency (CR9)."""

    def test_cascade_stats_use_escalated_threshold(self, client):
        """
        When BFS returns >500 segments, cascade escalates to coarser threshold.
        Verify that aggregate_stats is called with the coarser upstream_indices.
        """
        cg, fine_stats, coarse_stats = _make_mock_cg_with_cascade()
        mock_db = _make_mock_db()

        with patch(
            "api.endpoints.select_stream.get_catchment_graph",
            return_value=cg,
        ), patch(
            "api.endpoints.select_stream.merge_catchment_boundaries",
            return_value=_make_boundary_wkb(),
        ), patch(
            "api.endpoints.select_stream.get_stream_info_by_segment_idx",
            return_value={
                "strahler_order": 3,
                "length_m": 5000.0,
                "upstream_area_km2": 100.0,
                "downstream_x": 639139.0,
                "downstream_y": 486706.0,
            },
        ), patch(
            "api.endpoints.select_stream.get_segment_outlet",
            return_value={"x": 639139.0, "y": 486706.0},
        ), patch(
            "api.endpoints.select_stream.get_main_stream_geojson",
            return_value=None,
        ), patch(
            "api.endpoints.select_stream.get_land_cover_for_boundary",
            return_value=None,
        ):
            app.dependency_overrides[get_db] = lambda: mock_db

            response = client.post(
                "/api/select-stream",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "threshold_m2": 1000,
                },
            )

            assert response.status_code == 200
            data = response.json()

            # After cascade, area should come from coarse stats (105.0),
            # not fine stats (100.0)
            assert data["watershed"]["area_km2"] == 105.0
            assert data["watershed"]["morphometry"]["area_km2"] == 105.0

            # aggregate_stats should have been called twice:
            # 1. First with fine upstream indices (len=600)
            # 2. Then with coarse upstream indices (len=50)
            assert cg.aggregate_stats.call_count == 2
            first_call_indices = cg.aggregate_stats.call_args_list[0][0][0]
            second_call_indices = cg.aggregate_stats.call_args_list[1][0][0]
            assert len(first_call_indices) == 600
            assert len(second_call_indices) == 50

            app.dependency_overrides.clear()

    def test_no_cascade_stats_unchanged(self, client):
        """
        When BFS returns <=500 segments, no cascade occurs.
        Stats should use the original upstream_indices.
        """
        cg = MagicMock()
        cg.loaded = True

        # Only 50 segments — no cascade needed
        upstream = np.arange(50, dtype=np.int32)
        segment_idxs = list(range(1, 51))

        stats = {
            "area_km2": 25.0,
            "elevation_min_m": 120.0,
            "elevation_max_m": 250.0,
            "elevation_mean_m": 185.0,
            "mean_slope_m_per_m": 0.04,
            "drainage_density_km_per_km2": 1.5,
            "stream_frequency_per_km2": 1.0,
            "max_strahler_order": 3,
        }

        cg.lookup_by_segment_idx.return_value = 0
        cg.get_segment_idx.return_value = 1
        cg.traverse_upstream.return_value = upstream
        cg.get_segment_indices.return_value = segment_idxs
        cg.aggregate_stats.return_value = stats.copy()
        cg.find_catchment_at_point.return_value = 0
        cg.trace_main_channel.return_value = {
            "main_channel_length_km": 5.0,
            "main_channel_slope_m_per_m": 0.005,
        }
        cg.aggregate_hypsometric.return_value = []

        mock_db = _make_mock_db()

        with patch(
            "api.endpoints.select_stream.get_catchment_graph",
            return_value=cg,
        ), patch(
            "api.endpoints.select_stream.merge_catchment_boundaries",
            return_value=_make_boundary_wkb(),
        ), patch(
            "api.endpoints.select_stream.get_stream_info_by_segment_idx",
            return_value={
                "strahler_order": 3,
                "length_m": 5000.0,
                "upstream_area_km2": 25.0,
                "downstream_x": 639139.0,
                "downstream_y": 486706.0,
            },
        ), patch(
            "api.endpoints.select_stream.get_segment_outlet",
            return_value={"x": 639139.0, "y": 486706.0},
        ), patch(
            "api.endpoints.select_stream.get_main_stream_geojson",
            return_value=None,
        ), patch(
            "api.endpoints.select_stream.get_land_cover_for_boundary",
            return_value=None,
        ):
            app.dependency_overrides[get_db] = lambda: mock_db

            response = client.post(
                "/api/select-stream",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "threshold_m2": 1000,
                },
            )

            assert response.status_code == 200
            data = response.json()

            # No cascade — stats should use original indices
            assert data["watershed"]["area_km2"] == 25.0

            # aggregate_stats called only once (no re-aggregation)
            assert cg.aggregate_stats.call_count == 1

            app.dependency_overrides.clear()

    def test_cascade_hypsometric_uses_escalated_indices(self, client):
        """
        After cascade, aggregate_hypsometric should also use
        the escalated upstream_indices, not the fine ones.
        """
        cg, fine_stats, coarse_stats = _make_mock_cg_with_cascade()
        mock_db = _make_mock_db()

        with patch(
            "api.endpoints.select_stream.get_catchment_graph",
            return_value=cg,
        ), patch(
            "api.endpoints.select_stream.merge_catchment_boundaries",
            return_value=_make_boundary_wkb(),
        ), patch(
            "api.endpoints.select_stream.get_stream_info_by_segment_idx",
            return_value={
                "strahler_order": 3,
                "length_m": 5000.0,
                "upstream_area_km2": 100.0,
                "downstream_x": 639139.0,
                "downstream_y": 486706.0,
            },
        ), patch(
            "api.endpoints.select_stream.get_segment_outlet",
            return_value={"x": 639139.0, "y": 486706.0},
        ), patch(
            "api.endpoints.select_stream.get_main_stream_geojson",
            return_value=None,
        ), patch(
            "api.endpoints.select_stream.get_land_cover_for_boundary",
            return_value=None,
        ):
            app.dependency_overrides[get_db] = lambda: mock_db

            response = client.post(
                "/api/select-stream",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "threshold_m2": 1000,
                },
            )

            assert response.status_code == 200

            # aggregate_hypsometric should be called with coarse indices (len=50)
            assert cg.aggregate_hypsometric.call_count == 1
            hypso_indices = cg.aggregate_hypsometric.call_args[0][0]
            assert len(hypso_indices) == 50

            # trace_main_channel should also use coarse indices
            assert cg.trace_main_channel.call_count == 1
            trace_indices = cg.trace_main_channel.call_args[0][1]
            assert len(trace_indices) == 50

            app.dependency_overrides.clear()


class TestWatershedCascadeStats:
    """Tests for watershed delineation cascade stats consistency (CR9)."""

    def test_cascade_stats_use_escalated_threshold(self, client):
        """
        When watershed BFS returns >500 segments, cascade escalates.
        Verify that build_morph_dict_from_graph is called with coarse indices.
        """
        cg = MagicMock()
        cg.loaded = True

        # Fine threshold: 600 upstream indices (triggers cascade)
        fine_upstream = np.arange(600, dtype=np.int32)
        fine_segment_idxs = list(range(1, 601))

        # Coarse threshold: 50 upstream indices (below limit)
        coarse_upstream = np.arange(50, dtype=np.int32)
        coarse_segment_idxs = list(range(1, 51))

        fine_stats = {"area_km2": 100.0, "elevation_min_m": 100.0}
        coarse_stats = {"area_km2": 105.0, "elevation_min_m": 95.0}

        cg.find_catchment_at_point.return_value = 0
        cg.get_segment_idx.return_value = 1

        cg.traverse_upstream.side_effect = [
            fine_upstream,
            coarse_upstream,
        ]
        cg.get_segment_indices.side_effect = [
            fine_segment_idxs,
            coarse_segment_idxs,
        ]

        def _aggregate_stats(indices):
            if len(indices) == 600:
                return fine_stats.copy()
            elif len(indices) == 50:
                return coarse_stats.copy()
            return fine_stats.copy()

        cg.aggregate_stats.side_effect = _aggregate_stats
        cg.aggregate_hypsometric.return_value = []

        mock_db = _make_mock_db()

        with patch(
            "api.endpoints.watershed.get_catchment_graph",
            return_value=cg,
        ), patch(
            "api.endpoints.watershed.get_stream_info_by_segment_idx",
            return_value={
                "downstream_x": 639139.0,
                "downstream_y": 486706.0,
            },
        ), patch(
            "api.endpoints.watershed.merge_catchment_boundaries",
            return_value=_make_boundary_wkb(),
        ), patch(
            "api.endpoints.watershed.get_segment_outlet",
            return_value={"x": 639139.0, "y": 486706.0},
        ), patch(
            "api.endpoints.watershed.get_main_stream_geojson",
            return_value=None,
        ), patch(
            "api.endpoints.watershed.get_land_cover_for_boundary",
            return_value=None,
        ), patch(
            "api.endpoints.watershed.build_morph_dict_from_graph",
            return_value={
                "area_km2": 105.0,
                "perimeter_km": 50.0,
                "length_km": 20.0,
                "elevation_min_m": 95.0,
                "elevation_max_m": 310.0,
                "elevation_mean_m": 202.0,
                "mean_slope_m_per_m": 0.048,
                "channel_length_km": 15.0,
                "channel_slope_m_per_m": 0.003,
                "compactness_coefficient": 1.4,
                "circularity_ratio": 0.5,
                "elongation_ratio": 0.6,
                "form_factor": 0.3,
                "mean_width_km": 5.0,
                "relief_ratio": 0.01,
                "hypsometric_integral": 0.45,
                "drainage_density_km_per_km2": 1.8,
                "stream_frequency_per_km2": 1.3,
                "ruggedness_number": 0.4,
                "max_strahler_order": 4,
            },
        ) as mock_morph:
            app.dependency_overrides[get_db] = lambda: mock_db

            response = client.post(
                "/api/delineate-watershed",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                },
            )

            assert response.status_code == 200
            data = response.json()

            # After cascade, area should come from coarse stats
            assert data["watershed"]["area_km2"] == 105.0

            # aggregate_stats called twice: fine then coarse
            assert cg.aggregate_stats.call_count == 2
            second_call_indices = cg.aggregate_stats.call_args_list[1][0][0]
            assert len(second_call_indices) == 50

            # build_morph_dict_from_graph should receive coarse indices
            morph_call_args = mock_morph.call_args
            morph_upstream_indices = morph_call_args[0][1]  # 2nd positional arg
            assert len(morph_upstream_indices) == 50

            app.dependency_overrides.clear()
