"""
Generate depression (blue spot) data from DEM difference and insert into PostGIS.

Computes terrain depressions as the difference between filled and original DEM,
vectorizes connected components, inserts geometry + metrics into depressions table,
and optionally generates a PNG overlay for Leaflet display.

The rasters are read in square tiles, so the memory does not grow with the grid. The
depression cells of a tile are labelled (4-connectivity, as `scipy.ndimage.label` of
the whole raster) and polygonized; a component that touches a seam to a tile not yet
read waits, with its partial statistics and polygon, and the components that meet
across a seam are joined (union-find) into one depression with one polygon. A
depression is handed on as soon as it is complete, so the database insert runs in
batches, and the overlay is drawn from the depression cells and depth of square blocks
of cells.

Usage:
    python -m scripts.generate_depressions \
        --dem ../data/nmt/dem.tif --filled ../data/nmt/dem_filled.tif

    python -m scripts.generate_depressions \
        --dem ../data/nmt/dem.tif --filled ../data/nmt/dem_filled.tif \
        --output-png ../frontend/data/depressions.png \
        --output-meta ../frontend/data/depressions.json
"""

import argparse
import io
import itertools
import json
import logging
import math
import sys
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import shapely
from affine import Affine
from PIL import Image
from rasterio.features import shapes
from rasterio.warp import Resampling, reproject
from rasterio.windows import Window
from scipy.ndimage import label
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from core.zonal_stats import zonal_bincount, zonal_max
from utils.dem_color import overlay_grid, reduce_into, reduction_factor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Depth color ramp: light blue (shallow) → dark blue (deep)
DEPTH_COLORS = [
    (0.0, 0xBB, 0xDE, 0xFB),  # #BBDEFB — very shallow
    (0.2, 0x64, 0xB5, 0xF6),  # #64B5F6
    (0.5, 0x21, 0x96, 0xF3),  # #2196F3
    (0.8, 0x0D, 0x47, 0xA1),  # #0D47A1
    (1.0, 0x01, 0x27, 0x64),  # #012764 — deepest
]

TILE_CELLS = 2048
"""Side (cells) of the square tiles read at a time: 4.2 M cells, some 200 MB."""

OVERVIEW_PX = 2048
"""Longest side (blocks) of the block rasters of the overlay."""

INSERT_BATCH_ROWS = 10_000
"""Depressions copied into the database at a time."""


def build_depth_colormap(n_steps: int = 256) -> np.ndarray:
    """Build a 256x3 uint8 colormap for depth values."""
    cmap = np.zeros((n_steps, 3), dtype=np.uint8)
    positions = [s[0] for s in DEPTH_COLORS]
    colors = np.array([[s[1], s[2], s[3]] for s in DEPTH_COLORS], dtype=np.float64)

    for i in range(n_steps):
        t = i / (n_steps - 1) if n_steps > 1 else 0
        for k in range(len(positions) - 1):
            if positions[k] <= t <= positions[k + 1]:
                local_t = (t - positions[k]) / (positions[k + 1] - positions[k])
                rgb = colors[k] * (1 - local_t) + colors[k + 1] * local_t
                cmap[i] = np.clip(rgb, 0, 255).astype(np.uint8)
                break
    return cmap


@dataclass(frozen=True)
class DepthOverview:
    """
    Depression cells and depth by square blocks of cells, the source of the overlay.

    Attributes
    ----------
    cells : np.ndarray
        Number of depression cells of each block (float64).
    depth_sum_m : np.ndarray
        Sum of the depth of the depression cells of each block (float64).
    factor : int
        Side of a block (cells).
    max_depth_m : float
        Depth of the deepest depression cell (0 without one).
    transform : Affine
        Transform of the blocks.
    crs : CRS
        CRS of the rasters.
    raster_transform : Affine
        Transform of the cells.
    raster_shape : tuple[int, int]
        Rows and columns of the cells.
    """

    cells: np.ndarray
    depth_sum_m: np.ndarray
    factor: int
    max_depth_m: float
    transform: Affine
    crs: Any
    raster_transform: Affine
    raster_shape: tuple[int, int]


@dataclass
class _Pending:
    """A component that touches an open seam: its partial statistics and polygon."""

    cells: int
    depth_sum_m: float
    max_depth_m: float
    pieces: list[BaseGeometry]
    members: list[int] = field(default_factory=list)


class DepressionScan:
    """
    Depressions of a DEM and its filled DEM, computed tile by tile.

    Iterating (once) yields one dict per depression as soon as it is complete:
    ``wkt`` (polygon in the CRS of the rasters), ``volume_m3``, ``area_m2``,
    ``max_depth_m`` and ``mean_depth_m``. After the iteration ``overview`` holds the
    depression cells and depth by blocks for the overlay, ``count`` the number of
    depressions and ``cells`` that of their cells.

    Parameters
    ----------
    dem_path : str
        Original DEM raster (GeoTIFF or VRT).
    filled_path : str
        Filled DEM raster on the grid of the DEM.
    min_depth_m : float
        Minimum depth of a depression cell.
    tile_cells : int
        Side (cells) of the square tiles read at a time.
    overview_px : int
        Longest side (blocks) of the block rasters of the overlay.
    """

    def __init__(
        self,
        dem_path: str,
        filled_path: str,
        min_depth_m: float = 0.001,
        tile_cells: int = TILE_CELLS,
        overview_px: int = OVERVIEW_PX,
    ) -> None:
        self.dem_path = dem_path
        self.filled_path = filled_path
        self.min_depth_m = min_depth_m
        self.tile_cells = tile_cells
        self.overview_px = overview_px
        self.count = 0
        self.cells = 0
        self._started = False
        self._overview: DepthOverview | None = None

    @property
    def overview(self) -> DepthOverview:
        """Depressions by blocks; available once the iteration has finished."""
        if self._overview is None:
            raise RuntimeError("The depression scan has not finished")
        return self._overview

    def __iter__(self) -> Iterator[dict[str, Any]]:
        """Run the scan; a scan runs once."""
        if self._started:
            raise RuntimeError("A depression scan can be iterated once")
        self._started = True
        return self._scan()

    def _scan(self) -> Iterator[dict[str, Any]]:
        with (
            rasterio.open(self.dem_path) as dem_src,
            rasterio.open(self.filled_path) as filled_src,
        ):
            height, width = dem_src.height, dem_src.width
            if (filled_src.height, filled_src.width) != (height, width):
                raise ValueError(
                    f"The filled DEM is {filled_src.width}x{filled_src.height} cells, "
                    f"the DEM {width}x{height}"
                )
            transform = dem_src.transform
            cell_area = abs(transform.a) * abs(transform.a)
            factor = reduction_factor(height, width, self.overview_px)
            blocks = (math.ceil(height / factor), math.ceil(width / factor))
            block_cells, block_depth_sum = np.zeros(blocks), np.zeros(blocks)
            seams = _Seams(width)
            volume_m3 = 0.0
            depth_range = [math.inf, 0.0]
            tiles = _tiles(height, width, self.tile_cells)
            logger.info(
                "Depressions of %dx%d cells in %d tiles of %d cells",
                width,
                height,
                len(tiles),
                self.tile_cells,
            )
            for row0, col0, rows, cols in tiles:
                window = Window(col0, row0, cols, rows)
                depth, mask = _depth(
                    dem_src.read(1, window=window),
                    filled_src.read(1, window=window),
                    dem_src.nodata,
                    filled_src.nodata,
                    self.min_depth_m,
                )
                reduce_into(
                    block_cells, mask.astype(np.float64), row0, col0, factor, np.add
                )
                reduce_into(block_depth_sum, depth, row0, col0, factor, np.add)
                if mask.any():
                    self.cells += int(mask.sum())
                    depth_range[0] = min(depth_range[0], float(depth[mask].min()))
                    depth_range[1] = max(depth_range[1], float(depth[mask].max()))
                tile = _Tile(
                    row0,
                    col0,
                    top=row0 > 0,
                    left=col0 > 0,
                    bottom=row0 + rows < height,
                    right=col0 + cols < width,
                )
                depressions = _tile_depressions(depth, mask, tile, seams)
                for row in _rows(depressions, transform, cell_area):
                    self.count += 1
                    volume_m3 += row["volume_m3"]
                    yield row
                if col0 + cols == width:
                    logger.info(
                        "  rows %d-%d: %d depressions so far",
                        row0,
                        row0 + rows,
                        self.count,
                    )
            self._overview = DepthOverview(
                cells=block_cells,
                depth_sum_m=block_depth_sum,
                factor=factor,
                max_depth_m=depth_range[1],
                transform=transform * Affine.scale(factor),
                crs=dem_src.crs,
                raster_transform=transform,
                raster_shape=(height, width),
            )
        if self.count:
            logger.info(
                "Depression pixels: %d (depth range: %.3f–%.3f m); %d depressions "
                "(total volume: %.1f m³)",
                self.cells,
                depth_range[0],
                depth_range[1],
                self.count,
                volume_m3,
            )
        else:
            logger.info("No depressions found")


def compute_depressions(
    dem_path: str,
    filled_path: str,
    min_depth_m: float = 0.001,
    tile_cells: int = TILE_CELLS,
    overview_px: int = OVERVIEW_PX,
) -> DepressionScan:
    """
    Compute terrain depressions from DEM difference.

    A depression is a 4-connected component of the cells whose depth, filled minus
    original elevation, is at least ``min_depth_m`` where both rasters have data.
    Nothing is computed until the returned scan is iterated.

    Parameters
    ----------
    dem_path : str
        Path to original DEM raster
    filled_path : str
        Path to filled DEM raster
    min_depth_m : float
        Minimum depth to consider as depression (default: 1mm)
    tile_cells : int
        Side (cells) of the square tiles read at a time.
    overview_px : int
        Longest side (blocks) of the block rasters of the overlay.

    Returns
    -------
    DepressionScan
        Iterate it once for the depression dicts (wkt, volume_m3, area_m2,
        max_depth_m, mean_depth_m); then its ``overview`` feeds `generate_overlay`.
    """
    return DepressionScan(dem_path, filled_path, min_depth_m, tile_cells, overview_px)


@dataclass(frozen=True)
class _Tile:
    """Position of a tile and which of its edges are seams to other tiles."""

    row0: int
    col0: int
    top: bool
    left: bool
    bottom: bool
    right: bool


def _tiles(height: int, width: int, side: int) -> list[tuple[int, int, int, int]]:
    """Return the tiles ``(row0, col0, rows, cols)`` row by row, left to right."""
    return [
        (row0, col0, min(side, height - row0), min(side, width - col0))
        for row0 in range(0, height, side)
        for col0 in range(0, width, side)
    ]


def _depth(
    dem: np.ndarray,
    filled: np.ndarray,
    nodata_dem: float | None,
    nodata_filled: float | None,
    min_depth_m: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return the depth (float64, 0 outside depressions) and the depression cells."""
    depth = filled.astype(np.float64)
    depth -= dem
    if nodata_dem is not None:
        depth[dem == nodata_dem] = 0
    if nodata_filled is not None:
        depth[filled == nodata_filled] = 0
    depth[depth < min_depth_m] = 0
    mask = depth > 0
    depth[~mask] = 0  # also the NaN of an input without a nodata value
    return depth, mask


def _tile_depressions(
    depth: np.ndarray, mask: np.ndarray, tile: _Tile, seams: "_Seams"
) -> list[tuple[int, float, float, BaseGeometry]]:
    """
    Label and polygonize the depression cells of a tile.

    Returns the depressions that are complete, as ``(cells, depth sum, max depth,
    polygon)`` with the polygon in cell coordinates of the whole grid: those of the
    tile that touch no seam, then those that the seams of the tile complete.
    """
    labels, n_labels = label(mask)
    complete: list[tuple[int, float, float, BaseGeometry]] = []
    pieces: dict[int, _Pending] = {}
    if n_labels:
        counts = zonal_bincount(labels, max_label=n_labels)
        depth_sums = zonal_bincount(labels, weights=depth, max_label=n_labels)
        max_depths = zonal_max(labels, depth, n_labels)

        on_seam = np.zeros(n_labels + 1, dtype=bool)
        for is_seam, edge in (
            (tile.top, labels[0]),
            (tile.bottom, labels[-1]),
            (tile.left, labels[:, 0]),
            (tile.right, labels[:, -1]),
        ):
            if is_seam:
                on_seam[edge] = True
        on_seam[0] = False

        # Cell coordinates of the whole grid: exact, so pieces meet on the seams.
        to_grid = Affine.translation(tile.col0, tile.row0)
        for geom, value in shapes(labels, mask=labels > 0, transform=to_grid):
            component = int(value)
            cells = int(counts[component])
            depth_sum = float(depth_sums[component])
            max_depth = float(max_depths[component - 1])
            if on_seam[component]:
                pieces[component] = _Pending(cells, depth_sum, max_depth, [shape(geom)])
            else:
                complete.append((cells, depth_sum, max_depth, shape(geom)))
    for group in seams.add(labels, n_labels, pieces, tile):
        polygon = group.pieces[0]
        if len(group.pieces) > 1:
            # The union keeps the seam crossings as collinear vertices; drop them.
            polygon = shapely.simplify(shapely.union_all(group.pieces), 0.0)
        complete.append((group.cells, group.depth_sum_m, group.max_depth_m, polygon))
    return complete


class _Seams:
    """
    The components that touch a seam still open, joined by union-find.

    Tiles come row by row, left to right. The seams still open are the lower edges of
    the read tiles whose tile below is not read yet (``lower``, one id per column) and
    the right edge of the last tile (``right``). A component is complete when none of
    the components joined to it touches an open seam; its group is then handed back
    and forgotten.
    """

    def __init__(self, width: int) -> None:
        self._parent: dict[int, int] = {}
        self._groups: dict[int, _Pending] = {}
        self._next_id = 1
        self.lower = np.zeros(width, dtype=np.int64)
        self.right = np.zeros(0, dtype=np.int64)

    def add(
        self,
        labels: np.ndarray,
        n_labels: int,
        pieces: dict[int, _Pending],
        tile: _Tile,
    ) -> list[_Pending]:
        """
        Add the seam components of a tile and return the groups now complete.

        Parameters
        ----------
        labels : np.ndarray
            Component labels of the tile (0 = no depression).
        n_labels : int
            Highest label.
        pieces : dict[int, _Pending]
            The components of the tile that touch one of its seams, by label.
        tile : _Tile
            Position and seams of the tile.

        Returns
        -------
        list[_Pending]
            Groups of joined components that no open seam touches any more.
        """
        ids = np.zeros(n_labels + 1, dtype=np.int64)
        for component, piece in pieces.items():
            cid = self._next_id
            self._next_id += 1
            ids[component] = cid
            piece.members.append(cid)
            self._parent[cid] = cid
            self._groups[cid] = piece

        cols_slice = slice(tile.col0, tile.col0 + labels.shape[1])
        if tile.left:
            self._join(ids[labels[:, 0]], self.right)
        if tile.top:
            self._join(ids[labels[0]], self.lower[cols_slice])
        self.lower[cols_slice] = ids[labels[-1]] if tile.bottom else 0
        self.right = ids[labels[:, -1]] if tile.right else np.zeros(0, np.int64)
        return self._complete()

    def _find(self, cid: int) -> int:
        root = cid
        while (parent := self._parent[root]) != root:
            root = parent
        while (parent := self._parent[cid]) != root:
            self._parent[cid] = root
            cid = parent
        return root

    def _join(self, here: np.ndarray, there: np.ndarray) -> None:
        """Join the components on both sides of a seam where both hold one."""
        touching = (here > 0) & (there > 0)
        if not touching.any():
            return
        pairs = np.unique(np.stack((here[touching], there[touching]), axis=1), axis=0)
        for a, b in pairs.tolist():
            root_a, root_b = self._find(a), self._find(b)
            if root_a == root_b:
                continue
            keep, absorbed = root_a, root_b
            if len(self._groups[root_a].members) < len(self._groups[root_b].members):
                keep, absorbed = root_b, root_a
            self._parent[absorbed] = keep
            group, other = self._groups[keep], self._groups.pop(absorbed)
            group.cells += other.cells
            group.depth_sum_m += other.depth_sum_m
            group.max_depth_m = max(group.max_depth_m, other.max_depth_m)
            group.pieces.extend(other.pieces)
            group.members.extend(other.members)

    def _complete(self) -> list[_Pending]:
        """Hand back and forget the groups that touch no open seam."""
        open_ids = np.unique(np.concatenate((self.lower, self.right)))
        open_roots = {self._find(cid) for cid in open_ids.tolist() if cid}
        complete = [root for root in self._groups if root not in open_roots]
        groups = []
        for root in complete:
            group = self._groups.pop(root)
            for member in group.members:
                del self._parent[member]
            groups.append(group)
        return groups


def _rows(
    depressions: list[tuple[int, float, float, BaseGeometry]],
    transform: Affine,
    cell_area_m2: float,
) -> list[dict[str, Any]]:
    """Return the database rows of depressions with their polygons in grid cells."""
    if not depressions:
        return []

    def to_crs(xy: np.ndarray) -> np.ndarray:
        # The arithmetic of GDAL's polygonizer: the same coordinates as `shapes`
        # with the transform of the raster.
        col, row = xy[:, 0], xy[:, 1]
        return np.column_stack(
            (
                transform.c + col * transform.a + row * transform.b,
                transform.f + col * transform.d + row * transform.e,
            )
        )

    polygons = np.empty(len(depressions), dtype=object)
    polygons[:] = [polygon for *_, polygon in depressions]
    # One call for all polygons; the WKT of `BaseGeometry.wkt`.
    wkts = shapely.to_wkt(shapely.transform(polygons, to_crs), rounding_precision=-1)
    rows = []
    for (cells, depth_sum_m, max_depth_m, _), wkt in zip(
        depressions, wkts, strict=True
    ):
        area_m2 = cells * cell_area_m2
        volume_m3 = depth_sum_m * cell_area_m2
        mean_depth_m = volume_m3 / area_m2 if area_m2 > 0 else 0
        rows.append(
            {
                "wkt": str(wkt),
                "volume_m3": round(volume_m3, 4),
                "area_m2": round(area_m2, 4),
                "max_depth_m": round(max_depth_m, 4),
                "mean_depth_m": round(mean_depth_m, 4),
            }
        )
    return rows


def insert_depressions(
    db_session,
    depressions: Iterable[dict[str, Any]],
    srid: int = 2180,
    batch_rows: int = INSERT_BATCH_ROWS,
) -> int:
    """
    Insert depressions into PostGIS using COPY bulk loading, in batches.

    The depressions are consumed as they come (a `DepressionScan` computes them
    meanwhile); every batch is copied into a temporary table and inserted from it, and
    one commit at the end makes all of them visible at once.

    Parameters
    ----------
    db_session : Session
        SQLAlchemy database session
    depressions : Iterable[dict]
        Depression dicts, as `compute_depressions` yields them
    srid : int
        SRID of the geometry (default: 2180)
    batch_rows : int
        Depressions copied at a time

    Returns
    -------
    int
        Number of depressions inserted
    """
    rows = iter(depressions)
    first = next(rows, None)
    if first is None:
        logger.info("No depressions to insert")
        return 0

    logger.info("Inserting depressions into database...")

    raw_conn = db_session.connection().connection
    cursor = raw_conn.cursor()

    # Bulk import can take minutes — disable statement_timeout
    cursor.execute("SET statement_timeout = 0")
    raw_conn.commit()

    # Create temp table (drop first for safety)
    cursor.execute("DROP TABLE IF EXISTS temp_depressions_import")
    cursor.execute("""
        CREATE TEMP TABLE temp_depressions_import (
            wkt TEXT,
            volume_m3 FLOAT,
            area_m2 FLOAT,
            max_depth_m FLOAT,
            mean_depth_m FLOAT
        )
    """)

    total = 0
    for batch in itertools.batched(itertools.chain([first], rows), batch_rows):
        tsv_buffer = io.StringIO()
        for dep in batch:
            tsv_buffer.write(
                f"{dep['wkt']}\t{dep['volume_m3']}\t{dep['area_m2']}\t"
                f"{dep['max_depth_m']}\t{dep['mean_depth_m']}\n"
            )
        tsv_buffer.seek(0)

        cursor.copy_expert(
            "COPY temp_depressions_import FROM STDIN"
            " WITH (FORMAT text, DELIMITER E'\\t', NULL '')",
            tsv_buffer,
        )

        # Insert with geometry construction
        cursor.execute(f"""
            INSERT INTO depressions
                (geom, volume_m3, area_m2, max_depth_m, mean_depth_m)
            SELECT
                ST_SetSRID(ST_GeomFromText(wkt), {srid}),
                volume_m3, area_m2, max_depth_m, mean_depth_m
            FROM temp_depressions_import
        """)
        total += cursor.rowcount
        cursor.execute("TRUNCATE temp_depressions_import")
        logger.debug("  Inserted %d depressions", total)

    raw_conn.commit()
    logger.info("  Committed %d depressions", total)

    return total


def generate_overlay(
    overview: DepthOverview,
    output_png: str,
    output_meta: str,
    max_size: int = 1024,
) -> None:
    """
    Generate depression depth overlay as PNG + JSON metadata.

    A pixel of the PNG is as opaque as the share of its area that depressions cover
    and coloured by their mean depth there, relative to the deepest depression cell.
    Shrinking the image so keeps the density of depressions that sampling the full
    image showed before, without its noise; without shrinking, a pixel is a cell,
    opaque where it is a depression and coloured by its depth, as before.

    Parameters
    ----------
    overview : DepthOverview
        Depression cells and depth by blocks of a finished `DepressionScan`
    output_png : str
        Output PNG file path
    output_meta : str
        Output JSON metadata file path
    max_size : int
        Max image dimension in pixels
    """
    dst_crs = "EPSG:4326"
    src_height, src_width = overview.raster_shape
    grid = overlay_grid(
        overview.crs,
        overview.raster_transform,
        src_width,
        src_height,
        max_size,
        dst_crs,
    )

    def warp(values: np.ndarray) -> np.ndarray:
        # No nodata: blocks without depressions are zeros that average in.
        warped = np.zeros((grid.height, grid.width), dtype=np.float64)
        reproject(
            source=values,
            destination=warped,
            src_transform=overview.transform,
            src_crs=overview.crs,
            dst_transform=grid.transform,
            dst_crs=dst_crs,
            resampling=Resampling.average if grid.downsampled else Resampling.nearest,
        )
        return warped

    # Per unit of area: the share covered by depressions and their depth.
    block_area = float(overview.factor**2)
    share = np.clip(warp(overview.cells / block_area), 0.0, 1.0)
    depth_per_area = warp(overview.depth_sum_m / block_area)

    height, width = share.shape
    has_depression = share > 0

    if not np.any(has_depression):
        logger.info("No depression pixels for overlay — skipping PNG generation")
        return

    # Normalize the mean depth of the depressions of a pixel to 0–255
    max_depth = overview.max_depth_m
    normalized = np.zeros_like(share)
    normalized[has_depression] = (
        depth_per_area[has_depression] / share[has_depression] / max_depth
    )
    indices = np.clip((normalized * 255).astype(np.int32), 0, 255)

    # Apply colormap
    cmap = build_depth_colormap()
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    rgba[..., 0] = cmap[indices, 0]
    rgba[..., 1] = cmap[indices, 1]
    rgba[..., 2] = cmap[indices, 2]
    rgba[..., 3] = np.where(has_depression, np.rint(share * 255), 0).astype(np.uint8)

    # Save PNG
    img = Image.fromarray(rgba, mode="RGBA")
    if grid.downsampled:
        logger.info(
            "Downsampled: %dx%d → %dx%d",
            grid.full_width,
            grid.full_height,
            img.width,
            img.height,
        )
    img.save(output_png, optimize=True)
    file_size = Path(output_png).stat().st_size
    logger.info("PNG saved: %s (%.0f KB)", output_png, file_size / 1024)

    bounds = grid.bounds
    (lat_min, lon_min), (lat_max, lon_max) = bounds
    meta = {
        "bounds": bounds,
        "max_depth_m": round(max_depth, 3),
        "width": img.width,
        "height": img.height,
        "crs_source": str(overview.crs),
    }

    with open(output_meta, "w") as f:
        json.dump(meta, f, indent=2)
    logger.info("Metadata: %s", output_meta)
    logger.info(
        "WGS84 bounds: [%.6f, %.6f] → [%.6f, %.6f]", lat_min, lon_min, lat_max, lon_max
    )


def main() -> None:
    """Run the depression generator."""
    parser = argparse.ArgumentParser(
        description="Generate depressions from DEM and insert into PostGIS"
    )
    parser.add_argument("--dem", required=True, help="Path to original DEM raster")
    parser.add_argument("--filled", required=True, help="Path to filled DEM raster")
    parser.add_argument(
        "--min-depth",
        type=float,
        default=0.001,
        help="Minimum depth in meters (default: 0.001 = 1mm)",
    )
    parser.add_argument(
        "--output-png",
        default=None,
        help="Output PNG path for depression overlay",
    )
    parser.add_argument(
        "--output-meta",
        default=None,
        help="Output JSON metadata path for depression overlay",
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=1024,
        help="Max overlay image dimension in pixels (default: 1024)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute depressions but skip database insert",
    )
    parser.add_argument(
        "--clear-existing",
        action="store_true",
        help="Clear existing depressions before insert (TRUNCATE)",
    )
    args = parser.parse_args()

    for path in [args.dem, args.filled]:
        if not Path(path).exists():
            print(f"Error: file not found: {path}", file=sys.stderr)
            sys.exit(1)

    start_time = time.time()

    # The overview keeps twice the resolution of the PNG.
    overview_px = 2 * args.max_size if args.max_size > 0 else OVERVIEW_PX
    scan = compute_depressions(
        args.dem, args.filled, args.min_depth, overview_px=overview_px
    )

    # Insert into database while the scan computes the depressions
    if args.dry_run:
        logger.info("Dry run — skipping database insert")
        for _ in scan:
            pass
    else:
        from sqlalchemy import text

        from core.database import get_db_session
        from core.db_bulk import override_statement_timeout

        with (
            get_db_session() as db,
            override_statement_timeout(
                db,
                timeout_s=600,
            ),
        ):
            if args.clear_existing:
                logger.info("Clearing existing depressions...")
                db.execute(text("TRUNCATE TABLE depressions"))
                db.commit()

            insert_depressions(db, scan)

    # Generate overlay if requested
    if args.output_png and args.output_meta:
        generate_overlay(
            scan.overview,
            args.output_png,
            args.output_meta,
            args.max_size,
        )

    elapsed = time.time() - start_time
    logger.info("Done in %.1fs — %d depressions processed", elapsed, scan.count)


if __name__ == "__main__":
    main()
