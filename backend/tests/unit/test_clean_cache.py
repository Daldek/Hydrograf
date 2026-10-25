"""clean_cache empties the large products of the Kartograf store and keeps the rest."""

import kartograf
import pytest
from kartograf.testing import build_fixture_store

from scripts.clean import build_plan, clean_cache
from tests.kartograf_offline import (
    Counties,
    SoilRasters,
    bdot10k_counties,
    soil_rasters,
)
from tests.kartograf_offline import offline as offline  # noqa: F401

META_FILES = ("kartograf_meta.db", "kartograf_meta.db-wal", "kartograf_meta.db-shm")
BBOX = kartograf.BBox(450000, 550000, 460000, 560000, "EPSG:2180")


@pytest.fixture
def cache_dir(tmp_path, offline):  # noqa: F811
    """A cache with a store (NMT, BDOT10k, SoilGrids, HSG) and the meta files."""
    root = tmp_path / "kartograf"
    build_fixture_store(root)
    with bdot10k_counties(Counties(["1465"])):
        report = kartograf.download_landcover(
            product="bdot10k", root=root, teryt="1465", cache=False
        )
    assert report.ok
    with soil_rasters(SoilRasters()):
        report = kartograf.calculate_hsg(
            root=root, bbox=BBOX, depth="0-5cm", cache=False
        )
    assert report.ok
    for name in META_FILES:
        (tmp_path / name).write_text("sqlite")
    return tmp_path


def _segments(cache_dir):
    return {
        segment.split("/")[0]
        for segment in kartograf.list_segments(cache_dir / "kartograf")
    }


def test_removes_nmt_bdot10k_and_metadata_and_keeps_hsg(cache_dir):
    assert _segments(cache_dir) == {"nmt", "landcover", "soil", "hsg"}

    clean_cache(cache_dir, dry_run=False)

    assert _segments(cache_dir) == {"soil", "hsg"}
    assert (cache_dir / "kartograf" / "kartograf-store.json").is_file()
    assert not [p for p in cache_dir.iterdir() if p.name.startswith("kartograf_meta")]


def test_what_is_left_is_a_store_that_kartograf_still_writes(cache_dir):
    clean_cache(cache_dir, dry_run=False)

    with bdot10k_counties(Counties(["1465"])):
        report = kartograf.download_landcover(
            product="bdot10k", root=cache_dir / "kartograf", teryt="1465", cache=False
        )

    assert report.ok
    assert [item.file.status for item in report.files] == ["new"]


def test_dry_run_removes_nothing(cache_dir):
    before = sorted(p for p in cache_dir.rglob("*") if p.is_file())

    clean_cache(cache_dir, dry_run=True)

    assert sorted(p for p in cache_dir.rglob("*") if p.is_file()) == before


def test_plan_counts_what_the_clean_removes(cache_dir):
    (entry,) = build_plan(["cache"], cache_dir / "data", cache_dir)
    files_before = sum(1 for p in cache_dir.rglob("*") if p.is_file())

    removed_files, _ = clean_cache(cache_dir, dry_run=False)
    files_after = sum(1 for p in cache_dir.rglob("*") if p.is_file())

    assert entry["files"] == removed_files == files_before - files_after
