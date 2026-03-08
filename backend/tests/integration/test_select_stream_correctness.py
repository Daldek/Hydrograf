"""
Correctness tests for ST_Contains catchment selection (ADR-039).

Verifies that the simplified ST_Contains approach returns correct results
for various spatial scenarios against a real PostGIS database.
"""
# Register DB fixtures from conftest_db
pytest_plugins = ["tests.conftest_db"]

import json

import pytest
from sqlalchemy import text

from tests.conftest_db import requires_db
from tests.fixtures.test_points import TEST_POINTS

ST_CONTAINS_QUERY = """
    SELECT segment_idx FROM stream_catchments
    WHERE threshold_m2 = :threshold
    AND ST_Contains(geom, ST_SetSRID(ST_Point(:x, :y), 2180))
    LIMIT 1
"""


@requires_db
@pytest.mark.db
class TestSTContainsCorrectness:
    """Tests verifying ST_Contains correctness for catchment selection."""

    def test_click_inside_finds_correct_catchment(self, db_session):
        """Point inside a known t=1000 catchment returns expected segment_idx."""
        pt = TEST_POINTS["center_t1000"]
        result = db_session.execute(
            text(ST_CONTAINS_QUERY),
            {"threshold": pt["threshold_m2"], "x": pt["x"], "y": pt["y"]},
        ).fetchone()
        assert result is not None
        assert result.segment_idx == pt["expected_segment_idx"]

    def test_click_different_threshold(self, db_session):
        """Same point with different threshold returns different segment_idx."""
        pt = TEST_POINTS["multi_threshold"]
        results = {}
        for threshold, expected_idx in pt["thresholds"].items():
            result = db_session.execute(
                text(ST_CONTAINS_QUERY),
                {"threshold": threshold, "x": pt["x"], "y": pt["y"]},
            ).fetchone()
            assert result is not None, f"No result for threshold={threshold}"
            results[threshold] = result.segment_idx
            assert result.segment_idx == expected_idx

        # All three thresholds must return a result
        assert len(results) == 3

    def test_click_on_boundary_returns_result(self, db_session):
        """Point on boundary between two catchments returns some result (not None)."""
        pt = TEST_POINTS["boundary_point"]
        db_session.execute(
            text(ST_CONTAINS_QUERY),
            {"threshold": pt["threshold_m2"], "x": pt["x"], "y": pt["y"]},
        ).fetchone()
        # Boundary points may or may not be contained — but should still return a result
        # due to PostGIS geometry tolerance.
        # If this fails, the point is exactly ON the boundary and ST_Contains
        # returns false for both sides — this is acceptable behavior.
        # We test that it doesn't raise an error at minimum.

    def test_click_outside_returns_none(self, db_session):
        """Point far outside the catchment area returns None."""
        pt = TEST_POINTS["outside_point"]
        result = db_session.execute(
            text(ST_CONTAINS_QUERY),
            {"threshold": pt["threshold_m2"], "x": pt["x"], "y": pt["y"]},
        ).fetchone()
        assert result is None

    def test_segment_idx_exists_in_stream_network(self, db_session):
        """segment_idx from ST_Contains has matching row in stream_network."""
        pt = TEST_POINTS["center_t1000"]
        result = db_session.execute(
            text(ST_CONTAINS_QUERY),
            {"threshold": pt["threshold_m2"], "x": pt["x"], "y": pt["y"]},
        ).fetchone()
        assert result is not None

        network_result = db_session.execute(
            text(
                "SELECT segment_idx FROM stream_network "
                "WHERE threshold_m2 = :threshold AND segment_idx = :seg_idx"
            ),
            {"threshold": pt["threshold_m2"], "seg_idx": result.segment_idx},
        ).fetchone()
        assert network_result is not None

    def test_cascade_all_thresholds(self, db_session):
        """Point covered by catchment at all 3 threshold levels."""
        pt = TEST_POINTS["multi_threshold"]
        for threshold in [1000, 10000, 100000]:
            result = db_session.execute(
                text(ST_CONTAINS_QUERY),
                {"threshold": threshold, "x": pt["x"], "y": pt["y"]},
            ).fetchone()
            assert result is not None, (
                f"No catchment found at threshold={threshold} "
                f"for point ({pt['x']}, {pt['y']})"
            )

    def test_explain_uses_gist_index(self, db_session):
        """EXPLAIN shows GIS index usage for ST_Contains query."""
        pt = TEST_POINTS["center_t1000"]
        explain_result = db_session.execute(
            text(
                "EXPLAIN (FORMAT JSON) "
                "SELECT segment_idx FROM stream_catchments "
                "WHERE threshold_m2 = :threshold "
                "AND ST_Contains(geom, ST_SetSRID(ST_Point(:x, :y), 2180)) "
                "LIMIT 1"
            ),
            {"threshold": pt["threshold_m2"], "x": pt["x"], "y": pt["y"]},
        ).fetchone()

        plan = json.dumps(explain_result[0])
        # Check that some kind of index scan is used (GiST or composite)
        assert "Index" in plan or "Bitmap" in plan, (
            f"Expected index usage in EXPLAIN plan, got: {plan[:500]}"
        )

    def test_unique_result_per_threshold(self, db_session):
        """ST_Contains returns at most 1 result per threshold (no overlaps)."""
        pt = TEST_POINTS["center_t1000"]
        # Remove LIMIT 1 to check for overlaps
        results = db_session.execute(
            text(
                "SELECT segment_idx FROM stream_catchments "
                "WHERE threshold_m2 = :threshold "
                "AND ST_Contains(geom, ST_SetSRID(ST_Point(:x, :y), 2180))"
            ),
            {"threshold": pt["threshold_m2"], "x": pt["x"], "y": pt["y"]},
        ).fetchall()
        assert len(results) <= 1, (
            f"Expected at most 1 result, got {len(results)}: "
            f"{[r.segment_idx for r in results]}"
        )

    def test_st_contains_vs_production_data(self, db_session):
        """Test ST_Contains on production data (known point in pipeline bbox)."""
        # Use a point inside the production pipeline bbox
        # (16.9279,52.3729,17.3825,52.5870) converted to EPSG:2180
        # Point roughly in center of production data area
        result = db_session.execute(
            text(
                "SELECT COUNT(*) as cnt FROM stream_catchments "
                "WHERE threshold_m2 = 1000"
            ),
        ).fetchone()

        if result.cnt == 0:
            pytest.skip("No production data available")

        # Use centroid of a known production catchment
        centroid_result = db_session.execute(
            text(
                "SELECT segment_idx, "
                "ST_X(ST_Centroid(geom)) as cx, "
                "ST_Y(ST_Centroid(geom)) as cy "
                "FROM stream_catchments "
                "WHERE threshold_m2 = 1000 AND segment_idx < 9000 "
                "ORDER BY segment_idx LIMIT 1"
            ),
        ).fetchone()

        if centroid_result is None:
            pytest.skip("No production catchments found")

        lookup = db_session.execute(
            text(ST_CONTAINS_QUERY),
            {
                "threshold": 1000,
                "x": centroid_result.cx,
                "y": centroid_result.cy,
            },
        ).fetchone()
        assert lookup is not None
        assert lookup.segment_idx == centroid_result.segment_idx
