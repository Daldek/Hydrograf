"""
Unit tests for land cover stats analysis in cn_calculator module.

Tests for:
- _extract_bdot_code() helper
- get_land_cover_stats() with mocked Kartograf
- _analyze_land_cover_gpkg() with mocked geopandas/fiona
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from core.cn_calculator import (
    BDOT10K_CATEGORY_MAP,
    _analyze_land_cover_gpkg,
    _extract_bdot_code,
    get_land_cover_stats,
)


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


class TestGetLandCoverStats:
    """Tests for get_land_cover_stats function."""

    @patch("core.cn_calculator._analyze_land_cover_gpkg")
    @patch("core.cn_calculator.LandCoverManager", create=True)
    def test_returns_percentages(self, mock_lc_cls, mock_analyze):
        """Test returns percentage dict when GeoPackage is available."""
        # Mock kartograf import inside function
        mock_manager = MagicMock()
        mock_manager.download_by_bbox.return_value = Path("/tmp/fake.gpkg")

        expected_stats = {"forest": 60.0, "arable": 30.0, "meadow": 10.0}
        mock_analyze.return_value = expected_stats

        bbox = MagicMock(min_x=500000, min_y=600000, max_x=501000, max_y=601000)

        with patch.dict(
            "sys.modules",
            {"kartograf": MagicMock(LandCoverManager=lambda **kw: mock_manager)},
        ):
            result = get_land_cover_stats(bbox, Path("/tmp/data"))

        assert result == expected_stats

    def test_returns_empty_on_import_error(self):
        """Test returns {} when kartograf is not available."""
        bbox = MagicMock()

        with patch.dict("sys.modules", {"kartograf": None}):
            # ImportError will be raised, caught by except block
            result = get_land_cover_stats(bbox, Path("/tmp/data"))

        assert result == {}

    @patch("core.cn_calculator._analyze_land_cover_gpkg")
    def test_returns_empty_when_download_returns_none(self, mock_analyze):
        """Test returns {} when LandCoverManager returns None."""
        mock_manager = MagicMock()
        mock_manager.download_by_bbox.return_value = None

        bbox = MagicMock()

        with patch.dict(
            "sys.modules",
            {"kartograf": MagicMock(LandCoverManager=lambda **kw: mock_manager)},
        ):
            result = get_land_cover_stats(bbox, Path("/tmp/data"))

        assert result == {}
        mock_analyze.assert_not_called()


class TestAnalyzeLandCoverGpkg:
    """Tests for _analyze_land_cover_gpkg function."""

    @patch("core.cn_calculator.fiona", create=True)
    @patch("core.cn_calculator.gpd", create=True)
    def test_returns_percentages_for_valid_gpkg(self, mock_gpd, mock_fiona):
        """Test returns correct percentages for a GeoPackage with PT layers."""
        import geopandas as gpd
        from shapely.geometry import box

        # Create mock bbox
        bbox = MagicMock(
            min_x=500000.0, min_y=600000.0, max_x=501000.0, max_y=601000.0
        )

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
            result = _analyze_land_cover_gpkg(gpkg_path, bbox)

        assert isinstance(result, dict)
        assert "forest" in result
        assert "arable" in result
        total = sum(result.values())
        assert abs(total - 100.0) < 1.0  # Should sum to ~100%

    def test_empty_gpkg_returns_empty_dict(self):
        """Test returns {} for GeoPackage with no PT layers."""
        bbox = MagicMock(
            min_x=500000.0, min_y=600000.0, max_x=501000.0, max_y=601000.0
        )
        gpkg_path = Path("/tmp/empty.gpkg")

        with patch("fiona.listlayers", return_value=["gpkg_contents", "OT_BUBD_A"]):
            result = _analyze_land_cover_gpkg(gpkg_path, bbox)

        assert result == {}

    def test_returns_empty_on_fiona_error(self):
        """Test returns {} when fiona raises an error."""
        bbox = MagicMock(
            min_x=500000.0, min_y=600000.0, max_x=501000.0, max_y=601000.0
        )
        gpkg_path = Path("/tmp/bad.gpkg")

        with patch("fiona.listlayers", side_effect=Exception("Cannot open file")):
            result = _analyze_land_cover_gpkg(gpkg_path, bbox)

        assert result == {}

    def test_aggregates_multiple_layers_to_same_category(self):
        """Test that PTTR and PTUT both map to 'arable' and areas are summed."""
        import geopandas as gpd
        from shapely.geometry import box

        bbox = MagicMock(
            min_x=500000.0, min_y=600000.0, max_x=501000.0, max_y=601000.0
        )

        poly1 = box(500000, 600000, 500500, 601000)
        poly2 = box(500500, 600000, 501000, 601000)

        gdf1 = gpd.GeoDataFrame({"geometry": [poly1]}, crs="EPSG:2180")
        gdf2 = gpd.GeoDataFrame({"geometry": [poly2]}, crs="EPSG:2180")

        gpkg_path = Path("/tmp/test_agg.gpkg")

        with (
            patch("fiona.listlayers", return_value=["OT_PTTR_A", "OT_PTUT_A"]),
            patch(
                "geopandas.read_file",
                side_effect=lambda path, layer=None: (
                    gdf1 if "PTTR" in layer else gdf2
                ),
            ),
            patch("geopandas.clip", side_effect=lambda gdf, mask: gdf),
        ):
            result = _analyze_land_cover_gpkg(gpkg_path, bbox)

        # Both PTTR and PTUT map to "arable"
        assert "arable" in result
        assert result["arable"] == 100.0

    def test_skips_empty_geodataframe(self):
        """Test that empty GeoDataFrames are skipped."""
        import geopandas as gpd

        bbox = MagicMock(
            min_x=500000.0, min_y=600000.0, max_x=501000.0, max_y=601000.0
        )

        empty_gdf = gpd.GeoDataFrame({"geometry": []}, crs="EPSG:2180")

        gpkg_path = Path("/tmp/test_empty_layer.gpkg")

        with (
            patch("fiona.listlayers", return_value=["OT_PTLZ_A"]),
            patch("geopandas.read_file", return_value=empty_gdf),
        ):
            result = _analyze_land_cover_gpkg(gpkg_path, bbox)

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
            "PTLZ", "PTTR", "PTUT", "PTWP", "PTWZ",
            "PTRK", "PTZB", "PTKM", "PTPL", "PTGN",
            "PTNZ", "PTSO",
        }
        assert set(BDOT10K_CATEGORY_MAP.keys()) == expected_codes
