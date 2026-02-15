# Changelog

All notable changes to Hydrograf will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Panel wynikow dokowany z prawej:** `#results-panel` przeniesiony wewnatrz `#map-wrapper` z `position: absolute; right: 0` (bylo: `position: fixed; right: 16px`). Slide in/out z CSS transition (`translateX`). Przycisk toggle (chevron) przy krawedzi panelu — zachowanie identyczne jak panel "Warstwy" (lewa strona). Kontrolki zoom Leaflet przesuwaja sie automatycznie gdy panel jest otwarty (`#map-wrapper.results-visible`).
- **Ikony chevron zamiast hamburger/minus:** layers toggle `☰` → `›`/`‹`, usuniety przycisk minimize `−` z naglowka panelu wynikow, usuniety `#results-restore` button
- **Escape: pojedynczy = zwin, podwojny = zamknij:** single Escape zwija panel (slide out, overlay na mapie zostaje); double Escape (w ciagu 400ms) zamyka calkowicie jak `×` (czysc overlay + marker)
- **Usuniety draggable na panelu wynikow:** panel jest teraz dokowany, nie przesuwalny (profil terenu nadal draggable)
- **Krzywa hipsometryczna:** sekcja "Rzezba terenu" zmieniona z histogramu slupkowego na krzywa hipsometryczna (scatter + line); os Y: wysokosc [m n.p.m.], os X: % powierzchni powyzej (0–100, co 20)

### Fixed (4 bugfixes — G1-G4, panel warstw i dane)
- **G1 — histogram za maly:** wysokosc `.chart-container` zwiekszona z 160px do 240px
- **G2 — brak pokrycia terenu:** naprawiono parsowanie nazw warstw GeoPackage (OT_PTLZ_A → PTLZ); zaimportowano 38560 rekordow BDOT10k (12 warstw, 7 kategorii) do tabeli `land_cover`
- **G3 — kolejnosc panelu warstw:** "Podklady kartograficzne" przeniesione na dol panelu (nowa kolejnosc: Warstwy podkladowe → Wyniki analiz → Podklady kartograficzne)
- **G4a — zaglbienia:** przeniesione do grupy "Warstwy podkladowe" (nowy kontener `#overlay-group-entries`)
- **G4b — checkbox zlewni:** auto-check tylko przy pierwszym wykryciu; odznaczenie recznie jest respektowane przy kolejnych wyznaczeniach; reset po usunieciu warstwy

### Fixed (4 bugfixes — D1-D4, profil terenu)
- **D1 — profil nie wyswietla wynikow:** `showProfileError()` przyjmuje `canvasId` zamiast hardkodowanego `#chart-profile`; w `activateDrawProfile().catch()` panel `#profile-panel` jest pokazywany przed renderowaniem bledu
- **D2 — duplikaty wierzcholkow dblclick:** guard w `addDrawVertex()` ignoruje duplikaty z sekwencji click+click+dblclick; `finishDrawing()` zmienia styl linii z dashed blue na solid
- **D3 — linia pozostaje po Escape:** `cancelDrawing()` czysci `profileLine`; `onMapClick()` w trybie profile re-aktywuje rysowanie gdy nie trwa (user moze kliknac mape po Escape)
- **D4 — akordeon acc-profile usuniety:** akordeon `#acc-profile` usuniety z `#results-panel`; przycisk "Ciek glowny" usuniety (tymczasowo — auto-profil do wdrozenia pozniej)

### Added (profil terenu — interaktywnosc)
- **Hover na profilu terenu:** przesuwanie myszy nad wykresem pokazuje czerwony marker na narysowanej linii (interpolacja wzdluz wierzcholkow) + pionowa linia crosshair na wykresie
- **DEM volume mount:** `docker-compose.yml` montuje `data/e2e_test` jako `/data/dem` — profil terenu dziala w kontenerze

### Changed (profil terenu — osobny panel)
- **`#profile-panel` (nowy floating panel):** niezalezny od "Parametrow zlewni", pozycja left-bottom, draggable, close button
- **`profile.js` refaktor:** `activateDrawProfile()` renderuje w `#chart-profile-standalone` zamiast przejmowac `#results-panel`; nowa funkcja `hideProfilePanel()`
- **`map.js` — cofanie wierzcholkow:** `undoLastVertex()` + Backspace handler w trybie rysowania
- **Chart.js fix:** canvasy wykresow owiniete w `.chart-container` (height: 160px) — zapobiega rozciaganiu przez `maintainAspectRatio: false`
- **`app.js`:** init close/draggable na `#profile-panel`, czyszczenie profilu przy zmianie trybu

### Fixed (10 bugfixes — A1-A5, B1-B4, C1)
- **A1 — odznaczanie zlewni:** przycisk "×" w panelu wyników teraz czyści warstwę zlewni z mapy (`clearWatershed`, `clearSelectionBoundary`, `clearCatchmentHighlights`, `clearProfileLine`)
- **A2 — min_area zagłębień:** domyślny filtr min_area zmieniony z 0 na 100 m² (API + frontend)
- **A3 — próg FA:** domyślny próg flow accumulation zmieniony z 10000 na 100000 m² (tiles.py + app.js + layers.js)
- **A4 — histogram height:** wysokość canvas histogramu wysokości zmieniona z 20px na 140px
- **A5 — BDOT opacity:** zbiorniki wodne BDOT10k ukrywane całkowicie przy opacity=0 (weight + fillOpacity + opacity)
- **B1 — profil DEM error:** zamiana alert() na inline Bootstrap alert-warning gdy DEM niedostępny (503) lub inny błąd
- **B3 — hydrogram ukryty:** sekcja hydrogramu ukryta z badge "w przygotowaniu" (d-none + tekst nagłówka)
- **C1 — usunięcie cell_count:** pole `cell_count` usunięte z WatershedResponse, 3 endpointów, frontendu i dokumentacji

### Added (nowe funkcje — B2, B4)
- **B2 — tryb "Profil":** nowy przycisk w toolbar pozwalający rysować profil terenu niezależnie od zlewni
- **B4 — traverse_to_confluence:** nowa metoda w CatchmentGraph — BFS upstream z zatrzymaniem na konfluencji, parametr `to_confluence` w select-stream

### Removed
- Pole `cell_count` z `WatershedResponse` i powiązane wyświetlanie w UI (wartość zawsze wynosiła 0 po migracji z FlowGraph)

### Changed (eliminacja FlowGraph z runtime — ADR-022)
- **`core/watershed_service.py` (nowy modul):** ~400 linii reużywalnych funkcji wyekstrahowanych z `select_stream.py` — `find_nearest_stream_segment()`, `merge_catchment_boundaries()`, `get_segment_outlet()`, `compute_watershed_length()`, `get_main_stream_geojson()`, `get_main_stream_coords_2180()`, `build_morph_dict_from_graph()`
- **`watershed.py` endpoint rewrite:** FlowGraph BFS (19.7M) → CatchmentGraph BFS (87k) + `watershed_service` — boundary z ST_Union, main_stream_geojson naprawiony (było broken/None)
- **`hydrograph.py` endpoint rewrite:** j.w., morph_dict z `build_morph_dict_from_graph(cn=cn)` → `WatershedParameters.from_dict()`
- **`select_stream.py` refactor:** 6 lokalnych funkcji (~155 LOC) zastąpionych importami z `watershed_service`, `_get_outlet_elevation()` → `stats["elevation_min_m"]` z CatchmentGraph
- **`profile.py` rewrite:** SQL LATERAL JOIN na 19.67M wierszach `flow_network` → bezpośredni odczyt z pliku DEM przez rasterio + pyproj transformer
- **`api/main.py`:** usunięte ładowanie FlowGraph z lifespan (~1 GB RAM, ~90s startup)
- **`core/flow_graph.py`:** oznaczony jako DEPRECATED — zachowany dla skryptów CLI
- **`core/watershed.py`:** legacy functions (find_nearest_stream, traverse_upstream) zachowane dla CLI
- **`docker-compose.yml`:** API memory limit 3G → 512M, nowa zmienna `DEM_PATH`
- **`core/config.py`:** nowe pole `dem_path` w Settings
- **`core/constants.py`:** nowa stała `DEFAULT_THRESHOLD_M2 = 100`
- **29 nowych testów:** 25 unit (test_watershed_service.py) + 4 integracyjne; łącznie 548 testów

### Documentation (audyt dokumentacji)
- **9 plikow .md zaktualizowanych:** ARCHITECTURE, CLAUDE, DATA_MODEL, SCOPE, QA_REPORT, TECHNICAL_DEBT, COMPUTATION_PIPELINE, README, PROGRESS
- **ARCHITECTURE.md v1.4:** `parameters.py`→`morphometry.py`, sygnatury, +catchment_graph.py/constants.py, +2 endpointy
- **COMPUTATION_PIPELINE.md:** +faza CatchmentGraph (ADR-021), fix LOC (~2800→~700 orchestrator)
- **QA_REPORT.md:** nota deprecation (175→519 testow, CORS fixed, CI/CD)
- **README.md:** CP3→CP4, tabela endpointow rozszerzona z 4 do 10

### Deployment
- Migracja 013 zastosowana na bazie produkcyjnej
- Obraz API przebudowany z commitami: LATERAL JOIN, cache, logging, constants

### Performance (audyt QA — wydajnosc)
- **Profile LATERAL JOIN:** zamiana N+1 correlated subquery na `CROSS JOIN LATERAL` w `profile.py` — lepszy plan KNN na 19.7M wierszy (~50-100ms oszczednosci/req)
- **Cache-Control headers:** `public, max-age=3600` na endpointach watershed, profile, select-stream, depressions — 0ms na powtorne zapytania
- **TTL cache traverse_upstream:** `cachetools.TTLCache(128, 3600s)` w FlowGraph — workflow delineate→hydrograph reuzytkowuje BFS (~100-400ms oszczednosci)
- **Partial GiST index (migracja 013):** `idx_flow_network_stream_geom WHERE is_stream=TRUE` — KNN na ~87k stream cells zamiast 19.7M
- **PostgreSQL tuning:** `effective_cache_size=1536MB`, `random_page_cost=1.1` (SSD), `jit=off` (szybsze proste zapytania KNN)
- **Land cover merge:** `hydrograph.py` uzywa `get_land_cover_for_boundary()` zamiast osobnego `calculate_weighted_cn()` — eliminacja duplikatu spatial intersection
- **Client-side cache:** `api.js` — Map cache (50 wpisow, TTL 5min) dla delineateWatershed, selectStream, getTerrainProfile — instant response na powtorne klikniecie
- **JS defer + preconnect:** `defer` na 13 script tagow, `preconnect` do CDN — szybsze First Contentful Paint
- **DEM fetch cache:** `force-cache` na metadata fetch w `map.js`

### Added (devops + code quality)
- **GitHub Actions CI** (`.github/workflows/ci.yml`): lint (ruff), test (pytest z PostGIS service container), security audit (pip-audit)
- **Pre-commit hooks** (`.pre-commit-config.yaml`): ruff check+format, trailing whitespace, YAML lint, large file guard
- **Structured logging** (`structlog`): JSON w produkcji, console w DEBUG; middleware `request_id` (X-Request-ID) per-request traceability
- **`core/constants.py`:** scentralizowane stale — `CRS_PL1992`, `CRS_WGS84`, `M_PER_KM`, `M2_PER_KM2`, `DEFAULT_CN`, `HYDROGRAPH_AREA_LIMIT_KM2`, `MAX_WATERSHED_CELLS`

### Changed (refactor)
- **Dedup shape indices:** usunieto `_compute_shape_indices()` z `select_stream.py`, import kanoniczny `calculate_shape_indices()` z `core/morphometry.py` (-30 LOC)
- **SessionLocal.configure():** przeniesiony z per-request `get_db()`/`get_db_session()` do jednorazowego `get_db_engine()`
- **Migracja 013:** partial GiST index na `flow_network WHERE is_stream = TRUE`

### Fixed
- **19 ruff warnings:** E501 (line too long), B905 (zip strict=), SIM108 (ternary operator)
- **ruff format:** 19 plikow przeformatowanych

### Dependencies
- `cachetools>=5.3.0` — TTL cache dla FlowGraph
- `structlog>=24.1.0` — structured logging

### Added (graf zlewni czastkowych — ADR-021)
- **`core/catchment_graph.py`** (nowy modul): in-memory graf zlewni czastkowych (~87k wezlow, ~8 MB) z numpy arrays + scipy sparse CSR matrix. Metody: `load()`, `find_catchment_at_point()`, `traverse_upstream()`, `aggregate_stats()`, `aggregate_hypsometric()`. Zaladowany przy starcie API obok FlowGraph.
- **Migracja 012:** 6 nowych kolumn w `stream_catchments`: `downstream_segment_idx`, `elevation_min_m`, `elevation_max_m`, `perimeter_km`, `stream_length_km`, `elev_histogram` (JSONB). Indeks `idx_catchments_downstream`.
- **`compute_downstream_links()`** w `stream_extraction.py`: wyznaczanie grafu connectivity — follow fdir 1 komorke z outlet kazdego segmentu → downstream segment label
- **`zonal_min()`** i **`zonal_elevation_histogram()`** w `zonal_stats.py`: nowe funkcje statystyk strefowych — min elewacji per label, histogram wysokosci z fixed interval 1m
- **Pre-computed stats** w pipeline: elevation min/max, perimeter_km, stream_length_km, elev_histogram obliczane w `polygonize_subcatchments()` i zapisywane przez `insert_catchments()`
- **19 testow jednostkowych** `test_catchment_graph.py`: BFS traversal, aggregate stats, hypsometric curve, find_catchment_at_point
- **7 testow** `test_zonal_stats.py`: zonal_min (3) + zonal_elevation_histogram (4)

### Changed (graf zlewni czastkowych)
- **`select_stream.py` — calkowity rewrite:** graf zlewni zamiast rastra. Flow: ST_Contains → BFS graph → aggregate numpy → ST_Union boundary → derived indices. Usunieto zaleznosc od FlowGraph i operacji rastrowych.
- **`api/main.py`:** ladowanie CatchmentGraph w lifespan obok FlowGraph
- **`db_bulk.py insert_catchments()`:** rozszerzony o 6 nowych kolumn + JSONB histogram
- **`stream_extraction.py vectorize_streams()`:** dodany `_outlet_rc` (outlet cell per segment)
- **`stream_extraction.py polygonize_subcatchments()`:** rozszerzony o elevation min/max, perimeter, stream_length, histogram, downstream_segment_idx
- **`test_select_stream.py`:** przepisany z CatchmentGraph mocks (8 testow)

### Fixed (audyt frontend — 5 bugow)
- **Memory leak wykresow hydrogramu:** `hydrograph.js` tworzyl `new Chart()` bez zapisywania instancji — dodano lokalny rejestr `_charts` z `destroy()` przed ponownym tworzeniem
- **Memory leak tooltipow:** `map.js` — tooltip ciekow/zlewni czastkowych tworzony ponownie bez usuwania starego; dodano `removeLayer()` przed kazdym `mouseover`
- **Broken depressions filters:** `depressions.js` — `document.getElementById('dep-vol-min')` zwracalo null (brak elementow w HTML); dodano null-guard z early return
- **Dead code:** `profile.js` — usunieto 3 nieuzywane zmienne (`drawingVertices`, `drawingMarkers`, `drawingPolyline`) i ich martwe przypisania
- **Polling CPU waste:** `layers.js` — `setInterval(fn, 500)` sprawdzajacy warste zlewni; zamieniono na event-driven `notifyWatershedChanged()` wywolywany z `app.js`

### Added (audyt frontend — UX + security + a11y)
- **Loading cursor:** kursor `wait` na mapie podczas wywolan API (nowa funkcja `setLoadingCursor` w `map.js`)
- **Banner instrukcji rysowania:** „Klik = wierzcholek, Podwojny klik = zakoncz, Esc = anuluj" wyswietlany na dole mapy w trybie rysowania profilu
- **Feedback bledow profilu:** `alert()` zamiast cichego `console.warn` przy bledach profilu terenu
- **Guard hydrogramu:** sprawdzenie `hydrograph_available` przed wywolaniem API generowania hydrogramu
- **CDN integrity hashes:** dodano `integrity="sha384-..."` do Chart.js 4.4.7 i Leaflet.VectorGrid 1.3.0
- **VectorGrid plugin guard:** `if (!L.vectorGrid)` w `loadStreamsVector()` i `loadCatchmentsVector()`
- **CSP wzmocniony:** `base-uri 'self'; form-action 'self'` + naglowek `Strict-Transport-Security` (HSTS)
- **ARIA attributes:** `aria-live` na status, `aria-expanded` na layers toggle, `role="radiogroup"` + `aria-checked` na mode buttons, `role="img"` + `aria-label` na 5 canvasach chartow
- **Keyboard a11y:** `tabindex="0"` + Enter/Space na akordeonach, `focus-visible` na mode buttons i layer items

### Changed (audyt frontend)
- **Accordion max-height:** 800px → 2000px w `glass.css` (zapobiega obcinaniu duzych sekcji)
- **Usunieto dead CSS:** sekcja `.dual-slider` (~55 linii) z `style.css` — nieuzywana przez zaden element HTML

### Fixed (4 krytyczne bledy post-e2e)
- **Stream burning — zla warstwa BDOT10k (KRYTYCZNY):** `burn_streams_into_dem()` czytal domyslna warstwe GeoPackage (OT_PTWP_A — jeziora poligonowe) zamiast warstw liniowych ciekow. Naprawiono: wykrywanie multi-layer GPKG via `fiona.listlayers()`, ladowanie warstw SWRS/SWKN/SWRM (liniowe) + PTWP (poligonowe), `pd.concat`. Wynik: 4 warstwy, 10726 features, 1.07M cells burned, max_acc +156% (8.85M vs 3.45M).
- **select-stream 500:** zapytanie SQL odwolywal sie do nieistniejącej kolumny `segment_idx` w tabeli `stream_network` — naprawiono na `id`
- **Wydajnosc MVT:** GZip middleware (FastAPI `GZipMiddleware`), czesciowe indeksy GIST per threshold (migracja 011), cache TTL 1 dzien, `minZoom: 12` dla catchments, nginx gzip dla protobuf. Kompresja: streams 41%, catchments 64%.
- **UI diagnostyka:** `console.warn` zamiast cichego `catch(() => null)` w BDOT loaderach, CSP `img-src` += `mapy.geoportal.gov.pl` (GUGiK WMTS)

### Added (e2e pipeline re-run)
- **Migracja 011:** czesciowe indeksy GIST na `stream_network` i `stream_catchments` per threshold (100, 1000, 10000, 100000 m²)
- **Nowy test** `test_multilayer_gpkg_loads_all_layers` — weryfikacja multi-layer GeoPackage w stream burning
- **Re-run pipeline:** 602,092 zaglebie (vs 581,553), GeoPackage 9 warstw / 777,455 features, DEM tiles 267 / 15.5 MB, BDOT GeoJSON (3529 jezior, 7197 ciekow)

### Added (select-stream stats + UI fixes)
- **Pelne statystyki zlewni w trybie "Wybor"**: endpoint `select-stream` zwraca `WatershedResponse` z morfometria, pokryciem terenu, krzywa hipsometryczna, ciekiem glownym
- **Podklady GUGiK WMTS**: ortofotomapa (HighResolution) i mapa topograficzna w panelu warstw
- **8 testow integracyjnych** `test_select_stream.py`: sukces, watershed w odpowiedzi, morfometria, 404, 422

### Changed (select-stream + UI)
- **Siec rzeczna BDOT10k**: `get_stream_stats_in_watershed()` uzywa `source != 'DEM_DERIVED'` z `ST_Intersection` dla dokladnych dlugosci w granicach zlewni
- **Histogram**: 10-25 klas (5m/klase), krotsza etykiety osi X (`Math.round(hLow)`), wysokosc 100px, rotacja 45-90 stopni
- **Akordeony**: inline `onclick` zastapione event listenerami w `app.js init()`

### Fixed (UI)
- **Przyciski zamkniecia/minimalizacji panelu**: `draggable.js` nie przechwytuje klikniec w `.results-btn` (early return w `onPointerDown`)
- **Suwaki przezroczystosci**: `overflow-x: hidden`, `padding-left: 0.8rem`, `flex-wrap: wrap`, `box-sizing: border-box` w panelu warstw
- **Frontend select mode**: pelne statystyki zlewni (zamiast tylko StreamInfo) wyswietlane po kliknieciu cieku

### Added (DEM tile pyramid + kolejnosc warstw)
- **`scripts/generate_dem_tiles.py`**: generacja piramidy kafelkow XYZ z rastra DEM — koloryzacja hipsometryczna + hillshade → RGBA GeoTIFF → `gdal2tiles.py --xyz` (zoom 8–18, nearest-neighbor, `--processes=4`)
- **`utils/dem_color.py`**: wspolny modul kolorow DEM — `COLOR_STOPS`, `build_colormap()`, `compute_hillshade()` wyekstrahowane z `generate_dem_overlay.py`
- **Custom panes** w `map.js`: kolejnosc warstw z-index — demPane (250) → catchmentsPane (300) → streamsPane (350); NMT zawsze pod zlewniami i ciekami
- **`L.tileLayer` z fallback**: DEM ladowany jako kafelki XYZ (`/data/dem_tiles/{z}/{x}/{y}.png`) z progresywnym ładowaniem; fallback na `L.imageOverlay` gdy `dem_tiles.json` brak

### Changed (DEM tile pyramid)
- **`generate_dem_overlay.py`**: refaktor — import `COLOR_STOPS`, `build_colormap`, `compute_hillshade` z `utils.dem_color` zamiast lokalnych definicji
- **`map.js` MVT layers**: `pane: 'streamsPane'` dla ciekow, `pane: 'catchmentsPane'` dla zlewni czastkowych — gwarancja poprawnej kolejnosci renderowania

### Added (frontend redesign — 7 poprawek UX)
- **Tryb wyboru obiektow**: toolbar "Zlewnia/Wybor" na gorze mapy, przelaczanie miedzy wyznaczaniem zlewni a selekcja ciekow
- **Endpoint `POST /api/select-stream`**: selekcja segmentu cieku + traversal upstream + granica zlewni + upstream segment indices
- **Podswietlanie zlewni czastkowych**: po kliknieciu cieku w trybie "Wybor" — upstream catchments podswietlone na zielono, reszta wygaszona
- **Histogram wysokosci**: `renderElevationHistogram()` w charts.js — wykres slupkowy pasm wysokosciowych zamiast krzywej hipsometrycznej
- **Kolorowanie ciekow po flow accumulation**: gradient log10 od jasnego (male zlewnie) do ciemnego (duze) zamiast dyskretnych kolorow Strahlera
- **Debounce klikniec**: 300ms debounce na onMapClick — zapobiega podwojnym wywolaniom API

### Added (frontend — legendy + UX)
- **Legendy warstw**: cieki (gradient flow acc) i zlewnie czastkowe (paleta Strahler) — automatyczne wyswietlanie/ukrywanie przy przelaczaniu warstw
- **Zoom do danych na starcie**: mapa automatycznie przybliża się do zasiegu NMT po zaladowaniu metadanych
- **Warstwa "Zlewnia" reaktywna**: wpis w panelu warstw automatycznie aktywuje sie po wyznaczeniu zlewni (checkbox + suwak przezroczystosci + zoom)

### Fixed (frontend + backend)
- **Zoom controls**: przeniesione z topleft (kolidowal z layers panel) do topright
- **Przezroczystosc zlewni czastkowych**: naprawiony fillOpacity (1.0 initial zamiast 0.3, bez mnoznika ×0.5 w setCatchmentsOpacity)
- **Rate limiting 429**: oddzielna strefa nginx `tile_limit` (30r/s) dla `/api/tiles/` — nie interferuje z `api_limit` (10r/s) dla reszty API
- **Flicker przezroczystosci**: suwak opacity dla ciekow i zlewni uzywa CSS container opacity zamiast redraw() — brak migotania
- **Blad serwera select-stream**: dodano obsluge ValueError (zlewnia za duza/za mala) + uzycie snapped outlet coords zamiast oryginalnego klikniecia

### Added (endorheic lake drain points — ADR-020)
- **`classify_endorheic_lakes()`** w `core/hydrology.py`: klasyfikacja zbiornikow wodnych z BDOT10k (OT_PTWP_A) jako bezodplywowe/przeplywowe na podstawie topologii ciekow i elewacji DEM
- **Klastrowanie zbiornikow:** bufor 20m + `unary_union` — stykajace sie jeziora i mokradla tworza klaster; odpływ w dowolnym elemencie klastra → caly klaster przepływowy
- **`_sample_dem_at_point()`**: probkowanie DEM z fallback na najblizszego sasiada gdy komorka jest NoData
- **Wstrzykniecie drain points** w `process_hydrology_pyflwdir()`: nowy parametr `drain_points`, NoData po fill_holes / przed pyflwdir
- **Krok 2b w `process_dem.py`**: automatyczna klasyfikacja jezior gdy `--burn-streams` wskazuje GPKG z OT_PTWP_A
- **20 testow** w `test_lake_drain.py`: klasyfikacja, probkowanie DEM, klastrowanie, drain point injection, integracja pipeline

### Changed
- **`burn_streams_into_dem()`**: domyslna glebokosc wypalania ciekow zwiekszona z 5m do 10m

### Added (frontend — warstwy BDOT10k + wyłączanie podkładu)
- **Zbiorniki wodne BDOT10k** w `map.js` + `layers.js`: warstwa GeoJSON z poligonami z OT_PTWP_A, checkbox + suwak przezroczystosci
- **Cieki BDOT10k** w `map.js` + `layers.js`: warstwa GeoJSON z liniami z OT_SWRS_L/SWKN_L/SWRM_L, kolorowanie wg typu
- **Opcja "Brak"** w podkladach kartograficznych: mozliwosc calkowitego wylaczenia warstwy podkladowej
- **GeoJSON export**: pliki `bdot_lakes.geojson` + `bdot_streams.geojson` w `frontend/data/`
- **nginx**: obsluga plikow `.geojson`, kompresja `application/geo+json`

### Added (e2e integration tests)
- **test_profile.py** (13 testow): `POST /api/terrain-profile` — struktura odpowiedzi, walidacja geometry (LineString/Point), n_samples limits, pusty wynik 404, multi-point LineString
- **test_depressions.py** (17 testow): `GET /api/depressions` — GeoJSON FeatureCollection, properties, filtry (volume/area/bbox), walidacja ujemnych wartosci 422, zaokraglenia, sortowanie
- **test_tiles.py** (21 testow): `GET /api/tiles/streams|catchments/{z}/{x}/{y}.pbf` + `GET /api/tiles/thresholds` — content-type protobuf, cache headers, puste tile, threshold walidacja, rozne zoom levels, graceful fallback brak tabeli

### Fixed (stream_network deduplication — ADR-019)
- **Migracja 010:** `idx_stream_unique` nie zawieral `threshold_m2` — cieki z roznych progow FA w tym samym miejscu byly traktowane jako duplikaty i cicho pomijane (`ON CONFLICT DO NOTHING`). Utrata: 2257 segmentow (26-42% przy wyzszych progach). Naprawiono: dodano `threshold_m2` do unique index.
- **Diagnostyka:** warning w `insert_stream_segments()` gdy segmenty pominiete przez constraint
- **Walidacja:** sprawdzenie stream_count vs catchment_count per threshold w `process_dem.py`
- **5 nowych testow:** multi-threshold insert, warning on dropped, empty segments, TSV threshold
- **Pipeline re-run:** migracje 008-010 zastosowane, pipeline z `--clear-existing` — siec ciekow naprawiona: progi 1000/10000/100000 m² idealnie sparowane ze zlewniami, prog 100 m² ma 9 geohash collisions (0.012%)

### Added (PostGIS optimization — ADR-018)
- **In-memory flow graph** (`core/flow_graph.py`): ladowanie grafu 19.7M komorek do numpy arrays + scipy sparse CSR matrix przy starcie API, BFS traversal via `breadth_first_order` (~50-200ms vs 2-5s SQL CTE)
- **Pre-generacja MVT tiles** (`scripts/generate_tiles.py`): eksport PostGIS → GeoJSON → tippecanoe .mbtiles → PMTiles; auto-detekcja w frontend z API fallback
- **Migracja 009:** partial GIST index na `stream_network WHERE source = 'DEM_DERIVED'`
- **18 nowych testow:** test_flow_graph.py (traversal, resolve, cells, loaded state)

### Removed
- DEM raster tile endpoint (`GET /tiles/dem/`, `GET /tiles/dem/metadata`) — martwy kod, frontend uzywa statycznego PNG
- `scripts/import_dem_raster.py` — niepotrzebny po usunieciu DEM tile endpoint
- Helpers: `_build_colormap()`, `_get_elev_range()`, `_tile_to_bbox_2180()`, `_empty_tile_png()` z tiles.py

### Changed
- `watershed.py traverse_upstream()`: in-memory BFS (domyslnie) + SQL CTE fallback
- `api/main.py lifespan`: ladowanie FlowGraph przy starcie API
- `docker-compose.yml`: API memory limit 1G → 3G (numpy arrays + sparse matrix)
- `tiles.py`: z 427 do 204 linii (usuniety DEM raster endpoint + helpers)

### Added (refactor + perf)
- **Refaktoryzacja process_dem.py (ADR-017):** podzial monolitu 2843 linii na 6 modulow `core/`:
  - `core/raster_io.py` — odczyt/zapis rastrow (ASC, VRT, GeoTIFF)
  - `core/hydrology.py` — hydrologia: fill, fdir, acc, stream burning
  - `core/morphometry_raster.py` — nachylenie, aspekt, TWI, Strahler
  - `core/stream_extraction.py` — wektoryzacja ciekow, zlewnie czastkowe
  - `core/db_bulk.py` — bulk INSERT via COPY, timeout management
  - `core/zonal_stats.py` — statystyki strefowe (bincount, max)
- **Numba @njit:** `_count_upstream_and_find_headwaters()` w `stream_extraction.py` (~300s → ~10s)
- **NumPy wektoryzacja:** `create_flow_network_tsv()` + `insert_records_batch_tsv()` (~120s → ~5s, 490MB → 200MB RAM)
- **Wspolne gradienty Sobel:** `_compute_gradients()` reuzywane przez slope i aspect (~12s → ~7s)
- **Migracja 008:** indeksy filtrujace na `depressions` (volume_m3, area_m2, max_depth_m)
- **Context manager:** `override_statement_timeout()` w `db_bulk.py` — centralizacja timeout
- **85 nowych testow:** test_zonal_stats, test_raster_io, test_hydrology, test_stream_extraction, test_db_bulk

### Added
- `GET /api/tiles/thresholds` — endpoint zwracajacy dostepne progi FA z bazy (`SELECT DISTINCT threshold_m2`)
- `docs/COMPUTATION_PIPELINE.md` — kompletna dokumentacja procedury obliczeniowej backendu
- Wektoryzacja ciekow MVT, multi-prog FA, hillshade, zaglbienia preprocessing (CP4 Faza 3):
  - **Migracja 005:** kolumna `threshold_m2 INTEGER NOT NULL DEFAULT 100` w `stream_network`, indeks kompozytowy `idx_stream_threshold(threshold_m2, strahler_order)`
  - **Multi-prog FA:** `--thresholds` CLI w `process_dem.py` (np. `100,1000,10000,100000` m²), osobna siec ciekow (Strahler + wektoryzacja) per prog FA, `insert_stream_segments()` z `threshold_m2`
  - **MVT endpoint:** `GET /api/tiles/streams/{z}/{x}/{y}.pbf?threshold=N` — Mapbox Vector Tiles z PostGIS (`ST_AsMVT`), `ST_Simplify` wg zoom, cache 1h, filtr progu FA
  - **Frontend MVT:** Leaflet.VectorGrid 1.3.0 CDN, `loadStreamsVector()` z kolorami Strahler (8-stopniowa paleta niebieska), selector progu FA (dropdown: 100/1000/10000/100000 m²), tooltip na klik (rzad, dlugosc, zlewnia)
  - **Hillshade:** `compute_hillshade()` w `generate_dem_overlay.py` — cieniowanie Lambertian (azimuth=315°, altitude=45°), multiply blend z rampa hipsometryczna (`rgb * (0.3 + 0.7 * hillshade)`), gradient w CRS zrodlowym (metry), `--no-hillshade` CLI
  - **Preprocessing zaglebie:** nowy skrypt `generate_depressions.py` — depth map (filled-original DEM), connected components (`scipy.ndimage.label`), wektoryzacja (`rasterio.features.shapes`), metryki (volume_m3, area_m2, max/mean_depth_m), COPY bulk insert do tabeli `depressions`
  - **Overlay zaglebie:** generacja `depressions.png` + `depressions.json` w `generate_depressions.py` — depth colormap (gradient niebieski), reprojekcja 2180→4326, `--output-png`/`--output-meta` CLI

### Changed
- `layers.js` — dynamiczne progi FA z backendu zamiast hardcoded listy: `fetch('/api/tiles/thresholds')` → `populateThresholdSelect()`; domyslny prog = pierwszy dostepny w bazie (nie zawsze 10000)
- `map.js` — `currentThreshold` i `currentCatchmentThreshold` domyslnie `null` (ustawiane dynamicznie z frontendu)

### Fixed
- Dropdown progu FA pokazywal 4 opcje (100/1000/10000/100000 m²) mimo ze baza miala dane tylko dla jednego progu — teraz dropdown dynamicznie pobiera dostepne progi z `GET /api/tiles/thresholds`
- Duplikat `var layer` w checkbox handlerach `addStreamsEntry()` i `addCatchmentsEntry()` — deklaracja przeniesiona przed `if`/`else`

### Changed (previous)
- `map.js` — zamiana rasterowego overlay ciekow (`L.imageOverlay` + `streams.png`) na wektorowy MVT (`L.vectorGrid.protobuf`)
- `layers.js` — nowa kontrolka `addStreamsEntry()` z dropdown progu FA zamiast prostego checkboxa
- `tiles.py` — nowa funkcja `_tile_to_bbox_3857()` i endpoint MVT streams obok istniejacego DEM tiles
- `process_dem.py` — parametr `thresholds: list[int]` w `process_dem()`, petla po progach z reuzyciem `compute_strahler_order()` i `vectorize_streams()`

### Added (previous)
- Frontend CP4 Faza 2 — redesign glassmorphism + nowe funkcjonalnosci:
  - **Redesign wizualny (WP1):** glassmorphism (glass.css), mapa 100% szerokosc, plywajacy przesuwalny panel wynikow (draggable.js), sekcje akordeonowe, minimalizacja do ikony, bottom sheet na mobile
  - **Panel warstw (WP2):** akordeon z grupami (Podklady / Warstwy podkladowe / Wyniki analiz), przelaczanie podkladow (OSM / ESRI Satellite / OpenTopoMap), per-layer opacity + zoom-to-extent
  - **Pokrycie terenu (WP3):** `LandCoverStats` model, integracja `get_land_cover_for_boundary()` w watershed response, wykres donut Chart.js z paleta PL (las/laka/grunt_orny/zabudowa/woda)
  - **Krzywa hipsometryczna (WP3):** Chart.js liniowy z wypelnieniem, dane z `include_hypsometric_curve=true`
  - **Profil terenu (WP4):** endpoint `POST /api/terrain-profile` (sampling po flow_network), tryb auto (ciek glowny) + rysowanie polilinii na mapie (click/dblclick/Escape)
  - **Zaglebie terrain (WP5):** migracja Alembic 004 (tabela `depressions`), endpoint `GET /api/depressions` z filtrami (volume/area/bbox), overlay loader, suwaki SCALGO-style
  - **Hydrogram (WP6):** formularz scenariusza (duration + probability z `/api/scenarios`), wykres hydrogramu + hietogram, tabela bilansu wodnego
  - `main_stream_geojson` (LineString WGS84) w watershed response — transformacja coords 2180→4326
- Nowe pliki frontend: `glass.css`, `draggable.js`, `charts.js`, `layers.js`, `profile.js`, `hydrograph.js`, `depressions.js`
- Nowe pliki backend: `api/endpoints/profile.py`, `api/endpoints/depressions.py`
- Chart.js 4.4.7 CDN w `index.html`
- Nginx CSP: dodano `server.arcgisonline.com` i `*.tile.opentopomap.org` do `img-src`

### Changed
- `index.html` — przebudowa z 2-kolumnowego layoutu na full-screen mapa + plywajacy panel
- `style.css` — glassmorphism, CSS variables, responsive bottom sheet (mobile)
- `app.js` — floating panel (show/hide/minimize/restore), delegacja warstw do layers.js
- `map.js` — base layer management, drawing mode (polyline), profile line display, `getWatershedLayer()`
- `api.js` — 6 nowych metod API, `include_hypsometric_curve=true` domyslnie
- `schemas.py` — `LandCoverCategory`, `LandCoverStats`, `TerrainProfileRequest/Response`, `main_stream_geojson` i `land_cover_stats` w `WatershedResponse`
- `watershed.py` — integracja land cover stats + main stream coords transform

- Frontend CP4 Faza 1 — mapa + wyznaczanie zlewni + parametry:
  - `frontend/index.html` — layout Bootstrap 5 (navbar + mapa + panel boczny)
  - `frontend/css/style.css` — style (crosshair, responsywnosc, tabele parametrow)
  - `frontend/js/api.js` — klient API (delineateWatershed, checkHealth, polskie bledy)
  - `frontend/js/map.js` — modul Leaflet.js (OSM, polygon zlewni, marker ujscia)
  - `frontend/js/app.js` — logika aplikacji (walidacja, wyswietlanie ~20 parametrow)
- CDN: Leaflet 1.9.4, Bootstrap 5.3.3 (z integrity hashes)
- Vanilla JS (ES6+, IIFE modules), bez bundlera
- Panel warstw (lewy, chowany) z przyciskiem toggle (hamburger)
- Panel parametrow domyslnie ukryty — auto-otwiera sie po wyznaczeniu zlewni, zamykany X
- Warstwa NMT (WIP): PostGIS raster + endpoint XYZ tiles + kolorystyka hipsometryczna
  - `scripts/import_dem_raster.py` — import DEM GeoTIFF do PostGIS jako kafelki 256x256
  - `api/endpoints/tiles.py` — `GET /api/tiles/dem/{z}/{x}/{y}.png` z PostGIS raster
  - Rampa kolorow: zielony (doliny) → zolty → brazowy → bialy (szczyty), semi-transparent
  - **Status:** backend dziala (tile PNG z bazy), frontend nie wyswietla (do debugowania)
- `scripts/generate_dem_overlay.py` — skrypt generujacy statyczny PNG z NMT (narzedzie pomocnicze)
- `--max-size` w `generate_dem_overlay.py` — downsampling LANCZOS (domyslnie 1024 px)
- `frontend/data/dem.png` + `dem.json` — pre-generowany overlay NMT z metadanymi WGS84 bounds
- `Pillow>=10.0.0` w requirements.txt (rendering tile PNG)
- Kontrolki warstwy NMT w panelu warstw:
  - Przycisk zoom-to-extent (⌖) — `fitDemBounds()` przybliza mape do zasiegu warstwy
  - Suwak przezroczystosci 0–100% — `setDemOpacity()`, pojawia sie po wlaczeniu warstwy
- Warstwa ciekow (Strahler order) jako `L.imageOverlay`:
  - `scripts/generate_streams_overlay.py` — skrypt generujacy PNG z rzedami Strahlera (dyskretna paleta niebieska 1-8, przezroczyste tlo)
  - `frontend/data/streams.png` + `streams.json` — pre-generowany overlay ciekow (48 KB, max order=5)
  - Dylatacja morfologiczna (`maximum_filter`) — grubosc linii proporcjonalna do rzedu (1→3px, 5→11px)
  - `map.js`: `loadStreamsOverlay()`, `getStreamsLayer()`, `fitStreamsBounds()`, `setStreamsOpacity()`
  - `app.js`: refaktor `initLayersPanel()` — wyodrebniony `addLayerEntry()`, dwa wpisy: NMT (30%) i Cieki (0%)

### Fixed
- Overlay NMT i ciekow przesuniety ~26 m wzgledem OSM — reprojekcja rastra do EPSG:4326:
  - Przyczyna: skrypty transformowaly tylko 2 narozniki (SW/NE), a obraz pozostawal w siatce EPSG:2180 obróconej ~0.63° wzgledem WGS84 (zbieznosc poludnikow PL-2000 strefa 6)
  - `generate_dem_overlay.py`: `rasterio.warp.reproject()` z `Resampling.bilinear` zamiast `pyproj` corner-only transform
  - `generate_streams_overlay.py`: dylatacja w EPSG:2180, nastepnie `reproject()` z `Resampling.nearest` (dane kategoryczne)
  - Bounds obliczane z transformu reprojekcji (nie z naroznikow)
  - Dodano `--source-crs` fallback gdy raster nie ma metadanych CRS
- Warstwa NMT "jezdzila" po mapie i miala artefakty — zamiana `L.tileLayer` na `L.imageOverlay`:
  - Przyczyna: `ST_Clip/ST_Resize` nieodpowiednia dla malego rastra (~2km x 2km); przy niskim zoomie DEM bylo rozciagniete na caly kafelek web
  - `map.js`: async `loadDemOverlay()` — fetch `/data/dem.json` → `L.imageOverlay` z georeferencjonowanymi granicami
  - `app.js`: null-guard w `initLayersPanel()` (layer moze byc null przed zaladowaniem)
- Suwak przezroczystosci odwrocony (0% = pelne krycie, 100% = niewidoczne) — dopasowanie do etykiety "Przezr."
- DEM overlay PNG: alpha 200→255 — przezroczystosc sterowana wylacznie przez Leaflet, nie wbudowana w obraz

### Security
- Naglowki bezpieczenstwa nginx: CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy
- Cache statycznych plikow (7d, immutable)
- Ograniczenie portow API (127.0.0.1:8000) i DB (127.0.0.1:5432) — jedyny punkt wejscia z sieci: nginx:8080
- Frontend: wylacznie `textContent` dla danych dynamicznych (brak innerHTML z danymi)

### Fixed
- Dockerfile: dodano `git` do system dependencies (wymagany przez `git+https://` w requirements.txt)
- docker-compose.yml: `effective_cache_size=1G` → `1GB` (poprawna jednostka PostgreSQL)
- Bootstrap 5.3.3 CSS integrity hash (zly hash blokowal zaladowanie stylow → mapa niewidoczna)
- Nginx: `^~` prefix na `/api/tiles/` (regex `.png` przechwytywal tile requesty jako statyczne pliki)

### Fixed
- Ochrona przed resource exhaustion (OOM) w `traverse_upstream()` (ADR-015):
  - Pre-flight check (`check_watershed_size()`) — odrzuca zlewnie >2M komorek przed CTE (<1ms)
  - LIMIT w rekurencyjnym CTE — ogranicza wyniki SQL jako safety net
  - `statement_timeout=30s` w polaczeniach z baza (30s API, 600s skrypty CLI)
  - Docker resource limits: db=2G, api=1G, PostgreSQL tuning (shared_buffers=512MB)
- `MAX_CELLS_DEFAULT` zmniejszony z 10M do 2M (bezpieczne dla 15 GB RAM)

### Tested
- E2E Task 9 (retry): N-33-131-C-b-2 — 4 testy pass:
  - A: 493k cells (0.49 km², 6.5s, Strahler=4, Dd=15.3 km/km²)
  - B: 1.5M cells (1.50 km², 21s, Strahler=4, Dd=14.7 km/km²)
  - C: Pre-flight reject (limit 100k) — natychmiastowe odrzucenie
  - D: Max outlet (1.76M, CTE=2M+1) — LIMIT safety net poprawnie zlapal nadmiar

### Changed
- Aktualizacja Kartograf v0.4.0 → v0.4.1 (BDOT10k hydro, geometry selection, rtree fix)
- Aktualizacja Kartograf v0.3.1 → v0.4.0 (nowe produkty: NMPT, Ortofotomapa, auto-ekspansja godel)
- `download_dem.py`: obsluga `Path | list[Path]` z `download_sheet()` (auto-ekspansja godel grubszych skal)

### Added (Kartograf v0.4.1)
- `download_landcover.py --category hydro` — pobieranie warstw BDOT10k hydrograficznych (SWRS, SWKN, SWRM, PTWP)
- `download_dem.py --geometry` — precyzyjny wybor arkuszy NMT z pliku SHP/GPKG
- `prepare_area.py --with-hydro` — automatyczne pobieranie danych hydro i stream burning

### Added
- Wypalanie ciekow BDOT10k w DEM (`--burn-streams`) — obnizenie DEM wzdluz znanych ciekow przed analiza hydrologiczna (ADR-013)
- 6 nowych testow jednostkowych dla `burn_streams_into_dem()`
- Nowe warstwy rastrowe w preprocessingu DEM (ADR-014):
  - Aspect (`09_aspect.tif`) — ekspozycja stoku 0-360° (N=0, zgodnie z zegarem)
  - TWI (`08_twi.tif`) — Topographic Wetness Index = ln(SCA / tan(slope))
  - Strahler stream order (`07_stream_order.tif`) — rzad cieku wg Strahlera
- Wektoryzacja ciekow z DEM jako LineString w `stream_network` (source='DEM_DERIVED')
- Migracja 003: `strahler_order` w `flow_network`, `upstream_area_km2` i `mean_slope_percent` w `stream_network`
- Wskazniki ksztaltu zlewni: wspolczynnik zwartosci Kc, kolowosci Rc, wydluzenia Re, ksztaltu Ff, szerokosc srednia
- Wskazniki rzezbowe: wspolczynnik rzezbowy Rh, calka hipsometryczna HI
- Krzywa hipsometryczna (opcjonalna, `include_hypsometric_curve=true`)
- Wskazniki sieci rzecznej: gestosc sieci Dd, czest. ciekow Fs, liczba chropowatosci Rn, max rzad Strahlera
- 11 nowych pol w `MorphometricParameters` (Optional, backward compatible)
- `HypsometricPoint` model i `hypsometric_curve` w `WatershedResponse`
- 38 nowych testow jednostkowych (18 DEM + 21 morfometria)
- Flaga `--skip-streams-vectorize` w CLI process_dem

### Removed
- Warstwa `02b_inflated` — zbedna po migracji na pyflwdir (Wang & Liu 2006 obsluguje plaskowyzyzny wewnetrznie)

### Fixed
- `idx_stream_unique` uzywal `ST_GeoHash(geom, 12)` na geometrii EPSG:2180 — naprawiono na `ST_GeoHash(ST_Transform(geom, 4326), 12)`
- `strahler_order=0` dla komorek z acc>=threshold ale pyflwdir order=0 — clamp do min 1
- Duplikaty geohash przy insercie stream segments — `ON CONFLICT DO NOTHING`
- Cieki konczace sie w srodku rastra — wypelnianie wewnetrznych dziur nodata + naprawa zlewow po pysheds
- Przerwane lancuchy downstream_id w flow_network spowodowane NaN fdir i nodata holes

### Changed
- Migracja z pysheds na pyflwdir (Deltares) — mniej zaleznosci, brak temp file, Wang & Liu 2006
- Migracja na .venv-first development workflow (ADR-011)
- Rozdzielenie deps runtime/dev (requirements.txt + pyproject.toml [dev])
- Usuniecie black/flake8 z requirements.txt, dodanie ruff do [dev]
- Aktualizacja docker-compose → docker compose w dokumentacji
- Restrukturyzacja dokumentacji wg shared/standards/DOCUMENTATION_STANDARDS.md
- CLAUDE.md rozbudowany z 14 do ~185 linii (7 sekcji)
- PROGRESS.md skondensowany z 975 do ~71 linii (4 sekcje)
- DEVELOPMENT_STANDARDS.md przepisany z Ruff (zamiast black+flake8)
- IMPLEMENTATION_PROMPT.md przepisany do stanu v0.3.0
- Migracja z black+flake8 na ruff (E, F, I, UP, B, SIM)
- Przeniesienie 6 plików MD z root do docs/

### Tested
- E2E Kartograf v0.4.1: N-33-131-C-b-2 — NMT download (4 sub-sheets), BDOT10k hydro (8.1 MB GPKG), stream burning, 20 rasterow posrednich (~444 MB); Task 9 FAILED (traverse_upstream resource exhaustion, outlet acc=1.76M, mozliwe ograniczenia zasobow Docker)
- E2E pipeline: N-33-131-C-b-2-3 z warstwami 01-09 — 198s, 4.9M komorek, max_strahler=8, 19,005 segmentow (641.6 km), wyniki w `data/results/`
- E2E pipeline: N-33-131-C-b-2-3 z stream burning — 2,856 cells burned, 55s, wyniki w `data/nmt/`
- E2E pipeline: N-33-131-C-b-2-3 z pyflwdir — broken streams: 233→1, max acc +71%, pipeline 17% szybciej
- E2E pipeline: N-33-131-C-b-2-3 (1:10000, 1 arkusz, 4.9M komorek) — flowacc fix verified
- E2E pipeline: N-33-131-C-b (5 m) — Kartograf download, pysheds processing, IMGW precipitation

### Added
- docs/DECISIONS.md — 10 Architecture Decision Records
- .editorconfig (UTF-8, LF, 4 spacje Python, 2 spacje YAML/MD)

### Fixed
- pyproject.toml: readme path outside package root, flat-layout discovery error (editable install)
- Cross-referencje w README.md (ścieżki do docs/)
- Usunięcie rozwiązanego TD-2 z TECHNICAL_DEBT.md (land_cover.py istnieje)
- Naprawa URL repozytorium w pyproject.toml
- 208 błędów ruff naprawionych (202 auto-fix + 6 ręcznie B904)

---

### Added
- `--use-cached` CLI option for `analyze_watershed.py` - skip delineation/morphometry (200x faster re-runs)
- `--tiles` option for specifying exact NMT sheet codes
- `--teryt` option for BDOT10k county code
- `--save-qgis` option for exporting intermediate layers
- `--max-stream-distance` option for outlet search radius
- `load_cached_results()` function for fast hydrograph recalculation
- `core/cn_tables.py` - centralized CN lookup tables for HSG × land cover combinations
- `core/cn_calculator.py` - Kartograf integration for HSG-based CN calculation
- `determine_cn()` function in `core/land_cover.py` - unified CN hierarchy
- 71 new unit tests for CN modules
- Raster utilities: `resample_raster()`, `polygonize_raster()`

### Changed
- **BREAKING**: Precipitation now uses KS (quantile) instead of SG (upper confidence bound)
- Hydrograph generation uses Beta hyetograph convolution for long-duration events
- Beta distribution parameters changed to (2, 5) for asymmetric rainfall
- Increased `max_cells` limit from 5M to 10M
- Refactored `scripts/analyze_watershed.py` - removed ~260 lines of CN logic
- CN calculation now uses modular approach: config → database → Kartograf → default

### Fixed
- Unrealistic Q results caused by using SG instead of KS for design precipitation
- Instantaneous rainfall assumption for long-duration events (now uses convolution)

## [0.3.0] - 2026-01-21

### Added
- Multi-tile DEM mosaic support for large watersheds
- Reverse trace optimization for `find_main_stream` (330x faster)
- COPY-based bulk insert for DEM import (27x faster)
- Land cover integration with weighted CN calculation
- Direct IMGWTools v2.1.0 dependency
- CI/CD pipeline with GitHub Actions (lint, test, coverage)
- Rate limiting in Nginx (10 req/s for API, 30 req/s general)
- `GET /api/scenarios` endpoint for listing valid hydrograph options
- `TECHNICAL_DEBT.md` documenting known issues
- `.pre-commit-config.yaml` for automated code quality checks
- CHECK constraint for `land_cover.category` column
- UNIQUE index for `stream_network` (name + geohash)

### Changed
- CORS configuration now uses environment variable `CORS_ORIGINS`
- Limited CORS methods to GET, POST, OPTIONS
- Disabled CORS credentials for security
- Migrated Pydantic settings from `class Config` to `model_config = SettingsConfigDict`
- Updated `black` to 26.1.0
- Unified line-length to 88 (was 100) for cross-project consistency

### Fixed
- 16 flake8 errors (unused imports, line length, spacing)
- 35 files reformatted with black (17 initial + 18 for line-length)

### Security
- Fixed critical CORS vulnerability (`allow_origins=["*"]` with `allow_credentials=True`)

### Performance
- DEM import: ~3.8 min (was ~102 min)
- `find_main_stream`: ~0.74s (was ~246s)

## [0.2.0] - 2026-01-18

### Added
- Hydrograph generation endpoint (`POST /api/generate-hydrograph`)
- Integration with Hydrolog library for SCS-CN calculations
- Morphometric parameters calculation (area, perimeter, length, slopes)
- Water balance output in hydrograph response
- Land cover support via Kartograf integration

### Changed
- Renamed project from HydroLOG to Hydrograf

## [0.1.0] - 2026-01-15

### Added
- Initial project setup
- Watershed delineation endpoint (`POST /api/delineate-watershed`)
- Health check endpoint (`GET /health`)
- PostgreSQL + PostGIS database schema
- DEM preprocessing script with pysheds
- IMGW precipitation data integration
- Docker Compose deployment configuration

### Documentation
- SCOPE.md - Project scope and requirements
- ARCHITECTURE.md - System architecture
- DATA_MODEL.md - Database schema
- PRD.md - Product requirements

[Unreleased]: https://github.com/Daldek/Hydrograf/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Daldek/Hydrograf/compare/v0.2.2...v0.3.0
[0.2.0]: https://github.com/Daldek/Hydrograf/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Daldek/Hydrograf/releases/tag/v0.1.0
