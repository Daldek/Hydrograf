# PROGRESS — Hydrograf

## Status projektu

| Element | Status | Uwagi |
|---------|--------|-------|
| API (FastAPI + PostGIS) | ✅ Gotowy | 6 endpointow (+ tiles MVT streams/catchments): delineate, hydrograph, scenarios, profile, depressions, health |
| Wyznaczanie zlewni | ✅ Gotowy | traverse_upstream, concave hull |
| Parametry morfometryczne | ✅ Gotowy | area, slope, length, CN + 11 nowych wskaznikow |
| Generowanie hydrogramu | ✅ Gotowy | SCS-CN, 42 scenariusze |
| Preprocessing NMT | ✅ Gotowy | pyflwdir + COPY (3.8 min/arkusz), stream burning |
| Integracja Hydrolog | ✅ Gotowy | v0.5.2 |
| Integracja Kartograf | ✅ Gotowy | v0.4.1 (NMT, NMPT, Orto, Land Cover, HSG, BDOT10k hydro) |
| Integracja IMGWTools | ✅ Gotowy | v2.1.0 (opady projektowe) |
| CN calculation | ✅ Gotowy | cn_tables + cn_calculator + determine_cn() |
| Frontend | 🔶 Faza 3 gotowa | CP4 — wektorowe cieki MVT, hillshade, zaglbienia preprocessing |
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

**Data:** 2026-02-12 (sesja 4)

### Co zrobiono

- **Analiza pozycji PostGIS w workflow (ADR-018):**
  - Analiza: preprocessing juz 100% numpy/pyflwdir; DB tylko na koniec i w runtime
  - PostGIS nie ma kluczowych algorytmow hydrologicznych (fill, fdir, acc, strahler)
  - Zidentyfikowano 4 optymalizacje hybrydowe (C1-C4)

- **C3: Usuniety martwy kod DEM raster:**
  - Usuniety endpoint `GET /tiles/dem/` i `GET /tiles/dem/metadata` z tiles.py (lines 1-238)
  - Usuniety `scripts/import_dem_raster.py`
  - tiles.py: 427 → 204 linii

- **C2: In-memory flow graph (core/flow_graph.py):**
  - Klasa `FlowGraph`: ladowanie 19.7M komorek do numpy arrays + scipy sparse CSR
  - BFS via `scipy.sparse.csgraph.breadth_first_order` (~50-200ms vs 2-5s SQL CTE)
  - `watershed.py`: nowe `traverse_upstream()` z in-memory path + SQL fallback
  - `api/main.py`: lifespan event laduje graf przy starcie API
  - `docker-compose.yml`: API memory 1G → 3G
  - 18 nowych testow w `test_flow_graph.py`

- **C1: Pre-generacja MVT tiles (scripts/generate_tiles.py):**
  - Skrypt: export GeoJSON → tippecanoe .mbtiles → PMTiles per threshold
  - Frontend: auto-detekcja statycznych tiles z API fallback
  - `map.js`: nowe `getTileUrl()` z dynamic/static switching

- **C4: Partial index na stream_network:**
  - Migracja 009: `idx_stream_geom_dem_derived` GIST WHERE source='DEM_DERIVED'

- **Laczny wynik:** 408 testow (347 + 18 flow_graph + 43 inne), wszystkie przechodza

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
1. Instalacja tippecanoe i uruchomienie `generate_tiles.py` na danych produkcyjnych
2. Benchmark `traverse_upstream`: in-memory vs SQL na 3 rozmiarach zlewni
3. Uruchomienie `alembic upgrade head` (migracja 009: partial index)
4. Benchmark pipeline po optymalizacji (~22 min → szacowane ~6-8 min)
5. Testy integracyjne e2e endpointow
6. Dlug techniczny: constants.py, hardcoded secrets
7. CP5: MVP — pelna integracja, deploy

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
