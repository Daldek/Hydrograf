# Critical Bugs Fix — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 6 critical/high-priority bugs (CR4, CR6, CR7, CR8, S5.3, Auth) in parallel teams on separate feature branches, then merge to develop.

**Architecture:** 3 independent teams work on feature branches. Each team follows TDD. Team 4 merges all branches after teams 1-3 complete.

**Tech Stack:** Python 3.12+, FastAPI, numpy, scipy, threading, pytest

---

## Team 1 — `feature/fix-catchment-graph` (CR4 + CR6 + CR7)

**Branch:** `feature/fix-catchment-graph` (from `develop`)

### Task 1.1: Thread-safe singleton (CR7)

**Files:**
- Modify: `backend/core/catchment_graph.py:1-18` (imports) + `:708-717` (singleton)
- Test: `backend/tests/unit/test_catchment_graph.py`

**Step 1: Create branch**

```bash
cd /home/claude-agent/workspace/Hydrograf
git checkout develop
git checkout -b feature/fix-catchment-graph
```

**Step 2: Write the failing test**

Add at the end of `backend/tests/unit/test_catchment_graph.py`:

```python
class TestGetCatchmentGraphThreadSafety:
    """Tests for get_catchment_graph() singleton thread safety (CR7)."""

    def test_returns_same_instance(self):
        """Concurrent calls return the same CatchmentGraph instance."""
        import threading
        from core.catchment_graph import get_catchment_graph, _catchment_graph_lock

        # Reset singleton for test
        import core.catchment_graph as cg_module
        cg_module._catchment_graph = None

        instances = []

        def get_instance():
            instances.append(get_catchment_graph())

        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads must get the exact same object
        assert len(instances) == 10
        assert all(inst is instances[0] for inst in instances)

        # Cleanup: reset singleton
        cg_module._catchment_graph = None

    def test_lock_exists(self):
        """Module-level lock exists for singleton protection."""
        import threading
        from core.catchment_graph import _catchment_graph_lock
        assert isinstance(_catchment_graph_lock, threading.Lock)
```

**Step 3: Run test to verify it fails**

```bash
cd /home/claude-agent/workspace/Hydrograf/backend
.venv/bin/python -m pytest tests/unit/test_catchment_graph.py::TestGetCatchmentGraphThreadSafety -v
```

Expected: FAIL — `_catchment_graph_lock` does not exist.

**Step 4: Implement thread-safe singleton**

In `backend/core/catchment_graph.py`, add `import threading` to imports (after `import time`, line ~8):

```python
import threading
```

Replace the singleton section (lines 708-717) with:

```python
# Global singleton
_catchment_graph: CatchmentGraph | None = None
_catchment_graph_lock = threading.Lock()


def get_catchment_graph() -> CatchmentGraph:
    """Get or create the global CatchmentGraph instance (thread-safe)."""
    global _catchment_graph
    if _catchment_graph is None:
        with _catchment_graph_lock:
            if _catchment_graph is None:
                _catchment_graph = CatchmentGraph()
    return _catchment_graph
```

**Step 5: Run test to verify it passes**

```bash
cd /home/claude-agent/workspace/Hydrograf/backend
.venv/bin/python -m pytest tests/unit/test_catchment_graph.py::TestGetCatchmentGraphThreadSafety -v
```

Expected: PASS

**Step 6: Run all catchment_graph tests**

```bash
cd /home/claude-agent/workspace/Hydrograf/backend
.venv/bin/python -m pytest tests/unit/test_catchment_graph.py -v
```

Expected: All existing tests still pass.

**Step 7: Commit**

```bash
git add backend/core/catchment_graph.py backend/tests/unit/test_catchment_graph.py
git commit -m "fix(core): add thread-safe singleton for CatchmentGraph (CR7)"
```

---

### Task 1.2: BFS deque optimization (CR4)

**Files:**
- Modify: `backend/core/catchment_graph.py:1-18` (imports) + `:385-422` (traverse_to_confluence)
- Test: `backend/tests/unit/test_catchment_graph.py`

**Step 1: Write the failing test (performance assertion)**

Add to `backend/tests/unit/test_catchment_graph.py`:

```python
class TestTraverseToConfluenceDeque:
    """Verify traverse_to_confluence uses collections.deque (CR4)."""

    def test_uses_deque_not_list(self):
        """Implementation must use deque for O(1) popleft."""
        import inspect
        from core.catchment_graph import CatchmentGraph
        source = inspect.getsource(CatchmentGraph.traverse_to_confluence)
        assert "deque" in source, "traverse_to_confluence should use collections.deque"
        assert ".pop(0)" not in source, "traverse_to_confluence should not use list.pop(0)"
```

**Step 2: Run test to verify it fails**

```bash
cd /home/claude-agent/workspace/Hydrograf/backend
.venv/bin/python -m pytest tests/unit/test_catchment_graph.py::TestTraverseToConfluenceDeque -v
```

Expected: FAIL — source still has `list.pop(0)`.

**Step 3: Implement deque fix**

In `backend/core/catchment_graph.py`, add to imports (after `import threading`):

```python
from collections import deque
```

Replace `traverse_to_confluence` method body (lines 406-422), specifically lines 407 and 412:

Change line 407 from:
```python
        queue = [start_idx]
```
to:
```python
        queue = deque([start_idx])
```

Change line 412 from:
```python
            current = queue.pop(0)
```
to:
```python
            current = queue.popleft()
```

**Step 4: Run tests**

```bash
cd /home/claude-agent/workspace/Hydrograf/backend
.venv/bin/python -m pytest tests/unit/test_catchment_graph.py::TestTraverseToConfluenceDeque tests/unit/test_catchment_graph.py::TestTraverseToConfluence -v
```

Expected: All PASS.

**Step 5: Commit**

```bash
git add backend/core/catchment_graph.py backend/tests/unit/test_catchment_graph.py
git commit -m "fix(core): use deque.popleft() in traverse_to_confluence BFS (CR4)"
```

---

### Task 1.3: Public getter for _segment_idx (CR6)

**Files:**
- Modify: `backend/core/catchment_graph.py` (new method after `lookup_by_segment_idx`)
- Modify: `backend/api/endpoints/watershed.py:129`
- Modify: `backend/api/endpoints/hydrograph.py:139`
- Modify: `backend/api/endpoints/select_stream.py:120`
- Test: `backend/tests/unit/test_catchment_graph.py`

**Step 1: Write the failing test**

Add to `backend/tests/unit/test_catchment_graph.py`:

```python
class TestGetSegmentIdx:
    """Tests for public get_segment_idx() accessor (CR6)."""

    def test_returns_correct_segment_idx(self, small_graph):
        """get_segment_idx returns the segment_idx for a given internal index."""
        # Node 0 has segment_idx=1 in the small_graph fixture
        assert small_graph.get_segment_idx(0) == 1
        assert small_graph.get_segment_idx(1) == 2
        assert small_graph.get_segment_idx(2) == 3
        assert small_graph.get_segment_idx(3) == 4

    def test_returns_int(self, small_graph):
        """Return type is Python int, not numpy int."""
        result = small_graph.get_segment_idx(0)
        assert isinstance(result, int)

    def test_raises_when_not_loaded(self):
        """Raises RuntimeError if graph not loaded."""
        from core.catchment_graph import CatchmentGraph
        cg = CatchmentGraph()
        import pytest
        with pytest.raises(RuntimeError, match="not loaded"):
            cg.get_segment_idx(0)
```

**Step 2: Run test to verify it fails**

```bash
cd /home/claude-agent/workspace/Hydrograf/backend
.venv/bin/python -m pytest tests/unit/test_catchment_graph.py::TestGetSegmentIdx -v
```

Expected: FAIL — `CatchmentGraph` has no `get_segment_idx`.

**Step 3: Add public method to CatchmentGraph**

In `backend/core/catchment_graph.py`, add after `lookup_by_segment_idx()` method (around line 303):

```python
    def get_segment_idx(self, internal_idx: int) -> int:
        """Get segment_idx for a node by its internal graph index.

        Parameters
        ----------
        internal_idx : int
            Internal index of the node in the graph (0..n-1)

        Returns
        -------
        int
            The segment_idx value from the stream_network table
        """
        if not self._loaded:
            raise RuntimeError("Catchment graph not loaded")
        return int(self._segment_idx[internal_idx])
```

**Step 4: Run test to verify it passes**

```bash
cd /home/claude-agent/workspace/Hydrograf/backend
.venv/bin/python -m pytest tests/unit/test_catchment_graph.py::TestGetSegmentIdx -v
```

Expected: PASS

**Step 5: Update 3 endpoints to use public getter**

In `backend/api/endpoints/watershed.py`, change line 129 from:
```python
segment_idx = int(cg._segment_idx[clicked_idx])
```
to:
```python
segment_idx = cg.get_segment_idx(clicked_idx)
```

In `backend/api/endpoints/hydrograph.py`, change line 139 from:
```python
segment_idx = int(cg._segment_idx[clicked_idx])
```
to:
```python
segment_idx = cg.get_segment_idx(clicked_idx)
```

In `backend/api/endpoints/select_stream.py`, change line 120 from:
```python
segment_idx = int(cg._segment_idx[clicked_idx])
```
to:
```python
segment_idx = cg.get_segment_idx(clicked_idx)
```

**Step 6: Verify no remaining direct access to _segment_idx in endpoints**

```bash
cd /home/claude-agent/workspace/Hydrograf/backend
grep -rn "_segment_idx" api/endpoints/
```

Expected: no matches.

**Step 7: Run full test suite for affected endpoints**

```bash
cd /home/claude-agent/workspace/Hydrograf/backend
.venv/bin/python -m pytest tests/unit/test_catchment_graph.py tests/integration/test_watershed.py tests/integration/test_hydrograph.py tests/integration/test_select_stream.py -v
```

Expected: All PASS.

**Step 8: Commit**

```bash
git add backend/core/catchment_graph.py backend/api/endpoints/watershed.py backend/api/endpoints/hydrograph.py backend/api/endpoints/select_stream.py backend/tests/unit/test_catchment_graph.py
git commit -m "refactor(core): add public get_segment_idx() accessor (CR6)"
```

---

## Team 2 — `feature/fix-profile-security` (CR8)

**Branch:** `feature/fix-profile-security` (from `develop`)

### Task 2.1: Remove server path from error detail + fix nodata float comparison

**Files:**
- Modify: `backend/api/endpoints/profile.py:1-10` (imports) + `:63-67` (error) + `:72` (nodata)
- Test: `backend/tests/integration/test_profile.py`

**Step 1: Create branch**

```bash
cd /home/claude-agent/workspace/Hydrograf
git checkout develop
git checkout -b feature/fix-profile-security
```

**Step 2: Write the failing test for info disclosure**

Add to `backend/tests/integration/test_profile.py`, in class `TestTerrainProfileEndpoint`:

```python
    def test_503_does_not_leak_server_path(self, client):
        """503 error must not contain server filesystem paths (CR8)."""
        with patch("api.endpoints.profile.os.path.exists", return_value=False):
            response = client.post(
                "/api/terrain-profile",
                json={
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[21.0, 52.0], [21.01, 52.01]],
                    },
                    "n_samples": 5,
                },
            )

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert "/data/" not in detail
        assert ".vrt" not in detail
        assert "dem" not in detail.lower() or "DEM" in detail
```

**Step 3: Write the failing test for nodata float comparison**

Add to `backend/tests/integration/test_profile.py`, in class `TestTerrainProfileEndpoint`:

```python
    def test_nodata_uses_approximate_comparison(self, client):
        """Nodata detection must use approximate float comparison, not == (CR8)."""
        import inspect
        from api.endpoints.profile import terrain_profile
        source = inspect.getsource(terrain_profile)
        assert "isclose" in source, "Must use math.isclose for nodata comparison"
        assert "elev == dataset.nodata" not in source, "Must not use == for float nodata"
```

**Step 4: Run tests to verify they fail**

```bash
cd /home/claude-agent/workspace/Hydrograf/backend
.venv/bin/python -m pytest tests/integration/test_profile.py::TestTerrainProfileEndpoint::test_503_does_not_leak_server_path tests/integration/test_profile.py::TestTerrainProfileEndpoint::test_nodata_uses_approximate_comparison -v
```

Expected: FAIL

**Step 5: Fix profile.py**

In `backend/api/endpoints/profile.py`:

Add `import math` to imports (after `import os`, line 9):
```python
import math
```

Replace the DEM-not-found error (lines 63-67) from:
```python
        if not os.path.exists(dem_path):
            raise HTTPException(
                status_code=503,
                detail=f"Plik DEM nie jest dostepny: {dem_path}. Skonfiguruj DEM_PATH.",
            )
```
to:
```python
        if not os.path.exists(dem_path):
            logger.error("DEM file not found at configured path: %s", dem_path)
            raise HTTPException(
                status_code=503,
                detail="Plik DEM nie jest dostepny. Skontaktuj sie z administratorem.",
            )
```

Replace the nodata comparison block (lines 69-75) from:
```python
        elevations: list[float] = []
        with rasterio.open(dem_path) as dataset:
            for val in dataset.sample(sample_points):
                elev = float(val[0])
                # Handle nodata
                if dataset.nodata is not None and elev == dataset.nodata:
                    elevations.append(0.0)
                else:
                    elevations.append(elev)
```
to:
```python
        elevations: list[float] = []
        nodata_count = 0
        with rasterio.open(dem_path) as dataset:
            for val in dataset.sample(sample_points):
                elev = float(val[0])
                if dataset.nodata is not None and math.isclose(
                    elev, float(dataset.nodata), rel_tol=1e-6
                ):
                    elevations.append(0.0)
                    nodata_count += 1
                else:
                    elevations.append(elev)
```

Replace the all-nodata check (lines 77-81) from:
```python
        if not elevations or all(e == 0.0 for e in elevations):
```
to:
```python
        if not elevations or nodata_count == len(elevations):
```

**Step 6: Run tests**

```bash
cd /home/claude-agent/workspace/Hydrograf/backend
.venv/bin/python -m pytest tests/integration/test_profile.py -v
```

Expected: All PASS (including existing tests).

**Step 7: Commit**

```bash
git add backend/api/endpoints/profile.py backend/tests/integration/test_profile.py
git commit -m "fix(api): remove path disclosure + use math.isclose for nodata (CR8)"
```

---

## Team 3 — `feature/fix-secrets-auth` (S5.3 + Auth)

**Branch:** `feature/fix-secrets-auth` (from `develop`)

### Task 3.1: Auto-generate admin API key (Auth)

**Files:**
- Modify: `backend/api/dependencies/admin_auth.py`
- Test: `backend/tests/unit/test_admin_auth.py`

**Step 1: Create branch**

```bash
cd /home/claude-agent/workspace/Hydrograf
git checkout develop
git checkout -b feature/fix-secrets-auth
```

**Step 2: Write the failing test**

Replace existing `test_no_configured_key_disables_auth` and add new tests in `backend/tests/unit/test_admin_auth.py`:

```python
    def test_no_configured_key_generates_random(self, caplog):
        """When no key configured, a random key is generated and logged."""
        import logging
        with caplog.at_level(logging.WARNING):
            # Call with expected_key="" to simulate no configured key
            # Should NOT just return — should generate a key
            from api.dependencies.admin_auth import _get_or_generate_admin_key
            key = _get_or_generate_admin_key("")
            assert len(key) == 36  # UUID4 format: 8-4-4-4-12
            assert "ADMIN_API_KEY" in caplog.text

    def test_generated_key_is_stable(self):
        """Generated key remains the same across calls."""
        from api.dependencies.admin_auth import _get_or_generate_admin_key, _generated_key
        import api.dependencies.admin_auth as auth_module
        auth_module._generated_key = None  # reset
        key1 = _get_or_generate_admin_key("")
        key2 = _get_or_generate_admin_key("")
        assert key1 == key2
        auth_module._generated_key = None  # cleanup

    def test_configured_key_skips_generation(self):
        """When key is configured, no generation happens."""
        from api.dependencies.admin_auth import _get_or_generate_admin_key
        result = _get_or_generate_admin_key("my-secret-key")
        assert result == "my-secret-key"
```

**Step 3: Run test to verify it fails**

```bash
cd /home/claude-agent/workspace/Hydrograf/backend
.venv/bin/python -m pytest tests/unit/test_admin_auth.py::TestVerifyAdminKey::test_no_configured_key_generates_random -v
```

Expected: FAIL — `_get_or_generate_admin_key` does not exist.

**Step 4: Implement auto-generation**

Rewrite `backend/api/dependencies/admin_auth.py`:

```python
"""
Admin API key authentication dependency.

Verifies the X-Admin-Key header against the configured admin_api_key.
If no key is configured, a random UUID is generated and logged as WARNING.
"""

import logging
import uuid
from pathlib import Path

from fastapi import Header, HTTPException

from core.config import get_settings

logger = logging.getLogger(__name__)

# Module-level generated key (stable for process lifetime)
_generated_key: str | None = None


def _get_or_generate_admin_key(configured_key: str) -> str:
    """Return configured key, or generate and log a random one."""
    global _generated_key
    if configured_key:
        return configured_key
    if _generated_key is None:
        _generated_key = str(uuid.uuid4())
        logger.warning(
            "ADMIN_API_KEY not configured — generated random key: %s "
            "(set ADMIN_API_KEY env var for persistent key)",
            _generated_key,
        )
    return _generated_key


def verify_admin_key(
    x_admin_key: str | None = Header(None, alias="X-Admin-Key"),
    *,
    expected_key: str | None = None,
) -> None:
    """
    Verify admin API key from request header.

    Parameters
    ----------
    x_admin_key : str | None
        API key from X-Admin-Key header
    expected_key : str | None
        Override for testing; if None, loads from settings

    Raises
    ------
    HTTPException
        401 if key is missing, 403 if key is wrong
    """
    if expected_key is None:
        settings = get_settings()
        expected_key = settings.admin_api_key

        if not expected_key and settings.admin_api_key_file:
            try:
                expected_key = Path(settings.admin_api_key_file).read_text().strip()
            except (OSError, IOError):
                pass

        expected_key = _get_or_generate_admin_key(expected_key or "")

    if not x_admin_key:
        raise HTTPException(status_code=401, detail="Missing admin API key")

    if x_admin_key != expected_key:
        raise HTTPException(status_code=403, detail="Invalid admin API key")
```

**Step 5: Update existing test that expected auth-disabled behavior**

In `backend/tests/unit/test_admin_auth.py`, remove or update `test_no_configured_key_disables_auth`:

The old test expected that `verify_admin_key(expected_key="")` returns `None` (auth disabled). Now it should raise 401 because a key is generated. Update:

```python
    def test_no_configured_key_still_requires_header(self):
        """When no key configured, auth is still enforced with generated key."""
        import pytest
        # Reset generated key
        import api.dependencies.admin_auth as auth_module
        auth_module._generated_key = None
        with pytest.raises(HTTPException) as exc_info:
            verify_admin_key(x_admin_key=None, expected_key="")
        assert exc_info.value.status_code == 401
        auth_module._generated_key = None  # cleanup
```

Also update `test_file_based_key_missing_file` — previously when file was missing and no key configured, auth was disabled. Now a random key is generated:

```python
    def test_file_based_key_missing_file_generates_random(self, monkeypatch):
        """Missing key file with no configured key generates random key."""
        import pytest
        import api.dependencies.admin_auth as auth_module
        auth_module._generated_key = None

        settings = get_settings()
        monkeypatch.setattr(settings, "admin_api_key", "")
        monkeypatch.setattr(settings, "admin_api_key_file", "/nonexistent/path")

        with pytest.raises(HTTPException) as exc_info:
            verify_admin_key(x_admin_key=None)
        assert exc_info.value.status_code == 401

        auth_module._generated_key = None  # cleanup
```

**Step 6: Run tests**

```bash
cd /home/claude-agent/workspace/Hydrograf/backend
.venv/bin/python -m pytest tests/unit/test_admin_auth.py -v
```

Expected: All PASS.

**Step 7: Commit**

```bash
git add backend/api/dependencies/admin_auth.py backend/tests/unit/test_admin_auth.py
git commit -m "fix(api): auto-generate admin API key when not configured (Auth)"
```

---

### Task 3.2: Warn about hardcoded secrets (S5.3)

**Files:**
- Modify: `backend/core/config.py` (add startup warning)
- Modify: `backend/migrations/env.py` (remove fallback or add warning)
- Test: `backend/tests/unit/test_yaml_config.py`

**Step 1: Write the failing test for config warning**

Add to `backend/tests/unit/test_yaml_config.py`:

```python
class TestSettingsSecurityWarnings:
    """Tests for security warnings on default credentials (S5.3)."""

    def test_warns_on_default_password(self, caplog, monkeypatch):
        """Startup logs WARNING when using default postgres_password."""
        import logging
        from core.config import Settings, get_settings

        get_settings.cache_clear()
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

        with caplog.at_level(logging.WARNING):
            settings = Settings()
            settings.warn_if_default_credentials()

        assert "default" in caplog.text.lower() or "hydro_password" in caplog.text
        get_settings.cache_clear()

    def test_no_warning_with_custom_password(self, caplog, monkeypatch):
        """No warning when password is explicitly set."""
        import logging
        from core.config import Settings, get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("POSTGRES_PASSWORD", "my-secure-password")

        with caplog.at_level(logging.WARNING):
            settings = Settings()
            settings.warn_if_default_credentials()

        assert "hydro_password" not in caplog.text
        get_settings.cache_clear()
```

**Step 2: Run test to verify it fails**

```bash
cd /home/claude-agent/workspace/Hydrograf/backend
.venv/bin/python -m pytest tests/unit/test_yaml_config.py::TestSettingsSecurityWarnings -v
```

Expected: FAIL — `warn_if_default_credentials` does not exist.

**Step 3: Add warning method to Settings**

In `backend/core/config.py`, add after the `database_url` property:

```python
    def warn_if_default_credentials(self) -> None:
        """Log warning if using default database credentials."""
        if self.postgres_password == "hydro_password":
            logger.warning(
                "Using default postgres_password='hydro_password'. "
                "Set POSTGRES_PASSWORD env var for production."
            )
```

Ensure `logger` exists at module level (add near top if missing):

```python
import logging

logger = logging.getLogger(__name__)
```

**Step 4: Call warning from get_settings()**

In `backend/core/config.py`, update `get_settings()`:

```python
@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.warn_if_default_credentials()
    return settings
```

**Step 5: Fix migrations/env.py fallback**

In `backend/migrations/env.py`, replace lines 26-29 from:
```python
database_url = os.getenv(
    "DATABASE_URL", "postgresql://hydro_user:hydro_password@localhost:5432/hydro_db"
)
```
to:
```python
database_url = os.getenv("DATABASE_URL")
if not database_url:
    import logging
    logging.getLogger(__name__).warning(
        "DATABASE_URL not set — using default local connection. "
        "Set DATABASE_URL env var for production."
    )
    database_url = "postgresql://hydro_user:hydro_password@localhost:5432/hydro_db"
```

**Step 6: Run tests**

```bash
cd /home/claude-agent/workspace/Hydrograf/backend
.venv/bin/python -m pytest tests/unit/test_yaml_config.py -v
```

Expected: All PASS.

**Step 7: Commit**

```bash
git add backend/core/config.py backend/migrations/env.py backend/tests/unit/test_yaml_config.py
git commit -m "fix(core): warn about default credentials at startup (S5.3)"
```

---

## Team 4 — Merge `merge-critical-fixes`

**Prerequisite:** Teams 1, 2, 3 all completed and their tests pass.

### Task 4.1: Merge feature branches to develop

**Step 1: Ensure develop is clean**

```bash
cd /home/claude-agent/workspace/Hydrograf
git checkout develop
git status
```

**Step 2: Merge Team 2 first (lowest conflict risk — isolated file)**

```bash
git merge feature/fix-profile-security --no-ff -m "merge: feature/fix-profile-security into develop (CR8)"
```

**Step 3: Merge Team 3 (touches config.py, admin_auth.py — no overlap with Team 1)**

```bash
git merge feature/fix-secrets-auth --no-ff -m "merge: feature/fix-secrets-auth into develop (S5.3 + Auth)"
```

**Step 4: Merge Team 1 (touches catchment_graph.py + 3 endpoints)**

```bash
git merge feature/fix-catchment-graph --no-ff -m "merge: feature/fix-catchment-graph into develop (CR4 + CR6 + CR7)"
```

If conflicts arise: resolve manually, prioritize Team 1 changes for catchment_graph.py.

**Step 5: Run full test suite**

```bash
cd /home/claude-agent/workspace/Hydrograf/backend
.venv/bin/python -m pytest tests/ -v --tb=short
```

Expected: All 729+ tests pass (including new ones from all teams).

**Step 6: Commit merge resolution if needed**

```bash
git add -A
git commit -m "merge: resolve conflicts from critical bug fixes"
```

**Step 7: Cleanup branches**

```bash
git branch -d feature/fix-catchment-graph
git branch -d feature/fix-profile-security
git branch -d feature/fix-secrets-auth
```

---

## Summary

| Team | Branch | Bugs | Files Modified | New Tests |
|------|--------|------|----------------|-----------|
| 1 | `feature/fix-catchment-graph` | CR4+CR6+CR7 | `catchment_graph.py`, 3 endpoints | ~8 |
| 2 | `feature/fix-profile-security` | CR8 | `profile.py` | ~2 |
| 3 | `feature/fix-secrets-auth` | S5.3+Auth | `admin_auth.py`, `config.py`, `env.py` | ~5 |
| 4 | (merge to develop) | — | conflict resolution | 0 |

**Parallel execution:** Teams 1, 2, 3 run concurrently. Team 4 runs after all complete.

**Conflict risk:** LOW — each team touches different files except Team 1 and Team 3 could theoretically conflict on imports in `config.py`, but Team 1 does not modify `config.py`.
