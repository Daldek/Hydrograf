"""The Kartograf inputs of the bootstrap, taken from a set of an Archiwista project.

ADR-067. The bootstrap reads a closed set strictly: every Kartograf input of steps 2 to
5 is a pinned version of the project's Kartograf store whose size and SHA-256 were
checked (``utils.archiwista_project``), and the set must hold what the run needs:

- the NMT sheets of the project's area: ``find_sheets_for_geometry`` of the area file
  at 1:10000 in the PL-1992 grid (the rule of Archiwista's call, Kartograf's ADR-058),
  among the pins of the segment ``nmt/pl_1992_<resolution>_evrf2007``; the pinned
  sheets beyond them are used too, and all of them make the mosaic. A sheet of the
  area that the segment lacks (GUGiK publishes some sheets only at 1 m) is taken from
  the segment of a finer resolution pinned in the set, the nearest finer one first
  (ADR-087); step 3 averages it onto the cells of the run;
- the BDOT10k packages (``landcover/pl_bdot10k_gpkg``) of the counties that the county
  register (PRG) names for the box of the mosaic, the rule of steps 3 and 4, unless the
  land cover is skipped (then step 3 burns the streams of the packages the set has);
- one HSG raster of the segment of ``soil.hsg_depth_rule`` (ADR-079; by default
  ``hsg/global_soilgrids_0-100cm_least-permeable_mean``) whose requested box, as its
  sidecar records it, covers the box of the mosaic, unless the HSG is skipped. An HSG
  raster of another rule is never taken instead: without the one of the rule the set
  is refused, with the Kartograf command that computes it.

A unit (a sheet, a county, a raster) has one version in the set. The other Kartograf
pins (the SoilGrids inputs of the HSG raster, an HSG raster of another rule) are
checked and not used; the pins of other producers are neither. A unit is the stem of
its version's file name, which Kartograf's layout makes the sheet code, the TERYT code
or the box of the request.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from core.errors import (
    ConflictError,
    InvalidDataError,
    NoDataError,
    SourceUnavailableError,
)
from utils.archiwista_project import (
    KARTOGRAF,
    Pin,
    PinSet,
    Project,
    kartograf_root,
    pins_digest,
    project_area,
    read_project,
    read_set,
    verify_pins,
)
from utils.kartograf_store import (
    DEFAULT_HSG_DEPTH_RULE,
    HSG_DEPTH_RULES,
    SHEET_SYSTEM,
    describe_error,
    open_metadata_cache,
)
from utils.nmt_coverage import sheets_bbox_2180

logger = logging.getLogger(__name__)

# The scale of the GUGiK sheets, the one Archiwista's call selects by.
SHEET_SCALE = "1:10000"
BDOT10K_SEGMENT = "landcover/pl_bdot10k_gpkg"

type Box = tuple[float, float, float, float]

# The NMT resolutions of the GUGiK sheets, the finest first.
NMT_RESOLUTIONS = ("1m", "5m")


def nmt_segment(resolution: str) -> str:
    """Return the store segment of the NMT sheets of ``resolution`` (``5m``, ``1m``)."""
    return f"nmt/pl_{SHEET_SYSTEM}_{resolution}_evrf2007"


def finer_resolutions(resolution: str) -> tuple[str, ...]:
    """Return the NMT resolutions finer than ``resolution``, the nearest first."""
    return tuple(reversed(NMT_RESOLUTIONS[: NMT_RESOLUTIONS.index(resolution)]))


@dataclass(frozen=True)
class SetInputs:
    """What a bootstrap from a set reads, all of it checked.

    Attributes
    ----------
    project : Project
        The project file as read.
    pin_set : PinSet
        The closed set.
    root : Path
        The project's Kartograf store.
    area : Path
        The area file, its SHA-256 checked.
    area_bbox_wgs84 : Box
        The box of the area (step 6, the precipitation grid).
    digest : str
        ``pins_sha256`` of the set: the one of the file, else computed.
    resolution : str
        The NMT resolution of the run.
    required_sheets : tuple[str, ...]
        The sheets of the area.
    sheets : dict[str, Path]
        The sheets of the mosaic, code to version file: every pinned sheet of the
        resolution's segment and the sheets of the area that a finer segment gives.
    finer_sheets : dict[str, tuple[str, ...]]
        The finer segments that give sheets of the area the resolution's segment
        lacks, each with the codes of its sheets (ADR-087); empty when none.
    mosaic_bbox_2180 : Box
        The box of the frames of ``sheets`` (EPSG:2180).
    counties : dict[str, Path]
        TERYT to the pinned BDOT10k package: the counties of the mosaic, or every
        pinned county when the land cover is skipped.
    counties_checked : bool
        Whether PRG named the counties of the mosaic (False: the land cover is
        skipped).
    hsg : Path or None
        The pinned HSG raster of the rule, None when the HSG is skipped.
    unused : tuple[str, ...]
        Versions of the set's Kartograf pins that the run does not read.
    foreign : int
        Pins of other producers (not read).
    """

    project: Project
    pin_set: PinSet
    root: Path
    area: Path
    area_bbox_wgs84: Box
    digest: str
    resolution: str
    required_sheets: tuple[str, ...]
    sheets: dict[str, Path]
    finer_sheets: dict[str, tuple[str, ...]]
    mosaic_bbox_2180: Box
    counties: dict[str, Path]
    counties_checked: bool
    hsg: Path | None
    unused: tuple[str, ...]
    foreign: int

    def identity(self) -> dict[str, Any]:
        """Return what ties the results of a run to the set (logged and recorded)."""
        area = self.project.area
        return {
            "project": {
                "path": str(self.project.directory),
                "name": self.project.name,
                "area_sha256": area.sha256 if area is not None else None,
            },
            "set": {
                "name": self.pin_set.name,
                "closed_at": self.pin_set.closed_at,
                "closed_by": self.pin_set.closed_by,
                "pins_sha256": self.digest,
                "pins_sha256_recorded": self.pin_set.pins_sha256 is not None,
                "pins": len(self.pin_set.pins),
            },
            "store": str(self.root),
            "inputs": {
                "nmt": {
                    "segment": nmt_segment(self.resolution),
                    "sheets": len(self.sheets),
                    "area_sheets": len(self.required_sheets),
                    "finer_sheets": {
                        segment: list(codes)
                        for segment, codes in self.finer_sheets.items()
                    },
                },
                "bdot10k": sorted(self.counties),
                "hsg": (
                    self.hsg.relative_to(self.root).as_posix()
                    if self.hsg is not None
                    else None
                ),
                "unused": len(self.unused),
                "other_producers": self.foreign,
            },
        }


def set_inputs(
    project_path: Path,
    set_name: str,
    *,
    resolution: str,
    cache_dir: Path,
    landcover: bool = True,
    hsg: bool = True,
    hsg_depth_rule: str = DEFAULT_HSG_DEPTH_RULE,
) -> SetInputs:
    """Read a set of an Archiwista project and check everything a bootstrap needs.

    In the order of ADR-067: the project file, the area, the set (closed, its
    digest), the store, every pin of the Kartograf store, then what the run needs.
    Nothing is downloaded; the only request is the county register (PRG) for the
    counties of the mosaic, answered from the metadata cache of ``cache_dir`` when it
    has the answer.

    Parameters
    ----------
    project_path : Path
        The project directory, or its ``archiwista-project.json``.
    set_name : str
        The set's name (compared case-folded).
    resolution : str
        ``5m`` or ``1m``: the NMT segment of the sheets. A sheet of the area that its
        segment lacks may come from the segment of a finer resolution (ADR-087).
    cache_dir : Path
        The cache directory of the pipeline (its Kartograf metadata cache).
    landcover : bool
        Require the BDOT10k packages of the mosaic's counties (False: the land cover
        is skipped).
    hsg : bool
        Require an HSG raster that covers the mosaic (False: the HSG is skipped).
    hsg_depth_rule : str
        ``soil.hsg_depth_rule``, a key of ``HSG_DEPTH_RULES``: the store segment of
        the HSG raster.

    Raises
    ------
    HydrografError
        Every refusal of ``utils.archiwista_project`` and, here: ``no_data``
        (``set_sheets_missing``, ``set_counties_missing``, ``set_hsg_missing``;
        ``details["units"]``), ``conflict`` (``set_unit_ambiguous``),
        ``source_unavailable`` (``prg_unavailable``), ``data_error``
        (``area_unreadable``).
    """
    project = read_project(project_path)
    area = project_area(project)
    pin_set = read_set(project, set_name)
    root = kartograf_root(project)
    pins = [pin for pin in pin_set.pins if pin.producer == KARTOGRAF]
    verify_pins(root, pins, pin_set.name)

    layers = HSG_DEPTH_RULES[hsg_depth_rule]
    by_segment = {
        segment: _units(pins, segment)
        for segment in (nmt_segment(resolution), BDOT10K_SEGMENT, layers.segment)
    }
    ambiguous = sorted(
        unit
        for units in by_segment.values()
        for unit, versions in units.items()
        if len(versions) > 1
    )
    if ambiguous:
        raise ConflictError(
            "set_unit_ambiguous",
            reason="set_unit_ambiguous",
            name=pin_set.name,
            count=len(ambiguous),
            units=ambiguous,
        )
    nmt, bdot10k, rasters = (
        {unit: root / versions[0] for unit, versions in sorted(units.items())}
        for units in by_segment.values()
    )
    required, area_bbox_wgs84 = _area_sheets(area)
    finer = _finer_sheets(pins, set(required) - set(nmt), resolution, pin_set.name)
    if finer:
        logger.warning(
            "NMT sheets of the area that %s lacks, taken from a finer segment of the "
            "set (averaged onto the %s cells in step 3): %s",
            nmt_segment(resolution),
            resolution,
            "; ".join(
                f"{segment}: {len(versions)} ({', '.join(versions)})"
                for segment, versions in finer.items()
            ),
        )
    sheets = dict(
        sorted(
            [
                *nmt.items(),
                *(
                    (code, root / version)
                    for versions in finer.values()
                    for code, version in versions.items()
                ),
            ]
        )
    )
    missing = sorted(set(required) - set(sheets))
    if missing or not sheets:
        raise NoDataError(
            "set_sheets_missing",
            reason="set_sheets_missing",
            name=pin_set.name,
            resolution=resolution,
            count=len(missing),
            units=missing,
        )
    mosaic = sheets_bbox_2180(sheets)

    counties = dict(bdot10k)
    if landcover:
        teryts = _counties(mosaic, cache_dir)
        missing = sorted(set(teryts) - set(bdot10k))
        if missing:
            raise NoDataError(
                "set_counties_missing",
                reason="set_counties_missing",
                name=pin_set.name,
                count=len(missing),
                units=missing,
            )
        counties = {teryt: bdot10k[teryt] for teryt in teryts}

    raster = None
    if hsg:
        covering = [path for path in rasters.values() if _covers(path, mosaic)]
        if not covering:
            raise NoDataError(
                "set_hsg_missing",
                reason="set_hsg_missing",
                name=pin_set.name,
                depth_rule=hsg_depth_rule,
                segment=layers.segment,
                command=layers.command(mosaic),
                rasters=sorted(rasters),
            )
        if len(covering) > 1:
            units = sorted(path.stem for path in covering)
            raise ConflictError(
                "set_unit_ambiguous",
                reason="set_unit_ambiguous",
                name=pin_set.name,
                count=len(units),
                units=units,
            )
        raster = covering[0]

    used = {*sheets.values(), *counties.values(), *([raster] if raster else [])}
    return SetInputs(
        project=project,
        pin_set=pin_set,
        root=root,
        area=area,
        area_bbox_wgs84=area_bbox_wgs84,
        digest=pin_set.pins_sha256 or pins_digest(pin_set.pins),
        resolution=resolution,
        required_sheets=tuple(required),
        sheets=sheets,
        finer_sheets={segment: tuple(codes) for segment, codes in finer.items()},
        mosaic_bbox_2180=mosaic,
        counties=counties,
        counties_checked=landcover,
        hsg=raster,
        unused=tuple(pin.version for pin in pins if root / pin.version not in used),
        foreign=len(pin_set.pins) - len(pins),
    )


def _units(pins: Sequence[Pin], segment: str) -> dict[str, list[str]]:
    """Return each unit of ``segment`` in the pins with its versions."""
    units: dict[str, list[str]] = {}
    for pin in pins:
        if pin.version.startswith(f"{segment}/versions/"):
            unit = PurePosixPath(pin.version).stem
            units.setdefault(unit, []).append(pin.version)
    return units


def _finer_sheets(
    pins: Sequence[Pin], gaps: set[str], resolution: str, set_name: str
) -> dict[str, dict[str, str]]:
    """Return the finer segments that give the sheets ``gaps``: code to version.

    Each sheet comes from the nearest finer resolution whose segment has it; a sheet
    with two versions there is refused (``set_unit_ambiguous``). The finer pins of
    other sheets are not used.
    """
    finer: dict[str, dict[str, str]] = {}
    left = set(gaps)
    for finer_resolution in finer_resolutions(resolution):
        segment = nmt_segment(finer_resolution)
        units = {u: v for u, v in _units(pins, segment).items() if u in left}
        ambiguous = sorted(
            unit for unit, versions in units.items() if len(versions) > 1
        )
        if ambiguous:
            raise ConflictError(
                "set_unit_ambiguous",
                reason="set_unit_ambiguous",
                name=set_name,
                count=len(ambiguous),
                units=ambiguous,
            )
        if units:
            finer[segment] = {unit: units[unit][0] for unit in sorted(units)}
            left -= set(units)
    return finer


def _area_sheets(area: Path) -> tuple[list[str], Box]:
    """Return the sheets of the area (ADR-058) and the area's box in EPSG:4326."""
    from kartograf import KartografError, find_sheets_for_geometry

    from core.boundary import boundary_to_bbox_wgs84, load_boundary

    try:
        sheets = find_sheets_for_geometry(area, SHEET_SCALE, sheet_system=SHEET_SYSTEM)
        bbox = boundary_to_bbox_wgs84(load_boundary(area))
    except (KartografError, ValueError) as error:
        raise InvalidDataError(
            "project_area_unreadable",
            reason="area_unreadable",
            path=str(area),
            cause=describe_error(error),
        ) from error
    return sheets, bbox


def _counties(mosaic: Box, cache_dir: Path) -> list[str]:
    """Return the counties that PRG names for the box of the mosaic."""
    from kartograf import BBox, Bdot10kProvider, KartografError

    provider = Bdot10kProvider(cache=open_metadata_cache(cache_dir))
    try:
        return sorted(provider.teryts_for_area(BBox(*mosaic, crs="EPSG:2180")))
    except (KartografError, OSError) as error:
        raise SourceUnavailableError(
            "prg_unavailable", reason="prg_unavailable", cause=describe_error(error)
        ) from error


def _covers(raster: Path, mosaic: Box) -> bool:
    """Say whether the box requested for an HSG raster covers the mosaic.

    The box and its CRS come from the sidecar of the version (``request``); a raster
    whose sidecar cannot be read, or has no box, covers nothing.
    """
    from kartograf import BBox, KartografError, read_sidecar, transform_bbox

    try:
        request = read_sidecar(raster).request or {}
        min_x, min_y, max_x, max_y = (float(value) for value in request["bbox"])
        box = BBox(min_x, min_y, max_x, max_y, crs=str(request["bbox_crs"]))
        if box.crs != "EPSG:2180":
            box = transform_bbox(box, "EPSG:2180")
    except (KartografError, KeyError, TypeError, ValueError) as error:
        logger.warning("HSG raster %s: no requested box (%s)", raster, error)
        return False
    return (
        box.min_x <= mosaic[0]
        and box.min_y <= mosaic[1]
        and box.max_x >= mosaic[2]
        and box.max_y >= mosaic[3]
    )
