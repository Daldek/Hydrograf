"""Tests for core.zonal_stats module."""

import numpy as np
import pytest

from core.zonal_stats import zonal_bincount, zonal_max


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
