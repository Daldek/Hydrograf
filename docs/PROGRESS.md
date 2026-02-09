# PROGRESS — Hydrograf

## Status projektu

| Element | Status | Uwagi |
|---------|--------|-------|
| API (FastAPI + PostGIS) | ✅ Gotowy | 6 endpointow (+ tiles): delineate, hydrograph, scenarios, profile, depressions, health |
| Wyznaczanie zlewni | ✅ Gotowy | traverse_upstream, concave hull |
| Parametry morfometryczne | ✅ Gotowy | area, slope, length, CN + 11 nowych wskaznikow |
| Generowanie hydrogramu | ✅ Gotowy | SCS-CN, 42 scenariusze |
| Preprocessing NMT | ✅ Gotowy | pyflwdir + COPY (3.8 min/arkusz), stream burning |
| Integracja Hydrolog | ✅ Gotowy | v0.5.2 |
| Integracja Kartograf | ✅ Gotowy | v0.4.1 (NMT, NMPT, Orto, Land Cover, HSG, BDOT10k hydro) |
| Integracja IMGWTools | ✅ Gotowy | v2.1.0 (opady projektowe) |
| CN calculation | ✅ Gotowy | cn_tables + cn_calculator + determine_cn() |
| Frontend | 🔶 Faza 2 gotowa | CP4 — redesign glassmorphism + Chart.js + hydrogram + profil + zaglebie |
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

**Data:** 2026-02-09

### Co zrobiono
- **Redesign frontend (CP4 Faza 2)** — kompletna przebudowa w 6 pakietach roboczych:
  - **WP1 — Glassmorphism:** `glass.css` (design tokens, CSS variables), `draggable.js` (pointer events), mapa 100% szerokosc, plywajacy panel wynikow (drag, minimize, close, bottom sheet mobile)
  - **WP2 — Panel warstw:** `layers.js` z akordeonowymi grupami, przelaczanie podkladow (OSM/ESRI/OpenTopoMap), opacity per-layer
  - **WP3 — Pokrycie terenu:** `LandCoverStats` schema, `get_land_cover_for_boundary()` w watershed response, `charts.js` (donut Chart.js, krzywa hipsometryczna), Chart.js 4.4.7 CDN
  - **WP4 — Profil terenu:** `profile.py` endpoint (ST_LineInterpolatePoint sampling), `profile.js` (auto ciek glowny + rysowanie polilinii), `main_stream_geojson` w watershed response
  - **WP5 — Zaglebie (blue spots):** migracja Alembic 004, `depressions.py` endpoint (filtr volume/area/bbox), `depressions.js` (overlay + suwaki SCALGO-style)
  - **WP6 — Hydrogram:** `hydrograph.js` (formularz scenariusza, wykres hydrogramu + hietogram, tabela bilansu wodnego)
  - Nginx CSP: ESRI + OpenTopoMap img-src

### W trakcie
- Brak

### Nastepne kroki
1. Wygenerowanie `depressions.png` + `depressions.json` (skrypt preprocessing)
2. Testy integracyjne e2e nowych endpointow (profile, depressions)
3. Dlug techniczny: constants.py, hardcoded secrets
4. CP5: MVP — pelna integracja, deploy

## Backlog

- [x] Fix traverse_upstream resource exhaustion (ADR-015: pre-flight check, CTE LIMIT, statement_timeout, Docker limits)
- [x] CP4 Faza 1: Frontend — mapa + zlewnia + parametry (Leaflet.js, Bootstrap 5)
- [x] CP4: Warstwa NMT — naprawiona (L.imageOverlay zamiast L.tileLayer)
- [x] CP4: Warstwa ciekow (Strahler) — L.imageOverlay z dylatacja morfologiczna
- [x] CP4 Faza 2: Redesign glassmorphism + Chart.js + hydrogram + profil + zaglebie
- [ ] CP5: MVP — pelna integracja, deploy
- [ ] Testy scripts/ (process_dem.py, import_landcover.py — 0% coverage)
- [ ] Utworzenie backend/core/constants.py (M_PER_KM, M2_PER_KM2, CRS_*)
- [ ] Usuniecie hardcoded secrets z config.py i migrations/env.py
- [ ] Problem jezior bezodplywowych (endorheic basins) — komorki bez odplywu moga powodowac niepoprawne wyznaczanie zlewni
- [ ] CI/CD pipeline (GitHub Actions)
