"""Every admin route refuses a request without the right key (Nogat DEV-15.13, ADR-086).

The routes are those the application documents under `/api/admin/`, so a new route is
checked as soon as it exists: with no key on the server, without the header and with a
wrong one, each answers the problem `unauthorized` with the reason of DEV-15.13 and,
like every admin answer, `Cache-Control: no-store`. Neither the server's key nor a
guess reaches a log.
"""

import json

import pytest
from fastapi.testclient import TestClient

from api.main import app
from core.config import get_settings

KEY = "the-operators-admin-key"

ADMIN_ROUTES = sorted(
    (method.upper(), path.replace("{feedback_id}", "1"))
    for path, operations in app.openapi()["paths"].items()
    if path.startswith("/api/admin/")
    for method in operations
)


@pytest.fixture
def server_key(monkeypatch):
    """Set the server's key: ADMIN_API_KEY, empty for none."""
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_api_key_file", "")

    def set_key(key: str) -> None:
        monkeypatch.setattr(settings, "admin_api_key", key)

    return set_key


def test_the_core_routes_of_dev_15_13_are_admin_routes():
    assert {
        ("GET", "/api/admin/feedback"),
        ("PATCH", "/api/admin/feedback/1"),
        ("DELETE", "/api/admin/feedback/1"),
        ("GET", "/api/admin/stats"),
        ("GET", "/api/admin/status"),
    } <= set(ADMIN_ROUTES)


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
@pytest.mark.parametrize(
    ("configured", "sent", "reason"),
    [
        ("", KEY, "admin_key_not_configured"),
        (KEY, None, "admin_key_missing"),
        (KEY, "a-wrong-key", "admin_key_invalid"),
    ],
)
def test_every_admin_route_refuses_without_the_key(
    server_key, method, path, configured, sent, reason
):
    server_key(configured)
    headers = {} if sent is None else {"X-Admin-Key": sent}

    response = TestClient(app).request(method, path, headers=headers)

    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["code"] == "unauthorized"
    assert response.json()["details"]["reason"] == reason
    assert response.headers["cache-control"] == "no-store"


def test_no_key_reaches_a_log(server_key, log_records, caplog):
    client = TestClient(app)
    server_key(KEY)
    client.get("/api/admin/stats", headers={"X-Admin-Key": KEY})
    client.get("/api/admin/stats", headers={"X-Admin-Key": "a-wrong-key"})
    server_key("")
    client.get("/api/admin/stats", headers={"X-Admin-Key": KEY})

    logged = json.dumps(log_records()) + caplog.text

    assert "/api/admin/stats" in logged
    assert KEY not in logged
    assert "a-wrong-key" not in logged
