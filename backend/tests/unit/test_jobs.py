"""
The jobs of the long commands (api/jobs.py, api/endpoints/jobs.py; AGI-6.10, ADR-091).

`POST /api/v1/jobs` checks the options of a long command and answers 202 at once with
the job's document `nogat-job/1`; the job waits `queued` for one of the store's
workers, runs in a thread of its own and ends `succeeded`, `failed` or `cancelled`;
`GET /api/v1/jobs/<id>/result` then answers what the command's route would, the
envelope or the problem of its error, and `409 conflict` before. An ended job is
forgotten after `keep_s` (`404 job_expired`); the store lists the active jobs, without
their options, in its file, and a restart ends them `interrupted`; a client holds at
most 2 active jobs. Here `Runs` stands in for the command's computation: each run
holds its job `running` until the test lets it end.
"""

import dataclasses
import datetime
import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from api import catalog
from api.envelope import Notice, Outcome
from api.jobs import ACTIVE, Job, JobStore
from api.main import app
from api.traffic import JobSlots
from core.errors import InvalidRequestError, NoDataError, UnsupportedError
from core.version import get_version
from models.schemas import HydrographRequest

JOBS = "/api/v1/jobs"
COMMAND = "hydrograph generate"
OPTIONS = {"latitude": 52.23, "longitude": 21.01, "duration": "1h", "probability": 10}
START = {"command": COMMAND, "options": OPTIONS}
CLIENT = "203.0.113.77"
# What a run gives, and the result and notices of its envelope
OUTCOME = Outcome(
    {"peak_discharge_m3s": 12.5},
    notices=[
        Notice(
            level="warning",
            code="tc_out_of_range",
            message="Czas koncentracji poza zakresem metody.",
        )
    ],
)
RESULT = {"schema": "hydrograf-hydrograph/1", "peak_discharge_m3s": 12.5}
NOTICES = [
    {
        "level": "warning",
        "code": "tc_out_of_range",
        "message": "Czas koncentracji poza zakresem metody.",
    }
]
JOB_SCHEMA = Draft202012Validator(
    json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "schemas"
            / "nogat"
            / "job-1.schema.json"
        ).read_text(encoding="utf-8")
    )
)
# How long a test waits for a job's thread at most, and how often it looks [s]
TIMEOUT_S = 30.0
POLL_S = 0.005


class Runs:
    """The runs of ``hydrograph generate``: each holds its job running until let go.

    A run returns ``OUTCOME`` once ``finish`` lets it, or raises the error that
    ``fail`` makes when it is set.
    """

    def __init__(self) -> None:
        self.fail: Callable[[], Exception] | None = None
        self.started = 0
        self.most = 0
        self._running = 0
        self._changed = threading.Condition()
        self._go = threading.Semaphore(0)

    def __call__(self, options: Any, db: Any) -> Outcome:
        with self._changed:
            self.started += 1
            self._running += 1
            self.most = max(self.most, self._running)
            self._changed.notify_all()
        try:
            if not self._go.acquire(timeout=TIMEOUT_S):
                raise TimeoutError("the test did not let the run end")
            if self.fail is not None:
                raise self.fail()
            return OUTCOME
        finally:
            with self._changed:
                self._running -= 1

    def wait_started(self, count: int) -> None:
        """Wait until ``count`` runs have begun."""
        with self._changed:
            if not self._changed.wait_for(lambda: self.started >= count, TIMEOUT_S):
                raise AssertionError(f"{count} runs did not begin in {TIMEOUT_S} s")

    def finish(self, count: int = 1) -> None:
        """Let ``count`` runs end: those that wait, then the next to begin."""
        self._go.release(count)


def _no_database() -> AbstractContextManager[Any]:
    """Open the database session of a run: a mock, the runs here read none."""
    return nullcontext(MagicMock())


def _serve(monkeypatch: pytest.MonkeyPatch, run: Callable[[Any, Any], Outcome]) -> None:
    """Make ``run`` the computation of ``hydrograph generate``."""
    command = dataclasses.replace(catalog.BY_NAME[COMMAND], run=run)
    monkeypatch.setitem(catalog.BY_NAME, COMMAND, command)


def _until(condition: Callable[[], bool], what: str) -> None:
    """Look at ``condition`` until it holds; fail if it does not in ``TIMEOUT_S``."""
    deadline = time.monotonic() + TIMEOUT_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"{what}: not in {TIMEOUT_S} s")
        time.sleep(POLL_S)


def _end_of(job: Job) -> None:
    """Wait until ``job`` has ended."""
    _until(lambda: job.state not in ACTIVE, f"the end of the job {job.id}")


def _thread(job_id: str) -> threading.Thread:
    """Return the thread of the job ``job_id`` while it waits for a worker or runs."""
    name = f"hydrograf-job-{job_id[:8]}"
    [thread] = [t for t in threading.enumerate() if t.name == name]
    return thread


def _run_to_end(client: TestClient) -> tuple[dict[str, Any], httpx.Response]:
    """Start a job of the command and wait until it ends: its document and result."""
    started = client.post(JOBS, json=START)
    assert started.status_code == 202, started.text
    job_id = started.json()["id"]
    _end_of(app.state.jobs.get(job_id))
    document: dict[str, Any] = client.get(f"{JOBS}/{job_id}").json()
    return document, client.get(f"{JOBS}/{job_id}/result")


def _envelope(
    status: str, result: dict[str, Any] | None, notices: list[dict[str, str]]
) -> dict[str, Any]:
    """Return the envelope ``hydrograf-result/1`` of a job of the command."""
    return {
        "schema": "hydrograf-result/1",
        "tool": "hydrograf",
        "version": get_version(),
        "command": COMMAND,
        "check": False,
        "status": status,
        "result": result,
        "notices": notices,
    }


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> Iterator[Runs]:
    """Serve ``hydrograph generate`` with held runs; let them all end after the test."""
    held = Runs()
    _serve(monkeypatch, held)
    yield held
    held.finish(100)


@pytest.fixture
def install(monkeypatch: pytest.MonkeyPatch) -> Callable[..., JobStore]:
    """Return a function that makes a new job store of the given settings the app's."""

    def make(path: Path | None = None, **settings: Any) -> JobStore:
        store = JobStore(path, session=_no_database, **settings)
        monkeypatch.setattr(app.state, "jobs", store)
        return store

    return make


@pytest.fixture
def client(install: Callable[..., JobStore]) -> TestClient:
    """A client of the API whose jobs run without a database."""
    install()
    return TestClient(app)


class TestLifecycle:
    def test_a_job_is_queued_then_running_then_succeeded(self, client, install, runs):
        store = install(workers=1)
        # Another job holds the only worker, so the job waits queued
        assert client.post(JOBS, json=START).status_code == 202
        runs.wait_started(1)

        started = client.post(JOBS, json=START)
        job_id = started.json()["id"]
        queued = client.get(f"{JOBS}/{job_id}").json()
        early = client.get(f"{JOBS}/{job_id}/result")
        runs.finish()
        runs.wait_started(2)
        running = client.get(f"{JOBS}/{job_id}").json()
        runs.finish()
        _end_of(store.get(job_id))
        succeeded = client.get(f"{JOBS}/{job_id}").json()
        result = client.get(f"{JOBS}/{job_id}/result")

        assert started.status_code == 202
        assert started.headers["location"] == f"jobs/{job_id}"
        assert re.fullmatch(r"[0-9a-f]{32}", job_id)
        assert started.json() == queued
        documents = [queued, running, succeeded]
        for document in documents:
            JOB_SCHEMA.validate(document)
        assert [d["state"] for d in documents] == ["queued", "running", "succeeded"]
        assert {
            (d["schema"], d["id"], d["tool"], d["command"], d["created_at"])
            for d in documents
        } == {("nogat-job/1", job_id, "hydrograf", COMMAND, queued["created_at"])}
        assert running["started_at"] == succeeded["started_at"]
        created, began, ended = (
            datetime.datetime.fromisoformat(succeeded[key])
            for key in ("created_at", "started_at", "finished_at")
        )
        assert created <= began <= ended
        assert early.status_code == 409
        assert result.status_code == 200
        assert result.json() == _envelope("ok", RESULT, NOTICES)

    def test_at_most_workers_jobs_run_at_once_the_others_wait_queued(self, runs):
        store = JobStore(None, session=_no_database, workers=2)
        options = HydrographRequest.model_validate(OPTIONS)
        command = catalog.BY_NAME[COMMAND]
        jobs = [store.start(command, options, MagicMock()) for _ in "abc"]

        runs.wait_started(2)
        two_running = sorted(job.state for job in jobs)
        runs.finish()
        runs.wait_started(3)
        one_ended = sorted(job.state for job in jobs)
        runs.finish(2)
        for job in jobs:
            _end_of(job)

        assert two_running == ["queued", "running", "running"]
        assert one_ended == ["running", "running", "succeeded"]
        assert runs.most == 2

    def test_the_result_of_an_active_job_is_409_job_running(self, client, runs):
        job_id = client.post(JOBS, json=START).json()["id"]
        runs.wait_started(1)

        response = client.get(f"{JOBS}/{job_id}/result")

        assert response.status_code == 409
        assert response.headers["content-type"] == "application/problem+json"
        problem = response.json()
        assert problem["code"] == "conflict"
        assert problem["details"] == {"reason": "job_running", "job_id": job_id}
        assert problem["command"] == COMMAND


class TestFailure:
    @pytest.mark.parametrize(
        ("error", "status"),
        [
            (
                InvalidRequestError(
                    "tc_inputs_missing",
                    reason="missing_field",
                    method="faa",
                    missing=["tc_runoff_coeff"],
                ),
                400,
            ),
            (
                NoDataError(
                    "no_precipitation_data",
                    reason="no_precipitation_data",
                    latitude=52.23,
                    longitude=21.01,
                ),
                404,
            ),
            (
                UnsupportedError(
                    "catchment_too_large",
                    reason="area_exceeds_limit",
                    area_km2=312.5,
                    limit_km2=250,
                ),
                422,
            ),
        ],
        ids=["validation_error", "no_data", "unsupported"],
    )
    def test_a_failed_job_answers_the_problem_of_its_error(
        self, client, monkeypatch, error, status
    ):
        def fail(options, db):
            raise error

        _serve(monkeypatch, fail)

        document, response = _run_to_end(client)

        JOB_SCHEMA.validate(document)
        assert document["state"] == "failed"
        assert response.status_code == status
        assert response.headers["content-type"] == "application/problem+json"
        problem = response.json()
        assert (problem["status"], problem["code"]) == (status, error.code)
        assert problem["details"] == error.details
        assert problem["command"] == COMMAND

    def test_an_unexpected_exception_fails_the_job_with_job_failed(
        self, client, monkeypatch, caplog
    ):
        def crash(options, db):
            raise RuntimeError("cannot open /data/hydrograf/secret.tif")

        _serve(monkeypatch, crash)

        with caplog.at_level(logging.ERROR, logger="api.jobs"):
            document, response = _run_to_end(client)

        assert document["state"] == "failed"
        assert response.status_code == 500
        problem = response.json()
        assert problem["code"] == "internal_error"
        assert problem["details"] == {"reason": "job_failed"}
        assert problem["command"] == COMMAND
        assert "secret.tif" not in response.text
        # The operator finds the traceback in the app log
        [record] = [r for r in caplog.records if r.name == "api.jobs"]
        assert record.levelno == logging.ERROR
        assert record.exc_info is not None


class TestCancel:
    def test_a_cancelled_queued_job_never_starts(self, client, install, runs):
        install(workers=1)
        assert client.post(JOBS, json=START).status_code == 202
        runs.wait_started(1)
        queued = client.post(JOBS, json=START).json()
        job_id = queued["id"]
        waiting = _thread(job_id)

        cancelled = client.post(f"{JOBS}/{job_id}/cancel")
        result = client.get(f"{JOBS}/{job_id}/result")
        # Its place in the client's limit comes back at once
        another = client.post(JOBS, json=START)
        # The worker becomes free and the cancelled job's thread passes it
        runs.finish(2)
        waiting.join(TIMEOUT_S)
        after = client.get(f"{JOBS}/{job_id}").json()

        assert queued["state"] == "queued"
        assert cancelled.status_code == 202
        document = cancelled.json()
        JOB_SCHEMA.validate(document)
        assert (document["state"], document["started_at"]) == ("cancelled", None)
        assert document["finished_at"] is not None
        assert result.status_code == 200
        assert result.json() == _envelope("cancelled", None, [])
        assert another.status_code == 202
        assert not waiting.is_alive()
        assert after == document

    def test_a_cancelled_running_job_ends_cancelled_when_its_run_returns(
        self, client, runs
    ):
        job_id = client.post(JOBS, json=START).json()["id"]
        runs.wait_started(1)
        job = app.state.jobs.get(job_id)

        cancelled = client.post(f"{JOBS}/{job_id}/cancel")
        before_the_end = client.get(f"{JOBS}/{job_id}/result")
        runs.finish()
        _end_of(job)
        document = client.get(f"{JOBS}/{job_id}").json()
        result = client.get(f"{JOBS}/{job_id}/result")

        assert cancelled.status_code == 202
        assert cancelled.json()["state"] == "running"
        assert before_the_end.status_code == 409
        JOB_SCHEMA.validate(document)
        assert document["state"] == "cancelled"
        assert document["started_at"] is not None
        assert result.status_code == 200
        # The run's result and notices are discarded
        assert result.json() == _envelope("cancelled", None, [])

    def test_cancelling_an_ended_job_changes_nothing(self, client, monkeypatch):
        _serve(monkeypatch, lambda options, db: OUTCOME)
        document, _ = _run_to_end(client)

        cancelled = client.post(f"{JOBS}/{document['id']}/cancel")
        result = client.get(f"{JOBS}/{document['id']}/result")

        assert cancelled.status_code == 202
        assert cancelled.json() == document
        assert result.json() == _envelope("ok", RESULT, NOTICES)


class TestExpiry:
    def test_an_ended_job_is_forgotten_after_keep_s(self, client, install, runs):
        store = install(keep_s=0.0)
        job_id = client.post(JOBS, json=START).json()["id"]
        runs.wait_started(1)
        job = store.get(job_id)

        # An active job is kept however long it runs
        while_running = client.get(f"{JOBS}/{job_id}")
        runs.finish()
        _end_of(job)
        _until(
            lambda: client.get(f"{JOBS}/{job_id}").status_code == 404,
            "the expiry of the job",
        )
        answers = [
            client.get(f"{JOBS}/{job_id}"),
            client.get(f"{JOBS}/{job_id}/result"),
            client.post(f"{JOBS}/{job_id}/cancel"),
        ]

        assert while_running.status_code == 200
        for response in answers:
            assert response.status_code == 404
            problem = response.json()
            assert problem["code"] == "not_found"
            assert problem["details"] == {"reason": "job_expired", "job_id": job_id}

    def test_an_unknown_job_is_404_job_expired(self, client):
        job_id = "0123456789abcdef0123456789abcdef"

        response = client.get(f"{JOBS}/{job_id}")

        assert response.status_code == 404
        assert response.json()["details"] == {
            "reason": "job_expired",
            "job_id": job_id,
        }


class TestRestart:
    def test_the_jobs_file_lists_the_active_jobs_without_options_or_client(
        self, tmp_path, client, install, runs
    ):
        path = tmp_path / "jobs.json"
        previous = JobStore(path, session=_no_database, workers=1)
        options = HydrographRequest.model_validate(
            {**OPTIONS, "latitude": 52.123456, "longitude": 21.654321}
        )
        slots = JobSlots(2)
        command = catalog.BY_NAME[COMMAND]
        running = previous.start(command, options, slots.take(CLIENT))
        runs.wait_started(1)
        queued = previous.start(command, options, slots.take(CLIENT))
        listed = path.read_text(encoding="utf-8")
        runs.finish(2)
        for job in (running, queued):
            _end_of(job)
        # A restart after they ended knows neither
        install(path).interrupt_previous()
        known = [
            client.get(f"{JOBS}/{job.id}").status_code for job in (running, queued)
        ]

        for value in (
            running.id,
            running.created_at,
            running.started_at,
            queued.id,
            queued.created_at,
        ):
            assert value in listed
        for private in ("52.123456", "21.654321", CLIENT):
            assert private not in listed
        assert known == [404, 404]

    def test_a_restart_ends_the_jobs_left_active_interrupted(
        self, tmp_path, client, install, runs
    ):
        path = tmp_path / "jobs.json"
        previous = JobStore(path, session=_no_database, workers=1)
        options = HydrographRequest.model_validate(OPTIONS)
        command = catalog.BY_NAME[COMMAND]
        running = previous.start(command, options, MagicMock())
        runs.wait_started(1)
        queued = previous.start(command, options, MagicMock())
        left = {job.id: job.document() for job in (running, queued)}

        install(path).interrupt_previous()
        documents = [client.get(f"{JOBS}/{job_id}").json() for job_id in left]
        result = client.get(f"{JOBS}/{running.id}/result")

        for document in documents:
            JOB_SCHEMA.validate(document)
            before = left[document["id"]]
            assert document["state"] == "interrupted"
            assert (
                document["command"],
                document["created_at"],
                document["started_at"],
            ) == (before["command"], before["created_at"], before["started_at"])
            assert document["finished_at"] is not None
        assert result.status_code == 409
        problem = result.json()
        assert problem["code"] == "conflict"
        assert problem["details"] == {
            "reason": "job_interrupted",
            "job_id": running.id,
        }
        assert problem["command"] == COMMAND

    @pytest.mark.parametrize(
        "spoil",
        [
            lambda path: path.write_text("{not json", encoding="utf-8"),
            lambda path: path.write_text('["active"]', encoding="utf-8"),
            lambda path: path.write_text('{"jobs": []}', encoding="utf-8"),
            lambda path: path.write_text('{"active": null}', encoding="utf-8"),
            lambda path: path.mkdir(),
        ],
        ids=["not-json", "a-list", "no-active", "active-null", "a-directory"],
    )
    def test_an_unreadable_jobs_file_is_logged_and_ignored(
        self, tmp_path, client, install, monkeypatch, caplog, spoil
    ):
        path = tmp_path / "jobs.json"
        spoil(path)
        store = install(path)
        _serve(monkeypatch, lambda options, db: OUTCOME)

        with caplog.at_level(logging.WARNING, logger="api.jobs"):
            store.interrupt_previous()
        warnings = [
            r
            for r in caplog.records
            if r.name == "api.jobs"
            and r.levelno == logging.WARNING
            and str(path) in r.getMessage()
        ]
        document, result = _run_to_end(client)

        assert warnings
        assert document["state"] == "succeeded"
        assert result.status_code == 200

    def test_a_first_start_without_a_jobs_file_logs_nothing(self, tmp_path, caplog):
        store = JobStore(tmp_path / "jobs.json", session=_no_database)

        with caplog.at_level(logging.DEBUG, logger="api.jobs"):
            store.interrupt_previous()

        assert [r for r in caplog.records if r.name == "api.jobs"] == []


class TestClientLimit:
    def test_a_client_holds_at_most_2_active_jobs(self, client, runs):
        first = [client.post(JOBS, json=START).status_code for _ in "ab"]

        refused = client.post(JOBS, json=START)

        assert first == [202, 202]
        assert refused.status_code == 429
        assert refused.headers["Retry-After"] == "10"
        assert refused.headers["content-type"] == "application/problem+json"
        problem = refused.json()
        assert problem["code"] == "rate_limited"
        assert problem["details"] == {
            "reason": "job_limit",
            "retry_after_s": 10,
            "limit": 2,
        }

    @pytest.mark.parametrize(
        "fail",
        [
            None,
            lambda: NoDataError(
                "no_precipitation_data",
                reason="no_precipitation_data",
                latitude=52.23,
                longitude=21.01,
            ),
            lambda: RuntimeError("the run broke"),
        ],
        ids=["succeeded", "failed", "crashed"],
    )
    def test_an_ended_job_gives_its_place_back(self, client, runs, fail):
        runs.fail = fail
        ids = [client.post(JOBS, json=START).json()["id"] for _ in "ab"]
        jobs = [app.state.jobs.get(job_id) for job_id in ids]
        refused = client.post(JOBS, json=START)
        runs.finish()
        _until(lambda: any(job.state not in ACTIVE for job in jobs), "a job's end")

        again = client.post(JOBS, json=START)

        assert refused.status_code == 429
        assert again.status_code == 202


class TestRefusedStart:
    def test_a_command_that_is_no_job_is_400_not_a_job(self, client):
        options = {"latitude": 52.23, "longitude": 21.01}

        response = client.post(
            JOBS, json={"command": "watershed delineate", "options": options}
        )

        assert response.status_code == 400
        problem = response.json()
        assert problem["code"] == "validation_error"
        details = problem["details"]
        assert details["reason"] == "not_a_job"
        # It names the command's own route and the commands that run as jobs
        assert details["path"] == "/api/v1/watershed/delineate"
        assert sorted(details["allowed"]) == [
            "hydrograph generate",
            "network delineate",
        ]

    def test_an_unknown_command_is_400_unknown_command(self, client):
        response = client.post(
            JOBS, json={"command": "hydrograph forecast", "options": {}}
        )

        assert response.status_code == 400
        problem = response.json()
        assert problem["code"] == "validation_error"
        assert problem["details"]["reason"] == "unknown_command"
        assert problem["details"]["command"] == "hydrograph forecast"
        assert COMMAND in problem["details"]["allowed"]

    def test_invalid_options_are_named_under_body_options(self, client):
        options = {"latitude": 95, "duration": "1h", "probability": 10}

        response = client.post(JOBS, json={"command": COMMAND, "options": options})

        assert response.status_code == 400
        problem = response.json()
        assert problem["code"] == "validation_error"
        pointers = ["/body/options/latitude", "/body/options/longitude"]
        assert problem["details"]["fields"] == pointers
        assert sorted(error["pointer"] for error in problem["errors"]) == pointers

    def test_a_refused_start_takes_no_place_in_the_limit(self, client, runs):
        refused = [
            client.post(JOBS, json={"command": command, "options": {}}).status_code
            for command in ("watershed delineate", COMMAND)
        ]

        started = [client.post(JOBS, json=START).status_code for _ in "ab"]

        assert refused == [400, 400]
        assert started == [202, 202]
