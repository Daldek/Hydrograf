"""Lazy-loading raster cache and on-the-fly partial watershed delineation.

Provides RasterCache for thread-safe lazy loading of DEM, flow direction,
and slope rasters. Supports on-the-fly watershed delineation from a point
using pyflwdir, returning a Shapely polygon, boolean mask, and zonal stats.
"""

import logging
import threading

import numpy as np
import pyflwdir
import rasterio
from rasterio.features import shapes
from rasterio.transform import Affine
from shapely.geometry import shape
from shapely.ops import unary_union

from core.config import get_settings

logger = logging.getLogger(__name__)


class RasterCache:
    """Thread-safe lazy cache for DEM, flow direction, and slope rasters.

    Rasters are loaded on first access and kept in memory until
    ``invalidate()`` is called.  The flow direction raster is converted
    from the on-disk int16 D8 convention (nodata=0) back to the pyflwdir
    uint8 convention (nodata=247, pit=0) at load time.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loaded = False
        self._dem: np.ndarray | None = None
        self._fdir: np.ndarray | None = None  # uint8, pyflwdir D8
        self._slope: np.ndarray | None = None
        self._transform: Affine | None = None
        self._crs = None
        self._dem_nodata: float | None = None
        self._slope_nodata: float | None = None
        self._shape: tuple[int, int] | None = None

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def loaded(self) -> bool:
        """Whether rasters have been loaded into memory."""
        return self._loaded

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load rasters from disk.  Thread-safe and idempotent."""
        with self._lock:
            if self._loaded:
                return
            self._do_load()

    def _do_load(self) -> None:
        """Internal loading logic (must be called under lock)."""
        cfg = get_settings()

        # --- Flow direction (required) ---
        fdir_path = cfg.resolve_flowdir_path()
        if not fdir_path:
            raise FileNotFoundError("Flow direction raster not found")

        with rasterio.open(fdir_path) as src:
            fdir_int16 = src.read(1)
            self._transform = src.transform
            self._crs = src.crs
            self._shape = fdir_int16.shape

        # Convert on-disk int16 D8 (nodata=0) → pyflwdir uint8 (nodata=247)
        fdir_u8 = fdir_int16.astype(np.uint8)
        fdir_u8[fdir_int16 == 0] = 247
        self._fdir = fdir_u8

        # --- DEM (required) ---
        dem_path = cfg.resolve_dem_path()
        if not dem_path:
            raise FileNotFoundError("DEM raster not found")

        with rasterio.open(dem_path) as src:
            self._dem = src.read(1)
            self._dem_nodata = src.nodata

        # --- Slope (optional) ---
        slope_path = cfg.resolve_slope_path()
        if slope_path:
            with rasterio.open(slope_path) as src:
                self._slope = src.read(1)
                self._slope_nodata = src.nodata

        self._loaded = True
        logger.info(
            "RasterCache loaded: shape=%s, mem=%.1f MB",
            self._shape,
            self._memory_mb(),
        )

    # ------------------------------------------------------------------
    # Memory management
    # ------------------------------------------------------------------

    def _memory_mb(self) -> float:
        total = 0
        for arr in (self._dem, self._fdir, self._slope):
            if arr is not None:
                total += arr.nbytes
        return total / (1024 * 1024)

    def invalidate(self) -> None:
        """Release all rasters from memory."""
        with self._lock:
            self._dem = None
            self._fdir = None
            self._slope = None
            self._transform = None
            self._crs = None
            self._dem_nodata = None
            self._slope_nodata = None
            self._shape = None
            self._loaded = False
            logger.info("RasterCache invalidated")

    # ------------------------------------------------------------------
    # Delineation
    # ------------------------------------------------------------------

    def delineate_from_point(self, x: float, y: float) -> dict:
        """Delineate watershed from a point in EPSG:2180 coordinates.

        Parameters
        ----------
        x, y : float
            Easting and northing in EPSG:2180 (PL-1992).

        Returns
        -------
        dict
            ``polygon`` : Shapely Polygon/MultiPolygon (EPSG:2180)
            ``mask``    : boolean np.ndarray (same shape as rasters)
            ``stats``   : dict with area_m2, elevation_min/max/mean_m,
                          and optionally slope_mean_percent
        """
        if not self._loaded:
            self.load()

        # --- Point → raster row/col ---
        # Inverse transform gives continuous pixel coordinates where integer
        # values sit on pixel edges.  Truncation (int()) maps to the correct
        # pixel index; round() would give wrong results at cell centres (x.5)
        # due to Python's banker's rounding.
        col_f, row_f = ~self._transform * (x, y)
        row, col = int(row_f), int(col_f)

        if row < 0 or row >= self._shape[0] or col < 0 or col >= self._shape[1]:
            raise ValueError(
                f"Point ({x}, {y}) is outside the raster extent "
                f"(shape={self._shape})"
            )

        # --- Delineate basin via pyflwdir ---
        flw = pyflwdir.from_array(
            self._fdir,
            ftype="d8",
            transform=self._transform,
            latlon=False,
        )
        flat_idx = np.ravel_multi_index((row, col), self._shape)
        basins = flw.basins(idxs=[flat_idx])
        mask = basins > 0

        if not np.any(mask):
            raise ValueError(
                f"Empty watershed mask for point ({x}, {y}) at row={row}, col={col}"
            )

        # --- Vectorise mask → polygon ---
        polygon = self._vectorize_mask(mask)
        if polygon is None:
            raise ValueError("Failed to vectorize watershed mask")

        # --- Zonal stats ---
        stats = self._compute_stats(mask)

        return {
            "polygon": polygon,
            "mask": mask,
            "stats": stats,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _vectorize_mask(self, mask: np.ndarray):
        """Convert boolean mask to a Shapely geometry via rasterio."""
        mask_uint8 = mask.astype(np.uint8)
        geoms = []
        for geom_dict, value in shapes(mask_uint8, transform=self._transform):
            if value == 1:
                geoms.append(shape(geom_dict))
        if not geoms:
            return None
        return unary_union(geoms)

    def _compute_stats(self, mask: np.ndarray) -> dict:
        """Compute zonal statistics for the masked area."""
        cell_area_m2 = abs(self._transform.a * self._transform.e)

        # DEM stats
        dem_vals = self._dem[mask]
        if self._dem_nodata is not None:
            dem_vals = dem_vals[dem_vals != self._dem_nodata]

        has_dem = len(dem_vals) > 0

        stats: dict = {
            "area_m2": float(np.sum(mask) * cell_area_m2),
            "elevation_min_m": float(np.min(dem_vals)) if has_dem else 0.0,
            "elevation_max_m": float(np.max(dem_vals)) if has_dem else 0.0,
            "elevation_mean_m": float(np.mean(dem_vals)) if has_dem else 0.0,
        }

        # Slope stats (optional)
        if self._slope is not None:
            slope_vals = self._slope[mask]
            if self._slope_nodata is not None:
                slope_vals = slope_vals[slope_vals != self._slope_nodata]
            has_slope = len(slope_vals) > 0
            stats["slope_mean_percent"] = (
                float(np.mean(slope_vals)) if has_slope else 0.0
            )

        return stats


# -----------------------------------------------------------------------
# Singleton access
# -----------------------------------------------------------------------

_raster_cache: RasterCache | None = None
_singleton_lock = threading.Lock()


def get_raster_cache() -> RasterCache:
    """Return the module-level RasterCache singleton (created on first call)."""
    global _raster_cache
    if _raster_cache is None:
        with _singleton_lock:
            if _raster_cache is None:
                _raster_cache = RasterCache()
    return _raster_cache
