# PROGRESS — Hydrograf

## Status projektu

| Element | Status | Uwagi |
|---------|--------|-------|
| API (FastAPI + PostGIS) | ✅ Gotowy | 6 endpointow (+ tiles DEM/MVT streams): delineate, hydrograph, scenarios, profile, depressions, health |
| Wyznaczanie zlewni | ✅ Gotowy | traverse_upstream, concave hull |
| Parametry morfometryczne | ✅ Gotowy | area, slope, length, CN + 11 nowych wskaznikow |
| Generowanie hydrogramu | ✅ Gotowy | SCS-CN, 42 scenariusze |
| Preprocessing NMT | ✅ Gotowy | pyflwdir + COPY (3.8 min/arkusz), stream burning |
| Integracja Hydrolog | ✅ Gotowy | v0.5.2 |
| Integracja Kartograf | ✅ Gotowy | v0.4.1 (NMT, NMPT, Orto, Land Cover, HSG, BDOT10k hydro) |
| Integracja IMGWTools | ✅ Gotowy | v2.1.0 (opady projektowe) |
| CN calculation | ✅ Gotowy | cn_tables + cn_calculator + determine_cn() |
| Frontend | 🔶 Faza 3 gotowa | CP4 — wektorowe cieki MVT, hillshade, zaglebieniaprzed procesowanie |
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

**Data:** 2026-02-12 (sesja 3)

### Co zrobiono

- **Faza 1 — Refaktoryzacja process_dem.py (ADR-017):**
  - Podzial monolitu 2843 linii na 6 modulow `core/`: `raster_io`, `hydrology`, `morphometry_raster`, `stream_extraction`, `db_bulk`, `zonal_stats`
  - `scripts/process_dem.py` → cienki orchestrator ~700 linii z re-eksportami (backward compat)
  - Usunieto martwy kod: `fill_depressions()`, `compute_flow_direction()`, `compute_flow_accumulation()`, `process_hydrology_whitebox()`

- **Faza 2 — Optymalizacja wydajnosci:**
  - Wspolne gradienty Sobel: `_compute_gradients()` reuzywane przez slope i aspect (~12s → ~7s)
  - Numba `@njit`: `_count_upstream_and_find_headwaters()` w `stream_extraction.py` (~300s → ~10s)
  - NumPy wektoryzacja: `create_flow_network_tsv()` + `insert_records_batch_tsv()` — TSV bezposrednio do COPY (~120s → ~5s, 490MB → 200MB RAM)

- **Faza 3 — Jakosc i testy:**
  - Migracja 008: indeksy filtrujace na `depressions` (volume_m3, area_m2, max_depth_m)
  - Centralizacja `override_statement_timeout()` context manager w `db_bulk.py`
  - `generate_depressions.py` — integracja `zonal_stats` utility zamiast inline bincount
  - 85 nowych testow: `test_zonal_stats.py`, `test_raster_io.py`, `test_hydrology.py`, `test_stream_extraction.py`, `test_db_bulk.py`
  - ADR-017: dokumentacja decyzji o podziale i optymalizacji

- **Laczny wynik:** 347 testow (z 46 wczesniejszych → 347), wszystkie przechodza

### Stan bazy danych
| Tabela | Rekordy | Uwagi |
|--------|---------|-------|
| flow_network | 19,667,699 | 4 progi FA |
| stream_network | 82,624 | 100: 76587, 1000: 5461, 10000: 530, 100000: 46 |
| stream_catchments | 84,881 | 100: 76596, 1000: 7427, 10000: 779, 100000: 79 |
| depressions | 560,198 | vol=4.6M m³, max_depth=7.01 m |

### Pliki wyjsciowe
- `data/e2e_test/pipeline_results.gpkg` — 556 MB, 9 warstw
- `data/e2e_test/PIPELINE_REPORT.md` — raport pipeline
- `frontend/data/depressions.png` — overlay 1024×677 px
- `frontend/data/depressions.json` — metadane (bounds WGS84)
- `data/e2e_test/intermediates/` — 17 plikow GeoTIFF

### Znane problemy
- Frontend wymaga dalszego audytu jakosci kodu
- stream_network ma mniej segmentow niz catchments (82624 vs 84881) — roznica wynika z filtrowania duplikatow przy INSERT

### Nastepne kroki
1. Benchmark pipeline po optymalizacji (~22 min → szacowane ~6-8 min)
2. Testy integracyjne e2e endpointow (streams MVT, catchments MVT, thresholds, profile, depressions)
3. Dlug techniczny: constants.py, hardcoded secrets
4. CP5: MVP — pelna integracja, deploy

## Backlog

- [x] Fix traverse_upstream resource exhaustion (ADR-015: pre-flight check, CTE LIMIT, statement_timeout, Docker limits)
- [x] CP4 Faza 1: Frontend — mapa + zlewnia + parametry (Leaflet.js, Bootstrap 5)
- [x] CP4: Warstwa NMT — naprawiona (L.imageOverlay zamiast L.tileLayer)
- [x] CP4: Warstwa ciekow (Strahler) — L.imageOverlay z dylatacja morfologiczna → zamieniona na MVT
- [x] CP4 Faza 2: Redesign glassmorphism + Chart.js + hydrogram + profil + zaglebie
- [x] CP4 Faza 3: Wektoryzacja ciekow MVT, multi-prog FA, hillshade, zaglbienia preprocessing
- [ ] CP5: MVP — pelna integracja, deploy
- [ ] Testy scripts/ (process_dem.py, import_landcover.py — 0% coverage)
- [ ] Utworzenie backend/core/constants.py (M_PER_KM, M2_PER_KM2, CRS_*)
- [ ] Usuniecie hardcoded secrets z config.py i migrations/env.py
- [ ] Problem jezior bezodplywowych (endorheic basins) — komorki bez odplywu moga powodowac niepoprawne wyznaczanie zlewni
- [ ] CI/CD pipeline (GitHub Actions)
