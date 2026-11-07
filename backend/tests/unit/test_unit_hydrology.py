"""PGW owner boundaries must not change the raster hydrology."""

import numpy as np
import pytest
import rasterio

from core.hydrology import D8_DIRECTIONS
from core.morphometry_raster import compute_strahler_from_fdir
from core.unit_hydrology import process_unit_hydrology
from tests.dem_equivalence import (
    NODATA,
    THRESHOLDS_M2,
    derive_hydrology,
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
    dem, metadata = synthetic_dem(
        nrows=121, ncols=131, seed=12, nodata_border=False, holes=holes
    )
    if holes:
        seam_col = 72 + round(6 * np.sin(23 / 7))
        dem[23, seam_col] = NODATA
    whole = derive_hydrology(dem, metadata)
    # Baseline fills internal holes for routing and restores DEM nodata afterward;
    # D8 and accumulation must still traverse those temporarily patched cells.
    if holes:
        assert np.any((dem == NODATA) & (whole.fdir > 0))
        assert whole.fdir[23, seam_col] > 0  # patched routing at the seam
    owners = np.empty(dem.shape, dtype=np.uint8)
    for row in range(dem.shape[0]):
        split = 72 + round(6 * np.sin(row / 7))
        owners[row, :split] = 1
        owners[row, split:] = 2
    if units == 3:
        owners[82:, :] = 3
    owners[dem == NODATA] = 0
    # The closed basin and plateau both straddle owner 1/2, rather than
    # testing only unrelated slopes away from the shared boundary.
    assert owners[59, 71] != owners[59, 78]
    assert owners[48, 69] != owners[48, 75]
    border = np.zeros(dem.shape, dtype=bool)
    vertical = owners[:, 1:] != owners[:, :-1]
    border[:, 1:] |= vertical
    border[:, :-1] |= vertical
    horizontal = owners[1:, :] != owners[:-1, :]
    border[1:, :] |= horizontal
    border[:-1, :] |= horizontal
    basin_border = border[55:65, 68:82]
    filled_basin = whole.filled_dem[55:65, 68:82] > dem[55:65, 68:82]
    assert np.any(basin_border & filled_basin)
    assert np.any(border[48:52, 68:76])
    first, second = np.nonzero(whole.fdir > 0)
    crosses = []
    for row, col in zip(first, second, strict=True):
        # Count actual D8 crossings to prove both directions of the quotient cycle.
        if int(whole.fdir[row, col]) not in D8_DIRECTIONS:
            continue
        dr, dc = D8_DIRECTIONS[int(whole.fdir[row, col])]
        tr, tc = int(row) + dr, int(col) + dc
        if (0 <= tr < dem.shape[0] and 0 <= tc < dem.shape[1]
                and owners[row, col] != owners[tr, tc]):
            crosses.append(
                (int(owners[row, col]), int(owners[tr, tc]), int(whole.acc[row, col]))
            )
    assert any(area < 40 for _a, _b, area in crosses), "hillslope leakage is exercised"
    assert (1, 2) in {(a, b) for a, b, _ in crosses}
    assert (2, 1) in {(a, b) for a, b, _ in crosses}, "unit-graph cycle is exercised"

    path = tmp_path / "dem.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=dem.shape[0],
        width=dem.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:2180",
        transform=metadata["transform"],
        nodata=NODATA,
    ) as dst:
        dst.write(dem, 1)
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
    # Float32 reduction order can move an outlet path by up to two ULPs.
    distance_error = np.abs(split_run.flow_dist_m - whole.flow_dist_m)
    ulp = np.spacing(np.maximum(np.abs(whole.flow_dist_m), np.float32(1)))
    np.testing.assert_array_less(distance_error, 2.01 * ulp)
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
        path, "w", driver="GTiff", height=40, width=48, count=1,
        dtype="float32", crs="EPSG:2180", transform=metadata["transform"],
        nodata=NODATA,
    ) as dst:
        dst.write(dem, 1)
    with pytest.raises(MemoryError, match="configured max_window_cells=100"):
        process_unit_hydrology(
            path, owners, tmp_path / "run", (1_000,), max_window_cells=100
        )
