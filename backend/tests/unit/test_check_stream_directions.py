"""scripts.check_stream_directions finds BDOT10k lines digitized upstream (ADR-077)."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

from scripts.check_stream_directions import (
    ATTRIBUTES,
    analyze,
    catchment_order,
    categories,
    check,
    join_ends,
    mouth_test,
    orient_watercourses,
    parse_layer_spec,
    sample_profiles,
    split_at_t_junctions,
    trace_watercourses,
    verdicts,
    watercourse_keys,
)

CELL_M = 5.0
X0, Y1 = -50.0, 350.0  # north-west corner of the DEM
SLOPE = 0.005  # the DEM falls east by 5 m per km
AREA = box(-1000.0, -1000.0, 2000.0, 1000.0)


def _dem(slope=SLOPE):
    """A DEM falling east (``slope`` m/m) over x -50..1000 m, y -350..350 m."""
    cols = np.arange(210) * CELL_M + X0 + CELL_M / 2
    dem = np.tile(100.0 - slope * cols, (140, 1)).astype(np.float32)
    return dem, from_origin(X0, Y1, CELL_M, CELL_M)


def _geoms(*lines):
    result = np.empty(len(lines), dtype=object)
    result[:] = [LineString(line) for line in lines]
    return result


# A watercourse of three lines from x 0 to 900 whose middle line is digitized
# upstream (west), and its receiver, a line of the prefix code through x 900
KCYNKA = [((0, 0), (300, 0)), ((600, 0), (300, 0)), ((600, 0), (900, 0))]
RECEIVER = [((900, 300), (900, 0)), ((900, 0), (900, -300))]


def _raw(connector_middle=False):
    """The lines of KCYNKA (MPHP 18852) and RECEIVER (MPHP 188) as read_lines reads."""
    rows = []
    geometry = []
    for i, line in enumerate(KCYNKA + RECEIVER):
        attributes = dict.fromkeys(ATTRIBUTES, "")
        attributes["IDENTYFIKATORMPHP"] = "18852" if i < 3 else "188"
        attributes["NAZWA"] = "Kcynka" if i < 3 else "Noteć"
        if connector_middle and i == 1:
            attributes["CECHAGEOMETRII"] = "sztuczny łącznik"
        rows.append({"warstwa": "SWRS", **attributes, "glowny": True})
        geometry.append(LineString(line))
    return gpd.GeoDataFrame(rows, geometry=geometry, crs=2180)


def _analyze(raw):
    dem, transform = _dem()
    empty = np.array([], dtype=object)
    return analyze(raw, AREA, empty, dem, transform, -9999.0, None, "main")


class TestParseLayerSpec:
    def test_layer_after_the_last_colon(self):
        assert parse_layer_spec("dane/obszar.gpkg:Zlewnie") == (
            Path("dane/obszar.gpkg"),
            "Zlewnie",
        )

    def test_without_a_layer(self):
        assert parse_layer_spec("dane/obszar.gpkg") == (Path("dane/obszar.gpkg"), None)

    def test_a_colon_in_a_directory_is_part_of_the_path(self):
        assert parse_layer_spec("a:b/obszar.gpkg") == (Path("a:b/obszar.gpkg"), None)


class TestSplitAtTJunctions:
    def test_an_end_on_the_middle_of_a_line_splits_it(self):
        geoms = _geoms(((0, 0), (100, 0)), ((40, 30), (40, 0.3)))
        pieces, source, part, ends_on_middle = split_at_t_junctions(geoms)
        assert source.tolist() == [0, 0, 1]
        assert part.tolist() == [0, 1, 0]
        assert pieces[0].coords[-1] == pytest.approx((40.0, 0.0))
        assert pieces[1].coords[0] == pytest.approx((40.0, 0.0))
        assert ends_on_middle.tolist() == [False, True]

    def test_ends_meeting_ends_split_nothing(self):
        geoms = _geoms(((0, 0), (100, 0)), ((100.3, 30), (100.3, 0.2)))
        pieces, source, _, ends_on_middle = split_at_t_junctions(geoms)
        assert len(pieces) == 2
        assert source.tolist() == [0, 1]
        assert not ends_on_middle.any()

    def test_an_end_farther_than_the_tolerance_splits_nothing(self):
        geoms = _geoms(((0, 0), (100, 0)), ((40, 30), (40, 0.6)))
        pieces, _, _, _ = split_at_t_junctions(geoms)
        assert len(pieces) == 2


class TestJoinEnds:
    def test_ends_within_half_a_metre_are_one_node(self):
        geoms = _geoms(((0, 0), (10, 0)), ((10.3, 0), (20, 0)), ((20, 0.7), (30, 0)))
        u, v, node_xy = join_ends(geoms)
        assert v[0] == u[1]
        assert v[1] != u[2]
        assert node_xy[v[0]] == pytest.approx((10.15, 0.0))
        assert len(node_xy) == 5


class TestWatercourses:
    def _course(self, slope):
        geoms = _geoms(*KCYNKA)
        u, v, _ = join_ends(geoms)
        key = watercourse_keys(
            np.array(["18852"] * 3, dtype=object), np.array([""] * 3)
        )
        closed = np.zeros(3, dtype=bool)
        courses, course, forward, joint = trace_watercourses(u, v, key, closed)
        dem, transform = _dem(slope)
        profiles = sample_profiles(geoms, dem, transform, -9999.0)
        lengths = np.array([g.length for g in geoms])
        versus, weight = orient_watercourses(courses, profiles, lengths, forward)
        return courses, course, joint, versus, weight

    def test_joints_where_the_digitizing_turns(self):
        _, course, joint, _, _ = self._course(SLOPE)
        assert course.tolist() == [0, 0, 0]
        assert joint.tolist() == [["", "ogon"], ["glowa", "ogon"], ["glowa", ""]]

    def test_the_dem_of_the_whole_watercourse_finds_the_line_against_it(self):
        courses, _, _, versus, weight = self._course(SLOPE)
        assert courses[0].source == "nmt"
        assert courses[0].rise_m == pytest.approx(-SLOPE * 675, abs=0.05)
        assert versus.tolist() == ["zgodny", "odwrocony", "zgodny"]
        assert weight.tolist() == [2, 2, 2]

    def test_a_flat_watercourse_goes_the_way_of_its_longer_digitizing(self):
        courses, _, _, versus, weight = self._course(0.0)
        assert courses[0].source == "wiekszosc"
        assert versus.tolist() == ["zgodny", "odwrocony", "zgodny"]
        assert weight.tolist() == [1, 1, 1]

    def test_a_line_without_mphp_or_name_belongs_to_no_watercourse(self):
        key = watercourse_keys(
            np.array(["18852", "", ""], dtype=object),
            np.array(["Kcynka", "Struga", ""], dtype=object),
        )
        assert key.tolist() == ["M:18852", "N:Struga", ""]


class TestMouthTest:
    def _test(self, lines, codes):
        geoms = _geoms(*lines)
        u, v, _ = join_ends(geoms)
        lengths = np.array([g.length for g in geoms])
        closed = np.zeros(len(lines), dtype=bool)
        return mouth_test(u, v, np.array(codes, dtype=object), lengths, closed)

    def test_lines_flow_to_the_receiver(self):
        result = self._test(KCYNKA + RECEIVER, ["18852"] * 3 + ["188"] * 2)
        assert result.tolist() == ["zgodny", "odwrocony", "zgodny", None, None]

    def test_a_tributary_is_no_mouth_of_its_receiver(self):
        tributary = [((-300, 0), (0, 0))]
        result = self._test(KCYNKA + tributary, ["18852"] * 3 + ["188521"])
        # 18852 reaches no line of a prefix code; the tributary flows into 18852
        assert result.tolist() == [None, None, None, "zgodny"]

    def test_with_two_contacts_each_line_flows_to_the_nearer(self):
        lines = [((900, 300), (900, 0)), ((-300, 0), (0, 0))] + KCYNKA
        result = self._test(lines, ["188", "188"] + ["18852"] * 3)
        assert result.tolist() == [None, None, "odwrocony", None, "zgodny"]


class TestCatchmentOrder:
    def test_order_of_the_river_s_own_catchments(self):
        result = catchment_order(
            np.array(["188", "188", "188", "188", "188"], dtype=object),
            np.array(["188519", "188531", "188519", "188519", "186"], dtype=object),
            np.array(["188531", "188519", "188422", "188519", "188531"], dtype=object),
        )
        assert result.tolist() == ["zgodny", "odwrocony", None, None, None]


class TestVerdicts:
    def test_weights_of_the_evidence(self):
        dem = np.array(["w_gore_wyraznie", "w_gore_slabo", "w_dol", "plaski", "w_dol"])
        in_run = np.array([False, False, False, True, False])
        catchment = np.array([None, None, "odwrocony", None, None], dtype=object)
        versus = np.array(["", "odwrocony", "", "", ""], dtype=object)
        weight = np.array([0, 1, 0, 0, 0])
        verdict, against, along = verdicts(dem, in_run, catchment, versus, weight)
        assert verdict.tolist() == [
            "odwrocony",
            "odwrocony",
            "sprzeczny",
            "podejrzany",
            "zgodny",
        ]
        assert against.tolist() == [2, 2, 2, 1, 0]
        assert along.tolist() == [0, 0, 2, 0, 2]


class TestCategories:
    def test_doubtful_reversed_lines_set_apart(self):
        verdict = np.array(
            ["odwrocony", "odwrocony", "odwrocony", "odwrocony", "zgodny"]
        )
        connector = np.array([False, True, False, True, True])
        detached = np.array([False, False, True, True, True])
        assert categories(verdict, connector, detached).tolist() == [
            "odwrocony",
            "odwrocony_lacznik",
            "odwrocony_siec_oderwana",
            "odwrocony_lacznik",
            "zgodny",
        ]


class TestAnalyze:
    def test_a_line_digitized_upstream_inside_its_watercourse(self):
        lines, nodes, courses = _analyze(_raw())
        assert lines["werdykt"].tolist()[:3] == ["zgodny", "odwrocony", "zgodny"]
        assert lines["kategoria"].tolist()[:3] == ["zgodny", "odwrocony", "zgodny"]
        assert lines["test_ujscia"].fillna("-").tolist() == [
            "zgodny",
            "odwrocony",
            "zgodny",
            "-",
            "-",
        ]
        # ADR-072 keeps it: its DEM rises 1.1 m, under 2 m
        assert lines["nmt"].tolist()[1] == "w_gore_slabo"
        assert not lines["hydrograf_odwraca"].any()
        kcynka = courses[courses["ciek"] == "M:18852"].iloc[0]
        assert kcynka["kierunek_z"] == "nmt"
        assert kcynka["odwrocone_odcinki"] == 1
        noteć = courses[courses["ciek"] == "M:188"].iloc[0]
        assert kcynka["uchodzi_do"] == str(noteć["id"])
        assert kcynka.geometry.coords[-1] == pytest.approx((900.0, 0.0))
        mouth = nodes[nodes["id"] == kcynka["wezel_ujscia"]].iloc[0]
        assert (mouth["typ"], mouth["typ_po"]) == ("zbieg", "zbieg")

    def test_a_reversed_connector_is_doubtful(self):
        lines, _, _ = _analyze(_raw(connector_middle=True))
        assert lines["kategoria"].tolist()[1] == "odwrocony_lacznik"


def test_an_existing_output_is_refused(tmp_path):
    out = tmp_path / "kierunki.gpkg"
    out.write_bytes(b"")
    with pytest.raises(ValueError, match="exists"):
        check(
            tmp_path / "hydro.gpkg",
            tmp_path / "dem.tif",
            "area.gpkg",
            None,
            "main",
            out,
        )
