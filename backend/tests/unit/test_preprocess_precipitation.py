"""
Unit tests for precipitation preprocessing script.

Tests grid generation and bounding box parsing.
"""

import pytest

from scripts.preprocess_precipitation import (
    parse_bbox,
    generate_grid_points,
)


class TestParseBbox:
    """Tests for parse_bbox function."""

    def test_valid_bbox(self):
        """Test parsing valid bounding box."""
        bbox = parse_bbox("19.5,51.5,20.5,52.5")
        assert bbox == (19.5, 51.5, 20.5, 52.5)

    def test_valid_bbox_with_spaces(self):
        """Test parsing bbox with spaces."""
        bbox = parse_bbox("19.5, 51.5, 20.5, 52.5")
        assert bbox == (19.5, 51.5, 20.5, 52.5)

    def test_invalid_format_raises(self):
        """Test that invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid bbox"):
            parse_bbox("19.5,51.5,20.5")  # Only 3 values

    def test_longitude_out_of_range_raises(self):
        """Test that longitude outside Poland raises ValueError."""
        with pytest.raises(ValueError, match="Longitude must be between"):
            parse_bbox("10.0,51.5,20.5,52.5")  # min_lon too small

        with pytest.raises(ValueError, match="Longitude must be between"):
            parse_bbox("19.5,51.5,25.0,52.5")  # max_lon too large

    def test_latitude_out_of_range_raises(self):
        """Test that latitude outside Poland raises ValueError."""
        with pytest.raises(ValueError, match="Latitude must be between"):
            parse_bbox("19.5,48.0,20.5,52.5")  # min_lat too small

        with pytest.raises(ValueError, match="Latitude must be between"):
            parse_bbox("19.5,51.5,20.5,56.0")  # max_lat too large

    def test_min_greater_than_max_raises(self):
        """Test that min > max raises ValueError."""
        with pytest.raises(ValueError, match="min values must be less than max"):
            parse_bbox("20.5,51.5,19.5,52.5")  # min_lon > max_lon

        with pytest.raises(ValueError, match="min values must be less than max"):
            parse_bbox("19.5,52.5,20.5,51.5")  # min_lat > max_lat


class TestGenerateGridPoints:
    """Tests for generate_grid_points function."""

    def test_generates_points(self):
        """Test that grid points are generated."""
        bbox = (20.0, 52.0, 20.2, 52.2)
        points = generate_grid_points(bbox, spacing_km=10.0)

        assert len(points) > 0
        assert all(isinstance(p, tuple) and len(p) == 2 for p in points)

    def test_points_within_bbox(self):
        """Test that all points are within bounding box."""
        bbox = (20.0, 52.0, 20.5, 52.5)
        min_lon, min_lat, max_lon, max_lat = bbox
        points = generate_grid_points(bbox, spacing_km=5.0)

        for lat, lon in points:
            assert min_lat <= lat <= max_lat
            assert min_lon <= lon <= max_lon

    def test_smaller_spacing_more_points(self):
        """Test that smaller spacing creates more points."""
        bbox = (20.0, 52.0, 20.5, 52.5)

        points_5km = generate_grid_points(bbox, spacing_km=5.0)
        points_10km = generate_grid_points(bbox, spacing_km=10.0)

        assert len(points_5km) > len(points_10km)

    def test_grid_point_count_estimate(self):
        """Test approximate number of grid points."""
        # Area: ~0.5° x 0.5° = ~34 km x 55 km at 52°N
        bbox = (20.0, 52.0, 20.5, 52.5)
        points = generate_grid_points(bbox, spacing_km=10.0)

        # Should be approximately (34/10) * (55/10) = 3 * 5 = 15-20 points
        assert 10 < len(points) < 30

    def test_single_point_for_small_bbox(self):
        """Test that very small bbox returns at least one point."""
        bbox = (20.0, 52.0, 20.001, 52.001)
        points = generate_grid_points(bbox, spacing_km=100.0)

        assert len(points) >= 1

    def test_point_format(self):
        """Test that points are (lat, lon) tuples."""
        bbox = (20.0, 52.0, 20.2, 52.2)
        points = generate_grid_points(bbox, spacing_km=20.0)

        for point in points:
            lat, lon = point
            # Latitude should be ~52
            assert 51 < lat < 53
            # Longitude should be ~20
            assert 19 < lon < 21
