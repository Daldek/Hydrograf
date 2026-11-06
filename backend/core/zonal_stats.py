"""
Zonal statistics of labelled rasters.

zonal_summary gives the statistics of the sub-catchments of process_dem with two numba
passes over the raster and memory per label only. The bincount and scipy functions
(zonal_bincount, zonal_min, zonal_max, zonal_elevation_histogram) serve
generate_depressions.py and are the reference of zonal_summary in the tests.
"""

import logging
from dataclasses import dataclass
from typing import Any

import numba
import numpy as np

logger = logging.getLogger(__name__)


def zonal_bincount(
    labels: np.ndarray,
    weights: np.ndarray | None = None,
    max_label: int | None = None,
    valid_mask: np.ndarray | None = None,
) -> np.ndarray:
    """
    Compute zonal sums (or counts) using np.bincount.

    Parameters
    ----------
    labels : np.ndarray
        Label array (int, 0 = background/excluded)
    weights : np.ndarray, optional
        Weight array for weighted sums. If None, returns counts.
    max_label : int, optional
        Maximum label value. Inferred from labels if not provided.
    valid_mask : np.ndarray, optional
        Boolean mask — only cells where True are counted.

    Returns
    -------
    np.ndarray
        Array of shape (max_label + 1,) with per-label sums/counts.
        Index 0 corresponds to background.
    """
    if max_label is None:
        max_label = int(labels.max())

    flat_labels = labels.ravel()

    if valid_mask is not None:
        flat_mask = valid_mask.ravel()
        flat_labels = np.where(flat_mask, flat_labels, 0)
        if weights is not None:
            weights = np.where(valid_mask, weights, 0.0)

    if weights is not None:
        return np.bincount(
            flat_labels, weights=weights.ravel(), minlength=max_label + 1
        )
    else:
        return np.bincount(flat_labels, minlength=max_label + 1)


def zonal_max(
    labels: np.ndarray,
    values: np.ndarray,
    n_labels: int,
) -> np.ndarray:
    """
    Compute per-label maximum using scipy.ndimage.maximum.

    Parameters
    ----------
    labels : np.ndarray
        Label array (1-based labels, 0 = background)
    values : np.ndarray
        Value array to compute max over
    n_labels : int
        Number of labels (1..n_labels)

    Returns
    -------
    np.ndarray
        Array of shape (n_labels,) with per-label max values
        (0-indexed: result[0] = label 1).
    """
    from scipy.ndimage import maximum

    return np.asarray(maximum(values, labels, index=np.arange(1, n_labels + 1)))


def zonal_min(
    labels: np.ndarray,
    values: np.ndarray,
    n_labels: int,
) -> np.ndarray:
    """
    Compute per-label minimum using scipy.ndimage.minimum.

    Parameters
    ----------
    labels : np.ndarray
        Label array (1-based labels, 0 = background)
    values : np.ndarray
        Value array to compute min over
    n_labels : int
        Number of labels (1..n_labels)

    Returns
    -------
    np.ndarray
        Array of shape (n_labels,) with per-label min values
        (0-indexed: result[0] = label 1).
    """
    from scipy.ndimage import minimum

    return np.asarray(minimum(values, labels, index=np.arange(1, n_labels + 1)))


def zonal_elevation_histogram(
    labels: np.ndarray,
    dem: np.ndarray,
    max_label: int,
    nodata: float,
    interval_m: int = 1,
) -> dict[int, dict[str, Any]]:
    """
    Compute per-label elevation histogram with fixed interval.

    Single-pass O(M) algorithm. Histograms use absolute elevation bins
    so they can be merged across catchments by aligning on base_m.

    Parameters
    ----------
    labels : np.ndarray
        Label array (1-based labels, 0 = background)
    dem : np.ndarray
        DEM array with elevation values
    max_label : int
        Maximum label value
    nodata : float
        NoData value in DEM
    interval_m : int
        Bin width in meters (default: 1)

    Returns
    -------
    dict[int, dict]
        Mapping label → {"base_m": int, "interval_m": int, "counts": list[int]}.
        Labels with no valid cells are omitted.
    """
    valid = (dem != nodata) & (labels > 0)
    flat_labels = labels.ravel()
    flat_dem = dem.ravel()

    valid_idx = np.where(valid.ravel())[0]
    del valid
    if len(valid_idx) == 0:
        return {}

    v_labels = flat_labels[valid_idx]
    # Compute bins directly — avoids keeping a separate v_elev copy
    v_bins = np.floor(flat_dem[valid_idx] / interval_m).astype(np.int64)
    del valid_idx

    # Sort by label for grouped processing
    order = np.argsort(v_labels, kind="stable")
    v_labels = v_labels[order]
    v_bins = v_bins[order]
    del order

    # Find boundaries between labels
    label_changes = np.where(np.diff(v_labels) != 0)[0] + 1
    starts = np.concatenate([[0], label_changes])
    ends = np.concatenate([label_changes, [len(v_labels)]])

    result = {}
    for s, e in zip(starts, ends, strict=True):
        lbl = int(v_labels[s])
        bins_chunk = v_bins[s:e]
        min_bin = int(bins_chunk.min())
        max_bin = int(bins_chunk.max())
        n_bins = max_bin - min_bin + 1
        counts = np.bincount(bins_chunk - min_bin, minlength=n_bins)
        result[lbl] = {
            "base_m": min_bin * interval_m,
            "interval_m": interval_m,
            "counts": counts.tolist(),
        }

    return result


@dataclass(frozen=True)
class ZonalSummary:
    """Statistics of the labels of a raster: arrays indexed by label (0 unused).

    Attributes
    ----------
    count : np.ndarray
        Cells of each label (int64).
    elev_count : np.ndarray
        Cells of each label with an elevation (int64).
    elev_sum_m : np.ndarray
        Sum of the elevations [m], added in the order of the cells (float64).
    elev_min_m, elev_max_m : np.ndarray
        Lowest and highest elevation [m]: inf and -inf without an elevation.
    slope_sum_percent : np.ndarray
        Sum of the slopes of all cells [%], in the order of the cells (float64).
    flow_dist_max_m : np.ndarray or None
        Largest flow distance to the outlet [m], -inf for a label without cells;
        None without flow distances.
    histograms : dict[int, dict]
        Elevation histograms of the labels with an elevation, as
        zonal_elevation_histogram gives them.
    """

    count: np.ndarray
    elev_count: np.ndarray
    elev_sum_m: np.ndarray
    elev_min_m: np.ndarray
    elev_max_m: np.ndarray
    slope_sum_percent: np.ndarray
    flow_dist_max_m: np.ndarray | None
    histograms: dict[int, dict[str, Any]]


def zonal_summary(
    labels: np.ndarray,
    dem: np.ndarray,
    slope: np.ndarray,
    nodata: float,
    flow_dist_m: np.ndarray | None = None,
    interval_m: int = 1,
) -> ZonalSummary:
    """Compute the statistics of every label: one pass, then one for the histograms.

    The results equal bit for bit those of zonal_bincount (sums in the order of the
    cells), zonal_min, zonal_max and zonal_elevation_histogram over the same cells:
    ``dem`` is compared with ``nodata`` and divided by ``interval_m`` in the types
    NumPy gives these operations. Besides the result, the memory is a few arrays per
    label and one count per histogram bin.

    Parameters
    ----------
    labels : np.ndarray
        Label raster (2-D int; 0 and below are no label).
    dem : np.ndarray
        Elevations [m]; cells equal to ``nodata`` have none.
    slope : np.ndarray
        Slope [%].
    nodata : float
        NoData value of ``dem``.
    flow_dist_m : np.ndarray, optional
        Flow distance to the outlet [m], for ``flow_dist_max_m``.
    interval_m : int
        Bin width of the elevation histograms [m].

    Returns
    -------
    ZonalSummary
        Statistics of the labels 0 to the highest label.
    """
    max_label = max(int(labels.max()), 0)
    nodata_value = np.result_type(dem.dtype, nodata).type(nodata)
    interval = np.result_type(dem.dtype, interval_m).type(interval_m)
    distances = (
        flow_dist_m if flow_dist_m is not None else np.zeros((0, 0), dtype=np.float32)
    )
    (
        count,
        elev_count,
        elev_sum,
        elev_min,
        elev_max,
        slope_sum,
        dist_max,
        bin_min,
        bin_max,
    ) = _summary_pass(
        labels,
        dem,
        nodata_value,
        slope,
        distances,
        flow_dist_m is not None,
        interval,
        max_label,
    )
    offsets = np.zeros(max_label + 2, dtype=np.int64)
    np.cumsum(np.where(elev_count > 0, bin_max - bin_min + 1, 0), out=offsets[1:])
    bin_counts = _histogram_pass(labels, dem, nodata_value, interval, bin_min, offsets)
    histograms = {
        int(label): {
            "base_m": int(bin_min[label]) * interval_m,
            "interval_m": interval_m,
            "counts": bin_counts[offsets[label] : offsets[label + 1]].tolist(),
        }
        for label in np.flatnonzero(elev_count)
    }
    return ZonalSummary(
        count=count,
        elev_count=elev_count,
        elev_sum_m=elev_sum,
        elev_min_m=elev_min,
        elev_max_m=elev_max,
        slope_sum_percent=slope_sum,
        flow_dist_max_m=dist_max if flow_dist_m is not None else None,
        histograms=histograms,
    )


@numba.njit(cache=True)
def _summary_pass(
    labels: np.ndarray,
    dem: np.ndarray,
    nodata: Any,
    slope: np.ndarray,
    flow_dist_m: np.ndarray,
    with_dist: bool,
    interval: Any,
    max_label: int,
) -> tuple[np.ndarray, ...]:
    """Accumulate the statistics and the histogram bin range of each label."""
    size = max_label + 1
    count = np.zeros(size, dtype=np.int64)
    elev_count = np.zeros(size, dtype=np.int64)
    elev_sum = np.zeros(size, dtype=np.float64)
    elev_min = np.full(size, np.inf)
    elev_max = np.full(size, -np.inf)
    slope_sum = np.zeros(size, dtype=np.float64)
    dist_max = np.full(size, -np.inf)
    bin_min = np.zeros(size, dtype=np.int64)
    bin_max = np.zeros(size, dtype=np.int64)
    nrows, ncols = labels.shape
    for row in range(nrows):
        for col in range(ncols):
            label = labels[row, col]
            if label <= 0:
                continue
            count[label] += 1
            slope_sum[label] += slope[row, col]
            if with_dist and flow_dist_m[row, col] > dist_max[label]:
                dist_max[label] = flow_dist_m[row, col]
            elevation = dem[row, col]
            if elevation == nodata:
                continue
            elev_sum[label] += elevation
            elev_min[label] = min(elev_min[label], elevation)
            elev_max[label] = max(elev_max[label], elevation)
            elevation_bin = np.int64(np.floor(elevation / interval))
            if elev_count[label] == 0 or elevation_bin < bin_min[label]:
                bin_min[label] = elevation_bin
            if elev_count[label] == 0 or elevation_bin > bin_max[label]:
                bin_max[label] = elevation_bin
            elev_count[label] += 1
    return (
        count,
        elev_count,
        elev_sum,
        elev_min,
        elev_max,
        slope_sum,
        dist_max,
        bin_min,
        bin_max,
    )


@numba.njit(cache=True)
def _histogram_pass(
    labels: np.ndarray,
    dem: np.ndarray,
    nodata: Any,
    interval: Any,
    bin_min: np.ndarray,
    offsets: np.ndarray,
) -> np.ndarray:
    """Count the cells of each elevation bin (bins of label l from offsets[l])."""
    counts = np.zeros(offsets[-1], dtype=np.int64)
    nrows, ncols = labels.shape
    for row in range(nrows):
        for col in range(ncols):
            label = labels[row, col]
            if label <= 0:
                continue
            elevation = dem[row, col]
            if elevation == nodata:
                continue
            elevation_bin = np.int64(np.floor(elevation / interval))
            counts[offsets[label] + elevation_bin - bin_min[label]] += 1
    return counts
