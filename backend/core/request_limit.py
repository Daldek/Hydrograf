"""Requests per client address in a window of time (Nogat DEV-15.9, ADR-084).

The first request of an address opens its window of ``window_s`` seconds; up to
``limit`` requests fit in it, and every later one is refused until the window ends,
which is the wait the answer names. The address is a key of a dictionary in memory and
stays there for its window only (``forget_expired`` drops the ended windows); it is
never written to disk or a log.
"""

import math
from dataclasses import dataclass


@dataclass
class _Window:
    """The requests of one address since ``start`` (seconds of a monotonic clock)."""

    start: float
    count: int


class RequestLimit:
    """A limit of ``limit`` requests per key in ``window_s`` seconds.

    Parameters
    ----------
    limit : int
        Requests one key may make in a window, at least 1.
    window_s : float
        Length of a window [s], above 0.
    """

    def __init__(self, limit: int, window_s: float) -> None:
        if limit < 1 or window_s <= 0:
            raise ValueError("a limit needs at least one request in a positive window")
        self.limit = limit
        self.window_s = window_s
        self._windows: dict[str, _Window] = {}

    def __len__(self) -> int:
        """Return the number of keys with an open window."""
        return len(self._windows)

    def hit(self, key: str, now: float) -> int | None:
        """Count one request of ``key`` at ``now``.

        Parameters
        ----------
        key : str
            The client address.
        now : float
            Seconds of a monotonic clock.

        Returns
        -------
        int or None
            None when the request is within the limit; otherwise the whole seconds,
            at least 1, until the window of ``key`` ends (``Retry-After``).
        """
        window = self._windows.get(key)
        if window is None or now >= window.start + self.window_s:
            self._windows[key] = _Window(start=now, count=1)
            return None
        window.count += 1
        if window.count <= self.limit:
            return None
        return max(1, math.ceil(window.start + self.window_s - now))

    def forget_expired(self, now: float) -> None:
        """Drop every key whose window has ended by ``now``."""
        self._windows = {
            key: window
            for key, window in self._windows.items()
            if now < window.start + self.window_s
        }
