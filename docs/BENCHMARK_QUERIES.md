# Benchmark zapytań PostGIS — Hydrograf

Dokument śledzący wydajność kluczowych zapytań SQL używanych w selekcji zlewni
i wyznaczaniu granic zlewni (ADR-039).

## 1. Środowisko

| Parametr | Wartość |
|----------|---------|
| PostgreSQL | 16 |
| PostGIS | 3.4 |
| OS | Debian Linux (Docker) |
| shared_buffers | 512MB |
| work_mem | 16MB |
| effective_cache_size | 1536MB |
| jit | off |
| Connection pool | SQLAlchemy (default) |
| Dataset | 10,014 catchments (t=1000), 1,068 (t=10000), 96 (t=100000) |
| stream_catchments | 11 MB (dane 8.6 MB) |
| stream_network | 7.3 MB (dane 3.3 MB) |

## 2. Katalog zapytań

### Q1: ST_Contains — punkt w zlewni

**Źródło:** `catchment_graph.py:272-280`

```sql
SELECT segment_idx FROM stream_catchments
WHERE threshold_m2 = :threshold
AND ST_Contains(geom, ST_SetSRID(ST_Point(:x, :y), 2180))
LIMIT 1
```

**Indeks:** `idx_catchment_geom_t1000` — GiST per-threshold (624 kB)

**EXPLAIN ANALYZE:**
```
Limit  (cost=0.15..14.87 rows=1 width=4) (actual time=0.150..0.150 rows=0 loops=1)
  ->  Index Scan using idx_catchment_geom_t1000 on stream_catchments
        Index Cond: (geom ~ point::geometry)
        Filter: st_contains(geom, point::geometry)
Planning Time: 9.311 ms
Execution Time: 0.195 ms
```

**Baseline (N=100):**

| min | mean | p95 | max |
|-----|------|-----|-----|
| 0.328 ms | 0.632 ms | 0.698 ms | 12.997 ms |

### Q2: Lookup segmentu

**Źródło:** `watershed_service.py:59-75`

```sql
SELECT segment_idx, strahler_order, ST_Length(geom) as length_m,
       upstream_area_km2,
       ST_X(ST_EndPoint(geom)) as downstream_x,
       ST_Y(ST_EndPoint(geom)) as downstream_y
FROM stream_network
WHERE threshold_m2 = :threshold AND segment_idx = :seg_idx
LIMIT 1
```

**Indeks:** `idx_stream_threshold_segidx` — B-tree (272 kB)

**EXPLAIN ANALYZE:**
```
Limit  (cost=0.29..1.74 rows=1 width=40) (actual time=0.022..0.023 rows=1 loops=1)
  ->  Index Scan using idx_stream_threshold_segidx on stream_network
        Index Cond: ((threshold_m2 = 1000) AND (segment_idx = 1))
Planning Time: 0.756 ms
Execution Time: 0.068 ms
```

**Baseline (N=100):**

| min | mean | p95 | max |
|-----|------|-----|-----|
| 0.321 ms | 0.398 ms | 0.551 ms | 0.811 ms |

### Q3: Merge granic (10 segmentów)

**Źródło:** `watershed_service.py:155-179`

```sql
SELECT ST_AsBinary(ST_Multi(ST_MakeValid(
    ST_ChaikinSmoothing(
        ST_SimplifyPreserveTopology(
            ST_Buffer(ST_Buffer(ST_UnaryUnion(ST_Collect(geom)), 0.1), -0.1),
        5.0), 3)
))) as geom
FROM stream_catchments
WHERE threshold_m2 = :threshold AND segment_idx = ANY(:idxs)
```

**Indeks:** Seq Scan (ANY z małą liczbą elementów)

**EXPLAIN ANALYZE:**
```
Aggregate  (cost=1253.88..1317.26 rows=1 width=32) (actual time=4.894..4.895 rows=1 loops=1)
  ->  Seq Scan on stream_catchments
        Filter: ((threshold_m2 = 1000) AND (segment_idx = ANY('{1..10}')))
        Rows Removed by Filter: 10153
Planning Time: 0.804 ms
Execution Time: 13.715 ms
```

**Baseline (N=50):**

| min | mean | p95 | max |
|-----|------|-----|-----|
| 4.018 ms | 4.390 ms | 4.716 ms | 4.880 ms |

### Q4: Merge granic (50 segmentów)

Jak Q3, ale z 50 segmentami. Koszt rośnie nieliniowo z powodu ST_UnaryUnion.

**Baseline (N=50):**

| min | mean | p95 | max |
|-----|------|-----|-----|
| 14.304 ms | 105.401 ms | 248.036 ms | 251.997 ms |

### Q5: Ekstrakcja ujścia

**Źródło:** `watershed_service.py:204-219`

```sql
SELECT ST_X(ST_EndPoint(geom)) as x, ST_Y(ST_EndPoint(geom)) as y
FROM stream_network
WHERE segment_idx = :seg_idx AND threshold_m2 = :threshold
LIMIT 1
```

**Indeks:** `idx_stream_threshold_segidx` — B-tree (272 kB)

**EXPLAIN ANALYZE:**
```
Limit  (cost=0.29..1.61 rows=1 width=16) (actual time=0.007..0.008 rows=1 loops=1)
  ->  Index Scan using idx_stream_threshold_segidx on stream_network
        Index Cond: ((threshold_m2 = 1000) AND (segment_idx = 1))
Planning Time: 0.067 ms
Execution Time: 0.016 ms
```

**Baseline (N=100):**

| min | mean | p95 | max |
|-----|------|-----|-----|
| 0.282 ms | 0.389 ms | 0.581 ms | 0.922 ms |

### Q6: GeoJSON cieku głównego

**Źródło:** `watershed_service.py:281-296`

```sql
SELECT ST_AsGeoJSON(ST_Transform(geom, 4326)) as geojson
FROM stream_network
WHERE segment_idx = :seg_idx AND threshold_m2 = :threshold
LIMIT 1
```

**Indeks:** `idx_stream_threshold_segidx` — B-tree (272 kB)

**EXPLAIN ANALYZE:**
```
Limit  (cost=0.29..14.48 rows=1 width=32) (actual time=17.491..17.492 rows=1 loops=1)
  ->  Index Scan using idx_stream_threshold_segidx on stream_network
        Index Cond: ((threshold_m2 = 1000) AND (segment_idx = 1))
Planning Time: 0.070 ms
Execution Time: 17.525 ms
```

Uwaga: pierwszy wywołanie ST_Transform jest wolne (cold proj cache). Kolejne < 1ms.

**Baseline (N=100):**

| min | mean | p95 | max |
|-----|------|-----|-----|
| 0.283 ms | 0.316 ms | 0.416 ms | 0.529 ms |

### Q7: ST_DWithin + ORDER BY (stare podejście)

**Źródło:** Usunięty kod (odtworzony do porównania z ADR-039)

```sql
SELECT segment_idx,
       ST_Distance(geom, ST_SetSRID(ST_Point(:x, :y), 2180)) as dist
FROM stream_network
WHERE threshold_m2 = :threshold
AND ST_DWithin(geom, ST_SetSRID(ST_Point(:x, :y), 2180), 500)
ORDER BY dist LIMIT 1
```

**EXPLAIN ANALYZE:**
```
Limit  (cost=27.50..27.51 rows=1 width=12) (actual time=0.237..0.238 rows=0 loops=1)
  ->  Sort  (cost=27.50..27.51 rows=1 width=12) (actual time=0.236..0.237 rows=0 loops=1)
        Sort Key: st_distance(geom, point)
        Sort Method: quicksort  Memory: 25kB
        ->  Index Scan using idx_stream_geom_t1000 on stream_network
              Index Cond: (geom && st_expand(point, 500))
              Filter: st_dwithin(geom, point, 500)
Planning Time: 0.321 ms
Execution Time: 0.286 ms
```

**Baseline (N=100):**

| min | mean | p95 | max |
|-----|------|-----|-----|
| 0.586 ms | 0.848 ms | 0.941 ms | 5.434 ms |

### Q8: Pełny pipeline (end-to-end)

Sekwencja: ST_Contains → segment lookup → merge (5 segs) → outlet → GeoJSON.

**Baseline (N=50):**

| min | mean | p95 | max |
|-----|------|-----|-----|
| 4.897 ms | 5.690 ms | 6.164 ms | 6.370 ms |

## 3. Analiza indeksów

### stream_catchments (11 MB total)

| Indeks | Typ | Rozmiar |
|--------|-----|---------|
| `stream_catchments_pkey` | B-tree (PK) | 504 kB |
| `idx_catchment_geom_t1000` | GiST (partial) | 624 kB |
| `idx_catchment_geom_t10000` | GiST (partial) | 64 kB |
| `idx_catchment_geom_t100000` | GiST (partial) | 8 kB |
| `idx_catchments_geom` | GiST (global) | 712 kB |
| `idx_catchments_threshold` | B-tree | 160 kB |
| `idx_catchments_area` | B-tree | 496 kB |
| `idx_catchments_downstream` | B-tree | 384 kB |

### stream_network (7.3 MB total)

| Indeks | Typ | Rozmiar |
|--------|-----|---------|
| `stream_network_pkey` | B-tree (PK) | 272 kB |
| `idx_stream_threshold_segidx` | B-tree (composite) | 272 kB |
| `idx_stream_geom_t1000` | GiST (partial) | 472 kB |
| `idx_stream_geom_t10000` | GiST (partial) | 56 kB |
| `idx_stream_geom_t100000` | GiST (partial) | 8 kB |
| `idx_stream_geom` | GiST (global) | 512 kB |
| `idx_stream_unique` | B-tree (unique) | 640 kB |
| `idx_stream_upstream_area` | B-tree | 360 kB |

## 4. Porównanie ST_Contains vs ST_Distance (ADR-039)

ST_Contains (Q1) vs ST_DWithin+ORDER BY (Q7):

| Metryka | ST_Contains (Q1) | ST_DWithin+ORDER BY (Q7) |
|---------|------------------|--------------------------|
| min | 0.328 ms | 0.586 ms |
| mean | 0.632 ms | 0.848 ms |
| p95 | 0.698 ms | 0.941 ms |
| max | 12.997 ms | 5.434 ms |
| Tabela | `stream_catchments` (poligony) | `stream_network` (linie) |
| Indeks | GiST per-threshold | GiST per-threshold + sort |
| Złożoność | O(log n) | O(log n) + sort |

**Wnioski:**

1. ST_Contains jest ~25% szybsze w mean i p95 od ST_DWithin+ORDER BY
2. ST_Contains odpytuje `stream_catchments` (poligony), ST_DWithin odpytywało `stream_network` (linie)
3. Po ADR-039 cała logika selekcji opiera się na jednym wywołaniu ST_Contains, eliminując
   3-warstwowy fallback chain i upraszczając kod
4. Pełny pipeline (Q8) wykonuje się w ~5.7 ms (mean), co jest poniżej budżetu 100 ms
5. Wąskie gardło: Q4 (merge 50 segmentów) — ST_UnaryUnion rośnie nieliniowo,
   p95=248 ms. Dla dużych zlewni (>500 segmentów) stosowany jest cascade do grubszych progów

## 5. Instrukcja reprodukcji

```bash
# 1. Uruchom bazę danych
docker compose up -d db

# 2. Załaduj dane testowe (opcjonalnie — testy robią to automatycznie)
cd backend
docker compose exec db psql -U hydro_user -d hydro_db \
    -f /dev/stdin < tests/fixtures/test_catchments.sql

# 3. Uruchom benchmarki
cd backend
.venv/bin/python -m pytest tests/performance/ -m benchmark -v -s

# 4. Uruchom EXPLAIN ANALYZE (przez Python)
.venv/bin/python -c "
from sqlalchemy import create_engine, text
e = create_engine('postgresql://hydro_user:hydro_password@localhost:5432/hydro_db')
with e.connect() as c:
    for row in c.execute(text('''
        EXPLAIN (ANALYZE, FORMAT TEXT)
        SELECT segment_idx FROM stream_catchments
        WHERE threshold_m2 = 1000
        AND ST_Contains(geom, ST_SetSRID(ST_Point(639100, 486300), 2180))
        LIMIT 1
    ''')):
        print(row[0])
e.dispose()
"
```
