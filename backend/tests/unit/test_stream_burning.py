"""Which BDOT10k streams the stream burning takes (``dem.stream_burning``)."""

import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import LineString, MultiLineString, box

from core.config import load_config
from core.hydrology import (
    STREAM_ATTRIBUTES,
    _load_stream_features,
    burn_streams_into_dem,
    smooth_streams_monotonic,
)

NODATA = -9999.0
NCOLS = 10
X0, Y0 = 500000.0, 300030.0  # top left corner, 1 m cells, 30 rows

# Every case on its own DEM row: (layer, row, attributes)
LINES = {
    "river": ("OT_SWRS_L", 1, ("rzeka", "ciek główny", None)),
    "mphp_stream": ("OT_SWRS_L", 4, ("strumień, potok lub struga", "ciek główny", "1")),
    "stream_without_mphp": (
        "OT_SWRS_L",
        7,
        ("strumień, potok lub struga", "ciek główny", "  "),
    ),
    "side_arm": ("OT_SWRS_L", 10, ("rzeka", "ramię boczne", "2")),
    "canal_with_mphp": ("OT_SWKN_L", 13, (None, None, "3")),
    "canal_without_mphp": ("OT_SWKN_L", 16, (None, None, None)),
    "ditch": ("OT_SWRM_L", 19, (None, None, "4")),
}
LAKE_ROW, LAKE_COL = 26, 2
MAIN = {"river", "mphp_stream", "canal_with_mphp"}


def _y(row: int) -> float:
    return Y0 - row - 0.5


@pytest.fixture()
def bdot_gpkg(tmp_path):
    """A BDOT10k hydro GeoPackage with every case of the selection."""
    path = tmp_path / "hydro.gpkg"
    for layer in ("OT_SWRS_L", "OT_SWKN_L", "OT_SWRM_L"):
        rows = [(row, attrs) for lyr, row, attrs in LINES.values() if lyr == layer]
        columns = {"IDENTYFIKATORMPHP": [a[2] for _, a in rows]}
        if layer == "OT_SWRS_L":  # the canal and ditch layers have no such columns
            columns["RODZAJ"] = [a[0] for _, a in rows]
            columns["PRZEBIEG"] = [a[1] for _, a in rows]
        geoms = [
            LineString([(X0 + 0.5, _y(row)), (X0 + NCOLS - 0.5, _y(row))])
            for row, _ in rows
        ]
        gpd.GeoDataFrame(columns, geometry=geoms, crs="EPSG:2180").to_file(
            path, layer=layer, driver="GPKG"
        )
    lake = box(X0 + 1, Y0 - 28, X0 + 4, Y0 - 25)
    gpd.GeoDataFrame({"NAZWA": ["Jezioro"]}, geometry=[lake], crs="EPSG:2180").to_file(
        path, layer="OT_PTWP_A", driver="GPKG"
    )
    return path


def _burned(gpkg, stream_burning):
    dem = np.full((30, NCOLS), 100.0)
    transform = from_origin(X0, Y0, 1.0, 1.0)
    burned, _ = burn_streams_into_dem(
        dem,
        transform,
        gpkg,
        burn_depth_m=5.0,
        nodata=NODATA,
        stream_burning=stream_burning,
    )
    lines = {name for name, (_, row, _) in LINES.items() if burned[row, 5] < 100.0}
    return lines, burned[LAKE_ROW, LAKE_COL] < 100.0


class TestStreamBurningSelection:
    def test_default_burns_every_line_and_the_lake(self, bdot_gpkg):
        default = load_config("/nonexistent/config.yaml")["dem"]["stream_burning"]
        lines, lake = _burned(bdot_gpkg, default)
        assert lines == set(LINES)
        assert lake

    def test_main_burns_rivers_mphp_streams_and_mphp_canals(self, bdot_gpkg):
        lines, lake = _burned(bdot_gpkg, "main")
        assert lines == MAIN
        assert lake

    def test_main_smooths_only_the_burned_lines(self, bdot_gpkg):
        dem = np.full((30, NCOLS), 100.0)
        transform = from_origin(X0, Y0, 1.0, 1.0)
        _, _, all_diag = smooth_streams_monotonic(
            dem, transform, bdot_gpkg, NODATA, "all"
        )
        _, _, main_diag = smooth_streams_monotonic(
            dem, transform, bdot_gpkg, NODATA, "main"
        )
        assert all_diag["segments_processed"] == len(LINES)
        assert main_diag["segments_processed"] == len(MAIN)

    def test_an_unknown_mode_is_refused(self, bdot_gpkg):
        with pytest.raises(ValueError, match="stream_burning"):
            _burned(bdot_gpkg, "rivers")


class TestTheBurnedFeatures:
    """The burned features with the attributes that orient a line (ADR-077)."""

    def test_the_attributes_come_stripped_and_blank_where_missing(self, bdot_gpkg):
        transform = from_origin(X0, Y0, 1.0, 1.0)
        features = _load_stream_features(bdot_gpkg, transform, (30, NCOLS), "all")
        assert list(features.columns) == [*STREAM_ATTRIBUTES, "geometry"]
        assert features.crs.to_epsg() == 2180
        lines = features[features.geom_type == "LineString"]
        rows = [int(Y0 - geom.coords[0][1]) for geom in lines.geometry]
        assert dict(zip(rows, lines["IDENTYFIKATORMPHP"], strict=True)) == {
            row: (attributes[2] or "").strip() for _, row, attributes in LINES.values()
        }
        # The line layers have no NAZWA or CECHAGEOMETRII; the lake has a name
        assert set(lines["NAZWA"]) == set(lines["CECHAGEOMETRII"]) == {""}
        lakes = features[features.geom_type == "Polygon"]
        assert list(lakes["NAZWA"]) == ["Jezioro"]

    def test_the_parts_of_a_multiline_keep_the_attributes_of_their_feature(
        self, tmp_path
    ):
        path = tmp_path / "multi.gpkg"
        parts = [
            LineString([(X0 + 0.5, _y(2)), (X0 + 4.5, _y(2))]),
            LineString([(X0 + 5.5, _y(2)), (X0 + 9.5, _y(2))]),
        ]
        gpd.GeoDataFrame(
            {
                "IDENTYFIKATORMPHP": [" 18852 "],
                "NAZWA": ["Kcynka "],
                "CECHAGEOMETRII": ["sztuczny łącznik"],
            },
            geometry=[MultiLineString(parts)],
            crs="EPSG:2180",
        ).to_file(path, layer="OT_SWRS_L", driver="GPKG")
        transform = from_origin(X0, Y0, 1.0, 1.0)
        features = _load_stream_features(path, transform, (30, NCOLS))
        assert [list(geom.coords) for geom in features.geometry] == [
            list(part.coords) for part in parts
        ]
        assert (
            features[list(STREAM_ATTRIBUTES)].values.tolist()
            == [["18852", "Kcynka", "sztuczny łącznik"]] * 2
        )

    def test_nothing_in_the_extent_gives_an_empty_frame(self, bdot_gpkg):
        transform = from_origin(0.0, 10.0, 1.0, 1.0)
        features = _load_stream_features(bdot_gpkg, transform, (10, 10), "all")
        assert features.empty
        assert list(features.columns) == [*STREAM_ATTRIBUTES, "geometry"]
