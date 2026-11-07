"""Run store of the PGW unit bootstrap against a real PostGIS (migration 005).

``publish_run`` deletes ALL DEM-derived streams and ALL sub-catchments, so the tests run
on a scratch database of their own (``tests.scratch_db``), never on the shared one.
Covers migration 005 (constraints, the one-active-run index, the downgrade cycle),
``core.unit_run_store`` (begin, checkpoint, publish all or nothing, fail) and the
``commit=False`` / ``local=True`` options of ``core.db_bulk`` that the publication uses.
"""

import hashlib
import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg2  # type: ignore[import-untyped]
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core import db_bulk, unit_run_store
from core.unit_run_store import (
    IncompleteRunError,
    RunNotFoundError,
    RunStateError,
    StagedOutputsError,
    UnknownUnitError,
    begin_run,
    checkpoint_unit,
    fail_run,
    publish_run,
)
from tests.conftest_db import requires_db
from tests.scratch_db import migrate, scratch_database

pytestmark = [requires_db, pytest.mark.db]

CODES = ("RW0001", "RW0002", "LW0003")
FILE_NAMES = ("filled_dem", "flow_dir", "acc")


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def engine():
    """Engine of a private database migrated to head."""
    with scratch_database() as url:
        scratch_engine = create_engine(url)
        try:
            yield scratch_engine
        finally:
            scratch_engine.dispose()


@pytest.fixture(autouse=True)
def clean(engine):
    """Start every test from empty run and network tables."""
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '10s'"))
        connection.execute(
            text(
                "TRUNCATE processing_runs, stream_network, stream_catchments "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
def session(engine):
    with Session(engine) as db:
        yield db


def scalar(engine, sql, **params):
    with engine.connect() as connection:
        return connection.execute(text(sql), params).scalar()


def rows(engine, sql, **params):
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(sql), params)]


def snapshot(engine):
    """Everything a failed publication must leave as it was."""
    return {
        "streams": rows(
            engine,
            "SELECT id, source, threshold_m2, segment_idx, ST_AsEWKT(geom) "
            "FROM stream_network ORDER BY id",
        ),
        "catchments": rows(
            engine,
            "SELECT id, threshold_m2, segment_idx, ST_AsEWKT(geom) "
            "FROM stream_catchments ORDER BY id",
        ),
        "runs": rows(
            engine,
            "SELECT id, status, activated_at, superseded_at, failed_at, error, "
            "published_counts::text FROM processing_runs ORDER BY id",
        ),
        "units": rows(
            engine,
            "SELECT run_id, owner_code, status, outputs::text "
            "FROM processing_units ORDER BY run_id, owner_code",
        ),
    }


def status_of(engine, run_id):
    return scalar(engine, "SELECT status FROM processing_runs WHERE id = :i", i=run_id)


def seg(x, y, order=1):
    return {
        "coords": [(x, y), (x + 10, y + 3), (x + 20, y), (x + 30, y + 5)],
        "strahler_order": order,
        "length_m": 31.0,
        "upstream_area_km2": 0.5,
        "mean_slope_percent": 2.0,
    }


def shed(i, x, y, downstream=None):
    ring = f"{x} {y}, {x + 100} {y}, {x + 100} {y + 100}, {x} {y + 100}, {x} {y}"
    return {
        "wkt": f"MULTIPOLYGON((({ring})))",
        "segment_idx": i,
        "area_km2": 0.01,
        "mean_elevation_m": 100.0,
        "mean_slope_percent": 2.0,
        "strahler_order": 1,
        "downstream_segment_idx": downstream,
    }


def results_for(n, base_x):
    """Results of thresholds 1000 (``n`` rows) and 10000 (``n // 2``, at least 1)."""
    half = max(1, n // 2)
    segments = {
        1000: [seg(base_x + 100 * i, 600000) for i in range(n)],
        10000: [seg(base_x + 100 * i, 610000) for i in range(half)],
    }
    catchments = {
        1000: [
            shed(i + 1, base_x + 200 * i, 620000, i + 2 if i + 1 < n else None)
            for i in range(n)
        ],
        10000: [shed(i + 1, base_x + 200 * i, 630000) for i in range(half)],
    }
    return segments, catchments


def seed_previous(engine):
    """A previous publication (3 DEM streams, 2 catchments) and a stream of BDOT10K."""
    insert_stream = text(
        "INSERT INTO stream_network "
        "(geom, strahler_order, length_m, source, threshold_m2, segment_idx) "
        "VALUES (ST_GeomFromText(:wkt, 2180), 1, 10, :source, 1000, :i)"
    )
    insert_catchment = text(
        "INSERT INTO stream_catchments (geom, segment_idx, threshold_m2, area_km2) "
        "VALUES (ST_Multi(ST_GeomFromText(:wkt, 2180)), :i, 1000, 0.01)"
    )
    with engine.begin() as connection:
        for i in range(3):
            x = 400000 + i * 50
            connection.execute(
                insert_stream,
                {
                    "wkt": f"LINESTRING({x} 500000, {x + 20} 500010)",
                    "source": "DEM_DERIVED",
                    "i": i + 1,
                },
            )
        connection.execute(
            insert_stream,
            {
                "wkt": "LINESTRING(300000 300000, 300020 300010)",
                "source": "BDOT10K",
                "i": 99,
            },
        )
        for i in range(2):
            x = 400000 + i * 200
            ring = f"{x} 500000, {x + 100} 500000, {x + 100} 500100, {x} 500000"
            connection.execute(
                insert_catchment, {"wkt": f"POLYGON(({ring}))", "i": i + 1}
            )


def write_unit_files(directory, code, filler=b"a"):
    """Write the three raster files of a unit; return ``{name: path}``."""
    directory = Path(directory) / code
    directory.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in FILE_NAMES:
        path = directory / f"{name}.bin"
        path.write_bytes(filler * 64 + code.encode() + name.encode())
        files[name] = path
    return files


def begin(engine, codes=CODES, fingerprint="fp-1"):
    with Session(engine) as db:
        return begin_run(
            db,
            input_fingerprint=fingerprint,
            source_raster="/data/dem.vrt",
            pgw_path="/data/pgw.gpkg",
            config={"thresholds_m2": [1000, 10000], "halo_m": 500},
            owner_codes=codes,
        )


def stage(engine, tmp_path, *, codes=CODES, fingerprint="fp-1", complete=True):
    """Begin a run, by default checkpoint every unit; return ``(run_id, files)``."""
    run_id = begin(engine, codes, fingerprint)
    files = {}
    if complete:
        for k, code in enumerate(codes):
            files[code] = write_unit_files(tmp_path / f"run{run_id}", code)
            with Session(engine) as db:
                checkpoint_unit(
                    db, run_id, code, (k * 10, k * 10 + 50, 0, 100), files[code]
                )
    return run_id, files


def violated_constraint(engine, sql, **params):
    """Run a statement that the database must reject; return the constraint's name."""
    with pytest.raises(IntegrityError) as caught, engine.begin() as connection:
        connection.execute(text(sql), params)
    return caught.value.orig.diag.constraint_name


# ---------------------------------------------------------------------------
# Migration 005
# ---------------------------------------------------------------------------


def test_migration_005_downgrade_and_upgrade_cycle():
    with scratch_database(revision="004") as url:
        scratch_engine = create_engine(url)

        def tables():
            return {
                name: scalar(
                    scratch_engine, "SELECT to_regclass(:n) IS NOT NULL", n=name
                )
                for name in ("processing_runs", "processing_units", "stream_network")
            }

        try:
            assert tables() == {
                "processing_runs": False,
                "processing_units": False,
                "stream_network": True,
            }
            migrate(url, "upgrade", "005")
            assert all(tables().values())
            # The new tables are usable, and a downgrade drops them with their rows.
            run_id = begin(scratch_engine, ("RW0001",))
            assert status_of(scratch_engine, run_id) == "staging"

            migrate(url, "downgrade", "004")
            assert tables() == {
                "processing_runs": False,
                "processing_units": False,
                "stream_network": True,
            }
            assert (
                scalar(scratch_engine, "SELECT version_num FROM alembic_version")
                == "004"
            )

            migrate(url, "upgrade", "head")
            assert all(tables().values())
            assert scalar(scratch_engine, "SELECT count(*) FROM processing_runs") == 0
        finally:
            scratch_engine.dispose()


RUN_DEFAULTS = {
    "status": "staging",
    "fingerprint": "fp",
    "config": "{}",
    "activated_at": None,
    "superseded_at": None,
    "failed_at": None,
    "error": None,
    "counts": None,
}
NOW = datetime(2026, 11, 7, tzinfo=UTC)
INSERT_RUN = (
    "INSERT INTO processing_runs (status, input_fingerprint, source_raster, pgw_path, "
    "config, activated_at, superseded_at, failed_at, error, published_counts) "
    "VALUES (:status, :fingerprint, 's', 'p', CAST(:config AS jsonb), :activated_at, "
    ":superseded_at, :failed_at, :error, CAST(:counts AS jsonb))"
)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"status": "bogus"}, "chk_processing_runs_status"),
        ({"fingerprint": ""}, "chk_processing_runs_fingerprint"),
        ({"config": "[]"}, "chk_processing_runs_config"),
        # A published run needs both the activation time and the counts.
        (
            {"status": "active", "activated_at": NOW},
            "chk_processing_runs_published",
        ),
        ({"status": "active", "counts": "{}"}, "chk_processing_runs_published"),
        ({"activated_at": NOW, "counts": "{}"}, "chk_processing_runs_published"),
        (
            {"status": "superseded", "activated_at": NOW, "counts": "{}"},
            "chk_processing_runs_superseded",
        ),
        ({"superseded_at": NOW}, "chk_processing_runs_superseded"),
        # A failed run needs its time and a reason.
        ({"status": "failed", "failed_at": NOW}, "chk_processing_runs_failed"),
        (
            {"status": "failed", "failed_at": NOW, "error": ""},
            "chk_processing_runs_failed",
        ),
        ({"status": "failed", "error": "boom"}, "chk_processing_runs_failed"),
    ],
)
def test_processing_runs_rejects_inconsistent_rows(engine, overrides, constraint):
    params = {**RUN_DEFAULTS, **overrides}
    assert violated_constraint(engine, INSERT_RUN, **params) == constraint
    assert scalar(engine, "SELECT count(*) FROM processing_runs") == 0


def test_processing_runs_accepts_each_consistent_state(engine):
    states = [
        {},
        {"status": "active", "activated_at": NOW, "counts": "{}"},
        {
            "status": "superseded",
            "activated_at": NOW,
            "superseded_at": NOW,
            "counts": "{}",
        },
        {"status": "failed", "failed_at": NOW, "error": "boom"},
    ]
    with engine.begin() as connection:
        for overrides in states:
            connection.execute(text(INSERT_RUN), {**RUN_DEFAULTS, **overrides})
    assert scalar(engine, "SELECT count(*) FROM processing_runs") == 4


def test_only_one_run_can_be_active_but_other_states_repeat(engine):
    active = {"status": "active", "activated_at": NOW, "counts": "{}"}
    inactive = [
        {},
        {},
        {"status": "failed", "failed_at": NOW, "error": "boom"},
        {
            "status": "superseded",
            "activated_at": NOW,
            "superseded_at": NOW,
            "counts": "{}",
        },
        {
            "status": "superseded",
            "activated_at": NOW,
            "superseded_at": NOW,
            "counts": "{}",
        },
    ]
    with engine.begin() as connection:
        for overrides in [active, *inactive]:
            connection.execute(text(INSERT_RUN), {**RUN_DEFAULTS, **overrides})

    assert (
        violated_constraint(engine, INSERT_RUN, **{**RUN_DEFAULTS, **active})
        == "idx_processing_runs_one_active"
    )
    staging_id = scalar(
        engine, "SELECT id FROM processing_runs WHERE status = 'staging' LIMIT 1"
    )
    activate = (
        "UPDATE processing_runs SET status = 'active', activated_at = now(), "
        "published_counts = '{}' WHERE id = :i"
    )
    assert violated_constraint(engine, activate, i=staging_id) == (
        "idx_processing_runs_one_active"
    )
    assert (
        scalar(engine, "SELECT count(*) FROM processing_runs WHERE status='active'")
        == 1
    )


@pytest.fixture
def unit_run(engine):
    """A staging run with the pending unit ``U1``."""
    return begin(engine, ("U1",))


COMPLETE = (
    "status = 'complete', row_start = 0, row_stop = 5, col_start = 0, col_stop = 5, "
    "outputs = '{\"a\": {}}', completed_at = now()"
)


@pytest.mark.parametrize(
    ("assignment", "constraint"),
    [
        ("status = 'bogus'", "chk_processing_units_status"),
        # Complete means bounds, manifest and time, all together.
        ("status = 'complete'", "chk_processing_units_complete"),
        (
            "status = 'complete', row_start = 0, row_stop = 5, col_start = 0, "
            "col_stop = 5, outputs = '{\"a\": {}}'",
            "chk_processing_units_complete",
        ),
        (
            "status = 'complete', row_start = 0, row_stop = 5, col_start = 0, "
            "col_stop = 5, completed_at = now()",
            "chk_processing_units_complete",
        ),
        (
            "status = 'complete', row_start = 0, row_stop = 5, col_start = 0, "
            "outputs = '{\"a\": {}}', completed_at = now()",
            "chk_processing_units_complete",
        ),
        (COMPLETE.replace("'complete'", "'pending'"), "chk_processing_units_complete"),
        (
            COMPLETE.replace("row_stop = 5", "row_stop = -1"),
            "chk_processing_units_bounds",
        ),
        (
            COMPLETE.replace(
                "row_start = 0, row_stop = 5", "row_start = 5, row_stop = 1"
            ),
            "chk_processing_units_bounds",
        ),
        (
            COMPLETE.replace(
                "col_start = 0, col_stop = 5", "col_start = 9, col_stop = 8"
            ),
            "chk_processing_units_bounds",
        ),
        (
            COMPLETE.replace("row_start = 0", "row_start = -1"),
            "chk_processing_units_bounds",
        ),
        (COMPLETE.replace("'{\"a\": {}}'", "'{}'"), "chk_processing_units_manifest"),
        (COMPLETE.replace("'{\"a\": {}}'", "'[1]'"), "chk_processing_units_manifest"),
    ],
)
def test_processing_units_rejects_inconsistent_rows(
    engine, unit_run, assignment, constraint
):
    before = snapshot(engine)["units"]
    sql = f"UPDATE processing_units SET {assignment} WHERE run_id = :run"
    assert violated_constraint(engine, sql, run=unit_run) == constraint
    assert snapshot(engine)["units"] == before


def test_processing_units_accepts_a_complete_row_with_empty_bounds(engine, unit_run):
    # An owner can own no cell in a tile: a zero-width half-open range is legal.
    empty = COMPLETE.replace("row_stop = 5", "row_stop = 0")
    sql = f"UPDATE processing_units SET {empty} WHERE run_id = :run"
    with engine.begin() as connection:
        connection.execute(text(sql), {"run": unit_run})
    assert rows(engine, "SELECT status, row_start, row_stop FROM processing_units") == [
        ("complete", 0, 0)
    ]


def test_processing_units_key_owner_and_run_reference(engine, unit_run):
    duplicate = "INSERT INTO processing_units (run_id, owner_code) VALUES (:run, 'U1')"
    assert (
        violated_constraint(engine, duplicate, run=unit_run) == "processing_units_pkey"
    )
    blank = "INSERT INTO processing_units (run_id, owner_code) VALUES (:run, '')"
    assert (
        violated_constraint(engine, blank, run=unit_run) == "chk_processing_units_owner"
    )
    orphan = "INSERT INTO processing_units (run_id, owner_code) VALUES (:run, 'X')"
    assert violated_constraint(engine, orphan, run=unit_run + 1000) == (
        "processing_units_run_id_fkey"
    )


def test_deleting_a_run_deletes_its_units(engine):
    keep = begin(engine, ("A",), "keep")
    drop = begin(engine, ("A", "B"), "drop")
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM processing_runs WHERE id = :i"), {"i": drop}
        )
    assert rows(engine, "SELECT run_id, owner_code FROM processing_units") == [
        (keep, "A")
    ]


# ---------------------------------------------------------------------------
# begin_run
# ---------------------------------------------------------------------------


def test_begin_run_records_a_staging_run_with_one_pending_unit_per_owner(
    engine, session
):
    seed_previous(engine)
    before = snapshot(engine)
    run_id = begin_run(
        session,
        input_fingerprint="abc123",
        source_raster=Path("/data/dem.vrt"),
        pgw_path="/data/pgw.gpkg",
        config={"thresholds_m2": [1000, 10000], "units": Path("/x/units.gpkg")},
        owner_codes=("RW0002", "RW0001"),
    )

    run = rows(
        engine,
        "SELECT status, input_fingerprint, source_raster, pgw_path, config::text, "
        "activated_at, superseded_at, failed_at, error, published_counts "
        "FROM processing_runs WHERE id = :i",
        i=run_id,
    )
    assert len(run) == 1
    status, fingerprint, source, pgw, config, *unset = run[0]
    assert (status, fingerprint, source, pgw) == (
        "staging",
        "abc123",
        "/data/dem.vrt",
        "/data/pgw.gpkg",
    )
    assert json.loads(config) == {
        "thresholds_m2": [1000, 10000],
        "units": "/x/units.gpkg",
    }
    assert unset == [None] * 5
    assert rows(
        engine,
        "SELECT owner_code, status, row_start, outputs, completed_at "
        "FROM processing_units WHERE run_id = :i ORDER BY owner_code",
        i=run_id,
    ) == [
        ("RW0001", "pending", None, None, None),
        ("RW0002", "pending", None, None, None),
    ]
    # The published tables are not touched.
    after = snapshot(engine)
    assert after["streams"] == before["streams"]
    assert after["catchments"] == before["catchments"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"owner_codes": ("A", "B", "A")},
        {"owner_codes": ()},
        {"owner_codes": "RW0001"},
        {"owner_codes": ("A", "  ")},
        {"owner_codes": ("A", None)},
        {"input_fingerprint": ""},
        {"source_raster": " "},
        {"pgw_path": ""},
        {"config": {"halo": {1, 2}}},
        {"config": {"halo": float("nan")}},
        {"config": ["not", "a", "dict"]},
        {"config": {1: object()}},
    ],
)
def test_begin_run_rejects_invalid_arguments_and_writes_nothing(
    engine, session, overrides
):
    arguments = {
        "input_fingerprint": "fp",
        "source_raster": "/data/dem.vrt",
        "pgw_path": "/data/pgw.gpkg",
        "config": {"halo_m": 500},
        "owner_codes": ("A", "B"),
        **overrides,
    }
    with pytest.raises(ValueError):
        begin_run(session, **arguments)
    assert scalar(engine, "SELECT count(*) FROM processing_runs") == 0
    assert scalar(engine, "SELECT count(*) FROM processing_units") == 0


def test_begin_run_rolls_back_the_run_when_the_units_cannot_be_written(engine, session):
    # The owner code is only checked for emptiness by Python; a NUL byte is rejected by
    # PostgreSQL after the run row was inserted.
    with pytest.raises(ValueError, match="NUL"):
        begin_run(
            session,
            input_fingerprint="fp",
            source_raster="s",
            pgw_path="p",
            config={},
            owner_codes=("A", "B\x00"),
        )
    assert scalar(engine, "SELECT count(*) FROM processing_runs") == 0
    assert scalar(engine, "SELECT count(*) FROM processing_units") == 0


# ---------------------------------------------------------------------------
# checkpoint_unit
# ---------------------------------------------------------------------------


def test_checkpoint_marks_the_unit_complete_with_bounds_and_manifest(
    engine, session, tmp_path
):
    run_id = begin(engine, ("RW0001", "RW0002"))
    files = write_unit_files(tmp_path, "RW0001")

    checkpoint_unit(session, run_id, "RW0001", (10, 60, 5, 105), files)

    row = rows(
        engine,
        "SELECT status, row_start, row_stop, col_start, col_stop, outputs::text, "
        "completed_at IS NOT NULL FROM processing_units "
        "WHERE run_id = :i AND owner_code = 'RW0001'",
        i=run_id,
    )[0]
    assert row[:5] == ("complete", 10, 60, 5, 105)
    assert row[6] is True
    manifest = json.loads(row[5])
    assert set(manifest) == set(FILE_NAMES)
    for name, path in files.items():
        data = path.read_bytes()
        assert manifest[name] == {
            "path": str(path),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        }
    # The other unit and the run are untouched.
    assert rows(
        engine,
        "SELECT status, outputs FROM processing_units WHERE owner_code = 'RW0002'",
    ) == [("pending", None)]
    assert status_of(engine, run_id) == "staging"


def test_checkpoint_stores_a_relative_path_as_an_absolute_one(
    engine, session, tmp_path, monkeypatch
):
    run_id = begin(engine, ("RW0001",))
    write_unit_files(tmp_path, "RW0001")
    monkeypatch.chdir(tmp_path)

    checkpoint_unit(
        session, run_id, "RW0001", (0, 1, 0, 1), {"acc": Path("RW0001/acc.bin")}
    )

    manifest = json.loads(scalar(engine, "SELECT outputs::text FROM processing_units"))
    assert manifest["acc"]["path"] == str(tmp_path / "RW0001" / "acc.bin")


def test_checkpointing_a_complete_unit_again_replaces_bounds_and_manifest(
    engine, tmp_path
):
    run_id, files = stage(engine, tmp_path, codes=("RW0001", "RW0002"))
    others = rows(
        engine, "SELECT outputs::text FROM processing_units WHERE owner_code = 'RW0002'"
    )
    # The unit was computed anew: other bytes, another window, a smaller file set.
    fresh = write_unit_files(tmp_path / "again", "RW0001", filler=b"z")
    with Session(engine) as db:
        checkpoint_unit(db, run_id, "RW0001", (1, 2, 3, 4), {"acc": fresh["acc"]})

    row = rows(
        engine,
        "SELECT status, row_start, row_stop, col_start, col_stop, outputs::text "
        "FROM processing_units WHERE owner_code = 'RW0001'",
    )[0]
    assert row[:5] == ("complete", 1, 2, 3, 4)
    manifest = json.loads(row[5])
    assert set(manifest) == {"acc"}
    assert (
        manifest["acc"]["sha256"]
        == hashlib.sha256(fresh["acc"].read_bytes()).hexdigest()
    )
    assert (
        rows(
            engine,
            "SELECT outputs::text FROM processing_units WHERE owner_code = 'RW0002'",
        )
        == others
    )


def test_checkpoint_of_an_unknown_unit_or_run_writes_nothing(engine, session, tmp_path):
    run_id = begin(engine, ("RW0001",))
    files = write_unit_files(tmp_path, "RW0001")
    before = snapshot(engine)

    with pytest.raises(UnknownUnitError):
        checkpoint_unit(session, run_id, "NOPE", (0, 1, 0, 1), files)
    with pytest.raises(RunNotFoundError):
        checkpoint_unit(session, run_id + 1, "RW0001", (0, 1, 0, 1), files)

    assert snapshot(engine) == before


@pytest.mark.parametrize("final", ["failed", "published"])
def test_checkpoint_refuses_a_run_that_is_no_longer_staging(
    engine, session, tmp_path, final
):
    run_id, _ = stage(engine, tmp_path)
    if final == "failed":
        fail_run(session, run_id, "given up")
    else:
        segments, catchments = results_for(2, 700000)
        publish_run(session, run_id, segments, catchments)
    before = snapshot(engine)
    fresh = write_unit_files(tmp_path / "fresh", "RW0001", filler=b"q")

    with pytest.raises(RunStateError):
        checkpoint_unit(session, run_id, "RW0001", (7, 8, 7, 8), fresh)

    assert snapshot(engine) == before


def test_checkpoint_of_a_missing_file_writes_nothing(engine, session, tmp_path):
    run_id = begin(engine, ("RW0001",))
    files = write_unit_files(tmp_path, "RW0001")
    files["flow_dir"].unlink()
    before = snapshot(engine)

    with pytest.raises(FileNotFoundError):
        checkpoint_unit(session, run_id, "RW0001", (0, 1, 0, 1), files)
    with pytest.raises(FileNotFoundError):
        checkpoint_unit(
            session,
            run_id,
            "RW0001",
            (0, 1, 0, 1),
            {"acc": tmp_path},  # a directory
        )

    assert snapshot(engine) == before


@pytest.mark.parametrize(
    "bbox",
    [
        (5, 4, 0, 1),
        (0, 1, 3, 2),
        (-1, 1, 0, 1),
        (0, 1, -2, 1),
        (0, 1, 0),
        (0, 1, 0, 1, 2),
        (0.0, 1, 0, 1),
        (True, 1, 0, 1),
        None,
    ],
)
def test_checkpoint_rejects_an_invalid_bbox_and_writes_nothing(
    engine, session, tmp_path, bbox
):
    run_id = begin(engine, ("RW0001",))
    files = write_unit_files(tmp_path, "RW0001")
    before = snapshot(engine)

    with pytest.raises(ValueError):
        checkpoint_unit(session, run_id, "RW0001", bbox, files)

    assert snapshot(engine) == before


def test_checkpoint_rejects_empty_outputs_and_blank_names(engine, session, tmp_path):
    run_id = begin(engine, ("RW0001",))
    files = write_unit_files(tmp_path, "RW0001")
    with pytest.raises(ValueError):
        checkpoint_unit(session, run_id, "RW0001", (0, 1, 0, 1), {})
    with pytest.raises(ValueError):
        checkpoint_unit(session, run_id, "RW0001", (0, 1, 0, 1), {"": files["acc"]})
    with pytest.raises(ValueError):
        checkpoint_unit(session, run_id, " ", (0, 1, 0, 1), files)
    assert status_of(engine, run_id) == "staging"
    assert scalar(engine, "SELECT status FROM processing_units") == "pending"


# ---------------------------------------------------------------------------
# publish_run
# ---------------------------------------------------------------------------


def published_shape(engine):
    """Segment and catchment indexes of the DEM-derived network by threshold."""
    return {
        "streams": rows(
            engine,
            "SELECT threshold_m2, array_agg(segment_idx ORDER BY segment_idx) "
            "FROM stream_network WHERE source = 'DEM_DERIVED' "
            "GROUP BY threshold_m2 ORDER BY threshold_m2",
        ),
        "catchments": rows(
            engine,
            "SELECT threshold_m2, array_agg(segment_idx ORDER BY segment_idx) "
            "FROM stream_catchments GROUP BY threshold_m2 ORDER BY threshold_m2",
        ),
    }


def test_publish_replaces_the_previous_network_and_activates_the_run(
    engine, session, tmp_path
):
    seed_previous(engine)
    old_stream_ids = {r[0] for r in rows(engine, "SELECT id FROM stream_network")}
    old_catchment_ids = {r[0] for r in rows(engine, "SELECT id FROM stream_catchments")}
    bdot_before = rows(
        engine,
        "SELECT id, ST_AsEWKT(geom), threshold_m2, segment_idx FROM stream_network "
        "WHERE source = 'BDOT10K'",
    )
    run_id, _ = stage(engine, tmp_path)
    segments, catchments = results_for(4, 540000)

    result = publish_run(session, run_id, segments, catchments)

    assert result == {
        "units": 3,
        "stream_segments_deleted": 3,
        "catchments_deleted": 2,
        "stream_segments_inserted": 4 + 2,
        "catchments_inserted": 4 + 2,
    }
    assert published_shape(engine) == {
        "streams": [(1000, [1, 2, 3, 4]), (10000, [1, 2])],
        "catchments": [(1000, [1, 2, 3, 4]), (10000, [1, 2])],
    }
    assert not old_stream_ids & {
        r[0]
        for r in rows(
            engine, "SELECT id FROM stream_network WHERE source='DEM_DERIVED'"
        )
    }
    assert not old_catchment_ids & {
        r[0] for r in rows(engine, "SELECT id FROM stream_catchments")
    }
    # Rows of another source survive the replacement unchanged.
    assert (
        rows(
            engine,
            "SELECT id, ST_AsEWKT(geom), threshold_m2, segment_idx FROM stream_network "
            "WHERE source = 'BDOT10K'",
        )
        == bdot_before
    )
    run = rows(
        engine,
        "SELECT status, activated_at IS NOT NULL, superseded_at, published_counts "
        "FROM processing_runs WHERE id = :i",
        i=run_id,
    )
    assert run == [
        (
            "active",
            True,
            None,
            {
                "stream_segments": {"1000": 4, "10000": 2},
                "catchments": {"1000": 4, "10000": 2},
            },
        )
    ]


def test_publishing_a_second_run_supersedes_the_first(engine, session, tmp_path):
    first, _ = stage(engine, tmp_path, fingerprint="fp-first")
    publish_run(session, first, *results_for(5, 540000))
    second, _ = stage(engine, tmp_path, fingerprint="fp-second")

    result = publish_run(session, second, *results_for(3, 560000))

    assert result["stream_segments_deleted"] == 5 + 2
    assert result["catchments_deleted"] == 5 + 2
    assert published_shape(engine) == {
        "streams": [(1000, [1, 2, 3]), (10000, [1])],
        "catchments": [(1000, [1, 2, 3]), (10000, [1])],
    }
    assert rows(
        engine,
        "SELECT id, status, superseded_at IS NOT NULL, activated_at IS NOT NULL "
        "FROM processing_runs ORDER BY id",
    ) == [(first, "superseded", True, True), (second, "active", False, True)]
    assert (
        scalar(engine, "SELECT count(*) FROM processing_runs WHERE status='active'")
        == 1
    )


def test_publish_counts_only_the_segments_the_unique_index_keeps(
    engine, session, tmp_path
):
    seed_previous(engine)
    run_id, _ = stage(engine, tmp_path)
    twin = seg(500000, 500000)

    # Two segments of one threshold on the same line collide in `idx_stream_unique`;
    # without catchments the previous catchments are deleted and none are written.
    result = publish_run(session, run_id, {1000: [twin, dict(twin)]}, {})

    assert result["stream_segments_inserted"] == 1
    assert result["catchments_inserted"] == 0
    assert result["catchments_deleted"] == 2
    assert scalar(engine, "SELECT count(*) FROM stream_catchments") == 0
    assert scalar(engine, "SELECT published_counts FROM processing_runs")[
        "stream_segments"
    ] == {"1000": 1}


@pytest.mark.parametrize(
    "segments",
    [
        {},
        {1000: []},
        {1000: [], 10000: []},
        {0: [seg(1, 1)]},
        {-1000: [seg(1, 1)]},
        {True: [seg(1, 1)]},
        {1000.5: [seg(1, 1)]},
        {"1000": [seg(1, 1)]},
    ],
)
def test_publish_rejects_empty_results_and_bad_thresholds_keeping_everything(
    engine, session, tmp_path, segments
):
    seed_previous(engine)
    run_id, _ = stage(engine, tmp_path)
    before = snapshot(engine)

    with pytest.raises(ValueError):
        publish_run(session, run_id, segments, {1000: [shed(1, 1, 1)]})

    assert snapshot(engine) == before


def test_publish_reports_pending_units_sorted_before_checking_the_files(
    engine, session, tmp_path
):
    seed_previous(engine)
    run_id = begin(engine, ("C", "B", "A", "D"))
    done = write_unit_files(tmp_path, "C")
    with Session(engine) as db:
        checkpoint_unit(db, run_id, "C", (0, 1, 0, 1), done)
    other = write_unit_files(tmp_path, "D")
    with Session(engine) as db:
        checkpoint_unit(db, run_id, "D", (0, 1, 0, 1), other)
    other["acc"].unlink()  # a staged-file problem, but the pending units come first
    before = snapshot(engine)

    with pytest.raises(IncompleteRunError) as caught:
        publish_run(session, run_id, *results_for(2, 540000))

    assert caught.value.pending == ("A", "B")
    assert "A" in str(caught.value)
    assert snapshot(engine) == before


def test_publish_names_the_units_whose_staged_files_changed(engine, session, tmp_path):
    seed_previous(engine)
    run_id, files = stage(engine, tmp_path)
    files["RW0001"]["flow_dir"].unlink()  # disappeared
    changed = files["LW0003"]["acc"]
    changed.write_bytes(b"b" * changed.stat().st_size)  # same size, other content
    before = snapshot(engine)

    with pytest.raises(StagedOutputsError) as caught:
        publish_run(session, run_id, *results_for(2, 540000))

    assert caught.value.owner_codes == ("LW0003", "RW0001")
    assert len(caught.value.problems) == 2
    assert caught.value.problems[0].startswith("LW0003/acc: ")
    assert caught.value.problems[1].startswith("RW0001/flow_dir: ")
    assert "missing" in caught.value.problems[1]
    assert snapshot(engine) == before
    assert status_of(engine, run_id) == "staging"


def test_publish_detects_a_resized_file_and_succeeds_after_a_new_checkpoint(
    engine, session, tmp_path
):
    run_id, files = stage(engine, tmp_path)
    grown = files["RW0002"]["filled_dem"]
    grown.write_bytes(grown.read_bytes() + b"tail")

    with pytest.raises(StagedOutputsError) as caught:
        publish_run(session, run_id, *results_for(2, 540000))
    assert caught.value.owner_codes == ("RW0002",)

    # The unit is computed again and checkpointed: the run can be published.
    with Session(engine) as db:
        checkpoint_unit(db, run_id, "RW0002", (10, 60, 0, 100), files["RW0002"])
    publish_run(session, run_id, *results_for(2, 540000))
    assert status_of(engine, run_id) == "active"


def test_publish_refuses_a_run_that_is_unknown_failed_or_already_published(
    engine, session, tmp_path
):
    seed_previous(engine)
    published, _ = stage(engine, tmp_path, fingerprint="published")
    failed, _ = stage(engine, tmp_path, fingerprint="failed")
    publish_run(session, published, *results_for(2, 540000))
    fail_run(session, failed, "given up")
    before = snapshot(engine)

    with pytest.raises(RunNotFoundError):
        publish_run(session, failed + 100, *results_for(2, 560000))
    with pytest.raises(RunStateError, match="failed"):
        publish_run(session, failed, *results_for(2, 560000))
    with pytest.raises(RunStateError, match="active"):
        publish_run(session, published, *results_for(2, 560000))

    assert snapshot(engine) == before


def _boom_after_last_catchments(db, catchments, **kwargs):
    count = db_bulk.insert_catchments(db, catchments, **kwargs)
    if kwargs["threshold_m2"] == 10000:
        raise RuntimeError("boom after the last insert, before the activation")
    return count


def _failure_cases():
    segments, catchments = results_for(4, 540000)
    point = shed(1, 1, 1)
    point["wkt"] = "POINT(1 1)"
    no_area = dict(shed(1, 1, 1), area_km2="")
    return {
        "stream-not-a-linestring": (
            {**segments, 10000: [dict(seg(1, 1), coords=[(1, 1)])]},
            catchments,
            psycopg2.Error,
            None,
        ),
        "catchment-of-the-wrong-geometry-type": (
            segments,
            {**catchments, 10000: [point]},
            psycopg2.Error,
            None,
        ),
        "catchment-violating-a-not-null-column": (
            segments,
            {**catchments, 10000: [no_area]},
            psycopg2.errors.NotNullViolation,
            None,
        ),
        "failure-after-every-insert": (
            segments,
            catchments,
            RuntimeError,
            _boom_after_last_catchments,
        ),
    }


@pytest.mark.parametrize("case", list(_failure_cases()))
def test_a_failed_publication_leaves_rows_and_runs_untouched(
    engine, session, tmp_path, monkeypatch, case
):
    segments, catchments, error, hook = _failure_cases()[case]
    previous, _ = stage(engine, tmp_path, fingerprint="previous")
    publish_run(session, previous, *results_for(2, 700000))
    seed_previous(engine)  # rows of the previous publication plus another source
    run_id, _ = stage(engine, tmp_path, fingerprint="next")
    before = snapshot(engine)
    timeout_before = session.execute(text("SHOW statement_timeout")).scalar()
    if hook is not None:
        monkeypatch.setattr(unit_run_store, "insert_catchments", hook)

    with pytest.raises(error):
        publish_run(session, run_id, segments, catchments)

    assert snapshot(engine) == before
    assert status_of(engine, run_id) == "staging"
    assert status_of(engine, previous) == "active"
    # The session is usable again and the publication's SET LOCAL did not leak.
    assert session.execute(text("SHOW statement_timeout")).scalar() == timeout_before
    monkeypatch.undo()
    publish_run(session, run_id, *results_for(3, 560000))
    assert status_of(engine, run_id) == "active"
    assert status_of(engine, previous) == "superseded"


def test_readers_see_the_previous_rows_until_the_commit(
    engine, session, tmp_path, monkeypatch
):
    seed_previous(engine)
    run_id, _ = stage(engine, tmp_path)
    old = snapshot(engine)
    seen = {}

    def peek(db, catchments, **kwargs):
        count = db_bulk.insert_catchments(db, catchments, **kwargs)
        if kwargs["threshold_m2"] == 10000:
            # Inside the publication: everything is written, nothing committed. A
            # reader on another connection is not blocked and sees the old state.
            seen["state"] = snapshot(engine)
            seen["in_transaction"] = db.execute(
                text("SELECT count(*) FROM stream_catchments")
            ).scalar()
        return count

    monkeypatch.setattr(unit_run_store, "insert_catchments", peek)
    publish_run(session, run_id, *results_for(4, 540000))

    assert seen["state"] == old
    assert seen["in_transaction"] == 4 + 2
    assert snapshot(engine) != old
    assert scalar(engine, "SELECT count(*) FROM stream_catchments") == 4 + 2


def test_two_concurrent_publications_serialise_and_leave_one_active_run(
    engine, tmp_path, monkeypatch
):
    seed_previous(engine)
    run_a, _ = stage(engine, tmp_path, fingerprint="a")
    run_b, _ = stage(engine, tmp_path, fingerprint="b")
    inside_a = threading.Event()
    release_a = threading.Event()
    outcome = {}

    def hooked(db, catchments, **kwargs):
        count = db_bulk.insert_catchments(db, catchments, **kwargs)
        if threading.current_thread().name == "A" and kwargs["threshold_m2"] == 10000:
            inside_a.set()
            if not release_a.wait(30):
                raise RuntimeError("publication A was never released")
        return count

    def publish(name, run_id, results):
        try:
            with Session(engine) as db:
                outcome[name] = publish_run(db, run_id, *results)
        except BaseException as error:  # noqa: BLE001 - reported by the test
            outcome[name] = error

    monkeypatch.setattr(unit_run_store, "insert_catchments", hooked)
    thread_a = threading.Thread(
        target=publish, args=("A", run_a, results_for(5, 600000)), name="A"
    )
    thread_b = threading.Thread(
        target=publish, args=("B", run_b, results_for(3, 620000)), name="B"
    )
    waiting_sql = (
        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
        "AND wait_event_type = 'Lock' AND query ILIKE 'LOCK TABLE%'"
    )
    try:
        thread_a.start()
        assert inside_a.wait(30)
        thread_b.start()
        deadline = time.monotonic() + 30
        while scalar(engine, waiting_sql) != 1 and time.monotonic() < deadline:
            time.sleep(0.05)
        # B waits at the table lock while A is mid-publication.
        assert scalar(engine, waiting_sql) == 1
        assert "B" not in outcome
    finally:
        release_a.set()
        thread_a.join(60)
        thread_b.join(60)

    assert isinstance(outcome["A"], dict), outcome
    assert isinstance(outcome["B"], dict), outcome
    # B ran after A: it deleted exactly A's rows, so no row of A is left mixed in.
    assert (
        outcome["B"]["stream_segments_deleted"]
        == outcome["A"]["stream_segments_inserted"]
    )
    assert outcome["B"]["catchments_deleted"] == outcome["A"]["catchments_inserted"]
    assert published_shape(engine) == {
        "streams": [(1000, [1, 2, 3]), (10000, [1])],
        "catchments": [(1000, [1, 2, 3]), (10000, [1])],
    }
    assert rows(engine, "SELECT id, status FROM processing_runs ORDER BY id") == [
        (run_a, "superseded"),
        (run_b, "active"),
    ]


# ---------------------------------------------------------------------------
# fail_run
# ---------------------------------------------------------------------------


def test_fail_run_records_the_reason_and_blocks_publication_and_checkpoints(
    engine, session, tmp_path
):
    seed_previous(engine)
    run_id, files = stage(engine, tmp_path)
    before_streams = snapshot(engine)["streams"]

    fail_run(session, run_id, "unit RW0002 ran out of memory")

    assert rows(
        engine,
        "SELECT status, error, failed_at IS NOT NULL, activated_at "
        "FROM processing_runs WHERE id = :i",
        i=run_id,
    ) == [("failed", "unit RW0002 ran out of memory", True, None)]
    assert snapshot(engine)["streams"] == before_streams
    state = snapshot(engine)
    with pytest.raises(RunStateError, match="failed"):
        publish_run(session, run_id, *results_for(2, 540000))
    with pytest.raises(RunStateError):
        checkpoint_unit(session, run_id, "RW0001", (0, 1, 0, 1), files["RW0001"])
    assert snapshot(engine) == state


def test_failing_a_run_twice_keeps_the_first_reason(engine, session):
    run_id = begin(engine, ("A",))
    fail_run(session, run_id, "first reason")
    first = rows(engine, "SELECT failed_at, error FROM processing_runs")

    fail_run(session, run_id, "second reason")

    assert rows(engine, "SELECT failed_at, error FROM processing_runs") == first
    assert first[0][1] == "first reason"


def test_failing_a_run_leaves_the_active_run_alone(engine, session, tmp_path):
    active, _ = stage(engine, tmp_path, fingerprint="active")
    publish_run(session, active, *results_for(2, 540000))
    staging = begin(engine, ("A",), "staging")
    published = snapshot(engine)

    fail_run(session, staging, "abandoned")

    after = snapshot(engine)
    assert after["streams"] == published["streams"]
    assert after["catchments"] == published["catchments"]
    assert status_of(engine, active) == "active"
    assert status_of(engine, staging) == "failed"


@pytest.mark.parametrize("final", ["active", "superseded"])
def test_fail_run_refuses_a_published_run(engine, session, tmp_path, final):
    first, _ = stage(engine, tmp_path, fingerprint="first")
    publish_run(session, first, *results_for(2, 540000))
    if final == "superseded":
        second, _ = stage(engine, tmp_path, fingerprint="second")
        publish_run(session, second, *results_for(2, 560000))
    before = snapshot(engine)

    with pytest.raises(RunStateError, match=final):
        fail_run(session, first, "too late")

    assert snapshot(engine) == before


def test_fail_run_rejects_a_blank_reason_and_an_unknown_run(engine, session):
    run_id = begin(engine, ("A",))
    for reason in ("", "   ", None):
        with pytest.raises(ValueError):
            fail_run(session, run_id, reason)
    with pytest.raises(RunNotFoundError):
        fail_run(session, run_id + 1, "reason")
    assert rows(engine, "SELECT status, error FROM processing_runs") == [
        ("staging", None)
    ]


# ---------------------------------------------------------------------------
# core.db_bulk: commit=False and local=True
# ---------------------------------------------------------------------------


def _timeout(db):
    return db.execute(text("SHOW statement_timeout")).scalar()


def test_bulk_inserts_without_commit_belong_to_the_callers_transaction(engine, session):
    original = _timeout(session)
    session.rollback()

    streams = db_bulk.insert_stream_segments(
        session, [seg(710000, 500000)], threshold_m2=1000, commit=False
    )
    sheds = db_bulk.insert_catchments(
        session, [shed(1, 710000, 510000)], threshold_m2=1000, commit=False
    )

    assert (streams, sheds) == (1, 1)
    assert session.execute(text("SELECT count(*) FROM stream_network")).scalar() == 1
    assert session.execute(text("SELECT count(*) FROM stream_catchments")).scalar() == 1
    # Not committed: another connection sees nothing.
    assert scalar(engine, "SELECT count(*) FROM stream_network") == 0
    assert scalar(engine, "SELECT count(*) FROM stream_catchments") == 0
    # The insert's own timeout is restored inside the transaction.
    assert _timeout(session) == original

    session.rollback()

    assert scalar(engine, "SELECT count(*) FROM stream_network") == 0
    assert scalar(engine, "SELECT count(*) FROM stream_catchments") == 0
    assert _timeout(session) == original


def test_bulk_inserts_without_commit_are_durable_once_the_caller_commits(
    engine, session
):
    original = _timeout(session)
    session.rollback()
    db_bulk.insert_stream_segments(
        session, [seg(710000, 500000)], threshold_m2=1000, commit=False
    )
    session.commit()

    assert scalar(engine, "SELECT count(*) FROM stream_network") == 1
    assert _timeout(session) == original


def test_bulk_inserts_commit_by_default_and_restore_the_session_timeout(
    engine, session
):
    original = _timeout(session)
    session.rollback()

    db_bulk.insert_stream_segments(session, [seg(710000, 500000)], threshold_m2=1000)
    db_bulk.insert_catchments(session, [shed(1, 710000, 510000)], threshold_m2=1000)

    assert scalar(engine, "SELECT count(*) FROM stream_network") == 1
    assert scalar(engine, "SELECT count(*) FROM stream_catchments") == 1
    assert _timeout(session) == original


@pytest.mark.parametrize("end", ["commit", "rollback"])
def test_local_timeout_override_never_outlives_the_transaction(engine, session, end):
    original = _timeout(session)
    session.rollback()

    with db_bulk.override_statement_timeout(session, timeout_s=77, local=True):
        inside = _timeout(session)
        assert scalar(engine, "SHOW statement_timeout") == original
    after_block = _timeout(session)
    getattr(session, end)()

    assert inside == "77s"
    assert after_block == original
    assert _timeout(session) == original


def test_session_override_applies_to_the_session_and_is_restored(engine, session):
    original = _timeout(session)
    session.rollback()

    with db_bulk.override_statement_timeout(session, timeout_s=77):
        inside = _timeout(session)

    assert inside == "77s"
    assert _timeout(session) == original
    session.rollback()
    assert _timeout(session) == original


def test_bulk_failure_without_commit_rolls_back_with_the_callers_transaction(
    engine, session
):
    original = _timeout(session)
    session.rollback()
    good = [seg(710000, 500000)]
    db_bulk.insert_stream_segments(session, good, threshold_m2=1000, commit=False)

    with pytest.raises(psycopg2.Error):
        db_bulk.insert_catchments(
            session,
            [dict(shed(1, 1, 1), wkt="POINT(1 1)")],
            threshold_m2=1000,
            commit=False,
        )
    session.rollback()

    assert scalar(engine, "SELECT count(*) FROM stream_network") == 0
    assert _timeout(session) == original
