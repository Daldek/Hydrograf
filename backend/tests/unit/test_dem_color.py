"""Tests for utils/dem_color.py: colormap, hillshade and the windowed helpers."""

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.transform import from_origin

from utils.dem_color import (
    HILLSHADE_HALO_ROWS,
    build_colormap,
    compute_hillshade,
    normalize_elevation,
    read_strips,
    reduce_into,
    shade_strip,
    summarize_elevation,
    thumbnail_size,
)

NODATA = -9999


def _write(path, data):
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype=data.dtype,
        crs="EPSG:2180",
        transform=from_origin(500000.0, 600000.0, 5.0, 5.0),
        nodata=NODATA,
    ) as dst:
        dst.write(data, 1)
    return path


class TestBuildColormap:
    """Tests for build_colormap()."""

    def test_default_shape_and_dtype(self):
        """Default call returns (256, 3) uint8 array."""
        cmap = build_colormap()
        assert cmap.shape == (256, 3)
        assert cmap.dtype == np.uint8

    def test_custom_steps(self):
        """Custom n_steps produces correct shape."""
        cmap = build_colormap(n_steps=64)
        assert cmap.shape == (64, 3)
        assert cmap.dtype == np.uint8

    def test_first_color_dark_green(self):
        """First color stop is dark green RGB(56, 128, 60)."""
        cmap = build_colormap()
        np.testing.assert_array_equal(cmap[0], [56, 128, 60])

    def test_last_color_near_white(self):
        """Last color stop is near white RGB(245, 245, 240)."""
        cmap = build_colormap()
        np.testing.assert_array_equal(cmap[-1], [245, 245, 240])

    def test_red_channel_monotonic_trend(self):
        """Red channel generally increases from dark green to near white.

        We check that the last value is greater than the first, and the
        overall trend is non-decreasing (allowing some interpolation noise).
        """
        cmap = build_colormap()
        red = cmap[:, 0].astype(int)
        assert red[-1] > red[0]
        # Smoothed trend: average of first 32 < average of last 32
        assert red[:32].mean() < red[-32:].mean()

    def test_single_step_raises(self):
        """Edge case: n_steps=1 raises ZeroDivisionError (division by n-1)."""
        with pytest.raises(ZeroDivisionError):
            build_colormap(n_steps=1)

    def test_two_steps(self):
        """n_steps=2 returns first and last color stops."""
        cmap = build_colormap(n_steps=2)
        assert cmap.shape == (2, 3)
        np.testing.assert_array_equal(cmap[0], [56, 128, 60])
        np.testing.assert_array_equal(cmap[1], [245, 245, 240])

    def test_values_in_valid_range(self):
        """All color values should be 0-255 (guaranteed by uint8)."""
        cmap = build_colormap()
        assert cmap.min() >= 0
        assert cmap.max() <= 255


class TestComputeHillshade:
    """Tests for compute_hillshade()."""

    def test_flat_dem_returns_uniform(self):
        """A perfectly flat DEM produces a uniform hillshade."""
        dem = np.ones((50, 50), dtype=np.float64) * 100.0
        hs = compute_hillshade(dem, cellsize=5.0)
        # All values should be identical (cos(slope_rad) = 1, sin(slope_rad) = 0)
        unique_values = np.unique(hs)
        assert len(unique_values) == 1

    def test_output_range_zero_to_one(self):
        """Output values are clipped to [0, 1]."""
        dem = np.random.default_rng(42).uniform(100, 200, (50, 50))
        hs = compute_hillshade(dem, cellsize=5.0)
        assert hs.min() >= 0.0
        assert hs.max() <= 1.0

    def test_dtype_float64(self):
        """Output dtype is float64."""
        dem = np.ones((20, 20), dtype=np.float64) * 100.0
        hs = compute_hillshade(dem, cellsize=5.0)
        assert hs.dtype == np.float64

    def test_shape_preserved(self):
        """Output shape matches input shape."""
        dem = np.ones((30, 40), dtype=np.float64) * 100.0
        hs = compute_hillshade(dem, cellsize=5.0)
        assert hs.shape == dem.shape

    def test_slope_creates_variation(self):
        """A DEM with varying terrain produces variation in hillshade values."""
        dem = np.zeros((50, 50), dtype=np.float64)
        # Create a ridge + valley terrain to produce varying slopes and aspects
        for row in range(50):
            for col in range(50):
                dem[row, col] = 50.0 * np.sin(row / 5.0) + 30.0 * np.cos(col / 3.0)
        hs = compute_hillshade(dem, cellsize=5.0)
        # Should have more than one unique value
        assert len(np.unique(hs)) > 1

    def test_custom_azimuth_altitude(self):
        """Custom azimuth and altitude produce valid output."""
        dem = np.random.default_rng(99).uniform(100, 200, (30, 30))
        hs = compute_hillshade(dem, cellsize=5.0, azimuth=180.0, altitude=30.0)
        assert hs.shape == dem.shape
        assert hs.min() >= 0.0
        assert hs.max() <= 1.0

    def test_flat_dem_hillshade_value(self):
        """Flat DEM hillshade equals sin(altitude_rad) since slope is zero."""
        dem = np.ones((20, 20), dtype=np.float64) * 100.0
        altitude = 45.0
        hs = compute_hillshade(dem, cellsize=5.0, altitude=altitude)
        expected = np.sin(np.radians(altitude))
        np.testing.assert_allclose(hs[10, 10], expected, atol=1e-10)


class TestNormalizeElevation:
    """Tests for normalize_elevation() percentile clipping."""

    def test_typical_range(self):
        """Percentile clipping returns narrower range than min/max."""
        rng = np.random.default_rng(42)
        data = rng.normal(200, 30, size=10000).astype(np.float64)
        # Add outliers (e.g. landfill at 500m, quarry at 50m)
        data = np.append(data, [500.0, 500.0, 50.0, 50.0])
        lo, hi = normalize_elevation(data)
        assert lo > float(np.min(data)), "Lower bound should clip outliers"
        assert hi < float(np.max(data)), "Upper bound should clip outliers"

    def test_percentile_boundaries(self):
        """Returns approximate 5th and 95th percentiles."""
        data = np.arange(0, 1000, dtype=np.float64)
        lo, hi = normalize_elevation(data)
        assert abs(lo - 50.0) < 5.0  # p5 of 0-999 ≈ 50
        assert abs(hi - 950.0) < 5.0  # p95 of 0-999 ≈ 950

    def test_flat_terrain_fallback(self):
        """Flat terrain (p5 == p95) falls back to full min/max range."""
        data = np.full(1000, 150.0)
        lo, hi = normalize_elevation(data)
        assert lo == 150.0
        assert hi == 150.0

    def test_empty_array(self):
        """Empty array returns (0, 0)."""
        lo, hi = normalize_elevation(np.array([]))
        assert lo == 0.0
        assert hi == 0.0

    def test_custom_percentiles(self):
        """Custom percentile boundaries are respected."""
        data = np.arange(0, 1000, dtype=np.float64)
        lo, hi = normalize_elevation(data, low_pct=10.0, high_pct=90.0)
        assert abs(lo - 100.0) < 5.0  # p10 ≈ 100
        assert abs(hi - 900.0) < 5.0  # p90 ≈ 900

    def test_values_outside_range_still_colored(self):
        """Outliers beyond percentile window get clamped, not dropped."""
        data = np.array([100.0, 150.0, 200.0, 250.0, 300.0, 1000.0])
        lo, hi = normalize_elevation(data)
        # 1000m outlier should be above hi, but still normalizable
        normalized = (1000.0 - lo) / (hi - lo) if hi > lo else 0.0
        # Clamped to 255 after np.clip — value > 1.0 is expected
        assert normalized > 1.0


class TestSummarizeElevation:
    """summarize_elevation() equals normalize_elevation() of all valid cells."""

    @pytest.mark.parametrize("dtype", ["float32", "float64", "int16"])
    @pytest.mark.parametrize("rows_per_strip", [1, 4, 1000])
    def test_equals_the_whole_array(self, tmp_path, dtype, rows_per_strip):
        rng = np.random.default_rng(3)
        # Negative elevations too: the sort keys of negative floats are reversed.
        data = rng.normal(20, 40, (23, 17)).astype(dtype)
        data[rng.random(data.shape) < 0.2] = NODATA
        if dtype != "int16":
            data[2, 3] = np.nan
        valid = data[np.isfinite(data) & (data != NODATA)]

        with rasterio.open(_write(tmp_path / "dem.tif", data)) as src:
            summary = summarize_elevation(src, rows_per_strip=rows_per_strip)

        assert summary.count == valid.size
        assert summary.elevation_min_m == float(valid.min())
        assert summary.elevation_max_m == float(valid.max())
        assert (summary.color_min_m, summary.color_max_m) == normalize_elevation(valid)

    @pytest.mark.parametrize("values", [[42.5], [7.0] * 30, [3.0, 3.0, 3.0, 9.0]])
    def test_few_or_equal_values(self, tmp_path, values):
        data = np.full((5, 8), NODATA, dtype="float32")
        data.flat[: len(values)] = values
        valid = np.array(values, dtype="float32")

        with rasterio.open(_write(tmp_path / "dem.tif", data)) as src:
            summary = summarize_elevation(src, rows_per_strip=2)

        assert (summary.color_min_m, summary.color_max_m) == normalize_elevation(valid)

    def test_no_valid_cell_raises(self, tmp_path):
        data = np.full((4, 4), NODATA, dtype="float32")

        with (
            rasterio.open(_write(tmp_path / "dem.tif", data)) as src,
            pytest.raises(ValueError, match="no valid elevation"),
        ):
            summarize_elevation(src)


def test_hillshade_of_strips_equals_that_of_the_whole_raster(tmp_path):
    rows, cols = np.indices((30, 20))
    data = (50 + 10 * np.sin(rows / 3) + 5 * np.cos(cols / 4)).astype("float32")
    data[10:13, 5:9] = NODATA
    data[:, 0] = NODATA
    whole = data.astype(np.float64)
    whole[data == NODATA] = np.nan
    expected = compute_hillshade(whole, 5.0)
    expected[~np.isfinite(expected)] = 0.0  # next to nodata, as reprojected before

    with rasterio.open(_write(tmp_path / "dem.tif", data)) as src:
        strips = read_strips(src, 4, HILLSHADE_HALO_ROWS)
        shaded = np.vstack([shade_strip(strip, src.nodata, 5.0) for strip in strips])

    np.testing.assert_array_equal(shaded, expected)


@pytest.mark.parametrize("ufunc", [np.maximum, np.add])
def test_windows_reduce_to_the_blocks_of_the_whole_raster(ufunc):
    data = np.random.default_rng(5).integers(0, 100, (23, 31)).astype(np.float64)
    padded = np.zeros((24, 32))
    padded[:23, :31] = data
    expected = ufunc.reduce(ufunc.reduce(padded.reshape(6, 4, 8, 4), axis=3), axis=1)

    blocks = np.zeros((6, 8))
    for row0 in range(0, 23, 5):  # windows that cut blocks
        for col0 in range(0, 31, 7):
            window = data[row0 : row0 + 5, col0 : col0 + 7]
            reduce_into(blocks, window, row0, col0, 4, ufunc)

    np.testing.assert_array_equal(blocks, expected)


@pytest.mark.parametrize(
    "size",
    [(2443, 1863), (1863, 2443), (1500, 1500), (1025, 3), (3, 1025), (1024, 1024)],
)
def test_thumbnail_size_is_that_of_pil(size):
    image = Image.new("1", size)
    image.thumbnail((1024, 1024))

    assert thumbnail_size(*size, 1024) == image.size
