"""Integration tests for GET /api/identify-point (offline).

Rasters, the results manifest and the water bodies file are synthetic files; the
answers of the PostGIS queries are stubbed (their SQL runs in
test_identify_point_db.py against a database).
"""

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import rasterio
from fastapi.testclient import TestClient
from pyproj import Transformer
from rasterio.transform import from_origin

from api.main import app
from core.attribution import PMAXTP
from core.config import Settings
from core.database import get_db

NODATA = -9999.0
X0, Y_TOP, CELL = 500000.0, 600000.0, 5.0
TO_WGS84 = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)
# The cells lie on 19°E, the meridian of PL-1992: zone 6 of PL-2000
TO_PL2000 = Transformer.from_crs("EPSG:2180", "EPSG:2177", always_xy=True)

# What the database holds at the point, as core.point_info returns it
LAND_COVER = {
    "category": "las",
    "cn": 60,
    "cn_amc_i": 40,
    "cn_amc_iii": 78,
    "imperviousness": 0.0,
    "bdot_class": "PTLZ",
}
STREAM = {"name": "Kamiennik", "layer_type": "SWRS", "distance_m": 7.4}
DEPRESSION = {
    "max_depth_m": 0.8,
    "mean_depth_m": 0.3,
    "area_m2": 450.0,
    "volume_m3": 135.0,
}
SUBCATCHMENT = {
    "segment_idx": 21911,
    "area_km2": 0.42,
    "upstream_area_km2": 37.22,
    "strahler_order": 4,
    "segment_length_m": 812.5,
    "is_real_stream": True,
}
# What the catchment graph gives for the segment, as core.point_info returns it
MAIN_CHANNEL = {"channel_length_km": 9.8123, "distance_to_outlet_km": 41.375}
# The lines the manifest gives the results: 'sfincs' of a PMAXTP rainfall, 'other'
# of another provider
RESULT_LINES = {
    "sfincs": {
        "attribution": list(PMAXTP.attribution),
        "terms_notice": list(PMAXTP.terms_notice),
    },
    "other": {"attribution": ["Źródło: inny dostawca"], "terms_notice": ["Regulamin"]},
}


def _raster(path, row):
    """One row of cells west to east from (X0, Y_TOP), EPSG:2180."""
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=1,
        width=len(row),
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=from_origin(X0, Y_TOP, CELL, CELL),
        nodata=NODATA,
    ) as dst:
        dst.write(np.array([row], dtype=np.float32), 1)


def _cell(col):
    """WGS84 (longitude, latitude) of the centre of a cell of the test rasters."""
    return TO_WGS84.transform(X0 + CELL * (col + 0.5), Y_TOP - CELL / 2)


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: MagicMock()
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def settings(tmp_path):
    """DEM 100 m with a gap in the last cell, slope, two results, one lake.

    Result 'sfincs' (cells 0-3): 101.5 (1.5 m of water), dry, 99.0 (below the
    terrain), 102.25. Result 'other' covers a raster far away from the cells. Each
    has the lines of RESULT_LINES.
    """
    nmt = tmp_path / "nmt"
    nmt.mkdir()
    _raster(nmt / "dem.tif", [100.0, 100.0, 100.0, 100.0, NODATA])
    _raster(nmt / "dem_mosaic_05_slope.tif", [4.26, 4.26, 4.26, 4.26, NODATA])
    data = tmp_path / "data"
    for result_id in ("sfincs", "other"):
        (data / "results" / result_id).mkdir(parents=True)
    _raster(data / "results" / "sfincs" / "wse_max.tif", [101.5, NODATA, 99.0, 102.25])
    with rasterio.open(
        data / "results" / "other" / "wse_max.tif",
        "w",
        driver="GTiff",
        height=1,
        width=1,
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=from_origin(X0 + 10_000.0, Y_TOP, CELL, CELL),
        nodata=NODATA,
    ) as dst:
        dst.write(np.array([[200.0]], dtype=np.float32), 1)
    (data / "results" / "index.json").write_text(
        json.dumps(
            {
                "schema": "hydrograf-results/1",
                "results": [
                    {
                        "id": result_id,
                        "kind": "raster_tiles",
                        "water_level": {
                            "path": f"/data/results/{result_id}/wse_max.tif",
                            "crs": "EPSG:2180",
                            "unit": "m n.p.m.",
                        },
                        **RESULT_LINES[result_id],
                    }
                    for result_id in ("sfincs", "other")
                ],
            }
        )
    )
    lon, lat = _cell(0)
    half = 0.00002  # about 1.5 m: the pond holds cell 0 only
    (data / "bdot_lakes.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"NAZWA": "Staw", "RODZAJ": "woda stojąca"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [lon - half, lat - half],
                                    [lon + half, lat - half],
                                    [lon + half, lat + half],
                                    [lon - half, lat + half],
                                    [lon - half, lat - half],
                                ]
                            ],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return Settings(
        dem_path=str(nmt / "dem.tif"),
        dem_dir=str(nmt),
        frontend_data_dir=str(data),
    )


@pytest.fixture
def database():
    """Stubbed answers of the PostGIS queries and of the graph at the point."""
    with (
        patch("api.endpoints.identify.land_cover_at", return_value=LAND_COVER) as lc,
        patch("api.endpoints.identify.soil_group_at", return_value="B") as soil,
        patch("api.endpoints.identify.depression_at", return_value=DEPRESSION) as dep,
        patch("api.endpoints.identify.nearest_stream", return_value=STREAM) as stream,
        patch(
            "api.endpoints.identify.subcatchment_at", return_value=SUBCATCHMENT
        ) as sub,
        patch(
            "api.endpoints.identify.main_channel_at", return_value=MAIN_CHANNEL
        ) as main,
    ):
        yield {
            "land_cover_at": lc,
            "soil_group_at": soil,
            "depression_at": dep,
            "nearest_stream": stream,
            "subcatchment_at": sub,
            "main_channel_at": main,
        }


def _get(client, settings, col=0, headers=None, **extra):
    lon, lat = _cell(col)
    with patch("api.endpoints.identify.get_settings", return_value=settings):
        return client.get(
            "/api/identify-point",
            params={"latitude": lat, "longitude": lon, **extra},
            headers=headers or {},
        )


class TestIdentifyPoint:
    def test_everything_known_at_the_point(self, client, settings, database):
        response = _get(client, settings, result_ids=["sfincs", "other", "nope"])

        assert response.status_code == 200
        data = response.json()
        lon, lat = _cell(0)
        easting, northing = TO_PL2000.transform(X0 + CELL / 2, Y_TOP - CELL / 2)
        assert data["coordinates"] == {
            "latitude": lat,
            "longitude": lon,
            "easting_m": X0 + CELL / 2,
            "northing_m": Y_TOP - CELL / 2,
            "pl2000": {
                "zone": 6,
                "epsg": 2177,
                "easting_m": pytest.approx(easting, abs=0.01),
                "northing_m": pytest.approx(northing, abs=0.01),
            },
        }
        assert data["elevation_m"] == 100.0
        assert data["slope_percent"] == 4.3
        # 'other' does not hold the point, 'nope' is not in the manifest
        assert data["water"] == [
            {"result_id": "sfincs", "water_level_m": 101.5, "depth_m": 1.5}
        ]
        assert data["stream"] == STREAM
        assert data["water_body"] == {"name": "Staw", "kind": "woda stojąca"}
        assert data["land_cover"] == LAND_COVER
        assert data["soil_hsg"] == "B"
        assert data["depression"] == DEPRESSION
        assert data["subcatchment"] == {
            "threshold_m2": 10000,
            **SUBCATCHMENT,
            **MAIN_CHANNEL,
        }

    @pytest.mark.parametrize(
        ("col", "water"),
        [
            (1, {"result_id": "sfincs", "water_level_m": None, "depth_m": None}),
            (2, {"result_id": "sfincs", "water_level_m": 99.0, "depth_m": None}),
            (3, {"result_id": "sfincs", "water_level_m": 102.25, "depth_m": 2.25}),
        ],
        ids=["dry", "water-below-terrain", "wet"],
    )
    def test_depth_only_where_the_water_lies_above_the_terrain(
        self, client, settings, database, col, water
    ):
        response = _get(client, settings, col=col, result_ids=["sfincs"])

        assert response.status_code == 200
        assert response.json()["water"] == [water]

    def test_no_water_without_result_ids(self, client, settings, database):
        assert _get(client, settings).json()["water"] == []

    def test_lines_of_the_results_whose_water_the_card_shows(
        self, client, settings, database
    ):
        # 'other' does not hold the point, 'nope' is not in the manifest
        data = _get(client, settings, result_ids=["sfincs", "other", "nope"]).json()

        # The results' lines first, then G and SG of the members (DEV-20.4)
        assert data["attribution"][:3] == list(PMAXTP.attribution)
        assert "Źródło: inny dostawca" not in data["attribution"]
        assert data["terms_notice"] == list(PMAXTP.terms_notice)

    def test_without_water_of_a_result_only_the_data_lines(
        self, client, settings, database
    ):
        data = _get(client, settings).json()

        assert data["attribution"][0].startswith(
            "Źródło: Główny Urząd Geodezji i Kartografii – GUGiK, NMT"
        )
        assert not set(PMAXTP.attribution) & set(data["attribution"])
        assert data["terms_notice"] == []

    @pytest.mark.parametrize(
        ("requested", "used"),
        [(None, 10000), (1000, 10000), (10000, 10000), (100000, 100000)],
    )
    def test_threshold_of_the_network_has_a_floor(
        self, client, settings, database, requested, used
    ):
        extra = {} if requested is None else {"threshold_m2": requested}

        response = _get(client, settings, **extra)

        assert response.json()["subcatchment"]["threshold_m2"] == used
        assert database["subcatchment_at"].call_args.args[3] == used
        # The main channel is read on the same network
        assert database["main_channel_at"].call_args.args[1:] == (
            used,
            SUBCATCHMENT["segment_idx"],
        )

    def test_sources_without_data_give_null(self, client, settings, database):
        for stub in database.values():
            stub.return_value = None

        response = _get(client, settings, col=1)

        assert response.status_code == 200
        data = response.json()
        assert data["elevation_m"] == 100.0
        for member in (
            "stream",
            "water_body",
            "land_cover",
            "soil_hsg",
            "depression",
            "subcatchment",
        ):
            assert data[member] is None, member

    def test_point_off_the_dem_is_404_in_polish(self, client, settings, database):
        response = _get(client, settings, col=4, headers={"Accept-Language": "pl"})

        assert response.status_code == 404
        assert response.headers["content-type"] == "application/problem+json"
        problem = response.json()
        assert problem["code"] == "no_data"
        assert problem["details"]["reason"] == "outside_data_area"
        assert problem["detail"] == (
            "Brak danych w tym miejscu: punkt leży poza obszarem danych Hydrografu."
        )
        assert problem["hint"] == "Kliknij w obszarze objętym danymi."
        database["land_cover_at"].assert_not_called()

    def test_point_outside_the_dem_extent_is_404(self, client, settings, database):
        response = _get(client, settings, col=40)

        assert response.status_code == 404
        assert response.json()["code"] == "no_data"

    def test_missing_dem_is_503(self, client, settings, database, tmp_path):
        settings.dem_path = str(tmp_path / "missing.tif")

        response = _get(client, settings)

        assert response.status_code == 503
        problem = response.json()
        assert problem["code"] == "store_unavailable"
        assert str(tmp_path) not in response.text

    @pytest.mark.parametrize(
        ("params", "pointer"),
        [
            ({"latitude": 95.0, "longitude": 16.0}, "/query/latitude"),
            ({"longitude": 16.0}, "/query/latitude"),
            (
                {"latitude": 51.0, "longitude": 16.0, "threshold_m2": 0},
                "/query/threshold_m2",
            ),
            (
                {"latitude": 51.0, "longitude": 16.0, "result_ids": [""]},
                "/query/result_ids/0",
            ),
            (
                {"latitude": 51.0, "longitude": 16.0, "result_ids": ["r"] * 21},
                "/query/result_ids",
            ),
        ],
        ids=["latitude-range", "latitude-missing", "threshold", "empty-id", "21-ids"],
    )
    def test_invalid_query_is_400(self, client, settings, database, params, pointer):
        response = client.get("/api/identify-point", params=params)

        assert response.status_code == 400
        assert response.headers["content-type"] == "application/problem+json"
        problem = response.json()
        assert problem["code"] == "validation_error"
        assert problem["details"]["fields"] == [pointer]
        assert [error["pointer"] for error in problem["errors"]] == [pointer]

    def test_post_is_405(self, client):
        response = client.post(
            "/api/identify-point", json={"latitude": 51.0, "longitude": 16.0}
        )

        assert response.status_code == 405

    def test_database_failure_is_500(self, client, settings, database):
        database["nearest_stream"].side_effect = RuntimeError("connection lost")

        response = _get(client, settings)

        assert response.status_code == 500
        problem = response.json()
        assert problem["code"] == "internal_error"
        assert problem["details"]["reason"] == "identify_failed"
