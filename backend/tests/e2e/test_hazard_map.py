"""Browser tests of the flood hazard map (MZP) and of the order of the overlays.

Nogat's plan 2026-11-24-hydrograf-maplibre, step 1 ("Tests"), read through the
requests the page sends, the layers panel, the map's legend and
``Hydrograf.map.describe()``:

* "MZP: no request to wody.isok.gov.pl below 1:50 000, the hint and the legend":
  ``test_hazard_map_on_farther_than_1_50000_asks_nothing_and_hints`` turns the layer
  on farther out than 1:50 000 and zooms out a step more: no request goes to
  wody.isok.gov.pl, and the hint „Przybliż mapę — … 1:50 000.” shows in the layer's
  row and in its legend, „Głębokość wody [m] — MZP, p = 1 %” with its four depth
  classes. ``test_hazard_map_zoomed_out_past_1_50000_asks_nothing`` turns it on at
  the data extent and zooms out past 1:50 000: today the first view farther out is
  asked for, a defect, marked as such (see its docstring).
* "at and above it requests with a 512 px box in EPSG:3857":
  ``test_hazard_map_from_1_50000_asks_512px_boxes_in_epsg3857`` reads the GetMap
  requests at the data extent and one step closer (keys in any case): WMS 1.3.0,
  CRS EPSG:3857, 512 × 512 px, the scenario's layer, square boxes whose side over
  512 px is the view's metres per pixel (its scale × 0.28 mm) and which cover the
  view in EPSG:3857; the hint is hidden.
* "a probability switch asks for its service":
  ``test_hazard_map_probability_switch_asks_its_service``: the default 1 % asks its
  service, then each other probability of „Prawdopodobieństwo powodzi” asks its own
  service with its layer and no other, and the legend's title names it.
* "the order: where the DEM, MZP, land cover, a result and the streams overlap,
  describe() lists them in M4's order":
  ``test_overlapping_overlays_described_in_m4_order`` turns the five on at the data
  extent in a scrambled order.
"""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.browser import (
    Tab,
    describe,
    open_map,
    overlay_ids,
    wait_view,
    zoom_in,
    zoom_out,
)
from tests.e2e.site import RESULT_ID, RESULT_TITLE

HAZARD = "Mapa zagrożenia powodziowego"
PROBABILITY = "Prawdopodobieństwo powodzi"
DEM = "NMT (wysokości)"
LANDCOVER = "Pokrycie terenu (BDOT10k)"
STREAMS = "Linie spływu"
# The services draw the depths at 1:50 000 and closer (the hint's scale)
MZP_FIRST_SCALE = 50_000
MZP_REQUESTS = r"^https://wody\.isok\.gov\.pl/"
MZP_SERVICE = "https://wody.isok.gov.pl/gpservices/KZGW/{}/MapServer/WMSServer"
MZP_HINT = re.compile(r"^Przybliż mapę — .*1:50\s000\.$")
DEPTH_CLASSES = ("≤ 0,5", "0,5–2,0", "2,0–4,0", "> 4,0")
# OGC's standard rendering pixel [m]: a scale times it is a view's metres per pixel
STANDARD_PIXEL_M = 0.00028
TILE_PX = 512
EARTH_RADIUS_M = 6_378_137.0
RELATIVE_TOLERANCE = 1e-6
# M4's order of the overlays, from the bottom up
M4_ORDER = ["dem", "hazard", "landcover", f"result:{RESULT_ID}", "streams"]


@dataclass(frozen=True)
class Scenario:
    """A probability of „Prawdopodobieństwo powodzi”: its option, service, layer."""

    option: str
    p: str
    service: str
    layers: str

    @property
    def legend_title(self) -> str:
        return f"Głębokość wody [m] — MZP, p = {self.p} %"


LOW = Scenario(
    "0,2 % — raz na 500 lat", "0,2", "MZP20_Glebokosc_NiskiePrawdopodPowodzi", "16"
)
MEDIUM = Scenario(
    "1 % — raz na 100 lat", "1", "MZP20_Glebokosc_SredniePrawdopodPowodzi", "16"
)
HIGH = Scenario(
    "10 % — raz na 10 lat", "10", "MZP20_Glebokosc_WysokiePrawdopodPowodzi", "1"
)


def _show(page: Page, label: str) -> None:
    """Turn on the overlay row ``label`` of the layers panel."""
    page.get_by_label(label, exact=True).check()


def _choose(select: Locator, label: str) -> None:
    """Pick the option of a ``<select>`` shown as ``label`` (any white space)."""
    texts = [
        " ".join(text.split()) for text in select.locator("option").all_inner_texts()
    ]
    assert label in texts, (label, texts)
    select.select_option(index=texts.index(label))


def _map_legend(page: Page) -> Locator:
    """The map, which holds its legends."""
    return page.locator("#map")


def _row_hint(page: Page) -> Locator:
    """The hint below the hazard map's row in the layers panel."""
    return page.locator("#layers-list").get_by_text(MZP_HINT)


def _mzp_asked(tab: Tab, mark: int) -> list[str]:
    """The requests to wody.isok.gov.pl since ``mark``."""
    return [sent.url for sent in tab.sent_since(mark, MZP_REQUESTS)]


def _step(tab: Tab, zoom: Callable[[Page], None]) -> tuple[dict[str, Any], list[str]]:
    """One step of the map's zoom buttons: the new view, the MZP requests on the way."""
    page = tab.page
    before = describe(page)["scale"]
    mark = tab.mark()
    zoom(page)
    page.wait_for_function(
        "(before) => Hydrograf.map.describe().scale !== before", arg=before
    )
    view = wait_view(page)
    tab.settle()
    return view, _mzp_asked(tab, mark)


def _zoom_to(
    tab: Tab, zoom: Callable[[Page], None], reached: Callable[[float], bool]
) -> dict[str, Any]:
    """Step the zoom buttons until the view's scale is ``reached``; that view."""
    view = describe(tab.page)
    while not reached(view["scale"]):
        view, _ = _step(tab, zoom)
    return view


def _closer_than_mzp(scale: float) -> bool:
    return scale <= MZP_FIRST_SCALE


def _farther_than_mzp(scale: float) -> bool:
    return scale > MZP_FIRST_SCALE


def _mercator(lng: float, lat: float) -> tuple[float, float]:
    """EPSG:3857 metres of a place in degrees."""
    return (
        EARTH_RADIUS_M * math.radians(lng),
        EARTH_RADIUS_M * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)),
    )


def _same(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=RELATIVE_TOLERANCE)


def _assert_get_maps(urls: list[str], scenario: Scenario, view: dict[str, Any]) -> None:
    """GetMap of the scenario's service: 512 px boxes of EPSG:3857 over the view.

    Every box is a square whose side over 512 px is the view's metres per pixel and
    which reaches into the view (within a pixel); together they cover it.
    """
    assert urls, "no request to the hazard map's service"
    metres_per_px = view["scale"] * STANDARD_PIXEL_M
    view_west, view_south = _mercator(*view["bounds"][:2])
    view_east, view_north = _mercator(*view["bounds"][2:])
    boxes = []
    for url in urls:
        parts = urlsplit(url)
        params = {
            k.lower(): v for k, v in parse_qsl(parts.query, keep_blank_values=True)
        }
        assert url.split("?")[0] == MZP_SERVICE.format(scenario.service), url
        assert params["service"].upper() == "WMS", url
        assert params["request"].lower() == "getmap", url
        assert params["version"] == "1.3.0", url
        assert params["crs"].upper() == "EPSG:3857", url
        assert (params["width"], params["height"]) == ("512", "512"), url
        assert params["layers"] == scenario.layers, url
        west, south, east, north = (float(v) for v in params["bbox"].split(","))
        assert _same(east - west, north - south), url
        assert _same((east - west) / TILE_PX, metres_per_px), (url, metres_per_px)
        assert west < view_east + metres_per_px, url
        assert east > view_west - metres_per_px, url
        assert south < view_north + metres_per_px, url
        assert north > view_south - metres_per_px, url
        boxes.append((west, south, east, north))
    assert min(box[0] for box in boxes) <= view_west + metres_per_px, boxes
    assert min(box[1] for box in boxes) <= view_south + metres_per_px, boxes
    assert max(box[2] for box in boxes) >= view_east - metres_per_px, boxes
    assert max(box[3] for box in boxes) >= view_north - metres_per_px, boxes


def _assert_hint_and_legend(page: Page, scenario: Scenario) -> None:
    """The hint in the row and in the legend, which names the depth classes."""
    expect(_row_hint(page)).to_be_visible()
    legend = _map_legend(page)
    expect(legend.get_by_text(scenario.legend_title, exact=True)).to_be_visible()
    for depth in DEPTH_CLASSES:
        expect(legend.get_by_text(depth, exact=True)).to_be_visible()
    expect(legend.get_by_text(MZP_HINT)).to_be_visible()


def test_hazard_map_on_farther_than_1_50000_asks_nothing_and_hints(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    _zoom_to(tab, zoom_out, _farther_than_mzp)
    mark = tab.mark()
    _show(page, HAZARD)
    tab.settle()
    _assert_hint_and_legend(page, MEDIUM)
    view, _ = _step(tab, zoom_out)
    assert _farther_than_mzp(view["scale"])
    _assert_hint_and_legend(page, MEDIUM)
    assert _mzp_asked(tab, mark) == []


@pytest.mark.xfail(
    raises=AssertionError,
    strict=True,
    reason=(
        "defect: with the hazard map on, a zoom-out click past 1:50 000 asks the "
        "service for the new view (Leaflet's WMS layer loads the target level on "
        "zoomanim before layers.js sync() removes it on zoomend)"
    ),
)
def test_hazard_map_zoomed_out_past_1_50000_asks_nothing(tab: Tab) -> None:
    """Zoomed out from the data extent, the view past 1:50 000 asks nothing.

    Today the first view farther out is asked for: at 1:68 247 two GetMap
    requests whose box side over 512 px is that view's metres per pixel.
    """
    page = tab.page
    open_map(tab)
    _zoom_to(tab, zoom_in, _closer_than_mzp)
    _show(page, HAZARD)
    tab.settle()
    view, asked = _step(tab, zoom_out)
    while not _farther_than_mzp(view["scale"]):
        view, asked = _step(tab, zoom_out)
    assert asked == [], (view["scale"], asked)


def test_hazard_map_from_1_50000_asks_512px_boxes_in_epsg3857(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    view = _zoom_to(tab, zoom_in, _closer_than_mzp)
    mark = tab.mark()
    with page.expect_request(re.compile(MZP_REQUESTS)):
        _show(page, HAZARD)
    tab.settle()
    _assert_get_maps(_mzp_asked(tab, mark), MEDIUM, view)
    legend = _map_legend(page)
    expect(legend.get_by_text(MEDIUM.legend_title, exact=True)).to_be_visible()
    expect(_row_hint(page)).to_be_hidden()
    expect(legend.get_by_text(MZP_HINT)).to_be_hidden()
    view, asked = _step(tab, zoom_in)
    _assert_get_maps(asked, MEDIUM, view)


def test_hazard_map_probability_switch_asks_its_service(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    view = _zoom_to(tab, zoom_in, _closer_than_mzp)
    mark = tab.mark()
    with page.expect_request(re.compile(re.escape(MZP_SERVICE.format(MEDIUM.service)))):
        _show(page, HAZARD)
    tab.settle()
    _assert_get_maps(_mzp_asked(tab, mark), MEDIUM, view)
    select = page.get_by_label(PROBABILITY, exact=True)
    for scenario in (LOW, HIGH):
        mark = tab.mark()
        service = re.compile(re.escape(MZP_SERVICE.format(scenario.service)))
        with page.expect_request(service):
            _choose(select, scenario.option)
        tab.settle()
        _assert_get_maps(_mzp_asked(tab, mark), scenario, view)
        expect(
            _map_legend(page).get_by_text(scenario.legend_title, exact=True)
        ).to_be_visible()


def test_overlapping_overlays_described_in_m4_order(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    _zoom_to(tab, zoom_in, _closer_than_mzp)
    for label in (STREAMS, RESULT_TITLE, LANDCOVER, HAZARD, DEM):
        _show(page, label)
    page.wait_for_function(
        "(ids) => { const shown = Hydrograf.map.describe().overlays.map((o) => o.id);"
        " return ids.every((id) => shown.includes(id)); }",
        arg=M4_ORDER,
    )
    tab.settle()
    assert overlay_ids(page) == M4_ORDER
