"""Tests for core.zonal_stats module."""

import numpy as np
import pytest

from core.zonal_stats import (
    zonal_bincount,
    zonal_elevation_histogram,
    zonal_max,
    zonal_min,
)


class TestZonalBincount:
    """Tests for zonal_bincount function."""

    def test_counts_without_weights(self):
        labels = np.array([[1, 1, 2], [2, 2, 0], [0, 3, 3]])
        result = zonal_bincount(labels)
        assert result[0] == 2  # background
        assert result[1] == 2  # label 1
        assert result[2] == 3  # label 2
        assert result[3] == 2  # label 3

    def test_weighted_sums(self):
        labels = np.array([[1, 1], [2, 2]])
        weights = np.array([[10.0, 20.0], [30.0, 40.0]])
        result = zonal_bincount(labels, weights=weights)
        assert result[1] == pytest.approx(30.0)  # 10 + 20
        assert result[2] == pytest.approx(70.0)  # 30 + 40

    def test_valid_mask(self):
        labels = np.array([[1, 1], [1, 1]])
        weights = np.array([[10.0, 20.0], [30.0, 40.0]])
        mask = np.array([[True, True], [False, True]])
        result = zonal_bincount(labels, weights=weights, valid_mask=mask)
        assert result[1] == pytest.approx(70.0)  # 10 + 20 + 40 (not 30)

    def test_max_label_parameter(self):
        labels = np.array([[1, 2]])
        result = zonal_bincount(labels, max_label=5)
        assert len(result) == 6  # 0..5

    def test_empty_labels(self):
        labels = np.array([[0, 0], [0, 0]])
        result = zonal_bincount(labels)
        assert result[0] == 4

    def test_counts_without_weights_valid_mask(self):
        labels = np.array([[1, 1], [1, 1]])
        mask = np.array([[True, False], [True, True]])
        result = zonal_bincount(labels, valid_mask=mask)
        assert result[1] == 3  # 3 of 4 cells valid


class TestZonalMax:
    """Tests for zonal_max function."""

    def test_simple_max(self):
        labels = np.array([[1, 1, 2], [2, 2, 0]])
        values = np.array([[5.0, 3.0, 10.0], [7.0, 1.0, 0.0]])
        result = zonal_max(labels, values, n_labels=2)
        assert result[0] == pytest.approx(5.0)  # max of label 1
        assert result[1] == pytest.approx(10.0)  # max of label 2

    def test_single_label(self):
        labels = np.array([[1, 1], [1, 1]])
        values = np.array([[1.0, 4.0], [2.0, 3.0]])
        result = zonal_max(labels, values, n_labels=1)
        assert result[0] == pytest.approx(4.0)

    def test_negative_values(self):
        labels = np.array([[1, 1], [2, 2]])
        values = np.array([[-5.0, -3.0], [-10.0, -1.0]])
        result = zonal_max(labels, values, n_labels=2)
        assert result[0] == pytest.approx(-3.0)  # max of label 1
        assert result[1] == pytest.approx(-1.0)  # max of label 2


class TestZonalMin:
    """Tests for zonal_min function."""

    def test_simple_min(self):
        labels = np.array([[1, 1, 2], [2, 2, 0]])
        values = np.array([[5.0, 3.0, 10.0], [7.0, 1.0, 0.0]])
        result = zonal_min(labels, values, n_labels=2)
        assert result[0] == pytest.approx(3.0)  # min of label 1
        assert result[1] == pytest.approx(1.0)  # min of label 2

    def test_single_label(self):
        labels = np.array([[1, 1], [1, 1]])
        values = np.array([[1.0, 4.0], [2.0, 3.0]])
        result = zonal_min(labels, values, n_labels=1)
        assert result[0] == pytest.approx(1.0)

    def test_negative_values(self):
        labels = np.array([[1, 1], [2, 2]])
        values = np.array([[-5.0, -3.0], [-10.0, -1.0]])
        result = zonal_min(labels, values, n_labels=2)
        assert result[0] == pytest.approx(-5.0)  # min of label 1
        assert result[1] == pytest.approx(-10.0)  # min of label 2


class TestZonalElevationHistogram:
    """Tests for zonal_elevation_histogram function."""

    def test_basic_histogram(self):
        labels = np.array([[1, 1], [1, 2]])
        dem = np.array([[150.3, 151.7], [152.9, 160.5]])
        result = zonal_elevation_histogram(labels, dem, max_label=2, nodata=-9999)

        assert 1 in result
        assert 2 in result
        assert result[1]["interval_m"] == 1
        assert result[2]["base_m"] == 160  # floor(160.5)
        assert sum(result[1]["counts"]) == 3  # 3 cells in label 1
        assert sum(result[2]["counts"]) == 1  # 1 cell in label 2

    def test_nodata_excluded(self):
        labels = np.array([[1, 1], [1, 0]])
        dem = np.array([[150.0, -9999, 152.0, 0.0]])
        dem = np.array([[150.0, -9999], [152.0, 0.0]])
        result = zonal_elevation_histogram(labels, dem, max_label=1, nodata=-9999)
        assert 1 in result
        # Only 2 valid cells (150.0 and 152.0, not -9999)
        assert sum(result[1]["counts"]) == 2

    def test_empty_input(self):
        labels = np.array([[0, 0]])
        dem = np.array([[150.0, 151.0]])
        result = zonal_elevation_histogram(labels, dem, max_label=0, nodata=-9999)
        assert result == {}

    def test_base_m_correct(self):
        labels = np.array([[1, 1, 1]])
        dem = np.array([[100.5, 103.2, 105.8]])
        result = zonal_elevation_histogram(labels, dem, max_label=1, nodata=-9999)
        assert result[1]["base_m"] == 100  # floor(100.5) = 100
