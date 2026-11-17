"""Hydrolog's warnings in the hydrograph (E5b-08).

A numba compile swaps the warning filters and handlers of the whole process while it
holds numba's compiler lock, takes the warnings of other threads for its own and emits
them again from their text. A HydrologWarning cannot be made from a text, so a compile
beside a hydrograph that warned failed with a TypeError; the hydrograph's Hydrolog
computations now hold that lock.
"""

import sys
import threading
from unittest.mock import MagicMock

import numba
import pytest

from api.endpoints.hydrograph import generate_hydrograph
from models.schemas import HydrographRequest

# A daily series: the step of 1440 min is outside the typical range of the SCS unit
# hydrograph, so every hydrograph warns (OutsideTypicalRange)
DAILY = HydrographRequest(
    latitude=51.0,
    longitude=16.05,
    custom_precipitation={"timestep_min": 1440, "depths_mm": [10.0, 60.0, 5.0]},
    morphometry={
        "area_km2": 10.0,
        "perimeter_km": 20.0,
        "length_km": 5.0,
        "elevation_min_m": 120.0,
        "elevation_max_m": 190.0,
        "elevation_mean_m": 155.0,
        "mean_slope_m_per_m": 0.04,
        "channel_length_km": 6.5,
        "channel_slope_m_per_m": 0.0108,
        "flow_path_length_km": 7.0,
        "flow_path_slope_m_per_m": 0.01,
        "length_to_centroid_km": 3.5,
        "cn": 72.0,
    },
)


def _fresh_function():
    """Return a function that numba has not compiled: its first call compiles it."""

    def double_plus_one(x):
        return x * 2.0 + 1.0

    return numba.njit(double_plus_one)


# Every warning reaches the handlers, not only the first of each place
@pytest.mark.filterwarnings("always::UserWarning")
def test_a_numba_compile_beside_warning_hydrographs_does_not_fail():
    started = threading.Event()
    stop = threading.Event()
    hydrograph_failures: list[Exception] = []

    def hydrographs() -> None:
        try:
            while not stop.is_set():
                generate_hydrograph(DAILY, db=MagicMock())
                started.set()
        except Exception as error:
            hydrograph_failures.append(error)
            started.set()

    # The threads take turns every 0.1 ms, so the compiles and the warnings
    # interleave as they do under load
    switch_interval_s = sys.getswitchinterval()
    sys.setswitchinterval(1e-4)
    thread = threading.Thread(target=hydrographs)
    thread.start()
    compile_failures: list[Exception] = []
    try:
        assert started.wait(timeout=30)
        for _ in range(10):
            try:
                _fresh_function()(1.0)
            except Exception as error:
                compile_failures.append(error)
    finally:
        stop.set()
        thread.join()
        sys.setswitchinterval(switch_interval_s)

    assert compile_failures == []
    assert hydrograph_failures == []
