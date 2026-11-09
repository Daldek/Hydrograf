"""
One-command bootstrap for the Hydrograf hydrological hub.

Downloads NMT, processes DEM, imports land cover, fetches precipitation data,
generates overlays, and starts the full stack — all from a single command.

Usage:
    cd backend

    # By bounding box (WGS84)
    python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4"

    # By sheet codes
    python -m scripts.bootstrap --sheets N-34-131-C-c-2-1 N-34-131-C-c-2-2

    # From a closed set of an Archiwista project (ADR-067): nothing is downloaded
    python -m scripts.bootstrap --project /srv/projects/kaczawa --set "Hydrograf 2020"

    # Dry run (show plan without executing; with --project: after every check)
    python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4" --dry-run

    # Skip optional steps
    python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4" \
        --skip-precipitation --skip-tiles

With HYDROGRAF_KARTOGRAF_ROOT set (a Kartograf store that Archiwista writes and
Hydrograf only reads) only --project and --set are allowed: --bbox, --sheets and
--boundary-file would download, and are refused (exit 12, forbidden). A refusal
ends with the error document hydrograf-error/1 as the last line of standard error
and the exit code of the Nogat registry.
"""

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

from shapely.geometry import box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from core._errors import BY_CODE
from core.active_run import active_run_raster
from core.errors import HydrografError, InvalidRequestError
from scripts.write_instance_info import (
    build_instance_info,
    resolution_m,
    write_instance_info,
)
from utils.kartograf_set import SHEET_SCALE, SetInputs, nmt_segment, set_inputs
from utils.kartograf_store import (
    HSG_DEPTH,
    SHEET_SYSTEM,
    describe_error,
    download_bdot10k,
    metadata_cache_path,
    open_metadata_cache,
    private_store_dir,
    refuse_shared_store,
    store_dir,
)
from utils.nmt_coverage import area_2180, check_nmt_coverage, sheet_frame

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Directories — derive BACKEND_DIR from __file__ so it works both
# in dev (Hydrograf/backend/scripts/bootstrap.py) and Docker (/app/scripts/bootstrap.py)
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_CACHE_DIR = PROJECT_ROOT / "cache"
# <output>/bootstrap_set.json: the set of an Archiwista project that a run took its
# Kartograf data from (ADR-067), written when the run starts and completed when it
# ends. A run without a set removes it, so no data is credited to a set it did not
# come from.
SET_RECORD_NAME = "bootstrap_set.json"
SET_RECORD_SCHEMA = "hydrograf-bootstrap-set/1"

# The map layer of the soil groups (frontend/data/soil_hsg.geojson) simplifies the
# polygons by 5 m and writes 6 decimal digits (about 0.1 m): the wetlands (ADR-078)
# bring the outlines of BDOT10k into soil_hsg, which made the layer of h07 14.7 MB
# instead of 0.3 MB. The table keeps the exact polygons.
HSG_MAP_TOLERANCE_M = 5.0

# Status symbols
SYM_DONE = "\u2713"  # checkmark
SYM_ACTIVE = "\u25cf"  # bullet
SYM_FAIL = "\u2717"  # cross
SYM_SKIP = "\u2013"  # en-dash

# Pipeline step names
STEP_NAMES = [
    "Infrastruktura",  # 1
    "Pobieranie NMT",  # 2
    "Przetwarzanie NMT",  # 3
    "Pokrycie terenu",  # 4
    "Dane glebowe HSG",  # 5
    "Opady IMGW",  # 6
    "Depresje",  # 7
    "Kafelki MVT",  # 8
    "Overlay PNG",  # 9
    "Uruchom serwer",  # 10
]

TOTAL_STEPS = len(STEP_NAMES)


class StepTracker:
    """Track pipeline step statuses and timings."""

    def __init__(self, total: int, skipped: set[int]):
        self.total = total
        self.statuses: list[str | None] = [None] * total  # None=pending
        self.details: list[str] = [""] * total
        self.timings: list[float] = [0.0] * total
        self.errors: list[str] = []
        for s in skipped:
            self.statuses[s - 1] = "skip"

    def start(self, step: int) -> float:
        """Mark the step as running and return its start time."""
        self.statuses[step - 1] = "active"
        self._print_status()
        return time.time()

    def done(self, step: int, t0: float, detail: str = ""):
        """Mark the step as done, with an optional detail."""
        self.timings[step - 1] = time.time() - t0
        self.statuses[step - 1] = "done"
        self.details[step - 1] = detail
        self._print_status()

    def fail(self, step: int, t0: float, error: str):
        """Mark the step as failed and record the error."""
        self.timings[step - 1] = time.time() - t0
        self.statuses[step - 1] = "fail"
        self.details[step - 1] = error
        self.errors.append(f"[{step}/{self.total}] {STEP_NAMES[step - 1]}: {error}")
        self._print_status()

    def is_skipped(self, step: int) -> bool:
        """Return whether the step was skipped."""
        return self.statuses[step - 1] == "skip"

    def _print_status(self):
        lines = []
        for i in range(self.total):
            num = f"[{i + 1}/{self.total}]"
            name = STEP_NAMES[i]
            status = self.statuses[i]
            detail = self.details[i]
            elapsed = self.timings[i]

            if status == "done":
                sym = SYM_DONE
                suffix = f"{detail:<40s} {elapsed:>6.1f}s"
            elif status == "active":
                sym = SYM_ACTIVE
                suffix = "..."
            elif status == "fail":
                sym = SYM_FAIL
                suffix = detail
            elif status == "skip":
                sym = SYM_SKIP
                suffix = "pominiety"
            else:
                sym = " "
                suffix = ""

            lines.append(f"{num} {sym} {name:<22s} {suffix}")

        print("\n".join(lines), flush=True)
        print()


def parse_bbox(bbox_str: str) -> tuple[float, float, float, float]:
    """Parse 'min_lon,min_lat,max_lon,max_lat' string."""
    parts = [float(x.strip()) for x in bbox_str.split(",")]
    if len(parts) != 4:
        raise ValueError(
            "bbox wymaga 4 wartosci "
            f"(min_lon,min_lat,max_lon,max_lat), "
            f"otrzymano {len(parts)}"
        )
    min_lon, min_lat, max_lon, max_lat = parts
    if not min_lon < max_lon:
        raise ValueError(f"bbox: min_lon ({min_lon}) musi byc < max_lon ({max_lon})")
    if not min_lat < max_lat:
        raise ValueError(f"bbox: min_lat ({min_lat}) musi byc < max_lat ({max_lat})")
    return tuple(parts)  # type: ignore[return-value]


def sheets_to_bbox(sheets: list[str]) -> tuple[float, float, float, float]:
    """Compute bounding box (WGS84) from list of sheet codes via Kartograf."""
    from kartograf import SheetParser
    from pyproj import Transformer

    t = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)

    all_bboxes = [SheetParser(s).get_bbox() for s in sheets]
    min_x = min(b.min_x for b in all_bboxes)
    min_y = min(b.min_y for b in all_bboxes)
    max_x = max(b.max_x for b in all_bboxes)
    max_y = max(b.max_y for b in all_bboxes)

    lon_min, lat_min = t.transform(min_x, min_y)
    lon_max, lat_max = t.transform(max_x, max_y)
    return (lon_min, lat_min, lon_max, lat_max)


def sheets_to_bbox_2180(
    sheets: list[str],
) -> tuple[float, float, float, float]:
    """Compute bounding box (EPSG:2180) from list of sheet codes."""
    from kartograf import SheetParser

    all_bboxes = [SheetParser(s).get_bbox(crs="EPSG:2180") for s in sheets]
    return (
        min(b.min_x for b in all_bboxes),
        min(b.min_y for b in all_bboxes),
        max(b.max_x for b in all_bboxes),
        max(b.max_y for b in all_bboxes),
    )


def resolve_sheets(
    bbox: tuple[float, float, float, float] | None,
    sheets: list[str] | None,
    scale: str,
) -> tuple[list[str], tuple[float, float, float, float]]:
    """Resolve sheets and bbox from CLI arguments."""
    from kartograf import BBox, find_sheets_for_bbox

    if sheets:
        resolved_bbox = sheets_to_bbox(sheets)
        return sheets, resolved_bbox

    assert bbox is not None
    min_lon, min_lat, max_lon, max_lat = bbox
    kartograf_bbox = BBox(
        min_x=min_lon,
        min_y=min_lat,
        max_x=max_lon,
        max_y=max_lat,
        crs="EPSG:4326",
    )
    resolved_sheets = find_sheets_for_bbox(
        kartograf_bbox, scale, sheet_system=SHEET_SYSTEM
    )
    return resolved_sheets, bbox


def resolve_boundary_file(
    boundary_file: Path,
    scale: str,
    layer: str | None = None,
) -> tuple[list[str], tuple[float, float, float, float]]:
    """Load boundary file, resolve NMT sheets and bbox."""
    from kartograf import BBox, find_sheets_for_bbox, find_sheets_for_geometry

    from core.boundary import (
        boundary_to_bbox_2180,
        boundary_to_bbox_wgs84,
        load_boundary,
    )

    geom = load_boundary(boundary_file, layer=layer)
    bbox = boundary_to_bbox_wgs84(geom)

    # Kartograf's find_sheets_for_geometry only supports .shp/.gpkg.
    # For other formats (GeoJSON, etc.) fall back to bbox-based lookup.
    ext = boundary_file.suffix.lower()
    if ext in (".shp", ".gpkg"):
        sheets = find_sheets_for_geometry(
            boundary_file, target_scale=scale, layer=layer, sheet_system=SHEET_SYSTEM
        )
    else:
        bbox_2180 = boundary_to_bbox_2180(geom)
        kartograf_bbox = BBox(
            min_x=bbox_2180[0],
            min_y=bbox_2180[1],
            max_x=bbox_2180[2],
            max_y=bbox_2180[3],
            crs="EPSG:2180",
        )
        sheets = find_sheets_for_bbox(kartograf_bbox, scale, sheet_system=SHEET_SYSTEM)

    return sheets, bbox


def print_header(
    bbox: tuple[float, float, float, float],
    sheets: list[str],
    port: int,
    boundary_file: Path | None = None,
    inputs: SetInputs | None = None,
):
    """Print bootstrap header with configuration summary."""
    min_lon, min_lat, max_lon, max_lat = bbox
    sep = "=" * 58
    area = (
        f"{min_lon:.3f}\u00b0E\u2013{max_lon:.3f}\u00b0E, "
        f"{min_lat:.3f}\u00b0N\u2013{max_lat:.3f}\u00b0N"
    )
    source = ""
    if boundary_file is not None:
        source = f"  Plik granicy: {boundary_file}\n"
    if inputs is not None:
        source = (
            f"  Projekt: {inputs.project.name} ({inputs.project.directory})\n"
            f"  Zestaw: {inputs.pin_set.name}\n"
        )
    header = (
        f"{sep}\n"
        f"  Hydrograf Bootstrap\n"
        f"{source}"
        f"  Obszar: {area}\n"
        f"  Arkusze: {len(sheets)}\n"
        f"  Port: {port}\n"
        f"{sep}\n"
    )
    print(header)


def update_env_file(key: str, value: str):
    """Add or update a key in the root .env file."""
    env_path = PROJECT_ROOT / ".env"
    lines: list[str] = []
    found = False

    if env_path.exists():
        lines = env_path.read_text().splitlines()
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                found = True
                break

    if not found:
        lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n")


def wait_for_health(url: str, timeout: int = 30, interval: float = 2.0) -> bool:
    """Poll a health endpoint until it responds 200."""
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(url, timeout=5)
            if resp.status == 200:
                return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------


def step_infra() -> str:
    """Step 1: Infrastructure — .venv, Docker DB, Alembic."""
    details = []

    # 1a. Check/create .venv from the lock (DEV-6.2, DEV-6.3)
    venv_python = BACKEND_DIR / ".venv" / "bin" / "python"

    if not venv_python.exists():
        logger.info("Tworzenie .venv...")
        subprocess.run(["uv", "sync", "--locked"], check=True, cwd=str(BACKEND_DIR))
        details.append(".venv utworzony")
    else:
        details.append(".venv OK")

    # 1b. Docker DB
    result = subprocess.run(
        ["docker", "compose", "ps", "--status", "running", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    running = result.stdout.strip()
    running_containers = running.split("\n") if running else []

    if "hydro_db" not in running_containers:
        logger.info("Uruchamianie bazy danych...")
        subprocess.run(
            ["docker", "compose", "up", "-d", "db"],
            check=True,
            cwd=str(PROJECT_ROOT),
        )
        # Wait for PostgreSQL to accept connections
        logger.info("Czekanie na gotowość PostgreSQL...")
        deadline = time.time() + 60
        while time.time() < deadline:
            ready = subprocess.run(
                [
                    "docker",
                    "compose",
                    "exec",
                    "db",
                    "pg_isready",
                    "-U",
                    "hydro_user",
                ],
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
            )
            if ready.returncode == 0:
                break
            time.sleep(2)
        else:
            raise RuntimeError("Baza danych nie uruchomila sie w 60s")
        details.append("DB uruchomiona")
    else:
        details.append("DB OK")

    # 1c. Alembic migrations
    logger.info("Uruchamianie migracji Alembic...")
    subprocess.run(
        [str(venv_python), "-m", "alembic", "upgrade", "head"],
        check=True,
        cwd=str(BACKEND_DIR),
    )
    details.append("migracje OK")

    # 1d. CDN integrity hashes
    cdn_script = PROJECT_ROOT / "scripts" / "verify_cdn_hashes.sh"
    if cdn_script.exists():
        logger.info("Weryfikacja hashów SRI zasobów CDN...")
        result = subprocess.run(
            ["bash", str(cdn_script)],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
        )
        if result.returncode != 0:
            logger.warning(
                "Niezgodność hashów CDN! Napraw: ./scripts/verify_cdn_hashes.sh --fix"
            )
            details.append("CDN HASH MISMATCH")
        else:
            details.append("CDN OK")

    return ", ".join(details)


def step_download_nmt(
    sheets: list[str],
    cache_dir: Path,
    resolution: str = "5m",
) -> tuple[list[Path], str]:
    """Step 2: Download NMT sheets via Kartograf.

    The sheets go into the private Kartograf store of the pipeline,
    ``<cache_dir>/kartograf`` (ADR-061): the standard path of a sheet is
    ``<store>/nmt/pl_1992_<res>_evrf2007/<hierarchy>/<sheet>.asc`` (a hard link to the
    newest flight) and the versions are below ``versions/``. The metadata cache is
    ``cache_dir/kartograf_meta.db``.
    Raises ForbiddenError while HYDROGRAF_KARTOGRAF_ROOT names a shared store, which
    Hydrograf only reads (ADR-067), and NmtDownloadError on any transport failure
    (full sheet list).
    """
    sys.path.insert(0, str(BACKEND_DIR))
    from scripts.download_dem import download_sheets

    if not sheets:
        raise ValueError("Pusta lista arkuszy NMT — nic do pobrania")

    report = download_sheets(
        sheets,
        private_store_dir(cache_dir),
        metadata_cache_path(cache_dir),
        skip_existing=True,
        resolution=resolution,
    )

    detail = f"{len(report.paths)}/{len(sheets)} arkuszy"
    if report.no_coverage:
        detail += f", {len(report.no_coverage)} bez pokrycia"
    if report.unverified:
        detail += f", {len(report.unverified)} niezweryfikowanych"

    return report.paths, detail


def step_set_nmt(inputs: SetInputs) -> tuple[list[Path], str]:
    """Step 2 from a set: the pinned sheets, by their version paths (ADR-067).

    Nothing is downloaded: every sheet of the set's NMT segment was checked with its
    SHA-256 before step 1, and a version path never changes.
    """
    files = list(inputs.sheets.values())
    return files, f"{len(files)}/{len(files)} arkuszy z zestawu"


def _merged_hydro(packages: list[Path], output_path: Path) -> Path | None:
    """Merge the hydro layers of the BDOT10k packages, or reuse their earlier merge.

    The merge is kept with the list of its packages (path, size, mtime) beside it
    and reused while that list is the same: a new merge is a new file, and a run by
    PGW units is resumed only with the very files it began with.
    """
    from scripts.download_landcover import merge_hydro_gpkgs

    sources = []
    for package in sorted(path.resolve() for path in packages):
        stat = package.stat()
        sources.append(
            {"path": str(package), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        )
    record = output_path.with_name(f"{output_path.stem}.sources.json")
    if output_path.is_file() and record.is_file():
        try:
            if json.loads(record.read_text(encoding="utf-8")) == sources:
                logger.info("Reusing %s: the same BDOT10k packages", output_path)
                return output_path
        except ValueError:
            pass
    record.unlink(missing_ok=True)
    merged = merge_hydro_gpkgs(packages, output_path)
    if merged == output_path:
        record.write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")
    return merged


def step_process_dem(
    downloaded_files: list[Path],
    output_dir: Path,
    cache_dir: Path,
    waterbody_mode: str = "none",
    waterbody_min_area_m2: float | None = None,
    sewer_config: dict[str, Any] | None = None,
    bdot10k: dict[str, Path] | None = None,
    stream_burning: str = "all",
    units_path: Path | None = None,
    units_area: tuple[Path, str | None] | None = None,
    units_scratch_dir: Path | None = None,
    units_catchments: tuple[Path, str | None, str] | None = None,
    units_resume: bool = True,
    resolution: str = "5m",
    fill_enclosed_nodata: bool = False,
) -> tuple[dict[str, Any], str, tuple[float, float, float, float]]:
    """Step 3: Process DEM — mosaic VRT + stream burning + hydrological analysis.

    ``bdot10k`` (TERYT to package) are the BDOT10k packages of a set (ADR-067); without
    it the packages of the mosaic's counties are downloaded. ``stream_burning``
    (``dem.stream_burning`` of the configuration) selects the burned streams and
    ``fill_enclosed_nodata`` (``dem.fill_enclosed_nodata``) interpolates the nodata
    that the mosaic encloses before the fill. With ``units_path`` (the PGW
    GeoPackage) the mosaic is processed by PGW units
    (ADR-071), the owners clipped to ``units_area``, the file and the layer of the
    analysis area, and grouped from ``units_catchments`` (file, layer, key field)
    when given; ``units_scratch_dir`` holds the scratch of the run and
    ``units_resume`` resumes a stopped run of the same inputs. The
    mosaic has the cells of the ``resolution`` sheets: finer sheets are averaged
    onto their grid first (``utils.raster_utils.align_to_cellsize``).
    """
    sys.path.insert(0, str(BACKEND_DIR))
    from core.constants import PIPELINE_THRESHOLDS_M2
    from scripts.process_dem import process_dem
    from utils.raster_utils import align_to_cellsize, create_vrt_mosaic, normalize_crs

    nmt_dir = output_dir / "nmt"
    nmt_dir.mkdir(parents=True, exist_ok=True)

    # Exactly the sheets returned by step 2 (standard paths, or the version paths
    # of a set) — never a directory scan: the store keeps every version of a sheet
    # under versions/ (and full_sheet/ links), and other resolutions may sit in it.
    nmt_files = sorted(set(downloaded_files))

    # Reproject PUWG 2000 files to EPSG:2180 before mosaicking
    normalized_files = normalize_crs(nmt_files, nmt_dir / "reprojected")
    # A 5 m set can hold 1 m sheets: the mosaic keeps the cells of the 5 m sheets
    aligned_files = align_to_cellsize(
        normalized_files, nmt_dir / "aligned", float(resolution.removesuffix("m"))
    )

    mosaic_path = create_vrt_mosaic(
        input_files=aligned_files,
        output_vrt=nmt_dir / "dem_mosaic.vrt",
        target_crs="EPSG:2180",
    )

    # Download & merge hydro BDOT10k for stream burning.
    # Use the ACTUAL mosaic extent (not the user bbox) for the counties,
    # because NMT sheets extend beyond the bbox and the DEM analysis covers
    # the full mosaic area — BDOT must match.
    burn_path = None
    try:
        import rasterio
        from kartograf import BBox

        with rasterio.open(mosaic_path) as src:
            mosaic_bounds = src.bounds  # (left, bottom, right, top) in EPSG:2180
        mosaic_bbox_2180 = (
            mosaic_bounds.left,
            mosaic_bounds.bottom,
            mosaic_bounds.right,
            mosaic_bounds.top,
        )
        logger.info(
            f"Mosaic extent for BDOT10k: "
            f"({mosaic_bbox_2180[0]:.0f}, {mosaic_bbox_2180[1]:.0f}, "
            f"{mosaic_bbox_2180[2]:.0f}, {mosaic_bbox_2180[3]:.0f})"
        )
        bdot_paths = (
            bdot10k
            if bdot10k is not None
            else download_bdot10k(
                cache_dir, bbox=BBox(*mosaic_bbox_2180, crs="EPSG:2180")
            )
        )

        if bdot_paths:
            hydro_out_dir = output_dir / "hydro"
            hydro_out_dir.mkdir(parents=True, exist_ok=True)
            burn_path = _merged_hydro(
                list(bdot_paths.values()), hydro_out_dir / "hydro_merged.gpkg"
            )
    except Exception as e:
        logger.warning(
            f"Hydro download/merge failed, proceeding without burning: "
            f"{describe_error(e)}"
        )
        burn_path = None

    # Export BDOT10k to GeoJSON for frontend
    if burn_path:
        try:
            frontend_data = FRONTEND_DIR / "data"
            frontend_data.mkdir(parents=True, exist_ok=True)
            bdot_result = export_bdot_geojson(
                burn_path, frontend_data, clip_bbox_2180=mosaic_bbox_2180
            )
            logger.info(f"BDOT10k GeoJSON exported: {bdot_result}")
        except Exception as e:
            logger.warning(f"BDOT10k GeoJSON export failed: {e}")

    stats = process_dem(
        input_path=mosaic_path,
        clear_existing=True,
        save_intermediates=True,
        output_dir=nmt_dir,
        thresholds=list(PIPELINE_THRESHOLDS_M2),
        burn_streams_path=burn_path,
        stream_burning=stream_burning,
        # hydro_resolution_m not needed when NMT downloaded at 5m resolution
        waterbody_mode=waterbody_mode,
        waterbody_min_area_m2=waterbody_min_area_m2,
        sewer_config=sewer_config,
        units_path=units_path,
        units_area_path=units_area[0] if units_area else None,
        units_area_layer=units_area[1] if units_area else None,
        units_catchments_path=units_catchments[0] if units_catchments else None,
        units_catchments_layer=units_catchments[1] if units_catchments else None,
        units_catchments_key=units_catchments[2] if units_catchments else "ID_HYD_10",
        units_scratch_dir=units_scratch_dir,
        units_resume=units_resume,
        fill_enclosed_nodata=fill_enclosed_nodata,
    )

    cells = stats.get("valid_cells", 0)
    streams = stats.get("stream_segments", 0)
    burn_info = f", burn={burn_path.name} ({stream_burning})" if burn_path else ""
    if fill_enclosed_nodata:
        burn_info += (
            f", enclosed nodata filled ({stats.get('enclosed_nodata_cells', 0)} cells)"
        )
    detail = f"{cells:,} cells, {streams} segments{burn_info}"

    return stats, detail, mosaic_bbox_2180


def _bdot10k_packages(
    sheets: list[str],
    cache_dir: Path,
    mosaic_bbox_2180: tuple[float, float, float, float] | None,
    bdot10k: dict[str, Path] | None,
) -> dict[str, Path]:
    """Return the BDOT10k packages of the area by TERYT (steps 4 and 5).

    ``bdot10k`` (TERYT to package) are the packages of a set (ADR-067), used without a
    download. Otherwise the counties of the area (the mosaic of step 3, else the
    sheets) come from Kartograf with their packages: a package that step 3 stored is
    local and not requested again, one that failed there is tried again.
    """
    from kartograf import BBox

    if bdot10k is not None:
        return bdot10k
    bbox_2180 = mosaic_bbox_2180 or sheets_to_bbox_2180(sheets)
    return download_bdot10k(cache_dir, bbox=BBox(*bbox_2180, crs="EPSG:2180"))


def step_landcover(
    sheets: list[str],
    output_dir: Path,
    cache_dir: Path,
    mosaic_bbox_2180: tuple[float, float, float, float] | None = None,
    bdot10k: dict[str, Path] | None = None,
) -> str:
    """Step 4: Download and import land cover data (per county).

    The packages are those of ``_bdot10k_packages``: of a set (``bdot10k``), else of
    the counties of the area.
    """
    sys.path.insert(0, str(BACKEND_DIR))
    from scripts.import_landcover import import_landcover

    bdot_paths = _bdot10k_packages(sheets, cache_dir, mosaic_bbox_2180, bdot10k)
    if not bdot_paths:
        logger.warning("Nie znaleziono powiatów dla podanego obszaru")
        return "0 obiektów, 0 powiatów"

    total_features = 0
    for teryt, gpkg in sorted(bdot_paths.items()):
        try:
            lc_stats = import_landcover(
                input_path=gpkg,
                clear_existing=False,
            )
            total_features += lc_stats.get("records_inserted", 0)
        except Exception as e:
            logger.warning(f"Land cover dla TERYT {teryt}: {e}")

    return f"{total_features} obiektów, {len(bdot_paths)} powiatów"


def step_soil_hsg(
    sheets: list[str],
    output_dir: Path,
    cache_dir: Path,
    mosaic_bbox_2180: tuple[float, float, float, float] | None = None,
    hsg_raster: Path | None = None,
    bdot10k: dict[str, Path] | None = None,
) -> str:
    """Step 5: Download HSG data from SoilGrids and import to DB.

    The HSG raster of Poland is a version of the private Kartograf store of the
    pipeline (``cache_dir/kartograf``, ADR-061): Kartograf fetches the SoilGrids clay,
    sand and silt once, computes the raster from them, and a second run uses it again
    without a request. ``hsg_raster`` is the raster of a set (ADR-067), used without a
    request. Processing: clip to project bbox -> warp to EPSG:2180 -> polygonize ->
    the soil under the wetlands (OT_OIMK_A) of the BDOT10k packages of the area
    (``_bdot10k_packages``, the packages of step 4) becomes group D (ADR-078) ->
    import.
    """
    import numpy as np
    import rasterio
    from kartograf import BBox, KartografError, calculate_hsg
    from rasterio.features import shapes
    from rasterio.warp import Resampling, reproject
    from shapely.geometry import MultiPolygon, shape

    sys.path.insert(0, str(BACKEND_DIR))
    from core.database import get_engine

    if hsg_raster is not None:
        logger.info("HSG: the raster of the set, %s", hsg_raster)
        hsg_path = hsg_raster
    else:
        # --- 1. Poland-wide HSG raster (one-time: a local version is used again) ---
        logger.info(
            "HSG: Poland-wide raster from SoilGrids (a local version is reused)..."
        )
        # Poland bbox in EPSG:2180 (PL-1992)
        bbox_poland = BBox(
            min_x=167000,
            min_y=29000,
            max_x=860000,
            max_y=814000,
            crs="EPSG:2180",
        )
        try:
            report = calculate_hsg(
                root=private_store_dir(cache_dir),
                bbox=bbox_poland,
                depth=HSG_DEPTH,
                cache=open_metadata_cache(cache_dir),
            )
        except KartografError as e:
            return f"pominięto (SoilGrids: {describe_error(e)})"

        if not report.files:
            reasons = "; ".join(f"{f.unit}: {f.error}" for f in report.failed)
            return f"pominięto (SoilGrids: {reasons})"
        hsg_path = report.files[0].file.path

    # --- 2. Clip + warp to project bbox in EPSG:2180 ---
    bbox_2180 = mosaic_bbox_2180 or sheets_to_bbox_2180(sheets)
    min_x, min_y, max_x, max_y = bbox_2180

    from rasterio.transform import from_bounds

    # Target: 250m pixels in EPSG:2180
    res_m = 250.0
    width = int((max_x - min_x) / res_m)
    height = int((max_y - min_y) / res_m)
    if width < 1 or height < 1:
        return "pominięto (bbox zbyt mały dla HSG)"

    dst_transform = from_bounds(min_x, min_y, max_x, max_y, width, height)
    dst_crs = rasterio.crs.CRS.from_epsg(2180)

    with rasterio.open(hsg_path) as src:
        dst_data = np.zeros((height, width), dtype=np.uint8)
        reproject(
            source=rasterio.band(src, 1),
            destination=dst_data,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            resampling=Resampling.nearest,
        )

    # --- 3. Nearest-neighbor fill for nodata pixels ---
    hsg_map = {1: "A", 2: "B", 3: "C", 4: "D"}
    valid_mask = np.isin(dst_data, [1, 2, 3, 4])
    if not valid_mask.any():
        return "brak danych HSG w obszarze"
    if not valid_mask.all():
        from scipy.ndimage import distance_transform_edt

        _, nearest_idx = distance_transform_edt(
            ~valid_mask,
            return_indices=True,
        )
        dst_data = np.where(
            valid_mask,
            dst_data,
            dst_data[nearest_idx[0], nearest_idx[1]],
        )
        logger.info(
            f"HSG: filled {(~valid_mask).sum()}/{dst_data.size} missing pixels"
            " with nearest-neighbor"
        )

    # --- 4. Polygonize ---
    soils = []
    for geom_dict, value in shapes(dst_data, transform=dst_transform):
        value = int(value)
        if value not in hsg_map:
            continue
        geom = shape(geom_dict)
        if geom.is_empty:
            continue
        if geom.area < 50:  # Skip micro-fragments (<50 m²)
            continue
        soils.append((geom, hsg_map[value]))

    if not soils:
        return "brak danych HSG"

    # --- 5. The soil under the wetlands is group D (ADR-078) ---
    soils, wetlands_detail = _soils_with_wetlands(
        soils, sheets, cache_dir, mosaic_bbox_2180, bdot10k
    )
    records = []
    for geom, group in soils:
        if geom.geom_type == "Polygon":
            geom = MultiPolygon([geom])
        records.append({"geom": geom.wkt, "hsg_group": group, "area_m2": geom.area})

    # --- 6. Bbox-scoped DB import ---
    engine = get_engine()
    from sqlalchemy import text

    with engine.connect() as conn:
        conn.execute(
            text(
                "DELETE FROM soil_hsg WHERE ST_Intersects(geom, "
                "ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 2180))"
            ),
            {"minx": min_x, "miny": min_y, "maxx": max_x, "maxy": max_y},
        )
        conn.execute(
            text("""
                INSERT INTO soil_hsg (geom, hsg_group, area_m2)
                VALUES (ST_SetSRID(ST_GeomFromText(:geom), 2180), :hsg_group, :area_m2)
            """),
            records,
        )
        conn.commit()

    # --- 7. Export GeoJSON for frontend ---
    try:
        import json

        rows = []
        with engine.connect() as conn2:
            result = conn2.execute(
                text(
                    "SELECT hsg_group, ST_AsGeoJSON(ST_Transform("
                    "ST_SimplifyPreserveTopology(geom, :tolerance), 4326), 6) "
                    "AS geojson, area_m2 FROM soil_hsg"
                ),
                {"tolerance": HSG_MAP_TOLERANCE_M},
            ).fetchall()
            for row in result:
                rows.append(
                    {
                        "type": "Feature",
                        "geometry": json.loads(row.geojson),
                        "properties": {
                            "hsg_group": row.hsg_group,
                            "area_m2": round(row.area_m2, 1),
                        },
                    }
                )

        frontend_data = FRONTEND_DIR / "data"
        frontend_data.mkdir(parents=True, exist_ok=True)
        with open(frontend_data / "soil_hsg.geojson", "w") as f:
            json.dump({"type": "FeatureCollection", "features": rows}, f)
        logger.info(f"HSG GeoJSON exported: {len(rows)} features")
    except Exception as e:
        logger.warning(f"HSG GeoJSON export failed: {e}")

    groups: dict[str, int] = {}
    for r in records:
        g = r["hsg_group"]
        groups[g] = groups.get(g, 0) + 1
    summary = ", ".join(f"{g}: {c}" for g, c in sorted(groups.items()))
    return f"{len(records)} poligonów ({summary}), {wetlands_detail}"


def _soils_with_wetlands(
    soils: list[tuple[Any, str]],
    sheets: list[str],
    cache_dir: Path,
    mosaic_bbox_2180: tuple[float, float, float, float] | None,
    bdot10k: dict[str, Path] | None,
) -> tuple[list[tuple[Any, str]], str]:
    """Make the soil under the wetlands of the area's packages group D (ADR-078).

    The wetlands are those of the BDOT10k packages of step 4 (``_bdot10k_packages``).
    Returns the soil polygons and the detail of step 5: the area made group D, or that
    no package was found, and then the soil groups of the raster stay.
    """
    from scripts.import_landcover import (
        WETLAND_HSG,
        read_wetlands,
        soils_with_wetlands,
    )

    try:
        packages = _bdot10k_packages(sheets, cache_dir, mosaic_bbox_2180, bdot10k)
    except Exception as e:
        logger.warning("HSG: no BDOT10k packages for the wetlands: %s", e)
        packages = {}
    if not packages:
        return soils, "bez mokradeł (brak paczek BDOT10k)"

    wetlands = []
    for teryt, gpkg in sorted(packages.items()):
        try:
            wetlands.extend(read_wetlands(gpkg))
        except Exception as e:
            logger.warning("HSG: the wetlands of TERYT %s not read: %s", teryt, e)
    pieces = soils_with_wetlands(soils, wetlands)
    wet_km2 = (
        sum(geom.area for geom, group in pieces if group == WETLAND_HSG)
        - sum(geom.area for geom, group in soils if group == WETLAND_HSG)
    ) / 1e6
    logger.info(
        "HSG: %d wetlands of %d packages, %.2f km2 of soil made group %s",
        len(wetlands),
        len(packages),
        wet_km2,
        WETLAND_HSG,
    )
    return pieces, f"mokradła {wet_km2:.2f} km² → {WETLAND_HSG}"


def step_precipitation(bbox: tuple[float, float, float, float]) -> str:
    """Step 6: Download IMGW precipitation data."""
    sys.path.insert(0, str(BACKEND_DIR))
    from scripts.preprocess_precipitation import process_grid

    total, success, records = asyncio.run(
        process_grid(bbox, spacing_km=2.0, delay_s=0.5)
    )

    return f"{success}/{total} punktow, {records} rekordow"


def _saved_raster(nmt_dir: Path, name: str) -> Path | None:
    """Return the raster ``dem_mosaic_<name>`` of the network of step 3, or None.

    A run by PGW units (``--units``) leaves its VRT mosaics in the run directory that
    ``active_run.json`` of ``nmt_dir`` points at (``core.active_run``); a run of the
    whole raster saves GeoTIFFs in ``nmt_dir`` and removes that pointer. So the run's
    VRT when the pointer is valid and the run has the raster, else the GeoTIFF.
    """
    mosaic = active_run_raster(nmt_dir, name)
    if mosaic is not None:
        return mosaic
    tif = nmt_dir / f"dem_mosaic_{name}.tif"
    return tif if tif.exists() else None


def step_depressions(output_dir: Path) -> str:
    """Step 7: Generate depressions (blue spots)."""
    sys.path.insert(0, str(BACKEND_DIR))
    from core.database import get_db_session
    from scripts.generate_depressions import (
        compute_depressions,
        generate_overlay,
        insert_depressions,
    )

    nmt_dir = output_dir / "nmt"
    dem_path = _saved_raster(nmt_dir, "01_dem")
    filled_path = _saved_raster(nmt_dir, "02_filled")

    # Fallback: try VRT for DEM
    if dem_path is None:
        dem_path = nmt_dir / "dem_mosaic.vrt"
    if filled_path is None:
        raise FileNotFoundError(
            f"Brak filled DEM: {nmt_dir / 'dem_mosaic_02_filled.tif'}. "
            "Upewnij sie ze krok 3 ukonczyl sie z save_intermediates=True"
        )

    # The scan computes the depressions tile by tile while they are inserted.
    scan = compute_depressions(str(dem_path), str(filled_path))
    with get_db_session() as db:
        n_inserted = insert_depressions(db, scan)

    # Generate overlay PNG
    data_dir = FRONTEND_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    generate_overlay(
        scan.overview,
        str(data_dir / "depressions.png"),
        str(data_dir / "depressions.json"),
    )

    return f"{n_inserted} depresji"


def step_tiles() -> str:
    """Step 8: Generate MVT tiles (requires tippecanoe)."""
    venv_tippecanoe = BACKEND_DIR / ".venv" / "bin" / "tippecanoe"
    if not venv_tippecanoe.exists() and not shutil.which("tippecanoe"):
        logger.warning(
            "tippecanoe nie znalezione — pomijam kafelki MVT. "
            "Zainstaluj: pip install tippecanoe"
        )
        return "brak tippecanoe"

    tiles_dir = FRONTEND_DIR / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.generate_tiles",
            "--output-dir",
            str(tiles_dir),
        ],
        check=True,
        cwd=str(BACKEND_DIR),
    )

    return "OK"


def step_overlays(output_dir: Path) -> str:
    """Step 9: Generate DEM and streams overlay PNG."""
    sys.path.insert(0, str(BACKEND_DIR))
    from scripts.generate_dem_overlay import generate_overlay as dem_overlay
    from scripts.generate_streams_overlay import generate_overlay as streams_overlay

    nmt_dir = output_dir / "nmt"
    data_dir = FRONTEND_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    generated = []

    # DEM overlay (prefer VRT, fallback to TIF or original DEM)
    dem_input = None
    for candidate in [
        nmt_dir / "dem_mosaic.vrt",
        nmt_dir / "dem_mosaic.tif",
        nmt_dir / "dem_mosaic_01_dem.tif",
    ]:
        if candidate.exists():
            dem_input = candidate
            break

    if dem_input is not None:
        dem_overlay(
            input_path=str(dem_input),
            output_png=str(data_dir / "dem.png"),
            output_meta=str(data_dir / "dem.json"),
            source_crs="EPSG:2180",
        )
        generated.append("DEM")

    # DEM tile pyramid (for high-zoom display)
    # Always regenerate — skip guard caused stale tiles after re-bootstrap
    dem_tiles_dir = data_dir / "dem_tiles"
    dem_tiles_meta = data_dir / "dem_tiles.json"
    if dem_input is not None:
        if dem_tiles_dir.exists():
            import shutil as _shutil
            import stat as _stat

            def _force_remove(_func, _path, _exc_info):
                """Handle permission errors in rmtree (rootless Docker UID remap)."""
                os.chmod(_path, _stat.S_IRWXU)
                _func(_path)

            _shutil.rmtree(dem_tiles_dir, onerror=_force_remove)
            logger.info("Removed old DEM tiles for regeneration")
        logger.info("Generating DEM tile pyramid...")
        from scripts.generate_dem_tiles import generate_tiles as gen_dem_tiles

        gen_dem_tiles(
            input_path=str(dem_input),
            output_dir=str(dem_tiles_dir),
            output_meta=str(dem_tiles_meta),
            source_crs="EPSG:2180",
            min_zoom=8,
            max_zoom=16,
            processes=4,
            # The temporary GeoTIFFs grow with the DEM: on disk, next to it.
            work_dir=str(nmt_dir),
        )
        generated.append("DEM tiles")

    # Streams overlay
    stream_order_path = _saved_raster(nmt_dir, "07_stream_order")
    if stream_order_path is not None:
        streams_overlay(
            input_path=str(stream_order_path),
            output_png=str(data_dir / "streams.png"),
            output_meta=str(data_dir / "streams.json"),
            source_crs="EPSG:2180",
        )
        generated.append("streams")

    return ", ".join(generated) if generated else "brak danych"


def export_bdot_geojson(
    hydro_gpkg: Path,
    output_dir: Path,
    clip_bbox_2180: tuple[float, float, float, float] | None = None,
) -> str:
    """Export BDOT10k hydro layers from GPKG to GeoJSON for frontend map.

    If clip_bbox_2180 is provided, clips features to the bbox (EPSG:2180)
    before export — keeps only features intersecting the analysis area.
    """
    import fiona
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import box

    layers = fiona.listlayers(str(hydro_gpkg))
    clip_geom = box(*clip_bbox_2180) if clip_bbox_2180 else None

    # Lakes (polygons) — OT_PTWP_A
    lakes_count = 0
    if "OT_PTWP_A" in layers:
        gdf = gpd.read_file(hydro_gpkg, layer="OT_PTWP_A")
        if not gdf.empty:
            if clip_geom is not None:
                gdf = gdf[gdf.intersects(clip_geom)]
            gdf["source_layer"] = "OT_PTWP_A"
            gdf = gdf.to_crs("EPSG:4326")
            gdf.to_file(output_dir / "bdot_lakes.geojson", driver="GeoJSON")
            lakes_count = len(gdf)

    # Streams (lines) — OT_SWRS_L + OT_SWKN_L + OT_SWRM_L
    stream_layers = ["OT_SWRS_L", "OT_SWKN_L", "OT_SWRM_L"]
    stream_gdfs = []
    for layer_name in stream_layers:
        if layer_name in layers:
            gdf = gpd.read_file(hydro_gpkg, layer=layer_name)
            if not gdf.empty:
                if clip_geom is not None:
                    gdf = gdf[gdf.intersects(clip_geom)]
                gdf["source_layer"] = layer_name
                stream_gdfs.append(gdf)

    streams_count = 0
    if stream_gdfs:
        merged = gpd.GeoDataFrame(pd.concat(stream_gdfs, ignore_index=True))
        merged = merged.to_crs("EPSG:4326")
        merged.to_file(output_dir / "bdot_streams.geojson", driver="GeoJSON")
        streams_count = len(merged)

    return f"{lakes_count} zbiorników, {streams_count} cieków"


def step_serve(port: int) -> str:
    """Step 10: Start full Docker Compose stack."""
    if port != 8080:
        update_env_file("HYDROGRAF_PORT", str(port))

    subprocess.run(
        ["docker", "compose", "up", "-d"],
        check=True,
        cwd=str(PROJECT_ROOT),
    )

    url = f"http://localhost:{port}/health"
    if wait_for_health(url, timeout=30):
        return f"http://localhost:{port}"
    else:
        logger.warning(f"Health check nie odpowiedzial na {url}")
        return f"http://localhost:{port} (brak health)"


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    sheets: list[str],
    bbox: tuple[float, float, float, float],
    output_dir: Path,
    cache_dir: Path,
    port: int,
    skips: set[int],
    waterbody_mode: str = "none",
    waterbody_min_area_m2: float | None = None,
    resolution: str = "5m",
    sewer_config: dict[str, Any] | None = None,
    inputs: SetInputs | None = None,
    stream_burning: str = "all",
    units_path: Path | None = None,
    units_area: tuple[Path, str | None] | None = None,
    units_scratch_dir: Path | None = None,
    units_catchments: tuple[Path, str | None, str] | None = None,
    units_resume: bool = True,
    fill_enclosed_nodata: bool = False,
    coverage_area: BaseGeometry | None = None,
    scale: str = "1:10000",
    allow_uncovered: bool = False,
):
    """Run the full 10-step bootstrap pipeline.

    With ``inputs``, the checked files of a set of an Archiwista project (ADR-067),
    steps 2 to 5 read the pinned files and download nothing. With ``units_path``
    step 3 processes the mosaic by PGW units (``step_process_dem``), and with
    ``fill_enclosed_nodata`` it interpolates the nodata the mosaic encloses first.
    With ``coverage_area`` (EPSG:2180) step 3 first refuses sheets that leave part
    of it, or a hole of their mosaic, uncovered (ADR-076; ``allow_uncovered``: a
    warning); a run from a set is checked before step 1.
    """
    tracker = StepTracker(TOTAL_STEPS, skips)
    downloaded_files: list[Path] = []

    cache_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Infrastructure (CRITICAL)
    if not tracker.is_skipped(1):
        t0 = tracker.start(1)
        try:
            detail = step_infra()
            tracker.done(1, t0, detail)
        except Exception as e:
            tracker.fail(1, t0, str(e))
            logger.error(f"Krok 1 (infrastruktura) nie powiodl sie: {e}")
            return tracker

    # Step 2: Download NMT (CRITICAL)
    if not tracker.is_skipped(2):
        t0 = tracker.start(2)
        try:
            if inputs is not None:
                downloaded_files, detail = step_set_nmt(inputs)
            else:
                downloaded_files, detail = step_download_nmt(
                    sheets, cache_dir, resolution=resolution
                )
            tracker.done(2, t0, detail)
        except Exception as e:
            tracker.fail(2, t0, describe_error(e))
            logger.error(
                f"Krok 2 (pobieranie NMT) nie powiodl sie: {describe_error(e)}"
            )
            return tracker

    # Variable populated by step 3 and forwarded to steps 4-5
    mosaic_bbox = None

    # Step 3: Process DEM (CRITICAL)
    if not tracker.is_skipped(3):
        t0 = tracker.start(3)
        try:
            if coverage_area is not None:
                # The sheets step 2 gave: a sheet without data is not among them
                check_nmt_coverage(
                    coverage_area,
                    [path.stem for path in downloaded_files],
                    scale=scale,
                    resolution=resolution,
                    allow_uncovered=allow_uncovered,
                )
            _, detail, mosaic_bbox = step_process_dem(
                downloaded_files,
                output_dir,
                cache_dir,
                waterbody_mode=waterbody_mode,
                waterbody_min_area_m2=waterbody_min_area_m2,
                sewer_config=sewer_config,
                bdot10k=inputs.counties if inputs is not None else None,
                stream_burning=stream_burning,
                units_path=units_path,
                units_area=units_area,
                units_scratch_dir=units_scratch_dir,
                units_catchments=units_catchments,
                units_resume=units_resume,
                resolution=resolution,
                fill_enclosed_nodata=fill_enclosed_nodata,
            )
            tracker.done(3, t0, detail)
        except Exception as e:
            tracker.fail(3, t0, str(e))
            logger.error(f"Krok 3 (przetwarzanie NMT) nie powiodl sie: {e}")
            return tracker

    # Step 4: Land cover (OPTIONAL)
    if not tracker.is_skipped(4):
        t0 = tracker.start(4)
        try:
            detail = step_landcover(
                sheets,
                output_dir,
                cache_dir,
                mosaic_bbox_2180=mosaic_bbox,
                bdot10k=inputs.counties if inputs is not None else None,
            )
            tracker.done(4, t0, detail)
        except Exception as e:
            tracker.fail(4, t0, describe_error(e))
            logger.warning(f"Krok 4 (pokrycie terenu): {describe_error(e)}")

    # Step 5: HSG (OPTIONAL)
    if not tracker.is_skipped(5):
        t0 = tracker.start(5)
        try:
            detail = step_soil_hsg(
                sheets,
                output_dir,
                cache_dir,
                mosaic_bbox_2180=mosaic_bbox,
                hsg_raster=inputs.hsg if inputs is not None else None,
                bdot10k=inputs.counties if inputs is not None else None,
            )
            tracker.done(5, t0, detail)
        except Exception as e:
            tracker.fail(5, t0, str(e))
            logger.warning(f"Krok 5 (HSG): {e}")

    # Step 6: Precipitation (OPTIONAL)
    if not tracker.is_skipped(6):
        t0 = tracker.start(6)
        try:
            detail = step_precipitation(bbox)
            tracker.done(6, t0, detail)
        except Exception as e:
            tracker.fail(6, t0, str(e))
            logger.warning(f"Krok 6 (opady IMGW): {e}")

    # Step 7: Depressions (OPTIONAL)
    if not tracker.is_skipped(7):
        t0 = tracker.start(7)
        try:
            detail = step_depressions(output_dir)
            tracker.done(7, t0, detail)
        except Exception as e:
            tracker.fail(7, t0, str(e))
            logger.warning(f"Krok 7 (depresje): {e}")

    # Step 8: MVT tiles (OPTIONAL)
    if not tracker.is_skipped(8):
        t0 = tracker.start(8)
        try:
            detail = step_tiles()
            tracker.done(8, t0, detail)
        except Exception as e:
            tracker.fail(8, t0, str(e))
            logger.warning(f"Krok 8 (kafelki MVT): {e}")

    # Step 9: Overlay PNG (OPTIONAL)
    if not tracker.is_skipped(9):
        t0 = tracker.start(9)
        try:
            detail = step_overlays(output_dir)
            tracker.done(9, t0, detail)
        except Exception as e:
            tracker.fail(9, t0, str(e))
            logger.warning(f"Krok 9 (overlay PNG): {e}")

    # Step 10: Start server (OPTIONAL)
    if not tracker.is_skipped(10):
        t0 = tracker.start(10)
        try:
            detail = step_serve(port)
            tracker.done(10, t0, detail)
        except Exception as e:
            tracker.fail(10, t0, str(e))
            logger.warning(f"Krok 10 (serwer): {e}")

    return tracker


def dry_run(
    sheets: list[str],
    bbox: tuple[float, float, float, float],
    output_dir: Path,
    cache_dir: Path,
    port: int,
    skips: set[int],
    inputs: SetInputs | None = None,
):
    """Show what would be done without executing (with a set: after every check)."""
    min_lon, min_lat, max_lon, max_lat = bbox
    print("\nDRY RUN — plan wykonania:\n")
    print(f"  Output dir: {output_dir}")
    print(f"  Cache dir:  {cache_dir}\n")

    tippecanoe_status = "(dostepne)" if shutil.which("tippecanoe") else "(NIEDOSTEPNE)"
    steps = [
        "Infrastruktura: .venv, docker compose up -d db, alembic upgrade head",
        f"Pobieranie NMT: {len(sheets)} arkuszy do {store_dir(cache_dir) / 'nmt'}",
        "Przetwarzanie NMT: mozaika VRT, "
        "stream_network, stream_catchments (ZAWSZE od zera)",
        f"Pokrycie terenu: BDOT10k per powiat (z {len(sheets)} arkuszy), "
        f"magazyn {store_dir(cache_dir)}",
        "Dane glebowe HSG: SoilGrids przez Kartograf (calculate_hsg), "
        "pod mokradłami BDOT10k grupa D",
        f"Opady IMGW: grid 2km w bbox "
        f"{min_lon:.3f},{min_lat:.3f},"
        f"{max_lon:.3f},{max_lat:.3f}",
        "Depresje: blue spots z filled DEM",
        f"Kafelki MVT: tippecanoe {tippecanoe_status}",
        f"Overlay PNG: DEM + streams do {FRONTEND_DIR / 'data'}",
        f"Uruchom serwer: docker compose up -d, port {port}",
    ]
    if inputs is not None:
        print_set(inputs)
        steps[1:5] = _set_steps(inputs)

    for i, desc in enumerate(steps, 1):
        skip = SYM_SKIP if i in skips else " "
        print(f"  [{i}/{TOTAL_STEPS}] {skip} {desc}")

    print()


def print_set(inputs: SetInputs) -> None:
    """Print what a set gives the run, below the header (the human-readable output)."""
    pin_set = inputs.pin_set
    state = (
        f"zamknięty {pin_set.closed_at} przez {pin_set.closed_by}"
        if pin_set.closed_at is not None
        else "zamknięty (bez daty zamknięcia: zestaw sprzed stanu zestawów)"
    )
    source = "z pliku projektu" if pin_set.pins_sha256 else "obliczony"
    area = inputs.project.area
    print(f"  Stan:        {state}")
    print(f"  Obszar:      {inputs.area} (SHA-256 {area.sha256 if area else '-'})")
    print(f"  pins_sha256: {inputs.digest} ({source})")
    print(f"  Magazyn:     {inputs.root}")
    print(
        f"  Piny:        {len(pin_set.pins)}; piny Kartografa sprawdzone (SHA-256), "
        f"nieużywane: {len(inputs.unused)}; innych producentów: {inputs.foreign}"
    )
    print()


def _set_steps(inputs: SetInputs) -> list[str]:
    """Return the dry-run lines of steps 2 to 5 of a run from a set."""
    counties = ", ".join(inputs.counties) or "-"
    which = "powiaty mozaiki (PRG)" if inputs.counties_checked else "paczki zestawu"
    hsg = inputs.hsg.relative_to(inputs.root).as_posix() if inputs.hsg else "-"
    return [
        f"NMT z zestawu, {nmt_segment(inputs.resolution)}: {len(inputs.sheets)} ark."
        f" (obszar projektu: {len(inputs.required_sheets)} ark.), bez pobierania",
        "Przetwarzanie NMT: mozaika VRT z wersji zestawu, "
        "stream_network, stream_catchments (ZAWSZE od zera)",
        f"Pokrycie terenu: BDOT10k z zestawu, {which}: {counties}",
        f"Dane glebowe HSG: raster z zestawu {hsg}, "
        "pod mokradłami paczek zestawu grupa D",
    ]


# The longest list of pins or units a refusal prints for a person; the error document
# holds all of them.
REFUSAL_LIST_LIMIT = 20


def fail(error: HydrografError) -> NoReturn:
    """End the bootstrap on a refusal (AGI-3.3).

    Standard error gets the Polish message, its hint and the first pins or units of
    the error for a person, then, as its last line, the error document
    ``hydrograf-error/1`` in English; the exit code is the registry's.
    """
    print(f"BŁĄD: {error.text('pl')}", file=sys.stderr)
    hint = error.hint_text("pl")
    if hint is not None:
        print(f"Wskazówka: {hint}", file=sys.stderr)
    for key in ("pins", "units"):
        items = error.details.get(key) or []
        for item in items[:REFUSAL_LIST_LIMIT]:
            print(f"  {item}", file=sys.stderr)
        if len(items) > REFUSAL_LIST_LIMIT:
            print(f"  … i {len(items) - REFUSAL_LIST_LIMIT} więcej", file=sys.stderr)
    document = json.dumps(error.document(), ensure_ascii=False, separators=(",", ":"))
    print(document, file=sys.stderr, flush=True)
    sys.exit(BY_CODE[error.code].exit_code or 1)


class _Parser(argparse.ArgumentParser):
    """The parser of the bootstrap: a wrong argument ends with the error document."""

    def error(self, message: str) -> NoReturn:
        """Print the usage, then refuse with ``validation_error`` (exit 2)."""
        self.print_usage(sys.stderr)
        fail(
            InvalidRequestError(
                "bootstrap_arguments_invalid",
                reason="invalid_arguments",
                cause=message,
            )
        )


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_set_record(
    path: Path,
    inputs: SetInputs,
    *,
    started_at: str,
    finished_at: str | None,
    status: str,
    stream_burning: str,
    fill_enclosed_nodata: bool,
) -> None:
    """Write the record of the set a run took its Kartograf data from (ADR-067).

    ``<output>/bootstrap_set.json``: the identity of the set (project, set,
    ``closed_at``, ``pins_sha256``, the pins per product), the BDOT10k streams the
    run burned (``stream_burning``), whether it filled the nodata the mosaic encloses
    (``fill_enclosed_nodata``), when the run started and ended, and ``status``
    (``running``, ``ok`` or ``failed``: a step 1 to 3 failed).
    """
    record = {
        "schema": SET_RECORD_SCHEMA,
        **inputs.identity(),
        "stream_burning": stream_burning,
        "fill_enclosed_nodata": fill_enclosed_nodata,
        "started_at": started_at,
        "finished_at": finished_at,
        "status": status,
    }
    partial = path.with_name(f".{path.name}.tmp")
    partial.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(partial, path)


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = _Parser(
        description="Jednokomendowy setup srodowiska Hydrograf",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required (mutually exclusive)
    area_group = parser.add_mutually_exclusive_group(required=True)
    area_group.add_argument(
        "--bbox",
        type=str,
        help='Bounding box WGS84: "min_lon,min_lat,max_lon,max_lat"',
    )
    area_group.add_argument(
        "--sheets",
        nargs="+",
        metavar="SHEET",
        help="Godla arkuszy: N-34-131-C-c-2-1 N-34-131-C-c-2-2",
    )
    area_group.add_argument(
        "--boundary-file",
        type=Path,
        help="Vector boundary file (SHP/ZIP, GPKG, GeoJSON)",
    )
    area_group.add_argument(
        "--project",
        type=Path,
        metavar="PATH",
        help=(
            "Katalog projektu Archiwisty (albo jego archiwista-project.json): dane "
            "Kartografa tylko z zamkniętego zestawu --set, sprawdzone SHA-256, bez "
            "pobierania (ADR-067)"
        ),
    )
    parser.add_argument(
        "--set",
        metavar="NAME",
        help="Zestaw projektu --project (wielkość liter bez znaczenia)",
    )

    # Optional
    parser.add_argument(
        "--scale",
        type=str,
        default="1:10000",
        choices=["1:10000", "1:25000", "1:50000", "1:100000"],
        help="Skala mapy (default: 1:10000)",
    )
    parser.add_argument(
        "--boundary-layer",
        type=str,
        default=None,
        help="Layer name for GPKG files (default: first layer)",
    )
    parser.add_argument(
        "--area-name",
        default=None,
        help="Name of the data area on the welcome screen (instance.json); default "
        "the Archiwista project's name, else the boundary file's stem",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help=f"Katalog wyjsciowy (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help=(
            "Directory for cached raw downloads: the Kartograf store is "
            f"<cache-dir>/kartograf (default: {DEFAULT_CACHE_DIR})"
        ),
    )
    parser.add_argument(
        "--units",
        type=Path,
        metavar="PGW.gpkg",
        help=(
            "Kartograf PGW GeoPackage: step 3 processes the NMT mosaic by its PGW "
            "units (ADR-071): one fill of the whole grid, the routing on disk, the "
            "same results; the units are clipped to the area of --boundary-file or "
            "--project"
        ),
    )
    parser.add_argument(
        "--units-catchments",
        type=Path,
        metavar="CATCHMENTS.gpkg",
        help=(
            "With --units: catchments (e.g. the MPHP catchments of the area) grouped "
            "into the units, each to the PGW unit it overlaps most; their keys are "
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
        "--units-scratch-dir",
        type=Path,
        default=None,
        metavar="DIR",
        help=(
            "With --units: the scratch of step 3 (the fill of the whole grid and "
            "the routing rasters, removed after a run) in DIR"
        ),
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
        "--allow-uncovered",
        action="store_true",
        help=(
            "Warn instead of refusing when the NMT sheets leave part of the area, or "
            "a hole inside their mosaic, without data (ADR-076); with "
            "dem.fill_enclosed_nodata the enclosed holes are interpolated (ADR-073)"
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port HTTP (default: 8080)",
    )

    # Skip flags
    skip_group = parser.add_argument_group("Pomijanie krokow")
    skip_group.add_argument(
        "--skip-infra",
        action="store_true",
        help="Pomin .venv/Docker/Alembic",
    )
    skip_group.add_argument(
        "--skip-landcover",
        action="store_true",
        help="Pomin pokrycie terenu",
    )
    skip_group.add_argument(
        "--skip-hsg",
        action="store_true",
        help="Pomin dane glebowe HSG",
    )
    skip_group.add_argument(
        "--skip-precipitation",
        action="store_true",
        help="Pomin opady IMGW",
    )
    skip_group.add_argument(
        "--skip-depressions",
        action="store_true",
        help="Pomin depresje",
    )
    skip_group.add_argument(
        "--skip-tiles",
        action="store_true",
        help="Pomin kafelki MVT",
    )
    skip_group.add_argument(
        "--skip-overlays",
        action="store_true",
        help="Pomin overlay PNG",
    )
    skip_group.add_argument(
        "--skip-serve",
        action="store_true",
        help="Pomin uruchomienie serwera",
    )

    parser.add_argument(
        "--resolution",
        type=str,
        default="5m",
        choices=["1m", "5m"],
        help="Rozdzielczość NMT: 1m (wysoka, wolna) lub 5m (domyślna, szybka)",
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

    # Sewer integration
    sewer_group = parser.add_argument_group("Kanalizacja deszczowa")
    sewer_group.add_argument(
        "--sewer-enabled",
        action="store_true",
        default=None,
        help="Wlacz integracje kanalizacji deszczowej",
    )
    sewer_group.add_argument(
        "--sewer-source",
        type=str,
        default=None,
        help="Sciezka do pliku z siecia kanalizacyjna (GPKG/SHP/GeoJSON)",
    )
    sewer_group.add_argument(
        "--sewer-layer",
        type=str,
        default=None,
        help="Nazwa warstwy linii w pliku wielowarstwowym",
    )

    # Configuration file
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Sciezka do pliku konfiguracyjnego YAML (default: config.yaml)",
    )

    # Dry run
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Tylko pokaz co zostanie zrobione",
    )

    return parser


def main():
    """Run the bootstrap pipeline."""
    parser = build_parser()
    args = parser.parse_args()
    if (args.project is None) != (args.set is None):
        parser.error("--project and --set go together")
    if args.units is not None and not args.units.is_file():
        parser.error(f"PGW units GeoPackage does not exist: {args.units}")
    if args.units is None and (
        args.units_catchments or args.units_scratch_dir or args.no_resume
    ):
        parser.error(
            "--units-catchments, --units-scratch-dir and --no-resume need --units"
        )
    if args.units_catchments is not None and not args.units_catchments.is_file():
        parser.error(f"Catchment file does not exist: {args.units_catchments}")
    if args.units_catchments is None and args.units_catchments_layer:
        parser.error("--units-catchments-layer needs --units-catchments")
    if args.project is None:
        # --bbox, --sheets and --boundary-file download: never into a shared store
        try:
            refuse_shared_store()
        except HydrografError as error:
            fail(error)

    # Load YAML pipeline configuration (merged with defaults)
    sys.path.insert(0, str(BACKEND_DIR))
    from core.config import load_config
    from core.hydrology import STREAM_BURNING_MODES

    config = load_config(args.config)
    logger.info(f"Konfiguracja zaladowana z: {args.config}")

    stream_burning = config["dem"]["stream_burning"]
    if stream_burning not in STREAM_BURNING_MODES:
        parser.error(
            f"dem.stream_burning in {args.config} must be one of "
            f"{', '.join(STREAM_BURNING_MODES)}, not {stream_burning!r}"
        )
    logger.info("Stream burning: %s", stream_burning)
    fill_enclosed_nodata = config["dem"]["fill_enclosed_nodata"]
    if not isinstance(fill_enclosed_nodata, bool):
        parser.error(
            f"dem.fill_enclosed_nodata in {args.config} must be true or false, "
            f"not {fill_enclosed_nodata!r}"
        )
    logger.info("Enclosed nodata filled: %s", fill_enclosed_nodata)

    # Resolve output directory
    output_dir = Path(args.output) if args.output else DEFAULT_DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # Resolve cache directory
    cache_dir = args.cache_dir or Path(
        config.get("paths", {}).get("cache_dir", str(DEFAULT_CACHE_DIR))
    )
    if not cache_dir.is_absolute():
        cache_dir = PROJECT_ROOT / cache_dir
    cache_dir = cache_dir.resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Collect skip flags → step numbers
    skips: set[int] = set()
    if args.skip_infra:
        skips.add(1)
    if args.skip_landcover:
        skips.add(4)
    if args.skip_hsg:
        skips.add(5)
    if args.skip_precipitation:
        skips.add(6)
    if args.skip_depressions:
        skips.add(7)
    if args.skip_tiles:
        skips.add(8)
    if args.skip_overlays:
        skips.add(9)
    if args.skip_serve:
        skips.add(10)

    from core.boundary import load_boundary

    inputs: SetInputs | None = None
    # The area the NMT mosaic must cover, checked after step 2 (ADR-076)
    coverage_area: BaseGeometry | None = None
    if args.project is not None:
        # Every check of ADR-067 before step 1: the project, the set, every pin
        try:
            inputs = set_inputs(
                args.project,
                args.set,
                resolution=args.resolution,
                cache_dir=cache_dir,
                landcover=4 not in skips,
                hsg=5 not in skips,
            )
            # ADR-076: the sheets of the set cover the area and enclose no hole
            check_nmt_coverage(
                area_2180(load_boundary(inputs.area)),
                inputs.sheets,
                scale=SHEET_SCALE,
                resolution=args.resolution,
                allow_uncovered=args.allow_uncovered,
            )
        except HydrografError as error:
            fail(error)
        logger.info(
            "Bootstrap from a set: %s",
            json.dumps(inputs.identity(), ensure_ascii=False),
        )
        sheets = list(inputs.sheets)
        bbox = inputs.area_bbox_wgs84
    else:
        # Parse bbox, resolve sheets, or load boundary file
        from kartograf import ParseError as KartografParseError
        from kartograf import ValidationError as KartografValidationError

        try:
            if args.boundary_file:
                sheets, bbox = resolve_boundary_file(
                    args.boundary_file, args.scale, args.boundary_layer
                )
            else:
                bbox_parsed = parse_bbox(args.bbox) if args.bbox else None
                sheets, bbox = resolve_sheets(bbox_parsed, args.sheets, args.scale)
        except (ValueError, KartografValidationError, KartografParseError) as e:
            parser.error(str(e))

        if not sheets:
            logger.error("Nie znaleziono arkuszy dla podanego obszaru")
            sys.exit(1)

        if args.boundary_file:
            coverage_area = area_2180(
                load_boundary(args.boundary_file, args.boundary_layer)
            )
        elif args.sheets:
            coverage_area = unary_union([sheet_frame(sheet) for sheet in sheets])
        else:
            coverage_area = area_2180(box(*bbox))

    # Print header
    print_header(
        bbox,
        sheets,
        args.port,
        boundary_file=getattr(args, "boundary_file", None),
        inputs=inputs,
    )

    if args.dry_run:
        dry_run(sheets, bbox, output_dir, cache_dir, args.port, skips, inputs=inputs)
        return

    # Build sewer config: CLI flags override config.yaml
    sewer_config = config.get("sewer", {})
    if args.sewer_enabled:
        sewer_config["enabled"] = True
    if args.sewer_source:
        sewer_config.setdefault("source", {})["path"] = args.sewer_source
        sewer_config["source"]["type"] = "file"
    if args.sewer_layer:
        sewer_config.setdefault("source", {})["lines_layer"] = args.sewer_layer

    # Wrap in top-level dict (process_dem expects sewer_config["sewer"])
    full_sewer_config = {"sewer": sewer_config} if sewer_config.get("enabled") else None

    # The record of the set ties the data of this run to it; a run without a set
    # leaves none (ADR-067)
    record = output_dir / SET_RECORD_NAME
    started_at = _utc_now()
    if inputs is not None:
        write_set_record(
            record,
            inputs,
            started_at=started_at,
            finished_at=None,
            status="running",
            stream_burning=stream_burning,
            fill_enclosed_nodata=fill_enclosed_nodata,
        )
    else:
        record.unlink(missing_ok=True)

    # The PGW units are the units of the analysis area, where the run has one
    units_area: tuple[Path, str | None] | None = None
    if args.units is not None:
        if inputs is not None:
            units_area = (inputs.area, None)
        elif args.boundary_file:
            units_area = (args.boundary_file, args.boundary_layer)
    units_catchments: tuple[Path, str | None, str] | None = None
    if args.units_catchments is not None:
        units_catchments = (
            args.units_catchments,
            args.units_catchments_layer,
            args.units_catchments_key,
        )

    # Run pipeline
    total_start = time.time()
    tracker = run_pipeline(
        sheets,
        bbox,
        output_dir,
        cache_dir,
        args.port,
        skips,
        waterbody_mode=args.waterbody_mode,
        waterbody_min_area_m2=args.waterbody_min_area,
        resolution=args.resolution,
        sewer_config=full_sewer_config,
        inputs=inputs,
        stream_burning=stream_burning,
        units_path=args.units,
        units_area=units_area,
        units_scratch_dir=args.units_scratch_dir,
        units_catchments=units_catchments,
        units_resume=not args.no_resume,
        fill_enclosed_nodata=fill_enclosed_nodata,
        coverage_area=coverage_area,
        scale=args.scale,
        allow_uncovered=args.allow_uncovered,
    )
    total_elapsed = time.time() - total_start

    # Final summary
    print(f"{'=' * 58}")
    print(f"  Czas calkowity: {total_elapsed:.1f}s")
    if tracker.errors:
        print(f"\n  Bledy ({len(tracker.errors)}):")
        for err in tracker.errors:
            print(f"    {SYM_FAIL} {err}")
    print(f"{'=' * 58}")

    # Exit with error if critical steps failed
    critical_failed = any(
        tracker.statuses[i] == "fail"
        for i in range(3)  # steps 1-3
    )
    if inputs is not None:
        write_set_record(
            record,
            inputs,
            started_at=started_at,
            finished_at=_utc_now(),
            status="failed" if critical_failed else "ok",
            stream_burning=stream_burning,
            fill_enclosed_nodata=fill_enclosed_nodata,
        )
    if critical_failed:
        sys.exit(1)
    write_instance(args, inputs)


def write_instance(args: argparse.Namespace, inputs: SetInputs | None) -> None:
    """Write ``frontend/data/instance.json`` after a run whose steps 1 to 3 passed.

    The area is the set's project area, else ``--boundary-file``; a run by ``--bbox``
    or ``--sheets`` has no boundary, so no area in km². The file only describes the
    instance to users: a failure to write it is a warning, not a failed run.
    """
    boundary = inputs.area if inputs is not None else args.boundary_file
    try:
        info = build_instance_info(
            generated_at=_utc_now(),
            area_name=args.area_name,
            boundary=boundary,
            boundary_layer=None if inputs is not None else args.boundary_layer,
            set_identity=inputs.identity() if inputs is not None else None,
            nmt_resolution_m=resolution_m(args.resolution),
        )
        path = write_instance_info(FRONTEND_DIR / "data", info)
    except (OSError, ValueError) as e:
        logger.warning(f"instance.json not written: {e}")
        return
    logger.info(f"Opis instancji: {path}")


if __name__ == "__main__":
    main()
