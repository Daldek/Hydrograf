"""
Unit tests of core.land_cover: the CN of the soil-cover complexes of a watershed
(ADR-075) and the hierarchy of determine_cn.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from shapely.geometry import Polygon, box

from core.land_cover import (
    VALID_CATEGORIES,
    determine_cn,
    get_land_cover_for_boundary,
    summarize_complexes,
)

HA = 10_000.0  # m2


def _row(category, area_ha, hsg=None, bdot_class=None, imperviousness=0.0):
    """A row of the land cover query: hsg None is the whole land cover."""
    return SimpleNamespace(
        category=category,
        bdot_class=bdot_class,
        imperviousness=imperviousness,
        hsg_group=hsg,
        area_m2=area_ha * HA,
    )


class TestValidCategories:
    """The categories of the constraint of land_cover."""

    def test_expected_categories_present(self):
        expected = {
            "las",
            "łąka",
            "grunt_orny",
            "zabudowa_mieszkaniowa",
            "zabudowa_przemysłowa",
            "droga",
            "woda",
            "inny",
        }
        assert expected == VALID_CATEGORIES


class TestSummarizeComplexes:
    """The weighted CN of the complexes, land cover x soil group."""

    def test_cn_of_known_complexes(self):
        """Forest 60 ha (40 on A, 20 on B) and arable land 40 ha on B.

        TR-55: woods, good A 30, B 55; small grain, good, B 75.
        CN = (40*30 + 20*55 + 40*75) / 100 = 53.0
        """
        rows = [
            _row("las", 60),
            _row("las", 40, "A"),
            _row("las", 20, "B"),
            _row("grunt_orny", 40),
            _row("grunt_orny", 40, "B"),
        ]

        result = summarize_complexes(rows)

        assert result["weighted_cn"] == 53.0
        assert result["hsg_assumed_pct"] == 0.0
        assert result["total_area_m2"] == 100 * HA
        assert result["categories"] == [
            {
                "category": "las",
                "area_m2": 60 * HA,
                "percentage": 60.0,
                "cn_value": 38.3,
            },
            {
                "category": "grunt_orny",
                "area_m2": 40 * HA,
                "percentage": 40.0,
                "cn_value": 75.0,
            },
        ]

    def test_land_cover_without_soil_takes_the_soil_shares_of_the_rest(self):
        """Arable land of 50 ha has 20 ha outside soil_hsg.

        The rest lies on A (forest 50 ha) and B (arable 30 ha): shares 0.625 and
        0.375, so the 20 ha are 12.5 ha on A (CN 63) and 7.5 ha on B (CN 75).
        CN = (50*30 + 30*75 + 12.5*63 + 7.5*75) / 100 = 51.0
        """
        rows = [
            _row("las", 50),
            _row("las", 50, "A"),
            _row("grunt_orny", 50),
            _row("grunt_orny", 30, "B"),
        ]

        result = summarize_complexes(rows)

        assert result["weighted_cn"] == 51.0
        assert result["hsg_assumed_pct"] == 20.0
        arable = next(c for c in result["categories"] if c["category"] == "grunt_orny")
        # (30*75 + 12.5*63 + 7.5*75) / 50
        assert arable["cn_value"] == 72.0

    def test_watershed_without_soil_groups_takes_group_b(self):
        rows = [_row("las", 70), _row("droga", 30)]

        result = summarize_complexes(rows)

        # (70*55 + 30*98) / 100
        assert result["weighted_cn"] == pytest.approx(67.9)
        assert result["hsg_assumed_pct"] == 100.0

    def test_source_of_a_row_selects_its_cover(self):
        """Commercial pieces of zabudowa_przemysłowa are TR-55 commercial (B 92)."""
        rows = [
            _row("zabudowa_przemysłowa", 10, bdot_class="KUPG:zakład prod."),
            _row("zabudowa_przemysłowa", 10, "B", bdot_class="KUPG:zakład prod."),
            _row("zabudowa_przemysłowa", 10, bdot_class="PTZB:handl.-usług."),
            _row("zabudowa_przemysłowa", 10, "B", bdot_class="PTZB:handl.-usług."),
        ]

        result = summarize_complexes(rows)

        assert result["categories"] == [
            {
                "category": "zabudowa_przemysłowa",
                "area_m2": 20 * HA,
                "percentage": 100.0,
                "cn_value": 90.0,
            }
        ]

    def test_overlapping_soil_pieces_do_not_exceed_the_land_cover(self):
        """Pieces summing to more than the land cover are scaled to it."""
        rows = [_row("las", 10), _row("las", 10, "A"), _row("las", 10, "D")]

        result = summarize_complexes(rows)

        assert result["total_area_m2"] == 10 * HA
        assert result["hsg_assumed_pct"] == 0.0
        assert result["weighted_cn"] == pytest.approx((30 + 77) / 2, abs=0.05)

    def test_weighted_imperviousness_and_lutz_shares(self):
        areas_ha = {
            "las": 100,
            "grunt_orny": 89,
            "zabudowa_mieszkaniowa": 20,
            "zabudowa_przemysłowa": 5,
            "droga": 12,
            "inny": 40,
            "woda": 20,
            "łąka": 14,
        }
        rows = [
            _row(category, area, imperviousness=0.95 if category == "droga" else None)
            for category, area in areas_ha.items()
        ]

        result = summarize_complexes(rows)

        # Of 300 ha: forest 100 (33.33%), built-up 25 and roads 12 (12.33%)
        assert (result["forest_pct"], result["urban_pct"]) == (33.3, 12.3)
        assert result["weighted_imperviousness"] == pytest.approx(
            12 * 0.95 / 300, abs=1e-3
        )

    @pytest.mark.parametrize(
        "rows", [[], [_row("las", 0)], [_row("las", 0), _row("las", 5, "B")]]
    )
    def test_no_land_cover_area_is_none(self, rows):
        assert summarize_complexes(rows) is None


class TestGetLandCoverForBoundary:
    """The query of the land cover and its soil pieces."""

    @pytest.fixture
    def sample_boundary(self):
        return box(500000, 600000, 501000, 601000)

    def test_returns_the_summary_of_the_rows(self, sample_boundary):
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = [
            _row("las", 100),
            _row("las", 100, "B"),
        ]

        result = get_land_cover_for_boundary(sample_boundary, db)

        assert result["weighted_cn"] == 55.0
        assert db.execute.call_args.args[1] == {"boundary_wkb": sample_boundary.wkb_hex}

    def test_returns_none_when_no_data(self, sample_boundary):
        db = MagicMock()
        db.execute.return_value.fetchall.return_value = []

        assert get_land_cover_for_boundary(sample_boundary, db) is None

    def test_returns_none_for_invalid_boundary(self):
        db = MagicMock()
        invalid_boundary = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])

        assert get_land_cover_for_boundary(invalid_boundary, db) is None
        db.execute.assert_not_called()

    def test_returns_none_on_database_error(self, sample_boundary):
        db = MagicMock()
        db.execute.side_effect = Exception("Connection failed")

        assert get_land_cover_for_boundary(sample_boundary, db) is None


class TestDetermineCN:
    """The hierarchy of the sources of the CN."""

    @pytest.fixture
    def sample_boundary(self):
        return box(500000, 600000, 501000, 601000)

    @pytest.fixture
    def mock_db(self):
        return MagicMock()

    def test_config_cn_has_highest_priority(self, sample_boundary, mock_db):
        cn, source, details = determine_cn(
            boundary=sample_boundary, db=mock_db, config_cn=80
        )

        assert (cn, source, details) == (80, "config", None)
        mock_db.execute.assert_not_called()

    def test_config_cn_zero_is_valid(self, sample_boundary, mock_db):
        cn, source, _ = determine_cn(boundary=sample_boundary, db=mock_db, config_cn=0)

        assert (cn, source) == (0, "config")

    def test_uses_the_complexes_of_the_database(self, sample_boundary, mock_db):
        mock_db.execute.return_value.fetchall.return_value = [
            _row("las", 100),
            _row("las", 60, "A"),
            _row("las", 40, "B"),
        ]

        cn, source, details = determine_cn(
            boundary=sample_boundary, db=mock_db, use_kartograf=False
        )

        assert (cn, source) == (40.0, "database_land_cover")  # 0.6*30 + 0.4*55
        assert details == {"stats": {"las": 100.0}, "hsg_assumed_pct": 0.0}

    @pytest.mark.parametrize("default_cn", [75, 80])
    def test_returns_default_when_no_data(self, sample_boundary, mock_db, default_cn):
        mock_db.execute.return_value.fetchall.return_value = []

        result = determine_cn(
            boundary=sample_boundary,
            db=mock_db,
            use_kartograf=False,
            default_cn=default_cn,
        )

        assert result == (default_cn, "default", None)

    def test_database_error_gives_the_default(self, sample_boundary, mock_db):
        mock_db.execute.side_effect = Exception("Connection failed")

        cn, source, _ = determine_cn(
            boundary=sample_boundary, db=mock_db, use_kartograf=False, default_cn=75
        )

        assert (cn, source) == (75, "default")

    @patch("core.cn_calculator.calculate_cn_from_kartograf")
    def test_uses_kartograf_when_db_empty(
        self, mock_kartograf, sample_boundary, mock_db, tmp_path
    ):
        from core.cn_calculator import CNCalculationResult

        mock_db.execute.return_value.fetchall.return_value = []
        mock_kartograf.return_value = CNCalculationResult(
            cn=72,
            method="kartograf_hsg",
            dominant_hsg="B",
            hsg_stats={"B": 100.0},
            land_cover_stats={"las": 100.0},
            cn_details=[{"land_cover": "las", "percentage": 100.0, "cn": 55.0}],
        )

        cn, source, details = determine_cn(
            boundary=sample_boundary,
            db=mock_db,
            use_kartograf=True,
            boundary_wgs84=[[17.31, 52.45], [17.32, 52.46]],
            cache_dir=tmp_path,
        )

        assert (cn, source) == (72, "kartograf_hsg")
        assert details["dominant_hsg"] == "B"

    @pytest.mark.parametrize(
        ("use_kartograf", "boundary_wgs84"),
        [(False, [[17.31, 52.45], [17.32, 52.46]]), (True, None)],
    )
    @patch("core.cn_calculator.calculate_cn_from_kartograf")
    def test_kartograf_skipped_when_disabled_or_without_boundary(
        self,
        mock_kartograf,
        sample_boundary,
        mock_db,
        tmp_path,
        use_kartograf,
        boundary_wgs84,
    ):
        mock_db.execute.return_value.fetchall.return_value = []

        _, source, _ = determine_cn(
            boundary=sample_boundary,
            db=mock_db,
            use_kartograf=use_kartograf,
            boundary_wgs84=boundary_wgs84,
            cache_dir=tmp_path,
        )

        assert source == "default"
        mock_kartograf.assert_not_called()
