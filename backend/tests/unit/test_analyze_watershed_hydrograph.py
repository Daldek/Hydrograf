"""Step 6 of analyze_watershed (hydrograph) on a small synthetic catchment, offline.

The morphometry of step 4 carries shape/relief indices and the CN next to the
fields of Hydrolog's WatershedParameters; step 6 must hand Hydrolog only the
accepted fields and the CN computed by the script.
"""

from typing import Any

import pytest
from shapely.geometry import Polygon

from models.schemas import MorphometricParameters
from scripts.analyze_watershed import (
    AnalysisConfig,
    calculate_morphometry,
    generate_hydrograph,
)


@pytest.fixture
def watershed() -> dict[str, Any]:
    """A 3 km2 catchment as step 3 returns it: the morphometry of the API."""
    morphometry = MorphometricParameters(
        area_km2=3.0,
        perimeter_km=8.0,
        length_km=2.5,
        elevation_min_m=100.0,
        elevation_max_m=125.0,
        elevation_mean_m=112.0,
        mean_slope_m_per_m=0.03,
        channel_length_km=2.4,
        channel_slope_m_per_m=0.01,
        compactness_coefficient=1.3,
        circularity_ratio=0.6,
        relief_ratio=14.4,
    )
    return {
        "morphometry": morphometry.model_dump(),
        "boundary": Polygon([(0, 0), (300, 0), (300, 200), (0, 200)]),
        "boundary_wgs84": [[17.0, 52.0], [17.01, 52.0], [17.01, 52.01]],
    }


def _config(tmp_path, *, cn: int, tc_method: str) -> AnalysisConfig:
    return AnalysisConfig(
        cn=cn,
        tc_method=tc_method,
        duration_min=60,
        output_dir=tmp_path / "results",
        data_dir=tmp_path / "data",
    )


@pytest.mark.parametrize("tc_method", ["kirpich", "nrcs"])
def test_generates_hydrograph_from_step_4_morphometry(tmp_path, watershed, tc_method):
    config = _config(tmp_path, cn=80, tc_method=tc_method)
    morph = calculate_morphometry(config, watershed, db=None)
    # The shape/relief indices of step 4 are what broke WatershedParameters(**morph).
    assert "compactness_coefficient" in morph

    hydrograph = generate_hydrograph(config, morph, None)

    assert hydrograph["cn"] == 80
    assert hydrograph["tc_method"] == tc_method
    assert hydrograph["tc_min"] > 0
    assert hydrograph["design_storm"]["Qmax_m3s"] > 0
    assert len(hydrograph["scenarios"]) == 6


def test_hydrograph_uses_the_cn_computed_by_the_script(tmp_path, watershed):
    low = calculate_morphometry(
        _config(tmp_path, cn=60, tc_method="nrcs"), watershed, db=None
    )
    high = calculate_morphometry(
        _config(tmp_path, cn=90, tc_method="nrcs"), watershed, db=None
    )

    q_low = generate_hydrograph(_config(tmp_path, cn=60, tc_method="nrcs"), low, None)
    q_high = generate_hydrograph(_config(tmp_path, cn=90, tc_method="nrcs"), high, None)

    assert q_low["cn"] == 60
    assert q_high["cn"] == 90
    assert q_high["design_storm"]["Qmax_m3s"] > q_low["design_storm"]["Qmax_m3s"]
