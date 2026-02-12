"""
Stream network vectorization and sub-catchment delineation.

Traces connected stream cells from headwaters downstream, creates
LineString segments, delineates sub-catchments using pyflwdir basins,
and polygonizes sub-catchment labels.
"""

import logging
from collections import defaultdict

import numpy as np

from core.hydrology import D8_DIRECTIONS

logger = logging.getLogger(__name__)


def vectorize_streams(
    dem: np.ndarray,
    fdir: np.ndarray,
    acc: np.ndarray,
    slope: np.ndarray,
    strahler: np.ndarray,
    metadata: dict,
    stream_threshold: int = 100,
    label_raster_out: np.ndarray | None = None,
) -> list[dict]:
    """
    Vectorize stream network from raster data as LineString segments.

    Traces connected stream cells from headwaters downstream to junctions
    or outlets. Each segment becomes a LineString with attributes.

    Parameters
    ----------
    dem : np.ndarray
        Filled DEM array
    fdir : np.ndarray
        Flow direction array (D8 encoding)
    acc : np.ndarray
        Flow accumulation array
    slope : np.ndarray
        Slope array (percent)
    strahler : np.ndarray
        Strahler stream order array (0 = non-stream)
    metadata : dict
        Grid metadata (xllcorner, yllcorner, cellsize, nodata_value)
    stream_threshold : int
        Flow accumulation threshold for stream identification
    label_raster_out : np.ndarray, optional
        Pre-allocated int32 array (same shape as dem). When provided,
        stream cells are painted with their 1-based segment index.
        Used by delineate_subcatchments() to seed downstream tracing.

    Returns
    -------
    list[dict]
        List of stream segment dicts with keys:
        - coords: list of (x, y) tuples
        - strahler_order: int
        - length_m: float
        - upstream_area_km2: float (at segment end)
        - mean_slope_percent: float
    """
    logger.info("Vectorizing stream network...")

    nrows, ncols = dem.shape
    cellsize = metadata["cellsize"]
    xll = metadata["xllcorner"]
    yll = metadata["yllcorner"]
    nodata = metadata["nodata_value"]
    cell_area = cellsize * cellsize

    stream_mask = (acc >= stream_threshold) & (dem != nodata)

    def cell_xy(row, col):
        """Get cell center coordinates in PL-1992."""
        x = xll + (col + 0.5) * cellsize
        y = yll + (nrows - row - 0.5) * cellsize
        return (x, y)

    def downstream_cell(row, col):
        """Get downstream cell (row, col) or None."""
        d = fdir[row, col]
        if d not in D8_DIRECTIONS:
            return None
        di, dj = D8_DIRECTIONS[d]
        ni, nj = row + di, col + dj
        if 0 <= ni < nrows and 0 <= nj < ncols and dem[ni, nj] != nodata:
            return (ni, nj)
        return None

    # Count upstream stream neighbors for each cell
    upstream_count = np.zeros((nrows, ncols), dtype=np.int32)
    for i in range(nrows):
        for j in range(ncols):
            if not stream_mask[i, j]:
                continue
            ds = downstream_cell(i, j)
            if ds is not None and stream_mask[ds[0], ds[1]]:
                upstream_count[ds[0], ds[1]] += 1

    # Headwaters: stream cells with no upstream stream neighbors
    headwaters = []
    for i in range(nrows):
        for j in range(ncols):
            if stream_mask[i, j] and upstream_count[i, j] == 0:
                headwaters.append((i, j))

    logger.info(f"  Found {len(headwaters)} headwater cells")

    # Trace segments from headwaters
    visited = np.zeros((nrows, ncols), dtype=bool)
    segments = []

    for hw_row, hw_col in headwaters:
        row, col = hw_row, hw_col

        while True:
            if visited[row, col]:
                break

            # Start new segment
            coords = [cell_xy(row, col)]
            slopes = [float(slope[row, col])]
            seg_order = max(int(strahler[row, col]), 1)
            length_m = 0.0
            visited[row, col] = True
            seg_rc_path = [(row, col)]

            # Trace downstream while same order
            while True:
                ds = downstream_cell(row, col)
                if ds is None:
                    break
                nr, nc = ds
                if not stream_mask[nr, nc]:
                    break
                if visited[nr, nc]:
                    # Add final point for connection
                    coords.append(cell_xy(nr, nc))
                    dist = (
                        (coords[-1][0] - coords[-2][0]) ** 2
                        + (coords[-1][1] - coords[-2][1]) ** 2
                    ) ** 0.5
                    length_m += dist
                    break

                next_order = max(int(strahler[nr, nc]), 1)
                if next_order != seg_order:
                    # Order changes: end segment, add junction pt
                    coords.append(cell_xy(nr, nc))
                    dist = (
                        (coords[-1][0] - coords[-2][0]) ** 2
                        + (coords[-1][1] - coords[-2][1]) ** 2
                    ) ** 0.5
                    length_m += dist
                    break

                visited[nr, nc] = True
                seg_rc_path.append((nr, nc))
                new_pt = cell_xy(nr, nc)
                dist = (
                    (new_pt[0] - coords[-1][0]) ** 2
                    + (new_pt[1] - coords[-1][1]) ** 2
                ) ** 0.5
                length_m += dist
                coords.append(new_pt)
                slopes.append(float(slope[nr, nc]))
                row, col = nr, nc

            # Only create segment if >= 2 points
            if len(coords) >= 2:
                upstream_area_km2 = (
                    float(acc[row, col]) * cell_area / 1_000_000
                )
                segments.append(
                    {
                        "coords": coords,
                        "strahler_order": seg_order,
                        "length_m": round(length_m, 1),
                        "upstream_area_km2": round(
                            upstream_area_km2, 4
                        ),
                        "mean_slope_percent": round(
                            float(np.mean(slopes)), 2
                        ),
                    }
                )

                # Paint label raster with 1-based segment index
                if label_raster_out is not None:
                    seg_id = len(segments)  # 1-based
                    for r, c in seg_rc_path:
                        label_raster_out[r, c] = seg_id

            # Continue from junction point if order changed
            ds = downstream_cell(row, col)
            if ds is None or not stream_mask[ds[0], ds[1]]:
                break
            if visited[ds[0], ds[1]]:
                break
            row, col = ds

    logger.info(
        f"Vectorized {len(segments)} stream segments "
        f"(total length: "
        f"{sum(s['length_m'] for s in segments) / 1000:.1f} km)"
    )

    return segments


def delineate_subcatchments(
    flw,
    label_raster: np.ndarray,
    dem: np.ndarray,
    nodata: float,
) -> np.ndarray:
    """
    Assign every non-stream cell to the stream segment it drains to.

    Uses pyflwdir.FlwdirRaster.basins() for O(n) upstream label propagation
    instead of pure-Python downstream tracing. See ADR-016.

    Parameters
    ----------
    flw : pyflwdir.FlwdirRaster
        Flow direction raster object built from d8_fdir
    label_raster : np.ndarray
        int32 array, pre-painted with stream segment labels (1-based).
        Modified in-place: non-stream cells get the label of the
        downstream segment they drain to.
    dem : np.ndarray
        DEM array (for nodata detection)
    nodata : float
        NoData value

    Returns
    -------
    np.ndarray
        The label_raster (modified in-place)
    """
    logger.info("Delineating sub-catchments...")

    flat = label_raster.ravel()
    stream_mask = flat > 0
    stream_idxs = np.where(stream_mask)[0]
    stream_ids = flat[stream_mask].astype(np.uint32)

    logger.info(
        f"  Seeding {len(stream_idxs):,} stream cells "
        f"({len(np.unique(stream_ids))} segments)"
    )

    basin_map = flw.basins(idxs=stream_idxs, ids=stream_ids)
    label_raster[:] = basin_map.astype(np.int32)

    total_valid = int(np.sum(dem != nodata))
    total_labeled = int(np.sum(label_raster != 0))
    unlabeled = total_valid - total_labeled
    logger.info(
        f"  Sub-catchments: {total_labeled:,}/{total_valid:,} cells labeled "
        f"({unlabeled:,} drain outside area)"
    )

    return label_raster


def polygonize_subcatchments(
    label_raster: np.ndarray,
    dem: np.ndarray,
    slope: np.ndarray,
    metadata: dict,
    segments: list[dict],
) -> list[dict]:
    """
    Convert label raster to sub-catchment polygons.

    Groups rasterio shapes by segment index, computes union geometry
    and zonal statistics (area, mean elevation, mean slope).

    Parameters
    ----------
    label_raster : np.ndarray
        int32 array with segment labels (1-based, 0=unassigned)
    dem : np.ndarray
        DEM array
    slope : np.ndarray
        Slope array (percent)
    metadata : dict
        Grid metadata (cellsize, nodata_value, transform)
    segments : list[dict]
        Stream segments from vectorize_streams()

    Returns
    -------
    list[dict]
        List of catchment dicts with keys: wkt, segment_idx,
        area_km2, mean_elevation_m, mean_slope_percent, strahler_order
    """
    from rasterio.features import shapes
    from shapely.geometry import MultiPolygon, shape
    from shapely.ops import unary_union

    from core.zonal_stats import zonal_bincount

    logger.info("Polygonizing sub-catchments...")

    nodata = metadata["nodata_value"]
    cellsize = metadata["cellsize"]
    cell_area_km2 = (cellsize * cellsize) / 1_000_000

    # Build transform
    transform = metadata.get("transform")
    if transform is None:
        from rasterio.transform import from_bounds

        nrows, ncols = label_raster.shape
        xll, yll = metadata["xllcorner"], metadata["yllcorner"]
        transform = from_bounds(
            xll, yll,
            xll + ncols * cellsize,
            yll + nrows * cellsize,
            ncols, nrows,
        )

    # Mask: only labeled cells
    mask = label_raster > 0

    # Polygonize
    geom_groups = defaultdict(list)
    for geom_dict, value in shapes(label_raster, mask=mask, transform=transform):
        seg_idx = int(value)
        if seg_idx > 0:
            geom_groups[seg_idx].append(shape(geom_dict))

    logger.info(f"  Found {len(geom_groups)} unique sub-catchment labels")

    # Pre-compute zonal statistics using np.bincount (O(M) not O(n*M))
    max_label = int(label_raster.max())

    counts = zonal_bincount(label_raster, max_label=max_label)

    # Elevation: mask nodata before bincount
    valid_elev = dem != nodata
    elev_sum = zonal_bincount(
        label_raster, weights=dem.astype(np.float64),
        max_label=max_label, valid_mask=valid_elev,
    )
    elev_count = zonal_bincount(
        label_raster, max_label=max_label, valid_mask=valid_elev,
    )

    # Slope
    slope_sum = zonal_bincount(
        label_raster, weights=slope, max_label=max_label,
    )

    logger.info("  Zonal statistics computed (single-pass bincount)")

    # Build catchment records
    catchments = []
    simplify_tol = cellsize / 2

    for seg_idx in sorted(geom_groups.keys()):
        geom_list = geom_groups[seg_idx]
        merged = unary_union(geom_list)

        # Ensure MULTIPOLYGON
        if merged.geom_type == "Polygon":
            merged = MultiPolygon([merged])

        # Simplify to reduce staircase vertices
        merged = merged.simplify(simplify_tol, preserve_topology=True)
        if merged.geom_type == "Polygon":
            merged = MultiPolygon([merged])

        # Zonal statistics from pre-computed arrays
        n_cells = int(counts[seg_idx])
        area_km2 = n_cells * cell_area_km2

        n_elev = int(elev_count[seg_idx])
        mean_elev = float(elev_sum[seg_idx] / n_elev) if n_elev > 0 else None
        mean_slp = float(slope_sum[seg_idx] / n_cells) if n_cells > 0 else None

        # Strahler order from segment
        strahler_order = None
        if 1 <= seg_idx <= len(segments):
            strahler_order = segments[seg_idx - 1].get("strahler_order")

        catchments.append({
            "wkt": merged.wkt,
            "segment_idx": seg_idx,
            "area_km2": round(area_km2, 6),
            "mean_elevation_m": round(mean_elev, 2) if mean_elev is not None else None,
            "mean_slope_percent": round(mean_slp, 2) if mean_slp is not None else None,
            "strahler_order": strahler_order,
        })

    logger.info(
        f"  Polygonized {len(catchments)} sub-catchments "
        f"(total area: {sum(c['area_km2'] for c in catchments):.2f} km²)"
    )

    return catchments
