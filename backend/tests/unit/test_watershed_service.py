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
    ensure_outlet_within_boundary,
    find_nearest_stream_segment,
    find_nearest_stream_segment_hybrid,
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
    cg.lookup_by_segment_idx.return_value = 0
    cg.trace_main_channel.return_value = {
        "main_channel_length_km": 8.5,
        "main_channel_slope_m_per_m": round((350.0 - 120.0) / (8.5 * 1000), 6),
        "main_channel_nodes": [0, 1, 2],
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
        row.segment_idx = 42
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

    def test_merge_sql_no_snap_to_grid(self):
        """merge_catchment_boundaries SQL should not use ST_SnapToGrid."""
        import inspect

        source = inspect.getsource(merge_catchment_boundaries)
        assert "ST_SnapToGrid" not in source
        assert "ST_Buffer" in source  # buffer-debuffer pattern


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

    def test_removes_small_interior_holes(self):
        """Small interior hole (< MIN_HOLE_AREA_M2) is removed."""
        # Outer ring: 200×200 m
        outer = [(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)]
        # Small hole: ~3×3 m = 9 m² (well below 100 m² threshold)
        hole = [(90, 90), (93, 90), (93, 93), (90, 93), (90, 90)]
        poly = Polygon(outer, [hole])

        assert len(list(poly.interiors)) == 1

        result = boundary_to_polygon(poly)

        assert isinstance(result, Polygon)
        assert len(list(result.interiors)) == 0
        # Area should now be the full outer ring
        assert result.area == pytest.approx(200 * 200, rel=1e-6)

    def test_preserves_large_interior_holes(self):
        """Large interior hole (>= MIN_HOLE_AREA_M2) is preserved."""
        # Outer ring: 200×200 m
        outer = [(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)]
        # Large hole: 50×50 m = 2500 m² (well above 100 m² threshold)
        hole = [(50, 50), (100, 50), (100, 100), (50, 100), (50, 50)]
        poly = Polygon(outer, [hole])

        result = boundary_to_polygon(poly)

        assert isinstance(result, Polygon)
        assert len(list(result.interiors)) == 1
        assert result.area == pytest.approx(200 * 200 - 50 * 50, rel=1e-6)

    def test_polygon_without_holes_unchanged(self):
        """Polygon with no holes passes through without modification."""
        poly = Polygon([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])

        result = boundary_to_polygon(poly)

        assert isinstance(result, Polygon)
        assert len(list(result.interiors)) == 0
        assert result.area == pytest.approx(10000.0, rel=1e-6)

    def test_multipolygon_holes_filtered(self):
        """MultiPolygon: small holes are removed from the largest polygon."""
        # Large polygon with a small hole
        outer1 = [(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)]
        small_hole = [(90, 90), (92, 90), (92, 92), (90, 92), (90, 90)]
        large_poly = Polygon(outer1, [small_hole])

        # Small polygon (no holes)
        small_poly = Polygon(
            [(300, 300), (301, 300), (301, 301), (300, 301), (300, 300)]
        )

        multi = MultiPolygon([small_poly, large_poly])

        result = boundary_to_polygon(multi)

        assert isinstance(result, Polygon)
        # Should be the largest polygon with small hole removed
        assert result.area == pytest.approx(200 * 200, rel=1e-6)
        assert len(list(result.interiors)) == 0


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

    def test_channel_length_uses_main_channel(
        self, mock_catchment_graph, simple_polygon
    ):
        """channel_length_km should come from trace_main_channel, not total network."""
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

        # Main channel = 8.5 km, NOT total network = 18.5 km
        assert result["channel_length_km"] == 8.5
        assert result["channel_length_km"] != 18.5
        # Slope from trace_main_channel
        expected_slope = round((350.0 - 120.0) / (8.5 * 1000), 6)
        assert result["channel_slope_m_per_m"] == expected_slope


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


# ---------------------------------------------------------------------------
# ensure_outlet_within_boundary (E4)
# ---------------------------------------------------------------------------


class TestEnsureOutletWithinBoundary:
    """Tests for ensure_outlet_within_boundary."""

    def test_outlet_inside_unchanged(self):
        """Outlet inside boundary returns unchanged."""
        from shapely.geometry import box

        boundary = box(0, 0, 100, 100)
        x, y = ensure_outlet_within_boundary(50.0, 50.0, boundary)
        assert x == 50.0
        assert y == 50.0

    def test_outlet_outside_snapped(self):
        """Outlet outside boundary is snapped to nearest point."""
        from shapely.geometry import box

        boundary = box(0, 0, 100, 100)
        x, y = ensure_outlet_within_boundary(150.0, 50.0, boundary)
        assert abs(x - 100.0) < 0.01
        assert abs(y - 50.0) < 0.01

    def test_outlet_on_edge_unchanged(self):
        """Outlet within 1m of boundary returns unchanged."""
        from shapely.geometry import box

        boundary = box(0, 0, 100, 100)
        x, y = ensure_outlet_within_boundary(100.5, 50.0, boundary)
        assert x == 100.5  # within 1m tolerance
        assert y == 50.0

    def test_multipolygon_boundary(self):
        """Works with MultiPolygon boundary (uses .boundary not .exterior)."""
        from shapely.geometry import box

        poly1 = box(0, 0, 100, 100)
        poly2 = box(200, 200, 300, 300)
        multi = MultiPolygon([poly1, poly2])
        # Point outside both polygons but closest to poly1
        x, y = ensure_outlet_within_boundary(150.0, 50.0, multi)
        assert abs(x - 100.0) < 0.01
        assert abs(y - 50.0) < 0.01


# ---------------------------------------------------------------------------
# find_nearest_stream_segment_hybrid (F2)
# ---------------------------------------------------------------------------


class TestFindNearestStreamSegmentHybrid:
    """Tests for find_nearest_stream_segment_hybrid."""

    def test_point_inside_catchment_returns_catchment_stream(self):
        """When point is inside a catchment, return that catchment's stream."""
        import inspect

        sig = inspect.signature(find_nearest_stream_segment_hybrid)
        assert "x" in sig.parameters
        assert "y" in sig.parameters
        assert "threshold_m2" in sig.parameters
        assert "db" in sig.parameters

    def test_hybrid_has_catchment_query(self):
        """Hybrid function uses ST_Contains on stream_catchments."""
        import inspect

        source = inspect.getsource(find_nearest_stream_segment_hybrid)
        assert "ST_Contains" in source
        assert "stream_catchments" in source
        assert "find_nearest_stream_segment" in source  # fallback
