"""
Unit tests for precipitation module.

Tests validation functions and data retrieval logic.
"""

import pytest
from unittest.mock import MagicMock, patch
from shapely.geometry import Point

from core.precipitation import (
    validate_duration,
    validate_probability,
    get_precipitation,
    get_precipitation_wgs84,
    get_all_scenarios,
    VALID_DURATIONS_MIN,
    VALID_DURATIONS_STR,
    VALID_PROBABILITIES,
    DURATION_MIN_TO_STR,
)


class TestValidateDuration:
    """Tests for validate_duration function."""

    @pytest.mark.parametrize(
        "duration_min,expected",
        [
            (15, "15min"),
            (30, "30min"),
            (60, "1h"),
            (120, "2h"),
            (360, "6h"),
            (720, "12h"),
            (1440, "24h"),
        ],
    )
    def test_valid_duration_minutes(self, duration_min, expected):
        """Test validation of duration in minutes."""
        result = validate_duration(duration_min)
        assert result == expected

    @pytest.mark.parametrize(
        "duration_str",
        ["15min", "30min", "1h", "2h", "6h", "12h", "24h"],
    )
    def test_valid_duration_string(self, duration_str):
        """Test validation of duration as string."""
        result = validate_duration(duration_str)
        assert result == duration_str

    @pytest.mark.parametrize(
        "invalid_duration",
        [0, 10, 45, 100, 180, 500, 1000, 2000],
    )
    def test_invalid_duration_minutes_raises(self, invalid_duration):
        """Test that invalid duration in minutes raises ValueError."""
        with pytest.raises(ValueError, match="Invalid duration"):
            validate_duration(invalid_duration)

    @pytest.mark.parametrize(
        "invalid_duration",
        ["1min", "5min", "45min", "3h", "4h", "8h", "48h", "invalid"],
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

    @pytest.mark.parametrize("probability", [1, 2, 5, 10, 20, 50])
    def test_valid_probability(self, probability):
        """Test validation of valid probabilities."""
        result = validate_probability(probability)
        assert result == probability

    @pytest.mark.parametrize(
        "invalid_probability",
        [0, 3, 4, 6, 7, 8, 9, 11, 15, 25, 30, 40, 100],
    )
    def test_invalid_probability_raises(self, invalid_probability):
        """Test that invalid probability raises ValueError."""
        with pytest.raises(ValueError, match="Invalid probability"):
            validate_probability(invalid_probability)


class TestGetPrecipitation:
    """Tests for get_precipitation function."""

    def test_get_precipitation_returns_value(self):
        """Test that get_precipitation returns interpolated value."""
        # Mock database session
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.precipitation_interpolated = 38.5
        mock_db.execute.return_value.fetchone.return_value = mock_result

        centroid = Point(500000, 600000)
        result = get_precipitation(centroid, 60, 10, mock_db)

        assert result == 38.5
        mock_db.execute.assert_called_once()

    def test_get_precipitation_returns_none_when_no_data(self):
        """Test that get_precipitation returns None when no data found."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.precipitation_interpolated = None
        mock_db.execute.return_value.fetchone.return_value = mock_result

        centroid = Point(500000, 600000)
        result = get_precipitation(centroid, 60, 10, mock_db)

        assert result is None

    def test_get_precipitation_validates_duration(self):
        """Test that invalid duration raises ValueError."""
        mock_db = MagicMock()
        centroid = Point(500000, 600000)

        with pytest.raises(ValueError, match="Invalid duration"):
            get_precipitation(centroid, 45, 10, mock_db)

    def test_get_precipitation_validates_probability(self):
        """Test that invalid probability raises ValueError."""
        mock_db = MagicMock()
        centroid = Point(500000, 600000)

        with pytest.raises(ValueError, match="Invalid probability"):
            get_precipitation(centroid, 60, 15, mock_db)

    def test_get_precipitation_accepts_string_duration(self):
        """Test that string duration is accepted."""
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.precipitation_interpolated = 42.0
        mock_db.execute.return_value.fetchone.return_value = mock_result

        centroid = Point(500000, 600000)
        result = get_precipitation(centroid, "1h", 10, mock_db)

        assert result == 42.0


class TestGetPrecipitationWgs84:
    """Tests for get_precipitation_wgs84 function."""

    @patch("core.precipitation.get_precipitation")
    def test_transforms_coordinates(self, mock_get_precip):
        """Test that WGS84 coordinates are transformed to PL-1992."""
        mock_get_precip.return_value = 38.5
        mock_db = MagicMock()

        result = get_precipitation_wgs84(52.23, 21.01, "1h", 10, mock_db)

        assert result == 38.5
        mock_get_precip.assert_called_once()

        # Check that transformed point is in reasonable PL-1992 range
        call_args = mock_get_precip.call_args
        centroid = call_args[0][0]
        assert 100000 < centroid.x < 900000  # PL-1992 X range
        assert 100000 < centroid.y < 900000  # PL-1992 Y range


class TestGetAllScenarios:
    """Tests for get_all_scenarios function."""

    @patch("core.precipitation.get_precipitation")
    def test_returns_all_42_scenarios(self, mock_get_precip):
        """Test that all 42 scenarios are returned."""
        mock_get_precip.return_value = 30.0
        mock_db = MagicMock()
        centroid = Point(500000, 600000)

        result = get_all_scenarios(centroid, mock_db)

        # Check structure
        assert len(result) == 7  # 7 durations
        for duration in VALID_DURATIONS_STR:
            assert duration in result
            assert len(result[duration]) == 6  # 6 probabilities
            for prob in VALID_PROBABILITIES:
                assert prob in result[duration]

        # Check total calls (7 * 6 = 42)
        assert mock_get_precip.call_count == 42


class TestDurationMapping:
    """Tests for duration mapping constants."""

    def test_duration_mapping_completeness(self):
        """Test that all durations are mapped."""
        assert len(DURATION_MIN_TO_STR) == 7
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
        assert sorted_probs == [1, 2, 5, 10, 20, 50]

    def test_probabilities_count(self):
        """Test that there are exactly 6 probabilities."""
        assert len(VALID_PROBABILITIES) == 6
