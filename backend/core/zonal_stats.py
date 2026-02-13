"""
Zonal statistics utilities using numpy bincount for O(M) performance.

Provides vectorized zonal statistics computation on labeled rasters,
avoiding per-label masking loops (O(n*M) → O(M)).
"""

import logging

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

    return maximum(values, labels, index=np.arange(1, n_labels + 1))


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

    return minimum(values, labels, index=np.arange(1, n_labels + 1))


def zonal_elevation_histogram(
    labels: np.ndarray,
    dem: np.ndarray,
    max_label: int,
    nodata: float,
    interval_m: int = 1,
) -> dict[int, dict]:
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
    flat_valid = valid.ravel()

    valid_idx = np.where(flat_valid)[0]
    if len(valid_idx) == 0:
        return {}

    v_labels = flat_labels[valid_idx]
    v_elev = flat_dem[valid_idx]
    v_bins = np.floor(v_elev / interval_m).astype(np.int64)

    # Sort by label for grouped processing
    order = np.argsort(v_labels, kind="stable")
    v_labels = v_labels[order]
    v_bins = v_bins[order]

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
