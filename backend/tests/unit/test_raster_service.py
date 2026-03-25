"""Unit tests for core.raster_service module.

Tests cover RasterCache initialization, lazy loading, fdir encoding
conversion, on-the-fly delineation from a point, stats computation,
vectorization, out-of-bounds handling, and memory invalidation.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from rasterio.transform import Affine

from core.raster_service import RasterCache, get_raster_cache


# -----------------------------------------------------------------------
# Fixtures — synthetic 5x5 rasters
# -----------------------------------------------------------------------

# D8 encoding: 4=South.  Bottom row = pit (0 in pyflwdir uint8).
# Layout: every cell flows south, bottom row is pit.
#   All cells in a column drain to the bottom cell of that column.
FDIR_PYFLWDIR_U8 = np.array(
    [
        [4, 4, 4, 4, 4],
        [4, 4, 4, 4, 4],
        [4, 4, 4, 4, 4],
        [4, 4, 4, 4, 4],
        [0, 0, 0, 0, 0],  # pits
    ],
    dtype=np.uint8,
)

# On-disk int16 convention: 0 means nodata/pit.
FDIR_SAVED_INT16 = FDIR_PYFLWDIR_U8.astype(np.int16)
# pits (0 in uint8) stay 0 in int16 — that's the saved convention

# DEM: simple elevation gradient (higher at top).
DEM = np.array(
    [
        [150, 150, 150, 150, 150],
        [140, 140, 140, 140, 140],
        [130, 130, 130, 130, 130],
        [120, 120, 120, 120, 120],
        [110, 110, 110, 110, 110],
    ],
    dtype=np.float32,
)

# Slope: uniform 5%.
SLOPE = np.full((5, 5), 5.0, dtype=np.float32)

# Transform: 5m cells, origin at (500000, 600025) top-left.
TRANSFORM = Affine(5.0, 0.0, 500000.0, 0.0, -5.0, 600025.0)
# Row 0 → y = 600025 - 0.5*5 = 600022.5 (center)
# Row 4 → y = 600025 - 4.5*5 = 600002.5 (center)
# Col 0 → x = 500000 + 0.5*5 = 500002.5 (center)
# Col 2 → x = 500000 + 2.5*5 = 500012.5 (center)


def _make_mock_rasterio_open(
    fdir_int16=FDIR_SAVED_INT16,
    dem=DEM,
    slope=SLOPE,
    transform=TRANSFORM,
    dem_nodata=-9999.0,
    slope_nodata=-9999.0,
):
    """Create a side_effect for rasterio.open that returns synthetic rasters."""

    def _open(path):
        ctx = MagicMock()
        if "flowdir" in path:
            ctx.read.return_value = fdir_int16[np.newaxis, :, :]
            ctx.__enter__ = lambda s: _make_src(fdir_int16, transform, None, nodata=0)
        elif "slope" in path:
            ctx.__enter__ = lambda s: _make_src(slope, transform, None, slope_nodata)
        else:
            # DEM
            ctx.__enter__ = lambda s: _make_src(dem, transform, None, dem_nodata)
        ctx.__exit__ = lambda s, *a: None
        return ctx

    return _open


def _make_src(data, transform, crs, nodata):
    """Create a mock rasterio dataset."""
    src = MagicMock()
    src.read.return_value = data
    src.transform = transform
    src.crs = crs
    src.nodata = nodata
    return src


@pytest.fixture
def mock_settings():
    """Patch get_settings to return a Settings-like object with resolve methods."""
    settings = MagicMock()
    settings.resolve_flowdir_path.return_value = "/fake/dem_mosaic_03_flowdir.tif"
    settings.resolve_dem_path.return_value = "/fake/dem_mosaic_01_dem.tif"
    settings.resolve_slope_path.return_value = "/fake/dem_mosaic_05_slope.tif"
    return settings


@pytest.fixture
def loaded_cache(mock_settings):
    """Return a RasterCache loaded with synthetic data."""
    cache = RasterCache()
    with (
        patch("core.raster_service.get_settings", return_value=mock_settings),
        patch("core.raster_service.rasterio") as mock_rio,
    ):
        mock_rio.open = MagicMock(side_effect=_make_mock_rasterio_open())
        cache.load()
    return cache


# -----------------------------------------------------------------------
# Tests: Initialization
# -----------------------------------------------------------------------


class TestRasterCacheInit:
    def test_not_loaded_on_creation(self):
        cache = RasterCache()
        assert cache.loaded is False

    def test_internal_arrays_are_none(self):
        cache = RasterCache()
        assert cache._dem is None
        assert cache._fdir is None
        assert cache._slope is None
        assert cache._transform is None


# -----------------------------------------------------------------------
# Tests: Loading
# -----------------------------------------------------------------------


class TestRasterCacheLoad:
    def test_load_sets_loaded_flag(self, loaded_cache):
        assert loaded_cache.loaded is True

    def test_load_populates_arrays(self, loaded_cache):
        assert loaded_cache._dem is not None
        assert loaded_cache._fdir is not None
        assert loaded_cache._slope is not None
        assert loaded_cache._shape == (5, 5)

    def test_fdir_converted_to_uint8(self, loaded_cache):
        assert loaded_cache._fdir.dtype == np.uint8

    def test_fdir_nodata_converted_to_247(self, loaded_cache):
        """On-disk int16 value 0 (nodata/pit) → pyflwdir uint8 value 247."""
        # Bottom row was 0 in int16 → should be 247 in uint8
        assert np.all(loaded_cache._fdir[4, :] == 247)

    def test_fdir_valid_values_preserved(self, loaded_cache):
        """D8 direction values (4=South) preserved after conversion."""
        assert np.all(loaded_cache._fdir[:4, :] == 4)

    def test_load_is_idempotent(self, mock_settings):
        """Calling load() twice does not reload."""
        cache = RasterCache()
        call_count = 0

        original_open = _make_mock_rasterio_open()

        def counting_open(path):
            nonlocal call_count
            call_count += 1
            return original_open(path)

        with (
            patch("core.raster_service.get_settings", return_value=mock_settings),
            patch("core.raster_service.rasterio") as mock_rio,
        ):
            mock_rio.open = MagicMock(side_effect=counting_open)
            cache.load()
            first_count = call_count
            cache.load()  # should be no-op
            assert call_count == first_count

    def test_load_without_flowdir_raises(self):
        """FileNotFoundError when flow direction raster is missing."""
        settings = MagicMock()
        settings.resolve_flowdir_path.return_value = None
        cache = RasterCache()
        with patch("core.raster_service.get_settings", return_value=settings):
            with pytest.raises(FileNotFoundError, match="Flow direction"):
                cache.load()

    def test_load_without_dem_raises(self):
        """FileNotFoundError when DEM raster is missing."""
        settings = MagicMock()
        settings.resolve_flowdir_path.return_value = "/fake/flowdir.tif"
        settings.resolve_dem_path.return_value = None
        cache = RasterCache()
        with (
            patch("core.raster_service.get_settings", return_value=settings),
            patch("core.raster_service.rasterio") as mock_rio,
        ):
            mock_rio.open = MagicMock(side_effect=_make_mock_rasterio_open())
            with pytest.raises(FileNotFoundError, match="DEM"):
                cache.load()

    def test_load_without_slope_ok(self, mock_settings):
        """Slope is optional — loading succeeds without it."""
        mock_settings.resolve_slope_path.return_value = None
        cache = RasterCache()
        with (
            patch("core.raster_service.get_settings", return_value=mock_settings),
            patch("core.raster_service.rasterio") as mock_rio,
        ):
            mock_rio.open = MagicMock(side_effect=_make_mock_rasterio_open())
            cache.load()
        assert cache.loaded is True
        assert cache._slope is None


# -----------------------------------------------------------------------
# Tests: Delineation
# -----------------------------------------------------------------------


class TestDelineateFromPoint:
    def test_delineates_single_column(self, loaded_cache):
        """Point at bottom valid row of center column → rows 0-3 of col 2.

        After fdir conversion, bottom row (int16=0) becomes nodata (uint8=247).
        Row 3 (fdir=4, south) points into nodata and becomes an effective pit.
        Delineating from row 3 gives rows 0-3 of column 2.
        """
        # Col 2, Row 3 center: x = 500012.5, y = 600025 - 3.5*5 = 600007.5
        x, y = 500012.5, 600007.5
        result = loaded_cache.delineate_from_point(x, y)

        mask = result["mask"]
        # Rows 0-3 in column 2 should be True
        assert np.all(mask[:4, 2])
        # Row 4 (nodata) should be False
        assert not mask[4, 2]
        # Other columns should be False (each column drains independently)
        assert not np.any(mask[:, 0])
        assert not np.any(mask[:, 1])
        assert not np.any(mask[:, 3])
        assert not np.any(mask[:, 4])

    def test_returns_polygon(self, loaded_cache):
        """Result contains a valid Shapely polygon."""
        x, y = 500012.5, 600007.5
        result = loaded_cache.delineate_from_point(x, y)
        polygon = result["polygon"]
        assert polygon is not None
        assert polygon.is_valid
        assert polygon.area > 0

    def test_returns_correct_keys(self, loaded_cache):
        x, y = 500012.5, 600007.5
        result = loaded_cache.delineate_from_point(x, y)
        assert "polygon" in result
        assert "mask" in result
        assert "stats" in result

    def test_partial_delineation_mid_column(self, loaded_cache):
        """Point at row 2, col 2 → watershed = rows 0-2 of col 2."""
        # Row 2 center: y = 600025 - 2.5*5 = 600012.5
        x, y = 500012.5, 600012.5
        result = loaded_cache.delineate_from_point(x, y)
        mask = result["mask"]
        # Rows 0, 1, 2 of col 2 should be in basin
        assert mask[0, 2]
        assert mask[1, 2]
        assert mask[2, 2]
        # Rows 3, 4 should NOT be (downstream of outlet)
        assert not mask[3, 2]
        assert not mask[4, 2]

    def test_point_outside_raster_raises(self, loaded_cache):
        """ValueError when point is outside the raster extent."""
        with pytest.raises(ValueError, match="outside"):
            loaded_cache.delineate_from_point(999999.0, 999999.0)

    def test_auto_loads_if_not_loaded(self, mock_settings):
        """delineate_from_point triggers lazy load if not loaded."""
        cache = RasterCache()
        with (
            patch("core.raster_service.get_settings", return_value=mock_settings),
            patch("core.raster_service.rasterio") as mock_rio,
        ):
            mock_rio.open = MagicMock(side_effect=_make_mock_rasterio_open())
            result = cache.delineate_from_point(500012.5, 600002.5)
        assert cache.loaded is True
        assert result["mask"] is not None


# -----------------------------------------------------------------------
# Tests: Stats computation
# -----------------------------------------------------------------------


class TestStatsComputation:
    def test_area_correct(self, loaded_cache):
        """Area = number of mask cells * cell area (5m * 5m = 25 m2).

        Outlet at row 3 col 2 → 4 cells (rows 0-3), each 25 m2.
        """
        x, y = 500012.5, 600007.5
        result = loaded_cache.delineate_from_point(x, y)
        stats = result["stats"]
        # 4 cells in column (rows 0-3), each 25 m2
        assert stats["area_m2"] == pytest.approx(4 * 25.0)

    def test_elevation_stats(self, loaded_cache):
        """Elevation min/max/mean from the DEM within the mask."""
        x, y = 500012.5, 600007.5
        result = loaded_cache.delineate_from_point(x, y)
        stats = result["stats"]
        # Column 2 rows 0-3 have DEM values: 150, 140, 130, 120
        assert stats["elevation_min_m"] == pytest.approx(120.0)
        assert stats["elevation_max_m"] == pytest.approx(150.0)
        assert stats["elevation_mean_m"] == pytest.approx(135.0)

    def test_slope_mean(self, loaded_cache):
        """Slope mean from the slope raster (uniform 5%)."""
        x, y = 500012.5, 600007.5
        result = loaded_cache.delineate_from_point(x, y)
        stats = result["stats"]
        assert "slope_mean_percent" in stats
        assert stats["slope_mean_percent"] == pytest.approx(5.0)

    def test_stats_without_slope(self, mock_settings):
        """Stats dict omits slope_mean_percent when slope raster is absent."""
        mock_settings.resolve_slope_path.return_value = None
        cache = RasterCache()
        with (
            patch("core.raster_service.get_settings", return_value=mock_settings),
            patch("core.raster_service.rasterio") as mock_rio,
        ):
            mock_rio.open = MagicMock(side_effect=_make_mock_rasterio_open())
            cache.load()
        cache._slope = None  # ensure slope is missing
        result = cache.delineate_from_point(500012.5, 600007.5)
        assert "slope_mean_percent" not in result["stats"]

    def test_partial_stats_correct(self, loaded_cache):
        """Stats for partial delineation (rows 0-2) are correct."""
        # Row 2 center: y = 600025 - 2.5*5 = 600012.5
        x, y = 500012.5, 600012.5
        result = loaded_cache.delineate_from_point(x, y)
        stats = result["stats"]
        # 3 cells (rows 0, 1, 2): elevations 150, 140, 130
        assert stats["area_m2"] == pytest.approx(3 * 25.0)
        assert stats["elevation_min_m"] == pytest.approx(130.0)
        assert stats["elevation_max_m"] == pytest.approx(150.0)
        assert stats["elevation_mean_m"] == pytest.approx(140.0)


# -----------------------------------------------------------------------
# Tests: Vectorization
# -----------------------------------------------------------------------


class TestVectorization:
    def test_polygon_area_matches_mask(self, loaded_cache):
        """Polygon area should match the mask area (4 cells * 25 m2)."""
        x, y = 500012.5, 600007.5
        result = loaded_cache.delineate_from_point(x, y)
        polygon = result["polygon"]
        # 4 cells of 5m x 5m = 100 m2
        assert polygon.area == pytest.approx(100.0, rel=0.01)

    def test_polygon_bounds_within_raster(self, loaded_cache):
        """Polygon should be within raster bounds."""
        x, y = 500012.5, 600007.5
        result = loaded_cache.delineate_from_point(x, y)
        polygon = result["polygon"]
        minx, miny, maxx, maxy = polygon.bounds
        assert minx >= 500000.0
        assert maxx <= 500025.0
        assert miny >= 600000.0
        assert maxy <= 600025.0


# -----------------------------------------------------------------------
# Tests: Invalidation
# -----------------------------------------------------------------------


class TestInvalidation:
    def test_invalidate_clears_loaded(self, loaded_cache):
        assert loaded_cache.loaded is True
        loaded_cache.invalidate()
        assert loaded_cache.loaded is False

    def test_invalidate_clears_arrays(self, loaded_cache):
        loaded_cache.invalidate()
        assert loaded_cache._dem is None
        assert loaded_cache._fdir is None
        assert loaded_cache._slope is None
        assert loaded_cache._transform is None
        assert loaded_cache._shape is None

    def test_can_reload_after_invalidate(self, loaded_cache, mock_settings):
        """After invalidate, a subsequent load reloads data."""
        loaded_cache.invalidate()
        assert loaded_cache.loaded is False
        with (
            patch("core.raster_service.get_settings", return_value=mock_settings),
            patch("core.raster_service.rasterio") as mock_rio,
        ):
            mock_rio.open = MagicMock(side_effect=_make_mock_rasterio_open())
            loaded_cache.load()
        assert loaded_cache.loaded is True
        assert loaded_cache._dem is not None


# -----------------------------------------------------------------------
# Tests: Singleton
# -----------------------------------------------------------------------


class TestGetRasterCache:
    def test_returns_raster_cache_instance(self):
        with patch("core.raster_service._raster_cache", None):
            cache = get_raster_cache()
            assert isinstance(cache, RasterCache)

    def test_returns_same_instance(self):
        with patch("core.raster_service._raster_cache", None):
            c1 = get_raster_cache()
            c2 = get_raster_cache()
            assert c1 is c2
