"""
Contract: nginx's Content-Security-Policy names the kit's base maps (Nogat DEV-15.13,
DEV-15.15; ADR-089).

Hydrograf's CSP is nginx's (`docker/nginx.conf`, the same in the TLS variant
`docker/nginx-ssl.conf.template`), not built by the API from its settings, so the page's
`img-src` and `connect-src` name the origin of every entry of the kit's catalogue
`frontend/nogat/nogat-basemaps.json` (the setting `basemaps` narrows the switcher, not
these lines), `img-src` besides the flood hazard map's WMS, the map's own layer, and no
directive a remote scheme source or `*`. The admin page's policy admits in `img-src`
only the origin of the first raster entry, the one its area map draws without a
switcher, and `data:`, the empty image Leaflet gives each tile it removes.
"""

import json
import re
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[3]
CONFIGURATIONS = ("docker/nginx.conf", "docker/nginx-ssl.conf.template")
CATALOGUE = json.loads(
    (REPOSITORY / "frontend" / "nogat" / "nogat-basemaps.json").read_text(
        encoding="utf-8"
    )
)["entries"]
# The map's own layer from another origin: the flood hazard map, WMS of Wody Polskie
MAP_LAYERS = {"https://wody.isok.gov.pl"}
REMOTE = re.compile(r"^https?://")
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:$")


def _policies(name: str) -> dict[str, dict[str, list[str]]]:
    """The CSP of the server and of the admin page's location, by directive."""
    found: dict[str, dict[str, list[str]]] = {}
    blocks: list[str] = []
    for line in (REPOSITORY / name).read_text(encoding="utf-8").splitlines():
        stripped = line.split("#", 1)[0].strip()
        csp = re.match(r'add_header\s+Content-Security-Policy\s+"([^"]+)"', stripped)
        if csp:
            directives: dict[str, list[str]] = {}
            for part in csp.group(1).split(";"):
                words = part.split()
                if words:
                    directives.setdefault(words[0], words[1:])
            found[blocks[-1]] = directives
        if stripped.endswith("{"):
            blocks.append(stripped[:-1].strip())
        elif stripped == "}":
            blocks.pop()
    return {"page": found["server"], "admin": found["location ^~ /_site/admin/"]}


def _remote(sources: list[str]) -> set[str]:
    return {source for source in sources if REMOTE.match(source)}


def _schemes(sources: list[str]) -> set[str]:
    return {source for source in sources if SCHEME.match(source) or source == "*"}


@pytest.mark.parametrize("name", CONFIGURATIONS)
def test_the_page_names_the_origins_of_every_base_map_of_the_catalogue(name):
    page = _policies(name)["page"]
    origins = {entry["origin"] for entry in CATALOGUE}

    assert _remote(page["img-src"]) == origins | MAP_LAYERS
    assert _remote(page["connect-src"]) == origins


@pytest.mark.parametrize("name", CONFIGURATIONS)
def test_no_directive_of_the_page_holds_a_remote_scheme_source(name):
    page = _policies(name)["page"]

    assert _schemes(page["img-src"]) == {"data:", "blob:"}
    assert _schemes(page["connect-src"]) == set()


@pytest.mark.parametrize("name", CONFIGURATIONS)
def test_the_admin_page_admits_only_the_base_map_of_its_area_map(name):
    admin = _policies(name)["admin"]
    first_raster = next(entry for entry in CATALOGUE if entry["kind"] == "raster")

    assert _remote(admin["img-src"]) == {first_raster["origin"]}
    assert _schemes(admin["img-src"]) == {"data:"}
    assert "connect-src" not in admin
    assert admin["default-src"] == ["'self'"]
