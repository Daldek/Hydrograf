"""Tests for utils/dem_color.py: colormap builder and hillshade computation."""

import numpy as np
import pytest

from utils.dem_color import build_colormap, compute_hillshade, normalize_elevation


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
