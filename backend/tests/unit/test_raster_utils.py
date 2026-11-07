"""Tests for utils.raster_utils: CRS normalization, mosaics and raster conversion.

The GDAL command line tools are replaced by FakeGdal, which records the command and
writes the file the tool would have written, so the tests run where only the Python
wheels are installed. Everything that rasterio can do is done for real on small
GeoTIFFs written into tmp_path.
"""

import logging
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from utils import raster_utils
from utils.raster_utils import (
    align_to_cellsize,
    convert_asc_to_geotiff,
    create_vrt_mosaic,
    get_mosaic_info,
    normalize_crs,
    read_vrt_as_array,
    resample_raster,
    validate_tiles_compatibility,
)

WEST, NORTH = 500000.0, 600030.0
NODATA = -9999.0


class FakeGdal:
    """Stands in for the `subprocess` module as seen by utils.raster_utils."""

    CalledProcessError = subprocess.CalledProcessError

    def __init__(self, *, stderr=None, missing=False, stdout=""):
        self.calls = []
        self.stderr = stderr  # not None: every command fails with this message
        self.missing = missing  # True: the tool is not installed
        self.stdout = stdout

    def run(self, cmd, **_kwargs):
        self.calls.append(list(cmd))
        if self.missing:
            raise FileNotFoundError(cmd[0])
        if self.stderr is not None:
            raise subprocess.CalledProcessError(1, cmd, stderr=self.stderr)
        output = self._output_of(cmd)
        if output is not None:
            output.write_text(f"written by {cmd[0]}")
        return subprocess.CompletedProcess(cmd, 0, stdout=self.stdout, stderr="")

    @staticmethod
    def _output_of(cmd):
        if cmd[0] in ("gdalwarp", "gdal_translate"):
            return Path(cmd[-1])
        if cmd[0] == "gdalbuildvrt":
            return next(Path(arg) for arg in cmd if arg.endswith(".vrt"))
        return None


def option(cmd, name, count=1):
    """Return the `count` values that follow the option `name` of a command."""
    at = cmd.index(name)
    values = cmd[at + 1 : at + 1 + count]
    return values[0] if count == 1 else values


def write_geotiff(
    path, data, *, west=WEST, north=NORTH, cell=10.0, crs="EPSG:2180", nodata=NODATA
):
    data = np.asarray(data, dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(west, north, cell, cell),
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)
    return path


def write_asc(path, xll, *, yll=500000.0, cellsize=1.0, xkey="xllcorner"):
    lines = [
        "ncols 2",
        "nrows 2",
        f"{xkey} {xll}",
        f"yllcorner {yll}",
        f"cellsize {cellsize}",
        "NODATA_value -9999",
        "1.0 2.0",
        "3.0 4.0",
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.fixture
def gdal(monkeypatch):
    """Working GDAL tools."""
    fake = FakeGdal()
    monkeypatch.setattr(raster_utils, "subprocess", fake)
    return fake


class TestAscHeader:
    def test_header_values_are_read_as_numbers_under_lower_case_keys(self, tmp_path):
        asc = write_asc(tmp_path / "t.asc", 6_500_000.0, yll=300000.0, cellsize=5.0)

        header = raster_utils._read_asc_header(asc)

        assert header == {
            "ncols": 2.0,
            "nrows": 2.0,
            "xllcorner": 6_500_000.0,
            "yllcorner": 300000.0,
            "cellsize": 5.0,
            "nodata_value": -9999.0,
        }

    def test_reading_stops_at_an_empty_line(self, tmp_path):
        asc = tmp_path / "short.asc"
        asc.write_text("ncols 2\nnrows 2\n\nxllcorner 1\n")

        assert raster_utils._read_asc_header(asc) == {"ncols": 2.0, "nrows": 2.0}


class TestDetectCrsFromCoords:
    @pytest.mark.parametrize(
        ("easting", "epsg"),
        [
            (5_450_000.0, "EPSG:2176"),
            (6_450_000.0, "EPSG:2177"),
            (7_450_000.0, "EPSG:2178"),
            (8_450_000.0, "EPSG:2179"),
        ],
    )
    def test_zone_prefix_of_a_puwg2000_easting_selects_the_epsg_code(
        self, easting, epsg
    ):
        assert raster_utils._detect_crs_from_coords(easting, 300000.0) == epsg

    @pytest.mark.parametrize("easting", [250_000.0, 500_000.0, 1_000_000.0])
    def test_puwg1992_eastings_need_no_reprojection(self, easting):
        assert raster_utils._detect_crs_from_coords(easting, 300000.0) is None

    def test_an_unknown_zone_is_reported_and_left_alone(self, caplog):
        with caplog.at_level(logging.WARNING, logger=raster_utils.logger.name):
            result = raster_utils._detect_crs_from_coords(9_450_000.0, 300000.0)

        assert result is None
        assert "Unknown PUWG 2000 zone" in caplog.text


class TestNormalizeCrs:
    def test_no_files_give_no_files(self, tmp_path, gdal):
        assert normalize_crs([], tmp_path / "out") == []

    def test_puwg1992_tiles_pass_through_and_nothing_is_written_beside_them(
        self, tmp_path, gdal
    ):
        store = tmp_path / "store"
        store.mkdir()
        tile = write_asc(store / "n33.asc", 500000.0)
        before = sorted(store.iterdir())

        result = normalize_crs([tile], tmp_path / "reprojected")

        assert result == [tile]
        assert sorted(store.iterdir()) == before
        assert not (tmp_path / "reprojected").exists()
        assert gdal.calls == []

    def test_files_that_do_not_exist_are_skipped(self, tmp_path, gdal):
        tile = write_asc(tmp_path / "n33.asc", 500000.0)

        assert normalize_crs([tmp_path / "gone.asc", tile], tmp_path / "out") == [tile]

    @pytest.mark.parametrize(
        ("easting", "source_crs"),
        [(5_450_000.0, "EPSG:2176"), (7_450_000.0, "EPSG:2178")],
    )
    def test_puwg2000_tile_is_warped_from_the_crs_of_its_zone(
        self, tmp_path, gdal, easting, source_crs
    ):
        store = tmp_path / "store"
        store.mkdir()
        tile = write_asc(store / "n34.asc", easting)
        target = tmp_path / "hydrograf" / "reprojected"

        result = normalize_crs([tile], target)

        out = target / "n34.asc"
        assert result == [out]
        assert out.exists()
        assert sorted(p.name for p in store.iterdir()) == ["n34.asc"]
        (cmd,) = gdal.calls
        assert cmd[0] == "gdalwarp"
        assert option(cmd, "-s_srs") == source_crs
        assert option(cmd, "-t_srs") == "EPSG:2180"
        assert option(cmd, "-of") == "AAIGrid"
        assert cmd[-2:] == [str(tile), str(out)]

    def test_native_resolution_is_kept_unless_it_is_finer_than_5_m(
        self, tmp_path, gdal
    ):
        fine = write_asc(tmp_path / "fine.asc", 6_450_000.0, cellsize=1.0)
        coarse = write_asc(tmp_path / "coarse.asc", 6_450_000.0, cellsize=10.0)

        normalize_crs([fine, coarse], tmp_path / "out")

        fine_cmd, coarse_cmd = gdal.calls
        assert option(fine_cmd, "-tr", 2) == ["5.0", "5.0"]
        assert option(coarse_cmd, "-tr", 2) == ["10.0", "10.0"]

    def test_xllcenter_headers_are_understood(self, tmp_path, gdal):
        tile = write_asc(tmp_path / "c.asc", 8_450_000.0, xkey="xllcenter")

        normalize_crs([tile], tmp_path / "out")

        assert option(gdal.calls[0], "-s_srs") == "EPSG:2179"

    def test_an_earlier_reprojection_is_reused(self, tmp_path, gdal):
        tile = write_asc(tmp_path / "n34.asc", 6_450_000.0)
        earlier = tmp_path / "out" / "n34.asc"
        earlier.parent.mkdir()
        earlier.write_text("from the previous run")

        result = normalize_crs([tile], tmp_path / "out")

        assert result == [earlier]
        assert gdal.calls == []
        assert earlier.read_text() == "from the previous run"

    def test_output_goes_to_the_requested_directory_and_order_is_kept(
        self, tmp_path, gdal
    ):
        puwg2000 = write_asc(tmp_path / "a.asc", 6_450_000.0)
        puwg1992 = write_asc(tmp_path / "b.asc", 500000.0)
        target = tmp_path / "out" / "nested"

        result = normalize_crs([puwg2000, puwg1992], output_dir=target)

        assert result == [target / "a.asc", puwg1992]
        assert (target / "a.asc").exists()

    def test_a_failing_warp_names_the_tile_and_the_tool_message(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(raster_utils, "subprocess", FakeGdal(stderr="ERROR 1: bad"))
        tile = write_asc(tmp_path / "n34.asc", 6_450_000.0)

        with pytest.raises(RuntimeError, match="Reprojection failed for n34.asc") as e:
            normalize_crs([tile], tmp_path / "out")

        assert "ERROR 1: bad" in str(e.value)


class TestCreateVrtMosaic:
    def test_no_input_files_is_an_error(self, gdal):
        with pytest.raises(ValueError, match="No input files"):
            create_vrt_mosaic([])

    def test_inputs_that_all_miss_are_an_error(self, tmp_path, gdal):
        with pytest.raises(ValueError, match="None of the input files exist"):
            create_vrt_mosaic([tmp_path / "gone.tif"])

    def test_virtual_raster_is_built_from_the_requested_inputs(self, tmp_path, gdal):
        a = write_geotiff(tmp_path / "a.tif", np.ones((3, 3)))
        b = write_geotiff(tmp_path / "b.tif", np.ones((3, 3)), west=WEST + 30)
        vrt = tmp_path / "mosaic.vrt"

        result = create_vrt_mosaic(
            [a, b], vrt, resolution="lowest", nodata=-1.0, target_crs="EPSG:2180"
        )

        assert result == vrt
        (cmd,) = gdal.calls
        assert cmd[0] == "gdalbuildvrt"
        assert option(cmd, "-resolution") == "lowest"
        assert option(cmd, "-srcnodata") == "-1.0"
        assert option(cmd, "-vrtnodata") == "-1.0"
        assert option(cmd, "-a_srs") == "EPSG:2180"
        assert "-allow_projection_difference" in cmd
        assert cmd[-3:] == [str(vrt), str(a), str(b)]

    def test_no_target_crs_leaves_the_projection_of_the_inputs(self, tmp_path, gdal):
        a = write_geotiff(tmp_path / "a.tif", np.ones((3, 3)))

        create_vrt_mosaic([a], tmp_path / "m.vrt")

        assert "-a_srs" not in gdal.calls[0]
        assert "-allow_projection_difference" not in gdal.calls[0]

    def test_missing_inputs_are_left_out_and_reported(self, tmp_path, gdal, caplog):
        a = write_geotiff(tmp_path / "a.tif", np.ones((3, 3)))
        gone = tmp_path / "gone.tif"

        with caplog.at_level(logging.WARNING, logger=raster_utils.logger.name):
            create_vrt_mosaic([a, gone], tmp_path / "m.vrt")

        assert str(a) in gdal.calls[0]
        assert str(gone) not in gdal.calls[0]
        assert "Missing files" in caplog.text

    def test_without_an_output_path_a_temporary_vrt_is_created(
        self, tmp_path, gdal, monkeypatch
    ):
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
        a = write_geotiff(tmp_path / "a.tif", np.ones((3, 3)))

        result = create_vrt_mosaic([a])

        assert result.parent == tmp_path
        assert result.name.startswith("dem_mosaic_")
        assert result.suffix == ".vrt"
        assert result.exists()

    def test_a_failing_tool_is_an_error_and_not_a_reason_to_merge(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(raster_utils, "subprocess", FakeGdal(stderr="bad input"))
        a = write_geotiff(tmp_path / "a.tif", np.ones((3, 3)))

        with pytest.raises(RuntimeError, match="Failed to create VRT: bad input"):
            create_vrt_mosaic([a], tmp_path / "m.vrt")

        assert not (tmp_path / "m.tif").exists()

    def test_without_gdal_neighbouring_tiles_are_merged_into_a_geotiff(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(raster_utils, "subprocess", FakeGdal(missing=True))
        west_tile = np.arange(1.0, 10.0).reshape(3, 3)
        east_tile = np.arange(11.0, 20.0).reshape(3, 3)
        a = write_geotiff(tmp_path / "a.tif", west_tile, crs="EPSG:2177")
        b = write_geotiff(
            tmp_path / "b.tif", east_tile, west=WEST + 30, crs="EPSG:2177"
        )

        result = create_vrt_mosaic([a, b], tmp_path / "mosaic.vrt", nodata=-1.0)

        assert result == tmp_path / "mosaic.tif"
        with rasterio.open(result) as merged:
            assert merged.crs == rasterio.crs.CRS.from_epsg(2177)
            assert merged.nodata == -1.0
            assert merged.bounds.left == WEST
            assert merged.bounds.right == WEST + 60
            assert np.array_equal(merged.read(1), np.hstack([west_tile, east_tile]))

    def test_without_gdal_grids_without_a_projection_get_the_target_crs(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(raster_utils, "subprocess", FakeGdal(missing=True))
        store = tmp_path / "store"
        store.mkdir()
        a = write_asc(store / "a.asc", 500000.0)
        b = write_asc(store / "b.asc", 500002.0)
        before = sorted(store.iterdir())
        out = tmp_path / "hydrograf"
        out.mkdir()

        result = create_vrt_mosaic(
            [a, b], out / "mosaic.vrt", nodata=NODATA, target_crs="EPSG:2180"
        )

        assert result == out / "mosaic.tif"
        assert sorted(store.iterdir()) == before
        with rasterio.open(result) as merged:
            assert merged.crs == rasterio.crs.CRS.from_epsg(2180)
            assert tuple(merged.bounds) == (500000.0, 500000.0, 500004.0, 500002.0)
            expected = np.array([[1.0, 2.0, 1.0, 2.0], [3.0, 4.0, 3.0, 4.0]])
            assert np.array_equal(merged.read(1), expected)

    def test_merged_tiles_fill_the_nodata_of_earlier_tiles(self, tmp_path, monkeypatch):
        monkeypatch.setattr(raster_utils, "subprocess", FakeGdal(missing=True))
        first = np.full((3, 3), 5.0)
        first[0, 0] = NODATA
        second = np.full((3, 3), 7.0)  # same extent as the first
        a = write_geotiff(tmp_path / "a.tif", first)
        b = write_geotiff(tmp_path / "b.tif", second)

        result = create_vrt_mosaic([a, b], tmp_path / "mosaic.vrt", nodata=NODATA)

        expected = np.full((3, 3), 5.0)
        expected[0, 0] = 7.0
        with rasterio.open(result) as merged:
            assert np.array_equal(merged.read(1), expected)


class TestReadAndDescribeMosaic:
    def test_array_comes_with_the_grid_description_of_an_ascii_grid(self, tmp_path):
        data = np.arange(12.0).reshape(3, 4)
        tif = write_geotiff(tmp_path / "m.tif", data, cell=5.0)

        array, meta = read_vrt_as_array(tif)

        assert np.array_equal(array, data)
        assert meta["xllcorner"] == WEST
        assert meta["yllcorner"] == NORTH - 3 * 5.0
        assert meta["cellsize"] == 5.0
        assert (meta["ncols"], meta["nrows"]) == (4, 3)
        assert meta["nodata_value"] == NODATA
        assert meta["crs"] == rasterio.crs.CRS.from_epsg(2180)

    def test_a_raster_without_nodata_gets_the_conventional_value(self, tmp_path):
        tif = write_geotiff(tmp_path / "m.tif", np.ones((2, 2)), nodata=None)

        _, meta = read_vrt_as_array(tif)

        assert meta["nodata"] is None
        assert meta["nodata_value"] == -9999.0

    def test_info_describes_the_mosaic_without_reading_it(self, tmp_path):
        tif = write_geotiff(tmp_path / "m.tif", np.zeros((512, 1024)), cell=2.0)

        info = get_mosaic_info(tif)

        assert (info["width"], info["height"]) == (1024, 512)
        assert info["total_cells"] == 512 * 1024
        assert info["cell_size_m"] == 2.0
        assert info["crs"] == "EPSG:2180"
        assert info["nodata"] == NODATA
        assert info["dtype"] == "float32"
        assert info["estimated_memory_mb"] == pytest.approx(2.0)  # 524,288 cells x 4 B


class TestValidateTilesCompatibility:
    def test_tiles_of_one_crs_and_cell_size_are_compatible(self, tmp_path):
        tiles = [
            write_geotiff(tmp_path / f"{i}.tif", np.ones((2, 2)), west=WEST + 20 * i)
            for i in range(3)
        ]

        result = validate_tiles_compatibility(tiles)

        assert result["valid"] is True
        assert result["issues"] == []
        assert result["summary"] == {
            "reference_crs": "EPSG:2180",
            "reference_cell_size": 10.0,
            "total_files": 3,
        }

    def test_no_files_are_not_valid(self):
        result = validate_tiles_compatibility([])

        assert result["valid"] is False
        assert result["issues"] == ["No input files provided"]

    def test_a_tile_in_another_crs_is_named(self, tmp_path):
        ok = write_geotiff(tmp_path / "ok.tif", np.ones((2, 2)))
        other = write_geotiff(tmp_path / "other.tif", np.ones((2, 2)), crs="EPSG:2177")

        result = validate_tiles_compatibility([ok, other])

        assert result["valid"] is False
        assert result["issues"] == [
            "CRS mismatch: other.tif has EPSG:2177, expected EPSG:2180"
        ]

    def test_a_tile_with_another_cell_size_is_named(self, tmp_path):
        ok = write_geotiff(tmp_path / "ok.tif", np.ones((2, 2)), cell=5.0)
        coarse = write_geotiff(tmp_path / "coarse.tif", np.ones((2, 2)), cell=10.0)

        result = validate_tiles_compatibility([ok, coarse])

        assert result["valid"] is False
        assert result["issues"] == [
            "Cell size mismatch: coarse.tif has 10.0, expected 5.0"
        ]

    def test_missing_and_unreadable_files_are_reported(self, tmp_path):
        ok = write_geotiff(tmp_path / "ok.tif", np.ones((2, 2)))
        broken = tmp_path / "broken.tif"
        broken.write_text("this is not a raster")
        gone = tmp_path / "gone.tif"

        result = validate_tiles_compatibility([ok, broken, gone])

        assert any(i.startswith(f"File not found: {gone}") for i in result["issues"])
        assert any(i.startswith(f"Cannot read {broken}") for i in result["issues"])
        assert result["summary"]["total_files"] == 1

    def test_when_no_file_can_be_read_the_set_is_not_valid(self, tmp_path):
        result = validate_tiles_compatibility([tmp_path / "gone.tif"])

        assert result["valid"] is False
        assert result["issues"][-1] == "No readable files found"


class TestResampleRaster:
    def test_nearest_upsampling_repeats_every_cell_and_keeps_the_extent(self, tmp_path):
        data = np.arange(16.0).reshape(4, 4)
        src = write_geotiff(tmp_path / "in.tif", data, north=NORTH + 10, cell=10.0)

        out = resample_raster(src, tmp_path / "out.tif", 5.0, method="nearest")

        assert out == tmp_path / "out.tif"
        with rasterio.open(src) as before, rasterio.open(out) as after:
            assert (after.width, after.height) == (8, 8)
            assert after.bounds == before.bounds
            assert after.crs == before.crs
            assert after.transform.a == 5.0
            assert np.array_equal(after.read(1), np.kron(data, np.ones((2, 2))))

    def test_average_downsampling_gives_the_mean_of_each_block(self, tmp_path):
        data = np.arange(16.0).reshape(4, 4)
        src = write_geotiff(tmp_path / "in.tif", data, north=NORTH + 10, cell=10.0)

        out = resample_raster(src, tmp_path / "out.tif", 20.0, method="average")

        with rasterio.open(out) as after:
            assert (after.width, after.height) == (2, 2)
            assert np.array_equal(
                after.read(1), data.reshape(2, 2, 2, 2).mean(axis=(1, 3))
            )

    def test_a_flat_surface_stays_flat_whatever_the_method(self, tmp_path):
        src = write_geotiff(tmp_path / "in.tif", np.full((4, 4), 123.0))

        for method in ("nearest", "bilinear", "cubic", "average"):
            out = resample_raster(src, tmp_path / f"{method}.tif", 5.0, method=method)
            with rasterio.open(out) as after:
                assert np.allclose(after.read(1), 123.0)

    def test_an_unknown_method_resamples_bilinearly(self, tmp_path):
        data = np.arange(16.0).reshape(4, 4)
        src = write_geotiff(tmp_path / "in.tif", data)

        guessed = resample_raster(src, tmp_path / "x.tif", 5.0, method="lanczos")
        bilinear = resample_raster(src, tmp_path / "y.tif", 5.0, method="bilinear")

        with rasterio.open(guessed) as x, rasterio.open(bilinear) as y:
            assert np.array_equal(x.read(1), y.read(1))


class TestConvertAscToGeotiff:
    def test_output_defaults_to_a_tif_beside_the_input(self, tmp_path, gdal):
        asc = write_asc(tmp_path / "dem.asc", 500000.0)

        result = convert_asc_to_geotiff(asc)

        assert result == tmp_path / "dem.tif"
        assert result.exists()
        (cmd,) = gdal.calls
        assert cmd[0] == "gdal_translate"
        assert option(cmd, "-of") == "GTiff"
        assert cmd[-2:] == [str(asc), str(result)]

    def test_compression_is_selectable_and_tiling_is_on(self, tmp_path, gdal):
        asc = write_asc(tmp_path / "dem.asc", 500000.0)

        convert_asc_to_geotiff(asc, tmp_path / "out.tif", compress="DEFLATE")

        cmd = gdal.calls[0]
        assert "COMPRESS=DEFLATE" in cmd
        assert "TILED=YES" in cmd

    def test_a_failing_conversion_carries_the_tool_message(self, tmp_path, monkeypatch):
        monkeypatch.setattr(raster_utils, "subprocess", FakeGdal(stderr="no driver"))
        asc = write_asc(tmp_path / "dem.asc", 500000.0)

        with pytest.raises(RuntimeError, match="gdal_translate failed: no driver"):
            convert_asc_to_geotiff(asc)


class TestAlignToCellsize:
    """A 5 m set with 1 m sheets gets a 5 m mosaic on the grid of its 5 m sheets."""

    def test_a_finer_sheet_is_averaged_onto_the_grid_of_the_others(
        self, tmp_path, gdal
    ):
        coarse = write_asc(tmp_path / "a.asc", 500002.5, yll=600002.5, cellsize=5.0)
        fine = write_asc(tmp_path / "b.asc", 500013.0, yll=600001.0, cellsize=1.0)
        out = tmp_path / "aligned"

        files = align_to_cellsize([coarse, fine], out, 5.0)

        assert files == [coarse, out / "b_5m.asc"]
        assert files[1].read_text() == "written by gdalwarp"
        (cmd,) = gdal.calls
        assert option(cmd, "-r") == "average"
        assert option(cmd, "-tr", 2) == ["5.0", "5.0"]
        assert option(cmd, "-of") == "AAIGrid"
        # The frame of the 1 m sheet grows outward to whole cells of the 5 m sheets,
        # whose corners lie 2.5 m off the multiples of 5 m
        assert option(cmd, "-te", 4) == [
            "500012.5",
            "599997.5",
            "500017.5",
            "600007.5",
        ]
        assert cmd[-2] == str(fine)
        # No partial file is left behind
        assert sorted(path.name for path in out.iterdir()) == ["b_5m.asc"]

    def test_an_averaged_sheet_is_used_again(self, tmp_path, gdal):
        coarse = write_asc(tmp_path / "a.asc", 500002.5, yll=600002.5, cellsize=5.0)
        fine = write_asc(tmp_path / "b.asc", 500013.0, yll=600001.0, cellsize=1.0)

        first = align_to_cellsize([coarse, fine], tmp_path / "aligned", 5.0)
        again = align_to_cellsize([coarse, fine], tmp_path / "aligned", 5.0)

        assert again == first
        assert len(gdal.calls) == 1

    def test_sheets_of_the_cell_size_alone_are_kept_as_they_are(self, tmp_path, gdal):
        sheets = [
            write_asc(tmp_path / "a.asc", 500002.5, yll=600002.5, cellsize=5.0),
            # A header with the centre of the corner cell (xllcenter) on the grid
            write_asc(
                tmp_path / "b.asc",
                500015.0,
                yll=600012.5,
                cellsize=5.0,
                xkey="xllcenter",
            ),
        ]

        assert align_to_cellsize(sheets, tmp_path / "aligned", 5.0) == sheets
        assert gdal.calls == []
        assert not (tmp_path / "aligned").exists()

    def test_sheets_of_the_cell_size_on_two_grids_are_refused(self, tmp_path, gdal):
        sheets = [
            write_asc(tmp_path / "a.asc", 500002.5, yll=600002.5, cellsize=5.0),
            write_asc(tmp_path / "b.asc", 500010.0, yll=600002.5, cellsize=5.0),
        ]

        with pytest.raises(ValueError, match="2 different grids"):
            align_to_cellsize(sheets, tmp_path / "aligned", 5.0)

    def test_a_coarser_sheet_is_refused(self, tmp_path, gdal):
        sheet = write_asc(tmp_path / "a.asc", 500000.0, cellsize=10.0)

        with pytest.raises(ValueError, match="coarser than the 5 m"):
            align_to_cellsize([sheet], tmp_path / "aligned", 5.0)
