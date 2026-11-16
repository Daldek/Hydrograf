"""Tests for admin resources endpoint (the section „Zasoby” of the panel)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.dependencies.admin_auth import verify_admin_key
from api.endpoints.admin import _dir_size_mb, router
from core.database import get_db
from scripts.clean import DB_TABLES


def _noop_auth():
    return None


@pytest.fixture
def app():
    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/admin")
    test_app.dependency_overrides[verify_admin_key] = _noop_auth
    yield test_app
    test_app.dependency_overrides.clear()


def _make_mock_db(db_size_bytes: int = 104857600):
    """Create a mock DB session returning db size."""
    db = MagicMock(spec=Session)
    result = MagicMock()
    result.scalar.return_value = db_size_bytes
    db.execute.return_value = result
    return db


class TestResources:
    """Tests for GET /api/admin/resources."""

    @pytest.fixture(autouse=True)
    def _sizes(self):
        """Five MB in each data directory, without walking the real ones."""
        with patch("api.endpoints.admin._dir_size_mb", return_value=5.0):
            yield

    @patch("api.endpoints.admin.get_db_engine")
    @patch("api.endpoints.admin.get_catchment_graph")
    def test_resources_returns_all_sections(self, mock_cg, mock_engine, app):
        """Resources endpoint returns process, db_pool, catchment_graph, db_size."""
        # Mock catchment graph
        cg = MagicMock()
        cg.loaded = False
        cg._n = 0
        cg._threshold_m2 = None
        mock_cg.return_value = cg

        # Mock engine pool
        pool = MagicMock()
        pool.size.return_value = 10
        pool.checkedout.return_value = 1
        pool.overflow.return_value = 0
        pool.checkedin.return_value = 9
        engine = MagicMock()
        engine.pool = pool
        mock_engine.return_value = engine

        mock_db = _make_mock_db(db_size_bytes=52428800)
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/admin/resources")
        assert response.status_code == 200

        data = response.json()
        assert "process" in data
        assert "db_pool" in data
        assert "catchment_graph" in data
        assert "db_size_mb" in data

    @patch("api.endpoints.admin.get_db_engine")
    @patch("api.endpoints.admin.get_catchment_graph")
    def test_resources_process_info(self, mock_cg, mock_engine, app):
        """Process info includes cpu, memory, pid, threads."""
        cg = MagicMock()
        cg.loaded = False
        cg._n = 0
        cg._threshold_m2 = None
        mock_cg.return_value = cg

        pool = MagicMock()
        pool.size.return_value = 10
        pool.checkedout.return_value = 0
        pool.overflow.return_value = 0
        pool.checkedin.return_value = 10
        engine = MagicMock()
        engine.pool = pool
        mock_engine.return_value = engine

        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/admin/resources")
        data = response.json()

        proc = data["process"]
        assert "cpu_percent" in proc
        assert "memory_mb" in proc
        assert "memory_percent" in proc
        assert "pid" in proc
        assert "threads" in proc
        assert proc["pid"] > 0

    @patch("api.endpoints.admin.get_db_engine")
    @patch("api.endpoints.admin.get_catchment_graph")
    def test_resources_db_pool(self, mock_cg, mock_engine, app):
        """DB pool info includes pool_size, checked_out, overflow, checked_in."""
        cg = MagicMock()
        cg.loaded = False
        cg._n = 0
        cg._threshold_m2 = None
        mock_cg.return_value = cg

        pool = MagicMock()
        pool.size.return_value = 10
        pool.checkedout.return_value = 2
        pool.overflow.return_value = 1
        pool.checkedin.return_value = 8
        engine = MagicMock()
        engine.pool = pool
        mock_engine.return_value = engine

        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/admin/resources")
        data = response.json()

        pool_data = data["db_pool"]
        assert pool_data["pool_size"] == 10
        assert pool_data["checked_out"] == 2
        assert pool_data["overflow"] == 1
        assert pool_data["checked_in"] == 8

    @patch("api.endpoints.admin.get_db_engine")
    @patch("api.endpoints.admin.get_catchment_graph")
    def test_resources_catchment_graph_not_loaded(self, mock_cg, mock_engine, app):
        """Catchment graph info when not loaded."""
        cg = MagicMock()
        cg.loaded = False
        cg._n = 0
        cg._threshold_m2 = None
        mock_cg.return_value = cg

        pool = MagicMock()
        pool.size.return_value = 10
        pool.checkedout.return_value = 0
        pool.overflow.return_value = 0
        pool.checkedin.return_value = 10
        engine = MagicMock()
        engine.pool = pool
        mock_engine.return_value = engine

        mock_db = _make_mock_db()
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/admin/resources")
        data = response.json()

        cg_data = data["catchment_graph"]
        assert cg_data["loaded"] is False
        assert cg_data["nodes"] == 0

    @patch("api.endpoints.admin.get_db_engine")
    @patch("api.endpoints.admin.get_catchment_graph")
    def test_resources_db_size(self, mock_cg, mock_engine, app):
        """Database size is returned in MB."""
        cg = MagicMock()
        cg.loaded = False
        cg._n = 0
        cg._threshold_m2 = None
        mock_cg.return_value = cg

        pool = MagicMock()
        pool.size.return_value = 10
        pool.checkedout.return_value = 0
        pool.overflow.return_value = 0
        pool.checkedin.return_value = 10
        engine = MagicMock()
        engine.pool = pool
        mock_engine.return_value = engine

        # 100 MB
        mock_db = _make_mock_db(db_size_bytes=104857600)
        app.dependency_overrides[get_db] = lambda: mock_db

        client = TestClient(app)
        response = client.get("/api/admin/resources")
        data = response.json()

        assert data["db_size_mb"] == 100.0

    @patch("api.endpoints.admin.get_db_engine")
    @patch("api.endpoints.admin.get_catchment_graph")
    def test_resources_count_the_rows_of_every_table(self, mock_cg, mock_engine, app):
        mock_cg.return_value = MagicMock(loaded=False)
        app.dependency_overrides[get_db] = lambda: _make_mock_db(db_size_bytes=42)

        data = TestClient(app).get("/api/admin/resources").json()

        assert data["tables"] == dict.fromkeys(DB_TABLES, 42)

    @patch("api.endpoints.admin.get_db_engine")
    @patch("api.endpoints.admin.get_catchment_graph")
    def test_resources_give_the_size_of_the_data(self, mock_cg, mock_engine, app):
        mock_cg.return_value = MagicMock(loaded=False)
        app.dependency_overrides[get_db] = lambda: _make_mock_db()

        data = TestClient(app).get("/api/admin/resources").json()

        assert data["disk"] == {
            "frontend_data_mb": 5.0,
            "frontend_tiles_mb": 5.0,
            "nmt_data_mb": 5.0,
            "cache_mb": 5.0,
            "total_mb": 20.0,
        }


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
