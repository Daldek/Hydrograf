"""POST /api/delineate-network over PostGIS: the real queries of the measures (ADR-080).

The synthetic DEM of the network tests (``tests.fixtures.pipeline_run``,
``river_network_dem``: a main river along column 85 with three tributaries) is
processed by ``process_dem`` into a private migrated database, with its rasters saved;
the land cover and soil groups of the unit tests and two BDOT10k stretches of the main
river are inserted into ``land_cover``, ``soil_hsg`` and ``bdot_streams``. The endpoint
runs on that database as the API does: ``get_db``, ``loaded_catchment_graph`` and every
query of the measures are the real ones. Plan tests 19 to 21.
"""

import json
from collections.abc import Iterator
from importlib.resources import files
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
import shapely
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import LineString, shape
from shapely.geometry.base import BaseGeometry
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

import core.catchment_graph as cg_module
from api.main import app
from core import database
from core.config import get_settings
from core.db_bulk import update_stream_real_flags_all
from core.watershed_service import build_land_cover_stats
from scripts.process_dem import process_dem
from tests.conftest_db import requires_db
from tests.fixtures.pipeline_run import (
    NETWORK_CELL_M,
    NETWORK_SHAPE,
    NETWORK_SNAP_THRESHOLD_M2,
    NETWORK_UNIT_THRESHOLD_M2,
    NETWORK_X0,
    NETWORK_Y1,
    land_cover_layout,
    river_network_dem,
    soil_layout,
)
from tests.scratch_db import scratch_database
from utils.geometry import transform_pl1992_to_wgs84

pytestmark = [requires_db, pytest.mark.db]

_ROOT = Path(__file__).resolve().parents[3]
ENVELOPE = Draft202012Validator(
    json.loads(
        (_ROOT / "schemas" / "nogat" / "handoff-1.schema.json").read_text(
            encoding="utf-8"
        )
    )
)
NETWORK = Draft202012Validator(
    json.loads(
        files("hydrolog")
        .joinpath("schemas/hydrolog-network-1.schema.json")
        .read_text(encoding="utf-8")
    )
)
URL = "/api/delineate-network"
OUTLET = (219, 85)  # A: the outlet cell of the grid, on the main river
# The last cell of each tributary above its confluence with the main river, (row,
# column): a click there moves to the mouth (D3)
T3_MOUTH, T2_MOUTH, T1_MOUTH = (75, 86), (123, 86), (159, 84)
MAIN_RIVER_COL = 85
# BDOT10k lines along the main river, (first row, last row) of the cell centres they
# join: one unbroken line over the stretch between the T2 and T1 confluences (rows
# 123 and 159) and beyond both, and two lines below with a gap of 60 m (rows 190 to
# 196), more than BDOT_BUFFER_M = 25 m from the reach between the gap's ends
STRAIGHT_LINE_ROWS = (110, 170)
GAPPED_LINE_ROWS = ((172, 190), (196, 230))
LAND_COVER = land_cover_layout(
    NETWORK_X0,
    NETWORK_Y1,
    NETWORK_SHAPE[1] * NETWORK_CELL_M,
    NETWORK_SHAPE[0] * NETWORK_CELL_M,
)
SOILS = soil_layout(
    NETWORK_X0,
    NETWORK_Y1,
    NETWORK_SHAPE[1] * NETWORK_CELL_M,
    NETWORK_SHAPE[0] * NETWORK_CELL_M,
)
_TO_2180 = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True)


def cell_centre_xy(row: float, col: float) -> tuple[float, float]:
    """Centre of a cell of the grid, EPSG:2180 [m]."""
    return (
        NETWORK_X0 + (col + 0.5) * NETWORK_CELL_M,
        NETWORK_Y1 - (row + 0.5) * NETWORK_CELL_M,
    )


def main_river_line(first_row: int, last_row: int) -> LineString:
    """A straight line down the main river between the centres of two rows."""
    return LineString(
        [
            cell_centre_xy(first_row, MAIN_RIVER_COL),
            cell_centre_xy(last_row, MAIN_RIVER_COL),
        ]
    )


STRAIGHT_LINE = main_river_line(*STRAIGHT_LINE_ROWS)
BDOT_LINES = (STRAIGHT_LINE, *(main_river_line(*rows) for rows in GAPPED_LINE_ROWS))


def to_2180(geometry: dict[str, Any]) -> BaseGeometry:
    """A GeoJSON geometry of the response (WGS84) in EPSG:2180."""

    def project(coords: np.ndarray) -> np.ndarray:
        x, y = _TO_2180.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(shape(geometry), project)


def point(
    point_id: str, cell: tuple[int, int], name: str | None = None
) -> dict[str, Any]:
    """A point of the request at the centre of a cell of the grid."""
    longitude, latitude = transform_pl1992_to_wgs84(*cell_centre_xy(*cell))
    body: dict[str, Any] = {
        "id": point_id,
        "latitude": latitude,
        "longitude": longitude,
    }
    if name is not None:
        body["name"] = name
    return body


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    """A private migrated database, which ``core.database`` is bound to."""
    with scratch_database() as url:
        bound = create_engine(url)
        previous_engine = database._engine
        previous_bind = database.SessionLocal.kw.get("bind")
        database._engine = bound
        database.SessionLocal.configure(bind=bound)
        try:
            yield bound
        finally:
            database._engine = previous_engine
            database.SessionLocal.configure(bind=previous_bind)
            bound.dispose()


def _insert_layers(engine: Engine) -> None:
    """Insert the land cover, the soil groups and the BDOT10k lines."""
    with engine.begin() as connection:
        for category, bdot_class, imperviousness, geometry in LAND_COVER:
            connection.execute(
                text(
                    "INSERT INTO land_cover (geom, category, imperviousness, "
                    "bdot_class) VALUES (ST_Multi(ST_GeomFromWKB(:geom, 2180)), "
                    ":category, :imperviousness, :bdot_class)"
                ),
                {
                    "geom": geometry.wkb,
                    "category": category,
                    "imperviousness": imperviousness,
                    "bdot_class": bdot_class,
                },
            )
        for group, geometry in SOILS:
            connection.execute(
                text(
                    "INSERT INTO soil_hsg (geom, hsg_group, area_m2) VALUES "
                    "(ST_Multi(ST_GeomFromWKB(:geom, 2180)), :group, :area_m2)"
                ),
                {"geom": geometry.wkb, "group": group, "area_m2": geometry.area},
            )
        for line in BDOT_LINES:
            connection.execute(
                text(
                    "INSERT INTO bdot_streams (geom, layer_type, length_m) VALUES "
                    "(ST_GeomFromWKB(:geom, 2180), 'SWRS', :length_m)"
                ),
                {"geom": line.wkb, "length_m": line.length},
            )


@pytest.fixture(scope="module")
def run_dir(engine: Engine, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The run of process_dem over the network DEM, published in the database.

    process_dem of a whole raster matches the network to BDOT10k only for the lines
    it burns (``burn_streams_path``), which would deepen the main river; the lines
    are inserted beforehand and matched after the run, as process_dem matches them.
    """
    directory = tmp_path_factory.mktemp("network_db")
    dem = river_network_dem()
    dem_path = directory / "dem_mosaic.tif"
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        height=dem.shape[0],
        width=dem.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=from_origin(NETWORK_X0, NETWORK_Y1, NETWORK_CELL_M, NETWORK_CELL_M),
        nodata=-9999.0,
    ) as dst:
        dst.write(dem, 1)
    _insert_layers(engine)
    process_dem(
        dem_path,
        save_intermediates=True,
        output_dir=directory,
        clear_existing=True,
        thresholds=[NETWORK_UNIT_THRESHOLD_M2],
    )
    with database.get_db_session() as db:
        update_stream_real_flags_all(db, [NETWORK_UNIT_THRESHOLD_M2])
    return directory


@pytest.fixture(scope="module")
def mouths(run_dir: Path) -> dict[str, Any]:
    """The network of A at the outlet and P1 to P3 at the mouths of T1 to T3."""
    request = {
        "outlet": point("A", OUTLET, "Rzeka"),
        "points": [
            point("P1", T1_MOUTH, "Pierwszy"),
            point("P2", T2_MOUTH),
            point("P3", T3_MOUTH, "Trzeci"),
        ],
        "threshold_m2": NETWORK_SNAP_THRESHOLD_M2,
    }
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("DEM_DIR", str(run_dir))
        # The graph of another database must not answer for this one
        patch.setattr(cg_module, "_catchment_graph", None)
        get_settings.cache_clear()
        try:
            response = TestClient(app).post(URL, json=request)
        finally:
            get_settings.cache_clear()
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _layout_areas(
    layers: tuple[tuple[Any, ...], ...], boundary: BaseGeometry
) -> dict[str, float]:
    """Area [m²] of each class of a layout (first item, geometry last) in a boundary.

    Classes under 1 m² are left out: slivers of a boundary that crossed WGS84 and back
    along an edge of the layout.
    """
    areas: dict[str, float] = {}
    for layer in layers:
        areas[layer[0]] = (
            areas.get(layer[0], 0.0) + layer[-1].intersection(boundary).area
        )
    return {name: area for name, area in areas.items() if area >= 1.0}


def _land_cover_m2(watershed: dict[str, Any]) -> dict[str, float]:
    return {
        c["category"]: c["area_m2"] for c in watershed["land_cover_stats"]["categories"]
    }


def _approx(expected: dict[str, float]) -> dict[str, Any]:
    """Areas within 0.1 % (and the 0.1 m² of their rounding)."""
    return {k: pytest.approx(v, rel=1e-3, abs=0.1) for k, v in expected.items()}


class TestTheMeasuresOverPostgis:
    """Plan test 19: B5 and the parameters through the real queries."""

    def test_the_elements_add_up_to_a(self, mouths):
        areas = [
            s["watershed"]["morphometry"]["area_km2"] for s in mouths["subcatchments"]
        ]

        assert mouths["area_check"] == {
            "watershed_km2": mouths["area_km2"],
            "elements_km2": mouths["area_km2"],
        }
        assert len(areas) == 7
        assert sum(areas) == pytest.approx(mouths["area_km2"], abs=1e-6)

    def test_every_element_has_the_land_cover_soils_cn_and_flow_path_of_its_cells(
        self, mouths
    ):
        for element in mouths["subcatchments"]:
            watershed = element["watershed"]
            boundary = to_2180(watershed["boundary_geojson"]["geometry"])
            morphometry = watershed["morphometry"]
            soils = {
                c["group"]: c["area_m2"] for c in watershed["hsg_stats"]["categories"]
            }

            assert _land_cover_m2(watershed) == _approx(
                _layout_areas(LAND_COVER, boundary)
            ), element["id"]
            assert soils == _approx(_layout_areas(SOILS, boundary)), element["id"]
            assert 0 < morphometry["cn"] < 100, element["id"]
            assert morphometry["flow_path_length_km"] > 0, element["id"]
            assert morphometry["flow_path_slope_m_per_m"] > 0, element["id"]

    def test_the_land_cover_of_the_elements_sums_to_that_of_a(self, mouths):
        db = database.SessionLocal()
        try:
            whole = build_land_cover_stats(
                to_2180(mouths["boundary_geojson"]["geometry"]), db
            )
        finally:
            db.close()
        assert whole is not None
        summed: dict[str, float] = {}
        for element in mouths["subcatchments"]:
            for category, area_m2 in _land_cover_m2(element["watershed"]).items():
                summed[category] = summed.get(category, 0.0) + area_m2

        assert summed == _approx({c.category: c.area_m2 for c in whole.categories})
        assert set(summed) == {"las", "grunt_orny", "woda"}


def _reach_from(mouths: dict[str, Any], point_id: str) -> dict[str, Any]:
    """The reach that leaves the junction where the tributary of a point enters."""
    tributary = next(s["id"] for s in mouths["subcatchments"] if s["point"] == point_id)
    junction = next(j["id"] for j in mouths["junctions"] if tributary in j["inflows"])
    return next(r for r in mouths["reaches"] if r["from"] == junction)


class TestTheBdotCheckLength:
    """Plan test 20: the check length of a reach along the BDOT10k lines (D10)."""

    def test_a_reach_along_a_straight_line_has_its_length_between_its_ends(
        self, mouths
    ):
        reach = _reach_from(mouths, "P2")  # from the T2 confluence to T1's
        line = to_2180(reach["geojson"]["geometry"])
        upper, lower = shapely.get_point(line, 0), shapely.get_point(line, -1)
        between_ends_km = (
            abs(STRAIGHT_LINE.project(lower) - STRAIGHT_LINE.project(upper)) / 1000
        )

        assert reach["vector_length_km"] == pytest.approx(between_ends_km, rel=0.01)
        origin = mouths["handoff"]["node_provenance"][reach["id"]]["node"]
        assert origin["vector_length_km"] == reach["vector_length_km"]
        assert origin["vector_source"] == "bdot10k"

    def test_a_reach_with_a_gap_in_the_lines_has_none(self, mouths):
        reach = _reach_from(mouths, "P1")  # from the T1 confluence down to A
        line = to_2180(reach["geojson"]["geometry"])
        gap = main_river_line(GAPPED_LINE_ROWS[0][1], GAPPED_LINE_ROWS[1][0])

        # The gap lies on the reach
        assert line.buffer(1.0).contains(gap)
        assert reach["vector_length_km"] is None
        origin = mouths["handoff"]["node_provenance"][reach["id"]]["node"]
        assert not {"vector_length_km", "vector_source"} & set(origin)


class TestTheHandoff:
    """Plan test 21: the response's hand-off validates as in plan test 15."""

    def test_it_validates_against_the_envelope_and_hydrologs_network(self, mouths):
        handoff = mouths["handoff"]

        assert [e.message for e in ENVELOPE.iter_errors(handoff)] == []
        assert [e.message for e in NETWORK.iter_errors(handoff["payload"])] == []

    def test_every_node_but_the_outlet_has_its_origin(self, mouths):
        handoff = mouths["handoff"]
        nodes = handoff["payload"]["nodes"]
        elements = (
            [s["id"] for s in mouths["subcatchments"]]
            + [r["id"] for r in mouths["reaches"]]
            + [j["id"] for j in mouths["junctions"]]
        )

        assert set(handoff["node_provenance"]) <= {n["id"] for n in nodes}
        assert set(handoff["node_provenance"]) == set(elements)
        assert "OUT" in {n["id"] for n in nodes}
        assert "OUT" not in handoff["node_provenance"]
