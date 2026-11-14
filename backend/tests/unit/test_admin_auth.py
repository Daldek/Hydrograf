"""The admin key of every admin route (Nogat DEV-15.13, ADR-086)."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.dependencies.admin_auth import _check_admin_key, verify_admin_key
from api.errors import install_error_handlers
from core.config import get_settings
from core.errors import UnauthorizedError


def _build_probe_app() -> FastAPI:
    """Minimal app with one route protected by the real admin dependency."""
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/api/admin/probe", dependencies=[Depends(verify_admin_key)])
    def probe():
        return {"ok": True}

    return app


class TestExpectedKeyNotClientSettable:
    """Regression: `expected_key` must never be a client-settable query parameter.

    It was a test seam declared as a keyword-only param on the dependency; FastAPI
    exposed it as an optional query parameter, letting a client supply both sides of
    the comparison (`?expected_key=x` + header `X-Admin-Key: x`) — a full auth bypass.
    """

    def test_expected_key_absent_from_openapi(self):
        schema = _build_probe_app().openapi()
        params = schema["paths"]["/api/admin/probe"]["get"].get("parameters", [])
        names = {p["name"] for p in params}
        assert "expected_key" not in names

    def test_query_expected_key_cannot_bypass_auth(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "admin_api_key", "real-secret")
        monkeypatch.setattr(settings, "admin_api_key_file", "")
        client = TestClient(_build_probe_app())

        bypass = client.get(
            "/api/admin/probe?expected_key=pwned",
            headers={"X-Admin-Key": "pwned"},
        )
        assert bypass.status_code == 401
        assert bypass.json()["details"]["reason"] == "admin_key_invalid"

        legit = client.get("/api/admin/probe", headers={"X-Admin-Key": "real-secret"})
        assert legit.status_code == 200


class TestVerifyAdminKey:
    """Tests for verify_admin_key dependency."""

    def test_valid_key_passes(self):
        """Valid key matching expected_key should not raise."""
        _check_admin_key(x_admin_key="secret123", expected_key="secret123")

    def test_missing_key_raises_unauthorized(self):
        """Missing header with configured key should raise ``unauthorized``."""
        with pytest.raises(UnauthorizedError) as exc_info:
            _check_admin_key(x_admin_key=None, expected_key="secret123")
        assert exc_info.value.code == "unauthorized"
        assert exc_info.value.details["reason"] == "admin_key_missing"

    def test_wrong_key_raises_unauthorized(self):
        """Wrong key should raise ``unauthorized`` (reason ``admin_key_invalid``)."""
        with pytest.raises(UnauthorizedError) as exc_info:
            _check_admin_key(x_admin_key="wrong", expected_key="secret123")
        assert exc_info.value.code == "unauthorized"
        assert exc_info.value.details["reason"] == "admin_key_invalid"

    def test_empty_key_raises_unauthorized(self):
        """Empty string as header value with configured key counts as missing."""
        with pytest.raises(UnauthorizedError) as exc_info:
            _check_admin_key(x_admin_key="", expected_key="secret123")
        assert exc_info.value.details["reason"] == "admin_key_missing"


def _server_key(monkeypatch, key: str = "", file: str = "") -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_api_key", key)
    monkeypatch.setattr(settings, "admin_api_key_file", file)


def _reason(supplied: str | None) -> str:
    with pytest.raises(UnauthorizedError) as exc_info:
        verify_admin_key(x_admin_key=supplied)
    assert exc_info.value.code == "unauthorized"
    return str(exc_info.value.details["reason"])


class TestConfiguredKey:
    """Where the server's key comes from: ADMIN_API_KEY, else ADMIN_API_KEY_FILE."""

    @pytest.mark.parametrize("supplied", [None, "", "anything"])
    def test_a_server_without_a_key_refuses_every_request(self, monkeypatch, supplied):
        _server_key(monkeypatch)

        assert _reason(supplied) == "admin_key_not_configured"

    def test_the_key_of_the_file(self, tmp_path, monkeypatch):
        key_file = tmp_path / "admin.key"
        key_file.write_text("file-secret-key\n")
        _server_key(monkeypatch, file=str(key_file))

        verify_admin_key(x_admin_key="file-secret-key")

    @pytest.mark.parametrize("content", [None, "", " \n"])
    def test_a_missing_or_blank_file_is_no_key(self, tmp_path, monkeypatch, content):
        key_file = tmp_path / "admin.key"
        if content is not None:
            key_file.write_text(content)
        _server_key(monkeypatch, file=str(key_file))

        assert _reason("anything") == "admin_key_not_configured"

    def test_the_file_is_read_on_every_request(self, tmp_path, monkeypatch):
        """A rotated key file applies at once, without a restart."""
        key_file = tmp_path / "admin.key"
        key_file.write_text("old-key\n")
        _server_key(monkeypatch, file=str(key_file))
        verify_admin_key(x_admin_key="old-key")

        key_file.write_text("new-key\n")

        assert _reason("old-key") == "admin_key_invalid"
        verify_admin_key(x_admin_key="new-key")

    def test_admin_api_key_comes_before_the_file(self, tmp_path, monkeypatch):
        key_file = tmp_path / "admin.key"
        key_file.write_text("file-key\n")
        _server_key(monkeypatch, key="env-key", file=str(key_file))

        verify_admin_key(x_admin_key="env-key")
        assert _reason("file-key") == "admin_key_invalid"
