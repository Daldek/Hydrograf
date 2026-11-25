"""Tests for admin resources endpoint (the section „Zasoby” of the panel)."""

import threading
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from api.dependencies.admin_auth import verify_admin_key
from api.endpoints.admin import FRONTEND_TILES, _DirSizes, router
from core.database import get_db
from scripts.clean import DB_TABLES

MB = 1024 * 1024


def _noop_auth():
    return None


@pytest.fixture
def app():
    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/v1/admin")
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


def _sizes_of(size_mb):
    """A stand-in of the module's _DirSizes: each directory measures size_mb(path)."""
    sizes = MagicMock()
    sizes.measure.side_effect = lambda paths: {path: size_mb(path) for path in paths}
    return sizes


class TestResources:
    """Tests for GET /api/v1/admin/resources."""

    @pytest.fixture(autouse=True)
    def _sizes(self):
        """Five MB in each data directory, without walking the real ones."""
        with patch("api.endpoints.admin._DIR_SIZES", _sizes_of(lambda path: 5.0)):
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
        response = client.get("/api/v1/admin/resources")
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
        response = client.get("/api/v1/admin/resources")
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
        response = client.get("/api/v1/admin/resources")
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
        response = client.get("/api/v1/admin/resources")
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
        response = client.get("/api/v1/admin/resources")
        data = response.json()

        assert data["db_size_mb"] == 100.0

    @patch("api.endpoints.admin.get_db_engine")
    @patch("api.endpoints.admin.get_catchment_graph")
    def test_resources_count_the_rows_of_every_table(self, mock_cg, mock_engine, app):
        mock_cg.return_value = MagicMock(loaded=False)
        app.dependency_overrides[get_db] = lambda: _make_mock_db(db_size_bytes=42)

        data = TestClient(app).get("/api/v1/admin/resources").json()

        assert data["tables"] == dict.fromkeys(DB_TABLES, 42)

    @patch("api.endpoints.admin.get_db_engine")
    @patch("api.endpoints.admin.get_catchment_graph")
    def test_resources_give_the_size_of_the_data(self, mock_cg, mock_engine, app):
        mock_cg.return_value = MagicMock(loaded=False)
        app.dependency_overrides[get_db] = lambda: _make_mock_db()

        data = TestClient(app).get("/api/v1/admin/resources").json()

        assert data["disk"] == {
            "frontend_data_mb": 5.0,
            "frontend_tiles_mb": 5.0,
            "nmt_data_mb": 5.0,
            "cache_mb": 5.0,
            "total_mb": 20.0,
        }

    @patch("api.endpoints.admin.get_db_engine")
    @patch("api.endpoints.admin.get_catchment_graph")
    def test_a_directory_still_walked_has_no_size_nor_total(
        self, mock_cg, mock_engine, app
    ):
        mock_cg.return_value = MagicMock(loaded=False)
        app.dependency_overrides[get_db] = lambda: _make_mock_db()
        walking = _sizes_of(lambda path: None if path == FRONTEND_TILES else 5.0)

        with patch("api.endpoints.admin._DIR_SIZES", walking):
            data = TestClient(app).get("/api/v1/admin/resources").json()

        assert data["disk"] == {
            "frontend_data_mb": 5.0,
            "frontend_tiles_mb": None,
            "nmt_data_mb": 5.0,
            "cache_mb": 5.0,
            "total_mb": None,
        }


class _BlockedWalk:
    """dir_size that waits for release() before it answers size_mb."""

    def __init__(self, size_mb: float):
        self.size_mb = size_mb
        self.calls = 0
        self._release = threading.Event()

    def __call__(self, path):
        self.calls += 1
        self._release.wait(10)
        return self.size_mb * MB

    def release(self):
        self._release.set()


class TestDirSizes:
    """The sizes of the data directories, walked in threads of their own (E5b-02)."""

    def test_missing_and_empty_directories_measure_zero(self, tmp_path):
        sizes = _DirSizes()
        missing = tmp_path / "missing"

        assert sizes.measure([missing, tmp_path], wait_s=5) == {
            missing: 0.0,
            tmp_path: 0.0,
        }

    def test_a_directory_measures_its_files_below_it(self, tmp_path):
        (tmp_path / "file1.bin").write_bytes(b"x" * (MB // 2))
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "file2.bin").write_bytes(b"x" * (MB // 2))

        assert _DirSizes().measure([tmp_path], wait_s=5) == {tmp_path: 1.0}

    def test_a_walk_longer_than_the_wait_gives_null_then_its_size(self, tmp_path):
        sizes = _DirSizes()
        walk = _BlockedWalk(1.0)
        with patch("api.endpoints.admin.dir_size", walk):
            try:
                assert sizes.measure([tmp_path], wait_s=0.05) == {tmp_path: None}
                assert sizes.measure([tmp_path], wait_s=0.05) == {tmp_path: None}
            finally:
                walk.release()
            assert sizes.measure([tmp_path], wait_s=5) == {tmp_path: 1.0}

        assert walk.calls == 1

    def test_a_size_past_its_time_is_given_while_it_is_walked_again(self, tmp_path):
        sizes = _DirSizes()
        with patch("api.endpoints.admin.dir_size", return_value=MB):
            assert sizes.measure([tmp_path], wait_s=5) == {tmp_path: 1.0}

        walk = _BlockedWalk(2.0)
        with (
            patch("api.endpoints.admin._DIR_SIZE_TTL", 0.0),
            patch("api.endpoints.admin.dir_size", walk),
        ):
            try:
                assert sizes.measure([tmp_path], wait_s=0.05) == {tmp_path: 1.0}
            finally:
                walk.release()
            assert sizes.measure([tmp_path], wait_s=5) == {tmp_path: 2.0}

    def test_a_size_within_its_time_is_not_walked_again(self, tmp_path):
        sizes = _DirSizes()
        with patch("api.endpoints.admin.dir_size", return_value=MB) as walk:
            sizes.measure([tmp_path], wait_s=5)
            assert sizes.measure([tmp_path], wait_s=5) == {tmp_path: 1.0}

        assert walk.call_count == 1

    def test_a_failed_walk_keeps_the_last_size_and_the_next_walks_again(self, tmp_path):
        sizes = _DirSizes()
        with patch("api.endpoints.admin.dir_size", side_effect=OSError("gone")):
            assert sizes.measure([tmp_path], wait_s=5) == {tmp_path: None}
        with patch("api.endpoints.admin.dir_size", return_value=MB):
            assert sizes.measure([tmp_path], wait_s=5) == {tmp_path: 1.0}
        with (
            patch("api.endpoints.admin._DIR_SIZE_TTL", 0.0),
            patch("api.endpoints.admin.dir_size", side_effect=OSError("gone")),
        ):
            assert sizes.measure([tmp_path], wait_s=5) == {tmp_path: 1.0}
