"""GET /api/admin/status: the server and its checks (Nogat DEV-15.13, ADR-086).

The answer has the fields of DEV-15.13 and the three checks the README names:
`database`, `catchment_graph` and `data_dir`, each `ok`, `warning` or `failed`.
"""

import datetime
import os
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies.admin_auth import verify_admin_key
from api.endpoints import admin
from api.errors import install_error_handlers
from core.config import get_settings
from core.database import get_db
from core.version import get_version


@pytest.fixture
def app():
    test_app = FastAPI()
    install_error_handlers(test_app)
    test_app.include_router(admin.router, prefix="/api/admin")
    test_app.dependency_overrides[verify_admin_key] = lambda: None
    test_app.dependency_overrides[get_db] = lambda: MagicMock()
    return test_app


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """The deployment's data_dir, HYDROGRAF_DATA_DIR."""
    folder = tmp_path / "data"
    folder.mkdir()
    monkeypatch.setattr(get_settings(), "hydrograf_data_dir", str(folder))
    return folder


@pytest.fixture
def graph(monkeypatch):
    """The catchment graph of the process, loaded with two thresholds."""
    loaded = MagicMock(loaded=True, _n=41515)
    loaded.thresholds_m2.return_value = [10000, 100000]
    monkeypatch.setattr(admin, "get_catchment_graph", lambda: loaded)
    return loaded


def _status(app):
    response = TestClient(app).get("/api/admin/status")
    assert response.status_code == 200
    return response.json()


def _checks(status):
    return {check["name"]: check for check in status["checks"]}


def test_the_status_has_the_fields_of_dev_15_13(app, data_dir, graph):
    status = _status(app)

    assert set(status) == {
        "app",
        "version",
        "started_at",
        "uptime_s",
        "data_dir",
        "disk",
        "checks",
    }
    assert (status["app"], status["version"]) == ("Hydrograf", get_version())
    started = datetime.datetime.fromisoformat(status["started_at"])
    assert started.utcoffset() == datetime.timedelta(0)
    assert status["uptime_s"] >= 0
    assert status["data_dir"] == str(data_dir)
    disk = status["disk"]
    assert 0 < disk["free_bytes"] <= disk["total_bytes"]
    assert [check["name"] for check in status["checks"]] == [
        "database",
        "catchment_graph",
        "data_dir",
    ]
    assert {check["status"] for check in status["checks"]} == {"ok"}
    assert "41\u00a0515" in _checks(status)["catchment_graph"]["detail"]


def test_a_database_that_does_not_answer_fails_its_check(app, data_dir, graph):
    db = MagicMock()
    db.execute.side_effect = RuntimeError("connection refused\nmore lines")
    app.dependency_overrides[get_db] = lambda: db

    check = _checks(_status(app))["database"]

    assert check["status"] == "failed"
    assert check["detail"] == "Baza danych nie odpowiada: connection refused"


def test_a_graph_that_is_not_loaded_is_a_warning(app, data_dir, graph):
    graph.loaded = False

    assert _checks(_status(app))["catchment_graph"]["status"] == "warning"


def test_a_missing_data_dir_fails_and_has_no_disk(app, data_dir, graph):
    data_dir.rmdir()

    status = _status(app)

    assert _checks(status)["data_dir"]["status"] == "failed"
    assert status["disk"] == {"free_bytes": None, "total_bytes": None}


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes into any directory")
def test_a_statistics_directory_that_cannot_be_written_fails(app, data_dir, graph):
    own = data_dir / "hydrograf"
    own.mkdir()
    own.chmod(0o555)
    try:
        check = _checks(_status(app))["data_dir"]
    finally:
        own.chmod(0o755)

    assert check["status"] == "failed"
    assert str(own) in check["detail"]
