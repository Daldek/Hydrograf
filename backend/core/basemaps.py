"""The base maps the map offers (Nogat DEV-15.15, DEV-18.1; ADR-089).

Nogat's GUI kit lists the shared base maps in its catalogue ``nogat-basemaps.json``,
copied byte for byte into ``frontend/nogat/`` (DEV-15.6): for each its id, label, kind
(``vector`` or ``raster``), tile address and origin, zoom range and bounds, whether it
is grey, whether it is the default, its credit line, and the blocks of the regulamin
its data needs (``osm``, ``gugik``). A deployment chooses in its settings which of them
the page offers (``basemaps``), may serve copies of them from its own addresses
(``basemap_mirrors``) and may add base maps of its own (``basemap_extra``): the first
of HYDROGRAF_BASEMAPS and NOGAT_BASEMAPS, then the keys of ``[hydrograf]`` before those
of ``[nogat]`` in the ``nogat.toml`` of NOGAT_CONFIG (DEV-18.1).

The page gets the entries of ``deployment_basemaps`` from ``GET /api/v1/basemaps`` and
draws them with the kit's ``nogat-basemaps.js``; the regulamin keeps the blocks those
entries name (``basemap_blocks``, ``core.terms``). A wrong setting raises
``InvalidSettingError`` naming the option, the value and where it was read, and the API
does not start (``api.main``).
"""

import json
from collections.abc import Iterable, Mapping
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlsplit

from core.config import KIT_DIR, Settings, get_settings, nogat_table
from core.errors import FileOperationError, InvalidSettingError

CATALOGUE = "nogat-basemaps.json"

# The sections of nogat.toml read, in order, and how an error names them
_SECTIONS = (
    ("hydrograf", "[hydrograf] of nogat.toml"),
    ("nogat", "[nogat] of nogat.toml"),
)

# A kind of an own base map -> the kind of its entry for the page
EXTRA_KINDS: Mapping[str, str] = {"xyz": "raster", "wms": "raster", "vector": "vector"}
EXTRA_KEYS = ("id", "name", "kind", "url", "attribution", "grayscale")
_REQUIRED = ("id", "name", "kind", "url", "attribution")
# An id the page keeps for the choice "no base map"
_NO_BASEMAP = "none"

# The tile of a WMS base map, as Archiwista's `tileUrl` builds it (map/style.js)
TILE_PX = 256
WMS_DEFAULTS: Mapping[str, str] = {
    "SERVICE": "WMS",
    "REQUEST": "GetMap",
    "VERSION": "1.1.1",
    "STYLES": "",
    "FORMAT": "image/png",
    "TRANSPARENT": "TRUE",
}
_WMS_REPLACED = ("SRS", "CRS", "BBOX", "WIDTH", "HEIGHT")
_DEFAULT_PORTS = {"http": 80, "https": 443}


def catalogue(kit_dir: Path = KIT_DIR) -> list[dict[str, Any]]:
    """Return the entries of the kit's catalogue of base maps, in its order.

    Raises
    ------
    FileOperationError
        When ``nogat-basemaps.json`` cannot be read or has no list ``entries``.
    """
    path = kit_dir / CATALOGUE
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))["entries"]
        if not isinstance(entries, list):
            raise TypeError("entries is not a list")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise FileOperationError(
            "basemap_catalogue_unreadable",
            reason="basemap_catalogue_unreadable",
            path=str(path),
        ) from error
    return entries


def origin(address: str) -> str | None:
    """Return the origin of an http or https address, or None for any other.

    As ``new URL(address).origin`` of a browser: the scheme, the host in lower case
    (an IPv6 address in brackets) and the port unless it is the scheme's default.
    """
    if any(char.isspace() for char in address):
        return None
    try:
        parts = urlsplit(address)
        host = parts.hostname
        port = parts.port
        if parts.scheme not in _DEFAULT_PORTS or not host:
            return None
        if not host.isascii():
            host = host.encode("idna").decode("ascii")
    except ValueError:  # a port out of range, a bracket left open, a bad name
        return None
    if ":" in host:
        host = f"[{host}]"
    if port is None or port == _DEFAULT_PORTS[parts.scheme]:
        return f"{parts.scheme}://{host}"
    return f"{parts.scheme}://{host}:{port}"


def wms_template(address: str) -> str:
    """Return the tile template of a WMS address, as Archiwista's ``tileUrl``.

    The parameters of the address are kept; those of ``WMS_DEFAULTS`` it lacks (in
    any case) are added; SRS, CRS, BBOX, WIDTH and HEIGHT (in any case) go, then SRS,
    or CRS for a VERSION 1.3, is EPSG:3857 and the tile 256 by 256 px. MapLibre fills
    ``{bbox-epsg-3857}``, whose braces stay unencoded. The query is written as a
    browser's ``URLSearchParams``; a fragment, never sent, is left out.
    """
    parts = urlsplit(address)
    params = parse_qsl(parts.query, keep_blank_values=True)
    given = {name.upper() for name, _ in params}
    params += [
        (name, value) for name, value in WMS_DEFAULTS.items() if name not in given
    ]
    params = [
        (name, value) for name, value in params if name.upper() not in _WMS_REPLACED
    ]
    version = _first(params, "VERSION")
    if version is None:
        version = _first(params, "version")
    crs = "CRS" if (version or "1.1.1").startswith("1.3") else "SRS"
    params += [(crs, "EPSG:3857"), ("WIDTH", str(TILE_PX)), ("HEIGHT", str(TILE_PX))]
    query = "&".join(f"{_form(name)}={_form(value)}" for name, value in params)
    return f"{origin(address)}{parts.path or '/'}?{query}&BBOX={{bbox-epsg-3857}}"


def _first(params: list[tuple[str, str]], name: str) -> str | None:
    """Return the first value of ``name``, as ``URLSearchParams.get``."""
    return next((value for key, value in params if key == name), None)


def _form(text: str) -> str:
    """Encode a name or value as ``URLSearchParams`` does (form encoding)."""
    return quote_plus(text, safe="*").replace("~", "%7E")


def _text(value: object) -> str:
    """Return a value of a setting as the text an error names: text as it is."""
    return value if isinstance(value, str) else repr(value)


def _section_value(settings: Settings, key: str) -> tuple[Any, str] | None:
    """Return the value of ``key`` of the first section that has it, and its source."""
    for section, source in _SECTIONS:
        table = nogat_table(settings.nogat_config, section)
        if key in table:
            return table[key], source
    return None


def _checked_ids(
    ids: Iterable[str], known: list[str], option: str, source: str
) -> None:
    """Refuse an id that is not in the catalogue."""
    for basemap in ids:
        if basemap not in known:
            raise InvalidSettingError(
                "basemap_unknown",
                reason="unknown_basemap",
                option=option,
                value=basemap,
                source=source,
                known=known,
            )


def allowed_ids(settings: Settings, known: list[str]) -> set[str]:
    """Return the ids of the setting ``basemaps``; every id of ``known`` by default.

    Raises
    ------
    InvalidSettingError
        When an id is not in the catalogue, or the value of nogat.toml is no list of
        texts.
    """
    for variable, source in (
        (settings.hydrograf_basemaps, "HYDROGRAF_BASEMAPS"),
        (settings.nogat_basemaps, "NOGAT_BASEMAPS"),
    ):
        if variable is not None:
            ids = [part.strip() for part in variable.split(",") if part.strip()]
            _checked_ids(ids, known, "basemaps", source)
            return set(ids)
    found = _section_value(settings, "basemaps")
    if found is None:
        return set(known)
    value, source = found
    if not isinstance(value, list) or not all(isinstance(i, str) for i in value):
        raise InvalidSettingError(
            "basemaps_invalid",
            reason="invalid_basemaps",
            option="basemaps",
            value=repr(value),
            source=source,
        )
    _checked_ids(value, known, "basemaps", source)
    return set(value)


def mirrors(settings: Settings, known: list[str]) -> dict[str, str]:
    """Return the setting ``basemap_mirrors``: catalogue id -> the copy's address.

    The table of ``[hydrograf]`` when it has the key, else that of ``[nogat]``.

    Raises
    ------
    InvalidSettingError
        When it is no table, an id is not in the catalogue or an address is not an
        http or https URL with a host.
    """
    found = _section_value(settings, "basemap_mirrors")
    if found is None:
        return {}
    table, source = found
    if not isinstance(table, dict):
        raise InvalidSettingError(
            "basemap_mirrors_invalid",
            reason="invalid_basemap_mirrors",
            option="basemap_mirrors",
            value=repr(table),
            source=source,
        )
    _checked_ids(table, known, "basemap_mirrors", source)
    for address in table.values():
        if not isinstance(address, str) or origin(address) is None:
            raise InvalidSettingError(
                "basemap_mirrors_invalid",
                reason="invalid_basemap_mirrors",
                option="basemap_mirrors",
                value=_text(address),
                source=source,
            )
    return dict(table)


def _extra_error(field: str, value: str, source: str) -> InvalidSettingError:
    """Return the error of a wrong value of ``basemap_extra``."""
    return InvalidSettingError(
        "basemap_extra_invalid",
        reason="invalid_basemap_extra",
        option="basemap_extra",
        field=field,
        value=value,
        source=source,
    )


def _extra_entry(
    item: object, source: str, known: list[str], seen: set[str]
) -> dict[str, Any]:
    """Return the page's entry of one own base map of ``basemap_extra``, checked."""
    if not isinstance(item, dict):
        raise _extra_error("basemap_extra", repr(item), source)
    for key, value in item.items():
        if key not in EXTRA_KEYS:
            raise _extra_error(key, _text(value), source)
    for key in _REQUIRED:
        if key not in item:
            raise InvalidSettingError(
                "basemap_extra_missing",
                reason="invalid_basemap_extra",
                option="basemap_extra",
                field=key,
                value=_text(item["id"]) if "id" in item else repr(item),
                source=source,
            )
    basemap, kind, url = item["id"], item["kind"], item["url"]
    if (
        not isinstance(basemap, str)
        or not basemap.strip()
        or basemap == _NO_BASEMAP
        or basemap in known
        or basemap in seen
    ):
        raise _extra_error("id", _text(basemap), source)
    for key in ("name", "attribution"):
        if not isinstance(item[key], str) or not item[key].strip():
            raise _extra_error(key, _text(item[key]), source)
    if not isinstance(kind, str) or kind not in EXTRA_KINDS:
        raise _extra_error("kind", _text(kind), source)
    address = origin(url) if isinstance(url, str) else None
    if address is None:
        raise _extra_error("url", _text(url), source)
    grey = item.get("grayscale", False)
    if not isinstance(grey, bool):
        raise _extra_error("grayscale", repr(grey), source)
    seen.add(basemap)
    return {
        "id": basemap,
        "label": item["name"],
        "kind": EXTRA_KINDS[kind],
        "url": wms_template(url) if kind == "wms" else url,
        "origin": address,
        "grey": grey,
        "default": False,
        "credit": {"text": item["attribution"], "links": []},
    }


def extra_entries(settings: Settings, known: list[str]) -> list[dict[str, Any]]:
    """Return the page's entries of ``basemap_extra``.

    The list of ``[hydrograf]`` when it has the key, else that of ``[nogat]``.

    Raises
    ------
    InvalidSettingError
        When the value is no list of tables of exactly ``EXTRA_KEYS`` (``grayscale``
        optional) with valid values, or an id repeats, is ``none`` or a catalogue id.
    """
    found = _section_value(settings, "basemap_extra")
    if found is None:
        return []
    value, source = found
    if not isinstance(value, list):
        raise _extra_error("basemap_extra", repr(value), source)
    seen: set[str] = set()
    return [_extra_entry(item, source, known, seen) for item in value]


def deployment_basemaps(
    settings: Settings, kit_dir: Path = KIT_DIR
) -> list[dict[str, Any]]:
    """Return the entries of the base maps the deployment's page offers.

    The catalogue's entries ``basemaps`` allows, in its order and as in the file but
    for the ``url`` and ``origin`` of a copy of ``basemap_mirrors``; then the own base
    maps of ``basemap_extra``, with no ``blocks``, zoom range or bounds.

    Raises
    ------
    FileOperationError
        When the catalogue cannot be read.
    InvalidSettingError
        When a setting is wrong.
    """
    entries = catalogue(kit_dir)
    known = [entry["id"] for entry in entries]
    allowed = allowed_ids(settings, known)
    copies = mirrors(settings, known)
    page: list[dict[str, Any]] = []
    for entry in entries:
        if entry["id"] not in allowed:
            continue
        item = dict(entry)
        if entry["id"] in copies:
            item["url"] = copies[entry["id"]]
            item["origin"] = origin(item["url"])
        page.append(item)
    return page + extra_entries(settings, known)


def basemap_blocks(entries: Iterable[Mapping[str, Any]]) -> set[str]:
    """Return the blocks of the regulamin the entries name (own ones name none)."""
    return {block for entry in entries for block in entry.get("blocks", ())}


@cache
def current_basemaps() -> list[dict[str, Any]]:
    """Return the base maps of this process's deployment, read on the first call."""
    return deployment_basemaps(get_settings())
