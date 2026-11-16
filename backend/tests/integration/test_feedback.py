"""
„Zgłoś uwagę”, POST /api/feedback (Nogat DEV-15.12, ADR-084).

A report stores its text and the context of the view with the server's app version,
and nothing that names its sender: a contact or another member is refused, and the
User-Agent of the request is not stored.
"""

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.main import app
from core.database import get_db
from core.version import get_version

CONTEXT = {
    "view": "select",
    "station": None,
    "parameters": {"map": {"center": {"lat": 51.2, "lng": 16.2}, "zoom": 12}},
}


@pytest.fixture
def db():
    """A database session whose INSERT returns the id 7."""
    session = MagicMock()
    row = MagicMock()
    row.id = 7
    session.execute.return_value.fetchone.return_value = row
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _stored(db):
    """The parameters of the INSERT."""
    return db.execute.call_args[0][1]


class TestSubmitFeedback:
    def test_report_stores_its_text_and_context_with_the_app_version(self, client, db):
        response = client.post(
            "/api/feedback",
            json={"message": "Nie działa hydrogram", "context": CONTEXT},
            headers={"User-Agent": "TestBrowser/1.0"},
        )

        assert response.status_code == 200
        assert response.json() == {"id": 7, "status": "ok"}
        db.commit.assert_called_once()
        stored = _stored(db)
        assert set(stored) == {"message", "context"}
        assert stored["message"] == "Nie działa hydrogram"
        assert json.loads(stored["context"]) == {
            **CONTEXT,
            "app_version": get_version(),
        }
        assert "TestBrowser" not in str(db.execute.call_args)

    def test_station_and_parameters_may_be_left_out(self, client, db):
        response = client.post(
            "/api/feedback", json={"message": "x", "context": {"view": "browse"}}
        )

        assert response.status_code == 200
        assert json.loads(_stored(db)["context"]) == {
            "view": "browse",
            "station": None,
            "parameters": {},
            "app_version": get_version(),
        }

    @pytest.mark.parametrize(
        "member",
        ["contact", "page_url", "user_agent", "diagnostics", "app_version"],
    )
    def test_any_other_member_is_refused(self, client, db, member):
        response = client.post(
            "/api/feedback",
            json={"message": "x", "context": CONTEXT, member: "jan@example.com"},
            headers={"Accept-Language": "pl"},
        )

        assert response.status_code == 400
        problem = response.json()
        assert problem["code"] == "validation_error"
        assert problem["errors"][0]["pointer"] == f"/body/{member}"
        assert problem["errors"][0]["message"] == "Nieznane pole."
        db.execute.assert_not_called()

    def test_contact_inside_the_context_is_refused(self, client, db):
        context = {**CONTEXT, "contact": "jan@example.com"}

        response = client.post(
            "/api/feedback", json={"message": "x", "context": context}
        )

        assert response.status_code == 400
        assert response.json()["errors"][0]["pointer"] == "/body/context/contact"
        db.execute.assert_not_called()

    def test_report_without_a_context_is_refused(self, client, db):
        response = client.post("/api/feedback", json={"message": "x"})

        assert response.status_code == 400
        assert response.json()["errors"][0]["pointer"] == "/body/context"

    def test_context_above_100_kb_is_refused(self, client, db):
        context = {**CONTEXT, "parameters": {"profileLine": "x" * 100_000}}

        response = client.post(
            "/api/feedback", json={"message": "x", "context": context}
        )

        assert response.status_code == 400
        db.execute.assert_not_called()

    @pytest.mark.parametrize("message", ["", "x" * 5001], ids=["empty", "too-long"])
    def test_message_outside_1_to_5000_characters_is_refused(self, client, db, message):
        response = client.post(
            "/api/feedback", json={"message": message, "context": CONTEXT}
        )

        assert response.status_code == 400
        db.execute.assert_not_called()

    def test_db_error_returns_500_and_rolls_back(self, client):
        session = MagicMock()
        session.execute.side_effect = RuntimeError("db down")
        app.dependency_overrides[get_db] = lambda: session
        try:
            response = client.post(
                "/api/feedback", json={"message": "x", "context": CONTEXT}
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 500
        session.rollback.assert_called_once()
