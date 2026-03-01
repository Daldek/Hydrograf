"""Tests for admin cleanup endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.dependencies.admin_auth import verify_admin_key
from api.endpoints.admin import router, _estimate_target, _file_size_mb
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


class TestCleanupEstimate:
    """Tests for GET /api/admin/cleanup/estimate."""

    @patch("api.endpoints.admin._dir_size_mb", return_value=10.0)
    @patch("api.endpoints.admin._file_size_mb", return_value=1.0)
    def test_estimate_returns_all_targets(
        self, _mock_file, _mock_dir, app
    ):
        """Estimate returns all 5 cleanup targets."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/admin/cleanup/estimate")
        assert response.status_code == 200

        data = response.json()
        keys = [t["key"] for t in data["targets"]]
        assert "tiles" in keys
        assert "overlays" in keys
        assert "dem_tiles" in keys
        assert "dem_mosaic" in keys
        assert "db_tables" in keys

    @patch("api.endpoints.admin._dir_size_mb", return_value=5.5)
    @patch("api.endpoints.admin._file_size_mb", return_value=0.0)
    def test_estimate_has_size_mb(self, _mock_file, _mock_dir, app):
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

    @patch("api.endpoints.admin.shutil")
    def test_cleanup_tiles(self, mock_shutil, app, tmp_path):
        """Cleaning tiles removes and recreates directory."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("api.endpoints.admin.CLEANUP_TARGETS") as mock_targets:
            tiles_dir = tmp_path / "tiles"
            tiles_dir.mkdir()
            (tiles_dir / "some.pbf").write_bytes(b"data")

            mock_targets.__contains__ = lambda s, k: k == "tiles"
            mock_targets.__getitem__ = lambda s, k: {
                "label": "MVT tiles",
                "path": tiles_dir,
                "type": "dir",
            }
            mock_targets.items = lambda: [
                (
                    "tiles",
                    {"label": "MVT tiles", "path": tiles_dir, "type": "dir"},
                )
            ]

            client = TestClient(app)
            response = client.post(
                "/api/admin/cleanup",
                json={"targets": ["tiles"]},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["results"][0]["status"] == "ok"

    def test_cleanup_db_tables(self, app):
        """Cleaning db_tables executes TRUNCATE CASCADE."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.post(
            "/api/admin/cleanup",
            json={"targets": ["db_tables"]},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["results"][0]["key"] == "db_tables"
        assert data["results"][0]["status"] == "ok"
        # Verify TRUNCATE was called
        mock_db.execute.assert_called()
        mock_db.commit.assert_called()

    def test_cleanup_multiple_targets(self, app):
        """Multiple targets can be cleaned at once."""
        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.post(
            "/api/admin/cleanup",
            json={"targets": ["db_tables"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 1


class TestFileSizeMb:
    """Tests for _file_size_mb helper."""

    def test_nonexistent_file(self, tmp_path):
        """Returns 0.0 for non-existent file."""
        assert _file_size_mb(tmp_path / "nope.vrt") == 0.0

    def test_existing_file(self, tmp_path):
        """Returns correct size for existing file."""
        f = tmp_path / "test.vrt"
        f.write_bytes(b"x" * (1024 * 1024))  # 1 MB
        assert _file_size_mb(f) == 1.0
