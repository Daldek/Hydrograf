"""Depressions computed tile by tile must equal those of the whole rasters.

The reference is the whole-array computation that generate_depressions.py did before
it read tiles: ``scipy.ndimage.label`` of all depression cells, bincount statistics and
``rasterio.features.shapes`` of the labels. Depths are multiples of 1/16 m, so sums
are exact in any order and the comparison can be exact.
"""

import json
from collections import Counter

import numpy as np
import pytest
import rasterio
import shapely
from PIL import Image
from rasterio.features import shapes
from rasterio.transform import Affine, from_origin
from scipy.ndimage import label, maximum
from shapely.geometry import shape

from scripts.generate_depressions import (
    build_depth_colormap,
    compute_depressions,
    generate_overlay,
)

NODATA = -9999.0
CELL = 5.0
TRANSFORM = from_origin(500000.0, 600000.0, CELL, CELL)


def _write(path, data):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=TRANSFORM,
        nodata=NODATA,
    ) as dst:
        dst.write(data.astype("float32"), 1)
    return str(path)


def _rasters(tmp_path, depth, dem_nodata=(), filled_nodata=()):
    """DEM and filled DEM whose difference is ``depth``, with nodata cells."""
    rows, cols = np.indices(depth.shape)
    dem = 100.0 + 0.25 * (rows + cols)
    filled = dem + depth
    for cell in dem_nodata:
        dem[cell] = NODATA
    for cell in filled_nodata:
        filled[cell] = NODATA
    return _write(tmp_path / "dem.tif", dem), _write(tmp_path / "filled.tif", filled)


def _whole_array_depth(dem_path, filled_path, min_depth_m=0.001):
    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(np.float64)
    with rasterio.open(filled_path) as src:
        filled = src.read(1).astype(np.float64)
    depth = filled - dem
    depth[dem == NODATA] = 0
    depth[filled == NODATA] = 0
    depth[depth < min_depth_m] = 0
    return depth


def _whole_array(dem_path, filled_path):
    """The depressions as the whole-array implementation computed them."""
    depth = _whole_array_depth(dem_path, filled_path)
    labels, n = label(depth > 0)
    counts = np.bincount(labels.ravel(), minlength=n + 1)
    sums = np.bincount(labels.ravel(), weights=depth.ravel(), minlength=n + 1)
    maxima = maximum(depth, labels, index=np.arange(1, n + 1))
    rows = []
    for geom, value in shapes(labels.astype(np.int32), transform=TRANSFORM):
        if value == 0:
            continue
        k = int(value)
        area = counts[k] * CELL * CELL
        volume = float(sums[k]) * CELL * CELL
        rows.append(
            {
                "wkt": shape(geom).wkt,
                "volume_m3": round(volume, 4),
                "area_m2": round(area, 4),
                "max_depth_m": round(float(maxima[k - 1]), 4),
                "mean_depth_m": round(volume / area, 4),
            }
        )
    return rows


def _as_set(rows):
    """Depressions as a multiset of (normalized geometry, statistics)."""
    return Counter(
        (
            shapely.normalize(shapely.from_wkt(row["wkt"])).wkb,
            row["area_m2"],
            row["volume_m3"],
            row["max_depth_m"],
            row["mean_depth_m"],
        )
        for row in rows
    )


def _seam_scene():
    """Depressions on a 32 x 40 grid laid out against the seams of 8-cell tiles.

    Seams of 8-cell tiles lie between rows 7/8, 15/16, 23/24 and columns 7/8,
    15/16, 23/24, 31/32.
    """
    d = np.zeros((32, 40))
    d[2, 5:12] = 0.5  # crosses a vertical seam
    d[5:13, 3] = 0.75  # crosses a horizontal seam
    d[14:18, 15:17] = 1.25  # a cross over the corner of four tiles
    d[15:17, 14:18] = 1.25
    d[7, 20], d[8, 21] = 0.25, 0.375  # diagonal neighbours across a seam
    d[23, 31], d[24, 32] = 0.5, 0.625  # diagonal neighbours across a corner
    d[10, 23], d[11, 24] = 0.875, 0.875  # diagonal across a vertical seam
    d[18:29, 6] = 0.5  # a U: two branches in two tiles of one band ...
    d[18:29, 10] = 0.5625
    d[28, 6:11] = 0.625  # ... that meet in the band below
    d[2, 30:35] = d[6, 30:35] = 1.5  # a ring with its hole across a seam
    d[2:7, 30] = d[2:7, 34] = 1.5
    d[30, 12:40] = 0.125  # crosses three seams and ends on the raster edge
    d[20, 26:31] = 1.0  # split by a nodata cell of the DEM
    d[12, 29:32] = 0.5  # split by a nodata cell of the filled DEM
    d[26, 20] = 0.0005  # shallower than the minimum depth
    d[12, 12] = 2.0  # inside one tile
    d[15, 36:38] = 0.25  # touches a seam without crossing it
    dem_nodata = [(20, 28), (4, 32)]  # the second lies in the hole of the ring
    filled_nodata = [(12, 30)]
    return d, dem_nodata, filled_nodata


class TestTiledEqualsWholeArray:
    @pytest.mark.parametrize("tile_cells", [8, 5, 13, 64])
    def test_seam_cases(self, tmp_path, tile_cells):
        depth, dem_nodata, filled_nodata = _seam_scene()
        dem, filled = _rasters(tmp_path, depth, dem_nodata, filled_nodata)

        tiled = list(compute_depressions(dem, filled, tile_cells=tile_cells))

        assert _as_set(tiled) == _as_set(_whole_array(dem, filled))

    def test_diagonal_neighbours_across_seams_stay_apart(self, tmp_path):
        depth, dem_nodata, filled_nodata = _seam_scene()
        dem, filled = _rasters(tmp_path, depth, dem_nodata, filled_nodata)

        tiled = list(compute_depressions(dem, filled, tile_cells=8))

        single_cells = sorted(r["max_depth_m"] for r in tiled if r["area_m2"] == 25.0)
        # The three cells of 0.5: a corner pair's and the two halves of the row
        # split by nodata of the filled DEM.
        assert single_cells == [0.25, 0.375, 0.5, 0.5, 0.5, 0.625, 0.875, 0.875, 2.0]

    @pytest.mark.parametrize("tile_cells", [6, 7, 16])
    def test_random_field(self, tmp_path, tile_cells):
        rng = np.random.default_rng(7)
        shape_ = (40, 50)
        depth = np.where(
            rng.random(shape_) < 0.55, rng.integers(1, 64, shape_) / 16, 0.0
        )
        nodata = [tuple(cell) for cell in rng.integers(0, 40, (12, 2))]
        dem, filled = _rasters(tmp_path, depth, dem_nodata=nodata)

        tiled = list(compute_depressions(dem, filled, tile_cells=tile_cells))

        whole = _whole_array(dem, filled)
        assert len(whole) > 50
        assert _as_set(tiled) == _as_set(whole)


def test_overview_sums_the_depressions_of_each_block(tmp_path):
    depth, dem_nodata, filled_nodata = _seam_scene()
    dem, filled = _rasters(tmp_path, depth, dem_nodata, filled_nodata)

    scan = compute_depressions(dem, filled, tile_cells=7, overview_px=12)
    for _ in scan:
        pass

    factor = 4  # ceil(40 / 12): the overview is 8 x 10 blocks, cut by the tiles
    whole = _whole_array_depth(dem, filled)

    def blocks(cells):
        return cells.reshape(8, factor, 10, factor).sum(axis=(1, 3))

    overview = scan.overview
    np.testing.assert_array_equal(overview.cells, blocks(whole > 0))
    np.testing.assert_array_equal(overview.depth_sum_m, blocks(whole))
    assert overview.max_depth_m == whole.max()
    assert overview.transform == TRANSFORM * Affine.scale(factor)


def test_a_shrunk_overlay_keeps_the_share_and_depth_of_depressions(tmp_path):
    depth = np.zeros((320, 400))
    depth[:, :200] = 1.0  # one large depression, half as deep ...
    depth[1::2, 201::2] = 2.0  # ... as the pits covering a quarter of the rest
    dem, filled = _rasters(tmp_path, depth)
    scan = compute_depressions(dem, filled, overview_px=100)  # blocks of 4 cells
    assert len(list(scan)) == 1 + 160 * 100

    png, meta_path = tmp_path / "depressions.png", tmp_path / "depressions.json"
    generate_overlay(scan.overview, str(png), str(meta_path), max_size=40)

    rgba = np.asarray(Image.open(png))
    meta = json.loads(meta_path.read_text())
    height, width = rgba.shape[:2]
    assert max(height, width) == 40
    rows = slice(height // 4, 3 * height // 4)
    left = rgba[rows, width // 8 : 3 * width // 8].reshape(-1, 4)
    right = rgba[rows, 5 * width // 8 : 7 * width // 8].reshape(-1, 4)
    cmap = build_depth_colormap()
    assert (left == [*cmap[127], 255]).all()  # mean depth 1 of 2 m, all covered
    assert (right == [*cmap[255], 64]).all()  # 2 m deep, a quarter covered
    assert meta["max_depth_m"] == 2.0
    assert set(meta) == {"bounds", "max_depth_m", "width", "height", "crs_source"}
