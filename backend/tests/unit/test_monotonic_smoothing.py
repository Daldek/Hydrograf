"""Tests for H4 monotonic stream smoothing (ADR-041)."""

import numpy as np
import pytest
from rasterio.transform import from_bounds
from shapely.geometry import LineString
from core.hydrology import _bresenham, _rasterize_line_ordered


class TestBresenham:
    """Test Bresenham line rasterization."""

    def test_horizontal_line(self):
        cells = _bresenham(0, 0, 0, 5)
        assert cells == [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4), (0, 5)]

    def test_vertical_line(self):
        cells = _bresenham(0, 0, 4, 0)
        assert cells == [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)]

    def test_diagonal_line(self):
        cells = _bresenham(0, 0, 3, 3)
        assert cells == [(0, 0), (1, 1), (2, 2), (3, 3)]

    def test_steep_line(self):
        cells = _bresenham(0, 0, 4, 1)
        assert len(cells) == 5
        assert cells[0] == (0, 0)
        assert cells[-1] == (4, 1)

    def test_reverse_direction(self):
        cells_fwd = _bresenham(0, 0, 3, 5)
        cells_rev = _bresenham(3, 5, 0, 0)
        assert cells_fwd == list(reversed(cells_rev))

    def test_single_point(self):
        cells = _bresenham(2, 3, 2, 3)
        assert cells == [(2, 3)]


class TestRasterizeLineOrdered:
    """Test ordered line rasterization with geotransform."""

    @pytest.fixture
    def simple_transform(self):
        """10x10 raster, 1m cells, origin at (0, 0)."""
        return from_bounds(0, 0, 10, 10, 10, 10)

    def test_simple_line(self, simple_transform):
        line = LineString([(0.5, 9.5), (4.5, 9.5)])
        cells = _rasterize_line_ordered(line, simple_transform)
        assert len(cells) >= 2
        assert cells[0] == (0, 0)
        assert cells[-1] == (0, 4)

    def test_deduplicated_at_vertices(self, simple_transform):
        line = LineString([(0.5, 9.5), (2.5, 9.5), (4.5, 9.5)])
        cells = _rasterize_line_ordered(line, simple_transform)
        assert len(cells) == len(set(cells)), "Duplicate cells found"

    def test_preserves_order(self, simple_transform):
        line = LineString([(0.5, 9.5), (0.5, 5.5)])
        cells = _rasterize_line_ordered(line, simple_transform)
        rows = [r for r, c in cells]
        assert rows == sorted(rows), "Cells not in line order"

    def test_single_pixel_line(self, simple_transform):
        line = LineString([(0.1, 9.9), (0.2, 9.8)])
        cells = _rasterize_line_ordered(line, simple_transform)
        assert len(cells) == 1

    def test_clips_to_raster_bounds(self, simple_transform):
        line = LineString([(-5, 9.5), (5, 9.5)])
        cells = _rasterize_line_ordered(line, simple_transform, shape=(10, 10))
        for r, c in cells:
            assert 0 <= r < 10 and 0 <= c < 10
