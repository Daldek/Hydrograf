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

from core.watershed import FlowCell


@pytest.fixture
def mock_db():
    """Create mock database session."""
    return MagicMock()


@pytest.fixture
def sample_outlet_cell():
    """Sample outlet FlowCell for testing."""
    return FlowCell(
        id=1,
        x=500000.0,
        y=600000.0,
        elevation=150.0,
        flow_accumulation=1000,
        slope=2.5,
        downstream_id=None,
        cell_area=25.0,
        is_stream=True,
    )


@pytest.fixture
def sample_cells():
    """Sample list of FlowCells representing a small watershed."""
    return [
        FlowCell(
            id=1,
            x=500000.0,
            y=600000.0,
            elevation=150.0,
            flow_accumulation=1000,
            slope=2.5,
            downstream_id=None,
            cell_area=25.0,
            is_stream=True,
        ),
        FlowCell(
            id=2,
            x=500005.0,
            y=600000.0,
            elevation=152.0,
            flow_accumulation=500,
            slope=3.0,
            downstream_id=1,
            cell_area=25.0,
            is_stream=False,
        ),
        FlowCell(
            id=3,
            x=500010.0,
            y=600000.0,
            elevation=154.0,
            flow_accumulation=200,
            slope=2.8,
            downstream_id=2,
            cell_area=25.0,
            is_stream=False,
        ),
        FlowCell(
            id=4,
            x=500000.0,
            y=600005.0,
            elevation=153.0,
            flow_accumulation=300,
            slope=2.2,
            downstream_id=1,
            cell_area=25.0,
            is_stream=False,
        ),
    ]


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
