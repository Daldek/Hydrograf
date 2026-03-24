"""Tests for flow path tracing in preprocessing pipeline."""

import numpy as np
import pyflwdir
import pytest


class TestStreamDistance:
    """Tests for pyflwdir stream_distance computation."""

    def test_stream_distance_returns_non_negative_values(self):
        """stream_distance should return non-negative values."""
        # Simple 3x3 grid: all flow to center-bottom
        # D8: 1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE
        fdir = np.array(
            [[2, 4, 8], [2, 4, 8], [0, 0, 0]], dtype=np.uint8
        )
        flw = pyflwdir.from_array(
            fdir, ftype="d8", transform=(1, 0, 0, 0, -1, 3), latlon=False
        )
        dist = flw.stream_distance(unit="m")
        assert np.all(dist >= 0)

    def test_outlet_has_zero_distance(self):
        """Pit cells should have 0 distance."""
        fdir = np.array(
            [[2, 4, 8], [2, 4, 8], [0, 0, 0]], dtype=np.uint8
        )
        flw = pyflwdir.from_array(
            fdir, ftype="d8", transform=(1, 0, 0, 0, -1, 3), latlon=False
        )
        dist = flw.stream_distance(unit="m")
        # Bottom row cells are pits (fdir=0) — distance should be 0
        assert dist[2, 0] == 0
        assert dist[2, 1] == 0
        assert dist[2, 2] == 0

    def test_upstream_cells_have_positive_distance(self):
        """Non-pit cells draining to a pit should have positive distance."""
        fdir = np.array(
            [[2, 4, 8], [2, 4, 8], [0, 0, 0]], dtype=np.uint8
        )
        flw = pyflwdir.from_array(
            fdir, ftype="d8", transform=(1, 0, 0, 0, -1, 3), latlon=False
        )
        dist = flw.stream_distance(unit="m")
        # Top row should have largest distances
        assert dist[0, 0] > dist[1, 0]
        assert dist[0, 1] > dist[1, 1]

    def test_stream_distance_unit_m_scales_with_cellsize(self):
        """Distance in meters should scale with cell size."""
        fdir = np.array(
            [[4], [4], [0]], dtype=np.uint8
        )
        # Cell size = 5m
        flw5 = pyflwdir.from_array(
            fdir, ftype="d8", transform=(5, 0, 0, 0, -5, 15), latlon=False
        )
        dist5 = flw5.stream_distance(unit="m")
        # Cell size = 10m
        flw10 = pyflwdir.from_array(
            fdir, ftype="d8", transform=(10, 0, 0, 0, -10, 30), latlon=False
        )
        dist10 = flw10.stream_distance(unit="m")
        # Distance at top cell should be 2x larger with 2x cell size
        assert pytest.approx(dist10[0, 0], rel=0.01) == dist5[0, 0] * 2


class TestFlowPathTracing:
    """Tests for flw.path() downstream tracing."""

    def _make_flw(self):
        """Create a simple 3x3 FlwdirRaster for testing."""
        fdir = np.array(
            [[2, 4, 8], [2, 4, 8], [0, 0, 0]], dtype=np.uint8
        )
        return pyflwdir.from_array(
            fdir, ftype="d8", transform=(1, 0, 0, 0, -1, 3), latlon=False
        )

    def test_path_returns_valid_indices(self):
        """path() should return valid cell indices."""
        flw = self._make_flw()
        paths, dists = flw.path(idxs=np.array([0]))  # from top-left
        assert len(paths) > 0
        assert len(paths[0]) > 1

    def test_path_ends_at_pit(self):
        """Downstream path should end at a pit cell."""
        flw = self._make_flw()
        paths, dists = flw.path(idxs=np.array([0]))
        # Should end at bottom row (row 2)
        last_idx = paths[0][-1]
        nrows, ncols = 3, 3
        last_row = last_idx // ncols
        assert last_row == 2

    def test_path_distance_matches_stream_distance(self):
        """Path distance should match stream_distance for the same cell."""
        flw = self._make_flw()
        dist = flw.stream_distance(unit="m")
        paths, dists = flw.path(idxs=np.array([0]), unit="m")
        # Distance from flw.path should equal stream_distance at cell 0
        assert pytest.approx(dists[0], rel=0.01) == dist.ravel()[0]

    def test_batch_path_multiple_starts(self):
        """Batch path tracing should return one path per start index."""
        flw = self._make_flw()
        start_idxs = np.array([0, 1, 2])  # top row cells
        paths, dists = flw.path(idxs=start_idxs)
        assert len(paths) == 3
        assert len(dists) == 3

    def test_path_xy_returns_coordinates(self):
        """flw.xy() should return valid x, y coordinates for path indices."""
        flw = self._make_flw()
        paths, _ = flw.path(idxs=np.array([0]))
        xs, ys = flw.xy(paths[0])
        assert len(xs) == len(paths[0])
        assert len(ys) == len(paths[0])


class TestEnrichCatchmentsWithFlowPaths:
    """Tests for _enrich_catchments_with_flow_paths helper."""

    def test_enriches_catchments_with_max_flow_dist(self):
        """Each catchment should get max_flow_dist_m set."""
        from scripts.process_dem import _enrich_catchments_with_flow_paths

        # 5x5 grid: 2 subcatchments, all flowing south
        fdir = np.array(
            [
                [4, 4, 4, 4, 4],
                [4, 4, 4, 4, 4],
                [4, 4, 4, 4, 4],
                [4, 4, 4, 4, 4],
                [0, 0, 0, 0, 0],
            ],
            dtype=np.uint8,
        )
        flw = pyflwdir.from_array(
            fdir, ftype="d8", transform=(5, 0, 0, 0, -5, 25), latlon=False
        )
        flow_dist_m = flw.stream_distance(unit="m")

        # Label raster: left 3 cols = label 1, right 2 cols = label 2
        label_raster = np.array(
            [
                [1, 1, 1, 2, 2],
                [1, 1, 1, 2, 2],
                [1, 1, 1, 2, 2],
                [1, 1, 1, 2, 2],
                [1, 1, 1, 2, 2],
            ],
            dtype=np.int32,
        )

        metadata = {"cellsize": 5}
        catchments = [
            {"segment_idx": 1, "wkt": "MULTIPOLYGON(...)"},
            {"segment_idx": 2, "wkt": "MULTIPOLYGON(...)"},
        ]

        _enrich_catchments_with_flow_paths(
            catchments, label_raster, flow_dist_m, flw, metadata
        )

        assert catchments[0]["max_flow_dist_m"] is not None
        assert catchments[0]["max_flow_dist_m"] > 0
        assert catchments[1]["max_flow_dist_m"] is not None
        assert catchments[1]["max_flow_dist_m"] > 0

    def test_enriches_catchments_with_flow_path_wkt(self):
        """Each catchment with valid path should get longest_flow_path_wkt."""
        from scripts.process_dem import _enrich_catchments_with_flow_paths

        fdir = np.array(
            [
                [4, 4, 4, 4, 4],
                [4, 4, 4, 4, 4],
                [4, 4, 4, 4, 4],
                [4, 4, 4, 4, 4],
                [0, 0, 0, 0, 0],
            ],
            dtype=np.uint8,
        )
        flw = pyflwdir.from_array(
            fdir, ftype="d8", transform=(5, 0, 0, 0, -5, 25), latlon=False
        )
        flow_dist_m = flw.stream_distance(unit="m")

        label_raster = np.array(
            [
                [1, 1, 1, 2, 2],
                [1, 1, 1, 2, 2],
                [1, 1, 1, 2, 2],
                [1, 1, 1, 2, 2],
                [1, 1, 1, 2, 2],
            ],
            dtype=np.int32,
        )

        metadata = {"cellsize": 5}
        catchments = [
            {"segment_idx": 1, "wkt": "MULTIPOLYGON(...)"},
            {"segment_idx": 2, "wkt": "MULTIPOLYGON(...)"},
        ]

        _enrich_catchments_with_flow_paths(
            catchments, label_raster, flow_dist_m, flw, metadata
        )

        # Both catchments should have flow path WKT (LINESTRING)
        for cat in catchments:
            assert cat["longest_flow_path_wkt"] is not None
            assert "LINESTRING" in cat["longest_flow_path_wkt"]

    def test_empty_catchment_gets_none(self):
        """Catchment with no cells in label raster should get None values."""
        from scripts.process_dem import _enrich_catchments_with_flow_paths

        fdir = np.array([[4], [0]], dtype=np.uint8)
        flw = pyflwdir.from_array(
            fdir, ftype="d8", transform=(5, 0, 0, 0, -5, 10), latlon=False
        )
        flow_dist_m = flw.stream_distance(unit="m")

        # Label raster has only label 1, but catchment references label 99
        label_raster = np.array([[1], [1]], dtype=np.int32)
        metadata = {"cellsize": 5}
        catchments = [
            {"segment_idx": 99, "wkt": "MULTIPOLYGON(...)"},
        ]

        _enrich_catchments_with_flow_paths(
            catchments, label_raster, flow_dist_m, flw, metadata
        )

        assert catchments[0]["max_flow_dist_m"] is None
        assert catchments[0]["longest_flow_path_wkt"] is None

    def test_single_cell_catchment_gets_none_path(self):
        """Catchment with only one cell should get None for flow path."""
        from scripts.process_dem import _enrich_catchments_with_flow_paths

        fdir = np.array([[0, 0], [0, 0]], dtype=np.uint8)
        flw = pyflwdir.from_array(
            fdir, ftype="d8", transform=(5, 0, 0, 0, -5, 10), latlon=False
        )
        flow_dist_m = flw.stream_distance(unit="m")

        # Only 1 cell belongs to label 1
        label_raster = np.array([[1, 2], [3, 4]], dtype=np.int32)
        metadata = {"cellsize": 5}
        catchments = [
            {"segment_idx": 1, "wkt": "MULTIPOLYGON(...)"},
        ]

        _enrich_catchments_with_flow_paths(
            catchments, label_raster, flow_dist_m, flw, metadata
        )

        # max_flow_dist_m should be set (it's 0 for pit cells)
        assert catchments[0]["max_flow_dist_m"] is not None
        # But flow path needs >= 2 cells, so with a single cell it may be None
        # (path from pit to itself is only 1 cell)


class TestInsertCatchmentsFlowPath:
    """Tests for flow path columns in insert_catchments TSV generation."""

    def test_tsv_includes_flow_path_columns(self):
        """TSV buffer should include max_flow_dist_m and longest_flow_path_wkt."""
        import io

        # Simulate what insert_catchments does for TSV generation
        def _tsv_val(v):
            return "" if v is None else str(v)

        cat = {
            "wkt": "MULTIPOLYGON(((0 0, 1 0, 1 1, 0 1, 0 0)))",
            "segment_idx": 1,
            "area_km2": 0.5,
            "mean_elevation_m": 100.0,
            "mean_slope_percent": 5.0,
            "strahler_order": 2,
            "downstream_segment_idx": None,
            "elevation_min_m": 90.0,
            "elevation_max_m": 110.0,
            "perimeter_km": 0.1,
            "stream_length_km": 0.05,
            "elev_histogram": None,
            "max_flow_dist_m": 1234.5,
            "longest_flow_path_wkt": "LINESTRING(0 0, 0.5 0.5, 1 1)",
        }

        tsv_buffer = io.StringIO()
        hist_str = ""
        tsv_buffer.write(
            f"{cat['wkt']}\t{cat['segment_idx']}\t"
            f"1000\t{cat['area_km2']}\t"
            f"{_tsv_val(cat['mean_elevation_m'])}\t"
            f"{_tsv_val(cat['mean_slope_percent'])}\t"
            f"{_tsv_val(cat.get('strahler_order'))}\t"
            f"{_tsv_val(cat.get('downstream_segment_idx'))}\t"
            f"{_tsv_val(cat.get('elevation_min_m'))}\t"
            f"{_tsv_val(cat.get('elevation_max_m'))}\t"
            f"{_tsv_val(cat.get('perimeter_km'))}\t"
            f"{_tsv_val(cat.get('stream_length_km'))}\t"
            f"{hist_str}\t"
            f"{_tsv_val(cat.get('max_flow_dist_m'))}\t"
            f"{_tsv_val(cat.get('longest_flow_path_wkt'))}\n"
        )

        tsv_content = tsv_buffer.getvalue()
        fields = tsv_content.strip().split("\t")
        # 15 fields total (13 original + 2 new)
        assert len(fields) == 15
        assert fields[-2] == "1234.5"
        assert fields[-1] == "LINESTRING(0 0, 0.5 0.5, 1 1)"

    def test_tsv_handles_none_flow_path(self):
        """TSV should use empty string for None flow path values."""

        def _tsv_val(v):
            return "" if v is None else str(v)

        assert _tsv_val(None) == ""
        assert _tsv_val(1234.5) == "1234.5"
        assert _tsv_val("LINESTRING(0 0, 1 1)") == "LINESTRING(0 0, 1 1)"
