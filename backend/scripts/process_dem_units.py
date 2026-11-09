"""Opt-in bootstrap of the DEM by PGW units (ADR-071), on the grid of the input DEM.

``process_dem --units`` fills the depressions of the whole prepared DEM once, as
``process_dem`` does (pyflwdir's fill and D8), takes every owner's cells from that
fill, then routes the whole area over disk-backed rasters (``core.unit_hydrology``).
The result is the one a run of the whole raster gives
(``tests/unit/test_unit_equivalence.py``): the same rows of ``stream_network`` and
``stream_catchments``, and the same rasters on the cells that hold DEM data. An owner
is a PGW unit, or with ``--units-catchments`` the group of the catchments that lie
(mostly) in one PGW unit (``core.unit_ownership``).

The outputs of a run, under ``<output_dir>/unit_runs/<run token>/``:

* ``units/<stem>_<raster>_<owner code>.tif``: the tiled GeoTIFFs of every owner's own
  cells, one per raster, and ``<stem>_<raster>.vrt``: the VRT mosaic of each raster over
  the whole grid (the names of ``process_dem --save-intermediates``, with ``.vrt``);
* ``report.json``: what the run did (owners, stages with wall time and peak memory,
  counts);
* ``stage/<owner code>.npz``: the fill and D8 of each owner's cells, from which an
  interrupted run is resumed; removed once the run is published;
* scratch (``<call token>/scratch/``, or under ``scratch_dir``): the fill of the
  whole grid and the disk-backed rasters of the routing, removed once the run
  succeeded.

A run that is not a dry run is recorded in ``processing_runs`` and
``processing_units`` (migration 005) and replaces the DEM-derived network in one
transaction (``core.unit_run_store``); ``<output_dir>/active_run.json`` then names its
directory (``core.active_run``). A run that stopped or failed is resumed by the next
call with the same inputs and settings. The sewer integration is not available in
this mode.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import resource
import shutil
import time
import uuid
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from functools import partial
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import numpy as np
import rasterio
from scipy.ndimage import find_objects

from core.active_run import write_active_run
from core.constants import PIPELINE_THRESHOLDS_M2
from core.database import get_db_engine, get_db_session
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
from core.unit_hydrology import UnitHydrology, UnitStage, process_unit_hydrology
from core.unit_ownership import DEFAULT_CATCHMENT_KEY, CatchmentFile, load_pgw_owners
from core.unit_rasters import write_unit_mosaics
from core.unit_run_store import (
    UnitState,
    begin_run,
    checkpoint_unit,
    fail_run,
    file_problem,
    publish_run,
    record_unit_stage,
    resume_run,
    run_lock,
)
from scripts.process_dem import (
    MIN_CATCHMENT_THRESHOLD_M2,
    _enrich_catchments_with_flow_paths,
    _record_threshold_stats,
)

logger = logging.getLogger(__name__)

_STRIP_ROWS = 512
# Linux: writing 5 resets the peak resident set (VmHWM) of the process
_CLEAR_REFS = Path("/proc/self/clear_refs")
_STATUS = Path("/proc/self/status")


def _file_dependencies(path: Path) -> list[Path]:
    """Resolve all local raster inputs of a VRT, including nested source VRTs.

    A VRT must read its sources cell for cell. A source drawn at another size or
    at a fraction of a cell is resampled on every read, and two windows can then
    read one cell differently (seen on a VRT shifted by half a cell from its
    sheets): the owners' windows would disagree with each other. Such a VRT is
    refused; build it on the grid of its sheets (``utils.raster_utils``).
    """
    resolved = path.resolve()
    if resolved.suffix.lower() != ".vrt":
        return [resolved]
    sources = [resolved]
    for element in ElementTree.parse(resolved).getroot().iter():
        entry = element.find("SourceFilename")
        if entry is None:
            continue
        if entry.text is None:
            raise ValueError(f"Empty VRT source in {resolved}")
        _require_cell_for_cell(resolved, entry.text, element)
        source = Path(entry.text)
        if entry.get("relativeToVRT") == "1":
            source = resolved.parent / source
        sources.extend(_file_dependencies(source))
    return sources


def _require_cell_for_cell(vrt: Path, name: str, source: ElementTree.Element) -> None:
    """Refuse a VRT source that is resampled: scaled or off the cells of the VRT."""
    src, dst = source.find("SrcRect"), source.find("DstRect")
    if src is None or dst is None:
        raise ValueError(f"{vrt}: source {name} has no SrcRect/DstRect")
    values = [
        float(rect.get(key, "nan"))
        for rect in (src, dst)
        for key in ("xOff", "yOff", "xSize", "ySize")
    ]
    sx, sy, sw, sh, dx, dy, dw, dh = values
    if (sw, sh) != (dw, dh) or not all(
        value.is_integer() for value in (sx, sy, dx, dy, dw, dh)
    ):
        raise ValueError(
            f"{vrt} resamples its source {name} (SrcRect {sx:g},{sy:g} {sw:g}x{sh:g}, "
            f"DstRect {dx:g},{dy:g} {dw:g}x{dh:g}): the input VRT must lie on the "
            "grid of its sheets"
        )


def _input_fingerprint(paths: list[Path], config: dict[str, Any]) -> str:
    """Identify the inputs: the text of each VRT, the size and mtime of other files.

    Reading every byte of the 708 sheets of an area (1.6 GB on a network share)
    delayed each run; the files of a Kartograf store are not changed in place (a
    new version is a new file), so their size and modification time identify
    them. A VRT is hashed whole: the bootstrap writes its mosaic again on every
    run, with the same text.
    """
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode())
    source_files: set[Path] = set()
    for path in paths:
        source_files.update(_file_dependencies(path))
    for path in sorted(source_files):
        digest.update(os.fsencode(path) + b"\0")
        if path.suffix.lower() == ".vrt":
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        else:
            stat = path.stat()
            digest.update(f"{stat.st_size}:{stat.st_mtime_ns}\0".encode())
    return digest.hexdigest()


class _RunCheckpoints:
    """Save the stage of each owner in the run's ``stage`` directory and the DB.

    The units the run already routed (``units``, from ``resume_run``) are restored
    from their files when those are intact (size and SHA-256 as recorded) and were
    taken with the halo asked for; any other unit is taken from the fill again.
    """

    def __init__(
        self,
        run_id: int,
        codes: tuple[str, ...],
        stage_dir: Path,
        units: dict[str, UnitState],
    ) -> None:
        self.run_id = run_id
        self.codes = codes
        self.stage_dir = stage_dir
        self.units = units
        self.restored: set[str] = set()
        self.stage_files: dict[str, Path] = {}

    def restore(self, owner: int, halo_m: float) -> UnitStage | None:
        """Return the recorded stage of the owner at ``halo_m`` if it is intact."""
        code = self.codes[owner - 1]
        unit = self.units.get(code)
        if (
            unit is None
            or unit.status == "pending"
            or unit.halo_m is None
            or not math.isclose(unit.halo_m, halo_m)
            or not unit.outputs
            or "stage" not in unit.outputs
        ):
            return None
        entry = unit.outputs["stage"]
        problem = file_problem(entry)
        if problem is not None:
            logger.warning("Unit %s is taken from the fill again: %s", code, problem)
            return None
        path = Path(entry["path"])
        stage = UnitStage.load(path)
        self.stage_files[code] = path
        self.restored.add(code)
        logger.info("Unit %s restored from %s (halo %g m)", code, path, halo_m)
        return stage

    def save(
        self,
        owner: int,
        halo_m: float,
        bbox: tuple[int, int, int, int],
        stage: UnitStage,
    ) -> None:
        """Write the stage file, then record the unit as routed."""
        code = self.codes[owner - 1]
        path = self.stage_dir / f"{code}.npz"
        stage.save(path)
        with get_db_session() as db:
            record_unit_stage(db, self.run_id, code, bbox, path, halo_m)
        self.stage_files[code] = path
        self.restored.discard(code)


@contextmanager
def _stage(stats: dict[str, Any], name: str) -> Iterator[None]:
    """Record the wall time of a stage and the peak RSS reached in it.

    On Linux the kernel's peak of the process (VmHWM) is reset as the stage begins,
    so the peak is the stage's own; elsewhere it is the peak so far. The peak of
    the run (``peak_rss_mb``) is the largest of them.
    """
    _reset_peak_rss()
    started = time.time()
    yield
    elapsed = time.time() - started
    peak = round(_peak_rss_mb(), 1)
    stats.setdefault("stages", {})[name] = {
        "elapsed_s": round(elapsed, 1),
        "peak_rss_mb": peak,
    }
    stats["peak_rss_mb"] = max(stats.get("peak_rss_mb", 0.0), peak)
    logger.info("Stage %s: %.1f s, peak RSS %.0f MB", name, elapsed, peak)


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
    it, and the result goes to ``scratch`` as a tiled GeoTIFF, freed before the fill
    of the whole grid reads it.

    Returns
    -------
    tuple[Path, list[tuple[int, int]] | None]
        The DEM the whole grid is filled from (``dem_path`` itself when nothing
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
    flow_lines = None
    if building_gpkg is not None:
        dem = raise_buildings_in_dem(dem, transform, 2180, building_gpkg, nodata=nodata)
        changed = True
    if burn_streams_path is not None:
        dem, burn_diag = burn_streams_into_dem(
            dem, transform, burn_streams_path, burn_depth_m, nodata, stream_burning
        )
        stats["burn_cells"] = burn_diag["cells_burned"]
        stats["stream_burning"] = stream_burning
        changed = True
        if smooth_streams:
            dem, flow_lines, smooth_diag = smooth_streams_monotonic(
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
            flow_lines=flow_lines,
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


def _reset_peak_rss() -> None:
    """Begin a new peak of the resident set where Linux allows it."""
    try:
        _CLEAR_REFS.write_text("5")
    except OSError:
        logger.debug("The peak RSS cannot be reset: stage peaks are cumulative")


def _peak_rss_mb() -> float:
    """Return the peak resident set [MB]: since the last reset where Linux has it."""
    try:
        for line in _STATUS.read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
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
    units_catchments_path: Path | None = None,
    units_catchments_layer: str | None = None,
    units_catchments_key: str = DEFAULT_CATCHMENT_KEY,
    scratch_dir: Path | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    """Process the DEM by PGW units and publish the run, or only compute it.

    The arguments are those of ``process_dem`` of the same name, plus the PGW
    GeoPackage and its options. A run always writes its unit rasters and VRT mosaics
    (``process_dem --save-intermediates`` is not needed). Without ``dry_run`` the run
    is recorded, each unit is checkpointed as soon as its cells are taken from the
    fill of the whole grid, and the DEM-derived network of the database is replaced
    by the run in one transaction; any failure before that leaves the database as it
    was and marks the run failed. A later call with the same inputs and settings
    resumes that run (``resume``): the units it routed are restored from their files.

    Parameters
    ----------
    input_path : Path
        The DEM (a GeoTIFF or the VRT mosaic of the NMT sheets, EPSG:2180; a VRT
        must read its sources cell for cell).
    units_path : Path
        The PGW GeoPackage of Kartograf.
    units_area_path : Path, optional
        Vector file of the analysis area; the owners are clipped to it
        (``core.unit_ownership.load_pgw_owners``).
    units_area_layer : str, optional
        Layer of ``units_area_path`` (default: the first).
    units_catchments_path : Path, optional
        Catchments to group into the owners (each goes to the PGW unit it overlaps
        most; ``core.unit_ownership.group_catchments``); their keys are recorded
        with the units.
    units_catchments_layer : str, optional
        Layer of ``units_catchments_path`` (default: the first).
    units_catchments_key : str
        Field of the unique key of a catchment (default ``ID_HYD_10``).
    scratch_dir : Path, optional
        Directory for the scratch of the call (the fill of the whole grid and the
        disk-backed rasters of the routing), instead of the run's directory: another
        disk when the one of ``output_dir`` cannot hold it.
    resume : bool
        Take up the latest staging or failed run with the same inputs and
        settings instead of beginning a new one.

    Returns
    -------
    dict
        The statistics of ``process_dem``, with ``run_id`` (None for a dry run),
        ``pgw_owners``, ``unit_rasters_dir``, ``unit_dem_vrt``, ``resumed_units``
        and ``stages`` (wall time and peak RSS by stage).
    """
    input_path = Path(input_path)
    units_path = Path(units_path)
    if not input_path.is_file() or not units_path.is_file():
        raise FileNotFoundError(
            f"DEM or PGW GeoPackage not found: {input_path}, {units_path}"
        )
    catchment_file = None
    if units_catchments_path is not None:
        if not Path(units_catchments_path).is_file():
            raise FileNotFoundError(
                f"Catchment file not found: {units_catchments_path}"
            )
        catchment_file = CatchmentFile(
            Path(units_catchments_path), units_catchments_layer, units_catchments_key
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
    if stream_burning not in STREAM_BURNING_MODES:
        raise ValueError(
            f"stream_burning must be one of {STREAM_BURNING_MODES}, "
            f"not {stream_burning!r}"
        )
    # Refuses a VRT that resamples its sources before any work.
    _file_dependencies(input_path)

    started = time.time()
    output_dir = Path(output_dir) if output_dir is not None else input_path.parent
    # The scratch of this call; a resumed run keeps its files where it began.
    token = uuid.uuid4().hex
    work_dir = output_dir / "unit_runs" / token
    work_dir.mkdir(parents=True)
    scratch = (
        Path(scratch_dir) / token if scratch_dir is not None else work_dir / "scratch"
    )
    scratch.mkdir(parents=True)
    run_dir = work_dir
    stats: dict[str, Any] = {"run_id": None, "resumed_units": 0}
    run_id: int | None = None
    published = False
    with ExitStack() as held:
        try:
            with _stage(stats, "ownership"):
                grid_dem = input_path
                if hydro_resolution_m is not None:
                    with rasterio.open(input_path) as original:
                        if hydro_resolution_m > original.transform.a:
                            grid_dem = downsample_raster(
                                input_path,
                                scratch / "downsampled.tif",
                                hydro_resolution_m,
                            )
                            stats["hydro_resolution_m"] = hydro_resolution_m
                owners = load_pgw_owners(
                    grid_dem,
                    units_path,
                    scratch / "ownership",
                    units_area_path,
                    units_area_layer,
                    catchment_file,
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
            if owners.members:
                stats["catchments"] = sum(len(keys) for keys in owners.members.values())
            # What the results depend on, besides the input files.
            parameters: dict[str, Any] = {
                "thresholds_m2": list(thresholds_m2),
                "hydro_resolution_m": stats.get("hydro_resolution_m"),
                "burn_depth_m": burn_depth_m if burn_streams_path else None,
                "stream_burning": stream_burning if burn_streams_path else None,
                "smooth_streams": smooth_streams if burn_streams_path else None,
                "waterbody_mode": waterbody_mode,
                "waterbody_min_area_m2": waterbody_min_area_m2,
                "units_area_layer": units_area_layer,
                "catchments": (
                    {"layer": catchment_file.layer, "key": catchment_file.key}
                    if catchment_file is not None
                    else None
                ),
                "grid": grid,
                "owners": list(active_owners),
            }
            checkpoints: _RunCheckpoints | None = None
            if not dry_run:
                source_paths = [input_path, units_path]
                for optional in (
                    burn_streams_path,
                    units_area_path,
                    units_catchments_path,
                ):
                    if optional is not None:
                        source_paths.append(Path(optional))
                if building_gpkg is not None:
                    source_paths.append(Path(building_gpkg))
                if waterbody_mode not in ("none", "auto"):
                    source_paths.append(Path(waterbody_mode))
                fingerprint = _input_fingerprint(source_paths, parameters)
                resumed = None
                with get_db_session() as db:
                    if resume:
                        resumed = resume_run(
                            db, input_fingerprint=fingerprint, config=parameters
                        )
                    if resumed is None:
                        candidate = begin_run(
                            db,
                            input_fingerprint=fingerprint,
                            source_raster=str(input_path),
                            pgw_path=str(units_path),
                            config={**parameters, "run_dir": str(run_dir.resolve())},
                            owner_codes=active_owners,
                            catchment_keys=(
                                {code: owners.members[code] for code in active_owners}
                                if owners.members
                                else None
                            ),
                        )
                    else:
                        candidate = resumed.run_id
                        run_dir = Path(resumed.config["run_dir"])
                # Raises before the run is ours if another process holds it.
                held.enter_context(run_lock(get_db_engine(), candidate))
                run_id = candidate
                stats["run_id"] = run_id
                if resumed is not None:
                    logger.info("Run %d is resumed in %s", run_id, run_dir)
                stage_dir = run_dir / "stage"
                stage_dir.mkdir(parents=True, exist_ok=True)
                checkpoints = _RunCheckpoints(
                    run_id,
                    owners.codes,
                    stage_dir,
                    resumed.units if resumed is not None else {},
                )

            with _stage(stats, "prepare_dem"):
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
                drain_points=drain_points,
                checkpoints=checkpoints,
                stage=partial(_stage, stats),
            )
            if checkpoints is not None:
                stats["resumed_units"] = len(checkpoints.restored)
                logger.info("Units restored: %d", stats["resumed_units"])
            with _stage(stats, "statistics"):
                lowest_cells = max(1, int(thresholds_m2[0] / cellsize**2))
                mean_slope, stream_cells = _row_statistics(
                    result, owners.valid, lowest_cells
                )
                stats.update(
                    max_accumulation=int(result.acc.max()),
                    mean_slope=mean_slope,
                    stream_cells=stream_cells,
                )
            with _stage(stats, "polygonize_subcatchments"):
                flow = UnitFlowPaths.from_hydrology(
                    result, metadata["transform"], scratch / "downstream.npy"
                )
                catchments = _network_rows(
                    result, flow, metadata, thresholds_m2, nodata, skip_catchments
                )
                segments = {t: result.segments[t] for t in thresholds_m2}
                _record_threshold_stats(stats, segments, catchments)

            with _stage(stats, "secondary_rasters"):
                secondary = _secondary_rasters(
                    result, cellsize, nodata, scratch, lowest_cells
                )
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
            with _stage(stats, "unit_mosaics"):
                mosaics, files_by_owner = write_unit_mosaics(
                    grid_dem,
                    owners.cells,
                    owners.codes,
                    rasters,
                    run_dir,
                    input_path.stem,
                )
            stats["unit_dem_vrt"] = str(mosaics["01_dem"])
            stats["unit_rasters_dir"] = str(run_dir)

            if run_id is not None and checkpoints is not None:
                with _stage(stats, "checkpoints"), get_db_session() as db:
                    for index, bbox in enumerate(owner_bboxes, start=1):
                        if bbox is None:
                            continue
                        row, col = bbox
                        code = owners.codes[index - 1]
                        outputs = dict(files_by_owner[index])
                        # The stage stays recorded: a failed publication resumes.
                        outputs["stage"] = checkpoints.stage_files[code]
                        checkpoint_unit(
                            db,
                            run_id,
                            code,
                            (row.start, row.stop, col.start, col.stop),
                            outputs,
                        )
                with _stage(stats, "publish"), get_db_session() as db:
                    stats.update(publish_run(db, run_id, segments, catchments))
                published = True
                logger.info("PGW run %s published as %s", run_id, run_dir)
                try:
                    write_active_run(output_dir, run_id, run_dir)
                    stats["active_run_written"] = True
                except OSError as error:
                    # The network is published; the pointer only shows the later
                    # steps and the API the files of the run.
                    stats["active_run_written"] = False
                    logger.warning(
                        "Run %s is published, but the active run pointer to %s "
                        "could not be written: %s",
                        run_id,
                        run_dir,
                        error,
                    )
            stats["peak_rss_mb"] = max(
                stats.get("peak_rss_mb", 0.0), round(_peak_rss_mb(), 1)
            )
            stats["elapsed_s"] = round(time.time() - started, 1)
            report: dict[str, Any] = {
                "run_id": run_id,
                "owners": list(active_owners),
                **{
                    key: stats[key]
                    for key in (
                        "valid_cells",
                        "catchments",
                        "resumed_units",
                        "stream_segments",
                        "stream_thresholds",
                        "stages",
                        "peak_rss_mb",
                        "elapsed_s",
                    )
                    if key in stats
                },
            }
            (run_dir / "report.json").write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            # The tiles hold everything the run publishes; the routing is scratch,
            # and the stages of a published run are never resumed.
            del result, flow, secondary, owners
            shutil.rmtree(scratch, ignore_errors=True)
            if run_dir != work_dir:
                shutil.rmtree(work_dir, ignore_errors=True)
            if published:
                shutil.rmtree(run_dir / "stage", ignore_errors=True)
        except BaseException as error:
            if run_id is not None and not published:
                try:
                    with get_db_session() as db:
                        fail_run(db, run_id, f"{type(error).__name__}: {error}")
                except Exception:
                    logger.exception("Run %s could not be marked failed", run_id)
            raise

        if burn_streams_path is not None and run_id is not None:
            # As process_dem does after its insert: the BDOT10k streams and the
            # match of the network with them; the run is already published.
            with _stage(stats, "bdot_streams"):
                bdot_data = load_bdot_streams_from_gpkg(burn_streams_path)
                if bdot_data:
                    with get_db_session() as db:
                        insert_bdot_streams(db, bdot_data)
                        update_stream_real_flags_all(db, list(thresholds_m2))
                else:
                    logger.warning(
                        "No BDOT hydro data found - skipping stream matching"
                    )
    return stats
