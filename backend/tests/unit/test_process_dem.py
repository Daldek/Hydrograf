"""
Unit tests for DEM processing fixes: nodata hole filling, sink fixing,
and flow accumulation recomputation.
"""

import numpy as np
import pytest

from scripts.process_dem import (
    VALID_D8_SET,
    burn_streams_into_dem,
    compute_aspect,
    compute_strahler_order,
    compute_twi,
    fill_internal_nodata_holes,
    fix_internal_sinks,
    process_hydrology_pyflwdir,
    recompute_flow_accumulation,
)

NODATA = -9999.0


class TestFillInternalNodataHoles:
    """Tests for fill_internal_nodata_holes()."""

    def test_fills_single_hole(self):
        """Single nodata cell surrounded by valid values is filled."""
        dem = np.array(
            [
                [10.0, 10.0, 10.0],
                [10.0, NODATA, 10.0],
                [10.0, 10.0, 10.0],
            ]
        )
        result, count = fill_internal_nodata_holes(dem, NODATA)

        assert count == 1
        assert result[1, 1] != NODATA
        assert result[1, 1] == 10.0

    def test_preserves_boundary_nodata(self):
        """Nodata on corner/edge with few valid neighbors is not filled."""
        dem = np.array(
            [
                [NODATA, 10.0, 10.0, 10.0],
                [10.0, 10.0, 10.0, 10.0],
                [10.0, 10.0, 10.0, 10.0],
                [10.0, 10.0, 10.0, NODATA],
            ]
        )
        result, count = fill_internal_nodata_holes(dem, NODATA, min_valid_neighbors=5)

        # Corner cells have at most 3 neighbors — should NOT be filled
        assert result[0, 0] == NODATA
        assert result[3, 3] == NODATA
        assert count == 0

    def test_fills_with_average(self):
        """Filled value equals the mean of valid neighbors."""
        dem = np.array(
            [
                [10.0, 20.0, 30.0],
                [10.0, NODATA, 30.0],
                [10.0, 20.0, 30.0],
            ]
        )
        result, count = fill_internal_nodata_holes(dem, NODATA)

        assert count == 1
        expected = np.mean([10.0, 20.0, 30.0, 10.0, 30.0, 10.0, 20.0, 30.0])
        assert abs(result[1, 1] - expected) < 0.01

    def test_no_holes_unchanged(self):
        """DEM without nodata holes is returned unchanged."""
        dem = np.array(
            [
                [10.0, 20.0, 30.0],
                [10.0, 20.0, 30.0],
                [10.0, 20.0, 30.0],
            ]
        )
        result, count = fill_internal_nodata_holes(dem, NODATA)

        assert count == 0
        np.testing.assert_array_equal(result, dem)

    def test_large_nodata_not_filled(self):
        """Large block of nodata — center cells should NOT be filled."""
        dem = np.full((7, 7), NODATA)
        # Only the border is valid
        dem[0, :] = 10.0
        dem[-1, :] = 10.0
        dem[:, 0] = 10.0
        dem[:, -1] = 10.0

        result, count = fill_internal_nodata_holes(dem, NODATA, min_valid_neighbors=5)

        # Center cell (3,3) has 0 valid neighbors initially — should stay nodata
        assert result[3, 3] == NODATA

    def test_iterative_filling(self):
        """Two adjacent holes are filled across iterations."""
        dem = np.array(
            [
                [10.0, 10.0, 10.0, 10.0, 10.0],
                [10.0, 10.0, 10.0, 10.0, 10.0],
                [10.0, 10.0, NODATA, NODATA, 10.0],
                [10.0, 10.0, 10.0, 10.0, 10.0],
                [10.0, 10.0, 10.0, 10.0, 10.0],
            ]
        )
        result, count = fill_internal_nodata_holes(
            dem, NODATA, min_valid_neighbors=5, max_iterations=3
        )

        # Both holes should be filled
        # (first has 6 valid, second has 5 valid + 1st gets filled)
        assert result[2, 2] != NODATA
        assert result[2, 3] != NODATA
        assert count >= 1  # At least one filled


class TestFixInternalSinks:
    """Tests for fix_internal_sinks()."""

    def test_fixes_by_steepest_descent(self):
        """Internal sink is fixed to flow toward steepest downhill neighbor."""
        # 3x3 grid: center is a sink (fdir=0), lower neighbor is lower
        dem = np.array(
            [
                [100.0, 100.0, 100.0],
                [100.0, 50.0, 100.0],
                [100.0, 30.0, 100.0],
            ]
        )
        inflated = dem.copy()
        fdir = np.array(
            [
                [4, 4, 4],
                [0, 0, 16],  # center is sink
                [0, 0, 16],
            ],
            dtype=np.int16,
        )
        acc = np.array(
            [
                [1, 1, 1],
                [1, 1, 1],
                [1, 2, 1],
            ],
            dtype=np.int32,
        )

        fdir_fixed, acc_fixed, diag = fix_internal_sinks(
            fdir, acc, inflated, dem, NODATA
        )

        # Center should now point S (dir 4) — steepest descent to (2,1)=30
        assert fdir_fixed[1, 1] == 4
        assert diag["total_fixed"] >= 1
        assert diag["by_strategy"]["steepest"] >= 1

    def test_no_sinks_unchanged(self):
        """No internal sinks — arrays returned unchanged."""
        dem = np.array(
            [
                [100.0, 100.0, 100.0],
                [100.0, 50.0, 100.0],
                [100.0, 100.0, 100.0],
            ]
        )
        fdir = np.array(
            [
                [4, 4, 4],
                [1, 4, 16],
                [0, 0, 0],  # edge sinks are OK (outlets)
            ],
            dtype=np.int16,
        )
        acc = np.ones((3, 3), dtype=np.int32)

        fdir_fixed, acc_fixed, diag = fix_internal_sinks(fdir, acc, dem, dem, NODATA)

        assert diag["total_fixed"] == 0
        np.testing.assert_array_equal(fdir_fixed, fdir)

    def test_edge_sinks_not_fixed(self):
        """Sinks on raster edge are not modified (valid outlets)."""
        dem = np.array(
            [
                [100.0, 100.0, 100.0],
                [100.0, 50.0, 100.0],
                [100.0, 100.0, 100.0],
            ]
        )
        fdir = np.array(
            [
                [0, 4, 0],
                [1, 4, 16],
                [0, 0, 0],
            ],
            dtype=np.int16,
        )
        acc = np.ones((3, 3), dtype=np.int32)

        fdir_fixed, _, diag = fix_internal_sinks(fdir, acc, dem, dem, NODATA)

        # All edge cells with fdir=0 should remain 0
        assert fdir_fixed[0, 0] == 0
        assert fdir_fixed[0, 2] == 0
        assert fdir_fixed[2, 0] == 0
        assert fdir_fixed[2, 1] == 0
        assert fdir_fixed[2, 2] == 0
        assert diag["total_fixed"] == 0

    def test_recomputes_accumulation(self):
        """Flow accumulation is recomputed after sink fixes."""
        # 5x5 grid with a sink at (2,2) blocking flow
        dem = np.full((5, 5), 100.0)
        dem[2, 2] = 50.0
        dem[3, 2] = 30.0
        dem[4, 2] = 10.0

        # All cells point south except center which is a sink
        fdir = np.full((5, 5), 4, dtype=np.int16)
        fdir[4, :] = 0  # bottom edge = outlets
        fdir[2, 2] = 0  # sink

        acc = np.ones((5, 5), dtype=np.int32)
        inflated = dem.copy()

        fdir_fixed, acc_fixed, diag = fix_internal_sinks(
            fdir, acc, inflated, dem, NODATA
        )

        # Sink should be fixed
        assert fdir_fixed[2, 2] != 0
        assert diag["total_fixed"] == 1
        # Accumulation should be recomputed (downstream of fixed sink gets more flow)
        assert acc_fixed[3, 2] > 1

    def test_flat_area_uses_max_acc(self):
        """Flat area sink uses max accumulation strategy when no slope exists."""
        # All same elevation — no steepest descent possible
        dem = np.full((5, 5), 50.0)
        inflated = dem.copy()  # No micro-gradients either

        fdir = np.full((5, 5), 1, dtype=np.int16)  # all flow East
        fdir[4, :] = 0  # bottom edge
        fdir[:, 4] = 0  # right edge
        fdir[2, 2] = 0  # internal sink

        # Give east neighbor high accumulation
        acc = np.ones((5, 5), dtype=np.int32)
        acc[2, 3] = 100

        fdir_fixed, _, diag = fix_internal_sinks(fdir, acc, inflated, dem, NODATA)

        assert fdir_fixed[2, 2] != 0
        assert diag["total_fixed"] == 1
        # Should route toward the neighbor with max accumulation (east = direction 1)
        assert diag["by_strategy"]["max_acc"] >= 1

    def test_fixes_negative_fdir_values(self):
        """Cells with fdir=-1 or fdir=-2 (pysheds pit/flat markers) are fixed."""
        dem = np.array(
            [
                [100.0, 100.0, 100.0, 100.0, 100.0],
                [100.0, 50.0, 50.0, 50.0, 100.0],
                [100.0, 50.0, 50.0, 50.0, 100.0],
                [100.0, 30.0, 30.0, 30.0, 100.0],
                [100.0, 100.0, 100.0, 100.0, 100.0],
            ]
        )
        inflated = dem.copy()
        inflated[2, 2] = 50.1  # slight gradient to help steepest descent
        inflated[3, 2] = 29.9

        fdir = np.full((5, 5), 4, dtype=np.int16)  # all flow South
        fdir[4, :] = 0  # bottom edge = outlets
        fdir[2, 1] = -1  # pysheds pit marker
        fdir[2, 2] = -2  # pysheds unresolved flat marker

        acc = np.ones((5, 5), dtype=np.int32)

        fdir_fixed, _, diag = fix_internal_sinks(fdir, acc, inflated, dem, NODATA)

        # Both negative-fdir cells should be fixed to valid D8 directions
        assert fdir_fixed[2, 1] in {1, 2, 4, 8, 16, 32, 64, 128}
        assert fdir_fixed[2, 2] in {1, 2, 4, 8, 16, 32, 64, 128}
        assert diag["total_fixed"] >= 2

    def test_edge_negative_fdir_not_fixed(self):
        """Negative fdir on raster edge is not modified (valid outlet)."""
        dem = np.full((3, 3), 50.0)
        fdir = np.array(
            [
                [-1, 4, -2],
                [1, 4, 16],
                [-1, -2, 0],
            ],
            dtype=np.int16,
        )
        acc = np.ones((3, 3), dtype=np.int32)

        fdir_fixed, _, diag = fix_internal_sinks(fdir, acc, dem, dem, NODATA)

        # All edge cells should remain unchanged
        assert fdir_fixed[0, 0] == -1
        assert fdir_fixed[0, 2] == -2
        assert fdir_fixed[2, 0] == -1
        assert fdir_fixed[2, 1] == -2
        assert fdir_fixed[2, 2] == 0
        assert diag["total_fixed"] == 0


class TestRecomputeFlowAccumulation:
    """Tests for recompute_flow_accumulation()."""

    def test_simple_chain(self):
        """3 cells E→E→outlet: accumulation = 1, 2, 3."""
        dem = np.array([[10.0, 10.0, 10.0]])
        fdir = np.array([[1, 1, 0]], dtype=np.int16)  # E, E, outlet

        acc = recompute_flow_accumulation(fdir, dem, NODATA)

        assert acc[0, 0] == 1
        assert acc[0, 1] == 2
        assert acc[0, 2] == 3

    def test_nodata_excluded(self):
        """Nodata cell has acc=0 and doesn't contribute to downstream."""
        dem = np.array([[10.0, NODATA, 10.0]])
        fdir = np.array([[1, 1, 0]], dtype=np.int16)

        acc = recompute_flow_accumulation(fdir, dem, NODATA)

        assert acc[0, 0] == 1  # valid, no upstream
        assert acc[0, 1] == 0  # nodata
        assert acc[0, 2] == 1  # valid, but no valid upstream (nodata blocks)

    def test_converging_flow(self):
        """Two cells converging to one: downstream acc = 3."""
        dem = np.array(
            [
                [10.0, 10.0],
                [10.0, 10.0],
            ]
        )
        # (0,0)→S, (0,1)→SW, both flow to (1,0). (1,0)→E to (1,1)
        fdir = np.array(
            [
                [4, 8],
                [1, 0],
            ],
            dtype=np.int16,
        )

        acc = recompute_flow_accumulation(fdir, dem, NODATA)

        assert acc[0, 0] == 1  # headwater
        assert acc[0, 1] == 1  # headwater
        assert acc[1, 0] == 3  # self + 2 upstream
        assert acc[1, 1] == 4  # self + 3 from (1,0)


class TestProcessHydrologyPyflwdir:
    """Integration tests for process_hydrology_pyflwdir()."""

    @pytest.fixture()
    def synthetic_dem_10x10(self):
        """Create a 10x10 DEM sloping SE with a small depression."""
        dem = np.zeros((10, 10), dtype=np.float64)
        for i in range(10):
            for j in range(10):
                # Elevation decreases toward SE corner
                dem[i, j] = 200.0 - i * 10.0 - j * 5.0
        # Add a small depression at (5, 5)
        dem[5, 5] = dem[5, 5] - 20.0
        # Add nodata on one corner
        dem[0, 0] = NODATA

        metadata = {
            "ncols": 10,
            "nrows": 10,
            "xllcorner": 500000.0,
            "yllcorner": 300000.0,
            "cellsize": 5.0,
            "nodata_value": NODATA,
        }
        return dem, metadata

    def test_returns_correct_shapes(self, synthetic_dem_10x10):
        """Output arrays have same shape as input DEM."""
        dem, metadata = synthetic_dem_10x10
        filled, fdir, acc, _d8 = process_hydrology_pyflwdir(dem, metadata)

        assert filled.shape == dem.shape
        assert fdir.shape == dem.shape
        assert acc.shape == dem.shape

    def test_fdir_contains_only_valid_d8(self, synthetic_dem_10x10):
        """All internal valid cells have D8 flow direction from VALID_D8_SET."""
        dem, metadata = synthetic_dem_10x10
        filled, fdir, _, _d8 = process_hydrology_pyflwdir(dem, metadata)

        valid = filled != NODATA
        edge_mask = np.zeros_like(valid)
        edge_mask[0, :] = True
        edge_mask[-1, :] = True
        edge_mask[:, 0] = True
        edge_mask[:, -1] = True

        internal_valid = valid & ~edge_mask
        internal_fdir = fdir[internal_valid]

        # Every internal valid cell must have a valid D8 direction
        assert all(d in VALID_D8_SET for d in internal_fdir), (
            f"Invalid fdir values found: {set(internal_fdir) - VALID_D8_SET}"
        )

    def test_acc_positive_for_valid_cells(self, synthetic_dem_10x10):
        """Flow accumulation >= 1 for all valid cells."""
        dem, metadata = synthetic_dem_10x10
        filled, _, acc, _d8 = process_hydrology_pyflwdir(dem, metadata)

        valid = filled != NODATA
        assert np.all(acc[valid] >= 1)

    def test_nodata_preserved(self, synthetic_dem_10x10):
        """Nodata cells in input remain nodata in filled DEM."""
        dem, metadata = synthetic_dem_10x10
        filled, _, _, _d8 = process_hydrology_pyflwdir(dem, metadata)

        assert filled[0, 0] == NODATA

    def test_depression_filled(self, synthetic_dem_10x10):
        """The depression at (5,5) is filled (elevation raised)."""
        dem, metadata = synthetic_dem_10x10
        filled, _, _, _d8 = process_hydrology_pyflwdir(dem, metadata)

        # Filled DEM should have the depression raised
        assert filled[5, 5] >= dem[5, 5]

    def test_no_internal_sinks(self, synthetic_dem_10x10):
        """No internal sinks remain after processing."""
        dem, metadata = synthetic_dem_10x10
        filled, fdir, _, _d8 = process_hydrology_pyflwdir(dem, metadata)

        valid = filled != NODATA
        edge_mask = np.zeros_like(valid)
        edge_mask[0, :] = True
        edge_mask[-1, :] = True
        edge_mask[:, 0] = True
        edge_mask[:, -1] = True

        is_valid_d8 = np.isin(fdir, list(VALID_D8_SET))
        internal_sinks = ~is_valid_d8 & valid & ~edge_mask

        assert int(np.sum(internal_sinks)) == 0


class TestBurnStreamsIntoDem:
    """Tests for burn_streams_into_dem()."""

    @pytest.fixture()
    def sample_dem_with_transform(self):
        """10x10 DEM with Affine transform in EPSG:2180."""
        from rasterio.transform import from_bounds

        dem = np.full((10, 10), 100.0)
        # Add some variation
        dem[5, :] = 90.0
        dem[0, 0] = NODATA

        xmin, ymin = 500000.0, 300000.0
        cellsize = 5.0
        xmax = xmin + 10 * cellsize
        ymax = ymin + 10 * cellsize
        transform = from_bounds(xmin, ymin, xmax, ymax, 10, 10)

        return dem, transform

    @pytest.fixture()
    def tmp_streams_gpkg(self, tmp_path, sample_dem_with_transform):
        """Create a temporary GeoPackage with a LineString crossing the DEM."""
        import geopandas as gpd
        from shapely.geometry import LineString

        _, transform = sample_dem_with_transform
        # Line across middle of DEM (y = 300025, from x=500000 to x=500050)
        xmin = transform.c
        ymin = transform.f + 10 * transform.e
        xmax = xmin + 10 * transform.a
        ymid = (ymin + transform.f) / 2

        line = LineString([(xmin, ymid), (xmax, ymid)])
        gdf = gpd.GeoDataFrame({"name": ["Glowna"]}, geometry=[line], crs="EPSG:2180")
        path = tmp_path / "streams.gpkg"
        gdf.to_file(path, driver="GPKG")
        return path

    @pytest.fixture()
    def tmp_streams_outside_gpkg(self, tmp_path):
        """Create a GeoPackage with a stream outside the DEM extent."""
        import geopandas as gpd
        from shapely.geometry import LineString

        line = LineString([(600000, 400000), (600100, 400100)])
        gdf = gpd.GeoDataFrame({"name": ["Daleka"]}, geometry=[line], crs="EPSG:2180")
        path = tmp_path / "streams_outside.gpkg"
        gdf.to_file(path, driver="GPKG")
        return path

    @pytest.fixture()
    def tmp_empty_gpkg(self, tmp_path):
        """Create an empty GeoPackage."""
        import geopandas as gpd

        gdf = gpd.GeoDataFrame({"name": []}, geometry=[], crs="EPSG:2180")
        gdf = gdf.set_geometry(gpd.GeoSeries([], crs="EPSG:2180"))
        path = tmp_path / "empty.gpkg"
        gdf.to_file(path, driver="GPKG")
        return path

    def test_burns_stream_cells(self, sample_dem_with_transform, tmp_streams_gpkg):
        """Stream cells are lowered by burn_depth_m."""
        dem, transform = sample_dem_with_transform
        original = dem.copy()

        burned, diag = burn_streams_into_dem(
            dem, transform, tmp_streams_gpkg, burn_depth_m=5.0, nodata=NODATA
        )

        assert diag["cells_burned"] > 0
        # Burned cells should be lower than original
        lowered = burned < original
        assert np.any(lowered)
        # Non-burned valid cells should be unchanged
        not_lowered_valid = ~lowered & (original != NODATA)
        np.testing.assert_array_equal(
            burned[not_lowered_valid], original[not_lowered_valid]
        )

    def test_preserves_nodata(self, sample_dem_with_transform, tmp_streams_gpkg):
        """Nodata cells under a stream are not modified."""
        dem, transform = sample_dem_with_transform
        # Ensure (0,0) is nodata
        assert dem[0, 0] == NODATA

        burned, _ = burn_streams_into_dem(
            dem, transform, tmp_streams_gpkg, burn_depth_m=5.0, nodata=NODATA
        )

        assert burned[0, 0] == NODATA

    def test_no_intersection_returns_unchanged(
        self, sample_dem_with_transform, tmp_streams_outside_gpkg
    ):
        """Stream outside DEM extent — DEM unchanged, cells_burned=0."""
        dem, transform = sample_dem_with_transform
        original = dem.copy()

        burned, diag = burn_streams_into_dem(
            dem, transform, tmp_streams_outside_gpkg, burn_depth_m=5.0, nodata=NODATA
        )

        assert diag["cells_burned"] == 0
        np.testing.assert_array_equal(burned, original)

    def test_custom_burn_depth(self, sample_dem_with_transform, tmp_streams_gpkg):
        """Custom burn depth is applied correctly."""
        dem, transform = sample_dem_with_transform
        original = dem.copy()

        burned, diag = burn_streams_into_dem(
            dem, transform, tmp_streams_gpkg, burn_depth_m=10.0, nodata=NODATA
        )

        assert diag["cells_burned"] > 0
        # Check that burned cells are exactly 10m lower
        lowered_mask = burned < original
        diffs = original[lowered_mask] - burned[lowered_mask]
        np.testing.assert_allclose(diffs, 10.0)

    def test_diagnostics_correct(self, sample_dem_with_transform, tmp_streams_gpkg):
        """Diagnostics dict contains correct keys and values."""
        dem, transform = sample_dem_with_transform

        _, diag = burn_streams_into_dem(
            dem, transform, tmp_streams_gpkg, burn_depth_m=5.0, nodata=NODATA
        )

        assert "cells_burned" in diag
        assert "streams_loaded" in diag
        assert "streams_in_extent" in diag
        assert diag["streams_loaded"] == 1
        assert diag["streams_in_extent"] >= 1
        assert diag["cells_burned"] > 0

    def test_empty_geodataframe(self, sample_dem_with_transform, tmp_empty_gpkg):
        """Empty GeoPackage — DEM unchanged."""
        dem, transform = sample_dem_with_transform
        original = dem.copy()

        burned, diag = burn_streams_into_dem(
            dem, transform, tmp_empty_gpkg, burn_depth_m=5.0, nodata=NODATA
        )

        assert diag["cells_burned"] == 0
        assert diag["streams_loaded"] == 0
        np.testing.assert_array_equal(burned, original)


class TestComputeAspect:
    """Tests for compute_aspect()."""

    def test_north_facing_slope(self):
        """Slope descending northward (row 0 is lower) → aspect ≈ 0° (N)."""
        # Row 0 = top = lower elevation, rows increase = higher elevation
        # In raster convention: row 0 is top (north), so elevation increasing
        # southward means the slope faces north.
        dem = np.array(
            [
                [10.0, 10.0, 10.0],
                [20.0, 20.0, 20.0],
                [30.0, 30.0, 30.0],
            ]
        )
        aspect = compute_aspect(dem, cellsize=1.0, nodata=NODATA)
        # Center cell should face north (~0° or ~360°)
        center = aspect[1, 1]
        assert center >= 0  # not flat
        assert center < 45 or center > 315  # roughly north

    def test_east_facing_slope(self):
        """Slope descending eastward → aspect ≈ 90° (E)."""
        dem = np.array(
            [
                [30.0, 20.0, 10.0],
                [30.0, 20.0, 10.0],
                [30.0, 20.0, 10.0],
            ]
        )
        aspect = compute_aspect(dem, cellsize=1.0, nodata=NODATA)
        center = aspect[1, 1]
        assert center >= 0
        assert 45 < center < 135  # roughly east

    def test_south_facing_slope(self):
        """Slope descending southward → aspect ≈ 180° (S)."""
        dem = np.array(
            [
                [30.0, 30.0, 30.0],
                [20.0, 20.0, 20.0],
                [10.0, 10.0, 10.0],
            ]
        )
        aspect = compute_aspect(dem, cellsize=1.0, nodata=NODATA)
        center = aspect[1, 1]
        assert center >= 0
        assert 135 < center < 225  # roughly south

    def test_west_facing_slope(self):
        """Slope descending westward → aspect ≈ 270° (W)."""
        dem = np.array(
            [
                [10.0, 20.0, 30.0],
                [10.0, 20.0, 30.0],
                [10.0, 20.0, 30.0],
            ]
        )
        aspect = compute_aspect(dem, cellsize=1.0, nodata=NODATA)
        center = aspect[1, 1]
        assert center >= 0
        assert 225 < center < 315  # roughly west

    def test_flat_area_negative(self):
        """Flat DEM → aspect = -1 for all cells."""
        dem = np.full((5, 5), 100.0)
        aspect = compute_aspect(dem, cellsize=1.0, nodata=NODATA)
        # All interior cells should be flat (-1)
        assert aspect[2, 2] == -1.0

    def test_nodata_handling(self):
        """Nodata cells get aspect = -1."""
        dem = np.array(
            [
                [NODATA, 20.0, 30.0],
                [10.0, 20.0, 30.0],
                [10.0, 20.0, 30.0],
            ]
        )
        aspect = compute_aspect(dem, cellsize=1.0, nodata=NODATA)
        assert aspect[0, 0] == -1.0

    def test_output_range_0_360(self):
        """All valid aspect values are in [0, 360) range."""
        dem = np.zeros((10, 10))
        for i in range(10):
            for j in range(10):
                dem[i, j] = 200.0 - i * 10.0 - j * 5.0
        aspect = compute_aspect(dem, cellsize=1.0, nodata=NODATA)
        valid = aspect[aspect >= 0]
        assert np.all(valid >= 0)
        assert np.all(valid < 360)


class TestComputeTwi:
    """Tests for compute_twi()."""

    def test_flat_dem_uniform_twi(self):
        """Flat DEM with uniform accumulation → uniform TWI."""
        acc = np.full((5, 5), 10, dtype=np.int32)
        slope = np.full((5, 5), 5.0)  # 5% slope
        cellsize = 1.0
        twi = compute_twi(acc, slope, cellsize, nodata_acc=0)
        # All cells should have same TWI
        assert np.std(twi[twi > -9999]) < 0.01

    def test_low_slope_high_twi(self):
        """Lower slope → higher TWI (wetter)."""
        acc = np.full((3, 3), 100, dtype=np.int32)
        slope_low = np.full((3, 3), 1.0)  # 1%
        slope_high = np.full((3, 3), 20.0)  # 20%
        cellsize = 1.0

        twi_low = compute_twi(acc, slope_low, cellsize, nodata_acc=0)
        twi_high = compute_twi(acc, slope_high, cellsize, nodata_acc=0)

        assert twi_low[1, 1] > twi_high[1, 1]

    def test_high_accumulation_high_twi(self):
        """Higher accumulation → higher TWI (wetter)."""
        acc_low = np.full((3, 3), 10, dtype=np.int32)
        acc_high = np.full((3, 3), 1000, dtype=np.int32)
        slope = np.full((3, 3), 5.0)
        cellsize = 1.0

        twi_low = compute_twi(acc_low, slope, cellsize, nodata_acc=0)
        twi_high = compute_twi(acc_high, slope, cellsize, nodata_acc=0)

        assert twi_high[1, 1] > twi_low[1, 1]

    def test_zero_slope_clamped(self):
        """Zero slope is clamped to min value (no division by zero)."""
        acc = np.full((3, 3), 10, dtype=np.int32)
        slope = np.full((3, 3), 0.0)  # flat
        cellsize = 1.0
        twi = compute_twi(acc, slope, cellsize, nodata_acc=0)
        # Should not contain inf or nan
        assert np.all(np.isfinite(twi[twi > -9999]))

    def test_nodata_accumulation_excluded(self):
        """Cells with acc=0 (nodata) get TWI nodata value."""
        acc = np.array(
            [
                [10, 10, 10],
                [10, 0, 10],
                [10, 10, 10],
            ],
            dtype=np.int32,
        )
        slope = np.full((3, 3), 5.0)
        cellsize = 1.0
        twi = compute_twi(acc, slope, cellsize, nodata_acc=0)
        assert twi[1, 1] == -9999.0

    def test_positive_twi_values(self):
        """Typical TWI values are positive for reasonable inputs."""
        acc = np.full((5, 5), 100, dtype=np.int32)
        slope = np.full((5, 5), 5.0)
        cellsize = 5.0
        twi = compute_twi(acc, slope, cellsize, nodata_acc=0)
        valid = twi[twi > -9999]
        assert np.all(valid > 0)


class TestComputeStrahlerOrder:
    """Tests for compute_strahler_order()."""

    @pytest.fixture()
    def v_shaped_dem_20x20(self):
        """
        Create 20x20 V-shaped DEM (valley running south down center).

        Elevation profile: higher at edges (east/west), lowest at center column,
        decreasing southward. This creates two ridge-to-valley streams that merge.
        """
        dem = np.zeros((20, 20), dtype=np.float64)
        for i in range(20):
            for j in range(20):
                # V-shape across columns: center (col 10) is low
                dist_from_center = abs(j - 10)
                # Decrease south (row increases)
                dem[i, j] = 200.0 + dist_from_center * 10.0 - i * 5.0
        # Ensure no negative
        dem = np.maximum(dem, 1.0)

        metadata = {
            "ncols": 20,
            "nrows": 20,
            "xllcorner": 500000.0,
            "yllcorner": 300000.0,
            "cellsize": 5.0,
            "nodata_value": NODATA,
        }
        return dem, metadata

    def test_returns_correct_shape(self, v_shaped_dem_20x20):
        """Output array has same shape as input DEM."""
        dem, metadata = v_shaped_dem_20x20
        strahler = compute_strahler_order(dem, metadata, stream_threshold=5)
        assert strahler.shape == dem.shape

    def test_non_stream_cells_zero(self, v_shaped_dem_20x20):
        """Non-stream cells have Strahler order 0."""
        dem, metadata = v_shaped_dem_20x20
        strahler = compute_strahler_order(dem, metadata, stream_threshold=50)
        # Many cells should be 0 (non-stream)
        assert np.sum(strahler == 0) > 0

    def test_headwaters_order_one(self, v_shaped_dem_20x20):
        """Headwater stream cells have Strahler order 1."""
        dem, metadata = v_shaped_dem_20x20
        strahler = compute_strahler_order(dem, metadata, stream_threshold=5)
        # At least some cells should have order 1
        assert np.any(strahler == 1)

    def test_max_order_increases_with_network(self, v_shaped_dem_20x20):
        """Lower threshold → more stream cells → potentially higher max order."""
        dem, metadata = v_shaped_dem_20x20
        strahler_low = compute_strahler_order(dem, metadata, stream_threshold=3)
        strahler_high = compute_strahler_order(dem, metadata, stream_threshold=100)

        max_low = int(strahler_low.max())
        max_high = int(strahler_high.max()) if np.any(strahler_high > 0) else 0

        # More stream cells should give same or higher max order
        assert max_low >= max_high

    def test_output_dtype_uint8(self, v_shaped_dem_20x20):
        """Output array is uint8."""
        dem, metadata = v_shaped_dem_20x20
        strahler = compute_strahler_order(dem, metadata, stream_threshold=5)
        assert strahler.dtype == np.uint8
