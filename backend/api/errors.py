"""Problem responses of the REST API (ERR-4, AGI-6.2, AGI-6.3, AGI-6.4).

Every error of the API is ``application/problem+json`` (RFC 9457): ``type`` (the entry
of the code on the registry page), ``title``, ``status`` (the HTTP status of the code),
``detail``, ``instance`` (the request path), ``code``, ``hint`` when a fix is known,
``details`` (its ``reason`` is the project's own cause, ERR-1) and, for invalid request
values, ``errors[]`` with a JSON Pointer, the type and the message of each value.

The texts follow ``Accept-Language``: English without the header, Polish for ``pl``
(the interface sends it); ``Content-Language`` names the language. Codes, keys and
reasons do not change with it. An error that the code raises is a ``HydrografError``;
the framework's own errors (an unknown route, a wrong method, invalid values) and every
unexpected exception are mapped to registry codes here.

The OpenAPI document (``install_openapi``) names every operation after its route
function, documents the problem of each status a route answers with, and shows
FastAPI's 422 as the 400 ``validation_error`` that the API sends.
"""

import logging
from collections.abc import Iterable, Mapping
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from core._errors import BY_CODE
from core.errors import HydrografError
from core.messages import MESSAGES, Language, render

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE: Final = "application/problem+json"
# The page of the registry; `#<code>` is the anchor of a code (ERR-4).
REGISTRY_PAGE: Final = (
    "https://github.com/Daldek/Nogat/blob/main/standards/ERROR_REGISTRY.md"
)
# Codes of the framework's own HTTP errors; other 4xx are `validation_error`, 5xx
# `internal_error`.
_HTTP_CODES: Final = {
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    429: "rate_limited",
}


class ProblemError(BaseModel):
    """One invalid value of a request."""

    pointer: str = Field(
        ..., description="JSON Pointer to the value", examples=["/body/latitude"]
    )
    type: str = Field(
        ..., description="Type of the failure", examples=["less_than_equal"]
    )
    message: str = Field(..., description="What is wrong with the value")


class Problem(BaseModel):
    """RFC 9457 problem document of the API (``application/problem+json``)."""

    type: str = Field(..., description="Entry of the code on the registry page")
    title: str = Field(..., description="Registry title of the code")
    status: int = Field(..., description="HTTP status of the code")
    detail: str = Field(..., description="What happened")
    instance: str = Field(..., description="Path of the request that failed")
    code: str = Field(..., description="Code of the shared error registry")
    hint: str | None = Field(None, description="How to fix it, when known")
    details: dict[str, Any] = Field(
        ..., description="`reason` (the project's cause) and the context of the error"
    )
    errors: list[ProblemError] | None = Field(
        None, description="Invalid request values, for `validation_error`"
    )


def language_of(header: str | None) -> Language:
    """Return the language an ``Accept-Language`` header asks for.

    Parameters
    ----------
    header : str or None
        Value of the header.

    Returns
    -------
    {"en", "pl"}
        ``"pl"`` when Polish has the highest weight among Polish and English, else
        ``"en"`` (also for a missing header or other languages).
    """
    best: tuple[float, Language] | None = None
    for item in (header or "").split(","):
        tag, _, params = item.strip().partition(";")
        primary = tag.strip().lower().split("-")[0]
        if primary not in ("pl", "en"):
            continue
        weight = 1.0
        for param in params.split(";"):
            name, _, value = param.partition("=")
            if name.strip().lower() == "q":
                try:
                    weight = float(value)
                except ValueError:
                    weight = 0.0
        language: Language = "pl" if primary == "pl" else "en"
        if weight > 0 and (best is None or weight > best[0]):
            best = (weight, language)
    return best[1] if best else "en"


def pointer_of(location: Iterable[object]) -> str:
    """Return the JSON Pointer (RFC 6901) of a FastAPI error location.

    Parameters
    ----------
    location : Iterable[object]
        The ``loc`` of a validation error, e.g. ``("body", "latitude")``.
    """
    parts = (str(part).replace("~", "~0").replace("/", "~1") for part in location)
    return "".join(f"/{part}" for part in parts)


def problem_body(
    code: str,
    *,
    detail: str,
    instance: str,
    lang: Language = "en",
    hint: str | None = None,
    details: Mapping[str, Any] | None = None,
    errors: Iterable[Mapping[str, str]] = (),
) -> dict[str, Any]:
    """Return the members of a problem document (RFC 9457, AGI-6.3).

    Parameters
    ----------
    code : str
        Registry code; it gives ``type``, ``title`` and ``status``.
    detail : str
        What happened, in ``lang``.
    instance : str
        Path of the request that failed.
    lang : {"en", "pl"}, optional
        Language of ``title``.
    hint : str or None, optional
        How to fix it, in ``lang``.
    details : Mapping[str, Any] or None, optional
        ``reason`` and the context of the error.
    errors : Iterable[Mapping[str, str]], optional
        Invalid values: ``pointer``, ``type``, ``message``.

    Returns
    -------
    dict[str, Any]
        The document; ``hint`` and ``errors`` appear only when there are any.
    """
    entry = BY_CODE[code]
    body: dict[str, Any] = {
        "type": f"{REGISTRY_PAGE}#{code}",
        "title": entry.title_pl if lang == "pl" else entry.title,
        "status": entry.http_status,
        "detail": detail,
        "instance": instance,
        "code": code,
    }
    if hint:
        body["hint"] = hint
    body["details"] = dict(details or {})
    listed = list(errors)
    if listed:
        body["errors"] = listed
    return body


def problem_response(
    request: Request,
    code: str,
    *,
    message_id: str,
    details: Mapping[str, Any],
    errors: Iterable[Mapping[str, str]] = (),
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Return the ``application/problem+json`` response for a catalogued message.

    The text, the hint and the title follow the ``Accept-Language`` of ``request``.

    Parameters
    ----------
    request : Request
        The failed request.
    code : str
        Registry code.
    message_id : str
        ID of the message in the catalogue.
    details : Mapping[str, Any]
        ``details`` of the problem; they also fill the fields of the message.
    errors : Iterable[Mapping[str, str]], optional
        Invalid values of the request.
    headers : Mapping[str, str] or None, optional
        Further headers, e.g. ``Allow``.
    """
    lang = language_of(request.headers.get("accept-language"))
    message = MESSAGES[message_id]
    hint = message.hint(lang)
    body = problem_body(
        code,
        detail=render(message.text(lang), details),
        instance=request.url.path,
        lang=lang,
        hint=None if hint is None else render(hint, details),
        details=details,
        errors=errors,
    )
    return JSONResponse(
        body,
        status_code=BY_CODE[code].http_status or 500,
        media_type=PROBLEM_MEDIA_TYPE,
        headers={"Content-Language": lang, **(headers or {})},
    )


async def _hydrograf_error(request: Request, error: HydrografError) -> JSONResponse:
    if error.http_status >= 500:
        logger.error("%s: %s", error.code, error.message, exc_info=error)
    return problem_response(
        request, error.code, message_id=error.message_id, details=error.details
    )


async def _validation_error(
    request: Request, error: RequestValidationError
) -> JSONResponse:
    errors = [
        {
            "pointer": pointer_of(item["loc"]),
            "type": str(item["type"]),
            "message": str(item["msg"]),
        }
        for item in error.errors()
    ]
    details = {
        "reason": "invalid_request",
        "fields": sorted({item["pointer"] for item in errors}),
    }
    return problem_response(
        request,
        "validation_error",
        message_id="invalid_request",
        details=details,
        errors=errors,
    )


async def _http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
    status = error.status_code
    headers = {
        key.lower(): value
        for key, value in (error.headers or {}).items()
        if key.lower() in ("allow", "retry-after")
    }
    if status == 404:
        return problem_response(
            request,
            "not_found",
            message_id="route_not_found",
            details={"reason": "route_not_found", "path": request.url.path},
            headers=headers,
        )
    if status == 405:
        return problem_response(
            request,
            "method_not_allowed",
            message_id="method_not_supported",
            details={
                "reason": "method_not_supported",
                "method": request.method,
                "path": request.url.path,
                "allowed": [
                    m.strip() for m in headers.get("allow", "").split(",") if m
                ],
            },
            headers=headers,
        )
    code = _HTTP_CODES.get(
        status, "validation_error" if status < 500 else "internal_error"
    )
    return problem_response(
        request,
        code,
        message_id="http_error",
        details={"reason": "http_error", "status": status},
        headers=headers,
    )


async def _internal_error(request: Request, error: Exception) -> JSONResponse:
    logger.error(
        "Unhandled %s on %s", type(error).__name__, request.url.path, exc_info=error
    )
    return problem_response(
        request,
        "internal_error",
        message_id="internal_error",
        details={"reason": "unexpected_exception"},
    )


def install_error_handlers(app: FastAPI) -> None:
    """Answer every failure of a request with a problem (see the module)."""
    app.exception_handler(HydrografError)(_hydrograf_error)
    app.exception_handler(RequestValidationError)(_validation_error)
    app.exception_handler(StarletteHTTPException)(_http_error)
    app.exception_handler(Exception)(_internal_error)


# ---- OpenAPI -------------------------------------------------------------------------

# One example per documented status: (code, message ID, details).
_EXAMPLES: Final[dict[int, tuple[str, str, dict[str, Any]]]] = {
    400: (
        "validation_error",
        "invalid_request",
        {"reason": "invalid_request", "fields": ["/body/latitude"]},
    ),
    401: ("unauthorized", "admin_key_missing", {"reason": "admin_key_missing"}),
    403: (
        "forbidden",
        "path_outside_project",
        {"reason": "path_outside_project"},
    ),
    404: (
        "not_found",
        "no_catchment_at_point",
        {"reason": "no_catchment_at_point"},
    ),
    405: (
        "method_not_allowed",
        "method_not_supported",
        {
            "reason": "method_not_supported",
            "method": "GET",
            "path": "/api/example",
            "allowed": ["POST"],
        },
    ),
    409: ("conflict", "bootstrap_running", {"reason": "bootstrap_running"}),
    422: (
        "unsupported",
        "catchment_too_large",
        {"reason": "catchment_too_large", "area_km2": 312.4, "limit_km2": 250},
    ),
    500: ("internal_error", "internal_error", {"reason": "unexpected_exception"}),
    503: (
        "store_unavailable",
        "catchment_graph_unavailable",
        {"reason": "catchment_graph_unavailable"},
    ),
}
# Statuses that two codes share get a description of their own.
_DESCRIPTIONS: Final = {
    422: "Unsupported request (`unsupported`) or no result (`calculation_error`)"
}


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Return the OpenAPI ``responses`` that document problems of the given statuses.

    Parameters
    ----------
    *statuses : int
        HTTP statuses a route answers with a problem, e.g. ``404``; each one needs an
        example in ``_EXAMPLES``.
    """
    responses: dict[int | str, dict[str, Any]] = {}
    for status in statuses:
        code, message_id, details = _EXAMPLES[status]
        hint_en = MESSAGES[message_id].hint_en
        example = problem_body(
            code,
            detail=render(MESSAGES[message_id].text("en"), details),
            instance="/api/example",
            hint=None if hint_en is None else render(hint_en, details),
            details=details,
        )
        responses[status] = {
            "description": _DESCRIPTIONS.get(status, BY_CODE[code].title),
            "content": {
                PROBLEM_MEDIA_TYPE: {
                    "schema": {"$ref": "#/components/schemas/Problem"},
                    "example": example,
                }
            },
        }
    return responses


def operation_id(route: APIRoute) -> str:
    """Name an operation after its route function, e.g. ``delineate_watershed``."""
    return route.name


def install_openapi(app: FastAPI) -> None:
    """Document the problems of the API in its OpenAPI document (AGI-6.2)."""
    build = app.openapi

    def document() -> dict[str, Any]:
        if app.openapi_schema is None:
            _document_problems(build())
        return app.openapi_schema or {}

    app.openapi = document  # type: ignore[method-assign]


def _document_problems(schema: dict[str, Any]) -> None:
    """Add the problem schema and the problem responses to an OpenAPI document.

    FastAPI's 422 and its validation schemas are replaced by the 400 ``Problem`` that
    the API sends, and every operation documents ``500``.
    """
    schemas: dict[str, Any] = schema.setdefault("components", {}).setdefault(
        "schemas", {}
    )
    schemas.pop("HTTPValidationError", None)
    schemas.pop("ValidationError", None)
    definitions = Problem.model_json_schema(ref_template="#/components/schemas/{model}")
    schemas.update(definitions.pop("$defs", {}))
    schemas["Problem"] = definitions
    for operations in schema.get("paths", {}).values():
        for operation in operations.values():
            responses: dict[str, Any] = operation.setdefault("responses", {})
            default = responses.get("422")
            if default is not None and default.get("description") == "Validation Error":
                del responses["422"]
            if operation.get("requestBody") or operation.get("parameters"):
                responses.setdefault("400", problem_responses(400)[400])
            responses.setdefault("500", problem_responses(500)[500])
