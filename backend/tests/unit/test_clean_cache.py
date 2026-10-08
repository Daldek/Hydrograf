"""clean_cache usuwa cache metadanych Kartografa razem z cache pobran."""

from pathlib import Path

from scripts.clean import build_plan, clean_cache

META_FILES = ("kartograf_meta.db", "kartograf_meta.db-wal", "kartograf_meta.db-shm")


def _populate(cache_dir: Path) -> None:
    sheet = cache_dir / "nmt" / "pl_1992_5m_evrf2007" / "N-33" / "a.asc"
    sheet.parent.mkdir(parents=True)
    sheet.write_text("x")
    for name in META_FILES:
        (cache_dir / name).write_bytes(b"sqlite")
    (cache_dir / "soil_hsg").mkdir()
    (cache_dir / "soil_hsg" / "hsg_poland.tif").write_bytes(b"hsg")


class TestCleanCacheMetadata:
    def test_removes_metadata_db_and_wal_files(self, tmp_path):
        _populate(tmp_path)

        clean_cache(tmp_path, dry_run=False)

        for name in META_FILES:
            assert not (tmp_path / name).exists()
        assert (tmp_path / "soil_hsg" / "hsg_poland.tif").exists()

    def test_dry_run_counts_but_keeps_metadata(self, tmp_path):
        _populate(tmp_path)

        n_files, _ = clean_cache(tmp_path, dry_run=True)

        assert n_files == 1 + len(META_FILES)
        assert (tmp_path / "kartograf_meta.db").exists()

    def test_plan_counts_metadata_files(self, tmp_path):
        _populate(tmp_path)

        plan = build_plan(["cache"], tmp_path / "data", tmp_path)

        assert plan[0]["files"] == 1 + len(META_FILES)
