"""Bootstrap step 5 on the private store: the HSG raster of ``soil.hsg_depth_rule``.

The real Kartograf computes the raster of Poland into the store of the test's cache
directory from stubbed SoilGrids layers (ADR-079): loamy sand (group A) in every layer
but 60-100 cm, which is loam (group B). The box of the mosaic is smaller than one cell
of the soil grid of step 5 (250 m), so the step ends after the raster, before the
database.
"""

import numpy as np
import pytest
import rasterio

from scripts.bootstrap import step_soil_hsg
from tests.kartograf_offline import LOAM, SANDY, SoilRasters, soil_rasters
from tests.kartograf_offline import offline as offline  # noqa: F401

MOSAIC = (500000.0, 500000.0, 500100.0, 500100.0)


@pytest.mark.usefixtures("offline")
@pytest.mark.parametrize(
    ("rule", "segment", "layers", "group"),
    [
        # clay, sand and silt of the five layers of 0-100 cm; the loam limits: B
        ("least-permeable", "hsg/global_soilgrids_0-100cm_least-permeable_mean", 15, 2),
        # of 0-5 cm only: the loamy sand, A
        ("topsoil", "hsg/global_soilgrids_0-5cm_mean", 3, 1),
    ],
)
def test_the_raster_of_poland_is_computed_by_the_rule(
    tmp_path, monkeypatch, rule, segment, layers, group
):
    monkeypatch.delenv("HYDROGRAF_KARTOGRAF_ROOT", raising=False)
    soil = SoilRasters(SANDY, layers={"60-100cm": LOAM})

    with soil_rasters(soil):
        detail = step_soil_hsg(
            [],
            tmp_path / "data",
            tmp_path / "cache",
            mosaic_bbox_2180=MOSAIC,
            hsg_depth_rule=rule,
        )

    assert detail == "pominięto (bbox zbyt mały dla HSG)"
    assert len(soil.downloads) == layers
    (raster,) = (tmp_path / "cache" / "kartograf" / segment / "versions").rglob("*.tif")
    with rasterio.open(raster) as src:
        assert np.unique(src.read(1)).tolist() == [group]
