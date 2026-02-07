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
- Audyt dokumentacji — 7 plikow poprawionych (ARCHITECTURE, DATA_MODEL, SCOPE, README, scripts/README, TECHNICAL_DEBT, QA_REPORT)
- E2E re-run pipeline N-33-131-C-b-2-3 z nowymi warstwami (07, 08, 09):
  - **Wyniki:** `data/results/` — 9 warstw GeoTIFF (01-09)
  - **Czas:** 198s (3.3 min), 4,917,888 komorek, max_acc=1,823,073
  - **Strahler:** max rzad 8, 490,130 komorek z rzedem
  - **Wektoryzacja:** 19,005 segmentow (641.6 km) w `stream_network`
  - **3 bugi naprawione** (ST_GeoHash WGS84, strahler floor, duplikaty geohash)
- Rozszerzenie analiz rastrowych i parametrow morfometrycznych (ADR-014)
- Rozpoznanie integracji z Kartografem v0.4.0 (rozpoczete, niezakonczone)
- **11 commitow** na galezi `develop`, 345 testow OK

### W trakcie
- Integracja z Kartografem v0.4.0 — przeprowadzono pelna analize obecnych punktow integracji:
  - `requirements.txt` — pin na v0.3.1
  - `core/cn_calculator.py` — BBox, HSGCalculator, LandCoverManager
  - `scripts/download_dem.py` — DownloadManager, GugikProvider
  - `scripts/download_landcover.py` — LandCoverManager
  - `scripts/prepare_area.py` — pipeline orchestrator
  - Nie zbadano jeszcze co dokladnie zmienilo sie w Kartograf v0.4.0

### Nastepne kroki
1. **Kartograf v0.4.0** — zbadac zmiany w nowej wersji, zaplanowac i wdrozyc aktualizacje
2. CP4 — frontend z mapa Leaflet.js
3. Dlug techniczny: constants.py, hardcoded secrets

## Backlog

- [ ] CP4: Frontend z mapa (Leaflet.js + Chart.js)
- [ ] CP5: MVP — pelna integracja, deploy
- [ ] Testy scripts/ (process_dem.py, import_landcover.py — 0% coverage)
- [ ] Utworzenie backend/core/constants.py (M_PER_KM, M2_PER_KM2, CRS_*)
- [ ] Usuniecie hardcoded secrets z config.py i migrations/env.py
- [ ] CI/CD pipeline (GitHub Actions)
