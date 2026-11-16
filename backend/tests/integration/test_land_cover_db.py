"""The CN of the soil-cover complexes of a watershed in PostGIS (marker ``db``).

Every test adds its own rows inside the session of ``db_session``, which rolls back,
at about (10 000, 10 000) in EPSG:2180: west and south of Poland, where no real data
lies.
"""

import pytest
from shapely.geometry import box
from sqlalchemy import text

from core.land_cover import get_land_cover_for_boundary
from tests.conftest_db import requires_db

pytest_plugins = ["tests.conftest_db"]

X0, Y0 = 10_000.0, 10_000.0


def _land_cover(db, category, bdot_class, geometry):
    db.execute(
        text(
            "INSERT INTO land_cover (geom, category, imperviousness, bdot_class) "
            "VALUES (ST_Multi(ST_GeomFromText(:wkt, 2180)), :category, 0.0, "
            ":bdot_class)"
        ),
        {"wkt": geometry.wkt, "category": category, "bdot_class": bdot_class},
    )


def _soil(db, group, geometry):
    db.execute(
        text(
            "INSERT INTO soil_hsg (geom, hsg_group, area_m2) "
            "VALUES (ST_Multi(ST_GeomFromText(:wkt, 2180)), :group, :area)"
        ),
        {"wkt": geometry.wkt, "group": group, "area": geometry.area},
    )


@requires_db
@pytest.mark.db
class TestComplexesOfAWatershed:
    def test_cn_of_the_pieces_with_a_part_outside_the_soil_groups(self, db_session):
        """Forest and arable land of 1 ha each; soil A in the west 0.6 ha, B 0.9 ha.

        Pieces [m²]: forest 6000 on A and 4000 on B, arable land 5000 on B and 5000
        without a soil group, which takes the shares of the rest: A 0.4, B 0.6.
        CN = (6000*30 + 4000*55 + 5000*75 + 2000*63 + 3000*75) / 20000 = 56.3
        """
        _land_cover(db_session, "las", "PTLZ", box(X0, Y0, X0 + 100, Y0 + 100))
        _land_cover(
            db_session,
            "grunt_orny",
            "PTTR:grunty orne",
            box(X0 + 100, Y0, X0 + 200, Y0 + 100),
        )
        _soil(db_session, "A", box(X0, Y0, X0 + 60, Y0 + 100))
        _soil(db_session, "B", box(X0 + 60, Y0, X0 + 150, Y0 + 100))

        result = get_land_cover_for_boundary(
            box(X0, Y0, X0 + 200, Y0 + 100), db_session
        )

        assert result["weighted_cn"] == 56.3
        assert result["hsg_assumed_pct"] == 25.0
        assert result["total_area_m2"] == pytest.approx(20_000.0)
        # Equal areas: the categories in alphabetical order
        assert [(c["category"], c["cn_value"]) for c in result["categories"]] == [
            ("grunt_orny", 72.6),
            ("las", 40.0),
        ]

    def test_only_the_part_inside_the_boundary_counts(self, db_session):
        """The boundary takes the east half of the forest: 2000 m² on A, 4000 on B."""
        _land_cover(db_session, "las", "PTLZ", box(X0, Y0, X0 + 100, Y0 + 100))
        _soil(db_session, "A", box(X0, Y0, X0 + 60, Y0 + 100))
        _soil(db_session, "B", box(X0 + 60, Y0, X0 + 150, Y0 + 100))

        result = get_land_cover_for_boundary(
            box(X0 + 40, Y0, X0 + 100, Y0 + 100), db_session
        )

        # (2000*30 + 4000*55) / 6000
        assert result["weighted_cn"] == pytest.approx(46.7)
        assert result["total_area_m2"] == pytest.approx(6_000.0)
        assert result["hsg_assumed_pct"] == 0.0

    def test_a_watershed_without_soil_groups_takes_group_b(self, db_session):
        _land_cover(
            db_session,
            "zabudowa_przemysłowa",
            "PTZB:handl.-usług.",
            box(X0, Y0, X0 + 100, Y0 + 100),
        )

        result = get_land_cover_for_boundary(
            box(X0, Y0, X0 + 100, Y0 + 100), db_session
        )

        assert result["weighted_cn"] == 92.0  # commercial and business, B
        assert result["hsg_assumed_pct"] == 100.0

    def test_no_land_cover_is_none(self, db_session):
        _soil(db_session, "A", box(X0, Y0, X0 + 60, Y0 + 100))

        assert (
            get_land_cover_for_boundary(box(X0, Y0, X0 + 60, Y0 + 100), db_session)
            is None
        )
