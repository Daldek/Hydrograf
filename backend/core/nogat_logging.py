"""Logs of a Nogat server: access, application and lifecycle records (nogat-log/1).

Nogat's reference implementation of DEV-12.4 to DEV-12.9. Every Python server
copies this file byte for byte into its package and never edits it (DEV-15.6):
a change is made in Nogat ``standards/reference/`` and copied again, and
``uv run scripts/ecosystem.py drift`` in Nogat reports each copy. Records follow
Nogat ``schemas/log/record-1.schema.json``. Standard library only.

Use::

    log = ServerLog("hydrolog", __version__, state_dir / "hydrolog" / "logs")
    app.add_middleware(AccessLog, log=log, quiet=r"^/(css|src|vendor|nogat)/")
    # when serving starts, e.g. in the lifespan's startup:
    log.start({"host": host, "port": port, "public": True})
    # when it ends:
    log.stop()

uvicorn runs with ``access_log=False`` and ``log_config=None`` (on its command
line ``--no-access-log --log-level warning``). ``start`` sends the warnings and
errors that the process logs through ``logging`` to ``app`` records, deletes
the files dated 14 or more days ago, again at each 00:00 UTC, and writes the
lifecycle record ``start``.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import logging
import os
import re
import secrets
import sys
import threading
import time
import traceback
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from contextvars import ContextVar
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import Any, TextIO
from urllib.parse import unquote_plus

__all__ = [
    "FORMAT",
    "REDACTED",
    "REDACTED_PARTS",
    "RETENTION_DAYS",
    "AccessLog",
    "ServerLog",
    "agent_class",
    "redact_query",
    "request_id",
    "scrub",
]

FORMAT = "nogat-log/1"
"""The record format, the title of Nogat ``schemas/log/record-1.schema.json``."""

RETENTION_DAYS = 14
"""A file is deleted once its date is this many days before today (UTC)."""

REDACTED = frozenset(
    {
        # free text a person types
        "q",
        "query",
        "search",
        "text",
        "message",
        "comment",
        "address",
        # who someone is
        "name",
        "user",
        "username",
        "login",
        "email",
        "mail",
        "phone",
        # credentials
        "key",
        "token",
        "password",
        "secret",
        "session",
        "auth",
        "signature",
        "sig",
    }
)
"""Query parameters that keep their name and lose their value in a logged path.

A name is compared percent-decoded, in lower case, with ``-`` read as ``_``.
"""

REDACTED_PARTS = ("token", "secret", "passw", "apikey", "api_key", "session", "mail")
"""A query parameter whose name contains one of these loses its value too."""

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]
ExcInfo = tuple[type[BaseException], BaseException, TracebackType | None]

_REQUEST_ID: ContextVar[str | None] = ContextVar("nogat_request_id", default=None)
_FILE = re.compile(r"^(access|app|lifecycle)-(\d{4}-\d{2}-\d{2})\.jsonl$")
_BOT = re.compile(
    r"bot|crawl|spider|slurp|scrap|headless|lighthouse|externalhit|archiver|preview",
    re.IGNORECASE,
)
_IPV4 = re.compile(r"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9]|\.[0-9])")
_IPV6 = re.compile(r"[0-9A-Fa-f:]{7,}")
_LOGGED = "_nogat_logged"  # set on an exception once it is in the application log
_UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access")
_SCALARS = (str, int, float, bool, type(None))
_WRITE_FAILURE_PAUSE_S = 60.0


def request_id() -> str | None:
    """Return the id of the request being handled.

    Returns
    -------
    str or None
        16 random hexadecimal digits, or ``None`` outside a request.
    """
    return _REQUEST_ID.get()


def agent_class(user_agent: str | None) -> str:
    """Return the class of a User-Agent, the only part of it that is logged.

    Parameters
    ----------
    user_agent : str or None
        The ``User-Agent`` header of a request.

    Returns
    -------
    str
        ``bot`` when it names a robot, ``browser`` when it starts with
        ``Mozilla/``, ``script`` for any other value, ``none`` without one.
    """
    if user_agent is None or not user_agent.strip():
        return "none"
    if _BOT.search(user_agent):
        return "bot"
    if user_agent.startswith("Mozilla/"):
        return "browser"
    return "script"


def redact_query(query: str) -> str:
    """Return a query string with the values of personal or secret parameters dropped.

    Parameters
    ----------
    query : str
        The query string without ``?``, as sent.

    Returns
    -------
    str
        The same pairs in the same order; a parameter named in :data:`REDACTED`,
        or whose name contains one of :data:`REDACTED_PARTS`, keeps only its name
        and ``=``.
    """
    pairs = []
    for pair in query.split("&"):
        name, equals, _value = pair.partition("=")
        key = unquote_plus(name).strip().lower().replace("-", "_")
        if equals and (key in REDACTED or any(p in key for p in REDACTED_PARTS)):
            pairs.append(name + "=")
        else:
            pairs.append(pair)
    return "&".join(pairs)


def scrub(text: str) -> str:
    """Return a text with every IPv4 and IPv6 address replaced by ``[ip]``.

    Parameters
    ----------
    text : str
        A path, a log message or a traceback.

    Returns
    -------
    str
        The text; an address followed by its port keeps the port.
    """
    return _IPV6.sub(_scrub_ipv6, _IPV4.sub(_scrub_ipv4, text))


def _scrub_ipv4(match: re.Match[str]) -> str:
    try:
        ipaddress.IPv4Address(match.group(0))
    except ValueError:
        return match.group(0)
    return "[ip]"


def _scrub_ipv6(match: re.Match[str]) -> str:
    token = match.group(0)
    if token.count(":") < 2:
        return token
    start = 1 if token.startswith(":") and not token.startswith("::") else 0
    ends = [len(token)]
    colon = token.rfind(":")
    if colon > start and token[colon + 1 :].isdigit():
        ends.append(colon)  # an address and its port
    for end in ends:
        try:
            ipaddress.IPv6Address(token[start:end])
        except ValueError:
            continue
        return token[:start] + "[ip]" + token[end:]
    return token


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime) -> str:
    """RFC 3339 in UTC with milliseconds and ``Z``."""
    text = moment.astimezone(UTC).isoformat(timespec="milliseconds")
    return text.replace("+00:00", "Z")


def _level(levelno: int) -> str:
    for floor, name in ((50, "critical"), (40, "error"), (30, "warning"), (20, "info")):
        if levelno >= floor:
            return name
    return "debug"


def _type_name(error: BaseException) -> str:
    kind = type(error)
    if kind.__module__ == "builtins":
        return kind.__qualname__
    return f"{kind.__module__}.{kind.__qualname__}"


def _info(error: BaseException) -> ExcInfo:
    return type(error), error, error.__traceback__


def _encode(record: Mapping[str, object]) -> str:
    return json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"


class ServerLog:
    """The logs of one server: daily files, deletion after 14 days, standard error.

    Each record goes to ``<directory>/<kind>-YYYY-MM-DD.jsonl``, the date in
    UTC. Standard error gets only lifecycle records and app records of level
    ``error`` or ``critical``, these without ``request_id`` or ``message`` and
    with only the type of their error (DEV-12.7).

    Parameters
    ----------
    app : str
        The project's name in lower case, e.g. ``hydrolog``.
    version : str
        The server's version.
    directory : str or os.PathLike
        ``<state_dir>/<project>/logs`` (DEV-12.6); created when first written.
    stream : TextIO, optional
        Where lifecycle and error records are printed; ``sys.stderr`` when
        omitted, looked up at each record.
    clock : callable, optional
        The current time, timezone-aware; ``datetime.now(UTC)`` when omitted.
    """

    def __init__(
        self,
        app: str,
        version: str,
        directory: str | os.PathLike[str],
        *,
        stream: TextIO | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.app = app
        self.version = version
        self.directory = Path(directory)
        self._stream = stream
        self._clock = clock or _now
        self._lock = threading.Lock()
        self._open: dict[str, tuple[str, int]] = {}  # kind -> (date, descriptor)
        self._write_failed_at = -_WRITE_FAILURE_PAUSE_S
        self._handler = _AppHandler(self)
        self._replaced: list[logging.Handler] = []
        self._hook: Callable[[threading.ExceptHookArgs], object] | None = None
        self._stopped = threading.Event()
        self._keeper: threading.Thread | None = None

    def start(self, settings: Mapping[str, object] | None = None) -> None:
        """Begin logging the server: lifecycle ``start``, the application log, deletion.

        Replaces the root logger's handlers with one that writes ``app``
        records of level ``warning`` and above, sends uvicorn's loggers to it
        and silences its access logger, captures warnings and the uncaught
        exceptions of threads, deletes the files dated 14 or more days ago and
        starts a daemon thread that deletes them again at each 00:00 UTC.

        Parameters
        ----------
        settings : mapping, optional
            The summary of the server's settings for the record ``start``:
            names and scalar values (others are written as text), never a
            secret or the operator's details.
        """
        root = logging.getLogger()
        self._replaced = [h for h in root.handlers if h is not self._handler]
        for handler in self._replaced:
            root.removeHandler(handler)
        root.addHandler(self._handler)
        if root.level > logging.WARNING:
            root.setLevel(logging.WARNING)
        for name in _UVICORN:
            logger = logging.getLogger(name)
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)
            logger.propagate = True
        logging.getLogger("uvicorn.access").disabled = True
        logging.captureWarnings(True)
        self._hook = threading.excepthook
        threading.excepthook = self._thread_exception
        summary = {
            str(k): v if isinstance(v, _SCALARS) else str(v)
            for k, v in (settings or {}).items()
        }
        self.lifecycle("start", f"{self.app} {self.version} started", settings=summary)
        self.prune()
        self._stopped.clear()
        self._keeper = threading.Thread(
            target=self._keep, name="nogat-logging", daemon=True
        )
        self._keeper.start()

    def stop(self) -> None:
        """End logging: lifecycle ``stop``, handlers restored, files closed."""
        self.lifecycle("stop", f"{self.app} {self.version} stopped")
        self._stopped.set()
        if self._keeper is not None:
            self._keeper.join(timeout=5)
            self._keeper = None
        root = logging.getLogger()
        root.removeHandler(self._handler)
        for handler in self._replaced:
            root.addHandler(handler)
        self._replaced = []
        logging.captureWarnings(False)
        if self._hook is not None:
            threading.excepthook = self._hook
            self._hook = None
        self.close()

    def close(self) -> None:
        """Close the open files; the next record opens its file again."""
        with self._lock:
            for _day, descriptor in self._open.values():
                os.close(descriptor)
            self._open.clear()

    def lifecycle(
        self,
        event: str,
        message: str,
        *,
        level: int = logging.INFO,
        settings: Mapping[str, object] | None = None,
    ) -> None:
        """Write a lifecycle record to its file and to standard error.

        Parameters
        ----------
        event : str
            ``start``, ``stop``, ``prune`` or another code of the server's own.
        message : str
            A fixed text of the server, without request data.
        level : int, optional
            A ``logging`` level; ``INFO`` by default.
        settings : mapping, optional
            Only for ``start``: the summary of the server's settings.
        """
        record = self._base("lifecycle", _level(level), None)
        record.update(event=event, message=message)
        if settings is not None:
            record["settings"] = dict(settings)
        self._write(record)
        self._print(record)

    def access(
        self,
        *,
        request_id: str,
        method: str,
        path: str,
        status: int,
        size: int,
        duration_ms: float,
        agent: str,
    ) -> None:
        """Write the access record of one request.

        Parameters
        ----------
        request_id : str
            The request's random id.
        method : str
            The HTTP method.
        path : str
            The path with the query of :func:`redact_query`.
        status : int
            The status answered.
        size : int
            The bytes of the body sent.
        duration_ms : float
            From the request's arrival to its last byte, in milliseconds.
        agent : str
            The class of :func:`agent_class`.
        """
        record = self._base("access", "info", request_id)
        record.update(
            method=method,
            path=scrub(path),
            status=status,
            bytes=size,
            duration_ms=round(duration_ms, 1),
            agent=agent,
        )
        self._write(record)

    def application(
        self,
        levelno: int,
        event: str,
        message: str,
        exc_info: ExcInfo | None = None,
    ) -> None:
        """Write an app record; at ``error`` and above also its reduced form.

        An exception already in the application log is not logged again, so
        the server's own report of an exception the middleware logged is
        dropped.

        Parameters
        ----------
        levelno : int
            A ``logging`` level.
        event : str
            A stable code of what happened, or the logger's name.
        message : str
            The formatted message.
        exc_info : tuple, optional
            ``(type, exception, traceback)`` of an exception.
        """
        error: dict[str, str] | None = None
        if exc_info is not None:
            exception = exc_info[1]
            if getattr(exception, _LOGGED, False):
                return
            error = {
                "type": _type_name(exception),
                "message": scrub(str(exception)),
                "stack": scrub("".join(traceback.format_exception(*exc_info))),
            }
            # An exception that takes no attribute may be logged twice.
            with contextlib.suppress(AttributeError, TypeError):
                setattr(exception, _LOGGED, True)
        level = _level(levelno)
        record = self._base("app", level, _REQUEST_ID.get())
        record.update(event=event, message=scrub(message), error=error)
        self._write(record)
        if levelno >= logging.ERROR:
            reduced = self._base("app", level, None)
            kind = None if error is None else {"type": error["type"]}
            reduced.update(event=event, message=None, error=kind)
            self._print(reduced)

    def prune(self) -> list[Path]:
        """Delete the log files dated 14 or more days before today (UTC).

        Other files of the directory stay. When files are deleted, a lifecycle
        record ``prune`` says how many.

        Returns
        -------
        list of Path
            The files deleted.
        """
        today = self._clock().astimezone(UTC).date()
        cutoff = today - timedelta(days=RETENTION_DAYS)
        try:
            names = sorted(p.name for p in self.directory.iterdir())
        except FileNotFoundError:
            return []
        deleted = []
        for name in names:
            match = _FILE.match(name)
            if match is None:
                continue
            try:
                day = date.fromisoformat(match[2])
            except ValueError:
                continue
            if day > cutoff:
                continue
            with self._lock:
                opened = self._open.get(match[1])
                if opened is not None and opened[0] == match[2]:
                    os.close(self._open.pop(match[1])[1])
            try:
                (self.directory / name).unlink()
            except OSError:
                continue  # gone already, or held by another process: next time
            deleted.append(self.directory / name)
        if deleted:
            self.lifecycle(
                "prune",
                f"deleted {len(deleted)} log files dated {cutoff.isoformat()} "
                "or earlier",
            )
        return deleted

    def _base(self, kind: str, level: str, request: str | None) -> dict[str, object]:
        return {
            "time": _stamp(self._clock()),
            "level": level,
            "app": self.app,
            "version": self.version,
            "kind": kind,
            "request_id": request,
        }

    def _write(self, record: Mapping[str, object]) -> None:
        kind, day = str(record["kind"]), str(record["time"])[:10]
        data = _encode(record).encode("utf-8", "replace")
        try:
            with self._lock:
                opened = self._open.get(kind)
                if opened is None or opened[0] != day:
                    if opened is not None:
                        del self._open[kind]
                        os.close(opened[1])
                    self.directory.mkdir(parents=True, exist_ok=True)
                    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
                    flags |= getattr(os, "O_BINARY", 0)  # no newline translation
                    path = self.directory / f"{kind}-{day}.jsonl"
                    self._open[kind] = (day, os.open(path, flags, 0o666))
                os.write(self._open[kind][1], data)
        except OSError as exc:
            # A full disk must not fail requests nor flood standard error.
            now = time.monotonic()
            if now - self._write_failed_at >= _WRITE_FAILURE_PAUSE_S:
                self._write_failed_at = now
                self._print_failure(exc)

    def _print(self, record: Mapping[str, object]) -> None:
        stream = self._stream or sys.stderr
        try:
            stream.write(_encode(record))
            stream.flush()
        except (OSError, ValueError):
            pass  # no standard error left to report to

    def _print_failure(self, error: BaseException) -> None:
        record = self._base("app", "error", None)
        record.update(
            event="log_write_failed", message=None, error={"type": _type_name(error)}
        )
        self._print(record)

    def _keep(self) -> None:
        while True:
            now = self._clock().astimezone(UTC)
            midnight = datetime.combine(
                now.date() + timedelta(days=1), datetime.min.time(), UTC
            )
            if self._stopped.wait((midnight - now).total_seconds() + 1):
                return
            try:
                self.prune()
            except Exception as exc:  # the thread outlives a failed deletion
                self.application(
                    logging.ERROR,
                    "prune_failed",
                    "deleting old logs failed",
                    _info(exc),
                )

    def _thread_exception(self, args: threading.ExceptHookArgs) -> None:
        if args.exc_value is None:
            return
        thread = args.thread.name if args.thread is not None else "?"
        self.application(
            logging.CRITICAL,
            "uncaught_exception",
            f"uncaught exception in thread {thread}",
            (args.exc_type, args.exc_value, args.exc_traceback),
        )


class _AppHandler(logging.Handler):
    """Writes the ``logging`` records of ``warning`` and above as app records."""

    def __init__(self, log: ServerLog) -> None:
        super().__init__(logging.WARNING)
        self._log = log

    def emit(self, record: logging.LogRecord) -> None:
        """Write the record; a failure prints a reduced error, never the record."""
        try:
            info = record.exc_info
            exc_info = None
            if info is not None and info[1] is not None:
                exc_info = (type(info[1]), info[1], info[2])
            event = getattr(record, "event", None)
            self._log.application(
                record.levelno,
                event if isinstance(event, str) and event else record.name,
                record.getMessage(),
                exc_info,
            )
        except Exception as exc:
            self._log._print_failure(exc)


class AccessLog:
    """ASGI middleware: one access record per HTTP request (DEV-12.4, DEV-12.5).

    Add it as the outermost middleware, so that it records the answers of the
    rate limit too. It reads only the method, the path, the query and the
    ``User-Agent`` of a request, never the client's address or another
    header, and never sends the request id to the client. An exception that
    leaves the application becomes an app record of the request; WebSocket and
    lifespan messages pass through.

    Parameters
    ----------
    app : ASGI application
        The application it wraps.
    log : ServerLog
        Where the records go.
    quiet : str, optional
        A regular expression searched in the path without its query, matching
        static content: files, map tiles and documents the same for every
        client; their requests answered below 400 are not logged.
    """

    def __init__(self, app: ASGIApp, log: ServerLog, quiet: str | None = None) -> None:
        self.app = app
        self.log = log
        self.quiet = re.compile(quiet) if quiet else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI connection; log it when it is an HTTP request."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = secrets.token_hex(8)
        token = _REQUEST_ID.set(rid)
        started = time.perf_counter()
        answer = {"status": 0, "size": 0}

        async def counted(message: Message) -> None:
            if message["type"] == "http.response.start":
                answer["status"] = int(message["status"])
            elif message["type"] == "http.response.body":
                answer["size"] += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, counted)
        except Exception as exc:
            answer["status"] = answer["status"] or 500
            self.log.application(
                logging.ERROR, "unhandled_exception", "unhandled exception", _info(exc)
            )
            raise
        except BaseException:
            answer["status"] = answer["status"] or 499  # cancelled: the client left
            raise
        finally:
            path = _path(scope)
            status = answer["status"] or 500  # uvicorn answers 500 for no response
            if status >= 400 or self.quiet is None or not self.quiet.search(path):
                self.log.access(
                    request_id=rid,
                    method=str(scope.get("method", "")),
                    path=_with_query(path, scope),
                    status=status,
                    size=answer["size"],
                    duration_ms=(time.perf_counter() - started) * 1000,
                    agent=agent_class(_header(scope, b"user-agent")),
                )
            _REQUEST_ID.reset(token)


def _path(scope: Scope) -> str:
    raw = scope.get("raw_path")
    return bytes(raw).decode("utf-8", "replace") if raw else str(scope.get("path", ""))


def _with_query(path: str, scope: Scope) -> str:
    query = bytes(scope.get("query_string", b"")).decode("utf-8", "replace")
    return f"{path}?{redact_query(query)}" if query else path


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", ()):
        if bytes(key).lower() == name:
            return bytes(value).decode("latin-1")
    return None
