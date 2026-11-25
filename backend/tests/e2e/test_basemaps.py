"""Browser tests of the base maps of Nogat's kit on the map and the admin dialog.

Nogat's plan 2026-11-24-shared-base-maps, step 4 (DEV-15.13, DEV-15.15; ADR-089): the
layers panel's group „Podkłady kartograficzne” holds the kit's switcher, a radio group
„Podkład kartograficzny” with the entries of GET /api/v1/basemaps in the catalogue's
order (``frontend/nogat/nogat-basemaps.json``) and „bez podkładu” last, opening on
OpenFreeMap, which the map asks for its TileJSON and tiles only (the names in the
site's own Noto Sans) and credits in the map's corner as the catalogue writes it. A
choice survives a reload through the browser's ``nogat-basemap`` and sets no cookie; a
provider that fails is marked in the list and said on the map until the next choice;
with no entry there is no switcher and no request to a provider; a theme switch
repaints OpenFreeMap (the mean brightness of the map's middle, light then dark); on a
phone the credit shows when the map opens, folds behind „i” at the first drag and
shows again at a tap. The admin dialog's map draws the first raster entry, grey and
with its credit, and none without a raster entry.
"""

import io
import json
import re
from typing import Any

from PIL import Image, ImageStat
from playwright.sync_api import FloatRect, Locator, Page, Route, expect

from tests.e2e.browser import Tab, open_map
from tests.e2e.site import ADMIN_KEY, FRONTEND
from tests.e2e.test_layers import wait_still

CATALOGUE: list[dict[str, Any]] = json.loads(
    (FRONTEND / "nogat" / "nogat-basemaps.json").read_text(encoding="utf-8")
)["entries"]
ENTRIES = {entry["id"]: entry for entry in CATALOGUE}
NONE = "bez podkładu"
FAILED = "Podkład nie odpowiada"
# The kit's name of the credit's button („i”), BASEMAP_TEXTS.credit
CREDIT_BUTTON = "Pokaż lub ukryj źródło podkładu"
OPENFREEMAP = r"^https://tiles\.openfreemap\.org/"
GEOPORTAL = r"^https://mapy\.geoportal\.gov\.pl/"
GUGIK_OSM_TILES = re.compile(
    r"^https://mapy\.geoportal\.gov\.pl/wss/ext/OSM/BaseMap/.+\.png$"
)
GLYPHS = r"/vendor/openmaptiles-fonts-2.0/noto-sans-regular/\d+-\d+\.pbf$"
# The map's middle whose mean brightness tells the theme of the vector base map, and
# the brightness of each theme's grey style there (0-255; light ≈ 230, dark ≈ 35)
MIDDLE_PX = 120
LIGHT_ABOVE, DARK_BELOW = 170, 100
REPAINT_TIMEOUT_MS = 15_000
# A strip along the admin map's left edge, clear of the box its fit leaves 40 px from
# the edges and of the zoom buttons over its top: its width and height [px]
STRIP_PX = (24, 80)
# How far the channels of a pixel of a grey base map lie apart [0-255]
GREY_TOLERANCE = 3


def _switcher(page: Page) -> Locator:
    return page.get_by_role("radiogroup", name="Podkład kartograficzny", exact=True)


def _label(base_map: str) -> str:
    return str(ENTRIES[base_map]["label"])


def _credit(page: Page) -> Locator:
    return page.locator("#map .maplibregl-ctrl-attrib")


def _answer_basemaps(page: Page, entries: list[dict[str, Any]]) -> None:
    """Answer GET /api/v1/basemaps with ``entries`` as a deployment that allows them."""

    def answer(route: Route) -> None:
        route.fulfill(status=200, json=entries)

    page.route(re.compile(r"/api/v1/basemaps$"), answer)


def _brightness(page: Page) -> float:
    """The mean brightness of the middle of the map, 0 to 255."""
    box = page.locator("#map").bounding_box()
    assert box is not None
    clip: FloatRect = {
        "x": box["x"] + (box["width"] - MIDDLE_PX) / 2,
        "y": box["y"] + (box["height"] - MIDDLE_PX) / 2,
        "width": MIDDLE_PX,
        "height": MIDDLE_PX,
    }
    image = Image.open(io.BytesIO(page.screenshot(clip=clip))).convert("L")
    return float(ImageStat.Stat(image).mean[0])


def _strip(area: Locator) -> list[tuple[int, int, int]]:
    """The pixels of a strip along the left edge of a map, halfway down."""
    box = area.bounding_box()
    assert box is not None
    clip: FloatRect = {
        "x": box["x"] + 4,
        "y": box["y"] + (box["height"] - STRIP_PX[1]) / 2,
        "width": STRIP_PX[0],
        "height": STRIP_PX[1],
    }
    image = Image.open(io.BytesIO(area.page.screenshot(clip=clip))).convert("RGB")
    packed = image.tobytes()
    return [(packed[k], packed[k + 1], packed[k + 2]) for k in range(0, len(packed), 3)]


def _open_admin_map(tab: Tab) -> Locator:
    """Sign in to the admin page and open the dialog's map; its map."""
    page = tab.page
    page.goto(tab.site.base + "/admin/#processing")
    page.get_by_label("Klucz administratora", exact=True).fill(ADMIN_KEY)
    page.get_by_role("button", name="Zaloguj", exact=True).click()
    page.locator("#bbox-map-open").click()
    expect(page.get_by_role("dialog", name="Wybierz obszar na mapie")).to_be_visible()
    tab.settle()
    return page.locator("#bbox-map")


def test_switcher_lists_the_catalogue_and_opens_on_openfreemap(tab: Tab) -> None:
    page = tab.page
    open_map(tab)

    switcher = _switcher(page)
    expect(switcher.locator("label")).to_have_text(
        [entry["label"] for entry in CATALOGUE] + [NONE]
    )
    expect(switcher.get_by_role("radio", name=_label("openfreemap"))).to_be_checked()
    asked = [sent.url for sent in tab.requests]
    assert ENTRIES["openfreemap"]["url"] in asked
    assert [url for url in asked if re.search(r"\.pbf$", url) and "openfreemap" in url]
    # The grey style asks OpenFreeMap for nothing but its TileJSON and tiles
    assert not [
        url
        for url in asked
        if re.search(OPENFREEMAP, url)
        and url != ENTRIES["openfreemap"]["url"]
        and not re.search(r"/planet/[^/]+/\d+/\d+/\d+\.pbf$", url)
    ]
    assert [url for url in asked if re.search(GLYPHS, url)], "no glyph of the site"
    credit = _credit(page)
    expect(credit).to_contain_text(ENTRIES["openfreemap"]["credit"]["text"])
    for word, address in ENTRIES["openfreemap"]["credit"]["links"]:
        # The kit writes each address as the browser resolves it (a root path's "/")
        expect(credit.get_by_role("link", name=word, exact=True)).to_have_attribute(
            "href", re.compile(f"^{re.escape(address)}/?$")
        )
    assert credit.evaluate("(node) => getComputedStyle(node).fontSize") == "12px"


def test_the_choice_is_kept_in_the_browser_over_a_reload(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    _switcher(page).get_by_role("radio", name=_label("gugik-ortho")).check()
    tab.settle()
    assert page.evaluate("localStorage.getItem('nogat-basemap')") == "gugik-ortho"

    mark = tab.mark()
    open_map(tab)

    expect(
        _switcher(page).get_by_role("radio", name=_label("gugik-ortho"))
    ).to_be_checked()
    assert tab.sent_since(mark, r"/wss/service/PZGIK/ORTO/WMTS/")
    assert tab.sent_since(mark, OPENFREEMAP) == []
    expect(_credit(page)).to_contain_text(ENTRIES["gugik-ortho"]["credit"]["text"])
    assert page.context.cookies() == []


def test_a_failing_base_map_is_marked_and_said_on_the_map(tab: Tab) -> None:
    page = tab.page
    page.route(GUGIK_OSM_TILES, lambda route: route.fulfill(status=503, body=""))
    open_map(tab)
    notice = page.locator("#basemap-notice")
    expect(notice).to_be_hidden()

    _switcher(page).get_by_role("radio", name=_label("gugik-osm")).check()

    expect(notice).to_be_visible()
    expect(notice).to_contain_text(f"{FAILED}: {_label('gugik-osm')}")
    entry = _switcher(page).locator("label").filter(has_text=_label("gugik-osm"))
    expect(entry).to_contain_text(FAILED)
    expect(_credit(page)).not_to_contain_text(ENTRIES["gugik-osm"]["credit"]["text"])

    _switcher(page).get_by_role("radio", name=_label("openfreemap")).check()

    expect(notice).to_be_hidden()
    expect(_credit(page)).to_contain_text(ENTRIES["openfreemap"]["credit"]["text"])


def test_without_base_maps_no_switcher_and_no_provider_asked(tab: Tab) -> None:
    page = tab.page
    _answer_basemaps(page, [])
    open_map(tab)

    expect(page.locator("nogat-basemaps")).to_be_hidden()
    expect(page.get_by_text("Podkłady kartograficzne", exact=True)).to_be_visible()
    asked = [sent.url for sent in tab.requests]
    assert not [u for u in asked if re.search(f"{OPENFREEMAP}|{GEOPORTAL}", u)]


def test_a_theme_switch_repaints_openfreemap(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    light = _brightness(page)

    page.locator("#theme-dark").click()

    expect(page.locator("#theme-dark")).to_have_attribute("aria-pressed", "true")
    page.wait_for_timeout(100)
    deadline = REPAINT_TIMEOUT_MS
    dark = _brightness(page)
    while dark >= DARK_BELOW and deadline > 0:
        page.wait_for_timeout(250)
        deadline -= 250
        dark = _brightness(page)
    assert (light > LIGHT_ABOVE, dark < DARK_BELOW) == (True, True), (light, dark)


def test_on_a_phone_the_credit_folds_at_the_first_drag(new_tab: Any) -> None:
    tab = new_tab(width=390)
    page = tab.page
    open_map(tab)
    layers = page.locator("#open-layers")
    if layers.get_attribute("aria-expanded") == "true":
        layers.click()  # the layers sheet down, the map in view
    tab.settle()
    credit = _credit(page)
    osm = credit.get_by_role("link", name="OpenStreetMap", exact=True)
    expect(osm).to_be_visible()

    box = page.locator("#map").bounding_box()
    assert box is not None
    x, y = box["x"] + box["width"] / 2, box["y"] + 60
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 40, y + 60, steps=8)
    page.mouse.up()

    expect(osm).to_be_hidden()
    # MapLibre's compact credit folds behind a <summary> named by its aria-label
    button = credit.get_by_label(CREDIT_BUTTON, exact=True)
    expect(button).to_be_visible()
    button.tap()
    expect(osm).to_be_visible()


def test_the_admin_map_draws_the_first_raster_entry_grey_with_its_credit(
    tab: Tab,
) -> None:
    area = _open_admin_map(tab)

    assert tab.sent_since(0, GUGIK_OSM_TILES.pattern)
    assert tab.sent_since(0, r"/wss/service/PZGIK/ORTO/") == []
    assert tab.sent_since(0, OPENFREEMAP) == []
    # The tiles drawn grey: every pixel's channels alike, the tile's detail kept
    wait_still(tab.page, area)
    strip = _strip(area)
    assert all(max(p) - min(p) <= GREY_TOLERANCE for p in strip), set(strip)
    assert len(set(strip)) > 1, set(strip)
    credit = area.locator(".maplibregl-ctrl-attrib")
    expect(credit).to_contain_text(ENTRIES["gugik-osm"]["credit"]["text"])
    expect(tab.page.locator("#bbox-map-notice")).to_be_hidden()


def test_the_admin_map_draws_no_base_map_without_a_raster_entry(tab: Tab) -> None:
    _answer_basemaps(tab.page, [ENTRIES["openfreemap"]])

    area = _open_admin_map(tab)

    asked = [sent.url for sent in tab.requests]
    assert not [u for u in asked if re.search(f"{OPENFREEMAP}|{GEOPORTAL}", u)]
    # The map's own background alone
    wait_still(tab.page, area)
    assert len(set(_strip(area))) == 1
