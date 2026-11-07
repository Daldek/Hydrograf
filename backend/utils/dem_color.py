"""
Shared DEM visualization utilities: colour ramp, hillshade and windowed reading.

Used by scripts/generate_dem_overlay.py and scripts/generate_dem_tiles.py; the
overlay grid and the block reduction also serve scripts/generate_streams_overlay.py
and scripts/generate_depressions.py. The windowed helpers read band 1 in strips of
whole rows (`read_strips`), so their memory follows the width of a raster, not its
number of cells.
"""

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import numpy as np
from affine import Affine
from rasterio.io import DatasetReader
from rasterio.transform import array_bounds
from rasterio.warp import calculate_default_transform
from rasterio.windows import Window

STRIP_CELLS = 1 << 22
"""Cells per strip of the windowed helpers: about 4.2 M, 34 MB of float64."""

HILLSHADE_HALO_ROWS = 1
"""Rows read above and below a strip for `shade_strip`, those of its gradient."""

_DIGIT_BITS = 16

# Hypsometric color ramp: (position, R, G, B)
COLOR_STOPS = [
    (0.0, 56, 128, 60),  # dark green — valleys
    (0.15, 76, 175, 80),  # green
    (0.30, 139, 195, 74),  # light green
    (0.45, 205, 220, 57),  # lime
    (0.60, 255, 193, 7),  # amber
    (0.75, 161, 110, 60),  # brown
    (0.90, 120, 100, 90),  # dark brown/grey
    (1.0, 245, 245, 240),  # near white — peaks
]


def build_colormap(n_steps: int = 256) -> np.ndarray:
    """Build a 256x3 uint8 colormap from color stops."""
    cmap = np.zeros((n_steps, 3), dtype=np.uint8)
    positions = [s[0] for s in COLOR_STOPS]
    colors = np.array([[s[1], s[2], s[3]] for s in COLOR_STOPS], dtype=np.float64)

    for i in range(n_steps):
        t = i / (n_steps - 1)
        # Find interval
        for k in range(len(positions) - 1):
            if positions[k] <= t <= positions[k + 1]:
                local_t = (t - positions[k]) / (positions[k + 1] - positions[k])
                rgb = colors[k] * (1 - local_t) + colors[k + 1] * local_t
                cmap[i] = np.clip(rgb, 0, 255).astype(np.uint8)
                break
    return cmap


def normalize_elevation(
    valid_data: np.ndarray,
    low_pct: float = 5.0,
    high_pct: float = 95.0,
) -> tuple[float, float]:
    """Compute elevation range for color mapping using percentile clipping.

    Clips extreme outliers (e.g. landfills, quarries, antennas) that would
    compress the useful color range.  Values outside the percentile window
    are clamped to the boundary — they still get colored, just at the
    darkest/brightest end of the ramp.

    Parameters
    ----------
    valid_data : np.ndarray
        1-D array of valid (non-nodata) elevation values.
    low_pct : float
        Lower percentile boundary (default 5).
    high_pct : float
        Upper percentile boundary (default 95).

    Returns
    -------
    tuple[float, float]
        (elev_min, elev_max) to use for 0–1 normalization.
    """
    if valid_data.size == 0:
        return 0.0, 0.0
    lo = float(np.percentile(valid_data, low_pct))
    hi = float(np.percentile(valid_data, high_pct))
    if hi <= lo:
        # Flat terrain — fall back to full range
        lo = float(np.min(valid_data))
        hi = float(np.max(valid_data))
    return lo, hi


def compute_hillshade(
    dem: np.ndarray,
    cellsize: float,
    azimuth: float = 315.0,
    altitude: float = 45.0,
) -> np.ndarray:
    """
    Multi-directional hillshade for natural terrain visualization.

    Uses 4 light directions (NW, NE, SE, SW) averaged with weights.
    NW (315 deg) is dominant (conventional cartographic lighting).
    The ``azimuth`` parameter is kept for backward compatibility but
    is not used — the 4-direction blend replaces single-source lighting.

    Parameters
    ----------
    dem : np.ndarray
        DEM array (in metric CRS for correct gradients)
    cellsize : float
        Cell size in meters
    azimuth : float
        Kept for backward compatibility (ignored in multi-directional mode)
    altitude : float
        Light source altitude in degrees (default: 45)

    Returns
    -------
    np.ndarray
        Hillshade array, values 0–1 (float64)
    """
    azimuths = [315, 45, 135, 225]
    weights = [0.4, 0.2, 0.2, 0.2]

    dzdx = np.gradient(dem, cellsize, axis=1)
    dzdy = np.gradient(dem, cellsize, axis=0)
    slope = np.sqrt(dzdx**2 + dzdy**2)
    slope_rad = np.arctan(slope)
    aspect_rad = np.arctan2(-dzdy, dzdx)

    alt_rad = np.radians(altitude)

    result = np.zeros_like(dem, dtype=np.float64)
    for az, w in zip(azimuths, weights, strict=True):
        az_rad = np.radians(360 - az + 90)
        hs = np.cos(alt_rad) * np.sin(slope_rad) * np.cos(az_rad - aspect_rad) + np.sin(
            alt_rad
        ) * np.cos(slope_rad)
        hs = np.clip(hs, 0, 1)
        result += w * hs

    return np.clip(result, 0, 1)


def colorize_elevation(
    dem: np.ndarray,
    valid: np.ndarray,
    color_min_m: float,
    color_max_m: float,
    hillshade: np.ndarray | None = None,
) -> np.ndarray:
    """
    Colour elevations with the hypsometric ramp and blend in a hillshade.

    Parameters
    ----------
    dem : np.ndarray
        Elevations (m).
    valid : np.ndarray
        Cells with an elevation; the others are transparent.
    color_min_m, color_max_m : float
        Elevations of the two ends of the ramp; lower and higher terrain takes the
        end colours.
    hillshade : np.ndarray, optional
        Finite hillshade (0–1) of the same cells; it darkens the colours to
        ``rgb * (0.3 + 0.7 * hillshade)``.

    Returns
    -------
    np.ndarray
        RGBA image (``dem.shape + (4,)``, uint8), opaque on the valid cells.
    """
    normalized = np.zeros(dem.shape, dtype=np.float64)
    color_range = color_max_m - color_min_m
    if color_range > 0:
        normalized[valid] = (dem[valid] - color_min_m) / color_range
    indices = np.clip((normalized * 255).astype(np.int32), 0, 255)

    rgba = np.zeros((*dem.shape, 4), dtype=np.uint8)
    rgba[..., :3] = build_colormap()[indices]
    rgba[..., 3] = np.where(valid, 255, 0)
    if hillshade is not None:
        blend_factor = 0.3 + 0.7 * hillshade
        for channel in range(3):
            rgba[..., channel] = np.clip(
                rgba[..., channel] * blend_factor, 0, 255
            ).astype(np.uint8)
    return rgba


def valid_elevation(data: np.ndarray, nodata: float | None) -> np.ndarray:
    """Return the cells of ``data`` with an elevation: finite and not ``nodata``."""
    valid = np.isfinite(data)
    if nodata is not None:
        valid &= data != nodata
    return valid


def strip_rows(width: int, cells: int = STRIP_CELLS) -> int:
    """Return the rows of a strip of some ``cells`` cells of a raster ``width`` wide."""
    return max(1, cells // max(width, 1))


@dataclass(frozen=True)
class RasterStrip:
    """
    Rows of band 1 of a raster with the halo rows read around them.

    Attributes
    ----------
    row0 : int
        First row of the strip in the raster.
    rows : int
        Number of rows of the strip.
    data : np.ndarray
        The rows of the strip with the halo rows above and below them, as read.
    offset : int
        Index of the row ``row0`` in ``data``.
    """

    row0: int
    rows: int
    data: np.ndarray
    offset: int

    @property
    def core(self) -> np.ndarray:
        """The rows of the strip without the halo."""
        return self.data[self.offset : self.offset + self.rows]


def read_strips(
    src: DatasetReader, rows_per_strip: int, halo: int = 0
) -> Iterator[RasterStrip]:
    """
    Read band 1 of a raster top to bottom in strips of whole rows.

    Parameters
    ----------
    src : DatasetReader
        Open raster.
    rows_per_strip : int
        Rows of a strip; the last strip has the rows left.
    halo : int
        Rows read above and below each strip as far as the raster has them.

    Yields
    ------
    RasterStrip
        The strips in the order of their rows.
    """
    for row0 in range(0, src.height, rows_per_strip):
        rows = min(rows_per_strip, src.height - row0)
        top = max(row0 - halo, 0)
        bottom = min(row0 + rows + halo, src.height)
        data = src.read(1, window=Window(0, top, src.width, bottom - top))
        yield RasterStrip(row0=row0, rows=rows, data=data, offset=row0 - top)


def shade_strip(
    strip: RasterStrip, nodata: float | None, cellsize_m: float
) -> np.ndarray:
    """
    Hillshade the rows of a strip of elevations.

    `compute_hillshade` of the strip with its nodata as NaN: read with
    `HILLSHADE_HALO_ROWS` rows of halo, the rows equal those of the hillshade of the
    whole raster. Where the gradient reaches nodata the hillshade is undefined; it is
    0 there, the value that the reprojection of the whole hillshade gave such cells
    before (a dark rim along nodata).

    Parameters
    ----------
    strip : RasterStrip
        Elevations read with `HILLSHADE_HALO_ROWS` rows of halo.
    nodata : float or None
        Nodata value of the raster.
    cellsize_m : float
        Cell size (m) of the raster.

    Returns
    -------
    np.ndarray
        Hillshade (0–1, float64) of the rows of the strip, finite everywhere.
    """
    dem = strip.data.astype(np.float64)
    dem[~valid_elevation(strip.data, nodata)] = np.nan
    hillshade = compute_hillshade(dem, cellsize_m)[
        strip.offset : strip.offset + strip.rows
    ]
    hillshade[~np.isfinite(hillshade)] = 0.0
    return hillshade


@dataclass(frozen=True)
class ElevationSummary:
    """
    The valid elevations of a raster.

    Attributes
    ----------
    count : int
        Number of valid cells.
    elevation_min_m, elevation_max_m : float
        Lowest and highest valid elevation.
    color_min_m, color_max_m : float
        `normalize_elevation` of all the valid elevations: the percentile range of
        the colour ramp, or the extremes where the percentiles coincide.
    """

    count: int
    elevation_min_m: float
    elevation_max_m: float
    color_min_m: float
    color_max_m: float


def summarize_elevation(
    src: DatasetReader,
    low_pct: float = 5.0,
    high_pct: float = 95.0,
    rows_per_strip: int | None = None,
) -> ElevationSummary:
    """
    Compute `normalize_elevation` of all valid cells of a raster, strip by strip.

    The percentiles equal those of numpy (``linear`` method) of all the valid values,
    without holding them. The first pass counts the values by the top 16 bits of a key
    that sorts like them; every further pass counts the next 16 bits of the keys in
    the bins that hold the ranks of the percentiles, until the keys, and so the
    values, are known. Float32 rasters and integers of up to 16 bits take two passes;
    other types are compared as float64 and take four. As in numpy, the interpolation
    between two values is float32 arithmetic for a float32 raster, float64 otherwise.

    Parameters
    ----------
    src : DatasetReader
        Open raster; band 1 holds the elevations, its nodata and the non-finite
        values are not valid.
    low_pct, high_pct : float
        Percentiles (0–100) of the colour range, as in `normalize_elevation`.
    rows_per_strip : int, optional
        Rows read at a time (default: `strip_rows` of the width).

    Returns
    -------
    ElevationSummary
        Count, extremes and colour range of the valid elevations.

    Raises
    ------
    ValueError
        If band 1 has no valid cell.
    """
    rows = rows_per_strip or strip_rows(src.width)
    raster_dtype = np.dtype(src.dtypes[0])
    exact_float32 = raster_dtype == np.float32 or (
        raster_dtype.kind in "iu" and raster_dtype.itemsize <= 2
    )
    dtype = np.dtype(np.float32 if exact_float32 else np.float64)
    bits = 8 * dtype.itemsize

    def keys_by_strip() -> Iterator[np.ndarray]:
        for strip in read_strips(src, rows):
            values = strip.data[valid_elevation(strip.data, src.nodata)]
            yield _sort_keys(values.astype(dtype, copy=False))

    count = 0
    key_min, key_max = 1 << bits, -1
    top_counts = np.zeros(1 << _DIGIT_BITS, dtype=np.int64)
    for keys in keys_by_strip():
        if keys.size == 0:
            continue
        count += keys.size
        key_min = min(key_min, int(keys.min()))
        key_max = max(key_max, int(keys.max()))
        top_counts += np.bincount(
            (keys >> (bits - _DIGIT_BITS)).astype(np.intp),
            minlength=1 << _DIGIT_BITS,
        )
    if count == 0:
        raise ValueError("The raster has no valid elevation")

    plans = [_percentile_ranks(count, pct) for pct in (low_pct, high_pct)]
    ranks = sorted({rank for below, above, _ in plans for rank in (below, above)})
    keys_at = _keys_at_ranks(keys_by_strip, bits, top_counts, ranks)
    arithmetic = np.float32 if raster_dtype == np.float32 else np.float64
    lo, hi = (
        _lerp(
            arithmetic(_key_value(keys_at[below], dtype)),
            arithmetic(_key_value(keys_at[above], dtype)),
            weight,
        )
        for below, above, weight in plans
    )
    elevation_min = float(_key_value(key_min, dtype))
    elevation_max = float(_key_value(key_max, dtype))
    if hi <= lo:
        lo, hi = elevation_min, elevation_max
    return ElevationSummary(count, elevation_min, elevation_max, lo, hi)


def _sort_keys(values: np.ndarray) -> np.ndarray:
    """Return unsigned integers in the order of the finite float ``values``."""
    unsigned = np.dtype(f"u{values.dtype.itemsize}")
    raw = values.view(unsigned)
    sign = unsigned.type(1 << (8 * values.dtype.itemsize - 1))
    return np.where(raw & sign, ~raw, raw | sign)


def _key_value(key: int, dtype: np.dtype[Any]) -> np.floating[Any]:
    """Return the float of ``dtype`` whose sort key is ``key``."""
    bits = 8 * dtype.itemsize
    sign = 1 << (bits - 1)
    raw = key ^ sign if key & sign else ~key & ((1 << bits) - 1)
    value: np.floating[Any] = np.array([raw], dtype=f"u{dtype.itemsize}").view(dtype)[0]
    return value


def _percentile_ranks(count: int, pct: float) -> tuple[int, int, float]:
    """Return the ranks and weight of numpy's linear percentile of ``count`` values."""
    virtual = (count - 1) * (pct / 100)
    if virtual >= count - 1:
        return count - 1, count - 1, 0.0
    below = math.floor(virtual)
    return below, below + 1, virtual - below


def _lerp(below: np.floating[Any], above: np.floating[Any], weight: float) -> float:
    """Interpolate between neighbouring order statistics as numpy's percentile does."""
    difference = above - below
    if weight >= 0.5:
        return float(above - difference * (1 - weight))
    return float(below + difference * weight)


def _keys_at_ranks(
    keys_by_strip: Callable[[], Iterator[np.ndarray]],
    bits: int,
    top_counts: np.ndarray,
    ranks: list[int],
) -> dict[int, int]:
    """
    Select the keys at 0-based ranks of all keys, 16 bits per pass.

    Parameters
    ----------
    keys_by_strip : Callable
        Returns a new iterator over the keys of every strip; called once per pass.
    bits : int
        Bits of a key.
    top_counts : np.ndarray
        Number of keys by their top 16 bits.
    ranks : list[int]
        Wanted ranks.

    Returns
    -------
    dict[int, int]
        Key at each rank.
    """
    width = 1 << _DIGIT_BITS
    # Known high bits of the key at each rank and the number of keys below them.
    found = {rank: _locate(top_counts, rank) for rank in ranks}
    known = _DIGIT_BITS
    while known < bits:
        shift = bits - known - _DIGIT_BITS
        prefixes = sorted({prefix for prefix, _ in found.values()})
        counts = {prefix: np.zeros(width, dtype=np.int64) for prefix in prefixes}
        for keys in keys_by_strip():
            high = keys >> (bits - known)
            for prefix in prefixes:
                inside = keys[high == prefix]
                if inside.size:
                    digits = (inside >> shift) & (width - 1)
                    counts[prefix] += np.bincount(
                        digits.astype(np.intp), minlength=width
                    )
        for rank, (prefix, below) in found.items():
            digit, before = _locate(counts[prefix], rank - below)
            found[rank] = ((prefix << _DIGIT_BITS) | digit, below + before)
        known += _DIGIT_BITS
    return {rank: prefix for rank, (prefix, _) in found.items()}


def _locate(counts: np.ndarray, rank: int) -> tuple[int, int]:
    """Return the bin holding the 0-based ``rank`` and the count of the bins before."""
    cumulative = np.cumsum(counts)
    digit = int(np.searchsorted(cumulative, rank, side="right"))
    return digit, int(cumulative[digit - 1]) if digit else 0


def thumbnail_size(width: int, height: int, max_size: int) -> tuple[int, int]:
    """
    Return the size of an image shrunk to fit ``max_size`` px.

    The rule of `PIL.Image.Image.thumbnail`, which the overlays applied to the image
    at full resolution: the aspect ratio is kept, and an image that fits (or a
    ``max_size`` of 0) keeps its size.
    """
    if not max_size or (width <= max_size and height <= max_size):
        return width, height

    def round_aspect(number: float, key: Callable[[int], float]) -> int:
        return max(min(math.floor(number), math.ceil(number), key=key), 1)

    aspect = width / height
    x = y = max_size
    if x / y >= aspect:
        x = round_aspect(y * aspect, key=lambda n: abs(aspect - n / y))
    else:
        y = round_aspect(x / aspect, key=lambda n: 0 if n == 0 else abs(aspect - x / n))
    return x, y


@dataclass(frozen=True)
class OverlayGrid:
    """
    Pixel grid of an overlay PNG in its target CRS.

    Attributes
    ----------
    transform : Affine
        Transform of the PNG pixels.
    width, height : int
        Size of the PNG (px), at most ``max_size``.
    full_transform : Affine
        Transform of the reprojected raster at its own resolution
        (`calculate_default_transform`), the image the overlays shrank before.
    full_width, full_height : int
        Size of that image; the PNG has its bounds.
    """

    transform: Affine
    width: int
    height: int
    full_transform: Affine
    full_width: int
    full_height: int

    @property
    def downsampled(self) -> bool:
        """Whether the PNG has fewer pixels than the reprojected raster."""
        return (self.width, self.height) != (self.full_width, self.full_height)

    @property
    def bounds(self) -> list[list[float]]:
        """Return ``[[lat_min, lon_min], [lat_max, lon_max]]`` for Leaflet."""
        lon_min = self.full_transform.c
        lat_max = self.full_transform.f
        lon_max = lon_min + self.full_width * self.full_transform.a
        lat_min = lat_max + self.full_height * self.full_transform.e
        return [[lat_min, lon_min], [lat_max, lon_max]]


def overlay_grid(
    src_crs: Any,
    transform: Affine,
    width: int,
    height: int,
    max_size: int,
    dst_crs: str = "EPSG:4326",
) -> OverlayGrid:
    """
    Return the grid of an overlay PNG of a raster, at most ``max_size`` px.

    Parameters
    ----------
    src_crs : CRS or str
        CRS of the raster.
    transform : Affine
        Transform of the raster.
    width, height : int
        Size of the raster (cells).
    max_size : int
        Longest side of the PNG (px); 0 keeps the reprojected resolution.
    dst_crs : str
        CRS of the PNG.

    Returns
    -------
    OverlayGrid
        The grid of `calculate_default_transform` over the bounds of the raster and
        the PNG grid with the same bounds.
    """
    west, south, east, north = array_bounds(height, width, transform)
    full_transform, full_width, full_height = calculate_default_transform(
        src_crs, dst_crs, width, height, left=west, bottom=south, right=east, top=north
    )
    png_width, png_height = thumbnail_size(full_width, full_height, max_size)
    return OverlayGrid(
        transform=full_transform
        * Affine.scale(full_width / png_width, full_height / png_height),
        width=png_width,
        height=png_height,
        full_transform=full_transform,
        full_width=full_width,
        full_height=full_height,
    )


def reduction_factor(height: int, width: int, size_px: int) -> int:
    """Return the side (cells) of the blocks that reduce a raster to ``size_px``."""
    return max(1, math.ceil(max(height, width) / max(size_px, 1)))


def reduce_into(
    target: np.ndarray,
    data: np.ndarray,
    row0: int,
    col0: int,
    factor: int,
    ufunc: np.ufunc,
) -> None:
    """
    Reduce a window of a raster into its grid of blocks.

    The blocks are ``factor`` x ``factor`` cells of the raster from its first row and
    column; block ``(i, j)`` is cell ``(i, j)`` of ``target``. The cells of ``data``
    are combined into the blocks they fall in, and with what ``target`` holds, by
    ``ufunc`` (``np.maximum``, ``np.add``), so windows that split a block add up.

    Parameters
    ----------
    target : np.ndarray
        Grid of blocks, ``ceil(height / factor)`` x ``ceil(width / factor)``.
    data : np.ndarray
        The window: cells from row ``row0`` and column ``col0`` of the raster.
    row0, col0 : int
        Position of the window in the raster.
    factor : int
        Side of a block (cells).
    ufunc : np.ufunc
        Binary ufunc that combines cells.
    """
    if factor == 1:
        reduced = data
    else:
        rows = _block_starts(row0, data.shape[0], factor)
        cols = _block_starts(col0, data.shape[1], factor)
        reduced = ufunc.reduceat(ufunc.reduceat(data, rows, axis=0), cols, axis=1)
    top, left = row0 // factor, col0 // factor
    view = target[top : top + reduced.shape[0], left : left + reduced.shape[1]]
    ufunc(view, reduced, out=view)


def _block_starts(start: int, length: int, factor: int) -> np.ndarray:
    """Return the indexes in a window where the blocks of ``factor`` cells start."""
    first = -start % factor
    starts = np.arange(first, length, factor)
    return np.concatenate(([0], starts)) if first else starts
