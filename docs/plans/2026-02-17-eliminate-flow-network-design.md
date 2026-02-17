# Design: Eliminacja tabeli flow_network

**Data:** 2026-02-17
**Status:** Zatwierdzony
**Autor:** Claude Code + user

## Problem

Tabela `flow_network` przechowuje dane kazdego piksela DEM (~39.4M rekordow dla 8 arkuszy NMT). Ladowanie jej do bazy zajmuje ~17 min (58% calego pipeline'u). Przy skalowaniu do powiatu (~25 arkuszy) czas pipeline'u przekroczy 3 godziny.

Kluczowe odkrycie: **zadne API endpoint nie czyta z `flow_network` w runtime**. Wszystkie endpointy korzystaja z `stream_network` (~221k rekordow) i `stream_catchments` (~22.6k) oraz CatchmentGraph w pamieci. Wektoryzacja ciekow i polygonizacja zlewni pracuja bezposrednio na rasterach — nie na flow_network.

Jedyni konsumenci to legacy CLI w `watershed.py` (oznaczone "legacy, CLI only") i `flow_graph.py` (DEPRECATED).

## Rozwiazanie

Eliminacja tabeli `flow_network` z pipeline'u i bazy danych.

### Obecny pipeline
```
DEM rastery -> hydrologia -> TSV 39.4M -> COPY do flow_network (17 min)
                          \-> wektoryzacja -> stream_network (z rasterow)
                          \-> polygonizacja -> stream_catchments (z rasterow)
```

### Nowy pipeline
```
DEM rastery -> hydrologia -> wektoryzacja -> stream_network (z rasterow)
                          \-> polygonizacja -> stream_catchments (z rasterow)
```

## Zmiany

### 1. Migracja Alembic
- `DROP TABLE flow_network CASCADE`
- Zwalnia ~2 GB danych + 5 indeksow

### 2. Pipeline (`scripts/process_dem.py`)
- Usuniecie: `create_flow_network_tsv()` + `insert_records_batch_tsv()`
- Pipeline przeskakuje z obliczen rastrowych prosto do wektoryzacji

### 3. Bootstrap (`scripts/bootstrap.py`)
- `--clear-existing`: zamiast `TRUNCATE TABLE flow_network CASCADE` -> `DELETE FROM stream_network` + `DELETE FROM stream_catchments`

### 4. Dead code removal

**Plik do usuniecia:**
- `core/flow_graph.py` (DEPRECATED)

**Funkcje do usuniecia z `core/db_bulk.py`:**
- `create_flow_network_tsv()`
- `create_flow_network_records()`
- `insert_records_batch()`
- `insert_records_batch_tsv()`

**Funkcje do usuniecia z `core/watershed.py`:**
- `find_nearest_stream_cell()` (legacy CLI)
- `check_watershed_size()` (legacy CLI)
- `traverse_upstream_sql()` (legacy CLI)

**Zostaja bez zmian:**
- `core/db_bulk.py`: `insert_stream_segments()`, `insert_catchments()`, `override_statement_timeout()`
- `core/watershed_service.py` (caly plik)
- `core/catchment_graph.py` (caly plik)
- Wszystkie endpointy API
- Frontend

### 5. Testy
- Usuniecie testow `create_flow_network_tsv`, `insert_records_batch_tsv`
- Testy API bez zmian

### 6. Dokumentacja
- ADR-028 w `docs/DECISIONS.md`
- `docs/CHANGELOG.md`

## Oczekiwane rezultaty

| Metryka | Przed | Po | Zmiana |
|---------|-------|----|--------|
| Pipeline 8 arkuszy | ~29 min | ~12 min | -58% |
| Pipeline 25 arkuszy (powiat) | ~1.5-3h | ~35-50 min | -60% |
| Rozmiar DB | ~2.5 GB | ~0.5 GB | -80% |
| Kod w db_bulk.py | ~870 linii | ~400 linii | -54% |

## Ryzyka

| Ryzyko | Prawdopodobienstwo | Mitygacja |
|--------|-------------------|-----------|
| Legacy CLI przestaje dzialac | 100% (celowe) | Usuwamy, API jedyny interfejs |
| Utrata debugowania pikselowego | Niskie | Rastery na dysku, QGIS |
| Przyszla potrzeba flow_network | Niskie | Odtworzenie z rasterow w <5 min |

## Kolejnosc implementacji

1. Migracja Alembic (DROP TABLE flow_network)
2. process_dem.py (usuniecie krokow TSV + INSERT)
3. bootstrap.py (aktualizacja --clear-existing)
4. db_bulk.py (usuniecie funkcji flow_network)
5. watershed.py (usuniecie legacy CLI)
6. flow_graph.py (usuniecie pliku)
7. Testy (usuniecie/aktualizacja)
8. Dokumentacja (ADR-028 + CHANGELOG)
