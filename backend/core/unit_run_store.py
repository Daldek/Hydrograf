"""Run records of the PGW unit bootstrap: checkpoint per unit, publish all or nothing.

A run of ``process_dem --units`` leaves two kinds of rows (migration 005):

* ``processing_runs``: the immutable input fingerprint and configuration, the status
  (``staging``, then ``active`` and later ``superseded``, or ``failed``) and, through
  its partial unique index, the one ``active`` run whose results ``stream_network``
  and ``stream_catchments`` hold now.
* ``processing_units``: one row per PGW owner of the run, keyed by
  ``(run_id, owner_code)``: ``pending`` until the unit's owned-cell rasters are
  final, then ``complete`` with the unit's bounds on the shared grid and the manifest
  of those files (path, size, SHA-256).

Every public function takes a ``Session`` and ends its transaction: it commits when it
succeeds and rolls back when it raises, so a script may open a ``get_db_session()`` per
operation. Only :func:`publish_run` touches the published tables. It replaces the
DEM-derived streams and all sub-catchments and marks the run active in ONE
transaction: a failure anywhere leaves the previous rows and the previous active run
as they were.
"""

import hashlib
import json
import logging
import numbers
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult, Result
from sqlalchemy.orm import Session

from core.db_bulk import (
    insert_catchments,
    insert_stream_segments,
    override_statement_timeout,
)

logger = logging.getLogger(__name__)

__all__ = [
    "IncompleteRunError",
    "RunNotFoundError",
    "RunStateError",
    "StagedOutputsError",
    "UnitRunError",
    "UnknownUnitError",
    "begin_run",
    "checkpoint_unit",
    "fail_run",
    "publish_run",
]

# statement_timeout [s] of the publication transaction: the deletes of the previous
# network can outlast the 120 s default. Each bulk insert sets its own 600 s.
_PUBLISH_TIMEOUT_S = 3600

_SELECT_RUN_STATUS_SHARED = (
    "SELECT status FROM processing_runs WHERE id = :run_id FOR SHARE"
)
_SELECT_RUN_STATUS_EXCLUSIVE = (
    "SELECT status FROM processing_runs WHERE id = :run_id FOR UPDATE"
)

# (owner_code, status, manifest) of a unit; the manifest is None until the checkpoint.
_Unit = tuple[str, str, dict[str, dict[str, Any]] | None]


class UnitRunError(Exception):
    """Base of the errors of the run store."""


class RunNotFoundError(UnitRunError):
    """The run id is not in ``processing_runs``."""


class UnknownUnitError(UnitRunError):
    """The owner code is not a unit of the run."""


class RunStateError(UnitRunError):
    """The status of the run does not allow the operation."""


class IncompleteRunError(RunStateError):
    """A run with units that are not complete cannot be published.

    Attributes
    ----------
    pending : tuple[str, ...]
        Owner codes of the units that are not complete, sorted.
    """

    def __init__(self, message: str, pending: tuple[str, ...]) -> None:
        super().__init__(message)
        self.pending = pending


class StagedOutputsError(RunStateError):
    """A staged file is missing or no longer matches its unit's checkpoint.

    Attributes
    ----------
    owner_codes : tuple[str, ...]
        Owner codes of the units with at least one such file, sorted: the units to
        compute again.
    problems : tuple[str, ...]
        One line per file: ``<owner_code>/<name>: <what is wrong>``.
    """

    def __init__(
        self, message: str, owner_codes: tuple[str, ...], problems: tuple[str, ...]
    ) -> None:
        super().__init__(message)
        self.owner_codes = owner_codes
        self.problems = problems


def begin_run(
    db: Session,
    *,
    input_fingerprint: str,
    source_raster: str,
    pgw_path: str,
    config: dict[str, Any],
    owner_codes: tuple[str, ...],
) -> int:
    """Record a new run in staging with one pending unit per PGW owner.

    The published tables are not touched. The fingerprint, the paths and the
    configuration are never changed after this call.

    Parameters
    ----------
    db : Session
        Database session; its transaction is committed.
    input_fingerprint : str
        Identity of everything the results depend on (the DEM, the PGW file and
        the parameters), as the caller computes it.
    source_raster : str
        Path of the input DEM (or VRT) the run processes.
    pgw_path : str
        Path of the PGW GeoPackage that gives the owners.
    config : dict
        JSON-compatible parameters of the run (thresholds, halo, window limit,
        grid, ...). ``os.PathLike`` values are stored as their path.
    owner_codes : tuple[str, ...]
        Permanent codes of the owners (units) of the run; unique and not empty.

    Returns
    -------
    int
        Id of the run, for the other functions of this module.

    Raises
    ------
    ValueError
        An argument is empty, duplicated or not JSON-compatible; nothing is written.
    """
    fingerprint = _require_text(input_fingerprint, "input_fingerprint")
    source = _require_path_text(source_raster, "source_raster")
    pgw = _require_path_text(pgw_path, "pgw_path")
    config_json = _config_json(config)
    codes = _owner_code_list(owner_codes)
    with _transaction(db):
        run_id = int(
            db.execute(
                text("""
                    INSERT INTO processing_runs
                        (input_fingerprint, source_raster, pgw_path, config)
                    VALUES (:fingerprint, :source, :pgw, CAST(:config AS jsonb))
                    RETURNING id
                """),
                {
                    "fingerprint": fingerprint,
                    "source": source,
                    "pgw": pgw,
                    "config": config_json,
                },
            ).scalar_one()
        )
        db.execute(
            text(
                "INSERT INTO processing_units (run_id, owner_code) "
                "VALUES (:run_id, :owner_code)"
            ),
            [{"run_id": run_id, "owner_code": code} for code in codes],
        )
    logger.info(f"Run {run_id} staged with {len(codes)} pending units")
    return run_id


def checkpoint_unit(
    db: Session,
    run_id: int,
    owner_code: str,
    bbox: tuple[int, int, int, int],
    outputs: dict[str, Path],
) -> None:
    """Mark a unit complete and record the SHA-256 of its final files.

    Call it once the unit's files are in their final place. The files are hashed
    first, then the unit row is written in one short transaction. A unit that is
    already complete is checkpointed again (a stale unit that was computed anew);
    :func:`publish_run` checks the recorded checksums once more.

    Parameters
    ----------
    db : Session
        Database session; its transaction is committed.
    run_id : int
        Run from :func:`begin_run`; it must be in staging.
    owner_code : str
        Owner of the unit; it must be one of the run's ``owner_codes``.
    bbox : tuple[int, int, int, int]
        Bounds of the unit's owned cells on the shared grid as half-open cell
        indexes ``(row_start, row_stop, col_start, col_stop)``;
        ``0 <= start <= stop`` on both axes.
    outputs : dict[str, Path]
        The unit's final files by name (``filled_dem``, ``flow_dir``, ...); at least
        one. A relative path is stored as an absolute one.

    Raises
    ------
    ValueError
        ``bbox``, ``owner_code`` or the names of ``outputs`` are invalid.
    FileNotFoundError
        An output is not an existing file; nothing is written.
    RunNotFoundError
        The run does not exist.
    RunStateError
        The run is not in staging (it was published or failed).
    UnknownUnitError
        The owner is not a unit of the run.
    """
    run = _require_run_id(run_id)
    code = _require_text(owner_code, "owner_code")
    row_start, row_stop, col_start, col_stop = _bbox_bounds(bbox)
    manifest = _manifest(outputs)
    with _transaction(db):
        _require_staging(run, _lock_run(db, run, exclusive=False), "checkpointed")
        updated = db.execute(
            text("""
                UPDATE processing_units
                SET status = 'complete',
                    row_start = :row_start, row_stop = :row_stop,
                    col_start = :col_start, col_stop = :col_stop,
                    outputs = CAST(:outputs AS jsonb),
                    completed_at = now()
                WHERE run_id = :run_id AND owner_code = :owner_code
                RETURNING owner_code
            """),
            {
                "run_id": run,
                "owner_code": code,
                "row_start": row_start,
                "row_stop": row_stop,
                "col_start": col_start,
                "col_stop": col_stop,
                "outputs": json.dumps(manifest, sort_keys=True),
            },
        ).first()
        if updated is None:
            raise UnknownUnitError(f"run {run} has no unit {code!r}")
    logger.info(f"Run {run}: unit {code} complete ({len(manifest)} files)")


def publish_run(
    db: Session,
    run_id: int,
    segments: dict[int, list[dict[str, Any]]],
    catchments: dict[int, list[dict[str, Any]]],
) -> dict[str, int]:
    """Replace the DEM-derived network with the run's results and activate the run.

    In ONE transaction: the run's state and staged files are checked, the
    DEM-derived ``stream_network`` rows and all ``stream_catchments`` rows (the
    semantics of ``process_dem --clear-existing``) are deleted, the global results of
    each threshold are inserted, the active run becomes ``superseded`` and this run
    becomes ``active``. Any error rolls everything back: the previous rows and the
    previous active run stay as they were, and the run stays in staging. Readers see
    the previous rows until the commit. A concurrent publication waits for this one.

    Parameters
    ----------
    db : Session
        Database session; its transaction is committed.
    run_id : int
        Run from :func:`begin_run`; it must be in staging with every unit complete.
    segments : dict[int, list[dict]]
        Segment dicts of ``vectorize_streams`` by threshold [m²]. The ``segment_idx``
        of a row is its 1-based position in the list, as in
        :func:`core.db_bulk.insert_stream_segments`; at least one segment overall.
    catchments : dict[int, list[dict]]
        Sub-catchment dicts of ``polygonize_subcatchments`` by threshold [m²]; their
        ``segment_idx`` and ``downstream_segment_idx`` use the numbering of
        ``segments``.

    Returns
    -------
    dict[str, int]
        ``units`` of the run; ``stream_segments_deleted`` and ``catchments_deleted``,
        the rows of the previous publication that were removed;
        ``stream_segments_inserted`` and ``catchments_inserted``, the rows written
        (a segment dropped by the unique index of ``stream_network`` is not counted).

    Raises
    ------
    ValueError
        ``segments`` holds no segment, or a threshold is not a positive integer;
        nothing is read from the database.
    RunNotFoundError
        The run does not exist.
    RunStateError
        The run is not in staging.
    IncompleteRunError
        A unit is not complete.
    StagedOutputsError
        A recorded file is missing, or its size or SHA-256 changed.
    """
    run = _require_run_id(run_id)
    streams = _results_by_threshold(segments, "segments")
    sheds = _results_by_threshold(catchments, "catchments")
    if not any(streams.values()):
        raise ValueError(
            "segments hold no stream segment: publishing would only erase the "
            "published network"
        )
    with (
        _transaction(db),
        override_statement_timeout(db, timeout_s=_PUBLISH_TIMEOUT_S, local=True),
    ):
        _require_staging(run, _lock_run(db, run, exclusive=True), "published")
        units = _load_units(db, run)
        pending = tuple(code for code, state, _ in units if state != "complete")
        if pending:
            raise IncompleteRunError(
                f"run {run} has {len(pending)} units that are not complete: "
                + ", ".join(pending),
                pending,
            )
        _verify_outputs(run, units)

        # Writers of the two tables (a second publication) wait here; readers do not.
        db.execute(
            text(
                "LOCK TABLE stream_network, stream_catchments "
                "IN SHARE ROW EXCLUSIVE MODE"
            )
        )
        deleted_segments = _rowcount(
            db.execute(text("DELETE FROM stream_network WHERE source = 'DEM_DERIVED'"))
        )
        deleted_catchments = _rowcount(
            db.execute(text("DELETE FROM stream_catchments"))
        )
        inserted_segments = {
            threshold: insert_stream_segments(
                db, rows, threshold_m2=threshold, commit=False
            )
            for threshold, rows in streams.items()
        }
        inserted_catchments = {
            threshold: insert_catchments(db, rows, threshold_m2=threshold, commit=False)
            for threshold, rows in sheds.items()
        }
        db.execute(
            text(
                "UPDATE processing_runs SET status = 'superseded', "
                "superseded_at = now() WHERE status = 'active'"
            )
        )
        db.execute(
            text("""
                UPDATE processing_runs
                SET status = 'active', activated_at = now(),
                    published_counts = CAST(:counts AS jsonb)
                WHERE id = :run_id
            """),
            {
                "run_id": run,
                "counts": json.dumps(
                    {
                        "stream_segments": inserted_segments,
                        "catchments": inserted_catchments,
                    },
                    sort_keys=True,
                ),
            },
        )
    result = {
        "units": len(units),
        "stream_segments_deleted": deleted_segments,
        "catchments_deleted": deleted_catchments,
        "stream_segments_inserted": sum(inserted_segments.values()),
        "catchments_inserted": sum(inserted_catchments.values()),
    }
    logger.info(f"Run {run} published: {result}")
    return result


def fail_run(db: Session, run_id: int, error: str) -> None:
    """Mark a staging run failed with the reason; it can no longer be published.

    The published tables and the active run are not touched. A run that already
    failed keeps its first reason (the call changes nothing).

    Parameters
    ----------
    db : Session
        Database session; its transaction is committed.
    run_id : int
        Run from :func:`begin_run`.
    error : str
        Why the run was given up; not empty.

    Raises
    ------
    ValueError
        ``error`` is empty.
    RunNotFoundError
        The run does not exist.
    RunStateError
        The run was published (``active`` or ``superseded``).
    """
    run = _require_run_id(run_id)
    reason = _require_text(error, "error")
    with _transaction(db):
        status = _lock_run(db, run, exclusive=True)
        if status == "failed":
            return
        _require_staging(run, status, "failed")
        db.execute(
            text("""
                UPDATE processing_runs
                SET status = 'failed', failed_at = now(), error = :error
                WHERE id = :run_id
            """),
            {"run_id": run, "error": reason},
        )
    logger.warning(f"Run {run} failed: {reason}")


@contextmanager
def _transaction(db: Session) -> Iterator[None]:
    """End the session's transaction: commit when the block succeeds, else roll back."""
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def _lock_run(db: Session, run_id: int, *, exclusive: bool) -> str:
    """Lock the run's row until the end of the transaction and return its status."""
    row = db.execute(
        text(_SELECT_RUN_STATUS_EXCLUSIVE if exclusive else _SELECT_RUN_STATUS_SHARED),
        {"run_id": run_id},
    ).first()
    if row is None:
        raise RunNotFoundError(f"run {run_id} does not exist")
    return str(row.status)


def _require_staging(run_id: int, status: str, action: str) -> None:
    """Raise ``RunStateError`` unless the run is still in staging."""
    if status != "staging":
        raise RunStateError(
            f"run {run_id} is {status}: only a staging run can be {action}"
        )


def _load_units(db: Session, run_id: int) -> list[_Unit]:
    """Return ``(owner_code, status, manifest)`` of every unit of the run, sorted."""
    rows = db.execute(
        text("""
            SELECT owner_code, status, outputs::text AS outputs
            FROM processing_units
            WHERE run_id = :run_id
        """),
        {"run_id": run_id},
    ).all()
    units: list[_Unit] = [
        (row.owner_code, row.status, json.loads(row.outputs) if row.outputs else None)
        for row in rows
    ]
    return sorted(units, key=lambda unit: unit[0])


def _verify_outputs(run_id: int, units: Sequence[_Unit]) -> None:
    """Raise ``StagedOutputsError`` if a recorded file differs from its checkpoint."""
    problems: list[str] = []
    owners: set[str] = set()
    for owner_code, _, manifest in units:
        for name, entry in sorted((manifest or {}).items()):
            problem = _file_problem(entry)
            if problem is not None:
                problems.append(f"{owner_code}/{name}: {problem}")
                owners.add(owner_code)
    if problems:
        shown = "; ".join(problems[:5])
        more = f"; and {len(problems) - 5} more" if len(problems) > 5 else ""
        raise StagedOutputsError(
            f"run {run_id} cannot be published: {len(problems)} staged files differ "
            f"from their checkpoint: {shown}{more}",
            tuple(sorted(owners)),
            tuple(problems),
        )


def _file_problem(entry: Any) -> str | None:
    """Return the problem of a manifest entry's file, or ``None`` when it is intact."""
    if not isinstance(entry, dict):
        return "the manifest entry is malformed"
    path, digest, size = entry.get("path"), entry.get("sha256"), entry.get("size_bytes")
    if not isinstance(path, str) or not isinstance(digest, str):
        return "the manifest entry is malformed"
    try:
        actual_size = os.stat(path).st_size
        if actual_size != size:
            return f"size {actual_size} differs from the recorded {size} ({path})"
        if _sha256(path)[0] != digest:
            return f"SHA-256 differs from the recorded one ({path})"
    except FileNotFoundError:
        return f"file is missing ({path})"
    except OSError as error:
        return f"file cannot be read: {error.strerror} ({path})"
    return None


def _sha256(path: str) -> tuple[str, int]:
    """Return the SHA-256 (hex) and the size of a file, read in chunks."""
    with open(path, "rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return digest, os.fstat(stream.fileno()).st_size


def _manifest(outputs: dict[str, Path]) -> dict[str, dict[str, Any]]:
    """Hash the unit's final files into ``{name: {path, sha256, size_bytes}}``."""
    if not isinstance(outputs, Mapping) or not outputs:
        raise ValueError("outputs must name at least one file")
    manifest: dict[str, dict[str, Any]] = {}
    for name, path in outputs.items():
        if not isinstance(name, str) or not name:
            raise ValueError(f"output names must be non-empty strings, got {name!r}")
        absolute = os.path.abspath(os.fspath(path))
        if not os.path.isfile(absolute):
            raise FileNotFoundError(
                f"output {name!r} is not an existing file: {absolute}"
            )
        digest, size = _sha256(absolute)
        manifest[name] = {"path": absolute, "sha256": digest, "size_bytes": size}
    return manifest


def _rowcount(result: Result[Any]) -> int:
    """Return the number of rows a DELETE removed."""
    return int(cast("CursorResult[Any]", result).rowcount)


def _results_by_threshold(
    results: Mapping[int, list[dict[str, Any]]], name: str
) -> dict[int, list[dict[str, Any]]]:
    """Return the results ordered by threshold, each a positive integer of m²."""
    ordered: dict[int, list[dict[str, Any]]] = {}
    for key, rows in results.items():
        if not isinstance(key, numbers.Integral) or isinstance(key, bool) or key <= 0:
            raise ValueError(
                f"{name}: thresholds must be positive integers, got {key!r}"
            )
        ordered[int(key)] = rows
    return dict(sorted(ordered.items()))


def _require_run_id(run_id: int) -> int:
    """Return ``run_id`` as a plain ``int``."""
    if not isinstance(run_id, numbers.Integral) or isinstance(run_id, bool):
        raise ValueError(f"run_id must be an integer, got {run_id!r}")
    return int(run_id)


def _require_text(value: object, name: str) -> str:
    """Return ``value`` if it is a string with a visible character."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")
    return value


def _require_path_text(value: object, name: str) -> str:
    """Return a path (``str`` or ``os.PathLike``) as a non-empty string."""
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    return _require_text(value, name)


def _owner_code_list(owner_codes: Sequence[str]) -> list[str]:
    """Return the owner codes of a run: a non-empty, duplicate-free list of strings."""
    if isinstance(owner_codes, str):
        raise ValueError("owner_codes must be a sequence of codes, not one string")
    codes = [_require_text(code, "owner code") for code in owner_codes]
    if not codes:
        raise ValueError("owner_codes must hold at least one owner")
    duplicates = sorted({code for code in codes if codes.count(code) > 1})
    if duplicates:
        raise ValueError(f"owner_codes repeat: {', '.join(duplicates)}")
    return codes


def _bbox_bounds(bbox: Sequence[int]) -> tuple[int, int, int, int]:
    """Return ``(row_start, row_stop, col_start, col_stop)`` after checking them."""
    message = (
        "bbox must be four integers (row_start, row_stop, col_start, col_stop) "
        f"with 0 <= start <= stop on both axes, got {bbox!r}"
    )
    try:
        values = tuple(bbox)
    except TypeError:
        raise ValueError(message) from None
    if len(values) != 4 or not all(
        isinstance(v, numbers.Integral) and not isinstance(v, bool) for v in values
    ):
        raise ValueError(message)
    row_start, row_stop, col_start, col_stop = (int(v) for v in values)
    if not (0 <= row_start <= row_stop and 0 <= col_start <= col_stop):
        raise ValueError(message)
    return row_start, row_stop, col_start, col_stop


def _config_json(config: dict[str, Any]) -> str:
    """Return the run configuration as canonical JSON text."""
    if not isinstance(config, Mapping):
        raise ValueError(f"config must be a dict, got {type(config).__name__}")

    def encode(value: Any) -> Any:
        if isinstance(value, os.PathLike):
            return os.fspath(value)
        raise TypeError(f"config value of type {type(value).__name__} is not JSON")

    try:
        return json.dumps(config, sort_keys=True, allow_nan=False, default=encode)
    except (TypeError, ValueError) as error:
        raise ValueError(f"config is not JSON-compatible: {error}") from error
