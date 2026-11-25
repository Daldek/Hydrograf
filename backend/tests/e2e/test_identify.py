"""Browser tests of the mode „Identyfikuj” (js/identify.js): where its marker shows.

Nogat's plan 2026-11-24-hydrograf-maplibre, step 1, the bullet „identify's marker
stays above the sheet at 390 px”: on a phone a tap low on the map, where the point
card opens as a bottom sheet, puts the marker on the place tapped and the map moves so
that the marker shows above the sheet's top edge (``keepMarkerVisible``); on a desktop
the marker shows on the place clicked, beside the card. The card is found by its role
and name, its answer by GET /api/v1/point/identify (the command ``point identify``);
the marker is the overlay ``identify-marker`` of ``Hydrograf.map.describe()``, its
page pixel read by ``screen_point`` once the view is still.
"""

from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Locator, Page, Response, expect

from tests.e2e.browser import (
    Tab,
    describe,
    map_place,
    open_map,
    screen_point,
    wait_view,
)

# Cells (row, column) of the DEM: one in the south-west of the catchment, low on a
# phone's screen at the opening view, and one in its west, left of a desktop's card
PHONE_CELL = (205, 60)
DESKTOP_CELL = (110, 40)
CARD = "Informacje o punkcie"
# A row of the card's answer (the point's elevation)
ANSWERED = "Rzędna terenu"
# The marker stands on the point asked about: the same numbers, no projection [°]
SAME_PLACE_DEG = 1e-7

Place = tuple[float, float]


def is_identify(response: Response) -> bool:
    return urlsplit(response.url).path == "/api/v1/point/identify"


def asked_place(response: Response) -> Place:
    """(longitude, latitude) GET /api/v1/point/identify asked about."""
    query = parse_qs(urlsplit(response.url).query)
    return float(query["longitude"][0]), float(query["latitude"][0])


def pixel_size(page: Page) -> Place:
    """The size of one CSS pixel of the map in degrees of longitude and latitude."""
    west, south, east, north = describe(page)["bounds"]
    box = page.locator("#map").bounding_box()
    assert box is not None
    return (east - west) / box["width"], (north - south) / box["height"]


def cell_pixel(tab: Tab, cell: tuple[int, int]) -> tuple[int, int]:
    """The whole page pixel at the centre of a cell of the DEM."""
    x, y = screen_point(tab.page, *tab.site.cell_lnglat(*cell))
    return round(x), round(y)


def identify(tab: Tab, press: Callable[[], None]) -> tuple[Locator, Place]:
    """Identify by ``press`` on the map: the card once answered, the place asked."""
    page = tab.page
    with page.expect_response(is_identify) as answered:
        press()
    response = answered.value
    assert response.ok, f"identify failed: {response.status} {response.text()}"
    card = page.get_by_role("region", name=CARD, exact=True)
    expect(card.get_by_text(ANSWERED, exact=True)).to_be_visible()
    tab.settle()
    return card, asked_place(response)


def marker_place(described: dict[str, Any]) -> Place:
    """The place of the overlay ``identify-marker``."""
    markers = [o for o in described["overlays"] if o["id"] == "identify-marker"]
    assert len(markers) == 1, described["overlays"]
    lng, lat = markers[0]["lngLat"]
    return lng, lat


def test_identify_marker_stays_above_the_sheet_at_390_px(
    new_tab: Callable[..., Tab],
) -> None:
    tab = new_tab(width=390)
    page = tab.page
    open_map(tab)
    page.get_by_role("radio", name="Identyfikuj", exact=True).click()
    wait_view(page)
    x, y = cell_pixel(tab, PHONE_CELL)
    tapped = map_place(page, x, y)
    size = pixel_size(page)

    card, asked = identify(tab, lambda: page.touchscreen.tap(x, y))

    described = wait_view(page)
    sheet = card.bounding_box()
    area = page.locator("#map").bounding_box()
    assert sheet is not None and area is not None
    # The sheet covers the place tapped: the map has to move the marker clear of it
    assert y > sheet["y"], (y, sheet)
    place = marker_place(described)
    assert place == pytest.approx(asked, abs=SAME_PLACE_DEG), (place, asked)
    assert place == pytest.approx(tapped, abs=max(size)), (place, tapped)
    mx, my = screen_point(page, *place, described)
    assert area["y"] <= my < sheet["y"], (my, sheet, area)
    assert area["x"] <= mx <= area["x"] + area["width"], (mx, area)


def test_identify_marker_shows_where_the_map_was_clicked(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    page.get_by_role("radio", name="Identyfikuj", exact=True).click()
    wait_view(page)
    x, y = cell_pixel(tab, DESKTOP_CELL)
    clicked = map_place(page, x, y)
    size = pixel_size(page)

    card, asked = identify(tab, lambda: page.mouse.click(x, y))

    described = wait_view(page)
    place = marker_place(described)
    assert place == pytest.approx(asked, abs=SAME_PLACE_DEG), (place, asked)
    assert place == pytest.approx(clicked, abs=max(size)), (place, clicked)
    # It shows on the map beside the card; the strip of the data's providers that
    # opens under the map with the card makes the map shorter, which may move the
    # view by a few pixels, so the pixel is the place's, not the one clicked
    mx, my = screen_point(page, *place, described)
    area = page.locator("#map").bounding_box()
    box = card.bounding_box()
    assert area is not None and box is not None
    assert area["x"] <= mx < box["x"], (mx, area, box)
    assert area["y"] <= my <= area["y"] + area["height"], (my, area)
