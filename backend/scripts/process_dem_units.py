"""Opt-in bootstrap of the DEM by PGW units (ADR-071), on the grid of the input DEM.

``process_dem --units`` runs the hydrology of the whole input DEM owner by owner: the
fill and the D8 directions of each PGW owner with a 500 m halo, then the routing of the
whole area over disk-backed rasters (``core.unit_hydrology``), so the fill never holds
more than one buffered owner in memory. The result is the one a run of the whole raster
gives (``tests/unit/test_unit_equivalence.py``): the same rows of ``stream_network`` and
``stream_catchments``, and the same rasters on the cells that hold DEM data.

The outputs of a run, under ``<output_dir>/unit_runs/<run token>/``:

* ``units/<stem>_<raster>_<owner code>.tif``: the tiled GeoTIFFs of every owner's own
  cells, one per raster, and ``<stem>_<raster>.vrt``: the VRT mosaic of each raster over
  the whole grid (the names of ``process_dem --save-intermediates``, with ``.vrt``);
* ``report.json``: what the run did (owners, halo, peak memory, counts);
* scratch (``scratch/``): the disk-backed rasters of the routing, removed once the run
  succeeded.

A run that is not a dry run is recorded in ``processing_runs`` and
``processing_units`` (migration 005) and replaces the DEM-derived network in one
transaction (``core.unit_run_store``); ``<output_dir>/active_run`` then points at its
directory. The sewer integration is not available in this mode.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import resource
import shutil
import time
import uuid
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import numpy as np
import rasterio
from scipy.ndimage import find_objects

from core.constants import PIPELINE_THRESHOLDS_M2
from core.database import get_db_session
from core.db_bulk import (
    insert_bdot_streams,
    load_bdot_streams_from_gpkg,
    update_stream_real_flags_all,
)
from core.hydrology import (
    STREAM_BURNING_MODES,
    burn_streams_into_dem,
    classify_endorheic_lakes,
    raise_buildings_in_dem,
    smooth_streams_monotonic,
)
from core.morphometry_raster import (
    compute_aspect_from_gradients,
    compute_twi,
    gradient_strips,
)
from core.raster_io import downsample_raster, read_raster, save_raster_geotiff
from core.stream_extraction import polygonize_subcatchments
from core.unit_flow_paths import UnitFlowPaths
from core.unit_hydrology import UnitHydrology, process_unit_hydrology
from core.unit_ownership import load_pgw_owners
from core.unit_rasters import write_unit_mosaics
from core.unit_run_store import begin_run, checkpoint_unit, fail_run, publish_run
from scripts.process_dem import (
    MIN_CATCHMENT_THRESHOLD_M2,
    _enrich_catchments_with_flow_paths,
    _record_threshold_stats,
)

logger = logging.getLogger(__name__)

# Halo of the buffered windows [m] (ADR-071); it grows on a disagreement of the seams.
UNIT_BUFFER_M = 500.0
_STRIP_ROWS = 512


def _file_dependencies(path: Path) -> list[Path]:
    """Resolve all local raster inputs of a VRT, including nested source VRTs."""
    resolved = path.resolve()
    if resolved.suffix.lower() != ".vrt":
        return [resolved]
    sources = [resolved]
    for entry in ElementTree.parse(resolved).iter("SourceFilename"):
        if entry.text is None:
            raise ValueError(f"Empty VRT source in {resolved}")
        source = Path(entry.text)
        if entry.get("relativeToVRT") == "1":
            source = resolved.parent / source
        sources.extend(_file_dependencies(source))
    return sources


def _input_fingerprint(paths: list[Path], config: dict[str, Any]) -> str:
    """Hash actual raster/PGW/burn input bytes, not only their paths or mtimes."""
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode())
    source_files = set()
    for path in paths:
        source_files.update(_file_dependencies(path))
    for path in sorted(source_files):
        digest.update(os.fsencode(path))
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def _prepare_dem(
    dem_path: Path,
    scratch: Path,
    stats: dict[str, Any],
    *,
    building_gpkg: str | None,
    burn_streams_path: Path | None,
    burn_depth_m: float,
    stream_burning: str,
    smooth_streams: bool,
    waterbody_mode: str,
    waterbody_min_area_m2: float | None,
) -> tuple[Path, list[tuple[int, int]] | None]:
    """Raise buildings, burn streams and find the lake drain points, on the whole DEM.

    The same steps in the same order as ``process_dem``. A stream is smoothed along
    its whole length and a lake is classified by its whole area and outflow, so a
    window of an owner cannot do these; the DEM is held once, as ``process_dem`` holds
    it, and the result goes to ``scratch`` as a tiled GeoTIFF for the windowed reads.

    Returns
    -------
    tuple[Path, list[tuple[int, int]] | None]
        The DEM the owners are processed from (``dem_path`` itself when nothing
        changes it) and the drain points of the whole grid (row, column).
    """
    stats["waterbody_mode"] = waterbody_mode
    if waterbody_min_area_m2 is not None:
        stats["waterbody_min_area_m2"] = waterbody_min_area_m2
    if building_gpkg is None and burn_streams_path is None and waterbody_mode == "none":
        return dem_path, None
    dem, metadata = read_raster(dem_path)
    nodata = metadata["nodata_value"]
    transform = metadata["transform"]
    changed = False
    if building_gpkg is not None:
        dem = raise_buildings_in_dem(dem, transform, 2180, building_gpkg)
        changed = True
    if burn_streams_path is not None:
        dem, burn_diag = burn_streams_into_dem(
            dem, transform, burn_streams_path, burn_depth_m, nodata, stream_burning
        )
        stats["burn_cells"] = burn_diag["cells_burned"]
        stats["stream_burning"] = stream_burning
        changed = True
        if smooth_streams:
            dem, smooth_diag = smooth_streams_monotonic(
                dem, transform, burn_streams_path, nodata, stream_burning
            )
            stats["smooth_cells"] = smooth_diag["cells_smoothed"]
            stats["smooth_max_correction_m"] = smooth_diag["max_correction_m"]
    drain_points = None
    if waterbody_mode == "auto" and burn_streams_path is not None:
        drain_points, drain_diag = classify_endorheic_lakes(
            dem,
            transform,
            burn_streams_path,
            nodata,
            min_area_m2=waterbody_min_area_m2,
        )
    elif waterbody_mode not in ("auto", "none"):
        waterbody_path = Path(waterbody_mode)
        drain_points, drain_diag = classify_endorheic_lakes(
            dem,
            transform,
            burn_streams_path or waterbody_path,
            nodata,
            min_area_m2=waterbody_min_area_m2,
            waterbody_path=waterbody_path,
        )
    if drain_points is not None:
        stats["endorheic_lakes"] = drain_diag["endorheic"]
        stats["drain_points"] = len(drain_points)
    if not changed:
        return dem_path, drain_points
    prepared = scratch / "prepared_dem.tif"
    save_raster_geotiff(dem, metadata, prepared, nodata=nodata, dtype=str(dem.dtype))
    return prepared, drain_points


def _row_statistics(
    result: UnitHydrology, valid: np.ndarray, threshold_cells: int
) -> tuple[float, int]:
    """Mean slope over the valid cells and the cells of the stream mask.

    Strip by strip, so no whole-grid temporary is made. The stream mask is
    ``acc >= threshold_cells`` as in ``process_dem``: a routed cell without DEM data
    (a repaired hole) has an accumulation and counts.
    """
    slope_sum = 0.0
    valid_count = 0
    stream_count = 0
    for start in range(0, valid.shape[0], _STRIP_ROWS):
        rows = slice(start, min(start + _STRIP_ROWS, valid.shape[0]))
        included = valid[rows]
        slope_sum += float(np.sum(result.slope[rows], where=included))
        valid_count += int(np.count_nonzero(included))
        stream_count += int(np.count_nonzero(result.acc[rows] >= threshold_cells))
    return slope_sum / valid_count if valid_count else 0.0, stream_count


def _secondary_rasters(
    result: UnitHydrology,
    cellsize: float,
    nodata: float,
    scratch: Path,
    lowest_cells: int,
) -> dict[str, np.memmap]:
    """Compute aspect, TWI, float32 slope and the lowest-threshold stream mask.

    Strip by strip, bounded by the strip. ``slope`` is the float32 slope raster that
    ``process_dem`` saves (the routing keeps float64 for the statistics of the
    sub-catchments); ``streams`` is 1 where ``acc`` reaches the lowest threshold.
    """
    shape = result.filled_dem.shape
    rasters = {
        name: np.lib.format.open_memmap(
            scratch / f"{name}.npy", mode="w+", dtype=dtype, shape=shape
        )
        for name, dtype in (
            ("slope", "float32"),
            ("aspect", "float32"),
            ("twi", "float32"),
            ("streams", "uint8"),
        )
    }
    for rows, dx, dy in gradient_strips(
        result.filled_dem, cellsize, nodata, _STRIP_ROWS
    ):
        rasters["slope"][rows] = result.slope[rows]
        rasters["aspect"][rows] = compute_aspect_from_gradients(dx, dy)
        del dx, dy
        rasters["twi"][rows] = compute_twi(
            result.acc[rows], result.slope[rows], cellsize, nodata_acc=0
        )
        rasters["streams"][rows] = result.acc[rows] >= lowest_cells
    return rasters


def _swap_active_link(alias: Path, target: Path, run_token: str) -> None:
    """Point ``alias`` at the directory of the run, in one atomic rename.

    The directories of earlier runs stay; an ``alias`` that is a real directory (not a
    link of an earlier run) is moved aside, not deleted.
    """
    alias.parent.mkdir(parents=True, exist_ok=True)
    next_link = alias.with_name(f".{alias.name}.{run_token}.next")
    next_link.symlink_to(
        os.path.relpath(target, alias.parent), target_is_directory=True
    )
    try:
        if alias.exists() and not alias.is_symlink():
            archive = alias.with_name(f"{alias.name}_before_{run_token}")
            os.replace(alias, archive)
        os.replace(next_link, alias)
    finally:
        next_link.unlink(missing_ok=True)


def _network_rows(
    result: UnitHydrology,
    flow: UnitFlowPaths,
    metadata: dict[str, Any],
    thresholds_m2: tuple[int, ...],
    nodata: float,
    skip_catchments: bool,
) -> dict[int, list[dict[str, Any]]]:
    """Polygonize and describe the sub-catchments of each threshold from the largest.

    As ``process_dem`` does: only thresholds from ``MIN_CATCHMENT_THRESHOLD_M2`` have
    sub-catchments, and each gets the flow paths, heads and overland segments.
    """
    catchments: dict[int, list[dict[str, Any]]] = {}
    if skip_catchments:
        return catchments
    cellsize = metadata["cellsize"]
    for threshold_m2 in sorted(thresholds_m2, reverse=True):
        if threshold_m2 < MIN_CATCHMENT_THRESHOLD_M2:
            continue
        label = result.labels[threshold_m2]
        rows = polygonize_subcatchments(
            label,
            result.filled_dem,
            result.slope,
            metadata,
            result.segments[threshold_m2],
            flow_dist_m=result.flow_dist_m,
        )
        stream_mask = (result.acc >= max(1, int(threshold_m2 / cellsize**2))) & (
            result.filled_dem != nodata
        )
        _enrich_catchments_with_flow_paths(
            rows,
            label,
            result.flow_dist_m,
            flow,
            metadata,
            result.filled_dem,
            stream_mask,
        )
        del stream_mask
        catchments[threshold_m2] = rows
    return {t: catchments[t] for t in sorted(catchments)}


def _peak_rss_mb() -> float:
    """Return the peak resident set of this process so far [MB]."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def process_dem_units(
    input_path: Path,
    units_path: Path,
    *,
    dry_run: bool = False,
    output_dir: Path | None = None,
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
    units_area_path: Path | None = None,
    units_area_layer: str | None = None,
    max_unit_window_cells: int = 80_000_000,
) -> dict[str, Any]:
    """Process the DEM by PGW units and publish the run, or only compute it.

    The arguments are those of ``process_dem`` of the same name, plus the PGW
    GeoPackage and its options. A run always writes its unit rasters and VRT mosaics
    (``process_dem --save-intermediates`` is not needed). Without ``dry_run`` the run
    is recorded, its units are checkpointed and the DEM-derived network of the
    database is replaced by it in one transaction; any failure before that leaves the
    database as it was and marks the run failed.

    Parameters
    ----------
    input_path : Path
        The DEM (a GeoTIFF or the VRT mosaic of the NMT sheets, EPSG:2180).
    units_path : Path
        The PGW GeoPackage of Kartograf.
    units_area_path : Path, optional
        Vector file of the analysis area; the owners are clipped to it
        (``core.unit_ownership.load_pgw_owners``).
    units_area_layer : str, optional
        Layer of ``units_area_path`` (default: the first).
    max_unit_window_cells : int
        Largest buffered owner window [cells]; a larger one fails the run.

    Returns
    -------
    dict
        The statistics of ``process_dem``, with ``run_id`` (None for a dry run),
        ``pgw_owners``, ``unit_rasters_dir`` and ``unit_dem_vrt``.
    """
    input_path = Path(input_path)
    units_path = Path(units_path)
    if not input_path.is_file() or not units_path.is_file():
        raise FileNotFoundError(
            f"DEM or PGW GeoPackage not found: {input_path}, {units_path}"
        )
    if skip_streams_vectorize or (skip_catchments and not dry_run):
        raise ValueError(
            "A published PGW run needs the streams and sub-catchments of every "
            "threshold"
        )
    if sewer_config and sewer_config.get("sewer", {}).get("enabled"):
        raise ValueError("PGW unit routing cannot publish storm-sewer flow connections")
    if waterbody_mode not in ("none", "auto") and not Path(waterbody_mode).is_file():
        raise FileNotFoundError(f"Custom waterbody file not found: {waterbody_mode}")
    thresholds_m2 = tuple(sorted(set(thresholds or PIPELINE_THRESHOLDS_M2)))
    if any(threshold <= 0 for threshold in thresholds_m2):
        raise ValueError("Stream thresholds must be positive")
    if max_unit_window_cells < 1:
        raise ValueError("max_unit_window_cells must be positive")
    if stream_burning not in STREAM_BURNING_MODES:
        raise ValueError(
            f"stream_burning must be one of {STREAM_BURNING_MODES}, "
            f"not {stream_burning!r}"
        )

    started = time.time()
    output_dir = Path(output_dir) if output_dir is not None else input_path.parent
    run_token = uuid.uuid4().hex
    run_dir = output_dir / "unit_runs" / run_token
    scratch = run_dir / "scratch"
    scratch.mkdir(parents=True)
    stats: dict[str, Any] = {"run_id": None}
    run_id: int | None = None
    published = False
    try:
        grid_dem = input_path
        if hydro_resolution_m is not None:
            with rasterio.open(input_path) as original:
                if hydro_resolution_m > original.transform.a:
                    grid_dem = downsample_raster(
                        input_path, scratch / "downsampled.tif", hydro_resolution_m
                    )
                    stats["hydro_resolution_m"] = hydro_resolution_m
        owners = load_pgw_owners(
            grid_dem,
            units_path,
            scratch / "ownership",
            units_area_path,
            units_area_layer,
        )
        owner_bboxes = find_objects(owners.cells)
        active_owners = tuple(
            owners.codes[index]
            for index, bbox in enumerate(owner_bboxes)
            if bbox is not None
        )
        with rasterio.open(grid_dem) as source:
            cellsize = source.transform.a
            nodata = source.nodata
            if nodata is None:
                raise ValueError("The DEM must declare its nodata value")
            grid = {
                "nrows": source.height,
                "ncols": source.width,
                "transform": list(source.transform)[:6],
                "crs": source.crs.to_string(),
            }
            metadata: dict[str, Any] = {
                "cellsize": cellsize,
                "nodata_value": nodata,
                "transform": source.transform,
                "xllcorner": source.bounds.left,
                "yllcorner": source.bounds.bottom,
            }
        stats.update(
            ncols=grid["ncols"],
            nrows=grid["nrows"],
            cellsize=cellsize,
            total_cells=grid["ncols"] * grid["nrows"],
            valid_cells=int(np.count_nonzero(owners.valid)),
            pgw_owners=len(active_owners),
        )
        # What the results depend on, besides the bytes of the input files.
        parameters: dict[str, Any] = {
            "thresholds_m2": list(thresholds_m2),
            "halo_m": UNIT_BUFFER_M,
            "max_unit_window_cells": max_unit_window_cells,
            "hydro_resolution_m": stats.get("hydro_resolution_m"),
            "burn_depth_m": burn_depth_m if burn_streams_path else None,
            "stream_burning": stream_burning if burn_streams_path else None,
            "smooth_streams": smooth_streams if burn_streams_path else None,
            "waterbody_mode": waterbody_mode,
            "waterbody_min_area_m2": waterbody_min_area_m2,
            "units_area_layer": units_area_layer,
            "grid": grid,
            "owners": list(active_owners),
        }
        if not dry_run:
            source_paths = [input_path, units_path]
            for optional in (burn_streams_path, units_area_path):
                if optional is not None:
                    source_paths.append(Path(optional))
            if building_gpkg is not None:
                source_paths.append(Path(building_gpkg))
            if waterbody_mode not in ("none", "auto"):
                source_paths.append(Path(waterbody_mode))
            with get_db_session() as db:
                run_id = begin_run(
                    db,
                    input_fingerprint=_input_fingerprint(source_paths, parameters),
                    source_raster=str(input_path),
                    pgw_path=str(units_path),
                    config={**parameters, "run_dir": str(run_dir.resolve())},
                    owner_codes=active_owners,
                )
            stats["run_id"] = run_id

        working_dem, drain_points = _prepare_dem(
            grid_dem,
            scratch,
            stats,
            building_gpkg=building_gpkg,
            burn_streams_path=burn_streams_path,
            burn_depth_m=burn_depth_m,
            stream_burning=stream_burning,
            smooth_streams=smooth_streams,
            waterbody_mode=waterbody_mode,
            waterbody_min_area_m2=waterbody_min_area_m2,
        )
        result = process_unit_hydrology(
            working_dem,
            owners.cells,
            scratch / "routing",
            thresholds_m2,
            buffer_m=UNIT_BUFFER_M,
            max_window_cells=max_unit_window_cells,
            drain_points=drain_points,
        )
        logger.info(
            "Units routed: halo %g m, largest window %s cells, peak RSS %.0f MB",
            result.halo_m,
            f"{result.largest_window_cells:,}",
            _peak_rss_mb(),
        )
        lowest_cells = max(1, int(thresholds_m2[0] / cellsize**2))
        mean_slope, stream_cells = _row_statistics(result, owners.valid, lowest_cells)
        stats.update(
            max_accumulation=int(result.acc.max()),
            mean_slope=mean_slope,
            stream_cells=stream_cells,
        )
        flow = UnitFlowPaths.from_hydrology(
            result, metadata["transform"], scratch / "downstream.npy"
        )
        catchments = _network_rows(
            result, flow, metadata, thresholds_m2, nodata, skip_catchments
        )
        segments = {t: result.segments[t] for t in thresholds_m2}
        _record_threshold_stats(stats, segments, catchments)

        secondary = _secondary_rasters(result, cellsize, nodata, scratch, lowest_cells)
        rasters: dict[str, tuple[np.ndarray | Path, float | int]] = {
            "01_dem": (grid_dem, nodata),
            "02_filled": (result.filled_dem, nodata),
            "03_flowdir": (result.fdir, 0),
            "04_flowacc": (result.acc, 0),
            "04b_stream_distance": (result.flow_dist_m, -1),
            "05_slope": (secondary["slope"], -1),
            "06_streams": (secondary["streams"], 255),
            "07_stream_order": (result.strahler[thresholds_m2[0]], 0),
            "08_twi": (secondary["twi"], -9999),
            "09_aspect": (secondary["aspect"], -1),
        }
        for threshold_m2 in thresholds_m2:
            if threshold_m2 != thresholds_m2[0]:
                rasters[f"07_stream_order_{threshold_m2}"] = (
                    result.strahler[threshold_m2],
                    0,
                )
            if threshold_m2 >= MIN_CATCHMENT_THRESHOLD_M2:
                rasters[f"10_subcatchments_{threshold_m2}"] = (
                    result.labels[threshold_m2],
                    0,
                )
        mosaics, files_by_owner = write_unit_mosaics(
            grid_dem, owners.cells, owners.codes, rasters, run_dir, input_path.stem
        )
        stats["unit_dem_vrt"] = str(mosaics["01_dem"])
        stats["unit_rasters_dir"] = str(run_dir)

        if run_id is not None:
            with get_db_session() as db:
                for index, bbox in enumerate(owner_bboxes, start=1):
                    if bbox is None:
                        continue
                    row, col = bbox
                    checkpoint_unit(
                        db,
                        run_id,
                        owners.codes[index - 1],
                        (row.start, row.stop, col.start, col.stop),
                        files_by_owner[index],
                    )
            with get_db_session() as db:
                stats.update(publish_run(db, run_id, segments, catchments))
            published = True
            _swap_active_link(output_dir / "active_run", run_dir, run_token)
            logger.info("PGW run %s published as %s", run_id, run_dir)
        stats["peak_rss_mb"] = round(_peak_rss_mb(), 1)
        stats["elapsed_s"] = round(time.time() - started, 1)
        report: dict[str, Any] = {
            "run_id": run_id,
            "owners": list(active_owners),
            "halo_m": result.halo_m,
            "largest_window_cells": result.largest_window_cells,
            "max_unit_window_cells": max_unit_window_cells,
            **{
                key: stats[key]
                for key in (
                    "valid_cells",
                    "stream_segments",
                    "stream_thresholds",
                    "peak_rss_mb",
                    "elapsed_s",
                )
                if key in stats
            },
        }
        (run_dir / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        # The tiles hold everything the run publishes; the routing is scratch.
        del result, flow, secondary, owners
        shutil.rmtree(scratch, ignore_errors=True)
    except BaseException as error:
        if run_id is not None and not published:
            try:
                with get_db_session() as db:
                    fail_run(db, run_id, f"{type(error).__name__}: {error}")
            except Exception:
                logger.exception("Run %s could not be marked failed", run_id)
        raise

    if burn_streams_path is not None and run_id is not None:
        # As process_dem does after its insert: the BDOT10k streams and the match
        # of the network with them; the run is already published.
        bdot_data = load_bdot_streams_from_gpkg(burn_streams_path)
        if bdot_data:
            with get_db_session() as db:
                insert_bdot_streams(db, bdot_data)
                update_stream_real_flags_all(db, list(thresholds_m2))
        else:
            logger.warning("No BDOT hydro data found - skipping stream matching")
    return stats
