"""``process_dem --units`` equals ``process_dem`` of the whole raster.

Both run on the synthetic DEM of ``tests.dem_equivalence.split_scene``: owners that
straddle the closed basin and the plateau, hillslope leakage, repaired holes on the
seam, and D8 crossings both ways between two owners (a cycle of the owner graph in an
acyclic flow). The rows each run hands to the database (stream segments and
sub-catchments with their downstream links, which is the catchment graph) and the
rasters each saves (GeoTIFFs of the whole raster, VRT mosaics of the units) must agree,
up to the numbering of the segments; so must a run by units that was interrupted
after some units and resumed.
"""

import contextlib
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from shapely.geometry import LineString, box

from core.unit_run_store import ResumedRun, UnitState, _manifest
from scripts import process_dem as single
from scripts import process_dem_units as units
from tests.dem_equivalence import (
    NODATA,
    THRESHOLDS_M2,
    XLL_M,
    YLL_M,
    SplitScene,
    assert_same_network,
    split_scene,
    write_pgw_geopackage,
)

CODES = ("RW0001", "RW0002", "LW0003")


@pytest.fixture(params=[(2, False), (2, True), (3, False), (3, True)], ids=str)
def scene(request: pytest.FixtureRequest, tmp_path: Path) -> SplitScene:
    """The scene of 2 or 3 owners, without or with nodata holes."""
    units_count, holes = request.param
    return split_scene(tmp_path, units_count, holes)


def _fake_database(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Catch what each ``process_dem`` hands to the database; touch no database.

    The run store keeps the stages it is given (``units``) and resumes them for the
    next call while ``resumable`` is set; ``interrupt_after`` stops a run once that
    many units are routed.
    """
    rows = SimpleNamespace(
        single=None,
        units=None,
        stages={},
        run_dir=None,
        resumable=False,
        interrupt_after=None,
    )

    @contextlib.contextmanager
    def session() -> Any:
        yield MagicMock()

    def insert(db: Any, segments: Any, catchments: Any, stats: Any) -> None:
        rows.single = (segments, catchments)

    def publish_run(
        db: Any, run_id: int, segments: Any, catchments: Any
    ) -> dict[str, int]:
        rows.units = (segments, catchments)
        return {"stream_segments_inserted": 0, "catchments_inserted": 0}

    def begin_run(db: Any, **kwargs: Any) -> int:
        rows.run_dir = kwargs["config"]["run_dir"]
        rows.stages = {}
        return 7

    def resume_run(db: Any, *, input_fingerprint: str, config: Any) -> Any:
        if not rows.resumable:
            return None
        return ResumedRun(7, {**config, "run_dir": rows.run_dir}, dict(rows.stages))

    def record_unit_stage(
        db: Any, run_id: int, code: str, bbox: Any, path: Path, halo_m: float
    ) -> None:
        rows.stages[code] = UnitState("routed", halo_m, _manifest({"stage": path}))
        if (
            rows.interrupt_after is not None
            and len(rows.stages) >= rows.interrupt_after
        ):
            raise KeyboardInterrupt

    monkeypatch.setattr("core.database.get_db_session", session)
    monkeypatch.setattr(single, "_insert_thresholds", insert)
    monkeypatch.setattr(units, "get_db_session", session)
    monkeypatch.setattr(units, "get_db_engine", MagicMock)
    monkeypatch.setattr(
        units, "run_lock", lambda engine, run_id: contextlib.nullcontext()
    )
    monkeypatch.setattr(units, "begin_run", begin_run)
    monkeypatch.setattr(units, "resume_run", resume_run)
    monkeypatch.setattr(units, "record_unit_stage", record_unit_stage)
    monkeypatch.setattr(units, "checkpoint_unit", lambda *args: None)
    monkeypatch.setattr(units, "fail_run", lambda *args: None)
    monkeypatch.setattr(units, "publish_run", publish_run)
    # The BDOT10k step after the insert needs a database; the streams are not tested
    monkeypatch.setattr(single, "load_bdot_streams_from_gpkg", lambda path: [])
    monkeypatch.setattr(units, "load_bdot_streams_from_gpkg", lambda path: [])
    return rows


def _equivalent_labels(expected: np.ndarray, actual: np.ndarray) -> None:
    """Require a one-to-one renumbering of the segment labels."""
    assert np.array_equal(expected == 0, actual == 0)
    pairs = np.unique(np.stack([expected.ravel(), actual.ravel()]), axis=1)
    assert len(set(pairs[0])) == len(pairs[0]), "a label was split"
    assert len(set(pairs[1])) == len(pairs[1]), "two labels were merged"


def _both_runs(
    scene: SplitScene, tmp_path: Path, database: SimpleNamespace, **options: Any
) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    """Run ``process_dem`` on the whole raster and by the units of the scene."""
    codes = CODES[: int(scene.owners.max()) - 1] + CODES[-1:]
    write_pgw_geopackage(tmp_path / "pgw.gpkg", scene, codes)
    whole_dir = tmp_path / "whole"
    whole_dir.mkdir()
    shared: dict[str, Any] = {
        "clear_existing": True,
        "thresholds": list(THRESHOLDS_M2),
        **options,
    }
    whole_stats = single.process_dem(
        scene.dem_path, save_intermediates=True, output_dir=whole_dir, **shared
    )
    units_stats = single.process_dem(
        scene.dem_path,
        output_dir=tmp_path / "units",
        units_path=tmp_path / "pgw.gpkg",
        **shared,
    )
    assert units_stats["pgw_owners"] == len(codes)
    return whole_stats, units_stats, whole_dir, Path(units_stats["unit_rasters_dir"])


def _assert_same_statistics(units_stats: dict[str, Any], whole_stats: dict[str, Any]):
    for key in (
        "ncols",
        "nrows",
        "cellsize",
        "total_cells",
        "valid_cells",
        "max_accumulation",
        "stream_cells",
        "stream_segments",
        "stream_thresholds",
        "catchment_thresholds",
    ):
        assert units_stats[key] == whole_stats[key], key
    assert units_stats["mean_slope"] == pytest.approx(
        whole_stats["mean_slope"], rel=1e-12
    )


def _assert_same_rasters(
    scene: SplitScene, whole_dir: Path, run_dir: Path, not_mosaicked: set[str]
) -> None:
    """Every raster of the whole run is a VRT of the unit tiles on its cells."""
    saved = {path.stem: path for path in whole_dir.glob("dem_*.tif")}
    mosaics = {path.stem: path for path in run_dir.glob("dem_*.vrt")}
    assert set(saved) - set(mosaics) == not_mosaicked
    assert set(mosaics) <= set(saved)
    assert "dem_10_subcatchments_5000" in mosaics
    valid = scene.dem != NODATA
    for name, mosaic in mosaics.items():
        with rasterio.open(saved[name]) as expected, rasterio.open(mosaic) as actual:
            assert actual.shape == expected.shape
            assert actual.transform == expected.transform
            assert actual.crs == expected.crs
            assert actual.dtypes == expected.dtypes, name
            assert actual.nodata == expected.nodata, name
            nodata = actual.nodata
            wanted, got = expected.read(1), actual.read(1)
        if "subcatchments" in name:
            _equivalent_labels(wanted[valid], got[valid])
        else:
            np.testing.assert_array_equal(got[valid], wanted[valid], name)
        # A mosaic of tiles of owners holds nothing else: nodata outside the cells
        # of the DEM (the repaired holes of the whole run are no owner's cell).
        np.testing.assert_array_equal(got[~valid], np.asarray(nodata, got.dtype), name)


def test_run_by_units_equals_run_of_the_whole_raster(scene, tmp_path, monkeypatch):
    database = _fake_database(monkeypatch)

    whole_stats, units_stats, whole_dir, run_dir = _both_runs(scene, tmp_path, database)

    # The rows of stream_network and stream_catchments, the catchment graph
    assert_same_network(database.units, database.single)
    _assert_same_statistics(units_stats, whole_stats)
    _assert_same_rasters(scene, whole_dir, run_dir, not_mosaicked=set())


def test_a_resumed_run_equals_the_run_of_the_whole_raster(tmp_path, monkeypatch):
    scene = split_scene(tmp_path, 3, True)
    database = _fake_database(monkeypatch)
    write_pgw_geopackage(tmp_path / "pgw.gpkg", scene, CODES)
    arguments: dict[str, Any] = {
        "clear_existing": True,
        "thresholds": list(THRESHOLDS_M2),
        "output_dir": tmp_path / "units",
        "units_path": tmp_path / "pgw.gpkg",
    }
    # The run stops once two of the three units are routed
    database.interrupt_after = 2
    with pytest.raises(KeyboardInterrupt):
        single.process_dem(scene.dem_path, **arguments)
    assert database.units is None
    assert len(database.stages) == 2

    database.interrupt_after = None
    database.resumable = True
    units_stats = single.process_dem(scene.dem_path, **arguments)
    whole_dir = tmp_path / "whole"
    whole_dir.mkdir()
    whole_stats = single.process_dem(
        scene.dem_path,
        save_intermediates=True,
        output_dir=whole_dir,
        clear_existing=True,
        thresholds=list(THRESHOLDS_M2),
    )

    assert units_stats["resumed_units"] == 2
    assert units_stats["unit_rasters_dir"] == database.run_dir
    assert_same_network(database.units, database.single)
    _assert_same_statistics(units_stats, whole_stats)
    _assert_same_rasters(
        scene, whole_dir, Path(units_stats["unit_rasters_dir"]), not_mosaicked=set()
    )


def test_a_stage_file_that_changed_is_computed_again(tmp_path, monkeypatch):
    scene = split_scene(tmp_path, 2, False)
    database = _fake_database(monkeypatch)
    write_pgw_geopackage(tmp_path / "pgw.gpkg", scene, CODES[:1] + CODES[-1:])
    arguments: dict[str, Any] = {
        "clear_existing": True,
        "thresholds": list(THRESHOLDS_M2),
        "output_dir": tmp_path / "units",
        "units_path": tmp_path / "pgw.gpkg",
    }
    database.interrupt_after = 2
    with pytest.raises(KeyboardInterrupt):
        single.process_dem(scene.dem_path, **arguments)
    changed = Path(database.stages["LW0003"].outputs["stage"]["path"])
    with changed.open("r+b") as stage:
        stage.seek(-1, 2)
        last = stage.read(1)
        stage.seek(-1, 2)
        stage.write(b"\1" if last == b"\0" else b"\0")

    database.interrupt_after = None
    database.resumable = True
    units_stats = single.process_dem(scene.dem_path, **arguments)

    assert units_stats["resumed_units"] == 1


def _hydro_geopackage(path: Path, scene: SplitScene) -> Path:
    """A BDOT10k-like GeoPackage: the valley as a stream and two lakes without outflow.

    The stream crosses the seam of the owners, so a monotonic profile along it needs
    both sides; the lakes become drain points of the whole grid.
    """
    nrows, ncols = scene.dem.shape
    rows = np.arange(0, nrows, 2)
    valley = ncols / 2 + 0.1 * ncols * np.sin(2 * np.pi * rows / nrows)
    xs = XLL_M + (valley + 0.5) * 5
    ys = YLL_M + (nrows - rows - 0.5) * 5
    stream = LineString(list(zip(xs, ys, strict=True)))

    def lake(first_row: int, last_row: int, first_col: int, last_col: int) -> Any:
        return box(
            XLL_M + first_col * 5,
            YLL_M + (nrows - last_row) * 5,
            XLL_M + last_col * 5,
            YLL_M + (nrows - first_row) * 5,
        )

    lakes = [lake(20, 30, 10, 20), lake(60, 70, 100, 110)]
    gpd.GeoDataFrame({"geometry": lakes}, crs="EPSG:2180").to_file(
        path, layer="OT_PTWP_A", driver="GPKG"
    )
    # The valley is a main watercourse and a river; the ditch beside it is neither
    gpd.GeoDataFrame(
        {"geometry": [stream], "PRZEBIEG": ["ciek główny"], "RODZAJ": ["rzeka"]},
        crs="EPSG:2180",
    ).to_file(path, layer="OT_SWRS_L", driver="GPKG", mode="a")
    ditch = LineString(
        [(XLL_M + 105 * 5, YLL_M + 90 * 5), (XLL_M + 125 * 5, YLL_M + 75 * 5)]
    )
    gpd.GeoDataFrame({"geometry": [ditch]}, crs="EPSG:2180").to_file(
        path, layer="OT_SWRM_L", driver="GPKG", mode="a"
    )
    return path


@pytest.mark.parametrize("stream_burning", ["all", "main"])
def test_burning_smoothing_and_lake_drains_are_done_on_the_whole_dem(
    tmp_path, monkeypatch, stream_burning
):
    scene = split_scene(tmp_path, 3, True)
    database = _fake_database(monkeypatch)
    hydro = _hydro_geopackage(tmp_path / "hydro.gpkg", scene)

    whole_stats, units_stats, whole_dir, run_dir = _both_runs(
        scene,
        tmp_path,
        database,
        burn_streams_path=hydro,
        stream_burning=stream_burning,
        waterbody_mode="auto",
    )

    # The premises: the burn lowered cells, the smoothing corrected the profile of the
    # stream across the seam, and the lakes gave drain points of the whole grid
    assert whole_stats["burn_cells"] > 0
    assert whole_stats["smooth_cells"] > 0
    assert whole_stats["drain_points"] == 2
    assert units_stats["stream_burning"] == stream_burning
    for key in (
        "burn_cells",
        "smooth_cells",
        "smooth_max_correction_m",
        "endorheic_lakes",
        "drain_points",
    ):
        assert units_stats[key] == whole_stats[key], key
    assert_same_network(database.units, database.single)
    _assert_same_statistics(units_stats, whole_stats)
    _assert_same_rasters(
        scene,
        whole_dir,
        run_dir,
        # the intermediate DEMs of the whole run, which the units keep as scratch
        not_mosaicked={"dem_02a_burned", "dem_02b_smoothed"},
    )
