"""
Backfill the flow path heads, overland segments and stream heads of stream_catchments.

Fills flow_path_head_elev_m, overland_length_m, overland_drop_m and
stream_head_elev_m (migration 004) of the sub-catchments already in the database,
from the rasters that their run of process_dem saved with save_intermediates
(``<stem>_02_filled.tif``, ``_03_flowdir``, ``_04_flowacc``, ``_04b_stream_distance``
and the label raster ``<stem>_10_subcatchments_<threshold>.tif`` of each threshold),
without running the pipeline again. The values are the ones the pipeline computes
(process_dem._enrich_catchments_with_flow_paths). The head of a sub-catchment's
longest flow path is the first vertex of its longest_flow_path_geom; a row whose
head does not lie in its own label or whose flow distance there differs from
max_flow_dist_m means that the rasters are not those of the data, and the run
stops before it writes anything. Idempotent.

Usage
-----
    cd backend
    python -m scripts.backfill_flow_path_heads --input /data/nmt/dem_mosaic.tif
    python -m scripts.backfill_flow_path_heads --input ... --thresholds 10000 --dry-run
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import text

from core.database import get_db_session
from core.db_bulk import override_statement_timeout
from core.raster_io import read_raster
from scripts.process_dem import (
    _get_transform,
    _overland_segments,
    _per_label_argmax,
    _stream_head_cells,
    d8_from_saved_flowdir,
    load_hydrology_intermediates,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Agreement of the saved flow distance (float32) with max_flow_dist_m [m]
FLOW_DIST_TOLERANCE_M = 0.05

_UPDATE = text(
    "UPDATE stream_catchments SET flow_path_head_elev_m = :head, "
    "overland_length_m = :length, overland_drop_m = :drop, "
    "stream_head_elev_m = :stream WHERE id = :id"
)


def head_cells(rows: list[Any], metadata: dict[str, Any]) -> np.ndarray:
    """Return the flat index of the head of each row's longest flow path.

    The head is the cell under the first vertex of longest_flow_path_geom
    (``x``, ``y``); -1 for a row without that geometry or off the grid.

    Parameters
    ----------
    rows : list
        Rows with ``x`` and ``y``.
    metadata : dict
        Grid metadata (transform, nrows, ncols).

    Returns
    -------
    np.ndarray
        Flat indices, one per row.
    """
    nrows, ncols = metadata["nrows"], metadata["ncols"]
    inverse = ~_get_transform(metadata, (nrows, ncols))
    heads = np.full(len(rows), -1, dtype=np.intp)
    for i, row in enumerate(rows):
        if row.x is None or row.y is None:
            continue
        col_f, row_f = inverse * (row.x, row.y)
        r, c = int(np.floor(row_f)), int(np.floor(col_f))
        if 0 <= r < nrows and 0 <= c < ncols:
            heads[i] = r * ncols + c
    return heads


def farthest_cells(
    labels: list[int],
    flat_labels: np.ndarray,
    flat_dist: np.ndarray,
) -> dict[int, int]:
    """Return the farthest cell (largest flow distance) of each of ``labels``."""
    if not labels:
        return {}
    cells = np.flatnonzero(np.isin(flat_labels, labels))
    if cells.size == 0:
        return {}
    max_label = int(max(labels))
    _, best = _per_label_argmax(
        flat_labels[cells], flat_dist[cells].astype(np.float64), cells, max_label
    )
    return {label: int(best[label]) for label in labels if best[label] >= 0}


def backfill_threshold(
    db: Any,
    threshold_m2: int,
    label_path: Path,
    rasters: dict[str, np.ndarray],
    metadata: dict[str, Any],
    flw: Any,
    dry_run: bool,
) -> dict[str, int]:
    """Fill the four columns of the sub-catchments of one threshold.

    Returns
    -------
    dict[str, int]
        Counts: rows, heads, overland (measured), stream_heads.

    Raises
    ------
    RuntimeError
        When rows do not match the rasters (nothing is written then).
    """
    rows = db.execute(
        text(
            "SELECT id, segment_idx, max_flow_dist_m, "
            "ST_X(ST_StartPoint(longest_flow_path_geom)) AS x, "
            "ST_Y(ST_StartPoint(longest_flow_path_geom)) AS y "
            "FROM stream_catchments WHERE threshold_m2 = :threshold "
            "ORDER BY segment_idx"
        ),
        {"threshold": threshold_m2},
    ).fetchall()
    labels, label_meta = read_raster(label_path)
    if labels.shape != (metadata["nrows"], metadata["ncols"]) or (
        label_meta["transform"] != metadata["transform"]
    ):
        raise RuntimeError(f"{label_path} is not on the grid of the filled DEM")
    flat_labels = labels.ravel()
    flat_dist = rasters["flow_dist_m"].ravel()
    filled_dem = rasters["filled_dem"]
    flat_dem = filled_dem.ravel()

    heads = head_cells(rows, metadata)
    without_path = [r.segment_idx for r, h in zip(rows, heads, strict=True) if h < 0]
    farthest = farthest_cells(without_path, flat_labels, flat_dist)
    for i, row in enumerate(rows):
        if heads[i] < 0 and row.segment_idx in farthest:
            heads[i] = farthest[row.segment_idx]

    mismatched = [
        row.segment_idx
        for row, head in zip(rows, heads, strict=True)
        if head >= 0
        and (
            flat_labels[head] != row.segment_idx
            or (
                row.max_flow_dist_m is not None
                and abs(float(flat_dist[head]) - row.max_flow_dist_m)
                > FLOW_DIST_TOLERANCE_M
            )
        )
    ]
    if mismatched:
        raise RuntimeError(
            f"threshold {threshold_m2} m²: {len(mismatched)} sub-catchments do not "
            f"match the rasters (first segment_idx: {mismatched[:5]}); "
            "are these the rasters of the data in the database?"
        )

    cell_area = metadata["cellsize"] * metadata["cellsize"]
    cells = max(1, int(threshold_m2 / cell_area))
    stream_mask = (rasters["acc"] >= cells) & (filled_dem != metadata["nodata_value"])
    measured = heads >= 0
    lengths, drops = _overland_segments(heads[measured], flw, stream_mask, flat_dem)
    stream_heads = _stream_head_cells(
        flat_labels, stream_mask.ravel(), flat_dist, int(labels.max())
    )
    del stream_mask, labels, flat_labels

    overland = iter(zip(lengths, drops, strict=True))
    updates = []
    for row, head in zip(rows, heads, strict=True):
        length, drop = next(overland) if head >= 0 else (None, None)
        stream_head = (
            stream_heads[row.segment_idx] if row.segment_idx < stream_heads.size else -1
        )
        updates.append(
            {
                "id": row.id,
                "head": round(float(flat_dem[head]), 2) if head >= 0 else None,
                "length": length,
                "drop": drop,
                "stream": (
                    round(float(flat_dem[stream_head]), 2) if stream_head >= 0 else None
                ),
            }
        )

    counts = {
        "rows": len(rows),
        "heads": int(np.count_nonzero(measured)),
        "overland": sum(length is not None for length in lengths),
        "stream_heads": sum(u["stream"] is not None for u in updates),
    }
    if not dry_run and updates:
        db.execute(_UPDATE, updates)
        db.commit()
    return counts


def main() -> None:
    """Run the backfill."""
    parser = argparse.ArgumentParser(
        description=(
            "Backfill flow_path_head_elev_m, overland_length_m, overland_drop_m and "
            "stream_head_elev_m of stream_catchments from saved rasters"
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        help="DEM of the run whose rasters were saved (e.g. /data/nmt/dem_mosaic.tif)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory of the saved rasters (default: the directory of --input)",
    )
    parser.add_argument(
        "--thresholds",
        default=None,
        help="Comma-separated thresholds [m²] (default: all in the database)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Compute and check, no UPDATE"
    )
    args = parser.parse_args()

    import pyflwdir

    input_path = Path(args.input)
    directory = Path(args.output_dir) if args.output_dir else input_path.parent
    t0 = time.time()
    with get_db_session() as db, override_statement_timeout(db, timeout_s=1800):
        present = [
            int(r[0])
            for r in db.execute(
                text("SELECT DISTINCT threshold_m2 FROM stream_catchments ORDER BY 1")
            ).fetchall()
        ]
        thresholds = (
            [int(t) for t in args.thresholds.split(",")] if args.thresholds else present
        )
        unknown = sorted(set(thresholds) - set(present))
        label_paths = {
            t: directory / f"{input_path.stem}_10_subcatchments_{t}.tif"
            for t in thresholds
        }
        missing = [str(p) for p in label_paths.values() if not p.exists()]
        if unknown or missing:
            logger.error(
                f"Thresholds without sub-catchments: {unknown}; "
                f"label rasters not found: {missing}"
            )
            sys.exit(1)

        try:
            rasters, metadata = load_hydrology_intermediates(
                input_path,
                directory,
                names=("filled_dem", "fdir", "acc", "flow_dist_m"),
            )
        except (FileNotFoundError, ValueError) as e:
            logger.error(str(e))
            sys.exit(1)
        d8 = d8_from_saved_flowdir(
            rasters.pop("fdir"),
            rasters["flow_dist_m"],
            rasters["filled_dem"] != metadata["nodata_value"],
        )
        flw = pyflwdir.from_array(
            d8,
            ftype="d8",
            transform=_get_transform(metadata, d8.shape),
            latlon=False,
        )
        del d8

        for threshold_m2 in thresholds:
            try:
                counts = backfill_threshold(
                    db,
                    threshold_m2,
                    label_paths[threshold_m2],
                    rasters,
                    metadata,
                    flw,
                    args.dry_run,
                )
            except RuntimeError as e:
                logger.error(str(e))
                sys.exit(1)
            logger.info(
                f"threshold {threshold_m2} m²: {counts['rows']} rows, "
                f"{counts['heads']} heads, {counts['overland']} overland segments, "
                f"{counts['stream_heads']} stream heads"
                + (" (dry run, nothing written)" if args.dry_run else "")
            )

        if not args.dry_run:
            nulls = db.execute(
                text(
                    "SELECT threshold_m2, COUNT(*) FILTER "
                    "(WHERE flow_path_head_elev_m IS NULL), COUNT(*) FILTER "
                    "(WHERE overland_length_m IS NULL), COUNT(*) FILTER "
                    "(WHERE stream_head_elev_m IS NULL) "
                    "FROM stream_catchments GROUP BY 1 ORDER BY 1"
                )
            ).fetchall()
            for t, heads, overland, streams in nulls:
                logger.info(
                    f"NULL after the backfill, threshold {t} m²: {heads} heads, "
                    f"{overland} overland segments, {streams} stream heads"
                )
    logger.info(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
