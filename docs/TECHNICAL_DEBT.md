# Technical Debt - Hydrograf

A list of known technical problems to fix in future iterations.

---

## Hardcoded Values (Q3.9)

**Action:** ~~Create `backend/core/constants.py` with all the constants.~~ DONE (v0.4.0, `core/constants.py` — CRS, unit conversions, the default CN, the limits of the watershed and of the graph).

### Unit conversion constants — PARTLY DONE

The constants `M_PER_KM` and `M2_PER_KM2` exist in `core/constants.py`, but the `core/` modules do not use them:

| Value | Location | Status |
|-------|----------|--------|
| `1000.0` (m/km) | `core/morphometry.py` ×4 (lines 37, 73, 253, 486) | Still hardcoded — `M_PER_KM` is not imported |
| `1_000_000` (m²/km²) | `core/watershed.py:252`, `core/morphometry.py:598` | Still hardcoded — `M2_PER_KM2` is not imported |

**Note:** `M2_PER_KM2` is imported in `api/endpoints/watershed.py`, but the core modules do not use the constants — a gap between the intent and the implementation.

### Algorithm parameters

| Value | Location | Description | Status |
|-------|----------|-------------|--------|
| `0.3` | `core/watershed.py:211` | Concave hull ratio | Still hardcoded |
| `75` | ~~`core/morphometry.py`~~ | Default CN value | DONE — `DEFAULT_CN` in `constants.py`, used by `land_cover.py` |

### CRS identifiers — PARTLY DONE

The constants `CRS_PL1992` and `CRS_WGS84` exist in `core/constants.py`, but the string `"EPSG:2180"` still appears directly in 7+ core files:

| Value | Location | Status |
|-------|----------|--------|
| `"EPSG:2180"` | `core/cn_calculator.py`, `core/hydrology.py` ×2, `core/morphometry.py`, `core/precipitation.py`, `core/raster_io.py`, `core/watershed_service.py` | Still hardcoded — `CRS_PL1992` is not imported |
| `"EPSG:2180"` | `utils/geometry.py`, `models/schemas.py` | Still hardcoded |

### Other

| Value | Location | Status |
|-------|----------|--------|
| `"Hydrograf"` | `core/morphometry.py:613` | Still hardcoded |

**Priority:** LOW — `constants.py` exists, but the core modules have to be migrated to import the constants instead of literals. A purely cosmetic refactoring with no risk of error.

---

## Hardcoded Secrets (S5.3)

### S5.3a - Default password in config.py — STILL OPEN

```python
# backend/core/config.py:38
postgres_password: str = "hydro_password"

# backend/core/config.py:106 (_DEFAULT_CONFIG)
"password": "hydro_password",
```

**Problem:** The default password `hydro_password` appears in 2 places in `config.py` — in `Settings` (line 38) and in `_DEFAULT_CONFIG` for the pipeline YAML (line 106).

**Recommendation:**
- Remove the default value from `Settings`
- Require the environment variable `POSTGRES_PASSWORD`
- In `_DEFAULT_CONFIG` use a placeholder or `os.getenv()`

### S5.3b - Connection string in migrations/env.py — STILL OPEN

```python
# backend/migrations/env.py:27
database_url = os.getenv(
    "DATABASE_URL", "postgresql://hydro_user:hydro_password@localhost:5432/hydro_db"
)
```

**Problem:** A hardcoded connection string as a fallback in `os.getenv()`.

**Recommendation:**
- Require the variable `DATABASE_URL`
- Raise an error when the configuration is missing

**Priority:** MEDIUM — in a dev environment it is not a threat, but in production it can lead to the use of the default credentials when the environment variable is missing.

---

## Missing tests for scripts/ (T4.8) — PARTLY DONE

**Problem:** Most of the preprocessing scripts (`scripts/*.py`) had low test coverage.

**State of the tests (update 2026-03-01, 568 test functions, 35 files):**
- `scripts/process_dem.py` — **47 tests** (`test_process_dem.py`)
- `scripts/import_landcover.py` — **16 tests** (`test_import_landcover.py`) — NEW
- ~~`utils/sheet_finder.py` — 32 tests (`test_sheet_finder.py`)~~ REMOVED — replaced by `utils/sheet_lookup.py` (a thin wrapper around `kartograf.find_sheets_for_bbox()`, 6 tests in `test_sheet_lookup.py`), data acquisition only through Kartograf (ADR-057)
- ~~`utils/raster_utils.py` — 0% coverage~~ DONE — `test_raster_utils.py` (99%, 2026-10-25)
- `scripts/bootstrap.py` — **20 tests** (`test_bootstrap.py`) — NEW
- `scripts/download_landcover.py` — **17 tests** (`test_download_landcover.py`) — NEW
- `scripts/preprocess_precipitation.py` — **12 tests** (`test_preprocess_precipitation.py`) — NEW
- `scripts/generate_dem_overlay.py` — 0% coverage
- `scripts/generate_tiles.py` — 0% coverage
- `scripts/prepare_area.py` — 0% coverage
- `scripts/download_dem.py` — 0% coverage
- `scripts/analyze_watershed.py` — 0% coverage

**Priority:** LOW (the key core modules are covered, scripts are one-off pipeline tools)

> **Note:** A CI/CD pipeline through GitHub Actions was deployed (v0.4.0). It covers:
> lint (ruff check + format --check), tests (pytest), type-check (mypy).
> Every push and PR on `develop`/`main` runs the full validation.

---

## Documentation vs Code (C2.x) — PARTLY OUT OF DATE

**Problem:** The API documentation is out of date against the code.

**Known discrepancies (state of 2026-03-01):**
| Element | Documentation | Code | Status |
|---------|---------------|------|--------|
| `outlet_coords` | a `[lon, lat]` array | `outlet.latitude/longitude` (an `OutletInfo` object) | Probably fixed — needs an audit of ARCHITECTURE.md |
| `parameters` | a `parameters` section | `morphometry` (a `MorphometricParameters` object) | Needs an audit |
| `water_balance` | MISSING | a new section in the response | Needs an audit |
| Admin panel | MISSING | 8 `/api/admin/*` endpoints + the page `/admin` | Missing in ARCHITECTURE.md |
| SSE bootstrap | MISSING | `/api/admin/bootstrap/stream` (text/event-stream) | Missing in ARCHITECTURE.md |
| MVT tiles | Partly | 3 `/api/tiles/*` endpoints (streams, catchments, landcover) | Needs an audit |

**Action:** Update `docs/ARCHITECTURE.md` — the API endpoints section + the new patterns (admin, SSE, MVT).

**Priority:** MEDIUM

---

## ~~Database performance — bulk INSERT + indexes (P1.x)~~ DONE

**DONE (ADR-028, migration 015, session 33): the `flow_network` table was eliminated.**

The table `flow_network` (39.4M records, 58% of the pipeline time) was removed completely. The pipeline generates `stream_network` and `stream_catchments` directly from the raster. Sections P1.1 and P1.2 are out of date — they concerned the optimization of the removed table.

There is no reference to `flow_network` in any file `core/*.py` or `api/endpoints/*.py` (verified 2026-03-01).

---

## Checklist after DB migrations (preventing regressions)

**Problem:** Migration 014 added `segment_idx` to `stream_network`, but `find_nearest_stream_segment()` in `watershed_service.py` was not updated — the function still fetched `id` (the auto-increment PK) and returned it as `segment_idx`. The bug lasted 6 sessions (24-32).

**A checklist after every migration:**
1. `grep -r "TABLE_NAME" backend/` — find ALL the SQL queries to the changed table
2. Check that the new/changed column is used correctly in every query
3. Check that the mapping of the results (result.X → dict["Y"]) is consistent with the SQL SELECT
4. Run the existing integration tests — if the tests do not cover the new column, add them
5. `verify_graph()` at the API start — validation of the consistency of the data between the tables

**Priority:** HIGH — a silent bug lasted 6 sessions without being detected

---

## f-strings in logging (L1.x) — NEW

**Problem:** In 30 backend files f-strings are used in `logger.*()` calls instead of lazy formatting with `%s`. About 396 occurrences in total.

**Most often in:**
- `scripts/analyze_watershed.py` (61 occurrences)
- `scripts/prepare_area.py` (46 occurrences)
- `scripts/download_dem.py` (31 occurrences)
- `scripts/download_landcover.py` (32 occurrences)
- `utils/raster_utils.py` (20 occurrences)
- `scripts/process_dem.py` (26 occurrences)
- `scripts/bootstrap.py` (18 occurrences)
- core modules: `raster_io.py` (11), `cn_calculator.py` (9), `land_cover.py` (7), `hydrology.py` (7), `watershed.py` (5)

**Standard (DEV-12.3 of the Nogat standard):**
```python
# GOOD — lazy evaluation with %s
logger.info("Watershed area: %s km2", area_km2)

# BAD — an f-string (evaluated even if the logging level filters it out)
logger.info(f"Watershed area: {area_km2} km2")
```

**Priority:** LOW — it does not affect correctness, a minimal performance impact. The refactoring can be automated (the ruff rule `G` — flake8-logging-format).

---

## traceback.print_exc() instead of logger.exception() (L2.x) — NEW

**Problem:** In a few files `import traceback; traceback.print_exc()` is used instead of `logger.exception()`.

**Locations:**
- `core/cn_calculator.py:331-333`
- `scripts/prepare_area.py:330`
- `scripts/analyze_watershed.py:414-416, 1310-1312`

**Recommendation:** Replace with `logger.exception("Description of the error")` — it logs the traceback automatically and respects the logger configuration.

**Priority:** LOW

---

## TODO in the code (T5.x) — NEW

**Problem:** One active TODO in the production code (with .venv excluded):

| File | Line | Content | Priority |
|------|------|---------|----------|
| `core/cn_calculator.py:198` | `# TODO: Analiza pliku GeoPackage` (analyze the GeoPackage file) | The function `get_land_cover_stats()` returns an empty `{}` after downloading the GeoPackage — there is no parsing | MEDIUM |

**Context:** The function `get_land_cover_stats()` downloads the land cover file from Kartograf, but does not parse it — it returns an empty dictionary and falls back to the default values. This means that the CN calculation is based on estimated (not actual) land cover data when this code path is used.

**Priority:** MEDIUM — it affects the accuracy of the CN calculation on the Kartograf path

---

*Last update: 2026-03-01*
