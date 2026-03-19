"""
Unit tests for boundary smoothing (Chaikin smoothing) in watershed_service.

Verifies that merge helpers use ST_ChaikinSmoothing and
ST_SimplifyPreserveTopology for smooth catchment boundaries
instead of pixel-staircase output.

Also verifies topology-preserving changes:
- _merge_batched uses ST_SnapToGrid (not ST_SimplifyPreserveTopology)
  for pre-union vertex reduction to preserve shared edges
- ST_Buffer(0) used instead of ST_MakeValid to preserve connectivity
"""

import inspect

from core.watershed_service import (
    _merge_batched,
    _merge_direct,
    _merge_simplified_fallback,
)


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
        """_merge_direct does not pre-simplify, so no ST_SnapToGrid."""
        source = inspect.getsource(_merge_direct)
        assert "ST_SnapToGrid" not in source

    def test_merge_direct_retains_buffer_debuffer(self):
        """_merge_direct SQL should still use buffer-debuffer pattern."""
        source = inspect.getsource(_merge_direct)
        assert "ST_Buffer" in source


class TestMergeTopologyPreservation:
    """Tests for topology-preserving merge (gap closing, connectivity)."""

    def test_merge_batched_uses_snap_to_grid(self):
        """_merge_batched should use ST_SnapToGrid (not simplify) for
        pre-union vertex reduction to preserve shared edges."""
        source = inspect.getsource(_merge_batched)
        assert "ST_SnapToGrid" in source

    def test_merge_batched_no_pre_simplify(self):
        """_merge_batched should NOT pre-simplify individual polygons
        before union (destroys shared edges → gaps)."""
        source = inspect.getsource(_merge_batched)
        # The only ST_SimplifyPreserveTopology should be AFTER union
        # (in the smoothing pipeline), not on individual geom rows
        lines = source.split("\n")
        pre_union_simplify = any(
            "ST_SimplifyPreserveTopology(geom" in line for line in lines
        )
        assert not pre_union_simplify

    def test_merge_direct_uses_buffer_zero(self):
        """_merge_direct should use ST_Buffer(0) instead of ST_MakeValid
        to preserve polygon connectivity after Chaikin smoothing."""
        source = inspect.getsource(_merge_direct)
        assert "ST_MakeValid" not in source
        assert "0))" in source  # ST_Buffer(..., 0))

    def test_merge_batched_uses_buffer_zero(self):
        """_merge_batched should use ST_Buffer(0) instead of ST_MakeValid
        in the final smoothing pipeline."""
        source = inspect.getsource(_merge_batched)
        # ST_MakeValid is OK in the pre-union SnapToGrid step,
        # but not as the final topology fixer
        assert "ST_MakeValid(ST_SnapToGrid" in source
        # Final wrapping should be ST_Buffer(..., 0), not ST_MakeValid
        assert "ST_Multi(ST_Buffer(" in source

    def test_merge_fallback_uses_snap_to_grid(self):
        """_merge_simplified_fallback should use ST_SnapToGrid (not
        ST_SimplifyPreserveTopology) to preserve shared edges."""
        source = inspect.getsource(_merge_simplified_fallback)
        assert "ST_SnapToGrid" in source
        assert "ST_SimplifyPreserveTopology" not in source

    def test_merge_fallback_uses_buffer_zero(self):
        """_merge_simplified_fallback should use ST_Buffer(0) to
        preserve connectivity."""
        source = inspect.getsource(_merge_simplified_fallback)
        assert "ST_MakeValid" in source  # inside SnapToGrid
        assert "ST_Multi(ST_Buffer(" in source
