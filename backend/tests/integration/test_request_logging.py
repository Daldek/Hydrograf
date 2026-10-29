"""Request IDs and timing remain available when requests succeed or fail."""

import json
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.main import add_request_id, app


def _request_event(caplog, event):
    return next(
        json.loads(record.message)
        for record in caplog.records
        if record.name == "api.requests"
        and json.loads(record.message).get("event") == event
    )


def test_forwarded_request_id_matches_response_and_log(caplog):
    request_id = "0123456789abcdef0123456789abcdef"
    with caplog.at_level(logging.INFO, logger="api.requests"):
        response = TestClient(app).get("/", headers={"X-Request-ID": request_id})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id
    event = _request_event(caplog, "request_completed")
    assert event["request_id"] == request_id
    assert event["status_code"] == 200
    assert event["method"] == "GET"
    assert event["path"] == "/"
    assert event["duration_ms"] >= 0


def test_unhandled_error_is_logged_with_request_id_and_duration(caplog):
    failing_app = FastAPI()
    failing_app.middleware("http")(add_request_id)

    @failing_app.get("/fail")
    def fail():
        raise RuntimeError("test failure")

    request_id = "fedcba9876543210fedcba9876543210"
    with caplog.at_level(logging.ERROR, logger="api.requests"):
        response = TestClient(failing_app, raise_server_exceptions=False).get(
            "/fail", headers={"X-Request-ID": request_id}
        )

    assert response.status_code == 500
    event = _request_event(caplog, "request_failed")
    assert event["request_id"] == request_id
    assert event["status_code"] == 500
    assert event["path"] == "/fail"
    assert event["duration_ms"] >= 0
