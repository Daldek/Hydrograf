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


def compute_slope(
    dem: np.ndarray,
    cellsize: float,
    nodata: float,
) -> np.ndarray:
    """
    Compute slope in percent.

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
    np.ndarray
        Slope array in percent
    """
    logger.info("Computing slope...")
    dx, dy = _compute_gradients(dem, cellsize, nodata)
    slope = compute_slope_from_gradients(dx, dy)
    logger.info(f"Slope computed (range: {slope.min():.1f}% - {slope.max():.1f}%)")
    return slope


def compute_aspect(
    dem: np.ndarray,
    cellsize: float,
    nodata: float,
) -> np.ndarray:
    """
    Compute aspect (slope direction) in degrees.

    Convention: 0=North, 90=East, 180=South, 270=West
    (clockwise from North). Flat areas get value -1.

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
    np.ndarray
        Aspect array in degrees (0-360, -1 for flat areas)
    """
    logger.info("Computing aspect...")
    dx, dy = _compute_gradients(dem, cellsize, nodata)
    aspect_deg = compute_aspect_from_gradients(dx, dy)

    valid = aspect_deg[aspect_deg >= 0]
    if len(valid) > 0:
        logger.info(f"Aspect computed (range: {valid.min():.1f}° - {valid.max():.1f}°)")
    else:
        logger.info("Aspect computed (all flat)")

    return aspect_deg


def compute_strahler_order(
    dem: np.ndarray,
    metadata: dict[str, Any],
    stream_threshold: int = 1000,
) -> np.ndarray:
    """
    Compute Strahler stream order using pyflwdir.

    .. deprecated::
        Use ``compute_strahler_from_fdir()`` instead — it reuses
        pre-computed fdir/acc from the main pipeline, avoiding
        inconsistency between Strahler and vectorized streams.

    Uses pyflwdir's FlwdirRaster.stream_order() method.
    Only stream cells (flow_accumulation >= threshold) get an order.
    Non-stream cells have order 0 (nodata).

    Parameters
    ----------
    dem : np.ndarray
        Filled DEM array
    metadata : dict
        Grid metadata with transform or xllcorner/yllcorner/cellsize, nodata_value
    stream_threshold : int
        Flow accumulation threshold for stream identification

    Returns
    -------
    np.ndarray
        Strahler stream order array (uint8, nodata=0)
    """
    import pyflwdir
    from pyflwdir.dem import fill_depressions as pyflwdir_fill_depressions

    from core.hydrology import fill_internal_nodata_holes

    logger.info("Computing Strahler stream order via pyflwdir...")

    nodata = metadata["nodata_value"]

    # Patch internal nodata holes (same as main pipeline)
    dem_patched, _ = fill_internal_nodata_holes(dem, nodata)

    # Depression filling + D8 flow direction
    _filled, d8_fdir = pyflwdir_fill_depressions(
        dem_patched, nodata=nodata, max_depth=-1.0, outlets="edge"
    )

    # Build transform
    transform = metadata.get("transform")
    if transform is None:
        from rasterio.transform import from_bounds

        xll, yll = metadata["xllcorner"], metadata["yllcorner"]
        nrows, ncols = dem.shape
        cs = metadata["cellsize"]
        transform = from_bounds(
            xll, yll, xll + ncols * cs, yll + nrows * cs, ncols, nrows
        )

    # Build FlwdirRaster
    flw = pyflwdir.from_array(d8_fdir, ftype="d8", transform=transform, latlon=False)

    # Compute upstream area for mask
    acc_float = flw.upstream_area(unit="cell")
    acc = np.where(acc_float == -9999, 0, acc_float).astype(np.int32)

    # Stream mask
    stream_mask = acc >= stream_threshold

    # Compute Strahler order
    strahler = flw.stream_order(type="strahler", mask=stream_mask)
    strahler = strahler.astype(np.uint8)

    # Non-stream cells → 0 (nodata)
    strahler[~stream_mask] = 0

    max_order = int(strahler.max()) if np.any(strahler > 0) else 0
    stream_count = int(np.sum(strahler > 0))
    logger.info(
        f"Strahler order computed (max order: {max_order}, "
        f"stream cells: {stream_count:,})"
    )

    return np.asarray(strahler)


def compute_strahler_from_fdir(
    flw: Any,
    acc: np.ndarray,
    stream_threshold: int,
) -> np.ndarray:
    """
    Compute Strahler stream order using pre-computed flow directions and acc.

    Unlike ``compute_strahler_order()``, this function does NOT recompute
    hydrology from scratch. It reuses the FlwdirRaster and ``acc`` produced
    by ``process_hydrology_pyflwdir()``, ensuring that Strahler orders are
    consistent with the vectorized stream network. The orders come from
    pyflwdir.streams.strahler_order, not from FlwdirRaster.stream_order: that
    one caches the orders of its first call and ignores the mask of the next
    one, so the thresholds of a run could not share the FlwdirRaster.

    Parameters
    ----------
    flw : pyflwdir.FlwdirRaster
        Flow directions of the run (process_hydrology_pyflwdir)
    acc : np.ndarray
        Flow accumulation from the main pipeline (after fix_internal_sinks)
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
