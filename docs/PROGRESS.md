# PROGRESS — Hydrograf

## Status projektu

| Element | Status | Uwagi |
|---------|--------|-------|
| API (FastAPI + PostGIS) | ✅ Gotowy | 3 endpointy, v0.3.0 |
| Wyznaczanie zlewni | ✅ Gotowy | traverse_upstream, concave hull |
| Parametry morfometryczne | ✅ Gotowy | area, slope, length, CN |
| Generowanie hydrogramu | ✅ Gotowy | SCS-CN, 42 scenariusze |
| Preprocessing NMT | ✅ Gotowy | pysheds + COPY (3.8 min/arkusz) |
| Integracja Hydrolog | ✅ Gotowy | v0.5.2 |
| Integracja Kartograf | ✅ Gotowy | v0.3.1 (NMT, Land Cover, HSG) |
| Integracja IMGWTools | ✅ Gotowy | v2.1.0 (opady projektowe) |
| CN calculation | ✅ Gotowy | cn_tables + cn_calculator + determine_cn() |
| Frontend | ⏳ Zaplanowany | CP4 — mapa Leaflet.js |
| Testy scripts/ | ⏳ Zaplanowany | process_dem, import_landcover |
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
- Naprawa flowacc: cieki konczace sie w srodku rastra
  - `fill_internal_nodata_holes()` — wypelnianie wewnetrznych dziur nodata przed pysheds
  - `fix_internal_sinks()` — 3-strategiowa naprawa zlewow po pysheds (steepest/max_acc/any_valid)
  - `recompute_flow_accumulation()` — rekompozycja acc po naprawie fdir (BFS Kahn)
  - Integracja w `process_hydrology_pysheds()` (Level 1 + Level 2)
- Testy jednostkowe: 14 nowych testow w `tests/unit/test_process_dem.py`
- 293/293 testow przechodzi (14 nowych + 279 istniejacych)

### Poprzednia sesja
- Migracja na .venv-first development workflow (ADR-011)
- Test E2E pipeline: N-33-131-C-b (5 m, 1.57M komorek)
- Naprawa pyproject.toml: readme path + setuptools packages.find

### Nastepne kroki
1. CP4 — frontend z mapa Leaflet.js
2. Re-run process_dem na danych E2E i weryfikacja SQL (stream cells z downstream_id=NULL)
3. Dlug techniczny: constants.py, hardcoded secrets

## Backlog

- [ ] CP4: Frontend z mapa (Leaflet.js + Chart.js)
- [ ] CP5: MVP — pelna integracja, deploy
- [ ] Testy scripts/ (process_dem.py, import_landcover.py — 0% coverage)
- [ ] Utworzenie backend/core/constants.py (M_PER_KM, M2_PER_KM2, CRS_*)
- [ ] Usuniecie hardcoded secrets z config.py i migrations/env.py
- [ ] CI/CD pipeline (GitHub Actions)
