"""Tests for flow path tracing in preprocessing pipeline."""

import numpy as np
import pyflwdir
import pytest

from scripts.process_dem import _farthest_cells, _per_label_argmax, _trace_in_labels
from tests.dem_equivalence import (
    DEM_CASES,
    assert_identical,
    derive_hydrology,
    subcatchments,
    synthetic_dem,
)


class TestStreamDistance:
    """Tests for pyflwdir stream_distance computation."""

    def test_stream_distance_returns_non_negative_values(self):
        """stream_distance should return non-negative values."""
        # Simple 3x3 grid: all flow to center-bottom
        # D8: 1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE
        fdir = np.array([[2, 4, 8], [2, 4, 8], [0, 0, 0]], dtype=np.uint8)
        flw = pyflwdir.from_array(
            fdir, ftype="d8", transform=(1, 0, 0, 0, -1, 3), latlon=False
        )
        dist = flw.stream_distance(unit="m")
        assert np.all(dist >= 0)

    def test_outlet_has_zero_distance(self):
        """Pit cells should have 0 distance."""
        fdir = np.array([[2, 4, 8], [2, 4, 8], [0, 0, 0]], dtype=np.uint8)
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
        fdir = np.array([[2, 4, 8], [2, 4, 8], [0, 0, 0]], dtype=np.uint8)
        flw = pyflwdir.from_array(
            fdir, ftype="d8", transform=(1, 0, 0, 0, -1, 3), latlon=False
        )
        dist = flw.stream_distance(unit="m")
        # Top row should have largest distances
        assert dist[0, 0] > dist[1, 0]
        assert dist[0, 1] > dist[1, 1]

    def test_stream_distance_unit_m_scales_with_cellsize(self):
        """Distance in meters should scale with cell size."""
        fdir = np.array([[4], [4], [0]], dtype=np.uint8)
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
        fdir = np.array([[2, 4, 8], [2, 4, 8], [0, 0, 0]], dtype=np.uint8)
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
        ncols = 3
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
            catchments,
            label_raster,
            flow_dist_m,
            flw,
            metadata,
            np.zeros((5, 5), dtype=np.float32),
            np.zeros((5, 5), dtype=bool),
        )

        assert catchments[0]["max_flow_dist_m"] is not None
        assert catchments[0]["max_flow_dist_m"] > 0
        assert catchments[1]["max_flow_dist_m"] is not None
        assert catchments[1]["max_flow_dist_m"] > 0

        assert catchments[0]["outlet_flow_dist_m"] is not None
        assert catchments[0]["outlet_flow_dist_m"] <= catchments[0]["max_flow_dist_m"]
        assert catchments[1]["outlet_flow_dist_m"] is not None

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
            catchments,
            label_raster,
            flow_dist_m,
            flw,
            metadata,
            np.zeros((5, 5), dtype=np.float32),
            np.zeros((5, 5), dtype=bool),
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
            catchments,
            label_raster,
            flow_dist_m,
            flw,
            metadata,
            np.zeros((2, 1), dtype=np.float32),
            np.zeros((2, 1), dtype=bool),
        )

        assert catchments[0]["max_flow_dist_m"] is None
        assert catchments[0]["longest_flow_path_wkt"] is None
        for key in (
            "flow_path_head_elev_m",
            "overland_length_m",
            "overland_drop_m",
            "stream_head_elev_m",
        ):
            assert catchments[0][key] is None

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
            catchments,
            label_raster,
            flow_dist_m,
            flw,
            metadata,
            np.zeros((2, 2), dtype=np.float32),
            np.zeros((2, 2), dtype=bool),
        )

        # max_flow_dist_m should be set (it's 0 for pit cells)
        assert catchments[0]["max_flow_dist_m"] is not None
        # But flow path needs >= 2 cells, so with a single cell it may be None
        # (path from pit to itself is only 1 cell)

        # Jednokomorkowa: brak sciezki -> outlet = max_flow_dist (dlugosc 0)
        assert catchments[0]["outlet_flow_dist_m"] == catchments[0]["max_flow_dist_m"]


class TestFlowPathHeadsAndOverland:
    """The head of the longest flow path, its overland segment, the stream head.

    5 x 5 cells of 5 m, all draining south into pits in the bottom row; the left
    three columns are sub-catchment 1, the right two sub-catchment 2. The terrain
    rises 10 m per row to the north (row 0 at 140 m, row 4 at 100 m).
    """

    @staticmethod
    def _run(stream_mask):
        from scripts.process_dem import _enrich_catchments_with_flow_paths

        fdir = np.full((5, 5), 4, dtype=np.uint8)
        fdir[4, :] = 0
        flw = pyflwdir.from_array(
            fdir, ftype="d8", transform=(5, 0, 0, 0, -5, 25), latlon=False
        )
        labels = np.array([[1, 1, 1, 2, 2]] * 5, dtype=np.int32)
        dem = np.repeat(140.0 - 10.0 * np.arange(5), 5).reshape(5, 5)
        catchments = [{"segment_idx": 1}, {"segment_idx": 2}]
        _enrich_catchments_with_flow_paths(
            catchments,
            labels,
            flw.stream_distance(unit="m"),
            flw,
            {"cellsize": 5},
            dem.astype(np.float32),
            stream_mask,
        )
        return catchments

    def test_overland_runs_from_the_head_to_the_first_stream_cell(self):
        stream = np.zeros((5, 5), dtype=bool)
        stream[3:, 0] = True  # the stream of sub-catchment 1 starts in row 3

        one, _ = self._run(stream)

        # Head: the first farthest cell, (0, 0) at 140 m; stream entry (3, 0) at 110 m
        assert one["flow_path_head_elev_m"] == 140.0
        assert one["overland_length_m"] == 15.0
        assert one["overland_drop_m"] == 30.0

    def test_stream_head_is_the_upstream_end_of_the_segment(self):
        stream = np.zeros((5, 5), dtype=bool)
        stream[2:, 0] = True

        one, _ = self._run(stream)

        assert one["stream_head_elev_m"] == 120.0

    def test_no_stream_on_the_path_leaves_the_overland_segment_unmeasured(self):
        stream = np.zeros((5, 5), dtype=bool)
        stream[3:, 0] = True  # only sub-catchment 1 has a stream

        _, two = self._run(stream)

        # The head of 2 drains into a pit without passing a stream cell
        assert two["flow_path_head_elev_m"] == 140.0
        assert two["overland_length_m"] is None
        assert two["overland_drop_m"] is None
        assert two["stream_head_elev_m"] is None

    def test_a_head_on_a_stream_cell_has_no_overland_segment(self):
        stream = np.zeros((5, 5), dtype=bool)
        stream[:, 0] = True  # the farthest cell is already in the stream

        one, _ = self._run(stream)

        assert one["overland_length_m"] is None
        assert one["overland_drop_m"] is None
        assert one["stream_head_elev_m"] == 140.0


class TestRouteLengthsAddUpToTheFlowPath:
    """Overland segment + stream segments of one route = its flow path.

    The pipeline from flow directions to sub-catchments (vectorize_streams,
    delineate_subcatchments, compute_downstream_links,
    _enrich_catchments_with_flow_paths) on 10 x 7 cells of 5 m: a stem in
    column 3 flowing south to a pit at (9, 3), the slopes on both sides draining
    into it, and a tributary in column 5 that turns west in row 5 and joins the
    stem at (5, 3). Segments: 1 the stem above the confluence, 2 the stem below
    it, 3 the tributary.
    """

    @staticmethod
    def _fdir(lateral: bool) -> np.ndarray:
        east, south, west = 1, 4, 16
        fdir = np.full((10, 7), west, dtype=np.uint8)
        fdir[:, :3] = east
        fdir[:, 3] = south
        fdir[9, 3] = 0
        fdir[:5, 5] = south
        if lateral:
            # The farthest cell (0, 0) drains south, then east into the stem at
            # row 4, below the head of the stem's stream (row 2 at 10 cells)
            fdir[:4, 0] = south
        return fdir

    @staticmethod
    def _run(fdir: np.ndarray, threshold_cells: int):
        from core.morphometry_raster import compute_strahler_from_fdir
        from core.stream_extraction import (
            compute_downstream_links,
            delineate_subcatchments,
            vectorize_streams,
        )
        from scripts.process_dem import _enrich_catchments_with_flow_paths

        nrows = fdir.shape[0]
        meta = {
            "cellsize": 5.0,
            "xllcorner": 0.0,
            "yllcorner": 0.0,
            "nodata_value": -9999.0,
        }
        flw = pyflwdir.from_array(
            fdir, ftype="d8", transform=(5, 0, 0, 0, -5, 5 * nrows), latlon=False
        )
        acc = flw.upstream_area(unit="cell").astype(np.int32)
        dem = np.full(fdir.shape, 100.0)
        labels = np.zeros(fdir.shape, dtype=np.int32)
        fdir_i16 = fdir.astype(np.int16)
        segments = vectorize_streams(
            dem,
            fdir_i16,
            acc,
            np.zeros(fdir.shape),
            compute_strahler_from_fdir(flw, acc, threshold_cells),
            meta,
            threshold_cells,
            label_raster_out=labels,
        )
        delineate_subcatchments(flw, labels, dem, -9999.0)
        compute_downstream_links(segments, labels, fdir_i16, meta)
        catchments = [{"segment_idx": i + 1} for i in range(len(segments))]
        _enrich_catchments_with_flow_paths(
            catchments,
            labels,
            flw.stream_distance(unit="m"),
            flw,
            meta,
            dem,
            acc >= threshold_cells,
        )
        return segments, catchments

    @staticmethod
    def _route_excess(segments, catchments, start: int) -> list[float]:
        """Overland + segments minus the flow path, at each node of the route."""
        head = catchments[start - 1]
        total = head["overland_length_m"]
        excess = []
        idx = start
        while idx is not None:
            total += segments[idx - 1]["length_m"]
            outlet = catchments[idx - 1]["outlet_flow_dist_m"]
            excess.append(total - (head["max_flow_dist_m"] - outlet))
            idx = segments[idx - 1]["downstream_segment_idx"]
        return excess

    def test_route_entering_the_stream_at_its_head_adds_up(self):
        segments, catchments = self._run(self._fdir(lateral=False), 5)

        assert len(segments) == 3
        for start in (1, 2, 3):
            # Through the junction and to the outlet: no step counted twice or
            # past the outlet of the last sub-catchment of the route
            for excess in self._route_excess(segments, catchments, start):
                assert excess == pytest.approx(0.0, abs=0.1)

    def test_route_joining_the_stream_below_its_head_skips_the_stream_above(self):
        segments, catchments = self._run(self._fdir(lateral=True), 10)

        # Segment 1's stream starts at (2, 3); its longest flow path from (0, 0)
        # joins it at (4, 3), so its 10 m above the junction are not on the path
        assert self._route_excess(segments, catchments, 1) == pytest.approx(
            [10.0, 10.0], abs=0.1
        )
        assert self._route_excess(segments, catchments, 3) == pytest.approx(
            [0.0, 0.0], abs=0.1
        )


def _first_maximum_by_label(labels, values, flat_indices, max_label):
    """Reference: the first entry of the largest value of each label, label by label
    (np.argmax takes the first of equal maxima, as the stable sort of the old code)."""
    best_value = np.full(max_label + 1, -1.0)
    best_idx = np.full(max_label + 1, -1, dtype=np.intp)
    for label in np.unique(labels):
        entries = np.flatnonzero(labels == label)
        first = entries[np.argmax(values[entries])]
        best_value[label] = values[first]
        best_idx[label] = flat_indices[first]
    return best_value, best_idx


@pytest.fixture(scope="module", params=list(DEM_CASES.values()), ids=list(DEM_CASES))
def network(request):
    """Hydrology and sub-catchment labels (threshold 1000 m²) of a synthetic DEM."""
    hydrology = derive_hydrology(*synthetic_dem(**request.param))
    labels, _, _ = subcatchments(hydrology, 1_000)
    return hydrology, labels


class TestFarthestCellsAndPathsWithinSubcatchments:
    """The start cells and the flow paths of _enrich_catchments_with_flow_paths.

    The numba argmax per label equals a label-by-label np.argmax, the farthest
    cells overall and on the boundary equal that argmax over the labelled cells
    and over the boundary of the old shifted comparisons, and a path traced within
    its label equals pyflwdir's whole path cut after its first cell outside.
    """

    def test_argmax_per_label_takes_the_first_of_equal_maxima(self):
        rng = np.random.default_rng(0)
        labels = rng.integers(0, 40, 2_000).astype(np.int32)
        values = rng.integers(0, 6, 2_000).astype(np.float32)
        flat_indices = rng.permutation(10_000)[:2_000]

        result = _per_label_argmax(labels, values, flat_indices, 45)

        assert_identical(
            result, _first_maximum_by_label(labels, values, flat_indices, 45)
        )

    @pytest.mark.parametrize("ties", [True, False], ids=["ties", "distinct"])
    def test_farthest_cells_overall_and_on_the_boundary(self, network, ties):
        _, labels = network
        # Maxima inside the labels, unlike flow distances; equal maxima test the
        # order, distinct ones reach the cells late in it (bottom of a label)
        rng = np.random.default_rng(1)
        if ties:
            values = rng.integers(0, 30, labels.shape).astype(np.float32)
        else:
            values = rng.permutation(labels.size).reshape(labels.shape)
            values = values.astype(np.float32)
        top = int(labels.max())
        boundary = np.zeros(labels.shape, dtype=bool)
        boundary[1:, :] |= labels[1:, :] != labels[:-1, :]
        boundary[:-1, :] |= labels[:-1, :] != labels[1:, :]
        boundary[:, 1:] |= labels[:, 1:] != labels[:, :-1]
        boundary[:, :-1] |= labels[:, :-1] != labels[:, 1:]
        boundary[[0, -1], :] = True
        boundary[:, [0, -1]] = True
        flat_labels, flat_values = labels.ravel(), values.ravel()
        cells = np.flatnonzero(flat_labels > 0)
        edge = np.flatnonzero(boundary.ravel() & (flat_labels > 0))

        best_dist, best_idx, divide_idx = _farthest_cells(labels, values, top)

        expected_dist, expected_idx = _first_maximum_by_label(
            flat_labels[cells], flat_values[cells], cells, top
        )
        _, expected_divide = _first_maximum_by_label(
            flat_labels[edge], flat_values[edge], edge, top
        )
        assert_identical(
            (best_dist, best_idx, divide_idx),
            (expected_dist, expected_idx, expected_divide),
        )
        assert (divide_idx != best_idx).any()

    def test_paths_end_at_the_first_cell_outside_the_label(self, network):
        hydrology, labels = network
        idxs_ds = hydrology.flw.idxs_ds
        # Every labelled cell starts a path, and a label of cells without a flow
        # direction (nodata) gives paths that end where they start
        flat_labels = labels.ravel().copy()
        flat_labels[np.flatnonzero(idxs_ds < 0)[:5]] = flat_labels.max() + 1
        starts = np.flatnonzero(flat_labels > 0)
        whole_paths, _ = hydrology.flw.path(idxs=starts)

        cells, offsets = _trace_in_labels(starts, flat_labels, idxs_ds)

        expected = []
        for start, path in zip(starts, whole_paths, strict=True):
            outside = np.flatnonzero(flat_labels[path] != flat_labels[start])
            expected.append(path[: outside[0] + 1] if outside.size else path)
        assert_identical(
            [cells[offsets[k] : offsets[k + 1]] for k in range(starts.size)], expected
        )


class TestSampleStreamDistance:
    """Tests for sample_stream_distance point sampling."""

    def test_sample_returns_float_values(self, tmp_path):
        """Point sampling should return numeric float values."""
        import rasterio
        from rasterio.transform import from_origin

        # Create a small test raster
        tif_path = str(tmp_path / "test_stream_dist.tif")
        transform = from_origin(0.0, 10.0, 1.0, 1.0)
        data = np.array([[100.0, 200.0], [300.0, 400.0]], dtype=np.float32)
        with rasterio.open(
            tif_path,
            "w",
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="float32",
            crs="EPSG:2180",
            transform=transform,
            nodata=-1,
        ) as dst:
            dst.write(data, 1)

        from core.watershed_service import sample_stream_distance

        result = sample_stream_distance([(0.5, 9.5)], tif_path)
        assert len(result) == 1
        assert isinstance(result[0], float)
        assert result[0] == pytest.approx(100.0)

    def test_sample_outside_raster_returns_nan(self, tmp_path):
        """Points outside raster extent should return NaN."""
        import rasterio
        from rasterio.transform import from_origin

        tif_path = str(tmp_path / "test_stream_dist.tif")
        transform = from_origin(0.0, 10.0, 1.0, 1.0)
        data = np.array([[100.0, 200.0], [300.0, 400.0]], dtype=np.float32)
        with rasterio.open(
            tif_path,
            "w",
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="float32",
            crs="EPSG:2180",
            transform=transform,
            nodata=-1,
        ) as dst:
            dst.write(data, 1)

        from core.watershed_service import sample_stream_distance

        # Point far outside
        result = sample_stream_distance([(999.0, 999.0)], tif_path)
        assert len(result) == 1
        # Outside points get nodata value which maps to NaN
        # or the rasterio default for out-of-bounds

    def test_sample_nodata_returns_nan(self, tmp_path):
        """Points at nodata cells should return NaN."""
        import rasterio
        from rasterio.transform import from_origin

        tif_path = str(tmp_path / "test_stream_dist.tif")
        transform = from_origin(0.0, 10.0, 1.0, 1.0)
        data = np.array([[-1.0, 200.0], [300.0, 400.0]], dtype=np.float32)
        with rasterio.open(
            tif_path,
            "w",
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="float32",
            crs="EPSG:2180",
            transform=transform,
            nodata=-1,
        ) as dst:
            dst.write(data, 1)

        from core.watershed_service import sample_stream_distance

        result = sample_stream_distance([(0.5, 9.5)], tif_path)
        assert len(result) == 1
        assert np.isnan(result[0])

    def test_sample_multiple_points(self, tmp_path):
        """Batch sampling should return one value per point."""
        import rasterio
        from rasterio.transform import from_origin

        tif_path = str(tmp_path / "test_stream_dist.tif")
        transform = from_origin(0.0, 10.0, 1.0, 1.0)
        data = np.array([[100.0, 200.0], [300.0, 400.0]], dtype=np.float32)
        with rasterio.open(
            tif_path,
            "w",
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="float32",
            crs="EPSG:2180",
            transform=transform,
            nodata=-1,
        ) as dst:
            dst.write(data, 1)

        from core.watershed_service import sample_stream_distance

        result = sample_stream_distance([(0.5, 9.5), (1.5, 9.5), (0.5, 8.5)], tif_path)
        assert len(result) == 3
        assert result[0] == pytest.approx(100.0)
        assert result[1] == pytest.approx(200.0)
        assert result[2] == pytest.approx(300.0)


class TestFlowPathAggregation:
    """Tests for hydraulic_length_km in aggregate_stats."""

    def test_hydraulic_length_from_max_flow_dist(self):
        """hydraulic_length_km = (max(max_flow_dist_m) - baseline) / 1000.

        Baseline is outlet_flow_dist_m[outlet_idx]; this fixture uses an
        all-zero baseline, so the result reduces to max(max_flow_dist_m) / 1000.
        """
        from core.catchment_graph import CatchmentGraph

        cg = CatchmentGraph()
        # Manually set up minimal graph state for testing
        n = 3
        cg._n = n
        cg._loaded = True
        cg._segment_idx = np.array([1, 2, 3], dtype=np.int32)
        cg._threshold_m2 = np.array([1000, 1000, 1000], dtype=np.int32)
        cg._area_km2 = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        cg._elev_min = np.array([100.0, 90.0, 80.0], dtype=np.float32)
        cg._elev_max = np.array([200.0, 210.0, 220.0], dtype=np.float32)
        cg._elev_mean = np.array([150.0, 150.0, 150.0], dtype=np.float32)
        cg._slope_mean = np.array([5.0, 5.0, 5.0], dtype=np.float32)
        cg._perimeter_km = np.array([4.0, 5.0, 6.0], dtype=np.float32)
        cg._stream_length_km = np.array([1.0, 1.5, 2.0], dtype=np.float32)
        cg._strahler = np.array([1, 2, 3], dtype=np.int8)
        cg._max_flow_dist_m = np.array([5000.0, 8000.0, 12000.0], dtype=np.float64)
        cg._hydraulic_length_km = np.full(n, np.nan, dtype=np.float32)
        cg._outlet_flow_dist_m = np.zeros(3, dtype=np.float64)

        indices = np.array([0, 1, 2], dtype=np.int32)
        stats = cg.aggregate_stats(indices, outlet_idx=2)

        assert stats["hydraulic_length_km"] == pytest.approx(12.0, rel=0.01)

    def test_hydraulic_length_zero_when_no_flow_dist(self):
        """hydraulic_length_km should be None when all max_flow_dist_m are 0."""
        from core.catchment_graph import CatchmentGraph

        cg = CatchmentGraph()
        n = 2
        cg._n = n
        cg._loaded = True
        cg._segment_idx = np.array([1, 2], dtype=np.int32)
        cg._threshold_m2 = np.array([1000, 1000], dtype=np.int32)
        cg._area_km2 = np.array([1.0, 2.0], dtype=np.float32)
        cg._elev_min = np.array([100.0, 90.0], dtype=np.float32)
        cg._elev_max = np.array([200.0, 210.0], dtype=np.float32)
        cg._elev_mean = np.array([150.0, 150.0], dtype=np.float32)
        cg._slope_mean = np.array([5.0, 5.0], dtype=np.float32)
        cg._perimeter_km = np.array([4.0, 5.0], dtype=np.float32)
        cg._stream_length_km = np.array([1.0, 1.5], dtype=np.float32)
        cg._strahler = np.array([1, 2], dtype=np.int8)
        cg._max_flow_dist_m = np.array([0.0, 0.0], dtype=np.float64)
        cg._hydraulic_length_km = np.full(n, np.nan, dtype=np.float32)
        cg._outlet_flow_dist_m = np.zeros(2, dtype=np.float64)

        indices = np.array([0, 1], dtype=np.int32)
        stats = cg.aggregate_stats(indices, outlet_idx=0)

        assert stats["hydraulic_length_km"] is None

    def test_get_max_flow_dist_m(self):
        """get_max_flow_dist_m should return correct value."""
        from core.catchment_graph import CatchmentGraph

        cg = CatchmentGraph()
        cg._loaded = True
        cg._max_flow_dist_m = np.array([5000.0, 8000.0], dtype=np.float64)

        assert cg.get_max_flow_dist_m(0) == pytest.approx(5000.0)
        assert cg.get_max_flow_dist_m(1) == pytest.approx(8000.0)

    def test_get_outlet_flow_dist_m(self):
        """Getter zwraca wartosc lub NaN gdy tablica nie zaladowana."""
        import math

        from core.catchment_graph import CatchmentGraph

        cg = CatchmentGraph()
        cg._loaded = True
        cg._outlet_flow_dist_m = np.array([100.0, 250.0], dtype=np.float64)
        assert cg.get_outlet_flow_dist_m(1) == pytest.approx(250.0)

        cg._outlet_flow_dist_m = None
        assert math.isnan(cg.get_outlet_flow_dist_m(0))


class TestMorphometricFlowPathFields:
    """Tests for flow path fields in MorphometricParameters schema."""

    def test_schema_accepts_flow_path_fields(self):
        """MorphometricParameters should accept all 3 flow path fields."""
        from models.schemas import MorphometricParameters

        params = MorphometricParameters(
            area_km2=10.0,
            perimeter_km=20.0,
            length_km=5.0,
            elevation_min_m=100.0,
            elevation_max_m=300.0,
            longest_flow_path_km=8.5,
            divide_flow_path_km=7.2,
            centroid_flow_path_km=5.1,
        )
        assert params.longest_flow_path_km == 8.5
        assert params.divide_flow_path_km == 7.2
        assert params.centroid_flow_path_km == 5.1

    def test_schema_defaults_to_none(self):
        """Flow path fields should default to None."""
        from models.schemas import MorphometricParameters

        params = MorphometricParameters(
            area_km2=10.0,
            perimeter_km=20.0,
            length_km=5.0,
            elevation_min_m=100.0,
            elevation_max_m=300.0,
        )
        assert params.longest_flow_path_km is None
        assert params.divide_flow_path_km is None
        assert params.centroid_flow_path_km is None

    def test_schema_rejects_negative_values(self):
        """Flow path fields should reject negative values."""
        from pydantic import ValidationError

        from models.schemas import MorphometricParameters

        with pytest.raises(ValidationError):
            MorphometricParameters(
                area_km2=10.0,
                perimeter_km=20.0,
                length_km=5.0,
                elevation_min_m=100.0,
                elevation_max_m=300.0,
                longest_flow_path_km=-1.0,
            )
