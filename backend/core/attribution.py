"""
The lines the providers' terms require on every product made with their data.

Hydrograf's provider data are the PMAXTP precipitation quantiles of IMGW-PIB, which the
preprocessing fetches through Obserwator into ``precipitation_data``. Every product made
with them, the design depth, the hyetograph, the hydrograph, their exports and the
hand-off, carries the lines of DEV-20.2 of Nogat's standard in ``attribution`` (the
source with the address of the PMAXTP page, the note that the data were processed and
the monograph of the project) and the link to the PMAXTP terms of DEV-20.7 in
``terms_notice``, byte for byte (ECO-060; ECO-065: linked, never restated).

This module is the one place of the lines in the code (DEV-20.4): the API responses
carry them and the front end shows and exports what a response carries. The user
guide (``frontend/instrukcja/index.html``) and the slides
(``docs/Hydrograf-prezentacja.html``) quote them under their screenshots of PMAXTP
results.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

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
