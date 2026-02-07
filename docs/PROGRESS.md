# PROGRESS — Hydrograf

## Status projektu

| Element | Status | Uwagi |
|---------|--------|-------|
| API (FastAPI + PostGIS) | ✅ Gotowy | 3 endpointy, v0.3.0 |
| Wyznaczanie zlewni | ✅ Gotowy | traverse_upstream, concave hull |
| Parametry morfometryczne | ✅ Gotowy | area, slope, length, CN |
| Generowanie hydrogramu | ✅ Gotowy | SCS-CN, 42 scenariusze |
| Preprocessing NMT | ✅ Gotowy | pyflwdir + COPY (3.8 min/arkusz) |
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
- Migracja z pysheds na pyflwdir (Deltares) (ADR-012):
  - Nowa funkcja `process_hydrology_pyflwdir()` w `scripts/process_dem.py`
  - Usunieta `process_hydrology_pysheds()` — zastapiona przez pyflwdir
  - `requirements.txt`: `pysheds>=0.4` → `pyflwdir>=0.5.8`
  - Mniej zaleznosci (3 vs 10), brak temp file, Wang & Liu 2006 algorithm
  - Zachowane: `fill_internal_nodata_holes()`, `fix_internal_sinks()` (safety net)
  - 6 nowych testow integracyjnych dla `process_hydrology_pyflwdir()`
- E2E re-run pipeline z pyflwdir: N-33-131-C-b-2-3 (1:10000, 1 arkusz)
  - 4,917,888 rekordow w flow_network (5.17M komorek rastra)
  - 489,930 stream cells (acc >= 100), max acc = 1,823,073
  - Broken stream chains: **1** (vs 233 z pysheds) — jedyny to efekt brzegowy
  - 819 internal sinks naprawionych strategia max_acc
  - Czas pipeline: 173s (pyflwdir 27s, COPY 102s) — 17% szybciej niz pysheds
  - Kroki posrednie zapisane jako GeoTIFF w `data/nmt/`
- Aktualizacja dokumentacji: pysheds → pyflwdir w 10 plikach

### Poprzednia sesja
- Naprawa flowacc: `fill_internal_nodata_holes()`, `fix_internal_sinks()`, `recompute_flow_accumulation()`
- Testy jednostkowe: 14 nowych testow w `tests/unit/test_process_dem.py`
- Migracja na .venv-first development workflow (ADR-011)

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
