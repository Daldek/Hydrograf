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
| Integracja Kartograf | ✅ Gotowy | v0.4.1 (NMT, NMPT, Orto, Land Cover, HSG, BDOT10k hydro) |
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

**Data:** 2026-02-08 (domkniecie dokumentacji: 2026-02-09)

### Co zrobiono
- Upgrade Kartograf v0.4.0 → v0.4.1 (6 commitow na `develop`):
  - `a046400` — upgrade dependency w requirements.txt
  - `f003699` — `download_landcover.py --category hydro` (BDOT10k SWRS/SWKN/SWRM/PTWP)
  - `5a26feb` — `download_dem.py --geometry` (precyzyjny wybor arkuszy z SHP/GPKG)
  - `51b830e` — `prepare_area.py --with-hydro` (automatyczny stream burning)
  - `d0fff0e` — aktualizacja referencji wersji w dokumentacji
  - `6582be4` — lint fix E501 w 3 skryptach
- E2E test na arkuszu N-33-131-C-b-2 (Tasks 7–8 OK):
  - NMT: 4 sub-sheets (1–4), po ~32 MB kazdy
  - Hydro: BDOT10k GPKG 8.1 MB
  - Stream burning + preprocessing: 20 rasterow posrednich (~444 MB)
  - process_dem z burn_streams: 2 serie (dem_mosaic 4 tiles + N-33-131-C-b-2-3 single)
- Task 9 FAILED — traverse_upstream resource exhaustion:
  - Outlet z flow_accumulation = 1.76M cells
  - Recursive CTE bez LIMIT wyczerpalo zasoby PostgreSQL
  - Mozliwe ograniczenia zasobow Docker (pamiec, CPU)
  - TCP connection established, brak wymiany banera serwera

### W trakcie
- Brak

### Nastepne kroki
1. Fix traverse_upstream — zabezpieczenia przed resource exhaustion (statement_timeout, pre-flight check, LIMIT w CTE, konfiguracja zasobow Docker)
2. CP4 — frontend z mapa Leaflet.js
3. Dlug techniczny: constants.py, hardcoded secrets

## Backlog

- [ ] Fix traverse_upstream resource exhaustion (CTE LIMIT, statement_timeout, pre-flight acc check, Docker resource config)
- [ ] CP4: Frontend z mapa (Leaflet.js + Chart.js)
- [ ] CP5: MVP — pelna integracja, deploy
- [ ] Testy scripts/ (process_dem.py, import_landcover.py — 0% coverage)
- [ ] Utworzenie backend/core/constants.py (M_PER_KM, M2_PER_KM2, CRS_*)
- [ ] Usuniecie hardcoded secrets z config.py i migrations/env.py
- [ ] CI/CD pipeline (GitHub Actions)
