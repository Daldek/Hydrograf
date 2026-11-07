"""Owned-cell tiles of PGW units must mosaic back into the whole-grid rasters."""

import subprocess

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window

from core import unit_rasters
from core.unit_rasters import write_unit_mosaics

NODATA = -9999.0
CELL = 5.0
TRANSFORM = from_origin(500000.0, 600000.0, CELL, CELL)
CODES = ("PLRW0001", "PLRW0002", "PLRW0003", "PLRW0004")  # the 4th owns no cell


def _write_dem(path, dem):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=dem.shape[0],
        width=dem.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=TRANSFORM,
        nodata=NODATA,
    ) as dst:
        dst.write(dem, 1)


def _disk_array(path, values):
    array = np.lib.format.open_memmap(
        path, mode="w+", dtype=values.dtype, shape=values.shape
    )
    array[:] = values
    return array


def _scene(tmp_path, shape=(48, 60), owner_on_nodata=False):
    """Three jagged owners with overlapping boxes, a nodata gap on their seams.

    Every raster holds arbitrary positive values on the cells nobody owns (the
    gap, and the cells of the other owners inside a box), which would leak into a
    neighbour wherever a tile or the VRT fails to mask them, and legitimate zeros
    on owned cells, which nodata of the raster must not be mistaken for.
    """
    rows, cols = np.indices(shape)
    dem = (100 + 0.5 * rows + 0.25 * cols).astype("float32")
    dem[18:23, 38:48] = NODATA
    dem[:, -2:] = NODATA
    valid = dem != NODATA
    owners = np.ones(shape, np.uint8)
    owners[rows + cols // 2 > 40] = 2
    owners[(rows - 10) ** 2 + (cols - 45) ** 2 < 150] = 3
    if not owner_on_nodata:
        owners[~valid] = 0
    rng = np.random.default_rng(7)
    d8 = np.array([0, 1, 2, 4, 8, 16, 32, 64, 128])
    distance = rng.uniform(1.0, 500.0, shape).astype("float32")
    distance[rng.random(shape) < 0.1] = 0.0
    values = {
        "02_filled": (np.where(valid, dem + 1.5, 123.0).astype("float32"), NODATA),
        "03_flowdir": (rng.choice(d8, size=shape).astype("int16"), 0),
        "04_flowacc": (
            (16_777_217 + rng.integers(0, 5000, shape)).astype("int32"),
            0,
        ),
        "04b_stream_distance": (distance, -1),
        "07_stream_order": (rng.integers(0, 4, shape).astype("uint8"), 0),
        "10_subcatchments_1000000": (rng.integers(0, 6, shape).astype("int32"), 0),
    }
    values["04_flowacc"][0][0, 0] = 2**31 - 1
    dem_path = tmp_path / "dem.tif"
    _write_dem(dem_path, dem)
    rasters = {"01_dem": (dem_path, NODATA)}
    rasters.update(
        {
            suffix: (_disk_array(tmp_path / f"{suffix}.npy", array), nodata)
            for suffix, (array, nodata) in values.items()
        }
    )
    expected = {"01_dem": dem}
    expected.update({suffix: array for suffix, (array, _) in values.items()})
    return dem_path, owners, rasters, expected


def _owned_cells(owners, dem_path):
    with rasterio.open(dem_path) as dem:
        return (owners > 0) & (dem.read(1) != NODATA)


def _tile_cut(tile, dem):
    """Return the window of the DEM grid a tile covers; it must lie on the grid."""
    col = (tile.transform.c - dem.transform.c) / CELL
    row = (dem.transform.f - tile.transform.f) / CELL
    assert col == round(col) and row == round(row), "tile is off the pixel grid"
    assert (tile.transform.a, tile.transform.e) == (CELL, -CELL)
    window = Window(round(col), round(row), tile.width, tile.height)
    assert window.col_off >= 0 and window.col_off + window.width <= dem.width
    assert window.row_off >= 0 and window.row_off + window.height <= dem.height
    return window


def _run(tmp_path, scene, **kwargs):
    dem_path, owners, rasters, _ = scene
    return write_unit_mosaics(
        dem_path, owners, CODES, rasters, tmp_path / "run", "dem", **kwargs
    )


@pytest.mark.parametrize("owner_on_nodata", [False, True])
def test_vrt_of_every_raster_type_equals_the_whole_grid_array(
    tmp_path, owner_on_nodata
):
    dem_path, owners, rasters, expected = _scene(
        tmp_path, owner_on_nodata=owner_on_nodata
    )
    boxes = [
        (rows.min(), rows.max(), cols.min(), cols.max())
        for rows, cols in (np.nonzero(owners == k) for k in (1, 2, 3))
    ]
    for first in range(3):  # the premise: every pair of boxes overlaps
        for second in range(first + 1, 3):
            a, b = boxes[first], boxes[second]
            assert a[0] <= b[1] and b[0] <= a[1] and a[2] <= b[3] and b[2] <= a[3]
    assert np.any(expected["03_flowdir"][owners > 0] == 0)

    vrts, _ = _run(tmp_path, (dem_path, owners, rasters, expected))

    ours = _owned_cells(owners, dem_path)
    assert not ours.all(), "the DEM has a nodata gap"
    assert set(vrts) == set(rasters)
    with rasterio.open(dem_path) as dem:
        for suffix, (_, nodata) in rasters.items():
            assert vrts[suffix] == tmp_path / "run" / f"dem_{suffix}.vrt"
            with rasterio.open(vrts[suffix]) as vrt:
                assert vrt.crs.to_epsg() == 2180
                assert vrt.shape == dem.shape
                assert vrt.transform == dem.transform
                assert vrt.dtypes[0] == expected[suffix].dtype.name
                assert vrt.nodata == nodata
                np.testing.assert_array_equal(
                    vrt.read(1), np.where(ours, expected[suffix], nodata), suffix
                )
                # A window that crosses several seams reads the same cells.
                window = Window(30, 5, 28, 30)
                np.testing.assert_array_equal(
                    vrt.read(1, window=window),
                    np.where(ours, expected[suffix], nodata)[5:35, 30:58],
                )
    # The DEM's own nodata stays nodata in the copy of the DEM.
    with rasterio.open(vrts["01_dem"]) as vrt, rasterio.open(dem_path) as dem:
        np.testing.assert_array_equal(vrt.read(1), dem.read(1))


def test_tiles_hold_every_valid_cell_once_with_the_owner_values_only(tmp_path):
    scene = _scene(tmp_path)
    dem_path, owners, rasters, expected = scene
    _, tiles = _run(tmp_path, scene)

    ours = _owned_cells(owners, dem_path)
    assert set(tiles) == {1, 2, 3}  # PLRW0004 owns no cell: no tile
    with rasterio.open(dem_path) as dem:
        for suffix, (_, nodata) in rasters.items():
            held = np.zeros(dem.shape, dtype=int)
            for owner, files in tiles.items():
                assert set(files) == set(rasters)
                path = files[suffix]
                assert path.parent == tmp_path / "run" / "units"
                assert CODES[owner - 1] in path.name
                with rasterio.open(path) as tile:
                    assert tile.crs.to_epsg() == 2180
                    assert tile.profile["tiled"]
                    assert tile.nodata == nodata
                    window = _tile_cut(tile, dem)
                    rows, cols = window.toslices()
                    mine = (owners == owner) & ours
                    # The tile is the box of the owner's cells: no halo, no excess.
                    box_rows, box_cols = np.nonzero(mine)
                    assert (rows.start, rows.stop) == (
                        box_rows.min(),
                        box_rows.max() + 1,
                    )
                    assert (cols.start, cols.stop) == (
                        box_cols.min(),
                        box_cols.max() + 1,
                    )
                    # Its mask holds the owner's cells, also where the value is 0.
                    np.testing.assert_array_equal(
                        tile.read_masks(1) > 0, mine[rows, cols]
                    )
                    np.testing.assert_array_equal(
                        tile.read(1),
                        np.where(
                            mine[rows, cols], expected[suffix][rows, cols], nodata
                        ),
                    )
                    held[rows, cols] += tile.read_masks(1) > 0
            np.testing.assert_array_equal(held, ours.astype(int), suffix)


def test_tiles_are_named_by_owner_code_and_the_result_is_stable(tmp_path):
    scene = _scene(tmp_path)
    vrts, tiles = _run(tmp_path, scene)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.vrt")}
    again_vrts, again_tiles = _run(tmp_path, scene)

    assert (vrts, tiles) == (again_vrts, again_tiles)
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*.vrt")}
    assert sorted(p.name for p in (tmp_path / "run").iterdir()) == sorted(
        [f"dem_{suffix}.vrt" for suffix in scene[2]] + ["units"]
    )
    for owner, files in tiles.items():
        assert all(path.exists() for path in files.values())
        assert {path.name for path in files.values()} == {
            f"dem_{suffix}_{CODES[owner - 1]}.tif" for suffix in scene[2]
        }


def test_tiles_with_empty_blocks_and_many_windows_read_back_whole(
    tmp_path, monkeypatch
):
    """An owner whose box has blocks without a cell of it, in many windows."""
    shape = (600, 700)
    rows, cols = np.indices(shape)
    dem = (50 + 0.1 * rows + 0.05 * cols).astype("float32")
    dem[300:330, 100:600] = NODATA
    owners = np.full(shape, 2, np.uint8)
    owners[(rows < 120) | (cols < 120)] = 1  # an L: its box is the whole grid
    owners[dem == NODATA] = 0
    rng = np.random.default_rng(3)
    dem_path = tmp_path / "dem.tif"
    _write_dem(dem_path, dem)
    filled = np.where(dem != NODATA, dem + 1, 77.0).astype("float32")
    labels = rng.integers(0, 9, shape).astype("int32")
    rasters = {
        "02_filled": (_disk_array(tmp_path / "filled.npy", filled), NODATA),
        "10_subcatchments_1000000": (_disk_array(tmp_path / "labels.npy", labels), 0),
    }
    # One block per window, so every window edge and every skipped block is hit.
    monkeypatch.setattr(unit_rasters, "_WINDOW_CELLS", 256 * 256)
    monkeypatch.setattr(unit_rasters, "_MAX_WINDOW_COLS", 256)

    vrts, tiles = write_unit_mosaics(
        dem_path, owners, CODES[:2], rasters, tmp_path / "run", "dem"
    )

    ours = owners > 0
    with rasterio.open(tiles[1]["02_filled"]) as tile:
        assert (tile.height, tile.width) == shape
        assert tile.read_masks(1)[400:, 400:].max() == 0  # empty blocks are invalid
    for suffix, array, nodata in (
        ("02_filled", filled, NODATA),
        ("10_subcatchments_1000000", labels, 0),
    ):
        with rasterio.open(vrts[suffix]) as vrt:
            np.testing.assert_array_equal(vrt.read(1), np.where(ours, array, nodata))


@pytest.mark.parametrize(
    ("dtype", "nodata", "low", "high"),
    [
        ("uint8", 255, 0, 254),
        ("int16", -32768, -32767, 32767),
        ("uint16", 65535, 0, 65534),
        ("int32", -(2**31), 2**31 - 1, 16_777_217),
        ("float32", np.finfo("float32").min, 0.0, np.finfo("float32").max),
        ("float32", -9999.1, 0.1, 1e-30),
        ("float64", np.nan, 0.1, 1e300),
    ],
)
def test_every_supported_type_reads_back_exactly(tmp_path, dtype, nodata, low, high):
    shape = (40, 50)
    rows, cols = np.indices(shape)
    dem = np.full(shape, 10.0, dtype="float32")
    dem[:, 25] = NODATA
    owners = np.where(cols < 20 + rows % 7, 1, 2).astype(np.uint8)
    owners[dem == NODATA] = 0
    pattern = (rows * 7 + cols) % 3
    array = np.select([pattern == 0, pattern == 1], [low, high], default=high)
    array = array.astype(dtype)
    dem_path = tmp_path / "dem.tif"
    _write_dem(dem_path, dem)

    vrts, _ = write_unit_mosaics(
        dem_path, owners, CODES[:2], {"x": (array, nodata)}, tmp_path / "run", "dem"
    )

    with rasterio.open(vrts["x"]) as vrt:
        assert vrt.dtypes[0] == dtype
        np.testing.assert_array_equal(
            vrt.read(1), np.where(owners > 0, array, np.asarray(nodata, dtype))
        )
        stated = vrt.nodata
        assert (np.isnan(stated) and np.isnan(nodata)) or np.asarray(
            stated, dtype
        ) == np.asarray(nodata, dtype)


def _fails(tmp_path, scene, match, **kwargs):
    with pytest.raises(ValueError, match=match):
        _run(tmp_path, scene, **kwargs)
    assert not (tmp_path / "run").exists(), "a rejected run creates nothing"


def test_a_valid_cell_without_an_owner_is_rejected(tmp_path):
    dem_path, owners, rasters, expected = _scene(tmp_path)
    owners[30, 10] = 0
    _fails(tmp_path, (dem_path, owners, rasters, expected), "no owner .*row 30, col")


def test_an_owner_without_a_code_is_rejected(tmp_path):
    dem_path, owners, rasters, expected = _scene(tmp_path)
    owners[30, 10] = 5
    _fails(tmp_path, (dem_path, owners, rasters, expected), "outside 1..4")


def test_owners_off_the_dem_grid_are_rejected(tmp_path):
    dem_path, owners, rasters, expected = _scene(tmp_path)
    _fails(tmp_path, (dem_path, owners[:-1], rasters, expected), "integer array on the")
    _fails(
        tmp_path,
        (dem_path, owners.astype("float32"), rasters, expected),
        "integer array on the",
    )


def test_a_raster_off_the_dem_grid_is_rejected(tmp_path):
    dem_path, owners, rasters, expected = _scene(tmp_path)
    short = _disk_array(tmp_path / "short.npy", np.zeros((47, 60), "int16"))
    _fails(
        tmp_path,
        (dem_path, owners, {**rasters, "03_flowdir": (short, 0)}, expected),
        "03_flowdir.*47",
    )
    shifted = tmp_path / "shifted.tif"
    with rasterio.open(dem_path) as dem:
        profile = dem.profile
    profile["transform"] = from_origin(500000.0 + CELL, 600000.0, CELL, CELL)
    with rasterio.open(shifted, "w", **profile) as dst:
        dst.write(np.full((48, 60), 1, "float32"), 1)
    _fails(
        tmp_path,
        (dem_path, owners, {**rasters, "01_dem": (shifted, NODATA)}, expected),
        "not on the pixel grid",
    )


@pytest.mark.parametrize(
    ("dtype", "nodata"),
    [
        ("uint8", -1),
        ("int16", 0.5),
        ("int32", np.nan),
        ("float32", 1e300),
        ("bool", 0),
        # GDAL's ComplexSource would round values near 2**32 up to the nodata value.
        ("uint32", 0),
    ],
)
def test_a_type_or_nodata_value_the_tiles_cannot_carry_is_rejected(
    tmp_path, dtype, nodata
):
    dem_path, owners, rasters, expected = _scene(tmp_path)
    bad = {"bad": (np.zeros((48, 60), dtype), nodata)}
    _fails(tmp_path, (dem_path, owners, bad, expected), "bad")


@pytest.mark.parametrize("base_name", ["", "..", "a/b"])
def test_a_base_name_that_is_not_a_file_name_is_rejected(tmp_path, base_name):
    dem_path, owners, rasters, _ = _scene(tmp_path)
    with pytest.raises(ValueError, match="plain file name"):
        write_unit_mosaics(
            dem_path, owners, CODES, rasters, tmp_path / "run", base_name
        )


@pytest.mark.parametrize(
    "codes", [("a/b", "c", "d", "e"), ("A", "a", "c", "d"), ("..", "b", "c", "d")]
)
def test_owner_codes_that_cannot_name_files_are_rejected(tmp_path, codes):
    dem_path, owners, rasters, _ = _scene(tmp_path)
    with pytest.raises(ValueError, match="plain file name|unique"):
        write_unit_mosaics(dem_path, owners, codes, rasters, tmp_path / "run", "dem")
    assert not (tmp_path / "run").exists()


def test_a_failed_run_leaves_earlier_files_as_they_were(tmp_path):
    scene = _scene(tmp_path)
    _run(tmp_path, scene)
    run = tmp_path / "run"
    before = {path: path.read_bytes() for path in run.rglob("*") if path.is_file()}
    dem_path, owners, rasters, expected = scene
    owners[30, 10] = 0

    with pytest.raises(ValueError, match="no owner"):
        _run(tmp_path, (dem_path, owners, rasters, expected))

    assert before == {
        path: path.read_bytes() for path in run.rglob("*") if path.is_file()
    }
    assert [p.name for p in run.iterdir() if p.name.startswith(".")] == []


def test_a_vrt_that_overwrites_neighbours_is_not_published(tmp_path, monkeypatch):
    """Nodata cells of a later tile over an earlier owner's cells must be caught."""
    scene = _scene(tmp_path)
    real_write_vrt = unit_rasters._write_vrt

    def overwriting(path, grid, raster, tiles):
        real_write_vrt(path, grid, raster, tiles)
        path.write_text(path.read_text().replace("ComplexSource", "SimpleSource"))

    monkeypatch.setattr(unit_rasters, "_write_vrt", overwriting)

    _fails(tmp_path, scene, "differs from its raster")


def test_no_external_gdal_program_is_needed_and_no_full_raster_is_merged(
    tmp_path, monkeypatch
):
    def missing(*args, **kwargs):
        raise FileNotFoundError("gdalbuildvrt not found")

    monkeypatch.setattr(subprocess, "run", missing)
    monkeypatch.setattr(subprocess, "Popen", missing)
    scene = _scene(tmp_path)

    vrts, _ = _run(tmp_path, scene)

    assert list((tmp_path / "run").glob("*.tif")) == []
    with rasterio.open(vrts["02_filled"]) as vrt:
        assert vrt.shape == (48, 60)
