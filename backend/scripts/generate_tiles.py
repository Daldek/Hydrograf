"""
Pre-generate MVT vector tiles from PostGIS stream_network and stream_catchments.

Uses ogr2ogr to export GeoJSON and tippecanoe to build .mbtiles,
then converts to PMTiles for static file serving via Nginx.

Pre-generated tiles serve in ~1ms (static file) vs ~50-200ms (SQL per request).

Usage:
    cd backend
    .venv/bin/python -m scripts.generate_tiles [--output-dir ../frontend/tiles]
        [--thresholds 1000000,10000000]

Prerequisites:
    - tippecanoe: https://github.com/felt/tippecanoe
    - ogr2ogr (GDAL): already in .venv via rasterio
    - pmtiles CLI (optional): https://github.com/protomaps/go-pmtiles
"""

import argparse
import json
import logging
import os
import shutil
import stat
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

# Per-threshold zoom overrides: fine-grained thresholds only at high zooms
THRESHOLD_MIN_ZOOM = {
    1000: 14,
}


def check_prerequisites() -> dict[str, str | None]:
    """Check that required CLI tools are available."""
    venv_bin = Path(__file__).resolve().parent.parent / ".venv" / "bin"
    tools = {}
    for tool in ("tippecanoe", "ogr2ogr", "pmtiles"):
        path = shutil.which(tool) or shutil.which(tool, path=str(venv_bin))
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

    The rows are read with a server-side cursor and written feature by feature,
    so the memory does not grow with the table (180,431 catchments of 1 ha on the
    Hydroni area took 6.9 GB as one list of parsed geometries).

    Returns number of features exported.
    """
    cols = ", ".join(columns)
    query = (
        f"SELECT {cols}, "
        f"ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geometry "
        f"FROM {table} "
        f"WHERE threshold_m2 = :threshold AND geom IS NOT NULL"
    )
    rows = db.execute(
        text(query),
        {"threshold": threshold},
        execution_options={"stream_results": True, "yield_per": 2000},
    )
    count = 0
    with open(output_path, "w") as f:
        f.write('{"type": "FeatureCollection", "features": [')
        for r in rows:
            props = {col: r[i] for i, col in enumerate(columns)}
            if count:
                f.write(", ")
            f.write(
                '{"type": "Feature", "geometry": '
                f'{r[len(columns)]}, "properties": {json.dumps(props)}}}'
            )
            count += 1
        f.write("]}")
    return count


def run_tippecanoe(
    input_path: Path,
    output_path: Path,
    layer_name: str,
    min_zoom: int = MIN_ZOOM,
    max_zoom: int = MAX_ZOOM,
    *,
    executable: str = "tippecanoe",
) -> None:
    """Run tippecanoe to generate .mbtiles from GeoJSON."""
    cmd = [
        executable,
        "-o",
        str(output_path),
        f"-z{max_zoom}",
        f"-Z{min_zoom}",
        f"--layer={layer_name}",
        "--coalesce-densest-as-needed",
        "--extend-zooms-if-still-dropping",
        "--simplification=10",
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


def extract_mbtiles_to_pbf(mbtiles_path: Path, output_dir: Path, prefix: str) -> int:
    """
    Extract tiles from .mbtiles (SQLite) to static {z}/{x}/{y}.pbf files.

    Parameters
    ----------
    mbtiles_path : Path
        Path to the .mbtiles file
    output_dir : Path
        Base output directory (tiles will go into output_dir/prefix/{z}/{x}/{y}.pbf)
    prefix : str
        Subdirectory prefix, e.g. "streams_1000"

    Returns
    -------
    int
        Number of tiles extracted
    """
    import gzip
    import sqlite3

    tile_dir = output_dir / prefix
    if tile_dir.exists():

        def _on_error(_func, _path, _exc_info):
            os.chmod(_path, stat.S_IRWXU)
            _func(_path)

        shutil.rmtree(tile_dir, onerror=_on_error)

    conn = sqlite3.connect(str(mbtiles_path))
    cursor = conn.execute(
        "SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles"
    )

    count = 0
    for zoom, col, row, data in cursor:
        # MBTiles uses TMS (y flipped): y_xyz = 2^zoom - 1 - y_tms
        y_xyz = (1 << zoom) - 1 - row
        pbf_path = tile_dir / str(zoom) / str(col) / f"{y_xyz}.pbf"
        pbf_path.parent.mkdir(parents=True, exist_ok=True)
        # tippecanoe stores tiles gzip-compressed; decompress for static serving
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        pbf_path.write_bytes(data)
        count += 1

    conn.close()
    logger.info(f"Extracted {count} tiles from {mbtiles_path.name} → {tile_dir}")
    return count


def _publish_mbtiles(mbtiles_path: Path, output_dir: Path, has_pmtiles: bool) -> None:
    """Serve a tileset built in a temporary directory from ``output_dir``.

    Extracts its tiles to ``output_dir/<stem>/{z}/{x}/{y}.pbf``, converts it to
    ``.pmtiles`` when the tool is there, then copies the ``.mbtiles`` beside them
    (its bounds go into ``tiles_metadata.json``) and deletes the temporary file.
    A plain copy works on a network share, where SQLite cannot write.
    """
    stem = mbtiles_path.stem
    extract_mbtiles_to_pbf(mbtiles_path, output_dir, stem)
    if has_pmtiles:
        convert_to_pmtiles(mbtiles_path, output_dir / f"{stem}.pmtiles")
    # A journal left by an interrupted write would make a reader roll it back
    (output_dir / f"{mbtiles_path.name}-journal").unlink(missing_ok=True)
    shutil.copyfile(mbtiles_path, output_dir / mbtiles_path.name)
    mbtiles_path.unlink()


def mbtiles_bounds(paths: list[Path]) -> list[float] | None:
    """Return the union of the ``bounds`` of .mbtiles files, or None.

    The frontend passes it to the tile layers so the browser never asks
    for tiles outside the data (each of them would answer 404).

    Returns
    -------
    list[float] or None
        ``[west, south, east, north]`` in WGS84 (MBTiles convention);
        None when no file holds valid bounds.
    """
    import sqlite3

    union: list[float] | None = None
    for path in paths:
        if not path.exists():
            continue
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT value FROM metadata WHERE name = 'bounds'"
            ).fetchone()
        finally:
            conn.close()
        if not row:
            continue
        try:
            west, south, east, north = (float(v) for v in row[0].split(","))
        except ValueError:
            logger.warning(f"Invalid bounds in {path.name}: {row[0]!r}")
            continue
        if union is None:
            union = [west, south, east, north]
        else:
            union = [
                min(union[0], west),
                min(union[1], south),
                max(union[2], east),
                max(union[3], north),
            ]
    return union


def write_metadata(output_dir: Path, thresholds: list[int]) -> Path:
    """Write ``tiles_metadata.json`` for the tiles in ``output_dir``."""
    metadata = {
        "thresholds": thresholds,
        "min_zoom": MIN_ZOOM,
        "max_zoom": MAX_ZOOM,
        "threshold_min_zoom": {str(k): v for k, v in THRESHOLD_MIN_ZOOM.items()},
        "format": "pbf",
        "bounds": mbtiles_bounds(
            [
                output_dir / f"{layer}_{threshold}.mbtiles"
                for threshold in thresholds
                for layer in ("streams", "catchments")
            ]
        ),
    }
    meta_path = output_dir / "tiles_metadata.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    return meta_path


def tiled_thresholds(output_dir: Path, thresholds: list[int]) -> list[int]:
    """Return the thresholds of ``thresholds`` that have tiles in ``output_dir``."""
    return [
        t
        for t in thresholds
        if any(
            (output_dir / f"{layer}_{t}").is_dir()
            for layer in ("streams", "catchments")
        )
    ]


def generate_tiles(output_dir: Path, only_thresholds: list[int] | None = None) -> None:
    """Generate pre-built MVT tiles for the thresholds of the database.

    Parameters
    ----------
    output_dir : Path
        Directory of the tiles and of ``tiles_metadata.json``.
    only_thresholds : list[int], optional
        Build only these thresholds and keep the tiles of the others; the
        metadata then lists every threshold of the database with tiles.
    """
    t0 = time.time()
    output_dir.mkdir(parents=True, exist_ok=True)

    tools = check_prerequisites()
    tippecanoe_path = tools.get("tippecanoe")
    if not tippecanoe_path:
        logger.error("tippecanoe is required. Install: pip install tippecanoe")
        sys.exit(1)

    has_pmtiles = tools.get("pmtiles") is not None

    with get_db_session() as db:
        db_thresholds = get_thresholds(db)
        if not db_thresholds:
            logger.error("No thresholds found in stream_network")
            sys.exit(1)

        thresholds = db_thresholds
        if only_thresholds:
            unknown = sorted(set(only_thresholds) - set(db_thresholds))
            if unknown:
                logger.error(f"Thresholds not in stream_network: {unknown}")
                sys.exit(1)
            thresholds = sorted(set(only_thresholds))

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

                # Generate .mbtiles in the temporary directory: tippecanoe writes
                # SQLite, which fails on a network share ("database is locked"),
                # and the output directory may be one
                th_min_zoom = THRESHOLD_MIN_ZOOM.get(threshold, MIN_ZOOM)
                streams_mbt = tmp / f"streams_{threshold}.mbtiles"
                if n_streams > 0:
                    run_tippecanoe(
                        streams_json,
                        streams_mbt,
                        "streams",
                        min_zoom=th_min_zoom,
                        executable=tippecanoe_path,
                    )
                else:
                    logger.warning(f"No streams for threshold {threshold} — skipping")

                catchments_mbt = tmp / f"catchments_{threshold}.mbtiles"
                if n_catch > 0:
                    run_tippecanoe(
                        catchments_json,
                        catchments_mbt,
                        "catchments",
                        min_zoom=th_min_zoom,
                        executable=tippecanoe_path,
                    )
                else:
                    logger.warning(f"No catchments for threshold {threshold}")

                streams_json.unlink(missing_ok=True)
                catchments_json.unlink(missing_ok=True)
                for mbtiles in (streams_mbt, catchments_mbt):
                    if mbtiles.exists():
                        _publish_mbtiles(mbtiles, output_dir, has_pmtiles)

    write_metadata(output_dir, tiled_thresholds(output_dir, db_thresholds))

    elapsed = time.time() - t0
    logger.info(
        f"Tile generation complete: {len(thresholds)} thresholds in {elapsed:.1f}s"
    )
    logger.info(f"Output: {output_dir}")


def main() -> None:
    """Run the MVT tile generator."""
    parser = argparse.ArgumentParser(description="Pre-generate MVT tiles from PostGIS")
    parser.add_argument(
        "--output-dir",
        default="../frontend/tiles",
        help="Output directory for tile files (default: ../frontend/tiles)",
    )
    parser.add_argument(
        "--thresholds",
        default=None,
        help=(
            "Comma-separated thresholds [m²] to build; the tiles of the other "
            "thresholds stay (default: every threshold of the database)"
        ),
    )
    args = parser.parse_args()

    only = (
        [int(t.strip()) for t in args.thresholds.split(",")]
        if args.thresholds
        else None
    )
    generate_tiles(Path(args.output_dir), only)


if __name__ == "__main__":
    main()
