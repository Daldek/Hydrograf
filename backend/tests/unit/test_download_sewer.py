"""Tests for scripts.download_sewer module."""

import pytest
import geopandas as gpd
from shapely.geometry import LineString, Point

from scripts.download_sewer import (
    load_from_file,
    load_sewer_data,
    _validate_crs,
    _detect_geometry_type,
)


@pytest.fixture
def sewer_lines_gpkg(tmp_path):
    """Create a minimal GPKG with sewer lines in EPSG:2180."""
    lines = gpd.GeoDataFrame(
        {
            "geometry": [
                LineString([(500000, 600000), (500050, 600000)]),
                LineString([(500050, 600000), (500100, 600000)]),
                LineString([(500050, 600050), (500050, 600000)]),
            ],
            "srednica_mm": [300, 400, 300],
        },
        crs="EPSG:2180",
    )
    path = tmp_path / "sewer.gpkg"
    lines.to_file(path, driver="GPKG", layer="kolektory")
    return path


@pytest.fixture
def sewer_lines_no_crs(tmp_path):
    """Create a GeoJSON with sewer lines but NO CRS."""
    lines = gpd.GeoDataFrame(
        {"geometry": [LineString([(0, 0), (1, 1)])]},
    )
    path = tmp_path / "sewer_no_crs.geojson"
    lines.to_file(path, driver="GeoJSON")
    return path


@pytest.fixture
def sewer_config_file(tmp_path, sewer_lines_gpkg):
    """Config dict for file source."""
    return {
        "sewer": {
            "enabled": True,
            "source": {
                "type": "file",
                "path": str(sewer_lines_gpkg),
                "lines_layer": "kolektory",
                "points_layer": None,
                "assumed_crs": None,
            },
            "attribute_mapping": {"diameter": "srednica_mm"},
        }
    }


class TestLoadFromFile:
    def test_loads_gpkg_lines(self, sewer_lines_gpkg):
        points, lines = load_from_file(str(sewer_lines_gpkg), lines_layer="kolektory")
        assert len(lines) == 3
        assert lines.crs.to_epsg() == 2180
        assert all(lines.geometry.geom_type == "LineString")

    def test_auto_detect_layer(self, sewer_lines_gpkg):
        points, lines = load_from_file(str(sewer_lines_gpkg), lines_layer=None)
        assert len(lines) == 3

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            load_from_file("/nonexistent/path.gpkg")


class TestValidateCrs:
    def test_valid_crs_passes(self, sewer_lines_gpkg):
        gdf = gpd.read_file(sewer_lines_gpkg)
        result = _validate_crs(gdf, assumed_crs=None)
        assert result.crs.to_epsg() == 2180

    def test_no_crs_raises(self, sewer_lines_no_crs):
        gdf = gpd.read_file(sewer_lines_no_crs)
        gdf.crs = None
        with pytest.raises(ValueError, match="CRS"):
            _validate_crs(gdf, assumed_crs=None)

    def test_assumed_crs_fallback(self, sewer_lines_no_crs):
        gdf = gpd.read_file(sewer_lines_no_crs)
        gdf.crs = None
        result = _validate_crs(gdf, assumed_crs="EPSG:4326")
        assert result.crs is not None


class TestDetectGeometryType:
    def test_detects_linestring(self, sewer_lines_gpkg):
        gdf = gpd.read_file(sewer_lines_gpkg)
        assert _detect_geometry_type(gdf) == "lines"

    def test_detects_point(self):
        gdf = gpd.GeoDataFrame(
            {"geometry": [Point(0, 0), Point(1, 1)]}, crs="EPSG:2180"
        )
        assert _detect_geometry_type(gdf) == "points"


class TestLoadSewerData:
    def test_loads_with_config(self, sewer_config_file):
        points, lines = load_sewer_data(sewer_config_file)
        assert len(lines) == 3
        assert lines.crs.to_epsg() == 2180

    def test_reprojects_to_2180(self, tmp_path):
        lns = gpd.GeoDataFrame(
            {"geometry": [LineString([(17.0, 52.4), (17.1, 52.4)])]},
            crs="EPSG:4326",
        )
        path = tmp_path / "sewer_wgs84.gpkg"
        lns.to_file(path, driver="GPKG")
        cfg = {
            "sewer": {
                "source": {
                    "type": "file",
                    "path": str(path),
                    "lines_layer": None,
                    "points_layer": None,
                    "assumed_crs": None,
                },
                "attribute_mapping": {},
            }
        }
        points, lines = load_sewer_data(cfg)
        assert lines.crs.to_epsg() == 2180


class TestLoadSewerDataTupleReturn:
    def test_returns_tuple(self, tmp_path):
        gdf = gpd.GeoDataFrame(
            {"id": ["n1"], "role": ["outlet"], "geometry": [Point(500_000, 200_000)]},
            crs="EPSG:2180",
        )
        path = tmp_path / "test.gpkg"
        gdf.to_file(path, layer="nodes", driver="GPKG")

        config = {
            "sewer": {
                "source": {
                    "type": "file",
                    "path": str(path),
                    "points_layer": "nodes",
                    "format": "auto",
                },
                "field_mapping": {"node_id": "id", "node_role": "role"},
            }
        }
        result = load_sewer_data(config)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_points_only_returns_none_lines(self, tmp_path):
        gdf = gpd.GeoDataFrame(
            {"id": ["n1"], "role": ["outlet"], "geometry": [Point(500_000, 200_000)]},
            crs="EPSG:2180",
        )
        path = tmp_path / "test.gpkg"
        gdf.to_file(path, layer="nodes", driver="GPKG")

        config = {
            "sewer": {
                "source": {
                    "type": "file",
                    "path": str(path),
                    "points_layer": "nodes",
                    "format": "points_only",
                },
                "field_mapping": {"node_id": "id", "node_role": "role"},
            }
        }
        points, lines = load_sewer_data(config)
        assert points is not None
        assert lines is None


class TestAutoDetectFormat:
    def test_gpkg_two_layers_detected(self, tmp_path):
        from shapely.geometry import LineString as ShapelyLineString

        pts = gpd.GeoDataFrame(
            {"id": ["n1", "n2"], "role": ["inlet", "outlet"],
             "geometry": [Point(500_000, 200_000), Point(500_100, 200_100)]},
            crs="EPSG:2180",
        )
        lns = gpd.GeoDataFrame(
            {"from_node": ["n1"], "to_node": ["n2"],
             "geometry": [ShapelyLineString([(500_000, 200_000), (500_100, 200_100)])]},
            crs="EPSG:2180",
        )
        path = tmp_path / "sewer.gpkg"
        pts.to_file(path, layer="nodes", driver="GPKG")
        lns.to_file(path, layer="pipes", driver="GPKG")

        config = {
            "sewer": {
                "source": {
                    "type": "file",
                    "path": str(path),
                    "format": "auto",
                    "points_layer": "nodes",
                    "lines_layer": "pipes",
                },
                "field_mapping": {"node_id": "id", "node_role": "role"},
            }
        }
        points, lines = load_sewer_data(config)
        assert points is not None
        assert lines is not None
        assert len(lines) == 1
