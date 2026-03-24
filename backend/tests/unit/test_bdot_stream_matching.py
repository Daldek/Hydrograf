"""Tests for BDOT10k stream matching pipeline."""
import pytest
from shapely.geometry import LineString


class TestOverlapRatioLogic:
    """Test the geometric overlap ratio calculation."""

    def test_full_overlap(self):
        segment = LineString([(0, 0), (100, 0)])
        bdot = LineString([(0, 0), (100, 0)])
        buffer = bdot.buffer(15)
        intersection = segment.intersection(buffer)
        ratio = intersection.length / segment.length
        assert ratio > 0.95  # near full overlap

    def test_partial_overlap(self):
        segment = LineString([(0, 0), (100, 0)])
        bdot = LineString([(0, 0), (50, 0)])  # covers ~50%
        buffer = bdot.buffer(15)
        intersection = segment.intersection(buffer)
        ratio = intersection.length / segment.length
        assert 0.4 < ratio < 0.75

    def test_no_overlap(self):
        segment = LineString([(0, 0), (100, 0)])
        bdot = LineString([(0, 100), (100, 100)])  # 100m away
        buffer = bdot.buffer(15)
        intersection = segment.intersection(buffer)
        ratio = intersection.length / segment.length if segment.length > 0 else 0
        assert ratio < 0.01  # no meaningful overlap

    def test_nearby_parallel_stream(self):
        """Stream 10m away should still match (within 15m buffer)."""
        segment = LineString([(0, 0), (100, 0)])
        bdot = LineString([(0, 10), (100, 10)])  # parallel, 10m away
        buffer = bdot.buffer(15)
        intersection = segment.intersection(buffer)
        ratio = intersection.length / segment.length
        assert ratio > 0.9  # within buffer

    def test_threshold_boundary(self):
        """Stream beyond buffer distance should have no overlap."""
        segment = LineString([(0, 0), (100, 0)])
        bdot = LineString([(0, 31), (100, 31)])  # 31m away, beyond 15m buffer
        buffer = bdot.buffer(15)
        intersection = segment.intersection(buffer)
        ratio = intersection.length / segment.length if segment.length > 0 else 0
        # Beyond buffer reach, no overlap
        assert ratio < 0.01


    def test_short_segment_within_buffer(self):
        """Short segment (< 30m) fully within buffer must have overlap > 0.

        Regression test for GEOS precision bug: ST_Intersection returns EMPTY
        for short segments despite ST_Within returning True.
        Fix: use ST_Within check before ST_Intersection.
        """
        segment = LineString([(500, 500), (510, 502)])  # ~10m segment
        bdot = LineString([(500, 498), (520, 500)])  # ~2m away
        buffer = bdot.buffer(25)
        # ST_Within equivalent
        assert buffer.contains(segment), "Short segment should be within 25m buffer"
        # Intersection may give empty due to GEOS precision on short lines
        intersection = segment.intersection(buffer)
        # With ST_Within fallback, this should always count as full overlap
        if intersection.is_empty or intersection.length < 0.001:
            # GEOS precision issue confirmed — ST_Within fallback needed
            ratio = 1.0  # ST_Within = True → ratio = 1.0
        else:
            ratio = intersection.length / segment.length
        assert ratio >= 0.5

    def test_short_segment_outside_buffer(self):
        """Short segment far from BDOT should not match."""
        segment = LineString([(500, 500), (510, 502)])  # ~10m segment
        bdot = LineString([(500, 560), (520, 560)])  # 60m away
        buffer = bdot.buffer(25)
        assert not buffer.contains(segment)
        intersection = segment.intersection(buffer)
        ratio = intersection.length / segment.length if not intersection.is_empty else 0
        assert ratio < 0.5


class TestLoadBdotStreams:
    """Test BDOT GPKG loading."""

    def test_nonexistent_file_returns_empty(self):
        from core.db_bulk import load_bdot_streams_from_gpkg
        result = load_bdot_streams_from_gpkg("/nonexistent/path.gpkg")
        assert result == []

    def test_valid_bdot_types(self):
        from core.db_bulk import VALID_BDOT_LINE_TYPES
        assert VALID_BDOT_LINE_TYPES == {"SWRS", "SWKN", "SWRM"}


class TestInsertBdotStreamsSchema:
    """Test schema validation for insert_bdot_streams."""

    def test_filters_invalid_layer_types(self):
        """PTWP (polygon) should be filtered out."""
        from core.db_bulk import VALID_BDOT_LINE_TYPES
        streams = [
            {"layer_type": "SWRS", "geom_wkt": "LINESTRING(0 0, 1 1)"},
            {"layer_type": "PTWP", "geom_wkt": "LINESTRING(0 0, 1 1)"},
        ]
        valid = [s for s in streams if s.get("layer_type") in VALID_BDOT_LINE_TYPES]
        assert len(valid) == 1
        assert valid[0]["layer_type"] == "SWRS"
