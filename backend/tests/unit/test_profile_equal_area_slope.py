"""The equal-area slope of the profile of a D8 path (Lutz's Jg, ADR-088)."""

import numpy as np
import pytest

from core.divide_flow_path import profile_equal_area_slope

NODATA = -9999.0


def _path(elevations: list[float], step_m: float = 5.0):
    """A path along one row from the outlet (column 0) up; the cells head first."""
    n = len(elevations)
    dem = np.array([elevations], dtype=np.float32)
    flow_dist = np.array([[step_m * i for i in range(n)]], dtype=np.float32)
    cells = [(0, col) for col in range(n - 1, -1, -1)]
    return cells, flow_dist, dem


def test_a_straight_profile_gives_its_own_slope():
    cells, flow_dist, dem = _path([100.0, 101.0, 102.0, 103.0, 104.0])

    assert profile_equal_area_slope(cells, flow_dist, None, dem, NODATA) == 0.2


def test_a_concave_profile_is_less_steep_than_between_its_ends():
    cells, flow_dist, dem = _path([100.0, 100.5, 101.0, 102.0, 108.0])

    slope = profile_equal_area_slope(cells, flow_dist, None, dem, NODATA)

    assert slope is not None
    assert slope < (108.0 - 100.0) / 20.0


def test_an_end_beyond_the_data_starts_the_profile_at_the_cell_above():
    cells, flow_dist, dem = _path([NODATA, 101.0, 102.0, 103.0])

    assert profile_equal_area_slope(cells, flow_dist, None, dem, NODATA) == 0.2


@pytest.mark.parametrize(
    "elevations",
    [[100.0, 100.0, 100.0], [100.0, 101.0, NODATA, 103.0], [100.0]],
    ids=["flat", "gap", "one-cell"],
)
def test_a_profile_that_cannot_be_measured_has_no_slope(elevations):
    cells, flow_dist, dem = _path(elevations)

    assert profile_equal_area_slope(cells, flow_dist, None, dem, NODATA) is None
