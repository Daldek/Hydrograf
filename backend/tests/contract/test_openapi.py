"""Contract: the OpenAPI document of the API (AGI-6.2, AGI-6.3, AGI-6.6)."""

import pytest

from api.errors import PROBLEM_MEDIA_TYPE
from api.main import app

DOCUMENT = app.openapi()
OPERATIONS = [
    (path, method, operation)
    for path, item in DOCUMENT["paths"].items()
    for method, operation in item.items()
]


def test_document_is_openapi_3_1():
    assert DOCUMENT["openapi"].startswith("3.1")
    assert DOCUMENT["info"]["version"]


def test_operation_ids_are_unique_function_names():
    ids = [operation["operationId"] for _, _, operation in OPERATIONS]

    assert len(ids) == len(set(ids))
    assert not [i for i in ids if "__" in i or i.endswith(("_get", "_post"))], ids


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
            content = response["content"][PROBLEM_MEDIA_TYPE]
            assert content["schema"]["$ref"] == "#/components/schemas/Problem"
            assert content["example"]["status"] == int(status)
            assert content["example"]["type"].endswith(f"#{content['example']['code']}")


def test_problem_schema_replaces_the_validation_schemas():
    schemas = DOCUMENT["components"]["schemas"]

    assert "Problem" in schemas
    assert "ProblemError" in schemas
    assert "HTTPValidationError" not in schemas
    assert {"type", "title", "status", "detail", "instance", "code", "details"} <= set(
        schemas["Problem"]["required"]
    )


def test_operations_with_a_body_or_parameters_document_400():
    for path, method, operation in OPERATIONS:
        if operation.get("requestBody") or operation.get("parameters"):
            assert "400" in operation["responses"], f"{method} {path}"
