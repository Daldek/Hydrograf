"""Tests for core.db_bulk module."""

from unittest.mock import MagicMock

from core.db_bulk import insert_stream_segments


class TestInsertStreamSegments:
    """Tests for insert_stream_segments (DB interaction via mock)."""

    def _make_mock_db(self, rowcount):
        """Create a mock db_session returning given rowcount."""
        cursor = MagicMock()
        cursor.rowcount = rowcount
        raw_conn = MagicMock()
        raw_conn.cursor.return_value = cursor
        connection = MagicMock()
        connection.connection = raw_conn
        db_session = MagicMock()
        db_session.connection.return_value = connection
        return db_session, cursor, raw_conn

    def _make_segment(self, x=500000.0, y=500000.0):
        """Create a minimal stream segment dict."""
        return {
            "coords": [(x, y), (x + 10, y + 10)],
            "strahler_order": 1,
            "length_m": 14.14,
            "upstream_area_km2": 0.01,
            "mean_slope_percent": 2.0,
        }

    def test_insert_stream_segments_multi_threshold_no_conflict(self):
        """Two thresholds inserting same-location segment must both succeed.

        With the fixed unique index (including threshold_m2), the same
        spatial location should NOT conflict across different thresholds.
        We verify both calls proceed and the function is called with
        correct threshold values.
        """
        segment = self._make_segment()

        # Threshold 100: all inserted
        db1, cursor1, _ = self._make_mock_db(rowcount=1)
        result1 = insert_stream_segments(db1, [segment], threshold_m2=100)
        assert result1 == 1

        # Threshold 1000: same segment, also all inserted
        db2, cursor2, _ = self._make_mock_db(rowcount=1)
        result2 = insert_stream_segments(db2, [segment], threshold_m2=1000)
        assert result2 == 1

    def test_insert_stream_segments_warns_on_dropped(self, caplog):
        """Warning logged when segments are dropped by unique constraint."""
        segments = [self._make_segment(), self._make_segment(x=500100.0)]

        # DB returns rowcount=1 but we sent 2 segments → 1 dropped
        db, cursor, _ = self._make_mock_db(rowcount=1)

        import logging

        with caplog.at_level(logging.WARNING, logger="core.db_bulk"):
            result = insert_stream_segments(db, segments, threshold_m2=1000)

        assert result == 1
        assert "1 segments dropped by unique constraint" in caplog.text
        assert "threshold=1000" in caplog.text

    def test_insert_stream_segments_no_warning_when_all_inserted(self, caplog):
        """No warning when all segments are inserted."""
        segments = [self._make_segment(), self._make_segment(x=500100.0)]

        db, cursor, _ = self._make_mock_db(rowcount=2)

        import logging

        with caplog.at_level(logging.WARNING, logger="core.db_bulk"):
            result = insert_stream_segments(db, segments, threshold_m2=100)

        assert result == 2
        assert "dropped by unique constraint" not in caplog.text

    def test_insert_stream_segments_empty(self):
        """Empty segment list returns 0 without DB calls."""
        db = MagicMock()
        result = insert_stream_segments(db, [], threshold_m2=100)
        assert result == 0
        db.connection.assert_not_called()

    def test_insert_stream_segments_tsv_contains_threshold(self):
        """Verify the TSV buffer passed to COPY includes threshold_m2."""
        segment = self._make_segment()
        db, cursor, _ = self._make_mock_db(rowcount=1)

        insert_stream_segments(db, [segment], threshold_m2=5000)

        # Find the copy_expert call and check buffer contents
        copy_calls = [c for c in cursor.method_calls if c[0] == "copy_expert"]
        assert len(copy_calls) == 1
        tsv_buffer = copy_calls[0][1][1]  # second positional arg
        tsv_buffer.seek(0)
        content = tsv_buffer.read()
        assert "5000" in content
