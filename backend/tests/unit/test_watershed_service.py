"""
Unit tests for core.watershed_service module.

Tests cover stream lookup, boundary merging, outlet extraction,
watershed length computation, stream GeoJSON retrieval,
boundary-to-polygon conversion, morphometric dict construction,
and shape index computation.
"""

import math
from unittest.mock import MagicMock

import numpy as np
import pytest
from shapely import wkb
from shapely.geometry import MultiPolygon, Polygon

from core.watershed_service import (
    _compute_shape_indices,
    boundary_to_polygon,
    build_morph_dict_from_graph,
    compute_watershed_length,
    find_nearest_stream_segment,
    get_main_stream_geojson,
    get_segment_outlet,
    merge_catchment_boundaries,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock()


@pytest.fixture
def simple_polygon():
    """A 10x10 square polygon centred at (500100, 600100)."""
    return Polygon(
        [
            (500095, 600095),
            (500105, 600095),
            (500105, 600105),
            (500095, 600105),
            (500095, 600095),
        ]
    )


@pytest.fixture
def simple_multipolygon(simple_polygon):
    """MultiPolygon containing a single polygon."""
    return MultiPolygon([simple_polygon])


@pytest.fixture
def two_poly_multipolygon(simple_polygon):
    """MultiPolygon with two polygons of different areas."""
    small = Polygon(
        [
            (500000, 600000),
            (500001, 600000),
            (500001, 600001),
            (500000, 600001),
            (500000, 600000),
        ]
    )
    return MultiPolygon([small, simple_polygon])


@pytest.fixture
def mock_catchment_graph():
    """Mock CatchmentGraph with aggregate_stats returning known values."""
    cg = MagicMock()
    cg.aggregate_stats.return_value = {
        "area_km2": 45.3,
        "elevation_min_m": 120.0,
        "elevation_max_m": 350.0,
        "elevation_mean_m": 230.0,
        "mean_slope_m_per_m": 0.05,
        "mean_slope_percent": 5.0,
        "stream_length_km": 18.5,
        "drainage_density_km_per_km2": 0.4084,
        "max_strahler_order": 4,
        "stream_frequency_per_km2": 1.92,
    }
    return cg


# ---------------------------------------------------------------------------
# find_nearest_stream_segment
# ---------------------------------------------------------------------------


class TestFindNearestStreamSegment:
    """Tests for find_nearest_stream_segment."""

    def test_returns_dict_when_found(self, mock_db):
        """When DB returns a row, function returns a dict with all expected keys."""
        row = MagicMock()
        row.id = 42
        row.strahler_order = 3
        row.length_m = 1234.5
        row.upstream_area_km2 = 12.3
        row.downstream_x = 500100.0
        row.downstream_y = 600200.0
        mock_db.execute.return_value.fetchone.return_value = row

        result = find_nearest_stream_segment(500050.0, 600050.0, 100, mock_db)

        assert result is not None
        assert result["segment_idx"] == 42
        assert result["strahler_order"] == 3
        assert result["length_m"] == 1234.5
        assert result["upstream_area_km2"] == 12.3
        assert result["downstream_x"] == 500100.0
        assert result["downstream_y"] == 600200.0

    def test_returns_none_when_not_found(self, mock_db):
        """When DB returns None, function returns None."""
        mock_db.execute.return_value.fetchone.return_value = None

        result = find_nearest_stream_segment(500050.0, 600050.0, 100, mock_db)

        assert result is None


# ---------------------------------------------------------------------------
# merge_catchment_boundaries
# ---------------------------------------------------------------------------


class TestMergeCatchmentBoundaries:
    """Tests for merge_catchment_boundaries."""

    def test_returns_multipolygon_from_wkb(self, mock_db, simple_polygon):
        """When DB returns valid WKB, function returns parsed MultiPolygon."""
        multi = MultiPolygon([simple_polygon])
        wkb_bytes = wkb.dumps(multi)

        row = MagicMock()
        row.geom = wkb_bytes
        mock_db.execute.return_value.fetchone.return_value = row

        result = merge_catchment_boundaries([1, 2, 3], 100, mock_db)

        assert result is not None
        assert isinstance(result, MultiPolygon)
        assert result.is_valid
        assert result.area == pytest.approx(multi.area, rel=1e-6)

    def test_returns_none_when_no_geom(self, mock_db):
        """When DB row has None geom, returns None."""
        row = MagicMock()
        row.geom = None
        mock_db.execute.return_value.fetchone.return_value = row

        result = merge_catchment_boundaries([1], 100, mock_db)

        assert result is None

    def test_returns_none_when_no_row(self, mock_db):
        """When DB returns no rows, returns None."""
        mock_db.execute.return_value.fetchone.return_value = None

        result = merge_catchment_boundaries([1], 100, mock_db)

        assert result is None

    def test_returns_none_for_empty_segment_list(self, mock_db):
        """Empty segment_idxs list returns None without querying DB."""
        result = merge_catchment_boundaries([], 100, mock_db)

        assert result is None
        mock_db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# get_segment_outlet
# ---------------------------------------------------------------------------


class TestGetSegmentOutlet:
    """Tests for get_segment_outlet."""

    def test_returns_dict_when_found(self, mock_db):
        """Returns {x, y} dict when segment exists."""
        row = MagicMock()
        row.x = 500100.0
        row.y = 600200.0
        mock_db.execute.return_value.fetchone.return_value = row

        result = get_segment_outlet(42, 100, mock_db)

        assert result == {"x": 500100.0, "y": 600200.0}

    def test_returns_none_when_not_found(self, mock_db):
        """Returns None when segment not found."""
        mock_db.execute.return_value.fetchone.return_value = None

        result = get_segment_outlet(999, 100, mock_db)

        assert result is None


# ---------------------------------------------------------------------------
# compute_watershed_length
# ---------------------------------------------------------------------------


class TestComputeWatershedLength:
    """Tests for compute_watershed_length."""

    def test_with_simple_polygon(self, simple_polygon):
        """Computes max distance from outlet to boundary vertices for Polygon."""
        # Outlet at bottom-left corner (500095, 600095)
        # Farthest vertex is top-right corner (500105, 600105)
        # Distance = sqrt(10^2 + 10^2) = sqrt(200) ~ 14.14 m = 0.01414 km
        length_km = compute_watershed_length(simple_polygon, 500095.0, 600095.0)

        expected = math.sqrt(200) / 1000
        assert length_km == pytest.approx(expected, rel=1e-4)

    def test_with_multipolygon(self, simple_multipolygon):
        """Computes max distance correctly for MultiPolygon."""
        length_km = compute_watershed_length(simple_multipolygon, 500095.0, 600095.0)

        expected = math.sqrt(200) / 1000
        assert length_km == pytest.approx(expected, rel=1e-4)

    def test_outlet_at_centroid(self, simple_polygon):
        """When outlet is at centroid, length is half the diagonal."""
        length_km = compute_watershed_length(simple_polygon, 500100.0, 600100.0)

        # Half-diagonal of 10x10 square = sqrt(50) ~ 7.07 m = 0.00707 km
        expected = math.sqrt(50) / 1000
        assert length_km == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# get_main_stream_geojson
# ---------------------------------------------------------------------------


class TestGetMainStreamGeojson:
    """Tests for get_main_stream_geojson."""

    def test_returns_dict_when_found(self, mock_db):
        """Returns parsed GeoJSON dict when segment exists."""
        row = MagicMock()
        row.geojson = (
            '{"type": "LineString", "coordinates": [[21.0, 52.0], [21.1, 52.1]]}'
        )
        mock_db.execute.return_value.fetchone.return_value = row

        result = get_main_stream_geojson(42, 100, mock_db)

        assert result is not None
        assert result["type"] == "LineString"
        assert len(result["coordinates"]) == 2

    def test_returns_none_when_not_found(self, mock_db):
        """Returns None when segment not found."""
        mock_db.execute.return_value.fetchone.return_value = None

        result = get_main_stream_geojson(999, 100, mock_db)

        assert result is None

    def test_returns_none_when_geojson_null(self, mock_db):
        """Returns None when geojson column is NULL."""
        row = MagicMock()
        row.geojson = None
        mock_db.execute.return_value.fetchone.return_value = row

        result = get_main_stream_geojson(42, 100, mock_db)

        assert result is None


# ---------------------------------------------------------------------------
# boundary_to_polygon
# ---------------------------------------------------------------------------


class TestBoundaryToPolygon:
    """Tests for boundary_to_polygon."""

    def test_polygon_passthrough(self, simple_polygon):
        """Polygon input is returned unchanged."""
        result = boundary_to_polygon(simple_polygon)

        assert result is simple_polygon
        assert isinstance(result, Polygon)

    def test_single_poly_multipolygon(self, simple_multipolygon):
        """MultiPolygon with one polygon returns that polygon."""
        result = boundary_to_polygon(simple_multipolygon)

        assert isinstance(result, Polygon)
        assert result.area == pytest.approx(simple_multipolygon.area, rel=1e-6)

    def test_multi_poly_returns_largest(self, two_poly_multipolygon):
        """MultiPolygon with multiple polygons returns the largest."""
        result = boundary_to_polygon(two_poly_multipolygon)

        assert isinstance(result, Polygon)
        # The larger polygon is the 10x10 square (area=100), not the 1x1 (area=1)
        assert result.area == pytest.approx(100.0, rel=1e-6)


# ---------------------------------------------------------------------------
# build_morph_dict_from_graph
# ---------------------------------------------------------------------------


class TestBuildMorphDictFromGraph:
    """Tests for build_morph_dict_from_graph."""

    def test_returns_all_required_keys(self, mock_catchment_graph, simple_polygon):
        """Output dict contains all keys expected by MorphometricParameters."""
        upstream = np.array([0, 1, 2])

        result = build_morph_dict_from_graph(
            cg=mock_catchment_graph,
            upstream_indices=upstream,
            boundary_2180=simple_polygon,
            outlet_x=500095.0,
            outlet_y=600095.0,
            segment_idx=42,
            threshold_m2=100,
            cn=75,
        )

        # Core keys
        assert "area_km2" in result
        assert "perimeter_km" in result
        assert "length_km" in result
        assert "elevation_min_m" in result
        assert "elevation_max_m" in result
        assert "elevation_mean_m" in result
        assert "mean_slope_m_per_m" in result
        assert "channel_length_km" in result
        assert "channel_slope_m_per_m" in result
        assert "cn" in result
        assert "source" in result
        assert "crs" in result

        # Shape indices
        assert "compactness_coefficient" in result
        assert "circularity_ratio" in result
        assert "elongation_ratio" in result
        assert "form_factor" in result
        assert "mean_width_km" in result

        # Relief indices
        assert "relief_ratio" in result
        assert "hypsometric_integral" in result

        # Drainage indices
        assert "drainage_density_km_per_km2" in result
        assert "stream_frequency_per_km2" in result
        assert "ruggedness_number" in result
        assert "max_strahler_order" in result

    def test_hydrolog_compatibility_values(self, mock_catchment_graph, simple_polygon):
        """Returned values are numerically compatible with Hydrolog."""
        upstream = np.array([0, 1, 2])

        result = build_morph_dict_from_graph(
            cg=mock_catchment_graph,
            upstream_indices=upstream,
            boundary_2180=simple_polygon,
            outlet_x=500095.0,
            outlet_y=600095.0,
            segment_idx=42,
            threshold_m2=100,
            cn=75,
        )

        assert result["area_km2"] == 45.3
        assert result["cn"] == 75
        assert result["source"] == "Hydrograf"
        assert result["crs"] == "EPSG:2180"
        assert result["elevation_min_m"] == 120.0
        assert result["elevation_max_m"] == 350.0
        assert result["elevation_mean_m"] == 230.0
        assert result["mean_slope_m_per_m"] == 0.05
        assert result["max_strahler_order"] == 4

    def test_cn_none_allowed(self, mock_catchment_graph, simple_polygon):
        """CN can be None (optional parameter)."""
        upstream = np.array([0, 1])

        result = build_morph_dict_from_graph(
            cg=mock_catchment_graph,
            upstream_indices=upstream,
            boundary_2180=simple_polygon,
            outlet_x=500095.0,
            outlet_y=600095.0,
            segment_idx=42,
            threshold_m2=100,
            cn=None,
        )

        assert result["cn"] is None

    def test_perimeter_and_length_are_positive(
        self, mock_catchment_graph, simple_polygon
    ):
        """Perimeter and length should be positive for a valid polygon."""
        upstream = np.array([0, 1, 2])

        result = build_morph_dict_from_graph(
            cg=mock_catchment_graph,
            upstream_indices=upstream,
            boundary_2180=simple_polygon,
            outlet_x=500095.0,
            outlet_y=600095.0,
            segment_idx=42,
            threshold_m2=100,
        )

        assert result["perimeter_km"] > 0
        assert result["length_km"] > 0


# ---------------------------------------------------------------------------
# _compute_shape_indices
# ---------------------------------------------------------------------------


class TestComputeShapeIndices:
    """Tests for _compute_shape_indices."""

    def test_valid_inputs(self):
        """Shape indices are computed correctly for valid inputs."""
        area = 45.3
        perimeter = 30.0
        length = 12.0

        result = _compute_shape_indices(area, perimeter, length)

        # Compactness coefficient: P / (2 * sqrt(pi * A))
        expected_kc = perimeter / (2 * math.sqrt(math.pi * area))
        assert result["compactness_coefficient"] == pytest.approx(
            round(expected_kc, 4), rel=1e-4
        )

        # Circularity ratio: 4*pi*A / P^2
        expected_rc = 4 * math.pi * area / (perimeter**2)
        assert result["circularity_ratio"] == pytest.approx(
            round(expected_rc, 4), rel=1e-4
        )

        # Elongation ratio: (2/L) * sqrt(A/pi)
        expected_re = (2 / length) * math.sqrt(area / math.pi)
        assert result["elongation_ratio"] == pytest.approx(
            round(expected_re, 4), rel=1e-4
        )

        # Form factor: A / L^2
        expected_ff = area / (length**2)
        assert result["form_factor"] == pytest.approx(round(expected_ff, 4), rel=1e-4)

        # Mean width: A / L
        expected_w = area / length
        assert result["mean_width_km"] == pytest.approx(round(expected_w, 4), rel=1e-4)

    def test_zero_area_returns_nones(self):
        """When area is zero, all indices should be None."""
        result = _compute_shape_indices(0.0, 10.0, 5.0)

        assert result["compactness_coefficient"] is None
        assert result["circularity_ratio"] is None
        assert result["elongation_ratio"] is None
        assert result["form_factor"] is None
        assert result["mean_width_km"] is None

    def test_zero_perimeter_returns_nones(self):
        """When perimeter is zero, all indices should be None."""
        result = _compute_shape_indices(10.0, 0.0, 5.0)

        assert result["compactness_coefficient"] is None
        assert result["circularity_ratio"] is None
        assert result["elongation_ratio"] is None
        assert result["form_factor"] is None
        assert result["mean_width_km"] is None

    def test_zero_length_returns_nones(self):
        """When length is zero, all indices should be None."""
        result = _compute_shape_indices(10.0, 20.0, 0.0)

        assert result["compactness_coefficient"] is None
        assert result["circularity_ratio"] is None
        assert result["elongation_ratio"] is None
        assert result["form_factor"] is None
        assert result["mean_width_km"] is None
