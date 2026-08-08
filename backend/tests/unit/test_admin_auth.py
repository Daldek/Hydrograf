"""Tests for admin API key authentication dependency."""

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.dependencies.admin_auth import _check_admin_key, verify_admin_key
from core.config import get_settings


def _build_probe_app() -> FastAPI:
    """Minimal app with one route protected by the real admin dependency."""
    app = FastAPI()

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
        assert bypass.status_code == 403

        legit = client.get("/api/admin/probe", headers={"X-Admin-Key": "real-secret"})
        assert legit.status_code == 200


class TestVerifyAdminKey:
    """Tests for verify_admin_key dependency."""

    def test_valid_key_passes(self):
        """Valid key matching expected_key should not raise."""
        _check_admin_key(x_admin_key="secret123", expected_key="secret123")

    def test_missing_key_raises_401(self):
        """Missing header with configured key should raise 401."""
        with pytest.raises(HTTPException) as exc_info:
            _check_admin_key(x_admin_key=None, expected_key="secret123")
        assert exc_info.value.status_code == 401

    def test_wrong_key_raises_403(self):
        """Wrong key should raise 403."""
        with pytest.raises(HTTPException) as exc_info:
            _check_admin_key(x_admin_key="wrong", expected_key="secret123")
        assert exc_info.value.status_code == 403

    def test_empty_key_raises_401(self):
        """Empty string as header value with configured key should raise 401."""
        with pytest.raises(HTTPException) as exc_info:
            _check_admin_key(x_admin_key="", expected_key="secret123")
        assert exc_info.value.status_code == 401

    def test_no_configured_key_generates_random(self, caplog):
        """When no key configured, a random key is generated and logged."""
        import logging

        import api.dependencies.admin_auth as auth_module
        auth_module._generated_key = None  # reset

        with caplog.at_level(logging.WARNING):
            key = auth_module._get_or_generate_admin_key("")
            assert len(key) == 36  # UUID4 format
            assert "ADMIN_API_KEY" in caplog.text
        auth_module._generated_key = None  # cleanup

    def test_generated_key_is_stable(self):
        """Generated key remains the same across calls."""
        import api.dependencies.admin_auth as auth_module
        auth_module._generated_key = None
        key1 = auth_module._get_or_generate_admin_key("")
        key2 = auth_module._get_or_generate_admin_key("")
        assert key1 == key2
        auth_module._generated_key = None

    def test_configured_key_skips_generation(self):
        """When key is configured, no generation happens."""
        import api.dependencies.admin_auth as auth_module
        result = auth_module._get_or_generate_admin_key("my-secret-key")
        assert result == "my-secret-key"

    def test_no_configured_key_still_requires_header(self):
        """When no key configured, auth is still enforced with generated key."""
        import api.dependencies.admin_auth as auth_module
        auth_module._generated_key = None
        with pytest.raises(HTTPException) as exc_info:
            _check_admin_key(x_admin_key=None, expected_key="")
        assert exc_info.value.status_code == 401
        auth_module._generated_key = None

    def test_file_based_key(self, tmp_path, monkeypatch):
        """Key loaded from file when admin_api_key is empty."""
        key_file = tmp_path / "admin.key"
        key_file.write_text("file-secret-key\n")

        settings = get_settings()
        monkeypatch.setattr(settings, "admin_api_key", "")
        monkeypatch.setattr(settings, "admin_api_key_file", str(key_file))

        # Valid key from file should pass
        _check_admin_key(x_admin_key="file-secret-key", expected_key=None)

    def test_file_based_key_missing_file_generates_random(self, monkeypatch):
        """Missing key file with no configured key generates random key."""
        import api.dependencies.admin_auth as auth_module
        auth_module._generated_key = None

        settings = get_settings()
        monkeypatch.setattr(settings, "admin_api_key", "")
        monkeypatch.setattr(settings, "admin_api_key_file", "/nonexistent/path")

        with pytest.raises(HTTPException) as exc_info:
            verify_admin_key(x_admin_key=None)
        assert exc_info.value.status_code == 401
        auth_module._generated_key = None
