# Cross-Project Analysis

**Data:** 2026-01-21
**Autor:** Claude Code (sesja analizy)
**Projekty:** Hydrograf, Hydrolog, Kartograf, IMGWTools

---

## 1. Mapa zależności

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           HYDROGRAF                                      │
│         (Główna aplikacja - System Analizy Hydrologicznej)              │
│         FastAPI + PostgreSQL/PostGIS + Leaflet.js                       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────┐   ┌───────────────┐   ┌───────────────┐             │
│  │  IMGWTools    │   │   Kartograf   │   │   Hydrolog    │             │
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

| Projekt | Zależy od | Typ zależności |
|---------|-----------|----------------|
| **Hydrograf** | IMGWTools | bezpośrednia (requirements.txt) |
| **Hydrograf** | Kartograf | bezpośrednia (requirements.txt) |
| **Hydrograf** | Hydrolog | bezpośrednia (requirements.txt) |
| **Hydrolog** | Kartograf | opcjonalna (`[spatial]`) |

**Uwaga:** Hydrolog nie ma już zależności od IMGWTools (usunięta w v0.5.2).

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

## 3. Wykryte problemy

### 3.1 ✅ NAPRAWIONE (2026-01-21)

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

### 3.2 ✅ NAPRAWIONE (IMGWTools - 2026-01-21)

| # | Projekt | Problem | Commit | Status |
|---|---------|---------|--------|--------|
| 5 | **IMGWTools** | Python `>=3.11` (inne `>=3.12`) | `4bacf36` | ✅ NAPRAWIONE |
| 6 | **IMGWTools** | Brak DEVELOPMENT_STANDARDS.md | `4bacf36` | ✅ NAPRAWIONE |

### 3.3 🟡 INFORMACYJNE (bez akcji)

| # | Projekt | Obserwacja | Status |
|---|---------|------------|--------|
| 7 | IMGWTools | Używa `ruff` (inne `black+flake8`) | OK (nowoczesne) |
| 8 | IMGWTools | Używa `hatchling` (inne `setuptools`) | OK |

---

## 4. Porównanie standardów kodu

| Aspekt | Hydrograf | Hydrolog | Kartograf | IMGWTools |
|--------|-----------|----------|-----------|-----------|
| **Python** | >=3.12 | >=3.12 | >=3.12 | >=3.12 |
| **Line length** | 88 ✅ | 88 | 88 | 88 |
| **Formatter** | black | black | black | ruff |
| **Linter** | flake8 | flake8 | flake8 | ruff |
| **Type checker** | mypy | mypy | - | mypy |
| **Docstrings** | NumPy (PL) | NumPy (EN) | NumPy (PL/EN) | NumPy (EN) |
| **Build** | setuptools | setuptools | setuptools | hatchling |
| **Tests** | pytest | pytest | pytest | pytest |
| **Coverage** | ≥80% | ≥80% | ≥80% | 80% (cel) |
| **Git workflow** | main/develop | main/develop | main/develop | master/slave |

**✅ Wszystkie projekty używają teraz spójnej długości linii 88 znaków.**

---

## 5. Porównanie wersji zależności

| Zależność | Hydrograf | Hydrolog | Kartograf | IMGWTools |
|-----------|-----------|----------|-----------|-----------|
| **numpy** | >=1.26.3 | >=1.24 | >=1.24.0 | - |
| **scipy** | >=1.12.0 | >=1.10 (opt) | - | - |
| **requests** | - | - | >=2.31.0 | - |
| **httpx** | >=0.26.0 | - | - | >=0.25 |
| **pydantic** | >=2.5.3 | - | - | >=2.0 |
| **rasterio** | >=1.3.9 | - | >=1.3.0 | - |

---

## 6. Plan naprawy

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
```

### Priorytet 5: BACKLOG (opcjonalne)

```markdown
□ Wszystkie: Rozważyć migrację do ruff
□ Wszystkie: Ujednolicić docstrings do EN
```

---

## 7. Dokumentacja w projektach

| Projekt | PROGRESS.md | DEVELOPMENT_STANDARDS.md | Status |
|---------|-------------|--------------------------|--------|
| Hydrograf | ✅ Szczegółowy | ✅ | Zaktualizowany (sesja 12) |
| Hydrolog | ✅ Szczegółowy | ✅ | Zaktualizowany (sesja 18) |
| Kartograf | ✅ Szczegółowy | ✅ | Zaktualizowany (cross-project) |
| IMGWTools | ✅ Szczegółowy | ✅ | Zaktualizowany (2026-01-21) |

### Odnośniki do dokumentacji

- **Hydrograf:** `PROGRESS.md` - 12 sesji, checkpointy, optymalizacje
- **Hydrolog:** `docs/PROGRESS.md` - sesja 18 z planem naprawy
- **Kartograf:** `docs/PROGRESS.md` - sekcja Cross-Project Analysis
- **IMGWTools:** `docs/PROGRESS.md` + `docs/DEVELOPMENT_STANDARDS.md`

---

## 8. Rekomendowany wspólny standard

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

## 9. Podsumowanie

### Co działa dobrze

- ✅ Jasna architektura zależności
- ✅ Każdy projekt może działać niezależnie
- ✅ Spójna konwencja 88 znaków linii (naprawiono w sesji 2)
- ✅ Dobra dokumentacja CLAUDE.md
- ✅ Testy z pokryciem >80% (Hydrolog, Kartograf)
- ✅ Integracja WatershedParameters (Hydrograf ↔ Hydrolog)

### ✅ Naprawione (2026-01-21)

- ✅ ~~KRYTYCZNY błąd w Hydrolog (stała SCS)~~ → naprawione w v0.5.2
- ✅ ~~Niespójność wersji w Hydrolog~~ → zsynchronizowane do v0.5.2
- ✅ ~~Brakujące eksporty w Kartograf~~ → dodane SoilGridsProvider, HSGCalculator
- ✅ ~~SCOPE.md/PRD.md nieaktualne w Kartograf~~ → zaktualizowane do v2.0
- ✅ ~~IMGWTools: Python 3.11~~ → podniesione do >=3.12 w v2.1.0
- ✅ ~~IMGWTools: brak DEVELOPMENT_STANDARDS.md~~ → utworzone
- ✅ ~~Hydrograf: brak PROGRESS.md~~ → utworzone (sesja 12)
- ✅ ~~Hydrograf: line-length = 100~~ → zmieniono na 88, 18 plików przeformatowanych

### Pozostałe (backlog opcjonalny)

- 📋 Migracja do ruff (opcjonalne)
- 📋 Ujednolicenie docstrings do EN (opcjonalne)

---

**Ostatnia aktualizacja:** 2026-01-21 (sesja 2: naprawiono line-length 100→88 w Hydrograf)
