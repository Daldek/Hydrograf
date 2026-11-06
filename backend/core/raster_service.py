"""On-the-fly watershed delineation from a point in a window of the rasters.

The precise mode delineates the watershed of a point with pyflwdir on the flow
directions of the preprocessing. It reads them and the DEM only in a window
around the precomputed watershed of the point (the bounding box of its
sub-catchments plus WINDOW_MARGIN_M) and grows the window while the delineated
watershed touches its edge: a cell beyond the window can drain into the
watershed only through a cell on that edge, so the result is the one of the
whole rasters. The DEM must be on the grid of the flow directions (the same
transform and shape). A window of more than MAX_WINDOW_CELLS cells is refused
before it is read. The result is a Shapely polygon, the area and the elevations
of the watershed.
"""

import logging
from typing import Any

import numpy as np
import pyflwdir
import rasterio
from rasterio.features import shapes
from rasterio.transform import Affine
from rasterio.windows import Window
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from core.config import get_settings
from core.errors import StoreUnavailableError, UnsupportedError
from core.raster_io import RasterWindow, cells_window, read_window

logger = logging.getLogger(__name__)

# Margin [m] around the bounding box of the precomputed watershed of the point.
# That watershed holds the one delineated from the point, so the margin only
# covers small differences between the database and the rasters.
WINDOW_MARGIN_M = 50.0
# Largest window [cells] of a delineation: 1000 km² of 5 m cells. A delineation
# peaks at about 35 bytes per cell of its window plus GDAL's block cache
# (measured 2026-11-06 on a window of 16 million cells filled by the watershed:
# 535 MB with a cache of 16 MB, 607 MB with the default), about 1.5 GB at the cap.
MAX_WINDOW_CELLS = 40_000_000
# A side of the window that the watershed touches moves out by half the size
# of the window, by at least this many cells (as core.divide_flow_path does).
_MIN_GROWTH_CELLS = 64
# pyflwdir's D8 nodata, given to the cells off the DEM
_D8_NODATA = 247


def delineate_from_point(
    x: float,
    y: float,
    bounds_2180: tuple[float, float, float, float],
    max_cells: int = MAX_WINDOW_CELLS,
) -> dict[str, Any]:
    """Delineate the watershed of a point in a window of the rasters.

    Parameters
    ----------
    x, y : float
        Easting and northing in EPSG:2180 (PL-1992).
    bounds_2180 : tuple[float, float, float, float]
        Bounding box (minx, miny, maxx, maxy) in EPSG:2180 of the precomputed
        watershed of the point; with the point and WINDOW_MARGIN_M the first
        window.
    max_cells : int
        Largest window [cells].

    Returns
    -------
    dict
        ``polygon`` : Shapely Polygon/MultiPolygon (EPSG:2180)
        ``stats``   : dict with area_m2 and elevation_min/max/mean_m

    Raises
    ------
    FileNotFoundError
        Without the flow direction or the DEM raster.
    StoreUnavailableError
        ``store_unavailable`` (503, ``raster_grids_differ``) when the DEM has
        another transform or shape than the flow directions.
    UnsupportedError
        ``unsupported`` (422, ``window_too_large``) when the window would hold
        more than ``max_cells`` cells.
    ValueError
        When the point is off the rasters or its watershed is empty.
    """
    cfg = get_settings()
    fdir_path = cfg.resolve_flowdir_path()
    if not fdir_path:
        raise FileNotFoundError("Flow direction raster not found")
    dem_path = cfg.resolve_dem_path()
    if not dem_path:
        raise FileNotFoundError("DEM raster not found")

    with rasterio.open(fdir_path) as fdir_src, rasterio.open(dem_path) as dem_src:
        _require_one_grid(fdir_src, dem_src)
        row, col = fdir_src.index(x, y)
        if not (0 <= row < fdir_src.height and 0 <= col < fdir_src.width):
            raise ValueError(f"Point ({x}, {y}) is outside the raster extent")

        minx, miny, maxx, maxy = bounds_2180
        window = cells_window(
            fdir_src.transform,
            (min(minx, x), min(miny, y), max(maxx, x), max(maxy, y)),
            WINDOW_MARGIN_M,
        )
        growths = 0
        while True:
            cells = int(window.height) * int(window.width)
            if cells > max_cells:
                raise UnsupportedError(
                    "precise_window_too_large",
                    reason="window_too_large",
                    cells=cells,
                    max_cells=max_cells,
                )
            fdir = read_window(fdir_src, window)
            dem = read_window(dem_src, window)
            r, c = row - int(window.row_off), col - int(window.col_off)
            mask = _basin(fdir, dem, r, c)
            grown = _grown(window, mask, fdir_src.height, fdir_src.width)
            if grown is None:
                break
            window = grown
            growths += 1

    cell_area_m2 = abs(fdir.transform.a * fdir.transform.e)
    n_cells = int(np.count_nonzero(mask))
    logger.info(
        "Delineated from row=%d col=%d: %d cells, %.2f km2 "
        "(window of %d x %d cells, %d growths)",
        row,
        col,
        n_cells,
        n_cells * cell_area_m2 / 1_000_000,
        window.height,
        window.width,
        growths,
    )
    if n_cells == 0:
        raise ValueError(
            f"Empty watershed mask for point ({x}, {y}) at row={row}, col={col}"
        )

    polygon = _vectorize(mask, fdir.transform)
    if polygon is None:
        raise ValueError("Failed to vectorize watershed mask")
    return {"polygon": polygon, "stats": _stats(mask, cell_area_m2, dem)}


def _require_one_grid(
    fdir_src: rasterio.DatasetReader, dem_src: rasterio.DatasetReader
) -> None:
    """Refuse a DEM that is not on the grid of the flow directions.

    Raises
    ------
    StoreUnavailableError
        ``store_unavailable`` (``raster_grids_differ``) when the DEM has another
        transform or shape than the flow directions.
    """
    if (dem_src.shape, dem_src.transform) == (fdir_src.shape, fdir_src.transform):
        return
    logger.error(
        "Precise delineation: the DEM %s (%d x %d cells, transform %s) is not on "
        "the grid of the flow directions %s (%d x %d cells, transform %s)",
        dem_src.name,
        dem_src.height,
        dem_src.width,
        dem_src.transform.to_gdal(),
        fdir_src.name,
        fdir_src.height,
        fdir_src.width,
        fdir_src.transform.to_gdal(),
    )
    raise StoreUnavailableError("raster_grids_differ", reason="raster_grids_differ")


def _basin(fdir: RasterWindow, dem: RasterWindow, row: int, col: int) -> np.ndarray:
    """Cells of the window that drain to cell (row, col) of the window.

    The saved flow directions use 0 both for no data and for pits: the cells
    off the DEM become pyflwdir's nodata and the cell of the point a pit, the
    outlet pyflwdir's basins start from. A cell flowing out of the window is a
    pit of pyflwdir, so a watershed cut by the window touches its edge.
    """
    d8 = fdir.data.astype(np.uint8)
    if dem.nodata is not None:
        d8[dem.data == dem.nodata] = _D8_NODATA
    d8[row, col] = 0
    flw = pyflwdir.from_array(d8, ftype="d8", transform=fdir.transform, latlon=False)
    basins = flw.basins(idxs=[np.ravel_multi_index((row, col), d8.shape)])
    mask: np.ndarray = basins > 0
    return mask


def _grown(window: Window, mask: np.ndarray, height: int, width: int) -> Window | None:
    """Move out each side of the window that the watershed touches; None if none.

    A side at the edge of the raster (``height`` x ``width`` cells) stays.
    """
    row0, col0 = int(window.row_off), int(window.col_off)
    row1, col1 = row0 + int(window.height), col0 + int(window.width)
    rows = max(_MIN_GROWTH_CELLS, int(window.height) // 2)
    cols = max(_MIN_GROWTH_CELLS, int(window.width) // 2)
    grown = (
        max(row0 - rows, 0) if row0 > 0 and mask[0, :].any() else row0,
        max(col0 - cols, 0) if col0 > 0 and mask[:, 0].any() else col0,
        min(row1 + rows, height) if row1 < height and mask[-1, :].any() else row1,
        min(col1 + cols, width) if col1 < width and mask[:, -1].any() else col1,
    )
    if grown == (row0, col0, row1, col1):
        return None
    return Window(grown[1], grown[0], grown[3] - grown[1], grown[2] - grown[0])


def _vectorize(mask: np.ndarray, transform: Affine) -> BaseGeometry | None:
    """Convert the boolean mask to a Shapely geometry via rasterio."""
    geoms = [
        shape(geom_dict)
        for geom_dict, value in shapes(mask.astype(np.uint8), transform=transform)
        if value == 1
    ]
    if not geoms:
        return None
    return unary_union(geoms)


def _stats(mask: np.ndarray, cell_area_m2: float, dem: RasterWindow) -> dict[str, Any]:
    """Area and elevations of the cells of the mask."""
    dem_vals = dem.data[mask]
    if dem.nodata is not None:
        dem_vals = dem_vals[dem_vals != dem.nodata]
    has_dem = len(dem_vals) > 0
    return {
        "area_m2": float(np.sum(mask) * cell_area_m2),
        "elevation_min_m": float(np.min(dem_vals)) if has_dem else 0.0,
        "elevation_max_m": float(np.max(dem_vals)) if has_dem else 0.0,
        "elevation_mean_m": float(np.mean(dem_vals)) if has_dem else 0.0,
    }
