"""
Integration tests for watershed delineation endpoint.

Tests the GET /api/v1/watershed/delineate route (command `watershed delineate`)
using mocked CatchmentGraph and watershed_service functions. The command's
flow is:
  1. Transform coords (WGS84 -> PL-1992)
  2. Get CatchmentGraph (503 if not loaded)
  3. cg.find_catchment_at_point -> clicked_idx (404 if ValueError)
  4. cg._segment_idx[clicked_idx] -> segment_idx
  5. get_stream_info_by_segment_idx -> segment dict
  6. cg.traverse_upstream -> upstream_indices (numpy array)
  7. cg.get_segment_indices -> segment_idxs list
  8. cg.aggregate_stats -> stats dict with area_km2
  9. merge_catchment_boundaries -> MultiPolygon (500 if None)
 10. boundary_to_polygon -> Polygon
 11. get_segment_outlet -> outlet coords
 12. stats["elevation_min_m"] -> outlet_elevation
 13. build_morph_dict_from_graph -> morph_dict
"""

import contextlib
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from rasterio.transform import from_origin
from shapely.geometry import MultiPolygon, Polygon, box

from api.main import app
from core.catchment_graph import CatchmentGraph
from core.config import Settings
from core.constants import DEFAULT_THRESHOLD_M2
from core.raster_service import MAX_WINDOW_CELLS
from utils.geometry import transform_wgs84_to_pl1992


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


def _make_segment() -> dict[str, Any]:
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


def _make_morph_dict(area_km2: float = 10.0) -> dict[str, Any]:
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
    """Tests for GET /api/v1/watershed/delineate."""

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
            patch(f"{_WS}.loaded_catchment_graph", return_value=cg),
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
            patch(f"{_WS}.cascade_escalate", return_value=None),
            patch(f"{_WS}.thiessen_cells", return_value=[]),
        ]

    def test_success_returns_200(self, client):
        """Test successful delineation returns 200."""
        with contextlib.ExitStack() as stack:
            for p in self._patch_all():
                stack.enter_context(p)

            response = client.get(
                "/api/v1/watershed/delineate",
                params={"latitude": 52.23, "longitude": 21.01, "threshold_m2": 10000},
            )

        assert response.status_code == 200
        assert response.headers["cache-control"] == "public, max-age=3600"

    def test_response_structure(self, client):
        """Test response has correct structure."""
        with contextlib.ExitStack() as stack:
            for p in self._patch_all():
                stack.enter_context(p)

            response = client.get(
                "/api/v1/watershed/delineate",
                params={"latitude": 52.23, "longitude": 21.01, "threshold_m2": 10000},
            )

        data = response.json()["result"]
        assert "watershed" in data
        assert "boundary_geojson" in data["watershed"]
        assert "outlet" in data["watershed"]
        assert "area_km2" in data["watershed"]
        assert "hydrograph_available" in data["watershed"]

    def test_outlet_info_structure(self, client):
        """Test outlet info has correct structure."""
        with contextlib.ExitStack() as stack:
            for p in self._patch_all():
                stack.enter_context(p)

            response = client.get(
                "/api/v1/watershed/delineate",
                params={"latitude": 52.23, "longitude": 21.01, "threshold_m2": 10000},
            )

        data = response.json()["result"]
        outlet = data["watershed"]["outlet"]

        assert "latitude" in outlet
        assert "longitude" in outlet
        assert "elevation_m" in outlet

    def test_boundary_is_valid_geojson(self, client):
        """Test that boundary is valid GeoJSON Feature with Polygon geometry."""
        with contextlib.ExitStack() as stack:
            for p in self._patch_all():
                stack.enter_context(p)

            response = client.get(
                "/api/v1/watershed/delineate",
                params={"latitude": 52.23, "longitude": 21.01, "threshold_m2": 10000},
            )

        data = response.json()["result"]
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

            response = client.get(
                "/api/v1/watershed/delineate",
                params={"latitude": 52.23, "longitude": 21.01, "threshold_m2": 10000},
            )

        data = response.json()["result"]
        geojson = data["watershed"]["boundary_geojson"]

        assert "area_km2" in geojson["properties"]

    def test_no_stream_returns_404(self, client):
        """Test that a missing catchment returns 404 ``not_found``."""
        cg = _make_mock_cg()
        cg.find_catchment_at_point.side_effect = ValueError(
            "Nie znaleziono zlewni cząstkowej"
        )

        patches = [
            patch(f"{_WS}.loaded_catchment_graph", return_value=cg),
        ]

        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)

            response = client.get(
                "/api/v1/watershed/delineate",
                params={"latitude": 52.0, "longitude": 21.0, "threshold_m2": 10000},
            )

        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
        assert response.json()["details"]["reason"] == "no_catchment_at_point"

    def test_invalid_latitude_too_high_returns_400(self, client):
        """Test that latitude > 90 returns 400."""
        response = client.get(
            "/api/v1/watershed/delineate",
            params={"latitude": 100.0, "longitude": 21.0},
        )

        assert response.status_code == 400

    def test_invalid_latitude_too_low_returns_400(self, client):
        """Test that latitude < -90 returns 400."""
        response = client.get(
            "/api/v1/watershed/delineate",
            params={"latitude": -100.0, "longitude": 21.0},
        )

        assert response.status_code == 400

    def test_invalid_longitude_too_high_returns_400(self, client):
        """Test that longitude > 180 returns 400."""
        response = client.get(
            "/api/v1/watershed/delineate",
            params={"latitude": 52.0, "longitude": 200.0},
        )

        assert response.status_code == 400

    def test_invalid_longitude_too_low_returns_400(self, client):
        """Test that longitude < -180 returns 400."""
        response = client.get(
            "/api/v1/watershed/delineate",
            params={"latitude": 52.0, "longitude": -200.0},
        )

        assert response.status_code == 400

    def test_missing_latitude_returns_400(self, client):
        """Test that missing latitude returns 400."""
        response = client.get(
            "/api/v1/watershed/delineate",
            params={"longitude": 21.0},
        )

        assert response.status_code == 400

    def test_missing_longitude_returns_400(self, client):
        """Test that missing longitude returns 400."""
        response = client.get(
            "/api/v1/watershed/delineate",
            params={"latitude": 52.0},
        )

        assert response.status_code == 400

    def test_empty_query_returns_400(self, client):
        """Test that an empty query string returns 400."""
        response = client.get(
            "/api/v1/watershed/delineate",
            params={},
        )

        assert response.status_code == 400

    def test_small_watershed_hydrograph_available(self, client):
        """Test small watershed has hydrograph_available=True."""
        with contextlib.ExitStack() as stack:
            for p in self._patch_all():
                stack.enter_context(p)

            response = client.get(
                "/api/v1/watershed/delineate",
                params={"latitude": 52.23, "longitude": 21.01, "threshold_m2": 10000},
            )

        data = response.json()["result"]
        assert data["watershed"]["hydrograph_available"] is True

    def test_large_watershed_hydrograph_unavailable(self, client):
        """Test large watershed has hydrograph_available=False."""
        area_km2 = 300.0
        cg = _make_mock_cg(area_km2=area_km2)
        morph = _make_morph_dict(area_km2=area_km2)

        with contextlib.ExitStack() as stack:
            for p in self._patch_all(cg=cg, morph=morph):
                stack.enter_context(p)

            response = client.get(
                "/api/v1/watershed/delineate",
                params={"latitude": 52.23, "longitude": 21.01, "threshold_m2": 10000},
            )

        data = response.json()["result"]
        assert data["watershed"]["hydrograph_available"] is False
        assert data["watershed"]["area_km2"] == 300.0

    def test_area_calculation_correct(self, client):
        """Test that area_km2 matches the value from CatchmentGraph stats."""
        area_km2 = 45.67
        cg = _make_mock_cg(area_km2=area_km2)
        morph = _make_morph_dict(area_km2=area_km2)

        with contextlib.ExitStack() as stack:
            for p in self._patch_all(cg=cg, morph=morph):
                stack.enter_context(p)

            response = client.get(
                "/api/v1/watershed/delineate",
                params={"latitude": 52.23, "longitude": 21.01, "threshold_m2": 10000},
            )

        data = response.json()["result"]
        assert data["watershed"]["area_km2"] == 45.67

    def test_precomputed_mode_has_segments(self, client):
        """Test precomputed mode (threshold_m2 provided) returns upstream segments."""
        with contextlib.ExitStack() as stack:
            for p in self._patch_all():
                stack.enter_context(p)

            response = client.get(
                "/api/v1/watershed/delineate",
                params={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "threshold_m2": 10000,
                },
            )

        data = response.json()["result"]
        assert data["mode"] == "precomputed"
        assert data["upstream_segment_indices"] is not None
        assert len(data["upstream_segment_indices"]) > 0
        assert data["display_threshold_m2"] is not None

    def test_precomputed_mode_small_area(self, client):
        """Test precomputed mode with small area still returns mode='precomputed'."""
        area_km2 = 0.005  # 5000 m²
        cg = _make_mock_cg(area_km2=area_km2)
        morph = _make_morph_dict(area_km2=area_km2)

        with contextlib.ExitStack() as stack:
            for p in self._patch_all(cg=cg, morph=morph):
                stack.enter_context(p)

            response = client.get(
                "/api/v1/watershed/delineate",
                params={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "threshold_m2": 10000,
                },
            )

        data = response.json()["result"]
        assert data["mode"] == "precomputed"
        assert data["upstream_segment_indices"] is not None

    def test_precise_mode_refuses_a_watershed_too_large_for_its_window(
        self, client, tmp_path
    ):
        """The window of the precomputed watershed of the point, 80 km across,
        holds more than MAX_WINDOW_CELLS cells of the rasters: 422."""
        point = transform_wgs84_to_pl1992(52.23, 21.01)
        x, y = point.x, point.y
        transform = from_origin(x - 100.0, y + 100.0, 10.0, 10.0)
        for name, values, nodata in (
            ("dem_mosaic_03_flowdir.tif", np.zeros((20, 20), np.int16), 0),
            ("dem_mosaic_01_dem.tif", np.full((20, 20), 100.0, np.float32), -9999.0),
        ):
            with rasterio.open(
                tmp_path / name,
                "w",
                driver="GTiff",
                height=20,
                width=20,
                count=1,
                dtype=values.dtype,
                crs="EPSG:2180",
                transform=transform,
                nodata=nodata,
            ) as dst:
                dst.write(values, 1)
        settings = Settings(dem_dir=str(tmp_path), dem_path="")
        extent = (x - 40_000.0, y - 40_000.0, x + 40_000.0, y + 40_000.0)

        with (
            patch(f"{_WS}.loaded_catchment_graph", return_value=_make_mock_cg()),
            patch(f"{_WS}.catchments_bounds", return_value=extent),
            patch("core.raster_service.get_settings", return_value=settings),
        ):
            response = client.get(
                "/api/v1/watershed/delineate",
                params={"latitude": 52.23, "longitude": 21.01},
                headers={"Accept-Language": "pl"},
            )

        assert response.status_code == 422
        problem = response.json()
        assert problem["code"] == "unsupported"
        assert problem["details"]["reason"] == "window_too_large"
        assert problem["details"]["max_cells"] == MAX_WINDOW_CELLS
        assert problem["detail"].startswith("Zlewnia tego punktu jest za duża")


class TestOutletFarFromThePoint:
    """snap_distance_m and the notice of an outlet far from the point (E7-GAP-04)."""

    _POINT = {"latitude": 52.23, "longitude": 21.01}

    def _get(self, client, outlets, cg=None, escalation=None):
        """GET a precomputed delineation whose segments end east of the point.

        ``outlets`` maps (segment_idx, threshold_m2) to the distance east of the point
        [m] where that segment ends; the boundary holds every end. Returns the point
        and the envelope, whose ``notices`` hold the notice of a far outlet.
        """
        point = transform_wgs84_to_pl1992(**self._POINT)
        ends = {key: (point.x + east, point.y) for key, east in outlets.items()}
        boundary = MultiPolygon(
            [box(x - 50, y - 50, x + 50, y + 50) for x, y in ends.values()]
        )

        def outlet(segment_idx, threshold_m2, db):
            x, y = ends[(segment_idx, threshold_m2)]
            return {"x": x, "y": y}

        patches = [
            patch(f"{_WS}.loaded_catchment_graph", return_value=cg or _make_mock_cg()),
            patch(
                f"{_WS}.get_stream_info_by_segment_idx", return_value=_make_segment()
            ),
            patch(f"{_WS}.merge_catchment_boundaries", return_value=boundary),
            patch(f"{_WS}.get_segment_outlet", side_effect=outlet),
            patch(
                f"{_WS}.build_morph_dict_from_graph", return_value=_make_morph_dict()
            ),
            patch(f"{_WS}.get_main_stream_geojson", return_value=None),
            patch(f"{_WS}.get_main_channel_feature_collection", return_value=None),
            patch(f"{_WS}.build_land_cover_stats", return_value=None),
            patch(f"{_WS}.build_hsg_stats", return_value=None),
            patch(f"{_WS}.cascade_escalate", return_value=escalation),
            patch(f"{_WS}.thiessen_cells", return_value=[]),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            response = client.get(
                "/api/v1/watershed/delineate",
                params={**self._POINT, "threshold_m2": 10000},
            )
        assert response.status_code == 200
        return point, response.json()

    def test_an_outlet_500_m_away_is_given_without_a_notice(self, client):
        _, envelope = self._get(client, {(12, 10000): 500.0})

        assert envelope["result"]["snap_distance_m"] == pytest.approx(500.0, abs=0.1)
        assert envelope["notices"] == []

    @pytest.mark.parametrize(
        ("east_m", "distance"), [(500.2, "500 m"), (620.0, "620 m"), (1630.0, "1,6 km")]
    )
    def test_an_outlet_beyond_500_m_comes_with_a_warning_of_its_distance(
        self, client, east_m, distance
    ):
        _, envelope = self._get(client, {(12, 10000): east_m})

        assert envelope["result"]["snap_distance_m"] == pytest.approx(east_m, abs=0.1)
        # The notice is the envelope's, not a member of the result (ADR-091)
        assert "notices" not in envelope["result"]
        [notice] = envelope["notices"]
        assert (notice["level"], notice["code"]) == ("warning", "outlet_far_from_point")
        assert f"leży {distance} od wskazanego punktu" in notice["message"]

    def test_after_a_cascade_the_outlet_ends_the_coarser_segment(self, client):
        """The merged sub-catchments of 10 ha close 1.63 km down, not 100 m."""
        cg = _make_mock_cg()
        cg.get_segment_idx.side_effect = {0: 12, 7: 5}.get
        stats = {"area_km2": 12.0, "elevation_min_m": 110.0}
        escalation = ([5, 6], 100000, np.array([7, 8]), 7, stats, 12.0)

        point, envelope = self._get(
            client,
            {(12, 10000): 100.0, (5, 100000): 1630.0},
            cg=cg,
            escalation=escalation,
        )

        data = envelope["result"]
        outlet = data["watershed"]["outlet"]
        outlet_2180 = transform_wgs84_to_pl1992(outlet["latitude"], outlet["longitude"])
        assert outlet_2180.x == pytest.approx(point.x + 1630.0, abs=0.01)
        assert outlet_2180.y == pytest.approx(point.y, abs=0.01)
        assert data["snap_distance_m"] == pytest.approx(1630.0, abs=0.1)
        assert [n["code"] for n in envelope["notices"]] == ["outlet_far_from_point"]


class TestDelineateWatershedPreview:
    """Tests for GET /api/v1/watershed/preview.

    The preview must show the sub-catchments the delineation merges: same
    threshold floor, clicked sub-catchment and cascade, then one geometry
    request for the merged set in BFS order with depths.
    """

    _URL = "/api/v1/watershed/preview"
    _LEVELS = {"type": "FeatureCollection", "features": []}

    def _get(self, client, cg, threshold_m2=10000, escalation=None):
        """GET a preview with the graph, cascade and geometry query mocked."""
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch(f"{_WS}.loaded_catchment_graph", return_value=cg))
            stack.enter_context(
                patch(f"{_WS}.cascade_escalate", return_value=escalation)
            )
            levels = stack.enter_context(
                patch(
                    f"{_WS}.get_catchment_levels_feature_collection",
                    return_value=self._LEVELS,
                )
            )
            response = client.get(
                self._URL,
                params={
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "threshold_m2": threshold_m2,
                },
            )
        return response, levels

    def test_levels_of_the_clicked_subcatchment(self, client):
        """Without cascade the preview starts at the clicked sub-catchment."""
        cg = _make_mock_cg()
        cg.upstream_segments_by_depth.return_value = ([12, 10, 11], [0, 1, 1])

        response, levels = self._get(client, cg)

        assert response.status_code == 200
        data = response.json()["result"]
        assert data["threshold_m2"] == 10000
        assert data["segment_count"] == 3
        assert data["catchments"] == self._LEVELS
        cg.upstream_segments_by_depth.assert_called_once_with(0)
        segment_idxs, depths, threshold = levels.call_args[0][:3]
        assert (segment_idxs, depths, threshold) == ([12, 10, 11], [0, 1, 1], 10000)

    def test_cascade_previews_the_merged_threshold(self, client):
        """After a cascade the preview shows the coarser sub-catchments merged."""
        cg = _make_mock_cg()
        cg.upstream_segments_by_depth.return_value = ([6, 5], [0, 1])
        escalation = ([5, 6], 100000, np.array([7, 8]), 7, {"area_km2": 12.0}, 12.0)

        response, levels = self._get(client, cg, escalation=escalation)

        assert response.status_code == 200
        data = response.json()["result"]
        assert data["threshold_m2"] == 100000
        assert data["segment_count"] == 2
        cg.upstream_segments_by_depth.assert_called_once_with(7)
        assert levels.call_args[0][2] == 100000

    def test_threshold_below_floor_uses_default(self, client):
        """Thresholds below the default floor select at the default, as delineation."""
        cg = _make_mock_cg()
        cg.upstream_segments_by_depth.return_value = ([12], [0])

        response, _ = self._get(client, cg, threshold_m2=1000)

        assert response.status_code == 200
        assert response.json()["result"]["threshold_m2"] == DEFAULT_THRESHOLD_M2
        assert cg.find_catchment_at_point.call_args[0][2] == DEFAULT_THRESHOLD_M2

    def test_caps_subcatchments_nearest_outlet(self, client):
        """Above the cap only the sub-catchments nearest the outlet are drawn."""
        cg = _make_mock_cg()
        cg.upstream_segments_by_depth.return_value = ([12, 10, 11], [0, 1, 2])

        with patch(f"{_WS}._PREVIEW_MAX_CATCHMENTS", 2):
            response, levels = self._get(client, cg)

        assert response.status_code == 200
        assert response.json()["result"]["segment_count"] == 3
        segment_idxs, depths = levels.call_args[0][:2]
        assert (segment_idxs, depths) == ([12, 10], [0, 1])

    def test_missing_threshold_returns_400(self, client):
        """Precise mode (no threshold) has no preview."""
        response = client.get(self._URL, params={"latitude": 52.23, "longitude": 21.01})

        assert response.status_code == 400
        problem = response.json()
        assert problem["code"] == "validation_error"
        assert problem["details"]["fields"] == ["/query/threshold_m2"]

    def test_no_subcatchment_returns_404(self, client):
        """A point outside the sub-catchments fails like the delineation."""
        cg = _make_mock_cg()
        cg.find_catchment_at_point.side_effect = ValueError(
            "Nie znaleziono zlewni cząstkowej"
        )

        response, levels = self._get(client, cg)

        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"
        problem = response.json()
        assert problem["code"] == "not_found"
        assert problem["details"]["reason"] == "no_catchment_at_point"
        levels.assert_not_called()

    def test_graph_not_loaded_returns_503(self, client):
        """No catchment graph (empty tables or a failed load) returns 503."""
        response, _ = self._get(client, None)

        assert response.status_code == 503
        assert response.json()["code"] == "store_unavailable"
