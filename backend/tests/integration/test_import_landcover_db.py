"""The land cover import against a database (marker ``db``): the rows it replaces.

Every test works inside the session of ``db_session``, which rolls back, at about
(10 000, 10 000) in EPSG:2180: west and south of Poland, where no real data lies.
"""

import pytest
import shapely
from shapely.geometry import box
from sqlalchemy import text

from scripts.import_landcover import replace_land_cover
from tests.conftest_db import requires_db

# Register DB fixtures from conftest_db
pytest_plugins = ["tests.conftest_db"]

X0, Y0 = 10_000.0, 10_000.0


def _record(geom, category, bdot_class):
    return {
        "geom_wkb": shapely.to_wkb(shapely.MultiPolygon([geom])),
        "category": category,
        "imperviousness": 0.3,
        "bdot_class": bdot_class,
    }


def _rows(db):
    return [
        (row.category, row.bdot_class, round(row.area_m2, 6))
        for row in db.execute(
            text(
                "SELECT category, bdot_class, ST_Area(geom) AS area_m2 "
                "FROM land_cover "
                "WHERE geom && ST_MakeEnvelope(:x0, :y0, :x1, :y1, 2180) "
                "ORDER BY bdot_class"
            ),
            {"x0": X0 - 500, "y0": Y0 - 500, "x1": X0 + 500, "y1": Y0 + 500},
        )
    ]


@requires_db
@pytest.mark.db
class TestReplaceLandCover:
    def test_import_again_replaces_the_rows_of_its_area(self, db_session):
        """A package replaces its earlier rows, never those of the next county."""
        conn = db_session.connection()
        conn.execute(
            text(
                "INSERT INTO land_cover "
                "(geom, category, imperviousness, bdot_class) VALUES "
                "(ST_Multi(ST_MakeEnvelope(:x0, :y0, :x1, :y1, 2180)), "
                "'woda', 1.0, 'PTWP')"
            ),
            {"x0": X0 - 100, "y0": Y0, "x1": X0, "y1": Y0 + 100},
        )
        earlier = [
            _record(box(X0, Y0, X0 + 200, Y0 + 100), "zabudowa_mieszkaniowa", "PTZB")
        ]
        package = [
            _record(
                box(X0, Y0, X0 + 120, Y0 + 100),
                "zabudowa_mieszkaniowa",
                "PTZB:jednorodzinna",
            ),
            _record(
                box(X0 + 120, Y0, X0 + 200, Y0 + 100),
                "zabudowa_przemysłowa",
                "KUPG:zakład prod.",
            ),
        ]

        assert replace_land_cover(conn, earlier) == (1, 0)
        assert replace_land_cover(conn, package) == (2, 1)
        assert replace_land_cover(conn, package) == (2, 2)
        assert _rows(db_session) == [
            ("zabudowa_przemysłowa", "KUPG:zakład prod.", 8_000.0),
            ("woda", "PTWP", 10_000.0),
            ("zabudowa_mieszkaniowa", "PTZB:jednorodzinna", 12_000.0),
        ]

    def test_neighbour_overlapping_the_package_stays(self, db_session):
        """A row of the next county that overlaps the package by a strip stays.

        Its interior point lies in the overlap (the middle of its widest horizontal
        section), but most of its area lies outside the package.
        """
        neighbour = shapely.union_all(
            [
                box(X0 - 10, Y0 - 500, X0, Y0 + 600),
                box(X0, Y0 + 45, X0 + 90, Y0 + 55),
            ]
        )
        conn = db_session.connection()
        replace_land_cover(conn, [_record(neighbour, "łąka", "PTTR:trawiasta")])
        package = [_record(box(X0, Y0, X0 + 100, Y0 + 100), "las", "PTLZ")]

        assert replace_land_cover(conn, package) == (1, 0)
        assert _rows(db_session) == [
            ("las", "PTLZ", 10_000.0),
            ("łąka", "PTTR:trawiasta", 11_900.0),
        ]
