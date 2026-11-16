"""Per-owner GeoTIFF tiles and a whole-area VRT for every PGW unit raster.

``write_unit_mosaics`` publishes whole-grid rasters of the unit pipeline (disk-backed
arrays, or the original DEM file) as

* one tiled GeoTIFF per owner and raster in ``<output_dir>/units``: a whole-pixel
  window of the DEM grid (its CRS, cell size and alignment; no resampling and never
  a cell outside the DEM grid) that bounds the owner's valid cells. It holds the
  owner's values and the raster's nodata value everywhere else. Only the owner's
  cells are valid in its internal mask, so a legitimate 0 (a D8 outlet, "not a
  stream", "no label") is told from nodata by the mask, not by the value;
* one VRT per raster, ``<output_dir>/<base_name>_<suffix>.vrt``, on the full DEM
  grid with the nodata value of the raster.

The bounding boxes of jagged owners overlap. A ``SimpleSource`` writes the nodata
cells of a later tile over the cells an earlier one holds; the VRT therefore uses
``ComplexSource`` with ``NODATA``, which leaves a cell to the tile that holds it.
Each cell belongs to exactly one tile, so the composite has no overlap to resolve.
A holder's own cell equal to the nodata value (0 of a D8 outlet) shows the nodata
value either way, which is the value of the whole-grid array. The VRT is built
here, as XML, so it needs no external GDAL program, and nothing ever merges the
tiles into a full raster.

Nothing is published unless everything is: tiles and VRTs are staged in a hidden
directory of ``output_dir`` and read back (every valid input cell exactly once,
every VRT cell equal to the whole-grid array) before they replace any file. The
memory in use is bounded by the size of one window, never a raster or an owner's
bounding box.
"""

from __future__ import annotations

import logging
import math
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import MaskFlags
from rasterio.windows import Window
from rasterio.windows import transform as window_transform
from scipy.ndimage import find_objects

logger = logging.getLogger(__name__)

# Rows and columns of a GeoTIFF block (the convention of core.raster_io).
_BLOCK = 256
# A window is a whole number of blocks with at most this many cells.
_WINDOW_CELLS = 4 * 1024 * 1024
_MAX_WINDOW_COLS = 32 * _BLOCK
# Sub-directory of ``output_dir`` for the tiles; the VRTs refer to it by this name.
_TILE_DIR = "units"
# Data types that a GeoTIFF band, a VRT band and a ComplexSource copy exactly. UInt32
# is not one: GDAL's ComplexSource rounds values near 2**32 up to the nodata value.
_GDAL_TYPES = {
    "uint8": "Byte",
    "int16": "Int16",
    "uint16": "UInt16",
    "int32": "Int32",
    "float32": "Float32",
    "float64": "Float64",
}

_Reader = Callable[[int, int, int, int], np.ndarray]


@dataclass(frozen=True)
class _Grid:
    """The pixel grid of the DEM, which every tile and VRT keeps."""

    height: int
    width: int
    transform: Any
    crs: Any
    nodata: float


@dataclass(frozen=True)
class _Bounds:
    """Half-open pixel box of one owner's valid cells on the DEM grid."""

    row0: int
    row1: int
    col0: int
    col1: int

    @property
    def height(self) -> int:
        """Rows of the box."""
        return self.row1 - self.row0

    @property
    def width(self) -> int:
        """Columns of the box."""
        return self.col1 - self.col0

    @property
    def window(self) -> Window:
        """The box as a window of the DEM grid."""
        return Window(self.col0, self.row0, self.width, self.height)


@dataclass(frozen=True)
class _Raster:
    """A whole-grid raster to publish, readable window by window."""

    suffix: str
    dtype: np.dtype[Any]
    nodata: float | int
    fill: Any
    read: _Reader


@dataclass(frozen=True)
class _Tile:
    """One written tile: its box on the grid and its file in the tile directory."""

    owner: int
    suffix: str
    bounds: _Bounds
    name: str
    block: tuple[int, int]


def _windows(height: int, width: int) -> Iterator[tuple[int, int, int, int]]:
    """Yield ``(row, col, rows, cols)`` windows on the block grid of a raster."""
    cols = min(width, _MAX_WINDOW_COLS)
    rows = _WINDOW_CELLS // cols // _BLOCK * _BLOCK
    for row in range(0, height, rows):
        for col in range(0, width, cols):
            yield row, col, min(rows, height - row), min(cols, width - col)


def _check_name(kind: str, value: str) -> None:
    """Reject a name that is not one plain file-name component."""
    if (
        not isinstance(value, str)
        or value in ("", ".", "..")
        or any(char in value for char in "/\\\0")
    ):
        raise ValueError(f"{kind} {value!r} is not a plain file name part")


def _valid(block: np.ndarray, nodata: float) -> np.ndarray:
    """Return the cells of ``block`` that hold data (NaN-aware nodata)."""
    if math.isnan(nodata):
        return ~np.isnan(block)
    return np.asarray(block != nodata)


def _nodata_values(
    suffix: str, nodata: float | int, dtype: np.dtype[Any]
) -> tuple[float | int, Any]:
    """Return ``nodata`` as the files declare it and as a scalar of ``dtype``.

    An integer type takes an integer inside its range, a float type any number
    that does not overflow it. Cells are filled with the scalar; the declaration
    stays as given, as the DEM states its own, and GDAL compares in the type.
    """
    problem = f"Raster {suffix!r}: nodata {nodata!r} does not fit {dtype.name}"
    if isinstance(nodata, bool) or not isinstance(
        nodata, int | float | np.integer | np.floating
    ):
        raise ValueError(problem)
    declared: float | int
    if dtype.kind == "f":
        declared = float(nodata)
        with np.errstate(over="ignore"):
            fill = dtype.type(declared)
        if math.isfinite(declared) and not math.isfinite(float(fill)):
            raise ValueError(problem)
        return declared, fill
    try:
        declared = int(nodata)
    except (ValueError, OverflowError):
        raise ValueError(problem) from None
    limits = np.iinfo(dtype)
    if declared != nodata or not limits.min <= declared <= limits.max:
        raise ValueError(problem)
    return declared, dtype.type(declared)


def _same_grid(first: Any, second: Any, cell: float) -> bool:
    """Compare two transforms to a millionth of a cell."""
    return all(
        abs(left - right) <= 1e-6 * cell
        for left, right in zip(tuple(first)[:6], tuple(second)[:6], strict=True)
    )


def _array_reader(array: np.ndarray) -> _Reader:
    """Read windows of a whole-grid array (a memory map stays on disk)."""

    def read(row: int, col: int, rows: int, cols: int) -> np.ndarray:
        return np.asarray(array[row : row + rows, col : col + cols])

    return read


def _file_reader(dataset: Any) -> _Reader:
    """Read windows of band 1 of an open raster file."""

    def read(row: int, col: int, rows: int, cols: int) -> np.ndarray:
        return np.asarray(dataset.read(1, window=Window(col, row, cols, rows)))

    return read


def _open_raster(
    stack: ExitStack,
    suffix: str,
    entry: tuple[np.ndarray | Path, float | int],
    grid: _Grid,
) -> _Raster:
    """Validate one ``(source, nodata)`` entry against the DEM grid."""
    try:
        source, nodata = entry
    except (TypeError, ValueError):
        raise ValueError(f"Raster {suffix!r} must be a (source, nodata) pair") from None
    shape = (grid.height, grid.width)
    if isinstance(source, str | os.PathLike):
        dataset = stack.enter_context(rasterio.open(source))
        cell = abs(grid.transform.a) or abs(grid.transform.b)
        if (dataset.height, dataset.width) != shape:
            raise ValueError(
                f"Raster {suffix!r} is {dataset.height}x{dataset.width} cells, "
                f"the DEM grid is {shape[0]}x{shape[1]}"
            )
        if not _same_grid(dataset.transform, grid.transform, cell):
            raise ValueError(f"Raster {suffix!r} is not on the pixel grid of the DEM")
        if dataset.crs != grid.crs:
            raise ValueError(f"Raster {suffix!r} is not in the CRS of the DEM")
        dtype = np.dtype(dataset.dtypes[0])
        read = _file_reader(dataset)
    elif isinstance(source, np.ndarray):
        if source.shape != shape:
            raise ValueError(
                f"Raster {suffix!r} is {source.shape} cells, "
                f"the DEM grid is {shape[0]}x{shape[1]}"
            )
        dtype = source.dtype
        read = _array_reader(source)
    else:
        raise ValueError(f"Raster {suffix!r} must be an array or a raster file path")
    if dtype.name not in _GDAL_TYPES or not dtype.isnative:
        raise ValueError(f"Raster {suffix!r} has the unsupported type {dtype}")
    declared, fill = _nodata_values(suffix, nodata, dtype)
    return _Raster(suffix, dtype, declared, fill, read)


def _scan_owners(
    dem: Any, grid: _Grid, owners: np.ndarray, count: int, stage: Path
) -> tuple[np.ndarray, dict[int, _Bounds]]:
    """Find every owner's valid cells; return them as a raster and as boxes.

    The returned ``owned`` raster holds the owner of each valid DEM cell and 0
    elsewhere: an owner a nodata cell was given is dropped, the DEM defines the
    domain. A valid cell without an owner, or an owner without a code, is an error.
    """
    owned = np.lib.format.open_memmap(
        stage / "owned.npy",
        mode="w+",
        dtype=np.min_scalar_type(count),
        shape=(grid.height, grid.width),
    )
    extent: dict[int, list[int]] = {}
    for row, col, rows, cols in _windows(grid.height, grid.width):
        valid = _valid(dem.read(1, window=Window(col, row, cols, rows)), grid.nodata)
        ids = np.asarray(owners[row : row + rows, col : col + cols])
        if int(ids.min()) < 0 or int(ids.max()) > count:
            raise ValueError(
                f"Owner raster holds an owner outside 1..{count}, the number of "
                "owner codes"
            )
        unowned = valid & (ids == 0)
        if unowned.any():
            first_row, first_col = np.argwhere(unowned)[0]
            raise ValueError(
                "A valid DEM cell has no owner (first at row "
                f"{row + int(first_row)}, column {col + int(first_col)})"
            )
        block = np.where(valid, ids, 0).astype(owned.dtype, copy=False)
        owned[row : row + rows, col : col + cols] = block
        if not block.any():
            continue
        for owner, found in enumerate(find_objects(block), start=1):
            if found is None:
                continue
            rows_slice, cols_slice = found
            box = [
                row + rows_slice.start,
                row + rows_slice.stop,
                col + cols_slice.start,
                col + cols_slice.stop,
            ]
            old = extent.setdefault(owner, box)
            old[:] = [
                min(old[0], box[0]),
                max(old[1], box[1]),
                min(old[2], box[2]),
                max(old[3], box[3]),
            ]
    return owned, {owner: _Bounds(*box) for owner, box in sorted(extent.items())}


def _write_tiles(
    stage: Path,
    grid: _Grid,
    rasters: list[_Raster],
    owned: np.ndarray,
    bounds: dict[int, _Bounds],
    names: dict[tuple[int, str], str],
) -> list[_Tile]:
    """Write every raster's tile of every owner, one window at a time.

    The windows lie on the block grid of the tile, so each block is written once.
    A window without a cell of the owner is not written at all: GDAL fills such
    blocks with nodata (and an invalid mask) when it closes the file.
    """
    tiles: list[_Tile] = []
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
        for owner, box in bounds.items():
            transform = window_transform(box.window, grid.transform)
            with ExitStack() as stack:
                writers = []
                for raster in rasters:
                    name = names[owner, raster.suffix]
                    writer = stack.enter_context(
                        rasterio.open(
                            stage / _TILE_DIR / name,
                            "w",
                            driver="GTiff",
                            height=box.height,
                            width=box.width,
                            count=1,
                            dtype=raster.dtype.name,
                            crs=grid.crs,
                            transform=transform,
                            nodata=raster.nodata,
                            compress="lzw",
                            tiled=True,
                            blockxsize=_BLOCK,
                            blockysize=_BLOCK,
                            bigtiff="IF_SAFER",
                        )
                    )
                    writers.append((raster, writer))
                    block_rows, block_cols = writer.block_shapes[0]
                    tile_block = (int(block_rows), int(block_cols))
                    tiles.append(_Tile(owner, raster.suffix, box, name, tile_block))
                for row, col, rows, cols in _windows(box.height, box.width):
                    top, left = box.row0 + row, box.col0 + col
                    keep = owned[top : top + rows, left : left + cols] == owner
                    if not keep.any():
                        continue
                    window = Window(col, row, cols, rows)
                    mask = np.where(keep, np.uint8(255), np.uint8(0))
                    for raster, writer in writers:
                        data = raster.read(top, left, rows, cols)
                        data = np.where(keep, data, raster.fill)
                        writer.write(
                            data.astype(raster.dtype, copy=False), 1, window=window
                        )
                        writer.write_mask(mask, window=window)
    return tiles


def _tile_name(base_name: str, suffix: str, code: str) -> str:
    """Return the file name of a tile, stable for a raster and an owner code."""
    return f"{base_name}_{suffix}_{code}.tif"


def _number(value: float | int) -> str:
    """Format a nodata value for VRT XML (``nan`` for NaN)."""
    return str(value) if isinstance(value, int) else repr(float(value))


def _write_vrt(path: Path, grid: _Grid, raster: _Raster, tiles: list[_Tile]) -> None:
    """Write the VRT of one raster: its tiles composited on the full DEM grid."""
    gdal_type = _GDAL_TYPES[raster.dtype.name]
    nodata = _number(raster.nodata)
    root = ET.Element(
        "VRTDataset", rasterXSize=str(grid.width), rasterYSize=str(grid.height)
    )
    ET.SubElement(root, "SRS").text = grid.crs.to_wkt()
    ET.SubElement(root, "GeoTransform").text = ", ".join(
        repr(float(value)) for value in grid.transform.to_gdal()
    )
    band = ET.SubElement(root, "VRTRasterBand", dataType=gdal_type, band="1")
    ET.SubElement(band, "NoDataValue").text = nodata
    ET.SubElement(band, "ColorInterp").text = "Gray"
    for tile in tiles:
        box = tile.bounds
        source = ET.SubElement(band, "ComplexSource")
        name = ET.SubElement(source, "SourceFilename", relativeToVRT="1")
        name.text = f"{_TILE_DIR}/{tile.name}"
        ET.SubElement(source, "SourceBand").text = "1"
        ET.SubElement(
            source,
            "SourceProperties",
            RasterXSize=str(box.width),
            RasterYSize=str(box.height),
            DataType=gdal_type,
            BlockXSize=str(tile.block[1]),
            BlockYSize=str(tile.block[0]),
        )
        ET.SubElement(
            source,
            "SrcRect",
            xOff="0",
            yOff="0",
            xSize=str(box.width),
            ySize=str(box.height),
        )
        ET.SubElement(
            source,
            "DstRect",
            xOff=str(box.col0),
            yOff=str(box.row0),
            xSize=str(box.width),
            ySize=str(box.height),
        )
        ET.SubElement(source, "NODATA").text = nodata
    tree = ET.ElementTree(root)
    ET.indent(tree)
    tree.write(path, encoding="utf-8")


def _same_values(actual: np.ndarray, expected: np.ndarray) -> np.ndarray:
    """Compare cell by cell, two NaN being equal."""
    same = np.asarray(actual == expected)
    if actual.dtype.kind == "f":
        same |= np.isnan(actual) & np.isnan(expected)
    return same


def _states_nodata(dataset: Any, raster: _Raster) -> bool:
    """Tell whether a file declares the nodata value of the raster (in its type)."""
    if dataset.nodata is None:
        return False
    try:
        with np.errstate(over="ignore", invalid="ignore"):
            stated = raster.dtype.type(dataset.nodata)
    except (OverflowError, ValueError):
        return False
    both_nan = bool(stated != stated and raster.fill != raster.fill)
    return bool(stated == raster.fill) or both_nan


def _check_header(
    dataset: Any,
    what: str,
    shape: tuple[int, int],
    transform: Any,
    grid: _Grid,
    raster: _Raster,
) -> None:
    """Require the grid, CRS, type and nodata a file has to declare."""
    same_nodata = _states_nodata(dataset, raster)
    if (
        (dataset.height, dataset.width) != shape
        or dataset.transform != transform
        or dataset.crs != grid.crs
        or dataset.dtypes[0] != raster.dtype.name
        or not same_nodata
    ):
        raise ValueError(
            f"{what} does not have the geometry, CRS, type and nodata of the raster "
            f"{raster.suffix!r} on the DEM grid"
        )


def _verify(
    stage: Path,
    vrt_name: str,
    grid: _Grid,
    raster: _Raster,
    tiles: list[_Tile],
    owned: np.ndarray,
) -> None:
    """Read the staged VRT and its tiles back against the whole-grid raster.

    Every cell of the VRT must equal the array where a DEM cell has an owner, and
    the nodata value elsewhere. Every valid DEM cell must also be valid in the mask
    of exactly one tile: a value of 0 cannot show a cell held twice or not at all.
    """
    with ExitStack() as stack:
        vrt = stack.enter_context(rasterio.open(stage / vrt_name))
        shape = (grid.height, grid.width)
        _check_header(vrt, f"The VRT {vrt_name}", shape, grid.transform, grid, raster)
        opened = []
        for tile in tiles:
            box = tile.bounds
            dataset = stack.enter_context(rasterio.open(stage / _TILE_DIR / tile.name))
            _check_header(
                dataset,
                f"The tile {tile.name}",
                (box.height, box.width),
                window_transform(box.window, grid.transform),
                grid,
                raster,
            )
            if MaskFlags.per_dataset not in dataset.mask_flag_enums[0]:
                raise ValueError(f"The tile {tile.name} has no owner mask")
            opened.append((box, dataset))
        for row, col, rows, cols in _windows(grid.height, grid.width):
            ours = owned[row : row + rows, col : col + cols] > 0
            expected = np.where(ours, raster.read(row, col, rows, cols), raster.fill)
            actual = vrt.read(1, window=Window(col, row, cols, rows))
            different = ~_same_values(actual, expected)
            if different.any():
                bad_row, bad_col = np.argwhere(different)[0]
                raise ValueError(
                    f"The VRT {vrt_name} differs from its raster in "
                    f"{int(np.count_nonzero(different))} cells (first at row "
                    f"{row + int(bad_row)}, column {col + int(bad_col)}: "
                    f"{actual[bad_row, bad_col]!r} instead of "
                    f"{expected[bad_row, bad_col]!r})"
                )
            holders = np.zeros((rows, cols), dtype=np.uint16)
            for box, dataset in opened:
                top, bottom = max(row, box.row0), min(row + rows, box.row1)
                left, right = max(col, box.col0), min(col + cols, box.col1)
                if top >= bottom or left >= right:
                    continue
                inside = Window(
                    left - box.col0, top - box.row0, right - left, bottom - top
                )
                held = dataset.read_masks(1, window=inside) > 0
                holders[top - row : bottom - row, left - col : right - col] += held
            wrong = holders != ours
            if wrong.any():
                bad_row, bad_col = np.argwhere(wrong)[0]
                raise ValueError(
                    f"The tiles of {raster.suffix!r} hold the cell at row "
                    f"{row + int(bad_row)}, column {col + int(bad_col)} "
                    f"{int(holders[bad_row, bad_col])} times, not "
                    f"{int(ours[bad_row, bad_col])}"
                )


def write_unit_mosaics(
    dem_path: Path,
    owners: np.ndarray,
    owner_codes: tuple[str, ...],
    rasters: dict[str, tuple[np.ndarray | Path, float | int]],
    output_dir: Path,
    base_name: str,
) -> tuple[dict[str, Path], dict[int, dict[str, Path]]]:
    """Write every raster as owned-cell tiles per owner plus one VRT per raster.

    Each raster is cut by ``owners`` into non-overlapping tiled GeoTIFFs
    ``<output_dir>/units/<base_name>_<suffix>_<code>.tif`` and mosaicked, without
    copying a cell, by ``<output_dir>/<base_name>_<suffix>.vrt``. A VRT opens on the
    full grid of ``dem_path`` with the CRS, transform and cell size of the DEM and
    the nodata value given for the raster, and reads cell for cell like the
    whole-grid raster, where a cell that is nodata in the DEM or has no owner is
    the nodata value. A tile holds the cells of its owner only (see the module
    docstring); a window of the grid with no cell of the owner is never read.

    Parameters
    ----------
    dem_path : Path
        The DEM that defines the grid, the CRS and the valid cells (those that are
        not its nodata value, which it must declare).
    owners : np.ndarray
        Integer raster on the grid of the DEM (a memory map is fine): the 1-based
        index in ``owner_codes`` of the owner of each cell, 0 for no owner. Every
        valid DEM cell needs an owner; an owner on a nodata cell is ignored.
    owner_codes : tuple[str, ...]
        Owner codes in owner order; they name the tile files.
    rasters : dict[str, tuple[np.ndarray | Path, float | int]]
        Raster to write by file name suffix (``01_dem``, ``02_filled``,
        ``03_flowdir``, ...) as ``(source, nodata)``. The source is a whole-grid
        array of a type GeoTIFF supports (a memory map is fine) or the path of a
        raster on the pixel grid of the DEM (the DEM itself, for ``01_dem``). The
        nodata value must be exactly representable in the type of the source.
    output_dir : Path
        Directory of the VRTs; the tiles go to its ``units`` sub-directory.
    base_name : str
        File name prefix of tiles and VRTs.

    Returns
    -------
    tuple[dict[str, Path], dict[int, dict[str, Path]]]
        The VRT of each suffix, and the tile of each suffix by 1-based owner (an
        owner without a valid cell has no tile and no entry).

    Raises
    ------
    ValueError
        If an argument is malformed, a source is not on the grid of the DEM, a
        valid DEM cell has no owner, an owner has no code, or the files written do
        not read back as the arrays with every valid DEM cell held exactly once.
        Nothing is created or replaced in ``output_dir`` then.
    """
    dem_path = Path(dem_path)
    output_dir = Path(output_dir)
    codes = tuple(owner_codes)
    _check_name("Base name", base_name)
    for code in codes:
        _check_name("Owner code", code)
    if len({code.casefold() for code in codes}) != len(codes):
        raise ValueError("Owner codes must be unique, also ignoring case")
    if not rasters:
        raise ValueError("No rasters to write")
    for suffix in rasters:
        _check_name("Raster suffix", suffix)
    created = [path for path in (output_dir, *output_dir.parents) if not path.exists()]
    try:
        with ExitStack() as stack:
            dem = stack.enter_context(rasterio.open(dem_path))
            if dem.nodata is None or dem.crs is None:
                raise ValueError("The DEM requires a nodata value and a CRS")
            grid = _Grid(
                dem.height, dem.width, dem.transform, dem.crs, float(dem.nodata)
            )
            if (
                not isinstance(owners, np.ndarray)
                or owners.dtype.kind not in "iu"
                or owners.shape != (grid.height, grid.width)
            ):
                raise ValueError(
                    "Owners must be an integer array on the "
                    f"{grid.height}x{grid.width} DEM grid"
                )
            opened = [
                _open_raster(stack, suffix, entry, grid)
                for suffix, entry in rasters.items()
            ]
            output_dir.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix=".unit_rasters-", dir=output_dir))
            stack.callback(shutil.rmtree, stage, ignore_errors=True)
            (stage / _TILE_DIR).mkdir()
            owned, bounds = _scan_owners(dem, grid, owners, len(codes), stage)
            if not bounds:
                raise ValueError("The DEM has no valid cell to write")
            names = {
                (owner, raster.suffix): _tile_name(
                    base_name, raster.suffix, codes[owner - 1]
                )
                for owner in bounds
                for raster in opened
            }
            if len(set(names.values())) != len(names):
                raise ValueError(
                    "Raster suffixes and owner codes give equal tile names"
                )
            tiles = _write_tiles(stage, grid, opened, owned, bounds, names)
            vrt_names = {
                raster.suffix: f"{base_name}_{raster.suffix}.vrt" for raster in opened
            }
            for raster in opened:
                raster_tiles = [tile for tile in tiles if tile.suffix == raster.suffix]
                vrt_name = vrt_names[raster.suffix]
                _write_vrt(stage / vrt_name, grid, raster, raster_tiles)
                _verify(stage, vrt_name, grid, raster, raster_tiles, owned)
            # Every file is complete and verified; only now may a file be replaced.
            # The VRTs, the entry points, go last.
            (output_dir / _TILE_DIR).mkdir(exist_ok=True)
            for tile in tiles:
                os.replace(
                    stage / _TILE_DIR / tile.name, output_dir / _TILE_DIR / tile.name
                )
            for name in vrt_names.values():
                os.replace(stage / name, output_dir / name)
    except BaseException:
        # Leave no empty directory behind that this call had to create.
        for path in created:
            with suppress(OSError):
                path.rmdir()
        raise
    logger.info(
        "Wrote %d unit tiles and %d VRTs of %s to %s",
        len(tiles),
        len(vrt_names),
        base_name,
        output_dir,
    )
    return (
        {suffix: output_dir / name for suffix, name in vrt_names.items()},
        {
            owner: {
                raster.suffix: output_dir / _TILE_DIR / names[owner, raster.suffix]
                for raster in opened
            }
            for owner in bounds
        },
    )
