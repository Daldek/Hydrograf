"""
Unit tests for watershed delineation module.
"""

import pytest
from unittest.mock import MagicMock
from shapely.geometry import Point, Polygon

from core.watershed import (
    FlowCell,
    build_boundary,
    calculate_watershed_area_km2,
    find_nearest_stream,
    traverse_upstream,
    MAX_STREAM_DISTANCE_M,
)


class TestFindNearestStream:
    """Tests for find_nearest_stream function."""

    def test_returns_cell_when_found(self, mock_db, mock_stream_query_result):
        """Test that function returns FlowCell when stream found."""
        mock_db.execute.return_value.fetchone.return_value = mock_stream_query_result

        point = Point(500000, 600000)
        result = find_nearest_stream(point, mock_db)

        assert result is not None
        assert isinstance(result, FlowCell)
        assert result.is_stream is True
        assert result.id == 1

    def test_returns_none_when_not_found(self, mock_db):
        """Test that function returns None when no stream found."""
        mock_db.execute.return_value.fetchone.return_value = None

        point = Point(500000, 600000)
        result = find_nearest_stream(point, mock_db)

        assert result is None

    def test_uses_correct_max_distance(self, mock_db):
        """Test that max_distance parameter is passed correctly."""
        mock_db.execute.return_value.fetchone.return_value = None

        point = Point(500000, 600000)
        find_nearest_stream(point, mock_db, max_distance_m=500)

        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        assert params["max_dist"] == 500

    def test_uses_default_max_distance(self, mock_db):
        """Test that default max distance is used."""
        mock_db.execute.return_value.fetchone.return_value = None

        point = Point(500000, 600000)
        find_nearest_stream(point, mock_db)

        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        assert params["max_dist"] == MAX_STREAM_DISTANCE_M

    def test_passes_point_coordinates(self, mock_db):
        """Test that point coordinates are passed correctly."""
        mock_db.execute.return_value.fetchone.return_value = None

        point = Point(123456.0, 789012.0)
        find_nearest_stream(point, mock_db)

        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        assert params["x"] == 123456.0
        assert params["y"] == 789012.0


class TestTraverseUpstream:
    """Tests for traverse_upstream function."""

    def test_returns_all_cells(self, mock_db, mock_upstream_query_results):
        """Test that function returns all upstream cells."""
        mock_db.execute.return_value.fetchall.return_value = mock_upstream_query_results

        cells = traverse_upstream(1, mock_db)

        assert len(cells) == 4
        assert all(isinstance(c, FlowCell) for c in cells)

    def test_raises_on_too_many_cells(self, mock_db, large_upstream_results):
        """Test that function raises ValueError for large watersheds."""
        mock_db.execute.return_value.fetchall.return_value = large_upstream_results

        with pytest.raises(ValueError, match="too large"):
            traverse_upstream(1, mock_db, max_cells=50)

    def test_passes_outlet_id_correctly(self, mock_db):
        """Test that outlet_id is passed correctly."""
        mock_db.execute.return_value.fetchall.return_value = []

        traverse_upstream(123, mock_db)

        call_args = mock_db.execute.call_args
        params = call_args[0][1]
        assert params["outlet_id"] == 123

    def test_returns_empty_list_when_no_cells(self, mock_db):
        """Test handling of empty result."""
        mock_db.execute.return_value.fetchall.return_value = []

        cells = traverse_upstream(1, mock_db)

        assert cells == []


class TestBuildBoundary:
    """Tests for build_boundary function."""

    def test_convex_hull_returns_polygon(self, sample_cells):
        """Test that convex hull returns valid polygon."""
        boundary = build_boundary(sample_cells, method="convex")

        assert isinstance(boundary, Polygon)
        assert boundary.is_valid

    def test_raises_on_too_few_cells(self):
        """Test that function raises with less than 3 cells."""
        cells = [
            FlowCell(
                id=1,
                x=0,
                y=0,
                elevation=0,
                flow_accumulation=0,
                slope=0,
                downstream_id=None,
                cell_area=25,
                is_stream=True,
            ),
        ]

        with pytest.raises(ValueError, match="at least 3 cells"):
            build_boundary(cells)

    def test_raises_on_two_cells(self):
        """Test that function raises with exactly 2 cells."""
        cells = [
            FlowCell(id=1, x=0, y=0, elevation=0, flow_accumulation=0,
                     slope=0, downstream_id=None, cell_area=25, is_stream=True),
            FlowCell(id=2, x=10, y=0, elevation=0, flow_accumulation=0,
                     slope=0, downstream_id=1, cell_area=25, is_stream=False),
        ]

        with pytest.raises(ValueError, match="at least 3 cells"):
            build_boundary(cells)

    def test_raises_on_invalid_method(self, sample_cells):
        """Test that invalid method raises ValueError."""
        with pytest.raises(ValueError, match="Unknown method"):
            build_boundary(sample_cells, method="invalid")

    def test_concave_hull_returns_polygon(self, sample_cells):
        """Test concave hull method with enough cells."""
        # Add more cells for concave hull to work properly
        extra_cells = [
            FlowCell(
                id=5,
                x=500005.0,
                y=600005.0,
                elevation=155.0,
                flow_accumulation=100,
                slope=2.0,
                downstream_id=3,
                cell_area=25.0,
                is_stream=False,
            ),
            FlowCell(
                id=6,
                x=500010.0,
                y=600005.0,
                elevation=156.0,
                flow_accumulation=50,
                slope=2.1,
                downstream_id=5,
                cell_area=25.0,
                is_stream=False,
            ),
        ]
        cells = sample_cells + extra_cells

        boundary = build_boundary(cells, method="concave")

        assert isinstance(boundary, Polygon)
        assert boundary.is_valid

    def test_boundary_contains_points(self, sample_cells):
        """Test that boundary contains the cell points."""
        boundary = build_boundary(sample_cells, method="convex")

        # Check that centroid of cells is inside boundary
        centroid_x = sum(c.x for c in sample_cells) / len(sample_cells)
        centroid_y = sum(c.y for c in sample_cells) / len(sample_cells)

        assert boundary.contains(Point(centroid_x, centroid_y))


class TestCalculateWatershedArea:
    """Tests for calculate_watershed_area_km2 function."""

    def test_calculates_area_correctly(self, sample_cells):
        """Test area calculation."""
        # 4 cells * 25 m² = 100 m² = 0.0001 km²
        area = calculate_watershed_area_km2(sample_cells)

        assert area == pytest.approx(0.0001, rel=1e-6)

    def test_empty_cells_returns_zero(self):
        """Test that empty cell list returns zero area."""
        area = calculate_watershed_area_km2([])

        assert area == 0.0

    def test_single_cell(self):
        """Test area calculation for single cell."""
        cells = [
            FlowCell(
                id=1,
                x=0,
                y=0,
                elevation=0,
                flow_accumulation=0,
                slope=0,
                downstream_id=None,
                cell_area=1_000_000,  # 1 km²
                is_stream=True,
            ),
        ]

        area = calculate_watershed_area_km2(cells)

        assert area == pytest.approx(1.0, rel=1e-6)

    def test_large_watershed(self):
        """Test area calculation for larger watershed."""
        # 100 cells * 10000 m² = 1,000,000 m² = 1 km²
        cells = [
            FlowCell(
                id=i,
                x=i * 100,
                y=0,
                elevation=0,
                flow_accumulation=0,
                slope=0,
                downstream_id=i - 1 if i > 0 else None,
                cell_area=10000,
                is_stream=i == 0,
            )
            for i in range(100)
        ]

        area = calculate_watershed_area_km2(cells)

        assert area == pytest.approx(1.0, rel=1e-6)


class TestFlowCellDataclass:
    """Tests for FlowCell dataclass."""

    def test_create_flow_cell(self):
        """Test FlowCell creation."""
        cell = FlowCell(
            id=1,
            x=500000.0,
            y=600000.0,
            elevation=150.0,
            flow_accumulation=1000,
            slope=2.5,
            downstream_id=None,
            cell_area=25.0,
            is_stream=True,
        )

        assert cell.id == 1
        assert cell.x == 500000.0
        assert cell.y == 600000.0
        assert cell.elevation == 150.0
        assert cell.flow_accumulation == 1000
        assert cell.slope == 2.5
        assert cell.downstream_id is None
        assert cell.cell_area == 25.0
        assert cell.is_stream is True

    def test_flow_cell_with_downstream(self):
        """Test FlowCell with downstream_id set."""
        cell = FlowCell(
            id=2,
            x=500005.0,
            y=600000.0,
            elevation=152.0,
            flow_accumulation=500,
            slope=3.0,
            downstream_id=1,
            cell_area=25.0,
            is_stream=False,
        )

        assert cell.downstream_id == 1
        assert cell.is_stream is False
