"""Unit tests for morphometry module."""

import math

import pytest

from core.morphometry import calculate_shape_indices


class TestCalculateShapeIndices:
    """Tests for calculate_shape_indices function."""

    def test_circle_shape(self):
        """Circle: Kc≈1, Rc≈1, Re≈1."""
        area = 10.0  # km2
        radius = math.sqrt(area / math.pi)  # km
        perimeter = 2 * math.pi * radius
        # For circle, length = diameter
        length = 2 * radius

        result = calculate_shape_indices(area, perimeter, length)

        assert result["compactness_coefficient"] == pytest.approx(1.0, abs=0.01)
        assert result["circularity_ratio"] == pytest.approx(1.0, abs=0.01)
        assert result["elongation_ratio"] == pytest.approx(1.0, abs=0.01)

    def test_elongated_rectangle(self):
        """Elongated rectangle: Kc > 1, Rc < 1."""
        # 10 km x 1 km rectangle
        area = 10.0  # km2
        perimeter = 2 * (10 + 1)  # 22 km
        length = 10.0  # km

        result = calculate_shape_indices(area, perimeter, length)

        assert result["compactness_coefficient"] > 1.0
        assert result["circularity_ratio"] < 1.0
        assert result["form_factor"] == pytest.approx(0.1, abs=0.01)
        assert result["mean_width_km"] == pytest.approx(1.0, abs=0.01)

    def test_returns_all_keys(self):
        """All expected keys are present."""
        result = calculate_shape_indices(10.0, 15.0, 5.0)
        expected_keys = {
            "compactness_coefficient",
            "circularity_ratio",
            "elongation_ratio",
            "form_factor",
            "lemniscate_ratio",
            "mean_width_km",
        }
        assert set(result.keys()) == expected_keys

    def test_zero_values_return_none(self):
        """Zero area/perimeter/length → all None."""
        result = calculate_shape_indices(0, 0, 0)
        assert all(v is None for v in result.values())

    def test_positive_values(self):
        """All shape indices are positive for valid input."""
        result = calculate_shape_indices(5.0, 12.0, 3.0)
        for key, value in result.items():
            assert value is not None
            assert value > 0, f"{key} should be positive"
