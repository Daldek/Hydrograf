"""
Unit tests for Snyder unit hydrograph integration.

Tests cover:
1. Morph dict includes length_to_centroid_km
2. HydrographRequest schema validation for uh_model, snyder_ct, snyder_cp
3. HydrographGenerator with Snyder model (no DB required)
4. Scenarios endpoint includes uh_models
5. HydrographMetadata includes uh_model field
"""

import math
from unittest.mock import MagicMock

import numpy as np
import pytest
from pydantic import ValidationError
from shapely.geometry import MultiPolygon, Polygon

from core.watershed_service import build_morph_dict_from_graph
from models.schemas import (
    HydrographMetadata,
    HydrographRequest,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_polygon():
    """A 10x10 square polygon centred at (500100, 600100)."""
    return Polygon(
        [
            (500095, 600095),
            (500105, 600095),
            (500105, 600105),
            (500095, 600105),
            (500095, 600095),
        ]
    )


@pytest.fixture
def mock_catchment_graph():
    """Mock CatchmentGraph with aggregate_stats returning known values."""
    cg = MagicMock()
    cg.aggregate_stats.return_value = {
        "area_km2": 45.3,
        "elevation_min_m": 120.0,
        "elevation_max_m": 350.0,
        "elevation_mean_m": 230.0,
        "mean_slope_m_per_m": 0.05,
        "mean_slope_percent": 5.0,
        "stream_length_km": 18.5,
        "drainage_density_km_per_km2": 0.4084,
        "max_strahler_order": 4,
        "stream_frequency_per_km2": 1.92,
    }
    cg.lookup_by_segment_idx.return_value = 0
    cg.trace_main_channel.return_value = {
        "main_channel_length_km": 8.5,
        "main_channel_slope_m_per_m": round((350.0 - 120.0) / (8.5 * 1000), 6),
        "main_channel_nodes": [0, 1, 2],
    }
    return cg


# ---------------------------------------------------------------------------
# 1. Morph dict includes length_to_centroid_km
# ---------------------------------------------------------------------------


class TestMorphDictLengthToCentroid:
    """Tests that build_morph_dict_from_graph returns length_to_centroid_km."""

    def test_length_to_centroid_present_in_morph_dict(
        self, mock_catchment_graph, simple_polygon
    ):
        """build_morph_dict_from_graph returns length_to_centroid_km key."""
        upstream = np.array([0, 1, 2])

        result = build_morph_dict_from_graph(
            cg=mock_catchment_graph,
            upstream_indices=upstream,
            boundary_2180=simple_polygon,
            outlet_x=500095.0,
            outlet_y=600095.0,
            segment_idx=42,
            threshold_m2=1000,
            cn=75,
        )

        assert "length_to_centroid_km" in result

    def test_length_to_centroid_is_positive_float(
        self, mock_catchment_graph, simple_polygon
    ):
        """length_to_centroid_km is a positive float when boundary and outlet are valid."""
        upstream = np.array([0, 1, 2])

        result = build_morph_dict_from_graph(
            cg=mock_catchment_graph,
            upstream_indices=upstream,
            boundary_2180=simple_polygon,
            outlet_x=500095.0,
            outlet_y=600095.0,
            segment_idx=42,
            threshold_m2=1000,
            cn=75,
        )

        lc = result["length_to_centroid_km"]
        assert isinstance(lc, float)
        assert lc > 0

    def test_length_to_centroid_matches_geometry(
        self, mock_catchment_graph, simple_polygon
    ):
        """length_to_centroid_km matches distance from outlet to boundary centroid."""
        upstream = np.array([0, 1, 2])
        outlet_x, outlet_y = 500095.0, 600095.0

        result = build_morph_dict_from_graph(
            cg=mock_catchment_graph,
            upstream_indices=upstream,
            boundary_2180=simple_polygon,
            outlet_x=outlet_x,
            outlet_y=outlet_y,
            segment_idx=42,
            threshold_m2=1000,
            cn=75,
        )

        # Compute expected distance manually
        centroid = simple_polygon.centroid
        expected_km = math.sqrt(
            (centroid.x - outlet_x) ** 2 + (centroid.y - outlet_y) ** 2
        ) / 1000
        expected_km = round(expected_km, 4)

        assert result["length_to_centroid_km"] == pytest.approx(expected_km, rel=1e-4)

    def test_length_to_centroid_zero_when_outlet_at_centroid(
        self, mock_catchment_graph, simple_polygon
    ):
        """length_to_centroid_km is 0.0 when outlet is at the centroid."""
        upstream = np.array([0, 1, 2])
        centroid = simple_polygon.centroid

        result = build_morph_dict_from_graph(
            cg=mock_catchment_graph,
            upstream_indices=upstream,
            boundary_2180=simple_polygon,
            outlet_x=centroid.x,
            outlet_y=centroid.y,
            segment_idx=42,
            threshold_m2=1000,
            cn=75,
        )

        assert result["length_to_centroid_km"] == 0.0

    def test_length_to_centroid_with_multipolygon(self, mock_catchment_graph):
        """length_to_centroid_km works with MultiPolygon boundary."""
        poly = Polygon(
            [
                (500000, 600000),
                (501000, 600000),
                (501000, 601000),
                (500000, 601000),
                (500000, 600000),
            ]
        )
        multi = MultiPolygon([poly])
        upstream = np.array([0, 1, 2])

        result = build_morph_dict_from_graph(
            cg=mock_catchment_graph,
            upstream_indices=upstream,
            boundary_2180=multi,
            outlet_x=500000.0,
            outlet_y=600000.0,
            segment_idx=42,
            threshold_m2=1000,
            cn=75,
        )

        assert "length_to_centroid_km" in result
        lc = result["length_to_centroid_km"]
        assert isinstance(lc, float)
        assert lc > 0


# ---------------------------------------------------------------------------
# 2. Schema validation (HydrographRequest)
# ---------------------------------------------------------------------------


class TestHydrographRequestUhModel:
    """Tests for HydrographRequest uh_model, snyder_ct, snyder_cp validation."""

    _BASE = {
        "latitude": 52.23,
        "longitude": 21.01,
        "duration": "1h",
        "probability": 10,
    }

    def test_default_uh_model_is_scs(self):
        """Default uh_model is 'scs'."""
        req = HydrographRequest(**self._BASE)
        assert req.uh_model == "scs"

    def test_accepts_uh_model_scs(self):
        """uh_model='scs' is accepted."""
        req = HydrographRequest(**{**self._BASE, "uh_model": "scs"})
        assert req.uh_model == "scs"

    def test_accepts_uh_model_snyder(self):
        """uh_model='snyder' is accepted."""
        req = HydrographRequest(**{**self._BASE, "uh_model": "snyder"})
        assert req.uh_model == "snyder"

    def test_rejects_invalid_uh_model(self):
        """uh_model='invalid' is rejected by Pydantic validation."""
        with pytest.raises(ValidationError) as exc_info:
            HydrographRequest(**{**self._BASE, "uh_model": "invalid"})

        errors = exc_info.value.errors()
        assert any("uh_model" in str(e.get("loc", "")) for e in errors)

    def test_accepts_uh_model_nash(self):
        """uh_model='nash' is accepted."""
        req = HydrographRequest(**{**self._BASE, "uh_model": "nash"})
        assert req.uh_model == "nash"
        assert req.nash_estimation == "from_tc"
        assert req.nash_n == 3.0

    def test_snyder_ct_optional(self):
        """snyder_ct is optional and defaults to None."""
        req = HydrographRequest(**{**self._BASE, "uh_model": "snyder"})
        assert req.snyder_ct is None

    def test_snyder_cp_optional(self):
        """snyder_cp is optional and defaults to None."""
        req = HydrographRequest(**{**self._BASE, "uh_model": "snyder"})
        assert req.snyder_cp is None

    def test_snyder_ct_positive(self):
        """snyder_ct accepts positive values."""
        req = HydrographRequest(
            **{**self._BASE, "uh_model": "snyder", "snyder_ct": 2.0}
        )
        assert req.snyder_ct == 2.0

    def test_snyder_ct_rejects_zero(self):
        """snyder_ct rejects zero (gt=0)."""
        with pytest.raises(ValidationError):
            HydrographRequest(
                **{**self._BASE, "uh_model": "snyder", "snyder_ct": 0}
            )

    def test_snyder_ct_rejects_negative(self):
        """snyder_ct rejects negative values."""
        with pytest.raises(ValidationError):
            HydrographRequest(
                **{**self._BASE, "uh_model": "snyder", "snyder_ct": -1.0}
            )

    def test_snyder_cp_accepts_valid_range(self):
        """snyder_cp accepts values in (0, 1]."""
        for cp in [0.1, 0.5, 0.6, 1.0]:
            req = HydrographRequest(
                **{**self._BASE, "uh_model": "snyder", "snyder_cp": cp}
            )
            assert req.snyder_cp == cp

    def test_snyder_cp_rejects_greater_than_1(self):
        """snyder_cp rejects values > 1."""
        with pytest.raises(ValidationError):
            HydrographRequest(
                **{**self._BASE, "uh_model": "snyder", "snyder_cp": 1.5}
            )

    def test_snyder_cp_rejects_zero(self):
        """snyder_cp rejects zero (gt=0)."""
        with pytest.raises(ValidationError):
            HydrographRequest(
                **{**self._BASE, "uh_model": "snyder", "snyder_cp": 0}
            )

    def test_snyder_cp_rejects_negative(self):
        """snyder_cp rejects negative values."""
        with pytest.raises(ValidationError):
            HydrographRequest(
                **{**self._BASE, "uh_model": "snyder", "snyder_cp": -0.5}
            )

    def test_snyder_params_with_scs_model(self):
        """snyder_ct and snyder_cp can be set even with uh_model='scs' (ignored)."""
        req = HydrographRequest(
            **{
                **self._BASE,
                "uh_model": "scs",
                "snyder_ct": 1.5,
                "snyder_cp": 0.6,
            }
        )
        assert req.uh_model == "scs"
        assert req.snyder_ct == 1.5
        assert req.snyder_cp == 0.6


# ---------------------------------------------------------------------------
# 3. HydrographGenerator with Snyder (no DB required)
# ---------------------------------------------------------------------------


class TestHydrographGeneratorSnyder:
    """Tests for HydrographGenerator with uh_model='snyder'."""

    def test_snyder_generator_creation(self):
        """HydrographGenerator can be created with uh_model='snyder'."""
        from hydrolog.runoff import HydrographGenerator

        gen = HydrographGenerator(
            area_km2=10.0,
            cn=75,
            tc_min=30.0,
            uh_model="snyder",
            uh_params={"L_km": 6.5, "Lc_km": 3.0, "ct": 1.5, "cp": 0.6},
        )
        assert gen.uh_model == "snyder"

    def test_snyder_generator_produces_valid_output(self):
        """Snyder generator produces valid times and discharge arrays."""
        from hydrolog.precipitation import BetaHietogram
        from hydrolog.runoff import HydrographGenerator

        gen = HydrographGenerator(
            area_km2=10.0,
            cn=75,
            tc_min=30.0,
            uh_model="snyder",
            uh_params={"L_km": 6.5, "Lc_km": 3.0, "ct": 1.5, "cp": 0.6},
        )
        hiet = BetaHietogram(alpha=2.0, beta=5.0)
        precip = hiet.generate(total_mm=45.0, duration_min=60.0, timestep_min=5.0)
        result = gen.generate(precipitation=precip, timestep_min=5.0)

        assert len(result.hydrograph.times_min) > 0
        assert len(result.hydrograph.discharge_m3s) > 0
        assert len(result.hydrograph.times_min) == len(
            result.hydrograph.discharge_m3s
        )

    def test_snyder_generator_positive_peak(self):
        """Snyder generator produces a positive peak discharge."""
        from hydrolog.precipitation import BetaHietogram
        from hydrolog.runoff import HydrographGenerator

        gen = HydrographGenerator(
            area_km2=10.0,
            cn=75,
            tc_min=30.0,
            uh_model="snyder",
            uh_params={"L_km": 6.5, "Lc_km": 3.0, "ct": 1.5, "cp": 0.6},
        )
        hiet = BetaHietogram(alpha=2.0, beta=5.0)
        precip = hiet.generate(total_mm=45.0, duration_min=60.0, timestep_min=5.0)
        result = gen.generate(precipitation=precip, timestep_min=5.0)

        assert result.peak_discharge_m3s > 0
        assert result.time_to_peak_min > 0
        assert result.total_volume_m3 > 0

    def test_snyder_generator_default_ct_cp(self):
        """Snyder generator works with default ct=1.5, cp=0.6 (omitted from params)."""
        from hydrolog.precipitation import BetaHietogram
        from hydrolog.runoff import HydrographGenerator

        gen = HydrographGenerator(
            area_km2=10.0,
            cn=75,
            tc_min=30.0,
            uh_model="snyder",
            uh_params={"L_km": 6.5, "Lc_km": 3.0},
        )
        hiet = BetaHietogram(alpha=2.0, beta=5.0)
        precip = hiet.generate(total_mm=45.0, duration_min=60.0, timestep_min=5.0)
        result = gen.generate(precipitation=precip, timestep_min=5.0)

        assert result.peak_discharge_m3s > 0

    def test_snyder_requires_L_km(self):
        """Snyder generator raises error when L_km is missing."""
        from hydrolog.runoff import HydrographGenerator

        with pytest.raises(Exception, match="L_km"):
            HydrographGenerator(
                area_km2=10.0,
                cn=75,
                tc_min=30.0,
                uh_model="snyder",
                uh_params={"Lc_km": 3.0},
            )

    def test_snyder_requires_Lc_km(self):
        """Snyder generator raises error when Lc_km is missing."""
        from hydrolog.runoff import HydrographGenerator

        with pytest.raises(Exception, match="Lc_km"):
            HydrographGenerator(
                area_km2=10.0,
                cn=75,
                tc_min=30.0,
                uh_model="snyder",
                uh_params={"L_km": 6.5},
            )

    def test_snyder_vs_scs_different_peaks(self):
        """Snyder and SCS models produce different peak discharges for same input."""
        from hydrolog.precipitation import BetaHietogram
        from hydrolog.runoff import HydrographGenerator

        hiet = BetaHietogram(alpha=2.0, beta=5.0)
        precip = hiet.generate(total_mm=45.0, duration_min=60.0, timestep_min=5.0)

        gen_scs = HydrographGenerator(
            area_km2=10.0, cn=75, tc_min=30.0, uh_model="scs"
        )
        result_scs = gen_scs.generate(precipitation=precip, timestep_min=5.0)

        gen_snyder = HydrographGenerator(
            area_km2=10.0,
            cn=75,
            tc_min=30.0,
            uh_model="snyder",
            uh_params={"L_km": 6.5, "Lc_km": 3.0, "ct": 1.5, "cp": 0.6},
        )
        result_snyder = gen_snyder.generate(precipitation=precip, timestep_min=5.0)

        # Different models should produce different peak discharges
        assert result_scs.peak_discharge_m3s != pytest.approx(
            result_snyder.peak_discharge_m3s, rel=0.01
        )

    def test_snyder_water_balance_consistency(self):
        """Snyder result has consistent water balance values."""
        from hydrolog.precipitation import BetaHietogram
        from hydrolog.runoff import HydrographGenerator

        gen = HydrographGenerator(
            area_km2=10.0,
            cn=75,
            tc_min=30.0,
            uh_model="snyder",
            uh_params={"L_km": 6.5, "Lc_km": 3.0, "ct": 1.5, "cp": 0.6},
        )
        hiet = BetaHietogram(alpha=2.0, beta=5.0)
        precip = hiet.generate(total_mm=45.0, duration_min=60.0, timestep_min=5.0)
        result = gen.generate(precipitation=precip, timestep_min=5.0)

        assert result.total_precip_mm == pytest.approx(45.0, rel=0.01)
        assert result.total_effective_mm <= result.total_precip_mm
        assert result.total_effective_mm >= 0
        assert 0 <= result.runoff_coefficient <= 1
        assert result.cn_used == 75
        assert result.retention_mm > 0
        assert result.initial_abstraction_mm >= 0


# ---------------------------------------------------------------------------
# 4. Scenarios endpoint includes uh_models
# ---------------------------------------------------------------------------


class TestScenariosUhModels:
    """Tests that /api/scenarios includes uh_models and snyder_defaults."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient

        from api.main import app

        return TestClient(app)

    def test_scenarios_includes_uh_models(self, client):
        """Scenarios response includes uh_models list."""
        response = client.get("/api/scenarios")
        assert response.status_code == 200
        data = response.json()
        assert "uh_models" in data

    def test_scenarios_uh_models_values(self, client):
        """uh_models contains both 'scs' and 'snyder'."""
        response = client.get("/api/scenarios")
        data = response.json()
        assert "scs" in data["uh_models"]
        assert "snyder" in data["uh_models"]

    def test_scenarios_includes_snyder_defaults(self, client):
        """Scenarios response includes snyder_defaults with ct and cp."""
        response = client.get("/api/scenarios")
        data = response.json()
        assert "snyder_defaults" in data
        defaults = data["snyder_defaults"]
        assert "ct" in defaults
        assert "cp" in defaults
        assert defaults["ct"] == 1.5
        assert defaults["cp"] == 0.6


# ---------------------------------------------------------------------------
# 5. HydrographMetadata includes uh_model
# ---------------------------------------------------------------------------


class TestHydrographMetadataUhModel:
    """Tests for HydrographMetadata uh_model field."""

    def test_default_uh_model_is_scs(self):
        """HydrographMetadata default uh_model is 'scs'."""
        meta = HydrographMetadata(
            tc_min=30.0,
            tc_method="kirpich",
            hietogram_type="beta",
        )
        assert meta.uh_model == "scs"

    def test_uh_model_can_be_snyder(self):
        """HydrographMetadata accepts uh_model='snyder'."""
        meta = HydrographMetadata(
            tc_min=30.0,
            tc_method="kirpich",
            hietogram_type="beta",
            uh_model="snyder",
        )
        assert meta.uh_model == "snyder"

    def test_uh_model_serialization(self):
        """HydrographMetadata uh_model serializes correctly."""
        meta = HydrographMetadata(
            tc_min=30.0,
            tc_method="kirpich",
            hietogram_type="beta",
            uh_model="snyder",
        )
        data = meta.model_dump()
        assert data["uh_model"] == "snyder"
