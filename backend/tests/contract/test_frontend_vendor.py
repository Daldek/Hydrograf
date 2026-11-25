"""
The front end loads no script, stylesheet or font from another origin.

The libraries live in `frontend/vendor/<package>-<version>/`, copied byte for byte from
the published package, so a visit fetches code, styles and fonts only from this site
(Nogat DEV-15.7, regulamin § 8). A vendored file keeps its `integrity`: the browser
checks it for same-origin files too, and this test checks it names the file's bytes.
MapLibre GL JS's ES module and its worker load without a tag (js/map.js and
admin/processing.js import the module, which starts its worker), so no `integrity`
covers them: the SHA-256 of MapLibre's files stands for it (MAPLIBRE).
"""

import base64
import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
PAGES = ("index.html", "admin/index.html", "instrukcja/index.html")
# MapLibre GL JS 6.14.0 as npm publishes it (package/dist/, package/LICENSE.txt), the
# SHA-256 of Obserwator's and Archiwista's vendor.json (Nogat's plan
# 2026-11-24-hydrograf-maplibre, M1)
MAPLIBRE = {
    "maplibre-gl.mjs": (
        "244d36122c1398da3a8259817cc6d71e04321afe6404f32606b4b6c6cc4f26fb"
    ),
    "maplibre-gl-worker.mjs": (
        "5f1e2f0e1624082b7e88a06e4c86085992b0f8c02929801e552f3f7a119856a9"
    ),
    "maplibre-gl.css": (
        "bacba6a85a867fcf602f2ff88331b8acf7edf3fbd063a519888cfbff39970193"
    ),
    "LICENSE.txt": "ee5fc05a0677eaf69601d2c7db0d9ecd6cc27c3abc1d0733bc9ed34707cf8ef2",
}

# An absolute or protocol-relative address: another origin.
REMOTE = re.compile(r"^\s*(?:[a-z][a-z0-9+.-]*:)?//", re.IGNORECASE)
# The target of a CSS `url(...)` or `@import "..."`.
CSS_REF = re.compile(
    r"""url\(\s*['"]?([^'")]+)|@import\s+['"]([^'"]+)""", re.IGNORECASE
)


class _Refs(HTMLParser):
    """The `<script src>`, `<link href>` and inline `<style>` text of a page."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[dict[str, str]] = []
        self.styles: list[str] = []
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if tag == "script" and "src" in values:
            self.tags.append({"url": values["src"], **values})
        elif tag == "link" and "href" in values:
            self.tags.append({"url": values["href"], **values})
        elif tag == "style":
            self._in_style = True
        if "style" in values:
            self.styles.append(values["style"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._in_style = False

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.styles.append(data)


def _refs(name: str) -> _Refs:
    parser = _Refs()
    parser.feed((FRONTEND / name).read_text(encoding="utf-8"))
    return parser


def _local_file(name: str, url: str) -> Path:
    return ((FRONTEND / name).parent / urlsplit(url).path).resolve()


def _remote_css_refs(text: str) -> list[str]:
    return [
        ref
        for match in CSS_REF.finditer(text)
        for ref in match.groups()
        if ref and REMOTE.match(ref)
    ]


@pytest.mark.parametrize("name", PAGES)
def test_a_page_loads_nothing_from_another_origin(name):
    refs = _refs(name)
    stylesheets = [
        _local_file(name, tag["url"])
        for tag in refs.tags
        if not REMOTE.match(tag["url"]) and urlsplit(tag["url"]).path.endswith(".css")
    ]

    remote_tags = [tag["url"] for tag in refs.tags if REMOTE.match(tag["url"])]
    remote_in_css = [
        ref
        for text in refs.styles
        + [path.read_text(encoding="utf-8") for path in stylesheets]
        for ref in _remote_css_refs(text)
    ]

    assert remote_tags == []
    assert remote_in_css == []


@pytest.mark.parametrize("name", PAGES)
def test_every_vendored_file_has_the_integrity_of_its_bytes(name):
    vendored = [
        tag
        for tag in _refs(name).tags
        if not REMOTE.match(tag["url"])
        and _local_file(name, tag["url"]).is_relative_to(FRONTEND / "vendor")
    ]
    assert vendored or name == "instrukcja/index.html"

    for tag in vendored:
        integrity = tag.get("integrity", "")
        algorithm, _, _ = integrity.partition("-")
        assert algorithm in {"sha256", "sha384", "sha512"}, (
            f"{tag['url']}: no integrity"
        )
        data = _local_file(name, tag["url"]).read_bytes()
        digest = base64.b64encode(hashlib.new(algorithm, data).digest()).decode("ascii")
        assert integrity == f"{algorithm}-{digest}", tag["url"]


def test_maplibre_is_the_package_byte_for_byte():
    vendored = FRONTEND / "vendor" / "maplibre-gl-6.14.0"

    found = {path.name for path in vendored.iterdir()}
    digests = {
        name: hashlib.sha256((vendored / name).read_bytes()).hexdigest()
        for name in MAPLIBRE
    }

    assert found == set(MAPLIBRE)
    assert digests == MAPLIBRE
