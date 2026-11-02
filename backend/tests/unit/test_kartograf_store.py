"""The helpers that say where Kartograf writes and how its answers are read."""

import logging
import os
from pathlib import Path

import kartograf
import pytest
from kartograf.testing import build_fixture_store

from tests.kartograf_offline import Counties, bdot10k_counties
from tests.kartograf_offline import offline as offline  # noqa: F401
from utils.kartograf_store import (
    ACTIVE_WRITE_WINDOW_S,
    describe_error,
    download_bdot10k,
    metadata_cache_path,
    store_dir,
    writes_in_progress,
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


class TestWritesInProgress:
    NOW = 1_800_000_000.0

    def _staging(self, root, age_s, name="archiwista_4242_0a1b2c3d"):
        """A staging entry of a write with one partial file, both ``age_s`` old."""
        entry = root / "nmt" / "pl_1992_5m_evrf2007" / "versions" / ".incoming" / name
        entry.mkdir(parents=True)
        part = entry / "N-33-130-D-d-1-1.asc.4242_1.tmp"
        part.write_text("partial")
        self._age(part, age_s)
        self._age(entry, age_s)
        return entry

    def _age(self, path, age_s):
        os.utime(path, (self.NOW - age_s, self.NOW - age_s))

    def test_an_entry_changed_within_the_window_is_a_write(self, tmp_path):
        entry = self._staging(tmp_path, age_s=ACTIVE_WRITE_WINDOW_S - 1)

        assert writes_in_progress(tmp_path, now=self.NOW) == [entry]

    def test_an_older_entry_is_the_leftover_of_a_stopped_write(self, tmp_path):
        self._staging(tmp_path, age_s=ACTIVE_WRITE_WINDOW_S + 1)

        assert writes_in_progress(tmp_path, now=self.NOW) == []

    def test_a_file_still_being_written_keeps_an_old_entry_active(self, tmp_path):
        entry = self._staging(tmp_path, age_s=3 * ACTIVE_WRITE_WINDOW_S)
        growing = entry / "1465.gpkg.4242_2.tmp"
        growing.write_text("still coming")
        self._age(growing, 5)
        self._age(entry, 3 * ACTIVE_WRITE_WINDOW_S)

        assert writes_in_progress(tmp_path, now=self.NOW) == [entry]

    def test_a_store_without_staging_entries_has_no_writes(self, tmp_path):
        root = tmp_path / "store"
        build_fixture_store(root)
        # Kartograf keeps the empty .incoming directory after a published write.
        (root / "nmt" / "pl_1992_5m_evrf2007" / "versions" / ".incoming").mkdir(
            parents=True, exist_ok=True
        )

        assert writes_in_progress(root) == []
        assert writes_in_progress(tmp_path / "no-store") == []


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
