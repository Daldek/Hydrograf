"""
Integration tests for ``POST /api/v1/precipitation/depth`` (``precipitation depth``).

The command weighs a catchment's PMAXTP grid by Thiessen polygons (ADR-069). The tests
mock the database session: its ``precipitation_data`` queries (the grid points of
``core.precipitation.thiessen_cells`` and the depths of a scenario of
``core.precipitation.areal_depth``) answer from a regular 2 km grid whose depth varies
from point to point and with the scenario.
"""

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import MultiPolygon, Polygon, mapping

from api.main import app
from core.attribution import PMAXTP
from core.database import get_db
from core.precipitation import DURATION_STR_TO_MIN
from tests.job_runner import run_job
from utils.geometry import transform_polygon_pl1992_to_wgs84

URL = "/api/v1/precipitation/depth"

# Module paths for patching the delineation of the hydrograph's full path
_HG = "api.endpoints.hydrograph"
_WS = "api.endpoints.watershed"

# The grid: points every 2 km, so their Thiessen polygons are 2 km squares centred on
# them, with edges at odd kilometres
_GRID_XS = range(630_000, 652_001, 2_000)
_GRID_YS = range(476_000, 498_001, 2_000)

Depth = Callable[[float, float, str, float], float]


def _depth(x: float, y: float, duration: str, probability: float) -> float:
    """The grid's depth [mm] of a scenario at a point: varies with all four."""
    minutes = DURATION_STR_TO_MIN[duration]
    scale = (1 + minutes / 600) * (1 + (10.0 - probability) / 20)
    return scale * (40.0 + 0.37 * (x - 630_000) / 1000 + 0.11 * (y - 476_000) / 1000)


def _session(depth: Depth | None = _depth, *, grid: bool = True) -> MagicMock:
    """A session whose ``precipitation_data`` is the 2 km grid with ``depth``.

    ``grid=False`` leaves the table empty; ``depth=None`` keeps the grid points but
    holds no depth of any scenario.
    """
    points = [(x, y) for x in _GRID_XS for y in _GRID_YS] if grid else []
    session = MagicMock()

    def execute(query: Any, params: dict[str, Any] | None = None) -> MagicMock:
        result = MagicMock()
        sql = str(query)
        if "precipitation_data" not in sql:
            result.fetchone.return_value = None
            result.fetchall.return_value = []
            return result
        result.scalar.return_value = bool(points)
        if "duration = :duration" in sql:
            assert params is not None
            result.fetchall.return_value = (
                []
                if depth is None
                else [
                    SimpleNamespace(
                        x=x,
                        y=y,
                        precipitation_mm=depth(
                            x, y, params["duration"], params["probability"]
                        ),
                    )
                    for x, y in points
                ]
            )
        else:
            result.fetchall.return_value = [
                SimpleNamespace(x=x, y=y) for x, y in points
            ]
        return result

    session.execute.side_effect = execute
    return session


def _wgs84(polygon_2180: Polygon) -> dict[str, Any]:
    """The GeoJSON geometry of an EPSG:2180 polygon in WGS84."""
    return dict(mapping(transform_polygon_pl1992_to_wgs84(polygon_2180)))


# 2.5 km2 over two Thiessen polygons: 1 km2 in that of (640000, 486000) and 1.5 km2 in
# that of (642000, 486000)
_TWO_CELLS_2180 = Polygon(
    [(640_000, 486_000), (642_500, 486_000), (642_500, 487_000), (640_000, 487_000)]
)
_TWO_CELLS = _wgs84(_TWO_CELLS_2180)


@pytest.fixture
def client():
    """A test client on the grid of ``_session``."""
    app.dependency_overrides[get_db] = lambda: _session()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _post(client: TestClient, boundary: Any, **options: Any):
    body = {"boundary": boundary, "duration_min": 60, "probability_percent": 10}
    return client.post(URL, json={**body, **options})


def _assert_problem(response, status: int, code: str, reason: str) -> dict[str, Any]:
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    problem: dict[str, Any] = response.json()
    assert problem["code"] == code
    assert problem["details"]["reason"] == reason
    assert problem["command"] == "precipitation depth"
    return problem


class TestBoundary:
    """The boundary must be a valid polygon in WGS84."""

    @pytest.mark.parametrize(
        "boundary",
        [
            pytest.param({"type": "Point", "coordinates": [21.0, 52.0]}, id="point"),
            pytest.param(
                {"type": "LineString", "coordinates": [[21.0, 52.0], [21.1, 52.1]]},
                id="linestring",
            ),
            pytest.param(
                {"type": "Feature", "geometry": None, "properties": {}},
                id="feature-without-geometry",
            ),
            pytest.param(
                {"type": "Feature", "properties": {}}, id="feature-missing-geometry"
            ),
            pytest.param(
                {
                    "type": "Polygon",
                    "coordinates": [
                        [[21.0, 52.0], [21.1, 52.1], [21.1, 52.0], [21.0, 52.1]]
                    ],
                },
                id="self-intersecting",
            ),
            pytest.param({"type": "Polygon", "coordinates": []}, id="empty"),
            pytest.param({"type": "MultiPolygon", "coordinates": []}, id="empty-multi"),
            pytest.param(
                {
                    "type": "Polygon",
                    "coordinates": [
                        [[200.0, 52.0], [201.0, 52.0], [201.0, 53.0], [200.0, 52.0]]
                    ],
                },
                id="longitude-outside-wgs84",
            ),
            pytest.param(
                {
                    "type": "Polygon",
                    "coordinates": [
                        [[21.0, 95.0], [22.0, 95.0], [22.0, 96.0], [21.0, 95.0]]
                    ],
                },
                id="latitude-outside-wgs84",
            ),
            pytest.param({"type": "Polygon", "coordinates": "garbage"}, id="garbage"),
            pytest.param({"type": "Banana", "coordinates": [1, 2]}, id="unknown-type"),
            pytest.param({}, id="no-type"),
        ],
    )
    def test_invalid_boundary_is_400(self, client, boundary):
        problem = _assert_problem(
            _post(client, boundary), 400, "validation_error", "boundary_invalid"
        )
        assert problem["details"]["option"] == "boundary"

    @pytest.mark.parametrize(
        "boundary",
        [
            pytest.param(_TWO_CELLS, id="polygon"),
            pytest.param(
                {"type": "Feature", "geometry": _TWO_CELLS, "properties": {}},
                id="feature",
            ),
            pytest.param(
                {"type": "MultiPolygon", "coordinates": [_TWO_CELLS["coordinates"]]},
                id="multipolygon",
            ),
            pytest.param(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "MultiPolygon",
                        "coordinates": [_TWO_CELLS["coordinates"]],
                    },
                    "properties": {"area_km2": 2.5},
                },
                id="feature-of-multipolygon",
            ),
        ],
    )
    def test_polygon_forms_are_accepted(self, client, boundary):
        response = _post(client, boundary)

        assert response.status_code == 200
        assert response.json()["result"]["area_km2"] == pytest.approx(2.5)

    def test_boundary_above_the_limit_is_422(self, client):
        # About 136 km x 111 km
        boundary = {
            "type": "Polygon",
            "coordinates": [
                [[19.0, 51.5], [21.0, 51.5], [21.0, 52.5], [19.0, 52.5], [19.0, 51.5]]
            ],
        }

        problem = _assert_problem(
            _post(client, boundary), 422, "unsupported", "boundary_too_large"
        )

        assert problem["details"]["area_km2"] > 10_000
        assert problem["details"]["limit_km2"] == 10_000


class TestScenario:
    """The duration and probability must be those of PMAXTP's tables."""

    @pytest.mark.parametrize(
        ("options", "pointers"),
        [
            ({"duration_min": 61}, ["/body/duration_min"]),
            ({"duration_min": "1h"}, ["/body/duration_min"]),
            ({"probability_percent": 11}, ["/body/probability_percent"]),
            ({"probability_percent": 0}, ["/body/probability_percent"]),
            (
                {"duration_min": 7, "probability_percent": 15},
                ["/body/duration_min", "/body/probability_percent"],
            ),
        ],
    )
    def test_scenario_outside_the_tables_is_400(self, client, options, pointers):
        response = _post(client, _TWO_CELLS, **options)

        problem = _assert_problem(response, 400, "validation_error", "invalid_request")
        assert problem["details"]["fields"] == pointers
        assert [error["pointer"] for error in problem["errors"]] == pointers


class TestNoData:
    """Without the scenario's depths around the boundary the answer is 404."""

    @pytest.mark.parametrize(
        "session",
        [
            # thiessen_cells finds no point, areal_depth gives None
            pytest.param(lambda: _session(grid=False), id="no-grid-point"),
            # the points have no depth of the scenario: UnknownGridPointError
            pytest.param(lambda: _session(None), id="no-depth-of-the-scenario"),
        ],
    )
    def test_no_data_is_404(self, session):
        app.dependency_overrides[get_db] = session
        try:
            response = _post(TestClient(app), _TWO_CELLS, duration_min=360)
        finally:
            app.dependency_overrides.clear()

        problem = _assert_problem(response, 404, "no_data", "no_design_depth_data")
        assert problem["details"]["duration_min"] == 360
        assert problem["details"]["probability_percent"] == 10


class TestDesignDepth:
    """The answer: the Thiessen mean of the grid over the boundary."""

    def test_envelope(self, client):
        response = _post(client, _TWO_CELLS)

        assert response.status_code == 200
        body = response.json()
        assert body["schema"] == "hydrograf-result/1"
        assert body["command"] == "precipitation depth"
        assert body["status"] == "ok"
        assert body["result"]["schema"] == "hydrograf-design-depth/1"

    def test_depth_is_the_unrounded_thiessen_mean(self, client):
        response = _post(client, _TWO_CELLS, duration_min=360, probability_percent=1)

        result = response.json()["result"]
        west = _depth(640_000, 486_000, "6h", 1.0)
        east = _depth(642_000, 486_000, "6h", 1.0)
        expected = 0.4 * west + 0.6 * east
        # 4 decimals: a rounded depth would miss them
        assert round(expected, 2) != round(expected, 4)
        assert result["pmaxtp_depth_mm"] == pytest.approx(expected, abs=1e-6)
        assert result["duration_min"] == 360
        assert result["probability_percent"] == 1
        assert result["interpolation"] == "thiessen"
        assert result["area_km2"] == pytest.approx(2.5)

    def test_grid_points_carry_depths_and_weights(self, client):
        result = _post(client, _TWO_CELLS).json()["result"]

        points = sorted(result["pmaxtp_points"], key=lambda p: p["easting_m"])
        assert [(p["easting_m"], p["northing_m"]) for p in points] == [
            (640_000, 486_000),
            (642_000, 486_000),
        ]
        assert [p["precipitation_mm"] for p in points] == [
            pytest.approx(_depth(640_000, 486_000, "1h", 10.0)),
            pytest.approx(_depth(642_000, 486_000, "1h", 10.0)),
        ]
        assert [p["weight"] for p in points] == [
            pytest.approx(0.4),
            pytest.approx(0.6),
        ]
        assert [p["area_km2"] for p in points] == [
            pytest.approx(1.0),
            pytest.approx(1.5),
        ]
        for point in points:
            assert 51.0 < point["latitude"] < 53.0
            assert 20.0 < point["longitude"] < 22.0

    def test_pmaxtp_lines(self, client):
        result = _post(client, _TWO_CELLS).json()["result"]

        assert result["attribution"] == list(PMAXTP.attribution)
        assert result["terms_notice"] == list(PMAXTP.terms_notice)


# ---------------------------------------------------------------------------
# The depth equals the design depth of ``hydrograph generate``
# ---------------------------------------------------------------------------

# An irregular 18 km2 catchment over a dozen Thiessen polygons
_CATCHMENT_2180 = Polygon(
    [
        (638_300, 485_400),
        (641_900, 484_700),
        (643_600, 487_200),
        (642_100, 489_900),
        (639_400, 489_100),
        (638_900, 487_300),
    ]
)


def _delineation_patches(boundary_2180: MultiPolygon) -> list[Any]:
    """The patches of the full path's delineation, which merges ``boundary_2180``."""
    area_km2 = boundary_2180.area / 1e6
    cg = MagicMock()
    cg.loaded = True
    cg._segment_idx = np.array([10, 11, 12], dtype=np.int32)
    cg.find_catchment_at_point.return_value = 0
    cg.traverse_upstream.return_value = np.array([0, 1, 2])
    cg.get_segment_indices.return_value = [10, 11, 12]
    cg.aggregate_stats.return_value = {
        "area_km2": area_km2,
        "elevation_min_m": 120.0,
        "elevation_max_m": 190.0,
        "elevation_mean_m": 155.0,
        "mean_slope_m_per_m": 0.04,
        "stream_length_km": 6.5,
        "drainage_density_km_per_km2": 0.65,
        "stream_frequency_per_km2": 0.3,
        "max_strahler_order": 3,
    }
    morphometry = {
        "area_km2": round(area_km2, 2),
        "perimeter_km": boundary_2180.length / 1000,
        "length_km": 5.0,
        "elevation_min_m": 120.0,
        "elevation_max_m": 190.0,
        "elevation_mean_m": 155.0,
        "mean_slope_m_per_m": 0.04,
        "channel_length_km": 6.5,
        "channel_slope_m_per_m": 0.0108,
        "length_to_centroid_km": 3.5,
        "hydraulic_length_km": 7.0,
        "flow_path_length_km": 7.0,
        "flow_path_slope_m_per_m": 0.01,
        "flow_path_equal_area_slope_m_per_m": 0.007,
        "overland_length_km": 0.2,
        "overland_slope_m_per_m": 0.05,
        "cn": 75,
        "source": "Hydrograf",
        "crs": "EPSG:2180",
    }
    segment = {
        "segment_idx": 10,
        "strahler_order": 3,
        "length_m": 1200.0,
        "upstream_area_km2": area_km2,
        "downstream_x": 640_000.0,
        "downstream_y": 486_000.0,
    }
    return [
        patch(f"{_WS}.loaded_catchment_graph", return_value=cg),
        patch(f"{_WS}.get_stream_info_by_segment_idx", return_value=segment),
        patch(f"{_HG}.merge_catchment_boundaries", return_value=boundary_2180),
        patch(
            f"{_WS}.get_segment_outlet", return_value={"x": 640_000.0, "y": 486_000.0}
        ),
        patch(f"{_WS}.build_morph_dict_from_graph", return_value=morphometry),
        patch("core.land_cover.get_land_cover_for_boundary", return_value=None),
        patch(f"{_WS}.build_hsg_stats", return_value=None),
    ]


class TestEqualsTheHydrographsDepth:
    """The depth is the design depth ``hydrograph generate`` takes (ADR-069)."""

    @pytest.mark.parametrize(
        ("duration", "duration_min", "probability"),
        [("1h", 60, 10), ("6h", 360, 1)],
    )
    def test_depth_of_the_hydrographs_watershed(
        self, client, duration, duration_min, probability
    ):
        patches = _delineation_patches(MultiPolygon([_CATCHMENT_2180]))
        for p in patches:
            p.start()
        try:
            generated = run_job(
                client,
                "hydrograph generate",
                {
                    "latitude": 52.23,
                    "longitude": 21.01,
                    "duration": duration,
                    "probability": probability,
                },
            )
        finally:
            for p in patches:
                p.stop()
        assert generated.status_code == 200
        hydrograph = generated.json()["result"]
        precipitation = hydrograph["precipitation"]
        assert precipitation["interpolation"] == "thiessen"

        # The watershed the hydrograph delineated, as a client sends it on
        response = _post(
            client,
            hydrograph["watershed"]["boundary_geojson"],
            duration_min=duration_min,
            probability_percent=probability,
        )

        assert response.status_code == 200
        result = response.json()["result"]
        # The depth Hydrograf gave its hydrograph and hands Hydrolog over, unrounded;
        # the tolerance covers the boundary's round trip through WGS84
        (subcatchment,) = [
            node
            for node in hydrograph["handoff"]["payload"]["nodes"]
            if node["type"] == "subcatchment"
        ]
        rainfall = subcatchment["rainfall"]
        assert result["pmaxtp_depth_mm"] == pytest.approx(
            rainfall["total_mm"], rel=1e-9
        )
        assert round(result["pmaxtp_depth_mm"], 2) == precipitation["pmaxtp_depth_mm"]
        # The same grid points, with the same depths and weights
        hydrograph_points = {
            (p["easting_m"], p["northing_m"]): p for p in precipitation["pmaxtp_points"]
        }
        assert len(result["pmaxtp_points"]) > 4
        assert {
            (p["easting_m"], p["northing_m"]) for p in result["pmaxtp_points"]
        } == set(hydrograph_points)
        for point in result["pmaxtp_points"]:
            same = hydrograph_points[(point["easting_m"], point["northing_m"])]
            assert point["precipitation_mm"] == same["precipitation_mm"]
            assert point["weight"] == pytest.approx(same["weight"], rel=1e-9)
