"""Tests for H4 monotonic stream smoothing (ADR-041)."""

from unittest.mock import patch

import numpy as np
import pytest
from rasterio.transform import from_bounds
from shapely.geometry import LineString

from core.hydrology import (
    _bresenham,
    _build_stream_network_graph,
    _rasterize_line_ordered,
    smooth_streams_monotonic,
)


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


class TestBuildStreamNetworkGraph:
    """Test topology graph construction from stream geometries."""

    def _make_dem_and_transform(self, nrows=20, ncols=20):
        """Create a sloped DEM (high top-left, low bottom-right) + transform."""
        dem = np.zeros((nrows, ncols), dtype=np.float32)
        for r in range(nrows):
            for c in range(ncols):
                dem[r, c] = 200.0 - r * 5.0 - c * 2.0
        transform = from_bounds(0, 0, ncols, nrows, ncols, nrows)
        return dem, transform

    def test_single_segment(self):
        dem, transform = self._make_dem_and_transform()
        geoms = [LineString([(1, 19), (1, 1)])]
        graph, seg_nodes, outlets = _build_stream_network_graph(geoms, dem, transform)
        assert len(outlets) == 1
        assert len(graph) == 2
        assert 0 in seg_nodes

    def test_y_junction(self):
        """Two tributaries merging into one main stem."""
        dem, transform = self._make_dem_and_transform()
        trib_a = LineString([(2, 18), (5, 15)])
        trib_b = LineString([(8, 18), (5, 15)])
        main = LineString([(5, 15), (5, 2)])
        geoms = [trib_a, trib_b, main]
        graph, seg_nodes, outlets = _build_stream_network_graph(geoms, dem, transform)
        assert len(outlets) == 1
        assert len(seg_nodes) == 3

    def test_seg_nodes_maps_start_end(self):
        """seg_nodes correctly maps segment -> (start_node, end_node)."""
        dem, transform = self._make_dem_and_transform()
        geoms = [LineString([(2, 18), (10, 10)])]
        graph, seg_nodes, outlets = _build_stream_network_graph(geoms, dem, transform)
        start_node, end_node = seg_nodes[0]
        assert start_node != end_node

    def test_disconnected_components(self):
        dem, transform = self._make_dem_and_transform()
        stream_a = LineString([(1, 19), (1, 15)])
        stream_b = LineString([(15, 19), (15, 15)])
        geoms = [stream_a, stream_b]
        graph, seg_nodes, outlets = _build_stream_network_graph(geoms, dem, transform)
        assert len(outlets) == 2

    def test_edge_outlet_preferred(self):
        """Node on raster edge is preferred as outlet over interior node."""
        dem, transform = self._make_dem_and_transform()
        geoms = [LineString([(5, 10), (5, 0)])]
        graph, seg_nodes, outlets = _build_stream_network_graph(geoms, dem, transform)
        assert len(outlets) == 1


class TestSmoothStreamsMonotonic:
    """Test the main monotonic smoothing function.

    Covers spec test cases #1-#8, #11-#13.
    """

    def _make_sloped_dem(self, nrows=20, ncols=20):
        """Elevation decreases with row (top=high, bottom=low)."""
        dem = np.zeros((nrows, ncols), dtype=np.float32)
        for r in range(nrows):
            for c in range(ncols):
                dem[r, c] = 200.0 - r * 5.0
        return dem

    # Spec #1: bridge obstacle
    def test_bridge_obstacle_corrected(self):
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        dem[10, 5] = 200.0  # bridge bump
        line = LineString([(5, 18), (5, 2)])
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            result, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )
        assert result[10, 5] <= result[9, 5]
        assert diag["cells_smoothed"] > 0

    # Spec #2: flat terrain
    def test_flat_terrain_unchanged(self):
        dem = np.full((20, 20), 100.0, dtype=np.float32)
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        line = LineString([(5, 18), (5, 2)])
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            _, diag = smooth_streams_monotonic(dem.copy(), transform, "dummy.gpkg")
        assert diag["cells_smoothed"] == 0

    # Spec #3: already monotonic
    def test_already_monotonic_unchanged(self):
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        line = LineString([(5, 18), (5, 2)])
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            _, diag = smooth_streams_monotonic(dem.copy(), transform, "dummy.gpkg")
        assert diag["cells_smoothed"] == 0

    # Spec #4: confluence
    def test_confluence_takes_min_of_tributaries(self):
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        dem[5, 8] = 200.0  # bump on trib_a path
        trib_a = LineString([(8, 18), (10, 10)])
        trib_b = LineString([(12, 18), (10, 10)])
        main = LineString([(10, 10), (10, 2)])
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [trib_a, trib_b, main]
            result, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )
        assert diag["segments_processed"] == 3
        assert diag["disconnected_components"] == 1
        assert result[10, 10] <= dem[10, 10]

    # Spec #5: reversed geometry
    def test_reversed_geometry_handled(self):
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        line = LineString([(5, 2), (5, 18)])  # reversed: low elev first
        dem[10, 5] = 200.0  # bridge bump
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            result, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )
        assert result[10, 5] <= result[9, 5]
        assert diag["cells_smoothed"] > 0

    # Spec #6: MultiLineString decomposition
    def test_multilinestring_decomposed(self):
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        part_a = LineString([(5, 18), (5, 10)])
        part_b = LineString([(5, 10), (5, 2)])
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [part_a, part_b]
            _, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )
        assert diag["segments_processed"] == 2

    # Spec #7: NoData cells
    def test_nodata_cells_skipped(self):
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        nodata = -9999.0
        dem[10, 5] = nodata
        line = LineString([(5, 18), (5, 2)])
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            result, _ = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg", nodata=nodata
            )
        assert result[10, 5] == nodata

    # Spec #8: disconnected network
    def test_disconnected_network_separate_outlets(self):
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        stream_a = LineString([(3, 18), (3, 2)])
        stream_b = LineString([(15, 18), (15, 2)])
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [stream_a, stream_b]
            _, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )
        assert diag["disconnected_components"] == 2
        assert diag["segments_processed"] == 2

    # Spec #11: overlapping geometries
    def test_overlapping_geometries_min_wins(self):
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        dem[10, 5] = 200.0
        line_a = LineString([(5, 18), (5, 2)])
        line_b = LineString([(5, 18), (5, 2)])
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line_a, line_b]
            result, _ = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )
        assert result[10, 5] <= result[9, 5]

    # Spec #12: short segment
    def test_short_segment_handled(self):
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        short = LineString([(5.1, 10.1), (5.4, 10.4)])
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [short]
            _, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )
        assert diag["segments_processed"] + diag["segments_skipped"] == 1

    # Spec #13: segment outside DEM
    def test_segment_outside_dem_skipped(self):
        dem = self._make_sloped_dem(10, 10)
        transform = from_bounds(0, 0, 10, 10, 10, 10)
        line = LineString([(50, 50), (60, 60)])
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            _, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )
        assert diag["segments_skipped"] >= 1
        assert diag["segments_processed"] == 0

    # Diagnostics structure
    def test_diagnostics_structure(self):
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        line = LineString([(5, 18), (5, 2)])
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            _, diag = smooth_streams_monotonic(
                dem.copy(), transform, "dummy.gpkg"
            )
        required_keys = {
            "segments_processed",
            "segments_skipped",
            "cells_smoothed",
            "cells_unchanged",
            "max_correction_m",
            "mean_correction_m",
            "disconnected_components",
        }
        assert required_keys.issubset(set(diag.keys()))
