"""Browser tests of the option „Sieć zlewni” of „Wybierz zlewnię” (js/network.js).

Nogat's plan 2026-11-24-hydrograf-maplibre, step 1, the bullet „the network: points
placed, dragged and snapped, a label selects its element and places none, a click on a
point places none”:

* placed and snapped: clicks on the pixels of cells of the synthetic catchment place
  the closing section on the main river above the outlet, a point on T2 two cells
  above its mouth (within 50 m of the confluence, so the answer draws it into its
  node) and one three cells east of the main river; each request of the preview
  (POST /api/delineate-network/preview) carries the place clicked, and once its
  answer is shown every marker of ``describe()['points']`` stands at the place its
  point snapped to under the id of its node, the network is drawn, and the panel
  lists the points with their name fields and „Usuń”, a name naming the marker;
* dragged: the mouse drags a marker, found by its title as a pointer shows it, to a
  cell off the main river; the next preview carries the place it was dropped at, and
  the marker moves on to where that place snapped;
* a click on the label of an element (the labels name the elements on the map)
  selects it in the panel's tree and places no point; a click on a point's marker
  places no point either.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, Response, expect

from tests.e2e.browser import Tab, describe, map_place, open_map, overlay, screen_point
from tests.e2e.site import MAIN_RIVER_COL

# Cells (row, column) clicked: the closing section on the main river above the outlet,
# a point on T2 two cells above its mouth, which the preview draws into the confluence,
# and a point three cells east of the main river, which snaps onto it
OUTLET_CELL = (215, MAIN_RIVER_COL)
T2_MOUTH_CELL = (123, MAIN_RIVER_COL + 2)
EAST_OF_RIVER_CELL = (100, MAIN_RIVER_COL + 3)
# A marker stands where the answer put its point: the same numbers, no projection [°]
SNAPPED_TOLERANCE_DEG = 1e-7
# Two places closer than this are the same [°]
SAME_PLACE_DEG = 1e-6
PENDING = "Podgląd sieci…"
TREE = "Drzewo sieci od przekroju zamykającego w górę"

Place = tuple[float, float]


def as_place(point: dict[str, Any]) -> Place:
    """(longitude, latitude) of a point of a request or an answer."""
    return point["longitude"], point["latitude"]


@dataclass
class Preview:
    """A request of the network's preview and its answer."""

    body: dict[str, Any]
    answer: dict[str, Any]

    def asked(self) -> list[dict[str, Any]]:
        """The points of the request, the closing section first."""
        return [self.body["outlet"], *self.body["points"]]

    def snapped(self) -> dict[str, Place]:
        """The places the points snapped to by the ids of their nodes."""
        return {p["node"]: as_place(p) for p in self.answer["points"]}

    def answer_to(self, place: Place, size: Place) -> dict[str, Any]:
        """The answer's point of the one point the request asked within a pixel of
        ``place``."""
        handles = [p["id"] for p in self.asked() if within(as_place(p), place, size)]
        assert len(handles) == 1, f"{place} is not one point of {self.body}"
        return next(p for p in self.answer["points"] if p["id"] == handles[0])


@dataclass
class Click:
    """A click in the option: the place clicked, the preview it asked for and the
    answer's point of the click (its node, where it snapped)."""

    place: Place
    preview: Preview
    point: dict[str, Any]


def is_preview(response: Response) -> bool:
    return response.request.method == "POST" and response.url.endswith(
        "/api/delineate-network/preview"
    )


def within(place: Place, expected: Place, size: Place) -> bool:
    """Whether ``place`` lies within ``size`` (degrees of longitude, latitude)."""
    return all(abs(a - b) <= s for a, b, s in zip(place, expected, size, strict=True))


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


def enter_network(page: Page) -> None:
    """Choose the mode „Wybierz zlewnię” and its option „Sieć zlewni”."""
    page.get_by_role("radio", name="Wybierz zlewnię", exact=True).click()
    page.get_by_role("radio", name="Sieć zlewni", exact=True).click()
    expect(page.get_by_role("region", name="Sieć zlewni", exact=True)).to_be_visible()


def preview_after(tab: Tab, action: Callable[[], None]) -> Preview:
    """Do ``action``; return the preview it asked for once the page shows its answer."""
    page = tab.page
    with page.expect_response(is_preview) as answered:
        action()
    response = answered.value
    assert response.ok, f"the preview failed: {response.status} {response.text()}"
    # „Podgląd sieci…” shows from a change of the points until its answer is shown
    expect(page.get_by_text(PENDING, exact=True)).to_be_hidden()
    body = response.request.post_data_json
    assert isinstance(body, dict), body
    return Preview(body, response.json())


def place_at(tab: Tab, cell: tuple[int, int]) -> Click:
    """Click a cell of the DEM in the option."""
    page = tab.page
    x, y = cell_pixel(tab, cell)
    clicked = map_place(page, x, y)
    preview = preview_after(tab, lambda: page.mouse.click(x, y))
    return Click(clicked, preview, preview.answer_to(clicked, pixel_size(page)))


def points_shown(page: Page) -> dict[str, Place]:
    """The network's markers on the map by their ids: (longitude, latitude)."""
    return {p["id"]: (p["lngLat"][0], p["lngLat"][1]) for p in describe(page)["points"]}


def assert_markers_snapped(page: Page, preview: Preview) -> None:
    """The map shows the answered points, each where it snapped under its node's id."""
    shown = points_shown(page)
    snapped = preview.snapped()
    assert sorted(shown) == sorted(snapped), (shown, snapped)
    for node, place in snapped.items():
        assert shown[node] == pytest.approx(place, abs=SNAPPED_TOLERANCE_DEG), node


def point_marker(page: Page, point_id: str) -> Locator:
    """The marker of a point by its title, „J1 – punkt sieci…” or „J1 (name) – …”.

    The title is what a pointer over the marker shows; the labels of the elements are
    titled „Z1: …” and „R1: …”.
    """
    return page.get_by_title(re.compile(rf"^{re.escape(point_id)}[ (]"))


def drag(page: Page, marker: Locator, x: int, y: int) -> None:
    """Drag a marker with the mouse from its centre to a page pixel.

    The pointer goes down on the marker's own element, as a person grabs it: that
    element is the handle that moves the point, whatever library draws the map. The
    pointer moves by whole pixels, as a mouse's events count them, and the marker's
    anchor is its centre, so the point is dropped within a pixel of (x, y).
    """
    box = marker.bounding_box()
    assert box is not None, "the marker is not shown"
    page.mouse.move(
        round(box["x"] + box["width"] / 2), round(box["y"] + box["height"] / 2)
    )
    page.mouse.down()
    page.mouse.move(x, y, steps=10)
    page.mouse.up()


def closing_section_and_t2(tab: Tab) -> Click:
    """The closing section and the point at T2's mouth placed; the latter's click."""
    open_map(tab)
    enter_network(tab.page)
    place_at(tab, OUTLET_CELL)
    return place_at(tab, T2_MOUTH_CELL)


def test_network_points_placed_snap_to_the_streams_and_are_listed(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    enter_network(page)

    outlet = place_at(tab, OUTLET_CELL)
    assert outlet.preview.body["points"] == []
    assert_markers_snapped(page, outlet.preview)
    assert overlay(page, "network") is not None

    for cell in (T2_MOUTH_CELL, EAST_OF_RIVER_CELL):
        click = place_at(tab, cell)
        assert_markers_snapped(page, click.preview)
        # Its marker left the place clicked for the stream cell it snapped to
        assert as_place(click.point) != pytest.approx(click.place, abs=SAME_PLACE_DEG)
    ids = sorted(click.preview.snapped())
    assert len(ids) == 3, ids
    assert overlay(page, "network") is not None

    rows = page.get_by_role("list", name="Punkty sieci").get_by_role("listitem")
    expect(rows).to_have_count(len(ids))
    for point_id in ids:
        name = rows.get_by_role("textbox", name=f"Nazwa punktu {point_id}", exact=True)
        expect(name).to_be_editable()
        remove = rows.get_by_role("button", name=f"Usuń punkt {point_id}", exact=True)
        expect(remove).to_have_text("Usuń")

    # A name typed in the panel names the point's marker on the map
    named = click.point["node"]
    rows.get_by_role("textbox", name=f"Nazwa punktu {named}", exact=True).fill(
        "Dopływ wschodni"
    )
    expect(point_marker(page, named)).to_have_attribute(
        "title", re.compile(rf"^{named} \(Dopływ wschodni\) – ")
    )


def test_network_point_dragged_moves_and_snaps_again(tab: Tab) -> None:
    page = tab.page
    t2 = closing_section_and_t2(tab)
    outlet = t2.preview.answer["points"][0]
    x, y = cell_pixel(tab, EAST_OF_RIVER_CELL)
    dropped = map_place(page, x, y)

    after = preview_after(
        tab, lambda: drag(page, point_marker(page, t2.point["node"]), x, y)
    )

    # The request carries the place the marker was dropped at; the outlet stays
    asked = after.asked()
    assert len(asked) == 2, after.body
    assert as_place(asked[0]) == pytest.approx(
        as_place(outlet), abs=SNAPPED_TOLERANCE_DEG
    )
    moved = after.answer_to(dropped, pixel_size(page))
    # It snapped again: the marker leaves the drop for its stream cell, away from
    # the confluence it was dragged from
    assert as_place(moved) != pytest.approx(dropped, abs=SAME_PLACE_DEG)
    assert as_place(moved) != pytest.approx(as_place(t2.point), abs=SAME_PLACE_DEG)
    assert_markers_snapped(page, after)


def test_network_label_selects_its_element_and_places_no_point(tab: Tab) -> None:
    page = tab.page
    t2 = closing_section_and_t2(tab)
    # An element of the network that flows into T2's node, by the id its label shows
    element = next(
        s["id"]
        for s in t2.preview.answer["subcatchments"]
        if s["kind"] == "headwater" and s["to"] == t2.point["node"]
    )
    tree = page.get_by_role("table", name=TREE, exact=True)
    row = tree.get_by_role("button", name=re.compile(rf"^{element} "))
    expect(row).to_have_attribute("aria-pressed", "false")
    mark = tab.mark()

    page.get_by_title(re.compile(rf"^{element}: ")).click()

    expect(row).to_have_attribute("aria-pressed", "true")
    expect(
        page.get_by_role("heading", name=re.compile(rf"^{element} · "))
    ).to_be_visible()
    tab.settle()
    assert tab.sent_since(mark, r"/api/delineate-network") == []
    assert_markers_snapped(page, t2.preview)


def test_network_click_on_a_point_places_no_point(tab: Tab) -> None:
    page = tab.page
    t2 = closing_section_and_t2(tab)
    mark = tab.mark()

    point_marker(page, t2.point["node"]).click()

    tab.settle()
    assert tab.sent_since(mark, r"/api/delineate-network") == []
    assert_markers_snapped(page, t2.preview)
