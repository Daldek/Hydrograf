# Technical Debt - Hydrograf

Lista znanych problemów technicznych do naprawy w przyszłych iteracjach.

---

## Hardcoded Values (Q3.9)

### Stałe jednostek konwersji

| Wartość | Lokalizacja | Rekomendacja |
|---------|-------------|--------------|
| `1000.0` (m/km) | `core/morphometry.py` ×3 | Stała `M_PER_KM = 1000.0` |
| `1_000_000` (m²/km²) | `core/watershed.py`, `core/morphometry.py` | Stała `M2_PER_KM2 = 1_000_000` |

### Parametry algorytmów

| Wartość | Lokalizacja | Opis | Rekomendacja |
|---------|-------------|------|--------------|
| `0.3` | `core/watershed.py:300` | Concave hull ratio | Stała `CONCAVE_HULL_RATIO` |
| `4` | `core/precipitation.py:163` | IDW neighbors count | Stała `IDW_NUM_NEIGHBORS` |
| `75` | `core/morphometry.py` | Default CN value | Implementacja `land_cover.py` |

### Identyfikatory CRS

| Wartość | Lokalizacja | Rekomendacja |
|---------|-------------|--------------|
| `"EPSG:2180"` | `utils/geometry.py`, `models/schemas.py` | Stała `CRS_PL1992` |
| `"EPSG:4326"` | `utils/geometry.py` | Stała `CRS_WGS84` |

### Inne

| Wartość | Lokalizacja | Rekomendacja |
|---------|-------------|--------------|
| `"Hydrograf"` | `core/morphometry.py:304` | Config setting `app.name` |

**Akcja:** ~~Utworzyć `backend/core/constants.py` z wszystkimi stałymi.~~ ZREALIZOWANE (v0.4.0, `core/constants.py` — CRS, konwersje jednostek, domyslne CN, limity zlewni i grafu).

---

## Hardcoded Secrets (S5.3)

### S5.3a - Default password w config.py

```python
# backend/core/config.py:36
postgres_password: str = "hydro_password"
```

**Problem:** Domyślne hasło w kodzie źródłowym.

**Rekomendacja:**
- Usunąć domyślną wartość
- Wymagać zmiennej środowiskowej `POSTGRES_PASSWORD`
- Dodać walidację w `Settings`

### S5.3b - Connection string w migrations/env.py

```python
# backend/migrations/env.py:27
config.set_main_option(
    "sqlalchemy.url",
    "postgresql://hydro_user:hydro_password@localhost:5432/hydro_db"
)
```

**Problem:** Hardcoded connection string jako fallback.

**Rekomendacja:**
- Wymagać zmiennej `DATABASE_URL`
- Rzucać błąd jeśli brak konfiguracji

---

## Brakujące testy dla scripts/ (T4.8)

**Problem:** Większość skryptów preprocessingu (`scripts/*.py`) ma niskie pokrycie testami.

**Stan testów:**
- `scripts/process_dem.py` — **46 testów** (compute_slope, compute_aspect, compute_twi, compute_strahler, burn_streams, fill_sinks, pyflwdir)
- `scripts/import_landcover.py` — 0% pokrycia
- `utils/raster_utils.py` — 0% pokrycia
- `utils/sheet_finder.py` — 0% pokrycia

**Priorytet:** MEDIUM (process_dem pokryty, pozostałe do zrobienia)

> **Uwaga:** Pipeline CI/CD via GitHub Actions zostal wdrozony (v0.4.0). Obejmuje:
> lint (ruff check + format --check), testy (pytest), type-check (mypy).
> Kazdy push i PR na `develop`/`main` uruchamia pelna walidacje.

---

## Dokumentacja vs Kod (C2.x)

**Problem:** Dokumentacja API jest nieaktualna względem kodu.

**Rozbieżności:**
| Element | Dokumentacja | Kod |
|---------|--------------|-----|
| `outlet_coords` | `[lon, lat]` array | `outlet.latitude/longitude` objects |
| `parameters` | sekcja `parameters` | `morphometry` |
| `water_balance` | BRAK | nowa sekcja w response |

**Akcja:** Zaktualizować `docs/ARCHITECTURE.md` sekcja API endpoints.

---

## Wydajnosc bazy danych — bulk INSERT + indeksy (P1.x)

**Problem:** Bulk INSERT `flow_network` (39.4M rekordow) + odbudowa indeksow to najciezszy krok pipeline'u — ~17 min z 29 min calkowitego czasu (58%). Pomiary z pipeline run 2026-02-16 (stream burning z BDOT10k):

| Operacja | Czas | Rekordy |
|----------|------|---------|
| COPY do temp table | ~80s | 39,377,780 |
| INSERT z temp do flow_network | ~12 min | 39,377,780 |
| Odbudowa 5 indeksow + FK + ANALYZE | ~6 min | — |
| **Lacznie bulk INSERT** | **~17 min** | **58% calkowitego czasu** |

Porownanie z innymi krokami:
| Krok | Czas | % |
|------|------|---|
| Bulk INSERT flow_network + indeksy | ~17 min | 58% |
| Hydrologia pyflwdir (fill+fdir+acc) | ~4.6 min | 16% |
| Wektoryzacja + polygonizacja (4 progi) | ~2 min | 7% |
| Hydro download BDOT10k (siec) | ~2 min | 7% |
| Raster I/O + slope/aspect/TWI | ~3.8 min | 12% |

### P1.1 — Optymalizacja bulk INSERT flow_network

**Obecne podejscie:** TSV buffer w pamieci → COPY do temp table → INSERT INTO flow_network SELECT FROM temp → DROP temp → CREATE INDEX ×5 → ALTER TABLE ADD FK → ANALYZE.

**Mozliwe optymalizacje:**
- `UNLOGGED TABLE` podczas importu (ryzyko utraty danych przy crash)
- Zwiekszenie `maintenance_work_mem` (domyslnie 64 MB) na czas CREATE INDEX
- Zwiekszenie `max_wal_size` + `checkpoint_completion_target` zmniejszy checkpointy
- Rownolegle budowanie indeksow (`max_parallel_maintenance_workers`)
- `COPY` bezposrednio do docelowej tabeli (bez temp, ale wymaga wylaczonych FK/indeksow)
- Rozważenie `pg_bulkload` lub `timescaledb-parallel-copy`

### P1.2 — Redukcja rozmiaru flow_network

**Obecny stan:** 39.4M rekordow (42M komorek - ~2.6M nodata). Kazdy rekord zawiera: x, y, elevation, flow_direction, flow_accumulation, is_stream, strahler_order, geom (POINT).

**Mozliwe optymalizacje:**
- Usunięcie kolumny `geom` (POINT) — x, y wystarczą do odtworzenia geometrii w locie (ST_SetSRID(ST_MakePoint(x, y), 2180)). Oszczędność ~30% rozmiaru tabeli + eliminacja indeksu gist
- Przechowywanie tylko komorek streamowych (`is_stream=TRUE`, ~3.2M z 39.4M = 8%) — reszta odtwarzalna z rastra
- Partycjonowanie po `is_stream` lub `strahler_order`

### P1.3 — Alternatywa: rezygnacja z flow_network

**Kontekst:** Po wdrozeniu CatchmentGraph (ADR-021) i eliminacji FlowGraph (ADR-022) tabela `flow_network` nie jest juz uzywana w runtime API. Jedyne jej zastosowanie to preprocessing (budowa stream_network i stream_catchments).

**Pytanie architektoniczne:** Czy `flow_network` jest nadal potrzebna, skoro:
- Runtime API uzywa tylko `stream_network` + `stream_catchments` + `CatchmentGraph`
- Raster DEM jest dostepny na dysku (profil terenu, morphometria)
- 39.4M rekordow → ~2 GB w PostgreSQL (indeksy + WAL)

**Mozliwe podejscie:** generowanie `stream_network` i `stream_catchments` bezposrednio z rastra (bez posrednictwa flow_network) i pominięcie INSERT 39.4M rekordów. Wymaga refaktoru `process_dem.py`.

**Priorytet:** HIGH — eliminacja tego kroku skrocilaby pipeline o ~17 min (58%).

---

## Checklist po migracjach DB (zapobieganie regresji)

**Problem:** Migracja 014 dodala `segment_idx` do `stream_network`, ale nie zaktualizowano `find_nearest_stream_segment()` w `watershed_service.py` — funkcja nadal pobierala `id` (auto-increment PK) i zwracala go jako `segment_idx`. Bug trwal przez 6 sesji (24-32).

**Checklist po kazdej migracji:**
1. `grep -r "TABLE_NAME" backend/` — znajdz WSZYSTKIE zapytania SQL do zmienionej tabeli
2. Sprawdz czy nowa/zmieniona kolumna jest uzywana poprawnie w kazdym zapytaniu
3. Sprawdz czy mapowanie wynikow (result.X → dict["Y"]) jest spojne z SQL SELECT
4. Uruchom istniejace testy integracyjne — jesli testy nie pokrywaja nowej kolumny, dodaj
5. `verify_graph()` przy starcie API — walidacja spojnosci danych miedzy tabelami

**Priorytet:** HIGH — cichy bug tral 6 sesji bez wykrycia

---

*Ostatnia aktualizacja: 2026-02-17*
