"""Tests for the monotonic stream smoothing (ADR-041, ADR-072)."""

from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import from_bounds, from_origin
from shapely.geometry import LineString

from core.hydrology import (
    _bresenham,
    _line_nodes,
    _rasterize_line_ordered,
    burn_streams_into_dem,
    process_hydrology_pyflwdir,
    smooth_streams_monotonic,
)

NODATA = -9999.0


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


class TestLineNodes:
    """The nodes that join the ends of the stream lines."""

    def test_ends_within_one_cell_share_a_node(self):
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        main = LineString([(10.4, 10.4), (10.4, 1.4)])
        joined = LineString([(3.4, 18.4), (11.3, 11.3)])  # ends a cell off main's start
        apart = LineString([(17.4, 18.4), (12.4, 12.4)])  # ends two cells off
        ends, _ = _line_nodes([main, joined, apart], transform)
        assert ends[1][1] == ends[0][0]
        assert ends[2][1] not in ends[0]


class TestSmoothStreamsMonotonic:
    """Test the main monotonic smoothing function.

    Covers spec test cases #1-#7, #11-#13 (ADR-041) and the direction of ADR-072.
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
            result, diag = smooth_streams_monotonic(dem.copy(), transform, "dummy.gpkg")
        assert result[10, 5] <= result[9, 5]
        assert diag["cells_smoothed"] > 0

    # Spec #2: flat terrain
    def test_flat_line_descends_strictly_by_float32_steps(self):
        """No flat is left for the fill to drain either way (ADR-072)."""
        dem = np.full((20, 20), 100.0, dtype=np.float32)
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        line = LineString([(5, 18), (5, 2)])  # rows 2 to 18
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            result, diag = smooth_streams_monotonic(dem.copy(), transform, "dummy.gpkg")
        profile = result[2:19, 5]
        assert profile[0] == 100.0
        assert np.all(np.diff(profile) < 0)
        assert 100.0 - profile[-1] < 1e-3
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
    def test_a_line_starts_below_the_lines_ending_at_its_start(self):
        """The main stem, listed before its tributaries, starts below the lower one."""
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        main = LineString([(10, 10), (10, 2)])  # rows 10 to 18
        trib_a = LineString([(8, 18), (10, 10)])
        trib_b = LineString([(12, 18), (10, 10)])
        for cell in _rasterize_line_ordered(trib_b, transform)[1:-1]:
            dem[cell] = 120.0  # a hollow along trib_b, below the junction (150 m)
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [main, trib_a, trib_b]
            result, diag = smooth_streams_monotonic(dem.copy(), transform, "dummy.gpkg")
        assert diag["segments_processed"] == 3
        main_profile = result[10:19, 10]
        assert main_profile[0] < 120.0
        assert np.all(np.diff(main_profile) < 0)

    # Spec #5: reversed geometry
    def test_a_line_digitized_up_a_clear_rise_is_taken_down_it(self):
        """A digitizing error on a slope is not cut into a trench (ADR-072)."""
        dem = np.repeat(
            (200.0 - 0.5 * np.arange(40, dtype=np.float32))[:, None], 20, axis=1
        )
        transform = from_bounds(0, 0, 200, 400, 20, 40)  # 10 m cells, 5% slope
        dem[20, 5] = 200.0  # a bridge, 10 m above the cell below it
        line = LineString([(52, 17), (52, 383)])  # from row 38 up to row 2
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            result, diag = smooth_streams_monotonic(dem.copy(), transform, "dummy.gpkg")
        assert diag["segments_reversed"] == 1
        np.testing.assert_array_equal(result[2:20, 5], dem[2:20, 5])
        assert result[20, 5] < result[19, 5]
        np.testing.assert_array_equal(result[21:39, 5], dem[21:39, 5])

    # Spec #6: MultiLineString decomposition
    def test_multilinestring_decomposed(self):
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        part_a = LineString([(5, 18), (5, 10)])
        part_b = LineString([(5, 10), (5, 2)])
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [part_a, part_b]
            _, diag = smooth_streams_monotonic(dem.copy(), transform, "dummy.gpkg")
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

    def test_a_loop_is_taken_from_its_first_line(self):
        """A directed cycle has no flow order; each of its lines is smoothed once."""
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        down = LineString([(5, 18), (5, 2)])
        back = LineString([(5, 2), (15, 2), (15, 18), (5, 18)])
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [down, back]
            result, diag = smooth_streams_monotonic(dem.copy(), transform, "dummy.gpkg")
        assert diag["segments_processed"] == 2
        assert diag["segments_out_of_order"] == 1
        back_profile = [
            result[cell] for cell in _rasterize_line_ordered(back, transform)
        ]
        assert np.all(np.diff(back_profile) < 0)

    # Spec #11: overlapping geometries
    def test_overlapping_geometries_min_wins(self):
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        dem[10, 5] = 200.0
        line_a = LineString([(5, 18), (5, 2)])
        line_b = LineString([(5, 18), (5, 2)])
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line_a, line_b]
            result, _ = smooth_streams_monotonic(dem.copy(), transform, "dummy.gpkg")
        assert result[10, 5] <= result[9, 5]

    # Spec #12: short segment
    def test_short_segment_handled(self):
        dem = self._make_sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        short = LineString([(5.1, 10.1), (5.4, 10.4)])
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [short]
            _, diag = smooth_streams_monotonic(dem.copy(), transform, "dummy.gpkg")
        assert diag["segments_processed"] + diag["segments_skipped"] == 1

    # Spec #13: segment outside DEM
    def test_segment_outside_dem_skipped(self):
        dem = self._make_sloped_dem(10, 10)
        transform = from_bounds(0, 0, 10, 10, 10, 10)
        line = LineString([(50, 50), (60, 60)])
        with patch("core.hydrology._load_stream_geometries") as mock_load:
            mock_load.return_value = [line]
            _, diag = smooth_streams_monotonic(dem.copy(), transform, "dummy.gpkg")
        assert diag["segments_skipped"] >= 1
        assert diag["segments_processed"] == 0


class TestRiverCrossingTheEdgeOfTheData:
    """A river that crosses the data leaves it downstream (the Noteć of ADR-072).

    A valley runs west to east across a 5 m grid; its river is digitized eastwards, the
    way it flows. The floor rises 0.3 m that way (the noise of a water surface on a flat
    valley) or is level, so the upstream crossing is the lower one or as low. With
    ``margins`` the data ends inside the raster and the line runs on into nodata, as a
    river leaves the sheets of an area. The line runs a quarter or three quarters of a
    cell into the cells it is burned into; with ``gap_cells`` it is two features with a
    gap between them in the middle, as the Wełna where it enters h07.
    """

    NROWS, NCOLS, ROW = 30, 120, 15
    X0, Y0 = 400000.0, 500000.0

    def _scene(self, tmp_path, floor_rise_m, margins, offset, gap_cells=0):
        rows = np.arange(self.NROWS)[:, None]
        cols = np.arange(self.NCOLS)[None, :]
        dem = (
            50.0
            + floor_rise_m * cols / (self.NCOLS - 1)
            + 0.5 * np.abs(rows - self.ROW)
        ).astype(np.float32)
        first, last = 0, self.NCOLS - 1
        if margins:
            first, last = 10, self.NCOLS - 11
            dem[:, :first] = NODATA
            dem[:, last + 1 :] = NODATA
        y = self.Y0 - (self.ROW + offset) * 5
        x = [self.X0 + (col + offset) * 5 for col in (0, self.NCOLS - 1)]
        if gap_cells:
            middle = self.X0 + (self.NCOLS // 2 + offset) * 5
            features = [
                LineString([(x[0], y), (middle, y)]),
                LineString([(middle + (gap_cells + 1) * 5, y), (x[1], y)]),
            ]
        else:
            features = [LineString([(x[0], y), (x[1], y)])]
        gpkg = tmp_path / "hydro.gpkg"
        gpd.GeoDataFrame(
            {
                "PRZEBIEG": ["ciek główny"] * len(features),
                "RODZAJ": ["rzeka"] * len(features),
            },
            geometry=features,
            crs="EPSG:2180",
        ).to_file(gpkg, layer="OT_SWRS_L", driver="GPKG")
        return dem, gpkg, first, last

    def _directions(self, dem, gpkg):
        transform = from_origin(self.X0, self.Y0, 5.0, 5.0)
        burned, _ = burn_streams_into_dem(dem, transform, gpkg, 2.0, NODATA, "main")
        smoothed, _ = smooth_streams_monotonic(burned, transform, gpkg, NODATA, "main")
        _, fdir, acc, _ = process_hydrology_pyflwdir(
            smoothed, {"nodata_value": NODATA, "transform": transform}
        )
        return fdir, acc

    @pytest.mark.parametrize("offset", [0.25, 0.75])
    @pytest.mark.parametrize("floor_rise_m", [0.3, 0.0])
    @pytest.mark.parametrize("margins", [True, False])
    def test_the_river_flows_the_way_it_is_digitized(
        self, tmp_path, floor_rise_m, margins, offset
    ):
        dem, gpkg, first, last = self._scene(tmp_path, floor_rise_m, margins, offset)
        fdir, acc = self._directions(dem, gpkg)
        # Every cell of the river drains east, and the river leaves at its east end
        assert np.all(fdir[self.ROW, first:last] == 1)
        assert acc[self.ROW, last] >= last - first + 1

    @pytest.mark.parametrize("floor_rise_m", [0.3, 0.0])
    @pytest.mark.parametrize("margins", [True, False])
    def test_a_gap_between_two_features_is_bridged(
        self, tmp_path, floor_rise_m, margins
    ):
        dem, gpkg, first, last = self._scene(
            tmp_path, floor_rise_m, margins, 0.25, gap_cells=3
        )
        fdir, acc = self._directions(dem, gpkg)
        assert np.all(fdir[self.ROW, first:last] == 1)
        assert acc[self.ROW, last] >= last - first + 1
