"""What every request passes before the routes: the request limit and the daily totals.

Nogat DEV-15.9 to DEV-15.11, ADR-084. Hydrograf runs as one process, so its limits and
totals live in that process's memory (``app.state.traffic``):

- Limit (``core.request_limit``): pages and API routes, 300 requests in 60 s per client
  address by default (HYDROGRAF_REQUEST_LIMIT, HYDROGRAF_REQUEST_WINDOW); map tiles
  (``/api/tiles/``) ten times that in the same window instead; „Zgłoś uwagę”
  (``POST /api/feedback``) besides at most 5 reports in 5 minutes. nginx serves the
  static files itself, so they are not counted; ``/health`` is not either. Over a
  limit a page answers 429 with a Polish page and an API route with the problem
  ``rate_limited``, both with ``Retry-After`` in seconds.
- Totals (``core.usage``): a visitor for every counted request, and the page views,
  analyses and downloads of ``count``; stored every 10 minutes, at 00:00 UTC and at
  shutdown in ``<data_dir>/hydrograf/stats.jsonl``.
- Admin panel (Nogat DEV-15.13, ADR-086): its page under ``/admin/`` and its API under
  ``/api/admin/`` are limited like any page or route but count in no total, and each
  of their answers, a refusal included, is ``Cache-Control: no-store``.

The client's address: nginx passes the address of its own peer in ``X-Real-IP``.
Behind the Cloudflare Tunnel that peer is the tunnel's connector on the host, which
nginx sees from the Docker network, and the client is the address Cloudflare reports
in ``CF-Connecting-IP``. Each header is believed only from a hop on a loopback or
private network (nginx, the connector); a public hop is the client itself. The address
stays in memory, for the limit's window and the visitor's hash only; no log, file or
table holds it (DEV-15.10).
"""

import asyncio
import datetime
import ipaddress
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import HTMLResponse
from starlette.middleware.base import RequestResponseEndpoint

from api.errors import problem_response
from core.config import Settings
from core.request_limit import RequestLimit
from core.usage import DailyUsage, StatsFile, utc_today

logger = logging.getLogger(__name__)

# Requests no limit and no total counts: the health checks of Docker and nginx
UNCOUNTED = frozenset({"/health"})
# The admin panel and its API: limited, never counted, never cached (DEV-15.13)
ADMIN = ("/admin/", "/api/admin/")
TILES = "/api/tiles/"
FEEDBACK = ("POST", "/api/feedback")
# Map tiles have their own limit: this many times the general one, in its window
TILE_FACTOR = 10
# „Zgłoś uwagę” besides the general limit: reports per address and window [s]
FEEDBACK_LIMIT = 5
FEEDBACK_WINDOW_S = 300
# What the totals count besides visitors (README "Statistics"): successful answers of
# the routes that compute, and the files the interface reports it saved
ANALYSES = frozenset(
    {
        ("POST", "/api/delineate-watershed"),
        ("POST", "/api/delineate-network"),
        ("POST", "/api/generate-hydrograph"),
        ("POST", "/api/terrain-profile"),
    }
)
DOWNLOADS = frozenset({("POST", "/api/downloads")})
# Housekeeping: windows that ended are forgotten within this many seconds [s]
FORGET_EVERY_S = 5.0
# The day's totals are stored this often [s]
STORE_EVERY_S = 600.0
# Where a hop whose header is believed may be: loopback, the private networks of
# RFC 1918 and RFC 4193 (Docker's among them) and link-local addresses
PROXY_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "127.0.0.0/8",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "169.254.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)

PAGE_429 = """<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Zbyt wiele żądań · Hydrograf</title>
<link rel="stylesheet" href="/css/tokens.css">
<link rel="stylesheet" href="/nogat/nogat-terms.css">
</head>
<body>
<main class="nogat-terms">
<h1>Hydrograf</h1>
<p>Zbyt wiele żądań. Spróbuj ponownie za {seconds} s.</p>
</main>
</body>
</html>
"""


@dataclass(frozen=True)
class Refusal:
    """A request over a limit: which limit and how long to wait.

    Attributes
    ----------
    reason : str
        ``request_limit``, ``tile_limit`` or ``feedback_limit``.
    wait_s : int
        Seconds until the window of the address ends (``Retry-After``).
    limit : RequestLimit
        The limit the request is over.
    """

    reason: str
    wait_s: int
    limit: RequestLimit


class Traffic:
    """The limits and the day's totals of this process.

    Parameters
    ----------
    settings : Settings
        The limit, its window and the data directory of the statistics.
    """

    def __init__(self, settings: Settings) -> None:
        limit = settings.hydrograf_request_limit
        window_s = settings.hydrograf_request_window
        self.general = RequestLimit(limit, window_s)
        self.tiles = RequestLimit(TILE_FACTOR * limit, window_s)
        self.feedback = RequestLimit(FEEDBACK_LIMIT, FEEDBACK_WINDOW_S)
        self.usage = DailyUsage(utc_today())
        self.stats = StatsFile(
            Path(settings.hydrograf_data_dir) / "hydrograf" / "stats.jsonl"
        )

    def check(self, method: str, path: str, address: str, now: float) -> Refusal | None:
        """Count a request of ``address`` against its limits; the refusal, if any."""
        if path.startswith(TILES):
            wait = self.tiles.hit(address, now)
            return None if wait is None else Refusal("tile_limit", wait, self.tiles)
        wait = self.general.hit(address, now)
        if wait is not None:
            return Refusal("request_limit", wait, self.general)
        if (method, path) == FEEDBACK:
            wait = self.feedback.hit(address, now)
            if wait is not None:
                return Refusal("feedback_limit", wait, self.feedback)
        return None

    def count(self, method: str, path: str, status: int) -> None:
        """Add a successful answer to the day's totals (README "Statistics")."""
        if status >= 400:
            return
        if method == "GET" and path.endswith(".html"):
            self.usage.add("page_views")
        elif (method, path) in ANALYSES:
            self.usage.add("analyses_run")
        elif (method, path) in DOWNLOADS:
            self.usage.add("downloads")

    def new_day(self) -> None:
        """At the first moment of a UTC day: store the last day, start the new one."""
        finished = self.usage.roll(utc_today())
        if finished is not None:
            self._store(*finished)

    def store(self) -> None:
        """Store this process's totals of the current day."""
        self._store(self.usage.day, self.usage.totals())

    def forget_expired(self, now: float) -> None:
        """Forget the addresses whose windows have ended."""
        for limit in (self.general, self.tiles, self.feedback):
            limit.forget_expired(now)

    def _store(self, day: datetime.date, totals: dict[str, int]) -> None:
        try:
            self.stats.write(day, totals)
        except OSError as error:
            logger.warning(
                "The daily statistics cannot be stored in %s: %s",
                self.stats.path,
                error,
            )


def client_address(request: Request) -> str:
    """Return the address of the client of ``request`` (see the module)."""
    address = request.client.host if request.client else ""
    for header in ("x-real-ip", "cf-connecting-ip"):
        if not _is_proxy(address):
            break
        reported = _address(request.headers.get(header))
        if reported is None:
            break
        address = reported
    return address


def _address(text: str | None) -> str | None:
    """Return ``text`` as an IP address in its normal form, or None."""
    if not text:
        return None
    try:
        address = ipaddress.ip_address(text.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return str(address.ipv4_mapped)
    return str(address)


def _is_proxy(text: str) -> bool:
    """Whether a hop at ``text`` is on a network of ``PROXY_NETWORKS``."""
    normal = _address(text)
    if normal is None:
        return False
    address = ipaddress.ip_address(normal)
    return any(address in network for network in PROXY_NETWORKS)


def too_many_requests(request: Request, refusal: Refusal) -> Response:
    """Answer a request over a limit: a Polish page for a page, else a problem."""
    headers = {"Retry-After": str(refusal.wait_s)}
    if request.url.path.endswith(".html"):
        return HTMLResponse(
            PAGE_429.format(seconds=refusal.wait_s),
            status_code=429,
            headers={**headers, "Cache-Control": "no-store"},
        )
    return problem_response(
        request,
        "rate_limited",
        message_id="request_limit",
        details={
            "reason": refusal.reason,
            "retry_after_s": refusal.wait_s,
            "limit": refusal.limit.limit,
            "window_s": refusal.limit.window_s,
        },
        headers=headers,
    )


async def limit_and_count(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Limit a request per client address and count it in the day's totals."""
    path = request.url.path
    if path in UNCOUNTED:
        return await call_next(request)
    traffic: Traffic = request.app.state.traffic
    traffic.new_day()
    address = client_address(request)
    admin = path.startswith(ADMIN)
    if not admin:
        traffic.usage.visit(address, request.headers.get("user-agent", ""))
    refusal = traffic.check(request.method, path, address, time.monotonic())
    if refusal is not None:
        response = too_many_requests(request, refusal)
    else:
        response = await call_next(request)
        if not admin:
            traffic.count(request.method, path, response.status_code)
    if admin:
        response.headers["Cache-Control"] = "no-store"
    return response


async def keep_traffic(traffic: Traffic) -> None:
    """Forget ended windows, start each UTC day and store the totals until cancelled."""
    stored = time.monotonic()
    while True:
        await asyncio.sleep(FORGET_EVERY_S)
        now = time.monotonic()
        traffic.forget_expired(now)
        traffic.new_day()
        if now - stored >= STORE_EVERY_S:
            traffic.store()
            stored = now
