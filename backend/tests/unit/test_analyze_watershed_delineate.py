"""Step 3 of analyze_watershed (delineation) on a small synthetic catchment, offline.

Step 3 must run the code of the API (`POST /api/delineate-watershed`, precomputed
mode) and hand steps 4 and 6 what they need. The catchment graph is real (four
sub-catchments, 26 km2); the PostGIS queries are replaced by canned answers, as
in the other tests of the endpoint.
"""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from scipy import sparse
from shapely.geometry import MultiPolygon, Point, Polygon, box

from core.catchment_graph import CatchmentGraph
from scripts.analyze_watershed import (
    AnalysisConfig,
    calculate_morphometry,
    delineate_watershed,
    generate_hydrograph,
)
from utils.geometry import transform_wgs84_to_pl1992

LATITUDE = 52.45
LONGITUDE = 17.31
THRESHOLD_M2 = 10000


def _graph() -> CatchmentGraph:
    """Catchments 1 and 2 drain to 3, 3 drains to the outlet 4."""
    cg = CatchmentGraph()
    cg._n = 4
    cg._loaded = True
    cg._segment_idx = np.array([1, 2, 3, 4], dtype=np.int32)
    cg._threshold_m2 = np.full(4, THRESHOLD_M2, dtype=np.int32)
    cg._area_km2 = np.array([5.0, 3.0, 8.0, 10.0], dtype=np.float32)
    cg._elev_min = np.array([150.0, 160.0, 140.0, 120.0], dtype=np.float32)
    cg._elev_max = np.array([200.0, 210.0, 195.0, 180.0], dtype=np.float32)
    cg._elev_mean = np.array([175.0, 185.0, 167.5, 150.0], dtype=np.float32)
    cg._slope_mean = np.array([5.0, 6.0, 4.0, 3.0], dtype=np.float32)
    cg._stream_length_km = np.array([2.0, 1.5, 3.0, 4.0], dtype=np.float32)
    cg._hydraulic_length_km = np.array([12.5, 10.0, 8.0, 5.0], dtype=np.float32)
    cg._strahler = np.array([1, 1, 2, 3], dtype=np.int8)
    cg._max_flow_dist_m = np.array([12500.0, 10000.0, 8000.0, 5000.0])
    cg._outlet_flow_dist_m = np.array([7500.0, 7500.0, 4000.0, 0.0])
    cg._is_real_stream = np.array([True, False, True, False], dtype=np.bool_)
    cg._segment_length_km = np.array([1.8, 1.2, 2.5, 3.5])
    cg._histograms = [
        {"base_m": 150, "interval_m": 1, "counts": [10, 20, 30, 20, 10]},
        {"base_m": 160, "interval_m": 1, "counts": [5, 15, 25, 15, 5]},
        {"base_m": 140, "interval_m": 1, "counts": [8, 12, 18, 22, 18]},
        {"base_m": 120, "interval_m": 1, "counts": [3, 5, 10, 15, 20, 25]},
    ]
    cg._lookup = {(THRESHOLD_M2, s): i for i, s in enumerate([1, 2, 3, 4])}
    cg._upstream_adj = sparse.csr_matrix(
        (
            np.ones(3, dtype=np.int8),
            (np.array([2, 2, 3], dtype=np.int32), np.array([0, 1, 2], dtype=np.int32)),
        ),
        shape=(4, 4),
        dtype=np.int8,
    )
    return cg


@pytest.fixture
def outlet_point() -> Point:
    return transform_wgs84_to_pl1992(LATITUDE, LONGITUDE)


@pytest.fixture
def served(outlet_point: Point) -> Iterator[MagicMock]:
    """Serve the endpoint the graph and the database answers; yield the session."""
    db = MagicMock()
    # The point lies in the sub-catchment of the segment 4 (the outlet).
    db.execute.return_value.fetchone.return_value = SimpleNamespace(segment_idx=4)
    boundary = MultiPolygon(
        [
            box(
                outlet_point.x - 2000,
                outlet_point.y - 2000,
                outlet_point.x + 3000,
                outlet_point.y + 3000,
            )
        ]
    )
    stream: dict[str, Any] = {
        "strahler_order": 3,
        "length_m": 4000.0,
        "upstream_area_km2": 26.0,
        "downstream_x": outlet_point.x,
        "downstream_y": outlet_point.y,
    }
    target = "api.endpoints.watershed"
    with (
        patch(f"{target}.get_catchment_graph", return_value=_graph()),
        patch(f"{target}.merge_catchment_boundaries", return_value=boundary),
        patch(f"{target}.get_stream_info_by_segment_idx", return_value=stream),
        patch(
            f"{target}.get_segment_outlet",
            return_value={"x": outlet_point.x, "y": outlet_point.y},
        ),
        patch(f"{target}.get_main_channel_feature_collection", return_value=None),
        patch(f"{target}.get_main_stream_geojson", return_value=None),
        patch(f"{target}.get_longest_flow_path_geojson", return_value=None),
        patch(f"{target}.get_divide_flow_path_geojson", return_value=None),
        patch(f"{target}.build_land_cover_stats", return_value=None),
        patch(f"{target}.build_hsg_stats", return_value=None),
    ):
        yield db


def _config(tmp_path, **kwargs: Any) -> AnalysisConfig:
    return AnalysisConfig(
        latitude=LATITUDE,
        longitude=LONGITUDE,
        output_dir=tmp_path / "results",
        data_dir=tmp_path / "data",
        **kwargs,
    )


def test_step_3_delineates_the_catchment_the_api_delineates(
    tmp_path, served, outlet_point
):
    watershed = delineate_watershed(_config(tmp_path), served)

    # The four sub-catchments upstream of the clicked outlet: 5 + 3 + 8 + 10 km2.
    assert watershed["area_km2"] == pytest.approx(26.0)
    assert watershed["catchment_count"] == 4
    # The boundary is the merged one, in EPSG:2180 and in WGS84.
    assert watershed["boundary"].contains(outlet_point)
    assert Polygon(watershed["boundary_wgs84"]).contains(Point(LONGITUDE, LATITUDE))
    assert watershed["morphometry"]["area_km2"] == pytest.approx(26.0)
    assert watershed["morphometry"]["perimeter_km"] == pytest.approx(
        watershed["boundary"].length / 1000, rel=1e-3
    )
    # The hypsometric curve of the graph is kept for the figures.
    assert len(watershed["hypsometric_curve"]) > 1


def test_steps_3_4_and_6_run_on_the_result_of_step_3(tmp_path, served):
    config = _config(tmp_path, cn=75, tc_method="kirpich")
    watershed = delineate_watershed(config, served)

    morph = calculate_morphometry(config, watershed, served)
    hydrograph = generate_hydrograph(config, morph, None)

    assert morph["cn"] == 75
    assert morph["cn_source"] == "config"
    assert hydrograph["tc_min"] > 0
    assert hydrograph["design_storm"]["Qmax_m3s"] > 0
