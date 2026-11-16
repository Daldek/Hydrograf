"""Finding the NMT sheets of the Kartograf store (built by kartograf.testing)."""

import pytest
from kartograf.testing import PL_SEGMENT, build_fixture_store

from scripts.analyze_watershed import find_existing_nmt_files


@pytest.fixture
def store(tmp_path):
    """The fixture store: one PL 1 m sheet with 3 versions and a CZ sheet."""
    return build_fixture_store(tmp_path / "kartograf")


def test_returns_the_standard_path_of_the_sheet_without_its_copies(tmp_path, store):
    sheet = store.file(PL_SEGMENT)
    assert len(sheet.versions) == 3
    assert sheet.full_sheet_path is not None

    assert find_existing_nmt_files(tmp_path, "1m") == [sheet.path]


def test_ignores_other_resolutions_and_other_countries(tmp_path, store):
    # the store holds a PL 1 m segment and a CZ segment, no 5 m one
    with pytest.raises(FileNotFoundError, match="5m"):
        find_existing_nmt_files(tmp_path, "5m")


def test_raises_when_there_is_no_store(tmp_path):
    with pytest.raises(FileNotFoundError, match="5m"):
        find_existing_nmt_files(tmp_path, "5m")
