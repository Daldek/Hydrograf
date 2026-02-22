"""Tests for BDOT10k GeoJSON export."""

import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Polygon


def _create_mock_gpkg(tmp_path: Path) -> Path:
    """Create a minimal GPKG with BDOT10k-like layers."""
    gpkg_path = tmp_path / "hydro.gpkg"

    # Lakes
    lakes = gpd.GeoDataFrame(
        {"LOKALNYID": ["lake1"]},
        geometry=[
            Polygon(
                [
                    (400000, 500000),
                    (400100, 500000),
                    (400100, 500100),
                    (400000, 500100),
                ]
            )
        ],
        crs="EPSG:2180",
    )
    lakes.to_file(gpkg_path, layer="OT_PTWP_A", driver="GPKG")

    # Streams
    streams = gpd.GeoDataFrame(
        {"LOKALNYID": ["stream1"]},
        geometry=[LineString([(400000, 500000), (400500, 500500)])],
        crs="EPSG:2180",
    )
    streams.to_file(gpkg_path, layer="OT_SWRS_L", driver="GPKG")

    return gpkg_path


class TestExportBdotGeojson:
    def test_exports_both_files(self, tmp_path):
        from scripts.bootstrap import export_bdot_geojson

        gpkg = _create_mock_gpkg(tmp_path)
        out_dir = tmp_path / "output"
        out_dir.mkdir()

        result = export_bdot_geojson(gpkg, out_dir)

        assert (out_dir / "bdot_lakes.geojson").exists()
        assert (out_dir / "bdot_streams.geojson").exists()
        assert "1 zbiorników" in result
        assert "1 cieków" in result

    def test_source_layer_property(self, tmp_path):
        from scripts.bootstrap import export_bdot_geojson

        gpkg = _create_mock_gpkg(tmp_path)
        out_dir = tmp_path / "output"
        out_dir.mkdir()

        export_bdot_geojson(gpkg, out_dir)

        with open(out_dir / "bdot_lakes.geojson") as f:
            data = json.load(f)
        assert data["features"][0]["properties"]["source_layer"] == "OT_PTWP_A"

        with open(out_dir / "bdot_streams.geojson") as f:
            data = json.load(f)
        assert data["features"][0]["properties"]["source_layer"] == "OT_SWRS_L"

    def test_output_crs_is_wgs84(self, tmp_path):
        from scripts.bootstrap import export_bdot_geojson

        gpkg = _create_mock_gpkg(tmp_path)
        out_dir = tmp_path / "output"
        out_dir.mkdir()

        export_bdot_geojson(gpkg, out_dir)

        gdf = gpd.read_file(out_dir / "bdot_lakes.geojson")
        assert gdf.crs.to_epsg() == 4326

    def test_missing_layers_graceful(self, tmp_path):
        """GPKG with only streams, no lakes."""
        from scripts.bootstrap import export_bdot_geojson

        gpkg_path = tmp_path / "streams_only.gpkg"
        streams = gpd.GeoDataFrame(
            {"LOKALNYID": ["s1"]},
            geometry=[LineString([(400000, 500000), (400500, 500500)])],
            crs="EPSG:2180",
        )
        streams.to_file(gpkg_path, layer="OT_SWRS_L", driver="GPKG")

        out_dir = tmp_path / "output"
        out_dir.mkdir()

        result = export_bdot_geojson(gpkg_path, out_dir)
        assert "0 zbiorników" in result
        assert (out_dir / "bdot_streams.geojson").exists()
        assert not (out_dir / "bdot_lakes.geojson").exists()
