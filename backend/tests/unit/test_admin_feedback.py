"""Tests for admin feedback endpoints."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies.admin_auth import verify_admin_key
from api.endpoints.feedback import admin_router
from core.database import get_db


def _noop_auth():
    return None


@pytest.fixture
def app():
    test_app = FastAPI()
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
        item = _row(
            id=1,
            created_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
            message="m",
            contact=None,
            page_url=None,
            user_agent="UA",
            diagnostics=None,
            is_read=False,
        )
        db.execute.return_value.fetchall.return_value = [item]
        db.execute.return_value.fetchone.return_value = _row(total=1, unread=1)
        app.dependency_overrides[get_db] = lambda: db

        response = TestClient(app).get("/api/admin/feedback")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["unread_count"] == 1
        assert data["items"][0]["message"] == "m"
        assert data["items"][0]["created_at"].startswith("2026-08-02")


class TestMarkFeedbackRead:
    def test_marks_and_commits(self, app):
        db = MagicMock()
        db.execute.return_value.rowcount = 1
        app.dependency_overrides[get_db] = lambda: db

        response = TestClient(app).post("/api/admin/feedback/5/read")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        db.commit.assert_called_once()

    def test_missing_returns_404(self, app):
        db = MagicMock()
        db.execute.return_value.rowcount = 0
        app.dependency_overrides[get_db] = lambda: db

        response = TestClient(app).post("/api/admin/feedback/999/read")

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

    def test_wrong_key_returns_403(self):
        from api.main import app as main_app

        response = TestClient(main_app).get(
            "/api/admin/feedback",
            headers={"X-Admin-Key": "definitely-wrong-key-12345"},
        )
        assert response.status_code == 403
