"""
Script to process DEM (Digital Elevation Model) and populate flow_network table.

Reads ASCII GRID DEM file, computes hydrological parameters (flow direction,
flow accumulation, slope), and loads data into PostgreSQL/PostGIS.

Usage
-----
    cd backend
    python -m scripts.process_dem --help
    python -m scripts.process_dem --input ../data/nmt/N-33-131-D-a-3-2.asc

Examples
--------
    # Process single DEM tile
    python -m scripts.process_dem \\
        --input ../data/nmt/N-33-131-D-a-3-2.asc \\
        --stream-threshold 100

    # Dry run (only show statistics)
    python -m scripts.process_dem \\
        --input ../data/nmt/N-33-131-D-a-3-2.asc \\
        --dry-run

    # Process with custom batch size
    python -m scripts.process_dem \\
        --input ../data/nmt/N-33-131-D-a-3-2.asc \\
        --batch-size 50000
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Tuple, Optional

import numpy as np
from pyproj import CRS
from sqlalchemy import text

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# D8 flow direction encoding (pysheds default)
# Direction values and their (row_offset, col_offset) for downstream cell
D8_DIRECTIONS = {
    1: (0, 1),    # E
    2: (1, 1),    # SE
    4: (1, 0),    # S
    8: (1, -1),   # SW
    16: (0, -1),  # W
    32: (-1, -1), # NW
    64: (-1, 0),  # N
    128: (-1, 1), # NE
}


def save_raster_geotiff(
    data: np.ndarray,
    metadata: dict,
    output_path: Path,
    nodata: float = -9999.0,
    dtype: str = 'float32',
) -> None:
    """
    Save numpy array as GeoTIFF with PL-1992 (EPSG:2180) CRS.

    Parameters
    ----------
    data : np.ndarray
        Raster data array
    metadata : dict
        Grid metadata with xllcorner, yllcorner, cellsize
    output_path : Path
        Output GeoTIFF path
    nodata : float
        NoData value
    dtype : str
        Output data type ('float32', 'int32', 'int16')
    """
    import rasterio
    from rasterio.transform import from_bounds

    nrows, ncols = data.shape
    cellsize = metadata['cellsize']
    xll = metadata['xllcorner']
    yll = metadata['yllcorner']

    # Calculate bounds
    xmin = xll
    ymin = yll
    xmax = xll + ncols * cellsize
    ymax = yll + nrows * cellsize

    transform = from_bounds(xmin, ymin, xmax, ymax, ncols, nrows)

    # Map dtype string to numpy/rasterio dtype
    dtype_map = {
        'float32': (np.float32, rasterio.float32),
        'float64': (np.float64, rasterio.float64),
        'int32': (np.int32, rasterio.int32),
        'int16': (np.int16, rasterio.int16),
        'uint8': (np.uint8, rasterio.uint8),
    }

    np_dtype, rio_dtype = dtype_map.get(dtype, (np.float32, rasterio.float32))

    # Prepare data (flip vertically because ASCII GRID is top-down)
    out_data = data.astype(np_dtype)

    with rasterio.open(
        output_path,
        'w',
        driver='GTiff',
        height=nrows,
        width=ncols,
        count=1,
        dtype=rio_dtype,
        crs='EPSG:2180',
        transform=transform,
        nodata=nodata,
        compress='lzw',
    ) as dst:
        dst.write(out_data, 1)

    logger.info(f"Saved: {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")


def read_ascii_grid(filepath: Path) -> Tuple[np.ndarray, dict]:
    """
    Read ARC/INFO ASCII GRID file.

    Supports both corner (xllcorner/yllcorner) and center (xllcenter/yllcenter)
    coordinate formats. Center coordinates are converted to corner.

    Parameters
    ----------
    filepath : Path
        Path to .asc file

    Returns
    -------
    tuple
        (data array, metadata dict with ncols, nrows, xllcorner, yllcorner, cellsize, nodata)

    Raises
    ------
    FileNotFoundError
        If file does not exist
    ValueError
        If file format is invalid
    """
    if not filepath.exists():
        raise FileNotFoundError(f"DEM file not found: {filepath}")

    metadata = {}
    header_lines = 6

    with open(filepath, 'r') as f:
        # Read header
        for i in range(header_lines):
            line = f.readline().strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].lower()
                value = parts[1]
                if key in ('ncols', 'nrows'):
                    metadata[key] = int(value)
                elif key in ('xllcorner', 'yllcorner', 'xllcenter', 'yllcenter',
                             'cellsize', 'nodata_value'):
                    metadata[key] = float(value)

    # Handle center vs corner coordinates
    # If center is provided, convert to corner
    if 'xllcenter' in metadata and 'xllcorner' not in metadata:
        metadata['xllcorner'] = metadata['xllcenter'] - metadata.get('cellsize', 0) / 2
        logger.info("Converted xllcenter to xllcorner")
    if 'yllcenter' in metadata and 'yllcorner' not in metadata:
        metadata['yllcorner'] = metadata['yllcenter'] - metadata.get('cellsize', 0) / 2
        logger.info("Converted yllcenter to yllcorner")

    # Validate required fields
    required = ['ncols', 'nrows', 'xllcorner', 'yllcorner', 'cellsize']
    for field in required:
        if field not in metadata:
            raise ValueError(f"Missing required header field: {field}")

    # Set default nodata if not present
    if 'nodata_value' not in metadata:
        metadata['nodata_value'] = -9999.0

    # Read data
    data = np.loadtxt(filepath, skiprows=header_lines)

    if data.shape != (metadata['nrows'], metadata['ncols']):
        raise ValueError(
            f"Data shape {data.shape} doesn't match header "
            f"({metadata['nrows']}, {metadata['ncols']})"
        )

    logger.info(f"Read DEM: {metadata['nrows']}x{metadata['ncols']} cells")
    logger.info(f"Origin: ({metadata['xllcorner']:.1f}, {metadata['yllcorner']:.1f})")
    logger.info(f"Cell size: {metadata['cellsize']} m")

    return data, metadata


def fill_depressions(dem: np.ndarray, nodata: float) -> np.ndarray:
    """
    Fill depressions (sinks) in DEM using priority flood algorithm.

    Parameters
    ----------
    dem : np.ndarray
        Input DEM array
    nodata : float
        NoData value

    Returns
    -------
    np.ndarray
        Filled DEM
    """
    from scipy import ndimage

    logger.info("Filling depressions...")

    filled = dem.copy()
    mask = dem != nodata

    # Simple iterative filling - raise cells until no internal sinks
    # This is a basic implementation; pysheds has better algorithm
    max_iterations = 1000
    for iteration in range(max_iterations):
        # Find local minima (sinks)
        local_min = ndimage.minimum_filter(filled, size=3, mode='constant', cval=np.inf)
        sinks = (filled == local_min) & mask

        # Check neighbors for lower cells
        neighbors_min = ndimage.minimum_filter(filled, size=3, mode='constant', cval=np.inf)

        # Find cells that are sinks but not on edge
        edge_mask = np.zeros_like(mask)
        edge_mask[0, :] = True
        edge_mask[-1, :] = True
        edge_mask[:, 0] = True
        edge_mask[:, -1] = True

        internal_sinks = sinks & ~edge_mask & mask

        if not np.any(internal_sinks):
            break

        # Raise internal sinks to minimum neighbor + small epsilon
        for i, j in zip(*np.where(internal_sinks)):
            neighbors = []
            for di in [-1, 0, 1]:
                for dj in [-1, 0, 1]:
                    if di == 0 and dj == 0:
                        continue
                    ni, nj = i + di, j + dj
                    if 0 <= ni < filled.shape[0] and 0 <= nj < filled.shape[1]:
                        if filled[ni, nj] != nodata:
                            neighbors.append(filled[ni, nj])
            if neighbors:
                min_neighbor = min(neighbors)
                if filled[i, j] < min_neighbor:
                    filled[i, j] = min_neighbor + 0.001

    logger.info(f"Depression filling completed after {iteration + 1} iterations")
    return filled


def compute_flow_direction(dem: np.ndarray, nodata: float) -> np.ndarray:
    """
    Compute D8 flow direction.

    Parameters
    ----------
    dem : np.ndarray
        Filled DEM array
    nodata : float
        NoData value

    Returns
    -------
    np.ndarray
        Flow direction array (D8 encoding)
    """
    logger.info("Computing flow direction (D8)...")

    nrows, ncols = dem.shape
    fdir = np.zeros((nrows, ncols), dtype=np.int16)

    # D8 directions: E, SE, S, SW, W, NW, N, NE
    directions = [1, 2, 4, 8, 16, 32, 64, 128]
    offsets = [(0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1)]
    # Diagonal distance is sqrt(2) times cell size
    distances = [1, 1.414, 1, 1.414, 1, 1.414, 1, 1.414]

    for i in range(nrows):
        for j in range(ncols):
            if dem[i, j] == nodata:
                fdir[i, j] = 0
                continue

            max_slope = 0
            flow_dir = 0

            for d, (di, dj), dist in zip(directions, offsets, distances):
                ni, nj = i + di, j + dj

                if 0 <= ni < nrows and 0 <= nj < ncols:
                    if dem[ni, nj] != nodata:
                        slope = (dem[i, j] - dem[ni, nj]) / dist
                        if slope > max_slope:
                            max_slope = slope
                            flow_dir = d

            fdir[i, j] = flow_dir

    logger.info("Flow direction computed")
    return fdir


def compute_flow_accumulation(fdir: np.ndarray) -> np.ndarray:
    """
    Compute flow accumulation from flow direction.

    Parameters
    ----------
    fdir : np.ndarray
        Flow direction array (D8 encoding)

    Returns
    -------
    np.ndarray
        Flow accumulation array (number of upstream cells)
    """
    logger.info("Computing flow accumulation...")

    nrows, ncols = fdir.shape
    acc = np.ones((nrows, ncols), dtype=np.int32)

    # Count how many cells flow into each cell
    inflow_count = np.zeros((nrows, ncols), dtype=np.int32)

    for i in range(nrows):
        for j in range(ncols):
            d = fdir[i, j]
            if d in D8_DIRECTIONS:
                di, dj = D8_DIRECTIONS[d]
                ni, nj = i + di, j + dj
                if 0 <= ni < nrows and 0 <= nj < ncols:
                    inflow_count[ni, nj] += 1

    # Process cells in topological order (cells with no inflow first)
    # Use a queue-based approach
    from collections import deque

    queue = deque()

    # Initialize queue with cells that have no inflow
    for i in range(nrows):
        for j in range(ncols):
            if inflow_count[i, j] == 0 and fdir[i, j] != 0:
                queue.append((i, j))

    processed = 0
    while queue:
        i, j = queue.popleft()
        processed += 1

        d = fdir[i, j]
        if d in D8_DIRECTIONS:
            di, dj = D8_DIRECTIONS[d]
            ni, nj = i + di, j + dj

            if 0 <= ni < nrows and 0 <= nj < ncols:
                acc[ni, nj] += acc[i, j]
                inflow_count[ni, nj] -= 1

                if inflow_count[ni, nj] == 0:
                    queue.append((ni, nj))

    logger.info(f"Flow accumulation computed ({processed} cells processed)")
    return acc


def compute_slope(dem: np.ndarray, cellsize: float, nodata: float) -> np.ndarray:
    """
    Compute slope in percent.

    Parameters
    ----------
    dem : np.ndarray
        DEM array
    cellsize : float
        Cell size in meters
    nodata : float
        NoData value

    Returns
    -------
    np.ndarray
        Slope array in percent
    """
    logger.info("Computing slope...")

    # Use Sobel operator for gradient
    from scipy import ndimage

    # Replace nodata with nan for calculations
    dem_calc = dem.astype(np.float64)
    dem_calc[dem == nodata] = np.nan

    # Compute gradients
    dy = ndimage.sobel(dem_calc, axis=0, mode='constant', cval=np.nan) / (8 * cellsize)
    dx = ndimage.sobel(dem_calc, axis=1, mode='constant', cval=np.nan) / (8 * cellsize)

    # Slope in percent
    slope = np.sqrt(dx**2 + dy**2) * 100

    # Replace nan with 0
    slope = np.nan_to_num(slope, nan=0.0)

    logger.info(f"Slope computed (range: {slope.min():.1f}% - {slope.max():.1f}%)")
    return slope


def create_flow_network_records(
    dem: np.ndarray,
    fdir: np.ndarray,
    acc: np.ndarray,
    slope: np.ndarray,
    metadata: dict,
    stream_threshold: int = 100,
) -> list:
    """
    Create flow_network records from raster data.

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

    Returns
    -------
    list
        List of dicts with flow_network fields
    """
    logger.info("Creating flow_network records...")

    nrows, ncols = dem.shape
    cellsize = metadata['cellsize']
    xll = metadata['xllcorner']
    yll = metadata['yllcorner']
    nodata = metadata['nodata_value']
    cell_area = cellsize * cellsize

    records = []

    # Create index map for downstream_id lookup
    # Index = row * ncols + col + 1 (1-based for DB)
    def get_cell_index(row, col):
        return row * ncols + col + 1

    for i in range(nrows):
        for j in range(ncols):
            if dem[i, j] == nodata:
                continue

            # Cell center coordinates (PL-1992)
            # Note: ASCII GRID has origin at lower-left, row 0 is top
            x = xll + (j + 0.5) * cellsize
            y = yll + (nrows - i - 0.5) * cellsize

            cell_id = get_cell_index(i, j)

            # Find downstream cell
            downstream_id = None
            d = fdir[i, j]
            if d in D8_DIRECTIONS:
                di, dj = D8_DIRECTIONS[d]
                ni, nj = i + di, j + dj
                if 0 <= ni < nrows and 0 <= nj < ncols:
                    if dem[ni, nj] != nodata:
                        downstream_id = get_cell_index(ni, nj)

            records.append({
                'id': cell_id,
                'x': x,
                'y': y,
                'elevation': float(dem[i, j]),
                'flow_accumulation': int(acc[i, j]),
                'slope': float(slope[i, j]),
                'downstream_id': downstream_id,
                'cell_area': cell_area,
                'is_stream': bool(acc[i, j] >= stream_threshold),
            })

    logger.info(f"Created {len(records)} records")
    stream_count = sum(1 for r in records if r['is_stream'])
    logger.info(f"Stream cells (acc >= {stream_threshold}): {stream_count}")

    return records


def insert_records_batch(db_session, records: list, batch_size: int = 10000) -> int:
    """
    Insert records into flow_network table in batches.

    Due to self-referential FK constraint on downstream_id, we first insert
    all records with downstream_id=NULL, then update downstream_id separately.

    Parameters
    ----------
    db_session : Session
        SQLAlchemy database session
    records : list
        List of record dicts
    batch_size : int
        Number of records per batch

    Returns
    -------
    int
        Total records inserted
    """
    logger.info(f"Inserting {len(records)} records (batch size: {batch_size})...")

    # Phase 1: Insert all records with downstream_id = NULL
    logger.info("Phase 1: Inserting records without downstream_id...")
    total_inserted = 0

    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]

        for record in batch:
            try:
                db_session.execute(
                    text("""
                        INSERT INTO flow_network
                            (id, geom, elevation, flow_accumulation, slope,
                             downstream_id, cell_area, is_stream)
                        VALUES
                            (:id, ST_SetSRID(ST_Point(:x, :y), 2180), :elevation,
                             :flow_accumulation, :slope, NULL, :cell_area, :is_stream)
                        ON CONFLICT (id) DO UPDATE SET
                            geom = EXCLUDED.geom,
                            elevation = EXCLUDED.elevation,
                            flow_accumulation = EXCLUDED.flow_accumulation,
                            slope = EXCLUDED.slope,
                            cell_area = EXCLUDED.cell_area,
                            is_stream = EXCLUDED.is_stream
                    """),
                    record,
                )
                total_inserted += 1
            except Exception as e:
                logger.error(f"Failed to insert record {record['id']}: {e}")

        db_session.commit()
        logger.info(f"Inserted batch {i // batch_size + 1}: {total_inserted} total")

    # Phase 2: Update downstream_id for all records
    logger.info("Phase 2: Updating downstream_id references...")
    updates_done = 0

    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]

        for record in batch:
            if record['downstream_id'] is not None:
                try:
                    db_session.execute(
                        text("""
                            UPDATE flow_network
                            SET downstream_id = :downstream_id
                            WHERE id = :id
                        """),
                        {'id': record['id'], 'downstream_id': record['downstream_id']},
                    )
                    updates_done += 1
                except Exception as e:
                    logger.error(f"Failed to update downstream_id for record {record['id']}: {e}")

        db_session.commit()

    logger.info(f"Updated {updates_done} downstream_id references")

    return total_inserted


def process_dem(
    input_path: Path,
    stream_threshold: int = 100,
    batch_size: int = 10000,
    dry_run: bool = False,
    save_intermediates: bool = False,
    output_dir: Optional[Path] = None,
) -> dict:
    """
    Process DEM file and load into flow_network table.

    Parameters
    ----------
    input_path : Path
        Path to input ASCII GRID file
    stream_threshold : int
        Flow accumulation threshold for stream identification
    batch_size : int
        Database insert batch size
    dry_run : bool
        If True, only compute statistics without inserting
    save_intermediates : bool
        If True, save intermediate rasters as GeoTIFF
    output_dir : Path, optional
        Output directory for intermediate files (default: same as input)

    Returns
    -------
    dict
        Processing statistics
    """
    stats = {}

    # Setup output directory for intermediates
    if output_dir is None:
        output_dir = input_path.parent
    output_dir = Path(output_dir)
    base_name = input_path.stem

    # 1. Read DEM
    dem, metadata = read_ascii_grid(input_path)
    stats['ncols'] = metadata['ncols']
    stats['nrows'] = metadata['nrows']
    stats['cellsize'] = metadata['cellsize']
    stats['total_cells'] = metadata['ncols'] * metadata['nrows']

    nodata = metadata['nodata_value']
    valid_cells = np.sum(dem != nodata)
    stats['valid_cells'] = int(valid_cells)

    # Save original DEM as GeoTIFF
    if save_intermediates:
        save_raster_geotiff(
            dem, metadata,
            output_dir / f"{base_name}_01_dem.tif",
            nodata=nodata, dtype='float32'
        )

    # 2. Fill depressions
    filled_dem = fill_depressions(dem, nodata)

    if save_intermediates:
        save_raster_geotiff(
            filled_dem, metadata,
            output_dir / f"{base_name}_02_filled.tif",
            nodata=nodata, dtype='float32'
        )

    # 3. Compute flow direction
    fdir = compute_flow_direction(filled_dem, nodata)

    if save_intermediates:
        save_raster_geotiff(
            fdir, metadata,
            output_dir / f"{base_name}_03_flowdir.tif",
            nodata=0, dtype='int16'
        )

    # 4. Compute flow accumulation
    acc = compute_flow_accumulation(fdir)
    stats['max_accumulation'] = int(acc.max())

    if save_intermediates:
        save_raster_geotiff(
            acc, metadata,
            output_dir / f"{base_name}_04_flowacc.tif",
            nodata=0, dtype='int32'
        )

    # 5. Compute slope
    slope = compute_slope(filled_dem, metadata['cellsize'], nodata)
    stats['mean_slope'] = float(np.mean(slope[dem != nodata]))

    if save_intermediates:
        save_raster_geotiff(
            slope, metadata,
            output_dir / f"{base_name}_05_slope.tif",
            nodata=-1, dtype='float32'
        )

    # 6. Create stream mask
    stream_mask = (acc >= stream_threshold).astype(np.uint8)
    if save_intermediates:
        save_raster_geotiff(
            stream_mask, metadata,
            output_dir / f"{base_name}_06_streams.tif",
            nodata=255, dtype='uint8'
        )

    # 7. Create records
    records = create_flow_network_records(
        filled_dem, fdir, acc, slope, metadata, stream_threshold
    )
    stats['records'] = len(records)
    stats['stream_cells'] = sum(1 for r in records if r['is_stream'])

    # 8. Insert into database
    if not dry_run:
        from core.database import get_db_session

        with get_db_session() as db:
            # Clear existing data (optional - can be removed for append mode)
            logger.info("Clearing existing flow_network data...")
            db.execute(text("TRUNCATE TABLE flow_network CASCADE"))
            db.commit()

            inserted = insert_records_batch(db, records, batch_size)
            stats['inserted'] = inserted
    else:
        logger.info("Dry run - skipping database insert")
        stats['inserted'] = 0

    return stats


def main():
    """Main entry point for DEM processing script."""
    parser = argparse.ArgumentParser(
        description="Process DEM and populate flow_network table",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        required=True,
        help="Path to input ASCII GRID (.asc) file",
    )
    parser.add_argument(
        "--stream-threshold",
        type=int,
        default=100,
        help="Flow accumulation threshold for stream (default: 100)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10000,
        help="Database insert batch size (default: 10000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only compute statistics without database insert",
    )
    parser.add_argument(
        "--save-intermediates", "-s",
        action="store_true",
        help="Save intermediate rasters as GeoTIFF (for QGIS verification)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default=None,
        help="Output directory for intermediate files (default: same as input)",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output_dir) if args.output_dir else None

    logger.info("=" * 60)
    logger.info("DEM Processing Script")
    logger.info("=" * 60)
    logger.info(f"Input: {input_path}")
    logger.info(f"Stream threshold: {args.stream_threshold}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Save intermediates: {args.save_intermediates}")
    if output_dir:
        logger.info(f"Output dir: {output_dir}")
    logger.info("=" * 60)

    start_time = time.time()

    try:
        stats = process_dem(
            input_path,
            stream_threshold=args.stream_threshold,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            save_intermediates=args.save_intermediates,
            output_dir=output_dir,
        )
    except FileNotFoundError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        raise

    elapsed = time.time() - start_time

    logger.info("=" * 60)
    logger.info("Processing complete!")
    logger.info(f"  Grid size: {stats['ncols']} x {stats['nrows']}")
    logger.info(f"  Cell size: {stats['cellsize']} m")
    logger.info(f"  Total cells: {stats['total_cells']:,}")
    logger.info(f"  Valid cells: {stats['valid_cells']:,}")
    logger.info(f"  Max accumulation: {stats['max_accumulation']:,}")
    logger.info(f"  Mean slope: {stats['mean_slope']:.1f}%")
    logger.info(f"  Stream cells: {stats['stream_cells']:,}")
    logger.info(f"  Records created: {stats['records']:,}")
    logger.info(f"  Records inserted: {stats['inserted']:,}")
    logger.info(f"  Time elapsed: {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
