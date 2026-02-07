"""
Unit tests for cn_tables module.

Tests for CN lookup tables and functions.
"""

import pytest

from core.cn_tables import (
    CN_LOOKUP_TABLE,
    DEFAULT_CN,
    VALID_HSG,
    calculate_weighted_cn_from_stats,
    lookup_cn,
)


class TestConstants:
    """Tests for module constants."""

    def test_default_cn_value(self):
        """Test default CN is 75 (average condition)."""
        assert DEFAULT_CN == 75

    def test_default_cn_in_valid_range(self):
        """Test default CN is in valid SCS-CN range."""
        assert 0 <= DEFAULT_CN <= 100

    def test_valid_hsg_contains_all_groups(self):
        """Test VALID_HSG contains A, B, C, D."""
        assert frozenset(["A", "B", "C", "D"]) == VALID_HSG

    def test_valid_hsg_is_frozenset(self):
        """Test VALID_HSG is immutable."""
        assert isinstance(VALID_HSG, frozenset)


class TestCNLookupTable:
    """Tests for CN_LOOKUP_TABLE structure."""

    def test_table_not_empty(self):
        """Test CN lookup table is not empty."""
        assert len(CN_LOOKUP_TABLE) > 0

    def test_all_entries_have_all_hsg(self):
        """Test each entry has values for all HSG groups."""
        for land_cover, cn_values in CN_LOOKUP_TABLE.items():
            for hsg in VALID_HSG:
                assert hsg in cn_values, f"{land_cover} missing HSG {hsg}"

    def test_all_cn_values_in_range(self):
        """Test all CN values are in 0-100 range."""
        for land_cover, cn_values in CN_LOOKUP_TABLE.items():
            for hsg, cn in cn_values.items():
                assert 0 <= cn <= 100, f"{land_cover}/{hsg}: CN={cn} out of range"

    def test_cn_increases_with_hsg(self):
        """Test CN generally increases from A to D (less permeable soils)."""
        # For most land covers, CN: A < B < C < D
        permeable_categories = ["forest", "meadow", "arable"]
        for cat in permeable_categories:
            cn_values = CN_LOOKUP_TABLE.get(cat)
            if cn_values:
                assert cn_values["A"] <= cn_values["B"] <= cn_values["C"]
                assert cn_values["C"] <= cn_values["D"]

    def test_impervious_surfaces_high_cn(self):
        """Test impervious surfaces have high CN (98-100)."""
        impervious = ["road", "droga", "water", "woda"]
        for cat in impervious:
            cn_values = CN_LOOKUP_TABLE.get(cat)
            if cn_values:
                for hsg in VALID_HSG:
                    assert cn_values[hsg] >= 98

    def test_forest_has_low_cn(self):
        """Test forest has relatively low CN values."""
        forest_cn = CN_LOOKUP_TABLE.get("forest")
        assert forest_cn is not None
        assert forest_cn["A"] <= 40  # Low CN for HSG A
        assert forest_cn["D"] <= 80  # Moderate CN even for HSG D

    def test_bdot10k_categories_present(self):
        """Test BDOT10k category codes are present."""
        bdot_codes = ["PTLZ", "PTZB", "PTUT", "BUBD", "SKDR", "PTWP"]
        for code in bdot_codes:
            assert code in CN_LOOKUP_TABLE, f"Missing BDOT10k code: {code}"

    def test_corine_categories_present(self):
        """Test CORINE 2-digit codes are present."""
        corine_codes = ["11", "21", "31", "41", "51"]
        for code in corine_codes:
            assert code in CN_LOOKUP_TABLE, f"Missing CORINE code: {code}"

    def test_polish_names_present(self):
        """Test Polish land cover names are present."""
        polish_names = ["las", "łąka", "grunt_orny", "droga", "woda"]
        for name in polish_names:
            assert name in CN_LOOKUP_TABLE, f"Missing Polish name: {name}"


class TestLookupCN:
    """Tests for lookup_cn function."""

    def test_known_value_forest_b(self):
        """Test known CN value for forest with HSG B."""
        assert lookup_cn("forest", "B") == 55

    def test_known_value_forest_a(self):
        """Test known CN value for forest with HSG A."""
        assert lookup_cn("forest", "A") == 30

    def test_known_value_road_any_hsg(self):
        """Test road has CN=98 for all HSG groups."""
        for hsg in VALID_HSG:
            assert lookup_cn("road", hsg) == 98

    def test_known_value_water(self):
        """Test water has CN=100."""
        assert lookup_cn("water", "B") == 100

    def test_unknown_category_returns_other(self):
        """Test unknown category returns 'other' values."""
        cn = lookup_cn("completely_unknown_xyz", "B")
        assert cn == CN_LOOKUP_TABLE["other"]["B"]

    def test_invalid_hsg_uses_default(self):
        """Test invalid HSG uses default (B)."""
        cn_invalid = lookup_cn("forest", "X")
        cn_default = lookup_cn("forest", "B")
        assert cn_invalid == cn_default

    def test_empty_hsg_uses_default(self):
        """Test empty HSG uses default (B)."""
        cn_empty = lookup_cn("forest", "")
        cn_default = lookup_cn("forest", "B")
        assert cn_empty == cn_default

    def test_lowercase_hsg_works(self):
        """Test lowercase HSG letters work correctly."""
        assert lookup_cn("forest", "b") == lookup_cn("forest", "B")
        assert lookup_cn("forest", "a") == lookup_cn("forest", "A")

    def test_custom_default_hsg(self):
        """Test custom default HSG parameter."""
        cn = lookup_cn("forest", "X", default_hsg="C")
        assert cn == lookup_cn("forest", "C")

    @pytest.mark.parametrize(
        "land_cover,hsg,expected",
        [
            ("forest", "B", 55),
            ("las", "B", 55),
            ("PTLZ", "B", 55),
            ("meadow", "B", 58),
            ("arable", "B", 81),
            ("road", "A", 98),
            ("water", "D", 100),
            ("21", "B", 81),  # CORINE arable
            ("31", "B", 55),  # CORINE forest
        ],
    )
    def test_various_categories(self, land_cover, hsg, expected):
        """Test various land cover categories and HSG combinations."""
        assert lookup_cn(land_cover, hsg) == expected


class TestCalculateWeightedCNFromStats:
    """Tests for calculate_weighted_cn_from_stats function."""

    def test_single_category_100_percent(self):
        """Test single category at 100%."""
        stats = {"forest": 100.0}
        cn = calculate_weighted_cn_from_stats(stats, "B")
        assert cn == 55

    def test_two_categories_50_50(self):
        """Test two categories at 50% each."""
        stats = {"forest": 50.0, "road": 50.0}
        cn = calculate_weighted_cn_from_stats(stats, "B")
        # (55*0.5 + 98*0.5) = 76.5 -> 76 or 77
        assert cn in [76, 77]

    def test_three_categories_weighted(self):
        """Test three categories with different weights."""
        stats = {"forest": 60.0, "arable": 30.0, "road": 10.0}
        cn = calculate_weighted_cn_from_stats(stats, "B")
        # (55*0.6 + 81*0.3 + 98*0.1) = 33 + 24.3 + 9.8 = 67.1 -> 67
        assert cn == 67

    def test_empty_stats_returns_default(self):
        """Test empty stats returns DEFAULT_CN."""
        cn = calculate_weighted_cn_from_stats({}, "B")
        assert cn == DEFAULT_CN

    def test_result_clamped_to_range(self):
        """Test result is always in 0-100 range."""
        stats = {"water": 100.0}  # CN=100
        cn = calculate_weighted_cn_from_stats(stats, "D")
        assert 0 <= cn <= 100

    def test_normalization_when_not_100_percent(self):
        """Test normalization when percentages don't sum to 100."""
        # Only 50% specified
        stats = {"forest": 25.0, "road": 25.0}
        cn = calculate_weighted_cn_from_stats(stats, "B")
        # Should normalize to 100%: (55*0.5 + 98*0.5) = 76.5 -> 76 or 77
        assert cn in [76, 77]

    def test_different_hsg_affects_result(self):
        """Test different HSG produces different CN."""
        stats = {"forest": 100.0}
        cn_a = calculate_weighted_cn_from_stats(stats, "A")
        cn_d = calculate_weighted_cn_from_stats(stats, "D")
        assert cn_a < cn_d  # HSG A should have lower CN than D

    def test_all_water_returns_100(self):
        """Test 100% water returns CN=100."""
        stats = {"water": 100.0}
        cn = calculate_weighted_cn_from_stats(stats, "B")
        assert cn == 100

    def test_all_forest_hsg_a_returns_30(self):
        """Test 100% forest with HSG A returns CN=30."""
        stats = {"forest": 100.0}
        cn = calculate_weighted_cn_from_stats(stats, "A")
        assert cn == 30

    def test_realistic_mixed_land_cover(self):
        """Test realistic mixed land cover scenario."""
        # Typical rural watershed
        stats = {
            "arable": 45.0,  # Fields
            "meadow": 25.0,  # Meadows
            "forest": 20.0,  # Forest
            "urban_residential": 8.0,  # Villages
            "road": 2.0,  # Roads
        }
        cn = calculate_weighted_cn_from_stats(stats, "B")
        # Should be somewhere between forest (55) and urban (85)
        assert 60 < cn < 85
