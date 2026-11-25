"""Browser tests of the terrain profile (js/profile.js, the drawing of js/map.js).

Nogat's plan 2026-11-24-hydrograf-maplibre, step 1, the bullet „the profile: clicks,
Backspace, Esc, a double click, and at 390 px the three buttons and a tap near the
last vertex; the chart's readout moves the point on the map”. In the mode „Profil
terenu” each click or tap on the map adds a vertex: the drawing tools („Rysowanie
profilu terenu”) count them (``#draw-count``) and the map draws the overlay ``draw``
of ``Hydrograf.map.describe()``. Backspace and „Cofnij” take the last vertex back, Esc
and „Anuluj” drop the line; a double click, „Rysuj profil” or a tap within 20 px of
the last vertex (``FINISH_TAP_PX``) end it: POST /api/terrain-profile asks for the
profile along the vertices (compared with the places clicked), the drawer „Profil
terenu” shows its chart and the map the overlay ``profile-line``. A pointer over the
chart puts the overlay ``profile-marker`` on the line, farther along it the farther
right the pointer is, and takes it off when the pointer leaves.
"""

import json
import math
import re
from collections.abc import Callable, Sequence
from itertools import pairwise

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.browser import Sent, Tab, describe, open_map, overlay_ids, screen_point
from tests.e2e.test_watershed import js_fixed

PROFILE = re.compile(r"/api/terrain-profile$")
# Vertices of the lines drawn, cells (row, column) of the DEM: across the catchment
# from the north-west to the south-east, clear of the tools over the map's top
LINE = ((60, 20), (110, 80), (150, 150))
FOURTH = (200, 100)
PHONE_LINE = ((60, 40), (120, 90), (170, 130))
# What the drawing tools say after n vertices
COUNTS = {
    0: "Wskaż początek profilu",
    1: "1 punkt — wskaż kolejny",
    2: "2 punkty — dotknij ostatniego, aby narysować profil",
    3: "3 punkty — dotknij ostatniego, aby narysować profil",
}
# A tap this far from the last vertex ends the line (map.js FINISH_TAP_PX = 20)
NEAR_LAST_PX = (8, 6)
# Taps this far apart are separate taps, never a double tap (Leaflet's is two taps
# within 200 ms anywhere on the map, MapLibre's within 500 ms): the pace of a person
PHONE_TAP_GAP_MS = 600
# The vertices the request carries: the pixels clicked, as the map read them [px]
CLICKED_PX = 2
# The readout's point lies on the line drawn [m]
ON_LINE_M = 1.0
M_PER_DEG_LAT = 111_320.0

Place = tuple[float, float]


def drawing_tools(page: Page) -> Locator:
    return page.get_by_role("toolbar", name="Rysowanie profilu terenu")


def draw_count(page: Page) -> Locator:
    return page.locator("#draw-count")


def profile_drawer(page: Page) -> Locator:
    return page.get_by_role("region", name="Profil terenu")


def places(tab: Tab, cells: Sequence[tuple[int, int]]) -> list[Place]:
    return [tab.site.cell_lnglat(*cell) for cell in cells]


def click_place(page: Page, place: Place) -> None:
    page.mouse.click(*screen_point(page, *place))


def tap_place(page: Page, place: Place, offset: tuple[float, float] = (0, 0)) -> None:
    """Tap the map at a place (or ``offset`` px from it) and pause as a person does."""
    x, y = screen_point(page, *place)
    page.touchscreen.tap(x + offset[0], y + offset[1])
    page.wait_for_timeout(PHONE_TAP_GAP_MS)


def sent_line(sent: Sent) -> list[Place]:
    """The vertices (longitude, latitude) of a request of POST /api/terrain-profile."""
    body = json.loads(sent.post_data or "{}")
    return [(float(lng), float(lat)) for lng, lat in body["geometry"]["coordinates"]]


def assert_line(page: Page, line: list[Place], expected: list[Place]) -> None:
    """The line asked for has the vertices placed, each within CLICKED_PX."""
    west, south, east, north = describe(page)["bounds"]
    box = page.locator("#map").bounding_box()
    assert box is not None
    tolerance = (
        CLICKED_PX * (east - west) / box["width"],
        CLICKED_PX * (north - south) / box["height"],
    )
    assert len(line) == len(expected), (line, expected)
    for vertex, place in zip(line, expected, strict=True):
        assert vertex[0] == pytest.approx(place[0], abs=tolerance[0]), (line, expected)
        assert vertex[1] == pytest.approx(place[1], abs=tolerance[1]), (line, expected)


def finish_line(tab: Tab, finish: Callable[[], None]) -> list[Place]:
    """End the line by ``finish``: the vertices asked for, once the drawer shows."""
    page = tab.page
    mark = tab.mark()
    with page.expect_response(PROFILE) as answered:
        finish()
    response = answered.value
    assert response.ok, f"profile failed: {response.status} {response.text()}"
    sent = tab.sent_since(mark, PROFILE.pattern)
    assert [s.method for s in sent] == ["POST"], sent
    drawer = profile_drawer(page)
    expect(drawer.get_by_role("img", name="Profil terenu")).to_be_visible()
    length_km = js_fixed(response.json()["distances_m"][-1] / 1000, 2)
    expect(drawer).to_contain_text(f"Długość {length_km} km")
    ids = overlay_ids(page)
    assert "profile-line" in ids and "draw" not in ids, ids
    return sent_line(sent[0])


def along_line(line: list[Place], place: Place) -> tuple[float, float]:
    """(distance along the line, distance off it) of a place [m], locally flat."""
    lat0 = math.radians(line[0][1])

    def metres(p: Place) -> tuple[float, float]:
        return p[0] * M_PER_DEG_LAT * math.cos(lat0), p[1] * M_PER_DEG_LAT

    px, py = metres(place)
    best = (math.inf, 0.0)
    start = 0.0
    for a, b in pairwise(line):
        (ax, ay), (bx, by) = metres(a), metres(b)
        length = math.hypot(bx - ax, by - ay)
        t = ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / length**2
        t = min(max(t, 0.0), 1.0)
        off = math.hypot(px - (ax + t * (bx - ax)), py - (ay + t * (by - ay)))
        if off < best[0]:
            best = (off, start + t * length)
        start += length
    return best[1], best[0]


def readout_place(page: Page, previous: Place | None = None) -> Place:
    """The place of ``profile-marker`` once drawn (and away from ``previous``)."""
    page.wait_for_function(
        """(previous) => {
            const marker = Hydrograf.map.describe().overlays
                .find((o) => o.id === 'profile-marker');
            return marker && (previous === null
                || marker.lngLat[0] !== previous[0]
                || marker.lngLat[1] !== previous[1]);
        }""",
        arg=previous,
    )
    (marker,) = [o for o in describe(page)["overlays"] if o["id"] == "profile-marker"]
    lng, lat = marker["lngLat"]
    return float(lng), float(lat)


def test_profile_clicks_and_backspace_shape_the_line_double_click_ends_it(
    tab: Tab,
) -> None:
    page = tab.page
    open_map(tab)
    page.get_by_role("radio", name="Profil terenu", exact=True).click()
    expect(draw_count(page)).to_have_text(COUNTS[0])
    a, b, c = places(tab, LINE)
    (d,) = places(tab, [FOURTH])
    for n, place in enumerate((a, b, c), start=1):
        click_place(page, place)
        expect(draw_count(page)).to_have_text(COUNTS[n])
        assert "draw" in overlay_ids(page)

    page.keyboard.press("Backspace")

    expect(draw_count(page)).to_have_text(COUNTS[2])
    assert "draw" in overlay_ids(page)
    # The double click's first click adds its vertex, the second ends the line
    line = finish_line(tab, lambda: page.mouse.dblclick(*screen_point(page, *d)))
    assert_line(page, line, [a, b, d])
    expect(drawing_tools(page)).to_be_hidden()


def test_profile_esc_cancels_line(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    page.get_by_role("radio", name="Profil terenu", exact=True).click()
    mark = tab.mark()
    for n, place in enumerate(places(tab, LINE[:2]), start=1):
        click_place(page, place)
        expect(draw_count(page)).to_have_text(COUNTS[n])

    page.keyboard.press("Escape")

    expect(drawing_tools(page)).to_be_hidden()
    ids = overlay_ids(page)
    assert "draw" not in ids and "profile-line" not in ids, ids
    expect(profile_drawer(page)).to_be_hidden()
    tab.settle()
    assert tab.sent_since(mark, PROFILE.pattern) == []


def test_profile_chart_readout_moves_point_along_line(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    page.get_by_role("radio", name="Profil terenu", exact=True).click()
    a, b, c = places(tab, LINE)
    click_place(page, a)
    click_place(page, b)
    line = finish_line(tab, lambda: page.mouse.dblclick(*screen_point(page, *c)))
    drawer = profile_drawer(page)
    box = drawer.get_by_role("img", name="Profil terenu").bounding_box()
    assert box is not None
    total, _ = along_line(line, line[-1])

    def hover(share: float) -> None:
        page.mouse.move(box["x"] + share * box["width"], box["y"] + box["height"] / 2)

    hover(0.3)
    first = readout_place(page)
    hover(0.7)
    second = readout_place(page, first)

    (along_first, off_first), (along_second, off_second) = (
        along_line(line, first),
        along_line(line, second),
    )
    assert off_first < ON_LINE_M and off_second < ON_LINE_M, (first, second, line)
    assert 0 < along_first < along_second < total, (along_first, along_second, total)
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] - 2 * box["height"])
    page.wait_for_function(
        "() => !Hydrograf.map.describe().overlays"
        ".some((o) => o.id === 'profile-marker')"
    )


def test_profile_phone_buttons_undo_cancel_and_draw(
    new_tab: Callable[..., Tab],
) -> None:
    tab = new_tab(width=390)
    page = tab.page
    open_map(tab)
    tools = drawing_tools(page)
    page.get_by_role("radio", name="Profil terenu", exact=True).tap()
    expect(tools).to_be_visible()
    a, b, _ = places(tab, PHONE_LINE)
    for n, place in enumerate((a, b), start=1):
        tap_place(page, place)
        expect(draw_count(page)).to_have_text(COUNTS[n])

    tools.get_by_role("button", name="Cofnij").tap()

    expect(draw_count(page)).to_have_text(COUNTS[1])
    expect(tools.get_by_role("button", name="Rysuj profil")).to_be_disabled()
    assert "draw" in overlay_ids(page)

    tools.get_by_role("button", name="Anuluj").tap()

    expect(tools).to_be_hidden()
    assert "draw" not in overlay_ids(page)

    page.get_by_role("radio", name="Profil terenu", exact=True).tap()
    expect(draw_count(page)).to_have_text(COUNTS[0])
    tap_place(page, a)
    tap_place(page, b)
    line = finish_line(
        tab, lambda: tools.get_by_role("button", name="Rysuj profil").tap()
    )
    assert_line(page, line, [a, b])


def test_profile_phone_tap_near_last_vertex_ends_line(
    new_tab: Callable[..., Tab],
) -> None:
    tab = new_tab(width=390)
    page = tab.page
    open_map(tab)
    page.get_by_role("radio", name="Profil terenu", exact=True).tap()
    vertices = places(tab, PHONE_LINE)
    for n, place in enumerate(vertices, start=1):
        tap_place(page, place)
        expect(draw_count(page)).to_have_text(COUNTS[n])

    line = finish_line(tab, lambda: tap_place(page, vertices[-1], NEAR_LAST_PX))

    assert_line(page, line, vertices)
