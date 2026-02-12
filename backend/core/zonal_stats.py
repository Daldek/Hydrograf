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
