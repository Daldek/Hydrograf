"""
Daily totals of use (core/usage.py; Nogat DEV-15.11).

A visitor is one address and User-Agent of a day, counted again on the next day; the
file holds one line per UTC day in date order, and a restart adds to the day's line.
"""

import datetime
import json

from core.usage import TOTALS, DailyUsage, StatsFile

DAY = datetime.date(2026, 11, 13)
NEXT = datetime.date(2026, 11, 14)


def _totals(**counts: int) -> dict[str, int]:
    return {name: counts.get(name, 0) for name in TOTALS}


def _lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class TestDailyUsage:
    def test_a_visitor_is_one_address_and_browser_of_the_day(self):
        usage = DailyUsage(DAY)

        usage.visit("203.0.113.7", "Firefox")
        usage.visit("203.0.113.7", "Firefox")
        usage.visit("203.0.113.7", "Chrome")
        usage.visit("198.51.100.4", "Firefox")
        usage.add("page_views")
        usage.add("analyses_run")
        usage.add("analyses_run")

        assert usage.totals() == _totals(visitors=3, page_views=1, analyses_run=2)

    def test_the_same_day_does_not_roll(self):
        usage = DailyUsage(DAY)
        usage.visit("203.0.113.7", "Firefox")

        assert usage.roll(DAY) is None
        assert usage.totals()["visitors"] == 1

    def test_a_new_day_returns_the_finished_one_and_starts_from_zero(self):
        usage = DailyUsage(DAY)
        usage.visit("203.0.113.7", "Firefox")
        usage.add("downloads")

        finished = usage.roll(NEXT)

        assert finished == (DAY, _totals(visitors=1, downloads=1))
        assert usage.day == NEXT
        assert usage.totals() == _totals()
        usage.visit("203.0.113.7", "Firefox")
        assert usage.totals()["visitors"] == 1


class TestStatsFile:
    def test_one_line_per_day_in_date_order(self, tmp_path):
        stats = StatsFile(tmp_path / "hydrograf" / "stats.jsonl")

        stats.write(NEXT, _totals(visitors=2))
        stats.write(DAY, _totals(visitors=1))
        stats.write(NEXT, _totals(visitors=5, page_views=7))

        assert _lines(stats.path) == [
            {"date": "2026-11-13", **_totals(visitors=1)},
            {"date": "2026-11-14", **_totals(visitors=5, page_views=7)},
        ]

    def test_a_restart_adds_to_the_stored_day(self, tmp_path):
        path = tmp_path / "stats.jsonl"
        StatsFile(path).write(DAY, _totals(visitors=4, analyses_run=3))

        after_restart = StatsFile(path)
        after_restart.write(DAY, _totals(visitors=1))
        after_restart.write(DAY, _totals(visitors=2, analyses_run=1))

        assert _lines(path) == [
            {"date": "2026-11-13", **_totals(visitors=6, analyses_run=4)}
        ]

    def test_the_last_line_of_a_day_after_the_next_day_began_is_not_counted_twice(
        self, tmp_path
    ):
        path = tmp_path / "stats.jsonl"
        StatsFile(path).write(DAY, _totals(visitors=10))
        stats = StatsFile(path)

        stats.write(DAY, _totals(visitors=1))
        stats.write(NEXT, _totals(visitors=1))
        stats.write(DAY, _totals(visitors=3))

        assert _lines(path)[0] == {"date": "2026-11-13", **_totals(visitors=13)}
