"""Where Hydrograf keeps what Kartograf downloads, and how it reads its answers.

ADR-061. Kartograf writes either into a versioned store (``root``) or, for a file that
is used once, as plain files (``output_dir``). The cache of raw downloads of Hydrograf
(``paths.cache_dir``: NMT sheets, BDOT10k packages, the HSG raster of Poland) is a store
of its own, ``<cache_dir>/kartograf``: Kartograf refuses a root that holds other files,
so the store has a directory to itself. The SQLite metadata cache of Kartograf stays
beside it, in ``<cache_dir>``: the store would refuse a foreign file, and SQLite needs a
local disk. Every script passes the root and the cache explicitly; none relies on
``KARTOGRAF_ROOT`` or on the default store in the data directory of the user.

ADR-066, ADR-067. ``HYDROGRAF_KARTOGRAF_ROOT`` names a store outside the cache directory
that Archiwista alone writes; Hydrograf only reads it, through a set of an Archiwista
project (``utils.archiwista_project``). While it is set, every download into a store
is refused (:func:`refuse_shared_store`): a write goes only into the private store of
the cache directory (:func:`private_store_dir`). The metadata cache stays in
``<cache_dir>``, and the cache clean leaves a shared store whole.

This module only builds paths and reads reports, so a script that imports it for a path
does not import Kartograf.
"""

import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from core.errors import ForbiddenError, HydrografError

if TYPE_CHECKING:
    from kartograf import BBox, MetadataCache

logger = logging.getLogger(__name__)

# <cache_dir>/kartograf: the private Kartograf store of the pipeline.
STORE_DIR_NAME = "kartograf"
# A Kartograf store shared with Archiwista, read only (ADR-066, ADR-067). Not
# Kartograf's own KARTOGRAF_ROOT: a root set for the Kartograf command line must not
# redirect the pipeline.
STORE_ROOT_ENV = "HYDROGRAF_KARTOGRAF_ROOT"
# <cache_dir>/kartograf_meta.db (+ -wal, -shm): the SQLite metadata cache of Kartograf.
METADATA_CACHE_NAME = "kartograf_meta.db"
# The sheet grid of Hydrograf: PL-1992 (EPSG:2180), the one GUGiK publishes the NMT in.
SHEET_SYSTEM = "1992"


@dataclass(frozen=True)
class HsgLayers:
    """The SoilGrids layers of the hydrologic soil groups (HSG) of one rule.

    A rule is a value of ``soil.hsg_depth_rule`` in the configuration (ADR-079).
    Kartograf's ``calculate_hsg`` takes exactly one of ``depth`` (one layer) and
    ``depth_rule`` (a rule over the soil profile), so the other is None; ``segment``
    is the store segment of the raster that Kartograf computes from the layers.
    """

    depth: str | None
    depth_rule: str | None
    segment: str

    def command(self, box: tuple[float, float, float, float]) -> str:
        """Return the Kartograf command that computes this raster over ``box``.

        ``box`` is in EPSG:2180, the default CRS of ``--bbox``; it is rounded outwards
        to whole metres, so the box that the raster records as requested covers it.
        """
        layers = (
            f"--depth-rule {self.depth_rule}"
            if self.depth_rule is not None
            else f"--depth {self.depth}"
        )
        min_x, min_y, max_x, max_y = box
        corners = (
            math.floor(min_x),
            math.floor(min_y),
            math.ceil(max_x),
            math.ceil(max_y),
        )
        return f"kartograf soil hsg {layers} --bbox {','.join(map(str, corners))}"


# The rules of soil.hsg_depth_rule (ADR-079). "least-permeable", the default: per cell
# the group of the least permeable SoilGrids layer of 0-100 cm (Kartograf's ADR-061;
# NEH 630 ch. 7 takes the layer that limits the infiltration). "topsoil": the group of
# the 0-5 cm layer, the rule of Hydrograf before ADR-079.
HSG_DEPTH_RULES: Final[dict[str, HsgLayers]] = {
    "least-permeable": HsgLayers(
        depth=None,
        depth_rule="least-permeable",
        segment="hsg/global_soilgrids_0-100cm_least-permeable_mean",
    ),
    "topsoil": HsgLayers(
        depth="0-5cm", depth_rule=None, segment="hsg/global_soilgrids_0-5cm_mean"
    ),
}
DEFAULT_HSG_DEPTH_RULE: Final = "least-permeable"


def shared_store_root() -> Path | None:
    """Return the shared store that ``HYDROGRAF_KARTOGRAF_ROOT`` names, if any.

    Returns
    -------
    Path or None
        The root of a Kartograf store that Archiwista writes and Hydrograf only reads
        (ADR-067); None when the variable is unset or empty, that is for the private
        store of the cache directory.
    """
    value = os.environ.get(STORE_ROOT_ENV, "").strip()
    return Path(value).expanduser() if value else None


def store_dir(cache_dir: Path) -> Path:
    """Return the Kartograf store that the pipeline reads.

    The shared store of ``HYDROGRAF_KARTOGRAF_ROOT`` when it is set (ADR-066), else
    the private store inside the cache directory, ``<cache_dir>/kartograf`` (ADR-061).
    A download writes only into the private store: :func:`private_store_dir`.
    """
    return shared_store_root() or cache_dir / STORE_DIR_NAME


def refuse_shared_store() -> None:
    """Refuse a download while ``HYDROGRAF_KARTOGRAF_ROOT`` names a shared store.

    Archiwista alone writes the shared store (ADR-067), so every function of
    Hydrograf that may write into a Kartograf store calls this first.

    Raises
    ------
    ForbiddenError
        ``shared_store_read_only``: the variable is set.
    """
    root = shared_store_root()
    if root is not None:
        raise ForbiddenError(
            "shared_store_read_only", reason="shared_store_read_only", root=str(root)
        )


def private_store_dir(cache_dir: Path) -> Path:
    """Return the store a download writes into: ``<cache_dir>/kartograf`` (ADR-061).

    Raises
    ------
    ForbiddenError
        ``shared_store_read_only`` while ``HYDROGRAF_KARTOGRAF_ROOT`` is set
        (:func:`refuse_shared_store`).
    """
    refuse_shared_store()
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

    An error of Kartograf or of Hydrograf says its code of the Nogat registry and,
    when it has one, the hint that names the way out (for example ``kartograf store
    init --root DIR`` for a root that has the layout of a store and no marker); any
    other error is its text.
    """
    from kartograf import KartografError

    if not isinstance(error, KartografError | HydrografError):
        return str(error)
    text = f"{error} [{error.code}]"
    return f"{text} {error.hint}" if error.hint else text


def download_bdot10k(
    cache_dir: Path,
    *,
    teryt: str | None = None,
    bbox: "BBox | None" = None,
) -> dict[str, Path]:
    """Download BDOT10k into the private store of ``cache_dir``; return the packages.

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
    ForbiddenError
        ``shared_store_read_only`` while ``HYDROGRAF_KARTOGRAF_ROOT`` is set.
    kartograf.KartografError
        A request that Kartograf refuses (``validation_error``), a store that
        refuses the write (``conflict``, ``store_unavailable``) or a failed query of
        the county register (``source_unavailable``).
    """
    from kartograf import NoCoverageError, download_landcover

    root = private_store_dir(cache_dir)
    try:
        report = download_landcover(
            product="bdot10k",
            root=root,
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
