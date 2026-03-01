# PROGRESS — Hydrograf

## Status projektu

| Element | Status | Uwagi |
|---------|--------|-------|
| API (FastAPI + PostGIS) | ✅ Gotowy | 11 endpointow: delineate, hydrograph, scenarios, profile, depressions, select-stream, health, tiles/streams, tiles/catchments, tiles/thresholds, tiles/landcover. 672 testow. |
| Wyznaczanie zlewni | ✅ Gotowy | traverse_upstream, concave hull |
| Parametry morfometryczne | ✅ Gotowy | area, slope, length, CN + 11 nowych wskaznikow |
| Generowanie hydrogramu | ✅ Gotowy | SCS-CN, 42 scenariusze |
| Preprocessing NMT | ✅ Gotowy | pyflwdir (~12 min/8 arkuszy po eliminacji flow_network), stream burning BDOT10k |
| Integracja Hydrolog | ✅ Gotowy | v0.5.2 |
| Integracja Kartograf | ✅ Gotowy | v0.4.1 (NMT, NMPT, Orto, Land Cover, HSG, BDOT10k hydro) |
| Integracja IMGWTools | ✅ Gotowy | v2.1.0 (opady projektowe) |
| CN calculation | ✅ Gotowy | cn_tables + cn_calculator + determine_cn() |
| Frontend | 🔶 Faza 4 gotowa | CP4 — tryb wyboru obiektow, flow acc coloring, histogram, debounce, zoom fix |
| Testy scripts/ | ✅ Gotowy | 672 testow lacznie (109 nowych w sesji 47) |
| Dokumentacja | ✅ Gotowy | Audyt 16 plikow (2026-02-22), standaryzacja wg shared/standards (2026-02-07) |

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

### CP4 — Frontend z mapa ✅
- **Wersja:** v0.4.0
- **Zakres:** Leaflet.js, Chart.js, interaktywna mapa, panel parametrow, glassmorphism, MVT, select-stream, GUGiK WMTS

### CP5 — MVP ⏳
- **Wersja:** v1.0.0 (planowana)
- **Zakres:** Pelna integracja frontend+backend, deploy produkcyjny

## Ostatnia sesja

**Data:** 2026-03-01 (sesja 47)

### Co zrobiono

Realizacja 6 zadan sredniego priorytetu w trybie subagent-driven development (6 galezi feature, merge do develop). 109 nowych testow, 672 lacznie.

- **Team 1 — Testy scripts/ (83 nowe testy jednostkowe):**
  - `test_dem_color.py` (15 testow): `build_colormap()`, `compute_hillshade()` — weryfikacja numpy outputs, wymiary, zakresy wartosci
  - `test_sheet_finder.py` (32 testy): `get_sheet_1to10k_id()`, `get_sheet_1to25k_id()`, koordynaty ark. map polskich (graniczne, srodki, zakresy)
  - `test_import_landcover.py` (16 testow): `map_bdot_class()`, `extract_landcover_polygons()` — mapowanie klas BDOT10k na kategorie CN
  - `test_bootstrap.py` (20 testow): `parse_bbox()`, `StepTracker` — walidacja bbox, next/skip/retry, sekwencje krokow

- **Team 2 — Wygladzanie granic zlewni (ADR-032):**
  - `ST_SimplifyPreserveTopology(5.0)` + `ST_ChaikinSmoothing(3 iteracje)` w `merge_catchment_boundaries()` (watershed_service.py)
  - Eliminacja schodkowych krawedzi rastrowych, gladkie krzywe zamiast ortogonalnych krokow 5m
  - Tolerancja simplify w `stream_extraction.py`: `cellsize` → `2*cellsize`
  - 4 testy w `test_boundary_smoothing.py`, ADR-032

- **Team 5 — Warstwa tematyczna: pokrycie terenu (BDOT10k):**
  - Nowy endpoint MVT `/api/tiles/landcover/{z}/{x}/{y}.pbf` (tiles.py)
  - Frontend: `loadLandCoverVector()` w map.js, `addBdotOverlayEntry()` w layers.js
  - 8 kategorii kolorow, legenda, suwak przezroczystosci, lazy-load, pane z-index 260
  - 4 testy w `test_tiles_landcover.py`

- **Team 6 — Konfiguracja YAML pipeline:**
  - `load_config()`, `_deep_merge()`, `get_database_url_from_config()` w `core/config.py`
  - Szablon `config.yaml.example` (database, DEM, paths, steps, custom sources)
  - Flaga `--config` w `bootstrap.py`, `config.yaml` w `.gitignore`
  - 14 testow w `test_yaml_config.py`

- **Team 3 — Piramida kafelkow DEM + multi-directional hillshade:**
  - `compute_hillshade()` w `utils/dem_color.py`: 4 kierunki oswietlenia (NW 40%, NE 20%, SE 20%, SW 20%)
  - `generate_dem_tiles` wlaczony do `step_overlays()` w `bootstrap.py` (step 9)
  - Domyslny max zoom: 18→16, cache (pomija jesli kafelki istnieja)

- **Team 4 — Podniesienie budynkow w NMT (ADR-033):**
  - `raise_buildings_in_dem()` w `core/hydrology.py` (+5m pod obrysami budynkow z BDOT10k BUBD)
  - Nowy parametr `building_gpkg` w `process_dem()`
  - 4 testy w `test_building_raising.py`, ADR-033

- **Dokumentacja:** ADR-032, ADR-033, CHANGELOG, PROGRESS
- **Git:** 6 feature branches merged do develop, 3 konflikty CHANGELOG + 1 DECISIONS rozwiazane

### Nastepne kroki
1. CP5: MVP — pelna integracja, deploy
2. Code review CR4-CR11 (wazne)
3. Rozwazyc podwojna analize NMT (z/bez bezodplywowych) — nowy punkt backlog

### Poprzednia sesja (2026-02-25, sesja 46)

- **Flaga `--waterbody-mode` do sterowania obsluga zbiornikow wodnych (ADR-031):**
  - Nowe parametry `waterbody_mode` i `waterbody_min_area_m2` w `classify_endorheic_lakes()` (core/hydrology.py)
  - 3 tryby: `auto` (istniejace zachowanie BDOT10k), `none` (pomin klasyfikacje), sciezka do custom `.gpkg`/`.shp` (wszystkie endoreiczne)
  - `min_area_m2` filtruje male zbiorniki po powierzchni (dziala z auto i custom)
  - Parametry propagowane przez: `process_dem.py`, `bootstrap.py`, `prepare_area.py` (CLI + sygnatury funkcji)
  - 5 nowych testow w `test_lake_drain.py::TestWaterbodyMode`, 563 testow passed
  - Dokumentacja: ADR-031, scripts/README.md, PROGRESS, CHANGELOG
- **Backlog: punkt o podwojnej analizie NMT (z/bez obszarow bezodplywowych)**

### Poprzednia sesja (2026-02-24, sesja 45)

- **Usuniecie progu FA 100 m² z systemu (ADR-030):**
  - Prog 100 m² generowal ~2.5M segmentow ciekow (90% tabeli stream_network), bez odpowiednich zlewni czastkowych (usuniete w ADR-026), wydluzal pipeline o ~50%, zajmowal ~2 GB w bazie
  - Zmiana: `DEFAULT_THRESHOLDS_M2 = [100, 1000, 10000, 100000]` → `[1000, 10000, 100000]` (3 progi)
  - Domyslny `stream_threshold` zmieniony z 100 na 1000 we wszystkich skryptach i modulach core (10 plikow produkcyjnych)
  - Migracja Alembic 017: `DELETE FROM stream_network WHERE threshold_m2 = 100` + `DROP INDEX idx_stream_geom_t100/idx_catchment_geom_t100`
  - Testy zaktualizowane (4 pliki testowe), 558 testow passed
  - Dokumentacja: ADR-030, CHANGELOG, PROGRESS, README, scripts/README

### Poprzednia sesja (2026-02-24, sesja 44)

- **Fix statement_timeout dla bulk INSERT (2.5M segmentow stream):**
  - Dodano `override_statement_timeout(600s)` wrapper w `insert_stream_segments()` i `insert_catchments()` w `core/db_bulk.py` — domyslny timeout 30s byl za krotki przy 2.5M+ rekordow
- **Pelny bootstrap pipeline (10 arkuszy, 5m NMT):**
  - 18.9M komorek (4610×6059 przy 5m), mozaika VRT ze 100 plikow ASC
  - pyflwdir ukonczony w ~8 min (vs OOM przy rozdzielczosci 1m z 698M komorek)
  - DB: stream_network 2,780,056 segmentow (4 progi), stream_catchments 264,548, depressions 385,567, land_cover 101,237, precipitation 7,560, soil_hsg 121
  - Kafelki MVT wygenerowane (tippecanoe), overlay PNG (DEM + streams)
  - Calkowity czas pipeline: 2969s (~49 min)

### Poprzednia sesja (2026-02-22, sesja 42)

- **Naprawa 5 bugow UX (E1, E4, E12, E13, F2) — 3 rownolegle zespoly + 1 sekwencyjny:**
  - **E1 — Dziury na granicach zlewni:** `merge_catchment_boundaries()` w `watershed_service.py` — usunieto `ST_SnapToGrid(geom, 0.01)` (przesuwalo wierzcholki tworzac mikro-luki), zastapione buffer-debuffer (0.1m/-0.1m) ktory zamyka luki zachowujac rozmiar. `MIN_HOLE_AREA_M2`: 1000→100 m² (agresywniejsze usuwanie artefaktow merge).
  - **E4 — Outlet poza granica zlewni:** nowa funkcja `ensure_outlet_within_boundary()` w `watershed_service.py` — snap outleta do najblizszego punktu na granicy gdy wypada poza (tolerancja 1m). Zastosowanie w `select_stream.py` i `watershed.py`.
  - **E12 — Legenda HSG:** `createHsgLegend()`/`removeHsgLegend()` w `map.js` — 4 pozycje (A/B/C/D) z kolorami HSG_FILL, auto show/hide. Callbacki `onShow`/`onHide` w `addBdotOverlayEntry()` w `layers.js`.
  - **E13 — Fill brakujacych pikseli HSG:** `distance_transform_edt` nearest-neighbor fill w `step_soil_hsg()` w `bootstrap.py` — wypelnia luki w rasterze HSG na terenach zurbanizowanych przed polygonizacja.
  - **F2 — Snap-to-stream hybrydowy:** nowa funkcja `find_nearest_stream_segment_hybrid()` w `watershed_service.py` — priorytet: `ST_Contains` na `stream_catchments` (zlewnia pod kursorem), fallback: globalny `ST_Distance` snap. Zastosowanie w `select_stream.py`.
  - **Testy:** 8 nowych testow (4 outlet boundary, 2 hybrid snap, 1 HSG fill, 1 SQL inspect), 558 passed total, ruff clean
  - **4 commity** na feature branch, merge do develop

### Poprzednia sesja (2026-02-22, sesja 41)

- **CR3 — Cursor leak w `CatchmentGraph.load()` (catchment_graph.py):**
  - Named cursor `catchment_graph_load` nie byl zamykany gdy wyjatek wystapil w petli fetchmany — trzymal otwarta transakcje PostgreSQL
  - Opakowanie w `try/finally` z `cursor.close()` w `finally`
  - 550 testow passed, ruff clean

### Poprzednia sesja (2026-02-22, sesja 40)

- **CR2 — O(n²) → O(n) w `compute_downstream_links()` (stream_extraction.py):**
  - Zamiana `segments.index(seg) + 1` na `enumerate(segments, start=1)` — eliminacja ~1.6 mld porównan dla ~40k segmentów
  - 550 testów passed, ruff clean

- **CR1 — Naprawa krytycznego bugu: channel_slope z dlugosci glownego cieku (ADR-029):**
  - **Problem:** `channel_slope_m_per_m` obliczany z calkowitej dlugosci sieci rzecznej (suma WSZYSTKICH segmentow upstream) zamiast z dlugosci glownego cieku. Spadek zanizony 2-10x → czas koncentracji zawyZony → szczyt wezbrania zanizony.
  - **Rozwiazanie:** Nowa metoda `CatchmentGraph.trace_main_channel()` — traweruje upstream od outletu wg rzedu Strahlera (tie-break: max stream_length, max area). O(path_length), <1ms.
  - **Naprawione 3 miejsca:** `catchment_graph.py`, `watershed_service.py`, `select_stream.py`
  - **Testy:** 6 nowych testow (5 w test_catchment_graph.py, 1 w test_watershed_service.py), 550 passed total
  - `aggregate_stats()["stream_length_km"]` nadal zwraca sume calej sieci (drainage density)

### Poprzednia sesja (2026-02-22, sesja 39)

- **Audyt dokumentacji (16 plikow, ~35 problemow naprawionych):**
  - 5 rownoleglych subagentow: architektura+data model, PRD+SCOPE+CHANGELOG, DECISIONS+TECH_DEBT+QA, integracje+README, spojnosc krzyzowa+CLAUDE.md
  - **Krytyczne naprawy (8):**
    - `flow_graph.py`: DEPRECATED → USUNIETY (ADR-028) w CLAUDE.md, ARCHITECTURE.md, QA_REPORT.md, COMPUTATION_PIPELINE.md
    - `flow_network`: oznaczona jako USUNIETA w schematach DB (ARCHITECTURE.md, COMPUTATION_PIPELINE.md)
    - Dodano `soil_hsg.py` i `bootstrap.py` do struktur modulow (CLAUDE.md, scripts/README.md)
    - CatchmentGraph stats: ~117k/5MB → ~44k/0.5MB (CLAUDE.md, ARCHITECTURE.md)
    - ADR-024/025 oznaczone jako Superseded przez ADR-026 (DECISIONS.md)
    - Dodano `segment_idx` do schematu stream_network (ARCHITECTURE.md)
    - Dodano 7 brakujacych endpointow API do PRD.md
  - **Wazne naprawy (10):**
    - Liczba testow: 538/559 → 544 (QA_REPORT.md, PROGRESS.md)
    - Profil terenu przeniesiony z OUT do IN scope (SCOPE.md)
    - P1.x flow_network oznaczone jako ZREALIZOWANE (TECHNICAL_DEBT.md)
    - Dodano ADR-026/027/028 do tabeli QA_REPORT.md
    - Migracje 13 → 16, endpointy 7 → 10 (QA_REPORT.md)
    - Nowa sekcja soil_hsg w DATA_MODEL.md (migracja 016)
    - Dodano bootstrap.py do scripts/README.md
  - **Srednie naprawy (12):** CHANGELOG duplikat [Unreleased], daty SCOPE/HYDROLOG, Hydrolog v0.5.1→v0.5.2 w CROSS_PROJECT, uproszczenie isinstance w KARTOGRAF, CP4 emoji w README

- **Testy:** 544 passed, 0 failures (zweryfikowane pytest --collect-only)
- **1 commit** w sesji

### Poprzednia sesja (2026-02-17, sesja 37)

- **Naprawa 3 bugów po teście E2E (10 arkuszy):**
  - **Bug A — BDOT10k spacing:** `spacing_m` w `discover_teryts_for_bbox()` zmniejszony z 5000 na 2000m (gęstsza siatka punktów → lepsza detekcja małych TERYT-ów). Logi point→TERYT podniesione z DEBUG na INFO.
  - **Bug B — cieki MVT znikają przy oddaleniu:** 4-częściowa naprawa:
    - tippecanoe: `--drop-densest-as-needed` → `--coalesce-densest-as-needed` + `--simplification=10` (łączenie features zamiast usuwania)
    - Nowa funkcja `extract_mbtiles_to_pbf()` — ekstrakcja .mbtiles do statycznych `{z}/{x}/{y}.pbf` z dekompresją gzip
    - `tiles_metadata.json`: format `"mbtiles"` → `"pbf"`
    - `map.js`: `getTileUrl()` obsługa formatu `"pbf"` → `/tiles/{layer}_{threshold}/{z}/{x}/{y}.pbf`
  - **Bug C — wygładzony profil terenu:** `tension: 0.2` → `tension: 0` w charts.js (wyłączenie interpolacji Béziera)

- **Re-run BDOT10k hydro + regeneracja kafelków:**
  - Hydro: TERYT 3021 (8.0 MB) + 3064 (1.4 MB) → merged 12,321 features (bez zmian — dane 3064 faktycznie uboższe w obszarze miejskim)
  - Kafelki: 64,533 PBF tiles (4 progi × streams + catchments), 18 min (dominuje threshold 100: 390k features → 16 min tippecanoe)
  - Fix krytyczny: pliki PBF z mbtiles są gzip-compressed — dodano dekompresję w `extract_mbtiles_to_pbf()`

- **Testy:** 538 passed, 0 failures

### Poprzednia sesja (2026-02-17, sesja 36)

- **Test E2E bootstrap.py z rozszerzonym obszarem NMT (10 arkuszy):**
  - Reset bazy danych (`docker compose down -v`) + pełny bootstrap od zera
  - 10 arkuszy wejściowych → 16 arkuszy 1:10k (2 nowe arkusze 1:25k rozwinięte na 4+4)
  - Raster: 9500×8754 = 83.2M komórek (vs 43.5M poprzednio, +91%)
  - Czas całkowity: **1741.4s (~29 min)** vs 657.6s (~11 min) dla 8 arkuszy
  - NMT processing: 975.3s (sublinearny: +91% danych → +48% czasu)
  - Baza: 434,877 stream segments, 44,593 catchments, 2,239,703 depresji, 50,406 land cover, 1,050 precipitation
  - Health check OK, serwer pod http://localhost:8080
  - Raport: `data/e2e_report_sesja36.md`

### Poprzednia sesja (2026-02-17, sesja 35)

- **Naprawa 6 bugów UX (E5, E6, E9, E10, E11, F3) — 5 równoległych subagentów:**
  - **E5+E10 — Chart.js resize w ukrytych kontenerach:** `resizeChart()` w charts.js, accordion handler z 50ms setTimeout, profil terenu: d-none usunięte PRZED renderowaniem, canvas owinięty w `.chart-container`
  - **E6 — Liquid glass na panelu profilu:** dodane tokeny CSS (`--liquid-bg`, `--liquid-blur`, `--liquid-border`, `--liquid-shadow`, `--liquid-highlight`) do `#profile-panel` w style.css
  - **E9 — Usunięcie wpisu "Zlewnia" z panelu warstw:** ~101 linii usunięte z layers.js (zmienne, blok budowy, eksport), 3 wywołania `notifyWatershedChanged()` usunięte z app.js
  - **E11 — Dyskretna skala kolorów zagłębień:** YlOrRd paleta (żółty→pomarańczowy→czerwony) z 5 progami wg `volume_m3` (<1, <10, <100, <1000, ≥1000 m³) w depressions.js
  - **F3 — Fallback progu 100→1000 w select-stream:** automatyczna eskalacja progu gdy `threshold < DEFAULT_THRESHOLD_M2`, nowe pole `info_message` w `SelectStreamResponse`, banner informacyjny w app.js
  - Wszystkie 538 testów przechodzą, ruff clean

- **Naprawa krytycznego bugu CDN:**
  - Hash integralności Chart.js 4.4.7 był nieprawidłowy — blokował ładowanie WSZYSTKICH wykresów (profil terenu, pokrycie terenu, hipsometria)
  - Naprawiony hash w index.html, pozostałe 4 CDN hashe (Leaflet, Bootstrap CSS/JS, VectorGrid) zweryfikowane OK

- **Skrypt weryfikacji hashów SRI (`scripts/verify_cdn_hashes.sh`):**
  - Parsuje index.html (perl), pobiera zasoby CDN, oblicza hash (openssl), porównuje z deklarowanym
  - Tryb `--fix` automatycznie naprawia nieprawidłowe hashe
  - Exit code 1 przy niezgodności — gotowy do CI

- **Integracja CDN w bootstrap.py (krok 1d):**
  - Weryfikacja hashów SRI jako część kroku infrastruktury
  - Warning-only (nie blokuje pipeline), loguje "CDN HASH MISMATCH" przy niezgodności

- **9 commitów** w sesji, branch `develop`

### Poprzednia sesja (2026-02-17, sesja 34)

- **Reset bazy danych + pelny bootstrap (8 arkuszy NMT):**
  - `docker compose down -v` → pelny bootstrap z `scripts/bootstrap.py --sheets ...`
  - Czas calkowity: 657.6s (~11 min)
  - Wyniki: 39.4M cells, 220944 stream segments, 50406 land cover, 630 precipitation, 1125699 depressions
  - Serwer uruchomiony: http://localhost:8080, health OK

- **Instalacja tippecanoe via pip + poprawki skryptow:**
  - `pip install tippecanoe` (v2.72.0) — zainstalowany w `.venv/bin/`
  - `bootstrap.py`: szuka tippecanoe w `.venv/bin/` oprócz systemowego PATH
  - `generate_tiles.py`: szuka tippecanoe w `.venv/bin/`, przekazuje pelna sciezke do `run_tippecanoe()`, pomija puste eksporty (0 features — np. catchments dla progu 100 m² zgodnie z ADR-026)

- **Generacja kafelkow MVT (tippecanoe):**
  - 4 progi: 100, 1000, 10000, 100000 m²
  - 7 plikow `.mbtiles` (streams × 4, catchments × 3 — brak catchments dla progu 100)
  - Czas: 95.2s

### Poprzednia sesja (2026-02-17, sesja 33)

- **Eliminacja tabeli flow_network (ADR-028, migracja 015):**
  - Tabela `flow_network` przechowywala ~39.4M rekordow (dane kazdego piksela DEM) — zadne API endpoint nie czytalo z niej w runtime
  - Migracja 015: `DROP TABLE flow_network`
  - Pipeline DEM pomija krok INSERT flow_network — oszczednosc ~17 min (58% czasu pipeline)
  - Pipeline 8 arkuszy: ~29 min → ~12 min

- **Usuniecie ~1000 linii martwego kodu:**
  - `core/flow_graph.py` — caly modul (~360 linii, DEPRECATED od ADR-022)
  - `core/db_bulk.py` — 4 funkcje flow_network: `create_flow_network_tsv()`, `create_flow_network_records()`, `insert_records_batch()`, `insert_records_batch_tsv()` (~580 linii)
  - `core/watershed.py` — 5 legacy CLI functions: `find_nearest_stream()`, `check_watershed_size()`, `traverse_upstream()`, `_traverse_upstream_inmemory()`, `_traverse_upstream_sql()`
  - ~43 testow powiazanych z flow_network/flow_graph

- **Aktualizacja 4 skryptow CLI** z zapytaniami SQL na flow_network:
  - `analyze_watershed.py`, `e2e_task9.py`, `export_pipeline_gpkg.py`, `export_task9_gpkg.py` — przepisane na stream_network

- **Testy:** 538 testow (bylo 581), 0 failures, ruff clean
- **8 commitow** w sesji

### Poprzednia sesja (2026-02-17, sesja 32)

- **Naprawa blednej selekcji zlewni (ADR-027, 6 plikow, 581 testow):**
  - **Przyczyna glowna (2 bugi):**
    1. `find_nearest_stream_segment()` uzywala `id` (auto-increment PK) zamiast `segment_idx` — lookup w grafie zawisze zwracal None
    2. `ST_Contains` na `stream_catchments` moze trafic w sasiednia zlewnie przy kliknieciu blisko konfluencji
  - **Naprawa:** snap-to-stream (`ST_Distance` na `stream_network`) → `lookup_by_segment_idx()` O(1) → BFS, z ST_Contains jako fallback
  - **Nowe metody CatchmentGraph:** `lookup_by_segment_idx()`, `verify_graph()` (diagnostyka przy starcie)
  - **Usuniety martwy kod:** `find_stream_catchment_at_point()` w `watershed_service.py`
  - **Testy:** 581 testow, 0 failures, ruff clean

- **Reset bazy danych + pelny bootstrap:**
  - `docker compose down -v` → `docker compose up -d db`
  - `bootstrap.py --sheets` z istniejacymi 8 arkuszami NMT (~30 min)
  - Dane: flow_network 39.4M, stream_network ~221k (4 progi), stream_catchments ~22.6k (3 progi)

### Poprzednia sesja (2026-02-16, sesja 31)

- **Stream burning w bootstrap.py (rozszerzenie kroku 3):**
  - `step_process_dem()` pobiera teraz hydro BDOT10k (per-TERYT) i scala pliki przed przetwarzaniem DEM
  - Nowa funkcja `merge_hydro_gpkgs()` w `download_landcover.py` — scala multi-layer GeoPackage z zachowaniem warstw (SWRS, SWKN, SWRM, PTWP)
  - Graceful degradation: jesli download/merge fail → process_dem bez burning
  - Pipeline re-run: 1763s (~29.4 min), 706143 komorek wypalonych, 12321 features hydro z 2 powiatow (3021, 3064)
  - 5 nowych testow `merge_hydro_gpkgs`, lacznie 577 testow, 0 failures
  - Udokumentowane waskie gardla w `TECHNICAL_DEBT.md` (P1.x): bulk INSERT 58% czasu, pyflwdir 16%

- **`scripts/bootstrap.py` — jednokomendowy setup srodowiska (~460 linii):**
  - Nowy skrypt orkiestratora: 9 krokow pipeline'u od zera do dzialajacego systemu
  - Dwa tryby wejscia: `--bbox "min_lon,min_lat,max_lon,max_lat"` lub `--sheets GODLO1 GODLO2`
  - 7 flag `--skip-*`, `--dry-run`, `--port`

- **`docker-compose.yml` — konfigurowalny port nginx:**
  - `"8080:80"` → `"${HYDROGRAF_PORT:-8080}:80"`

- **Testy:** 560 testow, 0 failures, ruff clean.

### Poprzednia sesja (2026-02-16, sesja 30)

- **Auto-selekcja dużych zlewni w trybie "Wygeneruj":**
  - Gdy powierzchnia zlewni > 10 000 m² (0.01 km²), endpoint automatycznie przełącza wyświetlanie na styl selekcji (pomarańczowa granica + podświetlone zlewnie cząstkowe MVT) z banerem informacyjnym.
  - Nowa stała `DELINEATION_MAX_AREA_M2 = 10_000` w `core/constants.py`.
  - 4 nowe pola w `DelineateResponse`: `auto_selected`, `upstream_segment_indices`, `display_threshold_m2`, `info_message`.
  - Kaskadowe progi merge (>500 segmentów) w `watershed.py` — wzorzec z `select_stream.py`.
  - Banner `#panel-auto-select-info` w `index.html`, obsługa `auto_selected` w `app.js` (`onWatershedClick`, `closeResults`).
  - 3 nowe testy integracyjne: small area (5000 m²) → not auto-selected, large area (50000 m²) → auto-selected, boundary (10000 m²) → not auto-selected (≤ not <).
  - **Testy:** 560 testów, 0 failures, ruff clean.

### Poprzednia sesja (2026-02-16, sesja 29)

- **Naprawa niespójnych przebiegów cieków między zoomami MVT:**
  - **Przyczyna:** `ST_SimplifyPreserveTopology` z tolerancjami per-zoom (1-10m) tworzył dyskretne skoki w kształcie geometrii. 78% segmentów stawało się prostymi liniami (2 punkty) przy tolerancji 10m (zoomy 0-5), a przy 1m (zoomy 10+) miały 13+ punktów. Powodowało to co najmniej 3 wizualnie różne wersje sieci rzecznej.
  - **Rozwiązanie:** usunięcie jawnej `ST_SimplifyPreserveTopology` z zapytań MVT (streams + catchments). Geometria jest pre-simplifikowana do 1m w pipeline, a `ST_AsMVTGeom` kwantyzuje współrzędne do siatki 4096×4096 kafla — płynna redukcja szczegółów bez skoków.
  - **Efekty:** spójne przebiegi cieków na wszystkich zoomach, 2.5× szybsze generowanie kafli (355→139ms na zoom 8, 10k features), prostszy kod (usunięta tabela `_MVT_SIMPLIFY_TOLERANCE`).
  - **Testy:** 557 testów, 0 failures, ruff clean.

### Poprzednia sesja (2026-02-16, sesja 28)

- **Redesign selekcji zlewni cząstkowych (ADR-026):**
  - Selekcja oparta o poligon (`ST_Contains`), usunięcie progu 100 m², migracja 014 (`segment_idx`), uproszczenie API, pipeline re-run (801.6s).

- **Naprawa wizualizacji MVT (częściowa):**
  - `ST_Simplify` → `ST_SimplifyPreserveTopology`, tolerancje ograniczone do max 10m.

### Poprzednia sesja (2026-02-16, sesja 27)

- **Diagnostyka i ochrona przed "zielonymi" zlewniami (DO WERYFIKACJI):**
  - Problem: po selekcji cieku pojawiaja sie zielone zlewnie czastkowe o duzej powierzchni, niezwiazane z zaznaczeniem. Bug na progach 10000 i 100000 m².
  - Hipoteza: `segment_idx` naklada sie miedzy progami (threshold 100 → [1..105492], threshold 10000 → [1..1101]). Jesli indeksy trafia na MVT z innego progu — zielone zlewnie "losowe".
  - Implementacja: `display_threshold_m2` w response, walidacja progu w highlight, tooltip diagnostyczny
  - 559 testow, 0 failures, ruff clean

### Poprzednia sesja (2026-02-16, sesja 26)

- **F2 — warunkowy prog selekcji cieku (ADR-025):**
  - Snap-to-stream i BFS na progu wyswietlanym na mapie (1000, 10000, 100000) zamiast zawsze na progu 100 m²
  - Fine-BFS (ADR-024) aktywny tylko gdy display_threshold==100
  - Eliminuje snap do niewidocznych doplywow przy grubszych progach
  - Rename: `fine_threshold` → `bfs_threshold`, `fine_segment_idxs` → `bfs_segment_idxs`
  - 2 nowe testy + 1 zaktualizowany (559 testow lacznie, 0 failures)
  - Dokumentacja: ADR-025, CHANGELOG

### Poprzednia sesja (2026-02-16, sesja 25)

- **F1 — precyzyjna selekcja cieku — kontynuacja:**
  - **Re-run pipeline:** 105492 segmentow (prog 100, bylo 78829, +34%), lacznie 117228 across 4 progi. CatchmentGraph: 117228 nodes, 5.1 MB RAM, 1.5s startup.
  - **Fix wydajnosci duzych zlewni:** kaskadowe progi merge (100→1000→10000→100000) gdy fine segments >500 — zapobiega timeout ST_UnaryUnion na 30s.
  - **Weryfikacja F1:** dwa klikniecia na tym samym cieku daja rozne wyniki (precyzja miedzykonfluencyjna). Response time: 0.5-1.1s.
  - **Weryfikacja duzych zlewni:** threshold 100000 → 8.23 km², 73 segs, 18s (bylo timeout).

### Poprzednia sesja (2026-02-15, sesja 24)

- **F1 — precyzyjna selekcja cieku (ADR-024):**
  - **Czesc A (preprocessing):** dodano warunek konfluencji w `vectorize_streams()` — segmenty lamia sie przy kazdym polaczeniu doplywow, nie tylko przy zmianie Strahlera.
  - **Czesc B (query):** BFS na progu 100 m² zamiast display threshold. Nowe funkcje: `find_stream_catchment_at_point()` (snap-to-stream), `map_boundary_to_display_segments()` (mapowanie fine→display). Optymalizacja SQL: `ST_UnaryUnion + ST_SnapToGrid`. Fallback do display threshold.
  - **Testy:** 557 testow, 0 failures (+3 nowe: confluence segmentation, multi-threshold BFS, fallback)
  - **Dokumentacja:** ADR-024, CHANGELOG, PROGRESS

### Poprzednia sesja (2026-02-15, sesja 23)

- **Liquid glass:**
  - Panele "Warstwy" i "Parametry zlewni" + toggle buttons + legendy uzywaja stylu liquid glass
  - Nowe tokeny CSS: `--liquid-bg`, `--liquid-border`, `--liquid-blur`, `--liquid-shadow`, `--liquid-highlight`
  - Kolory czcionek zmienione na czarne (`--color-text: #000`, `--color-text-secondary: #1d1d1f`)
  - Czarne czcionki na osiach i etykietach wykresow Chart.js

- **Panel wynikow — zmiany UX:**
  - Panel na pelna wysokosc okna (`top: 0; bottom: 0`), zaokraglone rogi tylko po lewej
  - Akordeony domyslnie zwiniete (poza "Parametry podstawowe")
  - "Punkt ujsciowy" przeniesiony do "Parametry podstawowe" (ujscie φ, λ, H)
  - Usuniety akordeon `acc-outlet`

- **Tryby klikniecia:**
  - Nowy tryb "Przegladanie" (domyslny) — klikniecie nic nie robi, kursor `grab`
  - Zmienione nazwy: "Wygeneruj zlewnię", "Wybierz zlewnię", "Profil terenu"
  - Kolejnosc: Przegladanie → Wybierz → Wygeneruj → Profil
  - Przelaczanie trybow nie czysci warstw z mapy
  - Anulowanie rysowania profilu przy zmianie trybu

- **Warstwy domyslnie wysunięte** (bez klasy `layers-hidden` na starcie)

- **Bug E4 udokumentowany:** punkt ujsciowy poza granica zlewni (oba tryby)

### Poprzednia sesja (2026-02-15, sesja 22)

- **E3 — Panel wynikow dokowany z prawej (fix zoom overlap):**
  - `#results-panel` przeniesiony wewnatrz `#map-wrapper` z `position: absolute; right: 0`
  - Slide in/out z CSS transition (`translateX(400px)`, `opacity`)
  - Przycisk toggle (chevron `‹`/`›`) przy krawedzi panelu — zachowanie jak panel "Warstwy"
  - Kontrolki zoom Leaflet przesuwaja sie automatycznie (`#map-wrapper.results-visible .leaflet-bottom.leaflet-right { right: 390px }`)
  - Usuniety draggable na panelu wynikow, usuniety `#results-restore`, usuniety przycisk minimize
  - Ikony: layers toggle `☰` → `›`/`‹` (chevron kierunkowy)
  - Escape: pojedynczy = zwin panel (overlay zostaje), podwojny (400ms) = zamknij jak `×`
  - Mobile: bottom-sheet zachowany, toggle btn ukryty
  - Zoom control przeniesiony z `topright` na `bottomright`

- **Wynik:** 449 testow unit, 0 failures

### Poprzednia sesja (2026-02-15, sesja 21)

- **Naprawa 4 bugow panelu warstw i danych (G1-G4):**
  - **G1:** Wysokosc histogramu `.chart-container` zwiekszona z 160px do 240px
  - **G2:** Import pokrycia terenu BDOT10k — naprawiono parsowanie nazw warstw GeoPackage (OT_PTLZ_A → PTLZ); 38560 rekordow z 12 warstw, 7 kategorii (las, grunt_orny, zabudowa_mieszkaniowa, woda, droga, inny, laka)
  - **G3:** "Podklady kartograficzne" przeniesione na dol panelu warstw (nowa kolejnosc: Warstwy podkladowe → Wyniki analiz → Podklady kartograficzne)
  - **G4a:** Zaglbienia przeniesione do grupy "Warstwy podkladowe" (nowy kontener `#overlay-group-entries`)
  - **G4b:** Checkbox zlewni — auto-check tylko przy pierwszym wykryciu; flaga `_watershedFirstDetection` resetowana po usunieciu warstwy

- **Krzywa hipsometryczna:** sekcja "Rzezba terenu" zmieniona z histogramu na krzywa hipsometryczna — os Y: wysokosc [m n.p.m.], os X: % powierzchni powyzej (0–100, co 20)

- **Wynik:** 550 testow, 0 failures, 6 commitow

### Poprzednia sesja (2026-02-15, sesja 20)

- **Naprawa 4 bugow profilu terenu (D1-D4):**
  - D2: Guard duplikatow dblclick, styl linii solid
  - D1: showProfileError z canvasId, panel pokazywany w catch
  - D3: cancelDrawing czysci profileLine, re-aktywacja rysowania
  - D4: Usuniety acc-profile, btn-profile-auto
- **Interaktywny profil terenu:** hover → marker na mapie + crosshair
- **DEM w Docker:** volume mount data/e2e_test → /data/dem
- **Wynik:** 550 testow, 0 failures, 6 commitow

### Poprzednia sesja (2026-02-14, sesja 19)

#### Co zrobiono

- **Profil terenu jako osobny panel + UX drawing (plan z sesji 19):**
  - Nowy floating panel `#profile-panel` (left: 16px, bottom: 16px, 420px, z-index 1050) — niezalezny od panelu "Parametry zlewni"
  - `profile.js` refaktor: `activateDrawProfile()` renderuje w `#chart-profile-standalone`, pokazuje `#profile-panel`; dodana `hideProfilePanel()`
  - `map.js`: nowa funkcja `undoLastVertex()` — cofanie ostatniego wierzcholka (Backspace)
  - Banner rysowania zaktualizowany: "Klik = wierzcholek, Podwojny klik = zakoncz, Backspace = cofnij, Esc = anuluj"
  - Chart.js fix: canvasy (#chart-hypsometric, #chart-landcover, #chart-profile) owiniete w `.chart-container` (height: 160px) — zapobiega rozciaganiu wykresow
  - `app.js`: init close/draggable na `#profile-panel`, `hideProfilePanel()` przy zmianie trybu i zamknieciu panelu wynikow
  - Mobile responsive: `#profile-panel` fullwidth na ekranach < 768px
  - **Wynik:** 550 testow, 0 failures

- **Zapisano 13 nowych bugów/uwag do naprawy (D1-D4, E1-E3, F1, G1-G4)**

### Poprzednia sesja (2026-02-14, sesja 18)

- **Naprawa 10 bugów (zgłoszenie 2026-02-14, A1-A5, B1-B4, C1):**
  - **A1:** Przycisk "×" w panelu wyników czyści warstwę zlewni z mapy (clearWatershed + clearSelectionBoundary + clearCatchmentHighlights + clearProfileLine)
  - **A2:** Domyślny min_area zagłębień 0 → 100 m² (API + frontend)
  - **A3:** Domyślny próg FA 10000 → 100000 m² (tiles.py + app.js + layers.js)
  - **A4:** Wysokość canvas histogramu 20 → 140px
  - **A5:** Zbiorniki BDOT ukryte przy opacity=0 (weight + fillOpacity + opacity)
  - **B1:** Inline alert-warning zamiast alert() gdy DEM niedostępny
  - **B2:** Nowy przycisk "Profil" w toolbar — rysowanie profilu terenu niezależne od zlewni
  - **B3:** Sekcja hydrogramu ukryta z badge "w przygotowaniu"
  - **B4:** Nowa metoda traverse_to_confluence w CatchmentGraph + parametr to_confluence w select-stream
  - **C1:** Usunięcie cell_count z WatershedResponse, 3 endpointów, frontendu i dokumentacji
  - **Wynik:** 550 testów, 0 failures, ruff check+format clean, 10 commitów

### Poprzednia sesja (2026-02-14, sesja 17)

- **Eliminacja FlowGraph z runtime API (ADR-022, 10 faz):**
  - **Faza 1:** Nowy modul `core/watershed_service.py` (~400 linii) — reużywalne funkcje wyekstrahowane z `select_stream.py`: find_nearest_stream_segment, merge_catchment_boundaries, get_segment_outlet, compute_watershed_length, get_main_stream_geojson, build_morph_dict_from_graph
  - **Faza 2:** Rewrite `watershed.py` — FlowGraph BFS (19.7M) → CatchmentGraph BFS (87k) + watershed_service
  - **Faza 3:** Rewrite `hydrograph.py` — j.w., morph_dict → WatershedParameters.from_dict()
  - **Faza 4:** Refactor `select_stream.py` — 6 lokalnych funkcji zastąpionych importami z watershed_service
  - **Faza 5:** Rewrite `profile.py` — SQL LATERAL JOIN → rasterio DEM sampling + pyproj
  - **Faza 6:** Usunięcie FlowGraph z `api/main.py` lifespan
  - **Faza 7:** Cleanup `watershed.py` (legacy functions zachowane dla CLI), deprecation notice w `flow_graph.py`
  - **Faza 8:** 29 nowych testów (25 unit + 4 integracyjne) — łącznie 548 testów, 0 failures
  - **Faza 9:** Docker config — API memory 3G → 512M, DEM_PATH env var
  - **Faza 10:** Dokumentacja — ADR-022, CHANGELOG, PROGRESS
  - **Efekty:** RAM -96% (1.1 GB → 40 MB), startup -97% (93s → 3s), flow_network runtime queries: 0, main_stream_geojson naprawiony

- **Audyt dokumentacji post-ADR-022 (4 pliki):**
  - ARCHITECTURE.md v1.5: diagram "Flow Graph" → "Catchment Graph", +watershed_service.py, przepływ danych ADR-022, testy 548
  - COMPUTATION_PIPELINE.md v1.2: flow_graph DEPRECATED, Faza 2/6 zaktualizowane
  - CLAUDE.md: +watershed_service.py, flow_graph.py DEPRECATED
  - QA_REPORT.md: warning 519 → 548 testów, +ADR-022

### Poprzednia sesja (2026-02-13, sesja 16)

- **Audyt dokumentacji — spojnosc, aktualnosc, wzajemne odwolania (9 plikow):**
  - ARCHITECTURE.md: `parameters.py`→`morphometry.py`, zaktualizowane sygnatury, +catchment_graph.py/constants.py, v1.4
  - CLAUDE.md: +2 moduly core, +2 endpointy, +5 skryptow w drzewie
  - DATA_MODEL.md: +migracja 013, fix nazwy 010
  - SCOPE.md: status zatwierdzony, data 2026-02-13
  - QA_REPORT.md: nota deprecation (175→519 testow, CORS fixed, CI/CD)
  - TECHNICAL_DEBT.md: constants.py ZREALIZOWANE, +CI/CD, data
  - COMPUTATION_PIPELINE.md: +faza CatchmentGraph (ADR-021), LOC fix (~2800→~700)
  - README.md: CP3→CP4, +6 endpointow w tabeli
  - PROGRESS.md: 7→10 endpointow
  - **Wynik:** 9 plikow, 151 linii dodanych / 45 usunietych, 7/7 weryfikacji grep

- **Wdrozenie aktualizacji:**
  - Migracja 013 zastosowana (`alembic upgrade head`)
  - Obraz API przebudowany (`docker compose build api`)
  - Kontener zrestartowany, CatchmentGraph zaladowany (86913 nodes, 3.0s)
  - Weryfikacja: health OK, scenarios OK, thresholds OK

### Poprzednia sesja (2026-02-13, sesja 15)

- **Audyt QA — Wydajnosc i Efektywnosc Workflow (4 fazy):**
  - **Faza 1 (Quick Wins):** LATERAL JOIN w profile.py, Cache-Control headers na 4 endpointach, dedup `_compute_shape_indices()` (-30 LOC), SessionLocal.configure() jednorazowo
  - **Faza 2 (Backend Perf):** TTLCache na traverse_upstream (128 wpisow, 1h), migracja 013 partial GiST index `WHERE is_stream=TRUE`, PG tuning (effective_cache_size=1536MB, random_page_cost=1.1, jit=off), land cover query merge w hydrograph.py
  - **Faza 3 (Frontend Perf):** Client-side Map cache w api.js (50 wpisow, 5min TTL), defer na 13 script tagow + preconnect CDN, force-cache na DEM metadata fetch
  - **Faza 4 (DevOps):** GitHub Actions CI (lint+test+security), pre-commit hooks (ruff+format), structured logging (structlog JSON + request_id middleware), core/constants.py, naprawiono 19 ruff warnings, ruff format 19 plikow
  - **Wynik:** 519 testow, 0 failures, ruff check+format clean, 4 commity

### Poprzednia sesja (2026-02-13, sesja 14)

- **Graf zlewni czastkowych — ADR-021 (7 faz, caly plan zaimplementowany):**
  - **Faza 1:** Migracja 012 — 6 nowych kolumn w `stream_catchments` (downstream_segment_idx, elevation_min/max, perimeter_km, stream_length_km, elev_histogram JSONB)
  - **Faza 2:** `compute_downstream_links()` w stream_extraction.py — follow fdir z outlet cell kazdego segmentu, `_outlet_rc` w vectorize_streams()
  - **Faza 3:** `zonal_min()` + `zonal_elevation_histogram()` w zonal_stats.py, rozszerzenie `polygonize_subcatchments()` o nowe stats
  - **Faza 4:** Rozszerzenie `insert_catchments()` w db_bulk.py o 6 nowych kolumn + JSONB histogram
  - **Faza 5:** Nowy modul `core/catchment_graph.py` — in-memory graf (~87k wezlow, ~8 MB), BFS via scipy sparse, agregacja stats z numpy arrays, krzywa hipsometryczna z mergowania histogramow
  - **Faza 6:** Calkowity rewrite `select_stream.py` — graf zlewni zamiast rastra, ST_Union boundary, derived indices (Kc, Rc, Re, Ff)
  - **Faza 7:** 19 testow catchment_graph, 7 testow zonal_stats, 8 testow integracyjnych select-stream (przepisane), dokumentacja (DATA_MODEL, DECISIONS, CHANGELOG)
  - **Wynik:** 519 testow, 0 failures, lint clean

- **Re-run pipeline + deploy CatchmentGraph:**
  - Migracja 012 zastosowana (`alembic upgrade head`)
  - Pipeline re-run: 1114s (~18.5 min), 86913 zlewni z pelnym zestawem danych
  - Nowe kolumny: downstream_segment_idx 99%, elevation/perimeter/histogram 100%
  - Obraz API przebudowany (`docker compose build api`), kontener zrestartowany
  - CatchmentGraph zaladowany: 86913 nodes, 86178 edges, 3.0s, 3.8 MB RAM
  - Weryfikacja `select-stream`: 16 upstream segments, area 0.26 km², pelna morfometria + krzywa hipsometryczna (21 pkt)

### Poprzednia sesja (2026-02-13, sesja 13b)

- **Audyt i poprawki frontend (13 taskow, 3 fazy)**

### Poprzednia sesja (2026-02-13, sesja 13)

- **Naprawa 4 krytycznych bledow (post-e2e):**
  1. **Stream burning (KRYTYCZNY):** `hydrology.py` `burn_streams_into_dem()` — wykrywanie multi-layer GeoPackage via `fiona.listlayers()`, ladowanie warstw liniowych (SWRS, SWKN, SWRM) + poligonowych (PTWP), `pd.concat`. Wczesniej czytalo domyslna warstwe (jeziora poligonowe) zamiast ciekow liniowych.
  2. **select-stream 500:** `select_stream.py` — `segment_idx` → `id` w SQL SELECT (kolumna nie istniala w `stream_network`)
  3. **Wydajnosc MVT:** GZip middleware (`GZipMiddleware, minimum_size=500`), migracja 011 (czesciowe indeksy GIST per threshold), cache TTL 86400s, `minZoom: 12` dla catchments, nginx `gzip_types` protobuf
  4. **UI diagnostyka:** `console.warn` w BDOT catch blocks, CSP `img-src` += `mapy.geoportal.gov.pl`

- **Re-run pipeline z poprawionym stream burning:**
  - process_dem: 927.6s, 19.67M records, 4 warstwy BDOT10k zaladowane (10726 features), 1,073,455 cells burned
  - max_acc: 8,846,427 (vs 3.45M przed — poprawa o 156% dzieki poprawnemu stream burning)
  - generate_depressions: 602,092 zaglebie w 59.9s
  - export_pipeline_gpkg: 9 warstw, 777,455 features
  - generate_dem_tiles: 267 kafelkow, 15.5 MB
  - BDOT GeoJSON: 3529 jezior, 7197 ciekow

- **Weryfikacja endpointow:**
  - `/health` — 200, `select-stream` — 200 (brak 500), MVT streams — 44 KB → 26 KB z GZip (41%), catchments — 394 KB → 146 KB (64%)

- **Laczny wynik:** 493 testy, wszystkie przechodza

### Poprzednia sesja (2026-02-13, sesja 12)

- **Select-stream z pelnymi statystykami zlewni, siec rzeczna BDOT10k, naprawy UI**
- **8 testow integracyjnych select-stream**
- 492 testy

### Poprzednia sesja (2026-02-13, sesja 11)

- **DEM tile pyramid (`scripts/generate_dem_tiles.py`):**
  - Nowy skrypt: koloryzacja DEM + hillshade → RGBA GeoTIFF w EPSG:3857 → `gdal2tiles.py --xyz`
  - Zoom 8–18, nearest-neighbor (ostre krawedzie komorek 1m przy duzym zoomie)
  - Metadane JSON (bounds, zoom range, elevation stats)
  - Argumenty: `--input`, `--output-dir`, `--meta`, `--source-crs`, `--min-zoom`, `--max-zoom`, `--no-hillshade`

- **Wspolny modul `utils/dem_color.py`:**
  - Wyekstrahowane z `generate_dem_overlay.py`: `COLOR_STOPS`, `build_colormap()`, `compute_hillshade()`
  - Stary skrypt zrefaktoryzowany na importy — backwards compatible

- **Frontend — custom panes + L.tileLayer:**
  - Custom panes z-index: demPane (250) → catchmentsPane (300) → streamsPane (350)
  - `loadDemOverlay()`: L.tileLayer z `/data/dem_tiles/{z}/{x}/{y}.png`, fallback na L.imageOverlay
  - MVT layers: `pane: 'streamsPane'` i `pane: 'catchmentsPane'`

- **Laczny wynik:** 484 testy (teraz 492), wszystkie przechodza

### Poprzednia sesja (2026-02-12, sesja 10)

- **Frontend — 7 poprawek UX (przeprojektowanie, sesja 9):**
  - **Zoom controls** przeniesione do topright (nie koliduja z layers panel)
  - **Przezroczystosc zlewni czastkowych** naprawiona (fillOpacity=1.0 initial, bez ×0.5)
  - **Histogram wysokosci** zamiast krzywej hipsometrycznej — `renderElevationHistogram()` w charts.js
  - **Cieki kolorowane po flow accumulation** — gradient log10 (upstream_area_km2) zamiast Strahlera
  - **Osobna strefa nginx** `tile_limit` 30r/s dla kafelkow, `api_limit` 10r/s dla reszty API
  - **Debounce 300ms** na klikniecie mapy — zapobiega podwojnym wywolaniom
  - **Tryb wyboru obiektow** — toolbar "Zlewnia/Wybor", state.clickMode routing

- **Backend — endpoint `POST /api/select-stream`:**
  - Nowy plik `api/endpoints/select_stream.py`
  - Selekcja segmentu cieku z `stream_network`, traversal upstream, budowa granicy
  - Zwraca StreamInfo + upstream_segment_indices + boundary_geojson
  - 3 nowe schematy w `models/schemas.py`: SelectStreamRequest, StreamInfo, SelectStreamResponse

- **Frontend — podswietlanie zlewni czastkowych:**
  - `highlightUpstreamCatchments()` / `clearCatchmentHighlights()` w map.js
  - `showSelectionBoundary()` / `clearSelectionBoundary()` — warstwa boundary z dash
  - `selectStream()` w api.js — POST /api/select-stream

- **5 bugfixow (sesja 10):**
  - **Blad serwera select-stream**: dodano try/except ValueError + Exception (wzorzec z watershed.py), uzycie snapped outlet coords
  - **Flicker przezroczystosci**: setCatchmentsOpacity/setStreamsOpacity uzywaja CSS container opacity zamiast redraw()
  - **Legendy warstw**: L.control legendy dla ciekow (gradient flow acc) i zlewni (paleta Strahler), auto show/hide
  - **Zoom do danych na starcie**: fitBounds po zaladowaniu metadanych DEM
  - **Warstwa "Zlewnia" reaktywna**: wpis w panelu warstw aktywuje sie automatycznie po wyznaczeniu zlewni (polling 500ms)

- **Laczny wynik:** 484 testy, wszystkie przechodza

### Stan bazy danych (sesja 44 — 10 arkuszy, 5m NMT)
| Tabela | Rekordy | Uwagi |
|--------|---------|-------|
| flow_network | **USUNIETA** | Wyeliminowana w ADR-028, migracja 015 (DROP TABLE) |
| stream_network | ~263,791 | 3 progi: 1000, 10000, 100000 (prog 100 usuniety — ADR-030, migracja 017) |
| stream_catchments | 264,548 | 3 progi (bez progu 100, ADR-026) |
| land_cover | 101,237 | 2 powiaty (3021, 3064), 7 kategorii |
| depressions | 385,567 | pelny zestaw po bootstrap sesji 44 |
| precipitation_data | 7,560 | 180 punktow × 42 scenariusze |
| soil_hsg | 121 | grupy glebowe HSG |

### Znane problemy (infrastruktura)
- `generate_tiles.py` wymaga tippecanoe (`pip install tippecanoe` w .venv)
- FlowGraph (core/flow_graph.py) — USUNIETY w ADR-028 (sesja 33)
- ~~15 segmentow stream_network (prog 100 m²) odrzuconych przez geohash collision~~ — nieaktualne po usunieciu progu 100 (ADR-030)
- Endpoint `profile.py` wymaga pliku DEM (VRT/GeoTIFF) pod sciezka `DEM_PATH` — zwraca 503 gdy brak
- `bootstrap.py` nie importuje pokrycia terenu (land cover) — po pelnym bootstrap tabela `land_cover` jest pusta (0 rekordow), brak danych w UI. Wymaga dodania kroku importu land cover (skrypt `import_landcover.py`) do pipeline bootstrap. Priorytet: niski.

### Bledy do naprawy (zgloszenie sesja 18 — ZAMKNIETE)

**Status: ✅ Wszystkie 10 bugów naprawione (sesja 18, A1-A5, B1-B4, C1)**

### Bledy do naprawy (zgloszenie 2026-02-14, sesja 19)

**Status: ⏳ D1-D4 naprawione (sesja 20), G1-G4 naprawione (sesja 21), E2 naprawione (sesja 18 jako A1), E3 naprawione (sesja 22), F1 naprawione (sesja 24, ADR-024), E5+E6+E9+E10+E11 naprawione (sesja 35), F3 naprawione (sesja 35), E7+E8 naprawione (sesja 38), E1+E4+E12+E13+F2 naprawione (sesja 42). Pozostaje: H**

#### D. Frontend — profil terenu — ✅ NAPRAWIONE (sesja 20)

**D1. ✅ Profil terenu nadal nie dziala** → showProfileError z canvasId, panel pokazywany w catch
**D2. ✅ Dwuklik do zakonczenia rysowania zle dziala** → guard duplikatow, styl linii solid brown
**D3. ✅ Po Escape nie da sie usunac linii** → cancelDrawing czysci profileLine, re-aktywacja rysowania
**D4. ✅ Kontener "Profil terenu" nadal w panelu zlewni** → acc-profile usuniety, btn-profile-auto w profile-panel

#### E. Frontend — zlewnia i mapa

**E1. ✅ "Dziury" na granicach zlewni** → buffer-debuffer (0.1m/-0.1m) zamiast ST_SnapToGrid w merge_catchment_boundaries(), MIN_HOLE_AREA_M2: 1000→100 — sesja 42

**E2. ✅ Brak mozliwosci odznaczenia zlewni** → naprawione w sesji 18 jako A1 (closeResults czysci wszystkie warstwy)

**E3. ✅ Panel "Parametry zlewni" zaslania przyciski zoom** → panel dokowany z prawej (slide in/out), zoom przesuwa sie automatycznie (sesja 22)

**E4. ✅ Punkt ujsciowy poza granica zlewni** → ensure_outlet_within_boundary() snap do granicy (tolerancja 1m), zastosowanie w select_stream.py i watershed.py — sesja 42

**E5. ✅ Profil terenu nie generuje wykresu** → Chart.js resize w ukrytych kontenerach (d-none PRZED renderowaniem, resizeChart() z 50ms timeout, canvas w .chart-container) — sesja 35

**E6. ✅ Panel profilu terenu — styl liquid glass** → tokeny CSS liquid glass dodane do #profile-panel w style.css — sesja 35

**E7. ✅ Brak informacji o gruntach (HSG) w panelu wynikow** → grupy glebowe HSG w panelu i na mapie — sesja 38

**E8. ✅ Zbiorniki i cieki BDOT10k nie zaladowane do UI** → eksport BDOT10k GeoJSON dla frontendu — sesja 38

**E10. ✅ Brak wykresu hipsometrii w sekcji "Rzezba terenu"** → przyczyna ta sama co E5 (Chart.js nie załadowany przez zły hash CDN + resize w collapsed accordion). Naprawione hashami CDN + resizeChart() — sesja 35

**E11. ✅ Zmiana kolorystyki zaglebien na dyskretne progi** → YlOrRd paleta (5 progów wg volume_m3) w depressions.js — sesja 35

**E9. ✅ Usunac wpis "Zlewnia" z panelu Warstwy** → ~101 linii usunięte z layers.js + 3 wywołania z app.js — sesja 35

**E12. ✅ Brak legendy dla warstwy HSG** → createHsgLegend()/removeHsgLegend() w map.js, callbacki onShow/onHide w addBdotOverlayEntry() — sesja 42

**E13. ✅ Nieciaglosc danych HSG na terenach zurbanizowanych** → nearest-neighbor fill (distance_transform_edt) w step_soil_hsg() przed polygonizacja — sesja 42

#### F. Logika zlewni czastkowych

**F1. ✅ Selekcja cieku zaznacza cala zlewnię zamiast czesci miedzy doplywami** → ADR-024: segmentacja konfluencyjna + fine-threshold BFS (sesja 24). Wymaga re-run pipeline.

**F3. ✅ Automatyczny fallback na prog 1000 m² przy selekcji cieku z progu 100 m²** → eskalacja progu w select_stream.py gdy threshold < DEFAULT_THRESHOLD_M2, nowe pole `info_message` w SelectStreamResponse, banner w app.js — sesja 35

**F2. ✅ Snap-to-stream moze wybrac zlewnię sasiednia zamiast kliknietej** → find_nearest_stream_segment_hybrid(): ST_Contains na stream_catchments (priorytet) + fallback do globalnego ST_Distance snap — sesja 42

#### G. Frontend — panel warstw i dane — ✅ NAPRAWIONE (sesja 21)

**G1. ✅ Histogram "Rzezba terenu" za maly** → `.chart-container` height 160px → 240px
**G2. ✅ Brak informacji o pokryciu terenu** → naprawiono parsowanie warstw GeoPackage (OT_PTLZ_A → PTLZ); import 38560 rekordow BDOT10k
**G3. ✅ Podklady kartograficzne na dole panelu warstw** → przeniesione na koniec init(), nowa kolejnosc: Warstwy podkladowe → Wyniki analiz → Podklady kartograficzne
**G4. ✅ Reorganizacja wynikow analiz** → zaglbienia do #overlay-group-entries; checkbox zlewni: auto-check tylko przy 1. wykryciu, reset po usunieciu

#### I. Wizualizacja

**I1. Ścieżka spływu z punktu ujścia zlewni** (priorytet: niski)
- Po wyznaczeniu zlewni (tryb "Wybierz" lub "Wygeneruj") wyświetlić na mapie ścieżkę spływu wody od punktu ujścia zaznaczonej zlewni w dół cieku — pokazuje dokąd płynie woda opuszczająca zlewnię.
- Ścieżka wyznaczana na podstawie sieci cieków (`stream_network`) lub grafu przepływu (downstream traversal od outlet do granicy analizowanego obszaru).
- Wizualizacja jako linia na mapie (np. niebieska strzałka / animowana linia kierunku przepływu).
- **Lokalizacja:** `core/catchment_graph.py` (downstream traversal), `core/watershed_service.py` (outlet point), `frontend/js/map.js` (wizualizacja linii), `frontend/js/app.js` (wywołanie po wyznaczeniu zlewni)

**I2. Najdłuższa ścieżka spływu w zlewni** (priorytet: niski)
- Po wyznaczeniu zlewni wyświetlić na mapie najdłuższą ścieżkę spływu (longest flow path) — od najdalszego punktu działu wodnego do ujścia zlewni. Parametr hydrologicznie istotny: długość zlewni (watershed length) używana do obliczenia czasu koncentracji.
- Wymaga wyznaczenia najdalszej komórki od outletu wzdłuż sieci przepływu (upstream BFS z pomiarem odległości) lub geometrycznie (najdalszy punkt granicy zlewni mierzony wzdłuż cieku głównego + stoku).
- Wizualizacja jako linia na mapie (np. przerywana linia z zaznaczeniem punktu startowego i ujścia).
- **Lokalizacja:** `core/catchment_graph.py` (BFS z odległością), `core/watershed_service.py` (główny ciek + longest path), `frontend/js/map.js` (wizualizacja linii)

**I3. Poprawa jakości wyświetlania NMT** (priorytet: średni)
- Obecna piramida kafelków DEM (zoom 8–16, 267 plików, 15.5 MB) ma ograniczoną jakość — widoczna pikselizacja przy dużym zoomie, ograniczony zakres zoomów.
- Możliwe usprawnienia: rozszerzenie zakresu zoomów (do 18), lepsza rampa kolorów (np. terrain-classic), poprawa hillshade (multi-directional zamiast single azimuth 315°), antyaliasing przy downsamplingu (bilinear/lanczos zamiast nearest-neighbor na niższych zoomach), wyższa rozdzielczość kafelków (512×512 zamiast 256×256).
- Rozważyć dynamiczne generowanie kafelków DEM z serwera (endpoint XYZ z rasterio) zamiast pre-generowanych PNG — lepsza jakość kosztem wydajności.
- **Lokalizacja:** `scripts/generate_dem_tiles.py` (generacja piramidy), `utils/dem_color.py` (rampa kolorów, hillshade), `frontend/js/map.js` (L.tileLayer konfiguracja)

**I5. Pasek współrzędnych kursora (WGS 84 + PUWG 1992)** (priorytet: niski)
- Cienki pasek na samym dole strony (wzór: Geoportal) wyświetlający aktualną pozycję kursora na mapie w dwóch układach: WGS 84 (φ, λ) i EPSG:2180 (X, Y).
- Aktualizacja na zdarzeniu `mousemove` mapy Leaflet. Transformacja WGS 84 → PUWG 1992 po stronie klienta (proj4js lub prosta formuła Gaussa-Krügera).
- Styl liquid glass (tokeny CSS `--liquid-bg`, `--liquid-blur`, `--liquid-border`) — spójność z panelami warstw i wyników.
- **Lokalizacja:** `frontend/index.html` (nowy element `#coord-bar`), `frontend/css/style.css` (styl paska), `frontend/js/map.js` (nasłuch `mousemove`, transformacja współrzędnych)

**I4. Eksport profilu podłużnego do CSV** (priorytet: niski)
- Przycisk eksportu w panelu profilu terenu (`#profile-panel`) — pobieranie pliku CSV z danymi profilu.
- Format: `X;Y;Station;Elevation` (separator średnik), współrzędne domyślnie w EPSG:2180. Station = odległość wzdłuż profilu od pierwszego punktu [m].
- Dane dostępne po stronie frontendu (odpowiedź z `POST /api/terrain-profile` zawiera punkty z współrzędnymi i wysokościami). Transformacja WGS 84 → PUWG 1992 po stronie klienta lub rozszerzenie endpointu o opcjonalny parametr CRS.
- **Lokalizacja:** `frontend/js/profile.js` (przycisk eksportu, generacja CSV, download), `frontend/index.html` (przycisk w `#profile-panel`), `api/endpoints/profile.py` (opcjonalnie: współrzędne w EPSG:2180 w response)

#### J. Funkcjonalności użytkowe

**J1. Formularz feedbacku zapisywany do bazy** (priorytet: niski)
- Prosty formularz na stronie umożliwiający użytkownikom zgłaszanie uwag / błędów / sugestii.
- Dane zapisywane do tabeli w PostgreSQL (np. `feedback`: id, message, email (opcjonalny), created_at, user_agent, page_url).
- Endpoint `POST /api/feedback` z walidacją (max długość, rate limiting).
- Frontend: przycisk w navbarze lub floating button, modal z polem tekstowym + opcjonalnym emailem.
- **Lokalizacja:** nowa tabela `feedback` (migracja Alembic), `api/endpoints/feedback.py` (nowy endpoint), `frontend/index.html` (modal), `frontend/js/app.js` (obsługa formularza)

**J2. Wgrywanie własnych warstw wektorowych** (priorytet: niski)
- Użytkownik może wgrać plik wektorowy (SHP, GPKG, GeoJSON, KML) i wyświetlić go jako warstwę na mapie.
- Preferowane rozwiązanie: przetwarzanie po stronie frontendu (bez wysyłania na serwer). Kandydaci do zbadania: biblioteka `shpjs` (SHP→GeoJSON), `gdal3.js` / `ogr2ogr WASM` (GPKG/KML→GeoJSON), natywne parsowanie GeoJSON. Leaflet obsługuje GeoJSON natively — wystarczy konwersja do tego formatu.
- Pliki SHP wymagają ZIP (`.shp` + `.dbf` + `.shx` + opcjonalnie `.prj`) — obsługa via `JSZip` lub drag-and-drop folderu.
- Warstwa dodawana do panelu warstw z checkboxem, suwakiem przezroczystości i zoom-to-extent.
- **Lokalizacja:** `frontend/js/layers.js` (dodawanie warstwy użytkownika), `frontend/js/map.js` (rendering GeoJSON), `frontend/index.html` (przycisk upload / drag-and-drop zone)

**J3. Dodawanie własnych serwisów WMS/WMTS/WFS** (priorytet: niski)
- Użytkownik podaje URL serwisu OGC i wybiera warstwę do wyświetlenia — obsługa wyłącznie po stronie frontendu.
- WMS: `L.tileLayer.wms(url, { layers, format, transparent })` — Leaflet natywnie.
- WMTS: `L.tileLayer(templateUrl)` z parametrami z GetCapabilities.
- WFS: pobranie GeoJSON przez `fetch(url + '&outputFormat=application/json')` → `L.geoJSON()`.
- Formularz: pole URL + przycisk "Pobierz warstwy" (GetCapabilities) → lista warstw do wyboru → dodanie do panelu warstw z checkboxem i przezroczystością.
- **Lokalizacja:** `frontend/js/layers.js` (dodawanie serwisu, parsowanie GetCapabilities XML), `frontend/js/map.js` (tworzenie warstw L.tileLayer.wms / L.tileLayer / L.geoJSON), `frontend/index.html` (modal z formularzem URL)

**J4. Mapy glebowe i użytkowanie terenu w warstwach podkładowych** (priorytet: średni)
- Dodanie warstw tematycznych do panelu "Warstwy podkładowe": mapa glebowa i użytkowanie/pokrycie terenu.
- **Gleby:** serwis WMS z Geoportalu (mapy glebowo-rolnicze) lub dane SoilGrids (już pobierane przez Kartograf dla HSG). Alternatywnie: import danych glebowych do bazy i serwowanie jako MVT/GeoJSON z kolorowaniem wg typów gleb / grup HSG.
- **Użytkowanie terenu:** dane BDOT10k pokrycia terenu (już w tabeli `land_cover` — 50406 rekordów) lub Corine Land Cover (CLC) z serwisu WMS. Wizualizacja z paletą kolorów wg kategorii (las, łąka, grunt orny, zabudowa, woda, droga, inny).
- Obie warstwy z checkboxem, suwakiem przezroczystości i legendą kolorów w panelu warstw.
- **Lokalizacja:** `frontend/js/layers.js` (wpisy warstw + legenda), `frontend/js/map.js` (rendering), `api/endpoints/tiles.py` (opcjonalnie: MVT endpoint dla land_cover), `core/land_cover.py` (dane)

#### CR. Wyniki code review (2026-02-22)

**Status: ⏳ W trakcie — 16 pozycji (3/3 krytyczne naprawione ✅, 8 ważne, 5 sugestii)**

##### Krytyczne (must fix)

**CR1. ✅ `channel_slope_m_per_m` obliczany z całkowitej długości sieci rzecznej zamiast głównego cieku** (NAPRAWIONE)
- Nowa metoda `CatchmentGraph.trace_main_channel()` — tracing upstream wg Strahlera. ADR-029, 6 nowych testów.

**CR2. ✅ O(n^2) lookup segmentów w `compute_downstream_links()`** (NAPRAWIONE)
- `stream_extraction.py`: `segments.index(seg) + 1` → `enumerate(segments, start=1)`. 550 testów passed.

**CR3. ✅ Server-side cursor niezamykany na wyjątek w `CatchmentGraph.load()`** (NAPRAWIONE)
- Opakowanie w `try/finally` z `cursor.close()` w `finally`. 550 testów passed.

##### Ważne (should fix)

**CR4. `traverse_to_confluence` BFS z `list.pop(0)` — O(n^2)** (priorytet: średni)
- `catchment_graph.py:410-411`: `list.pop(0)` jest O(n), powinno być `collections.deque` + `popleft()`.
- **Lokalizacja:** `core/catchment_graph.py`

**CR5. `get_land_cover_stats()` zawsze zwraca pusty dict (TODO)** (priorytet: średni)
- `cn_calculator.py:196-200`: pobiera pokrycie terenu ale nie analizuje go — zawsze fallback do domyślnych wartości (hardcoded średnia centralna Polska).
- Cała ścieżka Kartograf CN de facto produkuje `CN = weighted_cn(default_land_cover, "B")`.
- **Lokalizacja:** `core/cn_calculator.py`

**CR6. Bezpośredni dostęp do prywatnego `cg._segment_idx` w 3 endpointach** (priorytet: średni)
- `watershed.py:128`, `hydrograph.py:139`, `select_stream.py:114` — wszystkie robią `int(cg._segment_idx[clicked_idx])`.
- **Rozwiązanie:** dodać publiczną metodę `CatchmentGraph.get_segment_idx(internal_idx: int) -> int`.
- **Lokalizacja:** `core/catchment_graph.py`, `api/endpoints/watershed.py`, `api/endpoints/hydrograph.py`, `api/endpoints/select_stream.py`

**CR7. Singleton `CatchmentGraph` bez thread safety** (priorytet: średni)
- `catchment_graph.py:625-633`: brak `threading.Lock` — race condition w thread pool executor (sync endpointy FastAPI).
- **Rozwiązanie:** double-check locking z `threading.Lock`.
- **Lokalizacja:** `core/catchment_graph.py`

**CR8. Terrain profile — wyciek ścieżki DEM + porównanie nodata z `==`** (priorytet: średni)
- `profile.py:84-88`: pełna ścieżka serwera (`/data/dem/dem.vrt`) trafia do klienta (information disclosure).
- `profile.py:95-96`: porównanie float z `==` jest zawodne; `0.0` jako replacement maskuje prawdziwą elewację poziomu morza.
- **Lokalizacja:** `api/endpoints/profile.py`

**CR9. Cascade threshold escalation — boundary vs stats mogą opisywać różne zlewnie** (priorytet: średni)
- `select_stream.py:137-161`: przy eskalacji progu statystyki pochodzą z fine-threshold BFS, ale boundary z coarse-threshold merge — mogą opisywać różne ekstenty.
- **Lokalizacja:** `api/endpoints/select_stream.py`

**CR10. `traceback.print_exc()` zamiast `logger.error(..., exc_info=True)`** (priorytet: niski)
- `cn_calculator.py:333`, `analyze_watershed.py:416,1312` — bypass logowania strukturalnego.
- **Lokalizacja:** `core/cn_calculator.py`, `scripts/analyze_watershed.py`

**CR11. CLAUDE.md — nieaktualna struktura modułów** (priorytet: niski)
- `core/flow_graph.py` wymieniony jako DEPRECATED ale usunięty (commit `a65c25d`).
- Brakuje: `core/soil_hsg.py`, `scripts/bootstrap.py`.
- **Lokalizacja:** `CLAUDE.md`

##### Sugestie (nice to have)

**CR12. Duplikacja logiki morfometrycznej** — `select_stream.py:193-314` reimplementuje `build_morph_dict_from_graph()` z `watershed_service.py`.

**CR13. `_MAX_MERGE = 500` zdefiniowane inline** w `watershed.py:152` i `select_stream.py:133` — powinno być w `core/constants.py`.

**CR14. Inline import `soil_hsg` w endpoint** — `watershed.py:263-264` i `select_stream.py:274-275` importują wewnątrz try-except zamiast na górze pliku.

**CR15. Integer division `n_bins` w `aggregate_hypsometric`** — `catchment_graph.py:578` używa `//` co może obciąć ostatni bin. Powinno być `math.ceil()`.

**CR16. Caching POST response** — `select_stream.py:343` ustawia `Cache-Control: public, max-age=3600` na POST — niestandardowe i ignorowane przez wiele proxy.

#### H. Do rozważenia (koncepcyjne)

**H1. Zlewnie bezposrednie jezior przeplywowych i bezodplywowych** (priorytet: do ustalenia)
- Jak wyznaczac zlewnię bezposrednia jeziora przeplywowego? Czy laczyc ze soba zlewnie czastkowe, zeby unikac ich nadmiernego rozdrobnienia?
- Jak traktowac jeziora bezodplywowe (endorheic)? Powoduja one "dziury" w zlewniach rzecznych, a dwa blisko polozone obok siebie zborniki nie maja wyznaczonych swoich zlewni.
- Jak wdrozyc zlewnie kanalizacyjne i przekazywac ich doplywu do wyplywu w innym miejscu analizowanego obszaru?
- Powiazanie z istniejaca klasyfikacja jezior (ADR-020: 45 endorheic, 18 exorheic) i drain points
- **Kontekst:** `core/hydrology.py` (classify_endorheic_lakes), `catchment_graph.py` (traverse_upstream)

**H2. Narzucenie kierunku splywu na podstawie warstwy wektorowej** (priorytet: do ustalenia)
- Mozliwosc wymuszenia kierunku splywu (flow direction) w oparciu o zewnetrzna warstwe wektorowa (np. BDOT10k cieki, OSM waterways)
- Przypadki uzycia: korygowanie bledow DEM na terenach plaskich (delty, polesia), kanaly, rowy melioracyjne
- Mozliwe podejscia: stream burning (juz zaimplementowane w `hydrology.py` — `burn_streams_into_dem()`), flow direction forcing (nadpisywanie fdir w komorkach pokrywajacych sie z wektorem)
- Pytanie: czy obecny stream burning jest wystarczajacy, czy potrzebna jest pelna kontrola fdir?
- **Kontekst:** `core/hydrology.py` (burn_streams_into_dem, process_hydrology_pyflwdir), `scripts/process_dem.py`

**H3. Podniesienie budynkow BDOT10k w NMT (building raising)** (priorytet: sredni)
- Obecnie budynki sa usuwane z NMT (lub nieuwzgledniane), wiec woda moze swobodnie przeplywac przez nie. Prowadzi to do nierealistycznych kierunkow splywu i akumulacji — cieki "przechodzace" przez zabudowe.
- Rozwiazanie: pobranie warstwy budynkow z BDOT10k i podniesienie wartosci NMT w obrebie ich footprintow o domyslna wartosc +5 m. Operacja powinna byc wykonywana **przed** wypalaniem ciekow (stream burning), aby cieki mogly nadpisac podniesione komorki tam, gdzie to konieczne.
- Kolejnosc preprocessingu NMT: (1) fill sinks → (2) **building raising** → (3) stream burning → (4) flow direction → (5) flow accumulation.
- Wymaga pobrania warstwy BUBD (budynki) z BDOT10k przez Kartograf — analogicznie do istniejacego pobierania warstw hydro (SWRS, SWKN, SWRM, PTWP).
- Parametr `building_raise_m` (domyslnie 5.0) jako stala w `core/constants.py` lub argument CLI.
- **Kontekst:** `core/hydrology.py` (burn_streams_into_dem, process_hydrology_pyflwdir), `scripts/process_dem.py` (orchestrator), `scripts/bootstrap.py` (step_process_dem)

**H4. Monotoniczne wygladzanie ciekow zamiast stalego wypalania (stream gradient enforcement)** (priorytet: niski)
- Obecny stream burning obniza NMT o stala wartosc wzdluz cieku. Problem: gdy ciek przechodzi przez obiekt o znacznej wysokosci (most, wiadukt, nasyp), nawet duze wypalenie moze byc niewystarczajace. Jednoczesnie stale wypalenie w normalnych odcinkach tworzy nadmierne obnizenia, ktore potem wymagaja duzego fill sinks — wypelnienie zaglebia moze zalewac okoliczne komorki.
- Rozwiazanie: zamiast obnizania o stala wartosc, wygladazac wartosci NMT wzdluz linii cieku tak, aby wysokosci monotonicznie malaly w kierunku splywu. Kazda komorka na cieku powinna miec wartosc <= poprzedniej komorki w gore cieku. Jesli napotkana wartosc jest wyzsza (most, nasyp), zostaje zastapiona wartoscia poprzedniej komorki (lub interpolacja liniowa miedzy znanymi punktami po obu stronach przeszkody).
- Algorytm: (1) pobranie profilu wysokosci wzdluz geometrii cieku (ordered vertices), (2) przejscie od zrodla do ujscia z wymuszeniem monotonicznosci (running minimum), (3) zapis wygladzonych wartosci do rastra NMT.
- Zaleta: eliminuje problem mostow/nasypow bez tworzenia sztucznych zaglebie w normalnych odcinkach. Wypalanie stalą wartoscia pozostaje jako fallback tam, gdzie brak geometrii ciekow.
- **Kontekst:** `core/hydrology.py` (burn_streams_into_dem), `scripts/process_dem.py`

**H5. Symplifikacja granic zlewni** (priorytet: sredni)
- Granice zlewni generowane z polygonizacji rastra maja ksztalt schodkowy (pikselowy) — kazda komorka rastra tworzy prostokatny fragment granicy. Przy duzym zoomie wyglada to nieatrakcyjnie i nierealistycznie.
- Mozliwe podejscia: (1) `ST_SimplifyPreserveTopology` post-hoc na wynikowej granicy z tolerancja np. 1-2× cellsize, (2) wygladzanie Chaikin/Bezier na granicy zlewni, (3) symplifikacja juz na etapie polygonizacji zlewni czastkowych (pipeline).
- Trzeba zachowac topologiczna spojnosc — symplifikacja nie moze tworzyc luk miedzy sasiednimi zlewniami ani nakładek. `ST_SimplifyPreserveTopology` jest bezpieczniejsza niz `ST_Simplify`.
- **Kontekst:** `core/stream_extraction.py` (polygonize_subcatchments), `core/watershed_service.py` (merge_catchment_boundaries), `core/watershed.py` (build_boundary)

**H6. Format danych HSG: wektor o uproszczonej geometrii vs raster** (priorytet: do ustalenia)
- Obecnie dane HSG (SoilGrids) sa pobierane jako raster (resolucja 250m) przez Kartograf i uzywane do obliczen CN. Do frontendu trafiaja jako warstwa wektorowa (GeoJSON z polygonami per-grupa glebowa).
- Pytanie: czy dane HSG powinny byc przekazywane do frontendu jako (a) wektor o uproszczonej geometrii (mniejszy rozmiar, szybsze renderowanie, ale wymaga polygonizacji + symplifikacji rastra) czy (b) raster/overlay PNG (prostsza generacja, ale brak interaktywnosci i tooltipow).
- Wektor: zalety — tooltips, klikanie, legenda dynamiczna, mozliwosc filtrowania; wady — duzy GeoJSON przy rozdzielczosci 250m, koniecznosc symplifikacji.
- Raster: zalety — prosty pipeline (analogicznie do DEM overlay), maly rozmiar, szybkie renderowanie; wady — brak interaktywnosci, statyczna legenda.
- Podejscie hybrydowe: raster jako warstwa podkladowa + wektor z uproszczona geometria dla tooltipow i statystyk.
- **Kontekst:** `core/cn_calculator.py` (dane HSG), `scripts/bootstrap.py` (pipeline), `frontend/js/layers.js` (renderowanie warstw)

### Nastepne kroki
1. ~~**Naprawa krytycznych bledow z code review:** CR1, CR2, CR3~~ ✅ (wszystkie 3 naprawione)
2. Naprawa waznych bledow z code review: CR4-CR9 (BFS deque, land cover TODO, enkapsulacja _segment_idx, thread safety, profile info disclosure)
3. ~~Naprawa pozostalych bugow UX: E1, E4, E12, E13, F2~~ ✅ (wszystkie 5 naprawione, sesja 42)
4. ~~Aktualizacja CLAUDE.md (CR11): usunac flow_graph.py, dodac soil_hsg.py i bootstrap.py~~ ✅ (sesja 39)
5. Weryfikacja podkladow GUGiK WMTS (czy URL-e dzialaja z `EPSG:3857:{z}`)
6. Usuniecie hardcoded secrets z config.py i migrations/env.py
7. CP5: MVP — pelna integracja, deploy

## Backlog

- [x] Fix traverse_upstream resource exhaustion (ADR-015: pre-flight check, CTE LIMIT, statement_timeout, Docker limits)
- [x] CP4 Faza 1: Frontend — mapa + zlewnia + parametry (Leaflet.js, Bootstrap 5)
- [x] CP4: Warstwa NMT — naprawiona (L.imageOverlay → tile pyramid XYZ + fallback)
- [x] CP4: Warstwa ciekow (Strahler) — L.imageOverlay z dylatacja morfologiczna → zamieniona na MVT
- [x] CP4: DEM tile pyramid + kolejnosc warstw (demPane/catchmentsPane/streamsPane)
- [x] CP4 Faza 2: Redesign glassmorphism + Chart.js + hydrogram + profil + zaglebie
- [x] CP4 Faza 3: Wektoryzacja ciekow MVT, multi-prog FA, hillshade, zaglbienia preprocessing
- [x] CP4 Faza 4: Select-stream pelne statystyki, GUGiK WMTS, UI fixes (492 testy)
- [x] Graf zlewni czastkowych (ADR-021): CatchmentGraph in-memory, migracja 012, pipeline re-run, select-stream rewrite
- [ ] CP5: MVP — pelna integracja, deploy
- [ ] Plik konfiguracyjny YAML — niestandardowe parametry i sciezki (np. wlasne wektory ciekow zamiast BDOT10k). Priorytet: sredni.
- [ ] Ikony trybow w toolbarze — lapka (przegladanie), kursor klikajacy (wybierz zlewnię), kafelki/siatka (wygeneruj zlewnię), profil terenu (profil). Priorytet: niski.
- [ ] Podzial NMT na kafle (tile pyramid) — szybsze wczytywanie nakladki DEM na mapie (obecnie pojedynczy PNG, przy duzych obszarach ciezki). Priorytet: sredni.
- [x] Naprawa bledow frontend/backend (zgloszenie 2026-02-14, 10 pozycji — A1-A5, B1-B4, C1)
- [ ] Naprawa bledow UX (zgloszenie 2026-02-14, 13 pozycji — D1-D4, E1-E3, F1, G1-G4)
- [ ] Testy scripts/ (process_dem.py, import_landcover.py — 0% coverage)
- [x] Utworzenie backend/core/constants.py (M_PER_KM, M2_PER_KM2, CRS_*)
- [ ] Usuniecie hardcoded secrets z config.py i migrations/env.py
- [x] Problem jezior bezodplywowych (endorheic basins) — ADR-020: klasyfikacja + drain points
- [x] CI/CD pipeline (GitHub Actions)
- [x] Audyt QA wydajnosci: LATERAL JOIN, cache headers, TTL cache, partial index, PG tuning, client cache, defer, structlog
- [x] Eliminacja FlowGraph z runtime API (ADR-022): RAM -96%, startup -97%, 548 testow
- [x] Code review CR1-CR3 (krytyczne): channel_slope, O(n^2) segments.index, cursor leak
- [ ] Code review CR4-CR11 (wazne): BFS deque, land cover TODO, enkapsulacja, thread safety, profile, cascade stats, traceback, CLAUDE.md
- [ ] Code review CR12-CR16 (sugestie): duplikacja morph, _MAX_MERGE const, inline import, n_bins ceil, POST cache
- [ ] Podwojna analiza NMT (z/bez obszarow bezodplywowych): pipeline generuje 2 warianty — pelny DEM (z endoreicznymi) i DEM hydrologicznie poprawny (bez). Cieki i obliczenia hydrologiczne (SCS-CN, hydrogram) oparte na wariancie bez bezodplywowych. W UI zlewnie bezodplywowe oznaczane innym kolorem (np. szarym/przezroczystym) ale widoczne na mapie. Wymaga: 2x process_hydrology_pyflwdir, osobne stream_network/catchments, warstwa UI z rozroznieniem. Priorytet: sredni.
