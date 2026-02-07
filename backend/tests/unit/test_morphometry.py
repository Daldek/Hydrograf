"""Unit tests for morphometry module."""

import pytest
from shapely.geometry import Polygon

from core.morphometry import (
    build_morphometric_params,
    calculate_drainage_indices,
    calculate_elevation_stats,
    calculate_hypsometric_curve,
    calculate_mean_slope,
    calculate_perimeter_km,
    calculate_relief_indices,
    calculate_shape_indices,
    calculate_watershed_length_km,
    find_main_stream,
)
from core.watershed import FlowCell

# ===== FIXTURES =====


@pytest.fixture
def sample_cells() -> list[FlowCell]:
    """
    Create sample FlowCell list for testing.

    Layout (3x3 grid, 100m spacing):
        4(125m) --- 5(120m)
           |          |
        1(100m) --- 2(110m) --- 3(115m)
           ↓ outlet

    Cell 1 is outlet (no downstream_id).
    Flow: 4→1, 5→2, 2→1, 3→2
    """
    return [
        FlowCell(
            id=1,
            x=0,
            y=0,
            elevation=100.0,
            flow_accumulation=5,
            slope=2.0,
            downstream_id=None,
            cell_area=10000.0,
            is_stream=True,
        ),
        FlowCell(
            id=2,
            x=100,
            y=0,
            elevation=110.0,
            flow_accumulation=3,
            slope=3.0,
            downstream_id=1,
            cell_area=10000.0,
            is_stream=True,
        ),
        FlowCell(
            id=3,
            x=200,
            y=0,
            elevation=115.0,
            flow_accumulation=1,
            slope=4.0,
            downstream_id=2,
            cell_area=10000.0,
            is_stream=False,
        ),
        FlowCell(
            id=4,
            x=0,
            y=100,
            elevation=125.0,
            flow_accumulation=1,
            slope=5.0,
            downstream_id=1,
            cell_area=10000.0,
            is_stream=False,
        ),
        FlowCell(
            id=5,
            x=100,
            y=100,
            elevation=120.0,
            flow_accumulation=1,
            slope=2.5,
            downstream_id=2,
            cell_area=10000.0,
            is_stream=False,
        ),
    ]


@pytest.fixture
def sample_outlet(sample_cells: list[FlowCell]) -> FlowCell:
    """Get outlet cell (id=1)."""
    return sample_cells[0]


@pytest.fixture
def sample_boundary() -> Polygon:
    """Create sample boundary polygon (1km x 1km square)."""
    return Polygon([(0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0)])


# ===== TEST: calculate_perimeter_km =====


class TestCalculatePerimeterKm:
    """Tests for calculate_perimeter_km function."""

    def test_square_perimeter(self, sample_boundary: Polygon):
        """Test perimeter of 1km square = 4km."""
        result = calculate_perimeter_km(sample_boundary)
        assert result == pytest.approx(4.0, rel=0.01)

    def test_triangle_perimeter(self):
        """Test perimeter of triangle."""
        triangle = Polygon([(0, 0), (3000, 0), (1500, 2000), (0, 0)])
        result = calculate_perimeter_km(triangle)
        assert result > 0
        # Perimeter ~ 3 + 2.5 + 2.5 = 8 km
        assert result == pytest.approx(8.0, rel=0.1)

    def test_returns_float(self, sample_boundary: Polygon):
        """Test that function returns float."""
        result = calculate_perimeter_km(sample_boundary)
        assert isinstance(result, float)


# ===== TEST: calculate_watershed_length_km =====


class TestCalculateWatershedLengthKm:
    """Tests for calculate_watershed_length_km function."""

    def test_length_calculation(
        self, sample_cells: list[FlowCell], sample_outlet: FlowCell
    ):
        """Test max distance from outlet."""
        result = calculate_watershed_length_km(sample_cells, sample_outlet)
        # Max distance from (0,0) to (200,0) = 200m = 0.2km
        # Or from (0,0) to (100,100) = ~141m
        assert result == pytest.approx(0.2, rel=0.01)

    def test_empty_cells(self, sample_outlet: FlowCell):
        """Test with empty cell list."""
        result = calculate_watershed_length_km([], sample_outlet)
        assert result == 0.0

    def test_single_cell(self, sample_outlet: FlowCell):
        """Test with single cell (outlet only)."""
        result = calculate_watershed_length_km([sample_outlet], sample_outlet)
        assert result == 0.0


# ===== TEST: calculate_elevation_stats =====


class TestCalculateElevationStats:
    """Tests for calculate_elevation_stats function."""

    def test_stats_calculation(self, sample_cells: list[FlowCell]):
        """Test elevation statistics."""
        result = calculate_elevation_stats(sample_cells)

        assert result["elevation_min_m"] == 100.0
        assert result["elevation_max_m"] == 125.0
        # Mean should be between min and max
        assert 100.0 <= result["elevation_mean_m"] <= 125.0

    def test_empty_cells(self):
        """Test with empty cell list."""
        result = calculate_elevation_stats([])
        assert result["elevation_min_m"] == 0.0
        assert result["elevation_max_m"] == 0.0
        assert result["elevation_mean_m"] == 0.0

    def test_weighted_mean(self):
        """Test that mean is weighted by area."""
        cells = [
            FlowCell(
                id=1,
                x=0,
                y=0,
                elevation=100.0,
                flow_accumulation=1,
                slope=1.0,
                downstream_id=None,
                cell_area=9000.0,
                is_stream=True,
            ),
            FlowCell(
                id=2,
                x=100,
                y=0,
                elevation=200.0,
                flow_accumulation=1,
                slope=1.0,
                downstream_id=1,
                cell_area=1000.0,
                is_stream=False,
            ),
        ]
        result = calculate_elevation_stats(cells)
        # Weighted mean: (100*9000 + 200*1000) / 10000 = 110
        assert result["elevation_mean_m"] == pytest.approx(110.0, rel=0.01)


# ===== TEST: calculate_mean_slope =====


class TestCalculateMeanSlope:
    """Tests for calculate_mean_slope function."""

    def test_slope_calculation(self, sample_cells: list[FlowCell]):
        """Test area-weighted mean slope."""
        result = calculate_mean_slope(sample_cells)
        # Slopes: 2, 3, 4, 5, 2.5 (%) -> mean = 3.3%
        # All cells have same area, so simple average = 16.5/5 = 3.3% = 0.033 m/m
        assert result == pytest.approx(0.033, rel=0.01)

    def test_conversion_to_m_per_m(self, sample_cells: list[FlowCell]):
        """Test that result is in m/m not percent."""
        result = calculate_mean_slope(sample_cells)
        # Should be small number (m/m), not percent
        assert result < 1.0

    def test_empty_cells(self):
        """Test with empty cell list."""
        result = calculate_mean_slope([])
        assert result == 0.0

    def test_cells_with_none_slope(self):
        """Test that None slopes are ignored."""
        cells = [
            FlowCell(
                id=1,
                x=0,
                y=0,
                elevation=100.0,
                flow_accumulation=1,
                slope=10.0,
                downstream_id=None,
                cell_area=1000.0,
                is_stream=True,
            ),
            FlowCell(
                id=2,
                x=100,
                y=0,
                elevation=110.0,
                flow_accumulation=1,
                slope=None,
                downstream_id=1,
                cell_area=1000.0,
                is_stream=False,
            ),
        ]
        result = calculate_mean_slope(cells)
        # Only cell 1 has valid slope: 10% = 0.1 m/m
        assert result == pytest.approx(0.1, rel=0.01)


# ===== TEST: find_main_stream =====


class TestFindMainStream:
    """Tests for find_main_stream function."""

    def test_stream_found(self, sample_cells: list[FlowCell], sample_outlet: FlowCell):
        """Test main stream detection."""
        length_km, slope = find_main_stream(sample_cells, sample_outlet)
        assert length_km > 0
        assert slope >= 0

    def test_empty_cells(self, sample_outlet: FlowCell):
        """Test with empty cell list."""
        length_km, slope = find_main_stream([], sample_outlet)
        assert length_km == 0.0
        assert slope == 0.0

    def test_longest_path(self, sample_cells: list[FlowCell], sample_outlet: FlowCell):
        """Test that longest path is found."""
        length_km, slope = find_main_stream(sample_cells, sample_outlet)
        # Longest path: 3 -> 2 -> 1 (200m) or 5 -> 2 -> 1 (~241m)
        # or 4 -> 1 (100m)
        # Path 3->2->1: distance = 100 + 100 = 200m = 0.2km
        # Path 5->2->1: distance = sqrt(100) + 100 = 100 + 100 = 200m
        assert length_km > 0.1  # At least 100m

    def test_positive_slope(
        self, sample_cells: list[FlowCell], sample_outlet: FlowCell
    ):
        """Test that slope is always non-negative."""
        _, slope = find_main_stream(sample_cells, sample_outlet)
        assert slope >= 0


# ===== TEST: build_morphometric_params =====


class TestBuildMorphometricParams:
    """Tests for build_morphometric_params function."""

    def test_returns_dict(
        self,
        sample_cells: list[FlowCell],
        sample_boundary: Polygon,
        sample_outlet: FlowCell,
    ):
        """Test that function returns proper dict."""
        result = build_morphometric_params(
            sample_cells, sample_boundary, sample_outlet, cn=72
        )
        assert isinstance(result, dict)

    def test_required_keys(
        self,
        sample_cells: list[FlowCell],
        sample_boundary: Polygon,
        sample_outlet: FlowCell,
    ):
        """Test that all required keys are present."""
        result = build_morphometric_params(sample_cells, sample_boundary, sample_outlet)
        required = [
            "area_km2",
            "perimeter_km",
            "length_km",
            "elevation_min_m",
            "elevation_max_m",
        ]
        for key in required:
            assert key in result

    def test_optional_keys(
        self,
        sample_cells: list[FlowCell],
        sample_boundary: Polygon,
        sample_outlet: FlowCell,
    ):
        """Test that optional keys are present."""
        result = build_morphometric_params(
            sample_cells, sample_boundary, sample_outlet, cn=72
        )
        optional = [
            "elevation_mean_m",
            "mean_slope_m_per_m",
            "channel_length_km",
            "channel_slope_m_per_m",
            "cn",
            "source",
            "crs",
        ]
        for key in optional:
            assert key in result

    def test_cn_passed_through(
        self,
        sample_cells: list[FlowCell],
        sample_boundary: Polygon,
        sample_outlet: FlowCell,
    ):
        """Test that CN is passed through."""
        result = build_morphometric_params(
            sample_cells, sample_boundary, sample_outlet, cn=72
        )
        assert result["cn"] == 72

    def test_source_and_crs(
        self,
        sample_cells: list[FlowCell],
        sample_boundary: Polygon,
        sample_outlet: FlowCell,
    ):
        """Test that source and crs are set correctly."""
        result = build_morphometric_params(sample_cells, sample_boundary, sample_outlet)
        assert result["source"] == "Hydrograf"
        assert result["crs"] == "EPSG:2180"

    def test_area_calculation(
        self,
        sample_cells: list[FlowCell],
        sample_boundary: Polygon,
        sample_outlet: FlowCell,
    ):
        """Test area calculation."""
        result = build_morphometric_params(sample_cells, sample_boundary, sample_outlet)
        # 5 cells * 10000 m² = 50000 m² = 0.05 km²
        assert result["area_km2"] == pytest.approx(0.05, rel=0.01)

    def test_hydrolog_compatibility(
        self,
        sample_cells: list[FlowCell],
        sample_boundary: Polygon,
        sample_outlet: FlowCell,
    ):
        """Test compatibility with Hydrolog's WatershedParameters."""
        result = build_morphometric_params(
            sample_cells, sample_boundary, sample_outlet, cn=72
        )

        # This should not raise
        from hydrolog.morphometry import WatershedParameters

        wp = WatershedParameters.from_dict(result)

        assert wp.area_km2 == result["area_km2"]
        assert wp.cn == result["cn"]
        assert wp.source == result["source"]


# ===== TEST: calculate_shape_indices =====


class TestCalculateShapeIndices:
    """Tests for calculate_shape_indices function."""

    def test_circle_shape(self):
        """Circle: Kc≈1, Rc≈1, Re≈1."""
        import math

        area = 10.0  # km2
        radius = math.sqrt(area / math.pi)  # km
        perimeter = 2 * math.pi * radius
        # For circle, length = diameter
        length = 2 * radius

        result = calculate_shape_indices(area, perimeter, length)

        assert result["compactness_coefficient"] == pytest.approx(
            1.0, abs=0.01
        )
        assert result["circularity_ratio"] == pytest.approx(
            1.0, abs=0.01
        )
        assert result["elongation_ratio"] == pytest.approx(
            1.0, abs=0.01
        )

    def test_elongated_rectangle(self):
        """Elongated rectangle: Kc > 1, Rc < 1."""
        # 10 km x 1 km rectangle
        area = 10.0  # km2
        perimeter = 2 * (10 + 1)  # 22 km
        length = 10.0  # km

        result = calculate_shape_indices(area, perimeter, length)

        assert result["compactness_coefficient"] > 1.0
        assert result["circularity_ratio"] < 1.0
        assert result["form_factor"] == pytest.approx(0.1, abs=0.01)
        assert result["mean_width_km"] == pytest.approx(1.0, abs=0.01)

    def test_returns_all_keys(self):
        """All expected keys are present."""
        result = calculate_shape_indices(10.0, 15.0, 5.0)
        expected_keys = {
            "compactness_coefficient",
            "circularity_ratio",
            "elongation_ratio",
            "form_factor",
            "mean_width_km",
        }
        assert set(result.keys()) == expected_keys

    def test_zero_values_return_none(self):
        """Zero area/perimeter/length → all None."""
        result = calculate_shape_indices(0, 0, 0)
        assert all(v is None for v in result.values())

    def test_positive_values(self):
        """All shape indices are positive for valid input."""
        result = calculate_shape_indices(5.0, 12.0, 3.0)
        for key, value in result.items():
            assert value is not None
            assert value > 0, f"{key} should be positive"


# ===== TEST: calculate_relief_indices =====


class TestCalculateReliefIndices:
    """Tests for calculate_relief_indices function."""

    def test_basic_relief(self):
        """Known values produce expected relief indices."""
        elev_stats = {
            "elevation_min_m": 100.0,
            "elevation_max_m": 500.0,
            "elevation_mean_m": 300.0,
        }
        result = calculate_relief_indices(elev_stats, length_km=10.0)

        # Rh = (500-100) / (10*1000) = 0.04
        assert result["relief_ratio"] == pytest.approx(
            0.04, abs=0.001
        )
        # HI = (300-100) / (500-100) = 0.5
        assert result["hypsometric_integral"] == pytest.approx(
            0.5, abs=0.01
        )

    def test_hi_range(self):
        """HI should be between 0 and 1."""
        elev_stats = {
            "elevation_min_m": 50.0,
            "elevation_max_m": 200.0,
            "elevation_mean_m": 150.0,
        }
        result = calculate_relief_indices(elev_stats, length_km=5.0)

        assert 0 <= result["hypsometric_integral"] <= 1

    def test_flat_returns_none(self):
        """Zero relief → None values."""
        elev_stats = {
            "elevation_min_m": 100.0,
            "elevation_max_m": 100.0,
            "elevation_mean_m": 100.0,
        }
        result = calculate_relief_indices(elev_stats, length_km=5.0)

        assert result["relief_ratio"] is None
        assert result["hypsometric_integral"] is None

    def test_zero_length_returns_none(self):
        """Zero length → relief_ratio is None."""
        elev_stats = {
            "elevation_min_m": 100.0,
            "elevation_max_m": 500.0,
            "elevation_mean_m": 300.0,
        }
        result = calculate_relief_indices(elev_stats, length_km=0)

        assert result["relief_ratio"] is None


# ===== TEST: calculate_hypsometric_curve =====


class TestCalculateHypsometricCurve:
    """Tests for calculate_hypsometric_curve function."""

    @pytest.fixture
    def uniform_cells(self) -> list[FlowCell]:
        """Create cells with linearly distributed elevations."""
        cells = []
        for i in range(100):
            cells.append(
                FlowCell(
                    id=i + 1,
                    x=float(i),
                    y=0.0,
                    elevation=100.0 + i * 1.0,  # 100 to 199
                    flow_accumulation=1,
                    slope=5.0,
                    downstream_id=None if i == 0 else i,
                    cell_area=100.0,
                    is_stream=False,
                )
            )
        return cells

    def test_returns_list(self, uniform_cells):
        """Returns list of dicts."""
        result = calculate_hypsometric_curve(uniform_cells)
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(p, dict) for p in result)

    def test_monotonicity(self, uniform_cells):
        """Relative area decreases as relative height increases."""
        result = calculate_hypsometric_curve(uniform_cells)
        areas = [p["relative_area"] for p in result]
        # First point: rh=1.0, area=0 (nothing above max)
        # Last point: rh=0.0, area=1.0 (everything above min)
        assert areas[0] <= areas[-1]
        # Check monotonic non-decreasing from top to bottom
        for i in range(len(areas) - 1):
            assert areas[i] <= areas[i + 1]

    def test_boundary_values(self, uniform_cells):
        """First point rh=1.0 area≈0, last point rh=0.0 area=1.0."""
        result = calculate_hypsometric_curve(uniform_cells)
        # Top: relative_height=1.0, only max elevation cell above
        assert result[0]["relative_height"] == pytest.approx(1.0)
        assert result[0]["relative_area"] <= 0.02  # ~1 cell out of 100
        # Bottom: relative_height=0.0, all cells above minimum
        assert result[-1]["relative_height"] == pytest.approx(0.0)
        assert result[-1]["relative_area"] == pytest.approx(1.0)

    def test_values_in_0_1(self, uniform_cells):
        """All relative_height and relative_area in [0, 1]."""
        result = calculate_hypsometric_curve(uniform_cells)
        for p in result:
            assert 0 <= p["relative_height"] <= 1
            assert 0 <= p["relative_area"] <= 1

    def test_empty_cells(self):
        """Empty cell list returns empty curve."""
        result = calculate_hypsometric_curve([])
        assert result == []

    def test_custom_bins(self, uniform_cells):
        """Custom n_bins produces correct number of points."""
        result = calculate_hypsometric_curve(uniform_cells, n_bins=10)
        assert len(result) == 11  # n_bins + 1 edges

    def test_flat_watershed(self):
        """Flat watershed returns degenerate curve."""
        cells = [
            FlowCell(
                id=i + 1,
                x=float(i),
                y=0.0,
                elevation=100.0,
                flow_accumulation=1,
                slope=0.0,
                downstream_id=None,
                cell_area=100.0,
                is_stream=False,
            )
            for i in range(10)
        ]
        result = calculate_hypsometric_curve(cells)
        assert len(result) >= 2


# ===== TEST: calculate_drainage_indices =====


class TestCalculateDrainageIndices:
    """Tests for calculate_drainage_indices function."""

    def test_basic_drainage(self):
        """Known stream stats produce correct indices."""
        stream_stats = {
            "total_stream_length_km": 20.0,
            "n_segments": 10,
            "max_strahler_order": 3,
        }
        result = calculate_drainage_indices(
            stream_stats, area_km2=10.0, relief_m=400.0
        )

        # Dd = 20/10 = 2.0
        assert result["drainage_density_km_per_km2"] == pytest.approx(
            2.0, abs=0.01
        )
        # Fs = 10/10 = 1.0
        assert result["stream_frequency_per_km2"] == pytest.approx(
            1.0, abs=0.01
        )
        # Rn = (400/1000) * 2.0 = 0.8
        assert result["ruggedness_number"] == pytest.approx(
            0.8, abs=0.01
        )
        assert result["max_strahler_order"] == 3

    def test_zero_area_returns_none(self):
        """Zero area → all None values."""
        stream_stats = {
            "total_stream_length_km": 5.0,
            "n_segments": 3,
            "max_strahler_order": 1,
        }
        result = calculate_drainage_indices(
            stream_stats, area_km2=0, relief_m=100.0
        )
        assert all(v is None for v in result.values())

    def test_zero_relief_rn_none(self):
        """Zero relief → ruggedness_number is None."""
        stream_stats = {
            "total_stream_length_km": 10.0,
            "n_segments": 5,
            "max_strahler_order": 2,
        }
        result = calculate_drainage_indices(
            stream_stats, area_km2=5.0, relief_m=0
        )
        assert result["ruggedness_number"] is None
        # Other indices should still work
        assert result["drainage_density_km_per_km2"] is not None

    def test_returns_all_keys(self):
        """All expected keys are present."""
        stream_stats = {
            "total_stream_length_km": 10.0,
            "n_segments": 5,
            "max_strahler_order": 2,
        }
        result = calculate_drainage_indices(
            stream_stats, area_km2=5.0, relief_m=200.0
        )
        expected_keys = {
            "drainage_density_km_per_km2",
            "stream_frequency_per_km2",
            "ruggedness_number",
            "max_strahler_order",
        }
        assert set(result.keys()) == expected_keys
