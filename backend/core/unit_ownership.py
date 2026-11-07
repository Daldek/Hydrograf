"""Rasterize PGW owners and extend them inside the existing DEM domain only."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fiona
import numpy as np
import rasterio
from rasterio.features import rasterize
from scipy.spatial import cKDTree
from shapely.geometry import shape


@dataclass
class PgwOwners:
    """PGW codes and owned cells on exactly the given DEM's grid."""

    codes: tuple[str, ...]
    cells: np.memmap
    valid: np.memmap
    pgw_area_cells: int


def nearest_valid_owners(
    owners: np.ndarray, valid: np.ndarray, *, tile_pixels: int = 512
) -> None:
    """Fill unowned input pixels by their nearest *original* owner pixel.

    A seed strictly surrounded by owner pixels cannot be the nearest seed to
    any unowned cell: one of its four owned neighbours is closer. Keep only
    the owned pixels bordering a zero cell in a KD-tree, built strip by strip
    to avoid a whole-area distance/index array. Queries operate on bounded
    core tiles; newly assigned pixels never become seeds.
    """
    if owners.shape != valid.shape or tile_pixels < 1:
        raise ValueError("owners and valid must share a shape; tile must be positive")
    nrows, ncols = owners.shape
    locations = []
    codes = []
    for row in range(0, nrows, tile_pixels):
        end = min(row + tile_pixels, nrows)
        pad = np.pad(owners[row:end], ((1, 1), (1, 1)), mode="constant")
        if row > 0:
            pad[0, 1:-1] = owners[row - 1]
        if end < nrows:
            pad[-1, 1:-1] = owners[end]
        central = pad[1:-1, 1:-1]
        boundary = (central > 0) & (
            (pad[:-2, 1:-1] == 0)
            | (pad[2:, 1:-1] == 0)
            | (pad[1:-1, :-2] == 0)
            | (pad[1:-1, 2:] == 0)
        )
        rows, cols = np.nonzero(boundary)
        if rows.size:
            locations.append(np.column_stack((rows + row, cols)).astype(np.int32))
            codes.append(central[rows, cols].copy())
    if not locations:
        if np.any((owners == 0) & valid):
            raise ValueError("PGW raster has no seed cells for the valid input")
        return
    seeds = np.concatenate(locations)
    seed_codes = np.concatenate(codes)
    tree = cKDTree(seeds)
    for row in range(0, nrows, tile_pixels):
        end_row = min(row + tile_pixels, nrows)
        for col in range(0, ncols, tile_pixels):
            end_col = min(col + tile_pixels, ncols)
            block = owners[row:end_row, col:end_col]
            missing = (valid[row:end_row, col:end_col] != 0) & (block == 0)
            if not np.any(missing):
                continue
            r, c = np.nonzero(missing)
            queries = np.column_stack((r + row, c + col))
            _, nearest = tree.query(queries, workers=1)
            block[missing] = seed_codes[nearest]


def load_pgw_owners(
    dem_path: Path, units_path: Path, output_dir: Path
) -> PgwOwners:
    """Partition every valid input DEM cell among intersecting river PGW owners.

    The outside-PGW cells are assigned to a nearest existing unit; this never
    changes the input domain, DEM nodata, or the run's base grid. Direct lake
    polygons already lie inside the river catchments and need no owner.
    """
    with fiona.open(units_path, layer="obszar") as source:
        area = shape(next(iter(source))["geometry"])
    shapes: list[tuple[str, Any]] = []
    for layer in ("Zlewnie_JCWP_rzecznych", "Pozostale_obszary_JCWP"):
        with fiona.open(units_path, layer=layer) as source:
            for feature in source:
                clipped = shape(feature["geometry"]).intersection(area)
                if not clipped.is_empty and clipped.area > 0:
                    shapes.append((str(feature["properties"]["MS_KOD"]), clipped))
    shapes.sort(key=lambda item: item[0])
    if not shapes or len(shapes) > 254:
        raise ValueError("PGW units must contain between 1 and 254 owners")
    output_dir.mkdir(parents=True, exist_ok=True)
    with rasterio.open(dem_path) as source:
        if source.nodata is None or source.crs is None or source.crs.to_epsg() != 2180:
            raise ValueError("DEM requires EPSG:2180 and a nodata value")
        cell_shape = source.shape
        owners = np.lib.format.open_memmap(
            output_dir / "owners.npy", mode="w+", dtype="uint8", shape=cell_shape
        )
        owners[:] = 0
        rasterize(
            [(geometry, i) for i, (_, geometry) in enumerate(shapes, start=1)],
            out=owners,
            transform=source.transform,
            all_touched=False,
        )
        area_mask = rasterize(
            [(area, 1)], out_shape=cell_shape, transform=source.transform,
            dtype="uint8", all_touched=False,
        )
        pgw_area_cells = int(np.count_nonzero(area_mask))
        if np.any((area_mask > 0) & (owners == 0)):
            raise ValueError("PGW polygons leave an unowned cell inside obszar")
        del area_mask
        valid = np.lib.format.open_memmap(
            output_dir / "valid_input.npy", mode="w+", dtype="bool", shape=cell_shape
        )
        for _, window in source.block_windows(1):
            cell_block = source.read(1, window=window)
            row, col = int(window.row_off), int(window.col_off)
            valid[row : row + cell_block.shape[0], col : col + cell_block.shape[1]] = (
                cell_block != source.nodata
            )
        owners[~valid] = 0
        nearest_valid_owners(owners, valid)
        if np.any((owners == 0) & valid):
            raise ValueError("A valid DEM cell has no owner")
    return PgwOwners(tuple(code for code, _ in shapes), owners, valid, pgw_area_cells)
