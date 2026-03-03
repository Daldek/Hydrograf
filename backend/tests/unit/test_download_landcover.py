"""Tests for download_landcover: TERYT discovery and hydro merge."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import fiona
import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from scripts.download_landcover import (
    _generate_sample_coords,
    discover_teryts_for_bbox,
    merge_hydro_gpkgs,
)


class TestGenerateSampleCoords:
    """Tests for _generate_sample_coords helper."""

    def test_start_equals_end(self):
        result = _generate_sample_coords(100.0, 100.0, 5000.0)
        assert result == [100.0]

    def test_small_range_returns_three_points(self):
        result = _generate_sample_coords(0.0, 3000.0, 5000.0)
        assert len(result) == 3
        assert result[0] == 0.0
        assert result[1] == 1500.0
        assert result[2] == 3000.0

    def test_large_range_includes_endpoints(self):
        result = _generate_sample_coords(0.0, 10000.0, 5000.0)
        assert result[0] == 0.0
        assert result[-1] == 10000.0

    def test_large_range_even_spacing(self):
        result = _generate_sample_coords(0.0, 10000.0, 5000.0)
        assert len(result) == 3  # 0, 5000, 10000
        assert result == [0.0, 5000.0, 10000.0]

    def test_reversed_range(self):
        """Start > end should still work (lo/hi normalization)."""
        result = _generate_sample_coords(10000.0, 0.0, 5000.0)
        assert result[0] == 0.0
        assert result[-1] == 10000.0

    def test_spacing_larger_than_range(self):
        result = _generate_sample_coords(100.0, 200.0, 5000.0)
        assert len(result) == 3
        assert result[0] == 100.0
        assert result[1] == 150.0
        assert result[2] == 200.0

    def test_exact_multiple_spacing(self):
        result = _generate_sample_coords(0.0, 15000.0, 5000.0)
        assert len(result) == 4  # 0, 5000, 10000, 15000
        assert result[0] == 0.0
        assert result[-1] == 15000.0


class TestDiscoverTerytsForBbox:
    """Tests for discover_teryts_for_bbox with mocked Bdot10kProvider."""

    @patch("kartograf.providers.bdot10k.Bdot10kProvider")
    def test_single_teryt(self, mock_cls):
        """All sample points return the same TERYT."""
        provider = MagicMock()
        provider._get_teryt_for_point.return_value = "1465"
        mock_cls.return_value = provider

        bbox = (400000.0, 500000.0, 402000.0, 502000.0)
        result = discover_teryts_for_bbox(bbox, spacing_m=5000.0)

        assert result == ["1465"]
        assert provider._get_teryt_for_point.call_count > 0

    @patch("kartograf.providers.bdot10k.Bdot10kProvider")
    def test_two_teryts_on_boundary(self, mock_cls):
        """Bbox spanning two counties returns both TERYTs."""
        provider = MagicMock()

        def side_effect(x, y):
            if x < 405000:
                return "1465"
            return "3064"

        provider._get_teryt_for_point.side_effect = side_effect
        mock_cls.return_value = provider

        bbox = (400000.0, 500000.0, 410000.0, 510000.0)
        result = discover_teryts_for_bbox(bbox, spacing_m=5000.0)

        assert result == ["1465", "3064"]

    @patch("kartograf.providers.bdot10k.Bdot10kProvider")
    def test_water_point_skipped(self, mock_cls):
        """Points on water (exception) are skipped, rest OK."""
        provider = MagicMock()
        call_count = 0

        def side_effect(x, y):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Water body — no TERYT")
            return "1465"

        provider._get_teryt_for_point.side_effect = side_effect
        mock_cls.return_value = provider

        bbox = (400000.0, 500000.0, 402000.0, 502000.0)
        result = discover_teryts_for_bbox(bbox, spacing_m=5000.0)

        assert result == ["1465"]

    @patch("kartograf.providers.bdot10k.Bdot10kProvider")
    def test_all_points_fail(self, mock_cls):
        """If all points fail, return empty list."""
        provider = MagicMock()
        provider._get_teryt_for_point.side_effect = Exception("WMS error")
        mock_cls.return_value = provider

        bbox = (400000.0, 500000.0, 402000.0, 502000.0)
        result = discover_teryts_for_bbox(bbox, spacing_m=5000.0)

        assert result == []

    @patch("kartograf.providers.bdot10k.Bdot10kProvider")
    def test_results_sorted_and_unique(self, mock_cls):
        """Duplicate TERYTs are deduplicated and sorted."""
        provider = MagicMock()
        cycle = ["3064", "1465", "3064", "1465", "1465", "3064", "0202", "0202", "3064"]
        provider._get_teryt_for_point.side_effect = cycle
        mock_cls.return_value = provider

        bbox = (400000.0, 500000.0, 402000.0, 502000.0)
        result = discover_teryts_for_bbox(bbox, spacing_m=1000.0)

        assert result == sorted(set(cycle))
        assert result == ["0202", "1465", "3064"]


class TestMergeHydroGpkgs:
    """Tests for merge_hydro_gpkgs."""

    @pytest.fixture()
    def _make_hydro_gpkg(self, tmp_path):
        """Factory: create a hydro GeoPackage with given layers."""

        def _factory(name: str, layers: dict[str, gpd.GeoDataFrame]) -> Path:
            path = tmp_path / name
            for layer_name, gdf in layers.items():
                gdf.to_file(path, layer=layer_name, driver="GPKG")
            return path

        return _factory

    def test_empty_list_returns_none(self):
        result = merge_hydro_gpkgs([], Path("/tmp/out.gpkg"))
        assert result is None

    def test_single_file_returns_same_path(self, tmp_path, _make_hydro_gpkg):
        gdf = gpd.GeoDataFrame(
            {"name": ["r1"]},
            geometry=[LineString([(0, 0), (1, 1)])],
            crs="EPSG:2180",
        )
        gpkg = _make_hydro_gpkg("single.gpkg", {"OT_SWRS_L": gdf})

        result = merge_hydro_gpkgs([gpkg], tmp_path / "out.gpkg")
        assert result == gpkg

    def test_two_files_same_layers_merged(self, tmp_path, _make_hydro_gpkg):
        gdf1 = gpd.GeoDataFrame(
            {"name": ["r1"]},
            geometry=[LineString([(0, 0), (1, 1)])],
            crs="EPSG:2180",
        )
        gdf2 = gpd.GeoDataFrame(
            {"name": ["r2"]},
            geometry=[LineString([(2, 2), (3, 3)])],
            crs="EPSG:2180",
        )
        gpkg1 = _make_hydro_gpkg("a.gpkg", {"OT_SWRS_L": gdf1})
        gpkg2 = _make_hydro_gpkg("b.gpkg", {"OT_SWRS_L": gdf2})

        out = tmp_path / "merged.gpkg"
        result = merge_hydro_gpkgs([gpkg1, gpkg2], out)

        assert result == out
        assert out.exists()

        import fiona

        layers = fiona.listlayers(str(out))
        assert "OT_SWRS_L" in layers

        merged = gpd.read_file(out, layer="OT_SWRS_L")
        assert len(merged) == 2

    def test_different_layers_preserved(self, tmp_path, _make_hydro_gpkg):
        gdf_swrs = gpd.GeoDataFrame(
            {"name": ["r1"]},
            geometry=[LineString([(0, 0), (1, 1)])],
            crs="EPSG:2180",
        )
        gdf_ptwp = gpd.GeoDataFrame(
            {"name": ["lake1"]},
            geometry=[Point(5, 5).buffer(1)],
            crs="EPSG:2180",
        )
        gpkg1 = _make_hydro_gpkg("a.gpkg", {"OT_SWRS_L": gdf_swrs})
        gpkg2 = _make_hydro_gpkg("b.gpkg", {"OT_PTWP_A": gdf_ptwp})

        out = tmp_path / "merged.gpkg"
        result = merge_hydro_gpkgs([gpkg1, gpkg2], out)

        assert result == out

        import fiona

        layers = fiona.listlayers(str(out))
        assert "OT_SWRS_L" in layers
        assert "OT_PTWP_A" in layers

    def test_all_empty_files_returns_none(self, tmp_path):
        """GeoPackages with no readable layers → None."""
        # Create empty files (not valid GeoPackage)
        p1 = tmp_path / "empty1.gpkg"
        p2 = tmp_path / "empty2.gpkg"
        p1.write_bytes(b"")
        p2.write_bytes(b"")

        out = tmp_path / "merged.gpkg"
        result = merge_hydro_gpkgs([p1, p2], out)
        assert result is None

    def test_merge_filters_only_hydro_layers(self, tmp_path):
        """Verify that merge_hydro_gpkgs filters out non-hydro (PT) layers."""
        from shapely.geometry import LineString

        gpkg_path = tmp_path / "mixed.gpkg"
        # Create a GPKG with both hydro (SWRS) and non-hydro (PTLZ) layers
        hydro_gdf = gpd.GeoDataFrame(
            {"geometry": [LineString([(0, 0), (1, 1)])]},
            crs="EPSG:2180",
        )
        non_hydro_gdf = gpd.GeoDataFrame(
            {"geometry": [LineString([(2, 2), (3, 3)])]},
            crs="EPSG:2180",
        )
        hydro_gdf.to_file(gpkg_path, layer="OT_SWRS_L", driver="GPKG")
        non_hydro_gdf.to_file(gpkg_path, layer="OT_PTLZ_A", driver="GPKG")

        # Second GPKG to force merge path (single-file returns early)
        gpkg_path2 = tmp_path / "mixed2.gpkg"
        hydro_gdf2 = gpd.GeoDataFrame(
            {"geometry": [LineString([(4, 4), (5, 5)])]},
            crs="EPSG:2180",
        )
        hydro_gdf2.to_file(gpkg_path2, layer="OT_SWRS_L", driver="GPKG")

        output = tmp_path / "merged.gpkg"
        result = merge_hydro_gpkgs([gpkg_path, gpkg_path2], output)

        assert result is not None
        layers = fiona.listlayers(result)
        # Only hydro layers should remain
        assert "OT_SWRS_L" in layers
        assert "OT_PTLZ_A" not in layers
