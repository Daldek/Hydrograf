"""Tests for admin cleanup endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.dependencies.admin_auth import verify_admin_key
from api.endpoints.admin import _CLEANUP_COMPONENTS, router
from core.database import get_db


def _noop_auth():
    return None


@pytest.fixture
def app():
    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/admin")
    test_app.dependency_overrides[verify_admin_key] = _noop_auth
    yield test_app
    test_app.dependency_overrides.clear()


def _make_mock_db():
    db = MagicMock(spec=Session)
    result = MagicMock()
    result.scalar.return_value = 52428800  # 50 MB
    db.execute.return_value = result
    return db


class TestCleanupComponents:
    """Tests for cleanup component configuration."""

    def test_all_target_excludes_cache(self):
        """'all' target does not include 'cache' component."""
        assert "cache" not in _CLEANUP_COMPONENTS["all"]["components"]

    def test_all_target_includes_db(self):
        """'all' target includes 'db' component."""
        assert "db" in _CLEANUP_COMPONENTS["all"]["components"]

    def test_cache_target_is_standalone(self):
        """'cache' target only contains 'cache' component."""
        assert _CLEANUP_COMPONENTS["cache"]["components"] == ["cache"]

    def test_all_target_covers_all_data(self):
        """'all' target includes rasters, hydro, boundary, overlays, geojson, tiles, db."""
        expected = {"rasters", "hydro", "boundary", "overlays", "geojson", "tiles", "db"}
        actual = set(_CLEANUP_COMPONENTS["all"]["components"])
        assert actual == expected


class TestCleanupEstimate:
    """Tests for GET /api/admin/cleanup/estimate."""

    @patch("api.endpoints.admin._dir_size_mb", return_value=10.0)
    def test_estimate_returns_all_and_cache(self, _mock_dir, app):
        """Estimate returns 'all' and 'cache' targets."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/admin/cleanup/estimate")
        assert response.status_code == 200

        data = response.json()
        keys = [t["key"] for t in data["targets"]]
        assert "all" in keys
        assert "cache" in keys

    @patch("api.endpoints.admin._dir_size_mb", return_value=5.5)
    def test_estimate_has_size_mb(self, _mock_dir, app):
        """Each target has a size_mb field."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/admin/cleanup/estimate")
        data = response.json()

        for target in data["targets"]:
            assert "size_mb" in target
            assert isinstance(target["size_mb"], float)


class TestCleanupExecute:
    """Tests for POST /api/admin/cleanup."""

    def test_unknown_target_returns_400(self, app):
        """Unknown target key returns 400."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.post(
            "/api/admin/cleanup",
            json={"targets": ["nonexistent"]},
        )
        assert response.status_code == 400

    @patch("api.endpoints.admin.execute_clean")
    def test_cleanup_all_delegates_to_execute_clean(self, mock_exec, app):
        """'all' target delegates to scripts.clean.execute_clean."""
        mock_exec.return_value = {"total_files": 42, "total_size": 1024, "results": {}}
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.post(
            "/api/admin/cleanup",
            json={"targets": ["all"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"][0]["status"] == "ok"
        assert data["results"][0]["total_files"] == 42

        # Verify execute_clean was called with all components except cache
        call_args = mock_exec.call_args
        assert "db" in call_args.kwargs["components"]
        assert "rasters" in call_args.kwargs["components"]
        assert "cache" not in call_args.kwargs["components"]
        assert call_args.kwargs["dry_run"] is False

    @patch("api.endpoints.admin.execute_clean")
    def test_cleanup_cache_delegates_to_execute_clean(self, mock_exec, app):
        """'cache' target delegates to scripts.clean.execute_clean with cache component."""
        mock_exec.return_value = {"total_files": 10, "total_size": 512, "results": {}}
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.post(
            "/api/admin/cleanup",
            json={"targets": ["cache"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"][0]["status"] == "ok"

        call_args = mock_exec.call_args
        assert call_args.kwargs["components"] == ["cache"]

    @patch("api.endpoints.admin.execute_clean", side_effect=Exception("disk full"))
    def test_cleanup_error_returns_error_status(self, mock_exec, app):
        """execute_clean failure is reported as error."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.post(
            "/api/admin/cleanup",
            json={"targets": ["all"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"][0]["status"] == "error"
        assert "disk full" in data["results"][0]["detail"]


class TestDbTablesImport:
    """Verify DB_TABLES is imported from scripts.clean (single source of truth)."""

    def test_db_tables_includes_bdot_streams(self):
        from scripts.clean import DB_TABLES
        assert "bdot_streams" in DB_TABLES

    def test_admin_uses_same_db_tables(self):
        """Admin module imports DB_TABLES from scripts.clean."""
        from api.endpoints import admin
        from scripts.clean import DB_TABLES
        # The admin module should use the same list
        # (it imports DB_TABLES at module level)
        assert admin.DB_TABLES is DB_TABLES
