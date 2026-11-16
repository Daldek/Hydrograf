"""GET /api/admin/stats: the days of stats.jsonl and their sums (Nogat DEV-15.13).

The days between `from` and `to`, both included (by default the last 30 up to today),
in date order, the current day as counted so far: what earlier processes stored of it
plus the counts of this one; `totals` sums every key but `visitors`.
"""

import datetime
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies.admin_auth import verify_admin_key
from api.endpoints import admin
from api.errors import install_error_handlers
from api.traffic import Traffic
from core.config import Settings
from core.usage import DailyUsage

TODAY = datetime.date(2026, 11, 14)


@pytest.fixture
def traffic(tmp_path, monkeypatch):
    """The totals of this process, which started counting today."""
    monkeypatch.setattr(admin, "utc_today", lambda: TODAY)
    state = Traffic(Settings(hydrograf_data_dir=str(tmp_path)))
    state.usage = DailyUsage(TODAY)
    return state


@pytest.fixture
def client(traffic):
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(admin.router, prefix="/api/admin")
    app.dependency_overrides[verify_admin_key] = lambda: None
    app.state.traffic = traffic
    return TestClient(app)


def _line(day: datetime.date, visitors: int = 1, page_views: int = 0, **others):
    return {
        "date": day.isoformat(),
        "visitors": visitors,
        "page_views": page_views,
        "stations_opened": others.get("stations_opened", 0),
        "analyses_run": others.get("analyses_run", 0),
        "downloads": others.get("downloads", 0),
    }


def _store(traffic, *lines):
    traffic.stats.path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(line) + "\n" for line in lines)
    traffic.stats.path.write_text(text, encoding="utf-8")


def _days_ago(n: int) -> datetime.date:
    return TODAY - datetime.timedelta(days=n)


def test_by_default_the_last_30_days_up_to_today(client, traffic):
    _store(traffic, _line(_days_ago(30)), _line(_days_ago(29)), _line(_days_ago(1)))

    days = client.get("/api/admin/stats").json()["days"]

    assert [day["date"] for day in days] == [
        _days_ago(29).isoformat(),
        _days_ago(1).isoformat(),
        TODAY.isoformat(),
    ]


def test_the_period_includes_both_days(client, traffic):
    _store(traffic, *(_line(_days_ago(n), visitors=n) for n in range(10, 0, -1)))

    answer = client.get(
        "/api/admin/stats",
        params={"from": _days_ago(7).isoformat(), "to": _days_ago(5).isoformat()},
    ).json()

    assert [day["visitors"] for day in answer["days"]] == [7, 6, 5]


def test_today_adds_this_process_to_what_earlier_ones_stored(client, traffic):
    _store(traffic, _line(TODAY, visitors=2, page_views=5, downloads=1))
    traffic.usage.visit("203.0.113.7", "Firefox/1")
    traffic.usage.add("page_views")

    before = client.get("/api/admin/stats").json()["days"][-1]
    traffic.store()
    traffic.usage.add("page_views")
    after = client.get("/api/admin/stats").json()["days"][-1]

    assert before == _line(TODAY, visitors=3, page_views=6, downloads=1)
    assert after == _line(TODAY, visitors=3, page_views=7, downloads=1)


def test_the_totals_sum_every_key_but_visitors(client, traffic):
    _store(
        traffic,
        _line(_days_ago(2), visitors=4, page_views=10, analyses_run=3, downloads=1),
        _line(_days_ago(1), visitors=6, page_views=5, analyses_run=2),
    )

    totals = client.get("/api/admin/stats").json()["totals"]

    assert totals == {
        "page_views": 15,
        "stations_opened": 0,
        "analyses_run": 5,
        "downloads": 1,
    }


def test_the_whole_record_without_a_file(client, traffic):
    answer = client.get("/api/admin/stats", params={"from": "1970-01-01"}).json()

    assert answer["days"] == [_line(TODAY, visitors=0)]


def test_a_period_that_ends_before_it_begins_is_refused(client):
    response = client.get(
        "/api/admin/stats", params={"from": "2026-11-10", "to": "2026-11-01"}
    )

    assert response.status_code == 400
    assert response.json()["details"]["reason"] == "stats_period_reversed"
