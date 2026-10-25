"""Where Hydrograf keeps what Kartograf downloads, and how it reads its answers.

ADR-061. Kartograf writes either into a versioned store (``root``) or, for a file that
is used once, as plain files (``output_dir``). The cache of raw downloads of Hydrograf
(``paths.cache_dir``: NMT sheets, BDOT10k packages, the HSG raster of Poland) is a store
of its own, ``<cache_dir>/kartograf``: Kartograf refuses a root that holds other files,
so the store has a directory to itself. The SQLite metadata cache of Kartograf stays
beside it, in ``<cache_dir>``: the store would refuse a foreign file, and SQLite needs a
local disk. Every script passes the root and the cache explicitly; none relies on
``KARTOGRAF_ROOT`` or on the default store in the data directory of the user.

This module only builds paths and reads reports, so a script that imports it for a path
does not import Kartograf.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kartograf import BBox, MetadataCache

logger = logging.getLogger(__name__)

# <cache_dir>/kartograf: the Kartograf store of the pipeline.
STORE_DIR_NAME = "kartograf"
# <cache_dir>/kartograf_meta.db (+ -wal, -shm): the SQLite metadata cache of Kartograf.
METADATA_CACHE_NAME = "kartograf_meta.db"
# The sheet grid of Hydrograf: PL-1992 (EPSG:2180), the one GUGiK publishes the NMT in.
SHEET_SYSTEM = "1992"
# Depth of the SoilGrids layers of the hydrologic soil groups (HSG) of Hydrograf.
HSG_DEPTH = "0-5cm"


def store_dir(cache_dir: Path) -> Path:
    """Return the Kartograf store inside the cache directory of the pipeline."""
    return cache_dir / STORE_DIR_NAME


def metadata_cache_path(cache_dir: Path) -> Path:
    """Return the SQLite file of the Kartograf metadata cache of the pipeline."""
    return cache_dir / METADATA_CACHE_NAME


def open_metadata_cache(cache_dir: Path) -> "MetadataCache":
    """Open the Kartograf metadata cache of ``cache_dir`` (the directory is created)."""
    from kartograf import MetadataCache

    cache_dir.mkdir(parents=True, exist_ok=True)
    return MetadataCache(
        metadata_cache_path(cache_dir),
        on_disabled=lambda reason: logger.warning(
            "Kartograf metadata cache disabled: %s", reason
        ),
    )


def describe_error(error: BaseException) -> str:
    """Return the text of a failure for a log line or the detail of a step.

    An error of Kartograf says its code of the Nogat registry and, when it has one,
    the hint that names the way out (for example ``kartograf store init --root DIR``
    for a root that has the layout of a store and no marker); any other error is its
    text.
    """
    from kartograf import KartografError

    if not isinstance(error, KartografError):
        return str(error)
    text = f"{error} [{error.code}]"
    return f"{text} {error.hint}" if error.hint else text


def download_bdot10k(
    cache_dir: Path,
    *,
    teryt: str | None = None,
    bbox: "BBox | None" = None,
) -> dict[str, Path]:
    """Download BDOT10k into the store of ``cache_dir`` and return the package paths.

    The data of one county (``teryt``, 4 digits) or of every county that an area
    (``bbox``) intersects: the whole package of a county, all layers, as a GeoPackage
    at the standard path of the store. A version that is already local is used without
    a request. A county that failed does not stop the others: it is logged and missing
    from the result. An area that intersects no county gives an empty result.

    Parameters
    ----------
    cache_dir : Path
        Cache directory of the pipeline; the store is ``<cache_dir>/kartograf``.
    teryt : str, optional
        TERYT code of a county (powiat), 4 digits.
    bbox : BBox, optional
        Area, in any CRS Kartograf supports (the pipeline gives EPSG:2180).

    Returns
    -------
    dict[str, Path]
        County code to the GeoPackage of the county.

    Raises
    ------
    kartograf.KartografError
        A request that Kartograf refuses (``validation_error``), a store that
        refuses the write (``conflict``, ``store_unavailable``) or a failed query of
        the county register (``source_unavailable``).
    """
    from kartograf import NoCoverageError, download_landcover

    try:
        report = download_landcover(
            product="bdot10k",
            root=store_dir(cache_dir),
            teryt=teryt,
            bbox=bbox,
            cache=open_metadata_cache(cache_dir),
        )
    except NoCoverageError as error:
        logger.warning("BDOT10k: %s", describe_error(error))
        return {}
    for failure in report.failed:
        logger.warning("BDOT10k, county %s: %s", failure.unit, failure.error)
    return {item.unit: item.file.path for item in report.files}
