"""What the old-versus-new tests of the DEM processing rely on (tests/dem_equivalence).

The synthetic DEMs hold the cases that the rewritten steps must get through, and
assert_identical misses no difference between an old and a new result.
"""

import re

import numpy as np
import pytest
from scipy import ndimage

from core.hydrology import fill_internal_nodata_holes
from tests.dem_equivalence import (
    DEM_CASES,
    NODATA,
    assert_identical,
    derive_hydrology,
    synthetic_dem,
)

HOLE_CASES = {name: case for name, case in DEM_CASES.items() if case.get("holes", True)}


@pytest.mark.parametrize("case", DEM_CASES.values(), ids=DEM_CASES.keys())
def test_the_same_arguments_give_the_same_dem(case):
    dem, metadata = synthetic_dem(**case)
    again, metadata_again = synthetic_dem(**case)

    assert_identical(again, dem)
    assert metadata_again == metadata


@pytest.mark.parametrize("case", HOLE_CASES.values(), ids=HOLE_CASES.keys())
def test_holes_take_up_to_four_passes_and_one_stays_open(case):
    dem, _ = synthetic_dem(**case)

    filled = [
        fill_internal_nodata_holes(dem, NODATA, max_iterations=passes)[1]
        for passes in (1, 2, 3, 4)
    ]
    patched, _ = fill_internal_nodata_holes(dem, NODATA, max_iterations=10)
    regions, count = ndimage.label(patched == NODATA, structure=np.ones((3, 3)))
    on_frame = np.unique(
        np.concatenate([regions[0], regions[-1], regions[:, 0], regions[:, -1]])
    )

    assert filled[0] < filled[1] < filled[2] < filled[3]
    assert count > np.count_nonzero(on_frame)


@pytest.mark.parametrize("case", DEM_CASES.values(), ids=DEM_CASES.keys())
def test_pyflwdir_leaves_internal_sinks_next_to_nodata(case):
    hydrology = derive_hydrology(*synthetic_dem(**case))
    inside = np.zeros(hydrology.d8_fdir.shape, dtype=bool)
    inside[1:-1, 1:-1] = True

    sinks = (hydrology.d8_fdir == 0) & (hydrology.filled_dem != NODATA) & inside

    assert sinks.any()


NAN_ROW = np.array([1.0, np.nan, -0.0], dtype=np.float32)


class TestAssertIdentical:
    def test_accepts_equal_results_with_nan(self):
        result = {"rasters": [NAN_ROW.copy()], "stats": (1, 2.5, None, "a")}

        assert_identical(
            {"rasters": [NAN_ROW.copy()], "stats": (1, 2.5, None, "a")}, result
        )

    @pytest.mark.parametrize(
        ("actual", "expected", "message"),
        [
            (
                np.array([1.0, 2.0, 3.0]),
                np.array([1.0, 2.5, 3.0]),
                "result: 1 of 3 values differ, the first at (1,)",
            ),
            (np.array([0.0]), np.array([-0.0]), "the first at (0,)"),
            (NAN_ROW.astype(np.float64), NAN_ROW, "float64 (3,) != float32 (3,)"),
            (np.float64(1.0), 1.0, "float64 != float"),
            ({"b": 1, "a": 2}, {"a": 2, "b": 1}, "keys ['b', 'a'] != ['a', 'b']"),
            ([1, 2], [1, 2, 3], "2 items != 3 items"),
            ({"segments": [(0, 1.0)]}, {"segments": [(0, 1.5)]}, "['segments'][0][1]"),
        ],
        ids=[
            "value",
            "signed-zero",
            "dtype",
            "scalar-type",
            "key-order",
            "length",
            "nested",
        ],
    )
    def test_rejects_any_difference(self, actual, expected, message):
        with pytest.raises(AssertionError, match=re.escape(message)):
            assert_identical(actual, expected)
