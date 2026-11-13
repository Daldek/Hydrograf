"""
Integration tests for terrain profile endpoint.
"""

import json
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from pyproj import Transformer
from rasterio.transform import from_origin

from api.main import app
from core.attribution import PMAXTP
from core.config import Settings

NODATA = -9999.0
# The line of most tests (WGS84) and the extent the DEM of `dem_settings` covers
LINE = [[21.0, 52.0], [21.01, 52.01]]
DEM_LON = (21.0, 21.015)
DEM_LAT = (52.0, 52.01)


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


def _write_dem(path, west, north, cell, values):
    """GeoTIFF in EPSG:2180 with the upper left corner (west, north)."""
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=from_origin(west, north, cell, cell),
        nodata=NODATA,
    ) as dst:
        dst.write(values.astype(np.float32), 1)


@pytest.fixture
def dem_settings(tmp_path):
    """Settings with a DEM of 10 m cells around the test lines."""
    to_2180 = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True)
    xs, ys = to_2180.transform(
        [DEM_LON[0], DEM_LON[1], DEM_LON[0], DEM_LON[1]],
        [DEM_LAT[0], DEM_LAT[0], DEM_LAT[1], DEM_LAT[1]],
    )
    west, north = min(xs) - 100.0, max(ys) + 100.0
    cols = int((max(xs) + 100.0 - west) // 10.0) + 1
    rows = int((north - min(ys) + 100.0) // 10.0) + 1
    values = np.tile(150.0 + 0.5 * np.arange(cols), (rows, 1))
    _write_dem(tmp_path / "dem.tif", west, north, 10.0, values)
    return Settings(dem_path=str(tmp_path / "dem.tif"))


def _post(client, settings, coordinates=LINE, **extra):
    """POST /api/terrain-profile of a LineString with the DEM of ``settings``."""
    with patch("api.endpoints.profile.get_settings", return_value=settings):
        return client.post(
            "/api/terrain-profile",
            json={
                "geometry": {"type": "LineString", "coordinates": coordinates},
                **extra,
            },
        )


class TestTerrainProfileEndpoint:
    """Tests for POST /api/terrain-profile."""

    def test_distances_and_elevations_lengths_match(self, client, dem_settings):
        """Test that distances and elevations arrays have same length."""
        response = _post(client, dem_settings, n_samples=5)

        assert response.status_code == 200
        data = response.json()
        assert len(data["distances_m"]) == len(data["elevations_m"])
        assert len(data["distances_m"]) == 5

    def test_total_length_positive(self, client, dem_settings):
        """Test that total_length_m is positive for a real line."""
        response = _post(client, dem_settings, n_samples=5)

        data = response.json()
        assert data["total_length_m"] > 0

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

    def test_line_off_the_dem_returns_404(self, client, dem_settings):
        """A line where the DEM has no data at any sample returns 404."""
        response = _post(
            client, dem_settings, coordinates=[[22.0, 53.0], [22.01, 53.01]]
        )

        assert response.status_code == 404
        assert response.json()["details"]["reason"] == "no_elevation_data"

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

    def test_default_n_samples(self, client, dem_settings):
        """Test that default n_samples is used when not specified."""
        response = _post(client, dem_settings)

        assert response.status_code == 200
        data = response.json()
        assert len(data["distances_m"]) == 100  # default n_samples

    def test_multi_point_linestring(self, client, dem_settings):
        """Test profile with multi-point LineString geometry."""
        response = _post(
            client,
            dem_settings,
            coordinates=[
                [21.0, 52.0],
                [21.005, 52.005],
                [21.01, 52.01],
                [21.015, 52.005],
            ],
            n_samples=5,
        )

        assert response.status_code == 200

    def test_cache_control_header(self, client, dem_settings):
        """Test that successful response includes Cache-Control header."""
        response = _post(client, dem_settings, n_samples=5)

        assert response.status_code == 200
        assert response.headers.get("cache-control") == "public, max-age=3600"

    def test_distances_start_at_zero(self, client, dem_settings):
        """Test that the first distance value is 0."""
        response = _post(client, dem_settings, n_samples=5)

        data = response.json()
        assert data["distances_m"][0] == 0.0

    def test_distances_monotonically_increasing(self, client, dem_settings):
        """Test that distances are monotonically increasing."""
        response = _post(client, dem_settings, n_samples=5)

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


class TestTerrainProfileDemSamples:
    """Each sample of the profile reads the DEM cell under it."""

    X0, Y_TOP, CELL, CELLS = 500000.0, 600000.0, 50.0, 60

    def test_each_sample_reads_its_cell_also_past_the_dem(self, client, tmp_path):
        """Every sample gets the value of its cell, a gap where there is none.

        One row of 60 cells of 50 m holding 100 + column, no data in column 30;
        the line runs from the centre of the first cell to 10 cells past the
        east edge, one sample per cell.
        """
        values = 100.0 + np.arange(self.CELLS, dtype=np.float64)
        values[30] = NODATA
        _write_dem(tmp_path / "dem.tif", self.X0, self.Y_TOP, self.CELL, values[None])
        settings = Settings(dem_path=str(tmp_path / "dem.tif"))
        to_wgs84 = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)
        y = self.Y_TOP - self.CELL / 2
        n_samples = self.CELLS + 10
        coords = [
            list(to_wgs84.transform(self.X0 + self.CELL / 2, y)),
            list(to_wgs84.transform(self.X0 + (n_samples - 0.5) * self.CELL, y)),
        ]

        response = _post(client, settings, coordinates=coords, n_samples=n_samples)

        assert response.status_code == 200
        data = response.json()
        gaps = [i == 30 or i >= self.CELLS for i in range(n_samples)]
        assert data["dem_gaps"] == gaps
        assert data["elevations_m"] == [
            0.0 if gap else 100.0 + i for i, gap in enumerate(gaps)
        ]


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
                            "attribution": list(PMAXTP.attribution),
                            "terms_notice": list(PMAXTP.terms_notice),
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

    def test_lines_of_the_results_whose_water_the_profile_shows(self, client, settings):
        data = self._post(client, settings, result_ids=["sfincs", "unknown"]).json()

        assert (data["attribution"], data["terms_notice"]) == (
            list(PMAXTP.attribution),
            list(PMAXTP.terms_notice),
        )

    def test_no_lines_without_water_levels(self, client, settings):
        data = self._post(client, settings).json()

        assert (data["attribution"], data["terms_notice"]) == ([], [])

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
