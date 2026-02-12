"""Tests for core.db_bulk module (non-DB functions only)."""

import numpy as np

from core.db_bulk import create_flow_network_records, create_flow_network_tsv


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
