"""
Admin panel API endpoints.

Provides dashboard, resources, cleanup, and bootstrap management
for the Hydrograf administration panel.
"""

import time
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.dependencies.admin_auth import verify_admin_key
from core.database import get_db

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
