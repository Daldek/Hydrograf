# PROGRESS — Hydrograf

## Status projektu

| Element | Status | Uwagi |
|---------|--------|-------|
| API (FastAPI + PostGIS) | ✅ Gotowy | 10 endpointow: delineate, hydrograph, scenarios, profile, depressions, select-stream, health, tiles/streams, tiles/catchments, tiles/thresholds. 538 testow. |
| Wyznaczanie zlewni | ✅ Gotowy | traverse_upstream, concave hull |
| Parametry morfometryczne | ✅ Gotowy | area, slope, length, CN + 11 nowych wskaznikow |
| Generowanie hydrogramu | ✅ Gotowy | SCS-CN, 42 scenariusze |
| Preprocessing NMT | ✅ Gotowy | pyflwdir (~12 min/8 arkuszy po eliminacji flow_network), stream burning BDOT10k |
| Integracja Hydrolog | ✅ Gotowy | v0.5.2 |
| Integracja Kartograf | ✅ Gotowy | v0.4.1 (NMT, NMPT, Orto, Land Cover, HSG, BDOT10k hydro) |
| Integracja IMGWTools | ✅ Gotowy | v2.1.0 (opady projektowe) |
| CN calculation | ✅ Gotowy | cn_tables + cn_calculator + determine_cn() |
| Frontend | 🔶 Faza 4 gotowa | CP4 — tryb wyboru obiektow, flow acc coloring, histogram, debounce, zoom fix |
| Testy scripts/ | ⏳ W trakcie | 538 testow lacznie (po usunieciu 43 testow martwego kodu flow_network/flow_graph) |
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

### CP4 — Frontend z mapa ✅
- **Wersja:** v0.4.0
- **Zakres:** Leaflet.js, Chart.js, interaktywna mapa, panel parametrow, glassmorphism, MVT, select-stream, GUGiK WMTS

### CP5 — MVP ⏳
- **Wersja:** v1.0.0 (planowana)
- **Zakres:** Pelna integracja frontend+backend, deploy produkcyjny

## Ostatnia sesja

**Data:** 2026-02-17 (sesja 34)

### Co zrobiono

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

### Stan bazy danych
| Tabela | Rekordy | Uwagi |
|--------|---------|-------|
| flow_network | **USUNIETA** | Wyeliminowana w ADR-028, migracja 015 (DROP TABLE) |
| stream_network | 220,859 | 100: 198258, 1000: 20302, 10000: 2087, 100000: 212 (z segment_idx, migracja 014) |
| stream_catchments | 22,613 | 1000: 20313, 10000: 2088, 100000: 212 (bez progu 100, ADR-026) |
| land_cover | 50,406 | 2 powiaty (3021, 3064), 7 kategorii |
| depressions | 1,125,699 | pelny zestaw po bootstrap sesji 34 |
| precipitation_data | 630 | 15 punktow × 42 scenariusze |

### Znane problemy (infrastruktura)
- `generate_tiles.py` wymaga tippecanoe (`pip install tippecanoe` w .venv)
- FlowGraph (core/flow_graph.py) — USUNIETY w ADR-028 (sesja 33)
- 15 segmentow stream_network (prog 100 m²) odrzuconych przez geohash collision — marginalny problem
- Endpoint `profile.py` wymaga pliku DEM (VRT/GeoTIFF) pod sciezka `DEM_PATH` — zwraca 503 gdy brak
- `bootstrap.py` nie importuje pokrycia terenu (land cover) — po pelnym bootstrap tabela `land_cover` jest pusta (0 rekordow), brak danych w UI. Wymaga dodania kroku importu land cover (skrypt `import_landcover.py`) do pipeline bootstrap. Priorytet: niski.

### Bledy do naprawy (zgloszenie sesja 18 — ZAMKNIETE)

**Status: ✅ Wszystkie 10 bugów naprawione (sesja 18, A1-A5, B1-B4, C1)**

### Bledy do naprawy (zgloszenie 2026-02-14, sesja 19)

**Status: ⏳ D1-D4 naprawione (sesja 20), G1-G4 naprawione (sesja 21), E2 naprawione (sesja 18 jako A1), E3 naprawione (sesja 22), F1 naprawione (sesja 24, ADR-024), E1-E4-H do rozwiazania**

#### D. Frontend — profil terenu — ✅ NAPRAWIONE (sesja 20)

**D1. ✅ Profil terenu nadal nie dziala** → showProfileError z canvasId, panel pokazywany w catch
**D2. ✅ Dwuklik do zakonczenia rysowania zle dziala** → guard duplikatow, styl linii solid brown
**D3. ✅ Po Escape nie da sie usunac linii** → cancelDrawing czysci profileLine, re-aktywacja rysowania
**D4. ✅ Kontener "Profil terenu" nadal w panelu zlewni** → acc-profile usuniety, btn-profile-auto w profile-panel

#### E. Frontend — zlewnia i mapa

**E1. "Dziury" na granicach zlewni** (priorytet: wysoki)
- Po wyborze zlewni na granicach pojawiaja sie widoczne "dziury"
- Prawdopodobnie zaglbienia terenowe lub bledy laczenia obiektow wektorowych (ST_Union artifacts)
- **Lokalizacja:** `watershed_service.py` (merge_catchment_boundaries), `watershed.py` (build_boundary)

**E2. ✅ Brak mozliwosci odznaczenia zlewni** → naprawione w sesji 18 jako A1 (closeResults czysci wszystkie warstwy)

**E3. ✅ Panel "Parametry zlewni" zaslania przyciski zoom** → panel dokowany z prawej (slide in/out), zoom przesuwa sie automatycznie (sesja 22)

**E4. Punkt ujsciowy poza granica zlewni** (priorytet: sredni)
- Dotyczy obu trybow: "Wybierz zlewnię" i "Wygeneruj zlewnię"
- Punkt ujsciowy (outlet) bywa przesuniety o kilkaset metrow poza granice wyznaczonej zlewni
- Pojawia sie przy ujsciu doplywu do cieku wyzszego rzedu — outlet "przeskakuje" do nastepnego wezla w dol cieku
- Prawdopodobna przyczyna: `traverse_upstream` zwraca segment_idx doplywu, ale outlet pobierany jest z downstream node cieku glownego
- **Lokalizacja:** `watershed_service.py` (logika wyznaczania outlet), `catchment_graph.py` (traverse_upstream)

**E5. Profil terenu nie generuje wykresu** (priorytet: wysoki)
- Panel profilu terenu pojawia sie po narysowaniu linii, ale wykres nie jest renderowany — okienko puste.
- Funkcjonalnosc dzialala wczesniej (potwierdzone w sesjach 19-20). Regresja — prawdopodobnie spowodowana zmianami w kolejnych sesjach.
- **Lokalizacja:** `frontend/js/profile.js` (activateDrawProfile, renderowanie Chart.js), `api/endpoints/profile.py` (endpoint POST /api/terrain-profile), `frontend/js/app.js` (obsluga trybu profilu)

**E6. Panel profilu terenu — styl liquid glass** (priorytet: niski)
- Panel `#profile-panel` nie uzywa stylu liquid glass — wyglada niespojnie z pozostalymi panelami (warstwy, parametry zlewni), ktore maja glassmorphism.
- Zastosowac te same tokeny CSS: `--liquid-bg`, `--liquid-border`, `--liquid-blur`, `--liquid-shadow`, `--liquid-highlight`.
- **Lokalizacja:** `frontend/css/glass.css`, `frontend/index.html` (`#profile-panel`)

**E7. Brak informacji o gruntach (HSG) w panelu wynikow** (priorytet: niski)
- Po wyznaczeniu zlewni panel wynikow nie wyswietla informacji o gruntach (Hydrologic Soil Group / typy gleb).
- Dane HSG sa pobierane przez Kartograf (SoilGrids) i uzywane do obliczen CN, ale nie sa prezentowane uzytkownikowi.
- Wyswietlenie w stylu analogicznym do sekcji "Pokrycie terenu" — wykres kolowy/slupkowy z podzialem na grupy gruntowe (A/B/C/D) i procentowym udzialem w zlewni.
- **Lokalizacja:** `frontend/js/charts.js` (renderowanie wykresow), `frontend/index.html` (sekcja wynikow), `core/cn_calculator.py` / `core/land_cover.py` (dane HSG)

**E8. Zbiorniki i cieki BDOT10k nie zaladowane do UI** (priorytet: wysoki)
- Warstwy wektorowe BDOT10k (zbiorniki wodne i cieki) nie sa wyswietlane na mapie.
- Dane BDOT10k hydro sa pobierane przez `bootstrap.py` (warstwy SWRS, SWKN, SWRM, PTWP) i uzywane do stream burning, ale nie sa serwowane do frontendu jako warstwy referencyjne.
- Wczesniej dzialalo — GeoJSON z 3529 jeziorami i 7197 ciekami byl generowany (sesja 13).
- Prawdopodobnie dane zostaly utracone po resecie bazy (`docker compose down -v`) w sesji 32 i nie zostaly ponownie wyeksportowane/zaladowane.
- **Lokalizacja:** `frontend/js/layers.js` (ladowanie warstw BDOT), `scripts/bootstrap.py` (brak kroku eksportu GeoJSON BDOT), `frontend/js/app.js` (inicjalizacja warstw)

**E10. Brak wykresu hipsometrii w sekcji "Rzezba terenu"** (priorytet: wysoki)
- Po wyznaczeniu zlewni sekcja "Rzezba terenu" w panelu wynikow nie wyswietla wykresu krzywej hipsometrycznej.
- Krzywa hipsometryczna byla zaimplementowana w sesji 21 (zamiana histogramu na krzywa — os Y: wysokosc m n.p.m., os X: % powierzchni powyzej).
- Regresja — prawdopodobnie spowodowana zmianami w kolejnych sesjach lub brakiem danych hipsometrycznych po resecie bazy.
- **Lokalizacja:** `frontend/js/charts.js` (renderElevationHistogram / krzywa hipsometryczna), `frontend/index.html` (sekcja #acc-elevation), `core/catchment_graph.py` (agregacja histogramow wysokosci)

**E11. Zmiana kolorystyki zaglebien na dyskretne progi** (priorytet: niski)
- Obecnie zaglbienia wyswietlane sa jednym ciaglym kolorem niebieskim niezaleznie od wielkosci/glebokosci.
- Zmienic na dyskretna skale kolorow z progami — np. male zaglbienia jasniejsze, duze ciemniejsze. Konkretne kolory i wartosci progow do ustalenia.
- **Lokalizacja:** `frontend/js/layers.js` (stylowanie warstwy zaglebien), `api/endpoints/depressions.py` (dane zaglebien)

**E9. Usunac wpis "Zlewnia" z grupy "Wyniki analiz" w panelu Warstwy** (priorytet: niski)
- Checkbox "Zlewnia" w sekcji "Wyniki analiz" panelu warstw jest zbedny — wszystkie informacje o zlewni (granica, parametry, zlewnie czastkowe) sa juz dostepne w panelu "Parametry zlewni".
- Usunac wpis z panelu warstw oraz powiazana logike auto-check (`_watershedFirstDetection`).
- **Lokalizacja:** `frontend/js/layers.js` (wpis "Zlewnia" w overlay group), `frontend/js/app.js` (logika auto-check)

#### F. Logika zlewni czastkowych

**F1. ✅ Selekcja cieku zaznacza cala zlewnię zamiast czesci miedzy doplywami** → ADR-024: segmentacja konfluencyjna + fine-threshold BFS (sesja 24). Wymaga re-run pipeline.

**F3. Automatyczny fallback na prog 1000 m² przy selekcji cieku z progu 100 m²** (priorytet: sredni)
- Gdy uzytkownik kliknie na ciek o progu FA 100 m² (najdrobniejsze cieki), system powinien automatycznie przejsc na selekcje z progu 1000 m² (najdrobniejszy prog z wygenerowanymi zlewniami czastkowymi — ADR-026 pomija catchments dla progu 100).
- W UI wyswietlic informacje o zmianie progu, np. banner: "Zlewnie czastkowe niedostepne dla progu 100 m². Zaznaczono z progu 1000 m². Uzyj trybu «Wygeneruj zlewnię» dla precyzyjniejszego wyniku."
- Obecne zachowanie: brak zlewni czastkowych dla progu 100 → brak wyniku lub blad.
- **Lokalizacja:** `api/endpoints/select_stream.py` (logika fallback progu), `frontend/js/app.js` (wyswietlanie baneru informacyjnego)

**F2. Snap-to-stream moze wybrac zlewnię sasiednia zamiast kliknietej** (priorytet: sredni)
- Po naprawie ADR-027 selekcja opiera sie na snap-to-stream (`ST_Distance` na `stream_network`) — system znajduje najblizszy segment cieku i buduje zlewnię w gore od niego.
- Problem: gdy uzytkownik kliknie wewnatrz jednej zlewni, ale najblizszy ciek nalezy do sasiedniej zlewni (np. blisko dzialu wodnego, przy konfluencji lub w szerokich zlewniach bez ciekow), system zaznaczy niewlasciwa zlewnię.
- Wczesniejszy system oparty na `ST_Contains` (identyfikacja zlewni czastkowej pod kursorem) dzialal poprawnie w tym scenariuszu, ale mial inne bledy (klikniecie blisko granicy zlewni moglo trafic w sasiada — dlatego wycofany na rzecz snap-to-stream w ADR-027).
- Mozliwe rozwiazanie: podejscie hybrydowe — najpierw `ST_Contains` na `stream_catchments` (ktora zlewnia pod kursorem?), a nastepnie snap-to-stream ograniczony do ciekow w obrebie tej zlewni. Fallback na obecny snap-to-stream gdy `ST_Contains` nie znajdzie wyniku.
- **Lokalizacja:** `api/endpoints/select_stream.py`, `core/watershed_service.py` (`find_nearest_stream_segment`)

#### G. Frontend — panel warstw i dane — ✅ NAPRAWIONE (sesja 21)

**G1. ✅ Histogram "Rzezba terenu" za maly** → `.chart-container` height 160px → 240px
**G2. ✅ Brak informacji o pokryciu terenu** → naprawiono parsowanie warstw GeoPackage (OT_PTLZ_A → PTLZ); import 38560 rekordow BDOT10k
**G3. ✅ Podklady kartograficzne na dole panelu warstw** → przeniesione na koniec init(), nowa kolejnosc: Warstwy podkladowe → Wyniki analiz → Podklady kartograficzne
**G4. ✅ Reorganizacja wynikow analiz** → zaglbienia do #overlay-group-entries; checkbox zlewni: auto-check tylko przy 1. wykryciu, reset po usunieciu

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

### Nastepne kroki
1. Weryfikacja `bootstrap.py` na malym bbox (1-2 arkusze): `python -m scripts.bootstrap --bbox "20.95,52.2,21.05,52.25"`
2. Weryfikacja podkladow GUGiK WMTS (czy URL-e dzialaja z `EPSG:3857:{z}`)
3. Instalacja tippecanoe i uruchomienie `generate_tiles.py` na danych produkcyjnych
4. Usuniecie hardcoded secrets z config.py i migrations/env.py
5. Faza 5 (opcjonalna): PMTiles, pre-computed watersheds, MapLibre GL JS
6. CP5: MVP — pelna integracja, deploy

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
- [x] Naprawa bledow frontend/backend (zgloszenie 2026-02-14, 10 pozycji — A1-A5, B1-B4, C1)
- [ ] Naprawa bledow UX (zgloszenie 2026-02-14, 13 pozycji — D1-D4, E1-E3, F1, G1-G4)
- [ ] Testy scripts/ (process_dem.py, import_landcover.py — 0% coverage)
- [x] Utworzenie backend/core/constants.py (M_PER_KM, M2_PER_KM2, CRS_*)
- [ ] Usuniecie hardcoded secrets z config.py i migrations/env.py
- [x] Problem jezior bezodplywowych (endorheic basins) — ADR-020: klasyfikacja + drain points
- [x] CI/CD pipeline (GitHub Actions)
- [x] Audyt QA wydajnosci: LATERAL JOIN, cache headers, TTL cache, partial index, PG tuning, client cache, defer, structlog
- [x] Eliminacja FlowGraph z runtime API (ADR-022): RAM -96%, startup -97%, 548 testow
