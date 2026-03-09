"""Tests for core.boundary module."""

import json
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import MultiPolygon, Point, Polygon

from core.boundary import (
    boundary_to_bbox_2180,
    boundary_to_bbox_wgs84,
    load_boundary,
    validate_boundary_file,
)


def _make_geojson_file(
    tmp_path: Path,
    geometry,
    crs="EPSG:4326",
    filename="test.geojson",
) -> Path:
    """Helper: create a GeoJSON file with given geometry."""
    gdf = gpd.GeoDataFrame(geometry=[geometry], crs=crs)
    path = tmp_path / filename
    gdf.to_file(path, driver="GeoJSON")
    return path


@pytest.fixture
def sample_polygon():
    """A small polygon around Poznan in WGS84."""
    return Polygon([
        (16.9, 52.4),
        (17.1, 52.4),
        (17.1, 52.5),
        (16.9, 52.5),
        (16.9, 52.4),
    ])


@pytest.fixture
def sample_polygon_2180():
    """A polygon in EPSG:2180 (Poland)."""
    return Polygon([
        (350000, 500000),
        (360000, 500000),
        (360000, 510000),
        (350000, 510000),
        (350000, 500000),
    ])


class TestLoadBoundary:
    def test_load_geojson_polygon(self, tmp_path, sample_polygon):
        path = _make_geojson_file(tmp_path, sample_polygon)
        result = load_boundary(path)
        assert result.geom_type in ("Polygon", "MultiPolygon")
        assert not result.is_empty

    def test_load_geojson_multipolygon(self, tmp_path, sample_polygon):
        # Two separate polygons
        poly2 = Polygon([
            (17.2, 52.4),
            (17.3, 52.4),
            (17.3, 52.5),
            (17.2, 52.5),
            (17.2, 52.4),
        ])
        multi = MultiPolygon([sample_polygon, poly2])
        path = _make_geojson_file(tmp_path, multi)
        result = load_boundary(path)
        assert result.geom_type in ("Polygon", "MultiPolygon")

    def test_load_gpkg(self, tmp_path, sample_polygon):
        gdf = gpd.GeoDataFrame(geometry=[sample_polygon], crs="EPSG:4326")
        path = tmp_path / "test.gpkg"
        gdf.to_file(path, driver="GPKG")
        result = load_boundary(path)
        assert result.geom_type in ("Polygon", "MultiPolygon")

    def test_reject_point_geometry(self, tmp_path):
        point = Point(17.0, 52.4)
        path = _make_geojson_file(tmp_path, point, filename="point.geojson")
        with pytest.raises(ValueError, match="No polygon geometries"):
            load_boundary(path)

    def test_reject_empty_file(self, tmp_path):
        # Create an empty GeoJSON
        empty_geojson = {"type": "FeatureCollection", "features": []}
        path = tmp_path / "empty.geojson"
        path.write_text(json.dumps(empty_geojson))
        with pytest.raises(ValueError, match="No features"):
            load_boundary(path)

    def test_crs_auto_detection_wgs84(self, tmp_path, sample_polygon):
        path = _make_geojson_file(tmp_path, sample_polygon, crs="EPSG:4326")
        result = load_boundary(path)
        # Should stay in WGS84 bounds
        bounds = result.bounds
        assert 16.0 < bounds[0] < 18.0  # lon
        assert 52.0 < bounds[1] < 53.0  # lat

    def test_crs_auto_detection_2180(self, tmp_path, sample_polygon_2180):
        """File in EPSG:2180 should be reprojected to WGS84."""
        path = _make_geojson_file(
            tmp_path,
            sample_polygon_2180,
            crs="EPSG:2180",
            filename="pl.geojson",
        )
        result = load_boundary(path)
        bounds = result.bounds
        # After reprojection, should be in WGS84 range
        assert 14.0 < bounds[0] < 25.0  # Poland lon range
        assert 49.0 < bounds[1] < 55.0  # Poland lat range

    def test_multi_feature_union(self, tmp_path):
        """Multiple features should be unioned into one geometry."""
        poly1 = Polygon([
            (16.9, 52.4),
            (17.0, 52.4),
            (17.0, 52.5),
            (16.9, 52.5),
            (16.9, 52.4),
        ])
        poly2 = Polygon([
            (17.0, 52.4),
            (17.1, 52.4),
            (17.1, 52.5),
            (17.0, 52.5),
            (17.0, 52.4),
        ])
        gdf = gpd.GeoDataFrame(geometry=[poly1, poly2], crs="EPSG:4326")
        path = tmp_path / "multi.geojson"
        gdf.to_file(path, driver="GeoJSON")
        result = load_boundary(path)
        # Union of adjacent polygons should be a single polygon
        assert result.geom_type == "Polygon"

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_boundary(Path("/nonexistent/file.geojson"))

    def test_file_too_large(self, tmp_path):
        """Files over 50 MB should be rejected."""
        path = tmp_path / "large.geojson"
        # Create a file that appears large (we'll check size validation)
        path.write_text("x" * (51 * 1024 * 1024))
        with pytest.raises(ValueError, match="too large"):
            load_boundary(path)

    def test_load_zip_shp(self, tmp_path, sample_polygon):
        """ZIP containing SHP should be loadable."""
        # Create shapefile
        shp_dir = tmp_path / "shp"
        shp_dir.mkdir()
        gdf = gpd.GeoDataFrame(geometry=[sample_polygon], crs="EPSG:4326")
        gdf.to_file(shp_dir / "test.shp")

        # ZIP it
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for f in shp_dir.iterdir():
                zf.write(f, f.name)

        result = load_boundary(zip_path)
        assert result.geom_type in ("Polygon", "MultiPolygon")


class TestBoundaryToBbox:
    def test_bbox_wgs84(self, sample_polygon):
        bbox = boundary_to_bbox_wgs84(sample_polygon)
        assert len(bbox) == 4
        assert bbox[0] == pytest.approx(16.9, abs=0.01)  # min_lon
        assert bbox[1] == pytest.approx(52.4, abs=0.01)  # min_lat
        assert bbox[2] == pytest.approx(17.1, abs=0.01)  # max_lon
        assert bbox[3] == pytest.approx(52.5, abs=0.01)  # max_lat

    def test_bbox_2180(self, sample_polygon):
        bbox = boundary_to_bbox_2180(sample_polygon)
        assert len(bbox) == 4
        # EPSG:2180 coords for Poland should be in this range
        assert 100_000 < bbox[0] < 900_000
        assert 100_000 < bbox[1] < 900_000


class TestValidateBoundaryFile:
    def test_validate_geojson(self, tmp_path, sample_polygon):
        path = _make_geojson_file(tmp_path, sample_polygon)
        result = validate_boundary_file(path)
        assert "crs" in result
        assert "n_features" in result
        assert result["n_features"] == 1
        assert "area_km2" in result
        assert result["area_km2"] > 0
        assert "bbox_wgs84" in result
        assert len(result["bbox_wgs84"]) == 4

    def test_validate_nonexistent(self):
        with pytest.raises(FileNotFoundError):
            validate_boundary_file(Path("/nonexistent.geojson"))
