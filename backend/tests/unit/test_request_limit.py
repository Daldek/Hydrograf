"""
Requests per client address in a window (core/request_limit.py; Nogat DEV-15.9).

The first request of an address opens its window; `limit` requests fit in it, the next
ones are refused with the whole seconds left, and the address is forgotten when its
window has ended.
"""

import pytest

from core.request_limit import RequestLimit


def test_the_limit_fits_in_a_window_and_the_next_request_waits_for_its_end():
    limit = RequestLimit(3, 60)

    assert [limit.hit("a", t) for t in (100.0, 110.0, 120.0)] == [None, None, None]
    assert limit.hit("a", 130.2) == 30
    assert limit.hit("a", 159.5) == 1


def test_a_new_window_opens_when_the_last_has_ended():
    limit = RequestLimit(1, 60)
    limit.hit("a", 100.0)

    assert limit.hit("a", 159.9) == 1
    assert limit.hit("a", 160.0) is None
    assert limit.hit("a", 161.0) == 59


def test_addresses_are_counted_apart():
    limit = RequestLimit(1, 60)
    limit.hit("a", 100.0)

    assert limit.hit("b", 100.0) is None
    assert limit.hit("a", 100.0) == 60


def test_ended_windows_are_forgotten_and_open_ones_kept():
    limit = RequestLimit(5, 60)
    limit.hit("old", 100.0)
    limit.hit("new", 130.0)

    limit.forget_expired(160.0)

    assert len(limit) == 1
    limit.forget_expired(190.0)
    assert len(limit) == 0


@pytest.mark.parametrize(("requests", "window_s"), [(0, 60), (1, 0)])
def test_a_limit_needs_a_request_and_a_window(requests, window_s):
    with pytest.raises(ValueError):
        RequestLimit(requests, window_s)
