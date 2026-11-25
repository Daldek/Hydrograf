"""A recording browser tab of the site, and what the tests read of the map.

``open_tab`` opens a fresh Chromium context (Polish locale, Warsaw time) at one of
``WIDTHS`` with a theme or the system's, the welcome dialog dismissed as a second
visit has it. Its ``Tab`` records the Content-Security-Policy violations
(``securitypolicyviolation``, from a script the page's policy does not cover), the
page errors, the console errors and every request. Every request to another origin
is answered by ``page.route`` from the files of ``recorded/`` (``OUTSIDE``: what
OpenFreeMap (the TileJSON and a vector tile of the kit's base map; its names come from
the site's own glyphs), GUGiK and the flood hazard WMS of Wody Polskie answered on
2026-11-25, each kind of request by one recorded answer, with the providers' CORS
header); anything else outside is refused and noted in ``Tab.refused``.

The map is read through ``Hydrograf.map.describe()`` (``describe``): the overlays
from the bottom up with their opacity, the network's points and the view in degrees
and as a scale, never as a zoom number, so that the tests hold for any library that
draws the map. Colours are read as the nearest of named colours (``nearest``), never
as exact pixels: antialiasing moves a pixel's value. A long command of the API runs as
a job (nogat-job/1), which the page polls: ``job_started`` tells the answer to its
start, ``job_result`` waits for the answer of its result.
"""

import io
import json
import math
import re
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import (
    Browser,
    ConsoleMessage,
    FloatRect,
    Frame,
    Page,
    Request,
    Response,
    Route,
    ViewportSize,
)

from tests.e2e.site import Site

RECORDED = Path(__file__).resolve().parent / "recorded"
# A desktop and a phone (the panels are bottom sheets up to 860 px)
WIDTHS: Mapping[int, ViewportSize] = {
    1440: {"width": 1440, "height": 900},
    390: {"width": 390, "height": 844},
}
# How long an expectation waits for the page, the API or the map: a bound for what
# never arrives, not a speed the page must keep
EXPECT_TIMEOUT_MS = 30_000
# The answers of the outside services: (URL pattern, file of recorded/, type)
OUTSIDE = (
    (
        r"https://tiles\.openfreemap\.org/planet",
        "openfreemap-planet.json",
        "application/json",
    ),
    (
        r"https://tiles\.openfreemap\.org/planet/[^/]+/\d+/\d+/\d+\.pbf",
        "openfreemap-14-9124-5386.pbf",
        "application/vnd.mapbox-vector-tile",
    ),
    (
        (
            r"https://mapy\.geoportal\.gov\.pl/wss/ext/OSM/BaseMap/wmts/osm_3857/"
            r"GLOBAL_WEBMERCATOR/\d+/\d+/\d+\.png"
        ),
        "gugik-osm-14-9124-5386.png",
        "image/png",
    ),
    (
        (
            r"https://mapy\.geoportal\.gov\.pl/wss/service/PZGIK/ORTO/WMTS/"
            r"StandardResolution\?.*"
        ),
        "gugik-ortho-14-9124-5386.jpg",
        "image/jpeg",
    ),
    (
        r"https://wody\.isok\.gov\.pl/gpservices/KZGW/MZP20_\w+/MapServer/WMSServer\?.*",
        "isok-mzp20-srednie-14.png",
        "image/png",
    ),
)
# Installed before any script of the page; the page's CSP does not cover it
CSP_WATCH = """
window.__cspViolations = [];
document.addEventListener("securitypolicyviolation", (event) => {
  window.__cspViolations.push({
    directive: event.violatedDirective,
    blocked: event.blockedURI,
    sample: event.sample,
  });
});
"""
# Chromium logs every 4xx and 5xx answer so (a missing DEM tile at the data's edge
# among them); the tests assert the answers they expect themselves
FAILED_RESOURCE = "Failed to load resource"
# How long the page has had no request in flight when it counts as settled
QUIET_S = 0.5
SETTLE_TIMEOUT_S = 30.0
JOBS = "/api/v1/jobs"

Rgb = tuple[int, int, int]


@dataclass
class Sent:
    """A request the page sent."""

    method: str
    url: str
    post_data: str | None


@dataclass
class Tab:
    """A browser page of the site and what happened on it."""

    page: Page
    site: Site
    page_errors: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    requests: list[Sent] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    in_flight: set[Request] = field(default_factory=set)
    document: Request | None = field(default=None, repr=False)
    tolerated: list[tuple[re.Pattern[str], str]] = field(default_factory=list)

    def watch(self) -> None:
        """Start recording; called once, before the first navigation."""
        self.page.on("pageerror", lambda error: self.page_errors.append(str(error)))
        self.page.on("console", self._console)
        self.page.on("request", self._request)
        # Answered is done: a page that never reads a body (the admin key's check)
        # never ends its request
        self.page.on("response", lambda response: self._ended(response.request))
        self.page.on("requestfinished", self._ended)
        self.page.on("requestfailed", self._ended)
        self.page.on("framenavigated", self._navigated)

    def mark(self) -> int:
        """The position in ``requests`` from which ``sent_since`` counts."""
        return len(self.requests)

    def sent_since(self, mark: int, pattern: str = "") -> list[Sent]:
        """The requests since ``mark`` whose URL matches the regular expression."""
        return [s for s in self.requests[mark:] if re.search(pattern, s.url)]

    def settle(self) -> None:
        """Wait until the page has had no request in flight for ``QUIET_S``."""
        deadline = time.monotonic() + SETTLE_TIMEOUT_S
        quiet_since = time.monotonic()
        while time.monotonic() - quiet_since < QUIET_S:
            pending = sorted(request.url for request in self.in_flight)
            assert time.monotonic() < deadline, f"the page did not settle: {pending}"
            self.page.wait_for_timeout(50)
            if self.in_flight:
                quiet_since = time.monotonic()

    def csp_violations(self) -> list[dict[str, str]]:
        """The CSP violations of the current document."""
        violations: list[dict[str, str]] = self.page.evaluate(
            "window.__cspViolations || []"
        )
        return violations

    def tolerate(self, pattern: str, reason: str) -> None:
        """Leave out of ``problems`` what matches ``pattern``.

        A known defect, named by ``reason``, that a test of its own tracks (marked
        xfail with the same reason).
        """
        self.tolerated.append((re.compile(pattern), reason))

    def problems(self) -> list[str]:
        """CSP violations, page errors, console errors and refused outside requests."""
        found = (
            [f"CSP: {v}" for v in self.csp_violations()]
            + [f"page error: {e}" for e in self.page_errors]
            + [f"console error: {e}" for e in self.console_errors]
            + [f"refused outside request: {u}" for u in self.refused]
        )
        return [
            problem
            for problem in found
            if not any(pattern.search(problem) for pattern, _ in self.tolerated)
        ]

    def _console(self, message: ConsoleMessage) -> None:
        if message.type == "error" and not message.text.startswith(FAILED_RESOURCE):
            self.console_errors.append(message.text)

    def _request(self, request: Request) -> None:
        self.requests.append(Sent(request.method, request.url, request.post_data))
        self.in_flight.add(request)
        if request.is_navigation_request() and request.frame == self.page.main_frame:
            self.document = request

    def _ended(self, request: Request) -> None:
        self.in_flight.discard(request)

    def _navigated(self, frame: Frame) -> None:
        """Forget the requests of the document a new one replaced (never answered)."""
        if frame == self.page.main_frame and self.document is not None:
            self.in_flight &= {self.document}
            self.document = None


def _answer_outside(tab: Tab, route: Route) -> None:
    """Answer a request to another origin from recorded/, or refuse it."""
    url = route.request.url
    for pattern, name, content_type in OUTSIDE:
        if re.fullmatch(pattern, url):
            route.fulfill(
                status=200,
                content_type=content_type,
                headers={"Access-Control-Allow-Origin": "*"},
                body=(RECORDED / name).read_bytes(),
            )
            return
    tab.refused.append(url)
    route.abort()


@contextmanager
def open_tab(
    browser: Browser,
    site: Site,
    *,
    width: int = 1440,
    theme: str | None = None,
    welcome: bool = False,
) -> Iterator[Tab]:
    """A recording tab of the site in a fresh context, before any navigation.

    Parameters
    ----------
    width : int
        One of ``WIDTHS``; the phone's (390) is a touch screen.
    theme : str, optional
        ``light`` or ``dark`` chosen in the page (``nogat-theme``); None: the
        system's, light.
    welcome : bool
        Whether the welcome dialog of a first visit shows.
    """
    phone = width < 860
    context = browser.new_context(
        viewport=WIDTHS[width],
        locale="pl-PL",
        timezone_id="Europe/Warsaw",
        color_scheme="light",
        has_touch=phone,
        is_mobile=phone,
    )
    try:
        page = context.new_page()
        tab = Tab(page, site)
        tab.watch()
        page.add_init_script(CSP_WATCH)
        # Kept once the page changes them (a reload does not undo a chosen theme)
        stored = {} if welcome else {"hydrograf-welcome-hidden": "1"}
        if theme is not None:
            stored["nogat-theme"] = theme
        if stored:
            page.add_init_script(
                f"Object.entries({json.dumps(stored)}).forEach(([k, v]) => "
                "localStorage.getItem(k) === null && localStorage.setItem(k, v));"
            )
        context.route(
            re.compile(r"^(?!https?://127\.0\.0\.1[:/]).+"),
            lambda route: _answer_outside(tab, route),
        )
        yield tab
    finally:
        context.close()


# --- the API's jobs ------------------------------------------------------------------


def job_started(command: str) -> Callable[[Response], bool]:
    """Whether an answer is the one to the start of a job of ``command``."""

    def started(response: Response) -> bool:
        request = response.request
        return (
            request.method == "POST"
            and urlsplit(response.url).path == JOBS
            and (request.post_data_json or {}).get("command") == command
        )

    return started


def job_result(page: Page, started: Response) -> Response:
    """The answer of the result of the job whose start ``started`` answered.

    The page polls the job until it ends, then asks GET /api/v1/jobs/<id>/result: its
    answer is the command's, the envelope or the problem document. A refused start
    (not 202) is its own answer.
    """
    if started.status != 202:
        return started
    path = f"{JOBS}/{started.json()['id']}/result"
    answered: Response = page.wait_for_event(
        "response", lambda response: urlsplit(response.url).path == path
    )
    return answered


# --- the map -------------------------------------------------------------------------


def describe(page: Page) -> dict[str, Any]:
    """``Hydrograf.map.describe()``: overlays bottom up, points, view, scale."""
    described: dict[str, Any] | None = page.evaluate("Hydrograf.map.describe()")
    assert described is not None, "the map does not exist"
    return described


def overlay_ids(page: Page) -> list[str]:
    """The overlays on the map, from the bottom up."""
    return [overlay["id"] for overlay in describe(page)["overlays"]]


def overlay(page: Page, overlay_id: str) -> dict[str, Any] | None:
    """The overlay ``overlay_id`` of the map, or None when it is not drawn."""
    for drawn in describe(page)["overlays"]:
        if drawn["id"] == overlay_id:
            found: dict[str, Any] = drawn
            return found
    return None


def wait_view(page: Page, timeout_s: float = 30.0) -> dict[str, Any]:
    """Wait until the view stops moving; return the description then."""
    deadline = time.monotonic() + timeout_s
    previous = None
    while True:
        current = describe(page)
        view = (current["center"], current["bounds"], current["scale"])
        if view == previous:
            return current
        assert time.monotonic() < deadline, "the map did not stop moving"
        previous = view
        page.wait_for_timeout(300)


def open_map(tab: Tab, path: str = "/") -> dict[str, Any]:
    """Open the site's map: the layers panel built, the page settled, the view still."""
    page = tab.page
    page.goto(tab.site.base + path)
    # A function, not an expression: Playwright re-polls an expression through eval,
    # which the page's CSP (no 'unsafe-eval') refuses
    page.wait_for_function(
        "() => window.Hydrograf && Hydrograf.map && Hydrograf.map.describe()"
    )
    # The streams' row waits for the thresholds of the API
    page.locator("#fa-threshold").wait_for(state="attached")
    tab.settle()
    return wait_view(page)


def zoom_in(page: Page) -> None:
    """One step closer by the map's own button."""
    page.get_by_role("button", name=re.compile(r"^(Zoom in|Przybliż)$")).click()


def zoom_out(page: Page) -> None:
    """One step farther by the map's own button."""
    page.get_by_role("button", name=re.compile(r"^(Zoom out|Oddal)$")).click()


def _mercator_y(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def screen_point(
    page: Page, lng: float, lat: float, described: dict[str, Any] | None = None
) -> tuple[float, float]:
    """The page's pixel of a place on the map (web mercator within the view)."""
    view = described or describe(page)
    west, south, east, north = view["bounds"]
    box = page.locator("#map").bounding_box()
    assert box is not None
    x = box["x"] + (lng - west) / (east - west) * box["width"]
    top, bottom = _mercator_y(north), _mercator_y(south)
    y = box["y"] + (top - _mercator_y(lat)) / (top - bottom) * box["height"]
    return x, y


def map_place(page: Page, x: float, y: float) -> tuple[float, float]:
    """The place (longitude, latitude) under a pixel of the page."""
    view = describe(page)
    west, south, east, north = view["bounds"]
    box = page.locator("#map").bounding_box()
    assert box is not None
    lng = west + (x - box["x"]) / box["width"] * (east - west)
    top, bottom = _mercator_y(north), _mercator_y(south)
    merc = top - (y - box["y"]) / box["height"] * (top - bottom)
    lat = math.degrees(2 * math.atan(math.exp(merc)) - math.pi / 2)
    return lng, lat


# --- colours -------------------------------------------------------------------------


def token_colors(page: Page, *names: str) -> dict[str, Rgb]:
    """The colours of tokens of tokens.css in the page's current theme."""
    values: dict[str, list[float]] = page.evaluate(
        "(names) => Object.fromEntries(names.map((n) => "
        "[n, Hydrograf.map.rgb(Hydrograf.map.token(n))]))",
        list(names),
    )
    return {name: (round(v[0]), round(v[1]), round(v[2])) for name, v in values.items()}


def pixels(page: Page, x: float, y: float, radius: int = 2) -> list[Rgb]:
    """The colours of the page's pixels within ``radius`` of a point."""
    side = 2 * radius + 1
    clip: FloatRect = {
        "x": max(0, round(x) - radius),
        "y": max(0, round(y) - radius),
        "width": side,
        "height": side,
    }
    image = Image.open(io.BytesIO(page.screenshot(clip=clip))).convert("RGB")
    packed = image.tobytes()
    return [(packed[k], packed[k + 1], packed[k + 2]) for k in range(0, len(packed), 3)]


def distance(a: Rgb, b: Rgb) -> float:
    return math.dist(a, b)


def nearest(color: Rgb, candidates: Mapping[str, Rgb]) -> str:
    """The name of the candidate colour nearest to ``color``."""
    return min(candidates, key=lambda name: distance(color, candidates[name]))
