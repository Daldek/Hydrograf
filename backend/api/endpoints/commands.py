"""
The routes of the catalog's commands, ``/api/v1/<group>/<verb>`` (AGI-6.1, ADR-091).

One route per command of ``api.catalog``, with the catalog's method, path,
``operationId``, texts and error codes: a GET route reads the options from the query
string (a list option as a repeated parameter), a POST route from the JSON body, both
checked by the command's model; the answer is the envelope ``hydrograf-result/1`` of
the command's run (``api.envelope``), with the ``Cache-Control`` the run gives. A long
command (``long: true``) is served only as a job (``api.jobs``): its route checks the
body and answers ``409 conflict``, ``run_as_job`` (AGI-6.10).
"""

import inspect
from collections.abc import Callable
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from api.catalog import COMMANDS, Command
from api.envelope import Outcome, document_model, envelope, envelope_model
from api.errors import PROBLEM_MEDIA_TYPE, command_responses
from core.database import get_db
from core.errors import ConflictError

router = APIRouter()


class ProblemOnly(JSONResponse):
    """The answer of a long command's route, which is only ever a problem document."""

    media_type = PROBLEM_MEDIA_TYPE


def answer(command: Command, outcome: Outcome) -> JSONResponse:
    """Return the synchronous answer of a run: its envelope and ``Cache-Control``."""
    headers = {}
    if outcome.cache_control is not None:
        headers["Cache-Control"] = outcome.cache_control
    return JSONResponse(
        envelope(command.name, command.result, outcome), headers=headers
    )


def run_as_job(command: Command) -> ConflictError:
    """Return the refusal of a long command's synchronous route (AGI-6.10)."""
    return ConflictError("run_as_job", reason="run_as_job", command=command.name)


def _model_name(command: Command) -> str:
    return "".join(part.capitalize() for part in command.name.replace("-", " ").split())


def _description(command: Command) -> str:
    rules = "\n".join(f"- {rule}" for rule in command.rules)
    examples = "\n".join(f"- `{example.call}`" for example in command.examples)
    return f"{command.description}\n\n**Rules**\n\n{rules}\n\n**Example**\n\n{examples}"


def _endpoint(command: Command) -> Callable[..., Any]:
    """Return the route function of ``command``, its parameters from the catalog."""
    options = inspect.Parameter(
        "options",
        inspect.Parameter.KEYWORD_ONLY,
        annotation=(
            Annotated[command.options, Query()]
            if command.method == "GET"
            else command.options
        ),
    )
    if command.long:

        def refuse(options: Any) -> NoReturn:
            raise run_as_job(command)

        endpoint: Callable[..., Any] = refuse
        parameters = [options]
    else:

        def run(options: Any, db: Session) -> JSONResponse:
            return answer(command, command.run(options, db))

        endpoint = run
        parameters = [
            options,
            inspect.Parameter(
                "db",
                inspect.Parameter.KEYWORD_ONLY,
                default=Depends(get_db),
                annotation=Session,
            ),
        ]
    endpoint.__signature__ = inspect.Signature(parameters)  # type: ignore[attr-defined]
    endpoint.__name__ = command.operation_id
    endpoint.__doc__ = command.summary
    return endpoint


for _command in COMMANDS:
    _name = _model_name(_command)
    _document = document_model(f"{_name}Document", _command.document, _command.result)
    router.add_api_route(
        _command.path,
        _endpoint(_command),
        methods=[_command.method],
        operation_id=_command.operation_id,
        summary=_command.summary,
        description=_description(_command),
        tags=[_command.name.split()[0]],
        response_model=None
        if _command.long
        else envelope_model(f"{_name}Result", _document),
        status_code=409 if _command.long else 200,
        response_class=ProblemOnly if _command.long else JSONResponse,
        responses=command_responses(_command.name, _command.codes),
    )
