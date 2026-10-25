"""The DEM steps of prepare_area and analyze_watershed on a tiny synthetic DEM, offline.

Both scripts call ``process_dem`` by keyword. They went on passing ``batch_size`` and
``stream_threshold`` after ``process_dem`` lost them, so the step failed with a
``TypeError`` that only a ``type: ignore`` comment hid from mypy. These tests run the
real ``process_dem`` (flow directions, accumulation, stream and sub-catchment
extraction) over a 40 x 40 DEM that falls to the south along a valley; only the
database is replaced, by recorders of the rows that ``process_dem`` would insert.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from scripts.analyze_watershed import AnalysisConfig, process_nmt_data
from scripts.download_dem import NmtDownloadReport
from scripts.prepare_area import prepare_area
from tests.kartograf_offline import offline as offline  # noqa: F401

CELLS = 40
CELL_SIZE_M = 10.0


@pytest.fixture
def dem_sheet(tmp_path):
    """One sheet in EPSG:2180: a V-shaped valley that falls to the south."""
    across = np.abs(np.arange(CELLS) - CELLS / 2) * 0.5
    along = (CELLS - np.arange(CELLS)) * 0.3
    dem = (100.0 + across[None, :] + along[:, None]).astype("float32")
    path = tmp_path / "sheet.tif"
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
    """Replace the database of process_dem; the rows it would insert are counted."""
    rows = {"segments": 0, "catchments": 0}

    def insert_segments(db, segments, **_):
        rows["segments"] += len(segments)
        return len(segments)

    def insert_catchments(db, catchments, **_):
        rows["catchments"] += len(catchments)
        return len(catchments)

    @contextmanager
    def session():
        yield MagicMock()

    monkeypatch.setattr("core.database.get_db_session", session)
    monkeypatch.setattr("scripts.process_dem.insert_stream_segments", insert_segments)
    monkeypatch.setattr("scripts.process_dem.insert_catchments", insert_catchments)
    return rows


@pytest.mark.usefixtures("offline")
class TestDemStepOfTheScripts:
    def test_prepare_area_processes_the_downloaded_sheets(
        self, tmp_path, monkeypatch, dem_sheet, inserted
    ):
        monkeypatch.setattr(
            "scripts.download_dem.download_for_point",
            lambda **_: NmtDownloadReport(paths=[dem_sheet]),
        )

        stats = prepare_area(lat=52.23, lon=21.01, buffer_km=0.1, output_dir=tmp_path)

        assert stats["errors"] == []
        assert stats["sheets_processed"] == 1
        assert stats["total_cells"] == CELLS * CELLS
        assert stats["stream_cells"] > 0
        assert inserted["segments"] > 0
        assert inserted["catchments"] > 0

    def test_analyze_watershed_processes_the_given_sheets(
        self, tmp_path, dem_sheet, inserted
    ):
        config = AnalysisConfig(
            data_dir=tmp_path / "data",
            cache_dir=tmp_path / "cache",
            output_dir=tmp_path / "results",
        )

        stats = process_nmt_data(config, [dem_sheet])

        assert stats["valid_cells"] == CELLS * CELLS
        assert stats["stream_cells"] > 0
        assert stats["stream_segments_inserted"] == inserted["segments"] > 0
        assert stats["catchments_inserted"] == inserted["catchments"] > 0
