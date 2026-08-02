"""
Integration tests for feedback endpoint.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.main import app
from core.database import get_db


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_db_insert():
    """Mock DB session returning inserted row id."""
    db = MagicMock()
    row = MagicMock()
    row.id = 7
    db.execute.return_value.fetchone.return_value = row
    return db


class TestSubmitFeedback:
    """Tests for POST /api/feedback."""

    def test_minimal_returns_200_and_commits(self, client, mock_db_insert):
        app.dependency_overrides[get_db] = lambda: mock_db_insert

        response = client.post(
            "/api/feedback", json={"message": "Nie dziala hydrogram"}
        )

        assert response.status_code == 200
        assert response.json() == {"id": 7, "status": "ok"}
        mock_db_insert.commit.assert_called_once()
        app.dependency_overrides.clear()

    def test_diagnostics_serialized_to_json_string(self, client, mock_db_insert):
        app.dependency_overrides[get_db] = lambda: mock_db_insert

        response = client.post(
            "/api/feedback",
            json={
                "message": "x",
                "diagnostics": {"events": [{"type": "map_click"}]},
            },
        )

        assert response.status_code == 200
        params = mock_db_insert.execute.call_args[0][1]
        assert isinstance(params["diagnostics"], str)
        assert '"map_click"' in params["diagnostics"]
        app.dependency_overrides.clear()

    def test_user_agent_from_header(self, client, mock_db_insert):
        app.dependency_overrides[get_db] = lambda: mock_db_insert

        client.post(
            "/api/feedback",
            json={"message": "x"},
            headers={"User-Agent": "TestBrowser/1.0"},
        )

        params = mock_db_insert.execute.call_args[0][1]
        assert params["user_agent"] == "TestBrowser/1.0"
        app.dependency_overrides.clear()

    def test_empty_message_returns_422(self, client):
        response = client.post("/api/feedback", json={"message": ""})
        assert response.status_code == 422

    def test_message_too_long_returns_422(self, client):
        response = client.post("/api/feedback", json={"message": "x" * 5001})
        assert response.status_code == 422

    def test_db_error_returns_500_and_rolls_back(self, client):
        db = MagicMock()
        db.execute.side_effect = RuntimeError("db down")
        app.dependency_overrides[get_db] = lambda: db

        response = client.post("/api/feedback", json={"message": "x"})

        assert response.status_code == 500
        db.rollback.assert_called_once()
        app.dependency_overrides.clear()
