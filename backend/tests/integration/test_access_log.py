"""
The access log of the API (api/main.py; Nogat DEV-12.4 to DEV-12.8, ECO-066).

Every request through the app writes one record `nogat-log/1` that Nogat's schema
accepts, without the client's address, and the answer carries no request id: the
record's id is random and never sent, nor is a forwarded `X-Request-ID` believed.
The refusals of the request limit are logged too (tests/integration/test_traffic.py).
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from api.main import app

SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[3]
        / "schemas"
        / "nogat"
        / "record-1.schema.json"
    ).read_text(encoding="utf-8")
)
FORWARDED_ID = "0123456789abcdef0123456789abcdef"
CLIENT = "203.0.113.77"


def test_a_request_writes_one_valid_access_record_and_sends_no_request_id(
    log_records,
):
    response = TestClient(app, client=("172.18.0.3", 50000)).get(
        "/api/gui",
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/140.0",
            "X-Request-ID": FORWARDED_ID,
            "X-Real-IP": "172.18.0.1",
            "CF-Connecting-IP": CLIENT,
        },
    )

    assert response.status_code == 200
    assert "x-request-id" not in response.headers
    [record] = [r for r in log_records() if r["kind"] == "access"]
    Draft202012Validator(SCHEMA).validate(record)
    assert (record["app"], record["method"], record["path"]) == (
        "hydrograf",
        "GET",
        "/api/gui",
    )
    assert (record["status"], record["agent"]) == (200, "browser")
    assert record["request_id"] not in (FORWARDED_ID, FORWARDED_ID[:16])
    assert CLIENT not in json.dumps(record)
    assert "172.18.0" not in json.dumps(record)
