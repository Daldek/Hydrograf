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


@pytest.fixture
def mock_db():
    """Create mock database session."""
    return MagicMock()


@pytest.fixture
def serve_imgw() -> Iterator[
    Callable[[Callable[[httpx.Request], httpx.Response]], None]
]:
    """Answer the HTTP calls of the real imgwtools client from a handler, offline.

    Call the returned function with ``handler(request) -> httpx.Response``; whatever
    imgwtools asks for from then on goes to the handler, never to the network.
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
