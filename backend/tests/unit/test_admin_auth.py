"""Tests for admin API key authentication dependency."""

import pytest
from fastapi import HTTPException

from api.dependencies.admin_auth import verify_admin_key


class TestVerifyAdminKey:
    """Tests for verify_admin_key dependency."""

    def test_valid_key_passes(self):
        """Valid key matching expected_key should not raise."""
        verify_admin_key(x_admin_key="secret123", expected_key="secret123")

    def test_missing_key_raises_401(self):
        """Missing header with configured key should raise 401."""
        with pytest.raises(HTTPException) as exc_info:
            verify_admin_key(x_admin_key=None, expected_key="secret123")
        assert exc_info.value.status_code == 401

    def test_wrong_key_raises_403(self):
        """Wrong key should raise 403."""
        with pytest.raises(HTTPException) as exc_info:
            verify_admin_key(x_admin_key="wrong", expected_key="secret123")
        assert exc_info.value.status_code == 403

    def test_empty_key_raises_401(self):
        """Empty string as header value with configured key should raise 401."""
        with pytest.raises(HTTPException) as exc_info:
            verify_admin_key(x_admin_key="", expected_key="secret123")
        assert exc_info.value.status_code == 401

    def test_no_configured_key_disables_auth(self):
        """When expected_key is empty, auth is disabled."""
        # Should not raise regardless of header value
        verify_admin_key(x_admin_key=None, expected_key="")
        verify_admin_key(x_admin_key="anything", expected_key="")
        verify_admin_key(x_admin_key="", expected_key="")

    def test_file_based_key(self, tmp_path, monkeypatch):
        """Key loaded from file when admin_api_key is empty."""
        key_file = tmp_path / "admin.key"
        key_file.write_text("file-secret-key\n")

        from core.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "admin_api_key", "")
        monkeypatch.setattr(settings, "admin_api_key_file", str(key_file))

        # Valid key from file should pass
        verify_admin_key(x_admin_key="file-secret-key", expected_key=None)

    def test_file_based_key_missing_file(self, monkeypatch):
        """Missing key file should disable auth (graceful fallback)."""
        from core.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "admin_api_key", "")
        monkeypatch.setattr(settings, "admin_api_key_file", "/nonexistent/admin.key")

        # Should not raise — auth disabled when file is missing
        verify_admin_key(x_admin_key=None, expected_key=None)
