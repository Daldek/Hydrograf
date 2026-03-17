"""
Unit tests for boundary smoothing (Chaikin smoothing) in watershed_service.

Verifies that merge helpers use ST_ChaikinSmoothing and
ST_SimplifyPreserveTopology for smooth catchment boundaries
instead of pixel-staircase output.
"""

import inspect

from core.watershed_service import _merge_batched, _merge_direct


class TestMergeCatchmentBoundariesSmoothing:
    """Tests for Chaikin smoothing in merge helpers."""

    def test_merge_direct_uses_chaikin(self):
        """_merge_direct SQL should use ST_ChaikinSmoothing."""
        source = inspect.getsource(_merge_direct)
        assert "ST_ChaikinSmoothing" in source

    def test_merge_batched_uses_chaikin(self):
        """_merge_batched SQL should use ST_ChaikinSmoothing."""
        source = inspect.getsource(_merge_batched)
        assert "ST_ChaikinSmoothing" in source

    def test_merge_direct_uses_simplify(self):
        """_merge_direct SQL should use ST_SimplifyPreserveTopology."""
        source = inspect.getsource(_merge_direct)
        assert "ST_SimplifyPreserveTopology" in source

    def test_merge_direct_no_snap_to_grid(self):
        """_merge_direct SQL should not use ST_SnapToGrid."""
        source = inspect.getsource(_merge_direct)
        assert "ST_SnapToGrid" not in source

    def test_merge_direct_retains_buffer_debuffer(self):
        """_merge_direct SQL should still use buffer-debuffer pattern."""
        source = inspect.getsource(_merge_direct)
        assert "ST_Buffer" in source
