"""Daily totals of the use of Hydrograf (Nogat DEV-15.11, ADR-084).

Hydrograf counts its use in totals per UTC day only. For each request the limit of
``core.request_limit`` counts, a visitor is the HMAC-SHA-256 of the client address and
the User-Agent under a 32-byte random salt drawn at start and at each 00:00 UTC; the
salt and the hashes stay in this process's memory to count the day's distinct visitors
and are never written. Each UTC day is one JSON object per line of
``<data_dir>/hydrograf/stats.jsonl``, in date order, with the keys of ``TOTALS`` after
``date``; ``api.traffic`` rewrites the day's line every 10 minutes, at 00:00 UTC and at
shutdown. What each total counts is in the README ("Statistics").
"""

import datetime
import hashlib
import hmac
import json
import logging
import os
import secrets
from collections.abc import Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# The totals of a line of stats.jsonl after its `date`, in this order
TOTALS = ("visitors", "page_views", "stations_opened", "analyses_run", "downloads")


def utc_today() -> datetime.date:
    """Return the current UTC day."""
    return datetime.datetime.now(datetime.UTC).date()


class DailyUsage:
    """The totals of one UTC day in this process, held in memory.

    Parameters
    ----------
    day : datetime.date
        The UTC day the counting starts in; a salt is drawn for it.
    """

    def __init__(self, day: datetime.date) -> None:
        self._start(day)

    def _start(self, day: datetime.date) -> None:
        self.day = day
        self._salt = secrets.token_bytes(32)
        self._visitors: set[bytes] = set()
        self._counts = dict.fromkeys(TOTALS[1:], 0)

    def visit(self, address: str, user_agent: str) -> None:
        """Count the visitor of a request: the client address and the User-Agent."""
        digest = hmac.new(
            self._salt, f"{address}\n{user_agent}".encode(), hashlib.sha256
        ).digest()
        self._visitors.add(digest)

    def add(self, total: str) -> None:
        """Add one to ``total``, a key of ``TOTALS`` other than ``visitors``."""
        self._counts[total] += 1

    def totals(self) -> dict[str, int]:
        """Return the day's totals in this process, in the order of ``TOTALS``."""
        return {"visitors": len(self._visitors), **self._counts}

    def roll(self, today: datetime.date) -> tuple[datetime.date, dict[str, int]] | None:
        """Start the UTC day ``today`` when it is not the current one.

        The new day has a new salt, no visitors and zero totals.

        Returns
        -------
        tuple of (datetime.date, dict) or None
            The finished day and its totals, to be stored; None on the same day.
        """
        if today == self.day:
            return None
        finished = (self.day, self.totals())
        self._start(today)
        return finished


class StatsFile:
    """The file ``stats.jsonl``: one JSON object per UTC day and line, in date order.

    A process adds its totals of a day to those an earlier process stored for that day
    (after a restart, with a new salt, a visitor of both counts twice): the first
    write of a day takes the day's line as it finds it, and every write replaces that
    line and writes the file anew through a temporary file.

    Parameters
    ----------
    path : Path
        ``<data_dir>/hydrograf/stats.jsonl``; its directory is made when missing.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._earlier: dict[datetime.date, dict[str, int]] = {}

    def write(self, day: datetime.date, totals: Mapping[str, int]) -> None:
        """Store this process's ``totals`` of ``day``.

        Raises
        ------
        OSError
            When the file cannot be read or written.
        """
        lines = self._read()
        if day not in self._earlier:
            self._earlier[day] = _totals_of(lines.get(day.isoformat(), {}))
        earlier = self._earlier[day]
        lines[day.isoformat()] = {
            "date": day.isoformat(),
            **{name: earlier[name] + totals[name] for name in TOTALS},
        }
        # Only the day before may still be written (its last line at 00:00 UTC)
        self._earlier = {
            known: value
            for known, value in self._earlier.items()
            if known >= day - datetime.timedelta(days=1)
        }
        self._replace(lines)

    def _read(self) -> dict[str, dict[str, Any]]:
        """Return the lines of the file by date; none when it does not exist."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        lines: dict[str, dict[str, Any]] = {}
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                entry = None
            if not (isinstance(entry, dict) and isinstance(entry.get("date"), str)):
                logger.warning(
                    "%s: line %d is no day of totals, dropped", self.path, number
                )
                continue
            lines[entry["date"]] = entry
        return lines

    def _replace(self, lines: Mapping[str, Mapping[str, Any]]) -> None:
        """Write ``lines`` in date order through a temporary file beside the file."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        text = "".join(json.dumps(lines[day]) + "\n" for day in sorted(lines))
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, self.path)


def _totals_of(line: Mapping[str, Any]) -> dict[str, int]:
    """Return the totals of a stored line; a missing or invalid one counts as 0."""
    totals: dict[str, int] = {}
    for name in TOTALS:
        value = line.get(name, 0)
        totals[name] = value if isinstance(value, int) and value >= 0 else 0
    return totals
