"""PGW owners cover the exact input DEM domain, without fringe owners."""

import fiona
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import MultiPolygon, box, mapping

from core.unit_ownership import (
    REMAINING_AREAS_LAYER,
    RIVER_CATCHMENTS_LAYER,
    CatchmentFile,
    group_catchments,
    load_pgw_owners,
    nearest_valid_owners,
)


def test_nearest_owner_uses_original_seeds_and_preserves_nodata():
    initial = np.zeros((31, 39), dtype=np.uint8)
    initial[4, 6] = 1
    initial[28, 34] = 2
    valid = np.ones_like(initial, dtype=bool)
    valid[0, 0] = False
    first = initial.copy()
    second = initial.copy()
    nearest_valid_owners(first, valid, tile_pixels=4)
    nearest_valid_owners(second, valid, tile_pixels=13)
    np.testing.assert_array_equal(first, second)
    assert first[0, 0] == 0
    rows, cols = np.indices(initial.shape)
    d1 = (rows - 4) ** 2 + (cols - 6) ** 2
    d2 = (rows - 28) ** 2 + (cols - 34) ** 2
    np.testing.assert_array_equal(first[valid & (d1 < d2)], 1)
    np.testing.assert_array_equal(first[valid & (d2 < d1)], 2)


def _layer(path, name, polygons, crs="EPSG:2180"):
    with fiona.open(
        path,
        mode="w",
        driver="GPKG",
        layer=name,
        crs=crs,
        schema={"geometry": "MultiPolygon", "properties": {"MS_KOD": "str"}},
    ) as sink:
        for code, polygon in polygons:
            sink.write(
                {
                    "geometry": mapping(MultiPolygon([polygon])),
                    "properties": {"MS_KOD": code},
                }
            )


def _dem(path, nodata_cells=((0, 0),)):
    """20 x 20 cells of 5 m: x 0..100, y 0..100; ``nodata_cells`` hold no data."""
    dem = np.ones((20, 20), dtype=np.float32)
    for row, col in nodata_cells:
        dem[row, col] = -9999
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=20,
        width=20,
        count=1,
        dtype="float32",
        transform=from_origin(0, 100, 5, 5),
        crs="EPSG:2180",
        nodata=-9999,
    ) as sink:
        sink.write(dem, 1)
    return path


REMAINDER = ("LW10235", box(70, 10, 90, 90))


def _units(path, rivers, remaining=(REMAINDER,)):
    _layer(path, RIVER_CATCHMENTS_LAYER, rivers)
    _layer(path, REMAINING_AREAS_LAYER, remaining)
    return path


RIVERS = [("RWA", box(10, 10, 40, 90)), ("RWB", box(40, 10, 70, 90))]


def test_pgw_loader_assigns_exterior_within_input_only(tmp_path):
    dem_path = _dem(tmp_path / "dem.tif")
    gpkg = _units(tmp_path / "units.gpkg", RIVERS)

    owners = load_pgw_owners(dem_path, gpkg, tmp_path / "out")

    assert owners.codes == ("LW10235", "RWA", "RWB")
    assert owners.pgw_cells == 256
    assert owners.cells[0, 0] == 0  # input nodata remains nodata
    assert owners.cells[1, 1] > 0  # valid exterior gets an existing owner
    assert owners.cells[1, 19] > 0
    assert np.count_nonzero((owners.cells == 0) & owners.valid) == 0
    assert np.count_nonzero(owners.valid) == 399


def test_area_clips_the_polygons_so_a_neighbour_in_the_margin_owns_nothing(tmp_path):
    dem_path = _dem(tmp_path / "dem.tif")
    # RWC only reaches into the margin of the DEM, beyond the analysis area.
    gpkg = _units(tmp_path / "units.gpkg", [*RIVERS, ("RWC", box(0, 0, 100, 10))])
    area = tmp_path / "area.gpkg"
    _layer(area, "obszar", [("AREA", box(10, 10, 90, 90))])

    unclipped = load_pgw_owners(dem_path, gpkg, tmp_path / "all")
    clipped = load_pgw_owners(dem_path, gpkg, tmp_path / "clip", area, "obszar")

    assert unclipped.codes == ("LW10235", "RWA", "RWB", "RWC")
    assert clipped.codes == ("LW10235", "RWA", "RWB")
    assert clipped.pgw_cells == 256
    # The margin of the DEM goes to the nearest owner instead.
    assert clipped.cells[19, 5] == clipped.codes.index("RWA") + 1
    assert np.count_nonzero((clipped.cells == 0) & clipped.valid) == 0


def test_area_must_be_covered_by_polygons_where_the_dem_has_data(tmp_path):
    dem_path = _dem(tmp_path / "dem.tif")
    gpkg = _units(tmp_path / "units.gpkg", RIVERS, remaining=[])
    area = tmp_path / "area.gpkg"
    _layer(area, "obszar", [("AREA", box(10, 10, 90, 90))])

    # x 70..90 of the area has no polygon.
    with pytest.raises(ValueError, match="without an owner"):
        load_pgw_owners(dem_path, gpkg, tmp_path / "out", area)


def test_a_gap_where_the_dem_has_no_data_is_not_a_gap(tmp_path):
    cells = [(r, c) for r in range(2, 18) for c in range(14, 18)]  # x 70..90
    dem_path = _dem(tmp_path / "dem.tif", nodata_cells=cells)
    gpkg = _units(tmp_path / "units.gpkg", RIVERS, remaining=[])
    area = tmp_path / "area.gpkg"
    _layer(area, "obszar", [("AREA", box(10, 10, 90, 90))])

    owners = load_pgw_owners(dem_path, gpkg, tmp_path / "out", area)

    assert owners.codes == ("RWA", "RWB")
    assert np.all(owners.cells[~owners.valid] == 0)


def test_overlapping_owners_are_refused(tmp_path):
    dem_path = _dem(tmp_path / "dem.tif")
    gpkg = _units(
        tmp_path / "units.gpkg",
        [("RWA", box(10, 10, 50, 90)), ("RWB", box(40, 10, 70, 90))],
    )

    with pytest.raises(ValueError, match="RWA and RWB overlap"):
        load_pgw_owners(dem_path, gpkg, tmp_path / "out")


def test_features_of_one_code_are_one_owner(tmp_path):
    dem_path = _dem(tmp_path / "dem.tif")
    gpkg = _units(
        tmp_path / "units.gpkg",
        [("RWA", box(10, 10, 40, 50)), ("RWA", box(10, 50, 40, 90))],
        remaining=[],
    )

    owners = load_pgw_owners(dem_path, gpkg, tmp_path / "out")

    assert owners.codes == ("RWA",)
    assert np.count_nonzero(owners.cells) == 399


def test_a_units_file_without_the_pgw_layers_is_refused(tmp_path):
    dem_path = _dem(tmp_path / "dem.tif")
    gpkg = tmp_path / "other.gpkg"
    _layer(gpkg, "Zlewnie_JCWP_rzecznych", RIVERS)

    with pytest.raises(ValueError, match="no layer 'zlewnie_jcwp_rzecznych'"):
        load_pgw_owners(dem_path, gpkg, tmp_path / "out")


def test_units_in_another_crs_are_refused(tmp_path):
    dem_path = _dem(tmp_path / "dem.tif")
    gpkg = tmp_path / "units.gpkg"
    _layer(gpkg, RIVER_CATCHMENTS_LAYER, RIVERS, crs="EPSG:4326")
    _layer(gpkg, REMAINING_AREAS_LAYER, [], crs="EPSG:4326")

    with pytest.raises(ValueError, match="EPSG:2180"):
        load_pgw_owners(dem_path, gpkg, tmp_path / "out")


def _catchment_file(path, catchments, crs="ESRI:102173", key="ID_HYD_10"):
    with fiona.open(
        path,
        mode="w",
        driver="GPKG",
        layer="zlewnie",
        crs=crs,
        schema={"geometry": "MultiPolygon", "properties": {key: "str"}},
    ) as sink:
        for value, polygon in catchments:
            sink.write(
                {
                    "geometry": mapping(MultiPolygon([polygon])),
                    "properties": {key: value},
                }
            )
    return CatchmentFile(path, "zlewnie", key)


def test_each_catchment_goes_to_the_unit_it_overlaps_most():
    units = {"RWA": box(0, 0, 50, 200), "RWB": box(50, 0, 100, 200)}
    catchments = {
        "c1": box(0, 0, 20, 100),
        # 60 % in RWA: the owner RWA reaches into RWB by this catchment
        "c2": box(20, 0, 70, 100),
        "c3": box(70, 0, 100, 100),
        # An equal overlap goes to the first code
        "c4": box(40, 100, 60, 120),
    }

    owners, members = group_catchments(units, catchments)

    assert members == {"RWA": ("c1", "c2", "c4"), "RWB": ("c3",)}
    assert owners["RWA"].equals(box(0, 0, 70, 100).union(box(40, 100, 60, 120)))
    assert owners["RWB"].equals(box(70, 0, 100, 100))


def test_a_catchment_outside_every_unit_is_refused():
    with pytest.raises(ValueError, match="'c9' overlaps no PGW unit"):
        group_catchments({"RWA": box(0, 0, 50, 100)}, {"c9": box(60, 0, 70, 10)})


def test_catchment_groups_are_the_owners_with_their_keys(tmp_path):
    dem_path = _dem(tmp_path / "dem.tif")
    gpkg = _units(tmp_path / "units.gpkg", RIVERS)
    # ESRI:102173 is EPSG:2180 as ArcGIS writes it
    catchments = _catchment_file(
        tmp_path / "h07.gpkg",
        [
            ("183811", box(10, 10, 40, 50)),
            ("183812", box(10, 50, 40, 90)),
            ("183813", box(40, 10, 90, 90)),
        ],
    )

    owners = load_pgw_owners(dem_path, gpkg, tmp_path / "out", catchments=catchments)

    # LW10235 holds no catchment: it is no owner, and RWB takes x 70..90 of it
    assert owners.codes == ("RWA", "RWB")
    assert owners.members == {"RWA": ("183811", "183812"), "RWB": ("183813",)}
    assert owners.pgw_cells == 256
    assert np.all(owners.cells[2:18, 2:8] == 1)
    assert np.all(owners.cells[2:18, 8:18] == 2)
    assert np.count_nonzero((owners.cells == 0) & owners.valid) == 0


@pytest.mark.parametrize(
    ("catchments", "options", "error"),
    [
        ([("1", box(10, 10, 40, 90)), ("1", box(40, 10, 70, 90))], {}, "repeats"),
        ([(" ", box(10, 10, 40, 90))], {}, "without ID_HYD_10"),
        ([("1", box(10, 10, 40, 90))], {"crs": "EPSG:4326"}, "EPSG:2180"),
        ([("1", box(10, 10, 40, 90))], {"key": "KOD"}, "no field 'ID_HYD_10'"),
    ],
)
def test_a_catchment_file_without_unique_keys_in_epsg_2180_is_refused(
    tmp_path, catchments, options, error
):
    dem_path = _dem(tmp_path / "dem.tif")
    gpkg = _units(tmp_path / "units.gpkg", RIVERS)
    source = _catchment_file(tmp_path / "h07.gpkg", catchments, **options)
    wanted = CatchmentFile(source.path, source.layer, "ID_HYD_10")

    with pytest.raises(ValueError, match=error):
        load_pgw_owners(dem_path, gpkg, tmp_path / "out", catchments=wanted)
