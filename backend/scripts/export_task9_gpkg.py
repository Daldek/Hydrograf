"""
Export E2E Task 9 results to GeoPackage for QGIS visualization.

Layers:
1. watershed_boundary — polygon boundary (A: 500k, B: 1.5M)
2. watershed_cells — point cloud of all cells (sampled for large)
3. outlet_points — outlet locations
4. stream_network — stream segments from DB

Usage:
    cd backend
    .venv/bin/python -m scripts.export_task9_gpkg
"""

import logging
import time

import geopandas as gpd
import numpy as np
from shapely.geometry import Point
from sqlalchemy import text

from core.database import get_db_session
from core.watershed import (
    FlowCell,
    build_boundary,
    calculate_watershed_area_km2,
    check_watershed_size,
    traverse_upstream,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

OUTPUT_PATH = "../data/e2e_test/task9_results.gpkg"

# Outlets from E2E Task 9
OUTLETS = [
    {"label": "A_500k", "id": 3417820, "min_acc": 100_000, "max_acc": 500_000},
    {"label": "B_1500k", "id": 1410764, "min_acc": 1_000_000, "max_acc": 1_500_000},
]


def find_outlet(db, min_acc: int, max_acc: int) -> FlowCell | None:
    result = db.execute(
        text("""
            SELECT id, ST_X(geom) as x, ST_Y(geom) as y,
                   elevation, flow_accumulation, slope,
                   downstream_id, cell_area, is_stream
            FROM flow_network
            WHERE is_stream = TRUE
              AND flow_accumulation BETWEEN :min_acc AND :max_acc
            ORDER BY flow_accumulation DESC
            LIMIT 1
        """),
        {"min_acc": min_acc, "max_acc": max_acc},
    ).fetchone()
    if result is None:
        return None
    return FlowCell(
        id=result.id, x=result.x, y=result.y,
        elevation=result.elevation,
        flow_accumulation=result.flow_accumulation,
        slope=result.slope, downstream_id=result.downstream_id,
        cell_area=result.cell_area, is_stream=result.is_stream,
    )


def main():
    logger.info("Eksport wynikow Task 9 do GeoPackage...")

    boundaries = []
    outlets_data = []
    all_cells = []

    with get_db_session() as db:
        for cfg in OUTLETS:
            label = cfg["label"]
            logger.info(f"\n--- {label} ---")

            outlet = find_outlet(db, cfg["min_acc"], cfg["max_acc"])
            if outlet is None:
                logger.warning("  Outlet nie znaleziony")
                continue

            logger.info(
                f"  Outlet: id={outlet.id}, acc={outlet.flow_accumulation:,}"
            )

            # Pre-flight
            check_watershed_size(outlet.id, db)

            # Traverse
            t0 = time.time()
            cells = traverse_upstream(outlet.id, db)
            logger.info(
                f"  Traverse: {len(cells):,} cells ({time.time()-t0:.1f}s)"
            )

            # Boundary
            boundary = build_boundary(cells, method="polygonize", cell_size=1.0)
            area_km2 = calculate_watershed_area_km2(cells)

            boundaries.append({
                "geometry": boundary,
                "label": label,
                "cell_count": len(cells),
                "area_km2": round(area_km2, 4),
                "outlet_id": outlet.id,
                "outlet_acc": outlet.flow_accumulation,
                "outlet_elev": outlet.elevation,
            })

            outlets_data.append({
                "geometry": Point(outlet.x, outlet.y),
                "label": label,
                "id": outlet.id,
                "flow_accumulation": outlet.flow_accumulation,
                "elevation": outlet.elevation,
            })

            # Sample cells for point cloud (max 50k per watershed)
            sample_size = min(len(cells), 50_000)
            if len(cells) > sample_size:
                indices = np.random.default_rng(42).choice(
                    len(cells), sample_size, replace=False
                )
                sampled = [cells[i] for i in indices]
            else:
                sampled = cells

            for c in sampled:
                all_cells.append({
                    "geometry": Point(c.x, c.y),
                    "label": label,
                    "elevation": c.elevation,
                    "flow_accumulation": c.flow_accumulation,
                    "slope": c.slope,
                    "is_stream": c.is_stream,
                })

        # Stream network from DB
        logger.info("\nPobieranie stream_network z bazy...")
        streams = db.execute(text("""
            SELECT ST_AsText(geom) as wkt,
                   strahler_order, length_m,
                   upstream_area_km2, mean_slope_percent
            FROM stream_network
            WHERE source = 'DEM_DERIVED'
        """)).fetchall()
        logger.info(f"  {len(streams)} segmentow")

    # --- Write GeoPackage ---
    from shapely import wkt

    # 1. Boundaries
    if boundaries:
        gdf = gpd.GeoDataFrame(boundaries, crs="EPSG:2180")
        gdf.to_file(OUTPUT_PATH, layer="watershed_boundary", driver="GPKG")
        logger.info(f"  watershed_boundary: {len(gdf)} features")

    # 2. Outlets
    if outlets_data:
        gdf = gpd.GeoDataFrame(outlets_data, crs="EPSG:2180")
        gdf.to_file(
            OUTPUT_PATH, layer="outlet_points",
            driver="GPKG", mode="a",
        )
        logger.info(f"  outlet_points: {len(gdf)} features")

    # 3. Cells (sampled)
    if all_cells:
        gdf = gpd.GeoDataFrame(all_cells, crs="EPSG:2180")
        gdf.to_file(
            OUTPUT_PATH, layer="watershed_cells",
            driver="GPKG", mode="a",
        )
        logger.info(f"  watershed_cells: {len(gdf)} features")

    # 4. Stream network
    if streams:
        stream_records = []
        for s in streams:
            geom = wkt.loads(s.wkt)
            stream_records.append({
                "geometry": geom,
                "strahler_order": s.strahler_order,
                "length_m": s.length_m,
                "upstream_area_km2": s.upstream_area_km2,
                "mean_slope_percent": s.mean_slope_percent,
            })
        gdf = gpd.GeoDataFrame(stream_records, crs="EPSG:2180")
        gdf.to_file(
            OUTPUT_PATH, layer="stream_network",
            driver="GPKG", mode="a",
        )
        logger.info(f"  stream_network: {len(gdf)} features")

    logger.info(f"\nGotowe: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
