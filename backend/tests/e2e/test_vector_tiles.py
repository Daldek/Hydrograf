"""Browser tests of the map's tiled vector layers: streams, land cover and sewer.

Nogat's plan 2026-11-24-hydrograf-maplibre, step 1 ("Tests"), read through the
requests the page sends, the layers panel and ``Hydrograf.map.describe()``:

* "the streams' threshold switch asks for the new threshold's tiles":
  ``test_streams_threshold_switch_asks_new_threshold_tiles`` turns the streams on
  (the default threshold's tiles are asked), then picks each other threshold of
  „Próg akumulacji spływu”: each asks for its own tiles (pre-generated
  ``/tiles/streams_<t>/…`` where ``tiles_metadata.json`` lists the threshold, else the
  dynamic ``/api/tiles/streams/…?threshold=<t>``) and for no other threshold's, and
  the map keeps its one overlay ``streams``.
* "a hover over a stream names its catchment, Strahler order and length":
  ``test_streams_hover_names_catchment_order_and_length`` points at the main river
  near its outlet and reads the tooltip by its words: the catchment of the whole grid,
  order 3 and the length of the reach from T1's mouth to the outlet.
* "the first scale of each tiled vector layer: the streams, the threshold 1000 and
  the sewer appear at the scale they do today (…), and below it no tile is asked", and
  the land cover's: ``test_<layer>_first_scale_*`` step the map's own zoom buttons
  from the data extent out to two views past the layer's first scale; at every view
  at that scale or closer the layer's tiles are asked, at every view farther out none.
  Without pre-generated streams' tiles (tippecanoe missing) the streams and the
  threshold 1000 come from the dynamic endpoint at every scale today, which the
  tests assert instead.

The first scales are today's, as ``describe()`` gives a view's scale: constants, never
derived from tile zoom numbers (step 2 asks one level lower for the same scale).
"""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass

from playwright.sync_api import Locator, Page, expect

from tests.e2e.browser import (
    Tab,
    describe,
    open_map,
    overlay_ids,
    screen_point,
    wait_view,
    zoom_out,
)
from tests.e2e.site import MAIN_RIVER_COL, THRESHOLDS_M2, Site
from tests.fixtures.pipeline_run import NETWORK_CELL_M, NETWORK_RIVERS, NETWORK_SHAPE

# Today's first scales (1:N as describe() gives a view's scale) of the tiled vector
# layers. The streams with pre-generated tiles, any threshold but 1000 m²: 1:2 183 915
STREAMS_FIRST_SCALE = 2_183_915.09
# The streams of the threshold 1000 m² with pre-generated tiles: 1:34 124
THRESHOLD_1000_FIRST_SCALE = 34_123.67
# The land cover: 1:2 183 915
LANDCOVER_FIRST_SCALE = 2_183_915.09
# The sewer: 1:545 979
SEWER_FIRST_SCALE = 545_978.77
# Relative tolerance of a view's scale against a first scale
SCALE_TOLERANCE = 1e-6
# How many views farther out than a layer's first scale a walk checks
VIEWS_PAST = 2

STREAMS = "Linie spływu"
LANDCOVER = "Pokrycie terenu (BDOT10k)"
SEWER = "Kanalizacja deszczowa"
THRESHOLD = "Próg akumulacji spływu"
# The thresholds [m²] of the site as the panel names them; 100 000 is the default
THRESHOLD_LABELS = {1_000: "0,1 ha", 10_000: "1 ha", 100_000: "10 ha"}
DEFAULT_THRESHOLD = 100_000
# A base map of image tiles, drawn at every scale (_raster_base_map)
RASTER_BASE_MAP = "OSM GUGiK szary (tylko Polska)"

ANY_STREAMS_TILES = r"/tiles/streams_\d+/|/api/tiles/streams/"
LANDCOVER_TILES = r"/api/tiles/landcover/\d+/\d+/\d+\.pbf"
SEWER_TILES = r"/api/tiles/sewer/\d+/\d+/\d+\.pbf"
# A stream's tooltip: catchment [km²], Strahler order, length [km]
STREAM_TOOLTIP = re.compile(
    r"Zlewnia:\s*([\d.,]+)\s*km²\s*Rząd Strahlera:\s*(\d+)\s*Długość:\s*([\d.,]+)\s*km"
)
# The synthetic grid drains whole to the main river's outlet on its south edge
GRID_AREA_KM2 = NETWORK_SHAPE[0] * NETWORK_SHAPE[1] * NETWORK_CELL_M**2 / 1e6
# The main river's last reach, from T1's mouth to the outlet ((column, row) of cells):
# below T1's mouth it is of order 3, as T1 (with T1a) and the main river (with T2
# and T3) are of order 2 each above it
T1_MOUTH = NETWORK_RIVERS["T1"][1][0]
OUTLET = NETWORK_RIVERS["main"][1][0]
LAST_REACH_KM = (OUTLET[1] - T1_MOUTH[1]) * NETWORK_CELL_M / 1000
LAST_REACH_ORDER = 3
# A row of the last reach, near the outlet
HOVER_ROW = 200
# Tolerance [km², km] of the tooltip's values, given to 0.01
VALUE_TOLERANCE = 0.05


@dataclass(frozen=True)
class View:
    """A view of the map and how many tiles of a layer were asked on the way to it."""

    scale: float
    tiles: int


def _streams_tiles(site: Site, threshold: int) -> str:
    """The URL pattern of the streams' tiles of a threshold."""
    meta = site.tiles_meta
    if meta is not None and threshold in meta["thresholds"]:
        return rf"/tiles/streams_{threshold}/\d+/\d+/\d+\.pbf$"
    return rf"/api/tiles/streams/\d+/\d+/\d+\.pbf\?(.*&)?threshold={threshold}(&|$)"


def _show(page: Page, label: str) -> None:
    """Turn on the overlay row ``label`` of the layers panel."""
    page.get_by_label(label, exact=True).check()


def _wait_overlay(page: Page, overlay_id: str) -> None:
    """Wait until describe() lists the overlay ``overlay_id``."""
    page.wait_for_function(
        "(id) => Hydrograf.map.describe().overlays.some((drawn) => drawn.id === id)",
        arg=overlay_id,
    )


def _choose(select: Locator, label: str) -> None:
    """Pick the option of a ``<select>`` shown as ``label`` (any white space)."""
    texts = [
        " ".join(text.split()) for text in select.locator("option").all_inner_texts()
    ]
    assert label in texts, (label, texts)
    select.select_option(index=texts.index(label))


def _raster_base_map(tab: Tab) -> None:
    """Draw the base map of image tiles, which today's map shows at every scale.

    With the default vector base map today's map zooms out no farther than the
    first scale of the tile layers it shows: a view past a layer's first scale
    needs a base map of image tiles, which has none.
    """
    tab.page.get_by_label(RASTER_BASE_MAP, exact=True).check()
    tab.settle()


def _view(tab: Tab, mark: int, tiles: str) -> View:
    """The view the map shows once still and the layer's tiles asked since ``mark``."""
    scale = wait_view(tab.page)["scale"]
    tab.settle()
    return View(scale, len(tab.sent_since(mark, tiles)))


def _zoom_step(tab: Tab, zoom: Callable[[Page], None], tiles: str) -> View:
    """One step of the map's zoom buttons; the layer's tiles asked on the way."""
    page = tab.page
    before = describe(page)["scale"]
    mark = tab.mark()
    zoom(page)
    page.wait_for_function(
        "(before) => Hydrograf.map.describe().scale !== before", arg=before
    )
    return _view(tab, mark, tiles)


def _shown_at(scale: float, first_scale: float) -> bool:
    """Whether a view's scale is a layer's first scale or closer."""
    return scale <= first_scale * (1 + SCALE_TOLERANCE)


def _walk_out(tab: Tab, start: View, tiles: str, first_scale: float) -> list[View]:
    """From ``start`` out a step at a time to ``VIEWS_PAST`` views past first_scale."""
    views = [start]
    while sum(not _shown_at(view.scale, first_scale) for view in views) < VIEWS_PAST:
        views.append(_zoom_step(tab, zoom_out, tiles))
    return views


def _assert_first_scale(views: list[View], first_scale: float | None) -> None:
    """Tiles asked at every view at the first scale or closer, none farther out.

    ``first_scale`` None: tiles asked at every view.
    """
    asked = [(round(view.scale), view.tiles > 0) for view in views]
    expected = [
        (round(view.scale), first_scale is None or _shown_at(view.scale, first_scale))
        for view in views
    ]
    assert asked == expected, views
    assert any(shown for _, shown in expected), views


def test_streams_threshold_switch_asks_new_threshold_tiles(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    with page.expect_request(re.compile(_streams_tiles(tab.site, DEFAULT_THRESHOLD))):
        _show(page, STREAMS)
    _wait_overlay(page, "streams")
    tab.settle()
    select = page.get_by_label(THRESHOLD, exact=True)
    for threshold in sorted(set(THRESHOLDS_M2) - {DEFAULT_THRESHOLD}, reverse=True):
        tiles = _streams_tiles(tab.site, threshold)
        mark = tab.mark()
        with page.expect_request(re.compile(tiles)):
            _choose(select, THRESHOLD_LABELS[threshold])
        tab.settle()
        asked = [sent.url for sent in tab.sent_since(mark, ANY_STREAMS_TILES)]
        assert [url for url in asked if not re.search(tiles, url)] == [], threshold
        assert overlay_ids(page) == ["streams"]


def test_streams_hover_names_catchment_order_and_length(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    _show(page, STREAMS)
    _wait_overlay(page, "streams")
    tab.settle()
    page.mouse.move(
        *screen_point(page, *tab.site.cell_lnglat(HOVER_ROW, MAIN_RIVER_COL))
    )
    tooltip = page.get_by_text(STREAM_TOOLTIP)
    expect(tooltip).to_be_visible()
    found = STREAM_TOOLTIP.search(tooltip.inner_text())
    assert found is not None
    area_km2 = float(found[1].replace(",", "."))
    length_km = float(found[3].replace(",", "."))
    assert math.isclose(area_km2, GRID_AREA_KM2, abs_tol=VALUE_TOLERANCE), area_km2
    assert int(found[2]) == LAST_REACH_ORDER
    assert math.isclose(length_km, LAST_REACH_KM, abs_tol=VALUE_TOLERANCE), length_km


def test_streams_first_scale_today_none_asked_farther_out(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    _raster_base_map(tab)
    tiles = _streams_tiles(tab.site, DEFAULT_THRESHOLD)
    mark = tab.mark()
    _show(page, STREAMS)
    _wait_overlay(page, "streams")
    views = _walk_out(tab, _view(tab, mark, tiles), tiles, STREAMS_FIRST_SCALE)
    # Without pre-generated tiles the dynamic endpoint draws them at every scale
    _assert_first_scale(views, STREAMS_FIRST_SCALE if tab.site.tiles_meta else None)


def test_streams_threshold_1000_first_scale_today_none_asked_farther_out(
    tab: Tab,
) -> None:
    page = tab.page
    open_map(tab)
    _raster_base_map(tab)
    tiles = _streams_tiles(tab.site, 1_000)
    mark = tab.mark()
    _show(page, STREAMS)
    _wait_overlay(page, "streams")
    _choose(page.get_by_label(THRESHOLD, exact=True), THRESHOLD_LABELS[1_000])
    views = _walk_out(tab, _view(tab, mark, tiles), tiles, THRESHOLD_1000_FIRST_SCALE)
    # Without pre-generated tiles the dynamic endpoint draws them at every scale
    _assert_first_scale(
        views, THRESHOLD_1000_FIRST_SCALE if tab.site.tiles_meta else None
    )


def test_landcover_first_scale_today_none_asked_farther_out(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    _raster_base_map(tab)
    mark = tab.mark()
    _show(page, LANDCOVER)
    _wait_overlay(page, "landcover")
    start = _view(tab, mark, LANDCOVER_TILES)
    views = _walk_out(tab, start, LANDCOVER_TILES, LANDCOVER_FIRST_SCALE)
    _assert_first_scale(views, LANDCOVER_FIRST_SCALE)


def test_sewer_first_scale_today_none_asked_farther_out(tab: Tab) -> None:
    page = tab.page
    open_map(tab)
    _raster_base_map(tab)
    mark = tab.mark()
    _show(page, SEWER)
    _wait_overlay(page, "sewer")
    start = _view(tab, mark, SEWER_TILES)
    views = _walk_out(tab, start, SEWER_TILES, SEWER_FIRST_SCALE)
    _assert_first_scale(views, SEWER_FIRST_SCALE)
