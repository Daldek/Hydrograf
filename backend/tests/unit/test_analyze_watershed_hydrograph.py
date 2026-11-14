"""Step 6 of analyze_watershed (hydrograph) on a small synthetic catchment, offline.

The morphometry of step 4 carries shape/relief indices and the CN next to the
fields of Hydrolog's WatershedParameters; step 6 must hand Hydrolog only the
accepted fields and the CN computed by the script. The results of step 8 carry the
provider lines exactly when the precipitation came from IMGW-PIB's PMAXTP.
"""

import json
from typing import Any

import pytest
from shapely.geometry import Polygon

from core.attribution import NO_PROVIDER, PMAXTP
from models.schemas import MorphometricParameters
from scripts.analyze_watershed import (
    PMAXTP_PRECIPITATION_SOURCE,
    AnalysisConfig,
    calculate_morphometry,
    data_lines,
    generate_hydrograph,
    save_results,
    write_attribution_file,
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
        flow_path_length_km=2.6,
        flow_path_slope_m_per_m=0.0115,
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


def _pmaxtp_precipitation() -> dict[str, Any]:
    """A precipitation as fetch_precipitation_imgw returns it from PMAXTP."""
    return {
        "source": PMAXTP_PRECIPITATION_SOURCE,
        "probability_percent": 1.0,
        "duration_min": 60,
        "precipitation_ks_mm": 42.0,
        "precipitation_sg_mm": 51.0,
        "precipitation_rb_mm": 4.0,
        "precipitation_mm": 42.0,
        "all_distributions": {"ks": 42.0, "sg": 51.0, "rb": 4.0},
    }


def _saved_results(tmp_path, watershed, precipitation):
    config = _config(tmp_path, cn=80, tc_method="nrcs")
    morph = calculate_morphometry(config, watershed, db=None)
    hydrograph = generate_hydrograph(config, morph, precipitation)
    step_3 = {**watershed, "area_km2": 3.0, "catchment_count": 4}
    path = save_results(config, step_3, morph, precipitation, hydrograph)
    return json.loads(path.read_text(encoding="utf-8"))


def test_results_with_pmaxtp_precipitation_carry_the_provider_lines(
    tmp_path, watershed
):
    results = _saved_results(tmp_path, watershed, _pmaxtp_precipitation())

    assert results["hydrograph"]["design_storm"]["P_mm"] == 42.0
    # PMAXTP's lines, then G and SG of the watershed (DEV-20.4)
    assert results["attribution"] == [
        *PMAXTP.attribution,
        *data_lines().attribution,
    ]
    assert results["attribution"][3].startswith("Źródło: Główny Urząd Geodezji")
    assert results["terms_notice"] == list(PMAXTP.terms_notice)


def test_results_without_pmaxtp_precipitation_carry_the_watershed_lines(
    tmp_path, watershed
):
    results = _saved_results(tmp_path, watershed, None)

    assert results["hydrograph"]["precipitation_source"] == "manual"
    assert results["attribution"] == list(data_lines().attribution)
    assert "terms_notice" not in results


def test_attribution_file_holds_the_lines_and_merges_into_an_existing_one(tmp_path):
    pmaxtp_lines = [*PMAXTP.attribution, *PMAXTP.terms_notice]
    assert write_attribution_file(tmp_path, NO_PROVIDER) is None
    assert not (tmp_path / "ATTRIBUTION.txt").exists()

    path = write_attribution_file(tmp_path, PMAXTP)
    assert path.read_text(encoding="utf-8") == "".join(f"{x}\n" for x in pmaxtp_lines)

    # Another command's line already in the file stays, the PMAXTP lines come once
    foreign = "Źródło: inny dostawca"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([foreign, *lines]) + "\n", encoding="utf-8")
    write_attribution_file(tmp_path, PMAXTP)

    assert path.read_text(encoding="utf-8").splitlines() == [foreign, *pmaxtp_lines]


def test_attribution_file_merge_drops_the_retired_lines_and_orders_the_terms(tmp_path):
    # A file written before Nogat's ECO-065: the old N and RK, another tool's terms
    # line in the new form („Regulamin <whose terms>: <address>”) ahead of its line
    path = tmp_path / "ATTRIBUTION.txt"
    foreign_terms = (
        "Regulamin danych IMGW-PIB: https://danepubliczne.imgw.pl/regulations"
    )
    foreign = "Źródło: inny dostawca"
    path.write_text(
        "\n".join(
            [
                foreign_terms,
                *PMAXTP.attribution,
                "Dane IMGW-PIB można wykorzystywać nieodpłatnie do celów prywatnych "
                "(niezarobkowych). Wykorzystanie … wymaga umowy z IMGW-PIB.",
                "Regulamin: https://klimat.imgw.pl/opady-maksymalne",
                foreign,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    write_attribution_file(tmp_path, PMAXTP)

    assert path.read_text(encoding="utf-8").splitlines() == [
        *PMAXTP.attribution,
        foreign,
        foreign_terms,
        *PMAXTP.terms_notice,
    ]
