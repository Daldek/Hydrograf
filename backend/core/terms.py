"""The regulamin of a deployment open to others (Nogat DEV-15.7, DEV-18.1; ADR-084).

A deployment that anyone uses without signing in names its operator in the table
``operator`` of ``[nogat]`` in its ``nogat.toml`` (NOGAT_CONFIG). Hydrograf then fills
the kit's template ``nogat-terms.html`` (Nogat's GUI kit, copied byte for byte into
``frontend/nogat/``) once per process and serves it at ``/regulamin.html``; the front
end links it in the footer of the map, in the guide and in the app menu
(``GET /api/terms``). Without the table, with a value missing, or with the template
missing, there is neither page nor link: a local run is no service offered to others.

Filling follows Nogat's ``design/README.md`` (its reference is ``fill`` of
``scripts/terms.py``): first the blocks, then the fields. The blocks kept are the data
sources Hydrograf shows (README, "Data and licensing"); ``imgw-terms`` follows from
``pmaxtp``. Every value is HTML-escaped.
"""

import datetime
import html
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from core.config import Settings, deployment_gui, get_settings, nogat_table

logger = logging.getLogger(__name__)

# Where the page is served, beside the start page; the front end links this address
URL = "/regulamin.html"

# The kit of the front end: frontend/nogat/ beside backend/ in a checkout, and the same
# directory mounted at /frontend/nogat beside /app in the API container
KIT_DIR = Path(__file__).resolve().parents[2] / "frontend" / "nogat"
TEMPLATE = "nogat-terms.html"

# The project's own values (DEV-15.7): its registry name, the licence of
# backend/pyproject.toml, its repository in Nogat's ecosystem.yaml and the addresses of
# its tokens and kit relative to the page
PROJECT_VALUES: Mapping[str, str] = {
    "service_name": "Hydrograf",
    "software_licence": "MIT",
    "source_url": "https://github.com/Daldek/Hydrograf",
    "tokens_href": "css/tokens.css",
    "kit_href": "nogat/",
}

# The blocks of Hydrograf's data sources: PMAXTP (hydrographs), GUGiK (NMT, BDOT10k,
# the grey OSM basemap), Copernicus (CORINE), ISRIC (SoilGrids), Wody Polskie (the MZP
# overlay), OpenStreetMap (OpenFreeMap and the geoportal basemap) and Esri (orthophoto)
BLOCKS = ("pmaxtp", "gugik", "copernicus", "isric", "wody-polskie", "osm", "esri")

# A key of [nogat.operator] -> the field of the template it fills
OPERATOR_FIELDS: Mapping[str, str] = {
    "name": "operator_name",
    "email": "operator_email",
    "terms_effective": "terms_effective",
    "processor": "processor",
    "processor_transfer": "processor_transfer",
    "processor_cookie": "processor_cookie",
    "mail_provider": "mail_provider",
    "mail_transfer": "mail_transfer",
}
# The only fields that may be empty (each a whole sentence or nothing)
OPTIONAL = frozenset({"processor_transfer", "processor_cookie", "mail_transfer"})
# Blocks that keep the block `imgw-terms`, which is never listed itself
IMGW_BLOCKS = frozenset({"imgw", "imgw-hydro", "pmaxtp"})

_PLACEHOLDER = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
_BLOCK = re.compile(
    r"^<!-- block: (?P<name>[a-z][a-z0-9-]*) -->\n(?P<body>.*?)^<!-- /block -->\n",
    re.MULTILINE | re.DOTALL,
)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class Terms:
    """The filled regulamin of the deployment.

    Attributes
    ----------
    page : str
        The HTML page served at ``URL``.
    operator_email : str
        The operator's e-mail, which the form „Zgłoś uwagę” names (DEV-15.12).
    """

    page: str
    operator_email: str


def fill(template: str, values: Mapping[str, str], listed: Iterable[str]) -> str:
    """Return the template with its blocks chosen and its fields filled.

    A block named in ``listed`` keeps its lines without its two marker lines; any
    other block goes with its markers (``imgw-terms`` stays with ``imgw``,
    ``imgw-hydro`` or ``pmaxtp``). Each ``{{name}}`` becomes its value, HTML-escaped.

    Raises
    ------
    ValueError
        When a field has no value, a value outside ``OPTIONAL`` is empty, or a ``{{``
        is left in the page.
    """
    keep = set(listed)
    if keep & IMGW_BLOCKS:
        keep.add("imgw-terms")
    missing = sorted(
        name
        for name in set(_PLACEHOLDER.findall(template))
        if name not in values or (name not in OPTIONAL and not values[name].strip())
    )
    if missing:
        raise ValueError(f"no value for {', '.join(missing)}")
    text = _BLOCK.sub(lambda m: m["body"] if m["name"] in keep else "", template)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = _PLACEHOLDER.sub(lambda m: html.escape(values[m[1]]), text)
    if "{{" in text:
        raise ValueError("a {{ is left in the page")
    return text


def operator_values(table: Mapping[str, Any]) -> dict[str, str]:
    """Return the fields of the template that ``[nogat.operator]`` gives.

    ``terms_effective`` is a TOML date or a ``YYYY-MM-DD`` text; every other value is
    text. A key the table lacks is left out, so ``fill`` names it.

    Raises
    ------
    TypeError
        When a value is not text (or a date for ``terms_effective``).
    ValueError
        When ``terms_effective`` is no date.
    """
    values: dict[str, str] = {}
    for key, field in OPERATOR_FIELDS.items():
        if key not in table:
            continue
        value = table[key]
        if key == "terms_effective":
            if isinstance(value, datetime.date) and not isinstance(
                value, datetime.datetime
            ):
                value = value.isoformat()
            if not isinstance(value, str):
                raise TypeError("terms_effective must be a date, e.g. 2026-11-20")
            if not _DATE.fullmatch(value):
                raise ValueError("terms_effective must be a date, e.g. 2026-11-20")
        elif not isinstance(value, str):
            raise TypeError(f"{key} must be text")
        values[field] = value
    return values


def build_terms(settings: Settings, kit_dir: Path = KIT_DIR) -> Terms | None:
    """Fill the regulamin of the deployment described by ``settings``.

    Returns
    -------
    Terms or None
        None without ``[nogat.operator]`` (a local run), and when the regulamin cannot
        be filled: a value missing or invalid, no address of Hydrograf in the table
        ``gui``, no template. The cause is logged; values never are.
    """
    table = nogat_table(settings.nogat_config).get("operator")
    if table is None:
        logger.info("No [nogat.operator] in nogat.toml: no regulamin is served")
        return None
    if not isinstance(table, dict):
        logger.warning("[nogat.operator] of nogat.toml is not a table: no regulamin")
        return None
    try:
        values = {
            **PROJECT_VALUES,
            **operator_values(table),
            "service_url": deployment_gui(settings).get("hydrograf", ""),
        }
        template = (kit_dir / TEMPLATE).read_text(encoding="utf-8")
        page = fill(template, values, BLOCKS)
    except (OSError, TypeError, ValueError) as error:
        logger.warning("The regulamin cannot be filled, none is served: %s", error)
        return None
    logger.info("The regulamin is served at %s", URL)
    return Terms(page=page, operator_email=values["operator_email"])


@cache
def current_terms() -> Terms | None:
    """Return the regulamin of this process's deployment, filled on the first call."""
    return build_terms(get_settings())
