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
    # SECURITY: SET doesn't support parameterized queries in PostgreSQL,
    # so we validate timeout_s is a non-negative integer before interpolation.
    if not isinstance(timeout_s, int) or timeout_s < 0:
        raise ValueError(f"timeout_s must be a non-negative integer, got {timeout_s}")

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
    threshold_m2: int = 1000,
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

    with override_statement_timeout(db_session, timeout_s=600):
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

    with override_statement_timeout(db_session, timeout_s=600):
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
                hydraulic_length_km FLOAT,
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
                f"{_tsv_val(cat.get('hydraulic_length_km'))}\t"
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
                perimeter_km, stream_length_km,
                hydraulic_length_km, elev_histogram
            )
            SELECT
                ST_SetSRID(ST_GeomFromText(wkt), 2180),
                segment_idx, threshold_m2,
                area_km2, mean_elevation_m, mean_slope_percent,
                strahler_order, downstream_segment_idx,
                elevation_min_m, elevation_max_m,
                perimeter_km, stream_length_km,
                hydraulic_length_km, elev_histogram
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


# ---------------------------------------------------------------------------
# BDOT10k stream import & matching
# ---------------------------------------------------------------------------

VALID_BDOT_LINE_TYPES = {"SWRS", "SWKN", "SWRM"}


def load_bdot_streams_from_gpkg(gpkg_path):
    """Load BDOT10k linear hydro features from merged GeoPackage.

    Reads OT_SWRS_L, OT_SWKN_L, OT_SWRM_L layers.
    Reprojects to EPSG:2180 if needed. Decomposes MultiLineString.

    Returns list of dicts ready for insert_bdot_streams().
    """
    from pathlib import Path
    import fiona
    import geopandas as gpd
    from shapely.geometry import LineString, MultiLineString

    gpkg_path = Path(gpkg_path)
    if not gpkg_path.exists():
        logger.warning(f"BDOT GPKG not found: {gpkg_path}")
        return []

    LAYER_MAP = {
        "OT_SWRS_L": "SWRS",
        "OT_SWKN_L": "SWKN",
        "OT_SWRM_L": "SWRM",
    }
    available = set(fiona.listlayers(str(gpkg_path)))
    results = []

    for layer_name, layer_type in LAYER_MAP.items():
        if layer_name not in available:
            continue
        gdf = gpd.read_file(str(gpkg_path), layer=layer_name)
        if gdf.crs and gdf.crs.to_epsg() != 2180:
            gdf = gdf.to_crs(epsg=2180)

        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            name = None
            for col in ("NAZWA", "nazwa", "Name", "name"):
                if col in row.index and row[col]:
                    name = str(row[col])
                    break

            lines = []
            if isinstance(geom, MultiLineString):
                lines = list(geom.geoms)
            elif isinstance(geom, LineString):
                lines = [geom]

            for line in lines:
                if line.length < 1.0:
                    continue
                results.append({
                    "geom_wkt": line.wkt,
                    "layer_type": layer_type,
                    "name": name,
                    "length_m": round(line.length, 1),
                })

    logger.info(f"Loaded {len(results)} BDOT stream features from {gpkg_path.name}")
    return results


def insert_bdot_streams(db_session, streams):
    """Insert BDOT10k linear hydro features into bdot_streams table.

    Full replace on each run (DELETE + INSERT).

    Returns number of inserted rows.
    """
    valid = [s for s in streams if s.get("layer_type") in VALID_BDOT_LINE_TYPES]
    if not valid:
        return 0

    raw_conn = db_session.connection().connection
    cursor = raw_conn.cursor()

    try:
        cursor.execute("DELETE FROM bdot_streams")
        cursor.execute("DROP TABLE IF EXISTS temp_bdot_import")
        cursor.execute("""
            CREATE TEMP TABLE temp_bdot_import (
                wkt TEXT,
                layer_type VARCHAR(10),
                name VARCHAR(200),
                length_m DOUBLE PRECISION
            )
        """)

        buf = io.StringIO()
        for s in valid:
            name = (s.get("name") or "").replace("\t", " ").replace("\n", " ")
            buf.write(f"{s['geom_wkt']}\t{s['layer_type']}\t{name}\t{s.get('length_m', 0)}\n")
        buf.seek(0)
        cursor.copy_expert(
            "COPY temp_bdot_import (wkt, layer_type, name, length_m) FROM STDIN WITH (FORMAT text)",
            buf,
        )

        cursor.execute("""
            INSERT INTO bdot_streams (geom, layer_type, name, length_m)
            SELECT
                ST_SetSRID(ST_GeomFromText(wkt), 2180),
                layer_type,
                NULLIF(name, ''),
                length_m
            FROM temp_bdot_import
        """)
        count = cursor.rowcount
        raw_conn.commit()
        logger.info(f"Inserted {count} BDOT streams into database")
        return count
    except Exception:
        raw_conn.rollback()
        raise


BDOT_BUFFER_M = 15.0
OVERLAP_THRESHOLD = 0.5


def update_stream_real_flags(db_session, threshold_m2, buffer_m=BDOT_BUFFER_M, overlap_threshold=OVERLAP_THRESHOLD):
    """Mark stream_network segments as real/overland based on BDOT overlap.

    Uses per-feature BDOT buffers with spatial join for efficient GIST-indexed
    matching.  Where multiple BDOT buffers overlap a single segment, ST_Union
    prevents double-counting before computing the overlap ratio.

    is_real_stream = true if overlap_ratio >= threshold, false otherwise.

    Returns dict with total/real/overland counts.
    """
    with override_statement_timeout(db_session, timeout_s=600):
        raw_conn = db_session.connection().connection
        cursor = raw_conn.cursor()

        try:
            # Step 1: Check if bdot_streams has data
            cursor.execute("SELECT COUNT(*) FROM bdot_streams")
            bdot_count = cursor.fetchone()[0]
            if bdot_count == 0:
                logger.warning("No BDOT streams in database — marking all as overland")
                cursor.execute(
                    "UPDATE stream_network SET is_real_stream = false WHERE threshold_m2 = %s",
                    (threshold_m2,),
                )
                raw_conn.commit()
                cursor.execute(
                    "SELECT COUNT(*) FROM stream_network WHERE threshold_m2 = %s",
                    (threshold_m2,),
                )
                total = cursor.fetchone()[0]
                return {"total": total, "real": 0, "overland": total}

            # Step 2: Materialize per-feature BDOT buffers (GIST-indexable)
            cursor.execute("DROP TABLE IF EXISTS temp_bdot_buffer")
            cursor.execute(
                "CREATE TEMP TABLE temp_bdot_buffer AS "
                "SELECT id, ST_Buffer(geom, %s) AS geom FROM bdot_streams",
                (buffer_m,),
            )
            cursor.execute("CREATE INDEX ON temp_bdot_buffer USING GIST (geom)")

            # Step 3: Spatial join + ST_Union to avoid double-counting
            # where multiple BDOT buffers overlap the same segment
            cursor.execute("""
                UPDATE stream_network sn
                SET is_real_stream = sub.is_real
                FROM (
                    SELECT
                        sn2.segment_idx,
                        (COALESCE(
                            ST_Length(ST_Intersection(sn2.geom, ST_Union(bb.geom)))
                            / NULLIF(ST_Length(sn2.geom), 0),
                            0
                        ) >= %s) AS is_real
                    FROM stream_network sn2
                    LEFT JOIN temp_bdot_buffer bb
                        ON ST_Intersects(sn2.geom, bb.geom)
                    WHERE sn2.threshold_m2 = %s
                    GROUP BY sn2.segment_idx, sn2.geom
                ) sub
                WHERE sn.threshold_m2 = %s
                  AND sn.segment_idx = sub.segment_idx
            """, (overlap_threshold, threshold_m2, threshold_m2))

            raw_conn.commit()

            # Count results
            cursor.execute("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE is_real_stream = true) AS real,
                    COUNT(*) FILTER (WHERE is_real_stream = false) AS overland
                FROM stream_network
                WHERE threshold_m2 = %s
            """, (threshold_m2,))
            row = cursor.fetchone()
            return {"total": row[0], "real": row[1], "overland": row[2]}

        except Exception:
            raw_conn.rollback()
            raise
