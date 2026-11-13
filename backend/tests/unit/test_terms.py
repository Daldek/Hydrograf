"""
The regulamin of a deployment (core/terms.py; Nogat DEV-15.7, DEV-18.1; ADR-084).

The kit's template is filled from `[nogat.operator]` and the entry `hydrograf` of the
table `gui`: the blocks of Hydrograf's data sources stay, the others go, every value is
escaped, and a value missing means no page at all.
"""

import logging

import pytest

from core.config import Settings, nogat_table
from core.terms import BLOCKS, KIT_DIR, TEMPLATE, build_terms, fill

OPERATOR = """
[nogat]
gui = { hydrograf = "https://hydrograf.example/", hydrolog = "https://hl.example/" }

[nogat.operator]
name = "Jan Kowalski"
email = "kontakt@example.pl"
terms_effective = 2026-11-20
processor = "Cloudflare, Inc."
processor_transfer = "Dane mogą być przekazywane do USA."
processor_cookie = ""
mail_provider = "Poczta <Example>"
mail_transfer = ""
"""


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    """Return the Settings of a deployment with the given nogat.toml."""
    monkeypatch.delenv("HYDROGRAF_GUI", raising=False)

    def settings(text: str, hydrograf_gui: str = "") -> Settings:
        path = tmp_path / "nogat.toml"
        path.write_text(text, encoding="utf-8")
        return Settings(nogat_config=str(path), hydrograf_gui=hydrograf_gui)

    nogat_table.cache_clear()
    yield settings
    nogat_table.cache_clear()


class TestFill:
    TEMPLATE = (
        "<h1>{{service_name}}</h1>\n"
        "<!-- block: gugik -->\n<h3>GUGiK</h3>\n<!-- /block -->\n"
        "<!-- block: chmi -->\n<h3>ČHMÚ</h3>\n<!-- /block -->\n"
        "<!-- block: pmaxtp -->\n<h3>PMAXTP</h3>\n<!-- /block -->\n"
        "<p>{{processor_transfer}}</p>\n"
    )

    def test_listed_blocks_stay_without_markers_and_the_others_go(self):
        page = fill(
            self.TEMPLATE,
            {"service_name": "Hydrograf", "processor_transfer": ""},
            ["gugik"],
        )

        assert page == "<h1>Hydrograf</h1>\n<h3>GUGiK</h3>\n<p></p>\n"

    def test_values_are_escaped(self):
        page = fill(
            self.TEMPLATE,
            {"service_name": '<b>"H" & H</b>', "processor_transfer": ""},
            [],
        )

        assert "<h1>&lt;b&gt;&quot;H&quot; &amp; H&lt;/b&gt;</h1>" in page

    @pytest.mark.parametrize(
        "values",
        [{"processor_transfer": ""}, {"service_name": " ", "processor_transfer": ""}],
        ids=["missing", "empty"],
    )
    def test_a_required_value_missing_or_empty_is_refused(self, values):
        with pytest.raises(ValueError, match="service_name"):
            fill(self.TEMPLATE, values, [])


def test_the_kit_template_has_every_block_hydrograf_keeps():
    """A block renamed in a new kit would drop a data source from the page unseen."""
    template = (KIT_DIR / TEMPLATE).read_text(encoding="utf-8")

    for name in BLOCKS:
        assert f"<!-- block: {name} -->" in template, name


class TestBuildTerms:
    def test_page_of_the_deployment(self, deployment):
        terms = build_terms(deployment(OPERATOR))

        assert terms is not None
        assert terms.operator_email == "kontakt@example.pl"
        page = terms.page
        assert "<h1>Regulamin serwisu Hydrograf</h1>" in page
        assert "Wersja 1.0, obowiązuje od 2026-11-20" in page
        assert "Serwis prowadzi Jan Kowalski" in page
        assert "https://hydrograf.example/" in page
        assert "w usłudze Poczta &lt;Example&gt;." in page
        assert "Dane mogą być przekazywane do USA." in page
        assert "na licencji MIT" in page
        for heading in (
            "IMGW-PIB: opady maksymalne PMAXTP",
            "GUGiK",
            "Copernicus",
            "ISRIC SoilGrids",
            "Wody Polskie",
            "OpenStreetMap (kafelki OpenFreeMap, podkład OSM serwisu geoportal.gov.pl)",
            "Esri World Imagery",
        ):
            assert f"<h3>{heading}</h3>" in page, heading
        # The PMAXTP block links the terms in RK's words, and restates none (ECO-065)
        assert (
            'Regulamin danych PMAXTP: <a href="https://klimat.imgw.pl/opady-maksymalne">'
            in page
        )
        assert "nieodpłatnie" not in page
        for heading in ("IMGW-PIB: dane publiczne", "ČHMÚ", "ČÚZK"):
            assert f"<h3>{heading}</h3>" not in page, heading
        assert "{{" not in page
        assert "<!-- block" not in page

    def test_no_operator_no_page(self, deployment):
        assert build_terms(deployment('[nogat]\ngui = {hydrograf = "/"}\n')) is None

    def test_no_file_no_page(self):
        assert build_terms(Settings(nogat_config="")) is None

    def test_a_value_missing_means_no_page_and_the_log_names_no_value(
        self, deployment, caplog
    ):
        text = OPERATOR.replace('email = "kontakt@example.pl"\n', "")

        with caplog.at_level(logging.WARNING, logger="core.terms"):
            assert build_terms(deployment(text)) is None

        assert "operator_email" in caplog.text
        assert "Jan Kowalski" not in caplog.text

    def test_without_the_address_of_hydrograf_no_page(self, deployment):
        text = OPERATOR.replace('hydrograf = "https://hydrograf.example/", ', "")

        assert build_terms(deployment(text)) is None

    def test_hydrograf_gui_names_the_address_before_the_file(self, deployment):
        settings = deployment(
            OPERATOR, hydrograf_gui='{"hydrograf": "https://hydroni.example/"}'
        )

        terms = build_terms(settings)

        assert terms is not None
        assert "https://hydroni.example/" in terms.page
        assert "https://hydrograf.example/" not in terms.page

    @pytest.mark.parametrize(
        ("value", "served"),
        [('"2026-11-20"', True), ('"20.11.2026"', False), ("20261120", False)],
        ids=["text-date", "other-format", "number"],
    )
    def test_terms_effective_is_a_date(self, deployment, value, served):
        text = OPERATOR.replace(
            "terms_effective = 2026-11-20", f"terms_effective = {value}"
        )

        assert (build_terms(deployment(text)) is not None) is served
