"""
Admin panel API endpoints.

Provides dashboard, resources, cleanup, and bootstrap management
for the Hydrograf administration panel.
"""

import os
import shutil
import time
from pathlib import Path

import psutil
from fastapi import APIRouter, Depends, HTTPException
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
            result = db.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
            tables[table] = result.scalar() or 0
        except Exception:
            tables[table] = 0

    # Disk usage
    frontend_data_mb = _dir_size_mb(FRONTEND_DATA)
    frontend_tiles_mb = _dir_size_mb(FRONTEND_TILES)
    nmt_data_mb = _dir_size_mb(DATA_NMT)

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
            "total_mb": round(
                frontend_data_mb + frontend_tiles_mb + nmt_data_mb, 2
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
        "label": "Overlay PNG + JSON",
        "path": FRONTEND_DATA,
        "type": "glob",
        "patterns": ["*.png", "*.json"],
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
    "db_tables": {
        "label": "Database tables (TRUNCATE)",
        "type": "db",
    },
}


def _estimate_target(target_key: str, db: Session | None = None) -> float:
    """Estimate size in MB for a cleanup target."""
    target = CLEANUP_TARGETS[target_key]
    ttype = target["type"]

    if ttype == "dir":
        return _dir_size_mb(target["path"])
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
                shutil.rmtree(path)
                path.mkdir(parents=True, exist_ok=True)
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

        elif ttype == "db":
            table_list = ", ".join(_TABLE_NAMES)
            db.execute(text(f"TRUNCATE TABLE {table_list} CASCADE"))  # noqa: S608
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
