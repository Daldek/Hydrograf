"""
The request limit and the daily totals of every request (api/traffic.py; ADR-084).

Nogat DEV-15.9 to DEV-15.11, AGI-6.9, AGI-6.10: pages and API routes are limited per
client address, the right-most address of `X-Forwarded-For` that is no private hop,
believed only from a private peer (nginx, a proxy on the host); over the limit a page
answers a Polish page and a route the problem `rate_limited`, both with `Retry-After`;
a client holds at most 2 active jobs; no log holds the address; the day's totals count
visitors, pages, analyses and downloads and are stored at shutdown.
"""

import dataclasses
import datetime
import json
import logging
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import api.endpoints.site
import api.traffic
from api import catalog
from api.envelope import Outcome
from api.jobs import JobStore
from api.main import app
from api.traffic import Traffic, client_address
from core.config import Settings
from core.database import get_db
from core.usage import DailyUsage

# The hops of a request through the Cloudflare Tunnel or Latarnik: the proxy on the
# host sends the client's address in X-Forwarded-For, nginx appends its own peer, that
# proxy seen from the Docker network, and nginx's container calls the API
NGINX = ("172.18.0.3", 50000)
HOST = "172.18.0.1"
CLIENT = "203.0.113.77"
THROUGH_TUNNEL = {"X-Forwarded-For": f"{CLIENT}, {HOST}"}
# Another client behind the same proxy and nginx
OTHER_CLIENT = "198.51.100.4"
OTHER_THROUGH_TUNNEL = {"X-Forwarded-For": f"{OTHER_CLIENT}, {HOST}"}
JOBS = "/api/v1/jobs"
HYDROGRAPH_JOB = {
    "command": "hydrograph generate",
    "options": {
        "latitude": 52.23,
        "longitude": 21.01,
        "duration": "1h",
        "probability": 10,
    },
}


@pytest.fixture
def traffic(tmp_path):
    """Install the traffic of a new process with the given limit and return it."""

    def install(limit: int = 2) -> Traffic:
        state = Traffic(
            Settings(
                hydrograf_request_limit=limit,
                hydrograf_request_window=60,
                hydrograf_data_dir=str(tmp_path),
            )
        )
        app.state.traffic = state
        return state

    return install


@pytest.fixture
def client():
    return TestClient(app, client=NGINX)


@pytest.fixture
def held_jobs(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep every job of ``hydrograph generate`` running until the test ends."""
    release = threading.Event()

    def hold(options: object, db: object) -> Outcome:
        release.wait(60)
        return Outcome({})

    command = dataclasses.replace(catalog.BY_NAME["hydrograph generate"], run=hold)
    monkeypatch.setitem(catalog.BY_NAME, command.name, command)
    store = JobStore(None, session=lambda: nullcontext(MagicMock()))
    monkeypatch.setattr(app.state, "jobs", store)
    yield
    release.set()


def _request(
    peer: str, headers: Mapping[str, str] | Sequence[tuple[str, str]]
) -> Request:
    lines = headers.items() if isinstance(headers, Mapping) else headers
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/gui",
        "headers": [(k.lower().encode(), v.encode()) for k, v in lines],
        "client": (peer, 50000),
    }
    return Request(scope)


class TestClientAddress:
    def test_the_tunnel_reports_the_client_before_its_own_hop(self):
        assert client_address(_request("172.18.0.3", THROUGH_TUNNEL)) == CLIENT

    def test_a_public_peer_of_nginx_is_the_client_itself(self):
        # Straight to nginx from the Internet: nginx appends that peer
        headers = {"X-Forwarded-For": OTHER_CLIENT}

        assert client_address(_request("172.18.0.3", headers)) == OTHER_CLIENT

    def test_a_public_peer_of_the_api_is_the_client_whatever_it_forwards(self):
        assert (
            client_address(_request("198.51.100.9", THROUGH_TUNNEL)) == "198.51.100.9"
        )

    @pytest.mark.parametrize(
        ("forwarded", "address"),
        [
            # Through the tunnel, with a header of the client's own
            (f"192.0.2.66, {CLIENT}, {HOST}", CLIENT),
            (f"10.0.0.7, {CLIENT}, {HOST}", CLIENT),
            # Straight to nginx, claiming to be another client
            (f"{CLIENT}, {OTHER_CLIENT}", OTHER_CLIENT),
        ],
        ids=["tunnel", "tunnel-private", "nginx"],
    )
    def test_a_forged_left_most_address_is_ignored(self, forwarded, address):
        headers = {"X-Forwarded-For": forwarded}

        assert client_address(_request("172.18.0.3", headers)) == address

    @pytest.mark.parametrize(
        ("peer", "headers", "address"),
        [
            # The API called on the host, from the Docker network or the loopback
            (HOST, {}, HOST),
            ("127.0.0.1", {}, "127.0.0.1"),
            # nginx called on the host: it appends its peer, the host
            ("172.18.0.3", {"X-Forwarded-For": HOST}, HOST),
        ],
        ids=["api-from-docker-host", "api-on-loopback", "nginx-from-host"],
    )
    def test_a_request_from_the_host_without_a_proxy_is_its_nearest_hop(
        self, peer, headers, address
    ):
        assert client_address(_request(peer, headers)) == address

    @pytest.mark.parametrize(
        ("forwarded", "address"),
        [
            (f"{CLIENT}, unknown, {HOST}", HOST),
            ("unknown", "172.18.0.3"),
            (f"{CLIENT}, 999.0.0.1", "172.18.0.3"),
        ],
        ids=["between-hops", "alone", "invalid-address"],
    )
    def test_an_item_that_is_no_address_stops_the_walk_at_the_nearest_hop(
        self, forwarded, address
    ):
        headers = {"X-Forwarded-For": forwarded}

        assert client_address(_request("172.18.0.3", headers)) == address

    def test_the_lines_of_x_forwarded_for_are_one_list(self):
        lines = [
            ("X-Forwarded-For", "192.0.2.66"),
            ("X-Forwarded-For", CLIENT),
            ("X-Forwarded-For", HOST),
        ]

        assert client_address(_request("172.18.0.3", lines)) == CLIENT

    @pytest.mark.parametrize(
        ("peer", "headers", "address"),
        [
            (
                "::ffff:172.18.0.3",
                {"X-Forwarded-For": f"::ffff:{CLIENT}, ::ffff:{HOST}"},
                CLIENT,
            ),
            ("::1", {"X-Forwarded-For": f"::ffff:{CLIENT}"}, CLIENT),
            (f"::ffff:{HOST}", {}, HOST),
            ("::ffff:198.51.100.9", {}, "198.51.100.9"),
        ],
        ids=["forwarded", "ipv6-loopback", "private-peer", "public-peer"],
    )
    def test_an_ipv4_mapped_address_is_the_ipv4_address(self, peer, headers, address):
        assert client_address(_request(peer, headers)) == address


class TestRequestLimit:
    def test_over_the_limit_a_route_answers_the_problem_rate_limited(
        self, traffic, client
    ):
        traffic(limit=2)
        headers = {**THROUGH_TUNNEL, "Accept-Language": "pl"}
        first = [client.get("/api/v1/gui", headers=headers).status_code for _ in "ab"]

        response = client.get("/api/v1/gui", headers=headers)

        assert first == [200, 200]
        assert response.status_code == 429
        assert response.headers["content-type"] == "application/problem+json"
        wait = int(response.headers["Retry-After"])
        assert 1 <= wait <= 60
        problem = response.json()
        assert problem["code"] == "rate_limited"
        assert problem["detail"] == f"Zbyt wiele żądań. Spróbuj ponownie za {wait} s."
        assert problem["details"] == {
            "reason": "request_limit",
            "retry_after_s": wait,
            "limit": 2,
            "window_s": 60,
        }

    def test_over_the_limit_a_page_answers_a_polish_page(self, traffic, client):
        traffic(limit=1)
        first = client.get("/index.html", headers=THROUGH_TUNNEL)

        response = client.get("/index.html", headers=THROUGH_TUNNEL)

        assert first.status_code == 200
        assert response.status_code == 429
        assert response.headers["content-type"].startswith("text/html")
        wait = response.headers["Retry-After"]
        assert f"Zbyt wiele żądań. Spróbuj ponownie za {wait} s." in response.text
        assert "X-Accel-Redirect" not in response.headers

    def test_two_clients_behind_one_proxy_are_limited_apart(self, traffic, client):
        traffic(limit=1)
        first = client.get("/api/v1/gui", headers=THROUGH_TUNNEL)

        second = client.get("/api/v1/gui", headers=THROUGH_TUNNEL)
        other = client.get("/api/v1/gui", headers=OTHER_THROUGH_TUNNEL)

        assert (first.status_code, second.status_code) == (200, 429)
        assert other.status_code == 200

    def test_two_clients_behind_one_proxy_hold_their_jobs_apart(
        self, client, held_jobs
    ):
        first = [
            client.post(JOBS, json=HYDROGRAPH_JOB, headers=THROUGH_TUNNEL).status_code
            for _ in "ab"
        ]

        third = client.post(JOBS, json=HYDROGRAPH_JOB, headers=THROUGH_TUNNEL)
        other = client.post(JOBS, json=HYDROGRAPH_JOB, headers=OTHER_THROUGH_TUNNEL)

        assert first == [202, 202]
        assert third.status_code == 429
        assert third.json()["code"] == "rate_limited"
        assert third.json()["details"]["reason"] == "job_limit"
        assert other.status_code == 202

    def test_health_checks_are_neither_limited_nor_counted(self, traffic, client):
        state = traffic(limit=1)
        app.dependency_overrides[get_db] = lambda: MagicMock()
        try:
            statuses = {client.get("/health").status_code for _ in range(3)}
        finally:
            app.dependency_overrides.clear()

        assert statuses == {200}
        assert state.usage.totals()["visitors"] == 0
        assert client.get("/api/v1/gui", headers=THROUGH_TUNNEL).status_code == 200

    def test_the_admin_panel_stays_under_the_limit(self, traffic, client):
        traffic(limit=1)
        page = client.get("/admin/index.html", headers=THROUGH_TUNNEL)

        response = client.get("/api/v1/admin/status", headers=THROUGH_TUNNEL)

        assert page.status_code == 200
        assert response.status_code == 429
        assert response.json()["code"] == "rate_limited"
        assert response.headers["cache-control"] == "no-store"

    def test_map_tiles_have_a_limit_of_their_own(self, traffic):
        state = traffic(limit=1)
        tile = "/api/tiles/streams/12/2240/1370.pbf"

        assert all(state.check("GET", tile, CLIENT, 0.0) is None for _ in range(10))
        refusal = state.check("GET", tile, CLIENT, 0.0)

        assert refusal is not None
        assert (refusal.reason, refusal.limit.limit) == ("tile_limit", 10)
        assert state.check("GET", "/api/v1/gui", CLIENT, 0.0) is None

    def test_feedback_has_a_stricter_limit_besides(self, traffic):
        state = traffic(limit=300)

        for _ in range(5):
            assert state.check("POST", "/api/v1/feedback", CLIENT, 0.0) is None
        refusal = state.check("POST", "/api/v1/feedback", CLIENT, 1.0)

        assert refusal is not None
        assert (refusal.reason, refusal.wait_s) == ("feedback_limit", 299)
        assert state.check("GET", "/api/v1/gui", CLIENT, 1.0) is None


def test_no_log_holds_the_client_address(traffic, client, log_records, caplog):
    traffic(limit=3)

    with caplog.at_level(logging.DEBUG):
        for path in ("/api/v1/gui", "/index.html", "/api/v1/nothing", "/api/v1/gui"):
            client.get(path, headers={**THROUGH_TUNNEL, "User-Agent": "Firefox/1"})

    records = log_records()
    # The refusal of the limit is logged too: the access log is outermost
    assert [r["status"] for r in records if r["kind"] == "access"] == [
        200,
        200,
        404,
        429,
    ]
    for text in [json.dumps(r) for r in records] + [
        r.getMessage() for r in caplog.records
    ]:
        assert CLIENT not in text
        assert "172.18.0" not in text


class TestTotals:
    def test_pages_downloads_and_visitors_are_counted(
        self, traffic, client, monkeypatch
    ):
        state = traffic(limit=10)
        monkeypatch.setattr(api.endpoints.site, "current_terms", lambda: None)

        assert client.get("/index.html", headers=THROUGH_TUNNEL).status_code == 200
        assert client.head("/index.html", headers=THROUGH_TUNNEL).status_code == 200
        assert client.get("/regulamin.html", headers=THROUGH_TUNNEL).status_code == 404
        assert (
            client.post("/api/v1/downloads", headers=THROUGH_TUNNEL).status_code == 204
        )

        assert state.usage.totals() == {
            "visitors": 1,
            "page_views": 1,
            "stations_opened": 0,
            "analyses_run": 0,
            "downloads": 1,
        }

    def test_the_admin_panel_counts_in_no_total(self, traffic, client):
        state = traffic(limit=10)

        page = client.get("/admin/index.html", headers=THROUGH_TUNNEL)
        refused = client.get("/api/v1/admin/stats", headers=THROUGH_TUNNEL)

        assert (page.status_code, refused.status_code) == (200, 401)
        assert set(state.usage.totals().values()) == {0}

    def test_an_analysis_counts_when_it_succeeds(self, traffic):
        state = traffic()

        state.count("GET", "/api/v1/watershed/delineate", 200)
        state.count("POST", "/api/v1/terrain/profile", 200)
        state.count("POST", "/api/v1/precipitation/depth", 200)
        # A job of the hydrograph or the network counts when it starts
        state.count("POST", "/api/v1/jobs", 202)
        state.count("GET", "/api/v1/watershed/delineate", 400)
        state.count("POST", "/api/v1/jobs", 429)
        state.count("GET", "/api/v1/watershed/preview", 200)

        assert state.usage.totals()["analyses_run"] == 4

    def test_a_new_utc_day_stores_the_finished_one(self, traffic, monkeypatch):
        state = traffic()
        day = datetime.date(2026, 11, 13)
        state.usage = DailyUsage(day)
        state.usage.visit(CLIENT, "Firefox/1")
        next_day = day + datetime.timedelta(days=1)
        monkeypatch.setattr(api.traffic, "utc_today", lambda: next_day)

        state.new_day()

        line = json.loads(state.stats.path.read_text(encoding="utf-8"))
        assert (line["date"], line["visitors"]) == ("2026-11-13", 1)
        assert state.usage.day == next_day

    def test_the_day_is_stored_at_shutdown(self, traffic):
        state = traffic()

        with TestClient(app, client=NGINX) as lifespan_client:
            lifespan_client.get("/api/v1/gui", headers=THROUGH_TUNNEL)

        line = json.loads(state.stats.path.read_text(encoding="utf-8"))
        assert line["date"] == state.usage.day.isoformat()
        assert line["visitors"] == 1
