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
| Frontend | 🔶 Faza 1 gotowa | CP4 — mapa + zlewnia + parametry (brak: hydrogram, Chart.js) |
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
- CP4 Faza 1 — Frontend (mapa + zlewnia + parametry):
  - 5 nowych plikow: index.html, style.css, api.js, map.js, app.js
  - Mapa Leaflet.js z OSM, klikniecie → wyznaczanie zlewni → polygon + ~20 parametrow
  - Panel boczny z 5 sekcjami parametrow (podstawowe, ksztalt, rzezba, siec rzeczna, ujscie)
  - Obsluga bledow (polskie komunikaty, walidacja granic Polski)
  - CDN: Leaflet 1.9.4, Bootstrap 5.3.3 (integrity hashes)
- Security hardening:
  - Naglowki nginx: CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy
  - Cache statycznych plikow (7d, immutable)
  - Porty API i DB ograniczone do 127.0.0.1 (jedyny punkt wejscia: nginx:80)
- Bugfix: Dockerfile brak `git`, docker-compose `effective_cache_size=1G` → `1GB`
- Weryfikacja: pelny stack uruchomiony, naglowki CSP potwierdzone, API proxy OK

### W trakcie
- Brak

### Nastepne kroki
1. CP4 Faza 2 — hydrogram (Chart.js, formularz parametrow, POST /api/generate-hydrograph)
2. Dlug techniczny: constants.py, hardcoded secrets
3. Testy frontend (opcjonalne)

## Backlog

- [x] Fix traverse_upstream resource exhaustion (ADR-015: pre-flight check, CTE LIMIT, statement_timeout, Docker limits)
- [x] CP4 Faza 1: Frontend — mapa + zlewnia + parametry (Leaflet.js, Bootstrap 5)
- [ ] CP4 Faza 2: Frontend — hydrogram (Chart.js, formularz)
- [ ] CP5: MVP — pelna integracja, deploy
- [ ] Testy scripts/ (process_dem.py, import_landcover.py — 0% coverage)
- [ ] Utworzenie backend/core/constants.py (M_PER_KM, M2_PER_KM2, CRS_*)
- [ ] Usuniecie hardcoded secrets z config.py i migrations/env.py
- [ ] Problem jezior bezodplywowych (endorheic basins) — komorki bez odplywu moga powodowac niepoprawne wyznaczanie zlewni
- [ ] CI/CD pipeline (GitHub Actions)
