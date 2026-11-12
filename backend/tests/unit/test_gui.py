"""
Tests of the deployment's GUIs for the app menu (HYDROGRAF_GUI, GET /api/gui, ADR-082).

The value is the table `gui` of `[nogat]` (Nogat DEV-15.4, DEV-18.1) as a JSON object;
the settings refuse one the menu cannot use, and the route serves it as it is, `{}`
without it.
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import api.endpoints.gui
from api.main import app
from core.config import Settings, gui_table

TABLE = (
    '{"hydrolog": "http://127.0.0.1:8070/", "archiwista": "https://archiwista.example/",'
    ' "obserwator": "/obserwator/"}'
)


class TestGuiTable:
    @pytest.mark.parametrize("value", ["", "  \n"])
    def test_empty_value_is_an_empty_table(self, value):
        assert gui_table(value) == {}

    def test_names_and_addresses_are_kept_in_order(self):
        assert list(gui_table(TABLE).items()) == [
            ("hydrolog", "http://127.0.0.1:8070/"),
            ("archiwista", "https://archiwista.example/"),
            ("obserwator", "/obserwator/"),
        ]

    @pytest.mark.parametrize(
        "value",
        [
            "hydrolog=http://127.0.0.1:8070/",
            '["http://127.0.0.1:8070/"]',
            '{"Hydrolog": "http://127.0.0.1:8070/"}',
            '{"": "http://127.0.0.1:8070/"}',
            '{"hydrolog": 8070}',
            '{"hydrolog": "127.0.0.1:8070"}',
            '{"hydrolog": "hydrolog/"}',
            '{"hydrolog": "//elsewhere.example/"}',
            '{"hydrolog": "http:///hydrolog/"}',
            '{"hydrolog": "ftp://127.0.0.1/"}',
            '{"hydrolog": "javascript:alert(1)"}',
        ],
        ids=[
            "not-json",
            "not-an-object",
            "name-not-lower-case",
            "empty-name",
            "address-not-text",
            "address-without-scheme",
            "relative-path",
            "another-host-by-path",
            "url-without-host",
            "ftp",
            "javascript",
        ],
    )
    def test_value_the_menu_cannot_use_is_refused(self, value):
        with pytest.raises(ValueError, match="HYDROGRAF_GUI"):
            gui_table(value)

    def test_settings_refuse_a_bad_table_when_they_load(self, monkeypatch):
        monkeypatch.setenv("HYDROGRAF_GUI", '{"hydrolog": "127.0.0.1:8070"}')

        with pytest.raises(ValidationError, match="HYDROGRAF_GUI"):
            Settings()

    def test_settings_read_the_table_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("HYDROGRAF_GUI", TABLE)

        assert gui_table(Settings().hydrograf_gui) == gui_table(TABLE)


class TestGuiRoute:
    def _get(self, monkeypatch, value):
        settings = Settings(hydrograf_gui=value)
        monkeypatch.setattr(api.endpoints.gui, "get_settings", lambda: settings)
        return TestClient(app).get("/api/gui")

    def test_route_serves_the_table(self, monkeypatch):
        response = self._get(monkeypatch, TABLE)

        assert response.status_code == 200
        assert response.json() == gui_table(TABLE)

    def test_route_without_the_variable_serves_an_empty_table(self, monkeypatch):
        response = self._get(monkeypatch, "")

        assert response.status_code == 200
        assert response.json() == {}
