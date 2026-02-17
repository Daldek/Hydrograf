"""
Bulk database operations using PostgreSQL COPY for
stream_network and stream_catchments tables.

Provides high-performance bulk INSERT via temp tables and COPY FROM.
"""

import io
import json
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


@contextmanager
def override_statement_timeout(db_session, timeout_s: int = 0):
    """
    Context manager to override PostgreSQL statement_timeout.

    Uses session-level SET (not LOCAL) because LOCAL resets on commit.

    Parameters
    ----------
    db_session : Session
        SQLAlchemy database session
    timeout_s : int
        Timeout in seconds (0 = no limit)
    """
    raw_conn = db_session.connection().connection
    cursor = raw_conn.cursor()

    # Save current timeout
    cursor.execute("SHOW statement_timeout")
    original_timeout = cursor.fetchone()[0]

    # Set new timeout (session-level, survives commits)
    cursor.execute(f"SET statement_timeout = '{timeout_s}s'")
    raw_conn.commit()

    try:
        yield
    finally:
        # Restore original timeout (connection may already be closed)
        try:
            cursor.execute(f"SET statement_timeout = '{original_timeout}'")
            raw_conn.commit()
        except Exception:
            pass


def insert_stream_segments(
    db_session,
    segments: list[dict],
    threshold_m2: int = 100,
) -> int:
    """
    Insert vectorized stream segments into stream_network table.

    Uses COPY for bulk loading via temporary table.

    Parameters
    ----------
    db_session : Session
        SQLAlchemy database session
    segments : list[dict]
        List of segment dicts from vectorize_streams()
    threshold_m2 : int
        Flow accumulation threshold in m² used to generate these segments

    Returns
    -------
    int
        Number of segments inserted
    """
    if not segments:
        logger.info("No stream segments to insert")
        return 0

    logger.info(
        f"Inserting {len(segments)} stream segments "
        f"(threshold={threshold_m2} m²) into stream_network..."
    )

    raw_conn = db_session.connection().connection
    cursor = raw_conn.cursor()

    # Create temp table (drop first in case of multi-threshold re-use)
    cursor.execute("DROP TABLE IF EXISTS temp_stream_import")
    cursor.execute("""
        CREATE TEMP TABLE temp_stream_import (
            wkt TEXT,
            strahler_order INT,
            length_m FLOAT,
            upstream_area_km2 FLOAT,
            mean_slope_percent FLOAT,
            source TEXT,
            threshold_m2 INT,
            segment_idx INT
        )
    """)

    # Build TSV
    tsv_buffer = io.StringIO()
    for i, seg in enumerate(segments, start=1):
        coords_wkt = ", ".join(f"{x} {y}" for x, y in seg["coords"])
        wkt = f"LINESTRING({coords_wkt})"
        tsv_buffer.write(
            f"{wkt}\t{seg['strahler_order']}\t"
            f"{seg['length_m']}\t{seg['upstream_area_km2']}\t"
            f"{seg['mean_slope_percent']}\tDEM_DERIVED\t"
            f"{threshold_m2}\t{i}\n"
        )

    tsv_buffer.seek(0)

    cursor.copy_expert(
        "COPY temp_stream_import FROM STDIN"
        " WITH (FORMAT text, DELIMITER E'\\t', NULL '')",
        tsv_buffer,
    )

    # Insert with geometry construction (skip geohash duplicates)
    cursor.execute("""
        INSERT INTO stream_network (
            geom, strahler_order, length_m,
            upstream_area_km2, mean_slope_percent, source,
            threshold_m2, segment_idx
        )
        SELECT
            ST_SetSRID(ST_GeomFromText(wkt), 2180),
            strahler_order, length_m,
            upstream_area_km2, mean_slope_percent, source,
            threshold_m2, segment_idx
        FROM temp_stream_import
        ON CONFLICT DO NOTHING
    """)

    total = cursor.rowcount
    raw_conn.commit()
    logger.info(f"  Inserted {total} stream segments")

    if total < len(segments):
        logger.warning(
            f"  {len(segments) - total} segments dropped by unique constraint "
            f"(threshold={threshold_m2} m²)"
        )

    return total


def insert_catchments(
    db_session,
    catchments: list[dict],
    threshold_m2: int,
) -> int:
    """
    Insert sub-catchment polygons into stream_catchments table.

    Uses COPY pattern (temp table + bulk insert) for performance.

    Parameters
    ----------
    db_session : Session
        SQLAlchemy database session
    catchments : list[dict]
        List of catchment dicts from polygonize_subcatchments()
    threshold_m2 : int
        Flow accumulation threshold in m²

    Returns
    -------
    int
        Number of catchments inserted
    """
    if not catchments:
        logger.info("No sub-catchments to insert")
        return 0

    logger.info(
        f"Inserting {len(catchments)} sub-catchments "
        f"(threshold={threshold_m2} m²) into stream_catchments..."
    )

    raw_conn = db_session.connection().connection
    cursor = raw_conn.cursor()

    # Create temp table (drop first in case of multi-threshold re-use)
    cursor.execute("DROP TABLE IF EXISTS temp_catchments_import")
    cursor.execute("""
        CREATE TEMP TABLE temp_catchments_import (
            wkt TEXT,
            segment_idx INT,
            threshold_m2 INT,
            area_km2 FLOAT,
            mean_elevation_m FLOAT,
            mean_slope_percent FLOAT,
            strahler_order INT,
            downstream_segment_idx INT,
            elevation_min_m FLOAT,
            elevation_max_m FLOAT,
            perimeter_km FLOAT,
            stream_length_km FLOAT,
            elev_histogram JSONB
        )
    """)

    # Build TSV
    def _tsv_val(v):
        return "" if v is None else str(v)

    tsv_buffer = io.StringIO()
    for cat in catchments:
        histogram = cat.get("elev_histogram")
        hist_str = "" if histogram is None else json.dumps(histogram)
        tsv_buffer.write(
            f"{cat['wkt']}\t{cat['segment_idx']}\t"
            f"{threshold_m2}\t{cat['area_km2']}\t"
            f"{_tsv_val(cat['mean_elevation_m'])}\t"
            f"{_tsv_val(cat['mean_slope_percent'])}\t"
            f"{_tsv_val(cat.get('strahler_order'))}\t"
            f"{_tsv_val(cat.get('downstream_segment_idx'))}\t"
            f"{_tsv_val(cat.get('elevation_min_m'))}\t"
            f"{_tsv_val(cat.get('elevation_max_m'))}\t"
            f"{_tsv_val(cat.get('perimeter_km'))}\t"
            f"{_tsv_val(cat.get('stream_length_km'))}\t"
            f"{hist_str}\n"
        )

    tsv_buffer.seek(0)

    cursor.copy_expert(
        "COPY temp_catchments_import FROM STDIN"
        " WITH (FORMAT text, DELIMITER E'\\t', NULL '')",
        tsv_buffer,
    )

    # Insert with geometry construction
    cursor.execute("""
        INSERT INTO stream_catchments (
            geom, segment_idx, threshold_m2,
            area_km2, mean_elevation_m, mean_slope_percent,
            strahler_order, downstream_segment_idx,
            elevation_min_m, elevation_max_m,
            perimeter_km, stream_length_km, elev_histogram
        )
        SELECT
            ST_SetSRID(ST_GeomFromText(wkt), 2180),
            segment_idx, threshold_m2,
            area_km2, mean_elevation_m, mean_slope_percent,
            strahler_order, downstream_segment_idx,
            elevation_min_m, elevation_max_m,
            perimeter_km, stream_length_km, elev_histogram
        FROM temp_catchments_import
    """)

    total = cursor.rowcount
    raw_conn.commit()
    logger.info(f"  Inserted {total} sub-catchments")

    # Clean up micro-fragments from raster polygonization.
    # Multipolygon geometries can contain tiny (1 m²) detached parts
    # that cause visual artifacts in MVT tile highlighting.
    _min_part_area = 50  # m² in EPSG:2180
    cursor.execute(
        """
        UPDATE stream_catchments
        SET geom = COALESCE(
            (SELECT ST_Multi(ST_Union(d.geom))
             FROM ST_Dump(geom) AS d
             WHERE ST_Area(d.geom) >= %s),
            (SELECT ST_Multi(d.geom)
             FROM ST_Dump(geom) AS d
             ORDER BY ST_Area(d.geom) DESC LIMIT 1)
        )
        WHERE threshold_m2 = %s AND ST_NumGeometries(geom) > 1
        """,
        (_min_part_area, threshold_m2),
    )
    cleaned = cursor.rowcount
    raw_conn.commit()
    if cleaned:
        logger.info(f"  Cleaned {cleaned} multi-part geometries")

    return total
