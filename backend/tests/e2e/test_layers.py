"""The layers panel: each overlay row, its opacity and legend; the view's extent.

Nogat's plan 2026-11-24-hydrograf-maplibre, step 1, „Tests”, read through what the
page shows (the panel's rows, the legends in the map's area), the requests it sends
and ``Hydrograf.map.describe()`` (the overlays drawn with their opacity, the view in
degrees and as a scale), never through the library that draws the map:

* „the page opens on the data's extent”: the first view contains the DEM's extent,
  which spans more than FIT_SHARE of the view across or up (a fit, not a far view);
* „each overlay row turns its layer on and off, its slider changes its opacity”:
  every row of the site (ROWS) turned on puts its overlay into ``describe()`` and
  asks for its data; once the map is still, its slider at 40 % shows „40%” in the
  row and gives the overlay an opacity of 0.4; turned off, the overlay leaves the
  map. A row with a legend shows it in the map's area while on and removes it when
  off. The opacity holds as the map moves: one step closer (new tiles), the overlay
  is still drawn at 0.4. For the land cover, the streams and the sewer it is not
  (LOST_OPACITY_DEFECT, strict xfails that turn into failures once fixed);
* „the sewer's tiles and the depressions' image turn on and off and take their
  opacity, as the other overlay rows”: their rows of ROWS, with the sewer's tile
  requests (``/api/tiles/sewer/``) and the depressions' image
  (``/data/depressions.png``); the sewer is drawn from 1:545 979 on, the page opens
  closer;
* „the extent button fits the enabled layers”: after zooming away by the map's own
  buttons, „Przybliż do zasięgu warstw” fits the view to the one layer on (the
  result), to the union of two (the result and the BDOT10k lake, which a fit to the
  result alone leaves out), and with nothing on to the data's extent (the streams
  tiles' bounds, else the DEM's).

A fit is read from ``describe()``: the view contains the extent and the extent spans
more than FIT_SHARE of it across or up, in web mercator. A fit at whole zoom levels
leaves the extent more than half of the view less its padding in one direction; a
finer fit leaves more.
"""

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.browser import (
    Tab,
    describe,
    open_map,
    overlay,
    overlay_ids,
    wait_view,
    zoom_in,
    zoom_out,
)
from tests.e2e.site import RESULT_ID, RESULT_TITLE, Site, result_bounds

Bounds = tuple[float, float, float, float]

# The share of the view's width or height an extent fitted to it spans at least
FIT_SHARE = 0.4
# The flood hazard map (MZP) is drawn from 1:50 000 on; the page opens closer
MZP_MAX_SCALE = 50_000
LAKE_ROW = "Zbiorniki wodne (BDOT10k)"
STILL_TIMEOUT_S = 30.0
# The rows whose slider's opacity the next tiles undo: it is written into the CSS of
# their VectorGrid container, which Leaflet's tile fade-in resets to the layer's own
LOST_OPACITY = {"landcover", "streams", "sewer"}
LOST_OPACITY_DEFECT = (
    "defect: the land cover's, streams' and sewer's sliders set their VectorGrid "
    "container's CSS opacity, which each tile's fade-in (Leaflet's "
    "GridLayer._updateOpacity) resets to 1"
)


@dataclass(frozen=True)
class Row:
    """An overlay row of the layers panel and what turning it on shows."""

    # The row's name: its checkbox's label, its slider's „Krycie: <label>”
    label: str
    # The id of its overlay in describe()
    overlay: str
    # A request its layer sends once on (regular expression searched in the URL)
    sent: str
    # The title of the legend it shows in the map's area while on
    legend: str | None


ROWS = (
    Row(
        "NMT (wysokości)",
        "dem",
        r"/data/dem(_tiles/\d+/\d+/\d+)?\.png",
        "Wysokość terenu [m n.p.m.]",
    ),
    Row(LAKE_ROW, "bdot-lakes", r"/data/bdot_lakes\.geojson$", None),
    Row("Cieki BDOT10k", "bdot-streams", r"/data/bdot_streams\.geojson$", None),
    Row("Grupy glebowe (HSG)", "hsg", r"/data/soil_hsg\.geojson$", "Grupy glebowe HSG"),
    Row(
        "Pokrycie terenu (BDOT10k)",
        "landcover",
        r"/api/tiles/landcover/\d+/\d+/\d+\.pbf$",
        "Pokrycie terenu",
    ),
    Row("Kanalizacja deszczowa", "sewer", r"/api/tiles/sewer/\d+/\d+/\d+\.pbf$", None),
    Row("Zagłębienia", "depressions", r"/data/depressions\.png$", None),
    Row(
        "Linie spływu",
        "streams",
        # The default threshold's pre-generated tiles, else the dynamic endpoint
        r"/(tiles/streams_100000|api/tiles/streams)/\d+/\d+/\d+\.pbf",
        "Linie spływu — zlewnia [km²]",
    ),
    Row(
        RESULT_TITLE,
        f"result:{RESULT_ID}",
        rf"/data/results/{RESULT_ID}/\d+/\d+/\d+\.png$",
        "Głębokość wody [m]",
    ),
    Row(
        "Mapa zagrożenia powodziowego",
        "hazard",
        r"^https://wody\.isok\.gov\.pl/gpservices/KZGW/\w+/MapServer/WMSServer\?",
        "Głębokość wody [m] — MZP, p = 1 %",
    ),
)


def _mercator_y(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _contains(view: Bounds, extent: Bounds) -> bool:
    """Whether the view's bounds hold the extent (both west, south, east, north)."""
    west, south, east, north = view
    e_west, e_south, e_east, e_north = extent
    return west <= e_west and south <= e_south and east >= e_east and north >= e_north


def _share(view: Bounds, extent: Bounds) -> float:
    """The larger share of the view's width or height the extent spans (mercator)."""
    west, south, east, north = view
    e_west, e_south, e_east, e_north = extent
    across = (e_east - e_west) / (east - west)
    up = (_mercator_y(e_north) - _mercator_y(e_south)) / (
        _mercator_y(north) - _mercator_y(south)
    )
    return max(across, up)


def _union(*extents: Bounds) -> Bounds:
    return (
        min(e[0] for e in extents),
        min(e[1] for e in extents),
        max(e[2] for e in extents),
        max(e[3] for e in extents),
    )


def _view_bounds(view: dict[str, Any]) -> Bounds:
    west, south, east, north = (float(v) for v in view["bounds"])
    return west, south, east, north


def _data_extent(site: Site) -> Bounds:
    """The data's extent the map fits: the streams tiles' bounds, else the DEM's."""
    bounds = (site.tiles_meta or {}).get("bounds")
    if bounds and len(bounds) == 4:
        west, south, east, north = (float(v) for v in bounds)
        return west, south, east, north
    return site.bounds


def _geojson_bounds(path: Path) -> Bounds:
    """West, south, east, north of the coordinates of a GeoJSON file in degrees."""
    lngs: list[float] = []
    lats: list[float] = []

    def walk(coordinates: Any) -> None:
        if isinstance(coordinates[0], int | float):
            lngs.append(float(coordinates[0]))
            lats.append(float(coordinates[1]))
            return
        for part in coordinates:
            walk(part)

    for feature in json.loads(path.read_text(encoding="utf-8"))["features"]:
        walk(feature["geometry"]["coordinates"])
    return min(lngs), min(lats), max(lngs), max(lats)


def _wait_overlay(page: Page, overlay_id: str, shown: bool) -> None:
    """Wait until describe() lists the overlay (``shown``) or no longer lists it."""
    page.wait_for_function(
        "([id, shown]) => Hydrograf.map.describe().overlays"
        ".some((drawn) => drawn.id === id) === shown",
        arg=[overlay_id, shown],
    )


def _turn_on(page: Page, label: str, overlay_id: str) -> None:
    """Check a row of the layers panel and wait for its overlay on the map."""
    page.get_by_label(label, exact=True).check()
    _wait_overlay(page, overlay_id, shown=True)


def wait_still(page: Page, element: Locator) -> None:
    """Wait until two screenshots of the element a short poll apart are the same.

    The map is still then: no move, no tile loading or fading in.
    """
    deadline = time.monotonic() + STILL_TIMEOUT_S
    previous = element.screenshot()
    while True:
        page.wait_for_timeout(300)
        current = element.screenshot()
        if current == previous:
            return
        assert time.monotonic() < deadline, "the map did not stop moving"
        previous = current


def _moved(page: Page, before: dict[str, Any]) -> dict[str, Any]:
    """Wait until the view differs from ``before``, then until it stops moving.

    A library may apply a move only at the end of its animation: the view read just
    after a click can still be the old one.
    """
    page.wait_for_function(
        "(before) => { const now = Hydrograf.map.describe();"
        " return now.scale !== before.scale"
        " || now.center.some((value, i) => value !== before.center[i]); }",
        arg={"scale": before["scale"], "center": before["center"]},
    )
    return wait_view(page)


def _zoom_out(page: Page, steps: int) -> dict[str, Any]:
    """Zoom out by the map's own button, one still view after another."""
    view = describe(page)
    for _ in range(steps):
        zoom_out(page)
        view = _moved(page, view)
    return view


def _fit_to_layers(page: Page, before: dict[str, Any]) -> dict[str, Any]:
    """Press the panel's extent button; the view once fitted."""
    page.get_by_role("button", name="Przybliż do zasięgu warstw", exact=True).click()
    return _moved(page, before)


def test_page_opens_on_data_extent(tab: Tab) -> None:
    view = _view_bounds(open_map(tab))
    extent = tab.site.bounds
    assert _contains(view, extent), (view, extent)
    assert _share(view, extent) > FIT_SHARE, (view, extent)


@pytest.mark.parametrize("row", [pytest.param(row, id=row.overlay) for row in ROWS])
def test_overlay_row_turns_layer_on_and_off(tab: Tab, row: Row) -> None:
    page = tab.page
    view = open_map(tab)
    # Every layer is drawn at the first view: the MZP from 1:50 000 on
    assert view["scale"] <= MZP_MAX_SCALE, view["scale"]
    checkbox = page.get_by_label(row.label, exact=True)
    slider = page.get_by_label(f"Krycie: {row.label}", exact=True)
    legend = (
        page.locator("#map").get_by_text(row.legend, exact=True) if row.legend else None
    )
    assert row.overlay not in overlay_ids(page)
    if legend is not None:
        expect(legend).to_be_hidden()

    mark = tab.mark()
    checkbox.check()
    _wait_overlay(page, row.overlay, shown=True)
    tab.settle()
    assert tab.sent_since(mark, row.sent), f"no request matching {row.sent}"
    wait_still(page, page.locator("#map"))
    if legend is not None:
        expect(legend).to_be_visible()

    slider.fill("40")
    expect(slider.locator("xpath=..").get_by_text("40%", exact=True)).to_be_visible()
    drawn = overlay(page, row.overlay)
    assert drawn is not None
    assert drawn["opacity"] == pytest.approx(0.4)

    checkbox.uncheck()
    _wait_overlay(page, row.overlay, shown=False)
    expect(checkbox).not_to_be_checked()
    if legend is not None:
        expect(legend).to_be_hidden()


@pytest.mark.parametrize(
    "row",
    [
        pytest.param(
            row,
            id=row.overlay,
            marks=(
                pytest.mark.xfail(strict=True, reason=LOST_OPACITY_DEFECT)
                if row.overlay in LOST_OPACITY
                else ()
            ),
        )
        for row in ROWS
    ],
)
def test_overlay_row_opacity_holds_as_map_moves(tab: Tab, row: Row) -> None:
    page = tab.page
    view = open_map(tab)
    _turn_on(page, row.label, row.overlay)
    tab.settle()
    wait_still(page, page.locator("#map"))
    page.get_by_label(f"Krycie: {row.label}", exact=True).fill("40")
    drawn = overlay(page, row.overlay)
    assert drawn is not None
    assert drawn["opacity"] == pytest.approx(0.4)

    zoom_in(page)
    _moved(page, view)
    tab.settle()
    wait_still(page, page.locator("#map"))
    drawn = overlay(page, row.overlay)
    assert drawn is not None
    assert drawn["opacity"] == pytest.approx(0.4)


def test_zoom_extent_without_layers_fits_data_extent(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    extent = _data_extent(tab.site)
    away = _zoom_out(page, steps=2)
    assert _share(_view_bounds(away), extent) < FIT_SHARE / 2

    view = _view_bounds(_fit_to_layers(page, away))
    assert _contains(view, extent), (view, extent)
    assert _share(view, extent) > FIT_SHARE, (view, extent)


def test_zoom_extent_with_result_on_fits_result(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    _turn_on(page, RESULT_TITLE, f"result:{RESULT_ID}")
    extent = result_bounds()
    away = _zoom_out(page, steps=2)
    assert _share(_view_bounds(away), extent) < FIT_SHARE / 2

    view = _view_bounds(_fit_to_layers(page, away))
    assert _contains(view, extent), (view, extent)
    assert _share(view, extent) > FIT_SHARE, (view, extent)


def test_zoom_extent_with_two_layers_on_fits_their_union(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    _turn_on(page, RESULT_TITLE, f"result:{RESULT_ID}")
    _turn_on(page, LAKE_ROW, "bdot-lakes")
    result = result_bounds()
    lake = _geojson_bounds(tab.site.data_dir / "bdot_lakes.geojson")
    away = _zoom_out(page, steps=2)

    view = _view_bounds(_fit_to_layers(page, away))
    assert _contains(view, result), (view, result)
    assert _contains(view, lake), (view, lake)
    assert _share(view, _union(result, lake)) > FIT_SHARE, (view, result, lake)
