"""
Unit tests for cn_calculator module.

Tests for CN calculation using Kartograf integration.
"""

from unittest.mock import MagicMock, patch

import kartograf
import pytest

from core.cn_calculator import (
    calculate_cn_from_kartograf,
    check_kartograf_available,
    get_default_land_cover_stats,
    get_hsg_from_soilgrids,
    weighted_cn_of_shares,
)
from core.land_cover import VALID_CATEGORIES
from tests.kartograf_offline import LOAM, SANDY, SoilRasters, soil_rasters
from tests.kartograf_offline import offline as offline  # noqa: F401


class TestCheckKartografAvailable:
    """Tests for check_kartograf_available function."""

    def test_true_when_the_functions_used_here_are_importable(self):
        """The Kartograf names that core.cn_calculator calls exist in the pinned one."""
        assert check_kartograf_available() is True


class TestGetDefaultLandCoverStats:
    """The assumed land cover of an area without one."""

    def test_categories_of_the_table_summing_to_100(self):
        stats = get_default_land_cover_stats()

        assert set(stats) <= VALID_CATEGORIES
        assert sum(stats.values()) == pytest.approx(100.0)


class TestWeightedCnOfShares:
    """Every category on every soil group in their shares (no overlay)."""

    def test_cn_of_the_complexes_weighted_by_both_shares(self):
        # las B 55, C 70; grunt_orny B 75, C 83
        cn, details = weighted_cn_of_shares(
            {"las": 60.0, "grunt_orny": 40.0}, {"A": 0.0, "B": 80.0, "C": 20.0}
        )

        # las: 0.8*55 + 0.2*70 = 58; grunt_orny: 0.8*75 + 0.2*83 = 76.6
        assert cn == pytest.approx(0.6 * 58 + 0.4 * 76.6, abs=0.05)
        assert details == [
            {"land_cover": "las", "percentage": 60.0, "cn": 58.0},
            {"land_cover": "grunt_orny", "percentage": 40.0, "cn": 76.6},
        ]

    @pytest.mark.parametrize(
        ("land_cover", "hsg"), [({}, {"B": 100.0}), ({"las": 100.0}, {"B": 0.0})]
    )
    def test_without_land_cover_or_soil_groups_the_default_cn(self, land_cover, hsg):
        assert weighted_cn_of_shares(land_cover, hsg) == (75.0, [])


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
        """The CN of forest is weighted over the soil groups of the area."""
        mock_check.return_value = True
        mock_bbox.return_value = MagicMock(
            min_x=500000, min_y=600000, max_x=501000, max_y=601000
        )
        mock_hsg.return_value = ("B", {"B": 80.0, "C": 20.0})
        mock_land_cover.return_value = {"las": 100.0}

        result = calculate_cn_from_kartograf(sample_boundary_wgs84, tmp_path)

        assert result is not None
        assert result.cn == 58.0  # woods, good: 0.8 * 55 (B) + 0.2 * 70 (C)
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
        mock_land_cover.return_value = {"las": 60.0, "grunt_orny": 40.0}

        result = calculate_cn_from_kartograf(sample_boundary_wgs84, tmp_path)

        assert result is not None
        assert result.cn_details == [
            {"land_cover": "las", "percentage": 60.0, "cn": 55.0},
            {"land_cover": "grunt_orny", "percentage": 40.0, "cn": 75.0},
        ]

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
        mock_land_cover.return_value = {"las": 100.0}

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
            "grunt_orny": 45.0,
            "łąka": 25.0,
            "las": 20.0,
            "zabudowa_mieszkaniowa": 8.0,
            "droga": 2.0,
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
            "zabudowa_przemysłowa": 40.0,
            "zabudowa_mieszkaniowa": 35.0,
            "droga": 20.0,
            "łąka": 5.0,
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
            "las": 85.0,
            "łąka": 10.0,
            "woda": 5.0,
        }

        result = calculate_cn_from_kartograf(sample_boundary_wgs84, tmp_path)

        assert result is not None
        # Forested watershed with HSG A should have low CN
        assert result.cn < 50
        assert result.dominant_hsg == "A"


@pytest.mark.usefixtures("offline")
class TestGetHsgFromSoilgrids:
    """The dominant soil group of an area through calculate_hsg (plain, temporary)."""

    BBOX = kartograf.BBox(450000, 550000, 460000, 560000, "EPSG:2180")

    def test_loam_is_group_b(self):
        with soil_rasters(SoilRasters(LOAM)):
            dominant, stats = get_hsg_from_soilgrids(self.BBOX)

        assert dominant == "B"
        assert stats == {"A": 0.0, "B": 100.0, "C": 0.0, "D": 0.0}

    def test_loamy_sand_is_group_a(self):
        with soil_rasters(SoilRasters(SANDY)):
            dominant, stats = get_hsg_from_soilgrids(self.BBOX)

        assert dominant == "A"
        assert stats["A"] == pytest.approx(100.0)

    def test_the_group_is_that_of_the_least_permeable_layer(self):
        """Loamy sand (A) over loam at 60-100 cm (B) is B, not A (ADR-079)."""
        soil = SoilRasters(SANDY, layers={"60-100cm": LOAM})
        with soil_rasters(soil):
            dominant, stats = get_hsg_from_soilgrids(self.BBOX)

        assert dominant == "B"
        assert stats == {"A": 0.0, "B": 100.0, "C": 0.0, "D": 0.0}

    def test_all_nodata_uses_the_default_group_not_group_a(self):
        empty = {"clay": 0.0, "sand": 0.0, "silt": 0.0}
        with soil_rasters(SoilRasters(empty)):
            result = get_hsg_from_soilgrids(self.BBOX)

        assert result == ("B", {"B": 100.0})

    def test_a_failed_download_uses_the_default_group(self):
        down = {name: kartograf.DownloadError("HTTP 500") for name in LOAM}
        with soil_rasters(SoilRasters(down)):
            result = get_hsg_from_soilgrids(self.BBOX)

        assert result == ("B", {"B": 100.0})

    def test_nothing_of_the_call_stays_on_disk(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with soil_rasters(SoilRasters(LOAM)):
            get_hsg_from_soilgrids(self.BBOX)

        assert list(tmp_path.iterdir()) == []
