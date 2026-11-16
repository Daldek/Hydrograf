"""core.network_delineation on the rasters of a synthetic process_dem run.

process_dem runs over a main river with three tributaries, one with a tributary of its
own (tests.fixtures.pipeline_run.river_network_dem: T3, T2 and T1 from the north down,
T1a joining T1), with its rasters saved and the database replaced by recorders; the
catchment graph of its units of 1 ha is built from the recorded rows and a fake
database answers the queries of the measures. The points snap to the streams of
NETWORK_SNAP_THRESHOLD_M2. Every cell of the grid drains to the outlet cell on the
south edge, where A lies.
"""

import numpy as np
import pytest
import rasterio
import shapely
from rasterio.features import shapes
from shapely.geometry import MultiPolygon, Point, shape

import core.config
import core.network_delineation
from api.endpoints.watershed import _build_watershed_response
from core.cell_parameters import read_cells
from core.config import Settings
from core.errors import (
    InternalError,
    NotFoundError,
    StoreUnavailableError,
    UnsupportedError,
)
from core.network_delineation import (
    MIN_REACH_SLOPE_M_PER_M,
    Click,
    NetworkGrid,
    area_check,
    catchment_window,
    delineate_network,
    element_raster,
    open_network_rasters,
    snap_point,
)
from core.network_tree import Place, build_network_tree
from core.watershed_service import boundary_to_polygon
from tests.fixtures.pipeline_run import (
    NETWORK_CELL_M,
    NETWORK_SHAPE,
    NETWORK_SNAP_THRESHOLD_M2,
    NETWORK_UNIT_THRESHOLD_M2,
    NETWORK_X0,
    NETWORK_Y1,
    PANEL_FIELDS,
    PANEL_TOLERANCES,
    FakeDatabase,
    catchment_graph,
    land_cover_layout,
    river_network_dem,
    run_pipeline,
    soil_layout,
)
from utils.geometry import transform_wgs84_to_pl1992

UNITS = NETWORK_UNIT_THRESHOLD_M2
SNAP = NETWORK_SNAP_THRESHOLD_M2
CELL_KM2 = NETWORK_CELL_M**2 / 1e6
OUTLET = (219, 85)  # A: the outlet cell of the grid, on the main river
# The last cell of each tributary above its confluence with the main river, (row,
# column)
T3_MOUTH, T2_MOUTH, T1_MOUTH = (75, 86), (123, 86), (159, 84)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    return run_pipeline(
        tmp_path_factory.mktemp("network"),
        river_network_dem(),
        cell_m=NETWORK_CELL_M,
        x0=NETWORK_X0,
        y1=NETWORK_Y1,
        thresholds=[UNITS],
    )


@pytest.fixture(scope="module")
def graph(run):
    return catchment_graph(run, UNITS)


@pytest.fixture(scope="module")
def saved(run):
    """The saved rasters of the run, by their suffix."""
    arrays = {}
    for suffix in ("01_dem", "03_flowdir", "04_flowacc", "04b_stream_distance"):
        with rasterio.open(run.directory / f"dem_mosaic_{suffix}.tif") as src:
            arrays[suffix] = src.read(1)
    with rasterio.open(
        run.directory / f"dem_mosaic_10_subcatchments_{UNITS}.tif"
    ) as src:
        arrays["labels"] = src.read(1)
    return arrays


@pytest.fixture
def db(run):
    height_m, width_m = (n * NETWORK_CELL_M for n in NETWORK_SHAPE)
    return FakeDatabase(
        run,
        UNITS,
        land_cover=land_cover_layout(NETWORK_X0, NETWORK_Y1, width_m, height_m),
        soils=soil_layout(NETWORK_X0, NETWORK_Y1, width_m, height_m),
    )


@pytest.fixture
def settings(run, monkeypatch):
    """Settings of the run's rasters, also for the panel's code (get_settings)."""
    settings = Settings(dem_dir=str(run.directory))
    monkeypatch.setattr(core.config, "get_settings", lambda: settings)
    return settings


def click(run, point_id, cell, dx_m=0.0, dy_m=0.0):
    x, y = run.cell_centre_xy(*cell)
    return Click(point_id, x + dx_m, y + dy_m)


def elements_of(graph, db, settings, outlet, *points):
    """The tree, the window and the element raster of a network."""
    with open_network_rasters(settings) as (rasters, _):
        snapped = [snap_point(rasters, graph, c, SNAP) for c in (outlet, *points)]
        tree = build_network_tree(graph, snapped[0], snapped[1:], SNAP)
        window = catchment_window(rasters, graph, db, tree)
        grid = NetworkGrid(read_cells(rasters, window), window, rasters)
        elements, _, outside = element_raster(grid, graph, tree)
    return tree, grid, elements, outside


def at_the_mouths(run):
    return [
        click(run, "A", OUTLET),
        click(run, "P1", T1_MOUTH),
        click(run, "P2", T2_MOUTH),
        click(run, "P3", T3_MOUTH),
    ]


def cell_of(lat_lon_or_xy, wgs84=True):
    """The cell of the grid of a point (latitude, longitude) or (x, y)."""
    if wgs84:
        point = transform_wgs84_to_pl1992(*lat_lon_or_xy)
        x, y = point.x, point.y
    else:
        x, y = lat_lon_or_xy
    return int((NETWORK_Y1 - y) // NETWORK_CELL_M), int(
        (x - NETWORK_X0) // NETWORK_CELL_M
    )


class TestSnapping:
    def test_a_point_snaps_to_the_nearest_stream_cell(
        self, run, graph, settings, saved
    ):
        with open_network_rasters(settings) as (rasters, _):
            point = snap_point(rasters, graph, click(run, "P", (100, 85), 34, 2), SNAP)

        assert point.place.cell == (100, 85)
        label = int(saved["labels"][100, 85])
        assert point.place.unit == graph.lookup_by_segment_idx(UNITS, label)
        assert point.place.flow_dist_m == float(saved["04b_stream_distance"][100, 85])
        # Its path runs down the main river as far as N3 looks, and its cells up the
        # main river as far as the head cell of its unit, where a hollow joins
        assert [p.cell for p in point.path] == [(101 + i, 85) for i in range(5)]
        assert [p.cell for p in point.upstream] == [(99 - i, 85) for i in range(4)]
        assert [p.at_head for p in point.upstream] == [False, False, False, True]
        assert {p.unit for p in point.upstream} == {point.place.unit}

    def test_on_a_tie_the_larger_accumulation_wins(self, run, graph, settings, saved):
        # The corner of four cells: the main river above and below its confluence
        # with T2, T2's last cell and a cell of the valley side
        x = NETWORK_X0 + 86 * NETWORK_CELL_M
        y = NETWORK_Y1 - 124 * NETWORK_CELL_M
        with open_network_rasters(settings) as (rasters, _):
            point = snap_point(rasters, graph, Click("P", x, y), SNAP)

        acc = saved["04_flowacc"]
        around = [(123, 85), (124, 85), (123, 86)]
        assert all(acc[cell] >= SNAP / NETWORK_CELL_M**2 for cell in around)
        assert point.place.cell == max(around, key=lambda cell: acc[cell])
        assert point.place.cell == (124, 85)
        assert point.place.at_head

    @pytest.mark.parametrize(
        "where",
        [(30, 5), (-30, 60)],
        ids=["150 m from a stream", "off the rasters"],
    )
    def test_a_point_without_a_stream_within_100_m_is_refused(
        self, run, graph, settings, where
    ):
        with (
            open_network_rasters(settings) as (rasters, _),
            pytest.raises(NotFoundError) as raised,
        ):
            snap_point(rasters, graph, click(run, "P7", where), SNAP)

        assert raised.value.message_id == "network_point_off_stream"
        assert raised.value.details["point_id"] == "P7"
        assert raised.value.http_status == 404


@pytest.mark.parametrize("rows", [(100,), (99, 102)], ids=["one point", "two points"])
def test_points_split_their_unit_into_parts_that_partition_it(
    run, graph, db, settings, saved, rows
):
    points = [click(run, f"P{i}", (row, 85)) for i, row in enumerate(rows, start=1)]
    tree, grid, elements, _ = elements_of(
        graph, db, settings, click(run, "A", OUTLET), *points
    )

    unit = saved["labels"][100, 85]
    assert all(saved["labels"][row, 85] == unit for row in rows)
    window = (slice(grid.row0, None), slice(grid.col0, None))
    in_unit = saved["labels"][window][: elements.shape[0], : elements.shape[1]] == unit
    parts = np.unique(elements[in_unit])
    assert 0 not in parts
    assert len(parts) == len(rows) + 1
    numbers = {s.point: s.number for s in tree.subcatchments if s.point}
    # Each point's part holds its cell, the part below the last one the outlet cell
    for i, row in enumerate(rows, start=1):
        assert elements[grid.local((row, 85))] == numbers[f"P{i}"]
    (split,) = [s for s in tree.splits if s.unit == tree.points[1].place.unit]
    below = elements[grid.cell_of(split.outlets[-1][0])]
    assert set(parts.tolist()) == {
        numbers[f"P{i}"] for i in range(1, len(rows) + 1)
    } | {int(below)}


class TestTheElementsAddUpToA:
    def test_the_element_raster_partitions_the_catchment_of_a(
        self, run, graph, db, settings
    ):
        a, *points = at_the_mouths(run)
        gauge = click(run, "G", (140, 85))
        tree, grid, elements, outside = elements_of(
            graph, db, settings, a, *points, gauge
        )

        # Every cell of the grid drains to A, and A is the outlet cell of its unit
        assert outside == 0
        assert np.count_nonzero(elements) == NETWORK_SHAPE[0] * NETWORK_SHAPE[1]
        watershed_km2, elements_km2 = area_check(
            graph, tree, elements, outside, NETWORK_CELL_M
        )
        assert watershed_km2 == elements_km2 == pytest.approx(3.74)
        # Each element is closed downstream: only its outlet drains out of it
        cells = np.argwhere(elements > 0)
        leaving = {}
        for row, col in cells:
            below = grid.below((row, col))
            if below is None or elements[below] != elements[row, col]:
                leaving.setdefault(int(elements[row, col]), []).append((row, col))
        assert sorted(leaving) == [s.number for s in tree.subcatchments]
        assert all(len(cells) == 1 for cells in leaving.values())

    def test_a_unit_missing_from_the_window_is_a_defect(self, run, graph, db, settings):
        with open_network_rasters(settings) as (rasters, _):
            snapped = [snap_point(rasters, graph, c, SNAP) for c in at_the_mouths(run)]
            tree = build_network_tree(graph, snapped[0], snapped[1:], SNAP)
            window = catchment_window(rasters, graph, db, tree)
            cells = read_cells(rasters, window)
            grid = NetworkGrid(cells, window, rasters)
            # A unit of T2 that the window does not show
            cells.labels[cells.labels == cells.labels[grid.local((123, 120))]] = 0
            elements, _, outside = element_raster(grid, graph, tree)

        with pytest.raises(InternalError) as raised:
            area_check(graph, tree, elements, outside, NETWORK_CELL_M)

        assert raised.value.message_id == "network_area_mismatch"
        details = raised.value.details
        assert details["watershed_cells"] - details["elements_cells"] > 0
        assert raised.value.http_status == 500

    def test_a_closing_section_at_a_node_leaves_its_unit_outside(
        self, run, graph, db, settings, saved
    ):
        # A at the confluence of T1 and the main river: each branch ends at the
        # outlet cell of its unit above A, and A's own unit, its cell and the main
        # river below it, lies outside, so the check adds up the branches (N5, D11)
        tree, grid, elements, outside = elements_of(
            graph, db, settings, click(run, "A", (160, 85))
        )

        assert [(p.node, p.at_node) for p in tree.points] == [("J1", True)]
        assert (outside, tree.splits, int(tree.unit_elements[0])) == (0, (), 0)
        window = (slice(grid.row0, None), slice(grid.col0, None))
        labels = saved["labels"][window][: elements.shape[0], : elements.shape[1]]
        assert not elements[labels == saved["labels"][160, 85]].any()
        for element in tree.subcatchments:
            cells = np.count_nonzero(elements == element.number)
            assert cells * CELL_KM2 == pytest.approx(
                graph.get_upstream_area_km2(element.outlet.unit), abs=1e-6
            )
        watershed_km2, elements_km2 = area_check(
            graph, tree, elements, outside, NETWORK_CELL_M
        )
        assert watershed_km2 == elements_km2
        assert elements_km2 == round(np.count_nonzero(elements) * CELL_KM2, 6)


@pytest.fixture
def mouths(run, graph, db, settings):
    """The network of points at the mouths of T1, T2 and T3: whole units only."""
    a, *points = at_the_mouths(run)
    tree, grid, elements, _ = elements_of(graph, db, settings, a, *points)
    network = delineate_network(graph, db, a, points, SNAP, settings)
    return tree, grid, elements, network


def test_every_element_of_whole_units_has_the_parameters_of_the_panel(
    graph, db, mouths
):
    tree, grid, elements, network = mouths
    assert tree.splits == ()
    assert {p.point_id: p.at_node for p in network.points} == {
        "A": False,
        "P1": True,
        "P2": True,
        "P3": True,
    }
    differences = []
    for element in network.subcatchments:
        item = element.subcatchment
        units = tree.units[tree.unit_elements == item.number]
        outlet_unit = item.outlet.unit
        boundary = element.boundary_2180
        if boundary.geom_type == "Polygon":
            boundary = MultiPolygon([boundary])
        stats = graph.aggregate_stats(units, outlet_idx=outlet_unit)
        panel = _build_watershed_response(
            graph,
            boundary.representative_point(),
            boundary,
            boundary_to_polygon(boundary),
            units,
            outlet_unit,
            graph.get_segment_idx(outlet_unit),
            UNITS,
            UNITS,
            stats["area_km2"],
            stats,
            False,
            db,
        )
        expected = panel.morphometry.model_dump()
        got = element.watershed.morphometry.model_dump()
        for field in PANEL_FIELDS:
            want, have = expected[field], got[field]
            if want is None or have is None:
                same = want is have
            else:
                same = abs(want - have) <= PANEL_TOLERANCES.get(field, 1e-9)
            if not same:
                differences.append((item.id, field, want, have))
        if element.watershed.outlet.elevation_m != panel.outlet.elevation_m:
            differences.append((item.id, "outlet elevation", panel.outlet, element))
        shares = {c.category: c.percentage for c in panel.land_cover_stats.categories}
        mine = {
            c.category: c.percentage
            for c in element.watershed.land_cover_stats.categories
        }
        if mine != shares:
            differences.append((item.id, "land cover", shares, mine))
        outlet = element.watershed.outlet
        panel_outlet = panel.outlet
        distance = transform_wgs84_to_pl1992(
            outlet.latitude, outlet.longitude
        ).distance(
            transform_wgs84_to_pl1992(panel_outlet.latitude, panel_outlet.longitude)
        )
        if distance > NETWORK_CELL_M:
            differences.append((item.id, "outlet", distance))

    assert differences == []
    kinds = {e.subcatchment.kind for e in network.subcatchments}
    assert kinds == {"headwater", "intermediate"}


def test_a_przyrzecze_is_measured_within_it_and_its_channel_runs_up_its_reach(
    graph, saved, mouths
):
    tree, grid, elements, network = mouths
    reaches = {r.reach.id: r for r in network.reaches}
    flow_dist = saved["04b_stream_distance"]
    intermediates = [
        e for e in network.subcatchments if e.subcatchment.kind == "intermediate"
    ]
    assert len(intermediates) == len(network.reaches) == 3
    for element in intermediates:
        number = element.subcatchment.number
        line = element.watershed.longest_flow_path_geojson["geometry"]["coordinates"]
        cells = [grid.local(cell_of((lat, lon))) for lon, lat in line]
        head, end = cells[0], cells[-1]
        # From its farthest cell through its own cells to the cell below its outlet,
        # or to its outlet where the flow leaves the grid there (at A)
        outlet = element.watershed.outlet
        outlet_cell = grid.local(cell_of((outlet.latitude, outlet.longitude)))
        below = grid.below(outlet_cell)
        assert end == (outlet_cell if below is None else below)
        assert all(elements[cell] == number for cell in cells[:-1])
        assert (elements[end] == number) == (below is None)
        own = np.argwhere(elements == number)
        local_fd = flow_dist[grid.row0 :, grid.col0 :]
        assert local_fd[head] == max(local_fd[tuple(cell)] for cell in own)
        expected_km = (float(local_fd[head]) - float(local_fd[end])) / 1000
        morphometry = element.watershed.morphometry
        assert morphometry.flow_path_length_km == pytest.approx(expected_km, abs=1e-4)
        # Its channel is its reach, less the cell of its lower node when it ends at
        # the outlet cell above a node (N5)
        reach = reaches[element.subcatchment.reach]
        assert morphometry.channel_length_km == pytest.approx(
            reach.length_km, abs=NETWORK_CELL_M * 2**0.5 / 1000 + 1e-4
        )
        assert morphometry.channel_length_km <= reach.length_km + 1e-4


def test_a_reach_is_as_long_as_the_fall_of_the_flow_distance(graph, saved, mouths):
    tree, grid, elements, network = mouths
    flow_dist, nmt = saved["04b_stream_distance"], saved["01_dem"]
    for reach in network.reaches:
        upper = cell_of(reach.line_2180[0], wgs84=False)
        lower = cell_of(reach.line_2180[-1], wgs84=False)
        expected_km = (float(flow_dist[upper]) - float(flow_dist[lower])) / 1000
        assert reach.length_km == pytest.approx(expected_km, abs=1e-4)
        drop_m = float(nmt[upper]) - float(nmt[lower])
        assert drop_m > 0
        assert reach.slope_method == "nmt"
        assert reach.slope_m_per_m == pytest.approx(
            drop_m / (reach.length_km * 1000), abs=1e-6
        )
        assert reach.upstream_elevation_m == round(float(nmt[upper]), 2)
    # The flow distance of the graph at a node is the raster's at its cell: the three
    # points lie at the confluences, the head cells of their units
    nodes = [j for j in tree.junctions if j.id.startswith("J")]
    assert len(nodes) == 3
    for node in nodes:
        raster_fd = float(flow_dist[node.place.cell])
        above = tree.units[tree.below == node.place.unit].tolist()
        assert len(above) == 2
        for unit in above:
            assert graph.get_outlet_flow_dist_m(unit) == pytest.approx(
                raster_fd, abs=0.01
            )


def test_a_reach_whose_nmt_does_not_fall_gets_the_minimum_slope(
    run, graph, db, settings, saved, tmp_path, mouths
):
    _, _, _, network = mouths
    reach = network.reaches[0]
    upper = cell_of(reach.line_2180[0], wgs84=False)
    lower = cell_of(reach.line_2180[-1], wgs84=False)
    nmt = saved["01_dem"].copy()
    nmt[upper] = nmt[lower] - 0.5
    with rasterio.open(run.directory / "dem_mosaic_01_dem.tif") as src:
        profile = src.profile
    path = tmp_path / "nmt.tif"
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(nmt, 1)
    a, *points = at_the_mouths(run)
    lowered = Settings(dem_dir=str(run.directory), dem_path=str(path))

    again = delineate_network(graph, db, a, points, SNAP, lowered)

    first = again.reaches[0]
    assert first.reach.id == reach.reach.id
    assert (first.slope_m_per_m, first.slope_method) == (
        MIN_REACH_SLOPE_M_PER_M,
        "minimum",
    )
    assert first.upstream_elevation_m < first.downstream_elevation_m
    assert [r.slope_method for r in again.reaches[1:]] == ["nmt"] * 2


def test_the_boundaries_are_a_valid_coverage_whose_union_is_a(mouths):
    tree, grid, elements, network = mouths
    boundaries = [e.boundary_2180 for e in network.subcatchments]

    assert shapely.coverage_is_valid(np.array(boundaries))
    assert all(b.is_valid for b in boundaries)
    cells = shapely.union_all(
        [
            shape(geometry)
            for geometry, value in shapes(
                (elements > 0).astype(np.uint8), transform=grid.cells.transform
            )
            if value == 1
        ]
    )
    union = network.boundary_2180
    assert union.equals(shapely.union_all(boundaries))
    assert union.symmetric_difference(cells).area < 0.02 * cells.area
    # The areas are the cells', exact, and add up to A's
    for element in network.subcatchments:
        count = int(np.count_nonzero(elements == element.subcatchment.number))
        assert element.area_km2 == round(count * CELL_KM2, 6)
    total = sum(e.area_km2 for e in network.subcatchments)
    assert total == pytest.approx(network.area_km2, abs=1e-9)
    assert network.area_km2 == network.elements_km2


def test_a_split_unit_gives_the_elements_their_parts(run, graph, db, settings):
    a = click(run, "A", OUTLET)
    gauge = click(run, "G", (100, 85))
    tree, grid, elements, _ = elements_of(graph, db, settings, a, gauge)
    network = delineate_network(graph, db, a, [gauge], SNAP, settings)

    by_point = {e.subcatchment.point: e for e in network.subcatchments}
    headwater, below = by_point["G"], by_point["A"]
    assert headwater.subcatchment.kind == "headwater"
    assert below.subcatchment.kind == "intermediate"
    assert headwater.area_km2 + below.area_km2 == pytest.approx(network.area_km2)
    gauge_place = next(p.place for p in tree.points if p.point_id == "G")
    assert isinstance(gauge_place, Place) and not gauge_place.at_outlet
    outlet = headwater.watershed.outlet
    assert cell_of((outlet.latitude, outlet.longitude)) == (100, 85)
    assert headwater.watershed.morphometry.flow_path_length_km > 0
    assert Point(run.cell_centre_xy(100, 85)).within(headwater.boundary_2180.buffer(5))


def test_a_point_at_the_mouth_of_a_tributarys_tributary_is_that_confluence(
    run, graph, db, settings
):
    # No point at T1's mouth: P1 30 m above the corner where T1a joins T1's main river,
    # the arm from the north (0.80 km² there, T1a 0.32 km²), as on the author's
    # Kaczawa of 2026-11-11. P1 moves to the corner and receives both, the arm as its
    # main river; its reach runs down T1 to the node the network makes at T1's mouth
    tree, grid, elements, _ = elements_of(
        graph, db, settings, click(run, "A", OUTLET), click(run, "P1", (159, 47))
    )

    (p1,) = [p for p in tree.points if p.point_id == "P1"]
    assert (p1.at_node, p1.place.cell) == (True, (159, 50))
    z = {s.id: s for s in tree.subcatchments}
    (corner,) = [j for j in tree.junctions if j.id == p1.node]
    assert (corner.id, corner.kind) == ("J2", "point")
    arm, t1a = (z[i] for i in corner.inflows)
    assert [(s.kind, s.point, s.to) for s in (arm, t1a)] == [
        ("headwater", "P1", "J2"),
        ("headwater", "P1", "J2"),
    ]
    (reach,) = [r for r in tree.reaches if r.from_node == corner.id]
    mouth = next(j for j in tree.junctions if j.id == reach.to)
    assert (mouth.id, mouth.kind) == ("J1", "confluence")
    # The north arm, T1a and T1 below the corner
    cells = ((100, 49), (159, 40), (159, 70))
    assert [elements[grid.local(cell)] for cell in cells] == [
        arm.number,
        t1a.number,
        z[reach.intermediate].number,
    ]


class TestTheWindow:
    def test_it_grows_while_the_catchment_touches_its_sides(
        self, run, graph, db, settings, monkeypatch
    ):
        # The units' extent in the database shrunk to a box around A
        x, y = run.cell_centre_xy(*OUTLET)
        monkeypatch.setattr(
            core.network_delineation,
            "catchments_bounds",
            lambda *_: (x - 20, y - 20, x + 20, y + 20),
        )
        tree, grid, elements, outside = elements_of(
            graph, db, settings, *at_the_mouths(run)
        )

        assert elements.shape == NETWORK_SHAPE
        watershed_km2, elements_km2 = area_check(
            graph, tree, elements, outside, NETWORK_CELL_M
        )
        assert watershed_km2 == elements_km2

    def test_a_window_above_the_cap_is_refused_before_it_is_read(
        self, run, graph, db, settings, monkeypatch
    ):
        monkeypatch.setattr(
            core.network_delineation, "NETWORK_MAX_WINDOW_CELLS", 10_000
        )
        monkeypatch.setattr(
            core.network_delineation,
            "read_cells",
            lambda *_: pytest.fail("the window was read"),
        )
        a, *points = at_the_mouths(run)

        with pytest.raises(UnsupportedError) as raised:
            delineate_network(graph, db, a, points, SNAP, settings)

        assert raised.value.message_id == "network_window_too_large"
        assert raised.value.details["max_cells"] == 10_000
        assert raised.value.details["cells"] > 10_000
        assert raised.value.http_status == 422


def test_missing_rasters_are_named(tmp_path):
    with (
        pytest.raises(StoreUnavailableError) as raised,
        open_network_rasters(Settings(dem_dir=str(tmp_path))),
    ):
        pass

    assert raised.value.message_id == "network_rasters_missing"
    assert set(raised.value.details["rasters"]) == {
        "02_filled",
        "03_flowdir",
        "04_flowacc",
        "04b_stream_distance",
        "05_slope",
        f"10_subcatchments_{UNITS}",
        "01_dem",
    }
    assert raised.value.http_status == 503


def test_rasters_off_one_grid_are_refused(run, tmp_path):
    for path in run.directory.glob("dem_mosaic*.tif"):
        (tmp_path / path.name).symlink_to(path)
    slope = tmp_path / "dem_mosaic_05_slope.tif"
    with rasterio.open(slope) as src:
        profile, data = src.profile, src.read(1)
    slope.unlink()
    profile["transform"] = profile["transform"] * rasterio.Affine.translation(1, 0)
    with rasterio.open(slope, "w", **profile) as dst:
        dst.write(data, 1)

    with (
        pytest.raises(StoreUnavailableError) as raised,
        open_network_rasters(Settings(dem_dir=str(tmp_path))),
    ):
        pass

    assert raised.value.message_id == "raster_grids_differ"
