"""The saved rasters of a run reproduce what the run computed.

process_dem runs over a small synthetic DEM with save_intermediates, the database
replaced by recorders of the rows it would insert. From the saved rasters alone,
scripts.backfill_flow_path_heads must give every sub-catchment the flow path head,
overland segment and stream head that the run computed, and
process_dem_from_intermediates must give a threshold the same streams and
sub-catchments as the full run: production adds the thresholds of 1 and 10 km²
and fills the new columns this way, without running the DEM again.
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely import wkt

from core.cell_parameters import d8_from_saved_flowdir
from scripts.backfill_flow_path_heads import backfill_threshold
from scripts.process_dem import (
    load_hydrology_intermediates,
    process_dem,
    process_dem_from_intermediates,
)

CELLS = 60
CELL_SIZE_M = 10.0
THRESHOLDS_M2 = (1000, 5000)
NEW_COLUMNS = (
    "flow_path_head_elev_m",
    "overland_length_m",
    "overland_drop_m",
    "stream_head_elev_m",
)


@pytest.fixture
def dem_path(tmp_path):
    """A valley falling to the south with ridges across it: a branching network."""
    y, x = np.mgrid[0:CELLS, 0:CELLS]
    dem = (
        100.0
        + 0.5 * (CELLS - y)
        + 0.3 * np.abs(x - CELLS / 2)
        + 2.0 * np.sin(x / 4.0) * np.cos(y / 5.0)
    ).astype("float32")
    path = tmp_path / "dem.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=CELLS,
        width=CELLS,
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=from_origin(500000.0, 600000.0, CELL_SIZE_M, CELL_SIZE_M),
        nodata=-9999.0,
    ) as dst:
        dst.write(dem, 1)
    return path


@pytest.fixture
def inserted(monkeypatch):
    """Replace the database of process_dem; record the rows it would insert."""
    rows = {"segments": {}, "catchments": {}}

    def insert_segments(db, segments, threshold_m2, **_):
        rows["segments"][threshold_m2] = segments
        return len(segments)

    def insert_catchments(db, catchments, threshold_m2, **_):
        rows["catchments"][threshold_m2] = catchments
        return len(catchments)

    @contextmanager
    def session():
        yield MagicMock()

    monkeypatch.setattr("core.database.get_db_session", session)
    monkeypatch.setattr("scripts.process_dem.insert_stream_segments", insert_segments)
    monkeypatch.setattr("scripts.process_dem.insert_catchments", insert_catchments)
    monkeypatch.setattr(
        "scripts.process_dem.update_stream_real_flags_all", lambda db, t: {}
    )
    return rows


@pytest.fixture
def full_run(dem_path, inserted):
    """The rows of a full run with its rasters saved next to the DEM."""
    process_dem(
        dem_path,
        save_intermediates=True,
        output_dir=dem_path.parent,
        thresholds=list(THRESHOLDS_M2),
    )
    segments = dict(inserted["segments"])
    catchments = dict(inserted["catchments"])
    inserted["segments"].clear()
    inserted["catchments"].clear()
    return segments, catchments


class FakeDatabase:
    """Answers the SELECT of the backfill with rows and records its UPDATE."""

    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def execute(self, statement, params=None):
        if str(statement).startswith("UPDATE"):
            self.updates.extend(params)
            return None
        return SimpleNamespace(fetchall=lambda: self.rows)

    def commit(self):
        pass


def database_rows(catchments, max_flow_dist_shift_m=0.0):
    """Rows of stream_catchments as the backfill selects them."""
    rows = []
    for i, catchment in enumerate(catchments):
        line = catchment["longest_flow_path_wkt"]
        x, y = wkt.loads(line).coords[0] if line else (None, None)
        rows.append(
            SimpleNamespace(
                id=i,
                segment_idx=catchment["segment_idx"],
                max_flow_dist_m=catchment["max_flow_dist_m"] + max_flow_dist_shift_m,
                x=x,
                y=y,
            )
        )
    return rows


def saved_hydrology(dem_path):
    rasters, metadata = load_hydrology_intermediates(
        dem_path, names=("filled_dem", "fdir", "acc", "flow_dist_m")
    )
    d8 = d8_from_saved_flowdir(
        rasters.pop("fdir"),
        rasters["flow_dist_m"],
        rasters["filled_dem"] != metadata["nodata_value"],
    )
    return rasters, metadata, d8


@pytest.mark.parametrize("threshold_m2", THRESHOLDS_M2)
def test_backfill_gives_the_values_of_the_run(dem_path, full_run, threshold_m2):
    _, catchments = full_run
    run = catchments[threshold_m2]
    assert len(run) > 1
    assert any(c["overland_length_m"] for c in run)  # the run measured something
    rasters, metadata, d8 = saved_hydrology(dem_path)
    db = FakeDatabase(database_rows(run))

    counts = backfill_threshold(
        db,
        threshold_m2,
        dem_path.parent / f"dem_10_subcatchments_{threshold_m2}.tif",
        rasters,
        metadata,
        d8,
        dry_run=False,
    )

    assert counts["rows"] == len(run)
    by_id = {update["id"]: update for update in db.updates}
    for i, catchment in enumerate(run):
        update = by_id[i]
        assert (
            update["head"],
            update["length"],
            update["drop"],
            update["stream"],
        ) == tuple(catchment[key] for key in NEW_COLUMNS), catchment["segment_idx"]


def test_backfill_refuses_rasters_that_do_not_match_the_rows(dem_path, full_run):
    _, catchments = full_run
    rasters, metadata, d8 = saved_hydrology(dem_path)
    db = FakeDatabase(database_rows(catchments[1000], max_flow_dist_shift_m=5.0))

    with pytest.raises(RuntimeError, match="do not match the rasters"):
        backfill_threshold(
            db,
            1000,
            dem_path.parent / "dem_10_subcatchments_1000.tif",
            rasters,
            metadata,
            d8,
            dry_run=False,
        )

    assert db.updates == []


def test_a_threshold_from_the_saved_rasters_equals_the_full_run(
    dem_path, full_run, inserted
):
    segments, catchments = full_run

    process_dem_from_intermediates(dem_path, [5000])

    assert [s["coords"] for s in inserted["segments"][5000]] == [
        s["coords"] for s in segments[5000]
    ]
    added = inserted["catchments"][5000]
    assert len(added) == len(catchments[5000])
    for new, old in zip(added, catchments[5000], strict=True):
        # The saved slope is float32, the run's float64: the rounded means may
        # differ in the last digit
        assert new.pop("mean_slope_percent") == pytest.approx(
            old.pop("mean_slope_percent"), abs=0.011
        )
        assert new == old
