"""Generate synthetic test dataset for catchment selection tests.

Produces:
  - test_catchments.sql  (SQL inserts for stream_catchments + stream_network)
  - test_points.py       (TEST_POINTS dict with known coords & expected results)

Usage:
    cd backend && .venv/bin/python tests/fixtures/generate_test_data.py
"""

from __future__ import annotations

import json
import math
import random
import textwrap
from pathlib import Path

import numpy as np
from scipy.spatial import Voronoi
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BBOX_MIN_X, BBOX_MIN_Y = 638800.0, 486000.0
BBOX_MAX_X, BBOX_MAX_Y = 639400.0, 486600.0
BBOX_WIDTH = BBOX_MAX_X - BBOX_MIN_X   # 600
BBOX_HEIGHT = BBOX_MAX_Y - BBOX_MIN_Y  # 600

SEGMENT_IDX_START = 9001

THRESHOLDS = {
    1000: 60,
    10000: 30,
    100000: 10,
}

CLIP_BOX = Polygon([
    (BBOX_MIN_X, BBOX_MIN_Y),
    (BBOX_MAX_X, BBOX_MIN_Y),
    (BBOX_MAX_X, BBOX_MAX_Y),
    (BBOX_MIN_X, BBOX_MAX_Y),
])

OUTPUT_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _voronoi_cells(points: np.ndarray) -> list[Polygon]:
    """Return Voronoi cells clipped to CLIP_BOX, one per input point."""
    # Add far-away mirror points so every real point gets a finite cell.
    mirror_dist = 2000.0
    cx, cy = (BBOX_MIN_X + BBOX_MAX_X) / 2, (BBOX_MIN_Y + BBOX_MAX_Y) / 2
    mirrors = []
    for angle_deg in range(0, 360, 15):
        a = math.radians(angle_deg)
        mirrors.append([cx + mirror_dist * math.cos(a), cy + mirror_dist * math.sin(a)])
    all_pts = np.vstack([points, np.array(mirrors)])

    vor = Voronoi(all_pts)
    n_real = len(points)
    cells: list[Polygon] = []

    for i in range(n_real):
        region_idx = vor.point_region[i]
        region = vor.regions[region_idx]
        if -1 in region or len(region) == 0:
            # Fallback: small buffer around the point
            cells.append(Point(points[i]).buffer(15).intersection(CLIP_BOX))
            continue
        verts = [vor.vertices[v] for v in region]
        poly = Polygon(verts).intersection(CLIP_BOX)
        if poly.is_empty:
            poly = Point(points[i]).buffer(15).intersection(CLIP_BOX)
        cells.append(poly)

    return cells


def _ensure_multi(geom) -> MultiPolygon:
    """Convert any polygon-ish geometry to MultiPolygon."""
    if geom.geom_type == "MultiPolygon":
        return geom
    if geom.geom_type == "Polygon":
        return MultiPolygon([geom])
    # GeometryCollection — extract polygons
    polys = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
    if not polys:
        raise ValueError(f"Cannot convert {geom.geom_type} to MultiPolygon")
    flat = []
    for p in polys:
        if p.geom_type == "MultiPolygon":
            flat.extend(p.geoms)
        else:
            flat.append(p)
    return MultiPolygon(flat)


def _elevation_at(y: float) -> float:
    """Elevation gradient N→S: higher in the north (200m), lower in south (80m)."""
    t = (y - BBOX_MIN_Y) / BBOX_HEIGHT  # 0 at south, 1 at north
    return 80.0 + t * 120.0


def _make_elev_histogram(mean_elev: float) -> dict:
    """Create a realistic elevation histogram around mean_elev."""
    base = int(mean_elev) - 5
    counts = []
    for i in range(11):
        elev = base + i
        dist = abs(elev - mean_elev)
        counts.append(max(1, int(20 * math.exp(-0.5 * (dist / 2.0) ** 2))))
    return {"base_m": base, "interval_m": 1, "counts": counts}


def _build_downstream_tree(n: int, centroids: list[Point]) -> list[int | None]:
    """Build a tree structure where each node drains to a lower-elevation neighbour.

    Returns list of downstream_segment_idx (offset by SEGMENT_IDX_START)
    or None for outlet.
    """
    # Sort by elevation (north→south = high→low), outlet is the southernmost.
    elevs = [_elevation_at(c.y) for c in centroids]
    order = sorted(range(n), key=lambda i: elevs[i])  # ascending elevation

    downstream: list[int | None] = [None] * n
    # For each node (except the lowest), find the nearest node with lower elevation.
    for idx in range(1, n):
        node = order[idx]
        node_pt = centroids[node]
        best_dist = float("inf")
        best_target = None
        for j in range(idx):  # only nodes with lower elevation
            candidate = order[j]
            d = node_pt.distance(centroids[candidate])
            if d < best_dist:
                best_dist = d
                best_target = candidate
        downstream[node] = (
            SEGMENT_IDX_START + best_target
            if best_target is not None
            else None
        )

    # The outlet (lowest elevation) has no downstream.
    downstream[order[0]] = None
    return downstream


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------

def generate() -> None:
    random.seed(42)
    np.random.seed(42)

    # --- Step 1: Generate t=1000 Voronoi cells (finest) ---
    n_fine = THRESHOLDS[1000]  # 60
    pts_fine = np.column_stack([
        np.random.uniform(BBOX_MIN_X + 20, BBOX_MAX_X - 20, n_fine),
        np.random.uniform(BBOX_MIN_Y + 20, BBOX_MAX_Y - 20, n_fine),
    ])
    cells_fine = _voronoi_cells(pts_fine)
    centroids_fine = [c.centroid for c in cells_fine]
    downstream_fine = _build_downstream_tree(n_fine, centroids_fine)

    # --- Step 2: Generate t=10000 by merging pairs ---
    n_medium = THRESHOLDS[10000]  # 30
    cells_medium: list[Polygon | MultiPolygon] = []
    centroids_medium: list[Point] = []
    for i in range(n_medium):
        merged = unary_union([cells_fine[2 * i], cells_fine[2 * i + 1]])
        cells_medium.append(merged)
        centroids_medium.append(merged.centroid)
    downstream_medium = _build_downstream_tree(n_medium, centroids_medium)

    # --- Step 3: Generate t=100000 by merging triplets of medium ---
    n_coarse = THRESHOLDS[100000]  # 10
    cells_coarse: list[Polygon | MultiPolygon] = []
    centroids_coarse: list[Point] = []
    for i in range(n_coarse):
        merged = unary_union([
            cells_medium[3 * i],
            cells_medium[3 * i + 1],
            cells_medium[3 * i + 2],
        ])
        cells_coarse.append(merged)
        centroids_coarse.append(merged.centroid)
    downstream_coarse = _build_downstream_tree(n_coarse, centroids_coarse)

    # --- Step 4: Build SQL ---
    sql_lines: list[str] = []
    sql_lines.append("-- Auto-generated test data for catchment selection tests")
    sql_lines.append("-- DO NOT EDIT MANUALLY — regenerate with generate_test_data.py")
    sql_lines.append("")
    sql_lines.append("BEGIN;")
    sql_lines.append("")
    sql_lines.append("-- Clean up any previous test data (segment_idx 9001-9100)")
    sql_lines.append(
        "DELETE FROM stream_catchments"
        " WHERE segment_idx BETWEEN 9001 AND 9100;"
    )
    sql_lines.append(
        "DELETE FROM stream_network"
        " WHERE segment_idx BETWEEN 9001 AND 9100;"
    )
    sql_lines.append("")

    # Collect all threshold data for iteration
    threshold_data = [
        (1000, cells_fine, centroids_fine, downstream_fine, n_fine),
        (10000, cells_medium, centroids_medium, downstream_medium, n_medium),
        (100000, cells_coarse, centroids_coarse, downstream_coarse, n_coarse),
    ]

    # stream_catchments
    sql_lines.append("-- ============================================================")
    sql_lines.append("-- stream_catchments")
    sql_lines.append("-- ============================================================")
    sql_lines.append("")

    for threshold, cells, centroids, downstream, n in threshold_data:
        sql_lines.append(f"-- threshold = {threshold}  ({n} catchments)")
        for i in range(n):
            seg_idx = SEGMENT_IDX_START + i
            cell = _ensure_multi(cells[i])
            centroid = centroids[i]
            mean_elev = round(_elevation_at(centroid.y), 1)
            elev_min = round(mean_elev - random.uniform(3, 10), 1)
            elev_max = round(mean_elev + random.uniform(3, 10), 1)
            slope = round(random.uniform(1.0, 8.0), 1)
            area_km2 = round(cell.area / 1e6, 6)
            perimeter_km = round(cell.length / 1000, 4)
            strahler = min(4, 1 + i % 4)
            stream_len_km = round(random.uniform(0.03, 0.15), 4)
            ds = downstream[i]
            ds_sql = str(ds) if ds is not None else "NULL"
            elev_hist = json.dumps(_make_elev_histogram(mean_elev))
            wkt = cell.wkt

            sql_lines.append(
                f"INSERT INTO stream_catchments "
                f"(geom, segment_idx, threshold_m2, area_km2, mean_elevation_m, "
                f"mean_slope_percent, strahler_order, downstream_segment_idx, "
                f"elevation_min_m, elevation_max_m, perimeter_km, stream_length_km, "
                f"elev_histogram) VALUES ("
                f"ST_SetSRID(ST_GeomFromText('{wkt}'), 2180), "
                f"{seg_idx}, {threshold}, {area_km2}, {mean_elev}, "
                f"{slope}, {strahler}, {ds_sql}, "
                f"{elev_min}, {elev_max}, {perimeter_km}, {stream_len_km}, "
                f"'{elev_hist}'::jsonb);"
            )
        sql_lines.append("")

    # stream_network
    sql_lines.append("-- ============================================================")
    sql_lines.append("-- stream_network")
    sql_lines.append("-- ============================================================")
    sql_lines.append("")

    for threshold, cells, centroids, _downstream, n in threshold_data:
        sql_lines.append(f"-- threshold = {threshold}  ({n} stream segments)")
        for i in range(n):
            seg_idx = SEGMENT_IDX_START + i
            centroid = centroids[i]
            # Stream line: from centroid going ~50m south
            line = LineString([
                (centroid.x, centroid.y),
                (centroid.x + random.uniform(-10, 10), centroid.y - 50),
            ])
            strahler = min(4, 1 + i % 4)
            area_km2 = round(cells[i].area / 1e6, 6)
            length_m = round(line.length, 2)
            slope = round(random.uniform(1.0, 8.0), 1)
            wkt = line.wkt

            sql_lines.append(
                f"INSERT INTO stream_network "
                f"(geom, segment_idx, threshold_m2, strahler_order, "
                f"upstream_area_km2, length_m, mean_slope_percent) VALUES ("
                f"ST_SetSRID(ST_GeomFromText('{wkt}'), 2180), "
                f"{seg_idx}, {threshold}, {strahler}, "
                f"{area_km2}, {length_m}, {slope});"
            )
        sql_lines.append("")

    sql_lines.append("COMMIT;")
    sql_lines.append("")

    # Write SQL
    sql_path = OUTPUT_DIR / "test_catchments.sql"
    sql_path.write_text("\n".join(sql_lines), encoding="utf-8")
    print(f"[OK] SQL written to {sql_path}  ({len(sql_lines)} lines)")

    # --- Step 5: Generate test_points.py ---
    # Find a point covered by all three thresholds
    multi_pt = None
    multi_seg_1000 = None
    multi_seg_10000 = None
    multi_seg_100000 = None
    for i in range(n_fine):
        pt = centroids_fine[i]
        # Check if this fine centroid falls inside a medium and coarse cell
        in_medium = None
        for j in range(n_medium):
            if cells_medium[j].contains(pt):
                in_medium = j
                break
        in_coarse = None
        for j in range(n_coarse):
            if cells_coarse[j].contains(pt):
                in_coarse = j
                break
        if in_medium is not None and in_coarse is not None:
            multi_pt = pt
            multi_seg_1000 = SEGMENT_IDX_START + i
            multi_seg_10000 = SEGMENT_IDX_START + in_medium
            multi_seg_100000 = SEGMENT_IDX_START + in_coarse
            break

    # Find boundary point (between two t=1000 catchments)
    boundary_pt = None
    for i in range(n_fine - 1):
        for j in range(i + 1, min(i + 5, n_fine)):
            shared = cells_fine[i].intersection(cells_fine[j])
            is_line = shared.geom_type in (
                "LineString", "MultiLineString",
            )
            if is_line and shared.length > 1:
                boundary_pt = shared.interpolate(0.5, normalized=True)
                break
        if boundary_pt is not None:
            break
    if boundary_pt is None:
        # Fallback: midpoint between two neighbouring centroids
        boundary_pt = Point(
            (centroids_fine[0].x + centroids_fine[1].x) / 2,
            (centroids_fine[0].y + centroids_fine[1].y) / 2,
        )

    # Pick specific known catchments
    c_t1000_idx = 5
    c_t1000_centroid = centroids_fine[c_t1000_idx]
    c_t1000_seg = SEGMENT_IDX_START + c_t1000_idx

    c_t10000_idx = 3
    c_t10000_centroid = centroids_medium[c_t10000_idx]
    c_t10000_seg = SEGMENT_IDX_START + c_t10000_idx

    c_t100000_idx = 2
    c_t100000_centroid = centroids_coarse[c_t100000_idx]
    c_t100000_seg = SEGMENT_IDX_START + c_t100000_idx

    # production_like point: verify it falls inside a t=1000 catchment
    prod_pt = Point(639100.0, 486300.0)
    prod_seg = None
    for i in range(n_fine):
        if cells_fine[i].contains(prod_pt):
            prod_seg = SEGMENT_IDX_START + i
            break

    if prod_seg is not None:
        prod_line = f'"expected_segment_idx": {prod_seg},'
    else:
        prod_line = "# Point may not fall inside any catchment"

    test_points_code = textwrap.dedent(f'''\
        """Known test points for catchment selection tests.

        Auto-generated by generate_test_data.py — DO NOT EDIT MANUALLY.
        """

        TEST_POINTS = {{
            "center_t1000": {{
                "x": {c_t1000_centroid.x:.4f},
                "y": {c_t1000_centroid.y:.4f},
                "expected_segment_idx": {c_t1000_seg},
                "threshold_m2": 1000,
            }},
            "center_t10000": {{
                "x": {c_t10000_centroid.x:.4f},
                "y": {c_t10000_centroid.y:.4f},
                "expected_segment_idx": {c_t10000_seg},
                "threshold_m2": 10000,
            }},
            "center_t100000": {{
                "x": {c_t100000_centroid.x:.4f},
                "y": {c_t100000_centroid.y:.4f},
                "expected_segment_idx": {c_t100000_seg},
                "threshold_m2": 100000,
            }},
            "boundary_point": {{
                "x": {boundary_pt.x:.4f},
                "y": {boundary_pt.y:.4f},
                "threshold_m2": 1000,
                # No expected_segment_idx — any result is OK as long as not None
            }},
            "outside_point": {{
                "x": 600000.0,
                "y": 400000.0,
                "threshold_m2": 1000,
                "expected_segment_idx": None,
            }},
            "multi_threshold": {{
                "x": {multi_pt.x:.4f},
                "y": {multi_pt.y:.4f},
                "thresholds": {{
                    1000: {multi_seg_1000},
                    10000: {multi_seg_10000},
                    100000: {multi_seg_100000},
                }},
            }},
            "production_like": {{
                "x": 639100.0,
                "y": 486300.0,
                "threshold_m2": 1000,
                {prod_line}
            }},
        }}
    ''')

    tp_path = OUTPUT_DIR / "test_points.py"
    tp_path.write_text(test_points_code, encoding="utf-8")
    print(f"[OK] test_points.py written to {tp_path}")

    # Print summary
    print()
    print("=== Summary ===")
    total_catchments = sum(THRESHOLDS.values())
    print(f"Total catchments: {total_catchments}")
    for t, n in THRESHOLDS.items():
        end_idx = SEGMENT_IDX_START + n - 1
        print(
            f"  threshold={t}: {n} catchments, "
            f"segment_idx {SEGMENT_IDX_START}-{end_idx}"
        )
    print(f"Boundary point: ({boundary_pt.x:.4f}, {boundary_pt.y:.4f})")
    print(f"Multi-threshold point: ({multi_pt.x:.4f}, {multi_pt.y:.4f})")
    print(
        f"  t=1000 → seg {multi_seg_1000}, "
        f"t=10000 → seg {multi_seg_10000}, "
        f"t=100000 → seg {multi_seg_100000}"
    )
    if prod_seg:
        print(f"Production-like point (639100, 486300) → seg {prod_seg}")
    else:
        print("Production-like point (639100, 486300) → outside all t=1000 catchments")


if __name__ == "__main__":
    generate()
