"""
Performance benchmarks for PostGIS spatial queries (ADR-039).

Measures latency of key database queries used in catchment selection
and watershed delineation pipeline. All queries run against real
PostGIS with production data.

Run: cd backend && .venv/bin/python -m pytest tests/performance/ -m benchmark -v
"""
# Register DB fixtures from conftest_db
pytest_plugins = ["tests.conftest_db"]

import statistics
import time

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from tests.conftest_db import requires_db

N_ITERATIONS = 100


def _run_benchmark(session, query_text, params, n=N_ITERATIONS):
    """Run a query n times and return timing statistics."""
    times = []
    for _ in range(n):
        start = time.perf_counter()
        session.execute(text(query_text), params).fetchall()
        elapsed = (time.perf_counter() - start) * 1000  # ms
        times.append(elapsed)

    times.sort()
    p95_idx = int(n * 0.95)
    return {
        "min_ms": round(times[0], 3),
        "mean_ms": round(statistics.mean(times), 3),
        "median_ms": round(statistics.median(times), 3),
        "p95_ms": round(times[p95_idx], 3),
        "max_ms": round(times[-1], 3),
        "iterations": n,
    }


@requires_db
@pytest.mark.benchmark
@pytest.mark.db
class TestQueryPerformance:
    """Benchmark key PostGIS queries for catchment selection."""

    @pytest.fixture(autouse=True)
    def _setup(self, db_engine, setup_test_data):
        """Ensure test data is loaded."""
        Session = sessionmaker(bind=db_engine)
        self.session = Session()

        # Find a valid test point (centroid of first catchment)
        result = self.session.execute(text(
            "SELECT segment_idx, threshold_m2, "
            "ST_X(ST_Centroid(geom)) as cx, ST_Y(ST_Centroid(geom)) as cy "
            "FROM stream_catchments WHERE threshold_m2 = 1000 LIMIT 1"
        )).fetchone()

        if result is None:
            pytest.skip("No catchment data available")

        self.test_x = result.cx
        self.test_y = result.cy
        self.test_seg_idx = result.segment_idx
        self.test_threshold = result.threshold_m2

        # Find 10 and 50 consecutive segment indices for merge tests
        segs = self.session.execute(text(
            "SELECT segment_idx FROM stream_catchments "
            "WHERE threshold_m2 = 1000 ORDER BY segment_idx LIMIT 50"
        )).fetchall()
        self.seg_10 = [r.segment_idx for r in segs[:10]]
        self.seg_50 = [r.segment_idx for r in segs[:50]]

        yield
        self.session.close()

    def test_bench_st_contains(self):
        """Q1: ST_Contains point-in-polygon lookup (catchment_graph.py:272-280)."""
        stats = _run_benchmark(
            self.session,
            "SELECT segment_idx FROM stream_catchments "
            "WHERE threshold_m2 = :threshold "
            "AND ST_Contains(geom, ST_SetSRID(ST_Point(:x, :y), 2180)) "
            "LIMIT 1",
            {"threshold": self.test_threshold, "x": self.test_x, "y": self.test_y},
        )
        print(f"\n  Q1 ST_Contains: {stats}")
        assert stats["p95_ms"] < 50, f"ST_Contains p95 too slow: {stats['p95_ms']}ms"

    def test_bench_segment_lookup(self):
        """Q2: Segment lookup by (threshold, segment_idx).

        Reference: watershed_service.py:59-75.
        """
        stats = _run_benchmark(
            self.session,
            "SELECT segment_idx, strahler_order, ST_Length(geom) as length_m, "
            "upstream_area_km2, ST_X(ST_EndPoint(geom)) as downstream_x, "
            "ST_Y(ST_EndPoint(geom)) as downstream_y "
            "FROM stream_network "
            "WHERE threshold_m2 = :threshold AND segment_idx = :seg_idx LIMIT 1",
            {"threshold": self.test_threshold, "seg_idx": self.test_seg_idx},
        )
        print(f"\n  Q2 Segment lookup: {stats}")
        assert stats["p95_ms"] < 10, f"Segment lookup p95 too slow: {stats['p95_ms']}ms"

    def test_bench_boundary_merge_10(self):
        """Q3: ST_UnaryUnion + Chaikin for 10 segments.

        Reference: watershed_service.py:155-179.
        """
        stats = _run_benchmark(
            self.session,
            "SELECT ST_AsBinary(ST_Multi(ST_MakeValid("
            "ST_ChaikinSmoothing(ST_SimplifyPreserveTopology("
            "ST_Buffer(ST_Buffer(ST_UnaryUnion(ST_Collect(geom)), 0.1), -0.1), "
            "5.0), 3)))) as geom "
            "FROM stream_catchments "
            "WHERE threshold_m2 = :threshold AND segment_idx = ANY(:idxs)",
            {"threshold": self.test_threshold, "idxs": self.seg_10},
            n=50,  # Fewer iterations for expensive query
        )
        print(f"\n  Q3 Boundary merge (10 segs): {stats}")
        assert stats["p95_ms"] < 200, f"Merge 10 p95 too slow: {stats['p95_ms']}ms"

    def test_bench_boundary_merge_50(self):
        """Q4: ST_UnaryUnion + Chaikin for 50 segments.

        Reference: watershed_service.py:155-179.
        """
        stats = _run_benchmark(
            self.session,
            "SELECT ST_AsBinary(ST_Multi(ST_MakeValid("
            "ST_ChaikinSmoothing(ST_SimplifyPreserveTopology("
            "ST_Buffer(ST_Buffer(ST_UnaryUnion(ST_Collect(geom)), 0.1), -0.1), "
            "5.0), 3)))) as geom "
            "FROM stream_catchments "
            "WHERE threshold_m2 = :threshold AND segment_idx = ANY(:idxs)",
            {"threshold": self.test_threshold, "idxs": self.seg_50},
            n=50,
        )
        print(f"\n  Q4 Boundary merge (50 segs): {stats}")
        assert stats["p95_ms"] < 500, f"Merge 50 p95 too slow: {stats['p95_ms']}ms"

    def test_bench_outlet_extraction(self):
        """Q5: ST_EndPoint outlet extraction (watershed_service.py:204-219)."""
        stats = _run_benchmark(
            self.session,
            "SELECT ST_X(ST_EndPoint(geom)) as x, ST_Y(ST_EndPoint(geom)) as y "
            "FROM stream_network "
            "WHERE segment_idx = :seg_idx AND threshold_m2 = :threshold LIMIT 1",
            {"seg_idx": self.test_seg_idx, "threshold": self.test_threshold},
        )
        print(f"\n  Q5 Outlet extraction: {stats}")
        assert stats["p95_ms"] < 10, f"Outlet p95 too slow: {stats['p95_ms']}ms"

    def test_bench_main_stream_geojson(self):
        """Q6: ST_AsGeoJSON + ST_Transform (watershed_service.py:281-296)."""
        stats = _run_benchmark(
            self.session,
            "SELECT ST_AsGeoJSON(ST_Transform(geom, 4326)) as geojson "
            "FROM stream_network "
            "WHERE segment_idx = :seg_idx AND threshold_m2 = :threshold LIMIT 1",
            {"seg_idx": self.test_seg_idx, "threshold": self.test_threshold},
        )
        print(f"\n  Q6 Main stream GeoJSON: {stats}")
        assert stats["p95_ms"] < 20, f"GeoJSON p95 too slow: {stats['p95_ms']}ms"

    def test_bench_st_distance_old(self):
        """Q7: Old ST_DWithin + ORDER BY ST_Distance (comparison baseline)."""
        stats = _run_benchmark(
            self.session,
            "SELECT segment_idx, "
            "ST_Distance(geom, ST_SetSRID(ST_Point(:x, :y), 2180)) as dist "
            "FROM stream_network "
            "WHERE threshold_m2 = :threshold "
            "AND ST_DWithin(geom, ST_SetSRID(ST_Point(:x, :y), 2180), 500) "
            "ORDER BY dist LIMIT 1",
            {"threshold": self.test_threshold, "x": self.test_x, "y": self.test_y},
        )
        print(f"\n  Q7 ST_Distance (old approach): {stats}")
        # This is comparison only — no assertion on speed

    def test_bench_full_pipeline(self):
        """Q8: Full pipeline: ST_Contains -> lookup -> merge -> outlet -> GeoJSON."""
        def _pipeline():
            start = time.perf_counter()
            # Step 1: ST_Contains
            r1 = self.session.execute(
                text(
                    "SELECT segment_idx FROM stream_catchments "
                    "WHERE threshold_m2 = :threshold "
                    "AND ST_Contains(geom, "
                    "ST_SetSRID(ST_Point(:x, :y), 2180)) "
                    "LIMIT 1"
                ),
                {
                    "threshold": self.test_threshold,
                    "x": self.test_x,
                    "y": self.test_y,
                },
            ).fetchone()
            if r1 is None:
                return None
            seg_idx = r1.segment_idx

            # Step 2: Segment lookup
            self.session.execute(
                text(
                    "SELECT segment_idx, strahler_order, "
                    "ST_Length(geom), upstream_area_km2 "
                    "FROM stream_network "
                    "WHERE threshold_m2 = :threshold "
                    "AND segment_idx = :seg_idx"
                ),
                {
                    "threshold": self.test_threshold,
                    "seg_idx": seg_idx,
                },
            ).fetchone()

            # Step 3: Boundary merge (5 segs for realistic scenario)
            self.session.execute(
                text(
                    "SELECT ST_AsBinary(ST_Multi(ST_MakeValid("
                    "ST_ChaikinSmoothing("
                    "ST_SimplifyPreserveTopology("
                    "ST_Buffer(ST_Buffer("
                    "ST_UnaryUnion(ST_Collect(geom))"
                    ", 0.1), -0.1), "
                    "5.0), 3)))) as geom "
                    "FROM stream_catchments "
                    "WHERE threshold_m2 = :threshold "
                    "AND segment_idx = ANY(:idxs)"
                ),
                {
                    "threshold": self.test_threshold,
                    "idxs": self.seg_10[:5],
                },
            ).fetchone()

            # Step 4: Outlet
            self.session.execute(
                text(
                    "SELECT ST_X(ST_EndPoint(geom)) as x, "
                    "ST_Y(ST_EndPoint(geom)) as y "
                    "FROM stream_network "
                    "WHERE segment_idx = :seg_idx "
                    "AND threshold_m2 = :threshold "
                    "LIMIT 1"
                ),
                {
                    "seg_idx": seg_idx,
                    "threshold": self.test_threshold,
                },
            ).fetchone()

            # Step 5: GeoJSON
            self.session.execute(
                text(
                    "SELECT ST_AsGeoJSON("
                    "ST_Transform(geom, 4326)) as geojson "
                    "FROM stream_network "
                    "WHERE segment_idx = :seg_idx "
                    "AND threshold_m2 = :threshold "
                    "LIMIT 1"
                ),
                {
                    "seg_idx": seg_idx,
                    "threshold": self.test_threshold,
                },
            ).fetchone()

            return (time.perf_counter() - start) * 1000

        times = [_pipeline() for _ in range(50)]
        times = [t for t in times if t is not None]
        times.sort()

        p95_idx = int(len(times) * 0.95)
        stats = {
            "min_ms": round(times[0], 3),
            "mean_ms": round(statistics.mean(times), 3),
            "p95_ms": round(times[p95_idx], 3),
            "max_ms": round(times[-1], 3),
            "iterations": len(times),
        }
        print(f"\n  Q8 Full pipeline: {stats}")
        assert stats["p95_ms"] < 300, f"Full pipeline p95 too slow: {stats['p95_ms']}ms"
