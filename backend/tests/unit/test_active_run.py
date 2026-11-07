"""The pointer to the active unit run, and the rasters that the API and bootstrap read.

A published run by PGW units writes ``active_run.json`` in its output directory (DEM_DIR
of the API); a run of the whole raster removes it. The resolvers of ``Settings`` return
the run's VRT mosaics while the pointer is valid, and the GeoTIFFs of a run of the whole
raster otherwise.
"""

import contextlib
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from core.active_run import (
    ACTIVE_RUN_FILE,
    clear_active_run,
    read_active_run,
    write_active_run,
)
from core.config import Settings
from scripts import process_dem as single
from tests.dem_equivalence import THRESHOLDS_M2, split_scene

RESOLVED = {
    "01_dem": Settings.resolve_dem_path,
    "04b_stream_distance": Settings.resolve_stream_distance_path,
    "03_flowdir": Settings.resolve_flowdir_path,
    "10_subcatchments_5000": lambda s: s.resolve_subcatchment_labels_path(5000),
    "05_slope": Settings.resolve_slope_path,
}


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def _settings(dem_dir: Path, **overrides: str) -> Settings:
    return Settings(
        dem_dir=str(dem_dir),
        dem_path=overrides.get("dem_path", ""),
        stream_distance_path=overrides.get("stream_distance_path", ""),
    )


def _whole_run_rasters(dem_dir: Path) -> dict[str, Path]:
    """The GeoTIFFs of a run of the whole raster (and the input mosaic of the DEM)."""
    rasters = {name: _touch(dem_dir / f"dem_mosaic_{name}.tif") for name in RESOLVED}
    rasters["01_dem"] = _touch(dem_dir / "dem_mosaic.vrt")
    return rasters


def _unit_run(dem_dir: Path, run_id: int = 7, token: str = "abc") -> dict[str, Path]:
    """The VRT mosaics of a published unit run, made active."""
    run_dir = dem_dir / "unit_runs" / token
    mosaics = {name: _touch(run_dir / f"dem_mosaic_{name}.vrt") for name in RESOLVED}
    write_active_run(dem_dir, run_id, run_dir)
    return mosaics


# ---------------------------------------------------------------------------
# The pointer file
# ---------------------------------------------------------------------------


def test_a_written_pointer_names_the_run_relative_to_its_directory(tmp_path):
    run_dir = tmp_path / "unit_runs" / "abc"
    run_dir.mkdir(parents=True)

    pointer = write_active_run(tmp_path, 12, run_dir)

    assert json.loads(pointer.read_text()) == {"run_id": 12, "run_dir": "unit_runs/abc"}
    active = read_active_run(tmp_path)
    assert active is not None
    assert (active.run_id, active.run_dir) == (12, run_dir)
    assert {path.name for path in tmp_path.iterdir()} == {"unit_runs", ACTIVE_RUN_FILE}


def test_a_moved_directory_keeps_its_active_run(tmp_path):
    """The API mounts the output directory elsewhere (DEM_DIR=/data/nmt)."""
    host = tmp_path / "host"
    write_active_run(host, 3, _touch(host / "unit_runs" / "abc" / "x.vrt").parent)

    host.rename(tmp_path / "mounted")

    active = read_active_run(tmp_path / "mounted")
    assert active is not None and active.run_dir == tmp_path / "mounted/unit_runs/abc"


def test_a_new_pointer_replaces_the_previous_one(tmp_path):
    for token in ("first", "second"):
        (tmp_path / "unit_runs" / token).mkdir(parents=True)
    write_active_run(tmp_path, 1, tmp_path / "unit_runs" / "first")

    write_active_run(tmp_path, 2, tmp_path / "unit_runs" / "second")

    active = read_active_run(tmp_path)
    assert active is not None and active.run_id == 2
    assert active.run_dir.name == "second"
    assert {path.name for path in tmp_path.iterdir()} == {"unit_runs", ACTIVE_RUN_FILE}


def test_a_pointer_that_cannot_be_renamed_leaves_the_previous_one(
    tmp_path, monkeypatch
):
    for token in ("first", "second"):
        (tmp_path / "unit_runs" / token).mkdir(parents=True)
    write_active_run(tmp_path, 1, tmp_path / "unit_runs" / "first")

    def refuse(source: Any, target: Any) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("core.active_run.os.replace", refuse)
    with pytest.raises(PermissionError):
        write_active_run(tmp_path, 2, tmp_path / "unit_runs" / "second")

    active = read_active_run(tmp_path)
    assert active is not None and active.run_id == 1
    assert {path.name for path in tmp_path.iterdir()} == {"unit_runs", ACTIVE_RUN_FILE}


def test_a_run_outside_the_directory_is_refused(tmp_path):
    directory = tmp_path / "out"
    (tmp_path / "elsewhere").mkdir()
    directory.mkdir()

    for run_dir in (tmp_path, tmp_path / "elsewhere", directory):
        with pytest.raises(ValueError):
            write_active_run(directory, 1, run_dir)
    assert list(directory.iterdir()) == []


def test_clearing_removes_the_pointer_once(tmp_path):
    (tmp_path / "unit_runs" / "abc").mkdir(parents=True)
    write_active_run(tmp_path, 1, tmp_path / "unit_runs" / "abc")

    assert clear_active_run(tmp_path) is True
    assert read_active_run(tmp_path) is None
    assert clear_active_run(tmp_path) is False
    assert (tmp_path / "unit_runs" / "abc").is_dir(), "the run's files stay"


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[1, 2]",
        '{"run_dir": "unit_runs/abc"}',
        '{"run_id": "7", "run_dir": "unit_runs/abc"}',
        '{"run_id": true, "run_dir": "unit_runs/abc"}',
        '{"run_id": 7}',
        '{"run_id": 7, "run_dir": ""}',
        '{"run_id": 7, "run_dir": "/abs/unit_runs/abc"}',
        '{"run_id": 7, "run_dir": "unit_runs/../unit_runs/abc"}',
        '{"run_id": 7, "run_dir": "../out/unit_runs/abc"}',
        '{"run_id": 7, "run_dir": "unit_runs\\\\abc"}',
    ],
)
def test_a_malformed_pointer_is_no_active_run(tmp_path, caplog, content):
    out = tmp_path / "out"
    (out / "unit_runs" / "abc").mkdir(parents=True)
    (out / ACTIVE_RUN_FILE).write_text(content)

    with caplog.at_level(logging.WARNING, logger="core.active_run"):
        assert read_active_run(out) is None
    assert ACTIVE_RUN_FILE in caplog.text


def test_a_run_reached_through_a_link_out_of_the_directory_is_no_active_run(
    tmp_path, caplog
):
    outside = tmp_path / "outside"
    outside.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    (out / "unit_runs").symlink_to(outside, target_is_directory=True)
    (outside / "abc").mkdir()
    (out / ACTIVE_RUN_FILE).write_text('{"run_id": 7, "run_dir": "unit_runs/abc"}')

    with caplog.at_level(logging.WARNING, logger="core.active_run"):
        assert read_active_run(out) is None
    assert "outside" in caplog.text


def test_a_dangling_pointer_is_no_active_run(tmp_path, caplog):
    (tmp_path / ACTIVE_RUN_FILE).write_text('{"run_id": 7, "run_dir": "unit_runs/x"}')

    with caplog.at_level(logging.WARNING, logger="core.active_run"):
        assert read_active_run(tmp_path) is None
    assert "missing run directory" in caplog.text


# ---------------------------------------------------------------------------
# The resolvers of Settings
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raster", list(RESOLVED))
def test_a_valid_pointer_resolves_the_vrt_mosaic_of_the_run(tmp_path, raster):
    _whole_run_rasters(tmp_path)
    mosaics = _unit_run(tmp_path)

    assert RESOLVED[raster](_settings(tmp_path)) == str(mosaics[raster])


@pytest.mark.parametrize("raster", list(RESOLVED))
def test_without_a_pointer_the_rasters_of_the_whole_run_are_resolved(tmp_path, raster):
    tifs = _whole_run_rasters(tmp_path)
    run_dir = tmp_path / "unit_runs" / "abc"
    for name in RESOLVED:
        _touch(run_dir / f"dem_mosaic_{name}.vrt")

    assert RESOLVED[raster](_settings(tmp_path)) == str(tifs[raster])


@pytest.mark.parametrize("raster", list(RESOLVED))
@pytest.mark.parametrize(
    "pointer",
    ["{broken", '{"run_id": 7, "run_dir": "unit_runs/gone"}'],
    ids=["malformed", "dangling"],
)
def test_a_malformed_or_dangling_pointer_falls_back_to_the_whole_run(
    tmp_path, raster, pointer
):
    tifs = _whole_run_rasters(tmp_path)
    for name in RESOLVED:
        _touch(tmp_path / "unit_runs" / "abc" / f"dem_mosaic_{name}.vrt")
    (tmp_path / ACTIVE_RUN_FILE).write_text(pointer)

    assert RESOLVED[raster](_settings(tmp_path)) == str(tifs[raster])


def test_a_raster_the_active_run_lacks_falls_back_to_the_whole_run(tmp_path):
    tif = _touch(tmp_path / "dem_mosaic_10_subcatchments_100000.tif")
    _unit_run(tmp_path)

    settings = _settings(tmp_path)
    assert settings.resolve_subcatchment_labels_path(100000) == str(tif)
    assert settings.resolve_subcatchment_labels_path(250) is None


def test_nothing_resolves_without_rasters(tmp_path):
    settings = _settings(tmp_path)

    assert [resolve(settings) for resolve in RESOLVED.values()] == [None] * 5


def test_the_explicit_paths_take_precedence_over_the_active_run(tmp_path):
    _whole_run_rasters(tmp_path)
    mosaics = _unit_run(tmp_path)
    dem = _touch(tmp_path / "elsewhere" / "dem.tif")
    distance = _touch(tmp_path / "elsewhere" / "distance.tif")

    settings = _settings(
        tmp_path, dem_path=str(dem), stream_distance_path=str(distance)
    )
    assert settings.resolve_dem_path() == str(dem)
    assert settings.resolve_stream_distance_path() == str(distance)
    # An override that does not exist is ignored
    missing = _settings(
        tmp_path,
        dem_path=str(tmp_path / "no.tif"),
        stream_distance_path=str(tmp_path / "no.tif"),
    )
    assert missing.resolve_dem_path() == str(mosaics["01_dem"])
    assert missing.resolve_stream_distance_path() == str(mosaics["04b_stream_distance"])


# ---------------------------------------------------------------------------
# A run of the whole raster makes the unit run stale
# ---------------------------------------------------------------------------


@pytest.fixture
def sessions(monkeypatch) -> list[MagicMock]:
    """Replace the database of ``process_dem``; the sessions it opens are kept.

    What the publication does to ``processing_runs`` is tested on PostGIS
    (``tests/integration/test_unit_run_db.py``).
    """
    opened: list[MagicMock] = []

    @contextlib.contextmanager
    def session() -> Any:
        opened.append(MagicMock())
        yield opened[-1]

    monkeypatch.setattr("core.database.get_db_session", session)
    monkeypatch.setattr(single, "_insert_thresholds", lambda *args: None)
    return opened


@pytest.mark.parametrize("clear_existing", [True, False])
def test_a_whole_raster_run_clears_the_pointer(tmp_path, sessions, clear_existing):
    scene = split_scene(tmp_path, 2, False)
    out = tmp_path / "out"
    _unit_run(out)

    single.process_dem(
        scene.dem_path,
        output_dir=out,
        clear_existing=clear_existing,
        thresholds=list(THRESHOLDS_M2),
    )

    assert len(sessions) == 1
    assert read_active_run(out) is None
    assert not (out / ACTIVE_RUN_FILE).exists()
    assert (out / "unit_runs" / "abc").is_dir(), "the files of the run stay"


def test_a_whole_raster_dry_run_keeps_the_pointer(tmp_path, sessions):
    scene = split_scene(tmp_path, 2, False)
    out = tmp_path / "out"
    _unit_run(out)

    single.process_dem(
        scene.dem_path, output_dir=out, dry_run=True, thresholds=list(THRESHOLDS_M2)
    )

    assert sessions == []
    active = read_active_run(out)
    assert active is not None and active.run_id == 7
