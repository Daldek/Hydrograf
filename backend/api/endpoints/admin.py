"""
The admin API of Hydrograf under /api/v1/admin/ (Nogat DEV-15.13, ADR-086).

The core routes of every GUI's panel, `status` and `stats` (the reports are in
`feedback.py`), then the routes of Hydrograf's own sections of the panel: resources,
cleanup, the DEM bootstrap, the boundary upload and the storm sewer. Every route needs
the admin key (`api/dependencies/admin_auth.py`).
"""

import asyncio
import datetime
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Any, Literal, NotRequired, TypedDict, cast

import psutil
from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.pool import QueuePool

from api.dependencies.admin_auth import verify_admin_key
from api.errors import problem_responses
from api.traffic import Traffic
from core.catchment_graph import (
    GRAPH_LOAD_TIMEOUT_S,
    catchment_graph_loading,
    get_catchment_graph,
    loaded_catchment_graph,
    wait_for_catchment_graph,
)
from core.config import get_settings
from core.database import get_db, get_db_engine
from core.errors import (
    ConflictError,
    FileOperationError,
    ForbiddenError,
    InvalidRequestError,
    NotFoundError,
)
from core.usage import TOTALS, utc_today
from core.version import get_version
from scripts.clean import DB_TABLES, dir_size, execute_clean, force_rmtree
from utils.kartograf_store import refuse_shared_store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_DATA = PROJECT_ROOT / "frontend" / "data"
FRONTEND_TILES = PROJECT_ROOT / "frontend" / "tiles"
DATA_NMT = PROJECT_ROOT / "data" / "nmt"
DATA_HYDRO = PROJECT_ROOT / "data" / "hydro"
DATA_SEWER = PROJECT_ROOT / "data" / "sewer"
CACHE_DIR = PROJECT_ROOT / "cache"

ALLOWED_SEWER_EXTENSIONS = {".shp", ".gpkg", ".geojson", ".json", ".zip"}
MAX_SEWER_UPLOAD_MB = 100

# When this process started: the module is imported as the API starts
_STARTED_AT = datetime.datetime.now(datetime.UTC)
_STARTED = time.monotonic()

# ---------------------------------------------------------------------------
# Router (all endpoints require admin auth)
# ---------------------------------------------------------------------------
router = APIRouter(dependencies=[Depends(verify_admin_key)])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# The sizes of the data directories, each walked in a thread of its own: the walk of the
# tiles of a large instance outlasts the admin proxy (E5b-02: 2.15 M files, 48.9 s
# against nginx's 30 s), so a route waits for the walks it starts at most
# _DIR_SIZE_WAIT_S and then answers the last size it knows, null before the first
_DIR_SIZE_TTL = 30.0  # seconds a measured size is reused
_DIR_SIZE_WAIT_S = 5.0  # seconds a route waits for the walks of its directories


class _DirSizes:
    """The sizes of directories in MB, each walked by at most one thread at a time."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sizes: dict[Path, tuple[float, float]] = {}  # path -> (monotonic, MB)
        self._walks: dict[Path, threading.Thread] = {}

    def _walk(self, path: Path) -> None:
        """Measure one directory and keep its size; a failed walk keeps the last one."""
        size_mb: float | None = None
        try:
            size_mb = round(dir_size(path) / (1024 * 1024), 2)
        except OSError as e:
            logger.warning("Could not measure the size of %s: %s", path, e)
        finally:
            with self._lock:
                if size_mb is not None:
                    self._sizes[path] = (time.monotonic(), size_mb)
                del self._walks[path]

    def measure(
        self, paths: Iterable[Path], wait_s: float = _DIR_SIZE_WAIT_S
    ) -> dict[Path, float | None]:
        """Return the size of each directory in MB, walking those not measured lately.

        Parameters
        ----------
        paths : Iterable[Path]
            The directories (a missing one measures 0.0).
        wait_s : float
            How long to wait for the walks that run [s]; a walk not done by then
            goes on in its thread.

        Returns
        -------
        dict[Path, float | None]
            The size of each directory: measured within ``_DIR_SIZE_TTL``, the last
            one known while a new walk runs, or None before its first walk ends.
        """
        unique = list(dict.fromkeys(paths))
        now = time.monotonic()
        with self._lock:
            for path in unique:
                measured = self._sizes.get(path)
                fresh = measured is not None and now - measured[0] < _DIR_SIZE_TTL
                if not fresh and path not in self._walks:
                    walk = threading.Thread(
                        target=self._walk,
                        args=(path,),
                        name=f"dir-size-{path.name}",
                        daemon=True,
                    )
                    # The walk ends by taking the lock this call holds, so it is
                    # registered before it can end
                    walk.start()
                    self._walks[path] = walk
            walks = [self._walks[path] for path in unique if path in self._walks]
        deadline = time.monotonic() + wait_s
        for walk in walks:
            walk.join(max(0.0, deadline - time.monotonic()))
        with self._lock:
            return {
                path: self._sizes[path][1] if path in self._sizes else None
                for path in unique
            }


_DIR_SIZES = _DirSizes()


def _sum_mb(sizes: Iterable[float | None]) -> float | None:
    """Return the sum of sizes in MB, None when one of them is not known yet."""
    total = 0.0
    for size in sizes:
        if size is None:
            return None
        total += size
    return round(total, 2)


# ---------------------------------------------------------------------------
# Status: GET /api/v1/admin/status of Nogat DEV-15.13, the view „Stan” of the panel
# ---------------------------------------------------------------------------
class DiskSpace(BaseModel):
    """The file system of the data directory; null where it cannot be read."""

    free_bytes: int | None = Field(description="Free space in bytes")
    total_bytes: int | None = Field(description="Size in bytes")


class StatusCheck(BaseModel):
    """One check of the status (README "Admin panel")."""

    name: str = Field(description="database, catchment_graph or data_dir")
    status: Literal["ok", "warning", "failed"] = Field(description="What it found")
    detail: str = Field(description="What it found, in Polish")


class StatusResponse(BaseModel):
    """The server and its checks (Nogat DEV-15.13)."""

    app: str = Field(description="Hydrograf")
    version: str = Field(description="Hydrograf version, from backend/pyproject.toml")
    started_at: str = Field(description="Start of the process, ISO 8601 with offset")
    uptime_s: int = Field(description="Seconds since the start")
    data_dir: str = Field(description="The deployment's data_dir (HYDROGRAF_DATA_DIR)")
    disk: DiskSpace
    checks: list[StatusCheck]


@router.get("/status", response_model=StatusResponse)
def server_status(db: Session = Depends(get_db)) -> StatusResponse:
    """Return the server and its checks: the database, the catchment graph, data_dir."""
    data_dir = Path(get_settings().hydrograf_data_dir)
    return StatusResponse(
        app="Hydrograf",
        version=get_version(),
        started_at=_STARTED_AT.isoformat(timespec="seconds"),
        uptime_s=int(time.monotonic() - _STARTED),
        data_dir=str(data_dir),
        disk=_disk_space(data_dir),
        checks=[
            _database_check(db),
            _catchment_graph_check(),
            _data_dir_check(data_dir),
        ],
    )


def _disk_space(path: Path) -> DiskSpace:
    """Return the free and the total bytes of the file system that holds ``path``."""
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return DiskSpace(free_bytes=None, total_bytes=None)
    return DiskSpace(free_bytes=usage.free, total_bytes=usage.total)


def _database_check(db: Session) -> StatusCheck:
    """Whether PostGIS answers a query."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as error:
        cause = (str(error).splitlines() or [type(error).__name__])[0]
        return StatusCheck(
            name="database",
            status="failed",
            detail=f"Baza danych nie odpowiada: {cause}",
        )
    return StatusCheck(name="database", status="ok", detail="Baza danych odpowiada.")


def _catchment_graph_check() -> StatusCheck:
    """Whether the in-memory catchment graph of the delineation is loaded."""
    graph = get_catchment_graph()
    if catchment_graph_loading():
        return StatusCheck(
            name="catchment_graph",
            status="warning",
            detail=(
                "Graf zlewni się wczytuje; do końca wczytywania wyznaczanie zlewni i "
                "sieci oraz hydrogram odpowiadają 503 („Spróbuj ponownie za chwilę.”)."
            ),
        )
    if not graph.loaded:
        return StatusCheck(
            name="catchment_graph",
            status="warning",
            detail=(
                "Graf zlewni nie jest wczytany: baza danych nie ma sieci cieków albo "
                "wczytanie się nie udało (log aplikacji). Następne wyznaczenie "
                "zlewni zacznie go wczytywać."
            ),
        )
    thresholds = ", ".join(_grouped(t) for t in graph.thresholds_m2())
    return StatusCheck(
        name="catchment_graph",
        status="ok",
        detail=(
            f"Wczytany: {_grouped(graph._n)} zlewni cząstkowych, progi {thresholds} m²."
        ),
    )


def _data_dir_check(data_dir: Path) -> StatusCheck:
    """Whether the daily statistics can be written: ``<data_dir>/hydrograf``.

    Before the first write that directory does not exist yet, and ``data_dir``,
    where it is then made, is checked.
    """
    own = data_dir / "hydrograf"
    folder = own if own.exists() else data_dir
    if not folder.is_dir():
        problem = f"Nie ma katalogu {folder}"
    elif not os.access(folder, os.W_OK | os.X_OK):
        problem = f"Katalog {folder} nie jest zapisywalny"
    else:
        return StatusCheck(
            name="data_dir", status="ok", detail=f"Katalog {folder} jest zapisywalny."
        )
    return StatusCheck(
        name="data_dir",
        status="failed",
        detail=f"{problem}: statystyki dzienne nie są zapisywane.",
    )


def _grouped(number: int) -> str:
    """Return a whole number with its thousands apart, as Polish writes it: 41 515."""
    return f"{number:,}".replace(",", "\u00a0")


# ---------------------------------------------------------------------------
# Statistics: GET /api/v1/admin/stats of Nogat DEV-15.13, the view „Statystyki”
# ---------------------------------------------------------------------------
# Days of the period when the request gives no `from`, the last one included
STATS_DAYS = 30


class StatsDay(BaseModel):
    """One UTC day of `stats.jsonl` (Nogat DEV-15.11; README "Public service")."""

    date: datetime.date
    visitors: int
    page_views: int
    stations_opened: int
    analyses_run: int
    downloads: int


class StatsTotals(BaseModel):
    """The sums of the days of the period: every total but the visitors."""

    page_views: int
    stations_opened: int
    analyses_run: int
    downloads: int


class StatsResponse(BaseModel):
    """The days of a period and their sums (Nogat DEV-15.13)."""

    days: list[StatsDay] = Field(
        description="The days of the file in the period, in date order; the current "
        "day as counted so far"
    )
    totals: StatsTotals


@router.get("/stats", response_model=StatsResponse)
async def daily_stats(
    request: Request,
    first: datetime.date | None = Query(
        None, alias="from", description="First UTC day; default 29 days before `to`"
    ),
    last: datetime.date | None = Query(
        None, alias="to", description="Last UTC day; default today"
    ),
) -> StatsResponse:
    """Return the daily totals between two UTC days, both included, and their sums.

    The lines of `<data_dir>/hydrograf/stats.jsonl` (Nogat DEV-15.11); the current day
    is what earlier processes stored of it plus what this one has counted so far.
    Runs in the event loop, like the middleware that counts, so it reads the totals
    of this process between two of its requests.
    """
    last = last or utc_today()
    first = first or last - datetime.timedelta(days=STATS_DAYS - 1)
    if first > last:
        raise InvalidRequestError(
            "stats_period_reversed",
            reason="stats_period_reversed",
            first=first.isoformat(),
            last=last.isoformat(),
        )
    traffic: Traffic = request.app.state.traffic
    days = traffic.stats.days(first, last, traffic.usage.day, traffic.usage.totals())
    totals = {
        name: sum(day[name] for day in days) for name in TOTALS if name != "visitors"
    }
    return StatsResponse(
        days=[StatsDay.model_validate(day) for day in days],
        totals=StatsTotals.model_validate(totals),
    )


# ---------------------------------------------------------------------------
# Resources: the section „Zasoby” of the panel
# ---------------------------------------------------------------------------
# DB_TABLES imported from scripts.clean — single source of truth


class ResourcesResponse(BaseModel):
    """System resource usage response."""

    process: dict[str, Any] = Field(description="Process CPU/memory info")
    db_pool: dict[str, Any] = Field(description="Database connection pool stats")
    catchment_graph: dict[str, Any] = Field(description="Catchment graph status")
    db_size_mb: float = Field(description="Database size in MB")
    tables: dict[str, int] = Field(description="Row counts per table")
    disk: dict[str, float | None] = Field(
        description="Disk usage in MB: frontend_data_mb, frontend_tiles_mb, "
        "nmt_data_mb, cache_mb and their total_mb; null for a directory whose first "
        "walk is still running, and total_mb null with it (E5b-02)"
    )


@router.get("/resources", response_model=ResourcesResponse)
def resources(db: Session = Depends(get_db)) -> ResourcesResponse:
    """System resource usage, the rows of the tables and the size of the data."""
    # Process info
    proc = psutil.Process(os.getpid())
    mem_info = proc.memory_info()
    process_info = {
        "cpu_percent": proc.cpu_percent(interval=0.1),
        "memory_mb": round(mem_info.rss / (1024 * 1024), 2),
        "memory_percent": round(proc.memory_percent(), 2),
        "pid": proc.pid,
        "threads": proc.num_threads(),
    }

    # DB pool info
    try:
        engine = get_db_engine()
        pool = cast(QueuePool, engine.pool)
        db_pool_info = {
            "pool_size": pool.size(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "checked_in": pool.checkedin(),
        }
    except Exception:
        db_pool_info = {
            "pool_size": 0,
            "checked_out": 0,
            "overflow": 0,
            "checked_in": 0,
        }

    # Catchment graph info
    cg = get_catchment_graph()
    cg_info: dict[str, Any] = {"loaded": cg.loaded, "nodes": 0, "threshold_m2": []}
    if cg.loaded:
        cg_info["nodes"] = cg._n
        if cg._threshold_m2 is not None:
            import numpy as np

            cg_info["threshold_m2"] = sorted(
                int(t) for t in np.unique(cg._threshold_m2)
            )

    # Database size
    try:
        result = db.execute(text("SELECT pg_database_size(current_database())"))
        db_size_bytes = result.scalar() or 0
        db_size_mb = round(db_size_bytes / (1024 * 1024), 2)
    except Exception:
        db_size_mb = 0.0

    # Table row counts; a failed count aborts the transaction, which is rolled back so
    # that the next counts run
    tables: dict[str, int] = {}
    for table in DB_TABLES:
        try:
            result = db.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608 — table names from hardcoded DB_TABLES, not user input
            tables[table] = result.scalar() or 0
        except Exception:
            db.rollback()
            tables[table] = 0

    # Disk usage: the directories are walked in threads of their own (E5b-02)
    sizes = _DIR_SIZES.measure([FRONTEND_DATA, FRONTEND_TILES, DATA_NMT, CACHE_DIR])
    disk = {
        "frontend_data_mb": sizes[FRONTEND_DATA],
        "frontend_tiles_mb": sizes[FRONTEND_TILES],
        "nmt_data_mb": sizes[DATA_NMT],
        "cache_mb": sizes[CACHE_DIR],
    }

    return ResourcesResponse(
        process=process_info,
        db_pool=db_pool_info,
        catchment_graph=cg_info,
        db_size_mb=db_size_mb,
        tables=tables,
        disk={**disk, "total_mb": _sum_mb(disk.values())},
    )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


class _CleanupTarget(TypedDict):
    label: str
    components: list[str]
    exclude_from_all: NotRequired[bool]


# Cleanup components — maps admin UI keys to scripts.clean component names.
# "all" runs every component except cache; "cache" is opt-in.
_CLEANUP_COMPONENTS: dict[str, _CleanupTarget] = {
    "all": {
        "label": "Dane przetwarzania (bez pamięci podręcznej)",
        "components": [
            "rasters",
            "hydro",
            "boundary",
            "overlays",
            "geojson",
            "tiles",
            "db",
        ],
    },
    "cache": {
        "label": "Pamięć podręczna pobrań (NMT, BDOT10k)",
        "components": ["cache"],
        "exclude_from_all": True,
    },
}

# Estimate helpers — reuse path constants
_ESTIMATE_DIRS = {
    "rasters": DATA_NMT,
    "hydro": DATA_HYDRO,
    "overlays": FRONTEND_DATA,
    "tiles": FRONTEND_TILES,
    "cache": CACHE_DIR,
}


class CleanupEstimateResponse(BaseModel):
    """Cleanup estimate response."""

    targets: list[dict[str, Any]] = Field(
        description="List of targets with size_mb, null while a directory of the "
        "target is still being walked (E5b-02)"
    )


class CleanupRequest(BaseModel):
    """Cleanup execution request."""

    targets: list[str] = Field(description="List of target keys to clean")


class CleanupResponse(BaseModel):
    """Cleanup execution response."""

    results: list[dict[str, Any]] = Field(description="Results per target")


@router.get("/cleanup/estimate", response_model=CleanupEstimateResponse)
def cleanup_estimate(
    db: Session = Depends(get_db),
) -> CleanupEstimateResponse:
    """Estimate cleanup sizes for all targets."""
    # Aggregate disk sizes per cleanup target; the directories are walked in threads
    # of their own (E5b-02)
    sizes = _DIR_SIZES.measure(_ESTIMATE_DIRS.values())
    targets = []
    for key, info in _CLEANUP_COMPONENTS.items():
        parts: list[float | None] = []
        for comp in info["components"]:
            if comp in _ESTIMATE_DIRS:
                parts.append(sizes[_ESTIMATE_DIRS[comp]])
            elif comp == "db":
                try:
                    result = db.execute(
                        text("SELECT pg_database_size(current_database())")
                    )
                    parts.append(round((result.scalar() or 0) / (1024 * 1024), 2))
                except Exception:
                    pass
        targets.append({"key": key, "label": info["label"], "size_mb": _sum_mb(parts)})
    return CleanupEstimateResponse(targets=targets)


@router.post("/cleanup", response_model=CleanupResponse)
def cleanup_execute(
    request: CleanupRequest,
    db: Session = Depends(get_db),
) -> CleanupResponse:
    """Execute cleanup by delegating to scripts.clean.execute_clean().

    Uses the same logic as ``python -m scripts.clean`` CLI — single source
    of truth for table lists, directory paths, and cleanup order.
    """
    results = []
    for target_key in request.targets:
        if target_key not in _CLEANUP_COMPONENTS:
            raise InvalidRequestError(
                "unknown_cleanup_target",
                reason="unknown_cleanup_target",
                target=target_key,
                allowed=sorted(_CLEANUP_COMPONENTS),
            )
        components = _CLEANUP_COMPONENTS[target_key]["components"]
        try:
            summary = execute_clean(
                components=components,
                data_dir=PROJECT_ROOT / "data",
                cache_dir=CACHE_DIR,
                dry_run=False,
            )
            results.append(
                {
                    "key": target_key,
                    "status": "ok",
                    "total_files": summary["total_files"],
                    "total_size": summary["total_size"],
                }
            )
        except Exception as e:
            results.append({"key": target_key, "status": "error", "detail": str(e)})

    return CleanupResponse(results=results)


# ---------------------------------------------------------------------------
# Boundary file upload
# ---------------------------------------------------------------------------
BOUNDARY_DIR = PROJECT_ROOT / "data" / "boundary"
ALLOWED_BOUNDARY_EXTENSIONS = {".gpkg", ".geojson", ".json", ".zip"}
MAX_UPLOAD_SIZE_MB = 50


@router.post("/bootstrap/upload-boundary")
async def upload_boundary(
    file: UploadFile = File(...),
    _admin: None = Depends(verify_admin_key),
) -> dict[str, Any]:
    """Upload and validate a boundary file. Returns metadata + filename."""
    if not file.filename:
        raise InvalidRequestError("filename_missing", reason="filename_missing")

    # Validate extension
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_BOUNDARY_EXTENSIONS:
        raise InvalidRequestError(
            "invalid_file_type",
            reason="invalid_file_type",
            suffix=suffix,
            allowed=sorted(ALLOWED_BOUNDARY_EXTENSIONS),
        )

    # Read file with size limit
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_UPLOAD_SIZE_MB:
        raise InvalidRequestError(
            "file_too_large",
            reason="file_too_large",
            size_mb=round(size_mb, 1),
            max_mb=MAX_UPLOAD_SIZE_MB,
        )

    # Sanitize filename
    safe_name = f"{uuid.uuid4()}_{Path(file.filename).name}"
    BOUNDARY_DIR.mkdir(parents=True, exist_ok=True)
    save_path = BOUNDARY_DIR / safe_name

    # Verify path is within boundary dir (prevent traversal)
    if not save_path.resolve().is_relative_to(BOUNDARY_DIR.resolve()):
        raise InvalidRequestError("invalid_filename", reason="invalid_filename")

    # Save file
    save_path.write_bytes(content)

    try:
        from core.boundary import validate_boundary_file

        metadata = validate_boundary_file(save_path)
    except (ValueError, Exception) as e:
        # Clean up on validation failure
        save_path.unlink(missing_ok=True)
        raise InvalidRequestError(
            "invalid_boundary_file", reason="invalid_boundary_file", cause=str(e)
        ) from e

    return {
        "filename": safe_name,
        "bbox_wgs84": metadata["bbox_wgs84"],
        "area_km2": metadata["area_km2"],
        "n_features": metadata["n_features"],
        "crs": metadata["crs"],
    }


# ---------------------------------------------------------------------------
# Bootstrap subprocess manager
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parents[2]
VENV_PYTHON = sys.executable  # works in both venv and Docker container

# SECURITY: Sheet codes should match patterns like "N-34-12-D-a-1".
# Validate before passing to subprocess to prevent command injection.
SHEET_CODE_PATTERN = re.compile(r"^[A-Za-z0-9\-]{3,30}$")

_HISTORY_MAX = 10

_bootstrap_state: dict[str, Any] = {
    "process": None,
    "status": "idle",
    "log_lines": [],
    "started_at": None,
    "params": None,
    "history": [],
}


def _validate_bbox(bbox_str: str) -> tuple[float, float, float, float]:
    """Validate and parse bbox string (min_lon,min_lat,max_lon,max_lat)."""
    parts = bbox_str.split(",")
    if len(parts) != 4:
        raise ValueError("bbox must have 4 comma-separated values")

    try:
        min_lon, min_lat, max_lon, max_lat = (float(p.strip()) for p in parts)
    except ValueError as exc:
        raise ValueError("bbox values must be valid numbers") from exc

    if min_lon >= max_lon:
        raise ValueError("min_lon must be less than max_lon")
    if min_lat >= max_lat:
        raise ValueError("min_lat must be less than max_lat")

    return min_lon, min_lat, max_lon, max_lat


def _load_catchment_graph() -> None:
    """Load the graph of the network in the database and wait for it (E5b-01).

    :func:`loaded_catchment_graph` starts the load in a thread of its own, unless
    the graph of the database is the current one, and this waits for it.

    Raises
    ------
    RuntimeError
        No graph of the network in the database: the load failed or still runs
        after ``GRAPH_LOAD_TIMEOUT_S``, ``stream_catchments`` is empty, or the
        network changed during the load.
    """
    from core.database import get_db_session

    with get_db_session() as db:
        if loaded_catchment_graph(db) is not None:
            return
    wait_for_catchment_graph(GRAPH_LOAD_TIMEOUT_S)
    with get_db_session() as db:
        if loaded_catchment_graph(db) is None:
            raise RuntimeError("catchment graph not loaded")


def _read_process_output(process: subprocess.Popen[str], state: dict[str, Any]) -> None:
    """Background thread: read stdout lines into state."""
    stdout = process.stdout
    try:
        for line in stdout or ():
            stripped = line.rstrip("\n")
            state["log_lines"].append(stripped)
    except Exception:
        pass
    finally:
        process.wait()
        state["process"] = None
        if process.returncode == 0:
            state["status"] = "completed"
            # Load the new network into the catchment graph now rather than at
            # the next request (requests start its load themselves once the
            # network in the database changed). Retries handle transient pool
            # exhaustion from concurrent admin-panel polling while bootstrap is
            # winding down.
            backoffs_s = (1, 5, 15)
            for attempt, wait_s in enumerate(backoffs_s, start=1):
                try:
                    _load_catchment_graph()
                    state["log_lines"].append("[INFO] CatchmentGraph reloaded")
                    logger.info("CatchmentGraph reloaded after bootstrap")
                    break
                except Exception as e:
                    is_last = attempt == len(backoffs_s)
                    if is_last:
                        state["log_lines"].append(
                            f"[WARN] CatchmentGraph reload failed after "
                            f"{attempt} attempts: {e}"
                        )
                        logger.exception(
                            "CatchmentGraph reload failed after %d attempts",
                            attempt,
                        )
                    else:
                        state["log_lines"].append(
                            f"[WARN] CatchmentGraph reload attempt {attempt} "
                            f"failed: {e}; retrying in {wait_s}s"
                        )
                        logger.warning(
                            "CatchmentGraph reload attempt %d failed: %s; "
                            "retrying in %ds",
                            attempt,
                            e,
                            wait_s,
                        )
                        time.sleep(wait_s)
        else:
            state["status"] = "failed"
        # Save to history
        state["history"].append(
            {
                "status": state["status"],
                "started_at": state["started_at"],
                "finished_at": time.time(),
                "params": state["params"],
                "lines": len(state["log_lines"]),
            }
        )
        if len(state["history"]) > _HISTORY_MAX:
            state["history"] = state["history"][:_HISTORY_MAX]


class BootstrapStatusResponse(BaseModel):
    """Bootstrap status response."""

    status: str = Field(description="idle/running/completed/failed")
    log_lines: int = Field(description="Number of log lines")
    started_at: float | None = Field(description="Start timestamp")
    params: dict[str, Any] | None = Field(description="Parameters used")
    pid: int | None = Field(default=None, description="Process PID")


class BootstrapStartRequest(BaseModel):
    """Bootstrap start request."""

    bbox: str | None = Field(default=None, description="Bounding box")
    sheets: list[str] | None = Field(default=None, description="Sheet codes")
    boundary_file: str | None = Field(
        default=None, description="Filename from upload-boundary endpoint"
    )
    boundary_layer: str | None = Field(
        default=None, description="Layer name for GPKG files"
    )
    skip_precipitation: bool = Field(default=False)
    skip_tiles: bool = Field(default=False)
    skip_overlays: bool = Field(default=False)
    waterbody_mode: str | None = Field(default=None, description="drain or keep")
    resolution: str = Field(
        default="5m",
        pattern=r"^(1m|5m)$",
        description="NMT resolution: 1m (high detail, slow) or 5m (default, fast)",
    )
    sewer_enabled: bool = Field(default=False, description="Enable sewer integration")
    sewer_source: str | None = Field(
        default=None, description="Path to sewer data file"
    )
    sewer_layer: str | None = Field(
        default=None, description="Layer name for multi-layer files"
    )


class BootstrapStartResponse(BaseModel):
    """Bootstrap start response."""

    status: str
    pid: int


@router.get("/bootstrap/status", response_model=BootstrapStatusResponse)
def bootstrap_status() -> BootstrapStatusResponse:
    """Get current bootstrap process status."""
    proc = _bootstrap_state["process"]
    return BootstrapStatusResponse(
        status=_bootstrap_state["status"],
        log_lines=len(_bootstrap_state["log_lines"]),
        started_at=_bootstrap_state["started_at"],
        params=_bootstrap_state["params"],
        pid=proc.pid if proc is not None else None,
    )


@router.post(
    "/bootstrap/start",
    response_model=BootstrapStartResponse,
    responses=problem_responses(
        (
            "forbidden",
            "shared_store_read_only",
            {"reason": "shared_store_read_only", "root": "/data/kartograf"},
        ),
        (
            "not_found",
            "boundary_file_missing",
            {"reason": "boundary_file_missing", "filename": "zlewnia.gpkg"},
        ),
        409,
    ),
)
def bootstrap_start(request: BootstrapStartRequest) -> BootstrapStartResponse:
    """Start bootstrap subprocess.

    Refused with 403 (``forbidden``, ``shared_store_read_only``) before any process
    starts while ``HYDROGRAF_KARTOGRAF_ROOT`` names a shared store: the panel's
    bootstrap downloads by area, and a bootstrap from a set runs from the command
    line (ADR-067).
    """
    refuse_shared_store()
    if _bootstrap_state["status"] == "running":
        raise ConflictError("bootstrap_running", reason="bootstrap_running")

    # Validate input: exactly one of bbox, sheets, boundary_file
    sources = sum(
        [
            request.bbox is not None,
            request.sheets is not None,
            request.boundary_file is not None,
        ]
    )
    if sources != 1:
        raise InvalidRequestError(
            "bootstrap_source_required",
            reason="bootstrap_source_required",
            options=["bbox", "sheets", "boundary_file"],
        )

    # Validate sheet codes before passing to subprocess
    if request.sheets:
        for sheet in request.sheets:
            if not SHEET_CODE_PATTERN.match(sheet):
                raise InvalidRequestError(
                    "invalid_sheet_code", reason="invalid_sheet_code", sheet=sheet
                )

    # Build command
    cmd = [str(VENV_PYTHON), "-m", "scripts.bootstrap"]

    if request.bbox:
        try:
            _validate_bbox(request.bbox)
        except ValueError as e:
            raise InvalidRequestError(
                "invalid_bbox", reason="invalid_bbox", cause=str(e)
            ) from e
        cmd.extend(["--bbox", request.bbox])
    elif request.sheets:
        cmd.extend(["--sheets"] + request.sheets)
    elif request.boundary_file:
        boundary_path = BOUNDARY_DIR / request.boundary_file
        if not boundary_path.exists():
            raise NotFoundError(
                "boundary_file_missing",
                reason="boundary_file_missing",
                filename=request.boundary_file,
            )
        if not boundary_path.resolve().is_relative_to(BOUNDARY_DIR.resolve()):
            raise InvalidRequestError("invalid_filename", reason="invalid_filename")
        cmd.extend(["--boundary-file", str(boundary_path)])
        if request.boundary_layer:
            cmd.extend(["--boundary-layer", request.boundary_layer])

    cmd.extend(["--skip-infra", "--skip-serve"])

    if request.skip_precipitation:
        cmd.append("--skip-precipitation")
    if request.skip_tiles:
        cmd.append("--skip-tiles")
    if request.skip_overlays:
        cmd.append("--skip-overlays")
    if request.waterbody_mode:
        cmd.extend(["--waterbody-mode", request.waterbody_mode])
    if request.resolution and request.resolution != "5m":
        cmd.extend(["--resolution", request.resolution])
    if request.sewer_enabled:
        cmd.append("--sewer-enabled")
        if request.sewer_source:
            # Resolve to absolute path (relative paths are relative to PROJECT_ROOT)
            sewer_abs = (PROJECT_ROOT / request.sewer_source).resolve()
            cmd.extend(["--sewer-source", str(sewer_abs)])
        if request.sewer_layer:
            cmd.extend(["--sewer-layer", request.sewer_layer])

    # Reset state
    _bootstrap_state["log_lines"] = []
    _bootstrap_state["started_at"] = time.time()
    _bootstrap_state["params"] = request.model_dump()
    _bootstrap_state["status"] = "running"

    # Start subprocess
    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(BACKEND_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except (FileNotFoundError, OSError) as e:
        _bootstrap_state["status"] = "failed"
        _bootstrap_state["log_lines"].append(f"[ERROR] Failed to start: {e}")
        raise FileOperationError(
            "bootstrap_start_failed", reason="bootstrap_start_failed", cause=str(e)
        ) from e

    _bootstrap_state["process"] = process

    # Background thread to read output
    thread = threading.Thread(
        target=_read_process_output,
        args=(process, _bootstrap_state),
        daemon=True,
    )
    thread.start()

    return BootstrapStartResponse(status="running", pid=process.pid)


@router.post(
    "/bootstrap/cancel",
    responses=problem_responses(
        ("conflict", "bootstrap_not_running", {"reason": "bootstrap_not_running"})
    ),
)
def bootstrap_cancel() -> dict[str, Any]:
    """Cancel running bootstrap process."""
    proc = _bootstrap_state["process"]
    if proc is None or _bootstrap_state["status"] != "running":
        raise ConflictError("bootstrap_not_running", reason="bootstrap_not_running")

    proc.send_signal(signal.SIGTERM)
    _bootstrap_state["status"] = "failed"
    _bootstrap_state["log_lines"].append("[CANCELLED by admin]")

    return {"status": "cancelled", "pid": proc.pid}


@router.get("/bootstrap/stream")
async def bootstrap_stream() -> StreamingResponse:
    """SSE stream of bootstrap log lines."""

    async def _event_generator() -> AsyncIterator[str]:
        sent = 0
        while True:
            lines = _bootstrap_state["log_lines"]
            while sent < len(lines):
                yield f"data: {lines[sent]}\n\n"
                sent += 1

            status = _bootstrap_state["status"]
            if status in ("completed", "failed", "idle"):
                yield f"event: done\ndata: {status}\n\n"
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Sewer management
# ---------------------------------------------------------------------------


@router.get("/sewer/status")
def sewer_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Get status of sewer data in the database and config."""
    try:
        result = db.execute(text("SELECT COUNT(*) FROM sewer_nodes"))
        node_count = result.scalar() or 0
        result = db.execute(text("SELECT COUNT(*) FROM sewer_network"))
        edge_count = result.scalar() or 0

        type_counts = {}
        if node_count > 0:
            rows = db.execute(
                text("SELECT node_type, COUNT(*) FROM sewer_nodes GROUP BY node_type")
            )
            type_counts = {r[0]: r[1] for r in rows}

        # Read current config
        config = _load_sewer_config()

        return {
            "loaded": node_count > 0,
            "nodes": node_count,
            "edges": edge_count,
            "node_types": type_counts,
            "config": {
                "enabled": config.get("enabled", False),
                "source_path": config.get("source", {}).get("path"),
                "source_type": config.get("source", {}).get("type", "file"),
            },
        }
    except Exception:
        return {
            "loaded": False,
            "nodes": 0,
            "edges": 0,
            "node_types": {},
            "config": {"enabled": False, "source_path": None, "source_type": "file"},
        }


class SewerConfigUpdate(BaseModel):
    """Request body for sewer config update."""

    enabled: bool = Field(..., description="Enable/disable sewer processing")
    source_path: str | None = Field(default=None, description="Path to sewer data file")
    lines_layer: str | None = Field(default=None, description="Layer name for lines")
    points_layer: str | None = Field(default=None, description="Layer name for points")
    field_mapping: dict[str, Any] | None = Field(
        default=None, description="Column name mapping"
    )
    role_mapping: dict[str, Any] | None = Field(
        default=None, description="Value mapping for roles"
    )


CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def _load_sewer_config() -> dict[str, Any]:
    """Read sewer section from config.yaml merged with defaults."""
    from core.config import load_config

    sewer: dict[str, Any] = load_config(str(CONFIG_PATH)).get("sewer", {})
    return sewer


def _save_sewer_config(sewer: dict[str, Any]) -> None:
    """Deep-merge sewer settings into config.yaml (create if needed)."""
    import yaml

    from core.config import _deep_merge

    data: dict[str, Any] = {}
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            data = yaml.safe_load(f) or {}

    data["sewer"] = _deep_merge(data.get("sewer", {}), sewer)
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


@router.put(
    "/sewer/config",
    responses=problem_responses(
        403,
        (
            "not_found",
            "source_file_missing",
            {"reason": "source_file_missing", "path": "data/sewer/siec.gpkg"},
        ),
    ),
)
def sewer_config_update(body: SewerConfigUpdate) -> dict[str, Any]:
    """Toggle sewer processing and set source file path.

    Updates config.yaml so the next pipeline run picks up the settings.
    """
    updates: dict[str, Any] = {"enabled": body.enabled}

    if body.source_path is not None:
        source_file = Path(body.source_path)
        abs_path = (PROJECT_ROOT / source_file).resolve()
        if not abs_path.is_relative_to(PROJECT_ROOT.resolve()):
            raise ForbiddenError("path_outside_project", reason="path_outside_project")
        if not abs_path.exists():
            raise NotFoundError(
                "source_file_missing",
                reason="source_file_missing",
                path=body.source_path,
            )
        updates["source"] = {
            "type": "file",
            "path": body.source_path,
        }
        if body.lines_layer:
            updates["source"]["lines_layer"] = body.lines_layer
        if body.points_layer:
            updates["source"]["points_layer"] = body.points_layer

    if body.field_mapping:
        updates.setdefault("field_mapping", {}).update(body.field_mapping)
    if body.role_mapping:
        updates.setdefault("role_mapping", {}).update(body.role_mapping)

    _save_sewer_config(updates)
    logger.info("Sewer config updated: enabled=%s", body.enabled)

    return {
        "message": f"Sewer {'enabled' if body.enabled else 'disabled'}",
        "config": updates,
        "next_step": (
            "Run pipeline (bootstrap) to process sewer data" if body.enabled else None
        ),
    }


@router.post("/sewer/upload")
async def sewer_upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Upload sewer network file (SHP/GPKG/GeoJSON)."""
    if not file.filename:
        raise InvalidRequestError("filename_missing", reason="filename_missing")

    # Validate extension
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_SEWER_EXTENSIONS:
        raise InvalidRequestError(
            "invalid_file_type",
            reason="invalid_file_type",
            suffix=suffix,
            allowed=sorted(ALLOWED_SEWER_EXTENSIONS),
        )

    # Read file with size limit
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_SEWER_UPLOAD_MB:
        raise InvalidRequestError(
            "file_too_large",
            reason="file_too_large",
            size_mb=round(size_mb, 1),
            max_mb=MAX_SEWER_UPLOAD_MB,
        )

    # Sanitize filename
    safe_name = f"{uuid.uuid4()}_{Path(file.filename).name}"
    DATA_SEWER.mkdir(parents=True, exist_ok=True)
    dest = DATA_SEWER / safe_name

    # Verify path is within sewer dir (prevent traversal)
    if not dest.resolve().is_relative_to(DATA_SEWER.resolve()):
        raise InvalidRequestError("invalid_filename", reason="invalid_filename")

    # Save file
    dest.write_bytes(content)

    # Validate file can be read as geodata
    try:
        import geopandas as gpd

        gdf = gpd.read_file(str(dest))
        n_features = len(gdf)
        geom_types = gdf.geometry.geom_type.unique().tolist()
    except Exception as e:
        dest.unlink(missing_ok=True)
        logger.error(f"Sewer upload geodata validation failed: {e}")
        raise InvalidRequestError("invalid_geodata", reason="invalid_geodata") from e

    # Auto-detect format from layers and geometry types
    import fiona

    detected_format = "unknown"
    layers_detected: list[str] = []
    try:
        layers = fiona.listlayers(str(dest))
        layers_detected = layers
        geom_types_per_layer: dict[str, str] = {}
        for layer_name in layers:
            import geopandas as gpd

            layer_gdf = gpd.read_file(dest, layer=layer_name, rows=1)
            if not layer_gdf.empty:
                geom_types_per_layer[layer_name] = layer_gdf.geometry.iloc[0].geom_type

        has_points = any("Point" in gt for gt in geom_types_per_layer.values())
        has_lines = any("Line" in gt for gt in geom_types_per_layer.values())

        if has_points and has_lines:
            detected_format = "points_and_lines"
        elif has_points:
            detected_format = "points_only"
        elif has_lines:
            detected_format = "lines_only"
    except Exception:
        pass

    return {
        "filename": safe_name,
        "features": n_features,
        "geometry_types": geom_types,
        "detected_format": detected_format,
        "layers": layers_detected,
        "message": "Plik wgrany. Uruchom analizę, aby przetworzyć dane kanalizacyjne.",
    }


@router.delete("/sewer")
def sewer_delete(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Delete all sewer data from database and disk."""
    db.execute(text("TRUNCATE TABLE sewer_network CASCADE"))
    db.execute(text("TRUNCATE TABLE sewer_nodes CASCADE"))
    db.execute(
        text(
            "UPDATE stream_network SET is_sewer_augmented = FALSE "
            "WHERE is_sewer_augmented = TRUE"
        )
    )
    db.commit()

    if DATA_SEWER.exists():
        force_rmtree(DATA_SEWER)

    return {"message": "Sewer data deleted", "pipeline_dirty": True}
