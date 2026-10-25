"""Tests for the sub-catchment steps of core.stream_extraction.

The network is a 5 x 6 grid of 10 m cells, south-west corner at (1000, 2000):

    flow direction         stream (acc >= 3)     catchment after delineation
    S  S  S  S  SW SW      .  .  .  .  .  .      3 3 3 1 1 2
    S  S  S  S  S  S       .  .  .  B  .  .      3 3 3 1 2 2
    E  E  E  E  E  E       A  A  A  M  M  M      3 3 3 2 2 2
    N  N  N  N  N  N       .  .  .  .  .  .      3 3 3 2 2 2
    N  N  N  N  E  pit     .  .  .  .  .  .      3 3 3 2 0 0

Tributary A (row 2, columns 0-2) and tributary B (cell (1, 3)) meet in the
confluence cell (2, 3); the main stem M runs east off the grid. The two cells at the
bottom right drain into a pit that no stream reaches, so no catchment owns them.
Segments are numbered in the order vectorize_streams finds them: B = 1, M = 2,
A = 3.
"""

from types import SimpleNamespace

import numpy as np
import pyflwdir
import pytest
from rasterio.transform import from_origin
from shapely import wkt as shapely_wkt

from core.stream_extraction import (
    compute_downstream_links,
    delineate_subcatchments,
    polygonize_subcatchments,
    vectorize_streams,
)

CELL_M = 10.0
XLL, YLL = 1000.0, 2000.0
NODATA = -9999.0
N, E, S, SW = 64, 1, 4, 8
PIT = 0


@pytest.fixture
def network():
    """Flow network of the module docstring, vectorized but not yet delineated."""
    fdir = np.array(
        [
            [S, S, S, S, SW, SW],
            [S, S, S, S, S, S],
            [E, E, E, E, E, E],
            [N, N, N, N, N, N],
            [N, N, N, N, E, PIT],
        ],
        dtype=np.uint8,
    )
    nrows, ncols = fdir.shape
    transform = from_origin(XLL, YLL + nrows * CELL_M, CELL_M, CELL_M)
    flw = pyflwdir.from_array(fdir, ftype="d8", transform=transform, latlon=False)
    acc = flw.upstream_area(unit="cell").astype(np.int32)

    strahler = np.zeros((nrows, ncols), dtype=np.uint8)
    strahler[1, 3] = 1
    strahler[2, 0:3] = 1
    strahler[2, 3:] = 2

    # Elevation falls to the east and rises away from the stream row.
    rows, cols = np.indices((nrows, ncols))
    dem = 100.0 - 2.0 * cols + 3.0 * np.abs(rows - 2)
    slope = np.full((nrows, ncols), 4.0)
    metadata = {
        "cellsize": CELL_M,
        "xllcorner": XLL,
        "yllcorner": YLL,
        "nodata_value": NODATA,
    }
    labels = np.zeros((nrows, ncols), dtype=np.int32)
    segments = vectorize_streams(
        dem,
        fdir,
        acc,
        slope,
        strahler,
        metadata,
        stream_threshold=3,
        label_raster_out=labels,
    )
    return SimpleNamespace(
        fdir=fdir,
        flw=flw,
        dem=dem,
        slope=slope,
        metadata=metadata,
        labels=labels,
        segments=segments,
    )


@pytest.fixture
def delineated(network):
    """The network with downstream links set and every cell assigned to a segment."""
    compute_downstream_links(
        network.segments, network.labels, network.fdir, network.metadata
    )
    delineate_subcatchments(network.flw, network.labels, network.dem, NODATA)
    return network


class TestComputeDownstreamLinks:
    def test_tributaries_drain_into_the_main_stem(self, network):
        compute_downstream_links(
            network.segments, network.labels, network.fdir, network.metadata
        )

        links = [seg["downstream_segment_idx"] for seg in network.segments]

        assert links == [2, None, 2]

    def test_outlet_without_a_usable_next_cell_has_no_downstream_segment(self):
        # 1 x 4 grid; every segment looks at a different kind of next cell.
        fdir = np.array([[E, E, E, PIT]], dtype=np.uint8)
        labels = np.array([[1, 4, 0, 2]], dtype=np.int32)
        segments = [
            {"_outlet_rc": (0, 0)},  # flows E into a cell of segment 4
            {"_outlet_rc": (0, 3)},  # is a pit
            {},  # has no recorded outlet
            {"_outlet_rc": (0, 1)},  # flows E into a cell that no segment owns
            {"_outlet_rc": (0, 2)},  # flows E into a cell of segment 2
        ]

        compute_downstream_links(segments, labels, fdir, {})

        assert [s["downstream_segment_idx"] for s in segments] == [
            4,
            None,
            None,
            None,
            2,
        ]

    def test_outlet_flowing_off_the_grid_has_no_downstream_segment(self):
        fdir = np.array([[E, E]], dtype=np.uint8)
        labels = np.array([[1, 1]], dtype=np.int32)
        segments = [{"_outlet_rc": (0, 1)}]

        compute_downstream_links(segments, labels, fdir, {})

        assert segments[0]["downstream_segment_idx"] is None

    def test_segment_draining_into_itself_is_not_linked(self):
        fdir = np.array([[E, PIT]], dtype=np.uint8)
        labels = np.array([[1, 1]], dtype=np.int32)  # the only segment is number 1
        segments = [{"_outlet_rc": (0, 0)}]

        compute_downstream_links(segments, labels, fdir, {})

        assert segments[0]["downstream_segment_idx"] is None


class TestDelineateSubcatchments:
    def test_every_cell_takes_the_segment_it_drains_to(self, network):
        delineate_subcatchments(network.flw, network.labels, network.dem, NODATA)

        expected = np.array(
            [
                [3, 3, 3, 1, 1, 2],
                [3, 3, 3, 1, 2, 2],
                [3, 3, 3, 2, 2, 2],
                [3, 3, 3, 2, 2, 2],
                [3, 3, 3, 2, 0, 0],
            ]
        )
        assert np.array_equal(network.labels, expected)

    def test_cells_draining_to_an_unseeded_pit_stay_unlabelled(self, network):
        delineate_subcatchments(network.flw, network.labels, network.dem, NODATA)

        assert network.labels[4, 4] == 0
        assert network.labels[4, 5] == 0

    def test_the_label_raster_is_updated_in_place_and_returned(self, network):
        result = delineate_subcatchments(
            network.flw, network.labels, network.dem, NODATA
        )

        assert result is network.labels
        assert result.dtype == np.int32


class TestPolygonizeSubcatchments:
    def _polygonize(self, net, **kwargs):
        return polygonize_subcatchments(
            net.labels, net.dem, net.slope, net.metadata, net.segments, **kwargs
        )

    def test_one_catchment_per_segment_in_label_order(self, delineated):
        catchments = self._polygonize(delineated)

        assert [c["segment_idx"] for c in catchments] == [1, 2, 3]

    def test_area_is_the_cell_count_times_the_cell_area(self, delineated):
        catchments = self._polygonize(delineated)

        # 3, 10 and 15 cells of 100 m2; 2 of the 30 cells drain to the pit.
        assert [c["area_km2"] for c in catchments] == [0.0003, 0.001, 0.0015]

    def test_polygons_cover_exactly_the_cells_of_their_catchment(self, delineated):
        catchments = self._polygonize(delineated)

        for c in catchments:
            polygon = shapely_wkt.loads(c["wkt"])
            assert polygon.geom_type == "MultiPolygon"
            assert polygon.area / 1e6 == pytest.approx(c["area_km2"])
        union_m2 = shapely_wkt.loads(catchments[0]["wkt"])
        for c in catchments[1:]:
            union_m2 = union_m2.union(shapely_wkt.loads(c["wkt"]))
        assert union_m2.area == pytest.approx(28 * CELL_M**2)
        assert union_m2.bounds == (XLL, YLL, XLL + 6 * CELL_M, YLL + 5 * CELL_M)

    def test_perimeter_is_measured_on_the_polygon(self, delineated):
        catchments = self._polygonize(delineated)

        # Catchment 3 is the 30 m x 50 m block of columns 0-2.
        assert catchments[2]["perimeter_km"] == pytest.approx(0.16)

    def test_elevation_statistics_come_from_the_cells_of_the_catchment(
        self, delineated
    ):
        catchments = self._polygonize(delineated)

        stats = [
            (c["mean_elevation_m"], c["elevation_min_m"], c["elevation_max_m"])
            for c in catchments
        ]
        assert stats == [
            (98.33, 97.0, 100.0),
            (94.5, 90.0, 100.0),
            (101.6, 96.0, 106.0),
        ]
        assert [c["mean_slope_percent"] for c in catchments] == [4.0, 4.0, 4.0]

    def test_elevation_histogram_counts_cells_per_metre(self, delineated):
        catchments = self._polygonize(delineated)

        assert catchments[0]["elev_histogram"] == {
            "base_m": 97,
            "interval_m": 1,
            "counts": [1, 1, 0, 1],  # 97 m, 98 m, (99 m), 100 m
        }
        assert sum(catchments[1]["elev_histogram"]["counts"]) == 10
        assert sum(catchments[2]["elev_histogram"]["counts"]) == 15

    def test_segment_attributes_are_carried_over(self, delineated):
        catchments = self._polygonize(delineated)

        assert [c["strahler_order"] for c in catchments] == [1, 2, 1]
        assert [c["downstream_segment_idx"] for c in catchments] == [2, None, 2]
        # Segment lengths are 10, 20 and 30 m.
        assert [c["stream_length_km"] for c in catchments] == [0.01, 0.02, 0.03]

    def test_hydraulic_length_is_the_longest_flow_distance_in_the_catchment(
        self, delineated
    ):
        # Distance grows with the row-major cell number, so the maximum of a
        # catchment is the distance of its highest-numbered cell.
        flow_dist_m = np.arange(30, dtype=np.float64).reshape(5, 6) * 10.0

        catchments = self._polygonize(delineated, flow_dist_m=flow_dist_m)

        # Highest cells: catchment 1 -> (1,3) = 9, 2 -> (4,3) = 27, 3 -> (4,2) = 26.
        assert [c["hydraulic_length_km"] for c in catchments] == [0.09, 0.27, 0.26]

    def test_hydraulic_length_is_missing_without_a_flow_distance(self, delineated):
        catchments = self._polygonize(delineated)

        assert [c["hydraulic_length_km"] for c in catchments] == [None] * 3

    def test_a_flow_distance_that_is_not_positive_gives_no_hydraulic_length(
        self, delineated
    ):
        flow_dist_m = np.zeros((5, 6))

        catchments = self._polygonize(delineated, flow_dist_m=flow_dist_m)

        assert [c["hydraulic_length_km"] for c in catchments] == [None] * 3

    def test_nodata_cells_do_not_enter_the_elevation_statistics(self, delineated):
        delineated.dem[0, 0] = NODATA  # a cell of catchment 3 (106 m)

        catchments = self._polygonize(delineated)

        c3 = catchments[2]
        assert c3["mean_elevation_m"] == pytest.approx((1524 - 106) / 14, abs=0.01)
        assert c3["elevation_max_m"] == 106.0  # (4,0) is 106 m as well
        assert c3["elevation_min_m"] == 96.0
        assert sum(c3["elev_histogram"]["counts"]) == 14
        assert c3["area_km2"] == 0.0015  # the cell still belongs to the catchment

    def test_catchment_of_nodata_cells_has_no_elevation_statistics(self):
        labels = np.array([[1, 1], [2, 2]], dtype=np.int32)
        dem = np.array([[NODATA, NODATA], [50.0, 52.0]])
        slope = np.full((2, 2), 3.0)
        metadata = {
            "cellsize": CELL_M,
            "xllcorner": XLL,
            "yllcorner": YLL,
            "nodata_value": NODATA,
        }

        catchments = polygonize_subcatchments(labels, dem, slope, metadata, [])

        empty, valid = catchments
        assert empty["mean_elevation_m"] is None
        assert empty["elevation_min_m"] is None
        assert empty["elevation_max_m"] is None
        assert empty["elev_histogram"] is None
        assert empty["mean_slope_percent"] == 3.0
        assert valid["mean_elevation_m"] == 51.0
        assert (valid["elevation_min_m"], valid["elevation_max_m"]) == (50.0, 52.0)

    def test_catchment_without_a_segment_has_no_segment_attributes(self):
        labels = np.array([[1, 5]], dtype=np.int32)
        dem = np.array([[10.0, 12.0]])
        metadata = {
            "cellsize": CELL_M,
            "xllcorner": XLL,
            "yllcorner": YLL,
            "nodata_value": NODATA,
        }
        segments = [
            {"strahler_order": 3, "length_m": 55.0, "downstream_segment_idx": 2}
        ]

        catchments = polygonize_subcatchments(
            labels, dem, np.zeros((1, 2)), metadata, segments
        )

        with_segment, without_segment = catchments
        assert with_segment["strahler_order"] == 3
        assert with_segment["stream_length_km"] == 0.055
        assert with_segment["downstream_segment_idx"] == 2
        assert without_segment["segment_idx"] == 5
        assert without_segment["strahler_order"] is None
        assert without_segment["stream_length_km"] is None
        assert without_segment["downstream_segment_idx"] is None

    def test_an_explicit_transform_places_the_polygons(self, delineated):
        metadata = dict(delineated.metadata)
        metadata["transform"] = from_origin(
            XLL + 500.0, YLL + 500.0 + 5 * CELL_M, CELL_M, CELL_M
        )

        catchments = polygonize_subcatchments(
            delineated.labels,
            delineated.dem,
            delineated.slope,
            metadata,
            delineated.segments,
        )

        polygon = shapely_wkt.loads(catchments[2]["wkt"])
        assert polygon.bounds == (XLL + 500.0, YLL + 500.0, XLL + 530.0, YLL + 550.0)
