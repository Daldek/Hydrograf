"""Bootstrap --bbox z Kartografem 0.7.0: walidacja i semantyka krawedzi arkuszy."""

import sys

import pytest
from kartograf import SheetParser

from scripts.bootstrap import main, parse_bbox, resolve_sheets


class TestParseBboxOrder:
    def test_reversed_lon_raises(self):
        with pytest.raises(ValueError, match="min_lon"):
            parse_bbox("21.2,52.1,20.8,52.4")

    def test_reversed_lat_raises(self):
        with pytest.raises(ValueError, match="min_lat"):
            parse_bbox("20.8,52.4,21.2,52.1")

    def test_degenerate_bbox_raises(self):
        with pytest.raises(ValueError, match="min_lon"):
            parse_bbox("20.8,52.1,20.8,52.4")


class TestResolveSheetsEdgeSemantics:
    def test_bbox_equal_to_sheet_returns_only_that_sheet(self):
        """Kartograf 0.7.0: stykajace sie krawedzie nie sa przecieciem (0.6.1: 4)."""
        godlo = "N-34-130-D-d-2-4"
        b = SheetParser(godlo).get_bbox(crs="EPSG:4326")
        bbox = (b.min_x, b.min_y, b.max_x, b.max_y)

        sheets, _ = resolve_sheets(bbox, None, "1:10000")

        assert sheets == [godlo]


class TestMainRejectsBadBbox:
    def test_reversed_bbox_is_cli_error(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "bootstrap",
                "--bbox", "21.2,52.1,20.8,52.4",
                "--output", str(tmp_path / "data"),
                "--cache-dir", str(tmp_path / "cache"),
                "--dry-run",
            ],
        )

        with pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 2
        assert "min_lon" in capsys.readouterr().err

    def test_invalid_sheet_code_is_cli_error(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "bootstrap",
                "--sheets", "abc",
                "--output", str(tmp_path / "data"),
                "--cache-dir", str(tmp_path / "cache"),
                "--dry-run",
            ],
        )

        with pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 2
        assert "abc" in capsys.readouterr().err
