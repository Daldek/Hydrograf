"""
Bulk database operations using PostgreSQL COPY for flow_network,
stream_network, and stream_catchments tables.

Provides high-performance bulk INSERT via temp tables and COPY FROM.
"""

import io
import logging
from contextlib import contextmanager

import numpy as np

from core.hydrology import D8_DIRECTIONS

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


def create_flow_network_tsv(
    dem: np.ndarray,
    fdir: np.ndarray,
    acc: np.ndarray,
    slope: np.ndarray,
    metadata: dict,
    stream_threshold: int = 100,
    strahler: np.ndarray | None = None,
) -> tuple[io.StringIO, int, int]:
    """
    Create flow_network TSV buffer directly using vectorized numpy.

    Replaces per-cell Python loop with numpy array operations,
    reducing time from ~120s to ~5s and memory from ~490MB to ~200MB.

    Parameters
    ----------
    dem : np.ndarray
        DEM array
    fdir : np.ndarray
        Flow direction array
    acc : np.ndarray
        Flow accumulation array
    slope : np.ndarray
        Slope array (percent)
    metadata : dict
        Grid metadata (xllcorner, yllcorner, cellsize, nodata_value)
    stream_threshold : int
        Flow accumulation threshold for stream identification
    strahler : np.ndarray, optional
        Strahler stream order array (0 = non-stream)

    Returns
    -------
    tuple[io.StringIO, int, int]
        (tsv_buffer, n_records, n_stream_cells)
    """
    logger.info("Creating flow_network TSV (vectorized numpy)...")

    nrows, ncols = dem.shape
    cellsize = metadata["cellsize"]
    xll = metadata["xllcorner"]
    yll = metadata["yllcorner"]
    nodata = metadata["nodata_value"]
    cell_area = cellsize * cellsize

    # Check for potential ID overflow
    max_id = nrows * ncols
    if max_id > 2_000_000_000:
        logger.warning(
            f"Large raster ({nrows}x{ncols} = {max_id:,} cells) "
            f"may cause ID overflow."
        )

    # Valid cells mask
    valid = dem != nodata
    rows, cols = np.where(valid)
    n_valid = len(rows)

    # Cell IDs (1-based)
    cell_ids = rows * ncols + cols + 1

    # Coordinates (PL-1992)
    xs = xll + (cols + 0.5) * cellsize
    ys = yll + (nrows - rows - 0.5) * cellsize

    # Elevations, accumulations, slopes
    elevations = dem[rows, cols]
    accumulations = acc[rows, cols]
    slopes = slope[rows, cols]

    # Downstream IDs via D8 lookup arrays
    dr_lookup = np.zeros(256, dtype=np.int32)
    dc_lookup = np.zeros(256, dtype=np.int32)
    valid_d8 = np.zeros(256, dtype=np.bool_)
    for d, (di, dj) in D8_DIRECTIONS.items():
        dr_lookup[d] = di
        dc_lookup[d] = dj
        valid_d8[d] = True

    fdirs = fdir[rows, cols].astype(np.int32)
    # Clamp to [0, 255] for safe lookup
    fdirs_safe = np.clip(fdirs, 0, 255)
    has_valid_dir = valid_d8[fdirs_safe]

    ni = rows + dr_lookup[fdirs_safe]
    nj = cols + dc_lookup[fdirs_safe]

    # Bounds check
    in_bounds = (
        has_valid_dir
        & (ni >= 0) & (ni < nrows)
        & (nj >= 0) & (nj < ncols)
    )

    # Downstream nodata check (only where in bounds)
    ds_valid = np.zeros(n_valid, dtype=np.bool_)
    valid_idx = np.where(in_bounds)[0]
    ni_valid = ni[valid_idx]
    nj_valid = nj[valid_idx]
    ds_valid[valid_idx] = dem[ni_valid, nj_valid] != nodata

    # Downstream IDs
    downstream_ids = np.full(n_valid, -1, dtype=np.int64)
    has_ds = ds_valid
    downstream_ids[has_ds] = (
        ni[has_ds] * ncols + nj[has_ds] + 1
    )

    # Is stream
    is_stream = accumulations >= stream_threshold

    # Strahler values
    if strahler is not None:
        strahler_vals = strahler[rows, cols].astype(np.int32)
    else:
        strahler_vals = np.zeros(n_valid, dtype=np.int32)

    # Build TSV buffer
    logger.info(f"  Writing {n_valid:,} records to TSV buffer...")
    tsv_buffer = io.StringIO()
    for k in range(n_valid):
        ds_str = "" if downstream_ids[k] < 0 else str(
            int(downstream_ids[k])
        )
        is_stream_str = "t" if is_stream[k] else "f"
        strahler_str = (
            "" if strahler_vals[k] == 0
            else str(int(strahler_vals[k]))
        )
        tsv_buffer.write(
            f"{int(cell_ids[k])}\t"
            f"{xs[k]}\t{ys[k]}\t"
            f"{float(elevations[k])}\t"
            f"{int(accumulations[k])}\t"
            f"{float(slopes[k])}\t"
            f"{ds_str}\t{cell_area}\t"
            f"{is_stream_str}\t{strahler_str}\n"
        )

    tsv_buffer.seek(0)
    n_stream = int(np.sum(is_stream))
    logger.info(f"Created {n_valid:,} records")
    logger.info(
        f"Stream cells (acc >= {stream_threshold}): {n_stream:,}"
    )

    return tsv_buffer, n_valid, n_stream


def create_flow_network_records(
    dem: np.ndarray,
    fdir: np.ndarray,
    acc: np.ndarray,
    slope: np.ndarray,
    metadata: dict,
    stream_threshold: int = 100,
    strahler: np.ndarray | None = None,
) -> list:
    """
    Create flow_network records from raster data.

    Backward-compatible wrapper returning list[dict].
    For production use, prefer create_flow_network_tsv() which
    generates TSV directly without intermediate dict list.

    Parameters
    ----------
    dem : np.ndarray
        DEM array
    fdir : np.ndarray
        Flow direction array
    acc : np.ndarray
        Flow accumulation array
    slope : np.ndarray
        Slope array (percent)
    metadata : dict
        Grid metadata (xllcorner, yllcorner, cellsize, nodata_value)
    stream_threshold : int
        Flow accumulation threshold for stream identification
    strahler : np.ndarray, optional
        Strahler stream order array (0 = non-stream)

    Returns
    -------
    list
        List of dicts with flow_network fields
    """
    logger.info("Creating flow_network records...")

    nrows, ncols = dem.shape
    cellsize = metadata["cellsize"]
    xll = metadata["xllcorner"]
    yll = metadata["yllcorner"]
    nodata = metadata["nodata_value"]
    cell_area = cellsize * cellsize

    # Check for potential ID overflow
    max_id = nrows * ncols
    if max_id > 2_000_000_000:
        logger.warning(
            f"Large raster ({nrows}x{ncols} = {max_id:,} cells) "
            f"may cause ID overflow."
        )

    records = []

    def get_cell_index(row, col):
        return row * ncols + col + 1

    for i in range(nrows):
        for j in range(ncols):
            if dem[i, j] == nodata:
                continue

            x = xll + (j + 0.5) * cellsize
            y = yll + (nrows - i - 0.5) * cellsize
            cell_id = get_cell_index(i, j)

            downstream_id = None
            d = fdir[i, j]
            if d in D8_DIRECTIONS:
                di, dj = D8_DIRECTIONS[d]
                ni, nj = i + di, j + dj
                if (
                    0 <= ni < nrows
                    and 0 <= nj < ncols
                    and dem[ni, nj] != nodata
                ):
                    downstream_id = get_cell_index(ni, nj)

            strahler_val = None
            if strahler is not None and strahler[i, j] > 0:
                strahler_val = int(strahler[i, j])

            records.append(
                {
                    "id": cell_id,
                    "x": x,
                    "y": y,
                    "elevation": float(dem[i, j]),
                    "flow_accumulation": int(acc[i, j]),
                    "slope": float(slope[i, j]),
                    "downstream_id": downstream_id,
                    "cell_area": cell_area,
                    "is_stream": bool(
                        acc[i, j] >= stream_threshold
                    ),
                    "strahler_order": strahler_val,
                }
            )

    logger.info(f"Created {len(records)} records")
    stream_count = sum(1 for r in records if r["is_stream"])
    logger.info(
        f"Stream cells (acc >= {stream_threshold}): "
        f"{stream_count}"
    )

    return records


def insert_records_batch(
    db_session,
    records: list,
    batch_size: int = 10000,
    table_empty: bool = True,
) -> int:
    """
    Insert records into flow_network table using PostgreSQL COPY.

    Uses COPY FROM for bulk loading (20x faster than individual INSERTs).
    Temporarily disables indexes for faster insert, then rebuilds them.

    Parameters
    ----------
    db_session : Session
        SQLAlchemy database session
    records : list
        List of record dicts
    batch_size : int
        Number of records per batch (unused, kept for API compatibility)
    table_empty : bool
        If True, skip ON CONFLICT check (much faster for empty tables)
        If False, use ON CONFLICT DO UPDATE for upsert behavior

    Returns
    -------
    int
        Total records inserted
    """
    logger.info(f"Inserting {len(records):,} records using COPY (optimized)...")

    # Get raw connection for COPY operation
    raw_conn = db_session.connection().connection
    cursor = raw_conn.cursor()

    # Bulk import can take minutes — disable statement_timeout for this session
    cursor.execute("SET statement_timeout = 0")
    raw_conn.commit()

    # Phase 1: Disable indexes and FK for faster bulk insert
    logger.info("Phase 1: Preparing for bulk insert...")

    cursor.execute("DROP INDEX IF EXISTS idx_flow_geom")
    cursor.execute("DROP INDEX IF EXISTS idx_downstream")
    cursor.execute("DROP INDEX IF EXISTS idx_is_stream")
    cursor.execute("DROP INDEX IF EXISTS idx_flow_accumulation")
    cursor.execute("DROP INDEX IF EXISTS idx_strahler")
    cursor.execute(
        "ALTER TABLE flow_network"
        " DROP CONSTRAINT IF EXISTS"
        " flow_network_downstream_id_fkey"
    )
    raw_conn.commit()
    logger.info("  Indexes and FK constraint dropped")

    # Phase 2: Bulk insert using COPY
    logger.info("Phase 2: Bulk inserting records with COPY...")

    # Create temporary table for COPY
    cursor.execute("""
        CREATE TEMP TABLE temp_flow_import (
            id INT,
            x FLOAT,
            y FLOAT,
            elevation FLOAT,
            flow_accumulation INT,
            slope FLOAT,
            downstream_id INT,
            cell_area FLOAT,
            is_stream BOOLEAN,
            strahler_order SMALLINT
        )
    """)

    # Create TSV buffer
    tsv_buffer = io.StringIO()
    for r in records:
        downstream = (
            "" if r["downstream_id"] is None
            else str(r["downstream_id"])
        )
        is_stream = "t" if r["is_stream"] else "f"
        strahler = (
            "" if r.get("strahler_order") is None
            else str(r["strahler_order"])
        )
        tsv_buffer.write(
            f"{r['id']}\t{r['x']}\t{r['y']}\t"
            f"{r['elevation']}\t{r['flow_accumulation']}\t"
            f"{r['slope']}\t{downstream}\t{r['cell_area']}\t"
            f"{is_stream}\t{strahler}\n"
        )

    tsv_buffer.seek(0)

    # COPY to temp table
    cursor.copy_expert(
        "COPY temp_flow_import FROM STDIN"
        " WITH (FORMAT text, DELIMITER E'\\t', NULL '')",
        tsv_buffer,
    )
    logger.info(f"  COPY to temp table: {len(records):,} records")

    # Insert from temp table with geometry construction
    # When table is empty, skip ON CONFLICT for faster insert
    if table_empty:
        cursor.execute("""
            INSERT INTO flow_network (
                id, geom, elevation, flow_accumulation, slope,
                downstream_id, cell_area, is_stream,
                strahler_order
            )
            SELECT
                id, ST_SetSRID(ST_Point(x, y), 2180),
                elevation, flow_accumulation, slope,
                downstream_id, cell_area, is_stream,
                strahler_order
            FROM temp_flow_import
        """)
    else:
        cursor.execute("""
            INSERT INTO flow_network (
                id, geom, elevation, flow_accumulation, slope,
                downstream_id, cell_area, is_stream,
                strahler_order
            )
            SELECT
                id, ST_SetSRID(ST_Point(x, y), 2180),
                elevation, flow_accumulation, slope,
                downstream_id, cell_area, is_stream,
                strahler_order
            FROM temp_flow_import
            ON CONFLICT (id) DO UPDATE SET
                geom = EXCLUDED.geom,
                elevation = EXCLUDED.elevation,
                flow_accumulation = EXCLUDED.flow_accumulation,
                slope = EXCLUDED.slope,
                downstream_id = EXCLUDED.downstream_id,
                cell_area = EXCLUDED.cell_area,
                is_stream = EXCLUDED.is_stream,
                strahler_order = EXCLUDED.strahler_order
        """)

    total_inserted = cursor.rowcount
    raw_conn.commit()
    logger.info(f"  Inserted {total_inserted:,} records into flow_network")

    # Phase 3: Restore FK constraint and indexes
    logger.info("Phase 3: Restoring indexes and constraints...")

    cursor.execute("""
        ALTER TABLE flow_network
        ADD CONSTRAINT flow_network_downstream_id_fkey
        FOREIGN KEY (downstream_id) REFERENCES flow_network(id) ON DELETE SET NULL
    """)
    logger.info("  FK constraint restored")

    cursor.execute("CREATE INDEX idx_flow_geom ON flow_network USING GIST (geom)")
    logger.info("  Index idx_flow_geom created")

    cursor.execute("CREATE INDEX idx_downstream ON flow_network (downstream_id)")
    logger.info("  Index idx_downstream created")

    cursor.execute(
        "CREATE INDEX idx_is_stream ON flow_network (is_stream) WHERE is_stream = TRUE"
    )
    logger.info("  Index idx_is_stream created")

    cursor.execute(
        "CREATE INDEX idx_flow_accumulation"
        " ON flow_network (flow_accumulation)"
    )
    logger.info("  Index idx_flow_accumulation created")

    cursor.execute(
        "CREATE INDEX idx_strahler"
        " ON flow_network (strahler_order)"
        " WHERE strahler_order IS NOT NULL"
    )
    logger.info("  Index idx_strahler created")

    cursor.execute("ANALYZE flow_network")
    raw_conn.commit()
    logger.info("  ANALYZE completed")

    return total_inserted


def insert_records_batch_tsv(
    db_session,
    tsv_buffer: io.StringIO,
    n_records: int,
    table_empty: bool = True,
) -> int:
    """
    Insert flow_network records from pre-built TSV buffer.

    Accepts TSV buffer directly from create_flow_network_tsv(),
    eliminating the intermediate list[dict] step.

    Parameters
    ----------
    db_session : Session
        SQLAlchemy database session
    tsv_buffer : io.StringIO
        TSV buffer with flow_network records
    n_records : int
        Number of records in the buffer
    table_empty : bool
        If True, skip ON CONFLICT check

    Returns
    -------
    int
        Total records inserted
    """
    logger.info(
        f"Inserting {n_records:,} records using COPY "
        f"(TSV direct)..."
    )

    raw_conn = db_session.connection().connection
    cursor = raw_conn.cursor()

    # Disable statement_timeout for bulk import
    cursor.execute("SET statement_timeout = 0")
    raw_conn.commit()

    # Phase 1: Drop indexes
    logger.info("Phase 1: Preparing for bulk insert...")
    cursor.execute("DROP INDEX IF EXISTS idx_flow_geom")
    cursor.execute("DROP INDEX IF EXISTS idx_downstream")
    cursor.execute("DROP INDEX IF EXISTS idx_is_stream")
    cursor.execute("DROP INDEX IF EXISTS idx_flow_accumulation")
    cursor.execute("DROP INDEX IF EXISTS idx_strahler")
    cursor.execute(
        "ALTER TABLE flow_network"
        " DROP CONSTRAINT IF EXISTS"
        " flow_network_downstream_id_fkey"
    )
    raw_conn.commit()
    logger.info("  Indexes and FK constraint dropped")

    # Phase 2: COPY directly from TSV buffer
    logger.info("Phase 2: Bulk inserting records with COPY...")
    cursor.execute("""
        CREATE TEMP TABLE temp_flow_import (
            id INT,
            x FLOAT,
            y FLOAT,
            elevation FLOAT,
            flow_accumulation INT,
            slope FLOAT,
            downstream_id INT,
            cell_area FLOAT,
            is_stream BOOLEAN,
            strahler_order SMALLINT
        )
    """)

    tsv_buffer.seek(0)
    cursor.copy_expert(
        "COPY temp_flow_import FROM STDIN"
        " WITH (FORMAT text, DELIMITER E'\\t', NULL '')",
        tsv_buffer,
    )
    logger.info(f"  COPY to temp table: {n_records:,} records")

    # Insert from temp table
    if table_empty:
        cursor.execute("""
            INSERT INTO flow_network (
                id, geom, elevation, flow_accumulation, slope,
                downstream_id, cell_area, is_stream,
                strahler_order
            )
            SELECT
                id, ST_SetSRID(ST_Point(x, y), 2180),
                elevation, flow_accumulation, slope,
                downstream_id, cell_area, is_stream,
                strahler_order
            FROM temp_flow_import
        """)
    else:
        cursor.execute("""
            INSERT INTO flow_network (
                id, geom, elevation, flow_accumulation, slope,
                downstream_id, cell_area, is_stream,
                strahler_order
            )
            SELECT
                id, ST_SetSRID(ST_Point(x, y), 2180),
                elevation, flow_accumulation, slope,
                downstream_id, cell_area, is_stream,
                strahler_order
            FROM temp_flow_import
            ON CONFLICT (id) DO UPDATE SET
                geom = EXCLUDED.geom,
                elevation = EXCLUDED.elevation,
                flow_accumulation = EXCLUDED.flow_accumulation,
                slope = EXCLUDED.slope,
                downstream_id = EXCLUDED.downstream_id,
                cell_area = EXCLUDED.cell_area,
                is_stream = EXCLUDED.is_stream,
                strahler_order = EXCLUDED.strahler_order
        """)

    total_inserted = cursor.rowcount
    raw_conn.commit()
    logger.info(
        f"  Inserted {total_inserted:,} records into flow_network"
    )

    # Phase 3: Restore indexes
    logger.info("Phase 3: Restoring indexes and constraints...")
    cursor.execute("""
        ALTER TABLE flow_network
        ADD CONSTRAINT flow_network_downstream_id_fkey
        FOREIGN KEY (downstream_id)
        REFERENCES flow_network(id) ON DELETE SET NULL
    """)
    logger.info("  FK constraint restored")

    cursor.execute(
        "CREATE INDEX idx_flow_geom"
        " ON flow_network USING GIST (geom)"
    )
    logger.info("  Index idx_flow_geom created")

    cursor.execute(
        "CREATE INDEX idx_downstream"
        " ON flow_network (downstream_id)"
    )
    logger.info("  Index idx_downstream created")

    cursor.execute(
        "CREATE INDEX idx_is_stream"
        " ON flow_network (is_stream)"
        " WHERE is_stream = TRUE"
    )
    logger.info("  Index idx_is_stream created")

    cursor.execute(
        "CREATE INDEX idx_flow_accumulation"
        " ON flow_network (flow_accumulation)"
    )
    logger.info("  Index idx_flow_accumulation created")

    cursor.execute(
        "CREATE INDEX idx_strahler"
        " ON flow_network (strahler_order)"
        " WHERE strahler_order IS NOT NULL"
    )
    logger.info("  Index idx_strahler created")

    cursor.execute("ANALYZE flow_network")
    raw_conn.commit()
    logger.info("  ANALYZE completed")

    return total_inserted


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
            threshold_m2 INT
        )
    """)

    # Build TSV
    tsv_buffer = io.StringIO()
    for seg in segments:
        coords_wkt = ", ".join(
            f"{x} {y}" for x, y in seg["coords"]
        )
        wkt = f"LINESTRING({coords_wkt})"
        tsv_buffer.write(
            f"{wkt}\t{seg['strahler_order']}\t"
            f"{seg['length_m']}\t{seg['upstream_area_km2']}\t"
            f"{seg['mean_slope_percent']}\tDEM_DERIVED\t"
            f"{threshold_m2}\n"
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
            threshold_m2
        )
        SELECT
            ST_SetSRID(ST_GeomFromText(wkt), 2180),
            strahler_order, length_m,
            upstream_area_km2, mean_slope_percent, source,
            threshold_m2
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
            strahler_order INT
        )
    """)

    # Build TSV
    tsv_buffer = io.StringIO()
    for cat in catchments:
        elev = cat["mean_elevation_m"]
        slp = cat["mean_slope_percent"]
        mean_elev = "" if elev is None else str(elev)
        mean_slp = "" if slp is None else str(slp)
        strahler = "" if cat["strahler_order"] is None else str(cat["strahler_order"])
        tsv_buffer.write(
            f"{cat['wkt']}\t{cat['segment_idx']}\t"
            f"{threshold_m2}\t{cat['area_km2']}\t"
            f"{mean_elev}\t{mean_slp}\t{strahler}\n"
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
            strahler_order
        )
        SELECT
            ST_SetSRID(ST_GeomFromText(wkt), 2180),
            segment_idx, threshold_m2,
            area_km2, mean_elevation_m, mean_slope_percent,
            strahler_order
        FROM temp_catchments_import
    """)

    total = cursor.rowcount
    raw_conn.commit()
    logger.info(f"  Inserted {total} sub-catchments")

    return total
