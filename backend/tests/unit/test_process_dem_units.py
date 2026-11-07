"""The run of ``process_dem --units``: what it records, publishes and leaves."""

import contextlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import fiona
import numpy as np
import pytest
import rasterio
from shapely.geometry import MultiPolygon, box

from scripts import process_dem as single
from scripts import process_dem_units as units
from tests.dem_equivalence import (
    THRESHOLDS_M2,
    XLL_M,
    YLL_M,
    SplitScene,
    split_scene,
    write_pgw_geopackage,
)

CODES = ("RW0001", "RW0002", "LW0003")


@pytest.fixture(autouse=True)
def _windows_smaller_than_the_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(units, "UNIT_BUFFER_M", 125.0)


@pytest.fixture
def scene(tmp_path: Path) -> SplitScene:
    return split_scene(tmp_path, 3, False)


@pytest.fixture
def pgw(scene: SplitScene, tmp_path: Path) -> Path:
    """The owners of the scene plus a river catchment far outside the DEM."""
    path = tmp_path / "pgw.gpkg"
    write_pgw_geopackage(path, scene, CODES)
    far = box(XLL_M + 1e5, YLL_M + 1e5, XLL_M + 1.1e5, YLL_M + 1.1e5)
    with fiona.open(path, "a", layer="zlewnie_jcwp_rzecznych") as sink:
        sink.write(
            {
                "geometry": MultiPolygon([far]).__geo_interface__,
                "properties": {"MS_KOD": "RW9999"},
            }
        )
    return path


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Replace the run store and the database session by recording fakes."""
    record = SimpleNamespace(calls=[], sessions=0, publish_error=None)

    @contextlib.contextmanager
    def session() -> Any:
        record.sessions += 1
        yield MagicMock()

    def begin_run(db: Any, **kwargs: Any) -> int:
        record.calls.append(("begin_run", kwargs))
        return 41

    def checkpoint_unit(
        db: Any, run_id: int, owner: str, bbox: Any, files: Any
    ) -> None:
        record.calls.append(("checkpoint_unit", run_id, owner, bbox, files))

    def publish_run(db: Any, run_id: int, segments: Any, catchments: Any) -> dict:
        record.calls.append(("publish_run", run_id))
        if record.publish_error is not None:
            raise record.publish_error
        return {"stream_segments_inserted": 1, "catchments_inserted": 1}

    def fail_run(db: Any, run_id: int, error: str) -> None:
        record.calls.append(("fail_run", run_id, error))

    monkeypatch.setattr(units, "get_db_session", session)
    monkeypatch.setattr(units, "begin_run", begin_run)
    monkeypatch.setattr(units, "checkpoint_unit", checkpoint_unit)
    monkeypatch.setattr(units, "publish_run", publish_run)
    monkeypatch.setattr(units, "fail_run", fail_run)
    return record


def _run(scene: SplitScene, pgw: Path, tmp_path: Path, **options: Any) -> dict:
    return units.process_dem_units(
        scene.dem_path,
        pgw,
        output_dir=tmp_path / "out",
        thresholds=list(THRESHOLDS_M2),
        **options,
    )


def test_a_run_records_the_owners_with_cells_and_publishes_after_every_checkpoint(
    scene, pgw, tmp_path, store
):
    stats = _run(scene, pgw, tmp_path)

    names = [call[0] for call in store.calls]
    assert names == [
        "begin_run",
        "checkpoint_unit",
        "checkpoint_unit",
        "checkpoint_unit",
        "publish_run",
    ]
    begin = store.calls[0][1]
    # RW9999 reaches no cell of the DEM: it is no unit of the run
    assert begin["owner_codes"] == ("LW0003", "RW0001", "RW0002")
    assert begin["source_raster"] == str(scene.dem_path)
    assert begin["pgw_path"] == str(pgw)
    assert len(begin["input_fingerprint"]) == 64
    config = begin["config"]
    assert config["thresholds_m2"] == list(THRESHOLDS_M2)
    assert config["halo_m"] == 125.0
    assert config["grid"]["nrows"] == 121 and config["grid"]["ncols"] == 131
    assert config["owners"] == ["LW0003", "RW0001", "RW0002"]
    # Each unit is checkpointed with the bounds of its own cells and its tiles on disk
    checkpoints = {
        call[2]: call for call in store.calls if call[0] == "checkpoint_unit"
    }
    assert set(checkpoints) == {"LW0003", "RW0001", "RW0002"}
    rows, cols = np.nonzero(scene.owners == 3)
    assert checkpoints["LW0003"][3] == (
        rows.min(),
        rows.max() + 1,
        cols.min(),
        cols.max() + 1,
    )
    for call in checkpoints.values():
        assert call[1] == 41
        assert set(call[4]) >= {"01_dem", "02_filled", "10_subcatchments_5000"}
        assert all(Path(path).is_file() for path in call[4].values())
    assert stats["run_id"] == 41 and stats["pgw_owners"] == 3
    assert stats["stream_segments_inserted"] == 1


def test_a_published_run_is_the_active_one_and_leaves_no_scratch(
    scene, pgw, tmp_path, store
):
    first = _run(scene, pgw, tmp_path)
    second = _run(scene, pgw, tmp_path)

    active = tmp_path / "out" / "active_run"
    assert active.is_symlink()
    assert active.resolve() == Path(second["unit_rasters_dir"]).resolve()
    # The directory of the earlier run stays, for a rollback of the files
    assert Path(first["unit_rasters_dir"]).is_dir()
    for stats in (first, second):
        run_dir = Path(stats["unit_rasters_dir"])
        assert not (run_dir / "scratch").exists()
        report = json.loads((run_dir / "report.json").read_text())
        assert report["run_id"] == 41
        assert report["owners"] == ["LW0003", "RW0001", "RW0002"]
        assert report["halo_m"] >= 125.0
        assert 0 < report["largest_window_cells"] <= 121 * 131
        assert report["peak_rss_mb"] > 0
    with rasterio.open(active / "dem_02_filled.vrt") as filled:
        assert filled.shape == (121, 131)


def test_a_dry_run_computes_the_mosaics_and_touches_no_database(
    scene, pgw, tmp_path, store
):
    stats = _run(scene, pgw, tmp_path, dry_run=True)

    assert store.calls == [] and store.sessions == 0
    assert stats["run_id"] is None
    run_dir = Path(stats["unit_rasters_dir"])
    assert (run_dir / "dem_04_flowacc.vrt").is_file()
    assert not (tmp_path / "out" / "active_run").exists()
    assert not (run_dir / "scratch").exists()


def test_a_failure_before_the_publication_fails_the_run_and_changes_nothing(
    scene, pgw, tmp_path, store
):
    store.publish_error = RuntimeError("the transaction broke")

    with pytest.raises(RuntimeError, match="the transaction broke"):
        _run(scene, pgw, tmp_path)

    names = [call[0] for call in store.calls]
    assert names[-2:] == ["publish_run", "fail_run"]
    reason = store.calls[-1]
    assert reason[1] == 41
    assert "RuntimeError: the transaction broke" in reason[2]
    assert not (tmp_path / "out" / "active_run").exists()


def test_an_input_that_is_refused_before_the_run_is_recorded_records_nothing(
    scene, tmp_path, store
):
    no_layers = tmp_path / "other.gpkg"
    with fiona.open(
        no_layers,
        "w",
        driver="GPKG",
        layer="other",
        crs="EPSG:2180",
        schema={"geometry": "Polygon", "properties": {}},
    ):
        pass

    with pytest.raises(ValueError, match="no layer 'zlewnie_jcwp_rzecznych'"):
        _run(scene, no_layers, tmp_path)

    assert store.calls == []


@pytest.mark.parametrize(
    ("options", "error"),
    [
        ({"skip_catchments": True}, "needs the streams and sub-catchments"),
        ({"skip_streams_vectorize": True}, "needs the streams and sub-catchments"),
        (
            {"sewer_config": {"sewer": {"enabled": True}}},
            "storm-sewer",
        ),
        ({"thresholds": [0]}, "positive"),
        ({"max_unit_window_cells": 0}, "positive"),
    ],
)
def test_options_a_published_run_cannot_honour_are_refused_up_front(
    scene, pgw, tmp_path, store, options, error
):
    with pytest.raises(ValueError, match=error):
        units.process_dem_units(
            scene.dem_path, pgw, output_dir=tmp_path / "out", **options
        )

    assert store.calls == []
    assert not (tmp_path / "out").exists()


def test_a_run_by_units_replaces_the_network_only_when_confirmed(
    scene, pgw, tmp_path, store
):
    with pytest.raises(ValueError, match="clear_existing"):
        single.process_dem(scene.dem_path, units_path=pgw, output_dir=tmp_path / "out")

    assert store.calls == []


def test_a_window_over_the_cell_limit_fails_the_run(scene, pgw, tmp_path, store):
    with pytest.raises(MemoryError, match="max_window_cells=1,000"):
        _run(scene, pgw, tmp_path, max_unit_window_cells=1_000)

    assert [call[0] for call in store.calls] == ["begin_run", "fail_run"]


def test_the_fingerprint_follows_the_bytes_of_every_source_of_a_vrt(tmp_path):
    sheet = tmp_path / "sheet.tif"
    sheet.write_bytes(b"first sheet")
    vrt = tmp_path / "mosaic.vrt"
    vrt.write_text(
        "<VRTDataset><VRTRasterBand><SimpleSource>"
        '<SourceFilename relativeToVRT="1">sheet.tif</SourceFilename>'
        "</SimpleSource></VRTRasterBand></VRTDataset>"
    )
    config = {"thresholds_m2": [1000]}

    before = units._input_fingerprint([vrt], config)
    assert units._input_fingerprint([vrt], config) == before
    assert units._input_fingerprint([vrt], {"thresholds_m2": [2000]}) != before
    sheet.write_bytes(b"first sheet, corrected")
    assert units._input_fingerprint([vrt], config) != before
