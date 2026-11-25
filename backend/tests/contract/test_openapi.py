"""Contract: the OpenAPI document of the API (AGI-6.2, AGI-6.3, AGI-6.6).

The document at ``/api/v1/openapi.json`` is OpenAPI 3.1: its paths are relative to the
API's base and its ``servers`` URL to the document itself, so that it reads right
behind a prefix, and every schema in it is a JSON Schema of the 2020-12 dialect. It
agrees with the command catalog (``api.catalog``): one operation per command at the
route of its ``rest``, named by its ``operation_id``, with its summary, its options
and exactly the problems of its registry codes.
"""

from typing import Any
from urllib.parse import urljoin

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from api import API_BASE
from api.catalog import COMMANDS, Command, options_of
from api.errors import PROBLEM_MEDIA_TYPE
from api.main import app
from core._errors import BY_CODE

DOCUMENT = app.openapi()
SCHEMAS = DOCUMENT["components"]["schemas"]
OPERATIONS = [
    (path, method, operation)
    for path, item in DOCUMENT["paths"].items()
    for method, operation in item.items()
]
BY_OPERATION_ID = {
    operation["operationId"]: operation for _, _, operation in OPERATIONS
}


def _component(reference: dict[str, Any]) -> dict[str, Any]:
    """Return the component schema a ``$ref`` names."""
    component: dict[str, Any] = SCHEMAS[reference["$ref"].rsplit("/", 1)[1]]
    return component


def _operation(command: Command) -> dict[str, Any]:
    path = command.path.removeprefix(API_BASE)
    operation: dict[str, Any] = DOCUMENT["paths"][path][command.method.lower()]
    return operation


def _problem_statuses(operation: dict[str, Any]) -> set[int]:
    return {int(status) for status in operation["responses"] if int(status) >= 400}


def test_document_is_openapi_3_1():
    assert DOCUMENT["openapi"].startswith("3.1")
    assert DOCUMENT["info"]["title"]
    assert DOCUMENT["info"]["version"]


def test_document_is_served_at_the_base_of_the_api():
    response = TestClient(app).get(f"{API_BASE}/openapi.json")

    assert response.status_code == 200
    assert response.json() == DOCUMENT


def test_every_schema_is_json_schema_2020_12():
    schemas = list(SCHEMAS.values())
    for _, _, operation in OPERATIONS:
        schemas += [p["schema"] for p in operation.get("parameters", [])]
        schemas += [
            content["schema"]
            for response in operation["responses"].values()
            for content in response.get("content", {}).values()
        ]

    for schema in schemas:
        Draft202012Validator.check_schema(schema)


def test_paths_are_relative_to_the_base_of_the_api():
    paths = list(DOCUMENT["paths"])

    assert paths
    assert not [p for p in paths if p.startswith("/api/") or not p.startswith("/")]
    # The map's tiles, the pages and the health check are no part of the API
    assert not [p for p in paths if p.startswith(("/tiles", "/health", "/index"))]


@pytest.mark.parametrize("base", [API_BASE, "/hydrograf/v1"])
def test_servers_url_resolves_to_the_base_the_document_is_served_under(base):
    (server,) = DOCUMENT["servers"]

    resolved = urljoin(f"https://example.org{base}/openapi.json", server["url"])

    assert resolved == f"https://example.org{base}"


def test_operation_ids_are_unique_and_meaningful():
    ids = [operation["operationId"] for _, _, operation in OPERATIONS]

    assert len(ids) == len(set(ids))
    # FastAPI's own ids end with the method and join the path with "__"
    assert not [i for i in ids if "__" in i or i.endswith(("_get", "_post"))], ids


def test_every_operation_of_a_command_is_in_the_catalog():
    commands = {command.operation_id for command in COMMANDS}
    named_as_commands = {i for i in BY_OPERATION_ID if i.startswith("hydrograf_")}

    assert named_as_commands == commands


@pytest.mark.parametrize("command", COMMANDS, ids=[c.name for c in COMMANDS])
def test_command_operation_agrees_with_the_catalog(command):
    operation = _operation(command)

    assert operation["operationId"] == command.operation_id
    assert operation["summary"] == command.summary
    assert operation["description"].startswith(command.description)
    assert operation["tags"] == [command.name.split()[0]]
    expected = {BY_CODE[code].http_status for code in command.codes}
    assert _problem_statuses(operation) == expected


@pytest.mark.parametrize("command", COMMANDS, ids=[c.name for c in COMMANDS])
def test_command_operation_takes_the_options_of_the_catalog(command):
    operation = _operation(command)
    options = {option["name"]: option["required"] for option in options_of(command)}

    if command.method == "GET":
        parameters = operation.get("parameters", [])
        assert {p["in"] for p in parameters} <= {"query"}
        assert {p["name"]: p.get("required", False) for p in parameters} == options
        assert "requestBody" not in operation
    else:
        body = _component(
            operation["requestBody"]["content"]["application/json"]["schema"]
        )
        assert list(body["properties"]) == list(options)
        assert set(body.get("required", ())) == {n for n, r in options.items() if r}


@pytest.mark.parametrize(
    "command", [c for c in COMMANDS if not c.long], ids=lambda c: c.name
)
def test_command_operation_answers_the_envelope_of_its_document(command):
    content = _operation(command)["responses"]["200"]["content"]["application/json"]
    envelope = _component(content["schema"])

    assert envelope["properties"]["schema"]["default"] == "hydrograf-result/1"
    (document, null) = envelope["properties"]["result"]["anyOf"]
    assert null == {"type": "null"}
    assert _component(document)["properties"]["schema"]["default"] == command.result


@pytest.mark.parametrize(
    "command", [c for c in COMMANDS if c.long], ids=lambda c: c.name
)
def test_long_command_operation_documents_its_refusal_and_no_answer(command):
    responses = _operation(command)["responses"]

    assert "200" not in responses
    example = responses["409"]["content"][PROBLEM_MEDIA_TYPE]["example"]
    assert example["details"] == {"reason": "run_as_job", "command": command.name}


@pytest.mark.parametrize(
    ("path", "method", "operation"),
    OPERATIONS,
    ids=[f"{m} {p}" for p, m, _ in OPERATIONS],
)
def test_operation_documents_its_problems(path, method, operation):
    responses = operation["responses"]

    assert "HTTPValidationError" not in str(responses), "invalid values are 400"
    assert "500" in responses
    for status, response in responses.items():
        if int(status) >= 400:
            assert list(response["content"]) == [PROBLEM_MEDIA_TYPE], status
            content = response["content"][PROBLEM_MEDIA_TYPE]
            assert content["schema"]["$ref"] == "#/components/schemas/Problem"
            assert content["example"]["status"] == int(status)
            assert content["example"]["type"].endswith(f"#{content['example']['code']}")


def test_problem_schema_replaces_the_validation_schemas():
    assert "Problem" in SCHEMAS
    assert "ProblemError" in SCHEMAS
    assert "HTTPValidationError" not in SCHEMAS
    assert {"type", "title", "status", "detail", "instance", "code", "details"} <= set(
        SCHEMAS["Problem"]["required"]
    )
    assert "command" in SCHEMAS["Problem"]["properties"]


def test_operations_with_a_body_or_parameters_document_400():
    for path, method, operation in OPERATIONS:
        if operation.get("requestBody") or operation.get("parameters"):
            assert "400" in operation["responses"], f"{method} {path}"


def test_network_delineate_documents_the_problems_of_its_route():
    operation = BY_OPERATION_ID["hydrograf_network_delineate"]

    # The window of a large catchment (422), the busy network and the catchment
    # graph (503), and its refusal to run outside a job (409)
    assert {"400", "404", "409", "422", "500", "503"} <= set(operation["responses"])


def test_network_preview_documents_the_problems_of_its_route():
    operation = BY_OPERATION_ID["hydrograf_network_preview"]

    # The preview reads no window of the rasters, so no 422 for a large one
    assert {"400", "404", "500", "503"} <= set(operation["responses"])
    assert "422" not in operation["responses"]


def test_job_start_documents_its_answer_and_the_job_limit():
    operation = DOCUMENT["paths"]["/jobs"]["post"]

    assert {"202", "400", "429"} <= set(operation["responses"])
    assert _component(operation["requestBody"]["content"]["application/json"]["schema"])


@pytest.mark.parametrize(
    ("operation_id", "reasons"),
    [
        (
            "bootstrap_start",
            {
                "403": "shared_store_read_only",
                "404": "boundary_file_missing",
                "409": "bootstrap_running",
            },
        ),
        ("bootstrap_cancel", {"409": "bootstrap_not_running"}),
        ("update_feedback", {"404": "feedback_not_found"}),
        ("delete_feedback", {"404": "feedback_not_found"}),
        (
            "sewer_config_update",
            {"403": "path_outside_project", "404": "source_file_missing"},
        ),
        ("job_status", {"404": "job_expired"}),
        ("job_result", {"404": "job_expired", "409": "job_running"}),
    ],
)
def test_operations_document_the_problems_of_their_route(operation_id, reasons):
    operation = BY_OPERATION_ID[operation_id]

    documented = {
        status: operation["responses"][status]["content"][PROBLEM_MEDIA_TYPE][
            "example"
        ]["details"]["reason"]
        for status in reasons
        if status in operation["responses"]
    }
    assert documented == reasons


def test_admin_operations_need_the_key():
    admin = [op for path, _, op in OPERATIONS if path.startswith("/admin/")]

    assert admin
    assert not [op["operationId"] for op in admin if "401" not in op["responses"]]
