#!/usr/bin/env python3
"""Benchmark: PostGIS vs. files loaded into memory for Hydrograf runtime queries.

Question being answered (shared GUI design, Nogat docs/plans/2026-10-20-unified-gui.md):
    If the data store becomes files (GeoPackage / GeoParquet) instead of
    PostGIS, how fast are Hydrograf's runtime queries when the data is read
    once from the file and queried in memory?

What the script does:
    1. Exports stream_catchments, stream_network and land_cover from the
       running Hydrograf PostGIS database to GeoPackage and GeoParquet.
    2. Measures how long it takes to load each file format and build
       in-memory spatial indexes (this is the "switch layer version" cost).
    3. Runs the queries Q1-Q8 from Hydrograf docs/BENCHMARK_QUERIES.md, plus
       Q9 (land cover overlay used for CN), in both engines on the same
       inputs, and compares the timings.
    4. Checks that both engines return the same results (correctness).
    5. Optionally measures throughput with several threads (many users).
    6. Writes raport.md and wyniki.json to the output directory.

The script only READS from the database. It does not modify Hydrograf.

Usage (from backend/, Hydrograf virtualenv, database running):
    export DATABASE_URL=postgresql://hydro_user:<password>@localhost:5432/hydro_db
    .venv/bin/python scripts/benchmark_storage.py --out-dir ~/storage_benchmark

See docs/STORAGE_BENCHMARK.md for details.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics
import sys
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Dependency check (clear message instead of a stack trace)
# ---------------------------------------------------------------------------

REQUIRED_PACKAGES = {
    "numpy": "numpy",
    "shapely": "shapely",
    "geopandas": "geopandas",
    "sqlalchemy": "sqlalchemy",
    "pyproj": "pyproj",
    "pyogrio": "pyogrio",
    "pyarrow": "pyarrow",
}


def _module_available(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except ImportError:
        return False


def normalize_db_url(url: str) -> str:
    """Pick the PostgreSQL driver that is actually installed.

    SQLAlchemy 2.1 maps a bare "postgresql://" URL to psycopg (v3), while
    Hydrograf uses psycopg2. Without this, the script fails on import.
    """
    if url.startswith("postgresql://"):
        driver = "psycopg2" if _module_available("psycopg2") else "psycopg"
        return url.replace("postgresql://", f"postgresql+{driver}://", 1)
    return url


def check_dependencies() -> None:
    """Stop with a readable message when a required package is missing."""
    missing = []
    for module_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            __import__(module_name)
        except ImportError:
            missing.append(pip_name)
    if not any(_module_available(name) for name in ("psycopg2", "psycopg")):
        missing.append("psycopg2-binary")
    if missing:
        print("BŁĄD: brakuje pakietów Pythona: " + ", ".join(missing))
        print("Zainstaluj je w środowisku backendu Hydrografa, np.:")
        print("    pip install " + " ".join(missing))
        sys.exit(1)


check_dependencies()

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import shapely  # noqa: E402
from pyproj import Transformer  # noqa: E402
from shapely import wkb  # noqa: E402
from shapely.geometry import MultiPolygon, Point, Polygon  # noqa: E402
from shapely.strtree import STRtree  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

# ---------------------------------------------------------------------------
# Constants copied from Hydrograf (backend/core/watershed_service.py)
# ---------------------------------------------------------------------------

GAP_CLOSE_M = 2.0  # _GAP_CLOSE_M
SNAP_SIZE_M = 10.0  # _SNAP_SIZE_M
BATCH_SIZE = 50  # _BATCH_SIZE
DIRECT_MERGE_LIMIT = 100  # merge_catchment_boundaries: n <= 100 -> direct
SIMPLIFY_TOLERANCE_M = 5.0
CHAIKIN_ITERATIONS = 3
DWITHIN_DISTANCE_M = 500.0
SRID = 2180

# Tolerances used by the correctness check
AREA_TOLERANCE = 0.005  # 0.5 % relative area difference
IOU_TOLERANCE = 0.99  # intersection over union of merged boundaries


# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------


@dataclass
class TimingStats:
    """Summary of repeated timings in milliseconds."""

    min_ms: float
    mean_ms: float
    median_ms: float
    p95_ms: float
    max_ms: float
    iterations: int

    @classmethod
    def from_samples(cls, samples_ms: list[float]) -> TimingStats:
        ordered = sorted(samples_ms)
        p95_index = min(len(ordered) - 1, int(len(ordered) * 0.95))
        return cls(
            min_ms=round(ordered[0], 3),
            mean_ms=round(statistics.mean(ordered), 3),
            median_ms=round(statistics.median(ordered), 3),
            p95_ms=round(ordered[p95_index], 3),
            max_ms=round(ordered[-1], 3),
            iterations=len(ordered),
        )


def measure(function, inputs: list, iterations: int, warmup: int = 3) -> TimingStats:
    """Call function(*input) `iterations` times, cycling through inputs.

    A few warm-up calls run first so that one-time costs (e.g. the PROJ
    cache in ST_Transform) do not distort the result for either engine.
    """
    for i in range(min(warmup, len(inputs))):
        function(*inputs[i])
    samples = []
    for i in range(iterations):
        args = inputs[i % len(inputs)]
        start = time.perf_counter()
        function(*args)
        samples.append((time.perf_counter() - start) * 1000.0)
    return TimingStats.from_samples(samples)


def memory_mb() -> float | None:
    """Current resident memory of this process in MB (best effort)."""
    try:
        import psutil

        return psutil.Process().memory_info().rss / 1024 / 1024
    except ImportError:
        pass
    try:
        import resource

        # On Linux ru_maxrss is the PEAK resident size in KB.
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Geometry helpers shared by the in-memory engine
# ---------------------------------------------------------------------------


def chaikin_ring(coords: np.ndarray, iterations: int) -> np.ndarray:
    """Chaikin corner cutting for a closed ring (first point == last point).

    Mirrors ST_ChaikinSmoothing for polygon rings: each edge P_i -> P_i+1 is
    replaced by points at 1/4 and 3/4 of its length.
    """
    points = coords[:-1]
    for _ in range(iterations):
        if len(points) < 3:
            break
        following = np.roll(points, -1, axis=0)
        quarter = 0.75 * points + 0.25 * following
        three_quarters = 0.25 * points + 0.75 * following
        points = np.empty((len(points) * 2, 2))
        points[0::2] = quarter
        points[1::2] = three_quarters
    return np.vstack([points, points[:1]])


def chaikin_polygon(geometry, iterations: int):
    """Apply Chaikin smoothing to every ring of a (Multi)Polygon."""

    def smooth_one(polygon: Polygon) -> Polygon:
        exterior = chaikin_ring(np.asarray(polygon.exterior.coords)[:, :2], iterations)
        interiors = [
            chaikin_ring(np.asarray(ring.coords)[:, :2], iterations)
            for ring in polygon.interiors
        ]
        return Polygon(exterior, interiors)

    if geometry.is_empty:
        return geometry
    if isinstance(geometry, Polygon):
        return smooth_one(geometry)
    if isinstance(geometry, MultiPolygon):
        return MultiPolygon([smooth_one(p) for p in geometry.geoms])
    # GeometryCollection etc.: keep only polygonal parts
    parts = [
        g
        for g in getattr(geometry, "geoms", [])
        if isinstance(g, (Polygon, MultiPolygon))
    ]
    return chaikin_polygon(shapely.union_all(parts), iterations) if parts else geometry


def as_multipolygon(geometry):
    """Equivalent of ST_Multi for polygonal results."""
    if isinstance(geometry, Polygon):
        return MultiPolygon([geometry])
    return geometry


def smooth_boundary(union_geometry):
    """Python version of Hydrograf _SMOOTH_SQL.

    ST_Multi(ST_Buffer(ST_ChaikinSmoothing(ST_SimplifyPreserveTopology(
        ST_Buffer(ST_Buffer(union, gap), -gap), 5.0), 3), 0))
    """
    closed = union_geometry.buffer(GAP_CLOSE_M).buffer(-GAP_CLOSE_M)
    simplified = shapely.simplify(closed, SIMPLIFY_TOLERANCE_M, preserve_topology=True)
    smoothed = chaikin_polygon(simplified, CHAIKIN_ITERATIONS)
    return as_multipolygon(smoothed.buffer(0))


# ---------------------------------------------------------------------------
# Engine 1: PostGIS (SQL copied from Hydrograf)
# ---------------------------------------------------------------------------

SMOOTH_SQL = """ST_Multi(ST_Buffer(
    ST_ChaikinSmoothing(
        ST_SimplifyPreserveTopology(
            ST_Buffer(ST_Buffer(
                {union_expr},
            :gap_close), -:gap_close),
        5.0),
    3),
0))"""

SQL_Q1_CONTAINS = """
    SELECT segment_idx FROM stream_catchments
    WHERE threshold_m2 = :threshold
      AND ST_Contains(geom, ST_SetSRID(ST_Point(:x, :y), 2180))
    LIMIT 1
"""

SQL_Q2_LOOKUP = """
    SELECT segment_idx, strahler_order, ST_Length(geom) AS length_m,
           upstream_area_km2,
           ST_X(ST_EndPoint(geom)) AS downstream_x,
           ST_Y(ST_EndPoint(geom)) AS downstream_y
    FROM stream_network
    WHERE threshold_m2 = :threshold AND segment_idx = :seg_idx
    LIMIT 1
"""

_MERGE_SELECT = SMOOTH_SQL.format(union_expr="ST_UnaryUnion(ST_Collect(geom))")

SQL_MERGE_DIRECT = f"""
    SELECT ST_AsBinary({_MERGE_SELECT}) AS geom
    FROM stream_catchments
    WHERE threshold_m2 = :threshold AND segment_idx = ANY(:idxs)
"""

SQL_MERGE_BATCHED = f"""
    WITH numbered AS (
        SELECT ST_MakeValid(ST_SnapToGrid(geom, :snap_size)) AS geom,
               ROW_NUMBER() OVER (ORDER BY segment_idx) AS rn
        FROM stream_catchments
        WHERE threshold_m2 = :threshold AND segment_idx = ANY(:idxs)
    ),
    batched AS (
        SELECT ST_UnaryUnion(ST_Collect(geom)) AS geom
        FROM numbered
        GROUP BY (rn - 1) / :batch_size
    )
    SELECT ST_AsBinary({_MERGE_SELECT}) AS geom
    FROM batched
"""

SQL_Q5_OUTLET = """
    SELECT ST_X(ST_EndPoint(geom)) AS x, ST_Y(ST_EndPoint(geom)) AS y
    FROM stream_network
    WHERE segment_idx = :seg_idx AND threshold_m2 = :threshold
    LIMIT 1
"""

SQL_Q6_GEOJSON = """
    SELECT ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geojson
    FROM stream_network
    WHERE segment_idx = :seg_idx AND threshold_m2 = :threshold
    LIMIT 1
"""

SQL_Q7_NEAREST = """
    SELECT segment_idx,
           ST_Distance(geom, ST_SetSRID(ST_Point(:x, :y), 2180)) AS dist
    FROM stream_network
    WHERE threshold_m2 = :threshold
      AND ST_DWithin(geom, ST_SetSRID(ST_Point(:x, :y), 2180), 500)
    ORDER BY dist LIMIT 1
"""

# Same query as backend/core/land_cover.py (CN calculation)
SQL_Q9_LANDCOVER = """
    WITH watershed AS (
        SELECT ST_SetSRID(ST_GeomFromWKB(decode(:boundary_wkb, 'hex')), 2180) AS geom
    ),
    intersections AS (
        SELECT lc.category, lc.cn_value,
               ST_Area(ST_Intersection(lc.geom, w.geom)) AS intersection_area_m2
        FROM land_cover lc
        CROSS JOIN watershed w
        WHERE ST_Intersects(lc.geom, w.geom)
    )
    SELECT category, cn_value, SUM(intersection_area_m2) AS total_area_m2
    FROM intersections
    GROUP BY category, cn_value
    ORDER BY total_area_m2 DESC
"""


class PostgisEngine:
    """Runs the Hydrograf queries against PostGIS."""

    name = "PostGIS"

    def __init__(self, engine, connection=None):
        self.engine = engine
        self.connection = connection or engine.connect()

    def clone(self) -> PostgisEngine:
        """A copy with its own connection (one per thread)."""
        return PostgisEngine(self.engine)

    def close(self) -> None:
        self.connection.close()

    def q1_contains(self, x: float, y: float, threshold: int):
        row = self.connection.execute(
            text(SQL_Q1_CONTAINS), {"threshold": threshold, "x": x, "y": y}
        ).fetchone()
        return row.segment_idx if row else None

    def q2_lookup(self, seg_idx: int, threshold: int):
        row = self.connection.execute(
            text(SQL_Q2_LOOKUP), {"threshold": threshold, "seg_idx": seg_idx}
        ).fetchone()
        return (row.length_m, row.downstream_x, row.downstream_y) if row else None

    def merge(self, idxs: list[int], threshold: int):
        if len(idxs) <= DIRECT_MERGE_LIMIT:
            sql, params = SQL_MERGE_DIRECT, {}
        else:
            sql, params = (
                SQL_MERGE_BATCHED,
                {"snap_size": SNAP_SIZE_M, "batch_size": BATCH_SIZE},
            )
        params.update(
            {"threshold": threshold, "idxs": list(idxs), "gap_close": GAP_CLOSE_M}
        )
        row = self.connection.execute(text(sql), params).fetchone()
        if row is None or row.geom is None:
            return None
        return wkb.loads(bytes(row.geom))

    def q5_outlet(self, seg_idx: int, threshold: int):
        row = self.connection.execute(
            text(SQL_Q5_OUTLET), {"threshold": threshold, "seg_idx": seg_idx}
        ).fetchone()
        return (row.x, row.y) if row else None

    def q6_geojson(self, seg_idx: int, threshold: int):
        row = self.connection.execute(
            text(SQL_Q6_GEOJSON), {"threshold": threshold, "seg_idx": seg_idx}
        ).fetchone()
        return row.geojson if row else None

    def q7_nearest(self, x: float, y: float, threshold: int):
        row = self.connection.execute(
            text(SQL_Q7_NEAREST), {"threshold": threshold, "x": x, "y": y}
        ).fetchone()
        return row.segment_idx if row else None

    def q9_landcover(self, boundary):
        rows = self.connection.execute(
            text(SQL_Q9_LANDCOVER), {"boundary_wkb": boundary.wkb_hex}
        ).fetchall()
        return {(r.category, r.cn_value): r.total_area_m2 for r in rows}


# ---------------------------------------------------------------------------
# Engine 2: files loaded into memory (shapely / GEOS, no database)
# ---------------------------------------------------------------------------


class MemoryEngine:
    """Same queries as PostgisEngine, computed on in-memory data."""

    name = "Pliki + pamięć"

    def __init__(
        self,
        catchments: gpd.GeoDataFrame,
        streams: gpd.GeoDataFrame,
        land_cover: gpd.GeoDataFrame,
    ):
        self.catchment_geoms: dict[int, np.ndarray] = {}
        self.catchment_segs: dict[int, np.ndarray] = {}
        self.catchment_trees: dict[int, STRtree] = {}
        self.catchment_by_seg: dict[tuple[int, int], object] = {}

        for threshold, group in catchments.groupby("threshold_m2"):
            geoms = np.asarray(group.geometry.values)
            segs = group["segment_idx"].to_numpy()
            self.catchment_geoms[threshold] = geoms
            self.catchment_segs[threshold] = segs
            self.catchment_trees[threshold] = STRtree(geoms)
            for seg, geom in zip(segs, geoms, strict=False):
                self.catchment_by_seg[(int(threshold), int(seg))] = geom

        self.stream_geoms: dict[int, np.ndarray] = {}
        self.stream_segs: dict[int, np.ndarray] = {}
        self.stream_trees: dict[int, STRtree] = {}
        self.stream_by_seg: dict[tuple[int, int], object] = {}
        for threshold, group in streams.groupby("threshold_m2"):
            geoms = np.asarray(group.geometry.values)
            segs = group["segment_idx"].to_numpy()
            self.stream_geoms[threshold] = geoms
            self.stream_segs[threshold] = segs
            self.stream_trees[threshold] = STRtree(geoms)
            for seg, geom in zip(segs, geoms, strict=False):
                if seg is not None and not np.isnan(seg):
                    self.stream_by_seg.setdefault((int(threshold), int(seg)), geom)

        self.landcover_geoms = np.asarray(land_cover.geometry.values)
        self.landcover_keys = list(
            zip(land_cover["category"], land_cover["cn_value"], strict=False)
        )
        self.landcover_tree = STRtree(self.landcover_geoms) if len(land_cover) else None

        self.to_wgs84 = Transformer.from_crs(SRID, 4326, always_xy=True)

    def clone(self) -> MemoryEngine:
        """Threads share the same read-only data."""
        return self

    def close(self) -> None:
        pass

    def q1_contains(self, x: float, y: float, threshold: int):
        tree = self.catchment_trees[threshold]
        # predicate "within": point within catchment == ST_Contains(catchment, point)
        hits = tree.query(Point(x, y), predicate="within")
        return int(self.catchment_segs[threshold][hits[0]]) if len(hits) else None

    def q2_lookup(self, seg_idx: int, threshold: int):
        geom = self.stream_by_seg.get((threshold, seg_idx))
        if geom is None:
            return None
        end_x, end_y = geom.coords[-1][:2]
        return (geom.length, end_x, end_y)

    def merge(self, idxs: list[int], threshold: int):
        geoms = [
            self.catchment_by_seg[(threshold, i)]
            for i in sorted(idxs)
            if (threshold, i) in self.catchment_by_seg
        ]
        if not geoms:
            return None
        # Plain union for every size. Hydrograf's batched path snaps to a 10 m
        # grid first (ST_SnapToGrid) to speed PostGIS up; raster-derived
        # catchments share exact edges, so the plain union is exact. A Python
        # port of the snap step was measured 3-4x slower than PostGIS, while
        # the union itself takes the same time in both (same GEOS library).
        return smooth_boundary(shapely.union_all(geoms))

    def q5_outlet(self, seg_idx: int, threshold: int):
        geom = self.stream_by_seg.get((threshold, seg_idx))
        return tuple(geom.coords[-1][:2]) if geom is not None else None

    def q6_geojson(self, seg_idx: int, threshold: int):
        geom = self.stream_by_seg.get((threshold, seg_idx))
        if geom is None:
            return None

        def reproject(coords: np.ndarray) -> np.ndarray:
            lon, lat = self.to_wgs84.transform(coords[:, 0], coords[:, 1])
            return np.column_stack([lon, lat])

        return shapely.to_geojson(shapely.transform(geom, reproject))

    def q7_nearest(self, x: float, y: float, threshold: int):
        tree = self.stream_trees[threshold]
        hits = tree.query_nearest(Point(x, y), max_distance=DWITHIN_DISTANCE_M)
        return int(self.stream_segs[threshold][hits[0]]) if len(hits) else None

    def q9_landcover(self, boundary):
        if self.landcover_tree is None:
            return {}
        hits = self.landcover_tree.query(boundary, predicate="intersects")
        if len(hits) == 0:
            return {}
        areas = shapely.area(shapely.intersection(self.landcover_geoms[hits], boundary))
        totals: dict[tuple, float] = defaultdict(float)
        for index, area in zip(hits, areas, strict=False):
            totals[self.landcover_keys[index]] += float(area)
        return dict(totals)


# ---------------------------------------------------------------------------
# Data export and loading
# ---------------------------------------------------------------------------

EXPORT_QUERIES = {
    "stream_catchments": (
        "SELECT segment_idx, threshold_m2, area_km2, downstream_segment_idx, geom "
        "FROM stream_catchments"
    ),
    "stream_network": (
        "SELECT segment_idx, threshold_m2, strahler_order, upstream_area_km2, geom "
        "FROM stream_network"
    ),
    "land_cover": "SELECT category, cn_value, geom FROM land_cover",
}


def export_from_postgis(engine, out_dir: Path) -> dict:
    """Copy the three tables to one GeoPackage and to GeoParquet files."""
    info = {}
    gpkg_path = out_dir / "hydrograf.gpkg"
    if gpkg_path.exists():
        gpkg_path.unlink()
    for layer, sql in EXPORT_QUERIES.items():
        start = time.perf_counter()
        frame = gpd.read_postgis(sql, engine, geom_col="geom", crs=f"EPSG:{SRID}")
        read_s = time.perf_counter() - start
        frame.to_file(gpkg_path, layer=layer, driver="GPKG", engine="pyogrio")
        frame.to_parquet(out_dir / f"{layer}.parquet")
        info[layer] = {"rows": len(frame), "read_from_postgis_s": round(read_s, 2)}
        print(f"  {layer}: {len(frame)} obiektów (odczyt z PostGIS {read_s:.1f} s)")
    info["gpkg_size_mb"] = round(gpkg_path.stat().st_size / 1024 / 1024, 1)
    info["parquet_size_mb"] = round(
        sum((out_dir / f"{layer}.parquet").stat().st_size for layer in EXPORT_QUERIES)
        / 1024
        / 1024,
        1,
    )
    return info


def load_layers(out_dir: Path, file_format: str) -> dict[str, gpd.GeoDataFrame]:
    """Read the exported layers from GeoPackage or GeoParquet."""
    layers = {}
    for layer in EXPORT_QUERIES:
        if file_format == "gpkg":
            layers[layer] = gpd.read_file(
                out_dir / "hydrograf.gpkg", layer=layer, engine="pyogrio"
            )
        else:
            layers[layer] = gpd.read_parquet(out_dir / f"{layer}.parquet")
    return layers


def _load_once(out_dir: Path, file_format: str) -> dict:
    """Read file + build indexes. Runs in a fresh process (see measure_loading)."""
    memory_before = memory_mb()
    start = time.perf_counter()
    layers = load_layers(out_dir, file_format)
    read_s = time.perf_counter() - start
    start = time.perf_counter()
    MemoryEngine(
        layers["stream_catchments"], layers["stream_network"], layers["land_cover"]
    )
    index_s = time.perf_counter() - start
    memory_after = memory_mb()
    return {
        "read_s": round(read_s, 2),
        "build_index_s": round(index_s, 2),
        "total_s": round(read_s + index_s, 2),
        "memory_growth_mb": (
            round(memory_after - memory_before, 1)
            if memory_before is not None and memory_after is not None
            else None
        ),
    }


def measure_loading(out_dir: Path) -> tuple[dict, MemoryEngine]:
    """Time: read file + build indexes. This is the cost of switching versions.

    Each format is measured in its own fresh process, so the timing and the
    memory growth of one format are not affected by data left over from the other.
    """
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    results = {}
    context = multiprocessing.get_context("spawn")
    for file_format in ("gpkg", "parquet"):
        with ProcessPoolExecutor(max_workers=1, mp_context=context) as pool:
            results[file_format] = pool.submit(
                _load_once, out_dir, file_format
            ).result()
        values = results[file_format]
        print(
            f"  {file_format}: odczyt {values['read_s']:.2f} s"
            f" + indeksy {values['build_index_s']:.2f} s,"
            f" RAM +{values['memory_growth_mb']} MB"
        )

    layers = load_layers(out_dir, "parquet")
    engine = MemoryEngine(
        layers["stream_catchments"], layers["stream_network"], layers["land_cover"]
    )
    return results, engine


# ---------------------------------------------------------------------------
# Test inputs: points, segments and realistic upstream sets
# ---------------------------------------------------------------------------


@dataclass
class Samples:
    threshold: int
    points: list[tuple[float, float]]
    segments: list[int]
    consecutive_10: list[int]
    consecutive_50: list[int]
    upstream_small: list[list[int]] = field(default_factory=list)  # 5..100 segments
    upstream_large: list[list[int]] = field(default_factory=list)  # 101..2000 segments


def build_samples(
    catchments: gpd.GeoDataFrame, threshold: int, count: int, seed: int
) -> Samples:
    """Pick random inputs so that both engines get exactly the same work."""
    rng = random.Random(seed)
    subset = catchments[catchments["threshold_m2"] == threshold]
    rows = subset.sample(n=min(count, len(subset)), random_state=seed)

    # representative_point() is always inside the polygon (centroid may not be)
    points = [(p.x, p.y) for p in rows.geometry.representative_point()]
    segments = [int(s) for s in rows["segment_idx"]]

    ordered = sorted(int(s) for s in subset["segment_idx"])

    # Upstream sets from the real catchment tree (downstream_segment_idx),
    # the same kind of input the API sends to merge_catchment_boundaries.
    children: dict[int, list[int]] = defaultdict(list)
    for seg, downstream in zip(
        subset["segment_idx"], subset["downstream_segment_idx"], strict=False
    ):
        if downstream is not None and not (
            isinstance(downstream, float) and np.isnan(downstream)
        ):
            children[int(downstream)].append(int(seg))

    def upstream_of(start: int, limit: int) -> list[int]:
        found, queue = [start], deque([start])
        while queue and len(found) <= limit:
            for child in children.get(queue.popleft(), []):
                found.append(child)
                queue.append(child)
        return found

    samples = Samples(threshold, points, segments, ordered[:10], ordered[:50])
    candidates = ordered[:]
    rng.shuffle(candidates)
    for start in candidates:
        upstream = upstream_of(start, 2000)
        if (
            5 <= len(upstream) <= DIRECT_MERGE_LIMIT
            and len(samples.upstream_small) < 20
        ):
            samples.upstream_small.append(upstream)
        elif (
            DIRECT_MERGE_LIMIT < len(upstream) <= 2000
            and len(samples.upstream_large) < 5
        ):
            samples.upstream_large.append(upstream)
        if len(samples.upstream_small) >= 20 and len(samples.upstream_large) >= 5:
            break
    return samples


# ---------------------------------------------------------------------------
# Correctness checks
# ---------------------------------------------------------------------------


def compare_geometries(a, b) -> dict:
    """Relative area difference and intersection-over-union of two shapes."""
    if a is None or b is None:
        return {"ok": a is None and b is None, "area_diff": None, "iou": None}
    area_a, area_b = a.area, b.area
    union_area = shapely.union(a, b).area
    iou = shapely.intersection(a, b).area / union_area if union_area else 1.0
    area_diff = (
        abs(area_a - area_b) / max(area_a, area_b) if max(area_a, area_b) else 0.0
    )
    return {
        "ok": area_diff <= AREA_TOLERANCE and iou >= IOU_TOLERANCE,
        "area_diff": round(area_diff, 6),
        "iou": round(iou, 6),
    }


def check_correctness(pg: PostgisEngine, mem: MemoryEngine, samples: Samples) -> dict:
    """Both engines must give the same answers, otherwise timings mean nothing."""
    t = samples.threshold
    report = {}

    q1_same = sum(
        pg.q1_contains(x, y, t) == mem.q1_contains(x, y, t) for x, y in samples.points
    )
    report["Q1 punkt w zlewni"] = f"{q1_same}/{len(samples.points)} identycznych"

    q7_same = sum(
        pg.q7_nearest(x, y, t) == mem.q7_nearest(x, y, t) for x, y in samples.points
    )
    report["Q7 najbliższy ciek"] = f"{q7_same}/{len(samples.points)} identycznych"

    q2_same = 0
    for seg in samples.segments:
        a, b = pg.q2_lookup(seg, t), mem.q2_lookup(seg, t)
        if (
            a is None
            and b is None
            or (a and b and np.allclose(a, b, rtol=1e-9, atol=1e-6))
        ):
            q2_same += 1
    report["Q2 lookup segmentu"] = f"{q2_same}/{len(samples.segments)} identycznych"

    merge_sets = (
        [samples.consecutive_10, samples.consecutive_50]
        + samples.upstream_small[:5]
        + samples.upstream_large[:2]
    )
    merge_results = [
        compare_geometries(pg.merge(s, t), mem.merge(s, t)) for s in merge_sets
    ]
    ok = sum(r["ok"] for r in merge_results)
    worst_iou = min(
        (r["iou"] for r in merge_results if r["iou"] is not None), default=None
    )
    report["Q3/Q4 sklejanie granic"] = (
        f"{ok}/{len(merge_results)} w tolerancji (najgorsze IoU = {worst_iou})"
    )

    if mem.landcover_tree is not None and samples.upstream_small:
        diffs = []
        for s in samples.upstream_small[:5]:
            boundary = pg.merge(s, t)
            pg_total = sum(pg.q9_landcover(boundary).values())
            mem_total = sum(mem.q9_landcover(boundary).values())
            if max(pg_total, mem_total) > 0:
                diffs.append(abs(pg_total - mem_total) / max(pg_total, mem_total))
        report["Q9 nakładka pokrycia terenu"] = (
            f"maks. różnica powierzchni {max(diffs) * 100:.4f} %"
            if diffs
            else "brak danych"
        )
    return report


# ---------------------------------------------------------------------------
# Benchmark runs
# ---------------------------------------------------------------------------


def q8_pipeline(engine, x: float, y: float, threshold: int, merge_set: list[int]):
    """Q8: point -> segment lookup -> merge (5 segments) -> outlet -> GeoJSON."""
    seg = engine.q1_contains(x, y, threshold)
    if seg is None:
        return None
    engine.q2_lookup(seg, threshold)
    engine.merge(merge_set, threshold)
    engine.q5_outlet(seg, threshold)
    return engine.q6_geojson(seg, threshold)


def run_query_benchmarks(
    engine, samples: Samples, iterations: int, merge_iterations: int
) -> dict:
    t = samples.threshold
    point_inputs = [(x, y, t) for x, y in samples.points]
    segment_inputs = [(s, t) for s in samples.segments]
    q8_inputs = [
        (engine, x, y, t, samples.consecutive_10[:5]) for x, y in samples.points
    ]

    results = {
        "Q1 punkt w zlewni": measure(engine.q1_contains, point_inputs, iterations),
        "Q2 lookup segmentu": measure(engine.q2_lookup, segment_inputs, iterations),
        "Q3 sklejanie 10 kolejnych": measure(
            engine.merge, [(samples.consecutive_10, t)], merge_iterations
        ),
        "Q4 sklejanie 50 kolejnych": measure(
            engine.merge, [(samples.consecutive_50, t)], merge_iterations
        ),
        "Q5 ujście": measure(engine.q5_outlet, segment_inputs, iterations),
        "Q6 GeoJSON cieku (4326)": measure(
            engine.q6_geojson, segment_inputs, iterations
        ),
        "Q7 najbliższy ciek 500 m": measure(
            engine.q7_nearest, point_inputs, iterations
        ),
        "Q8 pełny ciąg": measure(q8_pipeline, q8_inputs, merge_iterations),
    }
    if samples.upstream_small:
        results["Q3r sklejanie zlewni 5-100 (realne)"] = measure(
            engine.merge, [(s, t) for s in samples.upstream_small], merge_iterations
        )
    if samples.upstream_large:
        results["Q4r sklejanie zlewni >100 (realne)"] = measure(
            engine.merge,
            [(s, t) for s in samples.upstream_large],
            max(5, merge_iterations // 3),
        )
    return results


def run_landcover_benchmark(
    engine, boundaries: list, iterations: int
) -> TimingStats | None:
    if not boundaries:
        return None
    return measure(engine.q9_landcover, [(b,) for b in boundaries], iterations)


def run_throughput(engine, samples: Samples, threads: int, operations: int) -> float:
    """Operations per second for a realistic request (Q1 + small merge)."""
    t = samples.threshold
    merge_sets = samples.upstream_small or [samples.consecutive_10]
    jobs = [
        (samples.points[i % len(samples.points)], merge_sets[i % len(merge_sets)])
        for i in range(operations)
    ]
    workers = [engine.clone() for _ in range(threads)]

    def work(worker_index: int):
        worker = workers[worker_index]
        for (x, y), merge_set in jobs[worker_index::threads]:
            worker.q1_contains(x, y, t)
            worker.merge(merge_set, t)

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=threads) as pool:
        list(pool.map(work, range(threads)))
    elapsed = time.perf_counter() - start
    for worker in workers:
        if worker is not engine:
            worker.close()
    return round(operations / elapsed, 1)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def stats_row(name: str, a: TimingStats | None, b: TimingStats | None) -> str:
    def cell(s):
        return f"{s.median_ms:.3f} / {s.p95_ms:.3f}" if s else "—"

    ratio = f"{b.median_ms / a.median_ms:.2f}×" if a and b and a.median_ms > 0 else "—"
    return f"| {name} | {cell(a)} | {cell(b)} | {ratio} |"


def write_report(out_dir: Path, result: dict) -> Path:
    lines = [
        "# Benchmark: PostGIS vs pliki w pamięci (Hydrograf)",
        "",
        f"Data: {result['date']}  ",
        f"Próg zlewni: {result['threshold']} m²  ",
        f"Maszyna: {result['environment']['platform']}, "
        f"CPU: {result['environment']['cpu_count']}  ",
        f"Wersje: {result['environment']['versions']}",
        "",
        "## 1. Dane",
        "",
        "| Warstwa | Obiektów |",
        "|---|---|",
    ]
    for layer in EXPORT_QUERIES:
        lines.append(f"| {layer} | {result['export'][layer]['rows']} |")
    lines += [
        "",
        f"GeoPackage: {result['export']['gpkg_size_mb']} MB, "
        f"GeoParquet: {result['export']['parquet_size_mb']} MB",
        "",
        "## 2. Wczytanie danych (koszt przełączenia wersji warstwy)",
        "",
        "| Format | Odczyt [s] | Indeksy [s] | Razem [s] | Przyrost RAM [MB] |",
        "|---|---|---|---|---|",
    ]
    for fmt, values in result["loading"].items():
        lines.append(
            f"| {fmt} | {values['read_s']} | {values['build_index_s']} | "
            f"{values['total_s']} | {values['memory_growth_mb']} |"
        )
    lines += [
        "",
        "## 3. Zapytania (mediana / p95 w ms)",
        "",
        "Kolumna „Stosunek” = mediana pamięci / mediana PostGIS (< 1 → pliki szybsze).",
        "",
        "| Zapytanie | PostGIS | Pliki + pamięć | Stosunek |",
        "|---|---|---|---|",
    ]
    pg_stats, mem_stats = (
        result["queries"]["PostGIS"],
        result["queries"]["Pliki + pamięć"],
    )
    for name in pg_stats:
        lines.append(stats_row(name, pg_stats[name], mem_stats.get(name)))
    lines += ["", "## 4. Poprawność (czy oba silniki dają te same wyniki)", ""]
    for name, verdict in result["correctness"].items():
        lines.append(f"- **{name}:** {verdict}")
    if result.get("throughput"):
        lines += [
            "",
            f"## 5. Przepustowość ({result['throughput']['threads']} wątki, "
            f"Q1 + sklejanie małej zlewni)",
            "",
            "| Silnik | Operacji/s |",
            "|---|---|",
            f"| PostGIS | {result['throughput']['PostGIS']} |",
            f"| Pliki + pamięć | {result['throughput']['Pliki + pamięć']} |",
        ]
    lines += [
        "",
        "## Ograniczenia",
        "",
        "- Jeden proces Pythona; wiele procesów API (każdy z własną kopią danych)"
        " nie było mierzone.",
        "- Kafelki mapy (MVT/PMTiles) nie są objęte pomiarem.",
        "- PostGIS działa na tej samej maszynie"
        " (brak opóźnień sieci między serwerami).",
        "- Sklejanie >100 zlewni: PostGIS jak w Hydrografie"
        " (przyciąganie do siatki 10 m + wsady po 50),",
        "  pamięć bez przyciągania (zwykły union; dla zlewni z rastra wynik dokładny).",
        "",
    ]
    path = out_dir / "raport.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def to_jsonable(value):
    if isinstance(value, TimingStats):
        return value.__dict__
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    return value


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Porównanie szybkości zapytań Hydrografa:"
            " PostGIS vs pliki wczytane do pamięci."
        )
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DATABASE_URL"),
        help="Adres bazy PostGIS (domyślnie zmienna DATABASE_URL).",
    )
    parser.add_argument(
        "--out-dir",
        default="wyniki_benchmarku",
        type=Path,
        help="Katalog na pliki GPKG/Parquet i raport.",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="Próg zlewni w m² (domyślnie najmniejszy w bazie).",
    )
    parser.add_argument(
        "--samples", type=int, default=50, help="Liczba losowych punktów testowych."
    )
    parser.add_argument(
        "--iterations", type=int, default=200, help="Powtórzenia szybkich zapytań."
    )
    parser.add_argument(
        "--merge-iterations", type=int, default=30, help="Powtórzenia sklejania granic."
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=4,
        help="Wątki w teście przepustowości (0 = pomiń).",
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Ziarno losowania (powtarzalność)."
    )
    parser.add_argument(
        "--skip-export",
        action="store_true",
        help="Użyj plików z poprzedniego uruchomienia zamiast eksportu z bazy.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.db_url:
        print("BŁĄD: podaj adres bazy przez --db-url albo zmienną DATABASE_URL.")
        sys.exit(1)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    db = create_engine(
        normalize_db_url(args.db_url), pool_size=max(args.threads, 1) + 1
    )

    print("[1/6] Eksport danych z PostGIS do GPKG i GeoParquet")
    export_info_path = args.out_dir / "eksport.json"
    if args.skip_export and export_info_path.exists():
        export_info = json.loads(export_info_path.read_text(encoding="utf-8"))
        print("  pominięto (używam istniejących plików)")
    else:
        export_info = export_from_postgis(db, args.out_dir)
        export_info_path.write_text(json.dumps(export_info, indent=2), encoding="utf-8")

    print("[2/6] Wczytanie plików do pamięci i budowa indeksów")
    loading, memory_engine = measure_loading(args.out_dir)

    print("[3/6] Losowanie danych testowych")
    catchments = gpd.read_parquet(args.out_dir / "stream_catchments.parquet")
    threshold = args.threshold or int(catchments["threshold_m2"].min())
    samples = build_samples(catchments, threshold, args.samples, args.seed)
    print(
        f"  próg {threshold} m², punktów: {len(samples.points)}, zlewni 5-100: "
        f"{len(samples.upstream_small)}, zlewni >100: {len(samples.upstream_large)}"
    )

    postgis_engine = PostgisEngine(db)
    print("[4/6] Sprawdzenie poprawności wyników")
    correctness = check_correctness(postgis_engine, memory_engine, samples)
    for name, verdict in correctness.items():
        print(f"  {name}: {verdict}")

    print("[5/6] Pomiar czasu zapytań")
    queries = {}
    boundaries = [
        postgis_engine.merge(s, threshold) for s in samples.upstream_small[:10]
    ]
    boundaries = [b for b in boundaries if b is not None]
    for engine in (postgis_engine, memory_engine):
        print(f"  silnik: {engine.name}")
        queries[engine.name] = run_query_benchmarks(
            engine, samples, args.iterations, args.merge_iterations
        )
        landcover = run_landcover_benchmark(engine, boundaries, args.merge_iterations)
        if landcover and memory_engine.landcover_tree is not None:
            queries[engine.name]["Q9 nakładka pokrycia terenu (CN)"] = landcover

    throughput = None
    if args.threads > 0:
        print(f"[6/6] Przepustowość z {args.threads} wątkami")
        operations = max(args.threads * 20, 40)
        throughput = {
            "threads": args.threads,
            "PostGIS": run_throughput(
                postgis_engine, samples, args.threads, operations
            ),
            "Pliki + pamięć": run_throughput(
                memory_engine, samples, args.threads, operations
            ),
        }
    postgis_engine.close()

    result = {
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "threshold": threshold,
        "environment": {
            "platform": platform.platform(),
            "cpu_count": os.cpu_count(),
            "versions": (
                f"Python {platform.python_version()}, shapely {shapely.__version__}, "
                f"GEOS {shapely.geos_version_string}, geopandas {gpd.__version__}"
            ),
        },
        "export": export_info,
        "loading": loading,
        "queries": queries,
        "correctness": correctness,
        "throughput": throughput,
    }
    (args.out_dir / "wyniki.json").write_text(
        json.dumps(to_jsonable(result), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    report_path = write_report(args.out_dir, result)
    print(f"\nGotowe. Raport: {report_path}")


if __name__ == "__main__":
    main()
