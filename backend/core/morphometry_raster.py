"""
Raster-based morphometric computations: slope, aspect, TWI, Strahler order.

All functions operate on numpy arrays representing raster grids.
"""

import logging
from collections.abc import Iterator
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _compute_gradients(
    dem: np.ndarray,
    cellsize: float,
    nodata: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute Sobel gradients dx, dy (shared by slope and aspect).

    Parameters
    ----------
    dem : np.ndarray
        DEM array
    cellsize : float
        Cell size in meters
    nodata : float
        NoData value

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        (dx, dy) gradient arrays
    """
    from scipy import ndimage

    dem_calc = dem.astype(np.float64)
    dem_calc[dem == nodata] = np.nan

    dy = ndimage.sobel(
        dem_calc,
        axis=0,
        mode="constant",
        cval=np.nan,
    ) / (8 * cellsize)
    dx = ndimage.sobel(
        dem_calc,
        axis=1,
        mode="constant",
        cval=np.nan,
    ) / (8 * cellsize)

    return dx, dy


def gradient_strips(
    dem: np.ndarray,
    cellsize: float,
    nodata: float,
    strip_rows: int = 512,
) -> Iterator[tuple[slice, np.ndarray, np.ndarray]]:
    """
    Yield the Sobel gradients of the DEM strip by strip.

    Each strip of ``strip_rows`` rows (the last one may be shorter) is computed
    with the row of the DEM above it and the one below it, which the 3 x 3 Sobel
    kernel reads, so its gradients equal those rows of _compute_gradients over the
    whole DEM bit for bit, with the memory of one strip.

    Parameters
    ----------
    dem : np.ndarray
        DEM array
    cellsize : float
        Cell size in meters
    nodata : float
        NoData value
    strip_rows : int
        Rows of a strip (at least 1)

    Yields
    ------
    tuple[slice, np.ndarray, np.ndarray]
        The rows of the strip and its gradients (dx, dy)
    """
    if strip_rows < 1:
        raise ValueError(f"strip_rows must be at least 1, not {strip_rows}")
    nrows = dem.shape[0]
    for start in range(0, nrows, strip_rows):
        stop = min(start + strip_rows, nrows)
        top = max(start - 1, 0)
        dx, dy = _compute_gradients(dem[top : min(stop + 1, nrows)], cellsize, nodata)
        inner = slice(start - top, stop - top)
        yield slice(start, stop), dx[inner], dy[inner]


def compute_slope_from_gradients(
    dx: np.ndarray,
    dy: np.ndarray,
) -> np.ndarray:
    """
    Compute slope in percent from pre-computed gradients.

    Parameters
    ----------
    dx : np.ndarray
        X gradient (from _compute_gradients)
    dy : np.ndarray
        Y gradient (from _compute_gradients)

    Returns
    -------
    np.ndarray
        Slope array in percent
    """
    slope = np.sqrt(dx**2 + dy**2) * 100
    return np.asarray(np.nan_to_num(slope, nan=0.0))


def compute_aspect_from_gradients(
    dx: np.ndarray,
    dy: np.ndarray,
) -> np.ndarray:
    """
    Compute aspect in degrees from pre-computed gradients.

    Convention: 0=North, 90=East, 180=South, 270=West.
    Flat areas (no gradient) get value -1.

    Parameters
    ----------
    dx : np.ndarray
        X gradient (from _compute_gradients)
    dy : np.ndarray
        Y gradient (from _compute_gradients)

    Returns
    -------
    np.ndarray
        Aspect array in degrees (0-360, -1 for flat areas)
    """
    aspect_rad = np.arctan2(-dx, dy)
    aspect_deg = np.degrees(aspect_rad)
    aspect_deg = np.where(aspect_deg < 0, aspect_deg + 360.0, aspect_deg)

    flat_mask = (dx == 0) & (dy == 0)
    aspect_deg[flat_mask] = -1.0
    aspect_deg = np.nan_to_num(aspect_deg, nan=-1.0)

    return np.asarray(aspect_deg)


def compute_strahler_from_fdir(
    flw: Any,
    acc: np.ndarray,
    stream_threshold: int,
) -> np.ndarray:
    """
    Compute Strahler stream order using pre-computed flow directions and acc.

    It does not recompute the hydrology: it reuses the FlwdirRaster and ``acc``
    produced by ``process_hydrology_pyflwdir()``, so that Strahler orders are
    consistent with the vectorized stream network. The orders come from
    pyflwdir.streams.strahler_order, not from FlwdirRaster.stream_order: that
    one caches the orders of its first call and ignores the mask of the next
    one, so the thresholds of a run could not share the FlwdirRaster.

    Parameters
    ----------
    flw : pyflwdir.FlwdirRaster
        Flow directions of the run (process_hydrology_pyflwdir)
    acc : np.ndarray
        Flow accumulation from the main pipeline (process_hydrology_pyflwdir)
    stream_threshold : int
        Flow accumulation threshold (in cells) for stream identification

    Returns
    -------
    np.ndarray
        Strahler stream order array (uint8, nodata=0)
    """
    from pyflwdir import streams

    logger.info("Computing Strahler stream order (from pre-computed fdir)...")

    stream_mask = acc >= stream_threshold
    strahler = streams.strahler_order(
        flw.idxs_ds, flw.idxs_seq, mask=stream_mask.ravel()
    ).reshape(acc.shape)
    strahler[~stream_mask] = 0

    max_order = int(strahler.max()) if np.any(strahler > 0) else 0
    stream_count = int(np.sum(strahler > 0))
    logger.info(
        f"Strahler order computed (max order: {max_order}, "
        f"stream cells: {stream_count:,})"
    )

    return np.asarray(strahler)


def compute_twi(
    acc: np.ndarray,
    slope: np.ndarray,
    cellsize: float,
    nodata_acc: int = 0,
    min_slope_percent: float = 0.1,
) -> np.ndarray:
    """
    Compute Topographic Wetness Index (TWI).

    TWI = ln(SCA / tan(slope_rad)) where:
    - SCA = specific catchment area = upstream_area_m2 / cellsize
    - slope_rad = arctan(slope_percent / 100)
    - Minimum slope is clamped to avoid division by zero

    Parameters
    ----------
    acc : np.ndarray
        Flow accumulation array (number of upstream cells including self)
    slope : np.ndarray
        Slope array in percent
    cellsize : float
        Cell size in meters
    nodata_acc : int
        NoData value for accumulation (cells with this value are excluded)
    min_slope_percent : float
        Minimum slope in percent to avoid division by zero (default: 0.1%)

    Returns
    -------
    np.ndarray
        TWI array (float32, nodata=-9999); cell by cell, so the rows of a strip
        of ``acc`` and ``slope`` give those rows of the TWI
    """
    cell_area = cellsize * cellsize

    # Upstream area in m2 and specific catchment area (SCA)
    upstream_area_m2 = acc.astype(np.float64) * cell_area
    sca = upstream_area_m2 / cellsize

    # Clamp slope to minimum to avoid division by zero
    slope_clamped = np.maximum(slope, min_slope_percent)
    slope_rad = np.arctan(slope_clamped / 100.0)

    # TWI = ln(SCA / tan(slope_rad)), only for valid cells
    valid_mask = acc != nodata_acc
    tan_slope = np.tan(slope_rad)

    twi_result = np.full(acc.shape, -9999.0, dtype=np.float32)
    twi_result[valid_mask] = np.log(sca[valid_mask] / tan_slope[valid_mask]).astype(
        np.float32
    )

    return twi_result
