"""The admin dialog's map: a drag draws the box and fills the four fields.

Nogat's plan 2026-11-24-hydrograf-maplibre, step 1, „Tests”: „the admin dialog, under
the CSP of docker/nginx.conf:94: a drag draws the box and fills the four fields”.

The admin page's document carries nginx's admin policy (its location ``^~
/_site/admin/``); the tab fails at its end on any violation. Signed in with the admin
key, the section „Przetwarzanie NMT” opens the dialog
„Wybierz obszar na mapie”, whose map is fitted to the box of the four fields (their
defaults): whatever library draws it and at whatever scale, the map's centre is that
box's centre in web mercator. A mouse drag from the upper left to the lower right
draws the box in the accent colour (pixels on its edges nearest to the accent token,
where the map showed no such colour before) and, confirmed, fills the fields with the
places under the drag's ends: north above south, east of west, all four changed from
the defaults, and one scale (the fields' degrees per pixel across) puts west, north
and south at the drag's offsets from the centre, up and down in web mercator as
across, within PIXEL_TOLERANCE pixels.
"""

import math

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.browser import Rgb, Tab, nearest, pixels
from tests.e2e.site import ADMIN_KEY
from tests.e2e.test_layers import wait_still

SIDES = ("west", "south", "east", "north")
# How far (pixels) a field may lie from the place under its end of the drag
PIXEL_TOLERANCE = 2.0
# The drag within the map: from LEFT to RIGHT of its width, TOP_PX below its top to
# BOTTOM_PX above its bottom. The map fits the default box with 40 px to spare, so the
# box's top and bottom edges never lie on the default one's; the ends keep clear of
# the zoom buttons (top left) and the credits (bottom right).
LEFT, RIGHT = 0.30, 0.85
TOP_PX, BOTTOM_PX = 20, 30


def _mercator_y(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _sign_in(page: Page) -> None:
    """Sign in to the admin panel through the kit's key prompt."""
    page.get_by_label("Klucz administratora", exact=True).fill(ADMIN_KEY)
    page.get_by_role("button", name="Zaloguj", exact=True).click()


def _fields(page: Page) -> dict[str, str]:
    """The values of the four fields of the box by side, read at once."""
    values: dict[str, str] = page.evaluate(
        "(sides) => Object.fromEntries(sides.map((side) =>"
        " [side, document.getElementById('bbox-' + side).value]))",
        list(SIDES),
    )
    return values


def _token_rgb(page: Page, name: str) -> Rgb:
    """A colour token of tokens.css in the page's theme, as drawn on a canvas."""
    value: list[int] = page.evaluate(
        """(name) => {
            const context = document.createElement("canvas").getContext("2d");
            context.fillStyle = getComputedStyle(document.documentElement)
                .getPropertyValue(name).trim();
            context.fillRect(0, 0, 1, 1);
            return Array.from(context.getImageData(0, 0, 1, 1).data.slice(0, 3));
        }""",
        name,
    )
    return value[0], value[1], value[2]


def _drawn(before: list[Rgb], after: list[Rgb], color: Rgb) -> bool:
    """Whether a pixel now is nearer to ``color`` than to any the map showed before."""
    candidates = {"drawn": color} | {f"before {i}": c for i, c in enumerate(before)}
    return any(nearest(pixel, candidates) == "drawn" for pixel in after)


def test_admin_dialog_drag_draws_box_and_fills_fields(tab: Tab) -> None:
    page = tab.page
    response = page.goto(tab.site.base + "/admin/#processing")
    assert response is not None
    policy = response.header_value("Content-Security-Policy")
    assert policy == tab.site.policies.admin
    _sign_in(page)
    expect(
        page.get_by_role("heading", name="Przetwarzanie NMT", exact=True)
    ).to_be_visible()
    typed = _fields(page)
    defaults = {side: float(value) for side, value in typed.items()}

    page.locator("#bbox-map-open").click()
    dialog = page.get_by_role("dialog", name="Wybierz obszar na mapie")
    expect(dialog).to_be_visible()
    area = page.locator("#bbox-map")
    tab.settle()
    wait_still(page, area)
    box = area.bounding_box()
    assert box is not None
    centre_x = box["x"] + box["width"] / 2
    centre_y = box["y"] + box["height"] / 2
    start = round(box["x"] + LEFT * box["width"]), round(box["y"] + TOP_PX)
    end = (
        round(box["x"] + RIGHT * box["width"]),
        round(box["y"] + box["height"] - BOTTOM_PX),
    )
    middle_x = (start[0] + end[0]) / 2
    edges = [(middle_x, start[1]), (middle_x, end[1])]
    before = [pixels(page, x, y) for x, y in edges]

    page.mouse.move(*start)
    page.mouse.down()
    page.mouse.move(*end, steps=12)
    page.mouse.up()
    confirm = page.locator("#bbox-confirm")
    expect(confirm).to_be_enabled()
    accent = _token_rgb(page, "--accent")
    for (x, y), shown in zip(edges, before, strict=True):
        assert _drawn(shown, pixels(page, x, y), accent), f"no box edge at {x}, {y}"

    confirm.click()
    expect(dialog).to_be_hidden()
    # The dialog's close event, which fills the fields, follows its closing
    for side in SIDES:
        expect(page.locator(f"#bbox-{side}")).not_to_have_value(typed[side])
    expect(page.locator("#bbox-error")).to_be_hidden()
    filled = {side: float(value) for side, value in _fields(page).items()}
    west, south, east, north = (filled[side] for side in SIDES)
    assert north > south, filled
    assert east > west, filled

    # The map's centre: the default box's centre in web mercator
    centre_lng = (defaults["west"] + defaults["east"]) / 2
    centre_merc = (_mercator_y(defaults["south"]) + _mercator_y(defaults["north"])) / 2
    # One scale across and up: degrees and mercator radians per pixel
    per_px = (east - west) / (end[0] - start[0])
    per_px_merc = math.radians(per_px)
    assert west == pytest.approx(
        centre_lng - per_px * (centre_x - start[0]), abs=PIXEL_TOLERANCE * per_px
    )
    assert _mercator_y(north) == pytest.approx(
        centre_merc + per_px_merc * (centre_y - start[1]),
        abs=PIXEL_TOLERANCE * per_px_merc,
    )
    assert _mercator_y(south) == pytest.approx(
        centre_merc - per_px_merc * (end[1] - centre_y),
        abs=PIXEL_TOLERANCE * per_px_merc,
    )
