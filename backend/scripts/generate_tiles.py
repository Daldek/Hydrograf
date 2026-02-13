"""
Pre-generate MVT vector tiles from PostGIS stream_network and stream_catchments.

Uses ogr2ogr to export GeoJSON and tippecanoe to build .mbtiles,
then converts to PMTiles for static file serving via Nginx.

Pre-generated tiles serve in ~1ms (static file) vs ~50-200ms (SQL per request).

Usage:
    cd backend
    .venv/bin/python -m scripts.generate_tiles [--output-dir ../frontend/tiles]

Prerequisites:
    - tippecanoe: https://github.com/felt/tippecanoe
    - ogr2ogr (GDAL): already in .venv via rasterio
    - pmtiles CLI (optional): https://github.com/protomaps/go-pmtiles
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from sqlalchemy import text

from core.database import get_db_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# Tile generation settings
MIN_ZOOM = 8
MAX_ZOOM = 18


def check_prerequisites() -> dict[str, str | None]:
    """Check that required CLI tools are available."""
    tools = {}
    for tool in ("tippecanoe", "ogr2ogr", "pmtiles"):
        path = shutil.which(tool)
        tools[tool] = path
        if path:
            logger.info(f"Found {tool}: {path}")
        elif tool == "pmtiles":
            logger.warning(
                f"{tool} not found — .mbtiles will be generated "
                f"but not converted to .pmtiles"
            )
        else:
            logger.error(f"Required tool not found: {tool}")
    return tools


def get_thresholds(db) -> list[int]:
    """Get available FA thresholds from database."""
    rows = db.execute(
        text("SELECT DISTINCT threshold_m2 FROM stream_network ORDER BY threshold_m2")
    ).fetchall()
    return [r[0] for r in rows]


def export_geojson(
    db,
    table: str,
    threshold: int,
    output_path: Path,
    columns: list[str],
) -> int:
    """
    Export PostGIS table to GeoJSON for a given threshold.

    Returns number of features exported.
    """
    cols = ", ".join(columns)
    query = (
        f"SELECT {cols}, "
        f"ST_AsGeoJSON(ST_Transform(geom, 4326))::json AS geometry "
        f"FROM {table} "
        f"WHERE threshold_m2 = :threshold AND geom IS NOT NULL"
    )

    rows = db.execute(text(query), {"threshold": threshold}).fetchall()

    features = []
    for r in rows:
        props = {}
        for i, col in enumerate(columns):
            props[col] = r[i]
        geom = r[len(columns)]
        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": props,
            }
        )

    geojson = {
        "type": "FeatureCollection",
        "features": features,
    }

    with open(output_path, "w") as f:
        json.dump(geojson, f)

    return len(features)


def run_tippecanoe(
    input_path: Path,
    output_path: Path,
    layer_name: str,
    min_zoom: int = MIN_ZOOM,
    max_zoom: int = MAX_ZOOM,
) -> None:
    """Run tippecanoe to generate .mbtiles from GeoJSON."""
    cmd = [
        "tippecanoe",
        "-o",
        str(output_path),
        f"-z{max_zoom}",
        f"-Z{min_zoom}",
        f"--layer={layer_name}",
        "--drop-densest-as-needed",
        "--extend-zooms-if-still-dropping",
        "--force",
        str(input_path),
    ]
    logger.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"tippecanoe failed: {result.stderr}")
        raise RuntimeError(f"tippecanoe failed: {result.stderr}")
    logger.info(f"Generated {output_path}")


def convert_to_pmtiles(
    mbtiles_path: Path,
    pmtiles_path: Path,
) -> None:
    """Convert .mbtiles to .pmtiles for static serving."""
    cmd = ["pmtiles", "convert", str(mbtiles_path), str(pmtiles_path)]
    logger.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"pmtiles convert failed: {result.stderr}")
        raise RuntimeError(f"pmtiles convert failed: {result.stderr}")
    logger.info(f"Generated {pmtiles_path}")


def generate_tiles(output_dir: Path) -> None:
    """Generate pre-built MVT tiles for all thresholds."""
    t0 = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)

    tools = check_prerequisites()
    if not tools.get("tippecanoe"):
        logger.error(
            "tippecanoe is required. Install: https://github.com/felt/tippecanoe"
        )
        sys.exit(1)

    has_pmtiles = tools.get("pmtiles") is not None

    with get_db_session() as db:
        thresholds = get_thresholds(db)
        if not thresholds:
            logger.error("No thresholds found in stream_network")
            sys.exit(1)

        logger.info(f"Thresholds: {thresholds}")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            for threshold in thresholds:
                logger.info(f"--- Threshold {threshold} m² ---")

                # Export streams
                streams_json = tmp / f"streams_{threshold}.geojson"
                n_streams = export_geojson(
                    db,
                    "stream_network",
                    threshold,
                    streams_json,
                    [
                        "strahler_order",
                        "length_m",
                        "upstream_area_km2",
                    ],
                )
                logger.info(f"Exported {n_streams} stream features")

                # Export catchments
                catchments_json = tmp / f"catchments_{threshold}.geojson"
                n_catch = export_geojson(
                    db,
                    "stream_catchments",
                    threshold,
                    catchments_json,
                    [
                        "strahler_order",
                        "area_km2",
                        "mean_elevation_m",
                        "segment_idx",
                    ],
                )
                logger.info(f"Exported {n_catch} catchment features")

                # Generate .mbtiles
                streams_mbt = output_dir / f"streams_{threshold}.mbtiles"
                run_tippecanoe(
                    streams_json,
                    streams_mbt,
                    "streams",
                )

                catchments_mbt = output_dir / f"catchments_{threshold}.mbtiles"
                run_tippecanoe(
                    catchments_json,
                    catchments_mbt,
                    "catchments",
                )

                # Convert to PMTiles if available
                if has_pmtiles:
                    convert_to_pmtiles(
                        streams_mbt,
                        output_dir / f"streams_{threshold}.pmtiles",
                    )
                    convert_to_pmtiles(
                        catchments_mbt,
                        output_dir / f"catchments_{threshold}.pmtiles",
                    )

    # Write metadata
    metadata = {
        "thresholds": thresholds,
        "min_zoom": MIN_ZOOM,
        "max_zoom": MAX_ZOOM,
        "format": "pmtiles" if has_pmtiles else "mbtiles",
    }
    meta_path = output_dir / "tiles_metadata.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    elapsed = time.time() - t0
    logger.info(
        f"Tile generation complete: {len(thresholds)} thresholds in {elapsed:.1f}s"
    )
    logger.info(f"Output: {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-generate MVT tiles from PostGIS")
    parser.add_argument(
        "--output-dir",
        default="../frontend/tiles",
        help="Output directory for tile files (default: ../frontend/tiles)",
    )
    args = parser.parse_args()

    generate_tiles(Path(args.output_dir))


if __name__ == "__main__":
    main()
