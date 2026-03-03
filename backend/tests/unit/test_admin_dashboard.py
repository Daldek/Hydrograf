"""Tests for admin dashboard endpoint."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.dependencies.admin_auth import verify_admin_key
from api.endpoints.admin import _dir_size_mb, router
from core.database import get_db


def _noop_auth():
    """Disable auth for tests."""
    return None


@pytest.fixture
def app():
    """Create test FastAPI app with admin router and mocked deps."""
    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/admin")
    test_app.dependency_overrides[verify_admin_key] = _noop_auth
    yield test_app
    test_app.dependency_overrides.clear()


def _make_mock_db(*, fail_connect: bool = False, row_count: int = 42):
    """Create a mock DB session."""
    db = MagicMock(spec=Session)
    if fail_connect:
        db.execute.side_effect = Exception("connection refused")
    else:
        result = MagicMock()
        result.scalar.return_value = row_count
        db.execute.return_value = result
    return db


class TestDashboard:
    """Tests for GET /api/admin/dashboard."""

    @patch("api.endpoints.admin._dir_size_mb", return_value=10.5)
    def test_dashboard_healthy(self, _mock_dir, app):
        """Dashboard returns healthy status when DB is connected."""
        mock_db = _make_mock_db(row_count=42)
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/admin/dashboard")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert data["version"] == "1.0.0"
        assert data["database"] == "connected"
        assert isinstance(data["uptime_s"], float)
        assert isinstance(data["tables"], dict)
        assert isinstance(data["disk"], dict)

    @patch("api.endpoints.admin._dir_size_mb", return_value=0.0)
    def test_dashboard_unhealthy(self, _mock_dir, app):
        """Dashboard returns unhealthy when DB raises error."""
        mock_db = _make_mock_db(fail_connect=True)
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/admin/dashboard")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "unhealthy"
        assert "error" in data["database"]

    @patch("api.endpoints.admin._dir_size_mb", return_value=0.0)
    def test_dashboard_table_counts(self, _mock_dir, app):
        """Dashboard includes row counts for all 6 tables."""
        mock_db = _make_mock_db(row_count=100)
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/admin/dashboard")
        data = response.json()

        expected_tables = [
            "stream_network",
            "stream_catchments",
            "depressions",
            "land_cover",
            "soil_hsg",
            "precipitation_data",
        ]
        for table in expected_tables:
            assert table in data["tables"]

    @patch("api.endpoints.admin._dir_size_mb", return_value=5.0)
    def test_dashboard_disk_info(self, _mock_dir, app):
        """Dashboard includes disk usage info."""
        mock_db = _make_mock_db(row_count=0)
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/admin/dashboard")
        data = response.json()

        assert "frontend_data_mb" in data["disk"]
        assert "frontend_tiles_mb" in data["disk"]
        assert "nmt_data_mb" in data["disk"]
        assert "cache_mb" in data["disk"]
        assert isinstance(data["disk"]["cache_mb"], (int, float))
        assert data["disk"]["cache_mb"] >= 0
        assert "total_mb" in data["disk"]


class TestDirSizeMb:
    """Tests for _dir_size_mb helper."""

    def test_nonexistent_path(self, tmp_path):
        """Returns 0.0 for non-existent path."""
        assert _dir_size_mb(tmp_path / "nonexistent") == 0.0

    def test_empty_dir(self, tmp_path):
        """Returns 0.0 for empty directory."""
        assert _dir_size_mb(tmp_path) == 0.0

    def test_dir_with_files(self, tmp_path):
        """Calculates correct size for directory with files."""
        # Write 1 MB of data to make rounding work
        (tmp_path / "file1.bin").write_bytes(b"x" * (512 * 1024))
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "file2.bin").write_bytes(b"x" * (512 * 1024))

        size = _dir_size_mb(tmp_path)
        assert size == 1.0
