"""Browser tests of the cursor's coordinates at the map's bottom left (js/coords.js).

Nogat's plan 2026-11-24-hydrograf-maplibre, step 1, the bullet „the coordinates
control (coords.js:141-190): a mouse move writes the cursor's coordinates in the chosen
system”. The mouse moves to whole pixels of the map; the readout (titled „Współrzędne
kursora”) shows the place under the cursor (``map_place``) in WGS84 as the control
writes it, degrees to five decimals with a decimal comma, within a pixel; once its own
select („Układ współrzędnych kursora”) chooses PL-1992 or PL-2000, it shows the place's
X and Y as pyproj projects it (EPSG:2180; EPSG:2178, zone 7, for the catchment at
about 20.5°E) within a pixel's size on the ground. The module keeps the choice in
localStorage, so the page opened again writes in the system chosen before.
"""

import math
import re
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, expect
from pyproj import Transformer

from tests.e2e.browser import Tab, describe, map_place, open_map

READOUT = "Współrzędne kursora"
SYSTEM = "Układ współrzędnych kursora"
# „52,35097° N 20,47637° E”, „X 499 360 Y 600 526 m” (groups of digits apart)
WGS84 = re.compile(r"(\d+,\d+)° ([NS])\s(\d+,\d+)° ([EW])")
GRID = re.compile(r"X (\d{1,3}(?:\s\d{3})*)\sY (\d{1,3}(?:\s\d{3})*) m")
ZONE_7 = "strefa 7"
# Half the last digit the readout writes: of degrees and of metres
DEGREES_ROUNDING = 0.5e-5
METRES_ROUNDING = 0.5
# OGC's standard rendering pixel, the unit of describe()'s scale [m]
STANDARD_PIXEL_M = 0.00028
# Where the mouse goes: fractions of the map's width and height, clear of controls
SPOTS = ((0.45, 0.40), (0.62, 0.58))
TO_PL1992 = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True)
TO_PL2000_ZONE_7 = Transformer.from_crs("EPSG:4326", "EPSG:2178", always_xy=True)

Place = tuple[float, float]
Pixel = tuple[int, int]


def readout(page: Page) -> Locator:
    return page.get_by_title(READOUT, exact=True)


def system(page: Page) -> Locator:
    return page.get_by_role("combobox", name=SYSTEM, exact=True)


def spots(page: Page) -> list[Pixel]:
    """Whole page pixels of the map at ``SPOTS``."""
    box = page.locator("#map").bounding_box()
    assert box is not None
    return [
        (round(box["x"] + fx * box["width"]), round(box["y"] + fy * box["height"]))
        for fx, fy in SPOTS
    ]


def shown(page: Page) -> str:
    """What the readout writes after its select (whose options' text comes first)."""
    text = readout(page).text_content() or ""
    options = system(page).text_content() or ""
    assert text.startswith(options), (text, options)
    return text[len(options) :]


def move_to(page: Page, pixel: Pixel) -> str:
    """Move the mouse to a page pixel; what the readout writes once it follows."""
    before = readout(page).text_content() or ""
    page.mouse.move(*pixel)
    expect(readout(page)).not_to_have_text(before)
    return shown(page)


def degrees(text: str) -> Place:
    """(longitude, latitude) the readout writes in WGS84."""
    found = WGS84.search(text)
    assert found, text
    lat = float(found[1].replace(",", ".")) * (1 if found[2] == "N" else -1)
    lng = float(found[3].replace(",", ".")) * (1 if found[4] == "E" else -1)
    return lng, lat


def grid(text: str) -> tuple[float, float]:
    """(X, Y) the readout writes in PL-1992 or PL-2000: northing, easting [m]."""
    found = GRID.search(text)
    assert found, text
    return float(re.sub(r"\s", "", found[1])), float(re.sub(r"\s", "", found[2]))


def projected(transformer: Transformer, place: Place) -> tuple[float, float]:
    """(X, Y) of a place by pyproj: northing, easting [m]."""
    easting, northing = transformer.transform(*place)
    return northing, easting


def pixel_metres(described: dict[str, Any]) -> float:
    """The size of a pixel of the map on the ground at its centre [m]."""
    lat = described["center"][1]
    return float(described["scale"]) * STANDARD_PIXEL_M * math.cos(math.radians(lat))


def assert_degrees(page: Page, text: str, pixel: Pixel) -> None:
    """The readout writes the place under a pixel in WGS84 within a pixel."""
    x, y = pixel
    place = map_place(page, x, y)
    beside = map_place(page, x + 1, y + 1)
    for value, expected, other in zip(degrees(text), place, beside, strict=True):
        tolerance = abs(other - expected) + DEGREES_ROUNDING
        assert value == pytest.approx(expected, abs=tolerance), (text, place)


def assert_grid(page: Page, text: str, pixel: Pixel, transformer: Transformer) -> None:
    """The readout writes the place under a pixel in a grid within a pixel's size."""
    expected = projected(transformer, map_place(page, *pixel))
    tolerance = pixel_metres(describe(page)) + METRES_ROUNDING
    assert grid(text) == pytest.approx(expected, abs=tolerance), (text, expected)


def test_coordinates_follow_the_cursor_in_the_chosen_system(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    chooser = system(page)
    expect(chooser.locator("option:checked")).to_have_text("WGS84")
    first, second = spots(page)

    assert_degrees(page, move_to(page, first), first)
    assert_degrees(page, move_to(page, second), second)

    # The cursor stays at the second spot: the readout writes it in the new system
    chooser.select_option(label="PL-1992")
    expect(readout(page)).to_contain_text(GRID)
    assert_grid(page, shown(page), second, TO_PL1992)

    chooser.select_option(label="PL-2000")
    expect(readout(page)).to_contain_text(ZONE_7)
    assert_grid(page, shown(page), second, TO_PL2000_ZONE_7)
    text = move_to(page, first)
    assert ZONE_7 in text, text
    assert_grid(page, text, first, TO_PL2000_ZONE_7)


def test_coordinates_system_chosen_holds_when_the_page_opens_again(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    system(page).select_option(label="PL-2000")

    # Opened again, as a reload: the module reads the choice from localStorage
    open_map(tab)

    expect(system(page).locator("option:checked")).to_have_text("PL-2000")
    pixel = spots(page)[1]
    text = move_to(page, pixel)
    assert ZONE_7 in text, text
    assert_grid(page, text, pixel, TO_PL2000_ZONE_7)
