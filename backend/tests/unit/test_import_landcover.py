"""Tests for scripts/import_landcover.py: DB URL, CRS, the land cover partition."""

from collections import defaultdict
from unittest.mock import patch

import geopandas as gpd
import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon, box

from scripts.import_landcover import (
    get_database_url,
    prepare_records,
    read_gpkg_layers,
    transform_to_2180,
)

X0, Y0 = 400_000.0, 500_000.0


class TestGetDatabaseUrl:
    """Tests for get_database_url()."""

    @patch.dict("os.environ", {"DATABASE_URL": "postgresql://test:test@db:5432/testdb"})
    def test_returns_env_var_when_set(self):
        """When DATABASE_URL env var is set, it is returned."""
        url = get_database_url()
        assert url == "postgresql://test:test@db:5432/testdb"

    @patch.dict("os.environ", {}, clear=True)
    @patch("scripts.import_landcover.Path")
    def test_fallback_default(self, mock_path):
        """When no env var and no config, returns default URL."""
        # Patch to prevent actual config import
        with patch.dict("sys.modules", {"core.config": None}):
            url = get_database_url()
        assert "postgresql://" in url
        assert "hydro_user" in url
        assert "hydro_db" in url

    @patch.dict(
        "os.environ",
        {"DATABASE_URL": "postgresql://custom:pass@remote:5433/prod_db"},
    )
    def test_env_var_takes_priority(self):
        """Environment variable has highest priority."""
        url = get_database_url()
        assert url == "postgresql://custom:pass@remote:5433/prod_db"


class TestTransformTo2180:
    """Tests for transform_to_2180()."""

    def test_already_2180_no_change(self):
        """GeoDataFrame already in EPSG:2180 is returned unchanged."""
        poly = Polygon([(400000, 500000), (401000, 500000), (401000, 501000)])
        gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[poly], crs="EPSG:2180")
        result = transform_to_2180(gdf)
        assert result.crs.to_epsg() == 2180
        # Coordinates should be essentially the same
        np.testing.assert_allclose(
            result.geometry.iloc[0].bounds,
            poly.bounds,
            atol=1.0,
        )

    def test_from_4326_transforms_to_metric(self):
        """GeoDataFrame in EPSG:4326 is transformed to EPSG:2180."""
        # A point roughly in central Poland (WGS84)
        poly = Polygon([(20.0, 52.0), (20.1, 52.0), (20.1, 52.1), (20.0, 52.1)])
        gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[poly], crs="EPSG:4326")
        result = transform_to_2180(gdf)
        assert result.crs.to_epsg() == 2180
        # EPSG:2180 uses metric coordinates — values should be large
        bounds = result.geometry.iloc[0].bounds
        assert bounds[0] > 100000  # x min should be large in 2180
        assert bounds[1] > 100000  # y min should be large in 2180

    def test_no_crs_assumes_2180(self):
        """GeoDataFrame with no CRS gets EPSG:2180 assigned."""
        poly = Polygon([(400000, 500000), (401000, 500000), (401000, 501000)])
        gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[poly])
        assert gdf.crs is None
        result = transform_to_2180(gdf)
        assert result.crs.to_epsg() == 2180


def _square(x, y, size=100.0):
    """A square of the synthetic package, offset (x, y) in metres from (X0, Y0)."""
    return box(X0 + x, Y0 + y, X0 + x + size, Y0 + y + size)


def _package(path, layers):
    """Write a GeoPackage: layer name -> list of (attributes, geometry)."""
    for name, features in layers.items():
        attributes = [attrs for attrs, _ in features]
        gdf = gpd.GeoDataFrame(
            attributes, geometry=[geom for _, geom in features], crs="EPSG:2180"
        )
        gdf.to_file(path, layer=name, driver="GPKG")
    return path


def _areas(records):
    """Area [m²] of the records by (category, bdot_class)."""
    areas = defaultdict(float)
    for rec in records:
        geom = shapely.from_wkb(rec["geom_wkb"])
        areas[rec["category"], rec["bdot_class"]] += geom.area
    return dict(areas)


def _import(path, layers):
    return prepare_records(read_gpkg_layers(_package(path, layers)))


PLANT = "zakład produkcyjny, usługowy lub remontowy"


class TestIndustrialComplexes:
    """KUPG complexes cut out of the PT partition (ADR-074)."""

    def test_plant_over_housing_takes_exactly_its_overlap(self, tmp_path):
        """The PTZB part under a plant becomes industrial; the rest of it stays."""
        records = _import(
            tmp_path / "p.gpkg",
            {
                "OT_PTZB_A": [({"RODZAJ": "jednorodzinna"}, _square(0, 0))],
                "OT_PTTR_A": [({"RODZAJ": "roślinność trawiasta"}, _square(100, 0))],
                "OT_KUPG_A": [({"RODZAJ": PLANT}, box(X0 + 60, Y0, X0 + 130, Y0 + 50))],
            },
        )

        assert _areas(records) == pytest.approx(
            {
                ("zabudowa_mieszkaniowa", "PTZB:jednorodzinna"): 10_000 - 40 * 50,
                ("łąka", "PTTR:trawiasta"): 10_000 - 30 * 50,
                ("zabudowa_przemysłowa", "KUPG:zakład prod."): 70 * 50,
            }
        )
        industrial = [r for r in records if r["bdot_class"] == "KUPG:zakład prod."]
        assert {r["imperviousness"] for r in industrial} == {0.72}

    @pytest.mark.parametrize(
        ("kind", "plant"),
        [
            ("elektrownia", "słoneczna"),
            ("elektrownia", "wiatrowa"),
            ("kopalnia", None),
            ("gospodarstwo hodowlane", None),
        ],
    )
    def test_other_complexes_leave_the_land_cover(self, tmp_path, kind, plant):
        """Solar and wind farms, mines and farms are not industrial land."""
        records = _import(
            tmp_path / "p.gpkg",
            {
                "OT_PTNZ_A": [
                    (
                        {"RODZAJ": "teren pod urządzeniami technicznymi lub budowlami"},
                        _square(0, 0),
                    )
                ],
                "OT_KUPG_A": [
                    ({"RODZAJ": kind, "RODZAJELEKTROWNI": plant}, _square(-10, -10))
                ],
            },
        )

        assert _areas(records) == pytest.approx({("inny", "PTNZ:urządzenia"): 10_000})

    def test_thermal_power_plant_is_industrial(self, tmp_path):
        """Of the power plants, the kind decides: a thermal one is industrial."""
        records = _import(
            tmp_path / "p.gpkg",
            {
                "OT_PTTR_A": [({"RODZAJ": "uprawa na gruntach ornych"}, _square(0, 0))],
                "OT_KUPG_A": [
                    (
                        {"RODZAJ": "elektrownia", "RODZAJELEKTROWNI": "cieplna"},
                        _square(0, 0, size=50),
                    )
                ],
            },
        )

        assert _areas(records) == pytest.approx(
            {
                ("grunt_orny", "PTTR:grunty orne"): 7_500,
                ("zabudowa_przemysłowa", "KUPG:el. cieplna"): 2_500,
            }
        )

    def test_overlapping_complexes_count_once(self, tmp_path):
        """Two overlapping complexes take their union once, the first kind first."""
        records = _import(
            tmp_path / "p.gpkg",
            {
                "OT_PTTR_A": [({"RODZAJ": "uprawa na gruntach ornych"}, _square(0, 0))],
                "OT_KUPG_A": [
                    ({"RODZAJ": "baza paliw"}, box(X0, Y0, X0 + 60, Y0 + 100)),
                    ({"RODZAJ": PLANT}, box(X0 + 40, Y0, X0 + 80, Y0 + 100)),
                ],
            },
        )

        assert _areas(records) == pytest.approx(
            {
                ("grunt_orny", "PTTR:grunty orne"): 2_000,
                ("zabudowa_przemysłowa", "KUPG:baza paliw"): 6_000,
                ("zabudowa_przemysłowa", "KUPG:zakład prod."): 2_000,
            }
        )

    def test_industrial_land_and_water_stay_whole(self, tmp_path):
        """PT polygons that are industrial already, and water, keep their source."""
        records = _import(
            tmp_path / "p.gpkg",
            {
                "OT_PTZB_A": [({"RODZAJ": "przemysłowo-składowa"}, _square(0, 0))],
                "OT_PTWP_A": [({"RODZAJ": "woda stojąca"}, _square(100, 0))],
                "OT_KUPG_A": [({"RODZAJ": PLANT}, box(X0, Y0, X0 + 200, Y0 + 100))],
            },
        )

        assert _areas(records) == pytest.approx(
            {
                ("zabudowa_przemysłowa", "PTZB:przem.-skład."): 10_000,
                ("woda", "PTWP"): 10_000,
            }
        )
        assert len(records) == 2

    def test_areas_sum_to_the_pt_layers(self, tmp_path):
        """Complexes over many polygons change categories, never the total area."""
        pt = [
            ({"RODZAJ": "jednorodzinna"}, _square(x, y))
            for x in (0, 100, 200)
            for y in (0, 100)
        ]
        complexes = [
            ({"RODZAJ": PLANT}, shapely.Point(X0 + 150, Y0 + 100).buffer(70)),
            ({"RODZAJ": "gazownia"}, box(X0 + 250, Y0 - 50, X0 + 400, Y0 + 50)),
        ]
        records = _import(
            tmp_path / "p.gpkg", {"OT_PTZB_A": pt, "OT_KUPG_A": complexes}
        )

        areas = _areas(records)
        assert sum(areas.values()) == pytest.approx(60_000)
        assert areas["zabudowa_przemysłowa", "KUPG:zakład prod."] == pytest.approx(
            shapely.Point(X0 + 150, Y0 + 100).buffer(70).area
        )
        assert areas["zabudowa_przemysłowa", "KUPG:gazownia"] == pytest.approx(50 * 50)


class TestPtKinds:
    """The attribute of a PT layer that decides its category."""

    def test_grassland_and_arable_land(self, tmp_path):
        """PTTR splits into meadow (grass) and arable land by RODZAJ."""
        records = _import(
            tmp_path / "p.gpkg",
            {
                "OT_PTTR_A": [
                    ({"RODZAJ": "roślinność trawiasta"}, _square(0, 0)),
                    ({"RODZAJ": "uprawa na gruntach ornych"}, _square(100, 0, 200)),
                ],
            },
        )

        assert _areas(records) == pytest.approx(
            {
                ("łąka", "PTTR:trawiasta"): 10_000,
                ("grunt_orny", "PTTR:grunty orne"): 40_000,
            }
        )

    def test_built_up_kinds(self, tmp_path):
        """PTZB industrial and commercial kinds are industrial, the rest housing."""
        records = _import(
            tmp_path / "p.gpkg",
            {
                "OT_PTZB_A": [
                    ({"RODZAJ": "wielorodzinna"}, _square(0, 0)),
                    ({"RODZAJ": "przemysłowo-składowa"}, _square(100, 0)),
                    ({"RODZAJ": "handlowo-usługowa"}, _square(200, 0)),
                ],
            },
        )

        assert {
            (r["category"], r["bdot_class"], r["imperviousness"]) for r in records
        } == {
            ("zabudowa_mieszkaniowa", "PTZB:wielorodzinna", 0.65),
            ("zabudowa_przemysłowa", "PTZB:przem.-skład.", 0.72),
            ("zabudowa_przemysłowa", "PTZB:handl.-usług.", 0.85),
        }

    def test_unpaved_square_is_not_a_road(self, tmp_path):
        """PTPL of natural ground is `inny`; asphalt and an unknown surface `droga`."""
        records = _import(
            tmp_path / "p.gpkg",
            {
                "OT_PTPL_A": [
                    ({"MATERIALNAWIERZCHNI": "grunt naturalny"}, _square(0, 0)),
                    ({"MATERIALNAWIERZCHNI": "masa bitumiczna"}, _square(100, 0)),
                    ({"MATERIALNAWIERZCHNI": None}, _square(200, 0)),
                ],
            },
        )

        assert {(r["category"], r["bdot_class"]) for r in records} == {
            ("inny", "PTPL:nieutwardzony"),
            ("droga", "PTPL:utwardzony"),
            ("droga", "PTPL"),
        }

    def test_layers_without_the_attribute_take_the_layer_default(self, tmp_path):
        """Old layer names and missing attributes fall back to the layer's category."""
        records = _import(
            tmp_path / "p.gpkg",
            {
                "PTZB": [({"id": 1}, _square(0, 0))],
                "PTTR": [({"id": 1}, _square(100, 0))],
                "OT_PTXX_A": [({"id": 1}, _square(200, 0))],
            },
        )

        assert {(r["category"], r["bdot_class"]) for r in records} == {
            ("zabudowa_mieszkaniowa", "PTZB"),
            ("grunt_orny", "PTTR"),
            ("inny", "PTXX"),
        }


class TestGeometries:
    """The geometries that reach the partition."""

    def test_self_intersecting_polygon_keeps_its_area(self, tmp_path):
        """A bow-tie polygon is repaired into both of its triangles."""
        bow_tie = Polygon(
            [(X0, Y0), (X0 + 100, Y0 + 100), (X0 + 100, Y0), (X0, Y0 + 100)]
        )
        records = _import(tmp_path / "p.gpkg", {"OT_PTLZ_A": [({"id": 1}, bow_tie)]})

        assert _areas(records) == pytest.approx({("las", "PTLZ"): 5_000})
        assert all(shapely.from_wkb(r["geom_wkb"]).is_valid for r in records)

    def test_empty_geometry_skipped(self):
        """Records with empty geometry are skipped."""
        gdf = gpd.GeoDataFrame(
            {"id": [1, 2]}, geometry=[_square(0, 0), Polygon()], crs="EPSG:2180"
        )

        records = prepare_records({"PTLZ": gdf})

        assert _areas(records) == pytest.approx({("las", "PTLZ"): 10_000})
