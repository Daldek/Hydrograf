"""
The request limit and the daily totals of every request (api/traffic.py; ADR-084).

Nogat DEV-15.9 to DEV-15.11: pages and API routes are limited per client address, the
address being the one Cloudflare reports only when it comes through the private hops
of the tunnel and nginx; over the limit a page answers a Polish page and a route the
problem `rate_limited`, both with `Retry-After`; no log holds the address; the day's
totals count visitors, pages, analyses and downloads and are stored at shutdown.
"""

import datetime
import json
import logging
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import api.endpoints.site
import api.traffic
from api.main import app
from api.traffic import Traffic, client_address
from core.config import Settings
from core.database import get_db
from core.usage import DailyUsage

# The hops of a request through the tunnel: nginx's container calls the API, nginx's
# peer is the tunnel's connector seen from the Docker network, the client is the
# address Cloudflare reports
NGINX = ("172.18.0.3", 50000)
CLIENT = "203.0.113.77"
THROUGH_TUNNEL = {"X-Real-IP": "172.18.0.1", "CF-Connecting-IP": CLIENT}


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


def _request(peer: str, headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/gui",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 50000),
    }
    return Request(scope)


class TestClientAddress:
    def test_cloudflare_reports_the_client_through_the_private_hops(self):
        assert client_address(_request("172.18.0.3", THROUGH_TUNNEL)) == CLIENT

    def test_a_public_peer_of_nginx_is_the_client_itself(self):
        headers = {"X-Real-IP": "198.51.100.4", "CF-Connecting-IP": CLIENT}

        assert client_address(_request("172.18.0.3", headers)) == "198.51.100.4"

    def test_a_public_peer_of_the_api_is_the_client_itself(self):
        assert (
            client_address(_request("198.51.100.9", THROUGH_TUNNEL)) == "198.51.100.9"
        )

    def test_a_request_from_the_host_without_cloudflare_is_its_hop(self):
        headers = {"X-Real-IP": "172.18.0.1"}

        assert client_address(_request("172.18.0.3", headers)) == "172.18.0.1"

    @pytest.mark.parametrize("value", ["", "unknown", "203.0.113.77, 10.0.0.1"])
    def test_a_header_that_is_no_address_is_not_believed(self, value):
        headers = {"X-Real-IP": "172.18.0.1", "CF-Connecting-IP": value}

        assert client_address(_request("172.18.0.3", headers)) == "172.18.0.1"

    def test_an_ipv4_mapped_address_is_the_ipv4_address(self):
        headers = {"X-Real-IP": "::ffff:172.18.0.1", "CF-Connecting-IP": CLIENT}

        assert client_address(_request("::1", headers)) == CLIENT


class TestRequestLimit:
    def test_over_the_limit_a_route_answers_the_problem_rate_limited(
        self, traffic, client
    ):
        traffic(limit=2)
        headers = {**THROUGH_TUNNEL, "Accept-Language": "pl"}
        first = [client.get("/api/gui", headers=headers).status_code for _ in "ab"]

        response = client.get("/api/gui", headers=headers)

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

    def test_the_limit_is_per_client_address(self, traffic, client):
        traffic(limit=1)
        other = {**THROUGH_TUNNEL, "CF-Connecting-IP": "198.51.100.4"}
        client.get("/api/gui", headers=THROUGH_TUNNEL)

        assert client.get("/api/gui", headers=other).status_code == 200
        assert client.get("/api/gui", headers=THROUGH_TUNNEL).status_code == 429

    def test_health_checks_are_neither_limited_nor_counted(self, traffic, client):
        state = traffic(limit=1)
        app.dependency_overrides[get_db] = lambda: MagicMock()
        try:
            statuses = {client.get("/health").status_code for _ in range(3)}
        finally:
            app.dependency_overrides.clear()

        assert statuses == {200}
        assert state.usage.totals()["visitors"] == 0
        assert client.get("/api/gui", headers=THROUGH_TUNNEL).status_code == 200

    def test_the_admin_panel_stays_under_the_limit(self, traffic, client):
        traffic(limit=1)
        page = client.get("/admin/index.html", headers=THROUGH_TUNNEL)

        response = client.get("/api/admin/status", headers=THROUGH_TUNNEL)

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
        assert state.check("GET", "/api/gui", CLIENT, 0.0) is None

    def test_feedback_has_a_stricter_limit_besides(self, traffic):
        state = traffic(limit=300)

        for _ in range(5):
            assert state.check("POST", "/api/feedback", CLIENT, 0.0) is None
        refusal = state.check("POST", "/api/feedback", CLIENT, 1.0)

        assert refusal is not None
        assert (refusal.reason, refusal.wait_s) == ("feedback_limit", 299)
        assert state.check("GET", "/api/gui", CLIENT, 1.0) is None


def test_no_log_holds_the_client_address(traffic, client, log_records, caplog):
    traffic(limit=3)

    with caplog.at_level(logging.DEBUG):
        for path in ("/api/gui", "/index.html", "/api/no-such-route", "/api/gui"):
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
        assert client.post("/api/downloads", headers=THROUGH_TUNNEL).status_code == 204

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
        refused = client.get("/api/admin/stats", headers=THROUGH_TUNNEL)

        assert (page.status_code, refused.status_code) == (200, 401)
        assert set(state.usage.totals().values()) == {0}

    def test_an_analysis_counts_when_it_succeeds(self, traffic):
        state = traffic()

        state.count("POST", "/api/generate-hydrograph", 200)
        state.count("POST", "/api/delineate-watershed", 400)
        state.count("POST", "/api/delineate-watershed/preview", 200)

        assert state.usage.totals()["analyses_run"] == 1

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
            lifespan_client.get("/api/gui", headers=THROUGH_TUNNEL)

        line = json.loads(state.stats.path.read_text(encoding="utf-8"))
        assert line["date"] == state.usage.day.isoformat()
        assert line["visitors"] == 1
