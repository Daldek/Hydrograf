# PROGRESS — Hydrograf

## Status projektu

| Element | Status | Uwagi |
|---------|--------|-------|
| API (FastAPI + PostGIS) | ✅ Gotowy | 3 endpointy, v0.3.0 |
| Wyznaczanie zlewni | ✅ Gotowy | traverse_upstream, concave hull |
| Parametry morfometryczne | ✅ Gotowy | area, slope, length, CN |
| Generowanie hydrogramu | ✅ Gotowy | SCS-CN, 42 scenariusze |
| Preprocessing NMT | ✅ Gotowy | pyflwdir + COPY (3.8 min/arkusz), stream burning |
| Integracja Hydrolog | ✅ Gotowy | v0.5.2 |
| Integracja Kartograf | ✅ Gotowy | v0.3.1 (NMT, Land Cover, HSG) |
| Integracja IMGWTools | ✅ Gotowy | v2.1.0 (opady projektowe) |
| CN calculation | ✅ Gotowy | cn_tables + cn_calculator + determine_cn() |
| Frontend | ⏳ Zaplanowany | CP4 — mapa Leaflet.js |
| Testy scripts/ | ⏳ W trakcie | 28 testow process_dem (burn, fill, sinks, pyflwdir) |
| Dokumentacja | ✅ Gotowy | Standaryzacja wg shared/standards (2026-02-07) |

## Checkpointy

### CP1 — Health endpoint ✅
- **Data:** 2026-01-15
- **Wersja:** v0.1.0
- **Zakres:** Setup, Docker Compose, GET /health, migracje Alembic

### CP2 — Wyznaczanie zlewni ✅
- **Data:** 2026-01-18
- **Wersja:** v0.2.0
- **Zakres:** POST /delineate-watershed, traverse_upstream, build_boundary, integracja Hydrolog

### CP3 — Generowanie hydrogramu ✅
- **Data:** 2026-01-21
- **Wersja:** v0.3.0
- **Zakres:** POST /generate-hydrograph, SCS-CN, 42 scenariusze, COPY 27x, reverse trace 330x, Land Cover, IMGWTools

### CP4 — Frontend z mapa ⏳
- **Wersja:** v0.4.0 (planowana)
- **Zakres:** Leaflet.js, Chart.js, interaktywna mapa, panel parametrow

### CP5 — MVP ⏳
- **Wersja:** v1.0.0 (planowana)
- **Zakres:** Pelna integracja frontend+backend, deploy produkcyjny

## Ostatnia sesja

**Data:** 2026-02-07

### Co zrobiono
- Wypalanie ciekow w DEM (stream burning) (ADR-013):
  - Nowa funkcja `burn_streams_into_dem()` w `scripts/process_dem.py`
  - Nowe argumenty CLI: `--burn-streams <path.gpkg>`, `--burn-depth <m>`
  - Algorytm: wczytanie GeoPackage → walidacja CRS → clip do zasiegu DEM → rasteryzacja → obnizenie DEM
  - 6 nowych testow jednostkowych w `TestBurnStreamsIntoDem`
- Usuniecie warstwy `02b_inflated`:
  - `process_hydrology_pyflwdir()` zwraca 3 wartosci zamiast 4
  - `process_hydrology_whitebox()` analogicznie
  - Parametr `inflated_dem` → `filled_dem` w `fix_internal_sinks()`
  - Usuniecie zapisu `02b_inflated.tif` z `process_dem()`
  - Aktualizacja istniejacych testow (unpacking 4→3)
- Wszystkie 28 testow przechodzi, ruff check + format OK
- E2E pipeline z stream burning: N-33-131-C-b-2-3 (55s):
  - 2,856 komorek wypalonych (1 ciek z Rzeki.gpkg, depth=5m)
  - 820 internal sinks naprawionych (85 steepest, 735 max_acc)
  - Max acc: 1,823,073, stream cells: 450,325
  - 7 plikow GeoTIFF w `data/nmt/` (01_dem → 06_streams + 02a_burned)
- **Stan:** 5 plikow zmienionych, niezacommitowane (develop)

### Poprzednia sesja
- Migracja z pysheds na pyflwdir (Deltares) (ADR-012)
- E2E re-run pipeline z pyflwdir: N-33-131-C-b-2-3
- Naprawa flowacc: `fill_internal_nodata_holes()`, `fix_internal_sinks()`

### Nastepne kroki
1. CP4 — frontend z mapa Leaflet.js
2. Dlug techniczny: constants.py, hardcoded secrets

## Backlog

- [ ] CP4: Frontend z mapa (Leaflet.js + Chart.js)
- [ ] CP5: MVP — pelna integracja, deploy
- [ ] Testy scripts/ (process_dem.py, import_landcover.py — 0% coverage)
- [ ] Utworzenie backend/core/constants.py (M_PER_KM, M2_PER_KM2, CRS_*)
- [ ] Usuniecie hardcoded secrets z config.py i migrations/env.py
- [ ] CI/CD pipeline (GitHub Actions)
