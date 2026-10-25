"""The helpers that say where Kartograf writes and how its answers are read."""

import logging
from pathlib import Path

import kartograf
import pytest

from tests.kartograf_offline import Counties, bdot10k_counties
from tests.kartograf_offline import offline as offline  # noqa: F401
from utils.kartograf_store import (
    describe_error,
    download_bdot10k,
    metadata_cache_path,
    store_dir,
)

AREA = kartograf.BBox(450000, 550000, 460000, 560000, "EPSG:2180")


def test_store_and_metadata_cache_are_siblings_inside_the_cache_dir(tmp_path):
    assert store_dir(tmp_path) == tmp_path / "kartograf"
    assert metadata_cache_path(tmp_path) == tmp_path / "kartograf_meta.db"


class TestDescribeError:
    def test_other_errors_are_their_text(self):
        assert describe_error(ValueError("no area")) == "no area"

    def test_a_kartograf_error_says_its_code(self, tmp_path):
        with pytest.raises(kartograf.KartografError) as raised:
            kartograf.download_landcover(
                product="bdot10k", root=tmp_path, bbox=AREA, teryt="1465"
            )

        text = describe_error(raised.value)

        assert str(raised.value) in text
        assert f"[{raised.value.code}]" in text

    def test_the_hint_of_the_error_follows_the_code(self):
        error = kartograf.StoreUnavailableError(
            "no marker", hint="kartograf store init --root DIR", reason="no_marker"
        )

        assert describe_error(error) == (
            "no marker [store_unavailable] kartograf store init --root DIR"
        )


@pytest.mark.usefixtures("offline")
class TestDownloadBdot10k:
    def test_returns_the_package_of_each_county_of_the_area(self, tmp_path):
        with bdot10k_counties(Counties(["1401", "1465"])):
            paths = download_bdot10k(tmp_path, bbox=AREA)

        landcover = tmp_path / "kartograf" / "landcover" / "pl_bdot10k_gpkg" / "teryt"
        assert paths == {
            "1401": landcover / "1401.gpkg",
            "1465": landcover / "1465.gpkg",
        }

    def test_a_failed_county_is_logged_and_left_out(self, tmp_path, caplog):
        with (
            bdot10k_counties(Counties(["1401", "1465"], failing=["1401"])),
            caplog.at_level(logging.WARNING),
        ):
            paths = download_bdot10k(tmp_path, bbox=AREA)

        assert list(paths) == ["1465"]
        assert "county 1401" in caplog.text

    def test_an_area_without_counties_gives_nothing(self, tmp_path, caplog):
        with (
            bdot10k_counties(Counties([])),
            caplog.at_level(logging.WARNING),
        ):
            assert download_bdot10k(tmp_path, bbox=AREA) == {}

        assert "BDOT10k" in caplog.text

    def test_a_store_that_refuses_the_write_raises_with_its_code(self, tmp_path):
        store = tmp_path / "kartograf"
        store.mkdir()
        Path(store / "notes.txt").write_text("not a store")

        with (
            bdot10k_counties(Counties(["1465"])),
            pytest.raises(kartograf.ConflictError) as raised,
        ):
            download_bdot10k(tmp_path, teryt="1465")

        assert "[conflict]" in describe_error(raised.value)
