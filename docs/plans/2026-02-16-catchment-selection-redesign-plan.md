# Catchment Selection Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace snap-to-stream selection with direct catchment polygon lookup, remove threshold 100 m² catchments, increase geometry simplification.

**Architecture:** Direct `ST_Contains` on `stream_catchments` replaces two-step snap-to-stream + catchment lookup. Threshold 100 m² remains in `stream_network` (visualization) but is removed from `stream_catchments` (analysis). Geometry simplification increases from `cellsize/2` to `cellsize` in the pipeline.

**Tech Stack:** Python 3.12, FastAPI, PostGIS, SQLAlchemy, Alembic, numpy, scipy, Shapely, pytest

**Design doc:** `docs/plans/2026-02-16-catchment-selection-redesign.md`

---

### Kluczowy problem: segment_idx vs stream_network.id

`stream_network.id` jest auto-increment globalny. Przy progu 100 (pierwszym wstawianym) id=1..105492 pokrywa się z `stream_catchments.segment_idx`. Przy progach 1000+ id przesuwa się o offset i **nie pokrywa się**. Po usunięciu progu 100 z catchmentów, BFS daje `segment_idx` ze `stream_catchments`, którego nie da się wprost użyć do odpytania `stream_network.id`.

**Rozwiązanie:** Migracja 014 dodaje kolumnę `segment_idx` do `stream_network`. Pipeline wstawia 1-based index per threshold. Zapytania używają `(threshold_m2, segment_idx)` zamiast `id`.

---

### Task 1: Migracja 014 — segment_idx w stream_network

**Files:**
- Create: `backend/migrations/versions/014_add_segment_idx_to_stream_network.py`

**Step 1: Write migration**

```python
"""
Add segment_idx column to stream_network.

Enables lookup by (threshold_m2, segment_idx) instead of auto-increment id,
which diverges from stream_catchments.segment_idx at coarse thresholds.

Revision ID: 014
Revises: 013
Create Date: 2026-02-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "014"
down_revision: str | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE stream_network ADD COLUMN segment_idx INTEGER")
    op.execute(
        "CREATE INDEX idx_stream_threshold_segidx "
        "ON stream_network (threshold_m2, segment_idx)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_stream_threshold_segidx")
    op.execute("ALTER TABLE stream_network DROP COLUMN IF EXISTS segment_idx")
```

**Step 2: Commit**

```bash
git add backend/migrations/versions/014_add_segment_idx_to_stream_network.py
git commit -m "feat(db): migracja 014 — segment_idx w stream_network"
```

---

### Task 2: Pipeline — segment_idx w insert_stream_segments

**Files:**
- Modify: `backend/core/db_bulk.py` (function `insert_stream_segments`, ~line 635)

**Step 1: Write failing test**

File: `backend/tests/unit/test_db_bulk.py`

Dodaj test sprawdzający, że `insert_stream_segments` zapisuje `segment_idx` (1-based) dla każdego segmentu:

```python
def test_insert_stream_segments_saves_segment_idx(mock_db_session):
    """Verify segment_idx (1-based) is written to stream_network."""
    segments = [
        {
            "coords": [(500000, 600000), (500100, 600100)],
            "strahler_order": 1,
            "length_m": 141.4,
            "upstream_area_km2": 0.01,
            "mean_slope_percent": 2.0,
        },
        {
            "coords": [(500200, 600200), (500300, 600300)],
            "strahler_order": 2,
            "length_m": 141.4,
            "upstream_area_km2": 0.05,
            "mean_slope_percent": 1.5,
        },
    ]
    result = insert_stream_segments(mock_db_session, segments, threshold_m2=1000)
    assert result == 2

    # Verify TSV contains segment_idx = 1 and 2
    copy_call = mock_db_session._mock_cursor.copy_expert.call_args
    tsv_content = copy_call[0][1].getvalue()
    lines = tsv_content.strip().split("\n")
    assert lines[0].split("\t")[-1] == "1"  # segment_idx=1
    assert lines[1].split("\t")[-1] == "2"  # segment_idx=2
```

**Step 2: Run test — expect FAIL**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_db_bulk.py::test_insert_stream_segments_saves_segment_idx -v
```

**Step 3: Implement**

W `insert_stream_segments()` (db_bulk.py):

1. Dodaj `segment_idx` do temp table:
```sql
CREATE TEMP TABLE temp_stream_import (
    wkt TEXT,
    strahler_order INT,
    length_m FLOAT,
    upstream_area_km2 FLOAT,
    mean_slope_percent FLOAT,
    source TEXT,
    threshold_m2 INT,
    segment_idx INT          -- NOWA KOLUMNA
)
```

2. Dodaj `segment_idx` do TSV (1-based enumerate):
```python
for i, seg in enumerate(segments, start=1):
    # ... existing TSV fields ...
    tsv_buffer.write(
        f"{wkt}\t{seg['strahler_order']}\t"
        f"{seg['length_m']}\t{seg['upstream_area_km2']}\t"
        f"{seg['mean_slope_percent']}\tDEM_DERIVED\t"
        f"{threshold_m2}\t{i}\n"  # segment_idx=i
    )
```

3. Dodaj `segment_idx` do INSERT:
```sql
INSERT INTO stream_network (
    geom, strahler_order, length_m,
    upstream_area_km2, mean_slope_percent, source,
    threshold_m2, segment_idx           -- NOWA KOLUMNA
)
SELECT
    ST_SetSRID(ST_GeomFromText(wkt), 2180),
    strahler_order, length_m,
    upstream_area_km2, mean_slope_percent, source,
    threshold_m2, segment_idx           -- NOWA KOLUMNA
FROM temp_stream_import
ON CONFLICT DO NOTHING
```

**Step 4: Run test — expect PASS**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_db_bulk.py::test_insert_stream_segments_saves_segment_idx -v
```

**Step 5: Commit**

```bash
git add backend/core/db_bulk.py backend/tests/unit/test_db_bulk.py
git commit -m "feat(core): segment_idx w insert_stream_segments (1-based per threshold)"
```

---

### Task 3: Pipeline — pominięcie catchmentów dla progu 100 + zwiększenie simplify

**Files:**
- Modify: `backend/scripts/process_dem.py` (~lines 350-490)
- Modify: `backend/core/stream_extraction.py` (~line 464)

**Step 1: Zmień `process_dem.py` — rozdziel progi stream vs catchment**

Przed pętlą threshold (linia ~352):

```python
DEFAULT_THRESHOLDS_M2 = [100, 1000, 10000, 100000]

# Catchments only for thresholds >= 1000 m²
MIN_CATCHMENT_THRESHOLD_M2 = 1000
```

W pętli (linia ~462), warunek generowania catchmentów:

```python
            # Delineate and polygonize sub-catchments (skip finest threshold)
            generate_catchments = (
                not skip_catchments
                and label_raster is not None
                and threshold_m2 >= MIN_CATCHMENT_THRESHOLD_M2
            )
            if generate_catchments:
                delineate_subcatchments(flw, label_raster, filled_dem, nodata)
                # ... rest of catchment logic unchanged ...
```

Notatka: `label_raster` nadal alokowany dla każdego progu (potrzebny do `vectorize_streams`), ale catchment delineation + polygonization pomijane dla progu 100.

**Step 2: Zmień `stream_extraction.py` — zwiększ tolerancję simplify**

Linia ~464:

```python
# Przed:
simplify_tol = cellsize / 2
# Po:
simplify_tol = cellsize
```

**Step 3: Commit**

```bash
git add backend/scripts/process_dem.py backend/core/stream_extraction.py
git commit -m "feat(pipeline): skip catchments for threshold 100, simplify tolerance 1 cell"
```

---

### Task 4: Constants + schemat API

**Files:**
- Modify: `backend/core/constants.py` (line 26)
- Modify: `backend/models/schemas.py` (~lines 387-394)

**Step 1: Zmień DEFAULT_THRESHOLD_M2**

```python
# Przed:
DEFAULT_THRESHOLD_M2 = 100
# Po:
DEFAULT_THRESHOLD_M2 = 1000
```

**Step 2: Usuń `display_threshold_m2` z SelectStreamRequest**

Pole `display_threshold_m2` staje się zbędne — nie ma rozdzielenia na fine/display threshold. BFS zawsze na progu z requestu (`threshold_m2`).

Usuń z `SelectStreamRequest` (schemas.py):
```python
    display_threshold_m2: int | None = Field(...)  # USUNĄĆ
```

`display_threshold_m2` w `SelectStreamResponse` **zostaje** — informuje frontend o progu indeksów.

**Step 3: Commit**

```bash
git add backend/core/constants.py backend/models/schemas.py
git commit -m "feat(api): DEFAULT_THRESHOLD_M2=1000, remove display_threshold_m2 from request"
```

---

### Task 5: watershed_service.py — nowa funkcja lookup + cleanup

**Files:**
- Modify: `backend/core/watershed_service.py`
- Modify: `backend/tests/unit/test_watershed_service.py`

**Step 1: Nowa funkcja `get_stream_info_by_segment_idx`**

Zastępuje `find_nearest_stream_segment` — szuka cieku po `(threshold_m2, segment_idx)` zamiast spatial proximity:

```python
def get_stream_info_by_segment_idx(
    segment_idx: int,
    threshold_m2: int,
    db: Session,
) -> dict | None:
    """
    Get stream segment info by segment_idx and threshold.

    Uses the segment_idx column (1-based per threshold) for exact lookup
    instead of spatial proximity search.
    """
    query = text("""
        SELECT
            segment_idx,
            strahler_order,
            ST_Length(geom) as length_m,
            upstream_area_km2,
            ST_X(ST_EndPoint(geom)) as downstream_x,
            ST_Y(ST_EndPoint(geom)) as downstream_y
        FROM stream_network
        WHERE threshold_m2 = :threshold
          AND segment_idx = :seg_idx
        LIMIT 1
    """)
    result = db.execute(
        query,
        {"threshold": threshold_m2, "seg_idx": segment_idx},
    ).fetchone()
    if result is None:
        return None
    return {
        "segment_idx": result.segment_idx,
        "strahler_order": result.strahler_order,
        "length_m": result.length_m,
        "upstream_area_km2": result.upstream_area_km2,
        "downstream_x": result.downstream_x,
        "downstream_y": result.downstream_y,
    }
```

**Step 2: Zaktualizuj `get_segment_outlet`**

Zmień zapytanie z `WHERE id = :seg_idx` na `WHERE segment_idx = :seg_idx`:

```python
    query = text("""
        SELECT
            ST_X(ST_EndPoint(geom)) as x,
            ST_Y(ST_EndPoint(geom)) as y
        FROM stream_network
        WHERE segment_idx = :seg_idx
          AND threshold_m2 = :threshold
        LIMIT 1
    """)
```

**Step 3: Zaktualizuj `get_main_stream_geojson`**

Tak samo — `WHERE segment_idx = :seg_idx`:

```python
    query = text("""
        SELECT ST_AsGeoJSON(ST_Transform(geom, 4326)) as geojson
        FROM stream_network
        WHERE segment_idx = :seg_idx
          AND threshold_m2 = :threshold
        LIMIT 1
    """)
```

**Step 4: Zaktualizuj `get_main_stream_coords_2180`**

Tak samo — `WHERE segment_idx = :seg_idx`.

**Step 5: Write tests**

Dodaj test `test_get_stream_info_by_segment_idx` mockujący DB result.

**Step 6: Run tests**

```bash
cd backend && .venv/bin/python -m pytest tests/unit/test_watershed_service.py -v
```

**Step 7: Commit**

```bash
git add backend/core/watershed_service.py backend/tests/unit/test_watershed_service.py
git commit -m "feat(core): lookup stream by segment_idx instead of auto-increment id"
```

---

### Task 6: select_stream.py — uproszczenie selekcji

**Files:**
- Modify: `backend/api/endpoints/select_stream.py` (cały plik ~395 linii → ~300)
- Modify: `backend/tests/integration/test_select_stream.py`

**Step 1: Przepisz flow selekcji**

Nowy flow (zastępuje linie 63-220 obecnego kodu):

```
1. Transform WGS84 → PL-1992
2. CatchmentGraph.find_catchment_at_point(x, y, threshold_m2, db)
   → internal_idx (direct ST_Contains, no snap)
3. segment_idx = cg._segment_idx[internal_idx]
4. BFS: cg.traverse_upstream(internal_idx)
5. Segment indices: cg.get_segment_indices(upstream, threshold_m2)
6. Stream info: get_stream_info_by_segment_idx(segment_idx, threshold_m2, db)
7. Cascaded merge (jeśli >500 segmentów, cascade do coarser threshold)
8. Boundary: merge_catchment_boundaries(...)
9. Display indices = bfs_segment_idxs (same threshold, no cross-threshold mapping)
```

Kluczowe usunięcia:
- Cały blok `use_fine_bfs` (ADR-024) — nie ma progu 100
- `find_nearest_stream_segment()` — nie używane
- `find_stream_catchment_at_point()` — zastąpione przez `cg.find_catchment_at_point()`
- `display_threshold_m2` / `display_threshold` logic — threshold jest jeden
- `map_boundary_to_display_segments()` — nie potrzebne (BFS i display na tym samym progu)

Kluczowe uproszczenia:
- `threshold = request.threshold_m2` — jedyny próg w całym flow
- Cascade merge: nadal `for t in [1000, 10000, 100000]` ale bez warunku `t <= bfs_threshold`
- Response: `display_threshold_m2 = request.threshold_m2` (zawsze taki sam)

Import cleanup — usunąć:
```python
from core.watershed_service import find_nearest_stream_segment, find_stream_catchment_at_point, map_boundary_to_display_segments
```

Dodać:
```python
from core.watershed_service import get_stream_info_by_segment_idx
```

**Step 2: Update tests**

Testy do usunięcia/przepisania:
- `test_fine_threshold_bfs_with_display_mapping` — ADR-024 logic removed
- `test_fine_threshold_100_uses_adr024_logic` — ADR-024 logic removed
- `test_coarse_threshold_uses_display_threshold` — display_threshold removed

Nowy test:
- `test_direct_catchment_lookup` — mockuje `cg.find_catchment_at_point()`, weryfikuje że `find_nearest_stream_segment` NIE jest wywoływane
- `test_cascaded_merge_at_coarse_threshold` — dużo segmentów, kaskada do grubszego progu

**Step 3: Run all tests**

```bash
cd backend && .venv/bin/python -m pytest tests/ -v
```

**Step 4: Commit**

```bash
git add backend/api/endpoints/select_stream.py backend/tests/integration/test_select_stream.py
git commit -m "refactor(api): direct catchment lookup in select-stream, remove ADR-024/025"
```

---

### Task 7: watershed.py + hydrograph.py — ten sam wzorzec

**Files:**
- Modify: `backend/api/endpoints/watershed.py` (~lines 108-212)
- Modify: `backend/api/endpoints/hydrograph.py` (~lines 128-210)
- Modify: `backend/tests/integration/test_watershed.py`
- Modify: `backend/tests/integration/test_hydrograph.py`

**Step 1: watershed.py**

Nowy flow:
```
1. Transform → PL-1992
2. cg.find_catchment_at_point(x, y, DEFAULT_THRESHOLD_M2, db)
3. segment_idx = cg._segment_idx[clicked_idx]
4. stream_info = get_stream_info_by_segment_idx(segment_idx, DEFAULT_THRESHOLD_M2, db)
5. BFS, aggregate, merge — bez zmian
6. outlet z stream_info (nie z find_nearest_stream_segment)
```

Usunąć: `find_nearest_stream_segment()` call (linie 109-119). Segment info brany z nowej funkcji po catchment lookup.

**Step 2: hydrograph.py**

Analogiczna zmiana jak watershed.py.

**Step 3: Run tests**

```bash
cd backend && .venv/bin/python -m pytest tests/ -v
```

**Step 4: Commit**

```bash
git add backend/api/endpoints/watershed.py backend/api/endpoints/hydrograph.py
git add backend/tests/integration/test_watershed.py backend/tests/integration/test_hydrograph.py
git commit -m "refactor(api): watershed+hydrograph use direct catchment lookup"
```

---

### Task 8: Frontend — aktualizacja progów

**Files:**
- Modify: `frontend/js/layers.js` (line 429)
- Modify: `frontend/js/app.js` (threshold references)
- Modify: `frontend/js/map.js` (threshold mismatch guard)

**Step 1: layers.js**

Zmień fallback thresholds:
```javascript
// Przed:
var FALLBACK_THRESHOLDS = [100, 1000, 10000, 100000];
// Po:
var FALLBACK_THRESHOLDS = [1000, 10000, 100000];
```

**Step 2: app.js**

Usuń logikę `THRESHOLD MISMATCH!` — progi są zawsze spójne. Uprość przekazywanie progu do `selectStream()`:
- Nie wysyłaj `display_threshold_m2` w request body (pole usunięte z API)
- `data.display_threshold_m2` w response nadal obsługiwany (ale zawsze = threshold_m2)

**Step 3: map.js**

Usuń guard threshold mismatch w `highlightUpstreamCatchments()` — walidacja progu nie jest potrzebna (jeden próg).

**Step 4: Commit**

```bash
git add frontend/js/layers.js frontend/js/app.js frontend/js/map.js
git commit -m "feat(frontend): remove threshold 100 from catchments, simplify threshold logic"
```

---

### Task 9: Testy — aktualizacja fixture'ów

**Files:**
- Modify: `backend/tests/unit/test_watershed_service.py`
- Modify: `backend/tests/unit/test_db_bulk.py`
- Modify: `backend/tests/integration/test_tiles.py`

**Step 1: test_watershed_service.py**

Zamień `threshold_m2=100` → `threshold_m2=1000` w test fixtures (linie 397, 443, 468, 487).

Usuń testy `find_stream_catchment_at_point` jeśli funkcja jest usunięta.

**Step 2: test_db_bulk.py**

Zamień `threshold_m2=100` → `threshold_m2=1000` w fixture'ach (linie 256, 289, 297).

**Step 3: test_tiles.py**

Zamień `100` na `1000` w fixture'ach stream threshold (linia 56) i oczekiwanych wynikach (linia 260).

**Step 4: Run full test suite**

```bash
cd backend && .venv/bin/python -m pytest tests/ -v
```

Oczekiwany wynik: 0 failures. Liczba testów może się zmniejszyć (usunięte testy ADR-024/025).

**Step 5: Lint**

```bash
cd backend && .venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .
```

**Step 6: Commit**

```bash
git add backend/tests/
git commit -m "test: update fixtures to threshold 1000, remove ADR-024/025 tests"
```

---

### Task 10: Dokumentacja — ADR-026, cleanup

**Files:**
- Modify: `docs/DECISIONS.md`
- Modify: `docs/CHANGELOG.md`
- Modify: `docs/PROGRESS.md`
- Modify: `docs/DATA_MODEL.md` (default threshold)

**Step 1: ADR-026**

```markdown
### ADR-026: Selekcja oparta o poligon zlewni (2026-02-16)

**Status:** Zatwierdzony

**Kontekst:** Snap-to-stream (`ST_ClosestPoint`) powodował błędne przypisanie kliknięcia
do sąsiedniej zlewni, gdy jej ciek płynął blisko granicy. Próg 100 m² generował 105k
zlewni cząstkowych bez praktycznego zastosowania.

**Decyzja:**
1. Selekcja oparta o poligon (`ST_Contains` na `stream_catchments`) zamiast snap-to-stream
2. Usunięcie progu 100 m² ze zlewni cząstkowych (cieki w `stream_network` zostają)
3. Zwiększenie tolerancji simplify geometrii z `cellsize/2` do `cellsize` (1m)
4. Dodanie kolumny `segment_idx` do `stream_network` (migracja 014)
5. `DEFAULT_THRESHOLD_M2 = 1000` (było 100)

**Konsekwencje:**
- ADR-024 (fine-threshold BFS) i ADR-025 (warunkowy próg) stają się nieaktualne
- `stream_catchments`: 117k → ~12k rekordów
- CatchmentGraph: ~5 MB → <1 MB RAM
- Eliminacja `find_nearest_stream_segment()` i `find_stream_catchment_at_point()` z flow selekcji
- Wymaga re-run pipeline
```

**Step 2: Zaktualizuj CHANGELOG, PROGRESS**

**Step 3: Commit**

```bash
git add docs/DECISIONS.md docs/CHANGELOG.md docs/PROGRESS.md docs/DATA_MODEL.md
git commit -m "docs: ADR-026 — selekcja oparta o poligon zlewni"
```

---

### Task 11: Re-run pipeline

**Wymaga uruchomionej bazy danych.**

**Step 1: Migracja**

```bash
cd backend && .venv/bin/python -m alembic upgrade head
```

**Step 2: Re-run pipeline**

```bash
cd backend && .venv/bin/python -m scripts.process_dem \
    --input ../data/nmt/*.asc \
    --clear-existing \
    --stream-threshold 100
```

Oczekiwany wynik:
- `stream_network`: 4 progi (100, 1000, 10000, 100000) — z `segment_idx`
- `stream_catchments`: 3 progi (1000, 10000, 100000) — ~12k rekordów
- Geometrie uproszczone (tolerancja 1m zamiast 0.5m)
- Czas: ~15-20 min (mniej polygonizacji)

**Step 3: Weryfikacja**

```bash
# Sprawdź liczność
docker compose exec db psql -U hydro_user -d hydro_db -c \
    "SELECT threshold_m2, COUNT(*) FROM stream_catchments GROUP BY threshold_m2 ORDER BY 1;"

# Sprawdź segment_idx w stream_network
docker compose exec db psql -U hydro_user -d hydro_db -c \
    "SELECT threshold_m2, MIN(segment_idx), MAX(segment_idx), COUNT(*) FROM stream_network GROUP BY threshold_m2 ORDER BY 1;"

# Sprawdź uproszczenie geometrii (avg vertices)
docker compose exec db psql -U hydro_user -d hydro_db -c \
    "SELECT threshold_m2, AVG(ST_NPoints(geom))::int as avg_vertices FROM stream_catchments GROUP BY threshold_m2 ORDER BY 1;"
```

**Step 4: Restart API**

```bash
docker compose restart api
# Sprawdź logi — CatchmentGraph powinien załadować ~12k nodes
docker compose logs api | tail -5
```

**Step 5: Smoke test**

```bash
curl -s http://localhost/api/tiles/thresholds | python3 -m json.tool
# catchments should NOT contain 100

curl -s -X POST http://localhost/api/select-stream \
    -H "Content-Type: application/json" \
    -d '{"latitude": 52.23, "longitude": 21.01, "threshold_m2": 1000}' | python3 -m json.tool
```
