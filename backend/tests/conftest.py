"""
Shared test fixtures for pytest.

Provides mock database sessions, sample data, and common fixtures
used across unit and integration tests.
"""

from collections.abc import Callable, Iterator, Sequence
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
