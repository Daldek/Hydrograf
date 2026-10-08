"""Uniewaznianie cache hsg_poland.tif po zmianie Kartografa (progi USDA w 0.7.0)."""

import json
from pathlib import Path

import pytest

from scripts.bootstrap import HsgCacheStaleError, check_hsg_cache


def _write_sidecar(raster: Path, version: str, derived: str = "hsg") -> None:
    sidecar = raster.with_name(raster.name + ".meta.json")
    sidecar.write_text(
        json.dumps({"kartograf_version": version, "extra": {"derived": derived}})
    )


@pytest.fixture
def raster(tmp_path: Path) -> Path:
    path = tmp_path / "hsg_poland.tif"
    path.write_bytes(b"raster")
    return path


class TestCheckHsgCache:
    def test_current_version_passes(self, raster):
        _write_sidecar(raster, "0.7.0")
        check_hsg_cache(raster, "0.7.0")

    def test_missing_sidecar_is_stale(self, raster):
        with pytest.raises(HsgCacheStaleError, match="brak sidecara"):
            check_hsg_cache(raster, "0.7.0")

    def test_other_version_is_stale(self, raster):
        _write_sidecar(raster, "0.6.1")
        with pytest.raises(HsgCacheStaleError, match="0.6.1"):
            check_hsg_cache(raster, "0.7.0")

    def test_not_hsg_product_is_stale(self, raster):
        _write_sidecar(raster, "0.7.0", derived="clay")
        with pytest.raises(HsgCacheStaleError, match="HSG"):
            check_hsg_cache(raster, "0.7.0")

    def test_message_tells_how_to_fix(self, raster):
        with pytest.raises(HsgCacheStaleError, match="Usun"):
            check_hsg_cache(raster, "0.7.0")
