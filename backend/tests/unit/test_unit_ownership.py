"""PGW owners cover the exact input DEM domain, without fringe owners."""

import fiona
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import MultiPolygon, box, mapping

from core.unit_ownership import load_pgw_owners, nearest_valid_owners


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


def _layer(path, name, polygons):
    with fiona.open(
        path,
        mode="w",
        driver="GPKG",
        layer=name,
        crs="EPSG:2180",
        schema={"geometry": "MultiPolygon", "properties": {"MS_KOD": "str"}},
    ) as sink:
        for code, polygon in polygons:
            sink.write(
                {
                    "geometry": mapping(MultiPolygon([polygon])),
                    "properties": {"MS_KOD": code},
                }
            )


def test_pgw_loader_assigns_exterior_within_input_only(tmp_path):
    dem_path = tmp_path / "dem.tif"
    dem = np.ones((20, 20), dtype=np.float32)
    dem[0, 0] = -9999
    with rasterio.open(
        dem_path,
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
    gpkg = tmp_path / "units.gpkg"
    _layer(gpkg, "obszar", [("AREA", box(10, 10, 90, 90))])
    _layer(
        gpkg,
        "Zlewnie_JCWP_rzecznych",
        [("RWA", box(10, 10, 40, 90)), ("RWB", box(40, 10, 70, 90))],
    )
    _layer(gpkg, "Pozostale_obszary_JCWP", [("LW10235", box(70, 10, 90, 90))])
    owners = load_pgw_owners(dem_path, gpkg, tmp_path / "out")
    assert owners.codes == ("LW10235", "RWA", "RWB")
    assert owners.pgw_area_cells == 256
    assert owners.cells[0, 0] == 0  # input nodata remains nodata
    assert owners.cells[1, 1] > 0  # valid exterior gets an existing owner
    assert owners.cells[1, 19] > 0
    assert np.count_nonzero((owners.cells == 0) & owners.valid) == 0
    assert np.count_nonzero(owners.valid) == 399
