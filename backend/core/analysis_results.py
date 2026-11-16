"""
Water levels of analysis results along a terrain profile, and their providers' lines.

The analysis results manifest ``<frontend_data_dir>/results/index.json``
(schema ``hydrograf-results/1``, also read by frontend/js/results.js) may give
a result a maximum water level raster::

    "water_level": {"path": "/data/results/<id>/wse_max.tif",
                    "crs": "EPSG:2180", "unit": "m n.p.m."}

``path`` is the address the browser sees (nginx serves ``/data/`` from
``frontend/data``). Here it maps to a file under ``<frontend_data_dir>``, which
must stay inside ``<frontend_data_dir>/results``; anything else is skipped.

A result made with a provider's data, as the SFINCS depths of a PMAXTP rainfall,
carries the lines its producer wrote for it (Nogat DEV §20, ADR-083)::

    "attribution": ["Źródłem pochodzenia danych jest …", …],
    "terms_notice": ["Regulamin danych PMAXTP: https://klimat.imgw.pl/opady-maksymalne"]

and a response with its water carries them on (:func:`provider_lines`).
"""

import json
import logging
import math
from pathlib import Path
from typing import Any

import rasterio
from rasterio.errors import RasterioError
from rasterio.warp import transform

from core.attribution import NO_PROVIDER, ProviderLines, merge

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA = "hydrograf-results/1"
URL_PREFIX = "/data/"
PROFILE_CRS = "EPSG:2180"


def _manifest_entries(frontend_data_dir: str) -> dict[str, dict[str, Any]]:
    """Return the entries of the results manifest by id; none when it is unusable."""
    results_dir = Path(frontend_data_dir).resolve() / "results"
    try:
        manifest = json.loads((results_dir / "index.json").read_text("utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("Analysis results manifest not readable: %s", e)
        return {}
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        logger.warning("Analysis results manifest has an unsupported schema")
        return {}
    results = manifest.get("results")
    return {
        r["id"]: r
        for r in (results if isinstance(results, list) else [])
        if isinstance(r, dict) and isinstance(r.get("id"), str)
    }


def _water_level_rasters(
    frontend_data_dir: str, result_ids: list[str]
) -> list[tuple[str, Path]]:
    """Water level rasters of the requested results, in the order asked for."""
    data_dir = Path(frontend_data_dir).resolve()
    results_dir = (data_dir / "results").resolve()
    entries = _manifest_entries(frontend_data_dir)

    rasters = []
    for result_id in dict.fromkeys(result_ids):
        water_level = entries.get(result_id, {}).get("water_level")
        url = water_level.get("path") if isinstance(water_level, dict) else None
        if not isinstance(url, str) or not url.startswith(URL_PREFIX):
            continue
        path = (data_dir / url[len(URL_PREFIX) :]).resolve()
        if not path.is_relative_to(results_dir) or not path.is_file():
            logger.warning(
                "Water level of result %s skipped: %s is not a file under %s",
                result_id,
                url,
                results_dir,
            )
            continue
        rasters.append((result_id, path))
    return rasters


def _lines(entry: dict[str, Any], key: str) -> tuple[str, ...]:
    """Return the lines of a manifest entry under ``key``; none unless texts."""
    value = entry.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(line, str) and line for line in value
    ):
        logger.warning("Result %s: %s is not a list of texts", entry["id"], key)
        return ()
    return tuple(value)


def provider_lines(frontend_data_dir: str, result_ids: list[str]) -> ProviderLines:
    """Return the providers' lines of analysis results, as their manifest gives them.

    Parameters
    ----------
    frontend_data_dir : str
        Directory served under ``/data/`` (holds ``results/index.json``)
    result_ids : list[str]
        Ids of the manifest results whose data a response carries

    Returns
    -------
    ProviderLines
        Their ``attribution`` and ``terms_notice`` lines, each once in the order of
        the results; none for unknown ids and entries without lines
    """
    if not result_ids:
        return NO_PROVIDER
    entries = _manifest_entries(frontend_data_dir)
    return merge(
        ProviderLines(
            _lines(entries[result_id], "attribution"),
            _lines(entries[result_id], "terms_notice"),
        )
        for result_id in dict.fromkeys(result_ids)
        if result_id in entries
    )


def _sample(path: Path, points: list[tuple[float, float]]) -> list[float | None] | None:
    """Raster values at the points (EPSG:2180); None if no point is on it."""
    with rasterio.open(path) as dataset:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        if dataset.crs is not None and dataset.crs != PROFILE_CRS:
            xs, ys = transform(PROFILE_CRS, dataset.crs, xs, ys)
        left, bottom, right, top = dataset.bounds
        inside = [
            i
            for i, (x, y) in enumerate(zip(xs, ys, strict=True))
            if left <= x < right and bottom < y <= top
        ]
        if not inside:
            return None
        nodata = dataset.nodata
        levels: list[float | None] = [None] * len(points)
        for i, val in zip(
            inside, dataset.sample([(xs[i], ys[i]) for i in inside]), strict=True
        ):
            level = float(val[0])
            if math.isfinite(level) and not (
                nodata is not None and math.isclose(level, nodata, rel_tol=1e-6)
            ):
                levels[i] = level
        return levels


def sample_water_levels(
    frontend_data_dir: str,
    result_ids: list[str],
    points: list[tuple[float, float]],
) -> list[tuple[str, list[float | None]]]:
    """Maximum water level of each requested analysis result at the points.

    Parameters
    ----------
    frontend_data_dir : str
        Directory served under ``/data/`` (holds ``results/index.json``)
    result_ids : list[str]
        Ids of manifest results; unknown ids and results without a
        ``water_level`` raster are skipped
    points : list[tuple[float, float]]
        Profile samples (x, y) in EPSG:2180

    Returns
    -------
    list[tuple[str, list[float | None]]]
        (result id, level [m a.s.l.] per point, None where dry or off the
        raster) for each result whose raster holds at least one point
    """
    if not result_ids:
        return []
    profiles = []
    for result_id, path in _water_level_rasters(frontend_data_dir, result_ids):
        try:
            levels = _sample(path, points)
        except (RasterioError, OSError) as e:
            logger.warning("Water level of result %s not readable: %s", result_id, e)
            continue
        if levels is not None:
            profiles.append((result_id, levels))
    return profiles
