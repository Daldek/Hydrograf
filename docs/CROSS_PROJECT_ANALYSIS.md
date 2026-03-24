# Cross-Project Analysis

**Data:** 2026-01-21
**Ostatnia aktualizacja:** 2026-03-01
**Autor:** Claude Code (sesja analizy)
**Projekty:** Hydrograf, Hydrolog, Kartograf, IMGWTools

---

## 1. Mapa zależności

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           HYDROGRAF                                      │
│         (Główna aplikacja - System Analizy Hydrologicznej)              │
│         FastAPI + PostgreSQL/PostGIS + Leaflet.js                       │
│         19 endpointów (11 core + 8 admin), 955 testów                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────┐   ┌───────────────┐   ┌───────────────┐             │
│  │  IMGWTools    │   │   Kartograf   │   │   Hydrolog    │             │
│  │  v2.1.0       │   │   v0.4.1      │   │   v0.6.3      │             │
│  │  (dane IMGW)  │   │ (dane GIS)    │   │ (obliczenia)  │             │
│  └───────────────┘   └───────────────┘   └───────┬───────┘             │
│                                                  │                      │
└──────────────────────────────────────────────────┼──────────────────────┘
                                                   │
                                                   ▼
                                            ┌──────────────┐
                                            │  Kartograf   │
                                            │  (opcja)     │
                                            └──────────────┘
```

### Szczegóły zależności

| Projekt | Zależy od | Typ zależności | Wersja |
|---------|-----------|----------------|--------|
| **Hydrograf** | IMGWTools | bezpośrednia (requirements.txt) | v2.1.0 |
| **Hydrograf** | Kartograf | bezpośrednia (requirements.txt) | v0.6.1 |
| **Hydrograf** | Hydrolog | bezpośrednia (requirements.txt) | v0.6.3 |
| **Hydrolog** | Kartograf | opcjonalna (`[spatial]`) | - |

**Uwaga:** Hydrolog nie ma już zależności od IMGWTools (usunięta w v0.5.2).

### Instalacja zależności (requirements.txt)

```
imgwtools @ git+https://github.com/Daldek/IMGWTools.git@v2.1.0
kartograf @ git+https://github.com/Daldek/Kartograf.git@v0.6.1
hydrolog @ git+https://github.com/Daldek/Hydrolog.git@v0.6.3
```

---

## 2. Stan gałęzi Git

| Projekt | Gałąź robocza | Inne gałęzie | Stan |
|---------|---------------|--------------|------|
| Hydrograf | `develop` | main | ✅ OK |
| Hydrolog | `develop` | main | ✅ OK |
| Kartograf | `develop` | main | ✅ OK |
| IMGWTools | `master` | slave (=master) | ✅ OK |

**Uwaga:** IMGWTools używa `master/slave` zamiast `main/develop`.

---

## 3. Punkty integracji w kodzie

### 3.1 Hydrolog — importy w Hydrografie

| Moduł Hydrografa | Importy z Hydrologa | Zastosowanie |
|-------------------|---------------------|--------------|
| `api/endpoints/hydrograph.py` | `WatershedParameters`, `BetaHietogram`, `BlockHietogram`, `EulerIIHietogram`, `HydrographGenerator` | Endpoint API generowania hydrogramu |
| `scripts/analyze_watershed.py` | `WatershedParameters`, `BetaHietogram`, `SCSCN`, `HydrographGenerator`, `SCSUnitHydrograph` | Skrypt CLI pełnej analizy |
| `core/morphometry.py` | `WatershedParameters` (w docstring) | Dokumentacja formatu wymiany |
| `tests/unit/test_morphometry.py` | `WatershedParameters` | Test kompatybilności formatu |

### 3.2 Kartograf — importy w Hydrografie

| Moduł Hydrografa | Importy z Kartografa | Zastosowanie |
|-------------------|---------------------|--------------|
| `scripts/download_dem.py` | `DownloadManager`, `GugikProvider`, `find_sheets_for_geometry` | Pobieranie NMT z GUGiK |
| `scripts/download_landcover.py` | `LandCoverManager`, `BBox`, `Bdot10kProvider` | Pobieranie BDOT10k/CORINE, wykrywanie TERYT |
| `scripts/bootstrap.py` | `SheetParser`, `HSGCalculator`, `BBox` | Orchestrator preprocessingu |
| `scripts/prepare_area.py` | `SheetParser` | Pipeline przygotowania obszaru |
| `core/cn_calculator.py` | `BBox`, `HSGCalculator`, `LandCoverManager` | Obliczanie CN (HSG + land cover) |

### 3.3 IMGWTools — importy w Hydrografie

| Moduł Hydrografa | Importy z IMGWTools | Zastosowanie |
|-------------------|---------------------|--------------|
| `scripts/preprocess_precipitation.py` | `fetch_pmaxtp` | Pobieranie PMAXTP z IMGW (42 scenariusze) |
| `scripts/analyze_watershed.py` | `fetch_pmaxtp` | Pobieranie opadu dla skryptu CLI |

---

## 4. Wykryte problemy

### 4.1 ✅ NAPRAWIONE (2026-01-21)

| # | Projekt | Problem | Commit | Status |
|---|---------|---------|--------|--------|
| 1 | **Hydrolog** | Błąd stałej SCS - Qmax zawyżony ~10x | `cc3e2a7` | ✅ NAPRAWIONE |
| 2 | **Hydrolog** | Niespójność wersji | v0.5.2 | ✅ NAPRAWIONE |
| 3 | **Kartograf** | Brak eksportów `SoilGridsProvider`, `HSGCalculator` | `23887db` | ✅ NAPRAWIONE |
| 4 | **Kartograf** | SCOPE.md/PRD.md nieaktualne | `b99c08e` | ✅ NAPRAWIONE |

#### Szczegóły naprawy SCS (Hydrolog)

```python
# BYŁO (błędnie):
qp = 2.08 * self.area_km2 / tp_hours

# JEST (poprawnie):
qp = 0.208 * self.area_km2 / tp_hours
```

**Wersje po naprawie:**
- Hydrolog: v0.5.2
- Kartograf: v0.3.1 (SCOPE.md/PRD.md zaktualizowane do v2.0)
- IMGWTools: v2.1.0 (Hydrograf zaktualizowany 2026-01-21)

### 4.2 ✅ NAPRAWIONE (IMGWTools - 2026-01-21)

| # | Projekt | Problem | Commit | Status |
|---|---------|---------|--------|--------|
| 5 | **IMGWTools** | Python `>=3.11` (inne `>=3.12`) | `4bacf36` | ✅ NAPRAWIONE |
| 6 | **IMGWTools** | Brak DEVELOPMENT_STANDARDS.md | `4bacf36` | ✅ NAPRAWIONE |

### 4.3 ✅ NAPRAWIONE (Hydrograf - sesja 2+)

| # | Projekt | Problem | Status |
|---|---------|---------|--------|
| 7 | **Hydrograf** | line-length 100 → 88 | ✅ NAPRAWIONE |
| 8 | **Hydrograf** | Migracja z black/flake8 → ruff | ✅ ZROBIONE |

### 4.4 ℹ️ INFORMACYJNE (bez akcji)

| # | Projekt | Obserwacja | Status |
|---|---------|------------|--------|
| 9 | IMGWTools | Używa `hatchling` (inne `setuptools`) | OK |

---

## 5. Porównanie standardów kodu

| Aspekt | Hydrograf | Hydrolog | Kartograf | IMGWTools |
|--------|-----------|----------|-----------|-----------|
| **Python** | >=3.12 | >=3.12 | >=3.12 | >=3.12 |
| **Line length** | 88 ✅ | 88 | 88 | 88 |
| **Formatter** | ruff | black | black | ruff |
| **Linter** | ruff | flake8 | flake8 | ruff |
| **Type checker** | mypy | mypy | - | mypy |
| **Docstrings** | NumPy (PL) | NumPy (EN) | NumPy (PL/EN) | NumPy (EN) |
| **Build** | setuptools | setuptools | setuptools | hatchling |
| **Tests** | pytest | pytest | pytest | pytest |
| **Coverage** | ≥80% | ≥80% | ≥80% | 80% (cel) |
| **Git workflow** | main/develop | main/develop | main/develop | master/slave |

**Uwaga:** Hydrograf przeszedł z black/flake8 na ruff (formatter + linter) — nowoczesna konfiguracja w `[tool.ruff]` w pyproject.toml.

---

## 6. Porównanie wersji zależności

| Zależność | Hydrograf | Hydrolog | Kartograf | IMGWTools |
|-----------|-----------|----------|-----------|-----------|
| **numpy** | >=1.26.3 | >=1.24 | >=1.24.0 | - |
| **scipy** | >=1.12.0 | >=1.10 (opt) | - | - |
| **requests** | - | - | >=2.31.0 | - |
| **httpx** | >=0.26.0 | - | - | >=0.25 |
| **pydantic** | >=2.5.3 | - | - | >=2.0 |
| **rasterio** | >=1.3.9 | - | >=1.3.0 | - |
| **psutil** | >=5.9 | - | - | - |
| **geopandas** | >=0.14.2 | - | - | - |
| **fiona** | >=1.9.5 | - | - | - |

---

## 7. Metryki projektów

### Hydrograf (stan na 2026-03-24)

| Metryka | Wartość |
|---------|---------|
| Wersja | v0.4.0 (CP4 Faza 4) |
| Endpointy API | 19 (11 core + 8 admin) |
| Testy | 955 |
| Moduły core | 15 (w `backend/core/`) |
| Skrypty | 14 (w `backend/scripts/`) |
| Frontend JS | 13 modułów (9 core + 4 admin) |
| ADR | 41 decyzji architektonicznych |

### Punkty integracji per biblioteka

| Biblioteka | Pliki źródłowe | Pliki testowe | Łączne importy |
|------------|----------------|---------------|-----------------|
| Hydrolog | 4 | 2 | 6 |
| Kartograf | 6 | 4 | 10 |
| IMGWTools | 2 | 0 | 2 |

---

## 8. Plan naprawy — HISTORIA

### ✅ Priorytet 1: KRYTYCZNE - UKOŃCZONE

```markdown
✅ Hydrolog: Naprawić stałą SCS (commit cc3e2a7)
  - Plik: hydrolog/runoff/unit_hydrograph.py:214
  - Zmiana: 2.08 → 0.208
  - Zaktualizowano docstring z poprawną matematyką

✅ Hydrolog: Zsynchronizować wersję (v0.5.2)
  - Plik: hydrolog/__init__.py
  - Zmiana: __version__ = "0.4.0" → "0.5.1"
```

### ✅ Priorytet 2: WAŻNE - UKOŃCZONE

```markdown
✅ Kartograf: Dodać brakujące eksporty (commit 23887db)
  - Plik: kartograf/__init__.py
  - Dodano: SoilGridsProvider, HSGCalculator

✅ Kartograf: Zaktualizować SCOPE.md i PRD.md (commit b99c08e)
  - Dokumentacja zaktualizowana do v2.0
```

### ✅ Priorytet 3: IMGWTools - UKOŃCZONE

```markdown
✅ IMGWTools: Podniesiono Python do >=3.12 (commit 4bacf36)
  - Plik: pyproject.toml
  - Zmiana: requires-python = ">=3.11" → ">=3.12"
  - Wersja: v2.1.0

✅ IMGWTools: Utworzono DEVELOPMENT_STANDARDS.md (commit 4bacf36)
  - Plik: docs/DEVELOPMENT_STANDARDS.md
  - 425 linii, pełne standardy kodowania
```

### ✅ Priorytet 4: NAPRAWIONE (2026-01-21 sesja 2)

```markdown
✅ Hydrograf: line-length = 100 → 88
  - Plik: backend/pyproject.toml (zmieniono tool.black i tool.flake8)
  - 18 plików przeformatowanych z black
  - Wszystkie 200 testów przechodzą

✅ Hydrograf: Migracja z black/flake8 → ruff (sesje późniejsze)
  - [tool.ruff] w pyproject.toml
  - ruff>=0.8 w dev dependencies
```

### Priorytet 5: BACKLOG (opcjonalne)

```markdown
□ Wszystkie: Ujednolicić docstrings do EN
□ Kartograf: Rozważyć migrację do ruff
```

---

## 9. Dokumentacja w projektach

| Projekt | PROGRESS.md | DEVELOPMENT_STANDARDS.md | Status |
|---------|-------------|--------------------------|--------|
| Hydrograf | ✅ Szczegółowy | ✅ | Zaktualizowany (sesja 48) |
| Hydrolog | ✅ Szczegółowy | ✅ | Zaktualizowany (sesja 18) |
| Kartograf | ✅ Szczegółowy | ✅ | Zaktualizowany (cross-project) |
| IMGWTools | ✅ Szczegółowy | ✅ | Zaktualizowany (2026-01-21) |

### Dokumentacja integracji Hydrografa

| Plik | Opis | Status |
|------|------|--------|
| `docs/HYDROLOG_INTEGRATION.md` | Format wymiany, endpointy, moduły | ✅ Aktualny |
| `docs/KARTOGRAF_INTEGRATION.md` | NMT, BDOT10k, HSG, building raising, MVT | ✅ Aktualny |
| `docs/CROSS_PROJECT_ANALYSIS.md` | Zależności, standardy, metryki | ✅ Aktualny |

---

## 10. Rekomendowany wspólny standard

```toml
# Wspólna konfiguracja dla wszystkich projektów

[project]
requires-python = ">=3.12"

[tool.ruff]
target-version = "py312"
line-length = 88
select = ["E", "W", "F", "I", "B", "C4", "UP"]

[tool.mypy]
python_version = "3.12"
warn_return_any = true
disallow_untyped_defs = true

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v"

[tool.coverage.report]
fail_under = 80
```

**Docstrings:** NumPy style, English
**Commits:** Conventional Commits
**Git workflow:** main + develop (lub master + slave dla IMGWTools)

---

## 11. Podsumowanie

### Co działa dobrze

- ✅ Jasna architektura zależności (3 biblioteki, czyste kontrakty)
- ✅ Każdy projekt może działać niezależnie
- ✅ Spójna konwencja 88 znaków linii
- ✅ Dobra dokumentacja CLAUDE.md
- ✅ Testy z pokryciem >80% (Hydrolog, Kartograf)
- ✅ Integracja WatershedParameters (Hydrograf ↔ Hydrolog)
- ✅ Pełny pipeline preprocessingu (bootstrap.py + 9 kroków)
- ✅ CN calculation z HSG + land cover (Kartograf)
- ✅ Building raising z BUBD (ADR-033)
- ✅ Land cover MVT tiles
- ✅ Panel administracyjny z bootstrap SSE (ADR-034)

### ✅ Naprawione (2026-01-21 – 2026-03-01)

- ✅ ~~KRYTYCZNY błąd w Hydrolog (stała SCS)~~ → naprawione w v0.5.2
- ✅ ~~Niespójność wersji w Hydrolog~~ → zsynchronizowane do v0.5.2
- ✅ ~~Brakujące eksporty w Kartograf~~ → dodane SoilGridsProvider, HSGCalculator
- ✅ ~~SCOPE.md/PRD.md nieaktualne w Kartograf~~ → zaktualizowane do v2.0
- ✅ ~~IMGWTools: Python 3.11~~ → podniesione do >=3.12 w v2.1.0
- ✅ ~~IMGWTools: brak DEVELOPMENT_STANDARDS.md~~ → utworzone
- ✅ ~~Hydrograf: brak PROGRESS.md~~ → utworzone (sesja 12)
- ✅ ~~Hydrograf: line-length = 100~~ → zmieniono na 88
- ✅ ~~Hydrograf: black/flake8~~ → zmigrowano na ruff

### Pozostałe (backlog opcjonalny)

- Ujednolicenie docstrings do EN (opcjonalne)
- Kartograf: rozważyć migrację do ruff (opcjonalne)

---

**Ostatnia aktualizacja:** 2026-03-24 (sesja 67: BDOT stream matching, hydraulic length, 955 testow)
