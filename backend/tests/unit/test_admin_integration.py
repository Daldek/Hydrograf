"""Integration tests for admin panel auth across all endpoints."""

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.endpoints.admin import router


def _create_app():
    """Create a fresh FastAPI app with admin router."""
    app = FastAPI()
    app.include_router(router, prefix="/api/admin")
    return app


def _mock_settings(api_key=""):
    """Create a mock settings object."""
    s = MagicMock()
    s.admin_api_key = api_key
    s.admin_api_key_file = ""
    s.database_url = "postgresql://test:test@localhost/test"
    s.log_level = "INFO"
    s.cors_origins = "http://localhost"
    s.db_statement_timeout_ms = 30000
    s.dem_path = "/tmp/dem.vrt"
    return s


class TestAdminAuthIntegration:
    """Test auth middleware across different endpoints."""

    def test_no_key_configured_still_requires_auth(self):
        """Empty ADMIN_API_KEY generates random key — auth still enforced."""
        import api.dependencies.admin_auth as auth_module
        auth_module._generated_key = None  # reset generated key

        app = _create_app()
        client = TestClient(app)
        with patch(
            "api.dependencies.admin_auth.get_settings",
            return_value=_mock_settings(api_key=""),
        ):
            response = client.get("/api/admin/dashboard")
        assert response.status_code == 401
        auth_module._generated_key = None  # cleanup

    def test_wrong_key_blocked_on_dashboard(self):
        app = _create_app()
        client = TestClient(app)
        mock_settings = _mock_settings(api_key="correct")
        with patch(
            "api.dependencies.admin_auth.get_settings",
            return_value=mock_settings,
        ):
            response = client.get(
                "/api/admin/dashboard",
                headers={"X-Admin-Key": "wrong"},
            )
        assert response.status_code == 403

    def test_missing_key_blocked(self):
        app = _create_app()
        client = TestClient(app)
        mock_settings = _mock_settings(api_key="correct")
        with patch(
            "api.dependencies.admin_auth.get_settings",
            return_value=mock_settings,
        ):
            response = client.get("/api/admin/dashboard")
        assert response.status_code == 401

    def test_correct_key_passes(self):
        app = _create_app()
        client = TestClient(app)
        mock_settings = _mock_settings(api_key="my-secret")
        with (
            patch(
                "api.dependencies.admin_auth.get_settings",
                return_value=mock_settings,
            ),
            patch("api.endpoints.admin.get_db") as mock_get_db,
        ):
            mock_db = MagicMock()
            mock_db.execute.return_value.scalar.return_value = 0
            mock_get_db.return_value = iter([mock_db])
            response = client.get(
                "/api/admin/dashboard",
                headers={"X-Admin-Key": "my-secret"},
            )
        assert response.status_code == 200

    def test_auth_applies_to_resources(self):
        app = _create_app()
        client = TestClient(app)
        mock_settings = _mock_settings(api_key="secret")
        with patch(
            "api.dependencies.admin_auth.get_settings",
            return_value=mock_settings,
        ):
            response = client.get("/api/admin/resources")
        assert response.status_code == 401

    def test_auth_applies_to_cleanup(self):
        app = _create_app()
        client = TestClient(app)
        mock_settings = _mock_settings(api_key="secret")
        with patch(
            "api.dependencies.admin_auth.get_settings",
            return_value=mock_settings,
        ):
            response = client.get(
                "/api/admin/cleanup/estimate",
            )
        assert response.status_code == 401

    def test_auth_applies_to_bootstrap(self):
        app = _create_app()
        client = TestClient(app)
        mock_settings = _mock_settings(api_key="secret")
        with patch(
            "api.dependencies.admin_auth.get_settings",
            return_value=mock_settings,
        ):
            response = client.get(
                "/api/admin/bootstrap/status",
            )
        assert response.status_code == 401
