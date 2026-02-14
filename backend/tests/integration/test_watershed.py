"""
Integration tests for watershed delineation endpoint.

Tests the POST /api/delineate-watershed endpoint using mocked
CatchmentGraph and watershed_service functions. The endpoint
flow is:
  1. Transform coords (WGS84 -> PL-1992)
  2. Get CatchmentGraph (503 if not loaded)
  3. find_nearest_stream_segment -> segment dict (404 if None)
  4. cg.find_catchment_at_point -> clicked_idx (404 if ValueError)
  5. cg.traverse_upstream -> upstream_indices (numpy array)
  6. cg.get_segment_indices -> segment_idxs list
  7. cg.aggregate_stats -> stats dict with area_km2
  8. merge_catchment_boundaries -> MultiPolygon (500 if None)
  9. boundary_to_polygon -> Polygon
 10. get_segment_outlet -> outlet coords
 11. stats["elevation_min_m"] -> outlet_elevation
 12. build_morph_dict_from_graph -> morph_dict
 13. Response with cell_count=0
"""

import contextlib
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import MultiPolygon, Polygon

from api.main import app
from core.catchment_graph import CatchmentGraph


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


def _make_mock_cg(area_km2: float = 10.0) -> MagicMock:
    """Create a mock CatchmentGraph with sensible defaults."""
    cg = MagicMock(spec=CatchmentGraph)
    cg.loaded = True
    cg.find_catchment_at_point.return_value = 0  # internal idx
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
    """Create a mock stream segment dict as returned by find_nearest_stream_segment."""
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


# Patch target prefix for the watershed endpoint module
_WS = "api.endpoints.watershed"


class TestDelineateWatershedEndpoint:
    """Tests for POST /api/delineate-watershed."""

    def _patch_all(
        self,
        cg=None,
        segment=None,
        boundary=None,
        morph=None,
    ):
        """Create a list of context managers for all required patches.

        Parameters
        ----------
        cg : MagicMock | None
            Mock CatchmentGraph instance (defaults to _make_mock_cg())
        segment : dict | None
            Mock segment dict (defaults to _make_segment())
        boundary : MultiPolygon | None
            Mock boundary geometry (defaults to _make_boundary())
        morph : dict | None
            Mock morphometric dict (defaults to _make_morph_dict())

        Returns
        -------
        list
            List of unittest.mock._patch context managers
        """
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
            patch(f"{_WS}.find_nearest_stream_segment", return_value=segment),
            patch(f"{_WS}.merge_catchment_boundaries", return_value=boundary),
            patch(
                f"{_WS}.get_segment_outlet",
                return_value={"x": 639139.0, "y": 486706.0},
            ),
            patch(f"{_WS}.build_morph_dict_from_graph", return_value=morph),
            patch(f"{_WS}.get_main_stream_geojson", return_value=None),
            patch(f"{_WS}.get_land_cover_for_boundary", return_value=None),
        ]

    def test_success_returns_200(self, client):
        """Test successful delineation returns 200."""
        with contextlib.ExitStack() as stack:
            for p in self._patch_all():
                stack.enter_context(p)

            response = client.post(
                "/api/delineate-watershed",
                json={"latitude": 52.23, "longitude": 21.01},
            )

        assert response.status_code == 200

    def test_response_structure(self, client):
        """Test response has correct structure."""
        with contextlib.ExitStack() as stack:
            for p in self._patch_all():
                stack.enter_context(p)

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

    def test_outlet_info_structure(self, client):
        """Test outlet info has correct structure."""
        with contextlib.ExitStack() as stack:
            for p in self._patch_all():
                stack.enter_context(p)

            response = client.post(
                "/api/delineate-watershed",
                json={"latitude": 52.23, "longitude": 21.01},
            )

        data = response.json()
        outlet = data["watershed"]["outlet"]

        assert "latitude" in outlet
        assert "longitude" in outlet
        assert "elevation_m" in outlet

    def test_boundary_is_valid_geojson(self, client):
        """Test that boundary is valid GeoJSON Feature with Polygon geometry."""
        with contextlib.ExitStack() as stack:
            for p in self._patch_all():
                stack.enter_context(p)

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

    def test_boundary_has_area_property(self, client):
        """Test that boundary GeoJSON has area_km2 property."""
        with contextlib.ExitStack() as stack:
            for p in self._patch_all():
                stack.enter_context(p)

            response = client.post(
                "/api/delineate-watershed",
                json={"latitude": 52.23, "longitude": 21.01},
            )

        data = response.json()
        geojson = data["watershed"]["boundary_geojson"]

        assert "area_km2" in geojson["properties"]

    def test_no_stream_returns_404(self, client):
        """Test that missing stream returns 404 with Polish error message."""
        cg = _make_mock_cg()

        patches = [
            patch(f"{_WS}.get_catchment_graph", return_value=cg),
            patch(f"{_WS}.find_nearest_stream_segment", return_value=None),
        ]

        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)

            response = client.post(
                "/api/delineate-watershed",
                json={"latitude": 52.0, "longitude": 21.0},
            )

        assert response.status_code == 404
        assert "Nie znaleziono cieku" in response.json()["detail"]

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

    def test_small_watershed_hydrograph_available(self, client):
        """Test small watershed has hydrograph_available=True."""
        with contextlib.ExitStack() as stack:
            for p in self._patch_all():
                stack.enter_context(p)

            response = client.post(
                "/api/delineate-watershed",
                json={"latitude": 52.23, "longitude": 21.01},
            )

        data = response.json()
        assert data["watershed"]["hydrograph_available"] is True

    def test_large_watershed_hydrograph_unavailable(self, client):
        """Test large watershed has hydrograph_available=False."""
        area_km2 = 300.0
        cg = _make_mock_cg(area_km2=area_km2)
        morph = _make_morph_dict(area_km2=area_km2)

        with contextlib.ExitStack() as stack:
            for p in self._patch_all(cg=cg, morph=morph):
                stack.enter_context(p)

            response = client.post(
                "/api/delineate-watershed",
                json={"latitude": 52.23, "longitude": 21.01},
            )

        data = response.json()
        assert data["watershed"]["hydrograph_available"] is False
        assert data["watershed"]["area_km2"] == 300.0

    def test_cell_count_is_zero(self, client):
        """Test cell_count is 0 for graph-based approach."""
        with contextlib.ExitStack() as stack:
            for p in self._patch_all():
                stack.enter_context(p)

            response = client.post(
                "/api/delineate-watershed",
                json={"latitude": 52.23, "longitude": 21.01},
            )

        data = response.json()
        assert data["watershed"]["cell_count"] == 0

    def test_area_calculation_correct(self, client):
        """Test that area_km2 matches the value from CatchmentGraph stats."""
        area_km2 = 45.67
        cg = _make_mock_cg(area_km2=area_km2)
        morph = _make_morph_dict(area_km2=area_km2)

        with contextlib.ExitStack() as stack:
            for p in self._patch_all(cg=cg, morph=morph):
                stack.enter_context(p)

            response = client.post(
                "/api/delineate-watershed",
                json={"latitude": 52.23, "longitude": 21.01},
            )

        data = response.json()
        assert data["watershed"]["area_km2"] == 45.67
