# Cross-Project Analysis

**Date:** 2026-01-21
**Last update:** 2026-10-25 (the three producers on their heads, ADR-060, ADR-061; the document is in English)
**Author:** Claude Code (analysis session)
**Projects:** Hydrograf, Hydrolog, Kartograf, IMGWTools

---

## 1. Dependency map

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           HYDROGRAF                                     │
│         (Main application - Hydrological Analysis System)               │
│         FastAPI + PostgreSQL/PostGIS + Leaflet.js                       │
│         23 endpoints (11 core + 12 admin), 991 tests (2026-03-27)       │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────┐   ┌───────────────┐   ┌───────────────┐              │
│  │  IMGWTools    │   │   Kartograf   │   │   Hydrolog    │              │
│  │  3f7de36      │   │   45dedf4     │   │   5fa22b3     │              │
│  │  (IMGW data)  │   │  (GIS data)   │   │ (calculations)│              │
│  └───────────────┘   └───────────────┘   └───────────────┘              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Details of the dependencies

| Project | Depends on | Type of dependency | Version |
|---------|-----------|--------------------|---------|
| **Hydrograf** | IMGWTools | direct (pyproject.toml) | commit 3f7de36 (3.0.0) |
| **Hydrograf** | Kartograf | direct (pyproject.toml) | commit 45dedf4 (0.8.0.dev0) |
| **Hydrograf** | Hydrolog | direct (pyproject.toml) | commit 5fa22b3 (1.0.0.dev0) |
| **Hydrolog** | Kartograf | none (the `[spatial]` extra is gone; Hydrolog reads files that Kartograf wrote) | - |

**Note:** Hydrolog no longer depends on IMGWTools (removed in v0.5.2).

### Installing the dependencies (`backend/pyproject.toml`, versions in `backend/uv.lock`)

The three producers are pinned by the commit of their head until their tags exist (REL-5.3, ADR-060, ADR-061); the release replaces each commit with its tag:

```toml
# [tool.uv.sources]
imgwtools = { git = "https://github.com/Daldek/IMGWTools.git", rev = "3f7de36f98f1ba40d72ab5556942567cfbc55b92" }
kartograf = { git = "https://github.com/Daldek/Kartograf.git", rev = "45dedf4a155e2d2f7302459a8c383876fed98e98" }
hydrolog = { git = "https://github.com/Daldek/Hydrolog.git", rev = "5fa22b35e5e1ec9076c41d0be04d2a99458f5049" }
```

---

## 2. State of the Git branches

| Project | Working branch | Other branches | State |
|---------|----------------|----------------|-------|
| Hydrograf | `develop` | main | ✅ OK |
| Hydrolog | `develop` | main | ✅ OK |
| Kartograf | `develop` | main | ✅ OK |
| IMGWTools | `master` | slave (=master) | ✅ OK |

**Note:** IMGWTools uses `master/slave` instead of `main/develop`.

**Pinned branches:** the pins point at topic branches, not at the working branches: Kartograf and IMGWTools `feature/data-output`, Hydrolog `feature/routing-schematic`. All three commits are on GitHub (ADR-060).

---

## 3. Integration points in the code

### 3.1 Hydrolog: imports in Hydrograf

| Hydrograf module | Imports from Hydrolog | Use |
|------------------|-----------------------|-----|
| `api/endpoints/hydrograph.py` | `WatershedParameters`, `BetaHietogram`, `BlockHietogram`, `EulerIIHietogram`, `HydrographGenerator` | The hydrograph generation endpoint |
| `api/endpoints/hydrograph.py` | `ConcentrationTime` | Time of concentration: 6 methods: kirpich, nrcs, faa, kerby, kerby_kirpich, giandotti |
| `api/endpoints/hydrograph.py` | `NashIUH` | The Nash model: 3 parameter estimations: from_lutz, from_urban_regression, from_tc |
| `api/endpoints/hydrograph.py` | `uh_model` selector | The choice of the unit hydrograph model: scs / nash / snyder |
| `scripts/analyze_watershed.py` | `WatershedParameters`, `BetaHietogram`, `SCSCN`, `HydrographGenerator`, `SCSUnitHydrograph` | The CLI script of the full analysis |
| `core/morphometry.py` | `WatershedParameters` (in a docstring) | Documentation of the exchange format |
| `tests/unit/test_tc_methods.py` | `ConcentrationTime` | Tests of the tc methods (faa, kerby, kerby_kirpich) |

### 3.2 Kartograf: imports in Hydrograf

| Hydrograf module | Imports from Kartograf | Use |
|------------------|------------------------|-----|
| `utils/sheet_lookup.py` | `BBox`, `find_sheets_for_bbox` | Point + buffer to sheet codes (ADR-057) |
| `utils/kartograf_store.py` | `MetadataCache`, `download_landcover`, `BBox`, `KartografError`, `NoCoverageError` | The store of the pipeline, the metadata cache, the BDOT10k packages of the counties of an area (ADR-061) |
| `scripts/download_dem.py` | `DownloadManager`, `GugikProvider`, `MetadataCache`, `find_sheets_for_geometry` | NMT download into the store |
| `scripts/download_landcover.py` | `MetadataCache`, `download_landcover` | BDOT10k / CORINE download into the store |
| `scripts/bootstrap.py` | `SheetParser`, `BBox`, `find_sheets_for_bbox`, `find_sheets_for_geometry`, `calculate_hsg`, `KartografError`, `ParseError`, `ValidationError` | The preprocessing orchestrator |
| `scripts/prepare_area.py` | `BBox`, `SheetParser` | The area preparation pipeline |
| `scripts/analyze_watershed.py` | `iter_store`, `list_segments` | The NMT sheets of the store |
| `core/cn_calculator.py` | `BBox`, `calculate_hsg`, `download_landcover`, `hsg_statistics`, `KartografError` | The CN calculation (HSG + land cover) |
| `core/db_bulk.py` | none (works on the BDOT10k GeoPackage that Kartograf downloaded) | BDOT stream matching (ADR-044): the `is_real_stream` flag, the table `bdot_streams`, overlap-based matching |

The WFS PRG discovery of the counties (ADR-045) and its fallback on a private method of Kartograf (ADR-057, exception a) are gone: `download_landcover(bbox=)` finds the counties of an area itself (ADR-061). `LandCoverManager` and `HSGCalculator` are no longer public in Kartograf 0.8.0. Details: [integrations/KARTOGRAF.md](integrations/KARTOGRAF.md) §5.

### 3.3 IMGWTools: imports in Hydrograf

| Hydrograf module | Imports from IMGWTools | Use |
|------------------|------------------------|-----|
| `scripts/preprocess_precipitation.py` | `fetch_pmaxtp` | Downloading PMAXTP from IMGW (432 scenarios) |
| `scripts/analyze_watershed.py` | `fetch_pmaxtp` | Downloading the precipitation for the CLI script |

---

## 4. Problems found

### 4.1 ✅ FIXED (2026-01-21)

| # | Project | Problem | Commit | Status |
|---|---------|---------|--------|--------|
| 1 | **Hydrolog** | A bug in the SCS constant: Qmax overstated ~10x | `cc3e2a7` | ✅ FIXED |
| 2 | **Hydrolog** | Inconsistent versions | v0.5.2 | ✅ FIXED |
| 3 | **Kartograf** | Missing exports `SoilGridsProvider`, `HSGCalculator` | `23887db` | ✅ FIXED |
| 4 | **Kartograf** | SCOPE.md/PRD.md out of date | `b99c08e` | ✅ FIXED |

`HSGCalculator` itself was replaced in Kartograf 0.8.0 by `calculate_hsg` and `hsg_statistics` (ADR-061).

#### Details of the SCS fix (Hydrolog)

```python
# WAS (wrong):
qp = 2.08 * self.area_km2 / tp_hours

# IS (correct):
qp = 0.208 * self.area_km2 / tp_hours
```

**Versions after the fix:**
- Hydrolog: v0.5.2
- Kartograf: v0.3.1 (SCOPE.md/PRD.md updated to v2.0)
- IMGWTools: v2.1.0 (Hydrograf updated on 2026-01-21)

### 4.2 ✅ FIXED (IMGWTools - 2026-01-21)

| # | Project | Problem | Commit | Status |
|---|---------|---------|--------|--------|
| 5 | **IMGWTools** | Python `>=3.11` (the others `>=3.12`) | `4bacf36` | ✅ FIXED |
| 6 | **IMGWTools** | No DEVELOPMENT_STANDARDS.md | `4bacf36` | ✅ FIXED |

### 4.3 ✅ FIXED (Hydrograf - session 2+)

| # | Project | Problem | Status |
|---|---------|---------|--------|
| 7 | **Hydrograf** | line-length 100 → 88 | ✅ FIXED |
| 8 | **Hydrograf** | Migration from black/flake8 → ruff | ✅ DONE |

### 4.5 ✅ FIXED (sessions 69-71, 2026-03-25)

| # | Project | Problem | ADR/Commit | Status |
|---|---------|---------|------------|--------|
| 10 | **Kartograf** | WFS BBOX axis order fix (EPSG:2180 Y,X instead of X,Y) | session 69 | ✅ FIXED |
| 11 | **Hydrograf** | Mosaic bbox alignment (TERYT/BDOT/HSG): a mismatch of the extents | session 69 | ✅ FIXED |
| 12 | **Hydrograf** | DEM auto-discovery with a fallback chain | ADR-049 | ✅ FIXED |
| 13 | **Hydrograf** | Chaikin smoothing of streams in preprocessing | ADR-047 | ✅ FIXED |
| 14 | **Hydrograf** | The flow path from the watershed divide as a separate geometry | ADR-048 | ✅ FIXED |

### 4.4 ℹ️ INFORMATIONAL (no action)

| # | Project | Observation | Status |
|---|---------|-------------|--------|
| 9 | IMGWTools | Uses `hatchling` (the others `setuptools`) | OK |

---

## 5. Comparison of the code standards

| Aspect | Hydrograf | Hydrolog | Kartograf | IMGWTools |
|--------|-----------|----------|-----------|-----------|
| **Python** | >=3.12 | >=3.12 | >=3.12 | >=3.12 |
| **Line length** | 88 ✅ | 88 | 88 | 88 |
| **Formatter** | ruff | black | black | ruff |
| **Linter** | ruff | flake8 | flake8 | ruff |
| **Type checker** | mypy | mypy | - | mypy |
| **Docstrings** | NumPy (PL) | NumPy (EN) | NumPy (PL/EN) | NumPy (EN) |
| **Build** | setuptools | setuptools | setuptools | hatchling |
| **Tests** | pytest | pytest | pytest | pytest |
| **Coverage** | ≥80% | ≥80% | ≥80% | 80% (target) |
| **Git workflow** | main/develop | main/develop | main/develop | master/slave |

**Note:** Hydrograf moved from black/flake8 to ruff (formatter + linter): a modern configuration in `[tool.ruff]` in pyproject.toml.

---

## 6. Comparison of the versions of the dependencies

| Dependency | Hydrograf | Hydrolog | Kartograf | IMGWTools |
|------------|-----------|----------|-----------|-----------|
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

## 7. Project metrics

### Hydrograf (as of 2026-03-27)

| Metric | Value |
|--------|-------|
| Version | v0.4.0+ (CP4 + sewer integration) |
| API endpoints | 23 (11 core + 12 admin) |
| Tests | 991 |
| Core modules | 11 active (in `backend/core/`) |
| Scripts | 14+ (in `backend/scripts/`) |
| Front-end JS | 15 modules (10 core + 5 admin) |
| ADRs | 51 architecture decisions |

### Integration points per library (as of 2026-03-27)

| Library | Source files | Test files | Total imports |
|---------|--------------|------------|---------------|
| Hydrolog | 4 | 3 | 7 |
| Kartograf | 7 | 4 | 11 |
| IMGWTools | 2 | 0 | 2 |

---

## 8. Repair plan: HISTORY

### ✅ Priority 1: CRITICAL - DONE

```markdown
✅ Hydrolog: Fix the SCS constant (commit cc3e2a7)
  - File: hydrolog/runoff/unit_hydrograph.py:214
  - Change: 2.08 → 0.208
  - The docstring was updated with the correct maths

✅ Hydrolog: Synchronise the version (v0.5.2)
  - File: hydrolog/__init__.py
  - Change: __version__ = "0.4.0" → "0.5.1"
```

### ✅ Priority 2: IMPORTANT - DONE

```markdown
✅ Kartograf: Add the missing exports (commit 23887db)
  - File: kartograf/__init__.py
  - Added: SoilGridsProvider, HSGCalculator

✅ Kartograf: Update SCOPE.md and PRD.md (commit b99c08e)
  - The documentation was updated to v2.0
```

### ✅ Priority 3: IMGWTools - DONE

```markdown
✅ IMGWTools: Python raised to >=3.12 (commit 4bacf36)
  - File: pyproject.toml
  - Change: requires-python = ">=3.11" → ">=3.12"
  - Version: v2.1.0

✅ IMGWTools: DEVELOPMENT_STANDARDS.md created (commit 4bacf36)
  - File: docs/DEVELOPMENT_STANDARDS.md
  - 425 lines, the full coding standards
```

### ✅ Priority 4: FIXED (2026-01-21 session 2)

```markdown
✅ Hydrograf: line-length = 100 → 88
  - File: backend/pyproject.toml (tool.black and tool.flake8 changed)
  - 18 files reformatted with black
  - All 200 tests pass

✅ Hydrograf: Migration from black/flake8 → ruff (later sessions)
  - [tool.ruff] in pyproject.toml
  - ruff>=0.8 in the dev dependencies
```

### Priority 5: BACKLOG (optional)

```markdown
□ All: Unify the docstrings to EN
□ Kartograf: Consider migrating to ruff
```

---

## 9. Documentation in the projects

| Project | PROGRESS.md | DEVELOPMENT_STANDARDS.md | Status |
|---------|-------------|--------------------------|--------|
| Hydrograf | ✅ Detailed | ✅ | Updated (session 48) |
| Hydrolog | ✅ Detailed | ✅ | Updated (session 18) |
| Kartograf | ✅ Detailed | ✅ | Updated (cross-project) |
| IMGWTools | ✅ Detailed | ✅ | Updated (2026-01-21) |

### Documentation of the Hydrograf integrations

| File | Description | Status |
|------|-------------|--------|
| `docs/integrations/HYDROLOG.md` | The exchange format, endpoints, modules | ✅ Current |
| `docs/integrations/KARTOGRAF.md` | The Kartograf store, NMT, BDOT10k, HSG, building raising, MVT (version 7.0, ADR-061) | ✅ Current |
| `docs/integrations/IMGWTOOLS.md` | PMAXTP, `fetch_pmaxtp`, the errors | ✅ Current |
| `docs/CROSS_PROJECT_ANALYSIS.md` | Dependencies, standards, metrics | ✅ Current |

---

## 10. Recommended common standard

```toml
# A common configuration for all the projects

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
**Git workflow:** main + develop (or master + slave for IMGWTools)

---

## 11. Summary

### What works well

- ✅ A clear architecture of the dependencies (3 libraries, clean contracts)
- ✅ Each project can work independently
- ✅ A consistent convention of 88 characters per line
- ✅ Good CLAUDE.md documentation
- ✅ Tests with >80% coverage (Hydrolog, Kartograf)
- ✅ The integration of WatershedParameters (Hydrograf ↔ Hydrolog)
- ✅ A full preprocessing pipeline (bootstrap.py + 10 steps)
- ✅ The CN calculation from HSG + land cover (Kartograf)
- ✅ Land cover MVT tiles
- ✅ An admin panel with the bootstrap over SSE (ADR-034)
- ✅ ConcentrationTime: 6 tc methods (kirpich, nrcs, faa, kerby, kerby_kirpich, giandotti)
- ✅ NashIUH: 3 parameter estimations (from_lutz, from_urban_regression, from_tc)
- ✅ The UH model selector (scs/nash/snyder)
- ✅ County (TERYT) discovery by Kartograf (ADR-061; it replaced the WFS PRG code of ADR-045)
- ✅ BDOT stream matching with is_real_stream (ADR-044)
- ✅ DEM auto-discovery with a fallback chain (ADR-049)

### ✅ Fixed (2026-01-21 – 2026-03-25)

- ✅ ~~A CRITICAL bug in Hydrolog (the SCS constant)~~ → fixed in v0.5.2
- ✅ ~~Inconsistent versions in Hydrolog~~ → synchronised to v0.5.2
- ✅ ~~Missing exports in Kartograf~~ → SoilGridsProvider, HSGCalculator added
- ✅ ~~SCOPE.md/PRD.md out of date in Kartograf~~ → updated to v2.0
- ✅ ~~IMGWTools: Python 3.11~~ → raised to >=3.12 in v2.1.0
- ✅ ~~IMGWTools: no DEVELOPMENT_STANDARDS.md~~ → created
- ✅ ~~Hydrograf: no PROGRESS.md~~ → created (session 12)
- ✅ ~~Hydrograf: line-length = 100~~ → changed to 88
- ✅ ~~Hydrograf: black/flake8~~ → migrated to ruff
- ✅ ~~WFS BBOX axis order (EPSG:2180 Y,X)~~ → fixed (session 69)
- ✅ ~~Mosaic bbox alignment (TERYT/BDOT/HSG)~~ → fixed (session 69)
- ✅ ~~DEM auto-discovery~~ → ADR-049
- ✅ ~~Chaikin smoothing of streams~~ → ADR-047
- ✅ ~~The flow path from the watershed divide~~ → ADR-048

### Remaining (optional backlog)

- Unify the docstrings to EN (optional)
- Kartograf: consider migrating to ruff (optional)
- Building raising (ADR-033): `process_dem` takes the footprints, but no script passes them, so the pipeline does not raise buildings ([BACKLOG.md](BACKLOG.md))

---

**Last update:** 2026-10-25 (the producers pinned on their heads, the Kartograf 0.8.0 migration, ADR-060, ADR-061; translated to English). Before: 2026-03-25 (session 71: ConcentrationTime/NashIUH/uh_model, WFS PRG TERYT, BDOT stream matching, ADR-044..049, 899 tests).
