"""Bootstrap steps 2-3 with the real Kartograf: the store of the cache, no copies."""

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.bootstrap import step_download_nmt, step_process_dem
from tests.kartograf_offline import GugikIndex, flight, gugik_index
from tests.kartograf_offline import offline as offline  # noqa: F401

SHEET = "N-33-130-D-d-1-1"
NO_COVERAGE = "N-35-1-A-a-1-1"
STD = f"kartograf/nmt/pl_1992_5m_evrf2007/N-33/130/D/d/1/1/{SHEET}.asc"
VERSION = (
    "kartograf/nmt/pl_1992_5m_evrf2007/versions/N-33/130/D/d/1/1/"
    f"2025-09-09_83980_ab12cd34/{SHEET}.asc"
)


class _Stop(Exception):
    pass


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("ncols 1\n")
    return path


@pytest.mark.usefixtures("offline")
class TestStepDownloadNmt:
    def test_sheets_go_into_the_store_of_the_cache_dir(self, tmp_path):
        index = GugikIndex([flight(SHEET, "2025-09-09", "83980")])
        with gugik_index(index):
            paths, detail = step_download_nmt(
                [SHEET, NO_COVERAGE], tmp_path, resolution="5m"
            )

        assert paths == [tmp_path / STD]
        assert paths[0].is_file()
        assert (tmp_path / "kartograf" / "kartograf-store.json").is_file()
        assert "1/2 arkuszy" in detail
        assert "1 bez pokrycia" in detail

    def test_sheets_go_into_the_shared_store_and_not_into_the_cache_dir(
        self, tmp_path, monkeypatch
    ):
        shared = tmp_path / "shared"
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        monkeypatch.setenv("HYDROGRAF_KARTOGRAF_ROOT", str(shared))
        index = GugikIndex([flight(SHEET, "2025-09-09", "83980")])
        with gugik_index(index):
            paths, _ = step_download_nmt([SHEET], cache_dir, resolution="5m")

        assert paths == [shared / STD.removeprefix("kartograf/")]
        assert (shared / "kartograf-store.json").is_file()
        assert not (cache_dir / "kartograf").exists()

    def test_a_write_in_progress_in_the_store_stops_the_step_before_writing(
        self, tmp_path
    ):
        staging = (
            tmp_path
            / "kartograf/nmt/pl_1992_5m_evrf2007/versions/.incoming"
            / "archiwista_4242_0a1b2c3d"
        )
        staging.mkdir(parents=True)
        (staging / f"{SHEET}.asc.4242_1.tmp").write_text("partial")
        index = GugikIndex([flight(SHEET, "2025-09-09", "83980")])

        with gugik_index(index), pytest.raises(RuntimeError, match="ADR-066") as e:
            step_download_nmt([SHEET], tmp_path, resolution="5m")

        assert "archiwista_4242_0a1b2c3d" in str(e.value)
        assert not (tmp_path / STD).exists()
        assert not (tmp_path / "kartograf" / "kartograf-store.json").exists()


class TestStepProcessDemUsesDownloadedFiles:
    def test_version_copies_never_reach_mosaic(self, tmp_path):
        std = _touch(tmp_path / "cache" / STD)
        _touch(tmp_path / "cache" / VERSION)
        seen: dict[str, list[Path]] = {}

        def fake_normalize(files, _out):
            seen["files"] = list(files)
            raise _Stop

        with (
            patch("utils.raster_utils.normalize_crs", fake_normalize),
            pytest.raises(_Stop),
        ):
            step_process_dem(
                [std, std],
                output_dir=tmp_path / "data",
                cache_dir=tmp_path / "cache",
            )

        assert seen["files"] == [std]
