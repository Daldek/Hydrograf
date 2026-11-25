"""
The base maps a deployment offers (core/basemaps.py; Nogat DEV-15.15, DEV-18.1;
ADR-089).

The page gets the kit's catalogue entries the setting `basemaps` allows, as the
catalogue writes them but for the deployment's copies (`basemap_mirrors`), then the
deployment's own base maps (`basemap_extra`); a wrong setting is an error that names
the option, the value and where it was read.
"""

import json
from typing import Any

import pytest

from core.basemaps import basemap_blocks, catalogue, deployment_basemaps
from core.config import KIT_DIR, Settings, nogat_table
from core.errors import FileOperationError, InvalidSettingError

ENTRIES = json.loads((KIT_DIR / "nogat-basemaps.json").read_text(encoding="utf-8"))[
    "entries"
]
IDS = [entry["id"] for entry in ENTRIES]
EXTRA = """
[[nogat.basemap_extra]]
id = "{id}"
name = "Mapa gminy"
kind = "xyz"
url = "https://tiles.gmina.example/{{z}}/{{x}}/{{y}}.png"
attribution = "© Gmina"
"""


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """Return the base maps of a deployment with the given nogat.toml and settings."""
    monkeypatch.delenv("HYDROGRAF_BASEMAPS", raising=False)
    monkeypatch.delenv("NOGAT_BASEMAPS", raising=False)

    def basemaps(text: str = "", **settings: Any) -> list[dict[str, Any]]:
        path = tmp_path / "nogat.toml"
        path.write_text(text, encoding="utf-8")
        return deployment_basemaps(Settings(nogat_config=str(path), **settings))

    nogat_table.cache_clear()
    yield basemaps
    nogat_table.cache_clear()


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [entry["id"] for entry in entries]


def _refusal(deployment, text: str = "", **settings: Any) -> dict[str, Any]:
    """The details of the error the settings raise."""
    with pytest.raises(InvalidSettingError) as caught:
        deployment(text, **settings)
    assert caught.value.code == "validation_error"
    return caught.value.details


class TestCatalogue:
    def test_entries_of_the_kit_in_order(self):
        assert catalogue() == ENTRIES
        assert IDS == ["openfreemap", "gugik-osm", "gugik-ortho"]

    @pytest.mark.parametrize("content", [None, "{", '{"entries": 3}', "[]"])
    def test_an_unreadable_catalogue_is_an_io_error(self, tmp_path, content):
        if content is not None:
            (tmp_path / "nogat-basemaps.json").write_text(content, encoding="utf-8")

        with pytest.raises(FileOperationError) as caught:
            catalogue(tmp_path)

        assert caught.value.code == "io_error"
        assert caught.value.details["path"] == str(tmp_path / "nogat-basemaps.json")


class TestAllowed:
    def test_default_is_every_entry_unchanged_and_in_order(self, deployment):
        assert deployment() == ENTRIES

    @pytest.mark.parametrize(
        ("text", "settings", "expected"),
        [
            (
                '[hydrograf]\nbasemaps = ["gugik-osm"]\n'
                '[nogat]\nbasemaps = ["gugik-ortho"]\n',
                {"hydrograf_basemaps": "openfreemap", "nogat_basemaps": "gugik-osm"},
                ["openfreemap"],
            ),
            (
                '[hydrograf]\nbasemaps = ["openfreemap"]\n',
                {"nogat_basemaps": "gugik-ortho"},
                ["gugik-ortho"],
            ),
            (
                '[hydrograf]\nbasemaps = ["gugik-osm"]\n'
                '[nogat]\nbasemaps = ["gugik-ortho"]\n',
                {},
                ["gugik-osm"],
            ),
            ('[nogat]\nbasemaps = ["gugik-ortho"]\n', {}, ["gugik-ortho"]),
        ],
        ids=["HYDROGRAF_BASEMAPS", "NOGAT_BASEMAPS", "[hydrograf]", "[nogat]"],
    )
    def test_each_source_comes_before_the_later_ones(
        self, deployment, text, settings, expected
    ):
        assert _ids(deployment(text, **settings)) == expected

    def test_the_catalogue_order_whatever_the_order_given(self, deployment):
        entries = deployment(hydrograf_basemaps=" gugik-ortho , openfreemap ")

        assert _ids(entries) == ["openfreemap", "gugik-ortho"]

    def test_an_empty_variable_offers_none(self, deployment):
        assert (
            deployment('[nogat]\nbasemaps = ["openfreemap"]\n', nogat_basemaps="") == []
        )

    def test_an_empty_list_offers_none(self, deployment):
        assert deployment("[nogat]\nbasemaps = []\n") == []

    def test_an_unknown_id_is_refused_with_its_source(self, deployment):
        with pytest.raises(InvalidSettingError) as caught:
            deployment(hydrograf_basemaps="openfreemap,esri")

        document = caught.value.document()
        assert document["code"] == "validation_error"
        assert document["details"] == {
            "reason": "unknown_basemap",
            "option": "basemaps",
            "value": "esri",
            "source": "HYDROGRAF_BASEMAPS",
            "known": IDS,
        }
        assert document["hint"] == (
            "Use the ids of the catalogue: openfreemap, gugik-osm, gugik-ortho."
        )

    def test_an_unknown_id_of_the_file_names_its_section(self, deployment):
        details = _refusal(deployment, '[hydrograf]\nbasemaps = ["osm"]\n')

        assert (details["value"], details["source"]) == (
            "osm",
            "[hydrograf] of nogat.toml",
        )

    @pytest.mark.parametrize(
        ("value", "shown"),
        [
            ('"openfreemap"', "'openfreemap'"),
            ('["openfreemap", 1]', "['openfreemap', 1]"),
        ],
        ids=["text", "not-all-texts"],
    )
    def test_a_value_that_is_not_a_list_of_texts_is_refused(
        self, deployment, value, shown
    ):
        details = _refusal(deployment, f"[nogat]\nbasemaps = {value}\n")

        assert details == {
            "reason": "invalid_basemaps",
            "option": "basemaps",
            "value": shown,
            "source": "[nogat] of nogat.toml",
        }


class TestMirrors:
    def test_a_copy_replaces_the_address_and_its_origin(self, deployment):
        entries = deployment(
            "[nogat]\nbasemap_mirrors = { openfreemap = "
            '"HTTPS://Tiles.Example.ORG:8443/planet", gugik-ortho = '
            '"https://ortho.example.org:443/{z}/{x}/{y}.jpg" }\n'
        )

        mirrored = {entry["id"]: entry for entry in entries}
        assert mirrored["openfreemap"] == {
            **ENTRIES[0],
            "url": "HTTPS://Tiles.Example.ORG:8443/planet",
            "origin": "https://tiles.example.org:8443",
        }
        assert mirrored["gugik-ortho"]["origin"] == "https://ortho.example.org"
        assert mirrored["gugik-osm"] == ENTRIES[1]

    def test_an_ipv6_copy_keeps_its_brackets(self, deployment):
        entries = deployment(
            '[nogat]\nbasemap_mirrors = { gugik-osm = "http://[::1]:8081/{z}.png" }\n'
        )

        assert entries[1]["origin"] == "http://[::1]:8081"

    def test_the_table_of_hydrograf_replaces_that_of_nogat(self, deployment):
        entries = deployment(
            '[hydrograf]\nbasemap_mirrors = { gugik-osm = "https://a.example/t" }\n'
            '[nogat]\nbasemap_mirrors = { openfreemap = "https://b.example/t" }\n'
        )

        assert entries[0] == ENTRIES[0]
        assert entries[1]["url"] == "https://a.example/t"

    def test_a_copy_of_a_base_map_not_offered_is_ignored(self, deployment):
        entries = deployment(
            '[nogat]\nbasemaps = ["openfreemap"]\n'
            'basemap_mirrors = { gugik-osm = "https://a.example/t" }\n'
        )

        assert entries == [ENTRIES[0]]

    def test_an_unknown_id_is_refused(self, deployment):
        details = _refusal(
            deployment, '[nogat]\nbasemap_mirrors = { esri = "https://a.example/t" }\n'
        )

        assert (details["reason"], details["option"], details["value"]) == (
            "unknown_basemap",
            "basemap_mirrors",
            "esri",
        )

    @pytest.mark.parametrize(
        ("value", "shown"),
        [
            ('"ftp://a.example/t"', "ftp://a.example/t"),
            ('"https:///t"', "https:///t"),
            ('"/tiles/{z}"', "/tiles/{z}"),
            ('"https://a.example:99999/t"', "https://a.example:99999/t"),
            ("3", "3"),
        ],
        ids=["ftp", "no-host", "path", "bad-port", "number"],
    )
    def test_an_address_that_is_no_web_url_is_refused(self, deployment, value, shown):
        details = _refusal(
            deployment, f"[hydrograf]\nbasemap_mirrors = {{ openfreemap = {value} }}\n"
        )

        assert details == {
            "reason": "invalid_basemap_mirrors",
            "option": "basemap_mirrors",
            "value": shown,
            "source": "[hydrograf] of nogat.toml",
        }

    def test_a_value_that_is_no_table_is_refused(self, deployment):
        details = _refusal(
            deployment, '[nogat]\nbasemap_mirrors = ["https://a.example"]\n'
        )

        assert details["value"] == "['https://a.example']"


class TestExtra:
    def test_own_base_maps_follow_the_catalogue(self, deployment):
        entries = deployment(
            '[nogat]\nbasemaps = ["gugik-ortho"]\n'
            "[[nogat.basemap_extra]]\n"
            'id = "gmina"\nname = "Mapa gminy"\nkind = "xyz"\n'
            'url = "https://tiles.gmina.example/{z}/{x}/{y}.png"\n'
            'attribution = "© Gmina"\n'
            "[[nogat.basemap_extra]]\n"
            'id = "wektor"\nname = "Wektor"\nkind = "vector"\n'
            'url = "https://Vec.Example/tiles.json"\nattribution = "© Vec"\n'
            "grayscale = true\n"
        )

        assert entries == [
            ENTRIES[2],
            {
                "id": "gmina",
                "label": "Mapa gminy",
                "kind": "raster",
                "url": "https://tiles.gmina.example/{z}/{x}/{y}.png",
                "origin": "https://tiles.gmina.example",
                "grey": False,
                "default": False,
                "credit": {"text": "© Gmina", "links": []},
            },
            {
                "id": "wektor",
                "label": "Wektor",
                "kind": "vector",
                "url": "https://Vec.Example/tiles.json",
                "origin": "https://vec.example",
                "grey": True,
                "default": False,
                "credit": {"text": "© Vec", "links": []},
            },
        ]

    def test_the_list_of_hydrograf_replaces_that_of_nogat(self, deployment):
        text = EXTRA.format(id="gmina") + EXTRA.format(id="powiat").replace(
            "nogat.", "hydrograf."
        )

        assert _ids(deployment(text)) == [*IDS, "powiat"]

    @pytest.mark.parametrize(
        ("url", "template"),
        [
            (
                "https://wms.example.org/wms?LAYERS=a&srs=EPSG:2180",
                "https://wms.example.org/wms?LAYERS=a&SERVICE=WMS&REQUEST=GetMap"
                "&VERSION=1.1.1&STYLES=&FORMAT=image%2Fpng&TRANSPARENT=TRUE"
                "&SRS=EPSG%3A3857&WIDTH=256&HEIGHT=256&BBOX={bbox-epsg-3857}",
            ),
            (
                "https://WMS.example.org:443/w?version=1.3.0&layers=b%20c&crs=EPSG:2180"
                "&bbox=1,2,3,4&width=10&Styles=s~t",
                "https://wms.example.org/w?version=1.3.0&layers=b+c&Styles=s%7Et"
                "&SERVICE=WMS&REQUEST=GetMap&FORMAT=image%2Fpng&TRANSPARENT=TRUE"
                "&CRS=EPSG%3A3857&WIDTH=256&HEIGHT=256&BBOX={bbox-epsg-3857}",
            ),
        ],
        ids=["1.1.1", "1.3.0"],
    )
    def test_a_wms_becomes_a_tile_template_as_in_archiwista(
        self, deployment, url, template
    ):
        text = EXTRA.format(id="wms").replace('"xyz"', '"wms"')
        text = text.replace("https://tiles.gmina.example/{z}/{x}/{y}.png", url)

        entry = deployment(text, nogat_basemaps="")[0]

        assert (entry["kind"], entry["url"]) == ("raster", template)

    @pytest.mark.parametrize(
        ("replace", "field", "shown"),
        [
            (('id = "gmina"', 'id = "openfreemap"'), "id", "openfreemap"),
            (('id = "gmina"', 'id = "none"'), "id", "none"),
            (('id = "gmina"', 'id = " "'), "id", " "),
            (('id = "gmina"', "id = 7"), "id", "7"),
            (('name = "Mapa gminy"', 'name = ""'), "name", ""),
            (('kind = "xyz"', 'kind = "wmts"'), "kind", "wmts"),
            (('kind = "xyz"', "kind = []"), "kind", "[]"),
            (
                (
                    'url = "https://tiles.gmina.example/{z}/{x}/{y}.png"',
                    'url = "tiles/{z}"',
                ),
                "url",
                "tiles/{z}",
            ),
            (('attribution = "© Gmina"', 'attribution = ""'), "attribution", ""),
            (
                (
                    'attribution = "© Gmina"',
                    'attribution = "© Gmina"\ngrayscale = "yes"',
                ),
                "grayscale",
                "'yes'",
            ),
            (
                ('attribution = "© Gmina"', 'attribution = "© Gmina"\nopacity = 0.5'),
                "opacity",
                "0.5",
            ),
        ],
        ids=[
            "catalogue-id",
            "none",
            "blank-id",
            "number-id",
            "empty-name",
            "unknown-kind",
            "list-kind",
            "relative-url",
            "empty-attribution",
            "text-grayscale",
            "unknown-key",
        ],
    )
    def test_a_wrong_value_is_refused(self, deployment, replace, field, shown):
        details = _refusal(deployment, EXTRA.format(id="gmina").replace(*replace))

        assert details == {
            "reason": "invalid_basemap_extra",
            "option": "basemap_extra",
            "field": field,
            "value": shown,
            "source": "[nogat] of nogat.toml",
        }

    def test_a_missing_attribution_is_refused(self, deployment):
        text = EXTRA.format(id="gmina").replace('attribution = "© Gmina"\n', "")

        with pytest.raises(InvalidSettingError) as caught:
            deployment(text)

        assert caught.value.message_id == "basemap_extra_missing"
        assert caught.value.details == {
            "reason": "invalid_basemap_extra",
            "option": "basemap_extra",
            "field": "attribution",
            "value": "gmina",
            "source": "[nogat] of nogat.toml",
        }

    def test_a_repeated_id_is_refused(self, deployment):
        details = _refusal(deployment, EXTRA.format(id="gmina") * 2)

        assert (details["field"], details["value"], details["source"]) == (
            "id",
            "gmina",
            "[nogat] of nogat.toml",
        )

    def test_a_value_that_is_no_list_of_tables_is_refused(self, deployment):
        details = _refusal(deployment, '[hydrograf]\nbasemap_extra = ["gmina"]\n')

        assert (details["field"], details["value"]) == ("basemap_extra", "'gmina'")


class TestBlocks:
    @pytest.mark.parametrize(
        ("basemaps", "blocks"),
        [
            (None, {"osm", "gugik"}),
            ("", set()),
            ("openfreemap", {"osm"}),
            ("gugik-ortho", {"gugik"}),
        ],
        ids=["default", "none", "openfreemap", "orthophoto"],
    )
    def test_the_blocks_of_the_base_maps_offered(self, deployment, basemaps, blocks):
        settings = {} if basemaps is None else {"hydrograf_basemaps": basemaps}

        assert basemap_blocks(deployment(**settings)) == blocks

    def test_own_base_maps_name_no_block(self, deployment):
        entries = deployment(EXTRA.format(id="gmina"), hydrograf_basemaps="")

        assert "blocks" not in entries[0]
        assert basemap_blocks(entries) == set()
