"""
Backfill stream_catchments.outlet_flow_dist_m.

Samples the stream_distance raster at ST_EndPoint(longest_flow_path_geom)
(both in EPSG:2180). Rows without a path geometry get max_flow_dist_m
(single-cell catchments -> internal hydraulic length 0). Idempotent.
"""

import argparse
import logging
import math
import sys
import time

from sqlalchemy import text

from core.config import get_settings
from core.database import get_db_session
from core.db_bulk import override_statement_timeout
from core.watershed_service import sample_stream_distance

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CELL_TOLERANCE_M = 2.5


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill outlet_flow_dist_m in stream_catchments"
    )
    parser.add_argument(
        "--raster", default=None, help="Path to stream_distance GeoTIFF"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Compute but skip UPDATE"
    )
    args = parser.parse_args()

    raster_path = args.raster or get_settings().resolve_stream_distance_path()
    if not raster_path:
        print("Error: stream_distance raster not found", file=sys.stderr)
        sys.exit(1)

    t0 = time.time()
    with get_db_session() as db, override_statement_timeout(db, timeout_s=600):
        rows = db.execute(text("""
            SELECT id, max_flow_dist_m,
                   ST_X(ST_EndPoint(longest_flow_path_geom)) AS x,
                   ST_Y(ST_EndPoint(longest_flow_path_geom)) AS y
            FROM stream_catchments
        """)).fetchall()

        with_geom = [r for r in rows if r.x is not None and r.y is not None]
        without_geom = [r for r in rows if r.x is None or r.y is None]

        samples = sample_stream_distance(
            [(r.x, r.y) for r in with_geom], raster_path
        )

        updates = []
        nan_fallbacks = 0
        for r, dist in zip(with_geom, samples, strict=True):
            if math.isnan(dist):
                dist = r.max_flow_dist_m
                nan_fallbacks += 1
            updates.append({"id": r.id, "v": dist})
        for r in without_geom:
            updates.append({"id": r.id, "v": r.max_flow_dist_m})

        logger.info(
            f"{len(rows)} rows: {len(with_geom)} sampled "
            f"({nan_fallbacks} NaN fallbacks), "
            f"{len(without_geom)} without geometry"
        )

        if args.dry_run:
            logger.info("Dry run - skipping UPDATE")
            return

        db.execute(
            text(
                "UPDATE stream_catchments "
                "SET outlet_flow_dist_m = :v WHERE id = :id"
            ),
            updates,
        )
        db.commit()

        nulls = db.execute(text(
            "SELECT COUNT(*) FROM stream_catchments "
            "WHERE outlet_flow_dist_m IS NULL"
        )).scalar()
        inflated = db.execute(
            text(
                "SELECT COUNT(*) FROM stream_catchments "
                "WHERE outlet_flow_dist_m > max_flow_dist_m + :tol"
            ),
            {"tol": CELL_TOLERANCE_M},
        ).scalar()
        logger.info(
            f"NULL remaining: {nulls}, "
            f"outlet > max_flow_dist (+{CELL_TOLERANCE_M}m): {inflated}"
        )
        if nulls or inflated:
            logger.warning("Anomalie po backfillu - sprawdz dane")
        logger.info(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
