"""PGW owner boundaries must not change the raster hydrology."""

import numpy as np
import pytest
import rasterio

from core.hydrology import process_hydrology_pyflwdir
from core.morphometry_raster import compute_strahler_from_fdir
from core.unit_flow_paths import UnitFlowPaths
from core.unit_hydrology import process_unit_hydrology
from tests.dem_equivalence import (
    NODATA,
    THRESHOLDS_M2,
    split_scene,
    subcatchments,
    synthetic_dem,
)


def _equivalent_labels(expected: np.ndarray, actual: np.ndarray) -> None:
    """Require a one-to-one renumbering, not merely equal label counts."""
    assert np.array_equal(expected == 0, actual == 0)
    mappings = {}
    used = set()
    for original in np.unique(expected):
        if original == 0:
            continue
        values = np.unique(actual[expected == original])
        assert len(values) == 1
        replacement = int(values[0])
        assert replacement not in used
        used.add(replacement)
        mappings[int(original)] = replacement
    assert len(mappings) == len(np.unique(actual)) - 1


@pytest.mark.parametrize("holes", [False, True])
@pytest.mark.parametrize("units", [2, 3])
def test_split_hydrology_matches_uncut_dem_with_flat_and_crossings(
    tmp_path, units, holes
):
    scene = split_scene(tmp_path, units, holes)
    metadata, whole = scene.metadata, scene.whole
    owners, border, path = scene.owners, scene.border, scene.dem_path
    split_run = process_unit_hydrology(
        path, owners, tmp_path / "run", THRESHOLDS_M2, buffer_m=125
    )
    np.testing.assert_array_equal(split_run.filled_dem, whole.filled_dem)
    np.testing.assert_array_equal(split_run.fdir, whole.fdir)
    np.testing.assert_array_equal(
        split_run.filled_dem[border], whole.filled_dem[border]
    )
    np.testing.assert_array_equal(split_run.fdir[border], whole.fdir[border])
    np.testing.assert_array_equal(split_run.acc, whole.acc)
    raw = whole.flw.to_array()
    np.testing.assert_array_equal(
        np.load(tmp_path / "run/raw_fdir.npy"), np.where(raw == 247, 0, raw)
    )
    # Same float32 steps as pyflwdir's stream_distance: the same bits.
    np.testing.assert_array_equal(split_run.flow_dist_m, whole.flow_dist_m)
    flow_paths = UnitFlowPaths.from_hydrology(
        split_run, metadata["transform"], tmp_path / "run/downstream.npy"
    )
    np.testing.assert_array_equal(flow_paths.idxs_ds, whole.flw.idxs_ds)
    starts = np.array([0, 17 * 131 + 34, 50 * 131 + 70], dtype=np.int32)
    stream_cells = (whole.acc >= 40) & (whole.filled_dem != NODATA)
    expected_paths, expected_length = whole.flw.path(
        idxs=starts, mask=stream_cells, unit="m"
    )
    actual_paths, actual_length = flow_paths.path(
        idxs=starts, mask=stream_cells, unit="m"
    )
    for actual, expected in zip(actual_paths, expected_paths, strict=True):
        np.testing.assert_array_equal(actual, expected)
        actual_xy = flow_paths.xy(actual)
        expected_xy = whole.flw.xy(expected)
        for a, b in zip(actual_xy, expected_xy, strict=True):
            np.testing.assert_allclose(a, b, rtol=0, atol=1e-8)
    np.testing.assert_allclose(actual_length, expected_length, rtol=0, atol=3e-5)
    for threshold in THRESHOLDS_M2:
        expected_labels, expected_mask, _ = subcatchments(whole, threshold)
        actual_mask = (split_run.acc >= threshold / 25) & (
            split_run.filled_dem != NODATA
        )
        np.testing.assert_array_equal(actual_mask, expected_mask)

        expected_order = compute_strahler_from_fdir(
            whole.flw, whole.acc, threshold // 25
        )
        np.testing.assert_array_equal(split_run.strahler[threshold], expected_order)
        _equivalent_labels(expected_labels, split_run.labels[threshold])


def test_rejects_owner_window_that_exceeds_configured_cell_budget(tmp_path):
    dem, metadata = synthetic_dem(nrows=40, ncols=48, holes=False)
    owners = np.ones(dem.shape, dtype=np.uint8)
    owners[:, 24:] = 2
    owners[dem == NODATA] = 0
    path = tmp_path / "dem.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=40,
        width=48,
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=metadata["transform"],
        nodata=NODATA,
    ) as dst:
        dst.write(dem, 1)
    with pytest.raises(MemoryError, match="configured max_window_cells=100"):
        process_unit_hydrology(
            path, owners, tmp_path / "run", (1_000,), max_window_cells=100
        )


def test_drain_points_of_the_whole_grid_reach_the_windows_that_contain_them(tmp_path):
    dem, metadata = synthetic_dem(nrows=121, ncols=131, seed=12, holes=False)
    # The closed basin straddles the seam of owners 1 and 2; a drain point in it,
    # and one in the flat of owner 2, are outlets in the uncut run.
    drain_points = [(59, 75), (48, 100)]
    filled, fdir, acc, _ = process_hydrology_pyflwdir(
        dem, metadata, drain_points=drain_points
    )
    _, plain_fdir, _, _ = process_hydrology_pyflwdir(dem, metadata)
    assert not np.array_equal(fdir, plain_fdir), "the drain points matter"
    owners = np.empty(dem.shape, dtype=np.uint8)
    for row in range(dem.shape[0]):
        split = 72 + round(6 * np.sin(row / 7))
        owners[row, :split] = 1
        owners[row, split:] = 2
    owners[dem == NODATA] = 0
    path = tmp_path / "dem.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=121,
        width=131,
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=metadata["transform"],
        nodata=NODATA,
    ) as dst:
        dst.write(dem, 1)

    split_run = process_unit_hydrology(
        path,
        owners,
        tmp_path / "run",
        THRESHOLDS_M2,
        buffer_m=125,
        drain_points=drain_points,
    )

    np.testing.assert_array_equal(split_run.filled_dem, filled)
    np.testing.assert_array_equal(split_run.fdir, fdir)
    np.testing.assert_array_equal(split_run.acc, acc)
