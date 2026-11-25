"""Browser tests of the charts (js/charts.js on the chart module of Nogat's kit).

Nogat's plan 2026-11-24-unified-charts, step 5 (ADR-090): every chart of Hydrograf is
the kit's SVG chart (``nogat/nogat-chart.js``). A delineated watershed (CLICK_CELL of
``test_watershed``) draws the hypsometric curve and one bar per class of its land cover
and soil groups; an own rainfall series of twelve 5-minute steps (``RAIN_MM``, a CSV
given to „Importuj CSV” of „Własna seria”) draws the hietogram and the hydrograph of
POST /api/generate-hydrograph; a line of ``test_profile`` draws the terrain profile.

The tests read what a person sees: the axes' tick labels (a time axis in minutes or
hours, by its label), the bar under a zoomable chart (a lone „Przybliż” before a zoom;
„Oddal”, „Przybliż”, „Cały zakres” and the range shown after it), the readout's box,
the chart's live region, the profile's marker on the map (``profile-marker`` of
``Hydrograf.map.describe()``) and the files „PNG” saves. Numbers are written as the
kit writes Polish ones: a decimal comma, times as h:mm. On a phone (390 px) fingers are
DevTools' ``Input.dispatchTouchEvent``, so the browser's own ``touch-action`` decides
what scrolls.
"""

import io
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import pytest
from PIL import Image, ImageChops, ImageStat
from playwright.sync_api import CDPSession, FilePayload, Locator, Page, expect

from tests.e2e.browser import (
    Tab,
    distance,
    open_map,
    pixels,
    screen_point,
    token_colors,
    wait_view,
)
from tests.e2e.test_profile import (
    LINE,
    PHONE_LINE,
    along_line,
    click_place,
    finish_line,
    places,
    profile_drawer,
    readout_place,
    tap_place,
)
from tests.e2e.test_watershed import CLICK_CELL, DELINEATION, js_fixed, wait_for_overlay

HYDROGRAPH = re.compile(r"/api/generate-hydrograph$")
# The own rainfall series [mm per 5 min]: a storm of an hour peaking in its fifth step
RAIN_MM = (1, 2, 4, 8, 12, 8, 4, 2, 1, 0.5, 0.5, 0.5)
RAIN_CSV = ("\n".join(str(depth) for depth in RAIN_MM) + "\n").encode()
# The charts' names (their role img)
HYDROGRAPH_CHART = "Hydrogram odpływu"
HIETOGRAM_CHART = "Hietogram opadu"
PROFILE_CHART = "Profil terenu"
HYPSOMETRIC_CHART = "Krzywa hipsometryczna"
LAND_COVER_CHART = "Udział form pokrycia terenu"
HSG_CHART = "Udział hydrologicznych grup glebowych"
# The names the charts give the land cover classes and soil groups of the site
CLASS_NAMES = {"grunt_orny": "Grunty orne", "las": "Lasy", "woda": "Wody"}
GROUP_NAMES = {"A": "A: przepuszczalne", "B": "B: średnio przepuszczalne"}
# A gesture's points lie this far above the plot's x axis [px]
ABOVE_AXIS_PX = 30
# A range read from the bar is written in whole minutes (h:mm)
MINUTE = 1.0
# The PNG: twice the chart's drawn size, the lines under it in rows of 11 px × 1.4
# between margins of 8 px (the kit's FOOTER)
PNG_SCALE = 2
FOOTER_MARGINS_PX = 16
FOOTER_ROW_PX = 15
# A colour of a bar is its class's colour on the map (antialiasing aside)
SAME_COLOR = 12.0
# The PNG's chart, scaled to the page's size, differs from the chart drawn by its
# antialiasing only [mean of 0-255 grey levels]; another range differs by its curve
SAME_PICTURE = 6.0
SWIPE_STEPS = 8


@dataclass(frozen=True)
class Axes:
    """The axes of a drawn chart, in the page's pixels.

    ``left``, ``right`` and ``bottom`` are the ends of the x axis line; ``x_ticks`` the
    labelled ticks under it, (page x, value), the value in the axis's unit (minutes of a
    time axis whose label says „[h]”: hours times 60); ``y_ticks`` the values of the
    labels left of the plot.
    """

    left: float
    right: float
    bottom: float
    x_ticks: list[tuple[float, float]]
    y_ticks: list[float]

    def at(self, share: float) -> tuple[float, float]:
        """A point of the plot at a share of its width, above the x axis."""
        return self.left + share * (self.right - self.left), self.bottom - ABOVE_AXIS_PX

    def value(self, x: float) -> float:
        """The value of x under a page x, by the first and the last tick."""
        (x0, v0), (x1, v1) = self.x_ticks[0], self.x_ticks[-1]
        return v0 + (x - x0) * (v1 - v0) / (x1 - x0)

    def page_x(self, value: float) -> float:
        """The page x of a value of x."""
        (x0, v0), (x1, v1) = self.x_ticks[0], self.x_ticks[-1]
        return x0 + (value - v0) * (x1 - x0) / (v1 - v0)


def number(text: str) -> float:
    """A number as the kit writes it in Polish: a decimal comma, the minus U+2212."""
    plain = text.replace("\u2212", "-").replace("\u00a0", "").replace(" ", "")
    return float(plain.replace(",", "."))


def pl(value: float, digits: int) -> str:
    """A number as the kit writes it in Polish (below 10 000: no grouping)."""
    return js_fixed(value, digits).replace(".", ",")


def clock(minutes: float) -> str:
    """Minutes as a time axis writes them: h:mm."""
    total = round(minutes)
    return f"{total // 60}:{total % 60:02d}"


def chart(page: Page, name: str) -> Locator:
    """The SVG of a chart (role img, its name)."""
    return page.get_by_role("img", name=name, exact=True)


def holder(svg: Locator) -> Locator:
    """The chart's container: the SVG, the bar under it, the legend, the live region."""
    return svg.locator("xpath=..")


def axes(svg: Locator) -> Axes:
    """The axes of a drawn chart (see ``Axes``)."""
    drawn: dict[str, Any] = svg.evaluate(
        """(svg) => {
            const m = svg.getScreenCTM();
            const at = (x, y) => new DOMPoint(x, y).matrixTransform(m);
            const axis = [...svg.querySelectorAll('line.axis')]
                .find((l) => l.getAttribute('y1') === l.getAttribute('y2'));
            const y = Number(axis.getAttribute('y1'));
            const ends = [at(Number(axis.getAttribute('x1')), y),
                          at(Number(axis.getAttribute('x2')), y)];
            const ticks = [...svg.querySelectorAll('text.tick')];
            const label = [...svg.querySelectorAll('text.axis-label')]
                .find((t) => Number(t.getAttribute('y')) > y);
            return {
                left: ends[0].x, right: ends[1].x, bottom: ends[0].y,
                x: ticks.filter((t) => t.getAttribute('text-anchor') === 'middle')
                    .map((t) => [at(Number(t.getAttribute('x')), y).x, t.textContent]),
                y: ticks.filter((t) => t.getAttribute('text-anchor') === 'end')
                    .map((t) => t.textContent),
                label: label ? label.textContent : '',
            };
        }"""
    )
    per = 60 if "[h]" in drawn["label"] else 1
    return Axes(
        left=drawn["left"],
        right=drawn["right"],
        bottom=drawn["bottom"],
        x_ticks=[(x, number(text) * per) for x, text in drawn["x"]],
        y_ticks=[number(text) for text in drawn["y"]],
    )


def shown_range(svg: Locator) -> str:
    """The range the bar under the chart says, '' before a zoom."""
    text = holder(svg).locator(".nogat-chart-zoom-range").text_content() or ""
    return text.strip()


def time_range(svg: Locator) -> tuple[float, float]:
    """The range of a time axis the bar says, in minutes („0:18 – 4:18”)."""
    found = re.fullmatch(r"(\d+):(\d\d) – (\d+):(\d\d)", shown_range(svg))
    assert found, shown_range(svg)
    h0, m0, h1, m1 = (int(part) for part in found.groups())
    return 60 * h0 + m0, 60 * h1 + m1


def value_range(svg: Locator) -> tuple[float, float]:
    """The range of a value axis the bar says („0,79 – 1,59”)."""
    first, _, last = shown_range(svg).partition(" – ")
    return number(first), number(last)


def readout(svg: Locator) -> list[str]:
    """The lines of the readout's box, the heading first; [] while it is hidden."""
    lines: list[str] = svg.evaluate(
        "(svg) => [...svg.querySelectorAll('.readout text')].map((t) => t.textContent)"
    )
    return lines


def zoom_button(svg: Locator, name: str) -> Locator:
    """A button of the bar under the chart: „Oddal”, „Przybliż” or „Cały zakres”."""
    return holder(svg).get_by_role("button", name=name, exact=True)


def expect_zoomed(svg: Locator, zoomed: bool) -> None:
    """The bar: „Oddal”, „Przybliż”, „Cały zakres” (zoomed), else a lone „Przybliż”."""
    expect(zoom_button(svg, "Przybliż")).to_be_visible()
    for name in ("Oddal", "Cały zakres"):
        if zoomed:
            expect(zoom_button(svg, name)).to_be_visible()
        else:
            expect(zoom_button(svg, name)).to_be_hidden()


def drag(
    page: Page,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    button: Literal["left", "middle"] = "left",
    shift: bool = False,
) -> None:
    if shift:
        page.keyboard.down("Shift")
    page.mouse.move(*start)
    page.mouse.down(button=button)
    page.mouse.move(*end, steps=6)
    page.mouse.up(button=button)
    if shift:
        page.keyboard.up("Shift")


def park_mouse(page: Page) -> None:
    """The pointer off every chart (the top bar): no readout shows or anchors a zoom."""
    page.mouse.move(1, 1)


def in_view(svg: Locator) -> Locator:
    """The chart scrolled into the panel's view, the pointer parked off it first."""
    park_mouse(svg.page)
    svg.scroll_into_view_if_needed()
    return svg


def open_section(page: Page, section_id: str) -> None:
    """Open a section of the panel „Zlewnia” by its heading, unless it is open."""
    section = page.locator(f"#{section_id}")
    if not section.evaluate("(details) => details.open"):
        section.locator(":scope > summary").click()


def delineate_watershed(tab: Tab) -> dict[str, Any]:
    """Delineate CLICK_CELL's watershed by a click (a tap on a phone); the answer."""
    page = tab.page
    open_map(tab)
    page.get_by_role("radio", name="Wybierz zlewnię", exact=True).click()
    page.get_by_role("radio", name="Jedna zlewnia", exact=True).click()
    wait_view(page)
    x, y = screen_point(page, *tab.site.cell_lnglat(*CLICK_CELL))
    with page.expect_response(DELINEATION) as answered:
        if is_phone(page):
            page.touchscreen.tap(x, y)
        else:
            page.mouse.click(x, y)
    response = answered.value
    assert response.ok, f"delineation failed: {response.status} {response.text()}"
    wait_for_overlay(page, "watershed")
    # The PMAXTP hydrograph the page asks for next (the site has no PMAXTP data)
    tab.settle()
    answer: dict[str, Any] = response.json()
    return answer


def rain_hydrograph(tab: Tab) -> dict[str, Any]:
    """The hydrograph of RAIN_MM of the delineated watershed, its charts drawn."""
    page = tab.page
    open_section(page, "acc-hietogram")
    page.get_by_role("radio", name="Własna seria", exact=True).click()
    csv: FilePayload = {"name": "opad.csv", "mimeType": "text/csv", "buffer": RAIN_CSV}
    with page.expect_response(HYDROGRAPH) as answered:
        page.set_input_files("#custom-rain-file", files=csv)
    response = answered.value
    assert response.ok, f"hydrograph failed: {response.status} {response.text()}"
    open_section(page, "acc-hydrograph")
    expect(chart(page, HYDROGRAPH_CHART)).to_be_visible()
    answer: dict[str, Any] = response.json()
    return answer


def is_phone(page: Page) -> bool:
    size = page.viewport_size
    return size is not None and size["width"] < 860


def touch(cdp: CDPSession, kind: str, points: list[tuple[float, float]]) -> None:
    """A touch event of DevTools: touchStart, touchMove or touchEnd at page points."""
    touches = [{"x": x, "y": y, "id": n} for n, (x, y) in enumerate(points)]
    cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": touches})


def bar_boxes(svg: Locator) -> list[dict[str, Any]]:
    """The visible parts of the bar under the chart: tag, middle, width and height."""
    boxes: list[dict[str, Any]] = holder(svg).evaluate(
        """(host) => [...host.querySelectorAll('.nogat-chart-zoom > *')]
            .filter((part) => !part.hidden)
            .map((part) => { const r = part.getBoundingClientRect();
              return { tag: part.tagName, middle: r.top + r.height / 2,
                       width: r.width, height: r.height }; })"""
    )
    return boxes


# --- desktop: mouse, wheel and keys ---------------------------------------------------


def test_hydrograph_drag_selects_a_time_range_y_fits_double_click_shows_whole(
    tab: Tab,
) -> None:
    page = tab.page
    delineate_watershed(tab)
    rain_hydrograph(tab)
    svg = in_view(chart(page, HYDROGRAPH_CHART))
    whole = axes(svg)
    expect_zoomed(svg, False)
    span = whole.value(whole.right) - whole.value(whole.left)

    # The tail of the flood, from 60 % to 95 % of the plot
    drag(page, whole.at(0.6), whole.at(0.95))

    expect_zoomed(svg, True)
    start, end = time_range(svg)
    assert start == pytest.approx(whole.value(whole.at(0.6)[0]), abs=MINUTE)
    assert end == pytest.approx(whole.value(whole.at(0.95)[0]), abs=MINUTE)
    assert end - start == pytest.approx(0.35 * span, abs=2 * MINUTE)
    shown = axes(svg)
    assert start <= shown.x_ticks[0][1] and shown.x_ticks[-1][1] <= end, shown
    # The y axis fits the low flows of the tail
    assert max(shown.y_ticks) < max(whole.y_ticks), (shown.y_ticks, whole.y_ticks)

    page.mouse.dblclick(*shown.at(0.5))

    expect_zoomed(svg, False)
    assert axes(svg) == whole


def test_hydrograph_ctrl_wheel_zooms_at_cursor_wheel_alone_scrolls_panel(
    tab: Tab,
) -> None:
    page = tab.page
    delineate_watershed(tab)
    rain_hydrograph(tab)
    svg = in_view(chart(page, HYDROGRAPH_CHART))
    whole = axes(svg)
    span = whole.value(whole.right) - whole.value(whole.left)
    cursor = whole.at(0.3)
    under = whole.value(cursor[0])
    page.mouse.move(*cursor)

    page.keyboard.down("Control")
    page.mouse.wheel(0, -100)
    page.keyboard.up("Control")

    expect_zoomed(svg, True)
    start, end = time_range(svg)
    assert end - start == pytest.approx(span / 1.25, abs=2 * MINUTE)
    # The time under the cursor stays under it
    assert start + 0.3 * (end - start) == pytest.approx(under, abs=MINUTE)

    # The wheel alone scrolls the panel and leaves the chart as it was
    body = page.locator("#results-body")
    before = body.evaluate("(body) => body.scrollTop")
    page.mouse.wheel(0, 300)
    page.wait_for_function(
        "(before) => document.getElementById('results-body').scrollTop !== before",
        arg=before,
    )
    assert time_range(svg) == (start, end)


def test_hydrograph_shift_drag_and_middle_button_pan_within_whole(tab: Tab) -> None:
    page = tab.page
    delineate_watershed(tab)
    rain_hydrograph(tab)
    svg = in_view(chart(page, HYDROGRAPH_CHART))
    zoom_button(svg, "Przybliż").click()
    first, last = time_range(svg)
    size = last - first

    plot = axes(svg)
    drag(page, plot.at(0.6), plot.at(0.4), shift=True)

    moved = time_range(svg)
    assert moved[0] - first == pytest.approx(0.2 * size, abs=MINUTE)
    assert moved[1] - moved[0] == pytest.approx(size, abs=MINUTE)

    plot = axes(svg)
    drag(page, plot.at(0.4), plot.at(0.6), button="middle")

    back = time_range(svg)
    assert back[0] == pytest.approx(first, abs=MINUTE)

    # Held within the whole: dragged far right, the range stops at its start
    for _ in range(3):
        plot = axes(svg)
        drag(page, plot.at(0.05), plot.at(0.95), shift=True)
    held = time_range(svg)
    assert held[0] == 0
    assert held[1] - held[0] == pytest.approx(size, abs=MINUTE)


def test_hietogram_lone_plus_keys_and_reset_say_the_range(tab: Tab) -> None:
    page = tab.page
    delineate_watershed(tab)
    rain_hydrograph(tab)
    svg = in_view(chart(page, HIETOGRAM_CHART))
    live = holder(svg).locator(".nogat-chart-sr")
    expect_zoomed(svg, False)

    zoom_button(svg, "Przybliż").click()

    expect_zoomed(svg, True)
    assert time_range(svg) == (15, 45)  # half of the hour around its middle
    expect(live).to_have_text(shown_range(svg))
    zoom_button(svg, "Oddal").click()
    expect_zoomed(svg, False)
    expect(live).to_have_text("Cały zakres")

    # Keys: End reads the last step, + zooms around the readout, 0 shows the whole
    svg.focus()
    page.keyboard.press("End")
    last = f"{pl(RAIN_MM[-1], 2)}\u00a0mm"
    assert readout(svg)[:2] == ["0:55–1:00", f"Opad całkowity: {last}"]
    page.keyboard.press("+")
    expect_zoomed(svg, True)
    start, end = time_range(svg)
    assert end - start == pytest.approx(30, abs=MINUTE) and start < 55 < end
    expect(live).to_have_text(
        re.compile(rf"^0:55–1:00 · .* · {re.escape(shown_range(svg))}$")
    )
    page.keyboard.press("0")
    expect_zoomed(svg, False)
    expect(live).to_have_text(re.compile(r" · Cały zakres$"))


def test_hydrograph_readout_reads_the_answer_at_pointer_and_by_keys(tab: Tab) -> None:
    page = tab.page
    delineate_watershed(tab)
    hydrograph = rain_hydrograph(tab)["hydrograph"]
    svg = in_view(chart(page, HYDROGRAPH_CHART))
    peak, at = hydrograph["peak_discharge_m3s"], hydrograph["time_to_peak_min"]
    plot = axes(svg)
    expect(svg.locator(".peak-tag, .peak-label")).to_have_text(
        f"Qmax {pl(peak, 2)} m³/s · {clock(at)}"
    )

    page.mouse.move(plot.page_x(at), plot.bottom - ABOVE_AXIS_PX)

    assert readout(svg) == [f"t = {clock(at)}", f"Przepływ Q: {pl(peak, 2)}\u00a0m³/s"]

    svg.focus()
    page.keyboard.press("End")
    times, flows = hydrograph["times_min"], hydrograph["discharge_m3s"]
    value = flows[-1]
    digits = 2 if value >= 1 or value == 0 else 3
    assert readout(svg) == [
        f"t = {clock(times[-1])}",
        f"Przepływ Q: {pl(value, digits)}\u00a0m³/s",
    ]


def test_profile_readout_of_zoomed_range_puts_marker_at_distance_it_reads(
    tab: Tab,
) -> None:
    page = tab.page
    open_map(tab)
    page.get_by_role("radio", name="Profil terenu", exact=True).click()
    a, b, c = places(tab, LINE)
    click_place(page, a)
    click_place(page, b)
    line = finish_line(tab, lambda: page.mouse.dblclick(*screen_point(page, *c)))
    summary = page.locator("#profile-summary").text_content() or ""
    found = re.search(r"Długość ([\d.]+) km", summary)
    assert found, summary
    length_km = float(found.group(1))
    svg = profile_drawer(page).get_by_role("img", name=PROFILE_CHART, exact=True)
    whole = axes(svg)

    # The second half of the line
    drag(page, whole.at(0.5), whole.at(1.0))

    expect_zoomed(svg, True)
    start, end = value_range(svg)
    assert start == pytest.approx(whole.value(whole.at(0.5)[0]), abs=0.01)
    shown = axes(svg)
    page.mouse.move(*shown.at(0.02))
    heading = readout(svg)[0]
    read_km = number(heading.removesuffix(" km"))
    # The sample nearest to the range's start (samples 1 % of the line apart)
    assert start - 0.01 <= read_km <= start + 0.02 * length_km, (heading, start, end)
    marker = readout_place(page)
    along, off = along_line(line, marker)
    line_m, _ = along_line(line, line[-1])
    # The marker stands where the readout reads, as a share of the line's length
    assert along / line_m == pytest.approx(read_km / length_km, abs=0.01), heading
    assert off < 1.0


def test_watershed_charts_bars_in_map_colours_and_curve_reads_elevation(
    tab: Tab,
) -> None:
    page = tab.page
    watershed = delineate_watershed(tab)["watershed"]
    for section in ("acc-relief", "acc-landcover", "acc-hsg"):
        open_section(page, section)
    land_cover = watershed["land_cover_stats"]["categories"]
    soil_groups = watershed["hsg_stats"]["categories"]
    cases = (
        (
            LAND_COVER_CHART,
            "landCoverColor",
            "category",
            CLASS_NAMES,
            sorted(land_cover, key=lambda c: -c["percentage"]),
        ),
        (
            HSG_CHART,
            "hsgColor",
            "group",
            GROUP_NAMES,
            sorted(soil_groups, key=lambda c: c["group"]),
        ),
    )
    for name, palette, key, names, rows in cases:
        svg = in_view(chart(page, name))
        drawn = svg.evaluate(
            """(svg) => ({
                names: [...svg.querySelectorAll('.bar-name')].map((t) => t.textContent),
                shares: [...svg.querySelectorAll('.bar-val')].map((t) => t.textContent),
                bars: [...svg.querySelectorAll('rect.hbar')].map((r) => {
                    const box = r.getBoundingClientRect();
                    return [box.x + box.width / 2, box.y + box.height / 2];
                }),
                tabindex: svg.getAttribute('tabindex'),
            })"""
        )
        assert drawn["names"] == [names[row[key]] for row in rows]
        assert drawn["shares"] == [f"{pl(row['percentage'], 1)} %" for row in rows]
        # One bar per class in its colour on the map; a share chart neither zooms
        # nor reads out
        colors = page.evaluate(
            "([palette, keys]) => keys.map((k) => "
            "Hydrograf.map.rgb(Hydrograf.charts[palette](k)).map(Math.round))",
            [palette, [row[key] for row in rows]],
        )
        for (x, y), color in zip(drawn["bars"], colors, strict=True):
            drawn_color = pixels(page, x, y, radius=0)[0]
            assert distance(drawn_color, tuple(color)) < SAME_COLOR, (
                name,
                drawn_color,
                color,
            )
        assert drawn["tabindex"] is None
        expect(holder(svg).locator(".nogat-chart-zoom")).to_be_hidden()

    # The hypsometric curve reads the elevation at the share of the area pointed at
    svg = in_view(chart(page, HYPSOMETRIC_CHART))
    expect_zoomed(svg, False)
    plot = axes(svg)
    morphometry = watershed["morphometry"]
    low, high = morphometry["elevation_min_m"], morphometry["elevation_max_m"]
    curve = [
        (point["relative_area"] * 100, low + point["relative_height"] * (high - low))
        for point in watershed["hypsometric_curve"]
    ]
    pointer = plot.at(0.5)
    share, elevation = min(curve, key=lambda p: abs(plot.page_x(p[0]) - pointer[0]))
    page.mouse.move(*pointer)
    assert readout(svg) == [
        f"Pow. powyżej: {pl(share, 0)} %",
        f"Wysokość: {pl(elevation, 1)}\u00a0m n.p.m.",
    ]


def test_png_saves_chart_as_shown_with_lines_of_its_data(tab: Tab) -> None:
    page = tab.page
    delineate_watershed(tab)
    answer = rain_hydrograph(tab)
    svg = in_view(chart(page, HYDROGRAPH_CHART))
    zoom_button(svg, "Przybliż").click()
    expect_zoomed(svg, True)
    box = svg.bounding_box()
    assert box is not None
    shown = Image.open(io.BytesIO(svg.screenshot())).convert("L")
    save = page.get_by_role(
        "button", name=f"Pobierz wykres „{HYDROGRAPH_CHART}” jako PNG"
    )

    with page.expect_download() as got:
        save.click()

    download = got.value
    assert download.suggested_filename == "hydrograf_hydrograph_custom.png"
    image = Image.open(io.BytesIO(download.path().read_bytes())).convert("L")
    width, height = round(box["width"]), round(box["height"])
    lines = answer["attribution"] + answer["terms_notice"]
    assert lines, "the hydrograph carries the lines of its data"
    assert image.width == PNG_SCALE * width
    footer = FOOTER_MARGINS_PX + FOOTER_ROW_PX * len(lines)
    assert image.height >= PNG_SCALE * (height + footer), (image.size, len(lines))
    # Above the lines the chart as shown: the zoomed range, as the page draws it
    picture = image.crop((0, 0, PNG_SCALE * width, PNG_SCALE * height)).resize(
        shown.size
    )
    unlike = ImageStat.Stat(ImageChops.difference(picture, shown)).mean[0]
    assert unlike < SAME_PICTURE, unlike
    # The lines are written under the chart: dark text on the light surface
    under = image.crop((0, PNG_SCALE * height, image.width, image.height))
    ink = sum(under.histogram()[:128])
    assert ink > 50 * len(lines), ink


# --- phone: fingers ----------------------------------------------------------------


def test_phone_profile_one_finger_reads_along_line_two_fingers_zoom(
    new_tab: Callable[..., Tab],
) -> None:
    tab = new_tab(width=390)
    page = tab.page
    open_map(tab)
    tools = page.get_by_role("toolbar", name="Rysowanie profilu terenu")
    page.get_by_role("radio", name="Profil terenu", exact=True).tap()
    vertices = places(tab, PHONE_LINE)
    for place in vertices:
        tap_place(page, place)
    line = finish_line(
        tab, lambda: tools.get_by_role("button", name="Rysuj profil").tap()
    )
    svg = profile_drawer(page).get_by_role("img", name=PROFILE_CHART, exact=True)
    host = holder(svg)
    fitted = host.evaluate(
        """(host) => { const svg = host.querySelector('svg');
            return [host.clientWidth, host.scrollWidth,
                    svg.getBoundingClientRect().width,
                    getComputedStyle(svg).touchAction]; }"""
    )
    # Drawn at the drawer's width, never scrolled sideways: one finger is the page's
    # vertical scroll and the readout's
    assert fitted[0] == fitted[1] and fitted[2] == pytest.approx(fitted[0], abs=1)
    assert fitted[3] == "pan-y"
    cdp = page.context.new_cdp_session(page)
    plot = axes(svg)

    # One finger along the plot moves the readout, and the marker along the line
    start = plot.at(0.2)
    touch(cdp, "touchStart", [start])
    first = readout_place(page)
    step = 0.5 * (plot.right - plot.left) / SWIPE_STEPS
    for n in range(1, SWIPE_STEPS + 1):
        touch(cdp, "touchMove", [(start[0] + n * step, start[1])])
    second = readout_place(page, first)
    touch(cdp, "touchEnd", [])
    assert along_line(line, first)[0] < along_line(line, second)[0]
    expect_zoomed(svg, False)

    # Two fingers apart zoom around their middle
    middle = plot.at(0.5)
    left, right = (middle[0] - 30, middle[1]), (middle[0] + 30, middle[1])
    touch(cdp, "touchStart", [left, right])
    for n in range(1, SWIPE_STEPS + 1):
        apart = 10 * n
        touch(
            cdp, "touchMove", [(left[0] - apart, left[1]), (right[0] + apart, right[1])]
        )
    touch(cdp, "touchEnd", [])

    expect_zoomed(svg, True)
    start_km, end_km = value_range(svg)
    whole_km = plot.value(plot.right) - plot.value(plot.left)
    assert end_km - start_km == pytest.approx(whole_km * 60 / 220, rel=0.1)
    boxes = bar_boxes(svg)
    middles = [part["middle"] for part in boxes]
    assert max(middles) - min(middles) < 1, boxes  # one line
    buttons = [part for part in boxes if part["tag"] == "BUTTON"]
    assert len(buttons) == 3 and all(
        part["width"] >= 24 and part["height"] >= 24 for part in buttons
    ), buttons


def test_phone_hydrograph_fits_sheet_vertical_swipe_scrolls_it(
    new_tab: Callable[..., Tab],
) -> None:
    tab = new_tab(width=390)
    page = tab.page
    delineate_watershed(tab)
    rain_hydrograph(tab)
    svg = in_view(chart(page, HYDROGRAPH_CHART))
    host = holder(svg)
    sizes = host.evaluate(
        """(host) => [host.clientWidth, host.scrollWidth,
                      host.querySelector('svg').getBoundingClientRect().width,
                      host.parentElement.clientWidth]"""
    )
    assert sizes[0] == sizes[1] == sizes[3] and sizes[2] == pytest.approx(
        sizes[0], abs=1
    )

    # One finger up the plot scrolls the sheet; the chart stays as it was
    body = page.locator("#results-body")
    before = body.evaluate("(body) => body.scrollTop")
    cdp = page.context.new_cdp_session(page)
    plot = axes(svg)
    start = plot.at(0.5)
    touch(cdp, "touchStart", [start])
    for n in range(1, SWIPE_STEPS + 1):
        touch(cdp, "touchMove", [(start[0], start[1] - 20 * n)])
    touch(cdp, "touchEnd", [])
    page.wait_for_function(
        "(before) => document.getElementById('results-body').scrollTop > before",
        arg=before,
    )
    expect_zoomed(svg, False)


def test_theme_switch_recolours_charts_without_redraw(tab: Tab) -> None:
    page = tab.page
    delineate_watershed(tab)
    rain_hydrograph(tab)
    svg = in_view(chart(page, HYDROGRAPH_CHART))
    flow = svg.locator("path.ser")
    light = token_colors(page, "--info")["--info"]
    svg.evaluate("(svg) => { svg.dataset.drawn = 'before'; }")

    def stroke() -> tuple[int, int, int]:
        value: list[float] = flow.evaluate(
            "(path) => Hydrograf.map.rgb(getComputedStyle(path).stroke)"
        )
        return (round(value[0]), round(value[1]), round(value[2]))

    assert stroke() == light

    page.locator("#theme-dark").click()

    dark = token_colors(page, "--info")["--info"]
    assert dark != light
    page.wait_for_function(
        "(dark) => { const p = document.querySelector('#chart-hydrograph path.ser');"
        " return Hydrograf.map.rgb(getComputedStyle(p).stroke)"
        ".map(Math.round).join() === dark.join(); }",
        arg=list(dark),
    )
    assert svg.evaluate("(svg) => svg.dataset.drawn") == "before"
