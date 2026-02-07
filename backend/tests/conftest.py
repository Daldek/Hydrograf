"""
Shared test fixtures for pytest.

Provides mock database sessions, sample data, and common fixtures
used across unit and integration tests.
"""

from unittest.mock import MagicMock

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
def mock_stream_query_result():
    """Mock result from find_nearest_stream SQL query."""
    result = MagicMock()
    result.id = 1
    result.x = 500000.0
    result.y = 600000.0
    result.elevation = 150.0
    result.flow_accumulation = 1000
    result.slope = 2.5
    result.downstream_id = None
    result.cell_area = 25.0
    result.is_stream = True
    result.distance = 50.0
    return result


@pytest.fixture
def mock_upstream_query_results():
    """Mock results from traverse_upstream SQL query."""
    results = []
    for i in range(4):
        r = MagicMock()
        r.id = i + 1
        r.x = 500000.0 + i * 5
        r.y = 600000.0 + (i % 2) * 5
        r.elevation = 150.0 + i * 2
        r.flow_accumulation = 1000 - i * 250
        r.slope = 2.5
        r.downstream_id = i if i > 0 else None
        r.cell_area = 25.0
        r.is_stream = i == 0
        results.append(r)
    return results


@pytest.fixture
def large_upstream_results():
    """Mock results for large watershed (100 cells)."""
    results = []
    for i in range(100):
        r = MagicMock()
        r.id = i + 1
        r.x = 500000.0 + (i % 10) * 5
        r.y = 600000.0 + (i // 10) * 5
        r.elevation = 150.0 + i * 0.5
        r.flow_accumulation = max(0, 1000 - i * 10)
        r.slope = 2.0 + (i % 5) * 0.2
        r.downstream_id = i if i > 0 else None
        r.cell_area = 25.0
        r.is_stream = i == 0
        results.append(r)
    return results
