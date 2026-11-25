"""Browser tests of what only the map on MapLibre GL JS has.

Nogat's plan 2026-11-24-hydrograf-maplibre, step 2, „Tests”, beside step 1's tests,
which hold unchanged:

* "no request to blob: workers, the worker from vendor/":
  ``test_maplibres_worker_is_its_file_of_vendor_never_a_blob``: every worker the page
  starts is ``vendor/maplibre-gl-6.14.0/maplibre-gl-worker.mjs`` of the site's own
  origin, and no request goes to a ``blob:`` address.
* "with webgl2 refused by an init script Hydrograf.map.init resolves without a map and
  no unhandled rejection is logged, the map's area shows M13's words and the panels
  work": ``test_without_webgl2_the_map_says_so_and_the_panels_go_on``: with
  ``getContext("webgl2")`` answering null, ``Hydrograf.map.ready`` resolves to false,
  ``describe()`` to null, the map's area says „Mapa wymaga przeglądarki z WebGL 2.”,
  a row of the layers panel whose layer needs the map turns itself off and the theme
  switches; no promise is rejected unhandled.
* "and the admin dialog shows them in place of its map with its four fields taking
  input": ``test_without_webgl2_the_admin_dialog_says_so_and_the_fields_take_input``.
* "vector tiles asked at one level lower than step 1's run, each layer still first
  drawn at step 1's scale": ``test_vector_tiles_one_level_lower_at_the_first_scale``
  walks the map's zoom buttons out to the first scale of each tiled vector layer of
  ``test_vector_tiles.py`` (whose step 1 tests show it first drawn there): the tiles
  asked there are one level below those of 256 px at that scale, which step 1's map
  asked.
* "a result below its minzoom as open question 4 decides" (accepted, the row says
  „Przybliż mapę”): ``test_a_result_farther_out_than_its_first_level_says_zoom_in``:
  a step farther out than the result's first level the row says so and no tile of it
  is asked; back at that level it is drawn and the hint is gone.
"""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.browser import (
    EXPECT_TIMEOUT_MS,
    Tab,
    describe,
    open_map,
    overlay_ids,
    wait_view,
    zoom_in,
    zoom_out,
)
from tests.e2e.site import ADMIN_KEY, RESULT_ID, RESULT_TITLE, RESULT_ZOOMS
from tests.e2e.test_vector_tiles import (
    LANDCOVER,
    LANDCOVER_FIRST_SCALE,
    SEWER,
    SEWER_FIRST_SCALE,
    STREAMS,
    STREAMS_FIRST_SCALE,
    THRESHOLD,
    THRESHOLD_1000_FIRST_SCALE,
    THRESHOLD_LABELS,
)

WORKER_PATH = "/vendor/maplibre-gl-6.14.0/maplibre-gl-worker.mjs"
# Installed before any script of the page: no WebGL 2 context, and a record of the
# promises rejected with no handler
NO_WEBGL2 = """
const getContext = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function (kind, ...rest) {
  return kind === "webgl2" ? null : getContext.call(this, kind, ...rest);
};
window.__rejections = [];
window.addEventListener("unhandledrejection", (event) => {
  window.__rejections.push(String(event.reason));
});
"""
# Hydrograf.map.ready, or "pending" while it has not settled within the expectations'
# bound
READY = (
    "(bound) => Promise.race([Hydrograf.map.ready,"
    " new Promise((resolve) => setTimeout(() => resolve('pending'), bound))])"
)
MAP_NO_WEBGL2 = "Mapa wymaga przeglądarki z WebGL 2."
ADMIN_NO_WEBGL2 = (
    "Mapa wymaga przeglądarki z WebGL 2. Wpisz granice obszaru w pola formularza."
)
# A box of the four fields typed by hand (degrees)
TYPED = {"west": "20.4", "south": "52.3", "east": "20.6", "north": "52.4"}
# The scale as describe() gives it: the equator over the world's pixels at a level,
# over OGC's standard rendering pixel of 0.28 mm; step 1's map drew 256-px tiles
EQUATOR_M = 40_075_016.68557849
STANDARD_PIXEL_M = 0.00028
STEP_1_TILE_PX = 256
SCALE_TOLERANCE = 1e-6
# The result's first level, of 256-px tiles: 1:34 124, which its row's hint names
RESULT_FIRST_SCALE = (
    EQUATOR_M / (STEP_1_TILE_PX * 2 ** RESULT_ZOOMS[0]) / STANDARD_PIXEL_M
)
RESULT_HINT = re.compile(
    r"^Przybliż mapę — wynik jest rysowany od skali ok\. 1:34\s000\.$"
)
RESULT_TILES = rf"/data/results/{RESULT_ID}/\d+/\d+/\d+\.png$"


def _streams_tiles(threshold: int) -> str:
    """The streams' tiles of a threshold, either kind; a group: the level."""
    return (
        rf"/tiles/streams_{threshold}/(\d+)/\d+/\d+\.pbf$"
        r"|/api/tiles/streams/(\d+)/\d+/\d+\.pbf"
        rf"\?(?:.*&)?threshold={threshold}(?:&|$)"
    )


@dataclass(frozen=True)
class Tiled:
    """A tiled vector layer: its row, its overlay, its tiles (a group: the level)."""

    label: str
    overlay: str
    tiles: str
    # Step 1's first scale of the layer (test_vector_tiles.py)
    first_scale: float
    # The streams' threshold [m²] chosen, None for the default
    threshold: int | None = None


TILED = (
    Tiled(STREAMS, "streams", _streams_tiles(100_000), STREAMS_FIRST_SCALE),
    Tiled(STREAMS, "streams", _streams_tiles(1_000), THRESHOLD_1000_FIRST_SCALE, 1_000),
    Tiled(
        LANDCOVER,
        "landcover",
        r"/api/tiles/landcover/(\d+)/\d+/\d+\.pbf$",
        LANDCOVER_FIRST_SCALE,
    ),
    Tiled(SEWER, "sewer", r"/api/tiles/sewer/(\d+)/\d+/\d+\.pbf$", SEWER_FIRST_SCALE),
)


def _step_1_level(scale: float) -> int:
    """The level of 256-px tiles at a scale, which step 1's map asked there."""
    return round(math.log2(EQUATOR_M / (STEP_1_TILE_PX * scale * STANDARD_PIXEL_M)))


def _levels(tab: Tab, mark: int, tiles: str) -> set[int]:
    """The levels of the tiles of a pattern asked since ``mark``."""
    levels = set()
    for sent in tab.sent_since(mark, tiles):
        found = re.search(tiles, sent.url)
        assert found is not None
        levels.add(int(next(group for group in found.groups() if group)))
    return levels


def _step(tab: Tab, zoom: Callable[[Page], None]) -> dict[str, Any]:
    """One step of the map's zoom buttons; the view once still and settled."""
    page = tab.page
    before = describe(page)["scale"]
    zoom(page)
    page.wait_for_function(
        "(before) => Hydrograf.map.describe().scale !== before", arg=before
    )
    view = wait_view(page)
    tab.settle()
    return view


def _wait_listed(tab: Tab, overlay_id: str, listed: bool) -> None:
    """Wait until describe() lists the overlay, or no longer does."""
    tab.page.wait_for_function(
        "([id, listed]) => Hydrograf.map.describe().overlays"
        ".some((drawn) => drawn.id === id) === listed",
        arg=[overlay_id, listed],
    )


def _choose(select: Locator, label: str) -> None:
    """Pick the option of a ``<select>`` shown as ``label`` (any white space)."""
    texts = [
        " ".join(text.split()) for text in select.locator("option").all_inner_texts()
    ]
    select.select_option(index=texts.index(label))


def test_maplibres_worker_is_its_file_of_vendor_never_a_blob(tab: Tab) -> None:
    page = tab.page
    workers: list[str] = []
    page.on("worker", lambda worker: workers.append(worker.url))
    open_map(tab)
    assert workers, "no worker started"
    own = urlsplit(tab.site.base).netloc
    started = {(urlsplit(url).netloc, urlsplit(url).path) for url in workers}
    assert started == {(own, WORKER_PATH)}, workers
    assert [sent.url for sent in tab.requests if sent.url.startswith("blob:")] == []


def test_without_webgl2_the_map_says_so_and_the_panels_go_on(tab: Tab) -> None:
    page = tab.page
    page.add_init_script(NO_WEBGL2)
    page.goto(tab.site.base + "/")
    page.wait_for_function("() => window.Hydrograf && Hydrograf.map")
    assert page.evaluate(READY, EXPECT_TIMEOUT_MS) is False
    assert page.evaluate("() => Hydrograf.map.describe()") is None
    expect(page.locator("#map").get_by_role("status")).to_have_text(MAP_NO_WEBGL2)

    dem = page.get_by_label("NMT (wysokości)", exact=True)
    dem.click()
    expect(dem).not_to_be_checked()
    page.locator("#theme-dark").click()
    expect(page.locator("#theme-dark")).to_have_attribute("aria-pressed", "true")
    tab.settle()
    assert page.evaluate("() => window.__rejections") == []


def test_without_webgl2_the_admin_dialog_says_so_and_the_fields_take_input(
    tab: Tab,
) -> None:
    page = tab.page
    page.add_init_script(NO_WEBGL2)
    page.goto(tab.site.base + "/admin/#processing")
    page.get_by_label("Klucz administratora", exact=True).fill(ADMIN_KEY)
    page.get_by_role("button", name="Zaloguj", exact=True).click()
    page.locator("#bbox-map-open").click()
    dialog = page.get_by_role("dialog", name="Wybierz obszar na mapie")
    expect(dialog).to_be_visible()
    expect(page.locator("#bbox-map").get_by_role("status")).to_have_text(
        ADMIN_NO_WEBGL2
    )
    expect(page.locator("#bbox-confirm")).to_be_disabled()
    dialog.get_by_role("button", name="Anuluj", exact=True).click()
    expect(dialog).to_be_hidden()

    for side, value in TYPED.items():
        page.locator(f"#bbox-{side}").fill(value)
    for side, value in TYPED.items():
        expect(page.locator(f"#bbox-{side}")).to_have_value(value)
    expect(page.locator("#bbox-error")).to_be_hidden()
    assert page.evaluate("() => window.__rejections") == []


@pytest.mark.parametrize(
    "tiled",
    [
        pytest.param(tiled, id=f"{tiled.overlay}-{tiled.threshold or 'default'}")
        for tiled in TILED
    ],
)
def test_vector_tiles_one_level_lower_at_the_first_scale(
    tab: Tab, tiled: Tiled
) -> None:
    page = tab.page
    open_map(tab)
    mark = tab.mark()
    page.get_by_label(tiled.label, exact=True).check()
    _wait_listed(tab, tiled.overlay, listed=True)
    if tiled.threshold is not None:
        mark = tab.mark()
        _choose(
            page.get_by_label(THRESHOLD, exact=True), THRESHOLD_LABELS[tiled.threshold]
        )
    tab.settle()
    view = describe(page)
    while view["scale"] < tiled.first_scale * (1 - SCALE_TOLERANCE):
        mark = tab.mark()
        view = _step(tab, zoom_out)
    assert math.isclose(view["scale"], tiled.first_scale, rel_tol=SCALE_TOLERANCE)
    assert _levels(tab, mark, tiled.tiles) == {_step_1_level(tiled.first_scale) - 1}


def test_a_result_farther_out_than_its_first_level_says_zoom_in(tab: Tab) -> None:
    page = tab.page
    view = open_map(tab)
    while view["scale"] > RESULT_FIRST_SCALE * (1 + SCALE_TOLERANCE):
        view = _step(tab, zoom_in)
    while view["scale"] < RESULT_FIRST_SCALE * (1 - SCALE_TOLERANCE):
        view = _step(tab, zoom_out)
    assert math.isclose(view["scale"], RESULT_FIRST_SCALE, rel_tol=SCALE_TOLERANCE)
    result = f"result:{RESULT_ID}"
    hint = page.locator("#layers-list").get_by_text(RESULT_HINT)
    _step(tab, zoom_out)
    mark = tab.mark()
    page.get_by_label(RESULT_TITLE, exact=True).check()

    expect(hint).to_be_visible()
    tab.settle()
    assert tab.sent_since(mark, RESULT_TILES) == []
    assert result not in overlay_ids(page)

    _step(tab, zoom_in)
    expect(hint).to_be_hidden()
    _wait_listed(tab, result, listed=True)
    tab.settle()
    assert tab.sent_since(mark, RESULT_TILES)
