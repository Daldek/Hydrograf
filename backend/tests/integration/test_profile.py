"""
Integration tests for terrain profile endpoint.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import app


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
            patch("api.endpoints.profile.os.path.exists", return_value=True),
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
            patch("api.endpoints.profile.os.path.exists", return_value=True),
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
            patch("api.endpoints.profile.os.path.exists", return_value=True),
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
            patch("api.endpoints.profile.os.path.exists", return_value=True),
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
            patch("api.endpoints.profile.os.path.exists", return_value=True),
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
        assert "LineString" in response.json()["detail"]

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
        assert "2 coordinates" in response.json()["detail"]

    def test_nodata_result_returns_404(self, client, mock_rasterio_nodata):
        """Test that all-nodata profile result returns 404."""
        with (
            patch("api.endpoints.profile.os.path.exists", return_value=True),
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
        with patch("api.endpoints.profile.os.path.exists", return_value=False):
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
        assert "DEM" in response.json()["detail"]

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
            patch("api.endpoints.profile.os.path.exists", return_value=True),
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
            patch("api.endpoints.profile.os.path.exists", return_value=True),
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
            patch("api.endpoints.profile.os.path.exists", return_value=True),
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
            patch("api.endpoints.profile.os.path.exists", return_value=True),
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
            patch("api.endpoints.profile.os.path.exists", return_value=True),
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
