"""Tests for admin feedback endpoints."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies.admin_auth import verify_admin_key
from api.endpoints.feedback import admin_router
from api.errors import install_error_handlers
from core.database import get_db


def _noop_auth():
    return None


@pytest.fixture
def app():
    test_app = FastAPI()
    install_error_handlers(test_app)
    test_app.include_router(admin_router, prefix="/api/admin")
    test_app.dependency_overrides[verify_admin_key] = _noop_auth
    yield test_app
    test_app.dependency_overrides.clear()


def _row(**kwargs):
    row = MagicMock()
    for key, value in kwargs.items():
        setattr(row, key, value)
    return row


class TestListFeedback:
    def test_returns_items_and_unread_count(self, app):
        db = MagicMock()
        context = {
            "view": "select",
            "station": None,
            "parameters": {"map": {"zoom": 12}},
            "app_version": "0.5.0.dev0",
        }
        new = _row(
            id=2,
            created_at=datetime(2026, 11, 13, 12, 0, tzinfo=UTC),
            message="nowe",
            context=context,
            is_read=False,
            contact=None,
            page_url=None,
            user_agent=None,
            diagnostics=None,
        )
        db.execute.return_value.fetchall.return_value = [new]
        db.execute.return_value.fetchone.return_value = _row(total=2, unread=1)
        app.dependency_overrides[get_db] = lambda: db

        response = TestClient(app).get("/api/admin/feedback")

        assert response.status_code == 200
        data = response.json()
        assert (data["total"], data["unread_count"]) == (2, 1)
        assert data["items"][0] == {
            "id": 2,
            "created_at": "2026-11-13T12:00:00+00:00",
            "message": "nowe",
            "context": context,
            "is_read": False,
            "legacy": None,
        }

    def test_report_of_the_old_form_keeps_what_it_was_sent_with(self, app):
        """The operator still sees the contact of an old report, to handle it."""
        db = MagicMock()
        old = _row(
            id=1,
            created_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
            message="stare",
            context=None,
            is_read=True,
            contact="Jan",
            page_url="https://hydrograf.example/",
            user_agent="UA",
            diagnostics=None,
        )
        db.execute.return_value.fetchall.return_value = [old]
        db.execute.return_value.fetchone.return_value = _row(total=1, unread=0)
        app.dependency_overrides[get_db] = lambda: db

        item = TestClient(app).get("/api/admin/feedback").json()["items"][0]

        assert item["context"] is None
        assert item["legacy"] == {
            "contact": "Jan",
            "page_url": "https://hydrograf.example/",
            "user_agent": "UA",
            "diagnostics": None,
        }


class TestUpdateFeedback:
    @pytest.mark.parametrize("is_read", [True, False])
    def test_sets_the_read_flag_and_commits(self, app, is_read):
        db = MagicMock()
        db.execute.return_value.rowcount = 1
        app.dependency_overrides[get_db] = lambda: db

        response = TestClient(app).patch(
            "/api/admin/feedback/5", json={"is_read": is_read}
        )

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert db.execute.call_args.args[1] == {"id": 5, "is_read": is_read}
        db.commit.assert_called_once()

    def test_missing_returns_404(self, app):
        db = MagicMock()
        db.execute.return_value.rowcount = 0
        app.dependency_overrides[get_db] = lambda: db

        response = TestClient(app).patch(
            "/api/admin/feedback/999", json={"is_read": True}
        )

        assert response.status_code == 404

    @pytest.mark.parametrize("body", [{}, {"is_read": "yes"}, {"is_read": 1}])
    def test_a_body_without_a_boolean_is_read_is_rejected(self, app, body):
        db = MagicMock()
        app.dependency_overrides[get_db] = lambda: db

        response = TestClient(app).patch("/api/admin/feedback/5", json=body)

        assert response.status_code == 400
        assert response.json()["code"] == "validation_error"
        db.execute.assert_not_called()

    def test_the_old_read_route_is_gone(self, app):
        response = TestClient(app).post("/api/admin/feedback/5/read")

        assert response.status_code == 404


class TestDeleteFeedback:
    def test_deletes_and_returns_json(self, app):
        db = MagicMock()
        db.execute.return_value.rowcount = 1
        app.dependency_overrides[get_db] = lambda: db

        response = TestClient(app).delete("/api/admin/feedback/5")

        assert response.status_code == 200
        assert response.json() == {"status": "deleted"}
        db.commit.assert_called_once()

    def test_missing_returns_404(self, app):
        db = MagicMock()
        db.execute.return_value.rowcount = 0
        app.dependency_overrides[get_db] = lambda: db

        response = TestClient(app).delete("/api/admin/feedback/999")

        assert response.status_code == 404


class TestAdminFeedbackAuth:
    """Auth via real main app (verify_admin_key NOT overridden)."""

    def test_missing_key_returns_401(self):
        from api.main import app as main_app

        response = TestClient(main_app).get("/api/admin/feedback")
        assert response.status_code == 401

    def test_wrong_key_returns_401(self):
        from api.main import app as main_app

        response = TestClient(main_app).get(
            "/api/admin/feedback",
            headers={"X-Admin-Key": "definitely-wrong-key-12345"},
        )
        assert response.status_code == 401
        assert response.json()["details"]["reason"] == "admin_key_invalid"
