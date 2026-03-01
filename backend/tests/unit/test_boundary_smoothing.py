"""
Unit tests for boundary smoothing (Chaikin smoothing) in watershed_service.

Verifies that merge_catchment_boundaries uses ST_ChaikinSmoothing
and ST_SimplifyPreserveTopology for smooth catchment boundaries
instead of pixel-staircase output.
"""

import inspect

from core.watershed_service import merge_catchment_boundaries


class TestMergeCatchmentBoundariesSmoothing:
    """Tests for Chaikin smoothing in merge_catchment_boundaries."""

    def test_merge_query_uses_chaikin(self):
        """merge_catchment_boundaries SQL should use ST_ChaikinSmoothing."""
        source = inspect.getsource(merge_catchment_boundaries)
        assert "ST_ChaikinSmoothing" in source

    def test_merge_query_uses_simplify(self):
        """merge_catchment_boundaries SQL should use ST_SimplifyPreserveTopology."""
        source = inspect.getsource(merge_catchment_boundaries)
        assert "ST_SimplifyPreserveTopology" in source

    def test_merge_query_no_snap_to_grid(self):
        """merge_catchment_boundaries SQL should not use ST_SnapToGrid."""
        source = inspect.getsource(merge_catchment_boundaries)
        assert "ST_SnapToGrid" not in source

    def test_merge_query_retains_buffer_debuffer(self):
        """merge_catchment_boundaries SQL should still use buffer-debuffer pattern."""
        source = inspect.getsource(merge_catchment_boundaries)
        assert "ST_Buffer" in source
