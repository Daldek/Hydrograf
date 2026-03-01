"""Tests for utils/sheet_finder.py: map sheet code conversion utilities."""

import pytest

from utils.sheet_finder import (
    coordinates_to_sheet_code,
    get_neighboring_sheets,
    get_sheet_bounds,
    get_sheets_for_bbox,
    get_sheets_for_point_with_buffer,
)


class TestCoordinatesToSheetCode:
    """Tests for coordinates_to_sheet_code()."""

    def test_poznan(self):
        """Poznan (52.4, 16.9) returns a valid sheet code."""
        code = coordinates_to_sheet_code(52.4, 16.9)
        assert isinstance(code, str)
        assert code.startswith("N-")
        # Default scale is 1:10000, so code should have 7 parts
        assert len(code.split("-")) == 7

    def test_warszawa(self):
        """Warszawa (52.2, 21.0) returns a valid sheet code."""
        code = coordinates_to_sheet_code(52.2, 21.0)
        assert isinstance(code, str)
        assert code.startswith("N-")
        assert len(code.split("-")) == 7

    def test_same_point_returns_same_code(self):
        """Same coordinates always return the same sheet code."""
        code1 = coordinates_to_sheet_code(52.4, 16.9)
        code2 = coordinates_to_sheet_code(52.4, 16.9)
        assert code1 == code2

    def test_different_points_may_differ(self):
        """Sufficiently distant points return different sheet codes."""
        code_poz = coordinates_to_sheet_code(52.4, 16.9)
        code_waw = coordinates_to_sheet_code(52.2, 21.0)
        assert code_poz != code_waw

    def test_out_of_poland_raises(self):
        """Coordinates outside Poland raise ValueError."""
        with pytest.raises(ValueError, match="outside Poland"):
            coordinates_to_sheet_code(40.0, 10.0)  # Italy

    def test_out_of_poland_north_raises(self):
        """Coordinates north of Poland raise ValueError."""
        with pytest.raises(ValueError, match="outside Poland"):
            coordinates_to_sheet_code(60.0, 20.0)  # Scandinavia

    def test_scale_1_100000(self):
        """Scale 1:100000 returns a 3-part code."""
        code = coordinates_to_sheet_code(52.2, 21.0, scale="1:100000")
        parts = code.split("-")
        assert len(parts) == 3

    def test_scale_1_50000(self):
        """Scale 1:50000 returns a 4-part code."""
        code = coordinates_to_sheet_code(52.2, 21.0, scale="1:50000")
        parts = code.split("-")
        assert len(parts) == 4

    def test_scale_1_25000(self):
        """Scale 1:25000 returns a 5-part code."""
        code = coordinates_to_sheet_code(52.2, 21.0, scale="1:25000")
        parts = code.split("-")
        assert len(parts) == 5

    def test_invalid_scale_raises(self):
        """Invalid scale string raises ValueError."""
        with pytest.raises(ValueError, match="Invalid scale"):
            coordinates_to_sheet_code(52.2, 21.0, scale="1:5000")

    def test_warsaw_known_code(self):
        """Verify Warszawa (52.23, 21.01) produces a consistent code."""
        code = coordinates_to_sheet_code(52.23, 21.01)
        # Actual output from the implementation
        assert code == "N-34-139-A-c-1-1"


class TestGetSheetBounds:
    """Tests for get_sheet_bounds()."""

    def test_returns_four_values(self):
        """get_sheet_bounds returns a SheetBounds with min/max lat/lon."""
        code = coordinates_to_sheet_code(52.2, 21.0)
        bounds = get_sheet_bounds(code)
        assert hasattr(bounds, "min_lat")
        assert hasattr(bounds, "max_lat")
        assert hasattr(bounds, "min_lon")
        assert hasattr(bounds, "max_lon")

    def test_bounds_contain_original_point(self):
        """The bounds of the sheet should contain the original point."""
        lat, lon = 52.4, 16.9
        code = coordinates_to_sheet_code(lat, lon)
        bounds = get_sheet_bounds(code)
        assert bounds.min_lat <= lat < bounds.max_lat
        assert bounds.min_lon <= lon < bounds.max_lon

    def test_positive_area(self):
        """Sheet bounds should have positive area."""
        code = coordinates_to_sheet_code(52.2, 21.0)
        bounds = get_sheet_bounds(code)
        lat_size = bounds.max_lat - bounds.min_lat
        lon_size = bounds.max_lon - bounds.min_lon
        assert lat_size > 0
        assert lon_size > 0

    def test_1m_scale_bounds(self):
        """Bounds for 1:1M code have correct geographic extent."""
        code = coordinates_to_sheet_code(52.2, 21.0, scale="1:1000000")
        bounds = get_sheet_bounds(code)
        lat_size = bounds.max_lat - bounds.min_lat
        lon_size = bounds.max_lon - bounds.min_lon
        assert abs(lat_size - 4.0) < 0.001  # 4 degrees lat
        assert abs(lon_size - 6.0) < 0.001  # 6 degrees lon

    def test_invalid_code_raises(self):
        """Invalid sheet code raises ValueError."""
        with pytest.raises(ValueError, match="Invalid sheet code"):
            get_sheet_bounds("X")

    def test_roundtrip_consistency(self):
        """Bounds center, when converted back, gives the same sheet code."""
        lat, lon = 52.3, 17.5
        code = coordinates_to_sheet_code(lat, lon)
        bounds = get_sheet_bounds(code)
        center_lat, center_lon = bounds.center
        code_from_center = coordinates_to_sheet_code(center_lat, center_lon)
        assert code == code_from_center


class TestGetSheetsForBbox:
    """Tests for get_sheets_for_bbox()."""

    def test_single_sheet_bbox(self):
        """A tiny bbox within a single sheet returns at least 1 sheet."""
        # Use a known sheet center
        bounds = get_sheet_bounds("N-34-131-C-c-2-1")
        center_lat, center_lon = bounds.center
        # Very small bbox within one sheet
        delta = 0.001
        sheets = get_sheets_for_bbox(
            center_lat - delta,
            center_lon - delta,
            center_lat + delta,
            center_lon + delta,
        )
        assert len(sheets) >= 1

    def test_larger_bbox_returns_more(self):
        """A larger bbox returns more sheets than a smaller one."""
        sheets_small = get_sheets_for_bbox(52.2, 21.0, 52.21, 21.01)
        sheets_large = get_sheets_for_bbox(52.0, 20.5, 52.5, 21.5)
        assert len(sheets_large) >= len(sheets_small)

    def test_returns_strings(self):
        """All returned items are strings."""
        sheets = get_sheets_for_bbox(52.2, 21.0, 52.25, 21.1)
        assert all(isinstance(s, str) for s in sheets)

    def test_returns_sorted(self):
        """Result list is sorted."""
        sheets = get_sheets_for_bbox(52.2, 21.0, 52.25, 21.1)
        assert sheets == sorted(sheets)

    def test_scale_100k_fewer_sheets(self):
        """At 1:100000 scale, same bbox returns fewer sheets."""
        sheets_10k = get_sheets_for_bbox(52.0, 20.5, 52.5, 21.5, scale="1:10000")
        sheets_100k = get_sheets_for_bbox(52.0, 20.5, 52.5, 21.5, scale="1:100000")
        assert len(sheets_100k) <= len(sheets_10k)


class TestGetNeighboringSheets:
    """Tests for get_neighboring_sheets()."""

    def test_returns_list(self):
        """Result is a list."""
        neighbors = get_neighboring_sheets("N-34-131-C-c-2-2")
        assert isinstance(neighbors, list)

    def test_at_least_4_neighbors(self):
        """An interior sheet has at least 4 neighbors (cardinal directions)."""
        # Use a sheet well inside Poland
        neighbors = get_neighboring_sheets("N-34-131-C-c-2-2")
        assert len(neighbors) >= 4

    def test_does_not_include_self(self):
        """Self is not included in the neighbor list."""
        code = "N-34-131-C-c-2-2"
        neighbors = get_neighboring_sheets(code)
        assert code not in neighbors

    def test_with_diagonals_more_than_without(self):
        """Including diagonals returns >= neighbors without diagonals."""
        code = "N-34-131-C-c-2-2"
        with_diag = get_neighboring_sheets(code, include_diagonals=True)
        without_diag = get_neighboring_sheets(code, include_diagonals=False)
        assert len(with_diag) >= len(without_diag)

    def test_neighbors_are_strings(self):
        """All neighbors are string sheet codes."""
        neighbors = get_neighboring_sheets("N-34-131-C-c-2-2")
        assert all(isinstance(n, str) for n in neighbors)

    def test_neighbors_sorted_unique(self):
        """Neighbors are sorted and unique."""
        neighbors = get_neighboring_sheets("N-34-131-C-c-2-2")
        assert neighbors == sorted(set(neighbors))


class TestGetSheetsForPointWithBuffer:
    """Tests for get_sheets_for_point_with_buffer()."""

    def test_returns_list(self):
        """Result is a list of sheet codes."""
        sheets = get_sheets_for_point_with_buffer(52.23, 21.01, buffer_km=5.0)
        assert isinstance(sheets, list)
        assert len(sheets) >= 1

    def test_larger_buffer_returns_more_or_equal(self):
        """Larger buffer returns more or equal number of sheets."""
        sheets_small = get_sheets_for_point_with_buffer(
            52.23, 21.01, buffer_km=2.0
        )
        sheets_large = get_sheets_for_point_with_buffer(
            52.23, 21.01, buffer_km=20.0
        )
        assert len(sheets_large) >= len(sheets_small)

    def test_zero_buffer(self):
        """Zero buffer returns at least 1 sheet (the point's own sheet)."""
        sheets = get_sheets_for_point_with_buffer(52.23, 21.01, buffer_km=0.0)
        assert len(sheets) >= 1

    def test_returns_strings(self):
        """All items are strings."""
        sheets = get_sheets_for_point_with_buffer(52.23, 21.01, buffer_km=5.0)
        assert all(isinstance(s, str) for s in sheets)
