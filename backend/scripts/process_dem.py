r"""
Script to process DEM (Digital Elevation Model) and populate stream tables.

Reads ASCII GRID DEM file or VRT mosaic, computes hydrological parameters
(flow direction, flow accumulation, slope), and loads data into PostgreSQL/PostGIS.

Supports:
- Single ASCII GRID (.asc) files
- VRT mosaics (.vrt) created from multiple tiles
- GeoTIFF (.tif) files

For multi-tile processing, use VRT mosaic to ensure hydrological continuity
across tile boundaries. See utils/raster_utils.py for VRT creation.

Usage
-----
    cd backend
    python -m scripts.process_dem --help
    python -m scripts.process_dem --input ../data/nmt/N-33-131-D-a-3-2.asc

Examples
--------
    # Process single DEM tile
    python -m scripts.process_dem \
        --input ../data/nmt/N-33-131-D-a-3-2.asc

    # Process VRT mosaic (multiple tiles)
    python -m scripts.process_dem \
        --input ../data/nmt/mosaic.vrt

    # Dry run (only show statistics)
    python -m scripts.process_dem \
        --input ../data/nmt/N-33-131-D-a-3-2.asc \
        --dry-run
"""

import argparse
import logging
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import numba
import numpy as np
from sqlalchemy import text

from core.active_run import clear_active_run
from core.constants import PIPELINE_THRESHOLDS_M2
from core.db_bulk import (
    insert_bdot_streams,
    insert_catchments,
    insert_stream_segments,
    load_bdot_streams_from_gpkg,
    update_stream_real_flags_all,
)
from core.hydrology import (
    VALID_D8_SET,
    burn_streams_into_dem,
    classify_endorheic_lakes,
    fill_internal_nodata_holes,
    fix_internal_sinks,
    process_hydrology_pyflwdir,
    raise_buildings_in_dem,
    recompute_flow_accumulation,
)
from core.morphometry_raster import (
    compute_aspect,
    compute_aspect_from_gradients,
    compute_slope_from_gradients,
    compute_strahler_from_fdir,
    compute_strahler_order,
    compute_twi,
    gradient_strips,
)
from core.raster_io import (
    GeoTiffWriter,
    downsample_raster,
    read_ascii_grid,
    read_raster,
    save_raster_geotiff,
)
from core.sewer_service import (
    build_sewer_graph,
    burn_inlets,
    insert_sewer_data,
    propagate_fa_downstream,
    reconstruct_inlet_fa,
    route_fa_through_sewer,
)
from core.sewer_topology import parse_sewer_topology, validate_against_fdir
from core.stream_extraction import (
    compute_downstream_links,
    delineate_subcatchments,
    polygonize_subcatchments,
    vectorize_streams,
)
from scripts.download_sewer import load_sewer_data

# Re-export all public names for backward compatibility
__all__ = [
    "VALID_D8_SET",
    "burn_streams_into_dem",
    "classify_endorheic_lakes",
    "compute_aspect",
    "compute_downstream_links",
    "compute_strahler_from_fdir",
    "compute_strahler_order",
    "compute_twi",
    "d8_from_saved_flowdir",
    "delineate_subcatchments",
    "fill_internal_nodata_holes",
    "fix_internal_sinks",
    "insert_catchments",
    "insert_stream_segments",
    "load_hydrology_intermediates",
    "main",
    "polygonize_subcatchments",
    "process_dem",
    "process_dem_from_intermediates",
    "process_hydrology_pyflwdir",
    "raise_buildings_in_dem",
    "read_ascii_grid",
    "read_raster",
    "recompute_flow_accumulation",
    "save_raster_geotiff",
    "vectorize_streams",
]

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Catchments only for thresholds >= 1000 m² (ADR-026)
MIN_CATCHMENT_THRESHOLD_M2 = 1000

# Hydrology rasters saved with save_intermediates that later runs read again
# (load_hydrology_intermediates): name -> file suffix after the DEM's stem
INTERMEDIATE_SUFFIXES = {
    "filled_dem": "02_filled",
    "fdir": "03_flowdir",
    "acc": "04_flowacc",
    "flow_dist_m": "04b_stream_distance",
    "slope": "05_slope",
}

# Rows of a strip of the slope, aspect and TWI computation (_slope_aspect_twi); a
# multiple of the 256 rows of the tiles of GeoTiffWriter, which then writes every
# tile once
STRIP_ROWS = 512
# GeoTIFFs of _slope_aspect_twi: name -> nodata (float32)
_STRIP_RASTER_NODATA = {"slope": -1.0, "aspect": -1.0, "twi": -9999.0}


def _get_transform(metadata: dict[str, Any], dem_shape: tuple[int, int]):
    """Retrieve or construct rasterio Affine transform from metadata."""
    transform = metadata.get("transform")
    if transform is not None:
        return transform
    from rasterio.transform import from_bounds

    xll, yll = metadata["xllcorner"], metadata["yllcorner"]
    nrows, ncols = dem_shape
    cs = metadata["cellsize"]
    return from_bounds(xll, yll, xll + ncols * cs, yll + nrows * cs, ncols, nrows)


@numba.njit(cache=True)
def _per_label_argmax(
    labels: np.ndarray,
    values: np.ndarray,
    flat_indices: np.ndarray,
    max_label: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Find the max value per label and the flat index of its first entry.

    Parameters
    ----------
    labels : 1-D array of int labels (0..max_label).
    values : 1-D array of floats to maximize over.
    flat_indices : 1-D array of original flat raster indices corresponding
        to *labels* / *values* entries.
    max_label : maximum label value (result arrays sized max_label+1).

    Returns
    -------
    best_value : array[max_label+1] — max value per label (-1 if absent).
    best_idx : array[max_label+1] — original flat index of the first entry
        (in the order of the input) with the max value, -1 if absent.
    """
    best_value = np.full(max_label + 1, -1.0)
    best_idx = np.full(max_label + 1, -1, dtype=np.intp)
    for k in range(labels.size):
        label = labels[k]
        if label < 0 or label > max_label:
            raise IndexError("label outside 0..max_label")
        if best_idx[label] < 0 or values[k] > best_value[label]:
            best_value[label] = values[k]
            best_idx[label] = flat_indices[k]
    return best_value, best_idx


@numba.njit(cache=True)
def _farthest_cells(
    label_raster: np.ndarray,
    flow_dist_m: np.ndarray,
    max_label: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Find each label's cell of the largest flow distance, overall and on its boundary.

    One pass over the raster in the order of the flat indices: of equal flow
    distances the first cell wins, as in _per_label_argmax over the cells in that
    order. A cell of a label is on its boundary when it lies on the frame of the
    raster or a 4-neighbour has another label.

    Parameters
    ----------
    label_raster : 2-D array of int labels (0 = unassigned).
    flow_dist_m : 2-D array of the flow distance to the outlet [m].
    max_label : maximum label value (result arrays sized max_label+1).

    Returns
    -------
    best_dist : array[max_label+1] — largest flow distance per label (-1 if absent).
    best_idx : array[max_label+1] — flat index of its cell (-1 if absent).
    divide_idx : array[max_label+1] — flat index of the boundary cell with the
        largest flow distance (-1 if absent).
    """
    nrows, ncols = label_raster.shape
    best_dist = np.full(max_label + 1, -1.0)
    best_idx = np.full(max_label + 1, -1, dtype=np.intp)
    divide_dist = np.full(max_label + 1, -1.0)
    divide_idx = np.full(max_label + 1, -1, dtype=np.intp)
    for row in range(nrows):
        for col in range(ncols):
            label = label_raster[row, col]
            if label <= 0:
                continue
            dist = flow_dist_m[row, col]
            idx = row * ncols + col
            if best_idx[label] < 0 or dist > best_dist[label]:
                best_dist[label] = dist
                best_idx[label] = idx
            on_boundary = (
                row == 0
                or row == nrows - 1
                or col == 0
                or col == ncols - 1
                or label_raster[row - 1, col] != label
                or label_raster[row + 1, col] != label
                or label_raster[row, col - 1] != label
                or label_raster[row, col + 1] != label
            )
            if on_boundary and (divide_idx[label] < 0 or dist > divide_dist[label]):
                divide_dist[label] = dist
                divide_idx[label] = idx
    return best_dist, best_idx, divide_idx


@numba.njit(cache=True)
def _trace_in_labels(
    starts: np.ndarray,
    flat_labels: np.ndarray,
    idxs_ds: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Trace flow paths downstream, each only within the label of its start cell.

    A path runs from its start cell along ``idxs_ds`` to a pit, to a cell
    without a flow direction (-1 in ``idxs_ds``) or to the first cell of another
    label, which it includes: the path of pyflwdir's FlwdirRaster.path cut after
    it leaves the label.

    Parameters
    ----------
    starts : 1-D array of the flat indices of the start cells.
    flat_labels : flattened label raster.
    idxs_ds : flat index of the downstream cell of each cell (FlwdirRaster.idxs_ds).

    Returns
    -------
    cells : the paths one after another (flat indices, dtype of ``idxs_ds``).
    offsets : array[len(starts)+1] — path k is cells[offsets[k]:offsets[k + 1]].
    """
    offsets = np.zeros(starts.size + 1, dtype=np.int64)
    for k in range(starts.size):
        idx = starts[k]
        label = flat_labels[idx]
        length = 1
        downstream = idxs_ds[idx]
        while downstream != idx and downstream >= 0:
            length += 1
            if flat_labels[downstream] != label:
                break
            idx = downstream
            downstream = idxs_ds[idx]
        offsets[k + 1] = offsets[k] + length
    cells = np.empty(offsets[-1], dtype=idxs_ds.dtype)
    for k in range(starts.size):
        position = offsets[k]
        idx = starts[k]
        cells[position] = idx
        label = flat_labels[idx]
        downstream = idxs_ds[idx]
        while downstream != idx and downstream >= 0:
            position += 1
            cells[position] = downstream
            if flat_labels[downstream] != label:
                break
            idx = downstream
            downstream = idxs_ds[idx]
    return cells, offsets


def _path_wkt(
    path_idxs: np.ndarray,
    flat_dist: np.ndarray,
    flw: Any,
    simplify_tol: float,
) -> tuple[str | None, float | None]:
    """Return the simplified WKT of a flow path and the flow distance at its end [m]."""
    from shapely.geometry import LineString

    if len(path_idxs) < 2:
        return None, None
    outlet_flow_dist_m = float(flat_dist[path_idxs[-1]])
    xs, ys = flw.xy(path_idxs)
    line = LineString(zip(xs, ys, strict=True))
    if len(path_idxs) > 3:
        line = line.simplify(simplify_tol, preserve_topology=True)
    return line.wkt, outlet_flow_dist_m


def _stream_head_cells(
    flat_labels: np.ndarray,
    stream_flat: np.ndarray,
    flat_dist: np.ndarray,
    max_label: int,
) -> np.ndarray:
    """Return the upstream end of the stream segment of each label.

    The cells of a segment lie on one flow path, so its upstream end is its
    stream cell farthest from the outlet.

    Parameters
    ----------
    flat_labels : np.ndarray
        Flattened label raster (1-based segment indices, 0 = unassigned).
    stream_flat : np.ndarray
        Flattened stream mask of the labels' threshold (bool).
    flat_dist : np.ndarray
        Flattened flow distance to the outlet [m].
    max_label : int
        Highest label.

    Returns
    -------
    np.ndarray
        array[max_label + 1] of flat indices, -1 for a label without a stream cell.
    """
    stream_idx = np.flatnonzero(stream_flat & (flat_labels > 0))
    if stream_idx.size == 0:
        return np.full(max_label + 1, -1, dtype=np.intp)
    _, head_idx = _per_label_argmax(
        flat_labels[stream_idx], flat_dist[stream_idx], stream_idx, max_label
    )
    return head_idx


def _overland_segments(
    head_idxs: np.ndarray,
    flw: Any,
    stream_mask: np.ndarray,
    flat_dem: np.ndarray,
) -> tuple[list[float | None], list[float | None]]:
    """Measure the overland segment of flow paths, from their heads to the streams.

    The segment runs along the flow directions from a head cell to the first
    cell of the stream mask. It is not measurable (None) when the head is a
    stream cell or the path ends in a pit before it reaches a stream.

    Parameters
    ----------
    head_idxs : np.ndarray
        Flat indices of the head cells.
    flw : pyflwdir.FlwdirRaster
        Flow directions.
    stream_mask : np.ndarray
        2-D stream mask of the threshold (bool).
    flat_dem : np.ndarray
        Flattened filled DEM.

    Returns
    -------
    tuple[list[float | None], list[float | None]]
        Length [m] and drop [m] of the segment of each head.
    """
    paths, dists = flw.path(idxs=head_idxs, mask=stream_mask, unit="m")
    stream_flat = stream_mask.ravel()
    lengths: list[float | None] = []
    drops: list[float | None] = []
    for head, path, dist in zip(head_idxs, paths, dists, strict=True):
        end = path[-1]
        if len(path) < 2 or not stream_flat[end]:
            lengths.append(None)
            drops.append(None)
            continue
        lengths.append(round(float(dist), 1))
        drops.append(round(float(flat_dem[head]) - float(flat_dem[end]), 2))
    return lengths, drops


def _enrich_catchments_with_flow_paths(
    catchments: list[dict[str, Any]],
    label_raster: np.ndarray,
    flow_dist_m: np.ndarray,
    flw,
    metadata: dict[str, Any],
    filled_dem: np.ndarray,
    stream_mask: np.ndarray,
) -> None:
    """Add the flow path fields to each catchment dict.

    Sets max_flow_dist_m, longest_flow_path_wkt, divide_flow_path_wkt,
    outlet_flow_dist_m, flow_path_head_elev_m, overland_length_m,
    overland_drop_m and stream_head_elev_m.

    One pass over the label raster finds the farthest cell (max flow distance)
    of each sub-catchment, overall and on its boundary; the flow paths from
    them are traced only as far as the first cell outside the sub-catchment.

    Two flow paths are computed per subcatchment:
    - longest_flow_path: from the cell with max flow_dist_m (anywhere)
    - divide_flow_path: from the cell with max flow_dist_m on the boundary

    The head of the longest flow path gets its elevation and its overland
    segment (to the first cell of ``stream_mask``); the stream segment of the
    sub-catchment gets the elevation of its upstream end. Elevations come from
    ``filled_dem``, the DEM of the zonal statistics; what cannot be measured
    is None.

    Parameters
    ----------
    catchments : list[dict]
        Catchment dicts from polygonize_subcatchments() — modified in place.
    label_raster : np.ndarray
        int32 label raster (1-based segment indices, 0=unassigned).
    flow_dist_m : np.ndarray
        Flow distance from each cell to outlet [m].
    flw : pyflwdir.FlwdirRaster
        Flow direction raster object.
    metadata : dict
        Grid metadata (cellsize, transform, etc.).
    filled_dem : np.ndarray
        Filled DEM.
    stream_mask : np.ndarray
        Stream cells of the threshold of ``label_raster`` (bool, 2-D).
    """
    t0 = time.time()
    cellsize = metadata["cellsize"]
    simplify_tol = 2 * cellsize
    flat_dist = flow_dist_m.ravel()
    flat_labels = label_raster.ravel()
    flat_dem = filled_dem.ravel()

    # Phase 1: cell with max flow distance per sub-catchment, overall and on the
    # sub-catchment's boundary (a 4-neighbour with another label, or the frame)
    max_label = int(label_raster.max())
    best_dist, best_idx, divide_best_idx = _farthest_cells(
        label_raster, flow_dist_m, max_label
    )

    # Phase 1a: upstream end of the stream segment of each sub-catchment
    stream_head_idx = _stream_head_cells(
        flat_labels, stream_mask.ravel(), flat_dist, max_label
    )

    # Build batch arrays: one starting index per catchment (longest + divide)
    catch_order = []  # index into catchments list
    start_idxs = []  # flat index of farthest cell (overall)
    divide_catch_order = []  # index into catchments list (divide paths)
    divide_start_idxs = []  # flat index of farthest boundary cell
    for ci, catch in enumerate(catchments):
        seg_idx = catch["segment_idx"]
        head = stream_head_idx[seg_idx] if seg_idx <= max_label else -1
        catch["stream_head_elev_m"] = (
            round(float(flat_dem[head]), 2) if head >= 0 else None
        )
        if seg_idx <= max_label and best_idx[seg_idx] >= 0:
            catch_order.append(ci)
            start_idxs.append(best_idx[seg_idx])
            catch["max_flow_dist_m"] = float(best_dist[seg_idx])
        else:
            catch["max_flow_dist_m"] = None
            catch["longest_flow_path_wkt"] = None
            catch["divide_flow_path_wkt"] = None
            catch["outlet_flow_dist_m"] = None
            catch["flow_path_head_elev_m"] = None
            catch["overland_length_m"] = None
            catch["overland_drop_m"] = None
            continue

        # Divide path: only if boundary cell differs from overall max cell
        if (
            seg_idx <= max_label
            and divide_best_idx[seg_idx] >= 0
            and divide_best_idx[seg_idx] != best_idx[seg_idx]
        ):
            divide_catch_order.append(ci)
            divide_start_idxs.append(divide_best_idx[seg_idx])
        else:
            catch["divide_flow_path_wkt"] = None

    del best_idx, best_dist, divide_best_idx, stream_head_idx

    if not start_idxs:
        logger.info("  No flow paths to trace (no valid catchments)")
        return

    start_arr = np.array(start_idxs, dtype=np.intp)

    # Phase 2a: head of each longest flow path and its overland segment
    lengths, drops = _overland_segments(start_arr, flw, stream_mask, flat_dem)
    for i, ci in enumerate(catch_order):
        catchments[ci]["flow_path_head_elev_m"] = round(
            float(flat_dem[start_arr[i]]), 2
        )
        catchments[ci]["overland_length_m"] = lengths[i]
        catchments[ci]["overland_drop_m"] = drops[i]
    overland_measured = sum(length is not None for length in lengths)
    del lengths, drops

    # Phase 2: longest flow paths, each traced to the first cell outside its
    # sub-catchment
    paths, path_offsets = _trace_in_labels(start_arr, flat_labels, flw.idxs_ds)

    # Phase 2b: divide flow paths
    divide_paths = None
    if divide_start_idxs:
        divide_arr = np.array(divide_start_idxs, dtype=np.intp)
        divide_paths, divide_offsets = _trace_in_labels(
            divide_arr, flat_labels, flw.idxs_ds
        )
        del divide_arr

    # Phase 3: geometry of the longest flow paths
    traced = 0
    for i, ci in enumerate(catch_order):
        wkt, outlet_dist = _path_wkt(
            paths[path_offsets[i] : path_offsets[i + 1]], flat_dist, flw, simplify_tol
        )
        catchments[ci]["longest_flow_path_wkt"] = wkt
        # Jednokomorkowe/bez sciezki: ujscie = najdalsza komorka (dlugosc 0)
        catchments[ci]["outlet_flow_dist_m"] = (
            outlet_dist
            if outlet_dist is not None
            else catchments[ci]["max_flow_dist_m"]
        )
        if wkt is not None:
            traced += 1

    # Phase 3b: geometry of the divide flow paths
    divide_traced = 0
    if divide_paths is not None:
        for i, ci in enumerate(divide_catch_order):
            wkt, _ = _path_wkt(
                divide_paths[divide_offsets[i] : divide_offsets[i + 1]],
                flat_dist,
                flw,
                simplify_tol,
            )
            catchments[ci]["divide_flow_path_wkt"] = wkt
            if wkt is not None:
                divide_traced += 1

    elapsed = time.time() - t0
    logger.info(
        f"  Flow path tracing: {traced} longest + {divide_traced} divide "
        f"/ {len(catchments)} catchments, {overland_measured} overland segments "
        f"in {elapsed:.1f}s"
    )


def _slope_aspect_twi(
    filled_dem: np.ndarray,
    acc: np.ndarray,
    metadata: dict[str, Any],
    output_paths: dict[str, Path] | None = None,
    strip_rows: int = STRIP_ROWS,
) -> np.ndarray:
    """Compute the slope, aspect and TWI strip by strip; return the slope.

    The Sobel gradients of each strip of ``strip_rows`` rows come from
    gradient_strips, so the three rasters equal their computation over the whole
    raster bit for bit, while besides the slope only one strip is in memory. The
    aspect and the TWI are not kept: with ``output_paths`` their strips are
    written to GeoTIFF windows, and the ranges of all three are logged.

    Parameters
    ----------
    filled_dem : np.ndarray
        Filled DEM.
    acc : np.ndarray
        Flow accumulation [cells] (0 = nodata).
    metadata : dict
        Grid metadata (cellsize, nodata_value, transform).
    output_paths : dict[str, Path], optional
        GeoTIFFs (float32) of "slope", "aspect" and "twi", nodata in
        _STRIP_RASTER_NODATA.
    strip_rows : int
        Rows of a strip.

    Returns
    -------
    np.ndarray
        Slope [%] (float64).
    """
    cellsize = metadata["cellsize"]
    logger.info("Computing slope, aspect and TWI in strips of %d rows...", strip_rows)
    slope = np.empty(filled_dem.shape, dtype=np.float64)
    aspect_min, aspect_max = np.inf, -np.inf
    twi_min, twi_max = np.inf, -np.inf
    with ExitStack() as stack:
        writers = {
            name: stack.enter_context(
                GeoTiffWriter(
                    path,
                    metadata,
                    filled_dem.shape,
                    nodata=_STRIP_RASTER_NODATA[name],
                    dtype="float32",
                )
            )
            for name, path in (output_paths or {}).items()
        }
        for rows, dx, dy in gradient_strips(
            filled_dem, cellsize, metadata["nodata_value"], strip_rows
        ):
            slope[rows] = compute_slope_from_gradients(dx, dy)
            aspect = compute_aspect_from_gradients(dx, dy)
            del dx, dy
            twi = compute_twi(acc[rows], slope[rows], cellsize, nodata_acc=0)
            valid_aspect = aspect[aspect >= 0]
            if valid_aspect.size:
                aspect_min = min(aspect_min, valid_aspect.min())
                aspect_max = max(aspect_max, valid_aspect.max())
            valid_twi = twi[twi > -9999]
            if valid_twi.size:
                twi_min = min(twi_min, valid_twi.min())
                twi_max = max(twi_max, valid_twi.max())
            del valid_aspect, valid_twi
            for name, strip in (
                ("slope", slope[rows]),
                ("aspect", aspect),
                ("twi", twi),
            ):
                if name in writers:
                    writers[name].write_rows(rows.start, strip)
    logger.info("Slope computed (range: %.1f%% - %.1f%%)", slope.min(), slope.max())
    if aspect_min <= aspect_max:
        logger.info("Aspect computed (range: %.1f° - %.1f°)", aspect_min, aspect_max)
    if twi_min <= twi_max:
        logger.info("TWI computed (range: %.1f - %.1f)", twi_min, twi_max)
    return slope


def _process_thresholds(
    threshold_list_m2: list[int],
    *,
    filled_dem: np.ndarray,
    fdir: np.ndarray,
    acc: np.ndarray,
    slope: np.ndarray,
    flw: Any,
    flow_dist_m: np.ndarray,
    metadata: dict[str, Any],
    strahler_by_cells: dict[int, np.ndarray],
    skip_catchments: bool,
    save_intermediates: bool,
    output_dir: Path,
    base_name: str,
) -> tuple[dict[int, list[dict[str, Any]]], dict[int, list[dict[str, Any]]]]:
    """Vectorize the streams and delineate the sub-catchments of each threshold.

    Parameters
    ----------
    threshold_list_m2 : list[int]
        Flow accumulation thresholds [m²]. They are processed from the largest,
        so that the many results of the smallest one are not held while the
        others are computed; the results come back in ascending order of the
        thresholds, the order of the database rows.
    filled_dem : np.ndarray
        Filled DEM, the DEM of the zonal statistics.
    fdir : np.ndarray
        D8 flow directions (int16, 0 = none) of the stream tracing.
    acc : np.ndarray
        Flow accumulation [cells].
    slope : np.ndarray
        Slope [%].
    flw : pyflwdir.FlwdirRaster
        Flow directions of the basins and the flow paths.
    flow_dist_m : np.ndarray
        Flow distance to the outlet [m].
    metadata : dict
        Grid metadata (cellsize, nodata_value, transform).
    strahler_by_cells : dict[int, np.ndarray]
        Strahler orders computed beforehand, by threshold in cells. The others
        are computed here and, with ``save_intermediates``, saved as
        ``<base_name>_07_stream_order_<threshold>.tif``.
    skip_catchments : bool
        Vectorize the streams only.
    save_intermediates : bool
        Save the rasters of each threshold as GeoTIFF.
    output_dir : Path
        Directory of the saved rasters.
    base_name : str
        Prefix of the saved rasters.

    Returns
    -------
    tuple[dict, dict]
        Stream segments and sub-catchments by threshold [m²].
    """
    nodata = metadata["nodata_value"]
    cell_area = metadata["cellsize"] * metadata["cellsize"]
    all_stream_segments: dict[int, list[dict[str, Any]]] = {}
    all_catchment_data: dict[int, list[dict[str, Any]]] = {}
    for threshold_m2 in sorted(threshold_list_m2, reverse=True):
        threshold_cells = max(1, int(threshold_m2 / cell_area))
        logger.info(
            f"--- Vectorizing streams for threshold "
            f"{threshold_m2} m² ({threshold_cells} cells) ---"
        )

        strahler_t = strahler_by_cells.get(threshold_cells)
        if strahler_t is None:
            strahler_t = compute_strahler_from_fdir(flw, acc, threshold_cells)
            if save_intermediates:
                save_raster_geotiff(
                    strahler_t,
                    metadata,
                    output_dir / f"{base_name}_07_stream_order_{threshold_m2}.tif",
                    nodata=0,
                    dtype="uint8",
                )

        # Allocate label raster for sub-catchment delineation
        label_raster = None
        if not skip_catchments:
            label_raster = np.zeros_like(filled_dem, dtype=np.int32)

        segments = vectorize_streams(
            filled_dem,
            fdir,
            acc,
            slope,
            strahler_t,
            metadata,
            threshold_cells,
            label_raster_out=label_raster,
        )
        all_stream_segments[threshold_m2] = segments

        # Delineate and polygonize sub-catchments
        if label_raster is not None and threshold_m2 >= MIN_CATCHMENT_THRESHOLD_M2:
            delineate_subcatchments(flw, label_raster, filled_dem, nodata)

            # Compute downstream links for catchment graph
            compute_downstream_links(segments, label_raster, fdir, metadata)

            if save_intermediates:
                save_raster_geotiff(
                    label_raster,
                    metadata,
                    output_dir / f"{base_name}_10_subcatchments_{threshold_m2}.tif",
                    nodata=0,
                    dtype="int32",
                )

            catchments = polygonize_subcatchments(
                label_raster,
                filled_dem,
                slope,
                metadata,
                segments,
                flow_dist_m=flow_dist_m,
            )

            # Flow paths, their heads and overland segments (batch)
            stream_mask = (acc >= threshold_cells) & (filled_dem != nodata)
            _enrich_catchments_with_flow_paths(
                catchments,
                label_raster,
                flow_dist_m,
                flw,
                metadata,
                filled_dem,
                stream_mask,
            )
            del stream_mask

            all_catchment_data[threshold_m2] = catchments

        logger.info(f"  Threshold {threshold_m2} m²: {len(segments)} segments")
        # Free the rasters of this threshold before the next one is computed
        del label_raster, strahler_t

    return (
        {t: all_stream_segments[t] for t in sorted(all_stream_segments)},
        {t: all_catchment_data[t] for t in sorted(all_catchment_data)},
    )


def _record_threshold_stats(
    stats: dict[str, Any],
    all_stream_segments: dict[int, list[dict[str, Any]]],
    all_catchment_data: dict[int, list[dict[str, Any]]],
) -> None:
    """Put the counts of segments and sub-catchments per threshold in ``stats``."""
    stats["stream_segments"] = sum(len(s) for s in all_stream_segments.values())
    stats["stream_thresholds"] = {t: len(s) for t, s in all_stream_segments.items()}
    if all_catchment_data:
        stats["catchment_thresholds"] = {
            t: len(c) for t, c in all_catchment_data.items()
        }


def _insert_thresholds(
    db: Any,
    all_stream_segments: dict[int, list[dict[str, Any]]],
    all_catchment_data: dict[int, list[dict[str, Any]]],
    stats: dict[str, Any],
) -> None:
    """Insert the stream segments and sub-catchments of each threshold.

    Parameters
    ----------
    db : Session
        Database session.
    all_stream_segments, all_catchment_data : dict
        Results of _process_thresholds.
    stats : dict
        Gets ``stream_segments_inserted`` and ``catchments_inserted``.
    """
    total_seg_inserted = 0
    for threshold_m2, segments in all_stream_segments.items():
        if segments:
            total_seg_inserted += insert_stream_segments(
                db, segments, threshold_m2=threshold_m2
            )
    if total_seg_inserted > 0:
        stats["stream_segments_inserted"] = total_seg_inserted

    total_catch_inserted = 0
    for threshold_m2, catchments in all_catchment_data.items():
        if catchments:
            total_catch_inserted += insert_catchments(
                db, catchments, threshold_m2=threshold_m2
            )
    if total_catch_inserted > 0:
        stats["catchments_inserted"] = total_catch_inserted

    # Validate stream vs catchment counts per threshold
    for threshold_m2 in all_stream_segments:
        stream_count = len(all_stream_segments.get(threshold_m2, []))
        catchment_count = len(all_catchment_data.get(threshold_m2, []))
        if stream_count != catchment_count:
            logger.warning(
                f"Stream/catchment mismatch for threshold={threshold_m2} m²: "
                f"{stream_count} streams vs {catchment_count} catchments"
            )


def load_hydrology_intermediates(
    input_path: Path,
    output_dir: Path | None = None,
    names: tuple[str, ...] = tuple(INTERMEDIATE_SUFFIXES),
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Read the hydrology rasters that a run saved with ``save_intermediates``.

    Parameters
    ----------
    input_path : Path
        DEM of that run; its stem prefixes the rasters
        (``<stem>_02_filled.tif``, ``_03_flowdir``, ``_04_flowacc``,
        ``_04b_stream_distance``, ``_05_slope``).
    output_dir : Path, optional
        Directory of the rasters (default: the directory of ``input_path``).
    names : tuple[str, ...]
        Rasters to read, keys of INTERMEDIATE_SUFFIXES (default: all).

    Returns
    -------
    tuple[dict[str, np.ndarray], dict[str, Any]]
        The rasters by name (``filled_dem``, ``fdir``, ``acc``, ``flow_dist_m``,
        ``slope``) and the grid metadata of the first of them.

    Raises
    ------
    FileNotFoundError
        When a raster is missing.
    ValueError
        When the rasters are not on one grid.
    """
    directory = Path(output_dir) if output_dir is not None else input_path.parent
    paths = {
        name: directory / f"{input_path.stem}_{INTERMEDIATE_SUFFIXES[name]}.tif"
        for name in names
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Saved hydrology rasters not found: " + ", ".join(missing)
        )
    rasters: dict[str, np.ndarray] = {}
    metadata: dict[str, Any] = {}
    for name, path in paths.items():
        data, meta = read_raster(path)
        if not rasters:
            metadata = meta
        elif data.shape != (metadata["nrows"], metadata["ncols"]) or (
            meta["transform"] != metadata["transform"]
        ):
            raise ValueError(f"{path} is not on the grid of {paths[names[0]]}")
        rasters[name] = data
    return rasters, metadata


def d8_from_saved_flowdir(
    fdir: np.ndarray,
    flow_dist_m: np.ndarray,
    valid: np.ndarray,
) -> np.ndarray:
    """Rebuild the pyflwdir D8 grid of a run from its saved rasters.

    The saved flow directions (``_03_flowdir``) are pyflwdir's D8 grid; in the
    rasters of runs before fix_internal_sinks stopped fixing the pits at the
    edge of the data, it had given those pits a direction. Those pits are the
    only cells with a flow distance of 0, so they become pits again (a no-op for
    newer runs); cells outside the DEM become pyflwdir's nodata (247).

    Parameters
    ----------
    fdir : np.ndarray
        Saved D8 flow directions (int16, 0 = none).
    flow_dist_m : np.ndarray
        Saved flow distance to the outlet [m].
    valid : np.ndarray
        Cells of the DEM (bool).

    Returns
    -------
    np.ndarray
        pyflwdir D8 flow directions (uint8).
    """
    d8 = fdir.astype(np.uint8)
    d8[valid & (flow_dist_m == 0)] = 0
    d8[~valid] = 247
    return d8


def _supersede_active_unit_run(db: Any) -> int | None:
    """Mark the active run by PGW units ``superseded``; return its id, or None.

    A run of the whole raster replaces (or adds to) the network that the active run
    published. Without migration 005 there is no ``processing_runs`` and nothing to
    supersede. The caller commits.
    """
    if db.execute(text("SELECT to_regclass('processing_runs')")).scalar() is None:
        return None
    superseded: int | None = db.execute(
        text(
            "UPDATE processing_runs SET status = 'superseded', "
            "superseded_at = now() WHERE status = 'active' RETURNING id"
        )
    ).scalar()
    return superseded


def _thresholds_in_database(db: Any) -> set[int]:
    """Return the thresholds [m²] of the stream networks and sub-catchments."""
    rows = db.execute(
        text(
            "SELECT threshold_m2 FROM stream_network "
            "UNION SELECT threshold_m2 FROM stream_catchments"
        )
    ).fetchall()
    return {int(row[0]) for row in rows}


def process_dem_from_intermediates(
    input_path: Path,
    thresholds: list[int],
    output_dir: Path | None = None,
    dry_run: bool = False,
    save_intermediates: bool = False,
) -> dict[str, Any]:
    """Add the stream networks and sub-catchments of new thresholds.

    Reads the hydrology rasters of an earlier run (load_hydrology_intermediates)
    instead of computing it again, so the new thresholds share the flow
    directions, accumulation and flow distances of the data in the database,
    whose rows stay as they are. A threshold the database already holds is
    refused. The new streams are matched against the BDOT10k streams of the
    database.

    Parameters
    ----------
    input_path : Path
        DEM of the earlier run (only its stem and directory are used).
    thresholds : list[int]
        New flow accumulation thresholds [m²].
    output_dir : Path, optional
        Directory of the saved rasters (default: the directory of ``input_path``).
    dry_run : bool
        Compute without touching the database.
    save_intermediates : bool
        Save the Strahler and sub-catchment rasters of the new thresholds.

    Returns
    -------
    dict
        Processing statistics.

    Raises
    ------
    ValueError
        When a threshold is already in the database.
    """
    import pyflwdir

    from core.database import get_db_session

    directory = Path(output_dir) if output_dir is not None else input_path.parent
    threshold_list_m2 = sorted(set(thresholds))
    if not dry_run:
        with get_db_session() as db:
            present = sorted(set(threshold_list_m2) & _thresholds_in_database(db))
        if present:
            raise ValueError(
                f"Thresholds already in the database: {present} m². "
                "Run the full pipeline (--clear-existing) to compute them again."
            )

    rasters, metadata = load_hydrology_intermediates(input_path, directory)
    filled_dem = rasters["filled_dem"]
    d8_fdir = d8_from_saved_flowdir(
        rasters["fdir"],
        rasters["flow_dist_m"],
        filled_dem != metadata["nodata_value"],
    )
    flw = pyflwdir.from_array(
        d8_fdir,
        ftype="d8",
        transform=_get_transform(metadata, filled_dem.shape),
        latlon=False,
    )
    # As in process_hydrology_pyflwdir: ordered by sorting, without the upstream
    # matrix of pyflwdir's default walk
    flw.order_cells(method="sort")
    del d8_fdir
    stats: dict[str, Any] = {
        "ncols": metadata["ncols"],
        "nrows": metadata["nrows"],
        "cellsize": metadata["cellsize"],
        "thresholds": threshold_list_m2,
    }

    all_stream_segments, all_catchment_data = _process_thresholds(
        threshold_list_m2,
        filled_dem=filled_dem,
        fdir=rasters["fdir"],
        acc=rasters["acc"],
        slope=rasters["slope"],
        flw=flw,
        flow_dist_m=rasters["flow_dist_m"],
        metadata=metadata,
        strahler_by_cells={},
        skip_catchments=False,
        save_intermediates=save_intermediates,
        output_dir=directory,
        base_name=input_path.stem,
    )
    _record_threshold_stats(stats, all_stream_segments, all_catchment_data)
    del rasters, filled_dem, flw

    if dry_run:
        logger.info("Dry run - skipping database insert")
        return stats

    with get_db_session() as db:
        _insert_thresholds(db, all_stream_segments, all_catchment_data, stats)
        bdot_count = db.execute(text("SELECT COUNT(*) FROM bdot_streams")).scalar()
        if bdot_count:
            all_match = update_stream_real_flags_all(db, threshold_list_m2)
            for threshold_m2, stats_match in all_match.items():
                logger.info(
                    f"Stream matching (threshold={threshold_m2}): "
                    f"{stats_match['real']}/{stats_match['total']} real, "
                    f"{stats_match['overland']} overland"
                )
        else:
            logger.warning("No BDOT10k streams in the database: no stream matching")
    return stats


def process_dem(
    input_path: Path,
    dry_run: bool = False,
    save_intermediates: bool = False,
    output_dir: Path | None = None,
    clear_existing: bool = False,
    burn_streams_path: Path | None = None,
    burn_depth_m: float = 2.0,
    stream_burning: str = "all",
    smooth_streams: bool = True,
    skip_streams_vectorize: bool = False,
    thresholds: list[int] | None = None,
    skip_catchments: bool = False,
    hydro_resolution_m: float | None = None,
    waterbody_mode: str = "none",
    waterbody_min_area_m2: float | None = None,
    building_gpkg: str | None = None,
    sewer_config: dict[str, Any] | None = None,
    units_path: Path | None = None,
    units_area_path: Path | None = None,
    units_area_layer: str | None = None,
    units_catchments_path: Path | None = None,
    units_catchments_layer: str | None = None,
    units_catchments_key: str = "ID_HYD_10",
    max_unit_window_cells: int = 80_000_000,
    units_resume: bool = True,
) -> dict[str, Any]:
    """
    Process DEM file (ASC, VRT, or GeoTIFF) and extract stream network.

    Supports VRT mosaics for multi-tile processing with hydrological continuity
    across tile boundaries.

    Parameters
    ----------
    input_path : Path
        Path to input raster file (.asc, .vrt, or .tif)
    dry_run : bool
        If True, only compute statistics without inserting
    save_intermediates : bool
        If True, save intermediate rasters as GeoTIFF
    output_dir : Path, optional
        Output directory for intermediate files (default: same as input)
    clear_existing : bool
        If True, clear existing data before insert (DELETE).
        Default False to support incremental processing.
    burn_streams_path : Path, optional
        Path to GeoPackage/Shapefile with stream lines for DEM burning
    burn_depth_m : float
        Burn depth in meters (default: 2.0)
    stream_burning : str
        BDOT10k streams burned and smoothed: "all" (every line layer) or "main"
        (the main watercourses, ``core.hydrology._select_burned_features``)
    smooth_streams : bool
        If True, apply monotonic stream smoothing after burning (default: True)
    skip_streams_vectorize : bool
        If True, skip stream vectorization (default: False)
    skip_catchments : bool
        If True, skip sub-catchment delineation (default: False)
    hydro_resolution_m : float, optional
        If set, downsample DEM to this resolution (meters) before processing.
        Reduces memory usage for large rasters. Original resolution kept for overlays.
    waterbody_mode : str
        Waterbody handling mode: "auto" (BDOT10k classification), "none" (skip),
        or path to custom waterbody file (.gpkg/.shp, all treated as endorheic).
    waterbody_min_area_m2 : float, optional
        Minimum waterbody area in m². Bodies smaller than this are ignored.
    building_gpkg : str, optional
        Path to GeoPackage with building footprints (BUBD from BDOT10k).
        DEM is raised by +5m under building footprints before stream burning.
    thresholds : list[int], optional
        FA thresholds in m², one stream network and set of sub-catchments
        each (default: core.constants.PIPELINE_THRESHOLDS_M2). The lowest
        threshold is used for stream_mask and strahler_order.
    units_path : Path, optional
        PGW GeoPackage of Kartograf: process the DEM by PGW owners (ADR-071,
        scripts/process_dem_units.py) instead of as one raster. The results are the
        same; the memory is bounded by the largest buffered owner. A run that is not
        a dry run replaces the DEM-derived network (``clear_existing`` is required),
        and always writes its unit rasters and VRT mosaics (``save_intermediates`` is
        not needed).
    units_area_path : Path, optional
        With ``units_path``: vector file of the analysis area; owners are clipped to it.
    units_area_layer : str, optional
        Layer of ``units_area_path`` (default: the first).
    units_catchments_path : Path, optional
        With ``units_path``: catchments to group into the owners, each to the PGW
        unit it overlaps most; their keys are recorded with the units.
    units_catchments_layer : str, optional
        Layer of ``units_catchments_path`` (default: the first).
    units_catchments_key : str
        Field of the unique key of a catchment (default ``ID_HYD_10``).
    max_unit_window_cells : int
        With ``units_path``: the largest buffered owner window [cells]; a larger one
        fails the run.
    units_resume : bool
        With ``units_path``: resume the latest staging or failed run with the same
        inputs and settings (default) instead of beginning a new one.

    Returns
    -------
    dict
        Processing statistics including:
        - ncols, nrows, cellsize, total_cells
        - valid_cells, max_accumulation, mean_slope
        - stream_cells
        - burn_cells (if burn_streams_path provided)
        - with ``units_path``: run_id, pgw_owners, unit_rasters_dir, unit_dem_vrt,
          resumed_units, stages
    """
    if units_path is not None:
        from scripts.process_dem_units import process_dem_units

        if not dry_run and not clear_existing:
            raise ValueError(
                "A run by PGW units replaces the DEM-derived stream network and "
                "sub-catchments: pass clear_existing (--clear-existing) to confirm"
            )
        return process_dem_units(
            input_path=input_path,
            units_path=units_path,
            dry_run=dry_run,
            output_dir=output_dir,
            burn_streams_path=burn_streams_path,
            burn_depth_m=burn_depth_m,
            stream_burning=stream_burning,
            smooth_streams=smooth_streams,
            skip_streams_vectorize=skip_streams_vectorize,
            thresholds=thresholds,
            skip_catchments=skip_catchments,
            hydro_resolution_m=hydro_resolution_m,
            waterbody_mode=waterbody_mode,
            waterbody_min_area_m2=waterbody_min_area_m2,
            building_gpkg=building_gpkg,
            sewer_config=sewer_config,
            units_area_path=units_area_path,
            units_area_layer=units_area_layer,
            units_catchments_path=units_catchments_path,
            units_catchments_layer=units_catchments_layer,
            units_catchments_key=units_catchments_key,
            max_unit_window_cells=max_unit_window_cells,
            resume=units_resume,
        )

    stats = {}

    # Early validation: custom waterbody file must exist
    if waterbody_mode not in ("auto", "none"):
        wb_path = Path(waterbody_mode)
        if not wb_path.exists():
            raise FileNotFoundError(f"Custom waterbody file not found: {wb_path}")

    # Setup output directory for intermediates
    if output_dir is None:
        output_dir = input_path.parent
    output_dir = Path(output_dir)
    base_name = input_path.stem

    # 1. Read DEM (supports ASC, VRT, GeoTIFF)
    suffix = input_path.suffix.lower()
    if suffix in (".vrt", ".tif", ".tiff"):
        dem, metadata = read_raster(input_path)
    else:
        # Fallback to ASCII grid parser for .asc files
        dem, metadata = read_ascii_grid(input_path)

    stats["ncols"] = metadata["ncols"]
    stats["nrows"] = metadata["nrows"]
    stats["cellsize"] = metadata["cellsize"]
    stats["total_cells"] = metadata["ncols"] * metadata["nrows"]

    nodata = metadata["nodata_value"]
    valid_cells = np.sum(dem != nodata)
    stats["valid_cells"] = int(valid_cells)

    # Save original DEM as GeoTIFF (full resolution, before downsampling)
    if save_intermediates:
        save_raster_geotiff(
            dem,
            metadata,
            output_dir / f"{base_name}_01_dem.tif",
            nodata=nodata,
            dtype="float32",
        )

    # Downsample if requested (OOM prevention for large rasters)
    if hydro_resolution_m is not None and hydro_resolution_m > metadata["cellsize"]:
        fname = f"{base_name}_downsampled_{hydro_resolution_m}m.tif"
        downsampled_path = output_dir / fname
        downsample_raster(input_path, downsampled_path, hydro_resolution_m)
        dem, metadata = read_raster(downsampled_path)

        logger.info(
            f"Using downsampled DEM: {metadata['nrows']}x{metadata['ncols']} cells "
            f"({metadata['cellsize']}m resolution)"
        )

        # Update stats and variables
        stats["ncols"] = metadata["ncols"]
        stats["nrows"] = metadata["nrows"]
        stats["cellsize"] = metadata["cellsize"]
        stats["total_cells"] = metadata["ncols"] * metadata["nrows"]
        stats["hydro_resolution_m"] = hydro_resolution_m

        nodata = metadata["nodata_value"]
        valid_cells = np.sum(dem != nodata)
        stats["valid_cells"] = int(valid_cells)

    # 1b. Raise buildings (optional) — before stream burning and depression filling
    if building_gpkg is not None:
        transform_for_buildings = _get_transform(metadata, dem.shape)
        dem = raise_buildings_in_dem(
            dem, transform_for_buildings, 2180, building_gpkg, nodata=nodata
        )

    # 2. Burn streams (optional) — before depression filling
    if burn_streams_path is not None:
        transform = _get_transform(metadata, dem.shape)
        dem, burn_diag = burn_streams_into_dem(
            dem, transform, burn_streams_path, burn_depth_m, nodata, stream_burning
        )
        stats["burn_cells"] = burn_diag["cells_burned"]
        stats["stream_burning"] = stream_burning
        if save_intermediates:
            save_raster_geotiff(
                dem,
                metadata,
                output_dir / f"{base_name}_02a_burned.tif",
                nodata=nodata,
                dtype="float32",
            )

        # Step 3b: Monotonic stream smoothing
        if smooth_streams:
            from core.hydrology import smooth_streams_monotonic

            dem, smooth_diag = smooth_streams_monotonic(
                dem, transform, burn_streams_path, nodata, stream_burning
            )
            stats["smooth_cells"] = smooth_diag["cells_smoothed"]
            stats["smooth_max_correction_m"] = smooth_diag["max_correction_m"]
            logger.info(
                "Monotonic smoothing: %d cells corrected (max %.1fm)",
                smooth_diag["cells_smoothed"],
                smooth_diag["max_correction_m"],
            )
            if save_intermediates:
                save_raster_geotiff(
                    dem,
                    metadata,
                    output_dir / f"{base_name}_02b_smoothed.tif",
                    nodata=nodata,
                    dtype="float32",
                )

    # 2b. Classify endorheic lakes and compute drain points (optional)
    drain_points = None
    stats["waterbody_mode"] = waterbody_mode
    if waterbody_min_area_m2 is not None:
        stats["waterbody_min_area_m2"] = waterbody_min_area_m2

    if waterbody_mode == "none":
        logger.info("Waterbody mode: none — skipping lake classification")
    elif waterbody_mode == "auto" and burn_streams_path is not None:
        transform_for_lakes = _get_transform(metadata, dem.shape)
        drain_points, drain_diag = classify_endorheic_lakes(
            dem,
            transform_for_lakes,
            burn_streams_path,
            nodata,
            min_area_m2=waterbody_min_area_m2,
        )
        stats["endorheic_lakes"] = drain_diag["endorheic"]
        stats["drain_points"] = len(drain_points)
    elif waterbody_mode not in ("auto", "none"):
        # Custom waterbody file path (already validated above)
        wb_path = Path(waterbody_mode)
        transform_for_lakes = _get_transform(metadata, dem.shape)
        # gpkg_path is required but not used for loading waterbodies
        # when waterbody_path is set; pass burn_streams_path or a dummy
        gpkg_for_classify = burn_streams_path or wb_path
        drain_points, drain_diag = classify_endorheic_lakes(
            dem,
            transform_for_lakes,
            gpkg_for_classify,
            nodata,
            min_area_m2=waterbody_min_area_m2,
            waterbody_path=wb_path,
        )
        stats["endorheic_lakes"] = drain_diag["endorheic"]
        stats["drain_points"] = len(drain_points)

    # 3b. Sewer inlet burning (optional) — two-phase pipeline
    sewer_graph = None
    topology = None
    if sewer_config and sewer_config.get("sewer", {}).get("enabled"):
        logger.info("=== Sewer integration: loading and parsing topology ===")
        sewer_cfg = sewer_config["sewer"]

        # Load data (returns tuple: points_gdf, lines_gdf)
        points_gdf, lines_gdf = load_sewer_data(sewer_config)

        # Parse topology
        field_mapping = sewer_cfg.get(
            "field_mapping", sewer_cfg.get("attribute_mapping", {})
        )
        role_mapping = sewer_cfg.get(
            "role_mapping",
            {
                "inlet": "inlet",
                "outlet": "outlet",
                "junction": "junction",
                "storage": "storage",
            },
        )
        topology = parse_sewer_topology(
            points_gdf,
            lines_gdf,
            field_mapping,
            role_mapping,
        )
        logger.info(
            f"Sewer topology: {len(topology.nodes)} nodes, "
            f"{len(topology.edges)} edges, format={topology.source_format}"
        )

        # Map nodes to raster cells
        transform_sewer = _get_transform(metadata, dem.shape)
        nrows, ncols = dem.shape
        for node in topology.nodes:
            col_f, row_f = ~transform_sewer * (node["x"], node["y"])
            node["row"] = int(round(row_f))
            node["col"] = int(round(col_f))

        # PHASE 1: Compute clean fdir (no sewer burns) for loop validation
        logger.info("Phase 1: computing clean fdir for sewer loop validation")
        import pyflwdir as _pyflwdir

        flw_clean = _pyflwdir.from_dem(
            dem.copy(),
            nodata=metadata.get("nodata", -9999),
            transform=transform_sewer,
            latlon=False,
        )
        fdir_clean = flw_clean.to_d8()

        # Validate: no outlet should drain back to its own component's inlet
        loop_errors = validate_against_fdir(topology, fdir_clean, transform_sewer)
        if loop_errors:
            msg = "Sewer feedback loop detected:\n"
            for err in loop_errors:
                msg += f"  - {err['message']}\n"
            raise ValueError(msg)
        logger.info("Phase 1 complete — no feedback loops detected")
        del fdir_clean, flw_clean  # free memory

        # PHASE 2: Burn inlets into DEM
        inlets = [n for n in topology.nodes if n["role"] == "inlet"]
        dem, drain_points_sewer = burn_inlets(
            dem,
            inlets,
            default_depth_m=sewer_cfg.get("inlet_burn_depth_m", 0.5),
        )
        if drain_points is None:
            drain_points = []
        drain_points.extend(drain_points_sewer)
        stats["sewer_inlets_burned"] = len(drain_points_sewer)
        logger.info(f"Sewer: burned {len(drain_points_sewer)} inlet cells")

    # 3-5. Process hydrology using pyflwdir (fill depressions, flow dir, accumulation)
    # Note: Migrated from pysheds to pyflwdir (Deltares) — fewer deps, no temp files
    # The FlwdirRaster of the hydrology serves the whole run (stream distance,
    # Strahler, sub-catchments, flow paths)
    filled_dem, fdir, acc, flw = process_hydrology_pyflwdir(
        dem, metadata, drain_points=drain_points
    )
    stats["max_accumulation"] = int(acc.max())
    # The DEM is not needed after the hydrology (filled_dem from here on), only its
    # cells, which give the mean slope (drain points are nodata in filled_dem)
    dem_valid = dem != nodata
    del dem

    if save_intermediates:
        save_raster_geotiff(
            filled_dem,
            metadata,
            output_dir / f"{base_name}_02_filled.tif",
            nodata=nodata,
            dtype="float32",
        )
        save_raster_geotiff(
            fdir,
            metadata,
            output_dir / f"{base_name}_03_flowdir.tif",
            nodata=0,
            dtype="int16",
        )
        save_raster_geotiff(
            acc,
            metadata,
            output_dir / f"{base_name}_04_flowacc.tif",
            nodata=0,
            dtype="int32",
        )

    # 4a-4c. Sewer FA routing and propagation
    if topology is not None:
        logger.info("=== Sewer integration: building graph + FA routing ===")

        # Build sewer graph from pre-validated topology
        sewer_graph = build_sewer_graph(topology)
        logger.info(
            f"Sewer graph: {sewer_graph.n_nodes} nodes, "
            f"{sewer_graph.n_edges} edges, {sewer_graph.n_components} components"
        )

        # Copy raster coordinates from topology nodes to graph nodes
        topo_by_id = {n["id"]: n for n in topology.nodes}
        for node in sewer_graph.nodes:
            tn = topo_by_id.get(node["id"])
            if tn:
                node["row"] = tn["row"]
                node["col"] = tn["col"]
                node["dem_elev_m"] = tn.get("dem_elev_m")

        # 4a. Reconstruct FA at inlet cells (nodata from drain_points)
        inlets = sewer_graph.get_nodes_by_type("inlet")
        reconstruct_inlet_fa(acc, fdir, inlets)

        # 4b. Route FA through sewer graph
        route_fa_through_sewer(sewer_graph)

        # 4c. Propagate FA downstream from outlets
        outlets = sewer_graph.get_nodes_by_type("outlet")
        propagate_fa_downstream(acc, fdir, outlets)

        stats["sewer_outlets"] = len(outlets)
        stats["sewer_max_surplus"] = max(
            (o.get("total_upstream_fa", 0) for o in outlets), default=0
        )
        logger.info(
            f"Sewer: {len(outlets)} outlets, "
            f"max surplus FA = {stats['sewer_max_surplus']}"
        )

        # Update max_accumulation after sewer injection
        stats["max_accumulation"] = int(acc.max())

    # 4b. Compute stream distance (flow distance from each cell to outlet)
    logger.info("Computing stream distance to outlet...")
    t_sd = time.time()
    flow_dist_m = flw.stream_distance(unit="m").reshape(filled_dem.shape)
    logger.info(
        f"Stream distance computed in {time.time() - t_sd:.1f}s "
        f"(max={np.nanmax(flow_dist_m):.0f}m)"
    )
    if save_intermediates:
        save_raster_geotiff(
            flow_dist_m,
            metadata,
            output_dir / f"{base_name}_04b_stream_distance.tif",
            nodata=-1,
            dtype="float32",
        )

    # 5. Slope, aspect and TWI, strip by strip (shared Sobel gradients)
    strip_rasters = None
    if save_intermediates:
        strip_rasters = {
            "slope": output_dir / f"{base_name}_05_slope.tif",
            "aspect": output_dir / f"{base_name}_09_aspect.tif",
            "twi": output_dir / f"{base_name}_08_twi.tif",
        }
    slope = _slope_aspect_twi(filled_dem, acc, metadata, strip_rasters)
    stats["mean_slope"] = float(np.mean(slope[dem_valid]))
    del dem_valid

    # Determine thresholds for multi-density stream networks
    cell_area = metadata["cellsize"] * metadata["cellsize"]
    threshold_list_m2 = sorted(thresholds or PIPELINE_THRESHOLDS_M2)

    logger.info(f"Cell size: {metadata['cellsize']}m, cell area: {cell_area} m²")
    for t_m2 in threshold_list_m2:
        t_cells = max(1, int(t_m2 / cell_area))
        logger.info(f"  Threshold {t_m2} m² = {t_cells} cells")

    # Use lowest threshold for stream mask (most detailed network)
    lowest_threshold_cells = max(1, int(threshold_list_m2[0] / cell_area))

    # 5c. Compute Strahler stream order via pyflwdir (lowest threshold)
    strahler = compute_strahler_from_fdir(flw, acc, lowest_threshold_cells)

    if save_intermediates:
        save_raster_geotiff(
            strahler,
            metadata,
            output_dir / f"{base_name}_07_stream_order.tif",
            nodata=0,
            dtype="uint8",
        )

    # 6. Create stream mask (lowest threshold)
    stream_mask = (acc >= lowest_threshold_cells).astype(np.uint8)
    if save_intermediates:
        save_raster_geotiff(
            stream_mask,
            metadata,
            output_dir / f"{base_name}_06_streams.tif",
            nodata=255,
            dtype="uint8",
        )

    # 7. Stream cell count (from stream mask)
    stats["stream_cells"] = int(np.count_nonzero(stream_mask))
    del stream_mask  # Free — only needed for count above

    # 7b. Vectorize streams per threshold
    all_stream_segments: dict[int, list[dict[str, Any]]] = {}
    all_catchment_data: dict[int, list[dict[str, Any]]] = {}
    if not skip_streams_vectorize:
        all_stream_segments, all_catchment_data = _process_thresholds(
            threshold_list_m2,
            filled_dem=filled_dem,
            fdir=fdir,
            acc=acc,
            slope=slope,
            flw=flw,
            flow_dist_m=flow_dist_m,
            metadata=metadata,
            strahler_by_cells={lowest_threshold_cells: strahler},
            skip_catchments=skip_catchments,
            save_intermediates=save_intermediates,
            output_dir=output_dir,
            base_name=base_name,
        )
        _record_threshold_stats(stats, all_stream_segments, all_catchment_data)

    # Free large raster arrays no longer needed (~1.7 GB at 54.5M cells)
    del filled_dem, slope, acc, strahler, flow_dist_m, flw, fdir

    # 8. Insert into database
    if not dry_run:
        from core.database import get_db_session

        with get_db_session() as db:
            # The network of the database is no longer the one of a run by PGW
            # units: that run and its pointer go in the transaction of the delete.
            superseded = _supersede_active_unit_run(db)
            if clear_existing:
                logger.info("Clearing existing data...")
                db.execute(
                    text("DELETE FROM stream_network WHERE source = 'DEM_DERIVED'")
                )
                db.execute(text("DELETE FROM stream_catchments"))
            if clear_active_run(output_dir):
                logger.info("Active run pointer removed from %s", output_dir)
            db.commit()
            if superseded is not None:
                logger.info("PGW run %s superseded by this run", superseded)

            _insert_thresholds(db, all_stream_segments, all_catchment_data, stats)

            # === BDOT stream matching ===
            if burn_streams_path:
                logger.info("Loading BDOT streams into database...")
                bdot_data = load_bdot_streams_from_gpkg(burn_streams_path)
                if bdot_data:
                    bdot_count = insert_bdot_streams(db, bdot_data)
                    logger.info(f"Inserted {bdot_count} BDOT stream features")

                    all_match = update_stream_real_flags_all(db, threshold_list_m2)
                    for threshold_m2, stats_match in all_match.items():
                        logger.info(
                            f"Stream matching (threshold={threshold_m2}): "
                            f"{stats_match['real']}/{stats_match['total']} real, "
                            f"{stats_match['overland']} overland"
                        )
                else:
                    logger.warning(
                        "No BDOT hydro data found — skipping stream matching"
                    )

            # 8b. Insert sewer data
            if sewer_graph is not None:
                logger.info("Inserting sewer data into database...")
                sewer_count = insert_sewer_data(
                    sewer_graph,
                    db,
                    source_file=str(
                        (sewer_config or {})
                        .get("sewer", {})
                        .get("source", {})
                        .get("path", "unknown")
                    ),
                )
                stats["sewer_records_inserted"] = sewer_count
    else:
        logger.info("Dry run - skipping database insert")

    return stats


def main():
    """Run the DEM processing script."""
    parser = argparse.ArgumentParser(
        description="Process DEM and extract stream network",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        required=True,
        help="Path to input ASCII GRID (.asc) file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only compute statistics without database insert",
    )
    parser.add_argument(
        "--save-intermediates",
        "-s",
        action="store_true",
        help="Save intermediate rasters as GeoTIFF (for QGIS verification)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        default=None,
        help="Output directory for intermediate files (default: same as input)",
    )
    parser.add_argument(
        "--units",
        type=Path,
        metavar="PGW.gpkg",
        help=(
            "Process the DEM by the PGW owners of this Kartograf GeoPackage "
            "(layers zlewnie_jcwp_rzecznych, pozostale_obszary_jcwp; ADR-071): the "
            "same results with the memory of one buffered owner. Replaces the "
            "DEM-derived network (needs --clear-existing, unless --dry-run) and writes "
            "the unit rasters and VRT mosaics to <output-dir>/unit_runs/"
        ),
    )
    parser.add_argument(
        "--units-area",
        type=Path,
        metavar="AREA.gpkg",
        help="With --units: vector file of the analysis area; owners are clipped to it",
    )
    parser.add_argument(
        "--units-area-layer",
        type=str,
        default=None,
        help="With --units-area: layer name (default: first layer)",
    )
    parser.add_argument(
        "--units-catchments",
        type=Path,
        metavar="CATCHMENTS.gpkg",
        help=(
            "With --units: catchments grouped into the owners, each to the PGW unit "
            "it overlaps most (e.g. the MPHP catchments of the area); their keys are "
            "recorded with the units"
        ),
    )
    parser.add_argument(
        "--units-catchments-layer",
        type=str,
        default=None,
        help="With --units-catchments: layer name (default: first layer)",
    )
    parser.add_argument(
        "--units-catchments-key",
        type=str,
        default="ID_HYD_10",
        help="With --units-catchments: field of the unique key (default: ID_HYD_10)",
    )
    parser.add_argument(
        "--max-unit-window-cells",
        type=int,
        default=80_000_000,
        metavar="N",
        help="Buffered PGW DEM cell cap (default: 80000000; fails closed)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help=(
            "With --units: begin a new run even when a stopped or failed run with "
            "the same inputs and settings could be resumed"
        ),
    )
    parser.add_argument(
        "--clear-existing",
        action="store_true",
        help="Clear existing stream data before insert (DELETE)",
    )
    parser.add_argument(
        "--burn-streams",
        type=str,
        default=None,
        help="Path to GeoPackage/Shapefile with stream lines for DEM burning",
    )
    parser.add_argument(
        "--burn-depth",
        type=float,
        default=2.0,
        help="Burn depth in meters (default: 2.0)",
    )
    parser.add_argument(
        "--no-smooth-streams",
        action="store_true",
        default=False,
        help="Disable monotonic stream smoothing after burning",
    )
    parser.add_argument(
        "--skip-streams-vectorize",
        action="store_true",
        help="Skip stream vectorization (useful without DB)",
    )
    parser.add_argument(
        "--skip-catchments",
        action="store_true",
        help="Skip sub-catchment delineation (default: generate catchments)",
    )
    parser.add_argument(
        "--thresholds",
        type=str,
        default=None,
        help=(
            "Comma-separated FA thresholds in m² for multi-density "
            "stream networks (default: "
            + ",".join(str(t) for t in PIPELINE_THRESHOLDS_M2)
            + ")."
        ),
    )
    parser.add_argument(
        "--from-intermediates",
        action="store_true",
        help=(
            "Add the stream networks and sub-catchments of --thresholds (new "
            "ones only) from the hydrology rasters an earlier run saved with "
            "--save-intermediates (<stem of --input>_02_filled.tif, _03_flowdir, "
            "_04_flowacc, _04b_stream_distance, _05_slope in --output-dir or "
            "next to --input) without computing the hydrology again; the "
            "existing thresholds stay as they are."
        ),
    )
    parser.add_argument(
        "--hydro-resolution",
        type=float,
        default=None,
        help="Downsample DEM to this resolution (meters) before hydro processing. "
        "Reduces memory for large rasters. E.g. --hydro-resolution 2",
    )

    # Waterbody options
    wb_group = parser.add_argument_group("Zbiorniki wodne")
    wb_group.add_argument(
        "--waterbody-mode",
        type=str,
        default="none",
        help='Tryb obslugi zbiornikow: "auto" (BDOT10k klasyfikacja), '
        '"none" (pomin), lub sciezka do pliku .gpkg/.shp '
        "(wszystkie traktowane jako endoreiczne). Default: none",
    )
    wb_group.add_argument(
        "--waterbody-min-area",
        type=float,
        default=None,
        help="Min. powierzchnia zbiornika (m²). Zbiorniki mniejsze sa ignorowane.",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir) if args.output_dir else None
    burn_streams_path = Path(args.burn_streams) if args.burn_streams else None

    # Parse thresholds
    threshold_list = None
    if args.thresholds:
        threshold_list = [int(t.strip()) for t in args.thresholds.split(",")]

    if args.max_unit_window_cells < 1:
        parser.error("--max-unit-window-cells must be positive")
    if args.units is not None and args.from_intermediates:
        parser.error("--units cannot reuse a single-raster --from-intermediates run")
    if args.units is None and (
        args.units_area
        or args.units_area_layer
        or args.units_catchments
        or args.units_catchments_layer
        or args.no_resume
    ):
        parser.error(
            "--units-area, --units-catchments and their options and --no-resume "
            "need --units"
        )
    if args.units_catchments is None and args.units_catchments_layer:
        parser.error("--units-catchments-layer needs --units-catchments")
    if args.units is not None and not args.dry_run and not args.clear_existing:
        parser.error(
            "--units replaces the DEM-derived network: add --clear-existing "
            "(or --dry-run to compute only)"
        )
    if args.from_intermediates:
        if not threshold_list:
            parser.error("--from-intermediates needs --thresholds")
        if args.clear_existing or burn_streams_path or args.hydro_resolution:
            parser.error(
                "--from-intermediates reuses saved rasters: --clear-existing, "
                "--burn-streams and --hydro-resolution do not apply"
            )
        start_time = time.time()
        try:
            stats = process_dem_from_intermediates(
                input_path,
                threshold_list,
                output_dir=output_dir,
                dry_run=args.dry_run,
                save_intermediates=args.save_intermediates,
            )
        except (FileNotFoundError, ValueError) as e:
            logger.error(str(e))
            sys.exit(1)
        for t, count in stats["stream_thresholds"].items():
            logger.info(
                f"Threshold {t} m²: {count} segments, "
                f"{stats.get('catchment_thresholds', {}).get(t, 0)} sub-catchments"
            )
        logger.info(f"Time elapsed: {time.time() - start_time:.1f}s")
        return

    logger.info("=" * 60)
    logger.info("DEM Processing Script")
    logger.info("=" * 60)
    logger.info(f"Input: {input_path}")
    if threshold_list:
        logger.info(f"Multi-threshold FA: {threshold_list} m²")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Save intermediates: {args.save_intermediates}")
    logger.info(f"Clear existing: {args.clear_existing}")
    if burn_streams_path:
        logger.info(f"Burn streams: {burn_streams_path} (depth={args.burn_depth}m)")
    if output_dir:
        logger.info(f"Output dir: {output_dir}")
    logger.info("=" * 60)

    start_time = time.time()

    try:
        stats = process_dem(
            input_path,
            dry_run=args.dry_run,
            save_intermediates=args.save_intermediates,
            output_dir=output_dir,
            clear_existing=args.clear_existing,
            burn_streams_path=burn_streams_path,
            burn_depth_m=args.burn_depth,
            smooth_streams=not args.no_smooth_streams,
            skip_streams_vectorize=args.skip_streams_vectorize,
            thresholds=threshold_list,
            skip_catchments=args.skip_catchments,
            hydro_resolution_m=args.hydro_resolution,
            waterbody_mode=args.waterbody_mode,
            waterbody_min_area_m2=args.waterbody_min_area,
            units_path=args.units,
            units_area_path=args.units_area,
            units_area_layer=args.units_area_layer,
            units_catchments_path=args.units_catchments,
            units_catchments_layer=args.units_catchments_layer,
            units_catchments_key=args.units_catchments_key,
            max_unit_window_cells=args.max_unit_window_cells,
            units_resume=not args.no_resume,
        )
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        raise

    elapsed = time.time() - start_time

    logger.info("=" * 60)
    logger.info("Processing complete!")
    logger.info(f"  Grid size: {stats['ncols']} x {stats['nrows']}")
    logger.info(f"  Cell size: {stats['cellsize']} m")
    logger.info(f"  Total cells: {stats['total_cells']:,}")
    logger.info(f"  Valid cells: {stats['valid_cells']:,}")
    logger.info(f"  Max accumulation: {stats['max_accumulation']:,}")
    logger.info(f"  Mean slope: {stats['mean_slope']:.1f}%")
    if "burn_cells" in stats:
        logger.info(f"  Burned cells: {stats['burn_cells']:,}")
    if "endorheic_lakes" in stats:
        logger.info(
            f"  Endorheic lakes: {stats['endorheic_lakes']}, "
            f"drain points: {stats.get('drain_points', 0)}"
        )
    logger.info(f"  Stream cells: {stats['stream_cells']:,}")
    if "unit_rasters_dir" in stats:
        logger.info(
            f"  PGW run {stats['run_id']}: {stats['pgw_owners']} owners, rasters "
            f"in {stats['unit_rasters_dir']}, peak RSS {stats['peak_rss_mb']:.0f} MB"
        )
    if "stream_segments" in stats:
        logger.info(f"  Stream segments: {stats['stream_segments']:,}")
    if "stream_thresholds" in stats:
        for t, count in stats["stream_thresholds"].items():
            logger.info(f"    Threshold {t} m²: {count} segments")
    if "stream_segments_inserted" in stats:
        logger.info(
            f"  Stream segments inserted: {stats['stream_segments_inserted']:,}"
        )
    if "catchment_thresholds" in stats:
        for t, count in stats["catchment_thresholds"].items():
            logger.info(f"    Sub-catchments {t} m²: {count}")
    if "catchments_inserted" in stats:
        logger.info(f"  Sub-catchments inserted: {stats['catchments_inserted']:,}")
    logger.info(f"  Time elapsed: {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
