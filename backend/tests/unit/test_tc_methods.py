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

    def test_overland_length_optional(self):
        from models.schemas import HydrographRequest
        req = HydrographRequest(
            latitude=52.0, longitude=17.0, duration="1h", probability=10,
            tc_method="faa", tc_overland_length_km=0.5,
        )
        assert req.tc_overland_length_km == 0.5


class TestFaaRequiresOverlandLength:
    """Tests that FAA method requires tc_overland_length_km."""

    def test_faa_without_overland_raises(self):
        """FAA without tc_overland_length_km should raise ValueError."""
        from unittest.mock import MagicMock
        from api.endpoints.hydrograph import _calculate_tc
        from hydrolog.morphometry import WatershedParameters

        morph_dict = {
            "area_km2": 10.0, "perimeter_km": 15.0, "length_km": 5.0,
            "elevation_min_m": 100.0, "elevation_max_m": 200.0,
            "mean_slope_m_per_m": 0.02, "cn": 75,
        }
        wp = WatershedParameters.from_dict(morph_dict)
        request = MagicMock()
        request.tc_runoff_coeff = None
        request.tc_overland_length_km = None

        with pytest.raises(ValueError, match="FAA wymaga"):
            _calculate_tc("faa", wp, morph_dict, request)

    def test_faa_with_overland_works(self):
        """FAA with tc_overland_length_km should compute valid tc."""
        from unittest.mock import MagicMock
        from api.endpoints.hydrograph import _calculate_tc
        from hydrolog.morphometry import WatershedParameters

        morph_dict = {
            "area_km2": 10.0, "perimeter_km": 15.0, "length_km": 5.0,
            "elevation_min_m": 100.0, "elevation_max_m": 200.0,
            "mean_slope_m_per_m": 0.02, "cn": 75,
        }
        wp = WatershedParameters.from_dict(morph_dict)
        request = MagicMock()
        request.tc_runoff_coeff = None
        request.tc_overland_length_km = 0.5

        tc = _calculate_tc("faa", wp, morph_dict, request)
        assert tc > 0


class TestKerbyRequiresOverlandLength:
    """Tests that Kerby method requires tc_overland_length_km."""

    def test_kerby_without_overland_raises(self):
        """Kerby without tc_overland_length_km should raise ValueError."""
        from unittest.mock import MagicMock
        from api.endpoints.hydrograph import _calculate_tc
        from hydrolog.morphometry import WatershedParameters

        morph_dict = {
            "area_km2": 10.0, "perimeter_km": 15.0, "length_km": 5.0,
            "elevation_min_m": 100.0, "elevation_max_m": 200.0,
            "mean_slope_m_per_m": 0.02,
        }
        wp = WatershedParameters.from_dict(morph_dict)
        request = MagicMock()
        request.tc_retardance = 0.4
        request.tc_overland_length_km = None

        with pytest.raises(ValueError, match="Kerby wymaga"):
            _calculate_tc("kerby", wp, morph_dict, request)

    def test_kerby_with_overland_works(self):
        """Kerby with tc_overland_length_km should compute valid tc."""
        from unittest.mock import MagicMock
        from api.endpoints.hydrograph import _calculate_tc
        from hydrolog.morphometry import WatershedParameters

        morph_dict = {
            "area_km2": 10.0, "perimeter_km": 15.0, "length_km": 5.0,
            "elevation_min_m": 100.0, "elevation_max_m": 200.0,
            "mean_slope_m_per_m": 0.02,
        }
        wp = WatershedParameters.from_dict(morph_dict)
        request = MagicMock()
        request.tc_retardance = 0.4
        request.tc_overland_length_km = 0.2

        tc = _calculate_tc("kerby", wp, morph_dict, request)
        assert tc > 0


class TestNrcsUsesHydraulicLength:
    """Verify NRCS uses hydraulic_length_km when available."""

    def test_nrcs_with_hydraulic_length(self):
        """NRCS tc should be longer with hydraulic_length than without."""
        from hydrolog.morphometry import WatershedParameters
        # Simulate what _calculate_tc does: clear channel_slope, set length_km = hydraulic
        base = {
            "area_km2": 10, "perimeter_km": 15, "length_km": 7.0,
            "elevation_min_m": 100, "elevation_max_m": 200,
            "mean_slope_m_per_m": 0.03, "cn": 75,
        }
        # tc with default length (7km) — as if no hydraulic available
        wp1 = WatershedParameters.from_dict(base)
        tc_short = wp1.calculate_tc(method="nrcs")

        # tc with hydraulic length (9km)
        wp2 = WatershedParameters.from_dict({**base, "length_km": 9.0})
        tc_long = wp2.calculate_tc(method="nrcs")

        # Longer flow path → longer tc
        assert tc_long > tc_short

    def test_nrcs_calculate_tc_uses_hydraulic_from_morph_dict(self):
        """_calculate_tc for NRCS should use hydraulic_length_km from morph_dict."""
        from unittest.mock import MagicMock
        from api.endpoints.hydrograph import _calculate_tc
        from hydrolog.morphometry import WatershedParameters

        morph_dict = {
            "area_km2": 10.0, "perimeter_km": 15.0, "length_km": 7.0,
            "elevation_min_m": 100.0, "elevation_max_m": 200.0,
            "mean_slope_m_per_m": 0.03,
            "channel_length_km": 5.0, "channel_slope_m_per_m": 0.005,
            "cn": 75,
        }
        wp = WatershedParameters.from_dict(morph_dict)
        request = MagicMock()

        # Without hydraulic_length
        tc_no_hydraulic = _calculate_tc("nrcs", wp, morph_dict, request)

        # With hydraulic_length (longer path)
        morph_with_hydraulic = {**morph_dict, "hydraulic_length_km": 9.0}
        wp2 = WatershedParameters.from_dict(morph_dict)
        tc_with_hydraulic = _calculate_tc("nrcs", wp2, morph_with_hydraulic, request)

        assert tc_with_hydraulic > tc_no_hydraulic

    def test_kirpich_uses_hydraulic_from_morph_dict(self):
        """_calculate_tc for Kirpich should use hydraulic_length_km from morph_dict."""
        from unittest.mock import MagicMock
        from api.endpoints.hydrograph import _calculate_tc
        from hydrolog.morphometry import WatershedParameters

        morph_dict = {
            "area_km2": 10.0, "perimeter_km": 15.0, "length_km": 7.0,
            "elevation_min_m": 100.0, "elevation_max_m": 200.0,
            "mean_slope_m_per_m": 0.03,
            "channel_length_km": 5.0, "channel_slope_m_per_m": 0.005,
        }
        wp = WatershedParameters.from_dict(morph_dict)
        request = MagicMock()

        tc_no_hydraulic = _calculate_tc("kirpich", wp, morph_dict, request)

        morph_with_hydraulic = {**morph_dict, "hydraulic_length_km": 9.0}
        wp2 = WatershedParameters.from_dict(morph_dict)
        tc_with_hydraulic = _calculate_tc("kirpich", wp2, morph_with_hydraulic, request)

        assert tc_with_hydraulic > tc_no_hydraulic

    def test_kerby_kirpich_uses_hydraulic_for_overland(self):
        """Kerby-Kirpich overland fallback should prefer hydraulic_length_km."""
        from unittest.mock import MagicMock
        from api.endpoints.hydrograph import _calculate_tc
        from hydrolog.morphometry import WatershedParameters

        morph_dict = {
            "area_km2": 10.0, "perimeter_km": 15.0, "length_km": 5.0,
            "elevation_min_m": 100.0, "elevation_max_m": 200.0,
            "mean_slope_m_per_m": 0.02,
            "channel_length_km": 3.0, "channel_slope_m_per_m": 0.01,
        }
        wp = WatershedParameters.from_dict(morph_dict)
        request = MagicMock()
        request.tc_retardance = 0.4
        request.tc_overland_length_km = None

        # Without hydraulic: overland = max(5.0 - 3.0, 0.1) = 2.0
        tc_no_hydraulic = _calculate_tc("kerby_kirpich", wp, morph_dict, request)

        # With hydraulic_length (8km): overland = max(8.0 - 3.0, 0.1) = 5.0
        morph_with_hydraulic = {**morph_dict, "hydraulic_length_km": 8.0}
        wp2 = WatershedParameters.from_dict(morph_dict)
        tc_with_hydraulic = _calculate_tc("kerby_kirpich", wp2, morph_with_hydraulic, request)

        assert tc_with_hydraulic > tc_no_hydraulic


class TestKerbyKirpichOverlandFallback:
    """Tests that Kerby-Kirpich uses overland from request or fallback."""

    def test_kerby_kirpich_uses_provided_overland(self):
        """Kerby-Kirpich should prefer tc_overland_length_km when provided."""
        from unittest.mock import MagicMock
        from api.endpoints.hydrograph import _calculate_tc
        from hydrolog.morphometry import WatershedParameters

        morph_dict = {
            "area_km2": 10.0, "perimeter_km": 15.0, "length_km": 5.0,
            "elevation_min_m": 100.0, "elevation_max_m": 200.0,
            "mean_slope_m_per_m": 0.02,
            "channel_length_km": 3.0, "channel_slope_m_per_m": 0.01,
        }
        wp = WatershedParameters.from_dict(morph_dict)
        request = MagicMock()
        request.tc_retardance = 0.4
        request.tc_overland_length_km = 0.3

        tc_with = _calculate_tc("kerby_kirpich", wp, morph_dict, request)

        # Without overland: fallback = max(5.0 - 3.0, 0.1) = 2.0 km
        request.tc_overland_length_km = None
        tc_without = _calculate_tc("kerby_kirpich", wp, morph_dict, request)

        # With 0.3 km overland should give shorter tc than 2.0 km fallback
        assert tc_with < tc_without

    def test_kerby_kirpich_fallback_without_overland(self):
        """Kerby-Kirpich should fallback to total-channel when no overland."""
        from unittest.mock import MagicMock
        from api.endpoints.hydrograph import _calculate_tc
        from hydrolog.morphometry import WatershedParameters

        morph_dict = {
            "area_km2": 10.0, "perimeter_km": 15.0, "length_km": 5.0,
            "elevation_min_m": 100.0, "elevation_max_m": 200.0,
            "mean_slope_m_per_m": 0.02,
            "channel_length_km": 3.0, "channel_slope_m_per_m": 0.01,
        }
        wp = WatershedParameters.from_dict(morph_dict)
        request = MagicMock()
        request.tc_retardance = 0.4
        request.tc_overland_length_km = None

        tc = _calculate_tc("kerby_kirpich", wp, morph_dict, request)
        assert tc > 0
