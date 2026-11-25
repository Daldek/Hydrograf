"""Run a job of a long command through the API as a client does (AGI-6.10, ADR-091).

``POST /api/v1/jobs`` starts it, the job's thread runs it (on the test's ``get_db``
override, ``tests/conftest.py``) and ``GET /api/v1/jobs/<id>/result`` answers what the
command's synchronous route would: the envelope, or the problem of a failed job.
"""

import time
from typing import Any

import httpx
from fastapi.testclient import TestClient

from api.jobs import ACTIVE, JobStore
from api.main import app

JOBS = "/api/v1/jobs"


def run_job(
    client: TestClient,
    command: str,
    options: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout_s: float = 60.0,
) -> httpx.Response:
    """Start a job of ``command``, wait until it ends and return its result's answer.

    A refused start (a status other than 202) is returned as it is: a 400 of invalid
    options names them under ``/body/options``.
    """
    started: httpx.Response = client.post(
        JOBS, json={"command": command, "options": options}, headers=headers
    )
    if started.status_code != 202:
        return started
    job_id = started.json()["id"]
    store: JobStore = app.state.jobs
    deadline = time.monotonic() + timeout_s
    while store.get(job_id).state in ACTIVE:
        if time.monotonic() > deadline:
            raise AssertionError(f"the job of {command} did not end in {timeout_s} s")
        time.sleep(0.005)
    result: httpx.Response = client.get(f"{JOBS}/{job_id}/result", headers=headers)
    return result
