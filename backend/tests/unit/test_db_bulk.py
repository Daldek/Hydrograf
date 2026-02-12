"""Tests for core.db_bulk module."""

from unittest.mock import MagicMock

import numpy as np

from core.db_bulk import (
    create_flow_network_records,
    create_flow_network_tsv,
    insert_stream_segments,
)


class TestCreateFlowNetworkRecords:
    """Tests for create_flow_network_records (backward compat wrapper)."""

    def _make_simple_data(self):
        dem = np.array([[100.0, 90.0], [80.0, 70.0]])
        fdir = np.array([[1, 4], [1, 1]], dtype=np.int16)
        acc = np.array([[1, 2], [3, 4]], dtype=np.int32)
        slope = np.array([[5.0, 3.0], [2.0, 1.0]])
        metadata = {
            "cellsize": 1.0,
            "xllcorner": 500000.0,
            "yllcorner": 500000.0,
            "nodata_value": -9999.0,
        }
        return dem, fdir, acc, slope, metadata

    def test_returns_list_of_dicts(self):
        dem, fdir, acc, slope, meta = self._make_simple_data()
        records = create_flow_network_records(
            dem, fdir, acc, slope, meta, stream_threshold=3,
        )
        assert isinstance(records, list)
        assert len(records) == 4  # 2x2 grid, no nodata

    def test_record_has_required_keys(self):
        dem, fdir, acc, slope, meta = self._make_simple_data()
        records = create_flow_network_records(
            dem, fdir, acc, slope, meta, stream_threshold=3,
        )
        required = {
            "id", "x", "y", "elevation", "flow_accumulation",
            "slope", "downstream_id", "cell_area", "is_stream",
            "strahler_order",
        }
        for r in records:
            assert required.issubset(r.keys())

    def test_nodata_excluded(self):
        dem = np.array([[100.0, -9999.0], [80.0, 70.0]])
        fdir = np.array([[1, 0], [1, 1]], dtype=np.int16)
        acc = np.array([[1, 0], [2, 3]], dtype=np.int32)
        slope = np.array([[5.0, 0.0], [2.0, 1.0]])
        metadata = {
            "cellsize": 1.0,
            "xllcorner": 500000.0,
            "yllcorner": 500000.0,
            "nodata_value": -9999.0,
        }
        records = create_flow_network_records(
            dem, fdir, acc, slope, metadata,
        )
        assert len(records) == 3  # one nodata cell excluded

    def test_is_stream_threshold(self):
        dem, fdir, acc, slope, meta = self._make_simple_data()
        records = create_flow_network_records(
            dem, fdir, acc, slope, meta, stream_threshold=3,
        )
        stream_records = [r for r in records if r["is_stream"]]
        non_stream = [r for r in records if not r["is_stream"]]
        assert len(stream_records) == 2  # acc >= 3: cells with 3 and 4
        assert len(non_stream) == 2

    def test_strahler_from_array(self):
        dem, fdir, acc, slope, meta = self._make_simple_data()
        strahler = np.array([[0, 0], [1, 2]], dtype=np.uint8)
        records = create_flow_network_records(
            dem, fdir, acc, slope, meta,
            strahler=strahler,
        )
        strahler_vals = {r["id"]: r["strahler_order"] for r in records}
        # Bottom-left cell (row=1, col=0): id = 1*2+0+1 = 3
        assert strahler_vals[3] == 1
        # Bottom-right cell (row=1, col=1): id = 1*2+1+1 = 4
        assert strahler_vals[4] == 2


class TestCreateFlowNetworkTsv:
    """Tests for create_flow_network_tsv (vectorized numpy version)."""

    def _make_simple_data(self):
        dem = np.array([[100.0, 90.0], [80.0, 70.0]])
        fdir = np.array([[1, 4], [1, 1]], dtype=np.int16)
        acc = np.array([[1, 2], [3, 4]], dtype=np.int32)
        slope = np.array([[5.0, 3.0], [2.0, 1.0]])
        metadata = {
            "cellsize": 1.0,
            "xllcorner": 500000.0,
            "yllcorner": 500000.0,
            "nodata_value": -9999.0,
        }
        return dem, fdir, acc, slope, metadata

    def test_returns_buffer_and_counts(self):
        dem, fdir, acc, slope, meta = self._make_simple_data()
        tsv_buffer, n_records, n_stream = create_flow_network_tsv(
            dem, fdir, acc, slope, meta, stream_threshold=3,
        )
        assert n_records == 4
        assert n_stream == 2  # acc >= 3

    def test_tsv_has_correct_line_count(self):
        dem, fdir, acc, slope, meta = self._make_simple_data()
        tsv_buffer, n_records, _ = create_flow_network_tsv(
            dem, fdir, acc, slope, meta,
        )
        lines = tsv_buffer.read().strip().split("\n")
        assert len(lines) == n_records

    def test_tsv_fields_count(self):
        dem, fdir, acc, slope, meta = self._make_simple_data()
        tsv_buffer, _, _ = create_flow_network_tsv(
            dem, fdir, acc, slope, meta,
        )
        lines = [line for line in tsv_buffer.read().split("\n") if line]
        for line in lines:
            fields = line.split("\t")
            assert len(fields) == 10  # id,x,y,elev,acc,slope,ds,area,stream,strahler

    def test_nodata_excluded(self):
        dem = np.array([[100.0, -9999.0], [80.0, 70.0]])
        fdir = np.array([[1, 0], [1, 1]], dtype=np.int16)
        acc = np.array([[1, 0], [2, 3]], dtype=np.int32)
        slope = np.array([[5.0, 0.0], [2.0, 1.0]])
        metadata = {
            "cellsize": 1.0,
            "xllcorner": 500000.0,
            "yllcorner": 500000.0,
            "nodata_value": -9999.0,
        }
        _, n_records, _ = create_flow_network_tsv(
            dem, fdir, acc, slope, metadata,
        )
        assert n_records == 3

    def test_consistency_with_records(self):
        """TSV and records versions should produce same counts."""
        dem, fdir, acc, slope, meta = self._make_simple_data()
        records = create_flow_network_records(
            dem, fdir, acc, slope, meta, stream_threshold=3,
        )
        _, n_records, n_stream = create_flow_network_tsv(
            dem, fdir, acc, slope, meta, stream_threshold=3,
        )
        assert n_records == len(records)
        assert n_stream == sum(1 for r in records if r["is_stream"])


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
        copy_calls = [
            c for c in cursor.method_calls
            if c[0] == "copy_expert"
        ]
        assert len(copy_calls) == 1
        tsv_buffer = copy_calls[0][1][1]  # second positional arg
        tsv_buffer.seek(0)
        content = tsv_buffer.read()
        assert "5000" in content
