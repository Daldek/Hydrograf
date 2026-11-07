"""A run by PGW units leaves the database a run of the whole raster would.

The synthetic DEM of ``tests.dem_equivalence.split_scene`` is processed twice into a
private PostGIS database: ``process_dem`` of the whole raster, then ``process_dem
--units``. The rows of ``stream_network`` and ``stream_catchments``, and what the
runtime reads from them through the ``CatchmentGraph`` (upstream traversal and
aggregated statistics), must agree up to the numbering of the segments. A run that
fails leaves the published network as it was.
"""

import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from core import database, unit_hydrology
from core.active_run import ACTIVE_RUN_FILE, read_active_run
from core.catchment_graph import CatchmentGraph
from scripts import process_dem as single
from tests.conftest_db import requires_db
from tests.dem_equivalence import (
    THRESHOLDS_M2,
    SplitScene,
    split_scene,
    write_pgw_geopackage,
)
from tests.scratch_db import scratch_database

pytestmark = [requires_db, pytest.mark.db]

CODES = ("RW0001", "RW0002", "LW0003")
STREAM_COLUMNS = (
    "threshold_m2, strahler_order, length_m, upstream_area_km2, "
    "mean_slope_percent, source, ST_AsText(geom) AS geometry"
)
CATCHMENT_COLUMNS = (
    "threshold_m2, area_km2, mean_elevation_m, mean_slope_percent, strahler_order, "
    "elevation_min_m, elevation_max_m, perimeter_km, stream_length_km, "
    "hydraulic_length_km, elev_histogram::text AS histogram, max_flow_dist_m, "
    "outlet_flow_dist_m, flow_path_head_elev_m, overland_length_m, overland_drop_m, "
    "stream_head_elev_m, ST_AsText(geom) AS geometry, "
    "ST_AsText(longest_flow_path_geom) AS longest_flow_path, "
    "ST_AsText(divide_flow_path_geom) AS divide_flow_path"
)


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    """A private migrated database, which ``core.database`` is bound to."""
    with scratch_database() as url:
        bound = create_engine(url)
        previous_engine = database._engine
        previous_bind = database.SessionLocal.kw.get("bind")
        database._engine = bound
        database.SessionLocal.configure(bind=bound)
        try:
            yield bound
        finally:
            database._engine = previous_engine
            database.SessionLocal.configure(bind=previous_bind)
            bound.dispose()


@pytest.fixture(autouse=True)
def _empty_database(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE processing_runs, stream_network, stream_catchments "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture(scope="module")
def scene(tmp_path_factory: pytest.TempPathFactory) -> SplitScene:
    return split_scene(tmp_path_factory.mktemp("scene"), 3, True)


@pytest.fixture(scope="module")
def pgw(scene: SplitScene, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("pgw") / "pgw.gpkg"
    write_pgw_geopackage(path, scene, CODES)
    return path


def _snapshot(engine: Engine) -> dict[str, Any]:
    """Rows of the network by stream geometry, and the graph as the API reads it."""
    with engine.connect() as connection:
        streams = connection.execute(
            text(
                f"SELECT segment_idx, {STREAM_COLUMNS} FROM stream_network "
                "ORDER BY threshold_m2, segment_idx"
            )
        ).all()
        catchments = connection.execute(
            text(
                f"SELECT segment_idx, downstream_segment_idx, {CATCHMENT_COLUMNS} "
                "FROM stream_catchments ORDER BY threshold_m2, segment_idx"
            )
        ).all()
    key = {(row.threshold_m2, row.segment_idx): row.geometry for row in streams}
    for threshold in {t for t, _ in key}:
        indexes = sorted(i for t, i in key if t == threshold)
        assert indexes == list(range(1, len(indexes) + 1)), "ids are dense from 1"
        geometries = [g for (t, _), g in key.items() if t == threshold]
        assert len(set(geometries)) == len(geometries), "a segment is told by its line"
    return {
        "streams": {
            (row.threshold_m2, row.geometry): tuple(row)[1:] for row in streams
        },
        "catchments": {
            (row.threshold_m2, key[row.threshold_m2, row.segment_idx]): (
                key.get((row.threshold_m2, row.downstream_segment_idx)),
                *tuple(row)[2:],
            )
            for row in catchments
        },
        "graph": _graph(engine, key),
    }


def _graph(engine: Engine, key: dict[tuple[int, int], str]) -> dict[Any, Any]:
    """Upstream sets and aggregated statistics of every node, by stream geometry."""
    graph = CatchmentGraph()
    with Session(engine) as session:
        graph.load(session)
    nodes = {}
    for (threshold, segment_idx), geometry in key.items():
        node = graph.lookup_by_segment_idx(threshold, segment_idx)
        if node is None:
            continue  # a threshold without sub-catchments
        upstream = graph.traverse_upstream(node)
        members = sorted(
            key[threshold, index]
            for index in graph.get_segment_indices(upstream, threshold)
        )
        statistics = graph.aggregate_stats(upstream, outlet_idx=node)
        nodes[threshold, geometry] = (members, _plain(statistics))
    return nodes


def _plain(value: Any) -> Any:
    """Reduce aggregated statistics to comparable Python values.

    NaN is None, and floats are rounded to a nanometre or a nano-unit: the sums of a
    traversal over renumbered segments add in another order.
    """
    if isinstance(value, dict):
        return {name: _plain(item) for name, item in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    value = value.item() if hasattr(value, "item") else value
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, 9)
    return value


def _run_whole(scene: SplitScene, directory: Path) -> None:
    directory.mkdir()
    single.process_dem(
        scene.dem_path,
        output_dir=directory,
        clear_existing=True,
        thresholds=list(THRESHOLDS_M2),
    )


def _run_units(
    scene: SplitScene, pgw: Path, directory: Path, **options: Any
) -> dict[str, Any]:
    return single.process_dem(
        scene.dem_path,
        output_dir=directory,
        clear_existing=True,
        thresholds=list(THRESHOLDS_M2),
        units_path=pgw,
        **options,
    )


def test_a_run_by_units_leaves_the_database_of_the_whole_raster_run(
    engine, scene, pgw, tmp_path
):
    _run_whole(scene, tmp_path / "whole")
    whole = _snapshot(engine)
    assert whole["graph"], "the graph holds sub-catchments"

    stats = _run_units(scene, pgw, tmp_path / "units")
    by_units = _snapshot(engine)

    assert by_units["streams"] == whole["streams"]
    assert by_units["catchments"] == whole["catchments"]
    assert by_units["graph"] == whole["graph"]
    with engine.connect() as connection:
        runs = connection.execute(
            text("SELECT id, status, published_counts FROM processing_runs")
        ).all()
        units_rows = connection.execute(
            text(
                "SELECT owner_code, status, row_start, row_stop, col_start, col_stop "
                "FROM processing_units ORDER BY owner_code"
            )
        ).all()
    assert [(run.id, run.status) for run in runs] == [(stats["run_id"], "active")]
    assert runs[0].published_counts["stream_segments"] == {
        str(t): len([1 for (threshold, _) in by_units["streams"] if threshold == t])
        for t in THRESHOLDS_M2
    }
    assert [(row.owner_code, row.status) for row in units_rows] == [
        (code, "complete") for code in sorted(CODES)
    ]
    for row in units_rows:
        assert 0 <= row.row_start < row.row_stop <= scene.dem.shape[0]
        assert 0 <= row.col_start < row.col_stop <= scene.dem.shape[1]


def test_a_second_run_replaces_the_network_and_supersedes_the_first(
    engine, scene, pgw, tmp_path
):
    first = _run_units(scene, pgw, tmp_path / "first")
    network = _snapshot(engine)

    second = _run_units(scene, pgw, tmp_path / "second")

    assert _snapshot(engine) == network, "the same input gives the same network"
    with engine.connect() as connection:
        statuses = dict(
            connection.execute(text("SELECT id, status FROM processing_runs")).all()
        )
        segments = connection.execute(text("SELECT count(*) FROM stream_network"))
    assert statuses == {first["run_id"]: "superseded", second["run_id"]: "active"}
    for stats in (first, second):
        active = read_active_run(Path(stats["unit_rasters_dir"]).parents[1])
        assert active is not None and active.run_id == stats["run_id"]
    assert segments.scalar_one() == len(network["streams"]), "replaced, not added to"


def test_a_run_that_fails_leaves_the_published_network_as_it_was(
    engine, scene, pgw, tmp_path, monkeypatch
):
    _run_units(scene, pgw, tmp_path / "published")
    network = _snapshot(engine)

    def out_of_memory(*args: Any, **kwargs: Any) -> None:
        raise MemoryError("the fill of the whole grid")

    monkeypatch.setattr(unit_hydrology, "fill_whole_grid", out_of_memory)
    with pytest.raises(MemoryError, match="the fill of the whole grid"):
        _run_units(scene, pgw, tmp_path / "failed")

    assert _snapshot(engine) == network
    with engine.connect() as connection:
        runs = connection.execute(
            text(
                "SELECT status, error, "
                "(SELECT count(*) FROM processing_units u WHERE u.run_id = r.id "
                "   AND u.status = 'pending') AS pending "
                "FROM processing_runs r ORDER BY id"
            )
        ).all()
    assert [run.status for run in runs] == ["active", "failed"]
    assert "MemoryError" in runs[1].error
    assert runs[1].pending == 3
    assert not (tmp_path / "failed" / ACTIVE_RUN_FILE).exists()


def test_a_whole_raster_run_supersedes_the_unit_run_and_removes_its_pointer(
    engine, scene, pgw, tmp_path
):
    out = tmp_path / "out"
    by_units = _run_units(scene, pgw, out)
    active = read_active_run(out)
    assert active is not None and active.run_id == by_units["run_id"]

    single.process_dem(
        scene.dem_path,
        output_dir=out,
        clear_existing=True,
        thresholds=list(THRESHOLDS_M2),
    )

    assert read_active_run(out) is None
    assert Path(by_units["unit_rasters_dir"]).is_dir(), "the files of the run stay"
    with engine.connect() as connection:
        run = connection.execute(
            text("SELECT id, status, superseded_at FROM processing_runs")
        ).one()
        segments = connection.execute(text("SELECT count(*) FROM stream_network"))
    assert (run.id, run.status) == (by_units["run_id"], "superseded")
    assert run.superseded_at is not None
    assert segments.scalar_one() > 0


def test_a_schema_without_processing_runs_has_no_run_to_supersede():
    with scratch_database("004") as url:
        bound = create_engine(url)
        try:
            with Session(bound) as session:
                assert single._supersede_active_unit_run(session) is None
        finally:
            bound.dispose()
