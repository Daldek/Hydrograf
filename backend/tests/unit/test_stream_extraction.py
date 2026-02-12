"""Tests for core.stream_extraction module."""

import numpy as np

from core.stream_extraction import (
    _DC,
    _DR,
    _VALID,
    _count_upstream_and_find_headwaters,
    vectorize_streams,
)


class TestCountUpstreamAndFindHeadwaters:
    """Tests for numba-accelerated upstream counting."""

    def test_simple_chain(self):
        # 1x3 grid: all flowing east (D8=1)
        fdir = np.array([[1, 1, 1]], dtype=np.int16)
        stream_mask = np.array([[True, True, True]])
        nodata_mask = np.array([[False, False, False]])
        upstream_count, hw_rows, hw_cols = (
            _count_upstream_and_find_headwaters(
                fdir, stream_mask, nodata_mask, _DR, _DC, _VALID,
            )
        )
        # Cell 0 has no upstream → headwater
        assert upstream_count[0, 0] == 0
        assert upstream_count[0, 1] == 1
        assert upstream_count[0, 2] == 1
        assert len(hw_rows) == 1
        assert hw_rows[0] == 0
        assert hw_cols[0] == 0

    def test_no_streams(self):
        fdir = np.array([[1, 1]], dtype=np.int16)
        stream_mask = np.array([[False, False]])
        nodata_mask = np.array([[False, False]])
        upstream_count, hw_rows, hw_cols = (
            _count_upstream_and_find_headwaters(
                fdir, stream_mask, nodata_mask, _DR, _DC, _VALID,
            )
        )
        assert len(hw_rows) == 0

    def test_multiple_headwaters(self):
        # 3x3 grid: corners flow to center
        fdir = np.zeros((3, 3), dtype=np.int16)
        # top-left (0,0) → SE = 2
        fdir[0, 0] = 2
        # top-right (0,2) → SW = 8
        fdir[0, 2] = 8
        # bottom-left (2,0) → NE = 128
        fdir[2, 0] = 128
        # bottom-right (2,2) → NW = 32
        fdir[2, 2] = 32
        # center (1,1) → E = 1 (flows out)
        fdir[1, 1] = 1

        stream_mask = np.zeros((3, 3), dtype=bool)
        stream_mask[0, 0] = True
        stream_mask[0, 2] = True
        stream_mask[2, 0] = True
        stream_mask[2, 2] = True
        stream_mask[1, 1] = True

        nodata_mask = np.zeros((3, 3), dtype=bool)
        upstream_count, hw_rows, hw_cols = (
            _count_upstream_and_find_headwaters(
                fdir, stream_mask, nodata_mask, _DR, _DC, _VALID,
            )
        )
        assert upstream_count[1, 1] == 4  # 4 corners flow to center
        assert len(hw_rows) == 4  # 4 headwaters


class TestVectorizeStreams:
    """Tests for vectorize_streams function."""

    def _make_simple_data(self):
        """Create a simple 5x5 DEM with east-flowing streams."""
        dem = np.full((5, 5), 100.0)
        # Stream row at y=2
        dem[2, :] = [50, 49, 48, 47, 46]

        metadata = {
            "cellsize": 1.0,
            "xllcorner": 0.0,
            "yllcorner": 0.0,
            "nodata_value": -9999.0,
        }

        # All flow east (D8=1)
        fdir = np.ones((5, 5), dtype=np.int16)

        # Accumulation: stream row has high values
        acc = np.ones((5, 5), dtype=np.int32)
        acc[2, :] = [100, 200, 300, 400, 500]

        slope = np.full((5, 5), 5.0)

        strahler = np.zeros((5, 5), dtype=np.uint8)
        strahler[2, :] = 1

        return dem, fdir, acc, slope, strahler, metadata

    def test_returns_segments(self):
        dem, fdir, acc, slope, strahler, meta = self._make_simple_data()
        segments = vectorize_streams(
            dem, fdir, acc, slope, strahler, meta,
            stream_threshold=50,
        )
        assert len(segments) > 0

    def test_segment_has_required_keys(self):
        dem, fdir, acc, slope, strahler, meta = self._make_simple_data()
        segments = vectorize_streams(
            dem, fdir, acc, slope, strahler, meta,
            stream_threshold=50,
        )
        required = {
            "coords", "strahler_order", "length_m",
            "upstream_area_km2", "mean_slope_percent",
        }
        for seg in segments:
            assert required.issubset(seg.keys())

    def test_segment_coords_are_tuples(self):
        dem, fdir, acc, slope, strahler, meta = self._make_simple_data()
        segments = vectorize_streams(
            dem, fdir, acc, slope, strahler, meta,
            stream_threshold=50,
        )
        for seg in segments:
            assert len(seg["coords"]) >= 2
            for coord in seg["coords"]:
                assert len(coord) == 2

    def test_label_raster_painted(self):
        dem, fdir, acc, slope, strahler, meta = self._make_simple_data()
        label_raster = np.zeros_like(dem, dtype=np.int32)
        vectorize_streams(
            dem, fdir, acc, slope, strahler, meta,
            stream_threshold=50,
            label_raster_out=label_raster,
        )
        # Stream cells should have labels > 0
        assert np.any(label_raster > 0)
