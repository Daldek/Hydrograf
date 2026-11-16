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
from rasterio.features import shapes
from shapely.geometry import MultiPolygon, box, shape

from core import unit_hydrology
from core.active_run import ACTIVE_RUN_FILE, read_active_run
from scripts import process_dem as single
from scripts import process_dem_units as units
from tests.dem_equivalence import (
    NODATA,
    THRESHOLDS_M2,
    XLL_M,
    YLL_M,
    SplitScene,
    split_scene,
    write_pgw_geopackage,
)

CODES = ("RW0001", "RW0002", "LW0003")


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

    def resume_run(db: Any, **kwargs: Any) -> None:
        record.calls.append(("resume_run", kwargs))

    def begin_run(db: Any, **kwargs: Any) -> int:
        record.calls.append(("begin_run", kwargs))
        return 41

    def record_unit_stage(
        db: Any, run_id: int, owner: str, bbox: Any, path: Path, halo_m: float
    ) -> None:
        record.calls.append(("record_unit_stage", run_id, owner, bbox, path, halo_m))

    def checkpoint_unit(
        db: Any, run_id: int, owner: str, bbox: Any, files: Any
    ) -> None:
        record.calls.append(("checkpoint_unit", run_id, owner, bbox, files))

    def publish_run(
        db: Any, run_id: int, segments: Any, catchments: Any
    ) -> dict[str, int]:
        record.calls.append(("publish_run", run_id))
        if record.publish_error is not None:
            raise record.publish_error
        return {"stream_segments_inserted": 1, "catchments_inserted": 1}

    def fail_run(db: Any, run_id: int, error: str) -> None:
        record.calls.append(("fail_run", run_id, error))

    monkeypatch.setattr(units, "get_db_session", session)
    monkeypatch.setattr(units, "get_db_engine", MagicMock)
    monkeypatch.setattr(
        units, "run_lock", lambda engine, run_id: contextlib.nullcontext()
    )
    monkeypatch.setattr(units, "resume_run", resume_run)
    monkeypatch.setattr(units, "begin_run", begin_run)
    monkeypatch.setattr(units, "record_unit_stage", record_unit_stage)
    monkeypatch.setattr(units, "checkpoint_unit", checkpoint_unit)
    monkeypatch.setattr(units, "publish_run", publish_run)
    monkeypatch.setattr(units, "fail_run", fail_run)
    return record


def _run(
    scene: SplitScene, pgw: Path, tmp_path: Path, **options: Any
) -> dict[str, Any]:
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
        "resume_run",
        "begin_run",
        "record_unit_stage",
        "record_unit_stage",
        "record_unit_stage",
        "checkpoint_unit",
        "checkpoint_unit",
        "checkpoint_unit",
        "publish_run",
    ]
    begin = store.calls[1][1]
    # RW9999 reaches no cell of the DEM: it is no unit of the run
    assert begin["owner_codes"] == ("LW0003", "RW0001", "RW0002")
    assert begin["catchment_keys"] is None
    assert begin["source_raster"] == str(scene.dem_path)
    assert begin["pgw_path"] == str(pgw)
    assert len(begin["input_fingerprint"]) == 64
    config = begin["config"]
    assert config["thresholds_m2"] == list(THRESHOLDS_M2)
    assert config["grid"]["nrows"] == 121 and config["grid"]["ncols"] == 131
    assert config["owners"] == ["LW0003", "RW0001", "RW0002"]
    # The resumable run is looked up by the same inputs and settings
    resume = store.calls[0][1]
    assert resume["input_fingerprint"] == begin["input_fingerprint"]
    assert {**resume["config"], "run_dir": config["run_dir"]} == config
    # Each unit is routed once, with its stage on disk
    stages = {call[2]: call for call in store.calls if call[0] == "record_unit_stage"}
    assert set(stages) == {"LW0003", "RW0001", "RW0002"}
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
    for code, call in checkpoints.items():
        assert call[1] == 41
        assert call[3] == stages[code][3]
        assert set(call[4]) >= {"01_dem", "02_filled", "10_subcatchments_5000"}
        # The stage stays in the manifest until the publication
        assert call[4]["stage"] == stages[code][4]
    assert stats["run_id"] == 41 and stats["pgw_owners"] == 3
    assert stats["resumed_units"] == 0
    assert stats["stream_segments_inserted"] == 1
    assert {
        "ownership",
        "prepare_dem",
        "global_fill",
        "routing",
        "vectorize_streams",
        "polygonize_subcatchments",
        "unit_mosaics",
        "publish",
    } <= set(stats["stages"])


def test_a_published_run_is_the_active_one_and_leaves_no_scratch(
    scene, pgw, tmp_path, store
):
    first = _run(scene, pgw, tmp_path)
    second = _run(scene, pgw, tmp_path)

    out = tmp_path / "out"
    active = read_active_run(out)
    assert active is not None and active.run_id == 41
    assert active.run_dir.resolve() == Path(second["unit_rasters_dir"]).resolve()
    # The pointer names the run relative to its directory, never by a host path
    pointer = json.loads((out / ACTIVE_RUN_FILE).read_text())
    assert pointer == {
        "run_id": 41,
        "run_dir": f"unit_runs/{Path(second['unit_rasters_dir']).name}",
    }
    assert second["active_run_written"] is True
    # The directory of the earlier run stays, for a rollback of the files
    assert Path(first["unit_rasters_dir"]).is_dir()
    for stats in (first, second):
        run_dir = Path(stats["unit_rasters_dir"])
        assert not (run_dir / "scratch").exists()
        # The stages of a published run are never resumed
        assert not (run_dir / "stage").exists()
        report = json.loads((run_dir / "report.json").read_text())
        assert report["run_id"] == 41
        assert report["owners"] == ["LW0003", "RW0001", "RW0002"]
        assert report["peak_rss_mb"] > 0
    with rasterio.open(active.run_dir / "dem_02_filled.vrt") as filled:
        assert filled.shape == (121, 131)


def test_a_published_run_stays_published_when_the_pointer_cannot_be_written(
    scene, pgw, tmp_path, store, monkeypatch
):
    def refuse(directory, run_id, run_dir):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(units, "write_active_run", refuse)

    stats = _run(scene, pgw, tmp_path)

    names = [call[0] for call in store.calls]
    assert names[-1] == "publish_run" and "fail_run" not in names
    assert stats["active_run_written"] is False
    run_dir = Path(stats["unit_rasters_dir"])
    assert (run_dir / "report.json").is_file() and (
        run_dir / "dem_02_filled.vrt"
    ).is_file()
    assert not (run_dir / "scratch").exists()


def test_a_dry_run_computes_the_mosaics_and_touches_no_database(
    scene, pgw, tmp_path, store
):
    stats = _run(scene, pgw, tmp_path, dry_run=True)

    assert store.calls == [] and store.sessions == 0
    assert stats["run_id"] is None
    run_dir = Path(stats["unit_rasters_dir"])
    assert (run_dir / "dem_04_flowacc.vrt").is_file()
    assert not (tmp_path / "out" / ACTIVE_RUN_FILE).exists()
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
    assert not (tmp_path / "out" / ACTIVE_RUN_FILE).exists()


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


def test_a_fill_that_fails_fails_the_run(scene, pgw, tmp_path, store, monkeypatch):
    def out_of_memory(*args: Any, **kwargs: Any) -> None:
        raise MemoryError("the fill of the whole grid")

    monkeypatch.setattr(unit_hydrology, "fill_whole_grid", out_of_memory)

    with pytest.raises(MemoryError, match="the fill of the whole grid"):
        _run(scene, pgw, tmp_path)

    assert [call[0] for call in store.calls] == ["resume_run", "begin_run", "fail_run"]


def _pits_off_the_frame(run_dir: Path) -> int:
    """The routed cells of a published run without a D8 direction, off the frame."""
    with (
        rasterio.open(run_dir / "dem_03_flowdir.vrt") as fdir,
        rasterio.open(run_dir / "dem_04_flowacc.vrt") as acc,
    ):
        pits = (acc.read(1) > 0) & (fdir.read(1) == 0)
    return int(np.count_nonzero(pits[1:-1, 1:-1]))


def test_with_the_enclosed_nodata_filled_only_the_frame_drains_the_dem(tmp_path, store):
    scene = split_scene(tmp_path, 3, True)
    pgw = tmp_path / "pgw.gpkg"
    write_pgw_geopackage(pgw, scene, CODES)
    default = _run(scene, pgw, tmp_path)
    # The premise: the holes that the repair leaves drain the land around them
    assert _pits_off_the_frame(Path(default["unit_rasters_dir"])) > 0

    filled = _run(scene, pgw, tmp_path, fill_enclosed_nodata=True)

    run_dir = Path(filled["unit_rasters_dir"])
    assert _pits_off_the_frame(run_dir) == 0
    # The enclosed holes are DEM cells of the run now; the hole cell on the north
    # edge of the scene reaches the frame: the outside, which stays nodata
    outside = scene.dem == NODATA
    outside[1:-1, 1:-1] = False
    assert np.count_nonzero(outside) == 1
    holes = (scene.dem == NODATA) & ~outside
    assert filled["enclosed_nodata_cells"] == np.count_nonzero(holes)
    with rasterio.open(run_dir / "dem_01_dem.vrt") as dem:
        np.testing.assert_array_equal(dem.read(1) == dem.nodata, outside)
    # The setting is one of the run's, and the default runs keep their settings
    first, second = (call[1] for call in store.calls if call[0] == "begin_run")
    assert "fill_enclosed_nodata" not in first["config"]
    assert second["config"]["fill_enclosed_nodata"] is True


def test_the_scratch_of_a_run_lies_in_the_scratch_directory_until_it_succeeds(
    scene, pgw, tmp_path, store
):
    scratch = tmp_path / "scratch"
    store.publish_error = RuntimeError("the transaction broke")
    with pytest.raises(RuntimeError, match="the transaction broke"):
        _run(scene, pgw, tmp_path, scratch_dir=scratch)
    # A failed run leaves its scratch, in the scratch directory, not in the run's
    (failed,) = scratch.iterdir()
    assert (failed / "routing" / "acc.npy").is_file()
    assert not list((tmp_path / "out").rglob("*.npy"))

    store.publish_error = None
    stats = _run(scene, pgw, tmp_path, scratch_dir=scratch)

    assert list(scratch.iterdir()) == [failed]
    run_dir = Path(stats["unit_rasters_dir"])
    assert run_dir.parent == tmp_path / "out" / "unit_runs"
    assert (run_dir / "dem_02_filled.vrt").is_file()
    assert not (run_dir / "scratch").exists()


def _vrt(path: Path, source: str, src: str, dst: str) -> Path:
    path.write_text(
        "<VRTDataset><VRTRasterBand><SimpleSource>"
        f'<SourceFilename relativeToVRT="1">{source}</SourceFilename>'
        f"<SrcRect {src} /><DstRect {dst} />"
        "</SimpleSource></VRTRasterBand></VRTDataset>"
    )
    return path


CELL_FOR_CELL = 'xOff="0" yOff="0" xSize="10" ySize="10"'


def test_the_fingerprint_follows_every_source_of_a_vrt_and_the_vrt_text(tmp_path):
    sheet = tmp_path / "sheet.tif"
    sheet.write_bytes(b"first sheet")
    vrt = _vrt(tmp_path / "mosaic.vrt", "sheet.tif", CELL_FOR_CELL, CELL_FOR_CELL)
    config = {"thresholds_m2": [1000]}

    before = units._input_fingerprint([vrt], config)
    assert units._input_fingerprint([vrt], config) == before
    assert units._input_fingerprint([vrt], {"thresholds_m2": [2000]}) != before
    # The same text written again (the bootstrap rebuilds its mosaic) is the same
    _vrt(vrt, "sheet.tif", CELL_FOR_CELL, CELL_FOR_CELL)
    assert units._input_fingerprint([vrt], config) == before
    sheet.write_bytes(b"first sheet, corrected")
    assert units._input_fingerprint([vrt], config) != before


@pytest.mark.parametrize(
    "dst",
    [
        # Half a cell off the grid of the mosaic
        'xOff="0.5" yOff="0" xSize="10" ySize="10"',
        # Drawn at another size: 1 m cells in a 5 m mosaic
        'xOff="0" yOff="0" xSize="2" ySize="2"',
    ],
)
def test_a_vrt_that_resamples_its_sources_is_refused(tmp_path, dst):
    (tmp_path / "sheet.tif").write_bytes(b"sheet")
    vrt = _vrt(tmp_path / "mosaic.vrt", "sheet.tif", CELL_FOR_CELL, dst)

    with pytest.raises(ValueError, match="must lie on the grid of its sheets"):
        units._file_dependencies(vrt)


def _catchments(
    path: Path, scene: SplitScene, codes: tuple[str, ...]
) -> dict[str, tuple[str, ...]]:
    """Cut each owner of the scene into a northern and a southern catchment.

    Returns the keys of the catchments of each owner code.
    """
    transform = scene.metadata["transform"]
    middle = scene.owners.shape[0] // 2
    keys: dict[str, tuple[str, ...]] = {}
    with fiona.open(
        path,
        "w",
        driver="GPKG",
        layer="zlewnie",
        crs="ESRI:102173",
        schema={"geometry": "MultiPolygon", "properties": {"ID_HYD_10": "str"}},
    ) as sink:
        for owner, code in enumerate(codes, start=1):
            for half, rows in (("n", slice(0, middle)), ("s", slice(middle, None))):
                cells = np.zeros(scene.owners.shape, dtype=np.uint8)
                cells[rows] = scene.owners[rows] == owner
                if not cells.any():
                    continue
                parts = [
                    shape(geometry)
                    for geometry, _ in shapes(
                        cells, mask=cells > 0, transform=transform
                    )
                ]
                sink.write(
                    {
                        "geometry": MultiPolygon(parts).__geo_interface__,
                        "properties": {"ID_HYD_10": f"{code}-{half}"},
                    }
                )
                keys[code] = (*keys.get(code, ()), f"{code}-{half}")
    return keys


def test_a_run_of_catchment_groups_records_the_keys_of_each_unit(
    scene, pgw, tmp_path, store
):
    path = tmp_path / "catchments.gpkg"
    keys = _catchments(path, scene, CODES)
    assert sum(map(len, keys.values())) > len(CODES)

    stats = _run(scene, pgw, tmp_path, units_catchments_path=path)

    begin = store.calls[1][1]
    # The far PGW unit holds no catchment and is no unit
    assert begin["owner_codes"] == ("LW0003", "RW0001", "RW0002")
    assert begin["catchment_keys"] == keys
    assert begin["config"]["catchments"] == {"layer": None, "key": "ID_HYD_10"}
    assert stats["catchments"] == sum(map(len, keys.values()))
    assert stats["pgw_owners"] == 3
