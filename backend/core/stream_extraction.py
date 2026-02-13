"""
Stream network vectorization and sub-catchment delineation.

Traces connected stream cells from headwaters downstream, creates
LineString segments, delineates sub-catchments using pyflwdir basins,
and polygonizes sub-catchment labels.

Uses numba @njit for grid-scanning loops (upstream count, headwater
detection) to accelerate vectorize_streams from ~300s to ~10s.
"""

import logging
from collections import defaultdict

import numba
import numpy as np

from core.hydrology import D8_DIRECTIONS

logger = logging.getLogger(__name__)

# D8 lookup arrays for numba (dict not supported in njit)
_DR = np.zeros(256, dtype=np.int32)
_DC = np.zeros(256, dtype=np.int32)
_VALID = np.zeros(256, dtype=np.bool_)
for _d, (_di, _dj) in D8_DIRECTIONS.items():
    _DR[_d] = _di
    _DC[_d] = _dj
    _VALID[_d] = True


@numba.njit(cache=True)
def _count_upstream_and_find_headwaters(
    fdir: np.ndarray,
    stream_mask: np.ndarray,
    nodata_mask: np.ndarray,
    dr: np.ndarray,
    dc: np.ndarray,
    valid_d8: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Count upstream stream neighbors + find headwaters in one pass.

    Returns upstream_count, hw_rows, hw_cols arrays.
    """
    nrows, ncols = fdir.shape
    upstream_count = np.zeros((nrows, ncols), dtype=np.int32)

    # Pass 1: count upstream stream neighbors
    for i in range(nrows):
        for j in range(ncols):
            if not stream_mask[i, j]:
                continue
            d = fdir[i, j]
            if d < 0 or d >= 256:
                continue
            if not valid_d8[d]:
                continue
            ni = i + dr[d]
            nj = j + dc[d]
            if (
                0 <= ni < nrows
                and 0 <= nj < ncols
                and not nodata_mask[ni, nj]
                and stream_mask[ni, nj]
            ):
                upstream_count[ni, nj] += 1

    # Pass 2: collect headwaters
    # First count for pre-allocation
    n_hw = 0
    for i in range(nrows):
        for j in range(ncols):
            if stream_mask[i, j] and upstream_count[i, j] == 0:
                n_hw += 1

    hw_rows = np.empty(n_hw, dtype=np.int32)
    hw_cols = np.empty(n_hw, dtype=np.int32)
    idx = 0
    for i in range(nrows):
        for j in range(ncols):
            if stream_mask[i, j] and upstream_count[i, j] == 0:
                hw_rows[idx] = i
                hw_cols[idx] = j
                idx += 1

    return upstream_count, hw_rows, hw_cols


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

    Uses numba-accelerated grid scanning for upstream counting and
    headwater detection (the main bottleneck on large grids).

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
    nodata_mask = dem == nodata

    # Numba-accelerated upstream counting + headwater detection
    fdir_i16 = fdir.astype(np.int16)
    upstream_count, hw_rows, hw_cols = _count_upstream_and_find_headwaters(
        fdir_i16,
        stream_mask,
        nodata_mask,
        _DR,
        _DC,
        _VALID,
    )

    logger.info(f"  Found {len(hw_rows)} headwater cells")

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

    # Trace segments from headwaters (operates on ~200k stream cells)
    visited = np.zeros((nrows, ncols), dtype=bool)
    segments = []

    for hw_idx in range(len(hw_rows)):
        row, col = int(hw_rows[hw_idx]), int(hw_cols[hw_idx])

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
                    (new_pt[0] - coords[-1][0]) ** 2 + (new_pt[1] - coords[-1][1]) ** 2
                ) ** 0.5
                length_m += dist
                coords.append(new_pt)
                slopes.append(float(slope[nr, nc]))
                row, col = nr, nc

            # Only create segment if >= 2 points
            if len(coords) >= 2:
                upstream_area_km2 = float(acc[row, col]) * cell_area / 1_000_000
                # Last cell in seg_rc_path is the outlet of this segment
                outlet_rc = seg_rc_path[-1]
                segments.append(
                    {
                        "coords": coords,
                        "strahler_order": seg_order,
                        "length_m": round(length_m, 1),
                        "upstream_area_km2": round(upstream_area_km2, 4),
                        "mean_slope_percent": round(float(np.mean(slopes)), 2),
                        "_outlet_rc": outlet_rc,
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
        f"  Sub-catchments: {total_labeled:,}/{total_valid:,} "
        f"cells labeled ({unlabeled:,} drain outside area)"
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
        area_km2, mean_elevation_m, mean_slope_percent,
        strahler_order
    """
    from rasterio.features import shapes
    from shapely.geometry import MultiPolygon, shape
    from shapely.ops import unary_union

    from core.zonal_stats import (
        zonal_bincount,
        zonal_elevation_histogram,
        zonal_max,
        zonal_min,
    )

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
            xll,
            yll,
            xll + ncols * cellsize,
            yll + nrows * cellsize,
            ncols,
            nrows,
        )

    # Mask: only labeled cells
    mask = label_raster > 0

    # Polygonize
    geom_groups = defaultdict(list)
    for geom_dict, value in shapes(
        label_raster,
        mask=mask,
        transform=transform,
    ):
        seg_idx = int(value)
        if seg_idx > 0:
            geom_groups[seg_idx].append(shape(geom_dict))

    logger.info(f"  Found {len(geom_groups)} unique sub-catchment labels")

    # Pre-compute zonal stats using bincount (O(M) not O(n*M))
    max_label = int(label_raster.max())

    counts = zonal_bincount(label_raster, max_label=max_label)

    # Elevation: mask nodata before bincount
    valid_elev = dem != nodata
    elev_sum = zonal_bincount(
        label_raster,
        weights=dem.astype(np.float64),
        max_label=max_label,
        valid_mask=valid_elev,
    )
    elev_count = zonal_bincount(
        label_raster,
        max_label=max_label,
        valid_mask=valid_elev,
    )

    # Slope
    slope_sum = zonal_bincount(
        label_raster,
        weights=slope,
        max_label=max_label,
    )

    # Elevation min/max (for pre-computed stats)
    dem_for_min = np.where(valid_elev, dem, np.inf).astype(np.float64)
    dem_for_max = np.where(valid_elev, dem, -np.inf).astype(np.float64)
    elev_min = zonal_min(label_raster, dem_for_min, max_label)
    elev_max = zonal_max(label_raster, dem_for_max, max_label)

    # Elevation histograms (for hypsometric curve aggregation)
    elev_histograms = zonal_elevation_histogram(
        label_raster,
        dem,
        max_label,
        nodata,
        interval_m=1,
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
        merged = merged.simplify(
            simplify_tol,
            preserve_topology=True,
        )
        if merged.geom_type == "Polygon":
            merged = MultiPolygon([merged])

        # Zonal statistics from pre-computed arrays
        n_cells = int(counts[seg_idx])
        area_km2 = n_cells * cell_area_km2

        n_elev = int(elev_count[seg_idx])
        mean_elev = float(elev_sum[seg_idx] / n_elev) if n_elev > 0 else None
        mean_slp = float(slope_sum[seg_idx] / n_cells) if n_cells > 0 else None

        # Strahler order and segment-level stats
        strahler_order = None
        downstream_segment_idx = None
        stream_length_km = None
        if 1 <= seg_idx <= len(segments):
            seg = segments[seg_idx - 1]
            strahler_order = seg.get("strahler_order")
            downstream_segment_idx = seg.get("downstream_segment_idx")
            if seg.get("length_m") is not None:
                stream_length_km = round(seg["length_m"] / 1000, 4)

        # Elevation min/max from zonal stats
        e_min = float(elev_min[seg_idx - 1]) if n_elev > 0 else None
        e_max = float(elev_max[seg_idx - 1]) if n_elev > 0 else None
        # Guard against inf from nodata masking
        if e_min is not None and not np.isfinite(e_min):
            e_min = None
        if e_max is not None and not np.isfinite(e_max):
            e_max = None

        # Perimeter from polygon geometry (in km)
        perimeter_km = round(merged.length / 1000, 4)

        # Elevation histogram
        histogram = elev_histograms.get(seg_idx)

        catchments.append(
            {
                "wkt": merged.wkt,
                "segment_idx": seg_idx,
                "area_km2": round(area_km2, 6),
                "mean_elevation_m": (
                    round(mean_elev, 2) if mean_elev is not None else None
                ),
                "mean_slope_percent": (
                    round(mean_slp, 2) if mean_slp is not None else None
                ),
                "strahler_order": strahler_order,
                "downstream_segment_idx": downstream_segment_idx,
                "elevation_min_m": (round(e_min, 2) if e_min is not None else None),
                "elevation_max_m": (round(e_max, 2) if e_max is not None else None),
                "perimeter_km": perimeter_km,
                "stream_length_km": stream_length_km,
                "elev_histogram": histogram,
            }
        )

    logger.info(
        f"  Polygonized {len(catchments)} sub-catchments "
        f"(total area: "
        f"{sum(c['area_km2'] for c in catchments):.2f} km²)"
    )

    return catchments


def compute_downstream_links(
    segments: list[dict],
    label_raster: np.ndarray,
    fdir: np.ndarray,
    metadata: dict,
) -> None:
    """
    For each segment, follow fdir one cell from outlet to find downstream segment.

    Sets "downstream_segment_idx" key on each segment dict in-place.
    O(n_segments) — one fdir lookup per segment.

    Parameters
    ----------
    segments : list[dict]
        Stream segments from vectorize_streams() (must have "_outlet_rc").
    label_raster : np.ndarray
        Sub-catchment label raster (1-based segment indices).
    fdir : np.ndarray
        Flow direction array (D8 encoding).
    metadata : dict
        Grid metadata (nodata_value).
    """
    nrows, ncols = fdir.shape
    n_linked = 0

    for seg in segments:
        outlet_rc = seg.get("_outlet_rc")
        if outlet_rc is None:
            seg["downstream_segment_idx"] = None
            continue

        row, col = outlet_rc
        d = fdir[row, col]
        if d not in D8_DIRECTIONS:
            seg["downstream_segment_idx"] = None
            continue

        di, dj = D8_DIRECTIONS[d]
        nr, nc = row + di, col + dj

        if not (0 <= nr < nrows and 0 <= nc < ncols):
            seg["downstream_segment_idx"] = None
            continue

        ds_label = int(label_raster[nr, nc])
        seg_idx_1based = segments.index(seg) + 1

        if ds_label > 0 and ds_label != seg_idx_1based:
            seg["downstream_segment_idx"] = ds_label
            n_linked += 1
        else:
            seg["downstream_segment_idx"] = None

    n_outlets = len(segments) - n_linked
    logger.info(
        f"Downstream links: {n_linked} linked, {n_outlets} outlets (no downstream)"
    )
