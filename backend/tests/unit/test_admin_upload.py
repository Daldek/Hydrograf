"""Tests for admin boundary upload endpoint."""

import json
import tempfile
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

# We test via the endpoint functions directly to avoid needing full app setup
from api.endpoints.admin import ALLOWED_BOUNDARY_EXTENSIONS


def _create_test_geojson_bytes() -> bytes:
    """Create a valid GeoJSON file content."""
    polygon = Polygon([
        (16.9, 52.4), (17.1, 52.4), (17.1, 52.5), (16.9, 52.5), (16.9, 52.4)
    ])
    gdf = gpd.GeoDataFrame(geometry=[polygon], crs="EPSG:4326")
    with tempfile.NamedTemporaryFile(suffix=".geojson", delete=False) as f:
        gdf.to_file(f.name, driver="GeoJSON")
        return Path(f.name).read_bytes()


class TestUploadBoundaryValidation:
    def test_allowed_extensions(self):
        """Verify whitelist of allowed extensions."""
        assert ".gpkg" in ALLOWED_BOUNDARY_EXTENSIONS
        assert ".geojson" in ALLOWED_BOUNDARY_EXTENSIONS
        assert ".json" in ALLOWED_BOUNDARY_EXTENSIONS
        assert ".zip" in ALLOWED_BOUNDARY_EXTENSIONS
        assert ".exe" not in ALLOWED_BOUNDARY_EXTENSIONS
        assert ".py" not in ALLOWED_BOUNDARY_EXTENSIONS

    def test_geojson_content_is_valid(self):
        """Test that our helper creates valid GeoJSON."""
        content = _create_test_geojson_bytes()
        data = json.loads(content)
        assert data["type"] == "FeatureCollection"
        assert len(data["features"]) == 1


class TestBootstrapStartRequestBoundary:
    """Test that BootstrapStartRequest accepts boundary fields."""

    def test_boundary_fields_in_model(self):
        from api.endpoints.admin import BootstrapStartRequest

        # Should accept boundary_file
        req = BootstrapStartRequest(boundary_file="test.geojson")
        assert req.boundary_file == "test.geojson"
        assert req.boundary_layer is None

    def test_boundary_with_layer(self):
        from api.endpoints.admin import BootstrapStartRequest

        req = BootstrapStartRequest(
            boundary_file="test.gpkg",
            boundary_layer="my_layer",
        )
        assert req.boundary_file == "test.gpkg"
        assert req.boundary_layer == "my_layer"

    def test_default_none(self):
        from api.endpoints.admin import BootstrapStartRequest

        req = BootstrapStartRequest(bbox="16.9,52.4,17.1,52.5")
        assert req.boundary_file is None
        assert req.boundary_layer is None
