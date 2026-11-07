"""The overlays and the DEM tile colours read in strips equal those of the whole raster.

The strips are made short by patching ``strip_rows`` of each script, so a raster of a
few dozen rows is read in many strips with their halos.
"""

import json

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_origin

from scripts import generate_dem_overlay, generate_dem_tiles, generate_streams_overlay
from utils.dem_color import (
    colorize_elevation,
    compute_hillshade,
    summarize_elevation,
    valid_elevation,
)

NODATA = -9999.0
TRANSFORM = from_origin(500000.0, 600000.0, 5.0, 5.0)


def _write(path, data, nodata):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        crs="EPSG:2180",
        transform=TRANSFORM,
        nodata=nodata,
    ) as dst:
        dst.write(data, 1)
    return str(path)


def _dem(shape=(45, 38)):
    rows, cols = np.indices(shape)
    dem = 80 + 12 * np.sin(rows / 4) + 6 * np.cos(cols / 5) + 0.3 * rows
    dem[17:21, 9:14] = NODATA
    dem[:, -3:] = NODATA
    return dem.astype("float32")


def _png(path):
    return np.asarray(Image.open(path))


def _stream_orders(shape=(50, 41)):
    orders = np.zeros(shape, dtype="uint8")
    orders[3:47, 7] = 1
    orders[20, 7:35] = 2
    orders[20:44, 30] = 3
    orders[44, 12:31] = 1
    # Three rows above a strip of 4 rows: its widening needs a halo of 3 rows.
    orders[9, 15:26] = 3
    return orders


def test_streams_overlay_of_strips_equals_the_whole_raster(tmp_path, monkeypatch):
    path = _write(tmp_path / "orders.tif", _stream_orders(), 0)
    outputs = {}
    for name, rows in (("strips", 4), ("whole", 10_000)):
        monkeypatch.setattr(
            generate_streams_overlay, "strip_rows", lambda width, rows=rows: rows
        )
        png, meta = tmp_path / f"{name}.png", tmp_path / f"{name}.json"
        generate_streams_overlay.generate_overlay(path, str(png), str(meta), 0)
        outputs[name] = (_png(png), json.loads(meta.read_text()))

    np.testing.assert_array_equal(outputs["strips"][0], outputs["whole"][0])
    assert outputs["strips"][1] == outputs["whole"][1]
    assert outputs["whole"][1]["max_order"] == 3


def test_streams_overlay_keeps_a_thin_line_when_shrinking(tmp_path):
    orders = np.zeros((400, 400), dtype="uint8")
    orders[200, :] = 1
    path = _write(tmp_path / "orders.tif", orders, 0)
    png, meta = tmp_path / "streams.png", tmp_path / "streams.json"

    generate_streams_overlay.generate_overlay(path, str(png), str(meta), 40)

    alpha = _png(png)[..., 3]
    assert max(alpha.shape) == 40
    # Every column the line crosses has a visible pixel (inside the skew of the
    # reprojection, which shifts the ends of the line).
    width = alpha.shape[1]
    assert (alpha[:, width // 10 : width - width // 10] > 0).any(axis=0).all()


def test_dem_overlay_of_strips_equals_the_whole_raster(tmp_path, monkeypatch):
    path = _write(tmp_path / "dem.tif", _dem(), NODATA)
    outputs = {}
    for name, rows in (("strips", 4), ("whole", 10_000)):
        monkeypatch.setattr(
            generate_dem_overlay, "strip_rows", lambda width, rows=rows: rows
        )
        png, meta = tmp_path / f"{name}.png", tmp_path / f"{name}.json"
        generate_dem_overlay.generate_overlay(path, str(png), str(meta), 0)
        outputs[name] = (_png(png), json.loads(meta.read_text()))

    np.testing.assert_array_equal(outputs["strips"][0], outputs["whole"][0])
    strips_meta, whole_meta = outputs["strips"][1], outputs["whole"][1]
    strips_meta.pop("generated_at")
    whole_meta.pop("generated_at")
    assert strips_meta == whole_meta


def test_dem_tile_colours_of_strips_equal_the_whole_raster(tmp_path, monkeypatch):
    dem = _dem()
    path = _write(tmp_path / "dem.tif", dem, NODATA)
    monkeypatch.setattr(generate_dem_tiles, "BLOCK_PX", 16)
    monkeypatch.setattr(generate_dem_tiles, "strip_rows", lambda width: 1)
    colored = tmp_path / "colored.tif"

    with rasterio.open(path) as src:
        summary = summarize_elevation(src)
        generate_dem_tiles._write_colored(src, src.crs, colored, summary, True)

    valid = valid_elevation(dem, NODATA)
    whole = dem.astype(np.float64)
    whole[~valid] = np.nan
    hillshade = compute_hillshade(whole, 5.0)
    hillshade[~np.isfinite(hillshade)] = 0.0
    expected = colorize_elevation(
        dem, valid, summary.color_min_m, summary.color_max_m, hillshade
    )
    with rasterio.open(colored) as written:
        assert written.colorinterp[3] == rasterio.enums.ColorInterp.alpha
        np.testing.assert_array_equal(np.moveaxis(written.read(), 0, 2), expected)
