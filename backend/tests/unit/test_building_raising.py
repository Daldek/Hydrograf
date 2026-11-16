import os
import tempfile

import numpy as np
import pytest


class TestRaiseBuildingsInDem:
    @pytest.fixture()
    def flat_dem(self):
        return np.ones((10, 10), dtype=np.float64) * 100.0

    @pytest.fixture()
    def dem_transform(self):
        from rasterio.transform import from_bounds

        return from_bounds(400000, 500000, 400050, 500050, 10, 10)

    def _make_gpkg(self, geometries_with_props):
        """Create a temporary GPKG file with given geometries.

        Returns the path; caller is responsible for cleanup.
        """
        import fiona
        from fiona.crs import from_epsg

        fd, path = tempfile.mkstemp(suffix=".gpkg")
        os.close(fd)
        os.unlink(path)  # fiona needs the file to not exist for GPKG creation

        schema = {"geometry": "Polygon", "properties": {"typ": "str"}}
        with fiona.open(
            path, "w", driver="GPKG", schema=schema, crs=from_epsg(2180)
        ) as dst:
            for geom, props in geometries_with_props:
                dst.write(
                    {
                        "geometry": geom.__geo_interface__,
                        "properties": props,
                    }
                )
        return path

    def test_no_buildings_returns_unchanged(self, flat_dem, dem_transform):
        from core.hydrology import raise_buildings_in_dem

        result = raise_buildings_in_dem(
            flat_dem.copy(), dem_transform, None, nodata=-9999.0
        )
        np.testing.assert_array_equal(result, flat_dem)

    def test_building_raises_dem(self, flat_dem, dem_transform):
        from shapely.geometry import box

        from core.hydrology import raise_buildings_in_dem

        building = box(400020, 500020, 400030, 500030)
        path = self._make_gpkg([(building, {"typ": "budynek"})])
        try:
            result = raise_buildings_in_dem(
                flat_dem.copy(),
                dem_transform,
                path,
                building_raise_m=5.0,
                nodata=-9999.0,
            )
            assert result.max() > 100.0
            assert result[0, 0] == pytest.approx(100.0)
        finally:
            os.unlink(path)

    def test_custom_raise_height(self, flat_dem, dem_transform):
        from shapely.geometry import box

        from core.hydrology import raise_buildings_in_dem

        building = box(400010, 500010, 400040, 500040)
        path = self._make_gpkg([(building, {"typ": "budynek"})])
        try:
            result = raise_buildings_in_dem(
                flat_dem.copy(),
                dem_transform,
                path,
                building_raise_m=10.0,
                nodata=-9999.0,
            )
            assert result.max() == pytest.approx(110.0)
        finally:
            os.unlink(path)

    def test_empty_gpkg_returns_unchanged(self, flat_dem, dem_transform):
        from core.hydrology import raise_buildings_in_dem

        path = self._make_gpkg([])
        try:
            result = raise_buildings_in_dem(
                flat_dem.copy(), dem_transform, path, nodata=-9999.0
            )
            np.testing.assert_array_equal(result, flat_dem)
        finally:
            os.unlink(path)

    def test_cells_without_data_under_a_building_keep_nodata(
        self, flat_dem, dem_transform
    ):
        from shapely.geometry import box

        from core.hydrology import raise_buildings_in_dem

        dem = flat_dem.astype(np.float32)
        dem[3:5, 3:5] = -9999.0
        # Rows and columns 2 to 7, the hole of no data among them
        building = box(400010, 500010, 400040, 500040)
        path = self._make_gpkg([(building, {"typ": "budynek"})])
        try:
            result = raise_buildings_in_dem(
                dem, dem_transform, path, building_raise_m=5.0, nodata=-9999.0
            )
        finally:
            os.unlink(path)

        np.testing.assert_array_equal(result[3:5, 3:5], -9999.0)
        raised = np.zeros(dem.shape, dtype=bool)
        raised[2:8, 2:8] = True
        raised[3:5, 3:5] = False
        np.testing.assert_array_equal(result[raised], 105.0)
        np.testing.assert_array_equal(result[~raised & (result != -9999.0)], 100.0)
