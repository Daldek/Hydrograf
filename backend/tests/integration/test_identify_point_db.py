"""PostGIS queries of core.point_info against a database (marker ``db``).

Every test adds its own rows inside the session of ``db_session``, which rolls
back, at about (10 000, 10 000) in EPSG:2180: west and south of Poland, where no
real data lies.
"""

import pytest
from sqlalchemy import text

from core.point_info import (
    depression_at,
    land_cover_at,
    nearest_stream,
    soil_group_at,
    subcatchment_at,
)
from tests.conftest_db import requires_db

# Register DB fixtures from conftest_db
pytest_plugins = ["tests.conftest_db"]

X0, Y0 = 10_000.0, 10_000.0


def _square(x, y, size, multi=True):
    ring = (
        f"(({x} {y}, {x + size} {y}, {x + size} {y + size}, {x} {y + size}, {x} {y}))"
    )
    return f"MULTIPOLYGON({ring})" if multi else f"POLYGON{ring}"


def _insert(db, sql, **params):
    db.execute(text(sql), params)


@requires_db
@pytest.mark.db
class TestPointQueries:
    def test_land_cover_of_the_smallest_polygon(self, db_session):
        for wkt, category, cn, bdot in [
            (_square(X0, Y0, 100), "grunt_orny", 78, "PTTR"),
            (_square(X0 + 40, Y0 + 40, 20), "woda", 100, "PTWP"),
        ]:
            _insert(
                db_session,
                "INSERT INTO land_cover (geom, category, cn_value, imperviousness, "
                "bdot_class) VALUES (ST_GeomFromText(:wkt, 2180), :category, :cn, "
                "0.1, :bdot)",
                wkt=wkt,
                category=category,
                cn=cn,
                bdot=bdot,
            )

        # Water surfaces CN 98 (NEH 630, chapter 9), the same on every soil group
        assert land_cover_at(db_session, X0 + 50, Y0 + 50, None) == {
            "category": "woda",
            "cn": 98,
            "cn_amc_i": 96,
            "cn_amc_iii": 99,
            "imperviousness": 0.1,
            "bdot_class": "PTWP",
        }
        arable = land_cover_at(db_session, X0 + 10, Y0 + 10, "C")
        assert (arable["category"], arable["cn"]) == ("grunt_orny", 83)
        assert land_cover_at(db_session, X0 + 500, Y0 + 500, "B") is None

    def test_soil_group(self, db_session):
        _insert(
            db_session,
            "INSERT INTO soil_hsg (geom, hsg_group, area_m2) "
            "VALUES (ST_GeomFromText(:wkt, 2180), 'C', 10000)",
            wkt=_square(X0, Y0, 100),
        )

        assert soil_group_at(db_session, X0 + 50, Y0 + 50) == "C"
        assert soil_group_at(db_session, X0 + 150, Y0 + 50) is None

    def test_depression_of_the_smallest_polygon(self, db_session):
        for wkt, depth, area in [
            (_square(X0, Y0, 100, multi=False), 2.0, 10000.0),
            (_square(X0 + 45, Y0 + 45, 10, multi=False), 0.5, 100.0),
        ]:
            _insert(
                db_session,
                "INSERT INTO depressions (geom, volume_m3, area_m2, max_depth_m, "
                "mean_depth_m) VALUES (ST_GeomFromText(:wkt, 2180), :volume, :area, "
                ":depth, :mean)",
                wkt=wkt,
                volume=area * depth / 3,
                area=area,
                depth=depth,
                mean=depth / 3,
            )

        assert depression_at(db_session, X0 + 50, Y0 + 50) == pytest.approx(
            {
                "max_depth_m": 0.5,
                "mean_depth_m": 0.5 / 3,
                "area_m2": 100.0,
                "volume_m3": 100.0 * 0.5 / 3,
            }
        )
        assert depression_at(db_session, X0 + 5, Y0 + 5)["max_depth_m"] == 2.0
        assert depression_at(db_session, X0 - 5, Y0 - 5) is None

    def test_nearest_stream_at_any_distance_up_to_the_limit(self, db_session):
        for wkt, layer, name in [
            (f"LINESTRING({X0 - 50} {Y0 + 10}, {X0 + 50} {Y0 + 10})", "SWRS", "Potok"),
            (f"LINESTRING({X0 - 50} {Y0 - 20}, {X0 + 50} {Y0 - 20})", "SWRM", None),
        ]:
            _insert(
                db_session,
                "INSERT INTO bdot_streams (geom, layer_type, name, length_m) "
                "VALUES (ST_GeomFromText(:wkt, 2180), :layer, :name, 100)",
                wkt=wkt,
                layer=layer,
                name=name,
            )

        assert nearest_stream(db_session, X0, Y0) == {
            "name": "Potok",
            "layer_type": "SWRS",
            "distance_m": pytest.approx(10.0),
        }
        assert nearest_stream(db_session, X0, Y0 - 15) == {
            "name": None,
            "layer_type": "SWRM",
            "distance_m": pytest.approx(5.0),
        }
        # Far from both lines: still the nearer one, 2 km away
        assert nearest_stream(db_session, X0, Y0 + 2010)["distance_m"] == (
            pytest.approx(2000.0)
        )
        # Beyond STREAM_SEARCH_MAX_DISTANCE_M (5 km)
        assert nearest_stream(db_session, X0, Y0 + 5110) is None

    def test_subcatchment_of_the_requested_threshold(self, db_session):
        for threshold, segment, area, strahler in [
            (10000, 9901, 0.01, 2),
            (100000, 9902, 0.04, 1),
        ]:
            _insert(
                db_session,
                "INSERT INTO stream_catchments (geom, segment_idx, threshold_m2, "
                "area_km2, strahler_order) VALUES (ST_GeomFromText(:wkt, 2180), "
                ":segment, :threshold, :area, :strahler)",
                wkt=_square(X0, Y0, 100 if threshold == 10000 else 200),
                segment=segment,
                threshold=threshold,
                area=area,
                strahler=strahler,
            )
        # Only the segment of the finer network has a stream_network row
        _insert(
            db_session,
            "INSERT INTO stream_network (geom, length_m, strahler_order, source, "
            "upstream_area_km2, threshold_m2, segment_idx, is_real_stream) VALUES "
            "(ST_GeomFromText(:wkt, 2180), 100, 3, 'DEM_DERIVED', 1.5, 10000, 9901, "
            "true)",
            wkt=f"LINESTRING({X0} {Y0 + 50}, {X0 + 100} {Y0 + 50})",
        )

        assert subcatchment_at(db_session, X0 + 50, Y0 + 50, 10000) == {
            "segment_idx": 9901,
            "area_km2": 0.01,
            "upstream_area_km2": 1.5,
            "strahler_order": 3,
            "segment_length_m": pytest.approx(100.0),
            "is_real_stream": True,
        }
        assert subcatchment_at(db_session, X0 + 50, Y0 + 50, 100000) == {
            "segment_idx": 9902,
            "area_km2": 0.04,
            "upstream_area_km2": None,
            "strahler_order": 1,
            "segment_length_m": None,
            "is_real_stream": None,
        }
        assert subcatchment_at(db_session, X0 + 150, Y0 + 50, 10000) is None
