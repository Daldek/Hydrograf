"""The catchment graph follows the network in PostGIS (marker ``db``).

A publication, the stream matching after it and a clean-up change
``network_version``, so ``loaded_catchment_graph`` loads the network of the database
at the next request. The tests commit and truncate, so they use a private database.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import core.catchment_graph as cg_module
from core.catchment_graph import CatchmentGraph, loaded_catchment_graph
from tests.conftest_db import requires_db
from tests.scratch_db import scratch_database

pytestmark = [requires_db, pytest.mark.db]

THRESHOLD_M2 = 10_000


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    """A private migrated database."""
    with scratch_database() as url:
        bound = create_engine(url)
        try:
            yield bound
        finally:
            bound.dispose()


@pytest.fixture(autouse=True)
def _no_network(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cg_module, "_catchment_graph", None)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE stream_network, stream_catchments CASCADE"))


def _commit(engine: Engine, *statements: tuple[str, dict[str, Any]]) -> None:
    """Commit the statements in one transaction and flush its statistics.

    A backend adds the counts of its transactions when it goes idle, at most once
    a second (otherwise ten seconds later), and when it disconnects; the forced
    flush makes the test independent of that timing.
    """
    with engine.connect() as connection:
        connection.execute(text("SELECT pg_stat_force_next_flush()"))
        for sql, params in statements:
            connection.execute(text(sql), params)
        connection.commit()


_INSERT_CATCHMENT = """
    INSERT INTO stream_catchments
        (geom, segment_idx, threshold_m2, area_km2, downstream_segment_idx)
    VALUES (ST_Multi(ST_MakeEnvelope(:x, 0, :x + 100, 100, 2180)), :segment,
            :threshold, :area, :downstream)
"""
_INSERT_STREAM = """
    INSERT INTO stream_network
        (geom, threshold_m2, segment_idx, source, length_m, is_real_stream)
    VALUES (ST_MakeLine(ST_Point(:x, 50, 2180), ST_Point(:x + 100, 50, 2180)),
            :threshold, :segment, 'DEM_DERIVED', 100, false)
"""


def _publish(engine: Engine, areas_km2: list[float]) -> None:
    """Replace the network with a chain of sub-catchments, as a run does.

    Segment 1 drains into 2 and so on; the last one is the outlet. The streams
    are not matched to BDOT10k yet.
    """
    statements: list[tuple[str, dict[str, Any]]] = [
        ("DELETE FROM stream_network", {}),
        ("DELETE FROM stream_catchments", {}),
    ]
    for segment, area_km2 in enumerate(areas_km2, start=1):
        params = {
            "x": 100.0 * segment,
            "segment": segment,
            "threshold": THRESHOLD_M2,
            "area": area_km2,
            "downstream": segment + 1 if segment < len(areas_km2) else None,
        }
        statements += [(_INSERT_CATCHMENT, params), (_INSERT_STREAM, params)]
    _commit(engine, *statements)


def _graph(engine: Engine) -> CatchmentGraph | None:
    """The graph a request gets: a session of its own, as the API opens one."""
    with Session(engine) as db:
        return loaded_catchment_graph(db)


def _watershed(graph: CatchmentGraph, outlet_segment: int) -> dict[str, Any]:
    outlet = graph.lookup_by_segment_idx(THRESHOLD_M2, outlet_segment)
    assert outlet is not None
    return graph.aggregate_stats(graph.traverse_upstream(outlet), outlet_idx=outlet)


def test_a_publication_reloads_the_graph(engine):
    _publish(engine, [1.0, 2.0])
    old = _graph(engine)
    assert _graph(engine) is old

    _publish(engine, [1.0, 2.0, 4.0])
    new = _graph(engine)

    assert new is not old
    assert _watershed(new, 3)["area_km2"] == pytest.approx(7.0)
    # A request that took the old graph keeps the old network whole
    assert _watershed(old, 2)["area_km2"] == pytest.approx(3.0)


def test_the_stream_matching_after_a_publication_reloads_the_graph(engine):
    _publish(engine, [1.0, 2.0])
    assert _watershed(_graph(engine), 2)["bdot_stream_count"] == 0

    _commit(engine, ("UPDATE stream_network SET is_real_stream = true", {}))

    assert _watershed(_graph(engine), 2)["bdot_stream_count"] == 2


def test_a_clean_up_leaves_no_graph(engine):
    _publish(engine, [1.0, 2.0])
    assert _graph(engine) is not None

    _commit(engine, ("TRUNCATE stream_catchments, stream_network", {}))

    assert _graph(engine) is None
