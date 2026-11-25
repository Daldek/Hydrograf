"""The pages under nginx's Content-Security-Policy ask nothing outside it.

Nogat's plan 2026-11-24-hydrograf-maplibre, step 1, „Tests”: „under nginx's CSP of
docker/nginx.conf, no violation is reported and nothing is asked of an origin outside
it”.

The map's page is sent with exactly the server's policy of nginx.conf and the admin
page with its location's (``site.policies``, read from that file). The map's page is
exercised broadly: the default base map (OpenFreeMap, drawn by MapLibre in a worker),
every row of the layers panel on at the first view (≈1:34 124, so the flood hazard
map's WMS is asked too), then each other base map (GUGiK's OSM, the orthophoto, none)
and back. Then no violation was reported and no outside request refused; every
request went to the site's own origin or to one the policy's directive for its kind
lists (by Playwright's resource type: ``img-src`` for images, ``connect-src`` for
fetches and so on, with CSP's fallbacks), OpenFreeMap, GUGiK and the MZP's WMS among
them; and a worker started whose URL ``worker-src`` (or its fallbacks) allows:
MapLibre's file of ``vendor/`` under ``worker-src 'self'``.

The admin page, signed in with its dialog's map open, asks only what its own policy
allows (GUGiK's tiles, the first raster entry of the kit's catalogue, and MapLibre's
worker of ``vendor/``) and reports no violation.
"""

import re
from urllib.parse import urlsplit

from playwright.sync_api import Page, Response, expect

from tests.e2e.browser import Tab, open_map
from tests.e2e.site import ADMIN_KEY, RESULT_TITLE

# The fetch directive of each of Playwright's resource types; any other kind falls to
# default-src. "worker" is the tests' own kind, for a worker's script.
KIND_DIRECTIVES = {
    "image": "img-src",
    "fetch": "connect-src",
    "xhr": "connect-src",
    "eventsource": "connect-src",
    "websocket": "connect-src",
    "script": "script-src",
    "stylesheet": "style-src",
    "font": "font-src",
    "media": "media-src",
    "manifest": "manifest-src",
    "worker": "worker-src",
}
# CSP3's fallbacks of worker-src: the first directive of these the policy holds
# governs; any other directive falls back to default-src alone
WORKER_FALLBACKS = ("worker-src", "child-src", "script-src", "default-src")
DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}
# The outside services the map's page draws from: OpenFreeMap's vector base map,
# GUGiK's OSM and orthophoto, the flood hazard map's WMS of Wody Polskie
NAMED_ORIGINS = {
    "https://tiles.openfreemap.org",
    "https://mapy.geoportal.gov.pl",
    "https://wody.isok.gov.pl",
}
# The flood hazard map (MZP) is drawn from 1:50 000 on
MZP_MAX_SCALE = 50_000
# The rows that join the layers panel after an answer of their own
LATE_ROWS = ("Kanalizacja deszczowa", "Zagłębienia", RESULT_TITLE)
OTHER_BASEMAPS = (
    "OSM GUGiK szary (tylko Polska)",
    "Ortofotomapa GUGiK",
    "bez podkładu",
)
DEFAULT_BASEMAP = "OpenFreeMap szary"


def _record(page: Page) -> tuple[list[tuple[str, str]], list[str]]:
    """Record each request's resource type and URL, and each worker's URL."""
    sent: list[tuple[str, str]] = []
    workers: list[str] = []
    page.on(
        "request", lambda request: sent.append((request.resource_type, request.url))
    )
    page.on("worker", lambda worker: workers.append(worker.url))
    return sent, workers


def _is_document(response: Response) -> bool:
    return response.request.is_navigation_request()


def _directives(policy: str) -> dict[str, list[str]]:
    """A policy's directives, name → source list (CSP keeps the first of a name)."""
    found: dict[str, list[str]] = {}
    for part in policy.split(";"):
        words = part.split()
        if words:
            found.setdefault(words[0].lower(), words[1:])
    return found


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _host(url: str) -> tuple[str, str | None, int | None]:
    """Scheme, host and port (the scheme's default when none is written)."""
    parts = urlsplit(url)
    return parts.scheme, parts.hostname, parts.port or DEFAULT_PORTS.get(parts.scheme)


def _matches(source: str, url: str, own: str) -> bool:
    """Whether a source expression allows a URL (the forms nginx.conf writes)."""
    scheme = urlsplit(url).scheme
    if source == "'self'":
        return scheme in DEFAULT_PORTS and _host(url) == _host(own)
    if source == "*":
        return scheme in DEFAULT_PORTS
    if re.fullmatch(r"[a-z][a-z0-9+.-]*:", source):
        return scheme == source[:-1]
    if "://" in source:
        return _host(url) == _host(source)
    # 'none', 'unsafe-inline' and the like name no URL
    return False


def _allows(directives: dict[str, list[str]], kind: str, url: str, own: str) -> bool:
    """Whether the directive governing a kind of request allows the URL."""
    directive = KIND_DIRECTIVES.get(kind, "default-src")
    chain = WORKER_FALLBACKS if kind == "worker" else (directive, "default-src")
    for name in chain:
        if name in directives:
            return any(_matches(source, url, own) for source in directives[name])
    return True


def _outside_policy(
    policy: str, sent: list[tuple[str, str]], workers: list[str], own: str
) -> list[str]:
    """The requests outside the site's own origin and the workers the policy refuses.

    A request for a worker's script counts as that worker's.
    """
    directives = _directives(policy)
    refused = [
        f"{kind} {url}"
        for kind, url in sent
        if url not in workers
        and _origin(url) != own
        and not _allows(directives, kind, url, own)
    ]
    refused += [
        f"worker {url}"
        for url in workers
        if not _allows(directives, "worker", url, own)
    ]
    return refused


def _open_admin_map(tab: Tab) -> Response:
    """Open the admin page, sign in, open the dialog's map; the document's answer."""
    page = tab.page
    response = page.goto(tab.site.base + "/admin/#processing")
    assert response is not None
    page.get_by_label("Klucz administratora", exact=True).fill(ADMIN_KEY)
    page.get_by_role("button", name="Zaloguj", exact=True).click()
    page.locator("#bbox-map-open").click()
    expect(page.get_by_role("dialog", name="Wybierz obszar na mapie")).to_be_visible()
    tab.settle()
    return response


def test_map_page_under_nginx_policy_asks_only_allowed_origins(tab: Tab) -> None:
    page = tab.page
    site = tab.site
    sent, workers = _record(page)
    with page.expect_response(_is_document) as document:
        view = open_map(tab)
    assert document.value.header_value("Content-Security-Policy") == site.policies.page
    assert view["scale"] <= MZP_MAX_SCALE, view["scale"]

    for label in LATE_ROWS:
        expect(page.get_by_label(label, exact=True)).to_be_attached()
    rows = page.locator("#layers-list").get_by_role("checkbox")
    for index in range(rows.count()):
        rows.nth(index).check()
    tab.settle()
    for basemap in (*OTHER_BASEMAPS, DEFAULT_BASEMAP):
        page.get_by_role("radio", name=basemap, exact=True).check()
        tab.settle()

    own = _origin(site.base)
    assert tab.csp_violations() == []
    assert tab.refused == []
    assert _outside_policy(site.policies.page, sent, workers, own) == []
    asked = {_origin(url) for _, url in sent}
    assert asked >= NAMED_ORIGINS, sorted(asked)
    assert workers, "no worker started: MapLibre draws the vector base map in one"


def test_admin_page_under_nginx_policy_asks_only_allowed_origins(tab: Tab) -> None:
    site = tab.site
    sent, workers = _record(tab.page)
    response = _open_admin_map(tab)
    assert response.header_value("Content-Security-Policy") == site.policies.admin

    own = _origin(site.base)
    assert tab.refused == []
    assert _outside_policy(site.policies.admin, sent, workers, own) == []
    asked = {_origin(url) for _, url in sent}
    assert "https://mapy.geoportal.gov.pl" in asked, sorted(asked)


def test_admin_page_under_nginx_policy_reports_no_violation(tab: Tab) -> None:
    _open_admin_map(tab)
    assert tab.csp_violations() == []
