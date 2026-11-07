"""The pointer file to the active run by PGW units (ADR-071).

A published run of ``process_dem --units`` leaves its rasters as VRT mosaics in
``<output_dir>/unit_runs/<run token>/``. The file ``<output_dir>/active_run.json``
points at the run whose network the database holds::

    {"run_id": 12, "run_dir": "unit_runs/<run token>"}

``run_dir`` is relative to the directory of the pointer, so a container that mounts
that directory elsewhere (the API sees it as ``DEM_DIR``) resolves it the same way. The
pointer is a plain file, not a symbolic link, because the CIFS share of the data refuses
links; it is replaced in one atomic rename. A run of the whole raster removes it.

The module has no heavy imports: ``core.config`` imports it.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

logger = logging.getLogger(__name__)

ACTIVE_RUN_FILE = "active_run.json"

__all__ = [
    "ACTIVE_RUN_FILE",
    "ActiveRun",
    "active_run_raster",
    "clear_active_run",
    "read_active_run",
    "write_active_run",
]


@dataclass(frozen=True)
class ActiveRun:
    """The run that a pointer file names.

    Attributes
    ----------
    run_id : int
        ``processing_runs.id`` of the run.
    run_dir : Path
        Directory of the run's rasters (absolute, inside the pointer's directory).
    """

    run_id: int
    run_dir: Path


def read_active_run(directory: str | os.PathLike[str]) -> ActiveRun | None:
    """Return the active run of ``directory``, or None when it has none.

    A pointer that is not a JSON object with an integer ``run_id`` and a relative
    ``run_dir`` inside ``directory`` (no ``..``), or whose run directory does not exist,
    is logged as a warning and counts as no active run.

    Parameters
    ----------
    directory : str or PathLike
        Directory of the pointer file (the output directory of the runs, DEM_DIR).

    Returns
    -------
    ActiveRun or None
        The run, or None without a valid pointer.
    """
    base = Path(directory)
    pointer = base / ACTIVE_RUN_FILE
    try:
        text = pointer.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as error:
        logger.warning("Active run pointer %s cannot be read: %s", pointer, error)
        return None
    try:
        content = json.loads(text)
    except ValueError as error:
        logger.warning("Active run pointer %s is not JSON: %s", pointer, error)
        return None
    if not isinstance(content, dict):
        logger.warning("Active run pointer %s is not a JSON object", pointer)
        return None
    run_id = content.get("run_id")
    relative = content.get("run_dir")
    if not isinstance(run_id, int) or isinstance(run_id, bool):
        logger.warning("Active run pointer %s has no integer run_id", pointer)
        return None
    if not isinstance(relative, str) or not _is_plain_relative(relative):
        logger.warning(
            "Active run pointer %s has no relative run_dir inside %s: %r",
            pointer,
            base,
            relative,
        )
        return None
    run_dir = base / relative
    try:
        inside = run_dir.resolve().is_relative_to(base.resolve())
    except OSError:
        inside = False
    if not inside:
        logger.warning(
            "Active run pointer %s leads outside %s: %s", pointer, base, relative
        )
        return None
    if not run_dir.is_dir():
        logger.warning(
            "Active run pointer %s names a missing run directory %s", pointer, run_dir
        )
        return None
    return ActiveRun(run_id=run_id, run_dir=run_dir)


def active_run_raster(directory: str | os.PathLike[str], raster: str) -> Path | None:
    """Return the VRT mosaic ``dem_mosaic_<raster>.vrt`` of the active run, or None.

    Parameters
    ----------
    directory : str or PathLike
        Directory of the pointer file.
    raster : str
        Name of the raster after the stem, e.g. ``01_dem`` or ``10_subcatchments_5000``.

    Returns
    -------
    Path or None
        The mosaic, or None without a valid pointer or when the run has no such file.
    """
    run = read_active_run(directory)
    if run is None:
        return None
    mosaic = run.run_dir / f"dem_mosaic_{raster}.vrt"
    return mosaic if mosaic.is_file() else None


def write_active_run(
    directory: str | os.PathLike[str], run_id: int, run_dir: str | os.PathLike[str]
) -> Path:
    """Make ``run_dir`` the active run of ``directory``, in one atomic rename.

    Parameters
    ----------
    directory : str or PathLike
        Directory of the pointer file.
    run_id : int
        ``processing_runs.id`` of the run.
    run_dir : str or PathLike
        Directory of the run's rasters, inside ``directory``.

    Returns
    -------
    Path
        The pointer file.

    Raises
    ------
    ValueError
        When ``run_dir`` is not inside ``directory``.
    OSError
        When the file cannot be written; the previous pointer then stays.
    """
    base = Path(directory)
    try:
        relative = Path(run_dir).resolve().relative_to(base.resolve())
    except ValueError:
        raise ValueError(f"Run directory {run_dir} is not inside {base}") from None
    if not relative.parts:
        raise ValueError(f"Run directory {run_dir} is the directory {base} itself")
    content = json.dumps({"run_id": run_id, "run_dir": relative.as_posix()})
    pointer = base / ACTIVE_RUN_FILE
    # Not mkstemp: its mode 0600 would hide the pointer from the API's user.
    temporary = base / f".{ACTIVE_RUN_FILE}.{uuid.uuid4().hex}.tmp"
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(content + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, pointer)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return pointer


def clear_active_run(directory: str | os.PathLike[str]) -> bool:
    """Remove the pointer file of ``directory``.

    Parameters
    ----------
    directory : str or PathLike
        Directory of the pointer file.

    Returns
    -------
    bool
        True when a pointer was removed, False when there was none.
    """
    try:
        (Path(directory) / ACTIVE_RUN_FILE).unlink()
    except FileNotFoundError:
        return False
    return True


def _is_plain_relative(path: str) -> bool:
    """Tell a non-empty relative POSIX path without ``.``, ``..`` or empty parts."""
    if not path or "\\" in path or "\x00" in path:
        return False
    pure = PurePosixPath(path)
    if pure.is_absolute():
        return False
    return all(part not in ("", ".", "..") for part in path.split("/"))
