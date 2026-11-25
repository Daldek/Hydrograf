"""Browser tests of delineating one watershed by a click (js/app.js, js/map.js).

Nogat's plan 2026-11-24-hydrograf-maplibre, step 1, the bullet „a click delineates:
the preview, then the boundary, outlet, main channel and flow paths with their
legend, the view fitted; the outlet's tooltip”. In the mode „Wybierz zlewnię”, option
„Jedna zlewnia”, a click on the main river between the mouths of T2 and T1 asks
POST /api/delineate-watershed/preview and POST /api/delineate-watershed together.
The second is held by ``page.route`` until the preview is drawn (overlay ``preview``
of ``Hydrograf.map.describe()``), then let through: its answer replaces the preview by
the overlays ``watershed``, ``outlet``, ``main-channel``, ``longest-flow-path`` and
``divide-flow-path`` (where the answer has them), drawn above the streams (M4's
order). The answer is the reference of the rest: the rows of the map's legend
„Zlewnia” (title and labels by their text), the view (``describe()``'s bounds)
fitted to the boundary, the tooltip a hover over the outlet shows and the parameters
of the results panel „Zlewnia”.
"""

import json
import math
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, Route, expect

from tests.e2e.browser import (
    Tab,
    describe,
    open_map,
    overlay_ids,
    screen_point,
    wait_view,
)
from tests.e2e.site import MAIN_RIVER_COL, THRESHOLDS_M2

# On the main river between T2's mouth (row 123) and T1's (row 159): the watershed of
# that reach, the main river above T1's mouth with T2 and T3, smaller than the data
CLICK_CELL = (140, MAIN_RIVER_COL)
# The map asks with the threshold of its streams' layer, the largest by default
DEFAULT_THRESHOLD_M2 = THRESHOLDS_M2[-1]
DELINEATION = re.compile(r"/api/delineate-watershed(\?|$)")
PREVIEW = r"/api/delineate-watershed/preview$"
# The overlays of a delineated watershed
PARTS = ("watershed", "outlet", "main-channel", "longest-flow-path", "divide-flow-path")
# Their rows of the legend „Zlewnia”; the main channel's by its kinds of segment
PART_LABELS = {
    "watershed": "Granica zlewni",
    "outlet": "Ujście",
    "longest-flow-path": "Najdłuższa droga spływu",
    "divide-flow-path": "Najdłuższa droga spływu od granicy zlewni",
}
CHANNEL_LABELS = {True: "Ciek główny (BDOT10k)", False: "Ciek główny (z NMT)"}
# A view fitted to the boundary: the boundary spans more than half of it across or
# along (at a coarser scale step it would span less than half); the opening view,
# fitted to the whole data, leaves it less
FITTED_SHARE = 0.5
# The place clicked as the requests carry it [°]: the pixel clicked, rounded
CLICKED_DEG = 1e-4
# Places the map and the API both hold as numbers, compared without projection [°]
SAME_PLACE_DEG = 1e-7

Place = tuple[float, float]


def js_fixed(value: float, digits: int) -> str:
    """JavaScript's ``value.toFixed(digits)``: of two nearest, the larger."""
    step = Decimal(1).scaleb(-digits)
    return str(Decimal(value).quantize(step, rounding=ROUND_HALF_UP))


def mercator_y(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def coordinates(geojson: dict[str, Any]) -> list[Place]:
    """Every position of a GeoJSON geometry, feature or feature collection."""
    if geojson["type"] == "Feature":
        return coordinates(geojson["geometry"])
    if geojson["type"] == "FeatureCollection":
        return [p for f in geojson["features"] for p in coordinates(f)]
    found: list[Place] = []

    def walk(item: list[Any]) -> None:
        if isinstance(item[0], (int, float)):
            found.append((float(item[0]), float(item[1])))
        else:
            for child in item:
                walk(child)

    walk(geojson["coordinates"])
    return found


def view_share(view: dict[str, Any], boundary: dict[str, Any]) -> float:
    """How much of the view the boundary spans, across or along (the larger)."""
    places = coordinates(boundary)
    lngs = [lng for lng, _ in places]
    lats = [lat for _, lat in places]
    west, south, east, north = (float(edge) for edge in view["bounds"])
    across = (max(lngs) - min(lngs)) / (east - west)
    along = (mercator_y(max(lats)) - mercator_y(min(lats))) / (
        mercator_y(north) - mercator_y(south)
    )
    return max(across, along)


def expected_parts(watershed: dict[str, Any]) -> set[str]:
    """The overlays of the watershed of an answer of POST /api/delineate-watershed."""
    geojson = {
        "main-channel": watershed["main_stream_geojson"],
        "longest-flow-path": watershed["longest_flow_path_geojson"],
        "divide-flow-path": watershed["divide_flow_path_geojson"],
    }
    return {"watershed", "outlet"} | {part for part, g in geojson.items() if g}


def wait_for_overlay(page: Page, overlay_id: str) -> None:
    """Wait until the map draws the overlay ``overlay_id``."""
    page.wait_for_function(
        "(id) => Hydrograf.map.describe().overlays.some((o) => o.id === id)",
        arg=overlay_id,
    )


def choose_single_watershed(page: Page) -> None:
    """The mode „Wybierz zlewnię”, option „Jedna zlewnia”; the results column opens."""
    page.get_by_role("radio", name="Wybierz zlewnię", exact=True).click()
    page.get_by_role("radio", name="Jedna zlewnia", exact=True).click()
    expect(page.get_by_role("complementary", name="Zlewnia")).to_be_visible()
    wait_view(page)


def click_cell(tab: Tab, cell: tuple[int, int]) -> Place:
    """Click the centre of a cell of the DEM; the place clicked."""
    place = tab.site.cell_lnglat(*cell)
    tab.page.mouse.click(*screen_point(tab.page, *place))
    return place


def delineate(tab: Tab) -> dict[str, Any]:
    """Delineate by a click on CLICK_CELL; the API's answer, once drawn."""
    page = tab.page
    with page.expect_response(DELINEATION) as answered:
        click_cell(tab, CLICK_CELL)
    response = answered.value
    assert response.ok, f"delineation failed: {response.status} {response.text()}"
    wait_for_overlay(page, "watershed")
    # The hydrograph the page asks for next, the tiles of the fitted view
    tab.settle()
    wait_view(page)
    answer: dict[str, Any] = response.json()
    return answer


def map_legend(page: Page, title: str) -> Locator:
    """The legend of the map with the title ``title``."""
    return page.locator("#map").get_by_text(title, exact=True).locator("..")


def test_delineation_click_shows_preview_until_result_replaces_it(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    page.get_by_label("Linie spływu", exact=True).check()
    tab.settle()
    choose_single_watershed(page)
    held: list[Route] = []

    def hold(route: Route) -> None:
        held.append(route)

    page.route(DELINEATION, hold)
    mark = tab.mark()

    clicked = click_cell(tab, CLICK_CELL)

    wait_for_overlay(page, "preview")
    previews = tab.sent_since(mark, PREVIEW)
    assert [sent.method for sent in previews] == ["POST"], previews
    asked = json.loads(previews[0].post_data or "{}")
    assert asked["threshold_m2"] == DEFAULT_THRESHOLD_M2, asked
    place = (asked["longitude"], asked["latitude"])
    assert place == pytest.approx(clicked, abs=CLICKED_DEG), (place, clicked)
    assert len(held) == 1, "the delineation was not asked with its preview"
    assert held[0].request.post_data_json == asked
    during = overlay_ids(page)
    assert not set(during) & set(PARTS), during
    assert during.index("streams") < during.index("preview"), during

    with page.expect_response(DELINEATION) as answered:
        held[0].continue_()
    parts = expected_parts(answered.value.json()["watershed"])
    wait_for_overlay(page, "watershed")

    after = overlay_ids(page)
    assert "preview" not in after, after
    assert set(after) & set(PARTS) == parts, after
    assert all(after.index("streams") < after.index(part) for part in parts), after
    # The boundary's fill lies under the lines and the point drawn in it
    inside = parts - {"watershed"}
    assert all(after.index("watershed") < after.index(part) for part in inside), after
    tab.settle()


def test_delineation_result_legend_names_the_parts_drawn(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    choose_single_watershed(page)

    watershed = delineate(tab)["watershed"]

    parts = expected_parts(watershed)
    assert set(overlay_ids(page)) & set(PARTS) == parts
    expected = {PART_LABELS[part] for part in parts if part in PART_LABELS}
    expected |= {
        CHANNEL_LABELS[bool(feature["properties"].get("is_real_stream"))]
        for feature in watershed["main_stream_geojson"]["features"]
    }
    legend = map_legend(page, "Zlewnia")
    expect(legend).to_be_visible()
    rows = [line.strip() for line in legend.inner_text().splitlines()[1:]]
    assert sorted(row for row in rows if row) == sorted(expected), rows


def test_delineation_result_view_fitted_to_boundary(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    choose_single_watershed(page)
    before = wait_view(page)

    boundary = delineate(tab)["watershed"]["boundary_geojson"]

    view = wait_view(page)
    lngs, lats = zip(*coordinates(boundary), strict=True)
    west, south, east, north = view["bounds"]
    assert west <= min(lngs) and max(lngs) <= east, (view["bounds"], lngs)
    assert south <= min(lats) and max(lats) <= north, (view["bounds"], lats)
    assert view_share(view, boundary) > FITTED_SHARE, view
    assert view_share(before, boundary) < FITTED_SHARE, before


def test_delineation_result_outlet_hover_shows_elevation(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    choose_single_watershed(page)
    outlet = delineate(tab)["watershed"]["outlet"]
    drawn = [o for o in describe(page)["overlays"] if o["id"] == "outlet"]
    assert len(drawn) == 1, drawn
    place = drawn[0]["lngLat"]
    answered = [outlet["longitude"], outlet["latitude"]]
    assert place == pytest.approx(answered, abs=SAME_PLACE_DEG), (place, answered)
    elevation = js_fixed(outlet["elevation_m"], 1)
    tooltip = page.get_by_text(f"Ujście: {elevation} m n.p.m.", exact=True)
    expect(tooltip).to_be_hidden()

    page.mouse.move(*screen_point(page, *place))

    expect(tooltip).to_be_visible()


def test_delineation_result_panel_shows_parameters(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    choose_single_watershed(page)

    watershed = delineate(tab)["watershed"]

    panel = page.get_by_role("complementary", name="Zlewnia")

    def values(label: str) -> Locator:
        """The value and the unit of a row of the parameters."""
        row = panel.get_by_role("row", name=re.compile(f"^{re.escape(label)}"))
        return row.get_by_role("cell")

    area = js_fixed(watershed["morphometry"]["area_km2"], 2)
    expect(values("Powierzchnia zlewni")).to_have_text([area, "km²"])
    elevation = js_fixed(watershed["outlet"]["elevation_m"], 1)
    expect(values("Ujście — wysokość")).to_have_text([elevation, "m n.p.m."])
