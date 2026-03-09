"""
Admin panel API endpoints.

Provides dashboard, resources, cleanup, and bootstrap management
for the Hydrograf administration panel.
"""

import asyncio
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import psutil
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.dependencies.admin_auth import verify_admin_key
from core.catchment_graph import get_catchment_graph
from core.database import get_db, get_db_engine

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_DATA = PROJECT_ROOT / "frontend" / "data"
FRONTEND_TILES = PROJECT_ROOT / "frontend" / "tiles"
DATA_NMT = PROJECT_ROOT / "data" / "nmt"
DATA_HYDRO = PROJECT_ROOT / "data" / "hydro"
CACHE_DIR = PROJECT_ROOT / "cache"

# Module load time — for uptime calculation
_start_time = time.time()

# ---------------------------------------------------------------------------
# Router (all endpoints require admin auth)
# ---------------------------------------------------------------------------
router = APIRouter(dependencies=[Depends(verify_admin_key)])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _dir_size_mb(path: Path) -> float:
    """Sum file sizes recursively, return MB."""
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return round(total / (1024 * 1024), 2)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
_TABLE_NAMES = [
    "stream_network",
    "stream_catchments",
    "depressions",
    "land_cover",
    "soil_hsg",
    "precipitation_data",
]


class DashboardResponse(BaseModel):
    """Dashboard overview response."""

    status: str = Field(description="healthy or unhealthy")
    version: str = Field(default="1.0.0")
    uptime_s: float = Field(description="Seconds since module loaded")
    database: str = Field(description="connected or error message")
    tables: dict[str, int] = Field(description="Row counts per table")
    disk: dict[str, float] = Field(description="Disk usage in MB")


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(db: Session = Depends(get_db)) -> DashboardResponse:
    """Admin dashboard with system overview."""
    # Database check
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {e}"

    # Table row counts
    tables: dict[str, int] = {}
    for table in _TABLE_NAMES:
        try:
            result = db.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608 — table names from hardcoded _TABLE_NAMES, not user input
            tables[table] = result.scalar() or 0
        except Exception:
            tables[table] = 0

    # Disk usage
    frontend_data_mb = _dir_size_mb(FRONTEND_DATA)
    frontend_tiles_mb = _dir_size_mb(FRONTEND_TILES)
    nmt_data_mb = _dir_size_mb(DATA_NMT)
    cache_mb = _dir_size_mb(CACHE_DIR)

    status = "healthy" if db_status == "connected" else "unhealthy"

    return DashboardResponse(
        status=status,
        version="1.0.0",
        uptime_s=round(time.time() - _start_time, 1),
        database=db_status,
        tables=tables,
        disk={
            "frontend_data_mb": frontend_data_mb,
            "frontend_tiles_mb": frontend_tiles_mb,
            "nmt_data_mb": nmt_data_mb,
            "cache_mb": cache_mb,
            "total_mb": round(
                frontend_data_mb + frontend_tiles_mb + nmt_data_mb + cache_mb,
                2,
            ),
        },
    )


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------
class ResourcesResponse(BaseModel):
    """System resource usage response."""

    process: dict = Field(description="Process CPU/memory info")
    db_pool: dict = Field(description="Database connection pool stats")
    catchment_graph: dict = Field(description="Catchment graph status")
    db_size_mb: float = Field(description="Database size in MB")


@router.get("/resources", response_model=ResourcesResponse)
def resources(db: Session = Depends(get_db)) -> ResourcesResponse:
    """System resource usage."""
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
        pool = engine.pool
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
    cg_info: dict = {"loaded": cg.loaded, "nodes": 0, "threshold_m2": []}
    if cg.loaded:
        cg_info["nodes"] = cg._n
        if cg._threshold_m2 is not None:
            import numpy as np

            cg_info["threshold_m2"] = sorted(
                int(t) for t in np.unique(cg._threshold_m2)
            )

    # Database size
    try:
        result = db.execute(
            text("SELECT pg_database_size(current_database())")
        )
        db_size_bytes = result.scalar() or 0
        db_size_mb = round(db_size_bytes / (1024 * 1024), 2)
    except Exception:
        db_size_mb = 0.0

    return ResourcesResponse(
        process=process_info,
        db_pool=db_pool_info,
        catchment_graph=cg_info,
        db_size_mb=db_size_mb,
    )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
def _file_size_mb(path: Path) -> float:
    """Return single file size in MB, or 0 if not found."""
    if path.is_file():
        return round(path.stat().st_size / (1024 * 1024), 2)
    return 0.0


CLEANUP_TARGETS: dict[str, dict] = {
    "tiles": {
        "label": "MVT tiles",
        "path": FRONTEND_TILES,
        "type": "dir",
    },
    "overlays": {
        "label": "Overlay PNG + JSON + GeoJSON",
        "path": FRONTEND_DATA,
        "type": "glob",
        "patterns": ["*.png", "*.json", "*.geojson"],
    },
    "dem_tiles": {
        "label": "DEM raster tiles",
        "path": FRONTEND_DATA / "dem_tiles",
        "type": "dir",
    },
    "dem_mosaic": {
        "label": "DEM mosaic VRT",
        "path": DATA_NMT / "dem_mosaic.vrt",
        "type": "file",
    },
    "processed_data": {
        "label": "Processed rasters + hydro",
        "path": [DATA_NMT, DATA_HYDRO],
        "type": "multi_dir",
    },
    "db_tables": {
        "label": "Database tables (TRUNCATE)",
        "type": "db",
    },
    "cache": {
        "label": "Download cache (NMT, BDOT10k, HSG)",
        "path": CACHE_DIR,
        "type": "cache",
        "exclude_from_all": True,
    },
}

# Targets included when the frontend sends "all" — cache requires explicit opt-in
# because re-downloading is expensive.
ALL_CLEANUP_TARGETS = [
    k for k, v in CLEANUP_TARGETS.items() if not v.get("exclude_from_all")
]


def _estimate_target(target_key: str, db: Session | None = None) -> float:
    """Estimate size in MB for a cleanup target."""
    target = CLEANUP_TARGETS[target_key]
    ttype = target["type"]

    if ttype in ("dir", "cache"):
        return _dir_size_mb(target["path"])
    elif ttype == "multi_dir":
        return round(sum(_dir_size_mb(p) for p in target["path"]), 2)
    elif ttype == "file":
        return _file_size_mb(target["path"])
    elif ttype == "glob":
        base = target["path"]
        if not base.exists():
            return 0.0
        total = 0
        for pattern in target["patterns"]:
            for f in base.glob(pattern):
                total += f.stat().st_size
        return round(total / (1024 * 1024), 2)
    elif ttype == "db" and db is not None:
        try:
            result = db.execute(
                text("SELECT pg_database_size(current_database())")
            )
            return round((result.scalar() or 0) / (1024 * 1024), 2)
        except Exception:
            return 0.0
    return 0.0


class CleanupEstimateResponse(BaseModel):
    """Cleanup estimate response."""

    targets: list[dict] = Field(description="List of targets with size_mb")


class CleanupRequest(BaseModel):
    """Cleanup execution request."""

    targets: list[str] = Field(description="List of target keys to clean")


class CleanupResponse(BaseModel):
    """Cleanup execution response."""

    results: list[dict] = Field(description="Results per target")


@router.get("/cleanup/estimate", response_model=CleanupEstimateResponse)
def cleanup_estimate(
    db: Session = Depends(get_db),
) -> CleanupEstimateResponse:
    """Estimate cleanup sizes for all targets."""
    targets = []
    for key, info in CLEANUP_TARGETS.items():
        targets.append(
            {
                "key": key,
                "label": info["label"],
                "size_mb": _estimate_target(key, db),
            }
        )
    return CleanupEstimateResponse(targets=targets)


def _execute_cleanup_target(
    target_key: str, db: Session
) -> dict:
    """Execute cleanup for a single target, return result dict."""
    target = CLEANUP_TARGETS[target_key]
    ttype = target["type"]

    try:
        if ttype == "dir":
            path = target["path"]
            if path.exists():
                for child in path.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
            return {"key": target_key, "status": "ok"}

        elif ttype == "multi_dir":
            for path in target["path"]:
                if path.exists():
                    for child in path.iterdir():
                        if child.is_dir():
                            shutil.rmtree(child)
                        else:
                            child.unlink()
            return {"key": target_key, "status": "ok"}

        elif ttype == "file":
            path = target["path"]
            if path.is_file():
                path.unlink()
            return {"key": target_key, "status": "ok"}

        elif ttype == "glob":
            base = target["path"]
            if base.exists():
                for pattern in target["patterns"]:
                    for f in base.glob(pattern):
                        f.unlink()
            return {"key": target_key, "status": "ok"}

        elif ttype == "cache":
            path = target["path"]
            if path.exists():
                for subdir in path.iterdir():
                    if subdir.is_dir():
                        for child in subdir.iterdir():
                            if child.is_dir():
                                shutil.rmtree(child)
                            else:
                                child.unlink()
                    elif subdir.is_file():
                        subdir.unlink()
            return {"key": target_key, "status": "ok"}

        elif ttype == "db":
            table_list = ", ".join(_TABLE_NAMES)
            db.execute(text(f"TRUNCATE TABLE {table_list} CASCADE"))  # noqa: S608 — table names from hardcoded _TABLE_NAMES, not user input
            db.commit()
            return {"key": target_key, "status": "ok"}

        return {"key": target_key, "status": "error", "detail": "unknown type"}

    except Exception as e:
        return {"key": target_key, "status": "error", "detail": str(e)}


@router.post("/cleanup", response_model=CleanupResponse)
def cleanup_execute(
    request: CleanupRequest,
    db: Session = Depends(get_db),
) -> CleanupResponse:
    """Execute cleanup for selected targets."""
    # Validate targets
    for target_key in request.targets:
        if target_key not in CLEANUP_TARGETS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown cleanup target: {target_key}",
            )

    results = []
    for target_key in request.targets:
        result = _execute_cleanup_target(target_key, db)
        results.append(result)

    return CleanupResponse(results=results)


# ---------------------------------------------------------------------------
# Boundary file upload
# ---------------------------------------------------------------------------
BOUNDARY_DIR = Path("data/boundary")
ALLOWED_BOUNDARY_EXTENSIONS = {".gpkg", ".geojson", ".json", ".zip"}
MAX_UPLOAD_SIZE_MB = 50


@router.post("/bootstrap/upload-boundary")
async def upload_boundary(
    file: UploadFile = File(...),
    _admin: None = Depends(verify_admin_key),
) -> dict:
    """Upload and validate a boundary file. Returns metadata + filename."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    # Validate extension
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_BOUNDARY_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid file type: {suffix}. "
                f"Allowed: {', '.join(sorted(ALLOWED_BOUNDARY_EXTENSIONS))}"
            ),
        )

    # Read file with size limit
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_UPLOAD_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"File too large: {size_mb:.1f} MB (max {MAX_UPLOAD_SIZE_MB} MB)",
        )

    # Sanitize filename
    safe_name = f"{uuid.uuid4()}_{Path(file.filename).name}"
    BOUNDARY_DIR.mkdir(parents=True, exist_ok=True)
    save_path = BOUNDARY_DIR / safe_name

    # Verify path is within boundary dir (prevent traversal)
    if not save_path.resolve().is_relative_to(BOUNDARY_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Save file
    save_path.write_bytes(content)

    try:
        from core.boundary import validate_boundary_file

        metadata = validate_boundary_file(save_path)
    except (ValueError, Exception) as e:
        # Clean up on validation failure
        save_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400, detail=f"Invalid boundary file: {e}"
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
SHEET_CODE_PATTERN = re.compile(r'^[A-Za-z0-9\-]{3,30}$')

_HISTORY_MAX = 10

_bootstrap_state: dict = {
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


def _read_process_output(process: subprocess.Popen, state: dict) -> None:
    """Background thread: read stdout lines into state."""
    try:
        for line in process.stdout:
            stripped = line.rstrip("\n")
            state["log_lines"].append(stripped)
    except Exception:
        pass
    finally:
        process.wait()
        state["process"] = None
        if process.returncode == 0:
            state["status"] = "completed"
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
    params: dict | None = Field(description="Parameters used")
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
    waterbody_mode: str | None = Field(
        default=None, description="drain or keep"
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


@router.post("/bootstrap/start", response_model=BootstrapStartResponse)
def bootstrap_start(request: BootstrapStartRequest) -> BootstrapStartResponse:
    """Start bootstrap subprocess."""
    if _bootstrap_state["status"] == "running":
        raise HTTPException(
            status_code=409, detail="Bootstrap is already running"
        )

    # Validate input: exactly one of bbox, sheets, boundary_file
    sources = sum([
        request.bbox is not None,
        request.sheets is not None,
        request.boundary_file is not None,
    ])
    if sources != 1:
        raise HTTPException(
            status_code=400,
            detail="Exactly one of bbox, sheets, or boundary_file must be provided",
        )

    # Validate sheet codes before passing to subprocess
    if request.sheets:
        for sheet in request.sheets:
            if not SHEET_CODE_PATTERN.match(sheet):
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid sheet code: {sheet}",
                )

    # Build command
    cmd = [str(VENV_PYTHON), "-m", "scripts.bootstrap"]

    if request.bbox:
        try:
            _validate_bbox(request.bbox)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        cmd.extend(["--bbox", request.bbox])
    elif request.sheets:
        cmd.extend(["--sheets"] + request.sheets)
    elif request.boundary_file:
        boundary_path = BOUNDARY_DIR / request.boundary_file
        if not boundary_path.exists():
            raise HTTPException(
                status_code=400,
                detail="Boundary file not found. Upload first.",
            )
        if not boundary_path.resolve().is_relative_to(BOUNDARY_DIR.resolve()):
            raise HTTPException(status_code=400, detail="Invalid boundary filename")
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
        raise HTTPException(
            status_code=500, detail=f"Cannot start bootstrap: {e}"
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


@router.post("/bootstrap/cancel")
def bootstrap_cancel() -> dict:
    """Cancel running bootstrap process."""
    proc = _bootstrap_state["process"]
    if proc is None or _bootstrap_state["status"] != "running":
        raise HTTPException(
            status_code=409, detail="No bootstrap process running"
        )

    proc.send_signal(signal.SIGTERM)
    _bootstrap_state["status"] = "failed"
    _bootstrap_state["log_lines"].append("[CANCELLED by admin]")

    return {"status": "cancelled", "pid": proc.pid}


@router.get("/bootstrap/stream")
async def bootstrap_stream() -> StreamingResponse:
    """SSE stream of bootstrap log lines."""

    async def _event_generator():
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
