"""Kontrakt download_sheets() z Kartografem 0.7.0: raport, glosne bledy, cache."""

from pathlib import Path
from unittest.mock import patch

import pytest
from kartograf.download.manager import DownloadResult

from scripts.download_dem import NmtDownloadError, NmtDownloadReport, download_sheets


class FakeManager:
    """Atrapa DownloadManager: zwraca zadany wynik i zapisuje parametry."""

    result: DownloadResult = DownloadResult()
    paths: list[Path] = []
    init_kwargs: dict = {}
    disable_cache_with: str | None = None
    calls: list[tuple[list[str], bool]] = []

    def __init__(self, **kwargs):
        FakeManager.init_kwargs = kwargs
        self.last_result = None
        self.last_sheet = None

    def download_sheets(self, godla, skip_existing=True):
        FakeManager.calls.append((list(godla), skip_existing))
        if FakeManager.disable_cache_with:
            cache = FakeManager.init_kwargs["provider"].cache
            cache.on_disabled(FakeManager.disable_cache_with)
        self.last_result = FakeManager.result
        return list(FakeManager.paths)


class FakeProvider:
    def __init__(self, resolution, cache):
        self.resolution = resolution
        self.cache = cache


class FakeCache:
    def __init__(self, db_path, on_disabled):
        self.db_path = Path(db_path)
        self.on_disabled = on_disabled


@pytest.fixture
def fake_kartograf():
    FakeManager.result = DownloadResult()
    FakeManager.paths = []
    FakeManager.init_kwargs = {}
    FakeManager.disable_cache_with = None
    FakeManager.calls = []
    with (
        patch("kartograf.DownloadManager", FakeManager),
        patch("kartograf.GugikProvider", FakeProvider),
        patch("kartograf.MetadataCache", FakeCache),
    ):
        yield FakeManager


def _asc(tmp_path: Path, godlo: str) -> Path:
    return tmp_path / "nmt" / "pl_1992_5m_evrf2007" / f"{godlo}.asc"


class TestDownloadSheetsWiring:
    def test_uses_campaigns_newest_cache_and_data_root(self, fake_kartograf, tmp_path):
        fake_kartograf.paths = [_asc(tmp_path, "N-33-130-D-d-1-1")]
        fake_kartograf.result = DownloadResult(succeeded=list(fake_kartograf.paths))

        download_sheets(
            ["N-33-130-D-d-1-1"],
            output_dir=tmp_path,
            metadata_cache_path=tmp_path / "kartograf_meta.db",
            resolution="5m",
        )

        kw = fake_kartograf.init_kwargs
        assert kw["output_dir"] == str(tmp_path)
        assert kw["resolution"] == "5m"
        assert kw["campaigns"] == "newest"
        assert kw["provider"].resolution == "5m"
        assert kw["provider"].cache.db_path == tmp_path / "kartograf_meta.db"
        assert fake_kartograf.calls == [(["N-33-130-D-d-1-1"], True)]


class TestDownloadSheetsReport:
    def test_returns_report_with_paths(self, fake_kartograf, tmp_path):
        p = _asc(tmp_path, "N-33-130-D-d-1-1")
        fake_kartograf.paths = [p]
        fake_kartograf.result = DownloadResult(skipped=["N-33-130-D-d-1-1"])

        report = download_sheets(["N-33-130-D-d-1-1"], tmp_path, tmp_path / "m.db")

        assert isinstance(report, NmtDownloadReport)
        assert report.paths == [p]
        assert report.no_coverage == []
        assert report.unverified == {}

    def test_partial_no_coverage_is_reported_not_raised(self, fake_kartograf, tmp_path):
        p = _asc(tmp_path, "N-33-130-D-d-1-1")
        fake_kartograf.paths = [p]
        fake_kartograf.result = DownloadResult(
            succeeded=[p],
            failed=["M-33-60-A-a-1-1"],
            no_coverage=["M-33-60-A-a-1-1"],
        )

        report = download_sheets(
            ["N-33-130-D-d-1-1", "M-33-60-A-a-1-1"], tmp_path, tmp_path / "m.db"
        )

        assert report.paths == [p]
        assert report.no_coverage == ["M-33-60-A-a-1-1"]

    def test_unverified_reuse_is_reported(self, fake_kartograf, tmp_path):
        p = _asc(tmp_path, "N-33-130-D-d-1-1")
        fake_kartograf.paths = [p]
        fake_kartograf.result = DownloadResult(
            skipped=["N-33-130-D-d-1-1"],
            unverified={"N-33-130-D-d-1-1": "skorowidz niedostepny"},
        )

        report = download_sheets(["N-33-130-D-d-1-1"], tmp_path, tmp_path / "m.db")

        assert report.unverified == {"N-33-130-D-d-1-1": "skorowidz niedostepny"}


class TestDownloadSheetsLoudErrors:
    def test_hard_failures_raise_with_full_list(self, fake_kartograf, tmp_path):
        p = _asc(tmp_path, "N-33-130-D-d-1-1")
        fake_kartograf.paths = [p]
        fake_kartograf.result = DownloadResult(
            succeeded=[p],
            failed=["N-33-130-D-d-1-2", "N-33-130-D-d-1-3"],
        )

        with pytest.raises(NmtDownloadError) as exc:
            download_sheets(
                ["N-33-130-D-d-1-1", "N-33-130-D-d-1-2", "N-33-130-D-d-1-3"],
                tmp_path,
                tmp_path / "m.db",
            )

        msg = str(exc.value)
        assert "2 z 3" in msg
        assert "N-33-130-D-d-1-2" in msg
        assert "N-33-130-D-d-1-3" in msg

    def test_all_no_coverage_raises(self, fake_kartograf, tmp_path):
        fake_kartograf.paths = []
        fake_kartograf.result = DownloadResult(
            failed=["N-35-1-A-a-1-1"], no_coverage=["N-35-1-A-a-1-1"]
        )

        with pytest.raises(NmtDownloadError, match="brak pokrycia"):
            download_sheets(["N-35-1-A-a-1-1"], tmp_path, tmp_path / "m.db")

    def test_disabled_metadata_cache_raises(self, fake_kartograf, tmp_path):
        p = _asc(tmp_path, "N-33-130-D-d-1-1")
        fake_kartograf.paths = [p]
        fake_kartograf.result = DownloadResult(succeeded=[p])
        fake_kartograf.disable_cache_with = "cache metadanych nieczytelny (m.db)"

        with pytest.raises(NmtDownloadError, match="cache metadanych nieczytelny"):
            download_sheets(["N-33-130-D-d-1-1"], tmp_path, tmp_path / "m.db")

    def test_missing_cache_parent_dir_raises_before_download(
        self, fake_kartograf, tmp_path
    ):
        with pytest.raises(NmtDownloadError, match="nie istnieje"):
            download_sheets(
                ["N-33-130-D-d-1-1"], tmp_path, tmp_path / "brak" / "m.db"
            )
        assert fake_kartograf.calls == []
