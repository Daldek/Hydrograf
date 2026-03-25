"""
Integration tests for precomputed-mode delineation (formerly select-stream).

Tests the POST /api/delineate-watershed endpoint with threshold_m2 provided,
which uses CatchmentGraph BFS and ST_Union boundary (precomputed mode).
"""

import contextlib
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from scipy import sparse
from shapely.geometry import MultiPolygon, Polygon

from api.main import app
from core.catchment_graph import CatchmentGraph
from core.database import get_db

# Patch target prefix for the watershed endpoint module
_WS = "api.endpoints.watershed"


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


def _make_mock_cg(area_km2: float = 10.0) -> MagicMock:
    """Create a mock CatchmentGraph with sensible defaults."""
    cg = MagicMock(spec=CatchmentGraph)
    cg.loaded = True
    cg._segment_idx = np.array([10, 11, 12], dtype=np.int32)
    cg.find_catchment_at_point.return_value = 0  # internal idx
    cg.get_segment_idx.return_value = 12  # segment_idx for internal idx 0
    cg.traverse_upstream.return_value = np.array([0, 1, 2])
    cg.get_segment_indices.return_value = [10, 11, 12]
    cg.aggregate_stats.return_value = {
        "area_km2": area_km2,
        "elevation_min_m": 120.0,
        "elevation_max_m": 190.0,
        "elevation_mean_m": 155.0,
        "mean_slope_m_per_m": 0.04,
        "stream_length_km": 6.5,
        "drainage_density_km_per_km2": 0.65,
        "max_strahler_order": 2,
        "stream_frequency_per_km2": 0.3,
    }
    cg.aggregate_hypsometric.return_value = []
    return cg


def _make_segment() -> dict:
    """Create a mock stream segment dict."""
    return {
        "segment_idx": 12,
        "strahler_order": 2,
        "length_m": 3000.0,
        "upstream_area_km2": 10.0,
        "downstream_x": 639139.0,
        "downstream_y": 486706.0,
    }


def _make_boundary() -> MultiPolygon:
    """Create a simple rectangular MultiPolygon boundary in PL-1992."""
    poly = Polygon(
        [
            (639100, 486650),
            (639200, 486650),
            (639200, 486750),
            (639100, 486750),
            (639100, 486650),
        ]
    )
    return MultiPolygon([poly])


def _make_morph_dict(area_km2: float = 10.0) -> dict:
    """Create a morphometric parameter dict matching MorphometricParameters schema."""
    return {
        "area_km2": area_km2,
        "perimeter_km": 0.4,
        "length_km": 0.15,
        "elevation_min_m": 120.0,
        "elevation_max_m": 190.0,
        "elevation_mean_m": 155.0,
        "mean_slope_m_per_m": 0.04,
        "channel_length_km": 6.5,
        "channel_slope_m_per_m": 0.0108,
        "cn": None,
        "source": "Hydrograf",
        "crs": "EPSG:2180",
        "compactness_coefficient": 1.13,
        "circularity_ratio": 0.79,
        "elongation_ratio": 1.2,
        "form_factor": 0.44,
        "mean_width_km": 0.067,
        "relief_ratio": 0.47,
        "hypsometric_integral": 0.5,
        "drainage_density_km_per_km2": 0.65,
        "stream_frequency_per_km2": 0.3,
        "ruggedness_number": 0.046,
        "max_strahler_order": 2,
    }


def _patch_all(cg=None, segment=None, boundary=None, morph=None):
    """Create a list of context managers for all required patches."""
    if cg is None:
        cg = _make_mock_cg()
    if segment is None:
        segment = _make_segment()
    if boundary is None:
        boundary = _make_boundary()
    if morph is None:
        morph = _make_morph_dict()

    return [
        patch(f"{_WS}.get_catchment_graph", return_value=cg),
        patch(f"{_WS}.get_stream_info_by_segment_idx", return_value=segment),
        patch(f"{_WS}.merge_catchment_boundaries", return_value=boundary),
        patch(
            f"{_WS}.get_segment_outlet",
            return_value={"x": 639139.0, "y": 486706.0},
        ),
        patch(f"{_WS}.build_morph_dict_from_graph", return_value=morph),
        patch(f"{_WS}.get_main_stream_geojson", return_value=None),
        patch(f"{_WS}.get_main_channel_feature_collection", return_value=None),
        patch(f"{_WS}.build_land_cover_stats", return_value=None),
        patch(f"{_WS}.build_hsg_stats", return_value=None),
        patch(f"{_WS}.get_longest_flow_path_geojson", return_value=None),
        patch(f"{_WS}.get_divide_flow_path_geojson", return_value=None),
        patch(f"{_WS}.cascade_escalate", return_value=None),
    ]


class TestPrecomputedDelineation:
    """Tests for POST /api/delineate-watershed with threshold_m2 (precomputed mode)."""

    def test_success_returns_200(self, client):
        """Test successful precomputed delineation returns 200."""
        with contextlib.ExitStack() as stack:
            for p in _patch_all():
                stack.enter_context(p)

            response = client.post(
                "/api/delineate-watershed",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "threshold_m2": 10000,
                },
            )

        assert response.status_code == 200

    def test_response_mode_is_precomputed(self, client):
        """Test response mode is 'precomputed' when threshold_m2 provided."""
        with contextlib.ExitStack() as stack:
            for p in _patch_all():
                stack.enter_context(p)

            response = client.post(
                "/api/delineate-watershed",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "threshold_m2": 10000,
                },
            )

        data = response.json()
        assert data["mode"] == "precomputed"

    def test_response_has_watershed(self, client):
        """Test response contains watershed field with full stats."""
        with contextlib.ExitStack() as stack:
            for p in _patch_all():
                stack.enter_context(p)

            response = client.post(
                "/api/delineate-watershed",
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

    def test_morphometric_parameters_present(self, client):
        """Test watershed.morphometry has key parameters."""
        with contextlib.ExitStack() as stack:
            for p in _patch_all():
                stack.enter_context(p)

            response = client.post(
                "/api/delineate-watershed",
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

    def test_upstream_segments_present(self, client):
        """Test upstream_segment_indices is returned in precomputed mode."""
        with contextlib.ExitStack() as stack:
            for p in _patch_all():
                stack.enter_context(p)

            response = client.post(
                "/api/delineate-watershed",
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
        # Should contain all 3 segments (10, 11, 12)
        assert sorted(data["upstream_segment_indices"]) == [10, 11, 12]

    def test_no_catchment_returns_404(self, client):
        """Test that missing catchment returns 404."""
        cg = _make_mock_cg()
        cg.find_catchment_at_point.side_effect = ValueError(
            "Nie znaleziono zlewni cząstkowej"
        )

        patches = [
            patch(f"{_WS}.get_catchment_graph", return_value=cg),
        ]

        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)

            response = client.post(
                "/api/delineate-watershed",
                json={
                    "latitude": 52.0,
                    "longitude": 21.0,
                    "threshold_m2": 10000,
                },
            )

        assert response.status_code == 404
        assert "Nie znaleziono zlewni" in response.json()["detail"]

    def test_graph_not_loaded_returns_503(self, client):
        """Test that unloaded graph returns 503."""
        cg = MagicMock(spec=CatchmentGraph)
        cg.loaded = False

        with patch(f"{_WS}.get_catchment_graph", return_value=cg):
            response = client.post(
                "/api/delineate-watershed",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "threshold_m2": 10000,
                },
            )

        assert response.status_code == 503

    def test_invalid_coordinates_returns_422(self, client):
        """Test that latitude=200 returns 422."""
        response = client.post(
            "/api/delineate-watershed",
            json={
                "latitude": 200.0,
                "longitude": 21.0,
                "threshold_m2": 10000,
            },
        )

        assert response.status_code == 422

    def test_display_threshold_matches_request(self, client):
        """Test display_threshold_m2 in response matches request threshold."""
        with contextlib.ExitStack() as stack:
            for p in _patch_all():
                stack.enter_context(p)

            response = client.post(
                "/api/delineate-watershed",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "threshold_m2": 10000,
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["display_threshold_m2"] == 10000

    def test_stream_info_present(self, client):
        """Test stream info is returned in precomputed mode."""
        with contextlib.ExitStack() as stack:
            for p in _patch_all():
                stack.enter_context(p)

            response = client.post(
                "/api/delineate-watershed",
                json={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "threshold_m2": 10000,
                },
            )

        data = response.json()
        assert data["stream"] is not None
        assert data["stream"]["segment_idx"] == 12
        assert data["stream"]["strahler_order"] == 2
