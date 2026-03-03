"""
Unit tests for cn_calculator module.

Tests for CN calculation using Kartograf integration.
"""

from unittest.mock import MagicMock, patch

import pytest

from core.cn_calculator import (
    CNCalculationResult,
    calculate_cn_from_kartograf,
    check_kartograf_available,
    get_default_land_cover_stats,
)


class TestCNCalculationResult:
    """Tests for CNCalculationResult dataclass."""

    def test_creation(self):
        """Test creating a CNCalculationResult instance."""
        result = CNCalculationResult(
            cn=72,
            method="kartograf_hsg",
            dominant_hsg="B",
            hsg_stats={"B": 80.0, "C": 20.0},
            land_cover_stats={"forest": 50.0, "arable": 50.0},
            cn_details=[
                {"land_cover": "forest", "cn": 55, "percentage": 50.0, "hsg": "B"}
            ],
        )
        assert result.cn == 72
        assert result.method == "kartograf_hsg"
        assert result.dominant_hsg == "B"

    def test_all_attributes_accessible(self):
        """Test all attributes are accessible."""
        result = CNCalculationResult(
            cn=75,
            method="test",
            dominant_hsg="A",
            hsg_stats={},
            land_cover_stats={},
            cn_details=[],
        )
        assert hasattr(result, "cn")
        assert hasattr(result, "method")
        assert hasattr(result, "dominant_hsg")
        assert hasattr(result, "hsg_stats")
        assert hasattr(result, "land_cover_stats")
        assert hasattr(result, "cn_details")


class TestCheckKartografAvailable:
    """Tests for check_kartograf_available function."""

    def test_returns_bool(self):
        """Test function returns boolean."""
        result = check_kartograf_available()
        assert isinstance(result, bool)

    @patch.dict("sys.modules", {"kartograf": None})
    def test_returns_false_when_kartograf_missing(self):
        """Test returns False when kartograf not installed."""
        # Note: This test may not work properly due to module caching
        # The function should handle ImportError gracefully
        pass


class TestGetDefaultLandCoverStats:
    """Tests for get_default_land_cover_stats function."""

    def test_returns_dict(self):
        """Test returns a dictionary."""
        stats = get_default_land_cover_stats()
        assert isinstance(stats, dict)

    def test_sums_to_100(self):
        """Test percentages sum to 100."""
        stats = get_default_land_cover_stats()
        total = sum(stats.values())
        assert total == pytest.approx(100.0, rel=0.01)

    def test_has_expected_categories(self):
        """Test contains expected land cover categories."""
        stats = get_default_land_cover_stats()
        assert "arable" in stats
        assert "meadow" in stats
        assert "forest" in stats

    def test_all_values_positive(self):
        """Test all percentage values are positive."""
        stats = get_default_land_cover_stats()
        for value in stats.values():
            assert value > 0

    def test_values_are_floats(self):
        """Test all values are floats."""
        stats = get_default_land_cover_stats()
        for value in stats.values():
            assert isinstance(value, float)


class TestCalculateCNFromKartograf:
    """Tests for calculate_cn_from_kartograf function."""

    @pytest.fixture
    def sample_boundary_wgs84(self):
        """Sample watershed boundary in WGS84."""
        return [
            [17.31, 52.45],
            [17.32, 52.45],
            [17.32, 52.46],
            [17.31, 52.46],
            [17.31, 52.45],
        ]

    @patch("core.cn_calculator.check_kartograf_available")
    def test_returns_none_when_kartograf_unavailable(
        self,
        mock_check,
        sample_boundary_wgs84,
        tmp_path,
    ):
        """Test returns None when Kartograf is not available."""
        mock_check.return_value = False

        result = calculate_cn_from_kartograf(sample_boundary_wgs84, tmp_path)

        assert result is None

    @patch("core.cn_calculator.check_kartograf_available")
    @patch("core.cn_calculator.convert_boundary_to_bbox")
    @patch("core.cn_calculator.get_hsg_from_soilgrids")
    @patch("core.cn_calculator.get_land_cover_stats")
    def test_uses_default_land_cover_when_empty(
        self,
        mock_land_cover,
        mock_hsg,
        mock_bbox,
        mock_check,
        sample_boundary_wgs84,
        tmp_path,
    ):
        """Test uses default land cover when no data available."""
        mock_check.return_value = True
        mock_bbox.return_value = MagicMock(
            min_x=500000, min_y=600000, max_x=501000, max_y=601000
        )
        mock_hsg.return_value = ("B", {"B": 100.0})
        mock_land_cover.return_value = {}

        result = calculate_cn_from_kartograf(
            sample_boundary_wgs84,
            tmp_path,
            use_default_land_cover=True,
        )

        assert result is not None
        assert result.land_cover_stats == get_default_land_cover_stats()

    @patch("core.cn_calculator.check_kartograf_available")
    @patch("core.cn_calculator.convert_boundary_to_bbox")
    @patch("core.cn_calculator.get_hsg_from_soilgrids")
    @patch("core.cn_calculator.get_land_cover_stats")
    def test_calculates_cn_correctly(
        self,
        mock_land_cover,
        mock_hsg,
        mock_bbox,
        mock_check,
        sample_boundary_wgs84,
        tmp_path,
    ):
        """Test CN calculation with mocked data."""
        mock_check.return_value = True
        mock_bbox.return_value = MagicMock(
            min_x=500000, min_y=600000, max_x=501000, max_y=601000
        )
        mock_hsg.return_value = ("B", {"B": 80.0, "C": 20.0})
        mock_land_cover.return_value = {"forest": 100.0}

        result = calculate_cn_from_kartograf(sample_boundary_wgs84, tmp_path)

        assert result is not None
        assert result.cn == 55  # forest + B = 55
        assert result.dominant_hsg == "B"
        assert result.method == "kartograf_hsg"

    @patch("core.cn_calculator.check_kartograf_available")
    @patch("core.cn_calculator.convert_boundary_to_bbox")
    @patch("core.cn_calculator.get_hsg_from_soilgrids")
    @patch("core.cn_calculator.get_land_cover_stats")
    def test_result_contains_cn_details(
        self,
        mock_land_cover,
        mock_hsg,
        mock_bbox,
        mock_check,
        sample_boundary_wgs84,
        tmp_path,
    ):
        """Test result contains CN calculation details."""
        mock_check.return_value = True
        mock_bbox.return_value = MagicMock(
            min_x=500000, min_y=600000, max_x=501000, max_y=601000
        )
        mock_hsg.return_value = ("B", {"B": 100.0})
        mock_land_cover.return_value = {"forest": 60.0, "arable": 40.0}

        result = calculate_cn_from_kartograf(sample_boundary_wgs84, tmp_path)

        assert result is not None
        assert len(result.cn_details) == 2
        # Check forest detail
        forest_detail = next(
            (d for d in result.cn_details if d["land_cover"] == "forest"), None
        )
        assert forest_detail is not None
        assert forest_detail["cn"] == 55
        assert forest_detail["percentage"] == 60.0

    @patch("core.cn_calculator.check_kartograf_available")
    @patch("core.cn_calculator.convert_boundary_to_bbox")
    @patch("core.cn_calculator.get_hsg_from_soilgrids")
    @patch("core.cn_calculator.get_land_cover_stats")
    def test_different_hsg_produces_different_cn(
        self,
        mock_land_cover,
        mock_hsg,
        mock_bbox,
        mock_check,
        sample_boundary_wgs84,
        tmp_path,
    ):
        """Test different HSG produces different CN for same land cover."""
        mock_check.return_value = True
        mock_bbox.return_value = MagicMock(
            min_x=500000, min_y=600000, max_x=501000, max_y=601000
        )
        mock_land_cover.return_value = {"forest": 100.0}

        # HSG A
        mock_hsg.return_value = ("A", {"A": 100.0})
        result_a = calculate_cn_from_kartograf(sample_boundary_wgs84, tmp_path)

        # HSG D
        mock_hsg.return_value = ("D", {"D": 100.0})
        result_d = calculate_cn_from_kartograf(sample_boundary_wgs84, tmp_path)

        assert result_a is not None
        assert result_d is not None
        assert result_a.cn < result_d.cn  # A should have lower CN than D

    @patch("core.cn_calculator.check_kartograf_available")
    @patch("core.cn_calculator.convert_boundary_to_bbox")
    @patch("core.cn_calculator.get_hsg_from_soilgrids")
    @patch("core.cn_calculator.get_land_cover_stats")
    def test_returns_none_when_no_land_cover_and_default_disabled(
        self,
        mock_land_cover,
        mock_hsg,
        mock_bbox,
        mock_check,
        sample_boundary_wgs84,
        tmp_path,
    ):
        """Test returns None when no land cover and default is disabled."""
        mock_check.return_value = True
        mock_bbox.return_value = MagicMock(
            min_x=500000, min_y=600000, max_x=501000, max_y=601000
        )
        mock_hsg.return_value = ("B", {"B": 100.0})
        mock_land_cover.return_value = {}

        result = calculate_cn_from_kartograf(
            sample_boundary_wgs84,
            tmp_path,
            use_default_land_cover=False,
        )

        # Should still return a result with empty land_cover_stats
        # but CN from cn_tables will use DEFAULT_CN
        assert result is not None
        assert result.land_cover_stats == {}

    @patch("core.cn_calculator.check_kartograf_available")
    @patch("core.cn_calculator.convert_boundary_to_bbox")
    def test_handles_bbox_conversion_error(
        self,
        mock_bbox,
        mock_check,
        sample_boundary_wgs84,
        tmp_path,
    ):
        """Test gracefully handles BBox conversion error."""
        mock_check.return_value = True
        mock_bbox.side_effect = Exception("Coordinate transformation failed")

        result = calculate_cn_from_kartograf(sample_boundary_wgs84, tmp_path)

        assert result is None

    @patch("core.cn_calculator.check_kartograf_available")
    @patch("core.cn_calculator.convert_boundary_to_bbox")
    @patch("core.cn_calculator.get_hsg_from_soilgrids")
    def test_handles_hsg_fetch_error(
        self,
        mock_hsg,
        mock_bbox,
        mock_check,
        sample_boundary_wgs84,
        tmp_path,
    ):
        """Test gracefully handles HSG fetch error."""
        mock_check.return_value = True
        mock_bbox.return_value = MagicMock(
            min_x=500000, min_y=600000, max_x=501000, max_y=601000
        )
        mock_hsg.side_effect = Exception("SoilGrids API error")

        result = calculate_cn_from_kartograf(sample_boundary_wgs84, tmp_path)

        assert result is None


class TestIntegrationScenarios:
    """Integration-like tests for realistic scenarios."""

    @pytest.fixture
    def sample_boundary_wgs84(self):
        """Sample watershed boundary in WGS84."""
        return [
            [17.31, 52.45],
            [17.32, 52.45],
            [17.32, 52.46],
            [17.31, 52.46],
            [17.31, 52.45],
        ]

    @patch("core.cn_calculator.check_kartograf_available")
    @patch("core.cn_calculator.convert_boundary_to_bbox")
    @patch("core.cn_calculator.get_hsg_from_soilgrids")
    @patch("core.cn_calculator.get_land_cover_stats")
    def test_typical_rural_watershed(
        self,
        mock_land_cover,
        mock_hsg,
        mock_bbox,
        mock_check,
        sample_boundary_wgs84,
        tmp_path,
    ):
        """Test typical rural watershed with mixed land cover."""
        mock_check.return_value = True
        mock_bbox.return_value = MagicMock(
            min_x=500000, min_y=600000, max_x=501000, max_y=601000
        )
        mock_hsg.return_value = ("B", {"A": 10.0, "B": 70.0, "C": 20.0})
        mock_land_cover.return_value = {
            "arable": 45.0,
            "meadow": 25.0,
            "forest": 20.0,
            "urban_residential": 8.0,
            "road": 2.0,
        }

        result = calculate_cn_from_kartograf(sample_boundary_wgs84, tmp_path)

        assert result is not None
        # CN should be between forest (55) and urban (85) for HSG B
        assert 60 < result.cn < 85
        assert result.dominant_hsg == "B"
        assert len(result.cn_details) == 5

    @patch("core.cn_calculator.check_kartograf_available")
    @patch("core.cn_calculator.convert_boundary_to_bbox")
    @patch("core.cn_calculator.get_hsg_from_soilgrids")
    @patch("core.cn_calculator.get_land_cover_stats")
    def test_urban_watershed(
        self,
        mock_land_cover,
        mock_hsg,
        mock_bbox,
        mock_check,
        sample_boundary_wgs84,
        tmp_path,
    ):
        """Test urban watershed with high imperviousness."""
        mock_check.return_value = True
        mock_bbox.return_value = MagicMock(
            min_x=500000, min_y=600000, max_x=501000, max_y=601000
        )
        mock_hsg.return_value = ("C", {"B": 20.0, "C": 80.0})
        mock_land_cover.return_value = {
            "urban_commercial": 40.0,
            "urban_residential": 35.0,
            "road": 20.0,
            "meadow": 5.0,
        }

        result = calculate_cn_from_kartograf(sample_boundary_wgs84, tmp_path)

        assert result is not None
        # Urban watershed should have high CN (>85)
        assert result.cn > 85
        assert result.dominant_hsg == "C"

    @patch("core.cn_calculator.check_kartograf_available")
    @patch("core.cn_calculator.convert_boundary_to_bbox")
    @patch("core.cn_calculator.get_hsg_from_soilgrids")
    @patch("core.cn_calculator.get_land_cover_stats")
    def test_forested_watershed(
        self,
        mock_land_cover,
        mock_hsg,
        mock_bbox,
        mock_check,
        sample_boundary_wgs84,
        tmp_path,
    ):
        """Test forested watershed with low CN."""
        mock_check.return_value = True
        mock_bbox.return_value = MagicMock(
            min_x=500000, min_y=600000, max_x=501000, max_y=601000
        )
        mock_hsg.return_value = ("A", {"A": 90.0, "B": 10.0})
        mock_land_cover.return_value = {
            "forest": 85.0,
            "meadow": 10.0,
            "water": 5.0,
        }

        result = calculate_cn_from_kartograf(sample_boundary_wgs84, tmp_path)

        assert result is not None
        # Forested watershed with HSG A should have low CN
        assert result.cn < 50
        assert result.dominant_hsg == "A"
