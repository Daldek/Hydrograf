"""The helpers that say where Kartograf writes and how its answers are read."""

import logging
from pathlib import Path

import kartograf
import pytest

from core.errors import ForbiddenError
from scripts.download_dem import download_sheets
from scripts.download_landcover import fetch_landcover
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


class TestSharedStore:
    def test_the_variable_moves_the_store_and_keeps_the_metadata_cache(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("HYDROGRAF_KARTOGRAF_ROOT", str(tmp_path / "shared"))
        cache_dir = tmp_path / "cache"

        assert store_dir(cache_dir) == tmp_path / "shared"
        # Each producer keeps its own metadata cache, never inside the shared store.
        assert metadata_cache_path(cache_dir) == cache_dir / "kartograf_meta.db"

    @pytest.mark.parametrize("value", ["", "   "])
    def test_an_empty_variable_keeps_the_private_store(
        self, tmp_path, monkeypatch, value
    ):
        monkeypatch.setenv("HYDROGRAF_KARTOGRAF_ROOT", value)

        assert store_dir(tmp_path) == tmp_path / "kartograf"

    @pytest.mark.usefixtures("offline")
    @pytest.mark.parametrize(
        "download",
        [
            lambda cache: download_bdot10k(cache, bbox=AREA),
            lambda cache: download_sheets(
                ["N-33-130-D-d-1-1"], cache / "kartograf", cache / "meta.db"
            ),
            lambda cache: fetch_landcover(cache / "kartograf", teryt="1465"),
        ],
        ids=["download_bdot10k", "download_sheets", "fetch_landcover"],
    )
    def test_no_download_while_a_shared_store_is_set(
        self, tmp_path, monkeypatch, download
    ):
        """Archiwista alone writes the shared store (ADR-067): nothing is written."""
        shared = tmp_path / "shared"
        shared.mkdir()
        monkeypatch.setenv("HYDROGRAF_KARTOGRAF_ROOT", str(shared))
        cache = tmp_path / "cache"
        cache.mkdir()

        with pytest.raises(ForbiddenError) as raised:
            download(cache)

        assert raised.value.details["reason"] == "shared_store_read_only"
        assert list(shared.iterdir()) == []
        assert list(cache.iterdir()) == []


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

    def test_an_error_of_hydrograf_says_its_code_and_hint(self):
        error = ForbiddenError(
            "shared_store_read_only", reason="shared_store_read_only", root="/s"
        )

        assert describe_error(error) == f"{error} [forbidden] {error.hint}"


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
