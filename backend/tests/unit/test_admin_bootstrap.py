"""Tests for admin bootstrap endpoints."""

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies.admin_auth import verify_admin_key
from api.endpoints.admin import (
    _bootstrap_state,
    _validate_bbox,
    router,
)


def _noop_auth():
    return None


@pytest.fixture
def app():
    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/admin")
    test_app.dependency_overrides[verify_admin_key] = _noop_auth
    yield test_app
    test_app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_bootstrap_state():
    """Reset bootstrap state before each test."""
    _bootstrap_state["process"] = None
    _bootstrap_state["status"] = "idle"
    _bootstrap_state["log_lines"] = []
    _bootstrap_state["started_at"] = None
    _bootstrap_state["params"] = None
    yield
    # Cleanup after test
    proc = _bootstrap_state.get("process")
    if proc is not None:
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass
    _bootstrap_state["process"] = None
    _bootstrap_state["status"] = "idle"
    _bootstrap_state["log_lines"] = []
    _bootstrap_state["started_at"] = None
    _bootstrap_state["params"] = None


class TestValidateBbox:
    """Tests for _validate_bbox helper."""

    def test_valid_bbox(self):
        """Valid bbox is parsed correctly."""
        result = _validate_bbox("20.8,52.1,21.2,52.4")
        assert result == (20.8, 52.1, 21.2, 52.4)

    def test_wrong_number_of_values(self):
        """Bbox with wrong number of values raises ValueError."""
        with pytest.raises(ValueError, match="4 comma-separated"):
            _validate_bbox("20.8,52.1,21.2")

    def test_non_numeric_values(self):
        """Non-numeric values raise ValueError."""
        with pytest.raises(ValueError, match="valid numbers"):
            _validate_bbox("a,b,c,d")

    def test_min_lon_ge_max_lon(self):
        """min_lon >= max_lon raises ValueError."""
        with pytest.raises(ValueError, match="min_lon"):
            _validate_bbox("21.2,52.1,20.8,52.4")

    def test_min_lat_ge_max_lat(self):
        """min_lat >= max_lat raises ValueError."""
        with pytest.raises(ValueError, match="min_lat"):
            _validate_bbox("20.8,52.4,21.2,52.1")


class TestBootstrapStatus:
    """Tests for GET /api/admin/bootstrap/status."""

    def test_idle_status(self, app):
        """Returns idle status when no process is running."""
        client = TestClient(app)
        response = client.get("/api/admin/bootstrap/status")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "idle"
        assert data["log_lines"] == 0
        assert data["pid"] is None

    def test_running_status(self, app):
        """Returns running status with PID when process is active."""
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        _bootstrap_state["process"] = mock_proc
        _bootstrap_state["status"] = "running"
        _bootstrap_state["started_at"] = time.time()

        client = TestClient(app)
        response = client.get("/api/admin/bootstrap/status")
        data = response.json()

        assert data["status"] == "running"
        assert data["pid"] == 12345

        _bootstrap_state["process"] = None


class TestBootstrapStart:
    """Tests for POST /api/admin/bootstrap/start."""

    def test_start_requires_bbox_or_sheets(self, app):
        """Start without bbox or sheets returns 400."""
        client = TestClient(app)
        response = client.post(
            "/api/admin/bootstrap/start",
            json={},
        )
        assert response.status_code == 400

    def test_start_rejects_when_running(self, app):
        """Start when already running returns 409."""
        _bootstrap_state["status"] = "running"

        client = TestClient(app)
        response = client.post(
            "/api/admin/bootstrap/start",
            json={"bbox": "20.8,52.1,21.2,52.4"},
        )
        assert response.status_code == 409

    @patch("api.endpoints.admin.subprocess.Popen")
    def test_start_with_bbox(self, mock_popen, app):
        """Start with valid bbox starts subprocess."""
        mock_proc = MagicMock()
        mock_proc.pid = 99999
        mock_proc.stdout = iter([])  # Empty iterator for thread
        mock_proc.wait.return_value = 0
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        client = TestClient(app)
        response = client.post(
            "/api/admin/bootstrap/start",
            json={"bbox": "20.8,52.1,21.2,52.4"},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "running"
        assert data["pid"] == 99999

        # Wait for background thread to finish
        time.sleep(0.2)

    @patch("api.endpoints.admin.subprocess.Popen")
    def test_start_with_sheets(self, mock_popen, app):
        """Start with sheet codes starts subprocess."""
        mock_proc = MagicMock()
        mock_proc.pid = 88888
        mock_proc.stdout = iter([])
        mock_proc.wait.return_value = 0
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc

        client = TestClient(app)
        response = client.post(
            "/api/admin/bootstrap/start",
            json={"sheets": ["N-34-131-C-c-2-1"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"

        time.sleep(0.2)

    def test_start_with_invalid_bbox(self, app):
        """Start with invalid bbox returns 400."""
        client = TestClient(app)
        response = client.post(
            "/api/admin/bootstrap/start",
            json={"bbox": "invalid"},
        )
        assert response.status_code == 400


class TestBootstrapCancel:
    """Tests for POST /api/admin/bootstrap/cancel."""

    def test_cancel_when_idle(self, app):
        """Cancel when no process running returns 409."""
        client = TestClient(app)
        response = client.post("/api/admin/bootstrap/cancel")
        assert response.status_code == 409

    def test_cancel_running_process(self, app):
        """Cancel sends SIGTERM to running process."""
        mock_proc = MagicMock()
        mock_proc.pid = 77777
        _bootstrap_state["process"] = mock_proc
        _bootstrap_state["status"] = "running"

        client = TestClient(app)
        response = client.post("/api/admin/bootstrap/cancel")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "cancelled"
        mock_proc.send_signal.assert_called_once()

        _bootstrap_state["process"] = None


class TestBootstrapStream:
    """Tests for GET /api/admin/bootstrap/stream."""

    def test_stream_returns_event_stream(self, app):
        """Stream endpoint returns text/event-stream content type."""
        # Set state to idle so stream immediately finishes
        _bootstrap_state["status"] = "idle"

        client = TestClient(app)
        response = client.get("/api/admin/bootstrap/stream")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

    def test_stream_sends_done_event(self, app):
        """Stream sends done event when status is completed."""
        _bootstrap_state["status"] = "completed"
        _bootstrap_state["log_lines"] = ["line1", "line2"]

        client = TestClient(app)
        response = client.get("/api/admin/bootstrap/stream")
        body = response.text

        assert "data: line1" in body
        assert "data: line2" in body
        assert "event: done" in body
