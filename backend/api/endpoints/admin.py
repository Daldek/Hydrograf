"""
Admin panel API endpoints.

Provides dashboard, resources, cleanup, and bootstrap management
for the Hydrograf administration panel.
"""

import os
import time
from pathlib import Path

import psutil
from fastapi import APIRouter, Depends
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
