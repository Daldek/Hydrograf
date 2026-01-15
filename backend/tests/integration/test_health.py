"""
Integration tests for health endpoint.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from api.main import app
from core.database import get_db


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_db_session():
    """Create mock database session."""
    return MagicMock()


def test_health_endpoint_returns_200(client, mock_db_session):
    """Test that health endpoint returns 200 status code."""
    app.dependency_overrides[get_db] = lambda: mock_db_session

    response = client.get("/health")

    assert response.status_code == 200
    app.dependency_overrides.clear()


def test_health_endpoint_response_structure(client, mock_db_session):
    """Test that health response has correct structure."""
    app.dependency_overrides[get_db] = lambda: mock_db_session

    response = client.get("/health")
    data = response.json()

    assert "status" in data
    assert "database" in data
    assert "version" in data
    app.dependency_overrides.clear()


def test_health_endpoint_database_connected(client, mock_db_session):
    """Test health reports connected when DB works."""
    app.dependency_overrides[get_db] = lambda: mock_db_session

    response = client.get("/health")
    data = response.json()

    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert data["version"] == "1.0.0"
    app.dependency_overrides.clear()


def test_health_endpoint_database_error(client):
    """Test health reports error when DB fails."""
    mock_session = MagicMock()
    mock_session.execute.side_effect = Exception("Connection refused")
    app.dependency_overrides[get_db] = lambda: mock_session

    response = client.get("/health")
    data = response.json()

    assert data["status"] == "unhealthy"
    assert "error" in data["database"]
    app.dependency_overrides.clear()


def test_root_endpoint(client):
    """Test root endpoint returns API info."""
    response = client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert data["message"] == "HydroLOG API"
