"""Rasterize PGW owners and extend them inside the existing DEM domain only.

The owners are the polygons of Kartograf's PGW GeoPackage (``pl.pgw.pgw``): the river
catchments (layer ``zlewnie_jcwp_rzecznych``) and the remaining areas (layer
``pozostale_obszary_jcwp``), each named by its ``MS_KOD``. With a catchment file
(``CatchmentFile``: the MPHP catchments of the analysis area) the owners are groups
of those catchments instead: each catchment goes to the PGW unit it overlaps most,
and an owner is the union of its catchments, named by that unit's ``MS_KOD``. The
owners are rasterized on the grid of the input DEM, never on a grid of their own.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import fiona
import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from scipy.spatial import cKDTree
from shapely.geometry import box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree
from shapely.validation import make_valid

from core.boundary import load_boundary

logger = logging.getLogger(__name__)

RIVER_CATCHMENTS_LAYER = "zlewnie_jcwp_rzecznych"
REMAINING_AREAS_LAYER = "pozostale_obszary_jcwp"
# The key of an MPHP catchment, the default of ``CatchmentFile.key``.
DEFAULT_CATCHMENT_KEY = "ID_HYD_10"
# One byte per cell holds the 1-based owner index; 0 is "no owner".
MAX_OWNERS = 254
# Two owner polygons may overlap by at most this much (digitizing noise) [m2], and a
# polygon clipped to less than this reaches nothing: the area file is read through
# WGS84, which moves an edge by a hair, so a polygon that only touches the area keeps
# a sliver of it.
_OVERLAP_TOLERANCE_M2 = 1.0
_MIN_CLIPPED_AREA_M2 = 1.0
# Files written by ArcGIS declare EPSG:2180 as ESRI:102173 (ETRS 1989 UWPP 1992), the
# same projection under another authority, which pyproj does not equate with it.
_EPSG_2180_NAMES = frozenset({"EPSG:2180", "ESRI:102173"})


@dataclass(frozen=True)
class CatchmentFile:
    """The catchments the owners are grouped from.

    Attributes
    ----------
    path : Path
        Vector file of the catchments (EPSG:2180).
    layer : str or None
        Its layer (default: the first).
    key : str
        Field holding the unique key of a catchment (MPHP: ``ID_HYD_10``).
    """

    path: Path
    layer: str | None = None
    key: str = DEFAULT_CATCHMENT_KEY


@dataclass
class PgwOwners:
    """PGW codes and owned cells on exactly the given DEM's grid.

    Attributes
    ----------
    codes : tuple[str, ...]
        ``MS_KOD`` of the owners; the owner of a cell is the 1-based index in it.
    cells : np.memmap
        uint8 owner of every valid DEM cell, 0 where the DEM has no data.
    valid : np.memmap
        bool, the cells of the DEM that hold data.
    pgw_cells : int
        Valid DEM cells inside an owner polygon, before the cells outside every
        polygon were given their nearest owner.
    members : dict[str, tuple[str, ...]]
        With a catchment file: the keys of the catchments of each owner, sorted;
        empty for owners that are PGW polygons.
    """

    codes: tuple[str, ...]
    cells: np.memmap
    valid: np.memmap
    pgw_cells: int
    members: dict[str, tuple[str, ...]] = field(default_factory=dict)


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


def _read_pgw_polygons(units_path: Path) -> dict[str, BaseGeometry]:
    """Read the owner polygons of both PGW layers, joined by their ``MS_KOD``.

    Features that share a code (in one layer or in both) are one owner.
    """
    layers = fiona.listlayers(units_path)
    by_code: dict[str, list[BaseGeometry]] = {}
    for layer in (RIVER_CATCHMENTS_LAYER, REMAINING_AREAS_LAYER):
        if layer not in layers:
            raise ValueError(
                f"{units_path} has no layer {layer!r}: the units file is the "
                f"Kartograf PGW GeoPackage (layers: {', '.join(layers)})"
            )
        with fiona.open(units_path, layer=layer) as source:
            if source.crs is None or source.crs.to_epsg() != 2180:
                raise ValueError(f"PGW layer {layer!r} must be in EPSG:2180")
            for feature in source:
                if feature["geometry"] is None:
                    continue
                code = feature["properties"]["MS_KOD"]
                if code is None or not str(code).strip():
                    raise ValueError(
                        f"PGW layer {layer!r} has a feature without MS_KOD"
                    )
                geometry = shape(feature["geometry"])
                if not geometry.is_valid:
                    geometry = make_valid(geometry)
                by_code.setdefault(str(code), []).append(geometry)
    return {code: unary_union(parts) for code, parts in by_code.items()}


def _read_catchments(catchments: CatchmentFile) -> dict[str, BaseGeometry]:
    """Read the catchments by their key; every key is non-empty and unique."""
    layers = fiona.listlayers(catchments.path)
    layer = catchments.layer or layers[0]
    if layer not in layers:
        raise ValueError(
            f"{catchments.path} has no layer {layer!r} (layers: {', '.join(layers)})"
        )
    by_key: dict[str, BaseGeometry] = {}
    with fiona.open(catchments.path, layer=layer) as source:
        if source.crs is None or (
            source.crs.to_epsg() != 2180
            and source.crs.to_string() not in _EPSG_2180_NAMES
        ):
            raise ValueError(
                f"Catchment layer {layer!r} must be in EPSG:2180, not {source.crs}"
            )
        fields = source.schema["properties"]
        if catchments.key not in fields:
            raise ValueError(
                f"Catchment layer {layer!r} has no field {catchments.key!r} "
                f"(fields: {', '.join(fields)})"
            )
        for feature in source:
            value = feature["properties"][catchments.key]
            key = "" if value is None else str(value).strip()
            if not key:
                raise ValueError(
                    f"Catchment layer {layer!r} has a feature without {catchments.key}"
                )
            if key in by_key:
                raise ValueError(f"Catchment {catchments.key} {key!r} repeats")
            if feature["geometry"] is None:
                raise ValueError(f"Catchment {key!r} has no geometry")
            geometry = shape(feature["geometry"])
            by_key[key] = geometry if geometry.is_valid else make_valid(geometry)
    if not by_key:
        raise ValueError(f"Catchment layer {layer!r} is empty")
    return by_key


def group_catchments(
    units: dict[str, BaseGeometry], catchments: dict[str, BaseGeometry]
) -> tuple[dict[str, BaseGeometry], dict[str, tuple[str, ...]]]:
    """Give each catchment to the PGW unit it overlaps most.

    Parameters
    ----------
    units : dict[str, BaseGeometry]
        PGW polygons by ``MS_KOD``.
    catchments : dict[str, BaseGeometry]
        Catchment polygons by key.

    Returns
    -------
    tuple[dict[str, BaseGeometry], dict[str, tuple[str, ...]]]
        The owner polygons (the union of the catchments of a unit) and the keys
        of each owner's catchments, sorted, both by ``MS_KOD``; units without a
        catchment are no owners. An equal overlap goes to the first code.

    Raises
    ------
    ValueError
        A catchment overlaps no unit.
    """
    codes = sorted(units)
    tree = STRtree([units[code] for code in codes])
    members: dict[str, list[str]] = {}
    smallest_share = 1.0
    for key in sorted(catchments):
        geometry = catchments[key]
        best_code, best_area = None, 0.0
        for index in sorted(int(i) for i in tree.query(geometry)):
            area = geometry.intersection(units[codes[index]]).area
            if area > best_area:
                best_code, best_area = codes[index], area
        if best_code is None:
            raise ValueError(f"Catchment {key!r} overlaps no PGW unit")
        members.setdefault(best_code, []).append(key)
        if geometry.area > 0:
            smallest_share = min(smallest_share, best_area / geometry.area)
    owners = {
        code: unary_union([catchments[key] for key in keys])
        for code, keys in members.items()
    }
    logger.info(
        "%d catchments grouped into %d PGW units (smallest share of a catchment "
        "inside its unit: %.4f)",
        len(catchments),
        len(owners),
        smallest_share,
    )
    return owners, {code: tuple(keys) for code, keys in members.items()}


def _read_area(area_path: Path, layer: str | None) -> BaseGeometry:
    """Read the area file as one polygon in EPSG:2180."""
    boundary = load_boundary(area_path, layer=layer)
    return gpd.GeoSeries([boundary], crs="EPSG:4326").to_crs(2180).iloc[0]


def load_pgw_owners(
    dem_path: Path,
    units_path: Path,
    output_dir: Path,
    area_path: Path | None = None,
    area_layer: str | None = None,
    catchments: CatchmentFile | None = None,
) -> PgwOwners:
    """Partition every valid input DEM cell among the PGW owners that reach the DEM.

    An owner is a PGW polygon (Kartograf's GeoPackage, see the module docstring) that
    covers a cell of the DEM, rasterized with the cell centre as the test. With an
    ``area_path`` (a vector file, any CRS) the polygons are first clipped to that
    area: the analysis area of the run, so that a neighbouring catchment that only
    reaches into the margin of the DEM is no owner, and every cell of the area must
    then lie inside a polygon.

    The cells outside every polygon (and outside the area) are given the nearest
    existing owner; this never changes the input domain, the DEM nodata or the grid.
    Direct lake polygons already lie inside the river catchments and need no owner.
    With ``catchments`` the polygons are the groups of ``group_catchments`` instead
    of the PGW polygons themselves.

    Parameters
    ----------
    dem_path : Path
        The input DEM (EPSG:2180, square north-up cells, nodata declared).
    units_path : Path
        The PGW GeoPackage.
    output_dir : Path
        Directory of the disk-backed ``owners.npy`` and ``valid_input.npy``.
    area_path : Path, optional
        Vector file of the analysis area; owners are clipped to it.
    area_layer : str, optional
        Its layer (default: the first).
    catchments : CatchmentFile, optional
        Catchments to group into the owners.

    Raises
    ------
    ValueError
        A layer, code or CRS of the units or catchment file is wrong; a catchment
        overlaps no unit; owners overlap; the area has a valid cell no polygon
        covers; no polygon reaches the DEM; or there are more than ``MAX_OWNERS``
        owners.
    """
    polygons = _read_pgw_polygons(units_path)
    members: dict[str, tuple[str, ...]] = {}
    if catchments is not None:
        polygons, members = group_catchments(polygons, _read_catchments(catchments))
    area = _read_area(area_path, area_layer) if area_path is not None else None
    with rasterio.open(dem_path) as source:
        if source.nodata is None or source.crs is None or source.crs.to_epsg() != 2180:
            raise ValueError("DEM requires EPSG:2180 and a nodata value")
        cell_shape = source.shape
        transform = source.transform
        reach = box(*source.bounds)
        if area is not None:
            reach = reach.intersection(area)
        shapes: list[tuple[str, BaseGeometry]] = []
        for code in sorted(polygons):
            clipped = polygons[code].intersection(reach)
            if clipped.area >= _MIN_CLIPPED_AREA_M2:
                shapes.append((code, clipped))
        if not shapes:
            raise ValueError("No PGW polygon reaches the valid input DEM")
        if len(shapes) > MAX_OWNERS:
            raise ValueError(
                f"PGW units give {len(shapes)} owners, at most {MAX_OWNERS} fit"
            )
        _require_disjoint(shapes)
        output_dir.mkdir(parents=True, exist_ok=True)
        valid = np.lib.format.open_memmap(
            output_dir / "valid_input.npy", mode="w+", dtype="bool", shape=cell_shape
        )
        for _, window in source.block_windows(1):
            block = source.read(1, window=window)
            row, col = int(window.row_off), int(window.col_off)
            valid[row : row + block.shape[0], col : col + block.shape[1]] = (
                block != source.nodata
            )
        owners = np.lib.format.open_memmap(
            output_dir / "owners.npy", mode="w+", dtype="uint8", shape=cell_shape
        )
        owners[:] = 0
        rasterize(
            [(geometry, i) for i, (_, geometry) in enumerate(shapes, start=1)],
            out=owners,
            transform=transform,
            all_touched=False,
        )
        if area is not None:
            # Cells within one cell of the area's boundary are not checked: the area
            # file and the polygons are digitized apart (an Archiwista area is stored
            # in WGS84), so their outlines differ by less than a cell there; those
            # cells get the nearest owner below. A gap deeper inside is an error.
            core = area.buffer(-abs(transform.a))
            if core.is_empty:
                core = area
            area_cells = rasterize(
                [(core, 1)],
                out_shape=cell_shape,
                transform=transform,
                dtype="uint8",
                all_touched=False,
            )
            gaps = (area_cells > 0) & valid & (owners == 0)
            if np.any(gaps):
                row, col = np.argwhere(gaps)[0]
                raise ValueError(
                    f"PGW polygons leave {int(np.count_nonzero(gaps))} valid cells "
                    f"inside the area without an owner (first at row {row}, "
                    f"column {col})"
                )
            del area_cells, gaps
        owners[~valid] = 0
        pgw_cells = int(np.count_nonzero(owners))
        nearest_valid_owners(owners, valid)
        if np.any((owners == 0) & valid):
            raise ValueError("A valid DEM cell has no owner")
    codes = tuple(code for code, _ in shapes)
    return PgwOwners(
        codes,
        owners,
        valid,
        pgw_cells,
        {code: members[code] for code in codes if code in members},
    )


def _require_disjoint(shapes: list[tuple[str, BaseGeometry]]) -> None:
    """Refuse owners whose polygons overlap by more than digitizing noise."""
    tree = STRtree([geometry for _, geometry in shapes])
    for index, (code, geometry) in enumerate(shapes):
        for other in tree.query(geometry):
            if other <= index:
                continue
            overlap = geometry.intersection(shapes[other][1]).area
            if overlap > _OVERLAP_TOLERANCE_M2:
                raise ValueError(
                    f"PGW owners {code} and {shapes[other][0]} overlap by "
                    f"{overlap:,.1f} m2"
                )
