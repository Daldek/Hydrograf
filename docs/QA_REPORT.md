# QA Report — Hydrograf

**Data:** 2026-02-16
**Wersja repozytorium:** develop (commit caeaa4a)
**Autor:** Claude Code QA

---

## Executive Summary

| Metryka | Wartosc |
|---------|---------|
| **Ogolna ocena** | **8.5/10** |
| Issues CRITICAL | 0 |
| Issues HIGH | 2 |
| Issues MEDIUM | 5 |
| Issues LOW | 6 |
| **Testy** | 544 passing (25 plikow testowych) |
| **Lint (ruff)** | 0 bledow |
| **Format (ruff)** | 1 plik do sformatowania |
| **ADR** | 28 decyzji architektonicznych |
| **Migracje** | 16 |

### Glowne problemy do rozwiazania:
1. **HIGH:** Hardcoded default password w `config.py` i `migrations/env.py`
2. **HIGH:** Znany bug — zielone zlewnie po selekcji cieku (diagnostyka w toku)

### Postep od ostatniego raportu (2026-01-21):
- CORS: ❌ → ✅ (env var, `allow_credentials=False`)
- Rate limiting: ❌ → ✅ (3 strefy Nginx)
- CI/CD: ❌ → ✅ (GitHub Actions: lint + test + security)
- CHANGELOG: ❌ → ✅
- pre-commit: ❌ → ✅ (ruff check + format)
- pyproject.toml: ❌ → ✅
- constants.py: ❌ → ✅
- Testy: 175 → 544 (+220%)
- Architektura: FlowGraph (1.1 GB RAM) → CatchmentGraph (5 MB RAM)

---

## 1. Analiza Automatyczna

### 1.1 Testy (pytest)

```
544 passed in 11.80s
```

| Plik testowy | Liczba testow | Typ |
|-------------|---------------|-----|
| test_precipitation.py | 61 | unit |
| test_process_dem.py | 47 | unit |
| test_morphometry.py | 44 | unit |
| test_cn_tables.py | 41 | unit |
| test_watershed.py (unit) | 35 | unit |
| test_land_cover.py | 30 | unit |
| test_watershed_service.py | 29 | unit |
| test_catchment_graph.py | 22 | unit |
| test_hydrograph.py | 22 | integration |
| test_tiles.py | 21 | integration |
| test_lake_drain.py | 20 | unit |
| test_cn_calculator.py | 20 | unit |
| test_geometry.py | 19 | unit |
| test_flow_graph.py | 18 | unit |
| test_profile.py | 17 | integration |
| test_depressions.py | 17 | integration |
| test_zonal_stats.py | 16 | unit |
| test_watershed.py (integ.) | 16 | integration |
| test_db_bulk.py | 15 | unit |
| test_preprocess_precipitation.py | 12 | unit |
| test_select_stream.py | 12 | integration |
| test_hydrology.py | 9 | unit |
| test_stream_extraction.py | 8 | unit |
| test_health.py | 5 | integration |
| test_raster_io.py | 4 | unit |
| **Razem** | **544** | **18 unit + 7 integ.** |

### 1.2 Linting (ruff)

```
All checks passed!
```

Brak bledow. Projekt uzywa ruff (zamiast flake8/black) skonfigurowanego w `pyproject.toml`.

### 1.3 Formatowanie (ruff format)

```
1 file would be reformatted (models/schemas.py), 95 files already formatted
```

**Uwaga:** `models/schemas.py` ma niezacommitowane zmiany (sesja 27) — formatowanie zostanie naprawione po commicie.

### 1.4 Pokrycie testami wg modulow

| Modul | Testy | Status |
|-------|-------|--------|
| core/watershed.py | 35 unit + 16 integ. | ✅ |
| core/morphometry.py | 44 unit | ✅ |
| core/precipitation.py | 61 unit | ✅ |
| core/catchment_graph.py | 22 unit | ✅ |
| core/watershed_service.py | 29 unit | ✅ |
| core/land_cover.py | 30 unit | ✅ |
| core/cn_tables.py | 41 unit | ✅ |
| core/cn_calculator.py | 20 unit | ✅ |
| core/db_bulk.py | 15 unit | ✅ |
| core/hydrology.py | 9 unit | ✅ |
| core/stream_extraction.py | 8 unit | ✅ |
| core/zonal_stats.py | 16 unit | ✅ |
| core/raster_io.py | 4 unit | ⚠️ Niskie |
| core/flow_graph.py | 18 unit | ❌ USUNIETY (ADR-028, sesja 33) |
| core/morphometry_raster.py | — | ❌ Brak dedykowanych |
| core/database.py | — | ❌ Brak dedykowanych |
| api/endpoints/ (wszystkie) | 110 integ. | ✅ |
| models/schemas.py | — | ✅ (testowane posrednio) |
| utils/geometry.py | 19 unit | ✅ |
| utils/raster_utils.py | — | ❌ Brak |
| utils/sheet_finder.py | — | ❌ Brak |
| scripts/process_dem.py | 47 unit | ✅ |
| scripts/ (pozostale) | 12 unit | ⚠️ Niskie |

---

## 2. Architektura i Moduly

### 2.1 Struktura kodu (LOC)

| Warstwa | Pliki | LOC | Uwagi |
|---------|-------|-----|-------|
| core/ | 17 modulow | ~7140 | Logika biznesowa |
| api/endpoints/ | 10 endpointow (7 plikow, 10 endpointow logicznie) | ~1560 | Warstwa API |
| models/ | 1 | ~200 | Schematy Pydantic |
| utils/ | 4 | ~400 | Narzedzia |
| scripts/ | 12 | ~4500 | Preprocessing CLI |
| **Razem backend** | **~41** | **~13800** | |

### 2.2 Moduly core/

| Modul | LOC | Opis | Status |
|-------|-----|------|--------|
| hydrology.py | 877 | Fill, fdir, acc, stream burning | ✅ Aktywny |
| db_bulk.py | 867 | Bulk INSERT via COPY | ✅ Aktywny |
| morphometry.py | 652 | Parametry fizjograficzne | ✅ Aktywny |
| stream_extraction.py | 603 | Wektoryzacja ciekow, zlewnie | ✅ Aktywny |
| watershed_service.py | 567 | Wspolna logika delineacji (ADR-022) | ✅ Aktywny |
| catchment_graph.py | 551 | Graf in-memory, BFS, agregacja | ✅ Aktywny |
| watershed.py | 447 | build_boundary + legacy CLI | ✅ Aktywny |
| morphometry_raster.py | 386 | Nachylenie, aspekt, TWI, Strahler | ✅ Aktywny |
| flow_graph.py | 361 | Graf przeplywu | ❌ USUNIETY (ADR-028, sesja 33) |
| land_cover.py | 346 | Pokrycie terenu, CN | ✅ Aktywny |
| cn_calculator.py | 334 | HSG-based CN | ✅ Aktywny |
| precipitation.py | 320 | IDW interpolation | ✅ Aktywny |
| raster_io.py | 235 | Odczyt/zapis rastrow | ✅ Aktywny |
| zonal_stats.py | 185 | Statystyki strefowe (bincount) | ✅ Aktywny |
| constants.py | 27 | Stale projektowe | ✅ Aktywny |
| config.py | ~40 | Pydantic Settings | ✅ Aktywny |
| database.py | ~30 | Connection pool | ✅ Aktywny |

### 2.3 Endpointy API

| Endpoint | Plik | LOC | Testy | Status |
|----------|------|-----|-------|--------|
| GET /health | health.py | 48 | 5 | ✅ |
| POST /api/delineate-watershed | watershed.py | 275 | 16 | ✅ |
| POST /api/generate-hydrograph | hydrograph.py | 359 | 22 | ✅ |
| GET /api/scenarios | hydrograph.py | (w/w) | (w/w) | ✅ |
| POST /api/terrain-profile | profile.py | 120 | 17 | ✅ |
| GET /api/depressions | depressions.py | 142 | 17 | ✅ |
| POST /api/select-stream | select_stream.py | 395 | 12 | ✅ |
| GET /api/tiles/{layer}/{z}/{x}/{y}.pbf | tiles.py | 224 | 21 | ✅ |
| GET /api/tiles/thresholds | tiles.py | (w/w) | (w/w) | ✅ |

### 2.4 Decyzje architektoniczne (ADR)

28 decyzji w `docs/DECISIONS.md`. Kluczowe:

| ADR | Tytul | Status |
|-----|-------|--------|
| ADR-001 | Graf w bazie zamiast rastrow runtime | ✅ Przyjeta |
| ADR-011 | Development: .venv + Docker db only | ✅ Przyjeta |
| ADR-016 | pyflwdir zamiast Python pixel loops | ✅ Przyjeta |
| ADR-017 | Modularna architektura core/ | ✅ Przyjeta |
| ADR-021 | CatchmentGraph in-memory | ✅ Przyjeta |
| ADR-022 | Eliminacja FlowGraph z runtime API | ✅ Przyjeta |
| ADR-023 | Hierarchiczny merge zlewni | ✅ Przyjeta |
| ADR-024 | Precyzyjna selekcja cieku (konfluencja) | ⛔ Superseded (przez ADR-026) |
| ADR-025 | Warunkowy prog selekcji | ⛔ Superseded (przez ADR-026) |
| ADR-026 | Selekcja oparta o poligon zlewni + segment_idx | ⛔ Superseded (przez ADR-027) |
| ADR-027 | Snap-to-stream w selekcji cieku | ✅ Przyjeta (zastepuje ADR-026) |
| ADR-028 | Eliminacja tabeli flow_network | ✅ Przyjeta |

### 2.5 Migracje bazy danych

16 migracji Alembic (`001`–`016`). Kluczowe tabele:
- ~~`flow_network`~~ (usunieta, migracja 015, ADR-028)
- `stream_network` (~117k segmentow, 4 progi, kolumna `segment_idx` z migracji 014)
- `stream_catchments` (117k zlewni, 6 dodatkowych kolumn z migracji 012)
- `land_cover` (38.5k rekordow, 12 warstw BDOT10k)
- `depressions` (602k zaglebie)
- `precipitation_data` (dane opadowe IMGW)

---

## 3. Bezpieczenstwo

### 3.1 SQL Injection

**Status: ✅ BEZPIECZNY** — Wszystkie zapytania uzywaja parametryzacji z `text()` i `:param`

### 3.2 Input Validation

**Status: ✅ BEZPIECZNY** — Pydantic waliduje wszystkie inputy API

### 3.3 CORS

**Status: ✅ NAPRAWIONY**

```python
# api/main.py
cors_origins = [origin.strip() for origin in settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,         # Z env var CORS_ORIGINS
    allow_credentials=False,            # Bezpieczne
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)
```

### 3.4 Rate Limiting

**Status: ✅ NAPRAWIONY**

```nginx
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;    # API
limit_req_zone $binary_remote_addr zone=tile_limit:10m rate=30r/s;   # Kafelki MVT
limit_req_zone $binary_remote_addr zone=general_limit:10m rate=30r/s; # Ogolny
```

### 3.5 Security Headers (Nginx)

**Status: ✅ WDROZONE**

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy` (script-src, style-src, img-src, connect-src)
- `Strict-Transport-Security` (HSTS)

### 3.6 Secrets

**Status: ⚠️ MEDIUM — do poprawy**

| Problem | Lokalizacja | Priorytet |
|---------|-------------|-----------|
| Domyslne haslo `hydro_password` | core/config.py | MEDIUM |
| Hardcoded connection string | migrations/env.py | MEDIUM |

**Uwaga:** Oba wartosci sa default fallback — produkcja powinna uzywac zmiennych srodowiskowych. Nie stanowia ryzyka w deploymencie z poprawnym `.env`, ale najlepiej usunac defaults.

---

## 4. DevOps

### 4.1 CI/CD

**Status: ✅ WDROZONE**

GitHub Actions (`.github/workflows/ci.yml`) z 3 jobs:
- **lint:** ruff check + ruff format check
- **test:** pytest z PostGIS service container
- **security:** pip-audit (continue-on-error)

### 4.2 Pre-commit

**Status: ✅ WDROZONE**

`.pre-commit-config.yaml`:
- trailing-whitespace, end-of-file-fixer, check-yaml, check-added-large-files
- ruff check (--fix) + ruff format

### 4.3 Dockerfile

**Status: ⚠️ Do poprawy (LOW)**

| Problem | Priorytet |
|---------|-----------|
| Brak multi-stage build | LOW |
| Brak .dockerignore | LOW |
| `COPY . .` kopiuje wszystko (w tym testy, docs) | LOW |

Dockerfile jest funkcjonalny — poprawki to optymalizacja rozmiaru obrazu.

### 4.4 Dokumentacja

**Status: ✅ Kompletna**

| Dokument | Status | Uwagi |
|----------|--------|-------|
| PROGRESS.md | ✅ Aktualny | 27 sesji udokumentowanych |
| SCOPE.md | ✅ Zatwierdzony | Data 2026-02-13 |
| PRD.md | ✅ | Wymagania produktowe |
| ARCHITECTURE.md | ✅ v1.5 | Zaktualizowana po ADR-022 |
| DATA_MODEL.md | ✅ | +migracja 013 |
| DECISIONS.md | ✅ | 28 ADR |
| CHANGELOG.md | ✅ | Historia zmian per-release |
| COMPUTATION_PIPELINE.md | ✅ v1.2 | Pipeline preprocessing |
| CLAUDE.md | ✅ | Instrukcje dla Claude Code |
| QA_REPORT.md | ✅ | Niniejszy raport |
| README.md | ✅ | CP4, 10 endpointow |

### 4.5 Structured Logging

**Status: ✅ WDROZONE**

- structlog JSON format + request_id middleware w `api/main.py`

---

## 5. Jakosc Kodu

### 5.1 Styl i konwencje

| Metryka | Wynik |
|---------|-------|
| Linter | ruff (0 bledow) |
| Formatter | ruff format (1 plik — niezacommitowane zmiany) |
| Type hints | Szerokie uzycie |
| Docstrings | NumPy style, publiczne funkcje |
| Konwencja nazw | `area_km2`, `elevation_m`, `discharge_m3s` |
| Stale | Scentralizowane w `core/constants.py` |

### 5.2 Znane technical debt

| ID | Opis | Priorytet | Status |
|----|------|-----------|--------|
| TD-1 | ~~`flow_graph.py` DEPRECATED~~ USUNIETY (ADR-028, sesja 33) | LOW | ✅ Zrealizowane |
| TD-2 | Hardcoded secrets w defaults | MEDIUM | Do poprawy |
| TD-3 | Brak .dockerignore | LOW | Do dodania |
| TD-4 | Niska pokrywalnosc scripts/ (poza process_dem) | MEDIUM | Backlog |
| TD-5 | `morphometry_raster.py` bez dedykowanych testow | MEDIUM | Testowany posrednio |

---

## 6. Znane Problemy

### 6.1 Zielone zlewnie po selekcji cieku (OTWARTY)

**Priorytet: HIGH**
**Status:** Diagnostyka w toku (sesja 27)

Po wybraniu cieku pojawiaja sie dodatkowe zielone zlewnie czastkowe niezwiazane z zaznaczeniem. Wdrozono narzedzia diagnostyczne:
- `display_threshold_m2` w API response
- Tooltip z `segment_idx` + status `IN SET / not in set`
- Console warning `THRESHOLD MISMATCH!`

Mozliwe przyczyny: VectorGrid cache, overlapping `segment_idx` miedzy progami, MVT encoding.

### 6.2 Wydajnosc select-stream (OTWARTY)

**Priorytet: MEDIUM**

Czas odpowiedzi 10-25s dla duzych zlewni. Bottlenecki: ST_UnaryUnion na wielu poligonach, snap-to-stream, BFS. Kaskadowe progi merge (ADR-024) pomagaja, ale nie eliminuja problemu.

### 6.3 Drobne bugi UX (OTWARTE)

- **E1:** Dziury na granicach zlewni (ST_Union artifacts)
- **E4:** Punkt ujsciowy poza granica zlewni (outlet offset)
- **H1:** Zlewnie bezposrednie jezior (koncepcyjne)

---

## 7. Priorytetyzowane Akcje

### HIGH (przed nastepnym release)

1. **[6.1] Diagnostyka zielonych zlewni** — uzyc tooltipa do ustalenia root cause
2. **[3.6] Usun hardcoded default password** z `config.py` i `migrations/env.py`

### MEDIUM (w najblizszym sprincie)

3. **[6.2] Optymalizacja select-stream** — pre-computed boundaries lub cache
4. **[5.2/TD-4] Testy scripts/** — pokrycie dla `generate_*.py`, `import_landcover.py`
5. **[5.2/TD-5] Testy morphometry_raster.py** — dedykowane unit testy
6. **[6.3/E1] Dziury na granicach zlewni** — ST_Union/SnapToGrid tuning
7. **[6.3/E4] Outlet poza granica** — fix logiki outlet w watershed_service

### LOW (backlog)

8. **[4.3] Dockerfile** — multi-stage build, .dockerignore
9. ~~**[5.2/TD-1] Deprecation flow_graph.py**~~ — ZREALIZOWANE (ADR-028, sesja 33)
10. **[4.4] pyproject.toml version** — 0.3.0 → 0.4.0 (post CP4)
11. Formatowanie `models/schemas.py` (po commicie zmian z sesji 27)
12. Aktualizacja outdated packages
13. Testy dla `utils/raster_utils.py` i `utils/sheet_finder.py`

---

## 8. Status MVP

| Faza | Opis | Status |
|------|------|--------|
| Faza 0 | Setup | ✅ Ukonczona |
| Faza 1 | Backend MVP | ✅ CP1, CP2 |
| Faza 2 | Model Hydrologiczny | ✅ CP3 |
| Faza 3 | Frontend | ✅ CP4 (4 fazy frontendu) |
| **Faza 4** | **Testy i Deploy** | ⏳ **W trakcie** |
| Faza 5 | MVP Release (CP5) | ⏳ Planowana |

**Gotowe do CP5:** 10 endpointow, 544 testow, CI/CD, structured logging, security headers, rate limiting, CatchmentGraph in-memory.

**Blokery CP5:** zielone zlewnie (bug), wydajnosc select-stream, hardcoded secrets.

---

## Podsumowanie

Projekt Hydrograf przeszedl znaczaca ewolucje od ostatniego raportu QA (2026-01-21). Wszystkie problemy CRITICAL zostaly naprawione (CORS, rate limiting, CI/CD). Liczba testow wzrosla z 175 do 544. Architektura zostala zrefaktoryzowana — eliminacja FlowGraph z runtime API zmniejszyla zuzycie RAM o 96%.

Glowne obszary wymagajace uwagi:
1. **Bug zielonych zlewni** — wymaga diagnostyki (narzedzia juz wdrozone)
2. **Wydajnosc** — select-stream zbyt wolny dla duzych zlewni
3. **Hardcoded secrets** — jedyny pozostaly problem bezpieczenstwa

Po rozwiazaniu tych problemow projekt bedzie gotowy do release MVP (CP5).

---

*Raport wygenerowany przez Claude Code QA — 2026-02-16*
