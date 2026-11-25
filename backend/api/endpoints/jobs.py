"""
The routes of the jobs, ``/api/v1/jobs`` (AGI-6.10, ``nogat-job/1``, ADR-091).

``POST /api/v1/jobs`` starts a job of a long command of the catalog with its options
(checked as its synchronous route checks them) and answers ``202`` with the job's
document and the relative ``Location: jobs/<id>``; a client holds at most 2 active
jobs (``api.traffic``). ``GET /api/v1/jobs/<id>`` answers the document,
``GET /api/v1/jobs/<id>/result`` what the command's route would answer once the job
has ended (the envelope of a succeeded or cancelled job, the problem of a failed one),
``409 conflict`` before (``job_running``) and for a job a restart interrupted
(``job_interrupted``); ``POST /api/v1/jobs/<id>/cancel`` cancels it. An id the server
does not keep answers ``404 not_found``, ``job_expired`` (``api.jobs``).
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from api import catalog
from api.envelope import Envelope
from api.errors import hydrograf_problem, problem_responses
from api.jobs import JobDocument, JobStart, JobStore
from api.traffic import Traffic, client_address, too_many_jobs
from core.errors import ConflictError, InvalidRequestError

router = APIRouter()

_JOB_EXAMPLE = {
    "schema": "nogat-job/1",
    "id": "3f9c2a7be1d04c56a8e2b7f01d9c4e6a",
    "tool": "hydrograf",
    "command": "hydrograph generate",
    "state": "running",
    "created_at": "2026-11-25T10:15:02.120Z",
    "started_at": "2026-11-25T10:15:02.131Z",
    "finished_at": None,
}
_EXPIRED = ("not_found", "job_expired", {"reason": "job_expired", "job_id": "3f9c"})


def _store(request: Request) -> JobStore:
    store: JobStore = request.app.state.jobs
    return store


@router.post(
    "/jobs",
    status_code=202,
    response_model=JobDocument,
    summary="Start a job of a long command.",
    description=(
        "Starts `hydrograph generate` or `network delineate` with its options, as its "
        "synchronous route takes them in its body, and answers at once with the "
        "job's document and `Location: jobs/<id>`. Follow the job with `GET "
        "jobs/<id>` until it ends, then read `GET jobs/<id>/result`. A client holds "
        "at most 2 active jobs."
    ),
    responses={
        202: {"content": {"application/json": {"example": _JOB_EXAMPLE}}},
        **problem_responses(400, 429),
    },
)
def start_job(request: Request, start: JobStart) -> Response:
    """Start a job of a long command (see the module)."""
    command = catalog.find(start.command)
    if not command.long:
        raise InvalidRequestError(
            "not_a_job",
            reason="not_a_job",
            option="command",
            command=command.name,
            path=command.path,
            allowed=list(catalog.LONG),
        )
    try:
        options = command.options.model_validate(start.options)
    except ValidationError as error:
        raise RequestValidationError(
            [
                {**item, "loc": ("body", "options", *item["loc"])}
                for item in error.errors(include_url=False)
            ]
        ) from error
    traffic: Traffic = request.app.state.traffic
    slot = traffic.jobs.take(client_address(request))
    if slot is None:
        return too_many_jobs(request, traffic.jobs)
    job = _store(request).start(command, options, slot)
    return JSONResponse(
        job.document(), status_code=202, headers={"Location": f"jobs/{job.id}"}
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobDocument,
    summary="Read a job's state.",
    description="The job's document: its command, state and times.",
    responses={
        200: {"content": {"application/json": {"example": _JOB_EXAMPLE}}},
        **problem_responses(_EXPIRED),
    },
)
def job_status(request: Request, job_id: str) -> dict[str, Any]:
    """Return the job's document ``nogat-job/1``."""
    return _store(request).get(job_id).document()


@router.get(
    "/jobs/{job_id}/result",
    response_model=Envelope,
    summary="Read a job's result once it has ended.",
    description=(
        "What the command's synchronous route would answer: the envelope "
        "`hydrograf-result/1` of a succeeded job (`status` `cancelled` and `result` "
        "null for a cancelled one), the problem document of a failed one with its own "
        "status; `409 conflict` before the job ends (`job_running`) and for a job a "
        "restart of the server interrupted (`job_interrupted`)."
    ),
    responses=problem_responses(
        _EXPIRED,
        ("conflict", "job_running", {"reason": "job_running", "job_id": "3f9c"}),
    ),
)
def job_result(request: Request, job_id: str) -> Response:
    """Return the job's result (see the module)."""
    job = _store(request).get(job_id)
    if job.state in ("queued", "running"):
        return hydrograf_problem(
            request,
            ConflictError("job_running", reason="job_running", job_id=job.id),
            command=job.command,
        )
    if job.state == "interrupted":
        return hydrograf_problem(
            request,
            ConflictError("job_interrupted", reason="job_interrupted", job_id=job.id),
            command=job.command,
        )
    if job.error is not None:
        return hydrograf_problem(request, job.error, command=job.command)
    return Response(job.body or b"", media_type="application/json")


@router.post(
    "/jobs/{job_id}/cancel",
    status_code=202,
    response_model=JobDocument,
    summary="Cancel a job.",
    description=(
        "A queued job ends `cancelled` at once; a running one ends `cancelled` when "
        "its computation returns, its result discarded. An ended job stays as it is."
    ),
    responses={
        202: {"content": {"application/json": {"example": _JOB_EXAMPLE}}},
        **problem_responses(_EXPIRED),
    },
)
def cancel_job(request: Request, job_id: str) -> Response:
    """Cancel the job and answer its document."""
    job = _store(request).cancel(job_id)
    return JSONResponse(job.document(), status_code=202)
