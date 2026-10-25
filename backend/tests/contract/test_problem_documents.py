"""Contract: REST errors are problem documents of the shared registry (ERR-4, AGI-6.3).

Every error answers ``application/problem+json`` with ``type`` (the registry entry of
the code), ``title``, ``status`` from the registry, ``detail``, ``instance``, ``code``
and ``details`` whose ``reason`` is the project's cause; the texts follow
``Accept-Language`` and the machine members do not (AGI-6.4).
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.errors import (
    PROBLEM_MEDIA_TYPE,
    REGISTRY_PAGE,
    install_error_handlers,
    language_of,
    pointer_of,
)
from core._errors import BY_CODE
from core.errors import (
    ConflictError,
    HydrografError,
    InvalidRequestError,
    NotFoundError,
)
from models.schemas import DelineateRequest


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/echo")
    def echo(body: DelineateRequest) -> dict[str, float]:
        return {"latitude": body.latitude}

    @app.get("/missing")
    def missing() -> None:
        raise NotFoundError(
            "feedback_not_found", reason="feedback_not_found", feedback_id=7
        )

    @app.get("/conflict")
    def conflict() -> None:
        raise ConflictError("bootstrap_running", reason="bootstrap_running")

    @app.get("/crash")
    def crash() -> None:
        raise RuntimeError("secret internals")

    yield TestClient(app, raise_server_exceptions=False)


def _assert_problem(response: Any, code: str) -> dict[str, Any]:
    problem: dict[str, Any] = response.json()
    entry = BY_CODE[code]
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert problem["code"] == code
    assert problem["status"] == entry.http_status == response.status_code
    assert problem["type"] == f"{REGISTRY_PAGE}#{code}"
    assert problem["instance"] == response.request.url.path
    assert isinstance(problem["details"], dict) and problem["details"]["reason"]
    assert problem["detail"]
    return problem


def test_error_of_the_code_is_a_problem_with_registry_status(client):
    response = client.get("/conflict")

    problem = _assert_problem(response, "conflict")

    assert problem["title"] == BY_CODE["conflict"].title
    assert problem["hint"]
    assert response.headers["content-language"] == "en"


def test_polish_request_changes_the_texts_and_not_the_machine_members(client):
    english = client.get("/missing")
    polish = client.get("/missing", headers={"Accept-Language": "pl,en;q=0.5"})

    assert polish.headers["content-language"] == "pl"
    for key in ("type", "status", "code", "details", "instance"):
        assert polish.json()[key] == english.json()[key]
    assert polish.json()["title"] != english.json()["title"]
    assert polish.json()["detail"] != english.json()["detail"]


def test_invalid_values_are_400_with_json_pointers(client):
    response = client.post("/echo", json={"latitude": 200, "longitude": 21.0})

    problem = _assert_problem(response, "validation_error")

    assert problem["errors"][0]["pointer"] == "/body/latitude"
    assert problem["details"]["fields"] == ["/body/latitude"]


def test_unknown_route_and_wrong_method_use_registry_codes(client):
    unknown = client.get("/nowhere")
    wrong_method = client.get("/echo")

    _assert_problem(unknown, "not_found")
    problem = _assert_problem(wrong_method, "method_not_allowed")
    assert "POST" in wrong_method.headers["allow"]
    assert problem["details"]["allowed"] == ["POST"]


def test_unexpected_exception_is_internal_error_without_its_text(client):
    response = client.get("/crash")

    _assert_problem(response, "internal_error")
    assert "secret internals" not in response.text


def test_every_subclass_and_code_of_the_base_has_an_http_status():
    for cls in HydrografError.__subclasses__():
        assert BY_CODE[cls.default_code].http_status, cls
    with pytest.raises(ValueError):
        InvalidRequestError("filename_missing", reason="x", code="cancelled")
    with pytest.raises(ValueError):
        InvalidRequestError("filename_missing", reason="x", code="made_up")


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, "en"),
        ("", "en"),
        ("pl", "pl"),
        ("pl-PL,pl;q=0.9,en;q=0.8", "pl"),
        ("en-GB,en;q=0.9,pl;q=0.5", "en"),
        ("de,fr;q=0.8", "en"),
        ("pl;q=0", "en"),
    ],
)
def test_language_of_follows_the_weights(header, expected):
    assert language_of(header) == expected


def test_pointer_escapes_the_characters_of_rfc_6901():
    assert pointer_of(["body", "a/b", "c~d", 0]) == "/body/a~1b/c~0d/0"
