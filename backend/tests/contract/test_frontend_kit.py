"""
Nogat's GUI kit in the front end (ADR-082, ADR-086), the view's strip of provider
lines and the link to the regulamin.

The kit in `frontend/nogat/` is copied byte for byte from Nogat `design/kit/`
(DEV-15.6): every file has the SHA-256 its manifest `nogat-kit.json` names. The map is
one view, so it has one `<nogat-sources>` (DEV-20.5): the provider lines of all its data
go into that one strip, never into a block of their own beside a chart, card, legend or
drawer. A public view has no footer: its own link „Regulamin” is the last item of its
left navigation (DEV-15.7), opens a new tab and stays hidden until `js/terms.js` has the
address of a deployment with an operator. The admin page is the kit's shell
`<nogat-admin>` alone with Hydrograf's sections in it (DEV-15.13): no app menu or
regulamin of the public views, no inline script or style (CSP `'self'`), not indexed.
"""

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
KIT = FRONTEND / "nogat"


class _Page(HTMLParser):
    """The elements of a page with their attributes and the depth of each."""

    VOID = {"meta", "link", "input", "img", "br", "hr"}

    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[int, str, dict[str, str]]] = []
        self.inline_scripts = 0
        self._depth = 0
        self._script_src = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        self.elements.append((self._depth, tag, values))
        if tag == "script":
            self._script_src = "src" in values
        if tag not in self.VOID:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.VOID:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        tag = self.get_starttag_text() or ""
        if tag.startswith("<script") and not self._script_src and data.strip():
            self.inline_scripts += 1


def _page(name: str) -> tuple[str, _Page]:
    text = (FRONTEND / name).read_text(encoding="utf-8")
    page = _Page()
    page.feed(text)
    return text, page


def _admin_page() -> tuple[str, _Page]:
    return _page("admin/index.html")


def _children(page: _Page, class_name: str) -> list[tuple[str, dict[str, str]]]:
    """The direct children of the one element whose class list has `class_name`."""
    starts = [
        index
        for index, (_, _, attrs) in enumerate(page.elements)
        if class_name in attrs.get("class", "").split()
    ]
    assert len(starts) == 1
    depth = page.elements[starts[0]][0]
    children = []
    for level, tag, attrs in page.elements[starts[0] + 1 :]:
        if level <= depth:
            break
        if level == depth + 1:
            children.append((tag, attrs))
    return children


def test_the_admin_page_is_the_kit_shell():
    _, page = _admin_page()
    tags = [(tag, attrs) for _, tag, attrs in page.elements]
    shells = [attrs for tag, attrs in tags if tag == "nogat-admin"]
    stylesheets = [
        a["href"] for t, a in tags if t == "link" and a.get("rel") == "stylesheet"
    ]
    modules = [a["src"] for t, a in tags if t == "script" and a.get("type") == "module"]

    assert len(shells) == 1
    assert (shells[0]["app"], shells[0]["project"]) == ("Hydrograf", "hydrograf")
    assert any(href.startswith("../nogat/nogat-admin.css") for href in stylesheets)
    assert any(src.startswith("../nogat/nogat-admin.js") for src in modules)
    assert ("meta", {"name": "robots", "content": "noindex"}) in tags


def test_the_admin_page_has_hydrografs_sections_after_the_kits():
    _, page = _admin_page()
    shell = next(depth for depth, tag, _ in page.elements if tag == "nogat-admin")
    sections = [
        (attrs["data-admin-section"], attrs["data-label"])
        for depth, tag, attrs in page.elements
        if tag == "section" and depth == shell + 1
    ]

    assert sections == [
        ("resources", "Zasoby"),
        ("processing", "Przetwarzanie NMT"),
        ("cleanup", "Czyszczenie"),
        ("boundaries", "Granice i kanalizacja"),
    ]


def test_the_admin_page_is_no_public_view():
    text, page = _admin_page()
    tags = {tag for _, tag, _ in page.elements}

    assert not tags & {"nogat-app-menu", "nogat-sources", "style", "footer"}
    assert "regulamin" not in text.lower()
    assert page.inline_scripts == 0
    assert all("style" not in attrs for _, _, attrs in page.elements)


def test_every_kit_file_is_the_copy_its_manifest_names():
    manifest = json.loads((KIT / "nogat-kit.json").read_text(encoding="utf-8"))

    hashes = {
        name: hashlib.sha256((KIT / name).read_bytes()).hexdigest()
        for name in manifest["files"]
    }

    assert hashes == manifest["files"]


def test_the_map_view_has_one_strip_of_provider_lines():
    page = (FRONTEND / "index.html").read_text(encoding="utf-8")

    assert len(re.findall(r"<nogat-sources[\s>]", page)) == 1
    assert "provider-lines" not in page


@pytest.mark.parametrize(
    ("name", "navigation"),
    [("index.html", "rail"), ("instrukcja/index.html", "guide-toc")],
)
def test_a_public_view_links_the_regulamin_at_the_bottom_of_its_navigation(
    name, navigation
):
    _, page = _page(name)

    tag, attrs = _children(page, navigation)[-1]

    assert (tag, attrs["href"]) == ("a", "/regulamin.html")
    assert (attrs["target"], attrs["rel"]) == ("_blank", "noopener")
    # Without [nogat.operator] js/terms.js never shows it
    assert "hidden" in attrs
    assert "footer" not in {tag for _, tag, _ in page.elements}
