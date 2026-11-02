"""
Unit tests for land cover stats analysis in cn_calculator module.

Tests for:
- _extract_bdot_code() helper
- get_land_cover_stats() with the real Kartograf (stubbed BDOT10k service)
- _analyze_land_cover_gpkgs() with mocked geopandas/fiona
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import geopandas as gpd
import kartograf
import pytest
from shapely.geometry import box

from core.cn_calculator import (
    BDOT10K_CATEGORY_MAP,
    _analyze_land_cover_gpkgs,
    _extract_bdot_code,
    get_land_cover_stats,
)
from tests.kartograf_offline import Counties, bdot10k_counties
from tests.kartograf_offline import offline as offline  # noqa: F401


class TestExtractBdotCode:
    """Tests for _extract_bdot_code helper function."""

    def test_full_bdot_format(self):
        """Test extraction from full BDOT10k layer name: OT_PTLZ_A -> PTLZ."""
        assert _extract_bdot_code("OT_PTLZ_A") == "PTLZ"

    def test_full_bdot_format_various_codes(self):
        """Test extraction for various BDOT10k PT* codes."""
        assert _extract_bdot_code("OT_PTTR_A") == "PTTR"
        assert _extract_bdot_code("OT_PTWP_A") == "PTWP"
        assert _extract_bdot_code("OT_PTZB_A") == "PTZB"
        assert _extract_bdot_code("OT_PTKM_A") == "PTKM"

    def test_bare_code(self):
        """Test extraction from bare code: PTLZ -> PTLZ."""
        assert _extract_bdot_code("PTLZ") == "PTLZ"

    def test_lowercase_input(self):
        """Test extraction with lowercase input."""
        assert _extract_bdot_code("ot_ptlz_a") == "PTLZ"

    def test_line_suffix(self):
        """Test extraction with _L suffix (line features): OT_PTTR_L -> PTTR."""
        assert _extract_bdot_code("OT_PTTR_L") == "PTTR"

    def test_non_pt_layer(self):
        """Test returns None for non-PT layer names."""
        assert _extract_bdot_code("OT_BUBD_A") is None
        assert _extract_bdot_code("some_other_layer") is None
        assert _extract_bdot_code("gpkg_contents") is None

    def test_empty_string(self):
        """Test returns None for empty string."""
        assert _extract_bdot_code("") is None

    def test_all_known_codes_in_map(self):
        """Test that all BDOT10K_CATEGORY_MAP keys can be extracted."""
        for code in BDOT10K_CATEGORY_MAP:
            layer_name = f"OT_{code}_A"
            assert _extract_bdot_code(layer_name) == code


def _write_gpkg(path: Path, layers: dict[str, Any]) -> Path:
    """Write a BDOT10k-like GeoPackage: one polygon per PT* layer, in EPSG:2180."""
    for name, geometry in layers.items():
        gpd.GeoDataFrame({"geometry": [geometry]}, crs="EPSG:2180").to_file(
            path, layer=name, driver="GPKG"
        )
    return path


# the area of the tests: 1 km x 1 km, the west 60% is forest, the east 40% arable
AREA = kartograf.BBox(500000, 600000, 501000, 601000, "EPSG:2180")
WEST = box(500000, 600000, 500600, 601000)
EAST = box(500600, 600000, 501000, 601000)


@pytest.mark.usefixtures("offline")
class TestGetLandCoverStats:
    """get_land_cover_stats reads the packages of the counties from the store."""

    def test_percentages_of_a_county_by_teryt(self, tmp_path):
        gpkg = _write_gpkg(
            tmp_path / "1465.gpkg", {"OT_PTLZ_A": WEST, "OT_PTTR_A": EAST}
        )
        with bdot10k_counties(Counties(["1465"], geopackages={"1465": gpkg})):
            stats = get_land_cover_stats(AREA, tmp_path / "cache", teryt="1465")

        assert stats == {"forest": 60.0, "arable": 40.0}

    def test_counties_of_an_area_count_by_their_area_not_by_file(self, tmp_path):
        west = _write_gpkg(tmp_path / "1401.gpkg", {"OT_PTLZ_A": WEST})
        east = _write_gpkg(tmp_path / "1465.gpkg", {"OT_PTTR_A": EAST})
        counties = Counties(["1401", "1465"], geopackages={"1401": west, "1465": east})
        with bdot10k_counties(counties):
            stats = get_land_cover_stats(AREA, tmp_path / "cache")

        assert stats == {"forest": 60.0, "arable": 40.0}
        assert counties.packages == ["1401", "1465"]

    def test_packages_are_versions_of_the_store_of_the_cache(self, tmp_path):
        gpkg = _write_gpkg(tmp_path / "1465.gpkg", {"OT_PTLZ_A": WEST})
        counties = Counties(["1465"], geopackages={"1465": gpkg})
        with bdot10k_counties(counties):
            get_land_cover_stats(AREA, tmp_path / "cache", teryt="1465")
            get_land_cover_stats(AREA, tmp_path / "cache", teryt="1465")

        stored = tmp_path / "cache" / "kartograf" / "landcover"
        assert (stored / "pl_bdot10k_gpkg" / "teryt" / "1465.gpkg").is_file()
        assert counties.packages == ["1465"]  # the second call used the local one

    def test_returns_empty_when_the_county_fails(self, tmp_path):
        with bdot10k_counties(Counties(["1465"], failing=["1465"])):
            assert get_land_cover_stats(AREA, tmp_path, teryt="1465") == {}

    def test_returns_empty_when_the_store_refuses_the_write(self, tmp_path):
        store = tmp_path / "kartograf"
        store.mkdir()
        (store / "notes.txt").write_text("not a store")
        with bdot10k_counties(Counties(["1465"])):
            assert get_land_cover_stats(AREA, tmp_path, teryt="1465") == {}


class TestAnalyzeLandCoverGpkg:
    """Tests for _analyze_land_cover_gpkg function."""

    @patch("core.cn_calculator.fiona", create=True)
    @patch("core.cn_calculator.gpd", create=True)
    def test_returns_percentages_for_valid_gpkg(self, mock_gpd, mock_fiona):
        """Test returns correct percentages for a GeoPackage with PT layers."""
        import geopandas as gpd
        from shapely.geometry import box

        # Create mock bbox
        bbox = MagicMock(min_x=500000.0, min_y=600000.0, max_x=501000.0, max_y=601000.0)

        # Create test geometries in bbox
        forest_poly = box(500000, 600000, 500600, 601000)  # 60% area
        arable_poly = box(500600, 600000, 501000, 601000)  # 40% area

        # Create mock GeoDataFrames
        forest_gdf = gpd.GeoDataFrame(
            {"geometry": [forest_poly]},
            crs="EPSG:2180",
        )
        arable_gdf = gpd.GeoDataFrame(
            {"geometry": [arable_poly]},
            crs="EPSG:2180",
        )

        gpkg_path = Path("/tmp/test.gpkg")

        with (
            patch("fiona.listlayers", return_value=["OT_PTLZ_A", "OT_PTTR_A"]),
            patch(
                "geopandas.read_file",
                side_effect=lambda path, layer=None: (
                    forest_gdf if "PTLZ" in layer else arable_gdf
                ),
            ),
            patch("geopandas.clip", side_effect=lambda gdf, mask: gdf),
        ):
            result = _analyze_land_cover_gpkgs([gpkg_path], bbox)

        assert isinstance(result, dict)
        assert "forest" in result
        assert "arable" in result
        total = sum(result.values())
        assert abs(total - 100.0) < 1.0  # Should sum to ~100%

    def test_empty_gpkg_returns_empty_dict(self):
        """Test returns {} for GeoPackage with no PT layers."""
        bbox = MagicMock(min_x=500000.0, min_y=600000.0, max_x=501000.0, max_y=601000.0)
        gpkg_path = Path("/tmp/empty.gpkg")

        with patch("fiona.listlayers", return_value=["gpkg_contents", "OT_BUBD_A"]):
            result = _analyze_land_cover_gpkgs([gpkg_path], bbox)

        assert result == {}

    def test_returns_empty_on_fiona_error(self):
        """Test returns {} when fiona raises an error."""
        bbox = MagicMock(min_x=500000.0, min_y=600000.0, max_x=501000.0, max_y=601000.0)
        gpkg_path = Path("/tmp/bad.gpkg")

        with patch("fiona.listlayers", side_effect=Exception("Cannot open file")):
            result = _analyze_land_cover_gpkgs([gpkg_path], bbox)

        assert result == {}

    def test_aggregates_multiple_layers_to_same_category(self):
        """Test that PTTR and PTUT both map to 'arable' and areas are summed."""
        import geopandas as gpd
        from shapely.geometry import box

        bbox = MagicMock(min_x=500000.0, min_y=600000.0, max_x=501000.0, max_y=601000.0)

        poly1 = box(500000, 600000, 500500, 601000)
        poly2 = box(500500, 600000, 501000, 601000)

        gdf1 = gpd.GeoDataFrame({"geometry": [poly1]}, crs="EPSG:2180")
        gdf2 = gpd.GeoDataFrame({"geometry": [poly2]}, crs="EPSG:2180")

        gpkg_path = Path("/tmp/test_agg.gpkg")

        with (
            patch("fiona.listlayers", return_value=["OT_PTTR_A", "OT_PTUT_A"]),
            patch(
                "geopandas.read_file",
                side_effect=lambda path, layer=None: gdf1 if "PTTR" in layer else gdf2,
            ),
            patch("geopandas.clip", side_effect=lambda gdf, mask: gdf),
        ):
            result = _analyze_land_cover_gpkgs([gpkg_path], bbox)

        # Both PTTR and PTUT map to "arable"
        assert "arable" in result
        assert result["arable"] == 100.0

    def test_skips_empty_geodataframe(self):
        """Test that empty GeoDataFrames are skipped."""
        import geopandas as gpd

        bbox = MagicMock(min_x=500000.0, min_y=600000.0, max_x=501000.0, max_y=601000.0)

        empty_gdf = gpd.GeoDataFrame({"geometry": []}, crs="EPSG:2180")

        gpkg_path = Path("/tmp/test_empty_layer.gpkg")

        with (
            patch("fiona.listlayers", return_value=["OT_PTLZ_A"]),
            patch("geopandas.read_file", return_value=empty_gdf),
        ):
            result = _analyze_land_cover_gpkgs([gpkg_path], bbox)

        assert result == {}


class TestBdot10kCategoryMap:
    """Tests for BDOT10K_CATEGORY_MAP consistency."""

    def test_all_categories_are_valid_cn_lookup_keys(self):
        """Test all mapped categories exist in CN_LOOKUP_TABLE."""
        from core.cn_tables import CN_LOOKUP_TABLE

        for bdot_code, category in BDOT10K_CATEGORY_MAP.items():
            assert category in CN_LOOKUP_TABLE, (
                f"Category '{category}' (from {bdot_code}) not in CN_LOOKUP_TABLE"
            )

    def test_map_has_all_expected_pt_codes(self):
        """Test map contains all known PT codes from BDOT10k."""
        expected_codes = {
            "PTLZ",
            "PTTR",
            "PTUT",
            "PTWP",
            "PTWZ",
            "PTRK",
            "PTZB",
            "PTKM",
            "PTPL",
            "PTGN",
            "PTNZ",
            "PTSO",
        }
        assert set(BDOT10K_CATEGORY_MAP.keys()) == expected_codes
