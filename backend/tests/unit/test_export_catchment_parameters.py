"""scripts.export_catchment_parameters gives a polygon the values of the panel.

process_dem runs over a synthetic DEM (a valley falling to the south, ridges across it
and a hill) with its rasters saved and the database replaced by recorders of the rows
it would insert; the catchment graph is built from those rows as CatchmentGraph.load
builds it from the database. For a watershed of the graph the response builder of
POST /api/delineate-watershed (precomputed mode) gives the values of the panel, and
the export of the boundary of that watershed must give the same values. The database
of both is a fake: synthetic land cover, BDOT10k flags and the ends of the stream
segments.
"""

from contextlib import contextmanager
from itertools import combinations
from types import SimpleNamespace
from unittest.mock import MagicMock

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from pyproj import CRS
from rasterio.transform import from_origin
from scipy import sparse
from shapely import wkb, wkt
from shapely.geometry import MultiPolygon, box
from shapely.ops import unary_union

import core.config
from api.endpoints.watershed import _build_watershed_response
from core.active_run import write_active_run
from core.catchment_graph import CatchmentGraph
from core.config import Settings
from core.watershed_service import boundary_to_polygon
from scripts.export_catchment_parameters import (
    COLUMN_NAMES,
    COLUMNS,
    export,
    main_channel,
    open_rasters,
    polygon_parameters,
    read_polygon_cells,
    read_polygons,
)
from scripts.process_dem import process_dem
from utils.geometry import transform_wgs84_to_pl1992

CELLS = 100
CELL_M = 10.0
X0, Y1 = 500_000.0, 600_000.0  # north-west corner of the DEM
THRESHOLD_M2 = 5000
# The CRS of the MPHP catchments (ESRI:102173), PL-1992 under another datum name
ESRI_102173 = (
    'PROJCS["ETRS_1989_UWPP_1992",GEOGCS["ETRS89",DATUM["European_Terrestrial_'
    'Reference_System_1989",SPHEROID["GRS 1980",6378137,298.257222101]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
    'PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],'
    'PARAMETER["central_meridian",19],PARAMETER["scale_factor",0.9993],'
    'PARAMETER["false_easting",500000],PARAMETER["false_northing",-5300000],'
    'UNIT["metre",1],AUTHORITY["ESRI","102173"]]'
)
# The panel's values that the graph aggregates from sub-catchment values rounded
# to 0.01 (mean elevation [m], mean slope [%]), and the outlet, which the panel
# takes at the end of the outlet's stream segment snapped to the boundary
TOLERANCES = {"elevation_mean_m": 0.01, "mean_slope_m_per_m": 0.00005}
PANEL_FIELDS = (
    "area_km2",
    "perimeter_km",
    "elevation_min_m",
    "elevation_max_m",
    "elevation_mean_m",
    "mean_slope_m_per_m",
    "channel_length_km",
    "real_channel_length_km",
    "channel_slope_m_per_m",
    "flow_path_length_km",
    "flow_path_slope_m_per_m",
    "overland_length_km",
    "overland_slope_m_per_m",
    "divide_flow_path_km",
    "cn",
    "compactness_coefficient",
    "circularity_ratio",
)
# Synthetic land cover: forest in the west, arable land in the east, a pond between
_POND = box(X0 + 400, Y1 - 600, X0 + 600, Y1 - 400)
LAND_COVER = (
    ("las", "PTLZ", 0.0, box(X0, Y1 - 1000, X0 + 500, Y1).difference(_POND)),
    (
        "grunt_orny",
        "PTTR:grunty orne",
        0.1,
        box(X0 + 500, Y1 - 1000, X0 + 1000, Y1).difference(_POND),
    ),
    ("woda", "PTWP", 1.0, _POND),
)
# Synthetic soil groups: A in the west, B in the rest but a strip in the north-east
# without a soil group
SOILS = (
    ("A", box(X0, Y1 - 1000, X0 + 300, Y1)),
    ("B", box(X0 + 300, Y1 - 1000, X0 + 1000, Y1 - 200)),
)


def is_real(segment_idx):
    """BDOT10k flag of a segment: two of every three, so channels have gaps."""
    return segment_idx % 3 != 2


def line_length_m(segment):
    """length_m of stream_network: its smoothed line, shorter than its cells' path."""
    return round(0.95 * segment["length_m"], 1)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """Rasters of process_dem in a directory, its segments and sub-catchments."""
    directory = tmp_path_factory.mktemp("nmt")
    y, x = np.mgrid[0:CELLS, 0:CELLS]
    dem = (
        100.0
        + 0.5 * (CELLS - y)
        + 0.3 * np.abs(x - CELLS / 2)
        + 2.0 * np.sin(x / 4.0) * np.cos(y / 5.0)
        + 12.0 * np.exp(-((x - 50) ** 2 + (y - 15) ** 2) / 40.0)
    ).astype("float32")
    dem_path = directory / "dem_mosaic.tif"
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        height=CELLS,
        width=CELLS,
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=from_origin(X0, Y1, CELL_M, CELL_M),
        nodata=-9999.0,
    ) as dst:
        dst.write(dem, 1)

    rows = {}

    @contextmanager
    def session():
        yield MagicMock()

    def insert_segments(db, segments, threshold_m2, **_):
        rows[("segments", threshold_m2)] = segments
        return len(segments)

    def insert_catchments(db, catchments, threshold_m2, **_):
        rows[("catchments", threshold_m2)] = catchments
        return len(catchments)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("core.database.get_db_session", session)
        patch.setattr("scripts.process_dem.insert_stream_segments", insert_segments)
        patch.setattr("scripts.process_dem.insert_catchments", insert_catchments)
        patch.setattr(
            "scripts.process_dem.update_stream_real_flags_all", lambda db, t: {}
        )
        process_dem(
            dem_path,
            save_intermediates=True,
            output_dir=directory,
            thresholds=[1000, THRESHOLD_M2],
        )
    return SimpleNamespace(
        directory=directory,
        segments=rows[("segments", THRESHOLD_M2)],
        catchments=sorted(
            rows[("catchments", THRESHOLD_M2)], key=lambda c: c["segment_idx"]
        ),
    )


@pytest.fixture(scope="module")
def graph(run):
    """The catchment graph of the threshold, as CatchmentGraph.load builds it."""
    catchments = run.catchments
    n = len(catchments)

    def column(key, dtype=np.float32):
        values = [np.nan if c.get(key) is None else c[key] for c in catchments]
        return np.array(values, dtype=dtype)

    def segment(c):
        return run.segments[c["segment_idx"] - 1]

    cg = CatchmentGraph()
    cg._n = n
    cg._segment_idx = np.array([c["segment_idx"] for c in catchments], np.int32)
    cg._threshold_m2 = np.full(n, THRESHOLD_M2, np.int32)
    cg._area_km2 = column("area_km2")
    cg._elev_min = column("elevation_min_m")
    cg._elev_max = column("elevation_max_m")
    cg._elev_mean = column("mean_elevation_m")
    cg._slope_mean = column("mean_slope_percent")
    cg._stream_length_km = column("stream_length_km")
    cg._hydraulic_length_km = column("hydraulic_length_km")
    cg._strahler = np.array([c["strahler_order"] or 0 for c in catchments], np.int8)
    cg._max_flow_dist_m = np.nan_to_num(column("max_flow_dist_m", np.float64))
    cg._outlet_flow_dist_m = column("outlet_flow_dist_m", np.float64)
    cg._flow_path_head_elev_m = column("flow_path_head_elev_m")
    cg._overland_length_m = column("overland_length_m")
    cg._overland_drop_m = column("overland_drop_m")
    cg._stream_head_elev_m = column("stream_head_elev_m")
    cg._histograms = [c["elev_histogram"] for c in catchments]
    cg._is_real_stream = np.array([is_real(c["segment_idx"]) for c in catchments])
    cg._segment_length_km = np.array(
        [line_length_m(segment(c)) / 1000.0 for c in catchments]
    )
    cg._upstream_area_km2 = np.array(
        [segment(c)["upstream_area_km2"] for c in catchments]
    )
    cg._lookup = {(THRESHOLD_M2, c["segment_idx"]): i for i, c in enumerate(catchments)}
    links = [
        (i, cg._lookup[(THRESHOLD_M2, c["downstream_segment_idx"])])
        for i, c in enumerate(catchments)
        if c.get("downstream_segment_idx") is not None
    ]
    upstream, downstream = zip(*links, strict=True)
    cg._upstream_adj = sparse.csr_matrix(
        (np.ones(len(links), np.int8), (downstream, upstream)), shape=(n, n)
    )
    cg._loaded = True
    return cg


class FakeDatabase:
    """Answers the queries of the panel and of the export from synthetic data."""

    def __init__(self, run):
        self.segments = run.segments
        self.catchments = {c["segment_idx"]: c for c in run.catchments}

    @staticmethod
    def _result(rows=(), row=None, scalar=None):
        return SimpleNamespace(
            fetchall=lambda: list(rows),
            fetchone=lambda: row,
            scalar=lambda: scalar,
        )

    def execute(self, statement, params=None):
        sql = str(statement)
        if "FROM land_cover lc" in sql:
            boundary = wkb.loads(bytes.fromhex(params["boundary_wkb"]))
            rows = []
            for category, bdot_class, imperviousness, geometry in LAND_COVER:
                inside = geometry.intersection(boundary)
                if inside.is_empty:
                    continue
                pieces = [(None, inside)] + [
                    (group, inside.intersection(soil)) for group, soil in SOILS
                ]
                rows.extend(
                    SimpleNamespace(
                        category=category,
                        bdot_class=bdot_class,
                        imperviousness=imperviousness,
                        hsg_group=group,
                        area_m2=piece.area,
                    )
                    for group, piece in pieces
                    if not piece.is_empty
                )
            return self._result(rows)
        if "FROM soil_hsg sh" in sql:
            boundary = wkb.loads(bytes.fromhex(params["boundary_wkb"]))
            areas = {g: s.intersection(boundary).area for g, s in SOILS}
            total = sum(areas.values())
            return self._result(
                SimpleNamespace(
                    hsg_group=g, total_area_m2=a, percentage=a / total * 100
                )
                for g, a in sorted(areas.items(), key=lambda item: -item[1])
                if a > 0
            )
        if "is_real_stream" in sql and "ANY" in sql:
            return self._result(
                SimpleNamespace(
                    segment_idx=i,
                    is_real=is_real(i),
                    line_length_m=line_length_m(self.segments[i - 1]),
                    stream_length_km=self.catchments[i]["stream_length_km"],
                )
                for i in params["idxs"]
                if i in self.catchments
            )
        if "ST_EndPoint(geom)" in sql:
            x, y = self.segments[params["seg_idx"] - 1]["coords"][-1]
            return self._result(row=SimpleNamespace(x=x, y=y))
        if "EXISTS" in sql:
            return self._result(scalar=True)
        return self._result()


@pytest.fixture
def db(run):
    return FakeDatabase(run)


@pytest.fixture
def rasters(run, monkeypatch):
    """The rasters of the run, also for the API (DEM_DIR)."""
    settings = Settings(dem_dir=str(run.directory))
    monkeypatch.setattr(core.config, "get_settings", lambda: settings)
    with open_rasters(run.directory, THRESHOLD_M2) as opened:
        yield opened


def boundary_of(run, cg, outlet_idx):
    """Union of the cells of the sub-catchments upstream of a node."""
    labels = set(cg.get_segment_indices(cg.traverse_upstream(outlet_idx), THRESHOLD_M2))
    union = unary_union(
        [wkt.loads(c["wkt"]) for c in run.catchments if c["segment_idx"] in labels]
    )
    return MultiPolygon([union]) if union.geom_type == "Polygon" else union


def panel_of(cg, outlet_idx, boundary, db):
    """The response of POST /api/delineate-watershed for a watershed of the graph."""
    upstream = cg.traverse_upstream(outlet_idx)
    stats = cg.aggregate_stats(upstream, outlet_idx=outlet_idx)
    return _build_watershed_response(
        cg,
        boundary.representative_point(),
        boundary,
        boundary_to_polygon(boundary),
        upstream,
        outlet_idx,
        cg.get_segment_idx(outlet_idx),
        THRESHOLD_M2,
        THRESHOLD_M2,
        stats["area_km2"],
        stats,
        False,
        db,
    )


@pytest.fixture(scope="module")
def watersheds(run, graph):
    """Boundaries of the watersheds of every node that are one polygon, by node."""
    found = {}
    for outlet_idx in range(graph._n):
        boundary = boundary_of(run, graph, outlet_idx)
        # Cells touching at a corner make parts that the panel's gap closing of the
        # merged boundary joins and the bare union does not
        if len(boundary.geoms) == 1:
            found[outlet_idx] = boundary
    return found


def test_a_delineated_watershed_gets_the_values_of_the_panel(
    graph, watersheds, rasters, db
):
    differences = []
    divide_paths = real_channels = 0
    for outlet_idx, boundary in watersheds.items():
        panel = panel_of(graph, outlet_idx, boundary, db)
        expected = panel.morphometry.model_dump()
        row = polygon_parameters(boundary, rasters, db)
        for field in PANEL_FIELDS:
            want, got = expected[field], row[field]
            if want is None or got is None:
                same = want is got
            else:
                same = abs(want - got) <= TOLERANCES.get(field, 1e-9)
            if not same:
                differences.append((outlet_idx, field, want, got))
        if row["outlet_elevation_m"] != panel.outlet.elevation_m:
            differences.append(
                (outlet_idx, "outlet_elevation_m", panel.outlet.elevation_m, row)
            )
        shares = {c.category: c.percentage for c in panel.land_cover_stats.categories}
        exported = {
            category: row[f"lc_{category}_pct"]
            for category, *_ in LAND_COVER
            if row[f"lc_{category}_pct"]
        }
        if exported != shares:
            differences.append((outlet_idx, "land cover", shares, exported))
        panel_outlet = transform_wgs84_to_pl1992(
            panel.outlet.latitude, panel.outlet.longitude
        )
        outlet = transform_wgs84_to_pl1992(
            row["outlet_latitude_deg"], row["outlet_longitude_deg"]
        )
        if panel_outlet.distance(outlet) > CELL_M:
            differences.append((outlet_idx, "outlet", panel_outlet, outlet))
        divide_paths += expected["divide_flow_path_km"] is not None
        real_channels += bool(expected["real_channel_length_km"])

    assert differences == []
    # The watersheds compared have flow paths from the divide and BDOT10k channels
    assert len(watersheds) > 20
    assert divide_paths > 0
    assert real_channels > 0


def test_a_watershed_has_the_ratio_one_and_no_flag(watersheds, rasters, db):
    _, boundary = max(watersheds.items(), key=lambda item: item[1].area)

    row = polygon_parameters(boundary, rasters, db)

    assert row["polygon_to_upstream_area_ratio"] == 1.0
    assert row["outlet_upstream_area_km2"] == row["area_km2"]
    assert row["cell_count"] == round(boundary.area / CELL_M**2)
    assert row["quality_flag"] is None


def test_the_main_channel_crosses_a_gap_in_the_polygon(watersheds, rasters, db):
    # A boundary that leaves out a cell of the channel (one drawn without the NMT):
    # the channel goes on above it as in the whole watershed
    boundary = max(watersheds.values(), key=lambda w: w.area)
    cells = read_polygon_cells(boundary, rasters)
    outlet = np.unravel_index(
        np.argmax(np.where(cells.member, cells.acc, -1)), (cells.member.shape)
    )
    stream = (cells.acc >= rasters.threshold_cells) & cells.valid
    row, col = main_channel(cells, tuple(map(int, outlet)), stream)[10]
    (x0, y1), (x1, y0) = (
        cells.transform * (col, row),
        cells.transform * (col + 1, row + 1),
    )
    with_gap = boundary.difference(box(x0, y0, x1, y1))

    row_with_gap = polygon_parameters(with_gap, rasters, db)
    whole = polygon_parameters(boundary, rasters, db)

    assert row_with_gap["cell_count"] == whole["cell_count"] - 1
    for field in (
        "channel_length_km",
        "real_channel_length_km",
        "channel_slope_m_per_m",
    ):
        assert row_with_gap[field] == whole[field], field


def test_every_part_of_a_multipart_polygon_counts(watersheds, rasters, db):
    # Two separate watersheds: the outlet lies in the one of the larger accumulation
    a, b = next(
        (a, b)
        for a, b in combinations(sorted(watersheds.values(), key=lambda w: -w.area), 2)
        if a.distance(b) > CELL_M
    )
    both = MultiPolygon([*a.geoms, *b.geoms])

    row = polygon_parameters(both, rasters, db)
    alone = polygon_parameters(a, rasters, db)
    other = polygon_parameters(b, rasters, db)

    assert row["cell_count"] == alone["cell_count"] + other["cell_count"]
    assert row["area_km2"] == pytest.approx(alone["area_km2"] + other["area_km2"])
    assert row["perimeter_km"] == pytest.approx(
        alone["perimeter_km"] + other["perimeter_km"], abs=1e-4
    )
    assert row["elevation_min_m"] == min(
        alone["elevation_min_m"], other["elevation_min_m"]
    )
    assert row["elevation_max_m"] == max(
        alone["elevation_max_m"], other["elevation_max_m"]
    )
    # The flow paths and the main channel are those of the outlet's part
    for field in (
        "outlet_latitude_deg",
        "outlet_longitude_deg",
        "outlet_upstream_area_km2",
        "flow_path_length_km",
        "divide_flow_path_km",
        "overland_length_km",
        "channel_length_km",
        "real_channel_length_km",
    ):
        assert row[field] == alone[field], field
    assert row["polygon_to_upstream_area_ratio"] == pytest.approx(
        (a.area + b.area) / a.area, abs=1e-4
    )
    # The land cover of both parts, weighted by their areas (the panel takes the
    # largest part of a boundary only)
    assert row["cn"] == pytest.approx(
        (alone["cn"] * a.area + other["cn"] * b.area) / (a.area + b.area), abs=0.1
    )


def test_a_polygon_partly_outside_the_data_has_the_values_of_its_inside_part(
    rasters, db
):
    polygon = box(X0 - 300, Y1 - 700, X0 + 300, Y1 - 300)
    inside = box(X0, Y1 - 700, X0 + 300, Y1 - 300)

    row = polygon_parameters(polygon, rasters, db)
    expected = polygon_parameters(inside, rasters, db)

    assert row["quality_flag"] == "partly_outside_nmt"
    assert row["cell_count"] == 30 * 40
    assert row["polygon_area_km2"] == pytest.approx(0.24)
    for field in COLUMN_NAMES:
        if field not in {
            "polygon_area_km2",
            "perimeter_km",
            "polygon_to_upstream_area_ratio",
            "compactness_coefficient",
            "circularity_ratio",
            "quality_flag",
        }:
            assert row[field] == expected[field], field


def test_a_polygon_outside_the_data_has_no_terrain_values(rasters, db):
    row = polygon_parameters(box(X0 - 300, Y1 - 700, X0 - 100, Y1 - 300), rasters, db)

    assert row["quality_flag"] == "under_100_cells;outside_nmt"
    assert row["cell_count"] == 0
    assert row["area_km2"] is None
    assert row["polygon_area_km2"] == pytest.approx(0.08)


def test_a_polygon_of_few_cells_is_flagged(rasters, db):
    nine_cells = box(X0 + 300, Y1 - 330, X0 + 330, Y1 - 300)

    row = polygon_parameters(nine_cells, rasters, db)

    dem = rasters.filled_dem.read(1)[30:33, 30:33]
    assert row["cell_count"] == 9
    assert row["area_km2"] == 0.0009
    assert row["elevation_min_m"] == round(float(dem.min()), 2)
    assert row["elevation_max_m"] == round(float(dem.max()), 2)
    assert row["quality_flag"] == "under_100_cells"


def test_a_polygon_without_a_cell_centre_has_only_its_area_and_land_cover(rasters, db):
    sliver = box(X0 + 301, Y1 - 304, X0 + 304, Y1 - 301)

    row = polygon_parameters(sliver, rasters, db)

    assert row["cell_count"] == 0
    assert row["quality_flag"] == "under_100_cells"
    assert row["lc_las_pct"] == 100.0
    assert row["cn"] == 55.0  # woods, good, on soil group B
    assert row["polygon_area_km2"] == 0.0
    from_rasters = [
        c.name
        for c in COLUMNS
        if c.section in ("Parametry podstawowe", "Wskaźniki kształtu")
        and c.name not in ("perimeter_km", "cn")
    ] + ["outlet_upstream_area_km2", "polygon_to_upstream_area_ratio"]
    assert {name: row[name] for name in from_rasters} == dict.fromkeys(from_rasters)


def test_cn_of_the_soil_cover_complexes_and_the_soil_groups(rasters, db):
    """The whole domain: forest and arable land on A and B, a strip without soil.

    Land cover on a soil group [m²]: forest 300 000 on A and 140 000 on B, arable land
    380 000 on B, the pond 40 000 on B; without one: forest 40 000 and arable land
    100 000 (14%), which take the shares of the rest, A 300/860 and B 560/860.
    """
    domain = box(X0, Y1 - 1000, X0 + 1000, Y1)
    a, b = 300 / 860, 560 / 860
    forest = ((300_000 + 40_000 * a) * 30 + (140_000 + 40_000 * b) * 55) / 480_000
    arable = (100_000 * a * 63 + (380_000 + 100_000 * b) * 75) / 480_000
    cn = (forest * 480_000 + arable * 480_000 + 98 * 40_000) / 1_000_000

    row = polygon_parameters(domain, rasters, db)

    assert row["cn"] == round(cn, 1) == 58.1
    assert (row["lc_las_cn"], row["lc_grunt_orny_cn"], row["lc_woda_cn"]) == (
        round(forest, 1),
        round(arable, 1),
        98.0,
    )
    # AMC II is the composite CN; I and III are Hydrolog's conversion of it, as the
    # hydrograph converts it
    assert (row["cn_amc_i"], row["cn_amc_ii"], row["cn_amc_iii"]) == (38, 58.1, 76)
    assert [row[f"hsg_{g}_pct"] for g in "abcd"] == [34.9, 65.1, 0.0, 0.0]
    assert row["lc_without_hsg_pct"] == 14.0


def test_a_polygon_without_soil_groups_takes_group_b(rasters, db):
    strip = box(X0 + 600, Y1 - 150, X0 + 900, Y1 - 50)  # arable land, no soil group

    row = polygon_parameters(strip, rasters, db)

    assert row["cn"] == 75.0  # small grain, good, on B
    assert row["lc_without_hsg_pct"] == 100.0
    assert [row[f"hsg_{g}_pct"] for g in "abcd"] == [None] * 4


def _write_layer(path, frame):
    frame.to_file(path, layer="zlewnie", driver="GPKG")
    return path


def _catchments(crs):
    return gpd.GeoDataFrame(
        {
            "ID_HYD_10": ["1001", "1002"],
            "ID_HYD_50": ["10", "10"],
            "NAZ_ZLEWNI": ["Dopływ spod Lasu", "Struga"],
            "POW": [1.0, 2.0],
        },
        geometry=[
            box(X0 + 100, Y1 - 400, X0 + 400, Y1 - 100),
            box(X0 + 500, Y1 - 900, X0 + 900, Y1 - 500),
        ],
        crs=crs,
    )


def test_a_layer_in_esri_102173_is_read_as_pl1992(tmp_path):
    path = _write_layer(tmp_path / "in.gpkg", _catchments(CRS.from_wkt(ESRI_102173)))

    polygons = read_polygons(path, None, "ID_HYD_10", ["NAZ_ZLEWNI"])

    assert list(polygons.columns) == ["ID_HYD_10", "NAZ_ZLEWNI", "geometry"]
    assert polygons.crs.to_epsg() == 2180


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda f: f.to_crs("EPSG:4326"), "CRS mismatch"),
        (lambda f: f.to_crs("EPSG:2177"), "CRS mismatch"),
        (lambda f: f.assign(ID_HYD_10=["1001", "1001"]), "must be unique"),
        (lambda f: f.drop(columns="NAZ_ZLEWNI"), "no field NAZ_ZLEWNI"),
    ],
)
def test_a_layer_that_does_not_fit_is_refused(tmp_path, change, message):
    path = _write_layer(tmp_path / "in.gpkg", change(_catchments("EPSG:2180")))

    with pytest.raises(ValueError, match=message):
        read_polygons(path, "zlewnie", "ID_HYD_10", ["NAZ_ZLEWNI"])


def test_the_export_writes_the_polygons_their_columns_and_units(
    tmp_path, run, rasters, db
):
    source = _write_layer(tmp_path / "in.gpkg", _catchments("EPSG:2180"))
    output = tmp_path / "out.gpkg"

    count = export(
        source,
        "zlewnie",
        "ID_HYD_10",
        ["ID_HYD_50", "NAZ_ZLEWNI"],
        output,
        "parametry",
        run.directory,
        THRESHOLD_M2,
        db,
    )

    written = gpd.read_file(output, layer="parametry")
    units = gpd.read_file(output, layer="parametry_units")
    assert count == 2
    assert list(written.columns) == [
        "ID_HYD_10",
        "ID_HYD_50",
        "NAZ_ZLEWNI",
        *COLUMN_NAMES,
        "geometry",
    ]
    assert list(written["NAZ_ZLEWNI"]) == ["Dopływ spod Lasu", "Struga"]
    assert written.crs.to_epsg() == 2180
    assert written.geometry.geom_equals(_catchments("EPSG:2180").geometry).all()
    expected = polygon_parameters(written.geometry[1], rasters, db)
    assert written.loc[1, "area_km2"] == expected["area_km2"]
    assert written.loc[1, "lc_grunt_orny_pct"] == expected["lc_grunt_orny_pct"]
    assert dict(zip(units["column_name"], units["unit"], strict=True)) == {
        c.name: c.unit for c in COLUMNS
    }


def _vrt_of(tif, vrt):
    """A VRT of one GeoTIFF, as a unit run writes its mosaics."""
    with rasterio.open(tif) as source:
        geo = ", ".join(repr(v) for v in source.transform.to_gdal())
        nodata = (
            ""
            if source.nodata is None
            else f"<NoDataValue>{source.nodata!r}</NoDataValue>"
        )
        gdal_type = {
            "float32": "Float32",
            "float64": "Float64",
            "uint8": "Byte",
            "int32": "Int32",
            "uint32": "UInt32",
            "int16": "Int16",
        }[source.dtypes[0]]
        vrt.write_text(
            f'<VRTDataset rasterXSize="{source.width}" rasterYSize="{source.height}">'
            f"<SRS>EPSG:2180</SRS><GeoTransform>{geo}</GeoTransform>"
            f'<VRTRasterBand dataType="{gdal_type}" band="1">{nodata}<SimpleSource>'
            f'<SourceFilename relativeToVRT="1">{tif.name}</SourceFilename>'
            "<SourceBand>1</SourceBand></SimpleSource></VRTRasterBand></VRTDataset>"
        )


def test_the_rasters_of_an_active_unit_run_are_read(tmp_path, run, rasters):
    """A unit run publishes VRT mosaics in its run directory, not dem_mosaic_*.tif."""
    run_dir = tmp_path / "unit_runs" / "token"
    run_dir.mkdir(parents=True)
    for tif in run.directory.glob("dem_mosaic_*.tif"):
        copy = run_dir / tif.name
        copy.write_bytes(tif.read_bytes())
        _vrt_of(copy, run_dir / f"{tif.stem}.vrt")
    write_active_run(tmp_path, 1, run_dir)

    with open_rasters(tmp_path, THRESHOLD_M2) as opened:
        assert opened.filled_dem.name.endswith("dem_mosaic_02_filled.vrt")
        assert opened.labels.name.endswith(
            f"dem_mosaic_10_subcatchments_{THRESHOLD_M2}.vrt"
        )
        np.testing.assert_array_equal(opened.acc.read(1), rasters.acc.read(1))
        np.testing.assert_array_equal(opened.labels.read(1), rasters.labels.read(1))


def test_the_export_does_not_overwrite_a_file(tmp_path, run, db):
    source = _write_layer(tmp_path / "in.gpkg", _catchments("EPSG:2180"))
    output = tmp_path / "out.gpkg"
    output.write_bytes(b"")

    with pytest.raises(ValueError, match="exists"):
        export(
            source,
            "zlewnie",
            "ID_HYD_10",
            [],
            output,
            "parametry",
            run.directory,
            THRESHOLD_M2,
            db,
        )
