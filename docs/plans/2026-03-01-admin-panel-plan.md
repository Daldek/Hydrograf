# Panel Administracyjno-Diagnostyczny — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Panel webowy `/admin` z 4 sekcjami (Dashboard, Bootstrap, Zasoby, Czyszczenie) + backend API `/api/admin/*` z auth API key + SSE dla logów bootstrap.

**Architecture:** Nowy router FastAPI `/api/admin/*` z middleware API key (header `X-Admin-Key`). Bootstrap uruchamiany jako subprocess — stdout parsowany i streamowany przez SSE. Frontend: osobna strona `admin.html`, Vanilla JS (IIFE na `window.Hydrograf.admin`), glassmorphism CSS.

**Tech Stack:** FastAPI, SSE (sse-starlette), psutil, SQLAlchemy, Vanilla JS, Bootstrap 5.3.3, CSS glassmorphism

---

## Task 1: Admin API key middleware + Settings

**Files:**
- Modify: `backend/core/config.py` — dodaj `admin_api_key` do Settings
- Create: `backend/api/dependencies/admin_auth.py` — dependency do weryfikacji klucza
- Test: `backend/tests/unit/test_admin_auth.py`

**Step 1: Write the failing test**

Plik `backend/tests/unit/test_admin_auth.py`:

```python
"""Tests for admin API key authentication dependency."""

import pytest
from fastapi import HTTPException

from api.dependencies.admin_auth import verify_admin_key


class TestVerifyAdminKey:
    """Tests for verify_admin_key dependency."""

    def test_valid_key_passes(self):
        """Valid API key should not raise."""
        verify_admin_key(x_admin_key="test-secret-key", expected_key="test-secret-key")

    def test_missing_key_raises_401(self):
        """Missing API key should raise 401."""
        with pytest.raises(HTTPException) as exc_info:
            verify_admin_key(x_admin_key=None, expected_key="test-secret-key")
        assert exc_info.value.status_code == 401

    def test_wrong_key_raises_403(self):
        """Wrong API key should raise 403."""
        with pytest.raises(HTTPException) as exc_info:
            verify_admin_key(x_admin_key="wrong-key", expected_key="test-secret-key")
        assert exc_info.value.status_code == 403

    def test_empty_key_raises_401(self):
        """Empty string API key should raise 401."""
        with pytest.raises(HTTPException) as exc_info:
            verify_admin_key(x_admin_key="", expected_key="test-secret-key")
        assert exc_info.value.status_code == 401

    def test_no_configured_key_disables_auth(self):
        """When no key is configured (empty), auth is disabled — any request passes."""
        verify_admin_key(x_admin_key=None, expected_key="")
```

**Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.dependencies'`

**Step 3: Write minimal implementation**

Utwórz `backend/api/dependencies/__init__.py` (pusty plik).

Plik `backend/api/dependencies/admin_auth.py`:

```python
"""Admin API key authentication dependency."""

from fastapi import Header, HTTPException

from core.config import get_settings


def verify_admin_key(
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
    expected_key: str | None = None,
) -> None:
    """
    Verify admin API key from X-Admin-Key header.

    If ADMIN_API_KEY is not configured (empty), auth is disabled.

    Raises
    ------
    HTTPException
        401 if key is missing, 403 if key is wrong.
    """
    if expected_key is None:
        expected_key = get_settings().admin_api_key

    # No key configured — auth disabled
    if not expected_key:
        return

    if not x_admin_key:
        raise HTTPException(status_code=401, detail="Brak klucza API (X-Admin-Key)")

    if x_admin_key != expected_key:
        raise HTTPException(status_code=403, detail="Nieprawidlowy klucz API")
```

Dodaj do `backend/core/config.py` w klasie `Settings` (po linii `dem_path`):

```python
    # Admin
    admin_api_key: str = ""
```

**Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_auth.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add backend/api/dependencies/__init__.py backend/api/dependencies/admin_auth.py backend/core/config.py backend/tests/unit/test_admin_auth.py
git commit -m "feat(api): admin API key auth dependency (ADR-034)"
```

---

## Task 2: Dashboard endpoint — `/api/admin/dashboard`

**Files:**
- Create: `backend/api/endpoints/admin.py` — router z endpointem dashboard
- Modify: `backend/api/main.py:16-24` — dodaj import admin + include_router
- Test: `backend/tests/unit/test_admin_dashboard.py`

**Step 1: Write the failing test**

Plik `backend/tests/unit/test_admin_dashboard.py`:

```python
"""Tests for admin dashboard endpoint."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def admin_client():
    """Create test client with admin auth disabled."""
    with patch("core.config.get_settings") as mock_settings:
        s = MagicMock()
        s.admin_api_key = ""
        s.database_url = "postgresql://test:test@localhost/test"
        s.log_level = "INFO"
        s.cors_origins = "http://localhost"
        s.db_statement_timeout_ms = 30000
        s.dem_path = "/tmp/dem.vrt"
        mock_settings.return_value = s

        from api.endpoints.admin import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router, prefix="/api/admin")
        yield TestClient(app)


class TestDashboardEndpoint:
    """Tests for GET /api/admin/dashboard."""

    def test_dashboard_returns_status(self, admin_client):
        """Dashboard should return system status fields."""
        with patch("api.endpoints.admin.get_db") as mock_get_db:
            mock_db = MagicMock()
            # Mock row counts
            mock_db.execute.return_value.scalar.return_value = 1000
            mock_get_db.return_value = iter([mock_db])

            response = admin_client.get("/api/admin/dashboard")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "tables" in data
        assert "disk" in data

    def test_dashboard_table_counts(self, admin_client):
        """Dashboard should return row counts for each table."""
        with patch("api.endpoints.admin.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.execute.return_value.scalar.return_value = 42
            mock_get_db.return_value = iter([mock_db])

            response = admin_client.get("/api/admin/dashboard")

        data = response.json()
        tables = data["tables"]
        assert "stream_network" in tables
        assert "depressions" in tables
        assert "land_cover" in tables

    def test_dashboard_disk_usage(self, admin_client):
        """Dashboard should return disk usage info."""
        with patch("api.endpoints.admin.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.execute.return_value.scalar.return_value = 0
            mock_get_db.return_value = iter([mock_db])

            with patch("api.endpoints.admin._dir_size_mb", return_value=123.4):
                response = admin_client.get("/api/admin/dashboard")

        data = response.json()
        assert "disk" in data
```

**Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_dashboard.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.endpoints.admin'`

**Step 3: Write minimal implementation**

Plik `backend/api/endpoints/admin.py`:

```python
"""
Admin panel API endpoints.

Provides system diagnostics, bootstrap management, resource monitoring,
and data cleanup for the admin panel.
"""

import os
import time
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.dependencies.admin_auth import verify_admin_key
from core.database import get_db

router = APIRouter(dependencies=[Depends(verify_admin_key)])

# --- Startup time tracking ---
_start_time = time.time()

# --- Path constants ---
PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_DATA = PROJECT_ROOT / "frontend" / "data"
FRONTEND_TILES = PROJECT_ROOT / "frontend" / "tiles"
DATA_NMT = PROJECT_ROOT / "data" / "nmt"


def _dir_size_mb(path: Path) -> float:
    """Calculate directory size in MB. Returns 0 if path doesn't exist."""
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return round(total / (1024 * 1024), 1)


# --- Response Models ---

class TableCounts(BaseModel):
    stream_network: int = 0
    stream_catchments: int = 0
    depressions: int = 0
    land_cover: int = 0
    soil_hsg: int = 0
    precipitation_data: int = 0


class DiskUsage(BaseModel):
    frontend_data_mb: float = 0.0
    frontend_tiles_mb: float = 0.0
    nmt_data_mb: float = 0.0
    total_mb: float = 0.0


class DashboardResponse(BaseModel):
    status: str
    version: str = "1.0.0"
    uptime_s: float = Field(..., description="API uptime in seconds")
    database: str
    tables: TableCounts
    disk: DiskUsage


# --- Dashboard Endpoint ---

TABLE_NAMES = [
    "stream_network",
    "stream_catchments",
    "depressions",
    "land_cover",
    "soil_hsg",
    "precipitation_data",
]


@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(db: Session = Depends(get_db)) -> DashboardResponse:
    """System overview: health, DB row counts, disk usage."""
    # DB health
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {e}"

    # Row counts
    counts = {}
    for table in TABLE_NAMES:
        try:
            result = db.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
            counts[table] = result.scalar()
        except Exception:
            counts[table] = -1

    # Disk usage
    data_mb = _dir_size_mb(FRONTEND_DATA)
    tiles_mb = _dir_size_mb(FRONTEND_TILES)
    nmt_mb = _dir_size_mb(DATA_NMT)

    return DashboardResponse(
        status="healthy" if db_status == "connected" else "unhealthy",
        uptime_s=round(time.time() - _start_time, 1),
        database=db_status,
        tables=TableCounts(**counts),
        disk=DiskUsage(
            frontend_data_mb=data_mb,
            frontend_tiles_mb=tiles_mb,
            nmt_data_mb=nmt_mb,
            total_mb=round(data_mb + tiles_mb + nmt_mb, 1),
        ),
    )
```

Modyfikuj `backend/api/main.py` — dodaj import i router:

W bloku importów (linia 16-24) dodaj `admin`:
```python
from api.endpoints import (
    admin,
    depressions,
    health,
    hydrograph,
    profile,
    select_stream,
    tiles,
    watershed,
)
```

Po ostatnim `include_router` (po select_stream, ~linia 115) dodaj:
```python
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
```

**Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_dashboard.py -v`
Expected: 3 passed

**Step 5: Commit**

```bash
git add backend/api/endpoints/admin.py backend/api/main.py backend/tests/unit/test_admin_dashboard.py
git commit -m "feat(api): admin dashboard endpoint — health, row counts, disk usage"
```

---

## Task 3: Resources endpoint — `/api/admin/resources`

**Files:**
- Modify: `backend/api/endpoints/admin.py` — dodaj endpoint /resources
- Test: `backend/tests/unit/test_admin_resources.py`

**Step 1: Write the failing test**

Plik `backend/tests/unit/test_admin_resources.py`:

```python
"""Tests for admin resources endpoint."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def admin_client():
    """Create test client with admin auth disabled."""
    with patch("core.config.get_settings") as mock_settings:
        s = MagicMock()
        s.admin_api_key = ""
        s.database_url = "postgresql://test:test@localhost/test"
        s.log_level = "INFO"
        s.cors_origins = "http://localhost"
        s.db_statement_timeout_ms = 30000
        s.dem_path = "/tmp/dem.vrt"
        mock_settings.return_value = s

        from api.endpoints.admin import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router, prefix="/api/admin")
        yield TestClient(app)


class TestResourcesEndpoint:
    """Tests for GET /api/admin/resources."""

    def test_resources_returns_process_info(self, admin_client):
        """Resources should return CPU and memory info."""
        with patch("api.endpoints.admin.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.execute.return_value.scalar.return_value = 5
            mock_get_db.return_value = iter([mock_db])

            response = admin_client.get("/api/admin/resources")

        assert response.status_code == 200
        data = response.json()
        assert "process" in data
        assert "cpu_percent" in data["process"]
        assert "memory_mb" in data["process"]

    def test_resources_returns_db_pool_info(self, admin_client):
        """Resources should return database pool info."""
        with patch("api.endpoints.admin.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.execute.return_value.scalar.return_value = 5
            mock_get_db.return_value = iter([mock_db])

            response = admin_client.get("/api/admin/resources")

        data = response.json()
        assert "db_pool" in data

    def test_resources_returns_graph_info(self, admin_client):
        """Resources should return CatchmentGraph cache info."""
        with patch("api.endpoints.admin.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.execute.return_value.scalar.return_value = 5
            mock_get_db.return_value = iter([mock_db])

            response = admin_client.get("/api/admin/resources")

        data = response.json()
        assert "catchment_graph" in data
```

**Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_resources.py -v`
Expected: FAIL (endpoint not found, 404 or AttributeError)

**Step 3: Write minimal implementation**

Dodaj do `backend/api/endpoints/admin.py`:

Na górze, do importów dodaj:
```python
import psutil
from core.catchment_graph import get_catchment_graph
from core.database import get_db, get_db_engine
```

Dodaj modele i endpoint:
```python
class ProcessInfo(BaseModel):
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_percent: float = 0.0
    pid: int = 0
    threads: int = 0


class DbPoolInfo(BaseModel):
    pool_size: int = 0
    checked_out: int = 0
    overflow: int = 0
    checked_in: int = 0


class GraphInfo(BaseModel):
    loaded: bool = False
    nodes: int = 0
    threshold_m2: int = 0


class ResourcesResponse(BaseModel):
    process: ProcessInfo
    db_pool: DbPoolInfo
    catchment_graph: GraphInfo
    db_size_mb: float = 0.0


@router.get("/resources", response_model=ResourcesResponse)
def get_resources(db: Session = Depends(get_db)) -> ResourcesResponse:
    """System resource usage: process, DB pool, graph cache."""
    # Process info
    proc = psutil.Process()
    mem = proc.memory_info()
    process_info = ProcessInfo(
        cpu_percent=proc.cpu_percent(interval=0.1),
        memory_mb=round(mem.rss / (1024 * 1024), 1),
        memory_percent=round(proc.memory_percent(), 1),
        pid=proc.pid,
        threads=proc.num_threads(),
    )

    # DB pool
    engine = get_db_engine()
    pool = engine.pool
    db_pool = DbPoolInfo(
        pool_size=pool.size(),
        checked_out=pool.checkedout(),
        overflow=pool.overflow(),
        checked_in=pool.checkedin(),
    )

    # DB size
    try:
        result = db.execute(text("SELECT pg_database_size(current_database())"))
        db_bytes = result.scalar() or 0
        db_size_mb = round(db_bytes / (1024 * 1024), 1)
    except Exception:
        db_size_mb = 0.0

    # CatchmentGraph
    cg = get_catchment_graph()
    graph_info = GraphInfo(
        loaded=cg.is_loaded if hasattr(cg, "is_loaded") else len(cg._graph) > 0,
        nodes=len(cg._graph),
        threshold_m2=cg._threshold_m2 if hasattr(cg, "_threshold_m2") else 0,
    )

    return ResourcesResponse(
        process=process_info,
        db_pool=db_pool,
        catchment_graph=graph_info,
        db_size_mb=db_size_mb,
    )
```

Dodaj `psutil` do `backend/pyproject.toml` w sekcji `[project.optional-dependencies]` dev albo do `backend/requirements.txt` (runtime):

```
psutil>=5.9
```

**Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/pip install psutil && cd backend && .venv/bin/python -m pytest tests/unit/test_admin_resources.py -v`
Expected: 3 passed

**Step 5: Commit**

```bash
git add backend/api/endpoints/admin.py backend/tests/unit/test_admin_resources.py backend/requirements.txt
git commit -m "feat(api): admin resources endpoint — process, DB pool, graph cache"
```

---

## Task 4: Cleanup endpoints — estimate + execute

**Files:**
- Modify: `backend/api/endpoints/admin.py` — dodaj /cleanup/estimate i /cleanup
- Test: `backend/tests/unit/test_admin_cleanup.py`

**Step 1: Write the failing test**

Plik `backend/tests/unit/test_admin_cleanup.py`:

```python
"""Tests for admin cleanup endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def admin_client():
    """Create test client with admin auth disabled."""
    with patch("core.config.get_settings") as mock_settings:
        s = MagicMock()
        s.admin_api_key = ""
        s.database_url = "postgresql://test:test@localhost/test"
        s.log_level = "INFO"
        s.cors_origins = "http://localhost"
        s.db_statement_timeout_ms = 30000
        s.dem_path = "/tmp/dem.vrt"
        mock_settings.return_value = s

        from api.endpoints.admin import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router, prefix="/api/admin")
        yield TestClient(app)


class TestCleanupEstimate:
    """Tests for GET /api/admin/cleanup/estimate."""

    def test_estimate_returns_targets(self, admin_client):
        """Estimate should list cleanup targets with sizes."""
        with patch("api.endpoints.admin._dir_size_mb", return_value=50.0):
            response = admin_client.get("/api/admin/cleanup/estimate")

        assert response.status_code == 200
        data = response.json()
        assert "targets" in data
        assert len(data["targets"]) > 0
        for target in data["targets"]:
            assert "id" in target
            assert "label" in target
            assert "size_mb" in target


class TestCleanupExecute:
    """Tests for POST /api/admin/cleanup."""

    def test_cleanup_requires_targets(self, admin_client):
        """Cleanup without targets should return 422."""
        response = admin_client.post("/api/admin/cleanup", json={})
        assert response.status_code == 422

    def test_cleanup_invalid_target(self, admin_client):
        """Cleanup with unknown target should return 400."""
        response = admin_client.post(
            "/api/admin/cleanup", json={"targets": ["nonexistent"]}
        )
        assert response.status_code == 400

    def test_cleanup_tiles_removes_dir(self, admin_client):
        """Cleanup tiles target should remove tile directories."""
        with (
            patch("api.endpoints.admin.get_db") as mock_get_db,
            patch("shutil.rmtree") as mock_rmtree,
            patch("pathlib.Path.exists", return_value=True),
        ):
            mock_db = MagicMock()
            mock_get_db.return_value = iter([mock_db])

            response = admin_client.post(
                "/api/admin/cleanup", json={"targets": ["tiles"]}
            )

        assert response.status_code == 200
        data = response.json()
        assert "tiles" in [r["target"] for r in data["results"]]
```

**Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_cleanup.py -v`
Expected: FAIL (endpoints not found)

**Step 3: Write minimal implementation**

Dodaj do `backend/api/endpoints/admin.py`:

Na górze dodaj import:
```python
import shutil
```

Dodaj modele i endpointy:
```python
# --- Cleanup ---

CLEANUP_TARGETS = {
    "tiles": {
        "label": "Kafelki MVT",
        "paths": [FRONTEND_TILES],
    },
    "overlays": {
        "label": "Overlays PNG + JSON",
        "paths": [
            FRONTEND_DATA / "dem.png",
            FRONTEND_DATA / "dem.json",
            FRONTEND_DATA / "streams.png",
            FRONTEND_DATA / "streams.json",
            FRONTEND_DATA / "depressions.png",
            FRONTEND_DATA / "depressions.json",
        ],
    },
    "dem_tiles": {
        "label": "Kafelki DEM (hillshade)",
        "paths": [FRONTEND_DATA / "dem_tiles"],
    },
    "dem_mosaic": {
        "label": "Mozaika DEM (VRT + TIF)",
        "paths": [DATA_NMT / "dem_mosaic.vrt"],
    },
    "db_tables": {
        "label": "Dane w tabelach DB (TRUNCATE)",
        "paths": [],  # handled separately
    },
}


class CleanupTarget(BaseModel):
    id: str
    label: str
    size_mb: float


class CleanupEstimateResponse(BaseModel):
    targets: list[CleanupTarget]


class CleanupRequest(BaseModel):
    targets: list[str] = Field(..., min_length=1)


class CleanupResult(BaseModel):
    target: str
    success: bool
    detail: str = ""


class CleanupResponse(BaseModel):
    results: list[CleanupResult]


@router.get("/cleanup/estimate", response_model=CleanupEstimateResponse)
def cleanup_estimate() -> CleanupEstimateResponse:
    """Estimate disk usage per cleanup target."""
    targets = []
    for tid, cfg in CLEANUP_TARGETS.items():
        size = 0.0
        for p in cfg["paths"]:
            path = Path(p)
            if path.is_dir():
                size += _dir_size_mb(path)
            elif path.is_file():
                size += round(path.stat().st_size / (1024 * 1024), 2)
        targets.append(CleanupTarget(id=tid, label=cfg["label"], size_mb=round(size, 1)))
    return CleanupEstimateResponse(targets=targets)


@router.post("/cleanup", response_model=CleanupResponse)
def cleanup_execute(
    req: CleanupRequest,
    db: Session = Depends(get_db),
) -> CleanupResponse:
    """Delete selected data targets."""
    results = []
    for target_id in req.targets:
        if target_id not in CLEANUP_TARGETS:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail=f"Nieznany target: {target_id}")

        cfg = CLEANUP_TARGETS[target_id]
        try:
            if target_id == "db_tables":
                for table in TABLE_NAMES:
                    db.execute(text(f"TRUNCATE TABLE {table} CASCADE"))  # noqa: S608
                db.commit()
                results.append(CleanupResult(
                    target=target_id, success=True, detail="TRUNCATE 6 tabel"
                ))
            else:
                removed = 0
                for p in cfg["paths"]:
                    path = Path(p)
                    if path.is_dir():
                        shutil.rmtree(path)
                        path.mkdir(parents=True, exist_ok=True)
                        removed += 1
                    elif path.is_file():
                        path.unlink()
                        removed += 1
                results.append(CleanupResult(
                    target=target_id, success=True, detail=f"Usunieto {removed} elementow"
                ))
        except Exception as e:
            results.append(CleanupResult(target=target_id, success=False, detail=str(e)))

    return CleanupResponse(results=results)
```

**Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_cleanup.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add backend/api/endpoints/admin.py backend/tests/unit/test_admin_cleanup.py
git commit -m "feat(api): admin cleanup endpoints — estimate + execute (tiles, overlays, DB)"
```

---

## Task 5: Bootstrap subprocess manager + SSE stream

**Files:**
- Modify: `backend/api/endpoints/admin.py` — dodaj /bootstrap/start, /status, /stream, /cancel
- Test: `backend/tests/unit/test_admin_bootstrap.py`

**Step 1: Write the failing test**

Plik `backend/tests/unit/test_admin_bootstrap.py`:

```python
"""Tests for admin bootstrap management endpoints."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def admin_client():
    """Create test client with admin auth disabled."""
    with patch("core.config.get_settings") as mock_settings:
        s = MagicMock()
        s.admin_api_key = ""
        s.database_url = "postgresql://test:test@localhost/test"
        s.log_level = "INFO"
        s.cors_origins = "http://localhost"
        s.db_statement_timeout_ms = 30000
        s.dem_path = "/tmp/dem.vrt"
        mock_settings.return_value = s

        from api.endpoints.admin import router, _bootstrap_state
        from fastapi import FastAPI

        # Reset state between tests
        _bootstrap_state["process"] = None
        _bootstrap_state["status"] = "idle"
        _bootstrap_state["log_lines"] = []
        _bootstrap_state["started_at"] = None
        _bootstrap_state["params"] = {}
        _bootstrap_state["history"] = []

        app = FastAPI()
        app.include_router(router, prefix="/api/admin")
        yield TestClient(app)


class TestBootstrapStatus:
    """Tests for GET /api/admin/bootstrap/status."""

    def test_status_idle(self, admin_client):
        """Status should return idle when no bootstrap is running."""
        response = admin_client.get("/api/admin/bootstrap/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "idle"
        assert data["pid"] is None

    def test_status_while_running(self, admin_client):
        """Status should show running state."""
        from api.endpoints.admin import _bootstrap_state

        _bootstrap_state["status"] = "running"
        _bootstrap_state["started_at"] = 1000000.0

        response = admin_client.get("/api/admin/bootstrap/status")
        data = response.json()
        assert data["status"] == "running"


class TestBootstrapStart:
    """Tests for POST /api/admin/bootstrap/start."""

    def test_start_requires_bbox_or_sheets(self, admin_client):
        """Start without bbox or sheets should return 400."""
        response = admin_client.post("/api/admin/bootstrap/start", json={})
        assert response.status_code == 400

    def test_start_rejects_when_running(self, admin_client):
        """Start while already running should return 409."""
        from api.endpoints.admin import _bootstrap_state

        _bootstrap_state["status"] = "running"

        response = admin_client.post(
            "/api/admin/bootstrap/start",
            json={"bbox": "16.9,52.3,17.4,52.6"},
        )
        assert response.status_code == 409

    def test_start_validates_bbox_format(self, admin_client):
        """Start with invalid bbox should return 400."""
        response = admin_client.post(
            "/api/admin/bootstrap/start",
            json={"bbox": "invalid"},
        )
        assert response.status_code == 400


class TestBootstrapCancel:
    """Tests for POST /api/admin/bootstrap/cancel."""

    def test_cancel_when_idle(self, admin_client):
        """Cancel when no process running should return 409."""
        response = admin_client.post("/api/admin/bootstrap/cancel")
        assert response.status_code == 409
```

**Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_bootstrap.py -v`
Expected: FAIL (endpoints/state not found)

**Step 3: Write minimal implementation**

Dodaj do `backend/api/endpoints/admin.py`:

Na górze dodaj importy:
```python
import asyncio
import re
import signal
import subprocess

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
```

Dodaj state i endpointy:
```python
# --- Bootstrap State (in-memory, singleton) ---

_bootstrap_state: dict = {
    "process": None,       # subprocess.Popen | None
    "status": "idle",      # idle | running | completed | failed
    "log_lines": [],       # list[str]
    "started_at": None,    # float (time.time) | None
    "params": {},          # dict with bbox/sheets/options
    "history": [],         # list[dict] — last N runs
}

_HISTORY_MAX = 10


class BootstrapStartRequest(BaseModel):
    bbox: str | None = None
    sheets: list[str] | None = None
    skip_infra: bool = True
    skip_serve: bool = True
    skip_precipitation: bool = False
    skip_tiles: bool = False
    waterbody_mode: str | None = None


class BootstrapStatusResponse(BaseModel):
    status: str
    pid: int | None = None
    started_at: float | None = None
    elapsed_s: float | None = None
    log_lines_count: int = 0
    params: dict = {}
    history: list[dict] = []


def _validate_bbox(bbox: str) -> bool:
    """Validate bbox format: min_lon,min_lat,max_lon,max_lat."""
    parts = bbox.split(",")
    if len(parts) != 4:
        return False
    try:
        vals = [float(p) for p in parts]
        return vals[0] < vals[2] and vals[1] < vals[3]
    except ValueError:
        return False


def _build_bootstrap_cmd(params: BootstrapStartRequest) -> list[str]:
    """Build bootstrap.py command line arguments."""
    cmd = [
        str(Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python"),
        "-m", "scripts.bootstrap",
    ]
    if params.bbox:
        cmd += ["--bbox", params.bbox]
    if params.sheets:
        cmd += ["--sheets"] + params.sheets
    if params.skip_infra:
        cmd += ["--skip-infra"]
    if params.skip_serve:
        cmd += ["--skip-serve"]
    if params.skip_precipitation:
        cmd += ["--skip-precipitation"]
    if params.skip_tiles:
        cmd += ["--skip-tiles"]
    if params.waterbody_mode:
        cmd += ["--waterbody-mode", params.waterbody_mode]
    return cmd


def _run_bootstrap_subprocess(params: BootstrapStartRequest) -> None:
    """Launch bootstrap as subprocess and capture output."""
    cmd = _build_bootstrap_cmd(params)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    _bootstrap_state["process"] = proc
    _bootstrap_state["status"] = "running"
    _bootstrap_state["log_lines"] = []
    _bootstrap_state["started_at"] = time.time()
    _bootstrap_state["params"] = params.model_dump(exclude_none=True)

    import threading

    def _reader():
        try:
            for line in proc.stdout:
                _bootstrap_state["log_lines"].append(line.rstrip("\n"))
            proc.wait()
            exit_code = proc.returncode
            _bootstrap_state["status"] = "completed" if exit_code == 0 else "failed"
            _bootstrap_state["log_lines"].append(
                f"--- Proces zakonczony (exit code: {exit_code}) ---"
            )
        except Exception as e:
            _bootstrap_state["status"] = "failed"
            _bootstrap_state["log_lines"].append(f"--- Blad: {e} ---")
        finally:
            elapsed = time.time() - (_bootstrap_state["started_at"] or time.time())
            _bootstrap_state["history"].insert(0, {
                "status": _bootstrap_state["status"],
                "started_at": _bootstrap_state["started_at"],
                "elapsed_s": round(elapsed, 1),
                "params": _bootstrap_state["params"],
            })
            if len(_bootstrap_state["history"]) > _HISTORY_MAX:
                _bootstrap_state["history"] = _bootstrap_state["history"][:_HISTORY_MAX]
            _bootstrap_state["process"] = None

    threading.Thread(target=_reader, daemon=True).start()


@router.get("/bootstrap/status", response_model=BootstrapStatusResponse)
def bootstrap_status() -> BootstrapStatusResponse:
    """Current bootstrap process status."""
    elapsed = None
    if _bootstrap_state["started_at"] and _bootstrap_state["status"] == "running":
        elapsed = round(time.time() - _bootstrap_state["started_at"], 1)
    elif _bootstrap_state["started_at"] and _bootstrap_state["status"] in ("completed", "failed"):
        # Use last history entry for elapsed
        if _bootstrap_state["history"]:
            elapsed = _bootstrap_state["history"][0].get("elapsed_s")

    pid = None
    if _bootstrap_state["process"] is not None:
        pid = _bootstrap_state["process"].pid

    return BootstrapStatusResponse(
        status=_bootstrap_state["status"],
        pid=pid,
        started_at=_bootstrap_state["started_at"],
        elapsed_s=elapsed,
        log_lines_count=len(_bootstrap_state["log_lines"]),
        params=_bootstrap_state["params"],
        history=_bootstrap_state["history"],
    )


@router.post("/bootstrap/start")
def bootstrap_start(req: BootstrapStartRequest) -> dict:
    """Start bootstrap pipeline as subprocess."""
    if _bootstrap_state["status"] == "running":
        raise HTTPException(status_code=409, detail="Bootstrap juz uruchomiony")

    if not req.bbox and not req.sheets:
        raise HTTPException(status_code=400, detail="Wymagany bbox lub sheets")

    if req.bbox and not _validate_bbox(req.bbox):
        raise HTTPException(
            status_code=400,
            detail="Nieprawidlowy bbox: oczekiwany format min_lon,min_lat,max_lon,max_lat",
        )

    _run_bootstrap_subprocess(req)
    return {"status": "started", "pid": _bootstrap_state["process"].pid}


@router.post("/bootstrap/cancel")
def bootstrap_cancel() -> dict:
    """Cancel running bootstrap subprocess."""
    proc = _bootstrap_state["process"]
    if proc is None or _bootstrap_state["status"] != "running":
        raise HTTPException(status_code=409, detail="Brak uruchomionego procesu")

    proc.send_signal(signal.SIGTERM)
    _bootstrap_state["status"] = "failed"
    _bootstrap_state["log_lines"].append("--- Anulowano przez uzytkownika ---")
    return {"status": "cancelled"}


@router.get("/bootstrap/stream")
async def bootstrap_stream():
    """SSE stream of bootstrap log lines."""
    async def event_generator():
        last_idx = 0
        while True:
            lines = _bootstrap_state["log_lines"]
            if last_idx < len(lines):
                for i in range(last_idx, len(lines)):
                    yield f"data: {lines[i]}\n\n"
                last_idx = len(lines)

            if _bootstrap_state["status"] in ("completed", "failed", "idle"):
                yield f"event: done\ndata: {_bootstrap_state['status']}\n\n"
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

**Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_bootstrap.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add backend/api/endpoints/admin.py backend/tests/unit/test_admin_bootstrap.py
git commit -m "feat(api): admin bootstrap management — start/status/cancel/SSE stream"
```

---

## Task 6: Frontend — admin.html + admin.css

**Files:**
- Create: `frontend/admin.html` — strona panelu
- Create: `frontend/css/admin.css` — style admina

**Step 1: Create admin.html**

Plik `frontend/admin.html`:

```html
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hydrograf — Panel administracyjny</title>

    <link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>

    <!-- Bootstrap 5.3.3 CSS -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
          rel="stylesheet"
          integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH"
          crossorigin="anonymous">

    <link rel="stylesheet" href="css/glass.css">
    <link rel="stylesheet" href="css/admin.css">
</head>
<body>
    <!-- Auth overlay -->
    <div id="auth-overlay" class="auth-overlay">
        <div class="auth-card glass-panel">
            <h4>Panel administracyjny</h4>
            <p>Podaj klucz API:</p>
            <input type="password" id="auth-key-input" class="form-control mb-3"
                   placeholder="X-Admin-Key" autofocus>
            <button id="auth-submit" class="btn btn-primary w-100">Zaloguj</button>
            <div id="auth-error" class="text-danger mt-2" style="display:none"></div>
        </div>
    </div>

    <!-- Main content (hidden until auth) -->
    <div id="admin-main" style="display:none">
        <!-- Navbar -->
        <nav class="navbar navbar-dark bg-dark px-3 mb-0">
            <span class="navbar-brand">Hydrograf Admin</span>
            <div class="d-flex align-items-center gap-3">
                <span id="system-status" class="badge bg-secondary">...</span>
                <a href="/" class="btn btn-sm btn-outline-light">Mapa</a>
            </div>
        </nav>

        <div class="container-fluid p-3">
            <div class="row g-3">
                <!-- Dashboard -->
                <div class="col-md-6">
                    <div class="admin-card glass-panel p-3">
                        <h5>Dashboard</h5>
                        <div id="dashboard-content">
                            <div class="spinner-border spinner-border-sm"></div> Ladowanie...
                        </div>
                    </div>
                </div>

                <!-- Resources -->
                <div class="col-md-6">
                    <div class="admin-card glass-panel p-3">
                        <h5>Zasoby</h5>
                        <div id="resources-content">
                            <div class="spinner-border spinner-border-sm"></div> Ladowanie...
                        </div>
                    </div>
                </div>

                <!-- Bootstrap -->
                <div class="col-md-8">
                    <div class="admin-card glass-panel p-3">
                        <h5>Bootstrap Pipeline</h5>
                        <div id="bootstrap-content">
                            <!-- Form -->
                            <div id="bootstrap-form">
                                <div class="row g-2 mb-3">
                                    <div class="col-12">
                                        <label class="form-label">Bounding Box (WGS84)</label>
                                        <input type="text" id="bootstrap-bbox" class="form-control form-control-sm"
                                               placeholder="min_lon,min_lat,max_lon,max_lat"
                                               value="16.9279,52.3729,17.3825,52.5870">
                                    </div>
                                </div>
                                <div class="row g-2 mb-3">
                                    <div class="col-auto">
                                        <div class="form-check">
                                            <input type="checkbox" id="skip-precipitation" class="form-check-input">
                                            <label class="form-check-label" for="skip-precipitation">Pomin opady</label>
                                        </div>
                                    </div>
                                    <div class="col-auto">
                                        <div class="form-check">
                                            <input type="checkbox" id="skip-tiles" class="form-check-input">
                                            <label class="form-check-label" for="skip-tiles">Pomin kafelki</label>
                                        </div>
                                    </div>
                                </div>
                                <div class="d-flex gap-2">
                                    <button id="bootstrap-start" class="btn btn-success btn-sm">Start</button>
                                    <button id="bootstrap-cancel" class="btn btn-danger btn-sm" disabled>Anuluj</button>
                                </div>
                            </div>
                            <!-- Status -->
                            <div id="bootstrap-status" class="mt-2">
                                <span class="badge bg-secondary" id="bootstrap-badge">idle</span>
                                <span id="bootstrap-elapsed" class="text-muted ms-2"></span>
                            </div>
                            <!-- Log output -->
                            <pre id="bootstrap-log" class="admin-log mt-2"></pre>
                        </div>
                    </div>
                </div>

                <!-- Cleanup -->
                <div class="col-md-4">
                    <div class="admin-card glass-panel p-3">
                        <h5>Czyszczenie danych</h5>
                        <div id="cleanup-content">
                            <div class="spinner-border spinner-border-sm"></div> Ladowanie...
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Bootstrap JS -->
    <script defer src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"
            integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz"
            crossorigin="anonymous"></script>

    <script defer src="js/admin/admin-api.js"></script>
    <script defer src="js/admin/admin-bootstrap.js"></script>
    <script defer src="js/admin/admin-app.js"></script>
</body>
</html>
```

**Step 2: Create admin.css**

Plik `frontend/css/admin.css`:

```css
/* Admin Panel Styles — extends glass.css tokens */

body {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    min-height: 100vh;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

/* Auth overlay */
.auth-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 9999;
}

.auth-card {
    padding: 2rem;
    min-width: 340px;
    text-align: center;
}

/* Admin cards */
.admin-card {
    height: 100%;
}

.admin-card h5 {
    font-size: 0.95rem;
    font-weight: 700;
    margin-bottom: 0.75rem;
    color: var(--color-text);
    border-bottom: 1px solid var(--color-divider);
    padding-bottom: 0.5rem;
}

/* Stat grid */
.stat-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.5rem;
}

.stat-item {
    padding: 0.5rem;
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.12);
}

.stat-label {
    font-size: 0.7rem;
    color: var(--color-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.03em;
}

.stat-value {
    font-size: 1.1rem;
    font-weight: 600;
    color: var(--color-text);
}

/* Status badges */
.badge-healthy { background-color: var(--color-success) !important; }
.badge-unhealthy { background-color: var(--color-danger) !important; }
.badge-running { background-color: var(--color-primary) !important; }
.badge-idle { background-color: #6c757d !important; }
.badge-completed { background-color: var(--color-success) !important; }
.badge-failed { background-color: var(--color-danger) !important; }

/* Log output */
.admin-log {
    background: rgba(0, 0, 0, 0.85);
    color: #00ff41;
    font-family: 'Courier New', monospace;
    font-size: 0.75rem;
    line-height: 1.4;
    padding: 0.75rem;
    border-radius: 8px;
    max-height: 400px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
}

.admin-log:empty::after {
    content: "Brak logow...";
    color: #666;
}

/* Cleanup buttons */
.cleanup-target {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--color-divider);
}

.cleanup-target:last-child {
    border-bottom: none;
}

.cleanup-size {
    font-size: 0.75rem;
    color: var(--color-text-secondary);
}

/* Table styling */
.admin-table {
    font-size: 0.8rem;
    margin-bottom: 0;
}

.admin-table td {
    padding: 0.25rem 0.5rem;
    border-color: var(--color-divider);
}

.admin-table .table-label {
    color: var(--color-text-secondary);
    font-size: 0.75rem;
}
```

**Step 3: Commit**

```bash
git add frontend/admin.html frontend/css/admin.css
git commit -m "feat(frontend): admin panel HTML + CSS (glassmorphism, 4 sekcje)"
```

---

## Task 7: Frontend — admin-api.js (API client)

**Files:**
- Create: `frontend/js/admin/admin-api.js`

**Step 1: Create the API client module**

Plik `frontend/js/admin/admin-api.js`:

```javascript
/**
 * Admin API client module.
 *
 * Provides methods to interact with /api/admin/* endpoints.
 * Uses stored API key in sessionStorage for X-Admin-Key header.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var _apiKey = '';

    function setApiKey(key) {
        _apiKey = key;
        sessionStorage.setItem('adminApiKey', key);
    }

    function getApiKey() {
        if (!_apiKey) {
            _apiKey = sessionStorage.getItem('adminApiKey') || '';
        }
        return _apiKey;
    }

    function headers() {
        var h = { 'Content-Type': 'application/json' };
        var key = getApiKey();
        if (key) {
            h['X-Admin-Key'] = key;
        }
        return h;
    }

    async function request(method, path, body) {
        var opts = {
            method: method,
            headers: headers(),
        };
        if (body !== undefined) {
            opts.body = JSON.stringify(body);
        }
        var response = await fetch(path, opts);
        if (response.status === 401 || response.status === 403) {
            sessionStorage.removeItem('adminApiKey');
            _apiKey = '';
            window.location.reload();
            throw new Error('Unauthorized');
        }
        if (!response.ok) {
            var errData;
            try {
                errData = await response.json();
            } catch (e) {
                throw new Error('Blad ' + response.status);
            }
            throw new Error(errData.detail || 'Blad ' + response.status);
        }
        return response.json();
    }

    async function getDashboard() {
        return request('GET', '/api/admin/dashboard');
    }

    async function getResources() {
        return request('GET', '/api/admin/resources');
    }

    async function getCleanupEstimate() {
        return request('GET', '/api/admin/cleanup/estimate');
    }

    async function executeCleanup(targets) {
        return request('POST', '/api/admin/cleanup', { targets: targets });
    }

    async function getBootstrapStatus() {
        return request('GET', '/api/admin/bootstrap/status');
    }

    async function startBootstrap(params) {
        return request('POST', '/api/admin/bootstrap/start', params);
    }

    async function cancelBootstrap() {
        return request('POST', '/api/admin/bootstrap/cancel');
    }

    function streamBootstrapLogs(onMessage, onDone) {
        var key = getApiKey();
        var url = '/api/admin/bootstrap/stream';
        var es = new EventSource(url);

        es.onmessage = function (event) {
            onMessage(event.data);
        };

        es.addEventListener('done', function (event) {
            es.close();
            if (onDone) onDone(event.data);
        });

        es.onerror = function () {
            es.close();
            if (onDone) onDone('error');
        };

        return es;
    }

    /**
     * Verify API key by calling dashboard endpoint.
     * Returns true if key is valid, false otherwise.
     */
    async function verifyKey(key) {
        try {
            var response = await fetch('/api/admin/dashboard', {
                headers: { 'X-Admin-Key': key },
            });
            return response.ok;
        } catch (e) {
            return false;
        }
    }

    window.Hydrograf.adminApi = {
        setApiKey: setApiKey,
        getApiKey: getApiKey,
        verifyKey: verifyKey,
        getDashboard: getDashboard,
        getResources: getResources,
        getCleanupEstimate: getCleanupEstimate,
        executeCleanup: executeCleanup,
        getBootstrapStatus: getBootstrapStatus,
        startBootstrap: startBootstrap,
        cancelBootstrap: cancelBootstrap,
        streamBootstrapLogs: streamBootstrapLogs,
    };
})();
```

**Step 2: Commit**

```bash
mkdir -p frontend/js/admin
git add frontend/js/admin/admin-api.js
git commit -m "feat(frontend): admin API client module (IIFE, sessionStorage auth)"
```

---

## Task 8: Frontend — admin-bootstrap.js (SSE + form)

**Files:**
- Create: `frontend/js/admin/admin-bootstrap.js`

**Step 1: Create the bootstrap management module**

Plik `frontend/js/admin/admin-bootstrap.js`:

```javascript
/**
 * Admin Bootstrap panel — form + SSE log streaming.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    var _eventSource = null;
    var _elapsedTimer = null;

    function initBootstrap() {
        var startBtn = document.getElementById('bootstrap-start');
        var cancelBtn = document.getElementById('bootstrap-cancel');

        if (startBtn) startBtn.addEventListener('click', handleStart);
        if (cancelBtn) cancelBtn.addEventListener('click', handleCancel);

        // Initial status check
        refreshStatus();
    }

    async function refreshStatus() {
        try {
            var data = await window.Hydrograf.adminApi.getBootstrapStatus();
            updateStatusUI(data);

            // If running, start streaming
            if (data.status === 'running') {
                startStreaming();
                startElapsedTimer(data.started_at);
            }
        } catch (e) {
            console.error('Bootstrap status error:', e);
        }
    }

    function updateStatusUI(data) {
        var badge = document.getElementById('bootstrap-badge');
        var startBtn = document.getElementById('bootstrap-start');
        var cancelBtn = document.getElementById('bootstrap-cancel');

        if (badge) {
            badge.textContent = data.status;
            badge.className = 'badge badge-' + data.status;
        }

        var isRunning = data.status === 'running';
        if (startBtn) startBtn.disabled = isRunning;
        if (cancelBtn) cancelBtn.disabled = !isRunning;

        // Show elapsed
        if (data.elapsed_s) {
            var el = document.getElementById('bootstrap-elapsed');
            if (el) el.textContent = formatElapsed(data.elapsed_s);
        }
    }

    async function handleStart() {
        var bbox = document.getElementById('bootstrap-bbox').value.trim();
        if (!bbox) {
            alert('Podaj bounding box');
            return;
        }

        var params = {
            bbox: bbox,
            skip_precipitation: document.getElementById('skip-precipitation').checked,
            skip_tiles: document.getElementById('skip-tiles').checked,
            skip_infra: true,
            skip_serve: true,
        };

        try {
            clearLog();
            var result = await window.Hydrograf.adminApi.startBootstrap(params);
            appendLog('--- Bootstrap uruchomiony (PID: ' + result.pid + ') ---');
            startStreaming();
            startElapsedTimer(Date.now() / 1000);
            refreshStatus();
        } catch (e) {
            appendLog('--- Blad: ' + e.message + ' ---');
        }
    }

    async function handleCancel() {
        if (!confirm('Czy na pewno chcesz anulowac bootstrap?')) return;

        try {
            await window.Hydrograf.adminApi.cancelBootstrap();
            appendLog('--- Anulowano ---');
            stopStreaming();
            refreshStatus();
        } catch (e) {
            appendLog('--- Blad anulowania: ' + e.message + ' ---');
        }
    }

    function startStreaming() {
        stopStreaming();
        _eventSource = window.Hydrograf.adminApi.streamBootstrapLogs(
            function (line) { appendLog(line); },
            function (finalStatus) {
                appendLog('--- Zakonczono: ' + finalStatus + ' ---');
                stopStreaming();
                refreshStatus();
            }
        );
    }

    function stopStreaming() {
        if (_eventSource) {
            _eventSource.close();
            _eventSource = null;
        }
        if (_elapsedTimer) {
            clearInterval(_elapsedTimer);
            _elapsedTimer = null;
        }
    }

    function startElapsedTimer(startedAt) {
        if (_elapsedTimer) clearInterval(_elapsedTimer);
        var el = document.getElementById('bootstrap-elapsed');
        _elapsedTimer = setInterval(function () {
            var elapsed = Date.now() / 1000 - startedAt;
            if (el) el.textContent = formatElapsed(elapsed);
        }, 1000);
    }

    function appendLog(line) {
        var logEl = document.getElementById('bootstrap-log');
        if (!logEl) return;
        logEl.textContent += line + '\n';
        logEl.scrollTop = logEl.scrollHeight;
    }

    function clearLog() {
        var logEl = document.getElementById('bootstrap-log');
        if (logEl) logEl.textContent = '';
    }

    function formatElapsed(seconds) {
        var m = Math.floor(seconds / 60);
        var s = Math.floor(seconds % 60);
        return m + 'min ' + s + 's';
    }

    window.Hydrograf.adminBootstrap = {
        init: initBootstrap,
        refresh: refreshStatus,
    };
})();
```

**Step 2: Commit**

```bash
git add frontend/js/admin/admin-bootstrap.js
git commit -m "feat(frontend): admin bootstrap panel — SSE streaming, form, elapsed timer"
```

---

## Task 9: Frontend — admin-app.js (orchestrator)

**Files:**
- Create: `frontend/js/admin/admin-app.js`

**Step 1: Create the main admin app module**

Plik `frontend/js/admin/admin-app.js`:

```javascript
/**
 * Admin panel orchestrator — auth, dashboard, resources, cleanup.
 */
(function () {
    'use strict';

    var api;
    var _refreshInterval = null;

    document.addEventListener('DOMContentLoaded', function () {
        api = window.Hydrograf.adminApi;

        // Check for stored key
        var storedKey = sessionStorage.getItem('adminApiKey');
        if (storedKey) {
            api.setApiKey(storedKey);
            tryAuth(storedKey);
        } else {
            showAuth();
        }
    });

    // --- Auth ---

    function showAuth() {
        document.getElementById('auth-overlay').style.display = 'flex';
        document.getElementById('admin-main').style.display = 'none';

        var input = document.getElementById('auth-key-input');
        var btn = document.getElementById('auth-submit');

        btn.onclick = function () { tryAuth(input.value); };
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') tryAuth(input.value);
        });
    }

    async function tryAuth(key) {
        var errorEl = document.getElementById('auth-error');
        var valid = await api.verifyKey(key);
        if (valid) {
            api.setApiKey(key);
            document.getElementById('auth-overlay').style.display = 'none';
            document.getElementById('admin-main').style.display = 'block';
            initPanels();
        } else {
            if (errorEl) {
                errorEl.textContent = 'Nieprawidlowy klucz API';
                errorEl.style.display = 'block';
            }
        }
    }

    // --- Panels ---

    function initPanels() {
        loadDashboard();
        loadResources();
        loadCleanup();
        window.Hydrograf.adminBootstrap.init();

        // Auto-refresh every 30s
        _refreshInterval = setInterval(function () {
            loadDashboard();
            loadResources();
        }, 30000);
    }

    // --- Dashboard ---

    async function loadDashboard() {
        var el = document.getElementById('dashboard-content');
        try {
            var data = await api.getDashboard();
            var statusBadge = document.getElementById('system-status');
            if (statusBadge) {
                statusBadge.textContent = data.status;
                statusBadge.className = 'badge badge-' + data.status;
            }

            var html = '<div class="stat-grid">';
            html += statItem('Status', data.status);
            html += statItem('Wersja', data.version);
            html += statItem('Uptime', formatUptime(data.uptime_s));
            html += statItem('Baza', data.database);
            html += '</div>';

            html += '<h6 class="mt-3 mb-2" style="font-size:0.8rem">Tabele</h6>';
            html += '<table class="table admin-table">';
            var tables = data.tables;
            for (var key in tables) {
                html += '<tr><td class="table-label">' + key + '</td>';
                html += '<td class="text-end">' + formatNumber(tables[key]) + '</td></tr>';
            }
            html += '</table>';

            html += '<h6 class="mt-2 mb-2" style="font-size:0.8rem">Dysk</h6>';
            html += '<table class="table admin-table">';
            html += '<tr><td class="table-label">Frontend data</td><td class="text-end">' + data.disk.frontend_data_mb + ' MB</td></tr>';
            html += '<tr><td class="table-label">Kafelki MVT</td><td class="text-end">' + data.disk.frontend_tiles_mb + ' MB</td></tr>';
            html += '<tr><td class="table-label">NMT</td><td class="text-end">' + data.disk.nmt_data_mb + ' MB</td></tr>';
            html += '<tr><td class="table-label"><strong>Razem</strong></td><td class="text-end"><strong>' + data.disk.total_mb + ' MB</strong></td></tr>';
            html += '</table>';

            el.innerHTML = html;
        } catch (e) {
            el.innerHTML = '<div class="text-danger">' + e.message + '</div>';
        }
    }

    // --- Resources ---

    async function loadResources() {
        var el = document.getElementById('resources-content');
        try {
            var data = await api.getResources();

            var html = '<div class="stat-grid">';
            html += statItem('CPU', data.process.cpu_percent + '%');
            html += statItem('RAM', data.process.memory_mb + ' MB');
            html += statItem('RAM %', data.process.memory_percent + '%');
            html += statItem('PID', data.process.pid);
            html += statItem('Watki', data.process.threads);
            html += statItem('DB', data.db_size_mb + ' MB');
            html += '</div>';

            html += '<h6 class="mt-3 mb-2" style="font-size:0.8rem">Pool DB</h6>';
            html += '<table class="table admin-table">';
            html += '<tr><td class="table-label">Pool size</td><td class="text-end">' + data.db_pool.pool_size + '</td></tr>';
            html += '<tr><td class="table-label">Checked out</td><td class="text-end">' + data.db_pool.checked_out + '</td></tr>';
            html += '<tr><td class="table-label">Checked in</td><td class="text-end">' + data.db_pool.checked_in + '</td></tr>';
            html += '<tr><td class="table-label">Overflow</td><td class="text-end">' + data.db_pool.overflow + '</td></tr>';
            html += '</table>';

            html += '<h6 class="mt-2 mb-2" style="font-size:0.8rem">CatchmentGraph</h6>';
            html += '<table class="table admin-table">';
            html += '<tr><td class="table-label">Zaladowany</td><td class="text-end">' + (data.catchment_graph.loaded ? 'Tak' : 'Nie') + '</td></tr>';
            html += '<tr><td class="table-label">Wezly</td><td class="text-end">' + formatNumber(data.catchment_graph.nodes) + '</td></tr>';
            html += '</table>';

            el.innerHTML = html;
        } catch (e) {
            el.innerHTML = '<div class="text-danger">' + e.message + '</div>';
        }
    }

    // --- Cleanup ---

    async function loadCleanup() {
        var el = document.getElementById('cleanup-content');
        try {
            var data = await api.getCleanupEstimate();
            var html = '';
            data.targets.forEach(function (t) {
                html += '<div class="cleanup-target">';
                html += '<div>';
                html += '<div>' + t.label + '</div>';
                html += '<div class="cleanup-size">' + t.size_mb + ' MB</div>';
                html += '</div>';
                html += '<button class="btn btn-sm btn-outline-danger cleanup-btn" data-target="' + t.id + '">Usun</button>';
                html += '</div>';
            });
            el.innerHTML = html;

            // Bind click handlers
            el.querySelectorAll('.cleanup-btn').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    handleCleanup(btn.dataset.target);
                });
            });
        } catch (e) {
            el.innerHTML = '<div class="text-danger">' + e.message + '</div>';
        }
    }

    async function handleCleanup(targetId) {
        if (!confirm('Czy na pewno chcesz usunac: ' + targetId + '?')) return;

        try {
            var result = await api.executeCleanup([targetId]);
            var r = result.results[0];
            alert(r.success ? 'Usunieto: ' + r.detail : 'Blad: ' + r.detail);
            loadCleanup();
            loadDashboard();
        } catch (e) {
            alert('Blad: ' + e.message);
        }
    }

    // --- Helpers ---

    function statItem(label, value) {
        return '<div class="stat-item"><div class="stat-label">' + label + '</div><div class="stat-value">' + value + '</div></div>';
    }

    function formatUptime(seconds) {
        var h = Math.floor(seconds / 3600);
        var m = Math.floor((seconds % 3600) / 60);
        return h + 'h ' + m + 'min';
    }

    function formatNumber(n) {
        if (n < 0) return '?';
        return n.toLocaleString('pl-PL');
    }
})();
```

**Step 2: Commit**

```bash
git add frontend/js/admin/admin-app.js
git commit -m "feat(frontend): admin app orchestrator — dashboard, resources, cleanup UI"
```

---

## Task 10: Nginx config + psutil dependency + integration test

**Files:**
- Modify: `docker/nginx.conf` — dodaj /admin location
- Modify: `backend/requirements.txt` — dodaj psutil
- Create: `backend/tests/unit/test_admin_integration.py` — test integracyjny auth

**Step 1: Modify nginx.conf**

W `docker/nginx.conf`, PRZED blokiem `location /` (frontend), dodaj:

```nginx
    # Admin panel
    location /admin {
        alias /usr/share/nginx/html;
        index admin.html;
        try_files /admin.html =404;
    }
```

**Step 2: Add psutil to requirements.txt**

Dodaj do `backend/requirements.txt`:
```
psutil>=5.9
```

**Step 3: Write integration test for auth middleware**

Plik `backend/tests/unit/test_admin_integration.py`:

```python
"""Integration tests for admin panel auth + endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _make_app(api_key=""):
    """Create test app with given API key."""
    with patch("core.config.get_settings") as mock_settings:
        s = MagicMock()
        s.admin_api_key = api_key
        s.database_url = "postgresql://test:test@localhost/test"
        s.log_level = "INFO"
        s.cors_origins = "http://localhost"
        s.db_statement_timeout_ms = 30000
        s.dem_path = "/tmp/dem.vrt"
        mock_settings.return_value = s

        from api.endpoints.admin import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router, prefix="/api/admin")
        return TestClient(app)


class TestAdminAuth:
    """Test admin API key authentication across endpoints."""

    def test_no_key_configured_allows_access(self):
        """When ADMIN_API_KEY is empty, all requests pass."""
        client = _make_app(api_key="")
        with patch("api.endpoints.admin.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.execute.return_value.scalar.return_value = 0
            mock_get_db.return_value = iter([mock_db])

            response = client.get("/api/admin/dashboard")
        assert response.status_code == 200

    def test_wrong_key_returns_403(self):
        """Wrong API key should return 403 on all admin endpoints."""
        client = _make_app(api_key="correct-key")
        response = client.get(
            "/api/admin/dashboard",
            headers={"X-Admin-Key": "wrong-key"},
        )
        assert response.status_code == 403

    def test_missing_key_returns_401(self):
        """Missing API key should return 401 on all admin endpoints."""
        client = _make_app(api_key="correct-key")
        response = client.get("/api/admin/dashboard")
        assert response.status_code == 401

    def test_correct_key_allows_access(self):
        """Correct API key should allow access."""
        client = _make_app(api_key="my-secret")
        with patch("api.endpoints.admin.get_db") as mock_get_db:
            mock_db = MagicMock()
            mock_db.execute.return_value.scalar.return_value = 0
            mock_get_db.return_value = iter([mock_db])

            response = client.get(
                "/api/admin/dashboard",
                headers={"X-Admin-Key": "my-secret"},
            )
        assert response.status_code == 200
```

**Step 4: Run all admin tests**

Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_admin_*.py -v`
Expected: All passed (5 + 3 + 3 + 4 + 5 + 4 = ~24 tests)

**Step 5: Commit**

```bash
git add docker/nginx.conf backend/requirements.txt backend/tests/unit/test_admin_integration.py
git commit -m "feat(docker): nginx /admin route + psutil dep + admin auth integration tests"
```

---

## Task 11: ADR-034 + CHANGELOG + PROGRESS

**Files:**
- Modify: `docs/DECISIONS.md` — dodaj ADR-034
- Modify: `docs/CHANGELOG.md` — dodaj wpis
- Modify: `docs/PROGRESS.md` — zaktualizuj status

**Step 1: ADR-034**

Dodaj na koniec `docs/DECISIONS.md`:

```markdown
### ADR-034: Panel administracyjno-diagnostyczny

**Data:** 2026-03-01
**Status:** Zaakceptowana

**Kontekst:** Brak narzedzia do zarzadzania pipeline'em — bootstrap uruchamiany recznie z CLI, brak widocznosci na zasoby i dane.

**Decyzja:**
- Osobna strona `/admin` (admin.html) z 4 sekcjami: Dashboard, Bootstrap, Zasoby, Czyszczenie
- Backend: router `/api/admin/*` z auth API key (header X-Admin-Key, env ADMIN_API_KEY)
- Bootstrap jako subprocess + SSE (Server-Sent Events) do streamowania logow
- psutil do monitorowania zasobow procesu

**Konsekwencje:**
- (+) Zarzadzanie pipeline'em z przegladarki
- (+) Real-time logi bootstrap (SSE)
- (+) Diagnostyka systemu bez dostepu do CLI
- (-) Dodatkowa zaleznosc: psutil
- (-) Auth tylko API key (JWT w przyszlosci z uzytkownikami)
```

**Step 2: Update CHANGELOG + PROGRESS**

Dodaj wpis do CHANGELOG i zaktualizuj PROGRESS.

**Step 3: Commit**

```bash
git add docs/DECISIONS.md docs/CHANGELOG.md docs/PROGRESS.md
git commit -m "docs: ADR-034 panel administracyjny, CHANGELOG, PROGRESS"
```

---

## Summary

| Task | Opis | Testy |
|------|------|-------|
| 1 | Auth middleware + Settings | 5 |
| 2 | Dashboard endpoint | 3 |
| 3 | Resources endpoint | 3 |
| 4 | Cleanup endpoints | 4 |
| 5 | Bootstrap subprocess + SSE | 5 |
| 6 | Frontend HTML + CSS | 0 |
| 7 | Frontend admin-api.js | 0 |
| 8 | Frontend admin-bootstrap.js | 0 |
| 9 | Frontend admin-app.js | 0 |
| 10 | Nginx + psutil + integration | 4 |
| 11 | ADR-034 + docs | 0 |
| **Razem** | | **~24** |
