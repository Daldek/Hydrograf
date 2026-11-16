"""
Unit tests for precipitation module.

Tests validation functions and data retrieval logic.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from shapely.geometry import Point, box

from core.precipitation import (
    DURATION_MIN_TO_STR,
    VALID_DURATIONS_MIN,
    VALID_DURATIONS_STR,
    VALID_PROBABILITIES,
    ThiessenCell,
    UnknownGridPointError,
    areal_depth,
    point_depth,
    thiessen_cells,
    validate_duration,
    validate_probability,
)


def _db(rows):
    """A session whose every query returns ``rows``."""
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = rows
    return db


def _grid(spacing_m=2000.0, n=5):
    """Points of a regular grid from (-spacing, -spacing), as the table rows."""
    return [
        SimpleNamespace(x=(i - 1) * spacing_m, y=(j - 1) * spacing_m)
        for i in range(n)
        for j in range(n)
    ]


class TestValidateDuration:
    """Tests for validate_duration function."""

    @pytest.mark.parametrize(
        "duration_min,expected",
        [
            (5, "5min"),
            (10, "10min"),
            (15, "15min"),
            (30, "30min"),
            (45, "45min"),
            (60, "1h"),
            (90, "1.5h"),
            (120, "2h"),
            (180, "3h"),
            (360, "6h"),
            (720, "12h"),
            (1080, "18h"),
            (1440, "24h"),
            (2160, "36h"),
            (2880, "48h"),
            (4320, "72h"),
        ],
    )
    def test_valid_duration_minutes(self, duration_min, expected):
        """Test validation of duration in minutes."""
        result = validate_duration(duration_min)
        assert result == expected

    @pytest.mark.parametrize(
        "duration_str",
        [
            "5min",
            "10min",
            "15min",
            "30min",
            "45min",
            "1h",
            "1.5h",
            "2h",
            "3h",
            "6h",
            "12h",
            "18h",
            "24h",
            "36h",
            "48h",
            "72h",
        ],
    )
    def test_valid_duration_string(self, duration_str):
        """Test validation of duration as string."""
        result = validate_duration(duration_str)
        assert result == duration_str

    @pytest.mark.parametrize(
        "invalid_duration",
        [0, 7, 20, 25, 50, 100, 200, 500, 1000, 2000, 5000],
    )
    def test_invalid_duration_minutes_raises(self, invalid_duration):
        """Test that invalid duration in minutes raises ValueError."""
        with pytest.raises(ValueError, match="Invalid duration"):
            validate_duration(invalid_duration)

    @pytest.mark.parametrize(
        "invalid_duration",
        ["1min", "7min", "4h", "8h", "96h", "invalid"],
    )
    def test_invalid_duration_string_raises(self, invalid_duration):
        """Test that invalid duration string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid duration"):
            validate_duration(invalid_duration)

    def test_invalid_duration_type_raises(self):
        """Test that invalid type raises ValueError."""
        with pytest.raises(ValueError, match="must be int or str"):
            validate_duration(60.0)  # float instead of int

        with pytest.raises(ValueError, match="must be int or str"):
            validate_duration([60])  # list


class TestValidateProbability:
    """Tests for validate_probability function."""

    @pytest.mark.parametrize(
        "probability",
        [
            0.01,
            0.02,
            0.03,
            0.05,
            0.1,
            0.2,
            0.3,
            0.5,
            1,
            2,
            3,
            5,
            10,
            20,
            30,
            40,
            50,
            60,
            70,
            80,
            90,
            95,
            98,
            98.5,
            99,
            99.5,
            99.9,
        ],
    )
    def test_valid_probability(self, probability):
        """Test validation of valid probabilities."""
        result = validate_probability(probability)
        assert result == float(probability)

    @pytest.mark.parametrize(
        "invalid_probability",
        [0, 0.04, 4, 6, 7, 8, 9, 11, 15, 25, 35, 45, 55, 100],
    )
    def test_invalid_probability_raises(self, invalid_probability):
        """Test that invalid probability raises ValueError."""
        with pytest.raises(ValueError, match="Invalid probability"):
            validate_probability(invalid_probability)


class TestThiessenCells:
    """Thiessen polygons of the grid points inside a watershed."""

    def test_each_point_gets_the_part_of_the_watershed_nearest_to_it(self):
        # Grid every 2 km: the polygon of (0, 0) spans x, y in [-1, 1] km. The
        # watershed x in [0.5, 2] km, y in [0, 2] km takes 0.5 km x 1 km of the
        # polygons of (0, 0) and (0, 2000) and 1 km x 1 km of (2000, 0), (2000, 2000)
        cells = thiessen_cells(box(500, 0, 2000, 2000), _db(_grid()))

        areas = {(c.easting_m, c.northing_m): c.area_km2 for c in cells}
        assert areas == pytest.approx(
            {
                (0.0, 0.0): 0.5,
                (0.0, 2000.0): 0.5,
                (2000.0, 0.0): 1.0,
                (2000.0, 2000.0): 1.0,
            }
        )

    def test_areas_add_up_to_the_watershed(self):
        watershed = Point(3100, 2900).buffer(2500)

        cells = thiessen_cells(watershed, _db(_grid(n=7)))

        assert sum(c.area_km2 for c in cells) == pytest.approx(watershed.area / 1e6)

    def test_a_watershed_inside_one_polygon_takes_that_point_only(self):
        cells = thiessen_cells(box(1800, 1800, 2200, 2200), _db(_grid()))

        assert cells == [ThiessenCell(2000.0, 2000.0, pytest.approx(0.16))]

    def test_no_grid_points_near_the_watershed(self):
        assert thiessen_cells(box(0, 0, 100, 100), _db([])) == []


class TestArealDepth:
    """Watershed mean of a scenario over the Thiessen polygons."""

    CELLS = [
        ThiessenCell(0.0, 0.0, 0.5),
        ThiessenCell(0.0, 2000.0, 0.5),
        ThiessenCell(2000.0, 0.0, 1.0),
        ThiessenCell(2000.0, 2000.0, 1.0),
    ]

    def test_mean_weighted_by_polygon_area(self):
        # Rows in another order and off by centimetres (rounded coordinates)
        rows = [
            SimpleNamespace(x=2000.004, y=2000.0, precipitation_mm=40.0),
            SimpleNamespace(x=0.0, y=0.0, precipitation_mm=10.0),
            SimpleNamespace(x=2000.0, y=0.0, precipitation_mm=30.0),
            SimpleNamespace(x=0.0, y=1999.996, precipitation_mm=20.0),
        ]

        depth = areal_depth(self.CELLS, "1h", 10, _db(rows))

        # (10*0.5 + 20*0.5 + 30*1 + 40*1) / 3
        assert depth.precipitation_mm == pytest.approx(85.0 / 3)
        assert depth.interpolation == "thiessen"
        assert [p.precipitation_mm for p in depth.points] == [10.0, 20.0, 30.0, 40.0]
        assert [p.weight for p in depth.points] == pytest.approx(
            [1 / 6, 1 / 6, 1 / 3, 1 / 3]
        )
        assert [p.area_km2 for p in depth.points] == [0.5, 0.5, 1.0, 1.0]

    def test_a_cell_off_the_grid_is_refused(self):
        rows = [
            SimpleNamespace(x=c.easting_m, y=c.northing_m, precipitation_mm=1.0)
            for c in self.CELLS
        ]
        cells = [*self.CELLS, ThiessenCell(1000.0, 1000.0, 1.0)]

        with pytest.raises(UnknownGridPointError) as err:
            areal_depth(cells, "1h", 10, _db(rows))

        assert (err.value.easting_m, err.value.northing_m) == (1000.0, 1000.0)

    def test_no_rows_of_the_scenario_is_refused(self):
        with pytest.raises(UnknownGridPointError):
            areal_depth(self.CELLS, "1h", 10, _db([]))

    def test_no_cells_gives_no_depth(self):
        assert areal_depth([], "1h", 10, _db([])) is None

    def test_validates_the_scenario(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            areal_depth(self.CELLS, 100, 10, _db([]))
        with pytest.raises(ValueError, match="Invalid probability"):
            areal_depth(self.CELLS, 60, 15, _db([]))


class TestPointDepth:
    """Inverse distance weighting at a point."""

    def test_weights_fall_with_the_squared_distance(self):
        rows = [
            SimpleNamespace(x=1000.0, y=0.0, precipitation_mm=10.0),
            SimpleNamespace(x=0.0, y=2000.0, precipitation_mm=40.0),
        ]

        depth = point_depth(Point(0, 0), 60, 10, _db(rows))

        # weights 1/1000^2 and 1/2000^2: 4/5 and 1/5
        assert depth.precipitation_mm == pytest.approx(16.0)
        assert depth.interpolation == "idw"
        assert [p.weight for p in depth.points] == pytest.approx([0.8, 0.2])
        assert [p.distance_m for p in depth.points] == pytest.approx([1000.0, 2000.0])

    def test_a_point_on_the_grid_takes_its_value(self):
        rows = [
            SimpleNamespace(x=0.0, y=0.0, precipitation_mm=10.0),
            SimpleNamespace(x=2000.0, y=0.0, precipitation_mm=40.0),
        ]

        depth = point_depth(Point(0, 0), 60, 10, _db(rows))

        assert depth.precipitation_mm == 10.0
        assert [p.weight for p in depth.points] == [1.0, 0.0]

    def test_no_data_gives_no_depth(self):
        assert point_depth(Point(0, 0), "1h", 0.01, _db([])) is None


class TestDurationMapping:
    """Tests for duration mapping constants."""

    def test_duration_mapping_completeness(self):
        """Test that all durations are mapped."""
        assert len(DURATION_MIN_TO_STR) == 16
        assert set(DURATION_MIN_TO_STR.keys()) == VALID_DURATIONS_MIN
        assert set(DURATION_MIN_TO_STR.values()) == VALID_DURATIONS_STR

    def test_valid_durations_match(self):
        """Test that VALID_DURATIONS_MIN and VALID_DURATIONS_STR match."""
        assert len(VALID_DURATIONS_MIN) == len(VALID_DURATIONS_STR)
        for minutes, string in DURATION_MIN_TO_STR.items():
            assert minutes in VALID_DURATIONS_MIN
            assert string in VALID_DURATIONS_STR


class TestValidProbabilities:
    """Tests for probability constants."""

    def test_probabilities_are_sorted_ascending(self):
        """Test that probabilities can be sorted for display."""
        sorted_probs = sorted(VALID_PROBABILITIES)
        assert sorted_probs[0] == 0.01
        assert sorted_probs[-1] == 99.9

    def test_probabilities_count(self):
        """Test that there are exactly 27 probabilities."""
        assert len(VALID_PROBABILITIES) == 27
