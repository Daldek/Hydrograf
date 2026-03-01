"""Tests for scripts/import_landcover.py: DB URL, CRS transform, record preparation."""

from unittest.mock import patch

import geopandas as gpd
import numpy as np
from shapely.geometry import MultiPolygon, Polygon

from scripts.import_landcover import (
    BDOT10K_MAPPING,
    get_database_url,
    prepare_records,
    transform_to_2180,
)


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
        gdf = gpd.GeoDataFrame(
            {"id": [1]}, geometry=[poly], crs="EPSG:2180"
        )
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
        gdf = gpd.GeoDataFrame(
            {"id": [1]}, geometry=[poly], crs="EPSG:4326"
        )
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


class TestPrepareRecords:
    """Tests for prepare_records()."""

    def _make_gdf(self, n=1, geom_type="Polygon"):
        """Helper to create a GeoDataFrame with n polygons in EPSG:2180."""
        polys = []
        for i in range(n):
            poly = Polygon([
                (400000 + i * 100, 500000),
                (400100 + i * 100, 500000),
                (400100 + i * 100, 500100),
                (400000 + i * 100, 500100),
            ])
            if geom_type == "MultiPolygon":
                poly = MultiPolygon([poly])
            polys.append(poly)
        return gpd.GeoDataFrame(
            {"id": list(range(n))},
            geometry=polys,
            crs="EPSG:2180",
        )

    def test_returns_list_of_dicts(self):
        """prepare_records returns a list of dictionaries."""
        gdf = self._make_gdf(2)
        layers = {"PTLZ": gdf}
        records = prepare_records(layers)
        assert isinstance(records, list)
        assert all(isinstance(r, dict) for r in records)

    def test_record_has_required_keys(self):
        """Each record has geom_wkb, category, cn_value, imperviousness, bdot_class."""
        gdf = self._make_gdf(1)
        layers = {"PTLZ": gdf}
        records = prepare_records(layers)
        assert len(records) == 1
        rec = records[0]
        assert "geom_wkb" in rec
        assert "category" in rec
        assert "cn_value" in rec
        assert "imperviousness" in rec
        assert "bdot_class" in rec

    def test_ptlz_maps_to_las(self):
        """PTLZ layer is mapped to 'las' category."""
        gdf = self._make_gdf(1)
        layers = {"PTLZ": gdf}
        records = prepare_records(layers)
        assert records[0]["category"] == "las"
        assert records[0]["cn_value"] == 60

    def test_ptwp_maps_to_woda(self):
        """PTWP layer is mapped to 'woda' category."""
        gdf = self._make_gdf(1)
        layers = {"PTWP": gdf}
        records = prepare_records(layers)
        assert records[0]["category"] == "woda"
        assert records[0]["cn_value"] == 100

    def test_bdot10k_mapping_completeness(self):
        """All standard BDOT10k codes have a mapping entry."""
        expected_codes = [
            "PTLZ", "PTTR", "PTUT", "PTWP", "PTWZ", "PTRK",
            "PTZB", "PTKM", "PTPL", "PTGN", "PTNZ", "PTSO",
        ]
        for code in expected_codes:
            assert code in BDOT10K_MAPPING, f"Missing mapping for {code}"

    def test_empty_input_returns_empty(self):
        """Empty layers dict returns empty records list."""
        records = prepare_records({})
        assert records == []

    def test_multiple_layers(self):
        """Records from multiple layers are combined."""
        gdf1 = self._make_gdf(2)
        gdf2 = self._make_gdf(3)
        layers = {"PTLZ": gdf1, "PTWP": gdf2}
        records = prepare_records(layers)
        assert len(records) == 5
        categories = {r["category"] for r in records}
        assert "las" in categories
        assert "woda" in categories

    def test_empty_geometry_skipped(self):
        """Records with empty geometry are skipped."""
        empty_poly = Polygon()  # empty polygon
        valid_poly = Polygon([
            (400000, 500000), (401000, 500000),
            (401000, 501000), (400000, 501000),
        ])
        gdf = gpd.GeoDataFrame(
            {"id": [1, 2]},
            geometry=[valid_poly, empty_poly],
            crs="EPSG:2180",
        )
        layers = {"PTLZ": gdf}
        records = prepare_records(layers)
        assert len(records) == 1

    def test_bdot_class_recorded(self):
        """The bdot_class field records the original layer code."""
        gdf = self._make_gdf(1)
        layers = {"PTZB": gdf}
        records = prepare_records(layers)
        assert records[0]["bdot_class"] == "PTZB"

    def test_unknown_layer_gets_default(self):
        """Unknown layer code gets default mapping ('inny', 75, 0.2)."""
        gdf = self._make_gdf(1)
        layers = {"PTXX": gdf}
        records = prepare_records(layers)
        assert records[0]["category"] == "inny"
        assert records[0]["cn_value"] == 75
