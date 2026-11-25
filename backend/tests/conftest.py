"""
Shared test fixtures for pytest.

Provides mock database sessions, sample data, and common fixtures
used across unit and integration tests.
"""

import inspect
import json
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest


@pytest.fixture(autouse=True)
def _private_kartograf_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test the private Kartograf store of its cache directory (ADR-061).

    A ``HYDROGRAF_KARTOGRAF_ROOT`` of the shell names a real store shared with other
    producers (ADR-066); no test may download into it or clean it.
    """
    monkeypatch.delenv("HYDROGRAF_KARTOGRAF_ROOT", raising=False)


@pytest.fixture(autouse=True)
def _fresh_traffic(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Give every test the request limit and daily totals of a new process (ADR-084).

    The suite's requests all come from one client address, so one shared limit would
    refuse them after the first 300; the statistics go to the session's temporary
    directory, never to ``/data``.
    """
    from api.main import app
    from api.traffic import Traffic
    from core.config import Settings

    data_dir = tmp_path_factory.getbasetemp() / "data"
    app.state.traffic = Traffic(Settings(hydrograf_data_dir=str(data_dir)))


@contextmanager
def _job_session() -> Iterator[Any]:
    """Open the database session of a job: the test's ``get_db`` override, if any.

    A job runs in a thread of its own, outside FastAPI's dependencies, so it sees the
    database a synchronous route would see only through this factory.
    """
    from api.main import app
    from core.database import get_db, get_db_session

    override = app.dependency_overrides.get(get_db)
    if override is None:
        with get_db_session() as db:
            yield db
        return
    made = override()
    if not inspect.isgenerator(made):
        yield made
        return
    try:
        yield next(made)
    finally:
        made.close()


def _memory_jobs() -> None:
    """Give the app the job store of a new process that keeps no jobs file."""
    from api.jobs import JobStore
    from api.main import app

    app.state.jobs = JobStore(None, session=_job_session)


@pytest.fixture(autouse=True, scope="session")
def _no_jobs_file() -> None:
    """Keep the jobs of the whole session out of the shell's state directory (ADR-091).

    The store of ``api.main`` lists its active jobs in
    ``<state_dir>/hydrograf/jobs.json``; a fixture of a module or a class runs before
    the store of each test (``_fresh_jobs``) and gets this one.
    """
    _memory_jobs()


@pytest.fixture(autouse=True)
def _fresh_jobs() -> None:
    """Give every test the job store of a new process: in memory, on its database."""
    _memory_jobs()


@pytest.fixture(autouse=True, scope="session")
def _logs_in_session_temp(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Write the app's logs (Nogat DEV-12.6) into the session's temporary directory.

    ``api.main.log`` resolves its directory from the shell's state_dir when imported;
    no test may write into ``~/.local/state/nogat`` or prune the files there.
    """
    from api.main import log

    log.close()
    log.directory = tmp_path_factory.getbasetemp() / "state" / "hydrograf" / "logs"


@pytest.fixture
def log_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[[], list[dict[str, Any]]]]:
    """Give the app's logs a directory of the test alone; return the records' reader.

    The reader returns every record written during the test, file by file in the
    order of their names (``access``, ``app``, ``lifecycle``), each in written order.
    """
    from api.main import log

    directory = tmp_path / "logs"
    log.close()
    monkeypatch.setattr(log, "directory", directory)

    def read() -> list[dict[str, Any]]:
        return [
            json.loads(line)
            for path in sorted(directory.glob("*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()
        ]

    yield read
    log.close()


@pytest.fixture
def mock_db():
    """Create mock database session."""
    return MagicMock()


@pytest.fixture
def serve_imgw() -> Iterator[
    Callable[[Callable[[httpx.Request], httpx.Response]], None]
]:
    """Answer the HTTP calls of the real obserwator client from a handler, offline.

    Call the returned function with ``handler(request) -> httpx.Response``; whatever
    obserwator asks for from then on goes to the handler, never to the network.
    """
    real_client = httpx.Client
    patcher = pytest.MonkeyPatch()

    def serve(handler: Callable[[httpx.Request], httpx.Response]) -> None:
        def client(*args: Any, **kwargs: Any) -> httpx.Client:
            return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

        patcher.setattr(httpx, "Client", client)

    yield serve
    patcher.undo()


@pytest.fixture
def pmaxtp_body() -> Callable[..., dict[str, Any]]:
    """Build a PMAXTP answer: ``{"data": {"ks": {duration: {probability: mm}}, ...}}``.

    The value of a cell is ``duration / 10 + probability / 100`` for ks, ``+ 1`` for sg
    and ``0.5`` for rb, so a test can tell which cell a result was read from.
    """

    def build(
        durations: Sequence[int], probabilities: Sequence[float]
    ) -> dict[str, Any]:
        def key(number: float) -> str:
            return str(int(number)) if number == int(number) else str(number)

        def table(value: Callable[[int, float], float]) -> dict[str, dict[str, float]]:
            return {
                key(d): {key(p): value(d, p) for p in probabilities} for d in durations
            }

        return {
            "data": {
                "ks": table(lambda d, p: d / 10 + p / 100),
                "sg": table(lambda d, p: d / 10 + p / 100 + 1),
                "rb": table(lambda d, p: 0.5),
            }
        }

    return build
