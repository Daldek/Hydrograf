"""Tests for endorheic lake classification and drain point injection."""

import tempfile
from pathlib import Path

import geopandas as gpd
import numpy as np
from affine import Affine
from shapely.geometry import LineString, Polygon

from core.hydrology import (
    _add_drain_point,
    _sample_dem_at_point,
    classify_endorheic_lakes,
    process_hydrology_pyflwdir,
)

# Common test fixtures
NODATA = -9999.0
CELLSIZE = 1.0
# Simple transform: 1m cells, origin at (500000, 600100), y decreasing
TRANSFORM = Affine(CELLSIZE, 0, 500000.0, 0, -CELLSIZE, 600100.0)


def _make_dem(nrows=100, ncols=100, base_elev=100.0):
    """Create a simple sloped DEM (higher in NW, lower in SE)."""
    dem = np.full((nrows, ncols), base_elev, dtype=np.float64)
    for r in range(nrows):
        for c in range(ncols):
            dem[r, c] = base_elev - r * 0.1 - c * 0.1
    return dem


def _make_metadata(dem, transform=TRANSFORM):
    """Create metadata dict for a DEM."""
    nrows, ncols = dem.shape
    return {
        "ncols": ncols,
        "nrows": nrows,
        "cellsize": abs(transform.a),
        "nodata_value": NODATA,
        "xllcorner": transform.c,
        "yllcorner": transform.f + nrows * transform.e,
        "transform": transform,
    }


def _create_test_gpkg(lakes_wkt, streams_wkt, tmp_dir):
    """Create a test GeoPackage with water body and stream layers.

    Parameters
    ----------
    lakes_wkt : list of Polygon geometries
    streams_wkt : list of LineString geometries
    tmp_dir : str
        Temporary directory path

    Returns
    -------
    Path to GeoPackage
    """
    gpkg_path = Path(tmp_dir) / "test.gpkg"

    if lakes_wkt:
        lakes_gdf = gpd.GeoDataFrame({"geometry": lakes_wkt}, crs="EPSG:2180")
        lakes_gdf.to_file(gpkg_path, layer="OT_PTWP_A", driver="GPKG")

    if streams_wkt:
        streams_gdf = gpd.GeoDataFrame({"geometry": streams_wkt}, crs="EPSG:2180")
        if gpkg_path.exists():
            streams_gdf.to_file(gpkg_path, layer="OT_SWRS_L", driver="GPKG", mode="a")
        else:
            streams_gdf.to_file(gpkg_path, layer="OT_SWRS_L", driver="GPKG")

    return gpkg_path


# ---- Tests for _sample_dem_at_point ----


class TestSampleDemAtPoint:
    """Tests for _sample_dem_at_point helper."""

    def test_sample_valid_cell(self):
        dem = np.array([[100.0, 200.0], [300.0, 400.0]])
        transform = Affine(1, 0, 0.0, 0, -1, 2.0)
        # Point (0.5, 1.5) → row=0, col=0
        result = _sample_dem_at_point(dem, transform, 0.5, 1.5, NODATA)
        assert result == 100.0

    def test_sample_nodata_searches_neighbors(self):
        dem = np.array(
            [
                [100.0, 200.0, 300.0],
                [400.0, NODATA, 600.0],
                [700.0, 800.0, 900.0],
            ]
        )
        transform = Affine(1, 0, 0.0, 0, -1, 3.0)
        # Point (1.5, 1.5) → row=1, col=1 which is NODATA
        result = _sample_dem_at_point(dem, transform, 1.5, 1.5, NODATA)
        assert result is not None
        # Should find nearest valid neighbor
        assert result in [100.0, 200.0, 300.0, 400.0, 600.0, 700.0, 800.0, 900.0]

    def test_sample_all_nodata_returns_none(self):
        dem = np.full((3, 3), NODATA)
        transform = Affine(1, 0, 0.0, 0, -1, 3.0)
        result = _sample_dem_at_point(dem, transform, 1.5, 1.5, NODATA)
        assert result is None

    def test_sample_out_of_bounds_searches_neighbors(self):
        dem = np.array([[100.0, 200.0], [300.0, 400.0]])
        transform = Affine(1, 0, 0.0, 0, -1, 2.0)
        # Point far outside → row/col out of bounds
        result = _sample_dem_at_point(dem, transform, -10.0, 10.0, NODATA)
        assert result is None


# ---- Tests for classify_endorheic_lakes ----


class TestClassifyEndorheicLakes:
    """Tests for classify_endorheic_lakes."""

    def test_lake_no_streams_is_endorheic(self):
        """Lake with no touching streams → endorheic."""
        dem = _make_dem()
        # Lake polygon inside DEM extent
        lake = Polygon(
            [
                (500040, 600060),
                (500060, 600060),
                (500060, 600040),
                (500040, 600040),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            gpkg = _create_test_gpkg([lake], [], tmp)
            drain_pts, diag = classify_endorheic_lakes(dem, TRANSFORM, gpkg, NODATA)

        assert diag["total_lakes"] == 1
        assert diag["endorheic"] == 1
        assert diag["exorheic"] == 0
        assert len(drain_pts) == 1

    def test_lake_only_inflows_is_endorheic(self):
        """Lake with only inflow streams (far_elev > near_elev) → endorheic."""
        dem = _make_dem()
        lake = Polygon(
            [
                (500040, 600060),
                (500060, 600060),
                (500060, 600040),
                (500040, 600040),
            ]
        )
        # Stream flowing toward lake: start far and high, end near lake and low
        # Far point (500020, 600080) → row=20, col=20 → elev ~ 100-2-2=96
        # Near point (500040, 600060) → row=40, col=40 → elev ~ 100-4-4=92
        # far_elev (96) > near_elev (92) → inflow
        stream = LineString(
            [
                (500020, 600080),
                (500040, 600060),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            gpkg = _create_test_gpkg([lake], [stream], tmp)
            drain_pts, diag = classify_endorheic_lakes(dem, TRANSFORM, gpkg, NODATA)

        assert diag["endorheic"] == 1
        assert diag["exorheic"] == 0
        assert len(drain_pts) == 1

    def test_lake_with_outflow_is_exorheic(self):
        """Lake with outflow stream (far_elev < near_elev) → exorheic."""
        dem = _make_dem()
        lake = Polygon(
            [
                (500040, 600060),
                (500060, 600060),
                (500060, 600040),
                (500040, 600040),
            ]
        )
        # Stream flowing away from lake: start near lake and high, end far and low
        # Near point (500060, 600040) → row=60, col=60 → elev ~ 100-6-6=88
        # Far point (500080, 600020) → row=80, col=80 → elev ~ 100-8-8=84
        # far_elev (84) < near_elev (88) → outflow
        stream = LineString(
            [
                (500060, 600040),
                (500080, 600020),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            gpkg = _create_test_gpkg([lake], [stream], tmp)
            drain_pts, diag = classify_endorheic_lakes(dem, TRANSFORM, gpkg, NODATA)

        assert diag["exorheic"] == 1
        assert diag["endorheic"] == 0
        assert len(drain_pts) == 0

    def test_lake_mixed_inflow_outflow_is_exorheic(self):
        """Lake with both inflow and outflow → exorheic (has outflow)."""
        dem = _make_dem()
        lake = Polygon(
            [
                (500040, 600060),
                (500060, 600060),
                (500060, 600040),
                (500040, 600040),
            ]
        )
        # Inflow stream
        inflow = LineString([(500020, 600080), (500040, 600060)])
        # Outflow stream
        outflow = LineString([(500060, 600040), (500080, 600020)])

        with tempfile.TemporaryDirectory() as tmp:
            gpkg = _create_test_gpkg([lake], [inflow, outflow], tmp)
            drain_pts, diag = classify_endorheic_lakes(dem, TRANSFORM, gpkg, NODATA)

        assert diag["exorheic"] == 1
        assert diag["endorheic"] == 0
        assert len(drain_pts) == 0

    def test_ambiguous_elevation_treated_as_inflow(self):
        """Stream with |delta_elev| < 0.1m → treated as inflow → endorheic."""
        # Flat DEM where elevation difference is negligible
        dem = np.full((100, 100), 100.0, dtype=np.float64)
        lake = Polygon(
            [
                (500040, 600060),
                (500060, 600060),
                (500060, 600040),
                (500040, 600040),
            ]
        )
        stream = LineString(
            [
                (500020, 600080),
                (500040, 600060),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            gpkg = _create_test_gpkg([lake], [stream], tmp)
            drain_pts, diag = classify_endorheic_lakes(dem, TRANSFORM, gpkg, NODATA)

        assert diag["endorheic"] == 1
        assert len(drain_pts) == 1

    def test_empty_gpkg_no_drain_points(self):
        """GeoPackage without OT_PTWP_A layer → empty result."""
        dem = _make_dem(20, 20)

        with tempfile.TemporaryDirectory() as tmp:
            gpkg_path = Path(tmp) / "empty.gpkg"
            # Create a gpkg with only a stream layer (no PTWP)
            streams_gdf = gpd.GeoDataFrame(
                {"geometry": [LineString([(0, 0), (1, 1)])]},
                crs="EPSG:2180",
            )
            streams_gdf.to_file(gpkg_path, layer="OT_SWRS_L", driver="GPKG")

            drain_pts, diag = classify_endorheic_lakes(
                dem, TRANSFORM, gpkg_path, NODATA
            )

        assert len(drain_pts) == 0
        assert diag["total_lakes"] == 0


# ---- Tests for drain point injection ----


class TestDrainPointInjection:
    """Tests for _add_drain_point helper."""

    def test_drain_point_at_representative_point(self):
        """Drain point placed at representative_point of lake."""
        dem = _make_dem(20, 20)
        lake = Polygon(
            [
                (500005, 600095),
                (500015, 600095),
                (500015, 600085),
                (500005, 600085),
            ]
        )
        drain_points: list[tuple[int, int]] = []
        _add_drain_point(dem, TRANSFORM, lake, NODATA, drain_points)
        assert len(drain_points) == 1
        row, col = drain_points[0]
        assert 0 <= row < 20
        assert 0 <= col < 20

    def test_only_endorheic_get_drain_points(self):
        """Multiple lakes: only endorheic ones get drain points."""
        dem = _make_dem()
        # Endorheic lake (no streams) — far from lake2 (no clustering)
        lake1 = Polygon(
            [
                (500010, 600090),
                (500020, 600090),
                (500020, 600080),
                (500010, 600080),
            ]
        )
        # Exorheic lake (has outflow) — far from lake1
        lake2 = Polygon(
            [
                (500060, 600040),
                (500070, 600040),
                (500070, 600030),
                (500060, 600030),
            ]
        )
        # Outflow from lake2
        outflow = LineString([(500070, 600030), (500090, 600010)])

        with tempfile.TemporaryDirectory() as tmp:
            gpkg = _create_test_gpkg([lake1, lake2], [outflow], tmp)
            drain_pts, diag = classify_endorheic_lakes(dem, TRANSFORM, gpkg, NODATA)

        assert diag["endorheic"] == 1
        assert diag["exorheic"] == 1
        assert len(drain_pts) == 1


class TestLakeClustering:
    """Tests for lake/marsh clustering behavior."""

    def test_touching_lakes_form_cluster(self):
        """Two touching lakes are classified as a single cluster."""
        dem = _make_dem()
        # Lake A and Lake B are adjacent (within 20m buffer)
        lake_a = Polygon(
            [
                (500040, 600060),
                (500050, 600060),
                (500050, 600050),
                (500040, 600050),
            ]
        )
        lake_b = Polygon(
            [
                (500052, 600060),
                (500062, 600060),
                (500062, 600050),
                (500052, 600050),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            gpkg = _create_test_gpkg([lake_a, lake_b], [], tmp)
            drain_pts, diag = classify_endorheic_lakes(dem, TRANSFORM, gpkg, NODATA)

        # Both in one cluster, both endorheic (no streams)
        assert diag["clusters"] == 1
        assert diag["endorheic"] == 2
        assert len(drain_pts) == 2

    def test_cluster_exorheic_propagates(self):
        """If one lake in a cluster has outflow, all lakes are exorheic."""
        dem = _make_dem()
        # Small lake (would be endorheic alone — no streams touch it directly)
        small_lake = Polygon(
            [
                (500040, 600060),
                (500050, 600060),
                (500050, 600050),
                (500040, 600050),
            ]
        )
        # Large lake adjacent (within 20m buffer) — has outflow stream
        large_lake = Polygon(
            [
                (500055, 600060),
                (500070, 600060),
                (500070, 600045),
                (500055, 600045),
            ]
        )
        # Outflow from large_lake
        outflow = LineString([(500070, 600045), (500090, 600020)])

        with tempfile.TemporaryDirectory() as tmp:
            gpkg = _create_test_gpkg([small_lake, large_lake], [outflow], tmp)
            drain_pts, diag = classify_endorheic_lakes(dem, TRANSFORM, gpkg, NODATA)

        # Cluster has outflow → both lakes classified exorheic
        assert diag["clusters"] == 1
        assert diag["exorheic"] == 2
        assert diag["endorheic"] == 0
        assert len(drain_pts) == 0

    def test_distant_lakes_separate_clusters(self):
        """Lakes far apart remain in separate clusters."""
        dem = _make_dem()
        # Lake A in NW corner
        lake_a = Polygon(
            [
                (500005, 600095),
                (500015, 600095),
                (500015, 600085),
                (500005, 600085),
            ]
        )
        # Lake B in SE corner (>20m apart)
        lake_b = Polygon(
            [
                (500080, 600020),
                (500090, 600020),
                (500090, 600010),
                (500080, 600010),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:
            gpkg = _create_test_gpkg([lake_a, lake_b], [], tmp)
            drain_pts, diag = classify_endorheic_lakes(dem, TRANSFORM, gpkg, NODATA)

        assert diag["clusters"] == 2
        assert diag["endorheic"] == 2
        assert len(drain_pts) == 2

    def test_chain_of_lakes_single_cluster(self):
        """Chain A--B--C forms one cluster; outflow on C → all exorheic."""
        dem = _make_dem()
        # Three lakes in a chain, each 5m apart (within 20m buffer)
        lake_a = Polygon(
            [
                (500020, 600070),
                (500030, 600070),
                (500030, 600060),
                (500020, 600060),
            ]
        )
        lake_b = Polygon(
            [
                (500035, 600070),
                (500045, 600070),
                (500045, 600060),
                (500035, 600060),
            ]
        )
        lake_c = Polygon(
            [
                (500050, 600070),
                (500060, 600070),
                (500060, 600060),
                (500050, 600060),
            ]
        )
        # Outflow from lake_c
        outflow = LineString([(500060, 600060), (500080, 600040)])

        with tempfile.TemporaryDirectory() as tmp:
            gpkg = _create_test_gpkg([lake_a, lake_b, lake_c], [outflow], tmp)
            drain_pts, diag = classify_endorheic_lakes(dem, TRANSFORM, gpkg, NODATA)

        assert diag["clusters"] == 1
        assert diag["exorheic"] == 3
        assert diag["endorheic"] == 0
        assert len(drain_pts) == 0


# ---- Tests for pipeline integration ----


class TestPipelineIntegration:
    """Tests for drain point integration with process_hydrology_pyflwdir."""

    def _make_small_dem_metadata(self):
        """Create a small 20x20 DEM with metadata for hydrology processing."""
        dem = _make_dem(20, 20, base_elev=200.0)
        metadata = _make_metadata(dem)
        return dem, metadata

    def test_drain_point_injected_after_hole_filling(self):
        """Drain point cell has NoData in dem_patched before pyflwdir."""
        dem, metadata = self._make_small_dem_metadata()
        drain_points = [(10, 10)]

        # We can verify by checking the output — drain point should be NoData
        filled_dem, fdir, acc, d8_fdir = process_hydrology_pyflwdir(
            dem, metadata, drain_points=drain_points
        )
        # Drain point must be NoData in final filled_dem
        assert filled_dem[10, 10] == NODATA

    def test_drain_point_nodata_in_final_output(self):
        """filled_dem has NoData at drain point locations."""
        dem, metadata = self._make_small_dem_metadata()
        drain_points = [(5, 5), (15, 15)]

        filled_dem, fdir, acc, d8_fdir = process_hydrology_pyflwdir(
            dem, metadata, drain_points=drain_points
        )
        assert filled_dem[5, 5] == NODATA
        assert filled_dem[15, 15] == NODATA

    def test_no_drain_points_unchanged_behavior(self):
        """drain_points=None → identical to original behavior."""
        dem, metadata = self._make_small_dem_metadata()

        result_none = process_hydrology_pyflwdir(dem, metadata, drain_points=None)
        result_empty = process_hydrology_pyflwdir(dem, metadata, drain_points=[])

        # Both should produce identical results
        np.testing.assert_array_equal(result_none[0], result_empty[0])
        np.testing.assert_array_equal(result_none[1], result_empty[1])
        np.testing.assert_array_equal(result_none[2], result_empty[2])

    def test_pyflwdir_drain_point_is_sink(self):
        """Drain point is a proper sink: NoData in filled_dem, fdir=0, acc=0."""
        # Create a bowl-shaped DEM where center is lowest
        dem = np.full((11, 11), 200.0, dtype=np.float64)
        for r in range(11):
            for c in range(11):
                dist = ((r - 5) ** 2 + (c - 5) ** 2) ** 0.5
                dem[r, c] = 100.0 + dist * 5.0  # higher away from center

        metadata = _make_metadata(dem, Affine(1, 0, 500000.0, 0, -1, 600011.0))
        drain_points = [(5, 5)]

        filled_dem, fdir, acc, d8_fdir = process_hydrology_pyflwdir(
            dem, metadata, drain_points=drain_points
        )

        # Drain point must be NoData (sink) in filled_dem
        assert filled_dem[5, 5] == NODATA
        # Drain point fdir should be 0 (NoData/outlet)
        assert fdir[5, 5] == 0
        # Drain point acc should be 0 (NoData cells excluded)
        assert acc[5, 5] == 0
        # Valid neighbors should have valid flow directions
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = 5 + dr, 5 + dc
            assert fdir[nr, nc] != 0, f"Neighbor ({nr},{nc}) has invalid fdir=0"
