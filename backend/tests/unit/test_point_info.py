"""Tests for core.point_info: rasters, BDOT10k water bodies and the main channel.

The SQL queries of the module need PostGIS: tests/integration/test_identify_point_db.py.
"""

import json
import logging
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from scipy import sparse

from core.catchment_graph import CatchmentGraph
from core.point_info import (
    WATER_BODIES_FILE,
    land_cover_at,
    main_channel_at,
    sample_raster,
    water_body_at,
)

NODATA = -9999.0
X0, Y_TOP, CELL = 500000.0, 600000.0, 5.0
LON, LAT = 16.17, 51.03


def _write_raster(path, data, nodata=NODATA):
    data = np.asarray(data, dtype=np.float32)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=from_origin(X0, Y_TOP, CELL, CELL),
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)


def _centre(col, row=0):
    return X0 + CELL * (col + 0.5), Y_TOP - CELL * (row + 0.5)


class TestSampleRaster:
    @pytest.fixture
    def raster(self, tmp_path):
        path = tmp_path / "dem.tif"
        _write_raster(path, [[250.5, NODATA, np.nan, 251.25]])
        return str(path)

    def test_value_of_the_cell_under_the_point(self, raster):
        assert sample_raster(raster, *_centre(0)) == 250.5
        assert sample_raster(raster, *_centre(3)) == 251.25

    def test_nodata_and_nan_give_none(self, raster):
        assert sample_raster(raster, *_centre(1)) is None
        assert sample_raster(raster, *_centre(2)) is None

    @pytest.mark.parametrize(
        "point",
        [
            (X0 - 1.0, Y_TOP - 1.0),  # west of the raster
            (X0 + 4 * CELL, Y_TOP - 1.0),  # on the east edge (outside)
            (X0 + 1.0, Y_TOP - CELL - 0.01),  # south of the only row
            (X0 + 1.0, Y_TOP + 1.0),  # north of it
        ],
    )
    def test_point_off_the_raster_gives_none(self, raster, point):
        assert sample_raster(raster, *point) is None

    def test_raster_without_nodata_keeps_every_value(self, tmp_path):
        path = tmp_path / "slope.tif"
        _write_raster(path, [[0.0, 12.5]], nodata=None)

        assert sample_raster(str(path), *_centre(0)) == 0.0


class TestLandCoverAt:
    @pytest.mark.parametrize(
        ("category", "bdot_class", "hsg", "cns"),
        [
            ("grunt_orny", "PTTR:grunty orne", "A", (43, 63, 80)),
            ("grunt_orny", "PTTR", None, (57, 75, 88)),
            ("las", "PTLZ", "B", (35, 55, 74)),
        ],
        ids=["arable-on-A", "arable-without-soil-group-B", "forest-on-B"],
    )
    def test_cn_of_the_complex_of_the_point(self, category, bdot_class, hsg, cns):
        """TR-55 CN of the land cover on the point's soil group (B without one),
        converted to AMC I and III by Hydrolog as for the hydrograph."""
        db = MagicMock()
        db.execute.return_value.fetchone.return_value = SimpleNamespace(
            category=category, imperviousness=0.1, bdot_class=bdot_class
        )

        result = land_cover_at(db, *_centre(0), hsg)

        assert (result["cn_amc_i"], result["cn"], result["cn_amc_iii"]) == cns


def _square(lon, lat, half):
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - half, lat - half],
                [lon + half, lat - half],
                [lon + half, lat + half],
                [lon - half, lat + half],
                [lon - half, lat - half],
            ]
        ],
    }


def _feature(geometry, **properties):
    return {"type": "Feature", "geometry": geometry, "properties": properties}


def _write_water_bodies(data_dir, features):
    path = data_dir / WATER_BODIES_FILE
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )
    return path


class TestWaterBodyAt:
    @pytest.fixture
    def data_dir(self, tmp_path):
        """A named lake with an unnamed pond inside it and a river polygon apart."""
        _write_water_bodies(
            tmp_path,
            [
                _feature(
                    _square(LON, LAT, 0.01),
                    NAZWA="Jezioro Testowe",
                    RODZAJ="woda stojąca",
                    source_layer="OT_PTWP_A",
                ),
                _feature(
                    _square(LON + 0.005, LAT, 0.001),
                    NAZWA=None,
                    RODZAJ="woda stojąca",
                ),
                _feature(
                    _square(LON + 0.1, LAT, 0.002),
                    NAZWA="Kaczawa",
                    RODZAJ="woda płynąca",
                ),
            ],
        )
        return tmp_path

    def test_name_and_kind_of_the_polygon_with_the_point(self, data_dir):
        assert water_body_at(str(data_dir), LON, LAT) == {
            "name": "Jezioro Testowe",
            "kind": "woda stojąca",
        }
        assert water_body_at(str(data_dir), LON + 0.1, LAT) == {
            "name": "Kaczawa",
            "kind": "woda płynąca",
        }

    def test_smallest_polygon_wins_where_they_overlap(self, data_dir):
        assert water_body_at(str(data_dir), LON + 0.005, LAT) == {
            "name": None,
            "kind": "woda stojąca",
        }

    def test_point_outside_every_polygon_gives_none(self, data_dir):
        assert water_body_at(str(data_dir), LON + 0.05, LAT) is None

    def test_missing_file_gives_none(self, tmp_path):
        assert water_body_at(str(tmp_path), LON, LAT) is None

    def test_unreadable_file_gives_none_and_a_warning(self, tmp_path, caplog):
        (tmp_path / WATER_BODIES_FILE).write_text("{not json", encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="core.point_info"):
            assert water_body_at(str(tmp_path), LON, LAT) is None
        assert "not readable" in caplog.text

    def test_lower_case_attributes_and_blank_name(self, tmp_path):
        _write_water_bodies(
            tmp_path,
            [_feature(_square(LON, LAT, 0.01), nazwa="  ", rodzaj="woda stojąca")],
        )

        assert water_body_at(str(tmp_path), LON, LAT) == {
            "name": None,
            "kind": "woda stojąca",
        }

    def test_a_changed_file_is_read_again(self, data_dir):
        assert water_body_at(str(data_dir), LON, LAT)["name"] == "Jezioro Testowe"
        path = _write_water_bodies(
            data_dir,
            [_feature(_square(LON, LAT, 0.01), NAZWA="Zalew", RODZAJ="woda stojąca")],
        )
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

        assert water_body_at(str(data_dir), LON, LAT)["name"] == "Zalew"


def _network():
    """Graph of segments 11 to 14 at 10 000 m², nodes 0 to 3: 11 and 12 → 13 → 14.

    Segment 11 has the larger catchment, so the main channel takes it. The flow
    distances run on 2 km below the outlet of the network (segment 14), to the
    edge of the DEM, as they do in the data.
    """
    cg = CatchmentGraph()
    cg._n = 4
    cg._loaded = True
    cg._segment_idx = np.array([11, 12, 13, 14], dtype=np.int32)
    cg._threshold_m2 = np.full(4, 10000, dtype=np.int32)
    cg._lookup = {(10000, 11 + i): i for i in range(4)}
    cg._area_km2 = np.array([5.0, 2.0, 2.0, 6.0], dtype=np.float32)
    cg._upstream_area_km2 = np.array([5.0, 2.0, 9.0, 15.0])
    cg._strahler = np.array([1, 1, 2, 2], dtype=np.int8)
    cg._elev_min = np.array([300.0, 310.0, 250.0, 200.0], dtype=np.float32)
    cg._elev_max = np.array([400.0, 380.0, 320.0, 260.0], dtype=np.float32)
    cg._stream_length_km = np.array([2.0, 1.0, 3.0, 4.0], dtype=np.float32)
    cg._outlet_flow_dist_m = np.array([9000.0, 9000.0, 6000.0, 2000.0])
    cg._upstream_adj = sparse.csr_matrix(
        (np.ones(3, dtype=np.int8), ([2, 2, 3], [0, 1, 2])), shape=(4, 4)
    )
    return cg


class TestMainChannelAt:
    @pytest.mark.parametrize(
        ("segment", "channel_km", "outlet_km"),
        [(11, 2.0, 7.0), (13, 5.0, 4.0), (14, 9.0, 0.0)],
        ids=["headwater", "middle", "network-outlet"],
    )
    def test_main_channel_and_distance_to_the_network_outlet(
        self, segment, channel_km, outlet_km
    ):
        with patch("core.point_info.loaded_catchment_graph", return_value=_network()):
            result = main_channel_at(MagicMock(), 10000, segment)

        assert result == pytest.approx(
            {"channel_length_km": channel_km, "distance_to_outlet_km": outlet_km}
        )

    def test_without_flow_distances_only_the_channel(self):
        cg = _network()
        cg._outlet_flow_dist_m = None

        with patch("core.point_info.loaded_catchment_graph", return_value=cg):
            result = main_channel_at(MagicMock(), 10000, 13)

        assert result == {
            "channel_length_km": pytest.approx(5.0),
            "distance_to_outlet_km": None,
        }

    def test_nothing_without_the_graph_or_the_segment(self):
        nothing = {"channel_length_km": None, "distance_to_outlet_km": None}

        # No graph: stream_catchments is empty or the load failed
        with patch("core.point_info.loaded_catchment_graph", return_value=None):
            assert main_channel_at(MagicMock(), 10000, 13) == nothing
        # The segment is not in the graph's network of that threshold
        with patch("core.point_info.loaded_catchment_graph", return_value=_network()):
            assert main_channel_at(MagicMock(), 100000, 13) == nothing
