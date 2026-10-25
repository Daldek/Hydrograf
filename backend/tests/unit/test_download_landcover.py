"""Tests for download_landcover: fetch_landcover (real Kartograf), hydro merge."""

from pathlib import Path

import fiona
import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point

from scripts.download_landcover import fetch_landcover, merge_hydro_gpkgs
from tests.kartograf_offline import Counties, bdot10k_counties
from tests.kartograf_offline import offline as offline  # noqa: F401

LANDCOVER = "landcover/pl_bdot10k_gpkg/teryt"


@pytest.mark.usefixtures("offline")
class TestFetchLandcover:
    """The request goes to Kartograf and the file lands in the store (ADR-061)."""

    def test_teryt_lands_at_the_standard_path_of_the_store(self, tmp_path):
        root = tmp_path / "kartograf"
        with bdot10k_counties(Counties(["1465"])):
            report = fetch_landcover(root, teryt="1465")

        assert report.ok
        assert [item.file.path for item in report.files] == [
            root / LANDCOVER / "1465.gpkg"
        ]
        assert (root / "kartograf-store.json").is_file()

    def test_point_covers_every_county_of_the_square_around_it(self, tmp_path):
        counties = Counties(["1401", "1465"])
        with bdot10k_counties(counties):
            report = fetch_landcover(
                tmp_path / "k", lat=52.23, lon=21.01, buffer_km=5.0
            )

        assert sorted(item.unit for item in report.files) == ["1401", "1465"]
        (area,) = counties.areas
        assert area.crs == "EPSG:2180"
        assert area.max_x - area.min_x == pytest.approx(10000)
        assert area.max_y - area.min_y == pytest.approx(10000)

    def test_second_run_uses_the_local_version(self, tmp_path):
        counties = Counties(["1465"])
        with bdot10k_counties(counties):
            fetch_landcover(tmp_path / "k", teryt="1465")
            again = fetch_landcover(tmp_path / "k", teryt="1465")

        assert counties.packages == ["1465"]
        assert [item.file.status for item in again.files] == ["local"]

    def test_no_skip_existing_fetches_the_county_again(self, tmp_path):
        counties = Counties(["1465"])
        with bdot10k_counties(counties):
            fetch_landcover(tmp_path / "k", teryt="1465")
            fetch_landcover(tmp_path / "k", teryt="1465", skip_existing=False)

        assert counties.packages == ["1465", "1465"]

    def test_a_failed_county_does_not_stop_the_others(self, tmp_path):
        counties = Counties(["1401", "1465"], failing=["1401"])
        with bdot10k_counties(counties):
            report = fetch_landcover(tmp_path / "k", lat=52.23, lon=21.01)

        assert not report.ok
        assert [item.unit for item in report.files] == ["1465"]
        assert [failure.unit for failure in report.failed] == ["1401"]

    def test_no_area_raises(self, tmp_path):
        with pytest.raises(ValueError, match="--teryt"):
            fetch_landcover(tmp_path / "k")


class TestMergeHydroGpkgs:
    """Tests for merge_hydro_gpkgs."""

    @pytest.fixture()
    def _make_hydro_gpkg(self, tmp_path):
        """Factory: create a hydro GeoPackage with given layers."""

        def _factory(name: str, layers: dict[str, gpd.GeoDataFrame]) -> Path:
            path = tmp_path / name
            for layer_name, gdf in layers.items():
                gdf.to_file(path, layer=layer_name, driver="GPKG")
            return Path(path)

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
