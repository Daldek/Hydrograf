"""
The lines the providers' terms require on every product made with their data.

Hydrograf's provider data are the PMAXTP precipitation quantiles of IMGW-PIB, which the
preprocessing fetches through Obserwator into ``precipitation_data``, and the GUGiK
products NMT and BDOT10k and ISRIC's SoilGrids, which it fetches through Kartograf and
processes into every layer of the map and every result: the DEM, burned with the
BDOT10k watercourses, gives the flow, the catchments and every delineation; BDOT10k
gives the land cover, the water bodies and the stream lines; SoilGrids, with the
BDOT10k wetlands as group D, the soil groups; land cover and soil groups the CN.

Every product made with PMAXTP data, the design depth, the hyetograph, the hydrograph,
their exports and the hand-off, carries the lines of DEV-20.2 of Nogat's standard in
``attribution`` (the source with the address of the PMAXTP page, the note that the data
were processed and the monograph of the project) and the link to the PMAXTP terms of
DEV-20.7 in ``terms_notice``, byte for byte (ECO-060; ECO-065: linked, never restated).
Every product made with GUGiK or SoilGrids data carries G or SG (DEV §20, Nogat's plan
``2026-11-13-terms-fix``): G names the GUGiK products used, the years their data were
created and the days they were downloaded, from the Kartograf metadata of the files
(``core.data_sources``); SG names ISRIC and the licence. Neither has a terms line.

This module is the one place of the lines in the code (DEV-20.4): the API responses
carry them and the front end shows and exports what a response carries; the strip of
the view draws the short forms GK and SK from G and SG itself (Nogat's kit). The user
guide (``frontend/instrukcja/index.html``) and the slides
(``docs/Hydrograf-prezentacja.html``) quote the PMAXTP lines under their screenshots
of PMAXTP results.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from core.data_sources import BDOT10K, NMT, SOILGRIDS, ProductDates, read_data_sources

# PS: the source, with the address of the PMAXTP page (ust. 1 of the PMAXTP terms)
PMAXTP_SOURCE: Final = (
    "Źródłem pochodzenia danych jest Instytut Meteorologii i Gospodarki Wodnej – "
    "Państwowy Instytut Badawczy, dane pochodzą ze strony "
    "https://klimat.imgw.pl/opady-maksymalne"
)
# PP: the data were processed (ust. 2), as every depth, hyetograph and hydrograph is
PMAXTP_PROCESSED: Final = (
    "Dane Instytutu Meteorologii i Gospodarki Wodnej – Państwowego Instytutu "
    "Badawczego pochodzące ze strony https://klimat.imgw.pl/opady-maksymalne zostały "
    "przetworzone"
)
# M: the monograph of the project (ust. 1)
PMAXTP_MONOGRAPH: Final = (
    "„Modele probabilistyczne opadów maksymalnych o określonym czasie trwania i "
    "prawdopodobieństwie przewyższenia – Projekt PMAXTP”, red. Bogdan "
    "Ozga-Zieliński, Instytut Meteorologii i Gospodarki Wodnej – Państwowy Instytut "
    "Badawczy, Warszawa 2022"
)
# RK: the link to the PMAXTP terms (DEV-20.7)
PMAXTP_TERMS: Final = "Regulamin danych PMAXTP: https://klimat.imgw.pl/opady-maksymalne"
# G: the source of GUGiK data, with the products used, the years in which their data
# were created and the days on which they were downloaded (DEV §20)
GUGIK_SOURCE: Final = (
    "Źródło: Główny Urząd Geodezji i Kartografii – GUGiK, {products} "
    "(wytworzono {period}, pozyskano {date}); dane przetworzone"
)
# SG: the source of SoilGrids data, with its licence (DEV §20)
SOILGRIDS_SOURCE: Final = (
    "Źródło: ISRIC – World Soil Information, SoilGrids, licencja CC BY 4.0 "
    "(https://creativecommons.org/licenses/by/4.0/); dane przetworzone"
)
# The period or day of G that no metadata of the files gives („brak danych”)
UNKNOWN: Final = "b.d."

# What each kind of Hydrograf's data is made from. GUGiK's products in the order G
# names them
GUGIK_PRODUCTS: Final = (NMT, BDOT10K)
# Elevations and slopes of the NMT, and the depressions of the unburned NMT
ELEVATION: Final = frozenset({NMT})
# The flow of the NMT burned with the BDOT10k watercourses: flow directions, streams,
# catchments, delineations, flow paths and the morphometry of a catchment
DRAINAGE: Final = frozenset({NMT, BDOT10K})
# BDOT10k objects: the land cover, the water bodies and the stream lines
TOPOGRAPHY: Final = frozenset({BDOT10K})
# The soil groups of SoilGrids, the BDOT10k wetlands made group D (ADR-078)
SOILS: Final = frozenset({SOILGRIDS, BDOT10K})
# A catchment with its parameters: morphometry, land cover, soil groups and CN
CATCHMENT: Final = DRAINAGE | TOPOGRAPHY | SOILS
# The kinds of the map's layers by the names the front end asks for (GET /api/terms)
LAYER_KINDS: Final = {
    "elevation": ELEVATION,
    "drainage": DRAINAGE,
    "topography": TOPOGRAPHY,
    "soils": SOILS,
}

# A terms line names the terms it links: „Regulamin <whose terms>: <address>” (DEV §20)
_TERMS_LINE = re.compile(r"Regulamin [^:]+: \S+")


@dataclass(frozen=True)
class ProviderLines:
    """The lines a product carries for the providers of its data.

    Attributes
    ----------
    attribution : tuple[str, ...]
        The attribution lines, in the order of DEV-20.4; empty without provider data.
    terms_notice : tuple[str, ...]
        The links to the terms that apply (DEV-20.7), shown right after the
        attribution; empty without IMGW-PIB data.
    """

    attribution: tuple[str, ...] = ()
    terms_notice: tuple[str, ...] = ()


# A product of Hydrograf's own data or of the user's: no line
NO_PROVIDER: Final = ProviderLines()

# A product made with PMAXTP data: Hydrograf always processes them (DEV-20.2)
PMAXTP: Final = ProviderLines(
    attribution=(PMAXTP_SOURCE, PMAXTP_PROCESSED, PMAXTP_MONOGRAPH),
    terms_notice=(PMAXTP_TERMS,),
)


def merge(lines: Iterable[ProviderLines]) -> ProviderLines:
    """Return the lines of a product with the data of several products.

    Every line once, in the order it first comes (DEV-20.6).

    Parameters
    ----------
    lines : Iterable[ProviderLines]
        The lines of the products whose data the product holds.

    Returns
    -------
    ProviderLines
        Their union.
    """
    items = list(lines)
    return ProviderLines(
        attribution=tuple(dict.fromkeys(a for i in items for a in i.attribution)),
        terms_notice=tuple(dict.fromkeys(n for i in items for n in i.terms_notice)),
    )


def is_terms(line: str) -> bool:
    """Tell a terms line of DEV-20.7 (RD, RH, RK) from an attribution line."""
    return _TERMS_LINE.fullmatch(line) is not None


def _span(values: Iterable[str], dash: str) -> str:
    """Return one value, or the first and the last joined by ``dash``; else UNKNOWN."""
    ordered = sorted(set(values))
    if not ordered:
        return UNKNOWN
    if len(ordered) == 1:
        return ordered[0]
    return f"{ordered[0]}{dash}{ordered[-1]}"


def gugik_source(products: Iterable[str], dates: Mapping[str, ProductDates]) -> str:
    """Return G for GUGiK products with the dates of their files.

    Parameters
    ----------
    products : Iterable[str]
        The GUGiK products used, named in the order of ``GUGIK_PRODUCTS``.
    dates : Mapping[str, ProductDates]
        When the files of each product were created and downloaded; a product
        without an entry adds no date.

    Returns
    -------
    str
        G with ``<products>`` joined by „, ”, ``<period>`` one year or the first and
        the last year joined by an en dash („2020–2025”) and ``<date>`` one day or
        the first and the last day joined by a spaced en dash („2026-03-24 –
        2026-10-29”); a period or day that no metadata gives reads UNKNOWN.
    """
    named = [p for p in GUGIK_PRODUCTS if p in set(products)]
    entries = [dates[p] for p in named if p in dates]
    return GUGIK_SOURCE.format(
        products=", ".join(named),
        period=_span((str(year) for e in entries for year in e.created), "–"),
        date=_span((day for e in entries for day in e.acquired), " – "),
    )


def data_lines(
    uses: Iterable[str], dates: Mapping[str, ProductDates] | None
) -> ProviderLines:
    """Return the lines of a product made with GUGiK or SoilGrids data.

    Parameters
    ----------
    uses : Iterable[str]
        The products whose data the product holds (``NMT``, ``BDOT10K``,
        ``SOILGRIDS``), e.g. a kind of data such as ``CATCHMENT``.
    dates : Mapping[str, ProductDates] or None
        The products the instance's data were made from (``instance.json``): a
        product they do not name is not among the data, so it takes no line. None
        when the instance names none: every product used takes its line, G with
        UNKNOWN dates.

    Returns
    -------
    ProviderLines
        G for the GUGiK products used, then SG with SoilGrids, in the order of
        DEV-20.4; no terms line (G and SG need none).
    """
    used = set(uses)
    if dates is not None:
        used &= set(dates)
    attribution = []
    if used & set(GUGIK_PRODUCTS):
        attribution.append(gugik_source(used, dates or {}))
    if SOILGRIDS in used:
        attribution.append(SOILGRIDS_SOURCE)
    return ProviderLines(attribution=tuple(attribution))


def instance_lines(uses: Iterable[str], frontend_data_dir: str) -> ProviderLines:
    """Return ``data_lines`` with the dates of ``<frontend_data_dir>/instance.json``.

    Parameters
    ----------
    uses : Iterable[str]
        The products whose data the product holds.
    frontend_data_dir : str
        The directory served under ``/data/`` (``Settings.frontend_data_dir``).
    """
    return data_lines(uses, read_data_sources(frontend_data_dir))
