"""Wyszukiwanie istniejacych plikow NMT w ukladzie Kartografa 0.7.0."""

import pytest

from scripts.analyze_watershed import find_existing_nmt_files


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    return path


@pytest.fixture
def nmt_tree(tmp_path):
    nmt = tmp_path / "nmt"
    sheet5 = _touch(nmt / "pl_1992_5m_evrf2007" / "N-33-130-D-d-2-1.asc")
    _touch(nmt / "pl_1992_5m_evrf2007" / "kampanie" / "2022" / "N-33-130-D-d-2-1.asc")
    _touch(nmt / "pl_1992_1m_evrf2007" / "N-33-130-D-d-2-1-1.asc")
    _touch(nmt / "reprojected" / "a.tif")
    _touch(nmt / "dem_mosaic_x.tif")
    return tmp_path, sheet5


def test_returns_only_selected_resolution_without_campaigns(nmt_tree):
    data_dir, sheet5 = nmt_tree
    assert find_existing_nmt_files(data_dir, "5m") == [sheet5]


def test_ignores_intermediate_products_and_other_resolutions(nmt_tree):
    data_dir, _ = nmt_tree
    names = {p.name for p in find_existing_nmt_files(data_dir, "1m")}
    assert names == {"N-33-130-D-d-2-1-1.asc"}


def test_raises_when_nothing_found(tmp_path):
    (tmp_path / "nmt").mkdir()
    _touch(tmp_path / "nmt" / "dem_mosaic_x.tif")
    with pytest.raises(FileNotFoundError, match="5m"):
        find_existing_nmt_files(tmp_path, "5m")
