"""Tests for the monotonic stream smoothing (ADR-041, ADR-072, ADR-077)."""

from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import from_bounds, from_origin
from shapely.geometry import LineString

from core.hydrology import (
    CONNECTOR,
    _bresenham,
    _line_directions,
    _line_nodes,
    _rasterize_line_ordered,
    burn_streams_into_dem,
    process_hydrology_pyflwdir,
    smooth_streams_monotonic,
)

NODATA = -9999.0


def _features(lines, mphp=None, names=None, connectors=None):
    """Return the frame of ``_load_stream_features``: lines with their attributes.

    The attributes are blank unless given, line by line; ``connectors`` marks the
    artificial connectors.
    """
    blank = [""] * len(lines)
    return gpd.GeoDataFrame(
        {
            "IDENTYFIKATORMPHP": mphp or blank,
            "NAZWA": names or blank,
            "CECHAGEOMETRII": [CONNECTOR if flag else "" for flag in connectors]
            if connectors
            else blank,
        },
        geometry=list(lines),
        crs="EPSG:2180",
    )


def _smooth(dem, transform, lines, nodata=NODATA, **attributes):
    """Smooth a copy of ``dem`` along ``lines``: (DEM, flow lines, diagnostics)."""
    with patch(
        "core.hydrology._load_stream_features",
        return_value=_features(lines, **attributes),
    ):
        return smooth_streams_monotonic(
            dem.copy(), transform, "dummy.gpkg", nodata=nodata
        )


def _sloped_dem(nrows=20, ncols=20):
    """Elevation decreases with row (top=high, bottom=low), 5 m a row."""
    rows = np.arange(nrows, dtype=np.float32)[:, None]
    return np.repeat(200.0 - rows * 5.0, ncols, axis=1).astype(np.float32)


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

    # Spec #1: bridge obstacle
    def test_bridge_obstacle_corrected(self):
        dem = _sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        dem[10, 5] = 200.0  # bridge bump
        line = LineString([(5, 18), (5, 2)])
        result, _, diag = _smooth(dem, transform, [line])
        assert result[10, 5] <= result[9, 5]
        assert diag["cells_smoothed"] > 0

    # Spec #2: flat terrain
    def test_flat_line_descends_strictly_by_float32_steps(self):
        """No flat is left for the fill to drain either way (ADR-072)."""
        dem = np.full((20, 20), 100.0, dtype=np.float32)
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        line = LineString([(5, 18), (5, 2)])  # rows 2 to 18
        result, _, diag = _smooth(dem, transform, [line])
        profile = result[2:19, 5]
        assert profile[0] == 100.0
        assert np.all(np.diff(profile) < 0)
        assert 100.0 - profile[-1] < 1e-3
        assert diag["cells_smoothed"] == 0

    # Spec #3: already monotonic
    def test_already_monotonic_unchanged(self):
        dem = _sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        line = LineString([(5, 18), (5, 2)])
        _, _, diag = _smooth(dem, transform, [line])
        assert diag["cells_smoothed"] == 0

    # Spec #4: confluence
    def test_a_line_starts_below_the_lines_ending_at_its_start(self):
        """The main stem, listed before its tributaries, starts below the lower one."""
        dem = _sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        main = LineString([(10, 10), (10, 2)])  # rows 10 to 18
        trib_a = LineString([(8, 18), (10, 10)])
        trib_b = LineString([(12, 18), (10, 10)])
        for cell in _rasterize_line_ordered(trib_b, transform)[1:-1]:
            dem[cell] = 120.0  # a hollow along trib_b, below the junction (150 m)
        result, _, diag = _smooth(dem, transform, [main, trib_a, trib_b])
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
        result, flow_lines, diag = _smooth(dem, transform, [line])
        assert diag["segments_reversed"] == diag["segments_reversed_by_rise"] == 1
        assert list(flow_lines[0].coords) == list(line.coords)[::-1]
        np.testing.assert_array_equal(result[2:20, 5], dem[2:20, 5])
        assert result[20, 5] < result[19, 5]
        np.testing.assert_array_equal(result[21:39, 5], dem[21:39, 5])

    # Spec #6: MultiLineString decomposition
    def test_multilinestring_decomposed(self):
        dem = _sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        part_a = LineString([(5, 18), (5, 10)])
        part_b = LineString([(5, 10), (5, 2)])
        _, _, diag = _smooth(dem, transform, [part_a, part_b])
        assert diag["segments_processed"] == 2

    # Spec #7: NoData cells
    def test_nodata_cells_skipped(self):
        dem = _sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        nodata = -9999.0
        dem[10, 5] = nodata
        line = LineString([(5, 18), (5, 2)])
        result, _, _ = _smooth(dem, transform, [line], nodata=nodata)
        assert result[10, 5] == nodata

    def test_a_loop_is_taken_from_its_first_line(self):
        """A directed cycle has no flow order; each of its lines is smoothed once."""
        dem = _sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        down = LineString([(5, 18), (5, 2)])
        back = LineString([(5, 2), (15, 2), (15, 18), (5, 18)])
        result, _, diag = _smooth(dem, transform, [down, back])
        assert diag["segments_processed"] == 2
        assert diag["segments_out_of_order"] == 1
        back_profile = [
            result[cell] for cell in _rasterize_line_ordered(back, transform)
        ]
        assert np.all(np.diff(back_profile) < 0)

    # Spec #11: overlapping geometries
    def test_overlapping_geometries_min_wins(self):
        dem = _sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        dem[10, 5] = 200.0
        line_a = LineString([(5, 18), (5, 2)])
        line_b = LineString([(5, 18), (5, 2)])
        result, _, _ = _smooth(dem, transform, [line_a, line_b])
        assert result[10, 5] <= result[9, 5]

    # Spec #12: short segment
    def test_short_segment_handled(self):
        dem = _sloped_dem()
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        short = LineString([(5.1, 10.1), (5.4, 10.4)])
        _, _, diag = _smooth(dem, transform, [short])
        assert diag["segments_processed"] + diag["segments_skipped"] == 1

    # Spec #13: segment outside DEM
    def test_segment_outside_dem_skipped(self):
        dem = _sloped_dem(10, 10)
        transform = from_bounds(0, 0, 10, 10, 10, 10)
        line = LineString([(50, 50), (60, 60)])
        _, _, diag = _smooth(dem, transform, [line])
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
        smoothed, _, _ = smooth_streams_monotonic(
            burned, transform, gpkg, NODATA, "main"
        )
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


# A 5 m grid; the lines of the next tests run along its row ROW
TRANSFORM_5M = from_origin(0.0, 0.0, 5.0, 5.0)
ROW = 5


def _along_row(first_col, last_col):
    """Return a line along ROW from the centre of one column to that of another."""
    y = -(ROW + 0.5) * 5.0
    return LineString([((first_col + 0.5) * 5.0, y), ((last_col + 0.5) * 5.0, y)])


def _valley(floor):
    """Return the DEM of a valley along ROW, its floor one value per column."""
    sides = 0.5 * np.abs(np.arange(2 * ROW + 1) - ROW)[:, None]
    return (np.asarray(floor)[None, :] + sides).astype(np.float32)


class TestTheDirectionOfALine:
    """The smoothing takes each burned line the way the rules of ADR-077 give."""

    def test_a_block_digitized_upstream_flows_down_its_watercourse(self):
        """The middle line of three rises 0.8 m on 105 m the way it is digitized.

        ADR-072 kept it; the DEM along the whole watercourse falls 2.5 m the other way.
        """
        dem = _valley(52.5 - 2.5 * np.arange(64) / 63)
        lines = [_along_row(0, 20), _along_row(40, 20), _along_row(40, 63)]
        result, _, diag = _smooth(dem, TRANSFORM_5M, lines, names=["Struga"] * 3)
        assert diag["segments_reversed"] == 1
        assert diag["segments_reversed_by_watercourse"] == 1
        assert np.all(np.diff(result[ROW]) < 0)

    def test_a_connector_through_a_flat_lake_flows_the_way_of_its_watercourse(self):
        floor = np.concatenate(
            [np.linspace(52.5, 51.5, 21), np.full(19, 51.5), np.linspace(51.5, 50, 24)]
        )
        lines = [_along_row(0, 20), _along_row(40, 20), _along_row(40, 63)]
        result, _, diag = _smooth(
            _valley(floor),
            TRANSFORM_5M,
            lines,
            names=["Struga"] * 3,
            connectors=[False, True, False],
        )
        assert diag["connectors"] == 1
        assert diag["segments_reversed"] == 1
        assert diag["segments_reversed_by_watercourse"] == 1
        assert np.all(np.diff(result[ROW]) < 0)

    def test_the_dem_along_a_connector_does_not_reverse_it(self):
        """A lake surface read 3 m higher on 255 m the way it is digitized.

        ADR-072 reversed it; it is digitized the way of its watercourse.
        """
        floor = np.concatenate(
            [
                np.linspace(53.0, 52.0, 21),
                np.linspace(52.0, 55.0, 51)[1:],
                np.linspace(55.0, 54.0, 30)[1:],
            ]
        )
        lines = [_along_row(0, 20), _along_row(20, 70), _along_row(70, 99)]
        _, _, diag = _smooth(
            _valley(floor),
            TRANSFORM_5M,
            lines,
            names=["Struga"] * 3,
            connectors=[False, True, False],
        )
        assert diag["segments_reversed"] == 0

    @pytest.mark.parametrize(
        ("receiver", "reversed_lines"), [("188", 1), ("189", 0), ("188521", 0)]
    )
    def test_a_flat_watercourse_flows_to_its_mouth(self, receiver, reversed_lines):
        """18852 in two lines; the one at the end of a line of ``receiver`` leaves it.

        Only a receiver, whose identifier is a proper prefix of 18852, is a mouth.
        """
        lines = [_along_row(0, 20), _along_row(20, 40), _along_row(60, 40)]
        _, _, diag = _smooth(
            _valley(np.full(61, 100.0)),
            TRANSFORM_5M,
            lines,
            mphp=[receiver, "18852", "18852"],
        )
        assert diag["segments_reversed_by_mouth"] == reversed_lines
        assert diag["segments_reversed"] == reversed_lines

    def test_a_network_digitized_downstream_is_smoothed_as_without_attributes(self):
        transform = from_bounds(0, 0, 20, 20, 20, 20)
        lines = [
            LineString([(10, 18), (10, 10)]),
            LineString([(10, 10), (10, 2)]),
            LineString([(4, 18), (7, 14)]),
            LineString([(7, 14), (10, 10)]),
        ]
        attributed, _, diag = _smooth(
            _sloped_dem(),
            transform,
            lines,
            mphp=["188", "188", "18852", "18852"],
            names=["Noteć", "Noteć", "Kcynka", "Kcynka"],
        )
        blank, _, _ = _smooth(_sloped_dem(), transform, lines)
        assert diag["segments_by_mouth"] == 2
        assert diag["segments_reversed"] == 0
        np.testing.assert_array_equal(attributed, blank)

    def test_a_block_falling_from_a_divide_keeps_its_direction(self):
        """The guard: the watercourse falls 7 m east, its block off a divide 4 m west.

        Reversed, the block would be cut up to 4 m deep across the divide.
        """
        floor = np.concatenate(
            [np.linspace(107.0, 111.0, 51), np.linspace(111.0, 100.0, 50)[1:]]
        )
        lines = [_along_row(50, 0), _along_row(50, 99)]
        _, _, diag = _smooth(_valley(floor), TRANSFORM_5M, lines, names=["Struga"] * 2)
        assert diag["blocks_kept_by_fall"] == 1
        assert diag["segments_reversed"] == 0


class TestLineDirections:
    """``_line_directions`` on networks of nodes, lengths and DEM values 5 m apart."""

    @staticmethod
    def _directions(ends, values=None, lengths=None, mphp=None, names=None):
        flat = np.full(40, 100.0)
        blank = [""] * len(ends)
        return _line_directions(
            ends,
            {line: (values or {}).get(line, flat) for line in ends},
            lengths or dict.fromkeys(ends, 100.0),
            mphp or blank,
            names or blank,
            [False] * len(ends),
            5.0,
        )

    def test_the_mouth_comes_before_the_dem_of_the_watercourse(self):
        """18852 runs 1 -> 2 <- 3 from its receiver at node 1, its DEM falling to 3."""
        ends = {0: (0, 1), 1: (1, 2), 2: (3, 2)}
        values = {1: np.linspace(110.0, 105.0, 30), 2: np.linspace(100.0, 105.0, 30)}
        directions, _ = self._directions(
            ends, values, {0: 100.0, 1: 150.0, 2: 150.0}, ["188", "18852", "18852"]
        )
        assert directions[1] == (True, "mouth")
        assert directions[2] == (False, "mouth")

    def test_with_two_mouths_each_line_flows_to_the_nearer(self):
        """A side arm of 188 leaves it at node 1 and returns at node 4."""
        ends = {0: (0, 1), 1: (1, 2), 2: (2, 3), 3: (3, 4), 4: (4, 5)}
        lengths = {0: 100.0, 1: 100.0, 2: 200.0, 3: 400.0, 4: 100.0}
        mphp = ["188", "18852", "18852", "18852", "188"]
        directions, _ = self._directions(ends, lengths=lengths, mphp=mphp)
        assert directions[1] == (True, "mouth")
        assert directions[2] == (True, "mouth")
        assert directions[3] == (False, "mouth")

    def test_a_line_as_far_from_the_mouth_at_both_ends_goes_to_the_other_rules(self):
        """The middle line of the side arm; the DEM rises 3 m along it."""
        ends = {0: (0, 1), 1: (1, 2), 2: (2, 3), 3: (3, 4), 4: (4, 5)}
        lengths = {0: 100.0, 1: 100.0, 2: 250.0, 3: 100.0, 4: 100.0}
        mphp = ["188", "18852", "18852", "18852", "188"]
        values = {2: np.linspace(100.0, 103.0, 50)}
        directions, _ = self._directions(ends, values, lengths, mphp)
        assert directions[2] == (True, "rise")

    def test_a_loop_of_one_watercourse_is_walked_once(self):
        """Three lines of a canal round an island, digitized both ways, on a flat."""
        ends = {0: (1, 2), 1: (3, 2), 2: (3, 1)}
        directions, kept = self._directions(ends, names=["Kanał"] * 3)
        assert directions == dict.fromkeys(ends, (False, "digitized"))
        assert kept == []
