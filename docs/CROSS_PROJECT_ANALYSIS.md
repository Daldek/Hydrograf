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
│  └───────┬───────┘   └───────┬───────┘   └───────┬───────┘             │
│          │                   │                   │                      │
└──────────┼───────────────────┼───────────────────┼──────────────────────┘
           │                   │                   │
           │                   │        ┌──────────┴──────────┐
           │                   │        │                     │
           ▼                   ▼        ▼                     ▼
    ┌─────────────┐      ┌──────────┐  ┌─────────────┐  ┌──────────────┐
    │ IMGWTools   │      │Kartograf │  │ IMGWTools   │  │  Kartograf   │
    │ (standalone)│      │(optional)│  │ (wymagany)  │  │  (opcja)     │
    └─────────────┘      └──────────┘  └─────────────┘  └──────────────┘
```

### Szczegóły zależności

| Projekt | Zależy od | Typ zależności |
|---------|-----------|----------------|
| **Hydrograf** | IMGWTools | bezpośrednia (requirements.txt) |
| **Hydrograf** | Kartograf | bezpośrednia (requirements.txt) |
| **Hydrograf** | Hydrolog | bezpośrednia (requirements.txt) |
| **Hydrolog** | IMGWTools | wymagana (pyproject.toml) |
| **Hydrolog** | Kartograf | opcjonalna (`[spatial]`) |

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

### 3.1 🔴 KRYTYCZNE

| # | Projekt | Problem | Plik | Status |
|---|---------|---------|------|--------|
| 1 | **Hydrolog** | Błąd stałej SCS - Qmax zawyżony ~10x | `hydrolog/runoff/unit_hydrograph.py:214` | DO NAPRAWY |
| 2 | **Hydrolog** | Niespójność wersji (pyproject vs __init__) | `__init__.py`: 0.4.0, `pyproject.toml`: 0.5.0 | DO NAPRAWY |

#### Szczegóły błędu SCS

```python
# BŁĘDNIE (obecnie w kodzie):
qp = 2.08 * self.area_km2 / tp_hours

# Docstring twierdzi:
# "0.208 * 1000 / 3600 = 2.08"  ← BŁĄD MATEMATYCZNY!

# Prawidłowo:
# 0.208 * 1000 / 3600 = 0.0578

# POPRAWNA WARTOŚĆ:
qp = 0.208 * self.area_km2 / tp_hours
```

**Skutek:** Przepływ maksymalny (Qmax) jest zawyżony ~10x.

### 3.2 🟠 WAŻNE

| # | Projekt | Problem | Status |
|---|---------|---------|--------|
| 3 | IMGWTools | Python `>=3.11` (inne `>=3.12`) | DO ROZWAŻENIA |
| 4 | Kartograf | Brak eksportów `SoilGridsProvider`, `HSGCalculator` | DO NAPRAWY |

### 3.3 🟡 NISKI PRIORYTET

| # | Projekt | Problem | Status |
|---|---------|---------|--------|
| 5 | IMGWTools | Używa `ruff` (inne `black+flake8`) | INFO |
| 6 | IMGWTools | Używa `hatchling` (inne `setuptools`) | INFO |
| 7 | Kartograf | SCOPE.md/PRD.md nieaktualne | BACKLOG |
| 8 | IMGWTools | Brak DEVELOPMENT_STANDARDS.md | BACKLOG |

---

## 4. Porównanie standardów kodu

| Aspekt | Hydrograf | Hydrolog | Kartograf | IMGWTools |
|--------|-----------|----------|-----------|-----------|
| **Python** | >=3.12 (implicit) | >=3.12 | >=3.12 | >=3.11 ⚠️ |
| **Line length** | 88 | 88 | 88 | 88 |
| **Formatter** | black | black | black | ruff |
| **Linter** | flake8 | flake8 | flake8 | ruff |
| **Type checker** | mypy | mypy | - | mypy |
| **Docstrings** | NumPy (PL) | NumPy (EN) | NumPy (PL/EN) | NumPy (EN) |
| **Build** | - | setuptools | setuptools | hatchling |
| **Tests** | pytest | pytest | pytest | pytest |
| **Coverage** | ≥80% | ≥80% | ≥80% | 80% (cel) |
| **Git workflow** | main/develop | main/develop | main/develop | master/slave |

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

### Priorytet 1: KRYTYCZNE (natychmiast)

```markdown
□ Hydrolog: Naprawić stałą SCS
  - Plik: hydrolog/runoff/unit_hydrograph.py:214
  - Zmiana: 2.08 → 0.208
  - Zaktualizować docstring z poprawną matematyką

□ Hydrolog: Zsynchronizować wersję
  - Plik: hydrolog/__init__.py
  - Zmiana: __version__ = "0.4.0" → "0.5.0"
```

### Priorytet 2: WAŻNE (w ciągu tygodnia)

```markdown
□ Kartograf: Dodać brakujące eksporty
  - Plik: kartograf/__init__.py
  - Dodać: SoilGridsProvider, HSGCalculator

□ IMGWTools: Rozważyć podniesienie Python do >=3.12
```

### Priorytet 3: BACKLOG

```markdown
□ Kartograf: Zaktualizować SCOPE.md i PRD.md
□ IMGWTools: Utworzyć DEVELOPMENT_STANDARDS.md
□ Wszystkie: Rozważyć migrację do ruff
□ Wszystkie: Ujednolicić docstrings do EN
```

---

## 7. Dokumentacja w projektach

| Projekt | PROGRESS.md | Status |
|---------|-------------|--------|
| Hydrograf | ❌ Brak | Utworzyć |
| Hydrolog | ✅ Szczegółowy | Zaktualizowany (sesja 18) |
| Kartograf | ✅ Szczegółowy | Zaktualizowany (cross-project) |
| IMGWTools | ✅ Nowy | Utworzony (2026-01-21) |

### Odnośniki do dokumentacji

- **Hydrolog:** `docs/PROGRESS.md` - sesja 18 z planem naprawy
- **Kartograf:** `docs/PROGRESS.md` - sekcja Cross-Project Analysis
- **IMGWTools:** `docs/PROGRESS.md` - nowy plik

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
- ✅ Spójna konwencja 88 znaków linii
- ✅ Dobra dokumentacja CLAUDE.md
- ✅ Testy z pokryciem >80% (Hydrolog, Kartograf)
- ✅ Integracja WatershedParameters (Hydrograf ↔ Hydrolog)

### Do naprawy

- ❌ KRYTYCZNY błąd w Hydrolog (stała SCS)
- ⚠️ Niespójność wersji w Hydrolog
- ⚠️ Brakujące eksporty w Kartograf
- ⚠️ Różne wersje Pythona (3.11 vs 3.12)

---

**Ostatnia aktualizacja:** 2026-01-21
