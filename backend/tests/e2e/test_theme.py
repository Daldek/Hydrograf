"""Browser test of a theme switch repainting the map's overlays (js/map.js).

Nogat's plan 2026-11-24-hydrograf-maplibre, step 1, the bullet „a theme switch
repaints the overlays (pixels of the boundary and a stream in both themes)”. Without a
base map („bez podkładu”, the map's background is the token ``--surface-2``), with
the streams („Linie spływu”) and a delineated watershed on the map, the view one step
out so that the main river's lower course below the watershed shows: a pixel of the
watershed's boundary (at a vertex of the answer's boundary on its western divide) is
the light theme's ``--tool-hydrograf`` and a pixel of the main river's stream (row
207, outside the watershed) its ``--info``; after the page's own control „Ciemny”
(``#theme-dark``) the same pixels are the dark theme's tokens. Each colour is read as
the nearest of both themes' ``--tool-hydrograf``, ``--info``, ``--surface`` and
``--surface-2`` (light read before the switch, dark after, by ``token_colors``).
"""

import math
import re
import time
from collections.abc import Mapping
from typing import Any

from playwright.sync_api import Page, expect

from tests.e2e.browser import (
    Rgb,
    Tab,
    distance,
    nearest,
    open_map,
    pixels,
    screen_point,
    token_colors,
    wait_view,
    zoom_out,
)
from tests.e2e.site import MAIN_RIVER_COL

TOKENS = ("--tool-hydrograf", "--info", "--surface", "--surface-2")
# On the main river between T2's mouth (row 123) and T1's (row 159): its watershed
# ends at T1's mouth, north of the main river's lower course
CLICK_CELL = (140, MAIN_RIVER_COL)
DELINEATION = re.compile(r"/api/v1/watershed/delineate\?")
# The boundary's vertex nearest to this cell lies on the divide between T1 (column
# 49) and the main river, far from every stream and flow path
DIVIDE_CELL = (110, 60)
# The main river's lower course, outside the watershed, clear of the legends
STREAM_CELL = (207, MAIN_RIVER_COL)
# The pixels read around a point: a line's centre is within this of where its
# place falls [px]
RADIUS_PX = 3
REPAINT_TIMEOUT_S = 15.0

Place = tuple[float, float]


def ink(page: Page, place: Place, background: Rgb) -> Rgb:
    """The pixel near a place that differs most from the map's background.

    The pixel nearest to any candidate would not do: beside a thin line on the bare
    background it is a pixel of that background (it matches its token exactly), and
    across a translucent stream on the dark background an antialiased edge pixel lies
    nearer to the light ``--tool-hydrograf`` than the stream's centre lies to its own
    token. The line's centre differs most from the background.
    """
    x, y = screen_point(page, *place)
    return max(pixels(page, x, y, RADIUS_PX), key=lambda c: distance(c, background))


def steady_ink(page: Page, place: Place, background: Rgb) -> Rgb:
    """``ink`` once two reads a moment apart agree (the drawing is complete)."""
    deadline = time.monotonic() + REPAINT_TIMEOUT_S
    previous = None
    while True:
        current = ink(page, place, background)
        if current == previous:
            return current
        assert time.monotonic() < deadline, f"the map kept changing at {place}"
        previous = current
        page.wait_for_timeout(250)


def repainted_ink(
    page: Page, place: Place, background: Rgb, candidates: Mapping[str, Rgb], token: str
) -> Rgb:
    """``ink`` once it is nearest to ``token``, or the last read after the timeout."""
    deadline = time.monotonic() + REPAINT_TIMEOUT_S
    while True:
        current = ink(page, place, background)
        if nearest(current, candidates) == token or time.monotonic() > deadline:
            return current
        page.wait_for_timeout(250)


def boundary_place(boundary: dict[str, Any], near: Place) -> Place:
    """The vertex of the boundary's outer ring nearest to a place."""
    ring = boundary["geometry"]["coordinates"][0]
    cos_lat = math.cos(math.radians(near[1]))

    def apart(vertex: list[float]) -> float:
        return math.hypot((vertex[0] - near[0]) * cos_lat, vertex[1] - near[1])

    lng, lat = min(ring, key=apart)
    return float(lng), float(lat)


def themed(page: Page, theme: str) -> dict[str, Rgb]:
    """The colours of TOKENS in the page's current theme, named ``<theme> <token>``."""
    return {f"{theme} {name}": rgb for name, rgb in token_colors(page, *TOKENS).items()}


def test_theme_switch_repaints_boundary_and_stream(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    page.get_by_label("bez podkładu", exact=True).check()
    page.get_by_label("Linie spływu", exact=True).check()
    tab.settle()
    page.get_by_role("radio", name="Wybierz zlewnię", exact=True).click()
    page.get_by_role("radio", name="Jedna zlewnia", exact=True).click()
    expect(page.get_by_role("complementary", name="Zlewnia")).to_be_visible()
    wait_view(page)
    x, y = screen_point(page, *tab.site.cell_lnglat(*CLICK_CELL))
    with page.expect_response(DELINEATION) as answered:
        page.mouse.click(x, y)
    assert answered.value.ok, answered.value.text()
    page.wait_for_function(
        "() => Hydrograf.map.describe().overlays.some((o) => o.id === 'watershed')"
    )
    boundary = answered.value.json()["result"]["watershed"]["boundary_geojson"]
    wait_view(page)
    zoom_out(page)
    wait_view(page)
    tab.settle()
    divide = boundary_place(boundary, tab.site.cell_lnglat(*DIVIDE_CELL))
    stream = tab.site.cell_lnglat(*STREAM_CELL)
    light = themed(page, "light")
    light_ink = {
        place: steady_ink(page, place, light["light --surface-2"])
        for place in (divide, stream)
    }

    page.locator("#theme-dark").click()

    expect(page.locator("#theme-dark")).to_have_attribute("aria-pressed", "true")
    dark = themed(page, "dark")
    candidates = light | dark
    tab.settle()
    expected = {divide: "--tool-hydrograf", stream: "--info"}
    dark_ink = {
        place: repainted_ink(
            page, place, dark["dark --surface-2"], candidates, f"dark {token}"
        )
        for place, token in expected.items()
    }
    found = {
        (theme, token): nearest(inks[place], candidates)
        for theme, inks in (("light", light_ink), ("dark", dark_ink))
        for place, token in expected.items()
    }
    assert found == {key: f"{key[0]} {key[1]}" for key in found}, (
        found,
        light_ink,
        dark_ink,
    )
