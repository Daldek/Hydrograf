"""Tests for new tc methods integration (FAA, Kerby, Kerby-Kirpich)."""
import pytest
from hydrolog.time.concentration import ConcentrationTime


class TestFAAMethod:
    def test_faa_returns_positive(self):
        tc = ConcentrationTime.faa(length_km=1.0, slope_m_per_m=0.02, runoff_coeff=0.5)
        assert tc > 0

    def test_faa_shorter_with_steeper_slope(self):
        tc_flat = ConcentrationTime.faa(length_km=1.0, slope_m_per_m=0.01, runoff_coeff=0.5)
        tc_steep = ConcentrationTime.faa(length_km=1.0, slope_m_per_m=0.05, runoff_coeff=0.5)
        assert tc_steep < tc_flat

    def test_faa_shorter_with_higher_runoff_coeff(self):
        tc_low = ConcentrationTime.faa(length_km=1.0, slope_m_per_m=0.02, runoff_coeff=0.3)
        tc_high = ConcentrationTime.faa(length_km=1.0, slope_m_per_m=0.02, runoff_coeff=0.8)
        assert tc_high < tc_low


class TestKerbyMethod:
    def test_kerby_returns_positive(self):
        tc = ConcentrationTime.kerby(length_km=0.5, slope_m_per_m=0.03, retardance=0.4)
        assert tc > 0

    def test_kerby_longer_with_higher_retardance(self):
        tc_smooth = ConcentrationTime.kerby(length_km=0.5, slope_m_per_m=0.03, retardance=0.1)
        tc_rough = ConcentrationTime.kerby(length_km=0.5, slope_m_per_m=0.03, retardance=0.6)
        assert tc_rough > tc_smooth


class TestKerbyKirpichMethod:
    def test_kerby_kirpich_returns_positive(self):
        tc = ConcentrationTime.kerby_kirpich(
            overland_length_km=0.3, overland_slope_m_per_m=0.05,
            retardance=0.4,
            channel_length_km=2.0, channel_slope_m_per_m=0.01,
        )
        assert tc > 0

    def test_kerby_kirpich_longer_than_kirpich_alone(self):
        tc_composite = ConcentrationTime.kerby_kirpich(
            overland_length_km=0.3, overland_slope_m_per_m=0.05,
            retardance=0.4,
            channel_length_km=2.0, channel_slope_m_per_m=0.01,
        )
        tc_kirpich = ConcentrationTime.kirpich(
            length_km=2.0, slope_m_per_m=0.01,
        )
        assert tc_composite >= tc_kirpich


class TestTcMethodInSchema:
    def test_accepts_faa(self):
        from models.schemas import HydrographRequest
        req = HydrographRequest(
            latitude=52.0, longitude=17.0, duration="1h", probability=10,
            tc_method="faa",
        )
        assert req.tc_method == "faa"

    def test_accepts_kerby(self):
        from models.schemas import HydrographRequest
        req = HydrographRequest(
            latitude=52.0, longitude=17.0, duration="1h", probability=10,
            tc_method="kerby",
        )
        assert req.tc_method == "kerby"

    def test_accepts_kerby_kirpich(self):
        from models.schemas import HydrographRequest
        req = HydrographRequest(
            latitude=52.0, longitude=17.0, duration="1h", probability=10,
            tc_method="kerby_kirpich",
        )
        assert req.tc_method == "kerby_kirpich"

    def test_runoff_coeff_optional(self):
        from models.schemas import HydrographRequest
        req = HydrographRequest(
            latitude=52.0, longitude=17.0, duration="1h", probability=10,
            tc_method="faa", tc_runoff_coeff=0.6,
        )
        assert req.tc_runoff_coeff == 0.6

    def test_retardance_optional(self):
        from models.schemas import HydrographRequest
        req = HydrographRequest(
            latitude=52.0, longitude=17.0, duration="1h", probability=10,
            tc_method="kerby", tc_retardance=0.4,
        )
        assert req.tc_retardance == 0.4

    def test_rejects_invalid_tc_method(self):
        from models.schemas import HydrographRequest
        with pytest.raises(Exception):
            HydrographRequest(
                latitude=52.0, longitude=17.0, duration="1h", probability=10,
                tc_method="invalid_method",
            )
