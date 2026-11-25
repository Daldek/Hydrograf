"""The jobs of the long commands, ``nogat-job/1`` (AGI-6.10, ADR-091).

A command whose run can outlast a request (``long`` in ``api.catalog``: the hydrograph
and the network) is run as a job: ``POST /api/v1/jobs`` checks its options, starts it
and answers at once with its document; ``GET /api/v1/jobs/<id>`` follows it and
``GET /api/v1/jobs/<id>/result`` answers, once it has ended, what the command's
synchronous route would (``api.endpoints.jobs``).

The store keeps every job in this process's memory, its options and result included
(a result of a person's choices is held in memory only, ECO-059), and forgets a job
``KEEP_S`` after it ended. At most ``WORKERS`` jobs run at once, each in a daemon
thread of its own with a database session of its own; the others wait ``queued``.
A cancelled queued job never starts; a running one ends ``cancelled`` when its
computation returns, its result discarded. The ids and times of the active jobs
(never their options, results or clients) are written to a file of the state
directory at each change, so that the next start of the server ends them
``interrupted`` (kept like an ended job); the ended jobs of a previous process are
not kept. Each job holds its client's place in the limit of
``api.traffic.JobSlots`` until it ends.
"""

import contextlib
import datetime
import json
import logging
import secrets
import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, Protocol

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.catalog import Command
from api.envelope import TOOL, envelope
from core.database import get_db_session
from core.errors import HydrografError, InternalError, NotFoundError

logger = logging.getLogger(__name__)

JOB_SCHEMA: Final = "nogat-job/1"
# How long an ended job is kept [s]
KEEP_S: Final = 3600.0
# How many jobs run at once in this process
WORKERS: Final = 4

State = Literal[
    "queued", "running", "succeeded", "partial", "failed", "interrupted", "cancelled"
]
ACTIVE: Final = frozenset({"queued", "running"})


def _now() -> str:
    """Return the current time as RFC 3339 in UTC, to the millisecond."""
    moment = datetime.datetime.now(datetime.UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Slot(Protocol):
    """The place of a job in its client's limit (``api.traffic.JobSlots``)."""

    def release(self) -> None:
        """Give the place back; a second call does nothing."""


@dataclass
class Job:
    """One job of the store.

    Attributes
    ----------
    id : str
        128 random bits as 32 hexadecimal digits: the only way to the job.
    command : str
        The catalog name of the command.
    state : State
        ``queued`` and ``running`` are active, the others ended.
    created_at, started_at, finished_at : str or None
        The times of the document (RFC 3339).
    options : BaseModel or None
        The checked options until the job ends.
    body : bytes or None
        The envelope of a succeeded or cancelled job.
    error : HydrografError or None
        The error of a failed job.
    slot : Slot or None
        The client's place in the limit, given back when the job ends.
    cancel_requested : bool
        A running job ends ``cancelled``.
    ended : float or None
        ``time.monotonic()`` when it ended, for its expiry.
    """

    id: str
    command: str
    state: State
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    options: BaseModel | None = field(default=None, repr=False)
    body: bytes | None = field(default=None, repr=False)
    error: HydrografError | None = None
    slot: Slot | None = field(default=None, repr=False)
    cancel_requested: bool = False
    ended: float | None = None

    def document(self) -> dict[str, Any]:
        """Return the job's document ``nogat-job/1``."""
        return {
            "schema": JOB_SCHEMA,
            "id": self.id,
            "tool": TOOL,
            "command": self.command,
            "state": self.state,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class JobDocument(BaseModel):
    """A job of a long command, ``nogat-job/1`` (AGI-6.10)."""

    schema_: str = Field(JOB_SCHEMA, alias="schema", description="`nogat-job/1`")
    id: str = Field(..., description="128 random bits, the only way to the job")
    tool: str = Field(TOOL, description="`hydrograf`")
    command: str = Field(..., description="The catalog name of the command")
    state: State = Field(
        ...,
        description="queued and running are active; succeeded, failed, cancelled and "
        "interrupted (a restart of the server ended it) are ended",
    )
    created_at: str = Field(..., description="When it was started (RFC 3339)")
    started_at: str | None = Field(None, description="When it began to run")
    finished_at: str | None = Field(None, description="When it ended")


class JobStart(BaseModel):
    """The body of ``POST /api/v1/jobs`` (``$defs/start`` of ``nogat-job/1``)."""

    command: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9-]* [a-z][a-z0-9-]*$",
        description="The long command to run: `hydrograph generate` or `network "
        "delineate`",
        examples=["hydrograph generate"],
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description="Its options, as its synchronous route takes them in its body",
    )


SessionFactory = Callable[[], AbstractContextManager[Session]]


class JobStore:
    """The jobs of this process (see the module).

    Parameters
    ----------
    path : Path or None
        The file of the active jobs; None keeps none (tests).
    session : SessionFactory, optional
        The database sessions of the runs.
    workers : int, optional
        How many jobs run at once.
    keep_s : float, optional
        How long an ended job is kept [s].
    """

    def __init__(
        self,
        path: Path | None,
        *,
        session: SessionFactory = get_db_session,
        workers: int = WORKERS,
        keep_s: float = KEEP_S,
    ) -> None:
        self._path = path
        self._session = session
        self._keep_s = keep_s
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._workers = threading.BoundedSemaphore(workers)

    def interrupt_previous(self) -> None:
        """End ``interrupted`` the jobs a previous process left active (at start)."""
        if self._path is None:
            return
        try:
            listed = json.loads(self._path.read_text(encoding="utf-8"))["active"]
            if not isinstance(listed, list):
                raise TypeError(f"active is a {type(listed).__name__}, not a list")
        except FileNotFoundError:
            return
        except (OSError, ValueError, KeyError, TypeError) as error:
            logger.warning("The jobs file %s cannot be read: %s", self._path, error)
            listed = []
        now = _now()
        with self._lock:
            for item in listed:
                try:
                    job = Job(
                        id=str(item["id"]),
                        command=str(item["command"]),
                        state="interrupted",
                        created_at=str(item["created_at"]),
                        started_at=item.get("started_at"),
                        finished_at=now,
                        ended=time.monotonic(),
                    )
                except (KeyError, TypeError):
                    continue
                self._jobs[job.id] = job
            self._save()

    def start(self, command: Command, options: BaseModel, slot: Slot) -> Job:
        """Start a job of ``command`` with checked ``options``; return it queued."""
        job = Job(
            id=secrets.token_hex(16),
            command=command.name,
            state="queued",
            created_at=_now(),
            options=options,
            slot=slot,
        )
        with self._lock:
            self._forget_expired()
            self._jobs[job.id] = job
            self._save()
        threading.Thread(
            target=self._run,
            args=(job, command),
            name=f"hydrograf-job-{job.id[:8]}",
            daemon=True,
        ).start()
        return job

    def get(self, job_id: str) -> Job:
        """Return the job ``job_id``.

        Raises
        ------
        NotFoundError
            ``not_found`` (404, ``job_expired``) for a job this server does not keep.
        """
        with self._lock:
            self._forget_expired()
            job = self._jobs.get(job_id)
        if job is None:
            raise NotFoundError("job_expired", reason="job_expired", job_id=job_id)
        return job

    def cancel(self, job_id: str) -> Job:
        """Cancel the job ``job_id`` (see the module); return it.

        Raises
        ------
        NotFoundError
            ``not_found`` (404, ``job_expired``) for a job this server does not keep.
        """
        job = self.get(job_id)
        with self._lock:
            if job.state == "queued":
                self._end(job, "cancelled", body=self._cancelled(job))
            elif job.state == "running":
                job.cancel_requested = True
        return job

    def _run(self, job: Job, command: Command) -> None:
        """Run ``job`` in its thread once a worker is free."""
        with self._workers:
            with self._lock:
                if job.state != "queued":
                    return
                job.state = "running"
                job.started_at = _now()
                self._save()
            try:
                with self._session() as db:
                    outcome = command.run(job.options, db)
                body = bytes(
                    JSONResponse(envelope(command.name, command.result, outcome)).body
                )
                ended: tuple[State, bytes | None, HydrografError | None] = (
                    "succeeded",
                    body,
                    None,
                )
            except HydrografError as error:
                ended = ("failed", None, error)
            except Exception as error:
                logger.error(
                    "The job %s failed: %s", command.name, error, exc_info=True
                )
                ended = (
                    "failed",
                    None,
                    InternalError("job_failed", reason="job_failed"),
                )
            with self._lock:
                if job.cancel_requested:
                    self._end(job, "cancelled", body=self._cancelled(job))
                else:
                    state, body_or_none, error_or_none = ended
                    self._end(job, state, body=body_or_none, error=error_or_none)

    @staticmethod
    def _cancelled(job: Job) -> bytes:
        cancelled = envelope(job.command, "", None, status="cancelled")
        return bytes(JSONResponse(cancelled).body)

    def _end(
        self,
        job: Job,
        state: State,
        *,
        body: bytes | None = None,
        error: HydrografError | None = None,
    ) -> None:
        """End ``job`` (under the lock): its state, result, time and client's place."""
        job.state = state
        job.body = body
        job.error = error
        job.finished_at = _now()
        job.ended = time.monotonic()
        job.options = None
        if job.slot is not None:
            job.slot.release()
            job.slot = None
        self._save()

    def _forget_expired(self) -> None:
        """Forget the jobs that ended more than ``keep_s`` ago (under the lock)."""
        limit = time.monotonic() - self._keep_s
        for job_id in [
            job.id
            for job in self._jobs.values()
            if job.ended is not None and job.ended < limit
        ]:
            del self._jobs[job_id]

    def _save(self) -> None:
        """Write the active jobs' ids and times to the file (under the lock)."""
        if self._path is None:
            return
        active = [
            {
                "id": job.id,
                "command": job.command,
                "created_at": job.created_at,
                "started_at": job.started_at,
            }
            for job in self._jobs.values()
            if job.state in ACTIVE
        ]
        partial = self._path.with_suffix(".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            partial.write_text(json.dumps({"active": active}), encoding="utf-8")
            partial.replace(self._path)
        except OSError as error:
            logger.warning("The jobs file %s cannot be written: %s", self._path, error)
            with contextlib.suppress(OSError):
                partial.unlink()
