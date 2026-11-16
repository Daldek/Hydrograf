"""
Unit tests for geometry utilities module.
"""

import pytest
from shapely.geometry import Point, Polygon

from utils.geometry import (
    pl2000_zone,
    polygon_to_geojson_feature,
    transform_pl1992_to_wgs84,
    transform_polygon_pl1992_to_wgs84,
    transform_wgs84_to_pl1992,
    transform_wgs84_to_pl2000,
)


class TestTransformWgs84ToPl1992:
    """Tests for WGS84 to PL-1992 transformation."""

    def test_returns_point(self):
        """Test that function returns Shapely Point."""
        result = transform_wgs84_to_pl1992(52.0, 21.0)

        assert isinstance(result, Point)

    def test_coordinates_in_pl1992_range(self):
        """Test that coordinates are in valid PL-1992 range."""
        # Warsaw area coordinates
        result = transform_wgs84_to_pl1992(52.23, 21.01)

        # PL-1992 valid range for Poland (roughly)
        assert 100000 < result.x < 900000
        assert 100000 < result.y < 900000

    def test_known_transformation_warsaw(self):
        """Test transformation against known values for Warsaw."""
        # Warsaw center approximately
        result = transform_wgs84_to_pl1992(52.23, 21.01)

        # Expected values approximately (within 10km)
        assert abs(result.x - 639000) < 10000
        assert abs(result.y - 487000) < 10000

    def test_known_transformation_krakow(self):
        """Test transformation against known values for Krakow."""
        # Krakow center approximately
        result = transform_wgs84_to_pl1992(50.06, 19.94)

        # Expected values approximately (within 10km)
        assert abs(result.x - 567000) < 10000
        assert abs(result.y - 243000) < 10000

    def test_different_locations_produce_different_results(self):
        """Test that different locations produce different coordinates."""
        result1 = transform_wgs84_to_pl1992(52.0, 21.0)
        result2 = transform_wgs84_to_pl1992(50.0, 19.0)

        assert result1.x != result2.x
        assert result1.y != result2.y


class TestTransformWgs84ToPl2000:
    """WGS84 to PL-2000: the zone follows the longitude."""

    @pytest.mark.parametrize(
        ("longitude", "zone"),
        [
            (12.0, 5),
            (16.4999, 5),
            (16.5, 6),
            (19.4999, 6),
            (19.5, 7),
            (22.4999, 7),
            (22.5, 8),
            (26.0, 8),
        ],
    )
    def test_zone_by_longitude(self, longitude, zone):
        """Zones change at 16.5°, 19.5° and 22.5°E; outside Poland the nearest."""
        assert pl2000_zone(longitude) == zone

    @pytest.mark.parametrize("zone", [5, 6, 7, 8])
    def test_easting_on_the_central_meridian(self, zone):
        """On the meridian 3·zone °E the easting is zone·10⁶ + 500 000 m."""
        result = transform_wgs84_to_pl2000(51.0, 3.0 * zone)

        easting_m = zone * 1_000_000 + 500_000
        assert result[:2] == (zone, pytest.approx(easting_m, abs=0.01))

    def test_both_sides_of_the_boundary_of_zones_5_and_6(self):
        """At 16.5°E a point 105 km east of 15°E becomes 105 km west of 18°E."""
        west = transform_wgs84_to_pl2000(51.0, 16.4999)
        east = transform_wgs84_to_pl2000(51.0, 16.5)

        assert west[:2] == (5, pytest.approx(5_605_279, abs=1))
        assert east[:2] == (6, pytest.approx(6_394_714, abs=1))
        assert west[2] == pytest.approx(east[2], abs=1)


class TestTransformPl1992ToWgs84:
    """Tests for PL-1992 to WGS84 transformation."""

    def test_returns_tuple(self):
        """Test that function returns tuple of (lon, lat)."""
        result = transform_pl1992_to_wgs84(500000, 600000)

        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_coordinates_in_wgs84_range(self):
        """Test that output coordinates are in WGS84 range."""
        lon, lat = transform_pl1992_to_wgs84(500000, 600000)

        assert -180 <= lon <= 180
        assert -90 <= lat <= 90

    def test_coordinates_in_poland(self):
        """Test that coordinates are within Poland bounds."""
        lon, lat = transform_pl1992_to_wgs84(500000, 400000)

        # Poland approximate bounds
        assert 14 < lon < 25
        assert 49 < lat < 55

    def test_roundtrip_transformation(self):
        """Test that WGS84 -> PL1992 -> WGS84 preserves coordinates."""
        original_lat, original_lon = 52.23, 21.01

        point_2180 = transform_wgs84_to_pl1992(original_lat, original_lon)
        result_lon, result_lat = transform_pl1992_to_wgs84(point_2180.x, point_2180.y)

        assert abs(result_lat - original_lat) < 0.0001
        assert abs(result_lon - original_lon) < 0.0001


class TestTransformPolygonPl1992ToWgs84:
    """Tests for polygon transformation."""

    def test_returns_polygon(self):
        """Test that function returns Shapely Polygon."""
        polygon_2180 = Polygon(
            [
                (500000, 600000),
                (500100, 600000),
                (500100, 600100),
                (500000, 600100),
                (500000, 600000),
            ]
        )

        result = transform_polygon_pl1992_to_wgs84(polygon_2180)

        assert isinstance(result, Polygon)

    def test_polygon_is_valid(self):
        """Test that transformed polygon is valid."""
        polygon_2180 = Polygon(
            [
                (500000, 600000),
                (500100, 600000),
                (500100, 600100),
                (500000, 600100),
                (500000, 600000),
            ]
        )

        result = transform_polygon_pl1992_to_wgs84(polygon_2180)

        assert result.is_valid

    def test_coordinates_in_wgs84_range(self):
        """Test that output coordinates are in WGS84 range."""
        polygon_2180 = Polygon(
            [
                (500000, 600000),
                (500100, 600000),
                (500100, 600100),
                (500000, 600100),
                (500000, 600000),
            ]
        )

        result = transform_polygon_pl1992_to_wgs84(polygon_2180)

        for lon, lat in result.exterior.coords:
            assert -180 <= lon <= 180
            assert -90 <= lat <= 90

    def test_preserves_polygon_structure(self):
        """Test that transformation preserves number of vertices."""
        polygon_2180 = Polygon(
            [
                (500000, 600000),
                (500100, 600000),
                (500100, 600100),
                (500000, 600100),
                (500000, 600000),
            ]
        )

        result = transform_polygon_pl1992_to_wgs84(polygon_2180)

        # Same number of coords (including closing point)
        assert len(result.exterior.coords) == len(polygon_2180.exterior.coords)

    def test_handles_polygon_with_holes(self):
        """Test transformation of polygon with interior rings (holes)."""
        exterior = [
            (500000, 600000),
            (500200, 600000),
            (500200, 600200),
            (500000, 600200),
            (500000, 600000),
        ]
        interior = [
            (500050, 600050),
            (500150, 600050),
            (500150, 600150),
            (500050, 600150),
            (500050, 600050),
        ]
        polygon_2180 = Polygon(exterior, [interior])

        result = transform_polygon_pl1992_to_wgs84(polygon_2180)

        assert len(result.interiors) == 1
        assert result.is_valid


class TestPolygonToGeojsonFeature:
    """Tests for GeoJSON conversion."""

    def test_returns_feature_dict(self):
        """Test that function returns valid GeoJSON Feature."""
        polygon = Polygon(
            [
                (21.0, 52.0),
                (21.1, 52.0),
                (21.1, 52.1),
                (21.0, 52.1),
                (21.0, 52.0),
            ]
        )

        result = polygon_to_geojson_feature(polygon)

        assert result["type"] == "Feature"
        assert "geometry" in result
        assert result["geometry"]["type"] == "Polygon"
        assert "properties" in result

    def test_includes_properties(self):
        """Test that properties are included."""
        polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])
        properties = {"area_km2": 45.3, "name": "Test watershed"}

        result = polygon_to_geojson_feature(polygon, properties)

        assert result["properties"]["area_km2"] == 45.3
        assert result["properties"]["name"] == "Test watershed"

    def test_empty_properties_when_none(self):
        """Test that properties is empty dict when None."""
        polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)])

        result = polygon_to_geojson_feature(polygon)

        assert result["properties"] == {}

    def test_geometry_has_coordinates(self):
        """Test that geometry includes coordinates array."""
        polygon = Polygon(
            [
                (21.0, 52.0),
                (21.1, 52.0),
                (21.1, 52.1),
                (21.0, 52.1),
                (21.0, 52.0),
            ]
        )

        result = polygon_to_geojson_feature(polygon)

        assert "coordinates" in result["geometry"]
        # mapping() returns tuple, which is valid for GeoJSON
        assert isinstance(result["geometry"]["coordinates"], (list, tuple))
        assert len(result["geometry"]["coordinates"]) > 0

    def test_coordinates_are_correct(self):
        """Test that coordinates match input polygon."""
        polygon = Polygon(
            [
                (21.0, 52.0),
                (21.1, 52.0),
                (21.1, 52.1),
                (21.0, 52.1),
                (21.0, 52.0),
            ]
        )

        result = polygon_to_geojson_feature(polygon)
        coords = result["geometry"]["coordinates"][0]  # Exterior ring

        # First coordinate should match (allowing for floating point)
        assert abs(coords[0][0] - 21.0) < 0.0001
        assert abs(coords[0][1] - 52.0) < 0.0001
