"""Tests for download_landcover: TERYT discovery (WFS + grid fallback) and hydro merge."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import fiona
import geopandas as gpd
import pytest
import requests
from shapely.geometry import LineString, Point

from scripts.download_landcover import (
    _discover_teryts_grid,
    _generate_sample_coords,
    _parse_teryts_from_gml,
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


# ---------------------------------------------------------------------------
# GML parsing
# ---------------------------------------------------------------------------

SAMPLE_GML_TWO_POWIATS = """\
<?xml version="1.0" encoding="UTF-8"?>
<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"
    xmlns:ms="http://mapserver.gis.umn.edu/mapserver"
    numberMatched="2" numberReturned="2">
  <wfs:member>
    <ms:A02_Granice_powiatow>
      <ms:JPT_KOD_JE>3021</ms:JPT_KOD_JE>
      <ms:JPT_NAZWA_>powiat poznanski</ms:JPT_NAZWA_>
    </ms:A02_Granice_powiatow>
  </wfs:member>
  <wfs:member>
    <ms:A02_Granice_powiatow>
      <ms:JPT_KOD_JE>3064</ms:JPT_KOD_JE>
      <ms:JPT_NAZWA_>Poznan</ms:JPT_NAZWA_>
    </ms:A02_Granice_powiatow>
  </wfs:member>
</wfs:FeatureCollection>
"""

SAMPLE_GML_THREE_WITH_DUPLICATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"
    xmlns:ms="http://mapserver.gis.umn.edu/mapserver"
    numberMatched="3" numberReturned="3">
  <wfs:member>
    <ms:A02_Granice_powiatow>
      <ms:JPT_KOD_JE>3064</ms:JPT_KOD_JE>
      <ms:JPT_NAZWA_>Poznan</ms:JPT_NAZWA_>
    </ms:A02_Granice_powiatow>
  </wfs:member>
  <wfs:member>
    <ms:A02_Granice_powiatow>
      <ms:JPT_KOD_JE>3021</ms:JPT_KOD_JE>
      <ms:JPT_NAZWA_>powiat poznanski</ms:JPT_NAZWA_>
    </ms:A02_Granice_powiatow>
  </wfs:member>
  <wfs:member>
    <ms:A02_Granice_powiatow>
      <ms:JPT_KOD_JE>3064</ms:JPT_KOD_JE>
      <ms:JPT_NAZWA_>Poznan</ms:JPT_NAZWA_>
    </ms:A02_Granice_powiatow>
  </wfs:member>
</wfs:FeatureCollection>
"""

SAMPLE_GML_EMPTY = """\
<?xml version="1.0" encoding="UTF-8"?>
<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"
    xmlns:ms="http://mapserver.gis.umn.edu/mapserver"
    numberMatched="0" numberReturned="0">
</wfs:FeatureCollection>
"""


class TestParseTerytsFromGml:
    """Tests for _parse_teryts_from_gml GML parser."""

    def test_two_powiats(self):
        result = _parse_teryts_from_gml(SAMPLE_GML_TWO_POWIATS)
        assert result == {"3021", "3064"}

    def test_deduplication(self):
        result = _parse_teryts_from_gml(SAMPLE_GML_THREE_WITH_DUPLICATE)
        assert result == {"3021", "3064"}

    def test_empty_collection(self):
        result = _parse_teryts_from_gml(SAMPLE_GML_EMPTY)
        assert result == set()

    def test_invalid_xml(self):
        result = _parse_teryts_from_gml("<<<not valid xml>>>")
        assert result == set()

    def test_no_teryt_elements(self):
        gml = '<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"></wfs:FeatureCollection>'
        result = _parse_teryts_from_gml(gml)
        assert result == set()

    def test_whitespace_stripped(self):
        gml = """\
<?xml version="1.0" encoding="UTF-8"?>
<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"
    xmlns:ms="http://mapserver.gis.umn.edu/mapserver">
  <wfs:member>
    <ms:A02_Granice_powiatow>
      <ms:JPT_KOD_JE>  0202  </ms:JPT_KOD_JE>
    </ms:A02_Granice_powiatow>
  </wfs:member>
</wfs:FeatureCollection>
"""
        result = _parse_teryts_from_gml(gml)
        assert result == {"0202"}

    def test_alternative_namespace(self):
        """Namespace-agnostic parser handles different namespace URIs."""
        gml = """\
<?xml version="1.0" encoding="UTF-8"?>
<FeatureCollection xmlns:custom="http://example.com/custom">
  <member>
    <custom:A02_Granice_powiatow>
      <custom:JPT_KOD_JE>9999</custom:JPT_KOD_JE>
    </custom:A02_Granice_powiatow>
  </member>
</FeatureCollection>
"""
        result = _parse_teryts_from_gml(gml)
        assert result == {"9999"}

    def test_empty_teryt_text_ignored(self):
        """Elements with empty text content are skipped."""
        gml = """\
<?xml version="1.0" encoding="UTF-8"?>
<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0"
    xmlns:ms="http://mapserver.gis.umn.edu/mapserver">
  <wfs:member>
    <ms:A02_Granice_powiatow>
      <ms:JPT_KOD_JE>  </ms:JPT_KOD_JE>
    </ms:A02_Granice_powiatow>
  </wfs:member>
  <wfs:member>
    <ms:A02_Granice_powiatow>
      <ms:JPT_KOD_JE>1465</ms:JPT_KOD_JE>
    </ms:A02_Granice_powiatow>
  </wfs:member>
</wfs:FeatureCollection>
"""
        result = _parse_teryts_from_gml(gml)
        assert result == {"1465"}


# ---------------------------------------------------------------------------
# WFS-based discover_teryts_for_bbox
# ---------------------------------------------------------------------------


def _make_wfs_response(text: str, status_code: int = 200) -> MagicMock:
    """Create a mock requests.Response for WFS calls."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = text
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestDiscoverTerytsForBboxWfs:
    """Tests for discover_teryts_for_bbox — WFS primary path."""

    BBOX = (300000.0, 450000.0, 350000.0, 500000.0)

    @patch("scripts.download_landcover.requests.get")
    def test_wfs_success_returns_sorted(self, mock_get):
        mock_get.return_value = _make_wfs_response(SAMPLE_GML_TWO_POWIATS)
        result = discover_teryts_for_bbox(self.BBOX)
        assert result == ["3021", "3064"]
        mock_get.assert_called_once()

    @patch("scripts.download_landcover.requests.get")
    def test_wfs_deduplicates(self, mock_get):
        mock_get.return_value = _make_wfs_response(SAMPLE_GML_THREE_WITH_DUPLICATE)
        result = discover_teryts_for_bbox(self.BBOX)
        assert result == ["3021", "3064"]

    @patch("scripts.download_landcover.requests.get")
    def test_wfs_requests_only_attributes(self, mock_get):
        """propertyName should skip geometry for speed."""
        mock_get.return_value = _make_wfs_response(SAMPLE_GML_TWO_POWIATS)
        discover_teryts_for_bbox(self.BBOX)
        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params", {})
        assert params["propertyName"] == "JPT_KOD_JE,JPT_NAZWA_"

    @patch("scripts.download_landcover.requests.get")
    def test_wfs_bbox_format(self, mock_get):
        """BBOX param contains coordinates and EPSG:2180."""
        mock_get.return_value = _make_wfs_response(SAMPLE_GML_TWO_POWIATS)
        discover_teryts_for_bbox(self.BBOX)
        call_kwargs = mock_get.call_args
        params = call_kwargs.kwargs.get("params", {})
        assert params["BBOX"] == "300000.0,450000.0,350000.0,500000.0,EPSG:2180"

    @patch("scripts.download_landcover._discover_teryts_grid")
    @patch("scripts.download_landcover.requests.get")
    def test_wfs_timeout_falls_back_to_grid(self, mock_get, mock_grid):
        mock_get.side_effect = requests.exceptions.Timeout("timeout")
        mock_grid.return_value = ["1465"]
        result = discover_teryts_for_bbox(self.BBOX, spacing_m=3000.0)
        assert result == ["1465"]
        mock_grid.assert_called_once_with(self.BBOX, spacing_m=3000.0)

    @patch("scripts.download_landcover._discover_teryts_grid")
    @patch("scripts.download_landcover.requests.get")
    def test_wfs_connection_error_falls_back(self, mock_get, mock_grid):
        mock_get.side_effect = requests.exceptions.ConnectionError("refused")
        mock_grid.return_value = ["3064"]
        result = discover_teryts_for_bbox(self.BBOX)
        assert result == ["3064"]
        mock_grid.assert_called_once()

    @patch("scripts.download_landcover._discover_teryts_grid")
    @patch("scripts.download_landcover.requests.get")
    def test_wfs_http_500_falls_back(self, mock_get, mock_grid):
        resp = _make_wfs_response("", 500)
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
        mock_get.return_value = resp
        mock_grid.return_value = ["0202"]
        result = discover_teryts_for_bbox(self.BBOX)
        assert result == ["0202"]
        mock_grid.assert_called_once()

    @patch("scripts.download_landcover._discover_teryts_grid")
    @patch("scripts.download_landcover.requests.get")
    def test_wfs_empty_response_falls_back(self, mock_get, mock_grid):
        """0 TERYTs from WFS triggers fallback."""
        mock_get.return_value = _make_wfs_response(SAMPLE_GML_EMPTY)
        mock_grid.return_value = ["1465"]
        result = discover_teryts_for_bbox(self.BBOX)
        assert result == ["1465"]
        mock_grid.assert_called_once()

    @patch("scripts.download_landcover._discover_teryts_grid")
    @patch("scripts.download_landcover.requests.get")
    def test_wfs_malformed_xml_falls_back(self, mock_get, mock_grid):
        """Malformed XML triggers fallback."""
        mock_get.return_value = _make_wfs_response("<<<not xml>>>")
        mock_grid.return_value = ["1465"]
        result = discover_teryts_for_bbox(self.BBOX)
        assert result == ["1465"]
        mock_grid.assert_called_once()


# ---------------------------------------------------------------------------
# Legacy grid fallback
# ---------------------------------------------------------------------------


class TestDiscoverTerytsGrid:
    """Tests for _discover_teryts_grid (legacy WMS grid-sampling fallback)."""

    @patch("kartograf.providers.bdot10k.Bdot10kProvider")
    def test_single_teryt(self, mock_cls):
        """All sample points return the same TERYT."""
        provider = MagicMock()
        provider._get_teryt_for_point.return_value = "1465"
        mock_cls.return_value = provider

        bbox = (400000.0, 500000.0, 402000.0, 502000.0)
        result = _discover_teryts_grid(bbox, spacing_m=5000.0)

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
        result = _discover_teryts_grid(bbox, spacing_m=5000.0)

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
                raise Exception("Water body - no TERYT")
            return "1465"

        provider._get_teryt_for_point.side_effect = side_effect
        mock_cls.return_value = provider

        bbox = (400000.0, 500000.0, 402000.0, 502000.0)
        result = _discover_teryts_grid(bbox, spacing_m=5000.0)

        assert result == ["1465"]

    @patch("kartograf.providers.bdot10k.Bdot10kProvider")
    def test_all_points_fail(self, mock_cls):
        """If all points fail, return empty list."""
        provider = MagicMock()
        provider._get_teryt_for_point.side_effect = Exception("WMS error")
        mock_cls.return_value = provider

        bbox = (400000.0, 500000.0, 402000.0, 502000.0)
        result = _discover_teryts_grid(bbox, spacing_m=5000.0)

        assert result == []

    @patch("kartograf.providers.bdot10k.Bdot10kProvider")
    def test_results_sorted_and_unique(self, mock_cls):
        """Duplicate TERYTs are deduplicated and sorted."""
        provider = MagicMock()
        cycle = ["3064", "1465", "3064", "1465", "1465", "3064", "0202", "0202", "3064"]
        provider._get_teryt_for_point.side_effect = cycle
        mock_cls.return_value = provider

        bbox = (400000.0, 500000.0, 402000.0, 502000.0)
        result = _discover_teryts_grid(bbox, spacing_m=1000.0)

        assert result == sorted(set(cycle))
        assert result == ["0202", "1465", "3064"]


# ---------------------------------------------------------------------------
# Hydro merge
# ---------------------------------------------------------------------------


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

        layers = fiona.listlayers(str(out))
        assert "OT_SWRS_L" in layers
        assert "OT_PTWP_A" in layers

    def test_all_empty_files_returns_none(self, tmp_path):
        """GeoPackages with no readable layers -> None."""
        p1 = tmp_path / "empty1.gpkg"
        p2 = tmp_path / "empty2.gpkg"
        p1.write_bytes(b"")
        p2.write_bytes(b"")

        out = tmp_path / "merged.gpkg"
        result = merge_hydro_gpkgs([p1, p2], out)
        assert result is None

    def test_merge_filters_only_hydro_layers(self, tmp_path):
        """Verify that merge_hydro_gpkgs filters out non-hydro (PT) layers."""
        gpkg_path = tmp_path / "mixed.gpkg"
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
        assert "OT_SWRS_L" in layers
        assert "OT_PTLZ_A" not in layers
