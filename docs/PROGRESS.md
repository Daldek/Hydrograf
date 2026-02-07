# PROGRESS — Hydrograf

## Status projektu

| Element | Status | Uwagi |
|---------|--------|-------|
| API (FastAPI + PostGIS) | ✅ Gotowy | 3 endpointy, v0.3.0 |
| Wyznaczanie zlewni | ✅ Gotowy | traverse_upstream, concave hull |
| Parametry morfometryczne | ✅ Gotowy | area, slope, length, CN + 11 nowych wskaznikow |
| Generowanie hydrogramu | ✅ Gotowy | SCS-CN, 42 scenariusze |
| Preprocessing NMT | ✅ Gotowy | pyflwdir + COPY (3.8 min/arkusz), stream burning |
| Integracja Hydrolog | ✅ Gotowy | v0.5.2 |
| Integracja Kartograf | ✅ Gotowy | v0.3.1 (NMT, Land Cover, HSG) |
| Integracja IMGWTools | ✅ Gotowy | v2.1.0 (opady projektowe) |
| CN calculation | ✅ Gotowy | cn_tables + cn_calculator + determine_cn() |
| Frontend | ⏳ Zaplanowany | CP4 — mapa Leaflet.js |
| Testy scripts/ | ⏳ W trakcie | 46 testow process_dem (burn, fill, sinks, pyflwdir, aspect, TWI, Strahler) |
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
- Rozszerzenie analiz rastrowych, wektoryzacji i parametrow morfometrycznych (ADR-014):
  - **Nowe rastery:** aspect (09), TWI (08), Strahler stream order (07) w `process_dem.py`
  - **Wektoryzacja ciekow:** `vectorize_streams()` — tracing headwaters→junction, zapis do `stream_network` (source='DEM_DERIVED')
  - **Migracja 003:** `strahler_order` w `flow_network`, `upstream_area_km2`/`mean_slope_percent` w `stream_network`
  - **Wskazniki ksztaltu:** Kc, Rc, Re, Ff, mean_width_km w `calculate_shape_indices()`
  - **Wskazniki rzezbowe:** Rh, HI w `calculate_relief_indices()`
  - **Krzywa hipsometryczna:** `calculate_hypsometric_curve()` — 20 binow, opcjonalna w API
  - **Wskazniki sieci:** Dd, Fs, Rn, max_strahler w `calculate_drainage_indices()` + SQL query
  - **Integracja:** rozbudowa `build_morphometric_params()` o nowe wskazniki, opcjonalny `db` i `include_hypsometric_curve`
  - **API:** 11 nowych pol Optional w `MorphometricParameters`, `HypsometricPoint`, `hypsometric_curve` w `WatershedResponse`
  - **Flaga CLI:** `--skip-streams-vectorize`
  - **Testy:** 38 nowych (18 DEM + 21 morfometria), lacznie 345 przechodzi
  - **8 commitow** na galezi `develop`
- **Stan:** git clean, develop, 345 testow OK

### Poprzednia sesja
- Wypalanie ciekow w DEM (stream burning) (ADR-013)
- Migracja z pysheds na pyflwdir (Deltares) (ADR-012)

### Nastepne kroki
1. CP4 — frontend z mapa Leaflet.js
2. Dlug techniczny: constants.py, hardcoded secrets
3. E2E re-run pipeline z nowymi warstwami (07, 08, 09)

## Backlog

- [ ] CP4: Frontend z mapa (Leaflet.js + Chart.js)
- [ ] CP5: MVP — pelna integracja, deploy
- [ ] Testy scripts/ (process_dem.py, import_landcover.py — 0% coverage)
- [ ] Utworzenie backend/core/constants.py (M_PER_KM, M2_PER_KM2, CRS_*)
- [ ] Usuniecie hardcoded secrets z config.py i migrations/env.py
- [ ] CI/CD pipeline (GitHub Actions)
