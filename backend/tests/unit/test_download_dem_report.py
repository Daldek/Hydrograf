"""download_sheets with the real Kartograf: store, report, loud errors (ADR-061)."""

import kartograf
import pytest

from scripts.download_dem import NmtDownloadError, download_sheets
from tests.kartograf_offline import GugikIndex, flight, gugik_index
from tests.kartograf_offline import offline as offline  # noqa: F401

pytestmark = pytest.mark.usefixtures("offline")

S1 = "N-34-130-D-d-2-1"
S2 = "N-34-130-D-d-2-2"
SEGMENT = "nmt/pl_1992_5m_evrf2007"


class TestDownloadSheetsStore:
    def test_sheets_land_at_the_standard_path_of_a_store(self, tmp_path):
        root = tmp_path / "kartograf"
        with gugik_index(GugikIndex([flight(S1, "2023-05-01", "100")])):
            report = download_sheets([S1], root, tmp_path / "m.db")

        std = root / SEGMENT / "N-34/130/D/d/2/1" / f"{S1}.asc"
        assert report.paths == [std]
        assert std.is_file()
        assert (root / "kartograf-store.json").is_file()

    def test_second_run_uses_the_local_version_without_a_transfer(self, tmp_path):
        index = GugikIndex([flight(S1, "2023-05-01", "100")])
        with gugik_index(index):
            first = download_sheets([S1], tmp_path / "k", tmp_path / "m.db")
            second = download_sheets([S1], tmp_path / "k", tmp_path / "m.db")

        assert second.paths == first.paths  # a local sheet is still in the report
        assert len(index.downloaded) == 1

    def test_no_skip_existing_fetches_the_sheet_again(self, tmp_path):
        index = GugikIndex([flight(S1, "2023-05-01", "100")])
        with gugik_index(index):
            download_sheets([S1], tmp_path / "k", tmp_path / "m.db")
            again = download_sheets(
                [S1], tmp_path / "k", tmp_path / "m.db", skip_existing=False
            )

        assert len(index.downloaded) == 2
        assert len(again.paths) == 1

    def test_newest_flight_is_used_also_when_it_is_partial(self, tmp_path):
        # A sheet on the border has no full flight: a plain directory would drop it
        index = GugikIndex(
            [
                flight(S1, "2023-05-01", "100", full=True),
                flight(S2, "2023-05-01", "101", full=False),
            ]
        )
        with gugik_index(index):
            report = download_sheets([S1, S2], tmp_path / "k", tmp_path / "m.db")

        assert {p.name for p in report.paths} == {f"{S1}.asc", f"{S2}.asc"}


class TestDownloadSheetsReport:
    def test_no_coverage_is_reported_not_raised(self, tmp_path):
        with gugik_index(GugikIndex([flight(S1, "2023-05-01", "100")])):
            report = download_sheets([S1, S2], tmp_path / "k", tmp_path / "m.db")

        assert [p.name for p in report.paths] == [f"{S1}.asc"]
        assert report.no_coverage == [S2]

    def test_no_coverage_for_every_sheet_raises(self, tmp_path):
        with gugik_index(GugikIndex()), pytest.raises(NmtDownloadError, match=S1):
            download_sheets([S1], tmp_path / "k", tmp_path / "m.db")

    def test_transfer_failure_raises_naming_the_sheet(self, tmp_path):
        good, bad = flight(S1, "2023-05-01", "100"), flight(S2, "2023-05-01", "101")
        with (
            gugik_index(GugikIndex([good, bad], failing=[bad.url])),
            pytest.raises(NmtDownloadError, match=S2),
        ):
            download_sheets([S1, S2], tmp_path / "k", tmp_path / "m.db")

    def test_empty_sheet_list_raises(self, tmp_path):
        with pytest.raises(NmtDownloadError):
            download_sheets([], tmp_path / "k", tmp_path / "m.db")

    def test_missing_metadata_cache_directory_raises(self, tmp_path):
        with pytest.raises(NmtDownloadError, match="nie istnieje"):
            download_sheets([S1], tmp_path / "k", tmp_path / "absent" / "m.db")

    def test_invalid_sheet_code_raises_kartograf_parse_error(self, tmp_path):
        with gugik_index(GugikIndex()), pytest.raises(kartograf.ParseError):
            download_sheets(["not-a-sheet"], tmp_path / "k", tmp_path / "m.db")


class TestDownloadSheetsRefusedStore:
    def test_a_root_with_foreign_files_is_a_conflict(self, tmp_path):
        root = tmp_path / "k"
        root.mkdir()
        (root / "notes.txt").write_text("not a store")
        with (
            gugik_index(GugikIndex([flight(S1, "2023-05-01", "100")])),
            pytest.raises(kartograf.ConflictError) as raised,
        ):
            download_sheets([S1], root, tmp_path / "m.db")

        assert raised.value.code == "conflict"
        assert raised.value.reason == "not_empty"
