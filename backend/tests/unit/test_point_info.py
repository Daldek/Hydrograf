"""Tests for core.point_info: rasters and BDOT10k water bodies at one point.

The SQL queries of the module need PostGIS: tests/integration/test_identify_point_db.py.
"""

import json
import logging
import os

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from core.point_info import WATER_BODIES_FILE, sample_raster, water_body_at

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
