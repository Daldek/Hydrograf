"""
Export DEM pipeline results to GeoPackage with optional Markdown report.

Layers:
- streams_{threshold}      — LINESTRING per FA threshold
- catchments_{threshold}   — MULTIPOLYGON per FA threshold
- depressions              — POLYGON terrain depressions

Usage:
    cd backend
    .venv/bin/python -m scripts.export_pipeline_gpkg \
        --output ../data/e2e_test/pipeline_results.gpkg \
        --thresholds "100,1000,10000,100000" \
        --report ../data/e2e_test/PIPELINE_REPORT.md \
        --intermediates-dir ../data/e2e_test/intermediates
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import geopandas as gpd
from shapely import wkt
from sqlalchemy import text

from core.database import get_db_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def export_streams(db, output_path: Path, threshold: int, first: bool) -> int:
    """Export stream segments for a given threshold to GeoPackage layer."""
    layer = f"streams_{threshold}"
    rows = db.execute(
        text("""
            SELECT ST_AsText(geom) AS wkt,
                   strahler_order, length_m,
                   upstream_area_km2, mean_slope_percent
            FROM stream_network
            WHERE source = 'DEM_DERIVED' AND threshold_m2 = :t
        """),
        {"t": threshold},
    ).fetchall()

    if not rows:
        logger.warning(f"  {layer}: 0 features — skipping")
        return 0

    records = [
        {
            "geometry": wkt.loads(r.wkt),
            "strahler_order": r.strahler_order,
            "length_m": r.length_m,
            "upstream_area_km2": r.upstream_area_km2,
            "mean_slope_percent": r.mean_slope_percent,
        }
        for r in rows
    ]
    gdf = gpd.GeoDataFrame(records, crs="EPSG:2180")
    mode = "w" if first else "a"
    gdf.to_file(str(output_path), layer=layer, driver="GPKG", mode=mode)
    logger.info(f"  {layer}: {len(gdf)} features")
    return len(gdf)


def export_catchments(db, output_path: Path, threshold: int) -> int:
    """Export sub-catchment polygons for a given threshold to GeoPackage layer."""
    layer = f"catchments_{threshold}"
    rows = db.execute(
        text("""
            SELECT ST_AsText(geom) AS wkt,
                   segment_idx, area_km2,
                   mean_elevation_m, mean_slope_percent,
                   strahler_order
            FROM stream_catchments
            WHERE threshold_m2 = :t
        """),
        {"t": threshold},
    ).fetchall()

    if not rows:
        logger.warning(f"  {layer}: 0 features — skipping")
        return 0

    records = [
        {
            "geometry": wkt.loads(r.wkt),
            "segment_idx": r.segment_idx,
            "area_km2": r.area_km2,
            "mean_elevation_m": r.mean_elevation_m,
            "mean_slope_percent": r.mean_slope_percent,
            "strahler_order": r.strahler_order,
        }
        for r in rows
    ]
    gdf = gpd.GeoDataFrame(records, crs="EPSG:2180")
    gdf.to_file(str(output_path), layer=layer, driver="GPKG", mode="a")
    logger.info(f"  {layer}: {len(gdf)} features")
    return len(gdf)


def export_depressions(db, output_path: Path) -> int:
    """Export depression polygons to GeoPackage layer."""
    layer = "depressions"
    rows = db.execute(
        text("""
            SELECT ST_AsText(geom) AS wkt,
                   volume_m3, area_m2, max_depth_m, mean_depth_m
            FROM depressions
        """)
    ).fetchall()

    if not rows:
        logger.warning(f"  {layer}: 0 features — skipping")
        return 0

    records = [
        {
            "geometry": wkt.loads(r.wkt),
            "volume_m3": r.volume_m3,
            "area_m2": r.area_m2,
            "max_depth_m": r.max_depth_m,
            "mean_depth_m": r.mean_depth_m,
        }
        for r in rows
    ]
    gdf = gpd.GeoDataFrame(records, crs="EPSG:2180")
    gdf.to_file(str(output_path), layer=layer, driver="GPKG", mode="a")
    logger.info(f"  {layer}: {len(gdf)} features")
    return len(gdf)


def generate_report(
    db,
    report_path: Path,
    thresholds: list[int],
    gpkg_path: Path,
    intermediates_dir: Path | None,
    layer_counts: dict[str, int],
) -> None:
    """Generate Markdown report with pipeline statistics."""
    lines: list[str] = []
    lines.append("# Raport pipeline DEM\n")
    lines.append(f"Data generowania: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

    # --- Input data ---
    lines.append("## Dane wejsciowe\n")
    row = db.execute(
        text("SELECT COUNT(*) AS cnt FROM flow_network")
    ).fetchone()
    flow_count = row.cnt if row else 0

    row = db.execute(
        text("""
            SELECT MIN(elevation) AS elev_min,
                   MAX(elevation) AS elev_max,
                   AVG(slope) AS slope_avg,
                   MAX(flow_accumulation) AS fa_max
            FROM flow_network
        """)
    ).fetchone()

    lines.append(f"- Komorki flow_network: **{flow_count:,}**")
    if row and row.elev_min is not None:
        lines.append(f"- Zakres elewacji: {row.elev_min:.1f} – {row.elev_max:.1f} m n.p.m.")
        lines.append(f"- Sredni spadek: {row.slope_avg:.2f}%")
        lines.append(f"- Max flow accumulation: {row.fa_max:,}")
    lines.append("")

    # --- Threshold table ---
    lines.append("## Progi flow accumulation\n")
    lines.append("| Prog FA [m²] | Segmenty ciekow | Zlewnie | Max Strahler |")
    lines.append("|:---:|:---:|:---:|:---:|")

    for t in thresholds:
        sn = db.execute(
            text("""
                SELECT COUNT(*) AS cnt, COALESCE(MAX(strahler_order), 0) AS max_s
                FROM stream_network
                WHERE source = 'DEM_DERIVED' AND threshold_m2 = :t
            """),
            {"t": t},
        ).fetchone()

        sc = db.execute(
            text("""
                SELECT COUNT(*) AS cnt
                FROM stream_catchments
                WHERE threshold_m2 = :t
            """),
            {"t": t},
        ).fetchone()

        seg_count = sn.cnt if sn else 0
        max_strahler = sn.max_s if sn else 0
        catch_count = sc.cnt if sc else 0
        lines.append(f"| {t:,} | {seg_count:,} | {catch_count:,} | {max_strahler} |")

    lines.append("")

    # --- Database summary ---
    lines.append("## Statystyki bazy danych\n")
    total_streams = db.execute(
        text("SELECT COUNT(*) FROM stream_network WHERE source = 'DEM_DERIVED'")
    ).scalar()
    total_catchments = db.execute(
        text("SELECT COUNT(*) FROM stream_catchments")
    ).scalar()
    total_depressions = db.execute(
        text("SELECT COUNT(*) FROM depressions")
    ).scalar()

    lines.append(f"| Tabela | Liczba rekordow |")
    lines.append(f"|:---|:---:|")
    lines.append(f"| flow_network | {flow_count:,} |")
    lines.append(f"| stream_network (DEM_DERIVED) | {total_streams:,} |")
    lines.append(f"| stream_catchments | {total_catchments:,} |")
    lines.append(f"| depressions | {total_depressions:,} |")
    lines.append("")

    # --- Depressions stats ---
    if total_depressions and total_depressions > 0:
        lines.append("## Zaglebienia terenu\n")
        dep_stats = db.execute(
            text("""
                SELECT COUNT(*) AS cnt,
                       SUM(volume_m3) AS total_vol,
                       MAX(max_depth_m) AS max_depth,
                       AVG(max_depth_m) AS avg_depth,
                       SUM(area_m2) AS total_area
                FROM depressions
            """)
        ).fetchone()
        if dep_stats:
            lines.append(f"- Liczba: **{dep_stats.cnt:,}**")
            lines.append(f"- Sumaryczna objetosc: {dep_stats.total_vol:,.1f} m³")
            lines.append(f"- Sumaryczna powierzchnia: {dep_stats.total_area:,.1f} m²")
            lines.append(f"- Max glebokosc: {dep_stats.max_depth:.3f} m")
            lines.append(f"- Srednia max glebokosc: {dep_stats.avg_depth:.3f} m")
        lines.append("")

    # --- Intermediate files ---
    if intermediates_dir and intermediates_dir.exists():
        lines.append("## Pliki posrednie (GeoTIFF)\n")
        lines.append("| Plik | Rozmiar |")
        lines.append("|:---|:---:|")
        tif_files = sorted(intermediates_dir.glob("*.tif"))
        for f in tif_files:
            size_mb = f.stat().st_size / (1024 * 1024)
            lines.append(f"| `{f.name}` | {size_mb:.1f} MB |")
        lines.append(f"\nLaczna liczba: {len(tif_files)} plikow\n")

    # --- GeoPackage layers ---
    lines.append("## Warstwy GeoPackage\n")
    lines.append(f"Plik: `{gpkg_path.name}`\n")
    lines.append("| Warstwa | Liczba features |")
    lines.append("|:---|:---:|")
    for layer_name, count in sorted(layer_counts.items()):
        lines.append(f"| {layer_name} | {count:,} |")
    lines.append("")

    report_text = "\n".join(lines) + "\n"
    report_path.write_text(report_text, encoding="utf-8")
    logger.info(f"Raport: {report_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export DEM pipeline results to GeoPackage"
    )
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Output GeoPackage path",
    )
    parser.add_argument(
        "--thresholds",
        default="100,1000,10000,100000",
        help="Comma-separated FA thresholds (default: 100,1000,10000,100000)",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Output Markdown report path (optional)",
    )
    parser.add_argument(
        "--intermediates-dir",
        default=None,
        help="Directory with intermediate GeoTIFF files (for report listing)",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    thresholds = [int(t.strip()) for t in args.thresholds.split(",")]
    logger.info(f"Eksport do GeoPackage: {output_path}")
    logger.info(f"Progi FA: {thresholds}")

    layer_counts: dict[str, int] = {}
    start = time.time()

    with get_db_session() as db:
        db.execute(text("SET LOCAL statement_timeout = '600s'"))

        # Export streams (first layer uses mode='w')
        first = True
        for t in thresholds:
            count = export_streams(db, output_path, t, first=first)
            if count > 0:
                layer_counts[f"streams_{t}"] = count
                first = False

        # Export catchments
        for t in thresholds:
            count = export_catchments(db, output_path, t)
            if count > 0:
                layer_counts[f"catchments_{t}"] = count

        # Export depressions
        count = export_depressions(db, output_path)
        if count > 0:
            layer_counts["depressions"] = count

        elapsed = time.time() - start
        logger.info(f"GeoPackage gotowy: {output_path} ({elapsed:.1f}s)")
        logger.info(f"Warstwy: {len(layer_counts)}, features: {sum(layer_counts.values()):,}")

        # Generate report
        if args.report:
            report_path = Path(args.report)
            intermediates_dir = Path(args.intermediates_dir) if args.intermediates_dir else None
            generate_report(
                db, report_path, thresholds, output_path,
                intermediates_dir, layer_counts,
            )


if __name__ == "__main__":
    main()
