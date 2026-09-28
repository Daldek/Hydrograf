"""
Regression tests for scripts/download_dem.py --geometry path handling.

Kartograf's find_sheets_for_geometry() (and the SHP/GPKG readers it calls,
_read_shp_bboxes/_read_gpkg_bboxes) require a pathlib.Path and call
filepath.suffix on it. Passing a plain str crashes with AttributeError.
Both the real download path (download_for_geometry) and the --dry-run
branch in main() must pass a Path, never str(...).
"""

import sys
from pathlib import Path
from unittest.mock import patch

from scripts.download_dem import download_for_geometry, main


class TestDownloadForGeometryPassesPath:
    """download_for_geometry() must call find_sheets_for_geometry with a Path."""

    @patch("scripts.download_dem.download_sheets")
    @patch("kartograf.find_sheets_for_geometry")
    def test_calls_find_sheets_for_geometry_with_path_instance(
        self, mock_find, mock_download_sheets, tmp_path
    ):
        mock_find.return_value = ["M-33-48-D-d-3-1"]
        mock_download_sheets.return_value = [tmp_path / "M-33-48-D-d-3-1.asc"]

        geometry_path = tmp_path / "test.gpkg"
        geometry_path.touch()

        download_for_geometry(geometry_path, output_dir=tmp_path / "out")

        mock_find.assert_called_once()
        passed_path = mock_find.call_args[0][0]
        assert isinstance(passed_path, Path), (
            f"find_sheets_for_geometry must receive a Path, got {type(passed_path)}"
        )
        assert passed_path == geometry_path

    @patch("scripts.download_dem.download_sheets")
    @patch("kartograf.find_sheets_for_geometry")
    def test_does_not_pass_str(self, mock_find, mock_download_sheets, tmp_path):
        """Explicitly guard against the str(geometry_path) regression."""
        mock_find.return_value = []
        geometry_path = tmp_path / "test.gpkg"
        geometry_path.touch()

        download_for_geometry(geometry_path, output_dir=tmp_path / "out")

        passed_path = mock_find.call_args[0][0]
        assert not isinstance(passed_path, str)


class TestMainDryRunPassesPath:
    """main() --dry-run --geometry branch must also call with a Path."""

    @patch("kartograf.find_sheets_for_geometry")
    def test_dry_run_calls_find_sheets_for_geometry_with_path_instance(
        self, mock_find, tmp_path, monkeypatch
    ):
        mock_find.return_value = ["M-33-48-D-d-3-1"]
        geometry_path = tmp_path / "test.gpkg"
        geometry_path.touch()

        monkeypatch.setattr(
            sys,
            "argv",
            ["download_dem.py", "--geometry", str(geometry_path), "--dry-run"],
        )

        main()

        mock_find.assert_called_once()
        passed_path = mock_find.call_args[0][0]
        assert isinstance(passed_path, Path), (
            f"find_sheets_for_geometry must receive a Path, got {type(passed_path)}"
        )
        assert not isinstance(passed_path, str)
