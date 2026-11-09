r"""Write ``instance.json``: what the data of this Hydrograf instance cover.

The welcome dialog and the guide of the front end read ``/data/instance.json`` to name
the area of the instance; without the file they show a neutral text. The bootstrap
writes it at the end of a run; this script (re)writes it for an instance whose data
already exist, without a bootstrap run::

    python -m scripts.write_instance_info --area-name "zlewnia Kaczawy do Legnicy" \
        --boundary-file /data/boundary/zlewnia_kaczawy_790km2_przyciecie.gpkg

The file (schema ``hydrograf-instance/1``) is public: it holds no server paths, only
the boundary's file name.

- ``area.name``: ``--area-name``, else the name of the Archiwista project of the set
  (``bootstrap_set.json``), else the stem of the boundary file, else null;
- ``area.area_km2``: the area of the boundary (EPSG:2180), one decimal; the boundary is
  ``--boundary-file``, else the area file of the set's project; null without either;
- ``counties``: the TERYT codes of the BDOT10k packages of the set, null when unknown;
- ``nmt``: the NMT resolution (``--resolution``, else the set's NMT segment, else the
  cell of the saved DEM mosaic) and the set's segment;
- ``set``: project, name and ``closed_at`` of the set, null for a run without a set;
- ``generated_at``: when the file was written (UTC).
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

INSTANCE_INFO_NAME = "instance.json"
INSTANCE_INFO_SCHEMA = "hydrograf-instance/1"

# The NMT segments of the Kartograf store end in ``_<resolution>m_<datum>``
_SEGMENT_RESOLUTION = re.compile(r"_(\d+(?:\.\d+)?)m_")


def resolution_m(value: str) -> float:
    """Return the metres of a resolution written as the bootstrap's ``5m``."""
    return float(value.removesuffix("m"))


def _segment_resolution_m(segment: str | None) -> float | None:
    match = _SEGMENT_RESOLUTION.search(segment or "")
    return float(match.group(1)) if match else None


def build_instance_info(
    *,
    generated_at: str,
    area_name: str | None = None,
    boundary: Path | None = None,
    boundary_layer: str | None = None,
    set_identity: dict[str, Any] | None = None,
    nmt_resolution_m: float | None = None,
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
    return {
        "schema": INSTANCE_INFO_SCHEMA,
        "area": {
            "name": name,
            "area_km2": area_km2,
            "boundary": boundary.name if boundary else None,
        },
        "counties": sorted(counties) if counties is not None else None,
        "nmt": {"resolution_m": nmt_resolution_m, "segment": segment},
        "set": (
            {
                "project": project.get("name"),
                "name": pin_set.get("name"),
                "closed_at": pin_set.get("closed_at"),
            }
            if set_identity
            else None
        ),
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
    return parser


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
    info = build_instance_info(
        generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        area_name=args.area_name,
        boundary=boundary,
        boundary_layer=args.boundary_layer if args.boundary_file else None,
        set_identity=record,
        nmt_resolution_m=nmt_resolution,
    )
    path = write_instance_info(args.frontend_data, info)
    logger.info("Written %s: %s", path, json.dumps(info["area"], ensure_ascii=False))


if __name__ == "__main__":
    main()
