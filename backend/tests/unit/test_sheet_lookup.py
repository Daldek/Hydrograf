"""Tests for utils/sheet_lookup.py: NMT sheet lookup for a point via Kartograf.

utils/sheet_finder.py reimplemented the Polish map-sheet (godlo) math and was
wrong at 1:10000: it split a 1:25000 sheet into 2 rows x 4 cols instead of
Kartograf/GUGiK's nested 2x2 subdivision. sheets_for_point_buffer() replaces
it by delegating to kartograf.find_sheets_for_bbox().

Verified divergence: for bbox lat 52.40-52.42, lon 16.90-16.93, the old
sheet_finder returned N-33-130-D-b-2-1..2-3 / N-33-130-D-d-1-1..1-3, while
Kartograf's find_sheets_for_bbox() returns sheets including
N-33-130-D-b-3-3, which the old code never produced.
"""

from utils.sheet_lookup import sheets_for_point_buffer


class TestSheetsForPointBufferDivergentFromSheetFinder:
    """Point/buffer chosen to reproduce the sheet_finder 1:10000 bug."""

    def test_includes_sheet_sheet_finder_never_returns(self):
        """Kartograf splits 1:25000 into nested 2x2, so b-3-3 is reachable."""
        sheets = sheets_for_point_buffer(52.41, 16.915, buffer_km=2.0)

        assert "N-33-130-D-b-3-3" in sheets

    def test_matches_kartograf_find_sheets_for_bbox_directly(self):
        """Full result matches Kartograf, not the old duplicated 2x4 split."""
        sheets = sheets_for_point_buffer(52.41, 16.915, buffer_km=2.0)

        assert sheets == sorted(
            [
                "N-33-130-D-b-3-3",
                "N-33-130-D-b-3-4",
                "N-33-130-D-b-4-3",
                "N-33-130-D-d-1-1",
                "N-33-130-D-d-1-2",
                "N-33-130-D-d-1-3",
                "N-33-130-D-d-1-4",
                "N-33-130-D-d-2-1",
                "N-33-130-D-d-2-3",
            ]
        )

    def test_old_sheet_finder_codes_are_absent(self):
        """The wrong 2x4-derived codes from sheet_finder must not appear."""
        sheets = sheets_for_point_buffer(52.41, 16.915, buffer_km=2.0)

        assert "N-33-130-D-b-2-1" not in sheets
        assert "N-33-130-D-b-2-2" not in sheets
        assert "N-33-130-D-b-2-3" not in sheets


class TestSheetsForPointBufferInsideCacheSheet:
    """A point centered in a real cache sheet must resolve to just that sheet."""

    def test_point_inside_cache_sheet_returns_that_sheet(self):
        """N-34-139-A-c-4-1 mirrors real cache dir cache/nmt/nmt_1m/N-34/139/A/c/4/1."""
        from kartograf import SheetParser

        godlo = "N-34-139-A-c-4-1"
        bbox_wgs84 = SheetParser(godlo).get_bbox(crs="EPSG:4326")
        center_lat = (bbox_wgs84.min_y + bbox_wgs84.max_y) / 2
        center_lon = (bbox_wgs84.min_x + bbox_wgs84.max_x) / 2

        sheets = sheets_for_point_buffer(center_lat, center_lon, buffer_km=0.01)

        assert sheets == [godlo]


class TestSheetsForPointBufferZero:
    """buffer_km=0 (or a tiny buffer) must resolve to a single covering sheet."""

    def test_zero_buffer_returns_single_sheet(self):
        sheets = sheets_for_point_buffer(52.4, 16.9, buffer_km=0.0)

        assert sheets == ["N-33-130-D-d-1-1"]

    def test_zero_buffer_result_has_length_one(self):
        sheets = sheets_for_point_buffer(52.4, 16.9, buffer_km=0.0)

        assert len(sheets) == 1
