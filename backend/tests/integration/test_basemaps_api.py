"""
GET /api/v1/basemaps and the start of the API (api/endpoints/basemaps.py, api/main.py;
Nogat DEV-15.15, ADR-089).

The page gets the catalogue's entries as the kit writes them and the deployment's own
base maps without `blocks`; a wrong setting stops the API at start with the error
document on standard error.
"""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import core.basemaps
from api.main import app
from core.basemaps import catalogue, current_basemaps
from core.config import Settings, nogat_table
from core.errors import InvalidSettingError


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """Make the process's settings those of the given nogat.toml and variables."""

    def use(text: str = "", **settings: Any) -> None:
        path = tmp_path / "nogat.toml"
        path.write_text(text, encoding="utf-8")
        chosen = Settings(nogat_config=str(path), **settings)
        monkeypatch.setattr(core.basemaps, "get_settings", lambda: chosen)

    monkeypatch.delenv("HYDROGRAF_BASEMAPS", raising=False)
    monkeypatch.delenv("NOGAT_BASEMAPS", raising=False)
    nogat_table.cache_clear()
    current_basemaps.cache_clear()
    yield use
    nogat_table.cache_clear()
    current_basemaps.cache_clear()


def test_default_answer_is_the_catalogue(deployment):
    deployment()

    response = TestClient(app).get("/api/v1/basemaps")

    assert response.status_code == 200
    assert response.json() == catalogue()


def test_an_own_base_map_has_no_blocks_zooms_or_bounds(deployment):
    deployment(
        "[[nogat.basemap_extra]]\n"
        'id = "gmina"\nname = "Mapa gminy"\nkind = "xyz"\n'
        'url = "https://tiles.gmina.example/{z}/{x}/{y}.png"\n'
        'attribution = "© Gmina"\n',
        hydrograf_basemaps="",
    )

    response = TestClient(app).get("/api/v1/basemaps")

    assert response.json() == [
        {
            "id": "gmina",
            "label": "Mapa gminy",
            "kind": "raster",
            "url": "https://tiles.gmina.example/{z}/{x}/{y}.png",
            "origin": "https://tiles.gmina.example",
            "grey": False,
            "default": False,
            "credit": {"text": "© Gmina", "links": []},
        }
    ]


def test_an_unknown_id_stops_the_start_with_the_document_on_stderr(deployment, capsys):
    deployment(nogat_basemaps="openfreemap,esri")

    with pytest.raises(InvalidSettingError), TestClient(app):
        pass

    document = json.loads(capsys.readouterr().err.splitlines()[-1])
    assert document["code"] == "validation_error"
    assert document["details"]["option"] == "basemaps"
    assert document["details"]["value"] == "esri"
    assert document["details"]["source"] == "NOGAT_BASEMAPS"
