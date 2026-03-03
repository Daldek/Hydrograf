# Eliminacja tabeli flow_network — Plan implementacji

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Usunac tabele `flow_network` (39.4M rekordow, 58% czasu pipeline) z bazy danych i calego codebase, zachowujac pelna funkcjonalnosc API.

**Architecture:** Pipeline DEM pomija krok tworzenia TSV + INSERT do flow_network. Wektoryzacja ciekow i polygonizacja zlewni juz teraz pracuja na rasterach — zero zmian w logice biznesowej. Usuwamy ~800 linii martwego kodu (db_bulk flow_network functions, flow_graph.py, watershed.py legacy CLI).

**Tech Stack:** Python 3.12, PostgreSQL + PostGIS, Alembic, pytest, ruff

**Design doc:** `docs/plans/2026-02-17-eliminate-flow-network-design.md`

---

## Task 1: Migracja Alembic — DROP TABLE flow_network

**Files:**
- Create: `backend/migrations/versions/015_drop_flow_network.py`

**Step 1: Stworz migracje**

```python
"""
Drop flow_network table.

Table stored every DEM pixel (~39.4M rows) but is not used by any API
endpoint at runtime. Stream/catchment data is served from stream_network
and stream_catchments tables. Saves ~2 GB disk and 17 min pipeline time.

Revision ID: 015
Revises: 014
Create Date: 2026-02-17
"""

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("flow_network")


def downgrade() -> None:
    op.execute("""
        CREATE TABLE flow_network (
            id SERIAL PRIMARY KEY,
            geom geometry(Point, 2180) NOT NULL,
            elevation REAL NOT NULL,
            flow_accumulation INTEGER NOT NULL DEFAULT 0,
            slope REAL,
            downstream_id INTEGER REFERENCES flow_network(id),
            cell_area REAL NOT NULL DEFAULT 1.0,
            is_stream BOOLEAN NOT NULL DEFAULT FALSE,
            strahler_order SMALLINT
        )
    """)
    op.execute("CREATE INDEX idx_flow_geom ON flow_network USING GIST (geom)")
    op.execute("CREATE INDEX idx_downstream ON flow_network (downstream_id)")
    op.execute("CREATE INDEX idx_is_stream ON flow_network (is_stream)")
    op.execute("CREATE INDEX idx_flow_accumulation ON flow_network (flow_accumulation)")
    op.execute("CREATE INDEX idx_strahler ON flow_network (strahler_order)")
```

**Step 2: Uruchom migracje**

Run: `cd backend && .venv/bin/python -m alembic upgrade head`
Expected: Migracja 015 wykonana pomyslnie, tabela flow_network usunieta.

**Step 3: Zweryfikuj**

Run: `docker compose exec db psql -U hydro_user -d hydro_db -c "\dt flow_network"`
Expected: `Did not find any relation named "flow_network"`

**Step 4: Commit**

```bash
git add backend/migrations/versions/015_drop_flow_network.py
git commit -m "feat(db): migracja 015 — DROP TABLE flow_network (ADR-028)"
```

---

## Task 2: Usun flow_network z process_dem.py

**Files:**
- Modify: `backend/scripts/process_dem.py`

**Step 1: Usun importy flow_network z process_dem.py**

W linii 54-61, zmien importy z `core.db_bulk` — usun `create_flow_network_records`, `create_flow_network_tsv`, `insert_records_batch`, `insert_records_batch_tsv`:

```python
# PRZED:
from core.db_bulk import (
    create_flow_network_records,
    create_flow_network_tsv,
    insert_catchments,
    insert_records_batch,
    insert_records_batch_tsv,
    insert_stream_segments,
)

# PO:
from core.db_bulk import (
    insert_catchments,
    insert_stream_segments,
)
```

**Step 2: Usun flow_network z __all__**

W linii 100-103, usun `create_flow_network_records` i `create_flow_network_tsv` z listy `__all__`.

**Step 3: Usun krok 7 (TSV creation) — linie ~407-418**

Usun blok tworzenia TSV:
```python
# USUN caly blok:
# 7. Create flow_network TSV (vectorized numpy — ~5s vs ~120s)
tsv_buffer, n_records, n_stream = create_flow_network_tsv(...)
stats["records"] = n_records
stats["stream_cells"] = n_stream
```

Zastap obliczeniem `stream_cells` bezposrednio z `stream_mask` (ktory juz istnieje w linii 397):
```python
# 7. Stream cell count (from stream mask)
stats["stream_cells"] = int(np.count_nonzero(stream_mask))
```

**Step 4: Zaktualizuj sekcje "Insert into database" — linie ~510-531**

Usun `TRUNCATE TABLE flow_network CASCADE` (linia 517) i caly blok `insert_records_batch_tsv` (linie 525-531):

```python
# PRZED:
if clear_existing:
    logger.info("Clearing existing flow_network data...")
    db.execute(text("TRUNCATE TABLE flow_network CASCADE"))
    db.execute(
        text("DELETE FROM stream_network WHERE source = 'DEM_DERIVED'")
    )
    db.execute(text("DELETE FROM stream_catchments"))
    db.commit()

# TSV fast path — COPY directly from buffer
inserted = insert_records_batch_tsv(
    db,
    tsv_buffer,
    n_records,
    table_empty=clear_existing,
)
stats["inserted"] = inserted

# PO:
if clear_existing:
    logger.info("Clearing existing data...")
    db.execute(
        text("DELETE FROM stream_network WHERE source = 'DEM_DERIVED'")
    )
    db.execute(text("DELETE FROM stream_catchments"))
    db.commit()
```

**Step 5: Zaktualizuj stats reporting — linie ~729-736**

Usun linie raportujace `records` i `inserted`:
```python
# USUN:
logger.info(f"  Records created: {stats['records']:,}")
logger.info(f"  Records inserted: {stats['inserted']:,}")

# USUN z dry_run (linia 570):
stats["inserted"] = 0
```

**Step 6: Zaktualizuj docstringi**

- Linia 2: `"Script to process DEM..."` — usun "and populate flow_network table"
- Linia 146: `"Process DEM file..."` — usun "and load into flow_network table"
- Linia 578: `description=` w argparse — usun "and populate flow_network table"
- Linia 156-157: usun wzmianka o `flow_network.is_stream`

**Step 7: Usun parametr `batch_size` jesli nieuzywany**

Sprawdz czy `batch_size` w sygnaturze `process_dem()` jest jeszcze uzywany. Jesli jedynym zastosowaniem byl `insert_records_batch()`, usun parametr z sygnatury i z argparse (linia ~614-619).

**Step 8: Uruchom testy**

Run: `cd backend && .venv/bin/python -m pytest tests/ -x -q`
Expected: Niektore testy moga failowac (te ktore testuja flow_network functions) — to ok, naprawimy w Task 5.

**Step 9: Uruchom ruff**

Run: `cd backend && .venv/bin/python -m ruff check scripts/process_dem.py --fix`
Expected: Clean (usunie nieuzywane importy jesli jakies zostaly)

**Step 10: Commit**

```bash
git add backend/scripts/process_dem.py
git commit -m "refactor(core): usun flow_network z pipeline process_dem"
```

---

## Task 3: Usun flow_network functions z db_bulk.py

**Files:**
- Modify: `backend/core/db_bulk.py`

**Step 1: Usun 4 funkcje flow_network**

Usun nastepujace funkcje (kolejnosc od konca pliku, zeby numery linii sie nie przesunely):
1. `insert_records_batch_tsv()` (linie ~475-632)
2. `insert_records_batch()` (linie ~294-472)
3. `create_flow_network_records()` (linie ~192-291)
4. `create_flow_network_tsv()` (linie ~56-189)

**Step 2: Wyczysc importy**

Usun importy uzywane TYLKO przez usuniete funkcje:
- `import io` — sprawdz czy insert_stream_segments/insert_catchments tez uzywaja. Jesli nie, usun.
- `import numpy as np` — sprawdz czy insert_stream_segments/insert_catchments tez uzywaja. Jesli nie, usun.
- `from core.hydrology import D8_DIRECTIONS` — uzywane TYLKO przez create_flow_network_tsv. Usun.

**Step 3: Uruchom ruff**

Run: `cd backend && .venv/bin/python -m ruff check core/db_bulk.py --fix`
Expected: Clean

**Step 4: Commit**

```bash
git add backend/core/db_bulk.py
git commit -m "refactor(core): usun flow_network functions z db_bulk.py (~580 linii)"
```

---

## Task 4: Usun flow_graph.py i legacy watershed.py

**Files:**
- Delete: `backend/core/flow_graph.py`
- Modify: `backend/core/watershed.py`

**Step 1: Usun plik flow_graph.py**

```bash
git rm backend/core/flow_graph.py
```

**Step 2: Usun legacy functions z watershed.py**

Usun nastepujace funkcje (od konca pliku):
1. `_traverse_upstream_sql()` (linie ~391-447)
2. `_traverse_upstream_inmemory()` (linie ~357-388)
3. `traverse_upstream()` (linie ~345-354)
4. `check_watershed_size()` (linie ~321-342)
5. `find_nearest_stream()` (linie ~275-318)

**Step 3: Usun import flow_graph z watershed.py**

```python
# USUN linie 25:
from core.flow_graph import get_flow_graph
```

**Step 4: Sprawdz czy FlowCell jest uzywany gdzie indziej**

`FlowCell` jest uzywany przez `build_boundary_polygonize()` i `calculate_watershed_area_km2()` — te funkcje ZOSTAJA, wiec FlowCell tez zostaje.

**Step 5: Zaktualizuj komentarze w endpointach**

W `api/endpoints/hydrograph.py` i `api/endpoints/watershed.py` — zaktualizuj komentarze docstring ktore wsominaja "FlowGraph (19.7M cells)" na aktualne informacje o CatchmentGraph.

**Step 6: Uruchom ruff**

Run: `cd backend && .venv/bin/python -m ruff check core/watershed.py core/flow_graph.py api/endpoints/ --fix`
Expected: Clean (flow_graph.py juz nie istnieje, ruff powinien to zignorowac)

**Step 7: Commit**

```bash
git rm backend/core/flow_graph.py
git add backend/core/watershed.py backend/api/endpoints/hydrograph.py backend/api/endpoints/watershed.py
git commit -m "refactor(core): usun flow_graph.py i legacy CLI z watershed.py"
```

---

## Task 5: Aktualizacja testow

**Files:**
- Delete: `backend/tests/unit/test_flow_graph.py`
- Modify: `backend/tests/unit/test_db_bulk.py`
- Modify: `backend/tests/unit/test_watershed.py`
- Modify: `backend/tests/conftest.py`

**Step 1: Usun test_flow_graph.py**

```bash
git rm backend/tests/unit/test_flow_graph.py
```

**Step 2: Usun testy flow_network z test_db_bulk.py**

Usun klasy testowe:
- `TestCreateFlowNetworkRecords` (linie ~14-118)
- `TestCreateFlowNetworkTsv` (linie ~121-216)

Zostaw:
- `TestInsertStreamSegments` (linie ~219+) — ta klasa testuje insert_stream_segments ktora zostaje

Usun nieuzywane importy (`create_flow_network_records`, `create_flow_network_tsv`, itp).

**Step 3: Usun testy legacy functions z test_watershed.py**

Usun klasy testowe:
- `TestFindNearestStream` (linie ~23-80)
- `TestCheckWatershedSize` (linie ~82-133)
- `TestTraverseUpstream` (linie ~135-186)

Zostaw:
- `TestBuildBoundaryPolygonize`, `TestBuildBoundary`, `TestCalculateWatershedArea`, `TestFlowCellDataclass`

**Step 4: Usun fixtures z conftest.py**

Usun fixtures ktore mockuja flow_network queries:
- `mock_stream_query_result()` (linie ~89-102)
- `mock_upstream_query_results()` (linie ~105-121)
- `large_upstream_results()` (linie ~124-140)

Sprawdz czy `FlowCell` import jest nadal potrzebny (uzywa go `sample_cells` fixture — ZOSTAJE).

**Step 5: Uruchom pelny suite testow**

Run: `cd backend && .venv/bin/python -m pytest tests/ -v --tb=short`
Expected: Wszystkie testy PASS. Liczba testow spadnie o ~30-40 (usuniety flow_graph + flow_network tests).

**Step 6: Uruchom ruff na testach**

Run: `cd backend && .venv/bin/python -m ruff check tests/ --fix`
Expected: Clean

**Step 7: Commit**

```bash
git rm backend/tests/unit/test_flow_graph.py
git add backend/tests/unit/test_db_bulk.py backend/tests/unit/test_watershed.py backend/tests/conftest.py
git commit -m "test: usun testy flow_network i flow_graph (~40 testow)"
```

---

## Task 6: Dokumentacja — ADR-028 + CHANGELOG

**Files:**
- Modify: `docs/DECISIONS.md`
- Modify: `docs/CHANGELOG.md`
- Modify: `docs/PROGRESS.md`
- Modify: `docs/DATA_MODEL.md` (jesli opisuje flow_network)

**Step 1: Dodaj ADR-028 do DECISIONS.md**

```markdown
### ADR-028: Eliminacja tabeli flow_network (2026-02-17)

**Status:** Zatwierdzony
**Kontekst:** Tabela `flow_network` przechowywala dane kazdego piksela DEM (~39.4M wierszy dla 8 arkuszy). Ladowanie trwalo ~17 min (58% pipeline). Zadne API endpoint nie czyta z niej w runtime — wszystkie endpointy korzystaja z `stream_network`, `stream_catchments` i CatchmentGraph.
**Decyzja:** Eliminacja tabeli flow_network z pipeline i bazy. Migracja 015 (DROP TABLE). Usuniecie ~800 linii martwego kodu (db_bulk flow_network functions, flow_graph.py, watershed.py legacy CLI).
**Konsekwencje:**
- Pipeline 8 arkuszy: ~29 min → ~12 min (-58%)
- Pipeline 25 arkuszy (powiat): ~3h → ~50 min (-60%)
- Rozmiar DB: -2 GB (-80%)
- Legacy CLI (watershed.py traverse_upstream_sql) przestaje dzialac — celowe, API jest jedynym interfejsem
- Nadpisa: ADR-006 (COPY vs INSERT) — COPY juz nie jest potrzebne dla flow_network
```

**Step 2: Zaktualizuj CHANGELOG.md**

Dodaj wpis w sekcji Unreleased:
```markdown
### Removed
- Tabela `flow_network` — eliminacja 39.4M rekordow z bazy (ADR-028)
- `core/flow_graph.py` — DEPRECATED modul (~360 linii)
- Legacy CLI w `watershed.py` — 5 funkcji uzywajacych flow_network
- 4 funkcje flow_network w `db_bulk.py` (~580 linii)
- ~40 testow powiazanych z flow_network/flow_graph

### Changed
- Pipeline DEM pomija krok INSERT flow_network — oszczednosc ~17 min (58%)
- Migracja 015: DROP TABLE flow_network
```

**Step 3: Zaktualizuj PROGRESS.md**

Zaktualizuj sekcje "Ostatnia sesja" z informacja o eliminacji flow_network.

**Step 4: Zaktualizuj DATA_MODEL.md**

Sprawdz czy `docs/DATA_MODEL.md` opisuje tabele flow_network. Jesli tak, usun lub oznacz jako usunieta.

**Step 5: Commit**

```bash
git add docs/DECISIONS.md docs/CHANGELOG.md docs/PROGRESS.md docs/DATA_MODEL.md
git commit -m "docs: ADR-028 eliminacja flow_network + CHANGELOG + PROGRESS"
```

---

## Task 7: Weryfikacja koncowa

**Step 1: Uruchom pelny suite testow**

Run: `cd backend && .venv/bin/python -m pytest tests/ -v --tb=short`
Expected: ALL PASS

**Step 2: Uruchom ruff (lint + format)**

Run: `cd backend && .venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .`
Expected: Clean

**Step 3: Sprawdz czy flow_network nie jest wspomniana nigdzie w kodzie**

Run: `grep -r "flow_network" backend/ --include="*.py" | grep -v "migrations/" | grep -v "__pycache__"`
Expected: Zero trafien (lub tylko komentarze historyczne w migracji)

**Step 4: Sprawdz DB**

Run: `docker compose exec db psql -U hydro_user -d hydro_db -c "\dt"`
Expected: Tabela flow_network NIE istnieje. Tabele stream_network, stream_catchments, depressions, land_cover istnieja.

**Step 5: Sprawdz rozmiar DB**

Run: `docker compose exec db psql -U hydro_user -d hydro_db -c "SELECT pg_size_pretty(pg_database_size('hydro_db'))"`
Expected: Znacznie mniejszy rozmiar (ok. 0.5 GB zamiast 2.5 GB)
