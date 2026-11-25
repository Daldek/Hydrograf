"""Contract: Hydrograf's agent documents against the copies of Nogat's schemas.

The command catalog ``hydrograf-commands/1`` and its summary
``hydrograf-command-list/1`` (AGI §2), the result envelope ``hydrograf-result/1`` of a
command (AGI-4.2), the problems of a command's route (AGI-6.3), the server's
``nogat-server/1`` (AGI-6.7) and a job's ``nogat-job/1`` (AGI-6.10) validate against
``schemas/nogat/`` (ADR-091); the catalog's functions, routes and examples are those
the API runs and serves.
"""

import dataclasses
import importlib
import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from api import API_BASE, catalog
from api.catalog import BY_NAME, COMMANDS, Command, command_list, command_schema
from api.envelope import Outcome
from api.jobs import JobStore
from api.main import app
from core.database import get_db
from core.terms import URL, Terms

SCHEMAS = Path(__file__).resolve().parents[3] / "schemas" / "nogat"
_COPIES = {
    path.name: json.loads(path.read_text(encoding="utf-8"))
    for path in SCHEMAS.glob("*.schema.json")
}
REGISTRY: Registry[Any] = Registry().with_resources(
    (copy["$id"], Resource.from_contents(copy)) for copy in _COPIES.values()
)
AGENT = "https://github.com/Daldek/Nogat/schemas/agent"


def _validator(schema: dict[str, Any]) -> Draft202012Validator:
    return Draft202012Validator(
        schema, registry=REGISTRY, format_checker=Draft202012Validator.FORMAT_CHECKER
    )


COMMANDS_1 = _validator(_COPIES["commands-1.schema.json"])
COMMAND_LIST_1 = _validator(_COPIES["command-list-1.schema.json"])
RESULT_1 = _validator(_COPIES["result-1.schema.json"])
SERVER_1 = _validator(_COPIES["server-1.schema.json"])
JOB_1 = _validator(_COPIES["job-1.schema.json"])
JOB_START = _validator({"$ref": f"{_COPIES['job-1.schema.json']['$id']}#/$defs/start"})
COMMAND_NAME = _validator(
    {"$ref": f"{AGENT}/commands-1.schema.json#/$defs/command_name"}
)
ERROR_CODE = _validator({"$ref": f"{AGENT}/error-1.schema.json#/$defs/code"})
REASON = _validator({"$ref": f"{AGENT}/error-1.schema.json#/$defs/reason"})
# A body of `hydrograph generate` that its model accepts without a database
HYDROGRAPH = {
    "latitude": 51.01917,
    "longitude": 15.88497,
    "duration": "1h",
    "probability": 10,
}


def _errors(validator: Draft202012Validator, document: Any) -> list[str]:
    """Every violation of ``document``, each with the JSON path of its place."""
    return [
        f"{error.json_path}: {error.message}"
        for error in validator.iter_errors(document)
    ]


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: MagicMock()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---- The catalog ---------------------------------------------------------------------


def test_catalog_is_a_commands_1_document():
    assert _errors(COMMANDS_1, command_schema()) == []


def test_command_list_is_a_command_list_1_document():
    assert _errors(COMMAND_LIST_1, command_list()) == []


def test_list_summarises_the_entries_of_the_catalog():
    entries = {entry["name"]: entry for entry in command_schema()["commands"]}
    rows = command_list()["commands"]

    assert [row["name"] for row in rows] == list(entries)
    for row in rows:
        entry = entries[row["name"]]
        for key in ("operation_id", "summary", "effects", "check", "rest"):
            assert row[key] == entry[key], (row["name"], key)
        assert row["read_only"] == entry["effects"]["read_only"]
        assert row.get("long", False) == entry.get("long", False)


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: c.name)
def test_command_names_the_function_that_runs_it(command):
    module, _, name = command.function.rpartition(".")

    assert getattr(importlib.import_module(module), name) is command.run


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: c.name)
def test_command_is_served_at_its_group_and_verb(command):
    group, verb = command.name.split()

    assert command.rest == {
        "method": command.method,
        "path": f"{API_BASE}/{group}/{verb}",
        "key": False,
    }


def test_the_long_commands_are_the_hydrograph_and_the_network():
    assert sorted(catalog.LONG) == ["hydrograph generate", "network delineate"]


def _example_options(command: Command, call: str) -> dict[str, Any]:
    """Return the options an example's call gives its command."""
    if command.long:
        start = json.loads(call.removeprefix(f"POST {API_BASE}/jobs "))
        assert start["command"] == command.name
        assert _errors(JOB_START, start) == []
        options: dict[str, Any] = start["options"]
        return options
    method, _, rest = call.partition(" ")
    assert method == command.method
    if method == "POST":
        path, _, body = rest.partition(" ")
        assert path == command.path
        options = json.loads(body)
        return options
    url = urlsplit(rest)
    assert url.path == command.path
    return {
        key: values if len(values) > 1 else values[0]
        for key, values in parse_qs(url.query).items()
    }


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: c.name)
def test_examples_call_the_route_of_their_command_with_valid_options(command):
    for example in command.examples:
        options = _example_options(command, example.call)

        command.options.model_validate(options)
        assert example.result["status"] == "ok"
        assert example.result["result"]["schema"] == command.result


# ---- The routes of the catalog -------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "schema", "validator"),
    [
        ("/commands/list", "hydrograf-command-list/1", COMMAND_LIST_1),
        ("/commands/schema", "hydrograf-commands/1", COMMANDS_1),
    ],
    ids=["commands list", "commands schema"],
)
def test_catalog_routes_answer_envelopes_of_their_documents(
    client, path, schema, validator
):
    response = client.get(f"{API_BASE}{path}")

    assert response.status_code == 200
    body = response.json()
    assert _errors(RESULT_1, body) == []
    assert body["command"] == path.strip("/").replace("/", " ")
    assert body["result"]["schema"] == schema
    assert _errors(validator, body["result"]) == []


def test_commands_schema_of_one_command_is_its_entry(client):
    response = client.get(
        f"{API_BASE}/commands/schema", params={"command": "precipitation depth"}
    )

    assert response.status_code == 200
    assert response.json()["result"]["commands"] == [
        catalog.entry(BY_NAME["precipitation depth"])
    ]


def test_commands_schema_of_an_unknown_command_is_400(client):
    response = client.get(
        f"{API_BASE}/commands/schema", params={"command": "watershed fill"}
    )

    assert response.status_code == 400
    problem = response.json()
    assert problem["code"] == "validation_error"
    assert problem["command"] == "commands schema"
    assert problem["details"]["reason"] == "unknown_command"
    assert problem["details"]["allowed"] == sorted(BY_NAME)


def test_scenarios_answer_a_result_1_envelope(client):
    body = client.get(f"{API_BASE}/hydrograph/scenarios").json()

    assert _errors(RESULT_1, body) == []
    assert (body["command"], body["status"], body["notices"]) == (
        "hydrograph scenarios",
        "ok",
        [],
    )
    assert body["result"]["schema"] == "hydrograf-scenarios/1"


@pytest.mark.parametrize(
    "command",
    [c for c in COMMANDS if any(o["required"] for o in catalog.options_of(c))],
    ids=lambda c: c.name,
)
def test_problem_of_a_command_route_names_the_command(client, command):
    if command.method == "GET":
        response = client.get(command.path)
    else:
        response = client.post(command.path, json={})

    assert response.status_code == 400
    problem = response.json()
    assert problem["command"] == command.name
    assert _errors(COMMAND_NAME, problem["command"]) == []
    assert _errors(ERROR_CODE, problem["code"]) == []
    assert _errors(REASON, problem["details"]["reason"]) == []


@pytest.mark.parametrize(
    "command", [c for c in COMMANDS if c.long], ids=lambda c: c.name
)
def test_route_of_a_long_command_refuses_to_run_outside_a_job(client, command):
    options = {
        "hydrograph generate": HYDROGRAPH,
        "network delineate": {
            "outlet": {"id": "A", "latitude": 51.01917, "longitude": 15.88497},
            "points": [],
            "threshold_m2": 100000,
        },
    }[command.name]

    response = client.post(command.path, json=options)

    assert response.status_code == 409
    problem = response.json()
    assert problem["code"] == "conflict"
    assert problem["details"] == {"reason": "run_as_job", "command": command.name}
    assert problem["command"] == command.name


# ---- The server ----------------------------------------------------------------------


def test_server_is_a_nogat_server_1_document(client):
    response = client.get(f"{API_BASE}/server")

    assert response.status_code == 200
    document = response.json()
    assert _errors(SERVER_1, document) == []
    (service,) = document["services"]
    assert service["tool"] == "hydrograf"
    assert service["api"] == {"1": API_BASE}
    # Without [nogat.operator] the service serves no regulamin
    assert "terms" not in service


def test_server_capabilities_are_the_groups_of_the_catalog_the_catalog_and_jobs(
    client,
):
    (service,) = client.get(f"{API_BASE}/server").json()["services"]

    groups = list(dict.fromkeys(c.name.split()[0] for c in COMMANDS))
    groups.remove("commands")
    assert service["capabilities"] == [*groups, "catalog", "jobs"]


def test_server_names_the_regulamin_and_its_version_with_an_operator(client):
    terms = Terms(page="<html></html>", operator_email="ops@example.org", version="1.1")
    with patch("api.endpoints.server.current_terms", return_value=terms):
        document = client.get(f"{API_BASE}/server").json()

    assert _errors(SERVER_1, document) == []
    assert document["services"][0]["terms"] == {"url": URL, "version": "1.1"}


# ---- A job ---------------------------------------------------------------------------


@pytest.fixture
def held_hydrograph(monkeypatch: pytest.MonkeyPatch) -> threading.Event:
    """Make ``hydrograph generate`` a run that waits for the returned event."""
    release = threading.Event()

    def run(options: Any, db: Any) -> Outcome:
        assert release.wait(timeout=30)
        return Outcome({"hydrograph": {"peak_discharge_m3s": 1.5}})

    command = dataclasses.replace(BY_NAME["hydrograph generate"], run=run)
    monkeypatch.setitem(catalog.BY_NAME, command.name, command)
    return release


def _wait_until(job_id: str, states: set[str]) -> None:
    store: JobStore = app.state.jobs
    deadline = time.monotonic() + 30
    while store.get(job_id).state not in states:
        assert time.monotonic() < deadline, f"the job never reached {states}"
        time.sleep(0.005)


def test_job_documents_are_nogat_job_1_in_each_state(client, held_hydrograph):
    start = {"command": "hydrograph generate", "options": HYDROGRAPH}
    assert _errors(JOB_START, start) == []

    started = client.post(f"{API_BASE}/jobs", json=start)

    assert started.status_code == 202
    job_id = started.json()["id"]
    assert started.headers["location"] == f"jobs/{job_id}"
    assert _errors(JOB_1, started.json()) == []
    _wait_until(job_id, {"running"})
    running = client.get(f"{API_BASE}/jobs/{job_id}").json()
    assert running["state"] == "running"
    assert _errors(JOB_1, running) == []
    held_hydrograph.set()
    _wait_until(job_id, {"succeeded"})
    ended = client.get(f"{API_BASE}/jobs/{job_id}").json()
    assert _errors(JOB_1, ended) == []
    assert ended["state"] == "succeeded"


def test_result_of_a_job_is_the_envelope_of_its_command(client, held_hydrograph):
    held_hydrograph.set()
    started = client.post(
        f"{API_BASE}/jobs",
        json={"command": "hydrograph generate", "options": HYDROGRAPH},
    )
    job_id = started.json()["id"]
    _wait_until(job_id, {"succeeded"})

    body = client.get(f"{API_BASE}/jobs/{job_id}/result").json()

    assert _errors(RESULT_1, body) == []
    assert (body["command"], body["status"]) == ("hydrograph generate", "ok")
    assert body["result"] == {
        "schema": "hydrograf-hydrograph/1",
        "hydrograph": {"peak_discharge_m3s": 1.5},
    }


def test_result_of_a_cancelled_job_is_a_cancelled_envelope(client, held_hydrograph):
    started = client.post(
        f"{API_BASE}/jobs",
        json={"command": "hydrograph generate", "options": HYDROGRAPH},
    )
    job_id = started.json()["id"]
    _wait_until(job_id, {"running"})

    cancelled = client.post(f"{API_BASE}/jobs/{job_id}/cancel")
    held_hydrograph.set()
    _wait_until(job_id, {"cancelled"})

    assert cancelled.status_code == 202
    assert _errors(JOB_1, client.get(f"{API_BASE}/jobs/{job_id}").json()) == []
    body = client.get(f"{API_BASE}/jobs/{job_id}/result").json()
    assert _errors(RESULT_1, body) == []
    assert (body["status"], body["result"]) == ("cancelled", None)
