"""Bootstrap kroki 2-3 z Kartografem 0.7.0: uklad danych, brak duplikatow kampanii."""

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.bootstrap import step_download_nmt, step_process_dem
from scripts.download_dem import NmtDownloadReport

STD = "nmt/pl_1992_5m_evrf2007/N-33/130/D/d/1/1/N-33-130-D-d-1-1.asc"
CAMPAIGN = (
    "nmt/pl_1992_5m_evrf2007/kampanie/2025-09-09_83980/"
    "N-33/130/D/d/1/1/N-33-130-D-d-1-1.asc"
)


class _Stop(Exception):
    pass


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("ncols 1\n")
    return path


class TestStepDownloadNmt:
    def test_cache_dir_is_kartograf_data_root(self, tmp_path):
        std = tmp_path / STD
        report = NmtDownloadReport(paths=[std], no_coverage=["N-35-1-A-a-1-1"])
        with patch(
            "scripts.download_dem.download_sheets", return_value=report
        ) as mock_dl:
            paths, detail = step_download_nmt(
                ["N-33-130-D-d-1-1", "N-35-1-A-a-1-1"], tmp_path, resolution="5m"
            )

        args, kwargs = mock_dl.call_args
        assert args[1] == tmp_path
        assert args[2] == tmp_path / "kartograf_meta.db"
        assert kwargs["resolution"] == "5m"
        assert paths == [std]
        assert "1/2 arkuszy" in detail
        assert "1 bez pokrycia" in detail


class TestStepProcessDemUsesDownloadedFiles:
    def test_campaign_copies_never_reach_mosaic(self, tmp_path):
        std = _touch(tmp_path / "cache" / STD)
        _touch(tmp_path / "cache" / CAMPAIGN)
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
