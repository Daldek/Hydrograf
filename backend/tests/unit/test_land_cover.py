"""
Unit tests for land cover module.

Tests for CN (Curve Number) calculation from land cover data.
"""

from unittest.mock import MagicMock, patch

import pytest
from shapely.geometry import Polygon, box

from core.land_cover import (
    DEFAULT_CN,
    VALID_CATEGORIES,
    calculate_weighted_cn,
    determine_cn,
    get_land_cover_for_boundary,
)


class TestDefaultCN:
    """Tests for DEFAULT_CN constant."""

    def test_default_cn_value(self):
        """Test default CN is 75 (average condition)."""
        assert DEFAULT_CN == 75

    def test_default_cn_in_valid_range(self):
        """Test default CN is in valid SCS-CN range."""
        assert 0 <= DEFAULT_CN <= 100


class TestValidCategories:
    """Tests for VALID_CATEGORIES constant."""

    def test_expected_categories_present(self):
        """Test all expected categories are defined."""
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

    def test_categories_is_frozenset(self):
        """Test categories is immutable."""
        assert isinstance(VALID_CATEGORIES, frozenset)


class TestCalculateWeightedCN:
    """Tests for calculate_weighted_cn function."""

    @pytest.fixture
    def sample_boundary(self):
        """Create a sample boundary polygon in EPSG:2180."""
        return box(500000, 600000, 501000, 601000)

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return MagicMock()

    def test_returns_default_when_no_land_cover(self, sample_boundary, mock_db):
        """Test that default CN is returned when no land cover data."""
        mock_db.execute.return_value.fetchall.return_value = []

        cn, stats = calculate_weighted_cn(sample_boundary, mock_db)

        assert cn == DEFAULT_CN
        assert stats == {}

    def test_calculates_weighted_cn_correctly(self, sample_boundary, mock_db):
        """Test weighted CN calculation with multiple categories."""
        # Mock: 60% forest (CN=60), 40% arable (CN=78)
        mock_results = [
            MagicMock(category="las", cn_value=60, total_area_m2=600000),
            MagicMock(category="grunt_orny", cn_value=78, total_area_m2=400000),
        ]
        mock_db.execute.return_value.fetchall.return_value = mock_results

        cn, stats = calculate_weighted_cn(sample_boundary, mock_db)

        # Expected: (60*0.6 + 78*0.4) = 36 + 31.2 = 67.2 -> 67
        assert cn == 67
        assert stats["las"] == pytest.approx(60.0, abs=0.1)
        assert stats["grunt_orny"] == pytest.approx(40.0, abs=0.1)

    def test_single_category_returns_exact_cn(self, sample_boundary, mock_db):
        """Test with single land cover category."""
        mock_results = [
            MagicMock(category="droga", cn_value=98, total_area_m2=100000),
        ]
        mock_db.execute.return_value.fetchall.return_value = mock_results

        cn, stats = calculate_weighted_cn(sample_boundary, mock_db)

        assert cn == 98
        assert stats["droga"] == 100.0

    def test_handles_all_categories(self, sample_boundary, mock_db):
        """Test with all valid categories."""
        categories_with_cn = [
            ("las", 60),
            ("łąka", 70),
            ("grunt_orny", 78),
            ("zabudowa_mieszkaniowa", 85),
            ("zabudowa_przemysłowa", 92),
            ("droga", 98),
            ("woda", 100),
            ("inny", 75),
        ]

        mock_results = [
            MagicMock(category=cat, cn_value=cn, total_area_m2=125000)
            for cat, cn in categories_with_cn
        ]
        mock_db.execute.return_value.fetchall.return_value = mock_results

        cn, stats = calculate_weighted_cn(sample_boundary, mock_db)

        # Average of all CN values: (60+70+78+85+92+98+100+75)/8 = 82.25 -> 82
        expected_cn = round(
            sum(c[1] for c in categories_with_cn) / len(categories_with_cn)
        )
        assert cn == expected_cn
        assert len(stats) == 8

    def test_cn_clamped_to_valid_range(self, sample_boundary, mock_db):
        """Test that CN is always in 0-100 range."""
        mock_results = [
            MagicMock(category="las", cn_value=60, total_area_m2=1000000),
        ]
        mock_db.execute.return_value.fetchall.return_value = mock_results

        cn, _ = calculate_weighted_cn(sample_boundary, mock_db)

        assert 0 <= cn <= 100

    def test_returns_default_on_database_error(self, sample_boundary, mock_db):
        """Test that default CN is returned on database error."""
        mock_db.execute.side_effect = Exception("Database connection failed")

        cn, stats = calculate_weighted_cn(sample_boundary, mock_db)

        assert cn == DEFAULT_CN
        assert stats == {}

    def test_returns_default_for_zero_area(self, sample_boundary, mock_db):
        """Test that default CN is returned when total area is zero."""
        mock_results = [
            MagicMock(category="las", cn_value=60, total_area_m2=0),
        ]
        mock_db.execute.return_value.fetchall.return_value = mock_results

        cn, stats = calculate_weighted_cn(sample_boundary, mock_db)

        assert cn == DEFAULT_CN
        assert stats == {}

    def test_returns_default_for_invalid_boundary(self, mock_db):
        """Test that default CN is returned for invalid boundary."""
        # Create an invalid polygon (self-intersecting)
        invalid_boundary = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
        assert not invalid_boundary.is_valid

        cn, stats = calculate_weighted_cn(invalid_boundary, mock_db)

        assert cn == DEFAULT_CN
        assert stats == {}

    def test_aggregates_same_category(self, sample_boundary, mock_db):
        """Test that same category from different polygons is aggregated."""
        # Two forest polygons with different CN (shouldn't happen but test handling)
        mock_results = [
            MagicMock(category="las", cn_value=60, total_area_m2=500000),
            MagicMock(category="las", cn_value=65, total_area_m2=500000),
        ]
        mock_db.execute.return_value.fetchall.return_value = mock_results

        cn, stats = calculate_weighted_cn(sample_boundary, mock_db)

        # Weighted: (60*0.5 + 65*0.5) = 62.5 -> 62 (Python banker's rounding)
        assert cn == 62
        # Stats should aggregate percentages
        assert stats["las"] == 100.0

    def test_water_category_cn_100(self, sample_boundary, mock_db):
        """Test water bodies have CN=100."""
        mock_results = [
            MagicMock(category="woda", cn_value=100, total_area_m2=100000),
        ]
        mock_db.execute.return_value.fetchall.return_value = mock_results

        cn, stats = calculate_weighted_cn(sample_boundary, mock_db)

        assert cn == 100
        assert stats["woda"] == 100.0


class TestGetLandCoverForBoundary:
    """Tests for get_land_cover_for_boundary function."""

    @pytest.fixture
    def sample_boundary(self):
        """Create a sample boundary polygon in EPSG:2180."""
        return box(500000, 600000, 501000, 601000)

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return MagicMock()

    def test_returns_none_when_no_data(self, sample_boundary, mock_db):
        """Test returns None when no land cover data found."""
        mock_db.execute.return_value.fetchall.return_value = []

        result = get_land_cover_for_boundary(sample_boundary, mock_db)

        assert result is None

    def test_returns_detailed_info(self, sample_boundary, mock_db):
        """Test returns detailed land cover information."""
        mock_results = [
            MagicMock(
                category="las",
                cn_value=60,
                imperviousness=0.0,
                total_area_m2=600000,
            ),
            MagicMock(
                category="grunt_orny",
                cn_value=78,
                imperviousness=0.1,
                total_area_m2=400000,
            ),
        ]
        mock_db.execute.return_value.fetchall.return_value = mock_results

        result = get_land_cover_for_boundary(sample_boundary, mock_db)

        assert result is not None
        assert "categories" in result
        assert "total_area_m2" in result
        assert "weighted_cn" in result
        assert "weighted_imperviousness" in result
        assert len(result["categories"]) == 2
        assert result["weighted_cn"] == 67
        assert result["total_area_m2"] == 1000000

    def test_returns_none_for_invalid_boundary(self, mock_db):
        """Test returns None for invalid boundary."""
        invalid_boundary = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])

        result = get_land_cover_for_boundary(invalid_boundary, mock_db)

        assert result is None

    def test_returns_none_on_database_error(self, sample_boundary, mock_db):
        """Test returns None on database error."""
        mock_db.execute.side_effect = Exception("Connection failed")

        result = get_land_cover_for_boundary(sample_boundary, mock_db)

        assert result is None

    def test_calculates_weighted_imperviousness(self, sample_boundary, mock_db):
        """Test weighted imperviousness calculation."""
        # 50% impervious area (droga), 50% pervious (las)
        mock_results = [
            MagicMock(
                category="droga",
                cn_value=98,
                imperviousness=0.95,
                total_area_m2=500000,
            ),
            MagicMock(
                category="las",
                cn_value=60,
                imperviousness=0.0,
                total_area_m2=500000,
            ),
        ]
        mock_db.execute.return_value.fetchall.return_value = mock_results

        result = get_land_cover_for_boundary(sample_boundary, mock_db)

        # Expected: (0.95*0.5 + 0.0*0.5) = 0.475
        assert result["weighted_imperviousness"] == pytest.approx(0.475, abs=0.001)

    def test_handles_none_imperviousness(self, sample_boundary, mock_db):
        """Test handles None imperviousness values."""
        mock_results = [
            MagicMock(
                category="inny",
                cn_value=75,
                imperviousness=None,
                total_area_m2=1000000,
            ),
        ]
        mock_db.execute.return_value.fetchall.return_value = mock_results

        result = get_land_cover_for_boundary(sample_boundary, mock_db)

        assert result is not None
        assert result["weighted_imperviousness"] == 0.0


class TestDetermineCN:
    """Tests for determine_cn function (CN hierarchy)."""

    @pytest.fixture
    def sample_boundary(self):
        """Create a sample boundary polygon in EPSG:2180."""
        return box(500000, 600000, 501000, 601000)

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return MagicMock()

    def test_config_cn_has_highest_priority(self, sample_boundary, mock_db):
        """Test config_cn has highest priority."""
        cn, source, details = determine_cn(
            boundary=sample_boundary,
            db=mock_db,
            config_cn=80,
        )

        assert cn == 80
        assert source == "config"
        assert details is None
        # DB should not be queried
        mock_db.execute.assert_not_called()

    def test_uses_database_when_no_config(self, sample_boundary, mock_db):
        """Test uses database land_cover when no config_cn."""
        mock_results = [
            MagicMock(category="las", cn_value=60, total_area_m2=1000000),
        ]
        mock_db.execute.return_value.fetchall.return_value = mock_results

        cn, source, details = determine_cn(
            boundary=sample_boundary,
            db=mock_db,
            config_cn=None,
            use_kartograf=False,
        )

        assert cn == 60
        assert source == "database_land_cover"
        assert details is not None
        assert "stats" in details

    def test_returns_default_when_no_data(self, sample_boundary, mock_db):
        """Test returns default CN when no data available."""
        mock_db.execute.return_value.fetchall.return_value = []

        cn, source, details = determine_cn(
            boundary=sample_boundary,
            db=mock_db,
            config_cn=None,
            use_kartograf=False,
            default_cn=75,
        )

        assert cn == 75
        assert source == "default"
        assert details is None

    def test_custom_default_cn(self, sample_boundary, mock_db):
        """Test custom default_cn value is used."""
        mock_db.execute.return_value.fetchall.return_value = []

        cn, source, _ = determine_cn(
            boundary=sample_boundary,
            db=mock_db,
            config_cn=None,
            use_kartograf=False,
            default_cn=80,
        )

        assert cn == 80
        assert source == "default"

    def test_handles_database_error(self, sample_boundary, mock_db):
        """Test handles database error gracefully."""
        mock_db.execute.side_effect = Exception("Connection failed")

        cn, source, _ = determine_cn(
            boundary=sample_boundary,
            db=mock_db,
            config_cn=None,
            use_kartograf=False,
            default_cn=75,
        )

        assert cn == 75
        assert source == "default"

    def test_config_cn_zero_is_valid(self, sample_boundary, mock_db):
        """Test config_cn=0 is treated as valid explicit value."""
        # CN=0 is technically invalid but should be accepted if explicitly set
        cn, source, _ = determine_cn(
            boundary=sample_boundary,
            db=mock_db,
            config_cn=0,
        )

        assert cn == 0
        assert source == "config"

    @patch("core.cn_calculator.calculate_cn_from_kartograf")
    def test_uses_kartograf_when_db_empty(
        self, mock_kartograf, sample_boundary, mock_db, tmp_path
    ):
        """Test uses Kartograf when database has no data."""
        from core.cn_calculator import CNCalculationResult

        mock_db.execute.return_value.fetchall.return_value = []
        mock_kartograf.return_value = CNCalculationResult(
            cn=72,
            method="kartograf_hsg",
            dominant_hsg="B",
            hsg_stats={"B": 100.0},
            land_cover_stats={"forest": 100.0},
            cn_details=[{"land_cover": "forest", "cn": 55}],
        )

        cn, source, details = determine_cn(
            boundary=sample_boundary,
            db=mock_db,
            config_cn=None,
            use_kartograf=True,
            boundary_wgs84=[[17.31, 52.45], [17.32, 52.46]],
            data_dir=tmp_path,
        )

        assert cn == 72
        assert source == "kartograf_hsg"
        assert details is not None
        assert details["dominant_hsg"] == "B"

    @patch("core.cn_calculator.calculate_cn_from_kartograf")
    def test_kartograf_skipped_when_disabled(
        self, mock_kartograf, sample_boundary, mock_db
    ):
        """Test Kartograf is skipped when use_kartograf=False."""
        mock_db.execute.return_value.fetchall.return_value = []

        cn, source, _ = determine_cn(
            boundary=sample_boundary,
            db=mock_db,
            config_cn=None,
            use_kartograf=False,
        )

        assert source == "default"
        mock_kartograf.assert_not_called()

    @patch("core.cn_calculator.calculate_cn_from_kartograf")
    def test_kartograf_skipped_when_missing_params(
        self, mock_kartograf, sample_boundary, mock_db
    ):
        """Test Kartograf is skipped when boundary_wgs84 or data_dir missing."""
        mock_db.execute.return_value.fetchall.return_value = []

        # Missing boundary_wgs84
        cn, source, _ = determine_cn(
            boundary=sample_boundary,
            db=mock_db,
            config_cn=None,
            use_kartograf=True,
            boundary_wgs84=None,
            data_dir=None,
        )

        assert source == "default"
        mock_kartograf.assert_not_called()

    def test_return_types(self, sample_boundary, mock_db):
        """Test correct return types."""
        mock_db.execute.return_value.fetchall.return_value = []

        result = determine_cn(
            boundary=sample_boundary,
            db=mock_db,
            config_cn=None,
            use_kartograf=False,
        )

        assert isinstance(result, tuple)
        assert len(result) == 3
        cn, source, details = result
        assert isinstance(cn, int)
        assert isinstance(source, str)
        assert details is None or isinstance(details, dict)
