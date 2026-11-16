"""
The provider products the data of the instance were made from, and when.

GUGiK's conditions of reuse ask a product of its data for the time the data were
created and the time they were acquired (Nogat DEV §20, line G); both come from the
Kartograf metadata of the files the pipeline used. The pipeline writes them into
``<frontend_data_dir>/instance.json`` (``scripts/write_instance_info.py``, the end of a
bootstrap) as the member ``sources``, one entry per product::

    "sources": {
      "NMT": {"created": [2020, 2025], "acquired": ["2026-10-29"]},
      "BDOT10k": {"created": [2026], "acquired": ["2026-03-24", "2026-10-29"]},
      "SoilGrids": {"created": [], "acquired": ["2026-11-10"]}
    }

``created`` holds the years in which the data of the files were created, ``acquired``
the days (UTC) on which they were downloaded; a value no metadata gives is left out.
The API reads the member again when the file changes (:func:`read_data_sources`), so a
rewrite of ``instance.json`` needs no restart.
"""

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)

# The file of the instance's description in the directory nginx serves as /data
INSTANCE_FILE: Final = "instance.json"

# The products of the data, by the names the source lines use
NMT: Final = "NMT"
BDOT10K: Final = "BDOT10k"
SOILGRIDS: Final = "SoilGrids"
PRODUCTS: Final = (NMT, BDOT10K, SOILGRIDS)

_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class ProductDates:
    """When the files of one product were created and downloaded.

    Attributes
    ----------
    created : frozenset[int]
        The years in which the data of the files were created.
    acquired : frozenset[str]
        The days (``YYYY-MM-DD``, UTC) on which the files were downloaded.
    """

    created: frozenset[int] = frozenset()
    acquired: frozenset[str] = frozenset()


def sources_member(dates: Mapping[str, ProductDates]) -> dict[str, dict[str, Any]]:
    """Return the member ``sources`` of ``instance.json`` for the products' dates.

    Parameters
    ----------
    dates : Mapping[str, ProductDates]
        The dates of each product the data were made from, by a name of ``PRODUCTS``.

    Returns
    -------
    dict[str, dict[str, Any]]
        One entry per product, in the order of ``PRODUCTS``, with the sorted years
        and days.
    """
    return {
        product: {
            "created": sorted(dates[product].created),
            "acquired": sorted(dates[product].acquired),
        }
        for product in PRODUCTS
        if product in dates
    }


def parse_sources(member: object) -> dict[str, ProductDates] | None:
    """Return the dates of the products of a member ``sources``, None if unusable.

    A product with an unknown name, or whose years or days are not lists of years
    and ``YYYY-MM-DD`` days, is left out with a warning.
    """
    if not isinstance(member, dict):
        return None
    dates: dict[str, ProductDates] = {}
    for product, entry in member.items():
        if product not in PRODUCTS or not isinstance(entry, dict):
            logger.warning("instance.json: source %r is not a product entry", product)
            continue
        created = entry.get("created", [])
        acquired = entry.get("acquired", [])
        if not (
            isinstance(created, list)
            and all(isinstance(y, int) and not isinstance(y, bool) for y in created)
            and isinstance(acquired, list)
            and all(isinstance(d, str) and _DAY.fullmatch(d) for d in acquired)
        ):
            logger.warning("instance.json: the dates of %s are malformed", product)
            continue
        dates[product] = ProductDates(frozenset(created), frozenset(acquired))
    return dates


@lru_cache(maxsize=4)
def _read(path: Path, stamp: int | None) -> dict[str, ProductDates] | None:
    """Parse the member ``sources`` of the file as it is at ``stamp`` (its mtime)."""
    if stamp is None:
        logger.warning(
            "No %s: the source lines of GUGiK data lack their dates; write it with "
            "scripts.write_instance_info",
            path,
        )
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        logger.warning("%s cannot be read: %s", path, error)
        return None
    member = document.get("sources") if isinstance(document, dict) else None
    if member is None:
        logger.warning(
            "%s names no sources: the source lines of GUGiK data lack their dates; "
            "write them with scripts.write_instance_info",
            path,
        )
        return None
    dates = parse_sources(member)
    if dates is None:
        logger.warning("%s: sources is not an object", path)
    return dates


def read_data_sources(frontend_data_dir: str) -> dict[str, ProductDates] | None:
    """Return the products of the instance's data with their dates.

    Parameters
    ----------
    frontend_data_dir : str
        The directory served under ``/data/``, which holds ``instance.json``.

    Returns
    -------
    dict[str, ProductDates] or None
        The dates of each product the data were made from; None when the file or its
        member ``sources`` is missing or unusable (logged once per state of the file).
    """
    path = Path(frontend_data_dir) / INSTANCE_FILE
    try:
        stamp: int | None = path.stat().st_mtime_ns
    except OSError:
        stamp = None
    return _read(path, stamp)
