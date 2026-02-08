# QA Report - Hydrograf

**Data:** 2026-01-21
**Wersja repozytorium:** develop (commit f3b0b25)
**Autor:** Claude Code QA

> **Aktualizacja 2026-02-07:** Raport pochodzi z wersji v0.3.0. Od tego czasu naprawiono:
> CRITICAL CORS (`allow_origins` z listy), HIGH rate limiting (nginx 10/30 req/s),
> HIGH CHANGELOG (istnieje). Testy: 175 → 345. Pokrycie `process_dem.py`: 0% → 46 testów.
> Migracja na ruff (ADR-009), pyflwdir (ADR-012), nowe parametry morfometryczne (ADR-014).

---

## Executive Summary

| Metryka | Wartość |
|---------|---------|
| **Ogólna ocena** | **7/10** |
| Issues CRITICAL | 1 |
| Issues HIGH | 3 |
| Issues MEDIUM | 12 |
| Issues LOW | 15 |
| **Pokrycie testami** | 52% (core: 85-100%) |
| **Testy** | 175 passing |

### Główne problemy do natychmiastowej naprawy:
1. **CRITICAL:** Niebezpieczna konfiguracja CORS (`allow_origins=["*"]` + `allow_credentials=True`)
2. **HIGH:** Brak rate limiting w Nginx
3. **HIGH:** Brak CI/CD pipeline
4. **HIGH:** Brak CHANGELOG.md

---

## 1. Analiza Automatyczna

### 1.1 Pytest Coverage

```
Total: 52% (2933 statements, 1411 missed)
```

| Moduł | Pokrycie | Status |
|-------|----------|--------|
| api/endpoints/health.py | 100% | ✅ |
| api/endpoints/watershed.py | 85% | ✅ |
| api/endpoints/hydrograph.py | 92% | ✅ |
| core/watershed.py | 97% | ✅ |
| core/morphometry.py | 97% | ✅ |
| core/precipitation.py | 92% | ✅ |
| core/database.py | 71% | ⚠️ |
| models/schemas.py | 100% | ✅ |
| utils/geometry.py | 100% | ✅ |
| **scripts/*.py** | **0%** | ❌ |
| **utils/raster_utils.py** | **0%** | ❌ |
| **utils/sheet_finder.py** | **0%** | ❌ |

**Wnioski:** Core logic ma bardzo dobre pokrycie (85-100%), ale skrypty preprocessingu i utility nie mają testów.

### 1.2 Flake8 (kod projektu)

| Typ | Liczba | Przykłady |
|-----|--------|-----------|
| F401 (unused import) | 8 | `typing.Optional`, `numpy as np` |
| F821 (undefined name) | 4 | `geopandas` w type hints |
| E261 (spacing) | 2 | inline comments |
| E501 (line too long) | 1 | process_dem.py:765 |
| **Razem** | **15** | |

### 1.3 Black Formatting

**3 pliki wymagają formatowania:**
- `migrations/env.py`
- `migrations/versions/001_create_precipitation_data.py`
- `api/endpoints/watershed.py`

### 1.4 Outdated Packages

| Package | Current | Latest | Uwagi |
|---------|---------|--------|-------|
| black | 25.12.0 | 26.1.0 | ✅ Do aktualizacji |
| numpy | 2.3.5 | 2.4.1 | ⚠️ Blokuje numba <2.4 |

**Uwaga:** Kartograf (0.4.1) jest dostępny **tylko z GitHub** (https://github.com/Daldek/Kartograf), nie z PyPI.

---

## 2. Spójność Dokumentacji (D1.x)

### 2.1 Wersje Dokumentów

| Dokument | Wersja nagłówek | Wersja stopka | Data | Problem |
|----------|-----------------|---------------|------|---------|
| SCOPE.md | 1.0 | - | 2026-01-14 | Literówka "Nieatwierdzony" |
| ARCHITECTURE.md | **1.0** | **1.2** | 2026-01-14 / **2026-01-20** | **NIESPÓJNOŚĆ** |
| DATA_MODEL.md | 1.0 | 1.0 | 2026-01-14 | OK |
| PRD.md | 1.0 | 1.0 | 2026-01-14 | OK |

### 2.2 Checkpointy

| ID | Problem | Priorytet |
|----|---------|-----------|
| D1.2-1 | PRD.md nie definiuje checkpointów CP1-CP5 | LOW |
| D1.2-2 | CP3 status "przetestowane manualnie" niejasny | LOW |

### 2.3 Schematy Tabel vs Migracje

| ID | Problem | Lokalizacja | Priorytet |
|----|---------|-------------|-----------|
| D1.3-1 | `flow_network.slope` - różnica w dopuszczalności NULL | DATA_MODEL vs migration 002 | LOW |
| D1.3-2 | **Brak CHECK constraint** dla `land_cover.category` | migration 002 | **HIGH** |
| D1.3-3 | **Brak UNIQUE constraint** dla `stream_network(name, geom)` | migration 002 | MEDIUM |

### 2.4 API Endpoints

| Endpoint | Dokumentacja | Kod | Status |
|----------|--------------|-----|--------|
| GET /health | ✅ | ✅ | OK |
| POST /api/delineate-watershed | ✅ | ✅ (rozszerzony) | ROZSZERZENIE |
| POST /api/generate-hydrograph | ✅ | ✅ (rozszerzony) | ROZSZERZENIE |
| **GET /api/scenarios** | ✅ | **BRAK** | **NIEZAIMPLEMENTOWANY** |

---

## 3. Spójność Dokumentacji z Kodem (C2.x)

### 3.1 Brakujące moduły

| Moduł (wg dokumentacji) | Status w kodzie |
|------------------------|-----------------|
| `core/land_cover.py` | **BRAK** - CN hardcoded na 75 |
| `core/hydrograph.py` | **BRAK** - przeniesione do biblioteki Hydrolog |

### 3.2 Rozbieżności w strukturach API

| Element | Dokumentacja | Kod | Rekomendacja |
|---------|--------------|-----|--------------|
| `outlet_coords` | `[lon, lat]` array | `outlet.latitude/longitude` objects | Aktualizacja docs |
| `parameters` | sekcja `parameters` | `morphometry` | Aktualizacja docs |
| `land_cover.land_cover_percent` | wymagane | **BRAK** | Implementacja lub usunięcie |
| `water_balance` | **BRAK** | nowa sekcja | Aktualizacja docs |

### 3.3 Zależności zewnętrzne

| Biblioteka | Dokumentacja | Źródło | Uwagi |
|------------|--------------|--------|-------|
| kartograf | ✅ KARTOGRAF_INTEGRATION.md | GitHub only | @develop branch |
| hydrolog | ⚠️ Częściowa | GitHub only | @develop branch |
| pyflwdir | ✅ Udokumentowana | PyPI | Zastąpiła pysheds (ADR-012) |

---

## 4. Jakość Kodu (Q3.x)

### 4.1 Docstrings i Type Hints

| Metryka | Wynik |
|---------|-------|
| Funkcje publiczne z docstrings | **100%** ✅ |
| Funkcje z type hints | **99%** ✅ |
| Styl docstrings | NumPy ✅ |

### 4.2 Funkcje > 50 linii

| Funkcja | Linie | Rekomendacja |
|---------|-------|--------------|
| `traverse_upstream` | 105 | Wydzielić query builder |
| `find_main_stream` | 97 | Wydzielić graph builder |
| `get_precipitation` | 88 | Wydzielić IDW logic |

### 4.3 Hardcoded Values do Ekstrakcji

| Wartość | Lokalizacja | Rekomendacja |
|---------|-------------|--------------|
| `1000.0` (m/km) | morphometry.py × 3 | Stała `M_PER_KM` |
| `1_000_000` (m²/km²) | watershed.py, morphometry.py | Stała `M2_PER_KM2` |
| `0.3` (concave hull ratio) | watershed.py:300 | Stała `CONCAVE_HULL_RATIO` |
| `4` (IDW neighbors) | precipitation.py:163 | Stała `IDW_NUM_NEIGHBORS` |
| `"EPSG:2180"`, `"EPSG:4326"` | geometry.py | Stałe `CRS_PL1992`, `CRS_WGS84` |
| `"Hydrograf"` | morphometry.py:304 | Config setting |

**Rekomendacja:** Utworzyć `backend/core/constants.py`

### 4.4 Duplikacje

| Wzorzec | Lokalizacje | Rekomendacja |
|---------|-------------|--------------|
| Konstrukcja FlowCell z SQL row | watershed.py:134, :239 | Helper `_row_to_flowcell()` |
| Obliczanie odległości euklidesowej | morphometry.py:72, :231 | Helper `_euclidean_distance()` |

---

## 5. Testy (T4.x)

### 5.1 Mapowanie Testów

| Moduł | Unit Tests | Integration Tests |
|-------|------------|-------------------|
| watershed.py | ✅ 21 testów | ✅ 17 testów |
| morphometry.py | ✅ testy | - |
| precipitation.py | ✅ testy | - |
| geometry.py | ✅ 19 testów | - |
| health.py | - | ✅ testy |
| hydrograph.py | - | ✅ testy |
| **scripts/*.py** | ❌ **BRAK** | ❌ **BRAK** |

### 5.2 Brakujące Testy

| Priorytet | Moduł | Opis |
|-----------|-------|------|
| **HIGH** | scripts/process_dem.py | 0% coverage, krytyczny skrypt |
| **HIGH** | scripts/import_landcover.py | 0% coverage |
| MEDIUM | utils/raster_utils.py | 0% coverage |
| MEDIUM | utils/sheet_finder.py | 0% coverage |
| LOW | core/database.py | 71% coverage |

---

## 6. Bezpieczeństwo (S5.x)

### 6.1 SQL Injection

**Status: ✅ BEZPIECZNY** - Wszystkie zapytania używają parametryzacji z `text()` i `:param`

### 6.2 Input Validation

**Status: ✅ BEZPIECZNY** - Pydantic waliduje wszystkie inputy

| ID | Problem | Priorytet |
|----|---------|-----------|
| S5.2a | Brak walidacji enum dla `probability` w Pydantic | LOW |

### 6.3 CORS

**Status: ❌ CRITICAL**

```python
# api/main.py:41-47
allow_origins=["*"],        # NIEBEZPIECZNE
allow_credentials=True,     # W połączeniu z ["*"] = CRITICAL
```

**Rekomendacja:**
```python
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost").split(",")
allow_origins=ALLOWED_ORIGINS,
allow_methods=["GET", "POST"],
```

### 6.4 Rate Limiting

**Status: ❌ HIGH - BRAK**

Nginx config nie zawiera żadnego rate limiting. Dodać:
```nginx
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
```

### 6.5 Secrets

| ID | Problem | Lokalizacja | Priorytet |
|----|---------|-------------|-----------|
| S5.3a | Hardcoded default password | config.py:34 | MEDIUM |
| S5.3b | Hardcoded connection string | migrations/env.py:27 | MEDIUM |

---

## 7. DevOps (O7.x)

### 7.1 Brakujące Elementy

| Element | Status | Priorytet |
|---------|--------|-----------|
| **CI/CD pipeline** | ❌ BRAK `.github/workflows/` | **HIGH** |
| **CHANGELOG.md** | ❌ BRAK | **HIGH** |
| pyproject.toml | ❌ BRAK | MEDIUM |
| .pre-commit-config.yaml | ❌ BRAK | MEDIUM |
| pip-audit / safety | ❌ Niezainstalowane | MEDIUM |

### 7.2 Dockerfile

**Status: ⚠️ Do poprawy**

| Problem | Rekomendacja |
|---------|--------------|
| Brak multi-stage build | Dodać build stage dla mniejszego image |
| Brak .dockerignore | Utworzyć plik |
| COPY . . kopiuje wszystko | Selektywne COPY |

### 7.3 Zależności zewnętrzne (GitHub only)

**Status: ⚠️ RYZYKO**

| Biblioteka | Źródło | Gałąź |
|------------|--------|-------|
| kartograf | https://github.com/Daldek/Kartograf | @develop |
| hydrolog | https://github.com/user/hydrolog | @develop |

**Uwagi:**
- Kartograf i Hydrolog są dostępne **tylko z GitHub**, nie z PyPI
- Zależności na gałęziach @develop mogą powodować nieoczekiwane zmiany
- Rozważyć pin do konkretnych commitów lub tagów po stabilizacji

---

## 8. Kierunek Rozwoju (R8.x)

### 8.1 Status MVP

| Faza | Opis | Status |
|------|------|--------|
| Faza 0 | Setup | ✅ Ukończona |
| Faza 1 | Backend MVP | ✅ CP1, CP2 done |
| Faza 2 | Model Hydrologiczny | ✅ CP3 (przetestowane) |
| **Faza 3** | **Frontend** | ⏳ **PUSTE katalogi css/js** |
| Faza 4 | Testy i Deploy | ⏳ |

### 8.2 Technical Debt

| ID | Opis | Priorytet |
|----|------|-----------|
| TD-1 | Pydantic deprecation warning (class-based config) | MEDIUM |
| TD-2 | `land_cover.py` nieistniejący, CN=75 hardcoded | MEDIUM |
| TD-3 | `/api/scenarios` nieimplementowany | MEDIUM |
| TD-4 | Dokumentacja outdated vs kod | MEDIUM |

---

## Priorytetyzowane Akcje

### CRITICAL (natychmiast)

1. **[S5.5] Napraw CORS** - `api/main.py:41-47`
   - Zamień `allow_origins=["*"]` na listę dozwolonych domen
   - Usuń `allow_credentials=True` lub ogranicz origins

### HIGH (przed następnym release)

2. **[S5.6] Dodaj rate limiting** - `docker/nginx.conf`
3. **[O7.1] Utwórz CI/CD** - `.github/workflows/ci.yml`
4. **[O7.6] Utwórz CHANGELOG.md**
5. **[D1.3-2] Dodaj CHECK constraint** dla `land_cover.category`

### MEDIUM (w najbliższym sprincie)

6. **[Q3.9] Utwórz `constants.py`** z jednostkami i stałymi
7. **[C2.x] Zaktualizuj dokumentację** do aktualnego stanu kodu
8. **[T4.8] Dodaj testy dla scripts/** (szczególnie `process_dem.py`)
9. **[O7.x] Dodaj pyproject.toml i pre-commit**
10. **[S5.3] Usuń hardcoded secrets** z config.py i migrations/env.py

### LOW (backlog)

11. Napraw 15 błędów flake8
12. Sformatuj 3 pliki black
13. Zaktualizuj outdated packages
14. Dodaj Examples do `check_data_coverage` docstring
15. Zaimplementuj `/api/scenarios` lub usuń z dokumentacji

---

## Podsumowanie

Projekt Hydrograf ma solidną architekturę i dobrą jakość kodu w warstwie core logic. Główne obszary wymagające uwagi:

1. **Bezpieczeństwo** - CORS i rate limiting wymagają natychmiastowej naprawy
2. **DevOps** - Brak CI/CD i CHANGELOG to poważne braki dla projektu produkcyjnego
3. **Testy** - Skrypty preprocessingu nie mają żadnych testów
4. **Dokumentacja** - Wymaga synchronizacji z aktualnym stanem kodu

Po naprawie problemów CRITICAL i HIGH, projekt będzie gotowy do dalszego rozwoju w kierunku MVP.

---

*Raport wygenerowany przez Claude Code QA*
