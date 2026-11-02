"""
Integration tests for terrain profile endpoint.
"""

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from pyproj import Transformer
from rasterio.transform import from_origin

from api.main import app
from core.config import Settings


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


def _make_rasterio_ctx(mock_dataset):
    """Wrap a mock dataset in a context manager mimicking rasterio.open()."""

    @contextmanager
    def _open(*_args, **_kwargs):
        yield mock_dataset

    return _open


@pytest.fixture
def mock_rasterio_dataset():
    """Create a mock rasterio dataset that returns elevation data."""
    mock_dataset = MagicMock()
    mock_dataset.nodata = -9999.0

    # Return realistic elevation values for each sample point
    def sample_generator(points):
        for i, _ in enumerate(points):
            yield np.array([150.0 + i * 5.0])

    mock_dataset.sample = sample_generator
    return mock_dataset


@pytest.fixture
def mock_rasterio_nodata():
    """Create a mock rasterio dataset that returns all nodata."""
    mock_dataset = MagicMock()
    mock_dataset.nodata = -9999.0

    def sample_generator(points):
        for _ in points:
            yield np.array([-9999.0])

    mock_dataset.sample = sample_generator
    return mock_dataset


class TestTerrainProfileEndpoint:
    """Tests for POST /api/terrain-profile."""

    def test_success_returns_200(self, client, mock_rasterio_dataset):
        """Test successful profile extraction returns 200."""
        with (
            patch("os.path.exists", return_value=True),
            patch(
                "api.endpoints.profile.rasterio.open",
                new=_make_rasterio_ctx(mock_rasterio_dataset),
            ),
        ):
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

    def test_response_structure(self, client, mock_rasterio_dataset):
        """Test response has correct structure."""
        with (
            patch("os.path.exists", return_value=True),
            patch(
                "api.endpoints.profile.rasterio.open",
                new=_make_rasterio_ctx(mock_rasterio_dataset),
            ),
        ):
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

    def test_distances_and_elevations_lengths_match(
        self, client, mock_rasterio_dataset
    ):
        """Test that distances and elevations arrays have same length."""
        with (
            patch("os.path.exists", return_value=True),
            patch(
                "api.endpoints.profile.rasterio.open",
                new=_make_rasterio_ctx(mock_rasterio_dataset),
            ),
        ):
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

    def test_total_length_positive(self, client, mock_rasterio_dataset):
        """Test that total_length_m is positive for a real line."""
        with (
            patch("os.path.exists", return_value=True),
            patch(
                "api.endpoints.profile.rasterio.open",
                new=_make_rasterio_ctx(mock_rasterio_dataset),
            ),
        ):
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
        assert data["total_length_m"] > 0

    def test_elevations_are_floats(self, client, mock_rasterio_dataset):
        """Test that elevation values are numeric."""
        with (
            patch("os.path.exists", return_value=True),
            patch(
                "api.endpoints.profile.rasterio.open",
                new=_make_rasterio_ctx(mock_rasterio_dataset),
            ),
        ):
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

    def test_non_linestring_returns_400(self, client):
        """Test that non-LineString geometry returns 400."""
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
        assert response.json()["details"]["reason"] == "invalid_geometry_type"

    def test_too_few_coordinates_returns_400(self, client):
        """Test that LineString with < 2 coordinates returns 400."""
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
        assert response.json()["details"]["reason"] == "too_few_coordinates"

    def test_nodata_result_returns_404(self, client, mock_rasterio_nodata):
        """Test that all-nodata profile result returns 404."""
        with (
            patch("os.path.exists", return_value=True),
            patch(
                "api.endpoints.profile.rasterio.open",
                new=_make_rasterio_ctx(mock_rasterio_nodata),
            ),
        ):
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

    def test_dem_not_found_returns_503(self, client):
        """Test that missing DEM file returns 503."""
        with patch("os.path.exists", return_value=False):
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

        assert response.status_code == 503
        assert response.json()["code"] == "store_unavailable"
        assert response.json()["details"]["reason"] == "dem_unavailable"

    def test_n_samples_too_low_returns_400(self, client):
        """Test that n_samples < 2 returns 400."""
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

        assert response.status_code == 400

    def test_n_samples_too_high_returns_400(self, client):
        """Test that n_samples > 1000 returns 400."""
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

        assert response.status_code == 400

    def test_missing_geometry_returns_400(self, client):
        """Test that missing geometry returns 400."""
        response = client.post(
            "/api/terrain-profile",
            json={"n_samples": 5},
        )

        assert response.status_code == 400

    def test_default_n_samples(self, client, mock_rasterio_dataset):
        """Test that default n_samples is used when not specified."""
        # Mock dataset that works for any number of sample points
        mock_ds = MagicMock()
        mock_ds.nodata = -9999.0

        def sample_gen(points):
            for i, _ in enumerate(points):
                yield np.array([150.0 + i * 0.5])

        mock_ds.sample = sample_gen

        with (
            patch("os.path.exists", return_value=True),
            patch(
                "api.endpoints.profile.rasterio.open",
                new=_make_rasterio_ctx(mock_ds),
            ),
        ):
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
        data = response.json()
        assert len(data["distances_m"]) == 100  # default n_samples

    def test_multi_point_linestring(self, client, mock_rasterio_dataset):
        """Test profile with multi-point LineString geometry."""
        with (
            patch("os.path.exists", return_value=True),
            patch(
                "api.endpoints.profile.rasterio.open",
                new=_make_rasterio_ctx(mock_rasterio_dataset),
            ),
        ):
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

    def test_cache_control_header(self, client, mock_rasterio_dataset):
        """Test that successful response includes Cache-Control header."""
        with (
            patch("os.path.exists", return_value=True),
            patch(
                "api.endpoints.profile.rasterio.open",
                new=_make_rasterio_ctx(mock_rasterio_dataset),
            ),
        ):
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
        assert response.headers.get("cache-control") == "public, max-age=3600"

    def test_distances_start_at_zero(self, client, mock_rasterio_dataset):
        """Test that the first distance value is 0."""
        with (
            patch("os.path.exists", return_value=True),
            patch(
                "api.endpoints.profile.rasterio.open",
                new=_make_rasterio_ctx(mock_rasterio_dataset),
            ),
        ):
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
        assert data["distances_m"][0] == 0.0

    def test_distances_monotonically_increasing(self, client, mock_rasterio_dataset):
        """Test that distances are monotonically increasing."""
        with (
            patch("os.path.exists", return_value=True),
            patch(
                "api.endpoints.profile.rasterio.open",
                new=_make_rasterio_ctx(mock_rasterio_dataset),
            ),
        ):
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
        distances = data["distances_m"]
        for i in range(1, len(distances)):
            assert distances[i] > distances[i - 1]

    def test_503_does_not_leak_server_path(self, client):
        """503 error must not contain server filesystem paths (CR8)."""
        with patch("os.path.exists", return_value=False):
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

        assert response.status_code == 503
        body = response.text
        assert "/data/" not in body
        assert ".vrt" not in body


class TestTerrainProfileWaterLevels:
    """Water levels of analysis results in POST /api/terrain-profile."""

    X0, Y_TOP, CELL, NODATA = 500000.0, 600000.0, 5.0, -9999.0

    def _raster(self, path, row):
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            height=1,
            width=len(row),
            count=1,
            dtype="float32",
            crs="EPSG:2180",
            transform=from_origin(self.X0, self.Y_TOP, self.CELL, self.CELL),
            nodata=self.NODATA,
        ) as dst:
            dst.write(np.array([row], dtype=np.float32), 1)

    @pytest.fixture
    def settings(self, tmp_path):
        """DEM with a gap in the last cell; result 'sfincs' dry in the second."""
        self._raster(tmp_path / "dem.tif", [100.0, 100.0, 100.0, self.NODATA])
        result_dir = tmp_path / "data" / "results" / "sfincs"
        result_dir.mkdir(parents=True)
        self._raster(result_dir / "wse_max.tif", [101.5, self.NODATA, 102.0, 102.0])
        (tmp_path / "data" / "results" / "index.json").write_text(
            json.dumps(
                {
                    "schema": "hydrograf-results/1",
                    "results": [
                        {
                            "id": "sfincs",
                            "water_level": {
                                "path": "/data/results/sfincs/wse_max.tif",
                                "crs": "EPSG:2180",
                                "unit": "m n.p.m.",
                            },
                        }
                    ],
                }
            )
        )
        return Settings(
            dem_path=str(tmp_path / "dem.tif"),
            frontend_data_dir=str(tmp_path / "data"),
        )

    def _post(self, client, settings, **extra):
        """Line through the centres of the four cells, one sample per cell."""
        to_wgs84 = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)
        y = self.Y_TOP - self.CELL / 2
        coords = [
            list(to_wgs84.transform(self.X0 + self.CELL / 2, y)),
            list(to_wgs84.transform(self.X0 + 3.5 * self.CELL, y)),
        ]
        with patch("api.endpoints.profile.get_settings", return_value=settings):
            return client.post(
                "/api/terrain-profile",
                json={
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "n_samples": 4,
                    **extra,
                },
            )

    def test_levels_aligned_with_samples(self, client, settings):
        """Null where the result is dry and where the DEM has no data."""
        response = self._post(client, settings, result_ids=["sfincs", "unknown"])

        assert response.status_code == 200
        data = response.json()
        assert data["elevations_m"] == [100.0, 100.0, 100.0, 0.0]
        assert data["water_levels"] == [
            {"result_id": "sfincs", "levels_m": [101.5, None, 102.0, None]}
        ]

    def test_samples_without_dem_data_are_gaps_and_0_m_is_not(self, client, settings):
        """A nodata sample is a gap; an elevation of 0 m is not."""
        self._raster(settings.dem_path, [0.0, 12.5, self.NODATA, 12.5])

        response = self._post(client, settings)

        assert response.status_code == 200
        data = response.json()
        assert data["dem_gaps"] == [False, False, True, False]
        assert data["elevations_m"] == [0.0, 12.5, 0.0, 12.5]

    def test_too_many_result_ids_returns_400(self, client, settings):
        response = self._post(client, settings, result_ids=[f"r{i}" for i in range(21)])

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"
        problem = response.json()
        assert problem["code"] == "validation_error"
        assert problem["details"]["fields"] == ["/body/result_ids"]
