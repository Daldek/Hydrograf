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
        upstream_count, hw_rows, hw_cols = _count_upstream_and_find_headwaters(
            fdir,
            stream_mask,
            nodata_mask,
            _DR,
            _DC,
            _VALID,
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
        upstream_count, hw_rows, hw_cols = _count_upstream_and_find_headwaters(
            fdir,
            stream_mask,
            nodata_mask,
            _DR,
            _DC,
            _VALID,
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
        upstream_count, hw_rows, hw_cols = _count_upstream_and_find_headwaters(
            fdir,
            stream_mask,
            nodata_mask,
            _DR,
            _DC,
            _VALID,
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
            dem,
            fdir,
            acc,
            slope,
            strahler,
            meta,
            stream_threshold=50,
        )
        assert len(segments) > 0

    def test_segment_has_required_keys(self):
        dem, fdir, acc, slope, strahler, meta = self._make_simple_data()
        segments = vectorize_streams(
            dem,
            fdir,
            acc,
            slope,
            strahler,
            meta,
            stream_threshold=50,
        )
        required = {
            "coords",
            "strahler_order",
            "length_m",
            "upstream_area_km2",
            "mean_slope_percent",
        }
        for seg in segments:
            assert required.issubset(seg.keys())

    def test_segment_coords_are_tuples(self):
        dem, fdir, acc, slope, strahler, meta = self._make_simple_data()
        segments = vectorize_streams(
            dem,
            fdir,
            acc,
            slope,
            strahler,
            meta,
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
            dem,
            fdir,
            acc,
            slope,
            strahler,
            meta,
            stream_threshold=50,
            label_raster_out=label_raster,
        )
        # Stream cells should have labels > 0
        assert np.any(label_raster > 0)

    def test_confluence_segmentation(self):
        """Two tributaries merge without Strahler change → separate segments.

        Grid layout (8x6):
          Row 1: tributary A flowing east  (0,0)→(0,1)→(0,2)→(0,3)
          Row 3: tributary B flowing east  (2,0)→(2,1)→(2,2)→(2,3)
          Cells (0,3) and (2,3) both flow to (1,4) (confluence)
          Then (1,4)→(1,5) continues east (main stem)

        All cells Strahler order 1 — without confluence segmentation
        this would be fewer segments; with it, we expect a break at (1,4).
        """
        nrows, ncols = 4, 7
        dem = np.full((nrows, ncols), 100.0)
        # Tributaries slope east
        dem[0, :] = [60, 59, 58, 57, 56, 55, 54]
        dem[2, :] = [60, 59, 58, 57, 56, 55, 54]
        # Main stem from col 4 east
        dem[1, 4] = 50
        dem[1, 5] = 49
        dem[1, 6] = 48

        metadata = {
            "cellsize": 1.0,
            "xllcorner": 0.0,
            "yllcorner": 0.0,
            "nodata_value": -9999.0,
        }

        fdir = np.zeros((nrows, ncols), dtype=np.int16)
        # Tributary A (row 0): all flow east (D8=1) until col 3
        fdir[0, 0] = 1
        fdir[0, 1] = 1
        fdir[0, 2] = 1
        fdir[0, 3] = 2  # SE → (1,4)
        # Tributary B (row 2): all flow east until col 3
        fdir[2, 0] = 1
        fdir[2, 1] = 1
        fdir[2, 2] = 1
        fdir[2, 3] = 128  # NE → (1,4)
        # Main stem (row 1): from col 4 east
        fdir[1, 4] = 1  # E
        fdir[1, 5] = 1  # E
        fdir[1, 6] = 1  # E (outlet)

        # Accumulation: all stream cells above threshold
        acc = np.ones((nrows, ncols), dtype=np.int32)
        # Tributary A
        acc[0, 0:4] = [100, 200, 300, 400]
        # Tributary B
        acc[2, 0:4] = [100, 200, 300, 400]
        # Main stem (higher — receives both tribs)
        acc[1, 4] = 900
        acc[1, 5] = 1000
        acc[1, 6] = 1100

        slope = np.full((nrows, ncols), 5.0)

        # ALL stream cells have Strahler order 1 — no order change
        strahler = np.zeros((nrows, ncols), dtype=np.uint8)
        strahler[0, 0:4] = 1
        strahler[2, 0:4] = 1
        strahler[1, 4:7] = 1

        stream_mask = acc >= 50

        label_raster = np.zeros((nrows, ncols), dtype=np.int32)
        segments = vectorize_streams(
            dem,
            fdir,
            acc,
            slope,
            strahler,
            metadata,
            stream_threshold=50,
            label_raster_out=label_raster,
        )

        # With confluence segmentation: expect at least 3 segments
        # (trib A, trib B, main stem from confluence)
        assert len(segments) >= 3, (
            f"Expected >=3 segments (2 tribs + main stem), got {len(segments)}"
        )

        # Confluence cell (1,4) should be the endpoint of at least
        # one tributary and the start of the main stem segment
        confluence_xy = (4.5, 2.5)  # cell_xy(1, 4) with cellsize=1, yll=0, nrows=4
        segments_ending_at_confluence = [
            s for s in segments if s["coords"][-1] == confluence_xy
        ]
        assert len(segments_ending_at_confluence) >= 1, (
            "At least one segment should end at the confluence point"
        )

        # Label raster: each stream cell should have a label
        for r, c in [(0, 0), (0, 1), (0, 2), (0, 3),
                      (2, 0), (2, 1), (2, 2), (2, 3),
                      (1, 4), (1, 5), (1, 6)]:
            if stream_mask[r, c]:
                assert label_raster[r, c] > 0, (
                    f"Stream cell ({r},{c}) should have a label"
                )
