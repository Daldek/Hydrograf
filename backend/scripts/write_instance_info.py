r"""Write ``instance.json``: what the data of this Hydrograf instance cover.

The welcome dialog and the guide of the front end read ``/data/instance.json`` to name
the area of the instance; without the file they show a neutral text. The API reads its
``sources`` for the line G of GUGiK's data (Nogat DEV §20, ``core.data_sources``). The
bootstrap writes it at the end of a run; this script (re)writes it for an instance
whose data already exist, without a bootstrap run::

    python -m scripts.write_instance_info --area-name "zlewnia Kaczawy do Legnicy" \
        --boundary-file /data/boundary/zlewnia_kaczawy_790km2_przyciecie.gpkg \
        --nmt /cache/nmt/pl_1992_5m_evrf2007 --nmt-sheets /data/boundary/sheets.txt \
        --bdot10k /cache/bdot10k/bdot10k_teryt_0207.gpkg \
        --soilgrids /cache/soil_hsg/hsg_poland.tif

The file (schema ``hydrograf-instance/1``) is public: it holds no server paths, only
the boundary's file name.

- ``area.name``: ``--area-name``, else the name of the Archiwista project of the set
  (``bootstrap_set.json``), else the stem of the boundary file, else null;
- ``area.area_km2``: the area of the boundary (EPSG:2180), one decimal; the boundary is
  ``--boundary-file``, else the area file of the set's project; null without either;
- ``counties``: the TERYT codes of the BDOT10k packages of the set, null when unknown;
- ``nmt``: the NMT resolution (``--resolution``, else the set's NMT segment, else the
  cell of the saved DEM mosaic) and the set's segment;
- ``hsg``: the rule of the soil groups (``soil.hsg_depth_rule``, ADR-079) and the
  store segment of its raster: ``--hsg-depth-rule``, else the rule of the set record;
  null when unknown (a run that skipped step 5, data without a record);
- ``set``: project, name and ``closed_at`` of the set, null for a run without a set;
- ``sources``: the provider products the data were made from (``NMT``, ``BDOT10k``,
  ``SoilGrids``), each with the years its data were created (``created``) and the days
  its files were downloaded (``acquired``), from the Kartograf metadata of the files
  the run used (``--nmt``, ``--bdot10k``, ``--soilgrids`` here): an NMT sheet was
  created in the year of its flight (``extra.source.acquisition_date``), a BDOT10k
  package in the year of its edition, else of the ``Last-Modified`` of its download
  (``extra.http.last_modified``), else of the newest ``last_change`` of its tables;
  SoilGrids states no creation time. A package without metadata counts the day of its
  file as its download. A product the run did not use keeps the entry of the file
  written before; null when no product is known;
- ``generated_at``: when the file was written (UTC).
"""

import argparse
import json
import logging
import os
import re
import sqlite3
import sys
from collections.abc import Iterable, Mapping
from contextlib import closing
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from core.data_sources import (
    BDOT10K,
    NMT,
    SOILGRIDS,
    ProductDates,
    parse_sources,
    sources_member,
)
from utils.kartograf_store import HSG_DEPTH_RULES

if TYPE_CHECKING:
    from kartograf import Sidecar

logger = logging.getLogger(__name__)

INSTANCE_INFO_NAME = "instance.json"
INSTANCE_INFO_SCHEMA = "hydrograf-instance/1"

# The NMT segments of the Kartograf store end in ``_<resolution>m_<datum>``
_SEGMENT_RESOLUTION = re.compile(r"_(\d+(?:\.\d+)?)m_")
# The directories of a Kartograf store that hold its files again (versions, flights,
# full sheets): the standard paths have every file once
_STORE_COPIES = frozenset({"versions", "kampanie", "full_sheet"})
_SIDECAR = ".meta.json"


def resolution_m(value: str) -> float:
    """Return the metres of a resolution written as the bootstrap's ``5m``."""
    return float(value.removesuffix("m"))


def _segment_resolution_m(segment: str | None) -> float | None:
    match = _SEGMENT_RESOLUTION.search(segment or "")
    return float(match.group(1)) if match else None


def _sidecar(path: Path) -> "Sidecar | None":
    """Return the Kartograf metadata of a data file, None without them (logged)."""
    from kartograf import InvalidSidecarError, read_sidecar

    try:
        return read_sidecar(path)
    except InvalidSidecarError as error:
        logger.warning("%s has no Kartograf metadata: %s", path, error)
        return None


def _day(moment: str | None) -> str | None:
    """Return the UTC day of an ISO 8601 time, None for none or another text."""
    if not moment:
        return None
    try:
        parsed = datetime.fromisoformat(moment)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).date().isoformat()


def nmt_dates(files: Iterable[Path]) -> ProductDates:
    """Return when the NMT sheets were created (their flights) and downloaded."""
    created: set[int] = set()
    acquired: set[str] = set()
    for path in files:
        side = _sidecar(path)
        if side is None:
            continue
        if side.data_year is not None:
            created.add(side.data_year)
        if day := _day(side.downloaded_at):
            acquired.add(day)
    return ProductDates(frozenset(created), frozenset(acquired))


def _package_year(path: Path, side: "Sidecar | None") -> int | None:
    """Return the year a BDOT10k package was created.

    The edition of an archive package, else the ``Last-Modified`` of its download (the
    generation of the county's package), else the newest ``last_change`` of its tables.
    """
    if side is not None and side.data_year is not None:
        return side.data_year
    http = (side.extra or {}).get("http") if side is not None else None
    modified = http.get("last_modified") if isinstance(http, dict) else None
    if isinstance(modified, str):
        try:
            return parsedate_to_datetime(modified).astimezone(UTC).year
        except (TypeError, ValueError):
            logger.warning("%s: Last-Modified %r is no date", path, modified)
    # immutable: the package is only read, no journal is made beside it
    uri = f"file:{quote(str(path))}?mode=ro&immutable=1"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as db:
            (latest,) = db.execute(
                "SELECT max(last_change) FROM gpkg_contents"
            ).fetchone()
    except sqlite3.Error as error:
        logger.warning("%s: the tables of the package cannot be read: %s", path, error)
        return None
    if isinstance(latest, str) and latest[:4].isdigit():
        return int(latest[:4])
    return None


def bdot10k_dates(files: Iterable[Path]) -> ProductDates:
    """Return when the BDOT10k packages were created and downloaded."""
    created: set[int] = set()
    acquired: set[str] = set()
    for path in files:
        side = _sidecar(path)
        if (year := _package_year(path, side)) is not None:
            created.add(year)
        day = _day(side.downloaded_at) if side is not None else None
        if day is None:
            # Written by an older pipeline without metadata: the day of its file
            day = datetime.fromtimestamp(path.stat().st_mtime, UTC).date().isoformat()
            logger.warning("%s: downloaded on the day of its file, %s", path, day)
        acquired.add(day)
    return ProductDates(frozenset(created), frozenset(acquired))


def soilgrids_dates(files: Iterable[Path]) -> ProductDates:
    """Return when the SoilGrids rasters were downloaded; SoilGrids states no year."""
    acquired: set[str] = set()
    for path in files:
        side = _sidecar(path)
        if side is not None and (day := _day(side.downloaded_at)):
            acquired.add(day)
    return ProductDates(frozenset(), frozenset(acquired))


def data_sources(used: Mapping[str, Iterable[Path]]) -> dict[str, ProductDates]:
    """Return the dates of the products of the files a run used.

    Parameters
    ----------
    used : Mapping[str, Iterable[Path]]
        The files of each product (``NMT``, ``BDOT10K``, ``SOILGRIDS``); a product
        without files is left out.
    """
    dating = {NMT: nmt_dates, BDOT10K: bdot10k_dates, SOILGRIDS: soilgrids_dates}
    sources = {}
    for product, files in used.items():
        paths = sorted(set(files))
        if paths:
            sources[product] = dating[product](paths)
    return sources


def data_files(
    paths: Iterable[Path], suffix: str | None = None, names: set[str] | None = None
) -> list[Path]:
    """Return the data files of the given files and directories.

    A directory gives, below it, every file with Kartograf metadata, or with
    ``suffix`` (a BDOT10k package without metadata), without the store's copies of
    the same files (``versions/``, ``kampanie/``, ``full_sheet/``); with ``names``
    only the files whose name up to the first dot is one of them (NMT sheet codes).
    """
    files: list[Path] = []
    for path in paths:
        if not path.is_dir():
            files.append(path)
            continue
        for root, dirs, entries in os.walk(path):
            dirs[:] = sorted(d for d in dirs if d not in _STORE_COPIES)
            present = set(entries)
            for entry in sorted(entries):
                if entry.endswith(_SIDECAR):
                    continue
                if f"{entry}{_SIDECAR}" in present or (
                    suffix is not None and entry.endswith(suffix)
                ):
                    files.append(Path(root) / entry)
    if names is not None:
        files = [f for f in files if f.name.split(".", 1)[0] in names]
    return files


def merged_sources(
    previous: Mapping[str, ProductDates] | None, run: Mapping[str, ProductDates]
) -> dict[str, ProductDates] | None:
    """Return the products of a run's files over those of the file written before."""
    sources = {**(previous or {}), **run}
    return sources or None


def read_sources(frontend_data: Path) -> dict[str, ProductDates] | None:
    """Return the products of the ``instance.json`` written before, None without."""
    try:
        document = json.loads(
            (frontend_data / INSTANCE_INFO_NAME).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    return (
        parse_sources(document.get("sources")) if isinstance(document, dict) else None
    )


def build_instance_info(
    *,
    generated_at: str,
    area_name: str | None = None,
    boundary: Path | None = None,
    boundary_layer: str | None = None,
    set_identity: dict[str, Any] | None = None,
    nmt_resolution_m: float | None = None,
    hsg_depth_rule: str | None = None,
    sources: Mapping[str, ProductDates] | None = None,
) -> dict[str, Any]:
    """Build the document ``hydrograf-instance/1``.

    Parameters
    ----------
    generated_at : str
        The UTC time of writing (``YYYY-MM-DDTHH:MM:SSZ``).
    area_name : str, optional
        The name of the area; default the set's project name, else the boundary's stem.
    boundary : Path, optional
        The boundary file whose area the document gives.
    boundary_layer : str, optional
        Its layer, for a multi-layer file.
    set_identity : dict, optional
        The identity of the set the data come from: ``SetInputs.identity()`` or the
        record ``bootstrap_set.json``.
    nmt_resolution_m : float, optional
        The NMT resolution; default the one of the set's NMT segment.
    hsg_depth_rule : str, optional
        The rule of the soil groups of the data, a key of ``HSG_DEPTH_RULES``; default
        the one the set record keeps (``hsg_depth_rule``), else unknown.
    sources : Mapping[str, ProductDates], optional
        The provider products the data were made from, with their dates
        (``data_sources``, ``merged_sources``); unknown without.
    """
    identity = set_identity or {}
    project = identity.get("project") or {}
    pin_set = identity.get("set") or {}
    nmt = (identity.get("inputs") or {}).get("nmt") or {}
    segment = nmt.get("segment")
    if nmt_resolution_m is None:
        nmt_resolution_m = _segment_resolution_m(segment)
    name = area_name or project.get("name") or (boundary.stem if boundary else None)
    area_km2 = None
    if boundary is not None:
        from core.boundary import boundary_area_km2, load_boundary

        area_km2 = round(boundary_area_km2(load_boundary(boundary, boundary_layer)), 1)
    counties = (identity.get("inputs") or {}).get("bdot10k")
    if hsg_depth_rule is None:
        hsg_depth_rule = identity.get("hsg_depth_rule")
    return {
        "schema": INSTANCE_INFO_SCHEMA,
        "area": {
            "name": name,
            "area_km2": area_km2,
            "boundary": boundary.name if boundary else None,
        },
        "counties": sorted(counties) if counties is not None else None,
        "nmt": {"resolution_m": nmt_resolution_m, "segment": segment},
        "hsg": (
            {
                "depth_rule": hsg_depth_rule,
                "segment": HSG_DEPTH_RULES[hsg_depth_rule].segment,
            }
            if hsg_depth_rule is not None
            else None
        ),
        "set": (
            {
                "project": project.get("name"),
                "name": pin_set.get("name"),
                "closed_at": pin_set.get("closed_at"),
            }
            if set_identity
            else None
        ),
        "sources": sources_member(sources) if sources else None,
        "generated_at": generated_at,
    }


def write_instance_info(frontend_data: Path, info: dict[str, Any]) -> Path:
    """Write ``info`` to ``<frontend_data>/instance.json`` atomically; return it."""
    frontend_data.mkdir(parents=True, exist_ok=True)
    path = frontend_data / INSTANCE_INFO_NAME
    partial = path.with_name(f".{path.name}.tmp")
    partial.write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(partial, path)
    return path


def read_set_record(path: Path) -> dict[str, Any] | None:
    """Return the record ``bootstrap_set.json`` of a run from a set, else None."""
    if not path.is_file():
        return None
    record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return record


def _project_area(record: dict[str, Any]) -> Path:
    """Return the checked area file of the project a set record names."""
    from utils.archiwista_project import project_area, read_project

    return project_area(read_project(Path(record["project"]["path"])))


def _dem_resolution_m(nmt_dir: Path) -> float | None:
    """Return the cell size of the saved DEM mosaic of ``nmt_dir``, None without one."""
    import rasterio

    for name in ("dem_mosaic.tif", "dem_mosaic.vrt"):
        dem = nmt_dir / name
        if dem.is_file():
            with rasterio.open(dem) as src:
                return round(float(src.res[0]), 3)
    return None


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    from scripts.bootstrap import DEFAULT_DATA_DIR, FRONTEND_DIR

    parser = argparse.ArgumentParser(
        description="Write frontend/data/instance.json for an existing instance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--area-name", help="Name of the area shown to users (Polish)")
    parser.add_argument(
        "--boundary-file",
        type=Path,
        help="Boundary of the area (default: the area of the set's project)",
    )
    parser.add_argument("--boundary-layer", help="Layer of a multi-layer boundary")
    parser.add_argument(
        "--resolution",
        choices=["1m", "5m"],
        help="NMT resolution (default: from the set, else the saved DEM mosaic)",
    )
    parser.add_argument(
        "--hsg-depth-rule",
        choices=list(HSG_DEPTH_RULES),
        help="Rule of the soil groups of the data, soil.hsg_depth_rule of their run "
        "(default: from the set record, else unknown)",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Output directory of the bootstrap: bootstrap_set.json, nmt/ "
        f"(default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--frontend-data",
        type=Path,
        default=FRONTEND_DIR / "data",
        help=f"Directory nginx serves as /data (default: {FRONTEND_DIR / 'data'})",
    )
    sources = parser.add_argument_group(
        "sources",
        "The provider files the data were made from, for the line G of GUGiK's data "
        "(Nogat DEV §20); a product not given keeps its entry of the file written "
        "before",
    )
    sources.add_argument(
        "--nmt",
        type=Path,
        nargs="+",
        default=[],
        help="NMT sheets, or directories of the store that hold them",
    )
    sources.add_argument(
        "--nmt-sheets",
        type=Path,
        help="File of the sheet codes used, one per line: only these sheets of --nmt",
    )
    sources.add_argument(
        "--bdot10k",
        type=Path,
        nargs="+",
        default=[],
        help="BDOT10k packages (.gpkg), or directories that hold them",
    )
    sources.add_argument(
        "--soilgrids",
        type=Path,
        nargs="+",
        default=[],
        help="The SoilGrids (HSG) rasters of the soil groups",
    )
    return parser


def _sheet_codes(path: Path | None) -> set[str] | None:
    """Return the sheet codes of a file, one per line; None without a file."""
    if path is None:
        return None
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def main(argv: list[str] | None = None) -> None:
    """Write instance.json from the data of an existing instance."""
    from core.errors import HydrografError
    from scripts.bootstrap import SET_RECORD_NAME

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    args = build_parser().parse_args(argv)
    record = read_set_record(args.data_dir / SET_RECORD_NAME)
    boundary = args.boundary_file
    if boundary is None and record is not None:
        try:
            boundary = _project_area(record)
        except HydrografError as error:
            sys.exit(f"Area of the set's project: {error.text()}; pass --boundary-file")
    nmt_resolution = resolution_m(args.resolution) if args.resolution else None
    if nmt_resolution is None and record is None:
        nmt_resolution = _dem_resolution_m(args.data_dir / "nmt")
    run = data_sources(
        {
            NMT: data_files(args.nmt, names=_sheet_codes(args.nmt_sheets)),
            BDOT10K: data_files(args.bdot10k, suffix=".gpkg"),
            SOILGRIDS: data_files(args.soilgrids),
        }
    )
    info = build_instance_info(
        generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        area_name=args.area_name,
        boundary=boundary,
        boundary_layer=args.boundary_layer if args.boundary_file else None,
        set_identity=record,
        nmt_resolution_m=nmt_resolution,
        hsg_depth_rule=args.hsg_depth_rule,
        sources=merged_sources(read_sources(args.frontend_data), run),
    )
    path = write_instance_info(args.frontend_data, info)
    logger.info("Written %s: %s", path, json.dumps(info["area"], ensure_ascii=False))
    logger.info("Sources: %s", json.dumps(info["sources"], ensure_ascii=False))


if __name__ == "__main__":
    main()
