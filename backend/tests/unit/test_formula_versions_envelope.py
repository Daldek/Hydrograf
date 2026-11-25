"""
The formula versions of a hydrograph against those of Hydrolog's envelope (CMP-2.8).

Hydrograf computes with Hydrolog's classes and names the specs of the steps it ran in
``core.formula_versions``. Hydrolog's ``hydrograph generate`` run on the same inputs
(those of the response's hand-off, as Hydrolog's GUI opens them) declares in its
envelope the ``formula_versions`` of the formulas it ran. Both must agree exactly, but
for the steps Hydrograf does itself: the weighting of the PMAXTP grid and the
watershed's CN from land cover and equal-area slope. A spec Hydrolog adds or bumps and
Hydrograf forgets fails here.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import hydrolog
import pytest
from fastapi.testclient import TestClient

from api.main import app
from core.database import get_db
from core.formula_versions import (
    AREAL_DEPTHS,
    FLOW_PATH_EQUAL_AREA_SLOPE,
    TR55_CN,
    formula_versions,
)
from core.precipitation import DesignDepth
from tests.job_runner import run_job

# The steps of a hydrograph that Hydrograf computes itself, outside the command
HYDROGRAFS_OWN = frozenset(
    spec.name for spec in (*AREAL_DEPTHS.values(), TR55_CN, FLOW_PATH_EQUAL_AREA_SLOPE)
)

# The Kamiennik above its mouth into the Kaczawa, as the delineation gives it
MORPHOMETRY = {
    "area_km2": 134.9683,
    "perimeter_km": 84.4609,
    "length_km": 22.2789,
    "elevation_min_m": 256.77,
    "elevation_max_m": 722.68,
    "elevation_mean_m": 418.93,
    "mean_slope_m_per_m": 0.135824,
    "channel_length_km": 21.3978,
    "channel_slope_m_per_m": 0.016872,
    "real_channel_length_km": 20.724,
    "cn": 69.6,
    "imperviousness": 0.067,
    "forest_pct": 47.9,
    "urban_pct": 2.5,
    "compactness_coefficient": 2.0509,
    "length_to_centroid_km": 13.6173,
    "hydraulic_length_km": 22.2789,
    "flow_path_length_km": 22.2789,
    "flow_path_slope_m_per_m": 0.016038,
    "flow_path_equal_area_slope_m_per_m": 0.0084766,
    "overland_length_km": 0.2563,
    "overland_slope_m_per_m": 0.163324,
}

RAINFALLS = {
    "beta": {},
    "beta-shape": {"hietogram_alpha": 3.5, "hietogram_beta": 2.0},
    "block": {"hietogram_type": "block"},
    "euler_ii": {"hietogram_type": "euler_ii"},
    "own-series": {
        "custom_precipitation": {"timestep_min": 10, "depths_mm": [5.0, 20.0, 15.5]}
    },
}
UNIT_HYDROGRAPHS = {
    "scs-kirpich": {"uh_model": "scs", "tc_method": "kirpich"},
    "scs-nrcs": {"uh_model": "scs", "tc_method": "nrcs"},
    "scs-kerby-kirpich": {
        "uh_model": "scs",
        "tc_method": "kerby_kirpich",
        "tc_retardance": 0.4,
    },
    "snyder": {"uh_model": "snyder", "snyder_ct": 1.4, "snyder_cp": 0.65},
    "nash-lutz": {"uh_model": "nash", "nash_estimation": "from_lutz"},
    "nash-urban": {"uh_model": "nash", "nash_estimation": "from_urban_regression"},
}


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _hydrograph(client: TestClient, **options: Any) -> dict[str, Any]:
    """Hydrograf's hydrograph of the Kamiennik (fast path, PMAXTP lookup patched)."""
    body = {
        "latitude": 51.01544,
        "longitude": 15.88984,
        "duration": "6h",
        "probability": 1,
        "morphometry": MORPHOMETRY,
        **options,
    }
    depth = DesignDepth(73.123456789, "idw", ())
    with patch("api.endpoints.hydrograph.point_depth", return_value=depth):
        response = run_job(client, "hydrograph generate", body)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()["result"]
    return result


def _envelope_versions(handoff: dict[str, Any]) -> dict[str, int]:
    """The formula versions of Hydrolog's commands on the inputs of the hand-off."""
    payload = handoff["payload"]
    (subcatchment,) = [n for n in payload["nodes"] if n["type"] == "subcatchment"]
    options = {k: v for k, v in subcatchment["runoff"].items() if k != "model"}
    rainfall = subcatchment["rainfall"]
    if rainfall["kind"] == "series":
        options["values"] = rainfall["depths_mm"]
    else:
        options.update({k: v for k, v in rainfall.items() if k != "kind"})
    runoff_origin = handoff["provenance"].get("runoff", {})
    if runoff_origin.get("method") == "lutz":
        # Hydrolog's GUI reopens Nash by Lutz as Lutz, from the watershed
        del options["nash_n"], options["nash_k_min"]
        options["nash_estimation"] = "lutz"
    envelope = hydrolog.run_command(
        "hydrograph generate",
        watershed=subcatchment["watershed"],
        timestep_min=payload["timestep_min"],
        **options,
    ).to_dict()
    versions: dict[str, int] = envelope["formula_versions"]
    if runoff_origin.get("nash_estimation") == "from_urban_regression":
        # `hydrograph generate` takes the regression's n and K; `uh nash` gives them
        regression = hydrolog.run_command(
            "uh nash",
            area_km2=subcatchment["watershed"]["area_km2"],
            urban_effective_precip_mm=runoff_origin["effective_precip_mm"],
            urban_duration_h=runoff_origin["duration_h"],
            urban_fraction=runoff_origin["urban_fraction"],
            timestep_min=payload["timestep_min"],
        ).to_dict()
        versions = {**versions, **regression["formula_versions"]}
    return dict(sorted(versions.items()))


@pytest.mark.filterwarnings("ignore")
@pytest.mark.parametrize("amc", ["II", "III"])
@pytest.mark.parametrize("unit_hydrograph", UNIT_HYDROGRAPHS)
@pytest.mark.parametrize("rainfall", RAINFALLS)
def test_formula_versions_are_those_of_hydrologs_envelope(
    client, rainfall, unit_hydrograph, amc
):
    body = _hydrograph(
        client, amc=amc, **RAINFALLS[rainfall], **UNIT_HYDROGRAPHS[unit_hydrograph]
    )

    versions = body["formula_versions"]
    own = {name: v for name, v in versions.items() if name in HYDROGRAFS_OWN}
    origin = body["handoff"]["provenance"]["rainfall"]
    assert own == (
        formula_versions([AREAL_DEPTHS[origin["interpolation"]]])
        if origin["source"] == "pmaxtp"
        else {}
    )
    computed = {name: v for name, v in versions.items() if name not in own}
    assert computed == _envelope_versions(body["handoff"])
