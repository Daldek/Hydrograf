"""Tests for the bulk import and BDOT10k matching functions of core.db_bulk.

PostgreSQL is replaced by FakeCursor, a DB-API cursor that keeps one ordered log of
the statements and of the text sent through COPY, so a test can say what was loaded
and in which order. The statements themselves run against PostGIS in the `db` tests.
"""

import json
import logging
from types import SimpleNamespace

import geopandas as gpd
import pytest
from shapely import wkt as shapely_wkt
from shapely.geometry import LineString, MultiLineString, Polygon

from core.db_bulk import (
    insert_bdot_streams,
    insert_catchments,
    insert_stream_segments,
    load_bdot_streams_from_gpkg,
    override_statement_timeout,
    update_stream_real_flags,
    update_stream_real_flags_all,
)


class FakeCursor:
    """DB-API cursor with a log of everything the code under test does."""

    def __init__(self, fetches=None, rowcounts=None, fail_on=None):
        self.events = []  # ("execute" | "copy", whitespace-normalised SQL)
        self.executed = []  # (whitespace-normalised SQL, parameters)
        self.copied = []  # the text sent through each COPY
        self.rowcount = 0
        # A statement is answered by the first entry whose key it starts with.
        self._fetches = {"SHOW statement_timeout": ("30s",), **(fetches or {})}
        self._rowcounts = rowcounts or {}
        self._fail_on = fail_on
        self._answer = None

    @staticmethod
    def _lookup(table, sql):
        return next((v for key, v in table.items() if sql.startswith(key)), None)

    def execute(self, sql, params=None):
        sql = " ".join(sql.split())
        if self._fail_on and sql.startswith(self._fail_on):
            raise RuntimeError(f"database refused: {sql[:40]}")
        self.events.append(("execute", sql))
        self.executed.append((sql, params))
        self.rowcount = self._lookup(self._rowcounts, sql) or 0
        self._answer = self._lookup(self._fetches, sql)

    def copy_expert(self, sql, buffer):
        self.events.append(("copy", " ".join(sql.split())))
        self.copied.append(buffer.read())

    def fetchone(self):
        return self._answer

    def statements(self):
        return [sql for sql, _ in self.executed]

    def ran(self, prefix):
        """The executed statements that start with `prefix`."""
        return [sql for sql in self.statements() if sql.startswith(prefix)]

    def params_of(self, prefix):
        """The parameters of every statement that starts with `prefix`."""
        return [p for sql, p in self.executed if sql.startswith(prefix)]

    def order_of(self, *prefixes):
        """The given statement prefixes, in the order the cursor saw them."""
        return [
            prefix
            for _, sql in self.events
            for prefix in prefixes
            if sql.startswith(prefix)
        ]


class FakeSession:
    """The part of a SQLAlchemy session the bulk functions use.

    `session.connection().connection` is the DB-API connection.
    """

    def __init__(self, **cursor_args):
        self.cursor = FakeCursor(**cursor_args)
        self.commits = 0
        self.rollbacks = 0
        self.connections = 0
        self.raw = SimpleNamespace(
            cursor=lambda: self.cursor,
            commit=self._commit,
            rollback=self._rollback,
        )

    def _commit(self):
        self.commits += 1

    def _rollback(self):
        self.rollbacks += 1

    def connection(self):
        self.connections += 1
        return SimpleNamespace(connection=self.raw)


def rows_of(text):
    return [line.split("\t") for line in text.splitlines()]


def loaded_rows(cursor, table):
    """The rows sent through COPY, keyed by the columns of `table`.

    The columns come from the CREATE TEMP TABLE statement the cursor saw, so a
    value that lands in the wrong column of the staging table fails the test.
    """
    (create,) = cursor.ran(f"CREATE TEMP TABLE {table}")
    inner = create[create.index("(") + 1 : create.rindex(")")]
    columns = [part.split()[0] for part in inner.split(",")]
    (text,) = cursor.copied
    return [dict(zip(columns, fields, strict=True)) for fields in rows_of(text)]


class TestOverrideStatementTimeout:
    def test_timeout_is_changed_for_the_block_and_then_restored(self):
        db = FakeSession(fetches={"SHOW statement_timeout": ("45s",)})

        with override_statement_timeout(db, timeout_s=600):
            during = db.cursor.statements()

        assert during == ["SHOW statement_timeout", "SET statement_timeout = '600s'"]
        assert db.cursor.statements()[-1] == "SET statement_timeout = '45s'"
        assert db.commits == 2  # a SET inside an open transaction would be lost

    def test_zero_means_no_limit(self):
        db = FakeSession()

        with override_statement_timeout(db):
            pass

        assert "SET statement_timeout = '0s'" in db.cursor.statements()

    def test_original_timeout_returns_when_the_block_fails(self):
        db = FakeSession(fetches={"SHOW statement_timeout": ("45s",)})

        with pytest.raises(KeyError), override_statement_timeout(db, timeout_s=5):
            raise KeyError("work failed")

        assert db.cursor.statements()[-1] == "SET statement_timeout = '45s'"

    def test_a_closed_connection_does_not_hide_the_result_of_the_block(self):
        db = FakeSession(fail_on="SET statement_timeout = '30s'")

        with override_statement_timeout(db, timeout_s=5):
            result = "finished"

        assert result == "finished"

    @pytest.mark.parametrize("bad", [-1, 1.5, "5", "5s'; DROP TABLE streams; --", None])
    def test_only_non_negative_integers_reach_the_sql(self, bad):
        db = FakeSession()

        with (
            pytest.raises(ValueError, match="non-negative integer"),
            override_statement_timeout(db, timeout_s=bad),
        ):
            pass

        assert db.connections == 0


class TestInsertStreamSegmentRows:
    def test_each_segment_is_a_row_with_its_wkt_and_a_one_based_index(self):
        db = FakeSession(rowcounts={"INSERT INTO stream_network": 2})
        segments = [
            {
                "coords": [(500000.0, 600000.0), (500010.0, 600000.0)],
                "strahler_order": 1,
                "length_m": 10.0,
                "upstream_area_km2": 0.01,
                "mean_slope_percent": 2.5,
            },
            {
                "coords": [(500010.0, 600000.0), (500010.0, 599990.0)],
                "strahler_order": 2,
                "length_m": 10.0,
                "upstream_area_km2": 0.02,
                "mean_slope_percent": 1.5,
            },
        ]

        assert insert_stream_segments(db, segments, threshold_m2=2000) == 2

        assert loaded_rows(db.cursor, "temp_stream_import") == [
            {
                "wkt": "LINESTRING(500000.0 600000.0, 500010.0 600000.0)",
                "strahler_order": "1",
                "length_m": "10.0",
                "upstream_area_km2": "0.01",
                "mean_slope_percent": "2.5",
                "source": "DEM_DERIVED",
                "threshold_m2": "2000",
                "segment_idx": "1",
            },
            {
                "wkt": "LINESTRING(500010.0 600000.0, 500010.0 599990.0)",
                "strahler_order": "2",
                "length_m": "10.0",
                "upstream_area_km2": "0.02",
                "mean_slope_percent": "1.5",
                "source": "DEM_DERIVED",
                "threshold_m2": "2000",
                "segment_idx": "2",
            },
        ]


class TestInsertCatchments:
    FULL = {
        "wkt": "MULTIPOLYGON(((0 0, 0 1, 1 1, 0 0)))",
        "segment_idx": 7,
        "area_km2": 0.5,
        "mean_elevation_m": 123.4,
        "mean_slope_percent": 2.5,
        "strahler_order": 3,
        "downstream_segment_idx": 8,
        "elevation_min_m": 100.0,
        "elevation_max_m": 150.0,
        "perimeter_km": 4.2,
        "stream_length_km": 1.1,
        "hydraulic_length_km": 2.2,
        "elev_histogram": {"base_m": 100, "interval_m": 1, "counts": [1, 2]},
        "max_flow_dist_m": 9000.0,
        "longest_flow_path_wkt": "LINESTRING(0 0, 1 1)",
        "divide_flow_path_wkt": "LINESTRING(0 0, 2 2)",
        "outlet_flow_dist_m": 250.0,
    }
    MINIMAL = {
        "wkt": "MULTIPOLYGON(((5 5, 5 6, 6 6, 5 5)))",
        "segment_idx": 8,
        "area_km2": 0.1,
        "mean_elevation_m": None,
        "mean_slope_percent": None,
    }

    def test_nothing_to_insert_leaves_the_database_alone(self):
        db = FakeSession()

        assert insert_catchments(db, [], threshold_m2=1000) == 0

        assert db.connections == 0

    def test_each_value_lands_in_its_column_and_missing_values_are_empty(self):
        db = FakeSession(rowcounts={"INSERT INTO stream_catchments": 2})

        insert_catchments(db, [self.FULL, self.MINIMAL], threshold_m2=1000)

        full, minimal = loaded_rows(db.cursor, "temp_catchments_import")
        assert json.loads(full.pop("elev_histogram")) == self.FULL["elev_histogram"]
        sent = {k: str(v) for k, v in self.FULL.items() if k != "elev_histogram"}
        assert full == {**sent, "threshold_m2": "1000"}
        assert minimal.pop("elev_histogram") == ""
        assert minimal == {
            **dict.fromkeys(sent, ""),  # every optional column is NULL
            "wkt": self.MINIMAL["wkt"],
            "segment_idx": "8",
            "area_km2": "0.1",
            "threshold_m2": "1000",
        }

    def test_copy_reads_empty_fields_as_null(self):
        db = FakeSession()

        insert_catchments(db, [self.MINIMAL], threshold_m2=1000)

        (copy_sql,) = [sql for kind, sql in db.cursor.events if kind == "copy"]
        assert copy_sql.startswith("COPY temp_catchments_import FROM STDIN")
        assert "NULL ''" in copy_sql

    def test_staging_table_is_filled_before_it_is_read_and_cleaned_afterwards(self):
        db = FakeSession(rowcounts={"INSERT INTO stream_catchments": 1})
        steps = [
            "DROP TABLE IF EXISTS temp_catchments_import",
            "CREATE TEMP TABLE temp_catchments_import",
            "COPY temp_catchments_import",
            "INSERT INTO stream_catchments",
            "UPDATE stream_catchments",
        ]

        insert_catchments(db, [self.MINIMAL], threshold_m2=1000)

        assert db.cursor.order_of(*steps) == steps

    def test_returns_the_rows_inserted_and_commits_the_work(self):
        db = FakeSession(
            rowcounts={
                "INSERT INTO stream_catchments": 2,
                "UPDATE stream_catchments": 1,
            }
        )

        inserted = insert_catchments(db, [self.FULL, self.MINIMAL], threshold_m2=1000)

        assert inserted == 2  # the clean-up count is not the result
        assert db.commits == 4  # timeout set, insert, clean-up, timeout restored
        assert db.rollbacks == 0

    def test_tiny_detached_parts_are_removed_for_this_threshold_only(self):
        db = FakeSession()

        insert_catchments(db, [self.MINIMAL], threshold_m2=2500)

        ((min_part_area_m2, threshold),) = db.cursor.params_of(
            "UPDATE stream_catchments"
        )
        assert min_part_area_m2 > 0
        assert threshold == 2500  # catchments of other thresholds stay as they are


class TestLoadBdotStreamsFromGpkg:
    @staticmethod
    def _write(path, layer, geometries, crs="EPSG:2180", **columns):
        gdf = gpd.GeoDataFrame(columns, geometry=geometries, crs=crs)
        gdf.to_file(path, layer=layer, driver="GPKG")

    def test_a_missing_file_gives_no_streams(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="core.db_bulk"):
            assert load_bdot_streams_from_gpkg(tmp_path / "gone.gpkg") == []

        assert "BDOT GPKG not found" in caplog.text

    def test_the_three_hydro_line_layers_are_read_with_their_type_and_name(
        self, tmp_path
    ):
        gpkg = tmp_path / "hydro.gpkg"
        river = LineString([(500000, 500000), (500100, 500000)])
        canal = LineString([(500000, 500100), (500000, 500250)])
        ditch = LineString([(500200, 500000), (500200, 500040)])
        self._write(gpkg, "OT_SWRS_L", [river], NAZWA=["Bzura"])
        self._write(gpkg, "OT_SWKN_L", [canal], Name=["Kanał Zerański"])
        self._write(gpkg, "OT_SWRM_L", [ditch], id=[1])  # no name column at all
        # A layer outside the three line layers is ignored.
        self._write(
            gpkg, "OT_PTWP_A", [Polygon([(0, 0), (0, 5), (5, 5)])], NAZWA=["Jezioro"]
        )

        streams = load_bdot_streams_from_gpkg(gpkg)

        assert streams == [
            {
                "geom_wkt": "LINESTRING (500000 500000, 500100 500000)",
                "layer_type": "SWRS",
                "name": "Bzura",
                "length_m": 100.0,
            },
            {
                "geom_wkt": "LINESTRING (500000 500100, 500000 500250)",
                "layer_type": "SWKN",
                "name": "Kanał Zerański",
                "length_m": 150.0,
            },
            {
                "geom_wkt": "LINESTRING (500200 500000, 500200 500040)",
                "layer_type": "SWRM",
                "name": None,
                "length_m": 40.0,
            },
        ]

    def test_multipart_lines_become_single_lines_and_slivers_are_dropped(
        self, tmp_path
    ):
        gpkg = tmp_path / "hydro.gpkg"
        multi = MultiLineString(
            [
                [(500000, 500000), (500060, 500000)],
                [(500100, 500000), (500100.5, 500000)],  # 0.5 m long
                [(500200, 500000), (500200, 500025.26)],
            ]
        )
        self._write(gpkg, "OT_SWRS_L", [multi], NAZWA=["Rawka"])

        streams = load_bdot_streams_from_gpkg(gpkg)

        assert [s["length_m"] for s in streams] == [60.0, 25.3]
        assert {s["name"] for s in streams} == {"Rawka"}
        assert all(s["geom_wkt"].startswith("LINESTRING") for s in streams)

    def test_layers_in_other_crs_are_reprojected_to_epsg2180(self, tmp_path):
        gpkg = tmp_path / "hydro.gpkg"
        # 0.001 degree of longitude at 52 N is about 68 m.
        line = LineString([(21.000, 52.000), (21.001, 52.000)])
        self._write(gpkg, "OT_SWRS_L", [line], crs="EPSG:4326", NAZWA=["Wilanówka"])

        (stream,) = load_bdot_streams_from_gpkg(gpkg)

        x, y = shapely_wkt.loads(stream["geom_wkt"]).coords[0]
        assert 400_000 < x < 700_000  # metres of the Polish national grid
        assert 400_000 < y < 700_000
        assert 65.0 < stream["length_m"] < 72.0


class TestInsertBdotStreams:
    def test_without_a_known_layer_type_nothing_is_loaded(self):
        db = FakeSession()

        assert insert_bdot_streams(db, [{"layer_type": "SWXX", "geom_wkt": "L"}]) == 0
        assert insert_bdot_streams(db, []) == 0

        assert db.connections == 0

    def test_existing_rows_are_replaced_by_the_valid_streams(self):
        db = FakeSession(rowcounts={"INSERT INTO bdot_streams": 2})
        streams = [
            {"geom_wkt": "LINESTRING(0 0, 1 1)", "layer_type": "SWRS", "name": "A"},
            {"geom_wkt": "LINESTRING(5 5, 6 6)", "layer_type": "SWXX", "name": "B"},
            {
                "geom_wkt": "LINESTRING(2 2, 3 3)",
                "layer_type": "SWKN",
                "name": None,
                "length_m": 12.5,
            },
        ]

        inserted = insert_bdot_streams(db, streams)

        assert inserted == 2
        assert loaded_rows(db.cursor, "temp_bdot_import") == [
            # a missing length is 0
            {
                "wkt": "LINESTRING(0 0, 1 1)",
                "layer_type": "SWRS",
                "name": "A",
                "length_m": "0",
            },
            # a missing name is empty, which the INSERT turns into NULL
            {
                "wkt": "LINESTRING(2 2, 3 3)",
                "layer_type": "SWKN",
                "name": "",
                "length_m": "12.5",
            },
        ]
        assert db.cursor.statements()[0] == "DELETE FROM bdot_streams"
        assert db.commits == 1

    def test_tabs_and_line_breaks_in_a_name_cannot_split_a_row(self):
        db = FakeSession()
        stream = {
            "geom_wkt": "LINESTRING(0 0, 1 1)",
            "layer_type": "SWRS",
            "name": "Rzeka\tGłówna\nlewa",
            "length_m": 3.0,
        }

        insert_bdot_streams(db, [stream])

        (row,) = loaded_rows(db.cursor, "temp_bdot_import")
        assert row["name"] == "Rzeka Główna lewa"
        assert row["length_m"] == "3.0"

    def test_a_failure_rolls_back_and_is_raised(self):
        db = FakeSession(fail_on="INSERT INTO bdot_streams")
        stream = {"geom_wkt": "LINESTRING(0 0, 1 1)", "layer_type": "SWRS"}

        with pytest.raises(RuntimeError, match="database refused"):
            insert_bdot_streams(db, [stream])

        assert db.rollbacks == 1
        assert db.commits == 0


class TestUpdateStreamRealFlags:
    def test_without_bdot_streams_every_segment_is_overland(self, caplog):
        db = FakeSession(
            fetches={
                "SELECT COUNT(*) FROM bdot_streams": (0,),
                "SELECT COUNT(*) FROM stream_network": (12,),
            }
        )

        with caplog.at_level(logging.WARNING, logger="core.db_bulk"):
            result = update_stream_real_flags(db, threshold_m2=1000)

        assert result == {"total": 12, "real": 0, "overland": 12}
        assert "No BDOT streams" in caplog.text
        marked = "UPDATE stream_network SET is_real_stream = false"
        assert db.cursor.params_of(marked) == [(1000,)]
        assert not db.cursor.ran("CREATE TEMP TABLE temp_bdot_buffer")

    def test_matching_buffers_the_bdot_streams_and_reports_the_counts(self):
        db = FakeSession(
            fetches={
                "SELECT COUNT(*) FROM bdot_streams": (40,),
                "SELECT COUNT(*) AS total": (10, 7, 3),
            }
        )

        result = update_stream_real_flags(
            db, threshold_m2=2000, buffer_m=30.0, overlap_threshold=0.6
        )

        assert result == {"total": 10, "real": 7, "overland": 3}
        buffering = "CREATE TEMP TABLE temp_bdot_buffer"
        joining = "UPDATE stream_network sn"
        assert db.cursor.order_of(buffering, joining) == [buffering, joining]
        assert db.cursor.params_of(buffering) == [(30.0,)]
        assert db.cursor.params_of(joining) == [(0.6, 2000, 2000)]
        assert db.commits == 3  # timeout set, flags written, timeout restored

    def test_a_prepared_buffer_table_is_used_as_it_is(self):
        db = FakeSession(fetches={"SELECT COUNT(*) AS total": (4, 1, 3)})

        result = update_stream_real_flags(db, 500, _bdot_buffer_ready=True)

        assert result == {"total": 4, "real": 1, "overland": 3}
        assert not db.cursor.ran("SELECT COUNT(*) FROM bdot_streams")
        assert not db.cursor.ran("CREATE TEMP TABLE temp_bdot_buffer")
        assert not db.cursor.ran("DROP TABLE")

    def test_a_failure_rolls_back_and_is_raised(self):
        db = FakeSession(
            fetches={"SELECT COUNT(*) FROM bdot_streams": (40,)},
            fail_on="UPDATE stream_network sn",
        )

        with pytest.raises(RuntimeError, match="database refused"):
            update_stream_real_flags(db, threshold_m2=1000)

        assert db.rollbacks == 1


class TestUpdateStreamRealFlagsAll:
    def test_without_bdot_streams_every_threshold_is_marked_overland(self):
        db = FakeSession(
            fetches={
                "SELECT COUNT(*) FROM bdot_streams": (0,),
                "SELECT COUNT(*) FROM stream_network": (6,),
            }
        )

        result = update_stream_real_flags_all(db, [500, 1000])

        assert result == {
            500: {"total": 6, "real": 0, "overland": 6},
            1000: {"total": 6, "real": 0, "overland": 6},
        }
        marked = "UPDATE stream_network SET is_real_stream = false"
        assert db.cursor.params_of(marked) == [(500,), (1000,)]
        assert not db.cursor.ran("CREATE TEMP TABLE temp_bdot_buffer")

    def test_one_buffer_table_serves_all_thresholds(self):
        db = FakeSession(
            fetches={
                "SELECT COUNT(*) FROM bdot_streams": (40,),
                "SELECT COUNT(*) AS total": (10, 7, 3),
            }
        )

        result = update_stream_real_flags_all(db, [500, 1000, 5000], buffer_m=20.0)

        assert result == {
            500: {"total": 10, "real": 7, "overland": 3},
            1000: {"total": 10, "real": 7, "overland": 3},
            5000: {"total": 10, "real": 7, "overland": 3},
        }
        assert db.cursor.params_of("CREATE TEMP TABLE temp_bdot_buffer") == [(20.0,)]
        joins = db.cursor.params_of("UPDATE stream_network sn")
        assert [threshold for _, threshold, _ in joins] == [500, 1000, 5000]
