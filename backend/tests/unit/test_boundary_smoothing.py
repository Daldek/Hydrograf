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
    _SMOOTH_SQL,
    _merge_batched,
    _merge_direct,
    _merge_simplified_fallback,
)


class TestMergeCatchmentBoundariesSmoothing:
    """Tests for Chaikin smoothing in merge helpers.

    The smoothing pipeline is defined in _SMOOTH_SQL and used by both
    _merge_direct and _merge_batched via f-string interpolation.
    """

    def test_smooth_sql_uses_chaikin(self):
        """Shared smoothing pipeline should use ST_ChaikinSmoothing."""
        assert "ST_ChaikinSmoothing" in _SMOOTH_SQL

    def test_smooth_sql_uses_simplify(self):
        """Shared smoothing pipeline should use ST_SimplifyPreserveTopology."""
        assert "ST_SimplifyPreserveTopology" in _SMOOTH_SQL

    def test_smooth_sql_uses_buffer(self):
        """Shared smoothing pipeline should use buffer-debuffer pattern."""
        assert "ST_Buffer" in _SMOOTH_SQL

    def test_merge_direct_uses_smooth_sql(self):
        """_merge_direct should reference the shared smoothing pipeline."""
        source = inspect.getsource(_merge_direct)
        assert "_SMOOTH_SQL" in source

    def test_merge_batched_uses_smooth_sql(self):
        """_merge_batched should reference the shared smoothing pipeline."""
        source = inspect.getsource(_merge_batched)
        assert "_SMOOTH_SQL" in source

    def test_merge_direct_no_snap_to_grid(self):
        """_merge_direct does not pre-simplify, so no ST_SnapToGrid."""
        source = inspect.getsource(_merge_direct)
        assert "ST_SnapToGrid" not in source


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

    def test_smooth_sql_uses_buffer_zero(self):
        """Smoothing pipeline should use ST_Buffer(0) instead of ST_MakeValid
        to preserve polygon connectivity after Chaikin smoothing."""
        assert "ST_MakeValid" not in _SMOOTH_SQL
        assert "0))" in _SMOOTH_SQL  # ST_Buffer(..., 0))

    def test_smooth_sql_uses_multi(self):
        """Smoothing pipeline should wrap result as MultiPolygon."""
        assert "ST_Multi(ST_Buffer(" in _SMOOTH_SQL

    def test_merge_batched_pre_union_uses_make_valid(self):
        """_merge_batched pre-union step should use ST_MakeValid(ST_SnapToGrid(...))."""
        source = inspect.getsource(_merge_batched)
        assert "ST_MakeValid(ST_SnapToGrid" in source

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
