# PROGRESS — Hydrograf

## Status projektu

| Element | Status | Uwagi |
|---------|--------|-------|
| API (FastAPI + PostGIS) | ✅ Gotowy | 10 endpointow: delineate, hydrograph, scenarios, profile, depressions, select-stream, health, tiles/streams, tiles/catchments, tiles/thresholds. 550 testow. |
| Wyznaczanie zlewni | ✅ Gotowy | traverse_upstream, concave hull |
| Parametry morfometryczne | ✅ Gotowy | area, slope, length, CN + 11 nowych wskaznikow |
| Generowanie hydrogramu | ✅ Gotowy | SCS-CN, 42 scenariusze |
| Preprocessing NMT | ✅ Gotowy | pyflwdir + COPY (3.8 min/arkusz), stream burning |
| Integracja Hydrolog | ✅ Gotowy | v0.5.2 |
| Integracja Kartograf | ✅ Gotowy | v0.4.1 (NMT, NMPT, Orto, Land Cover, HSG, BDOT10k hydro) |
| Integracja IMGWTools | ✅ Gotowy | v2.1.0 (opady projektowe) |
| CN calculation | ✅ Gotowy | cn_tables + cn_calculator + determine_cn() |
| Frontend | 🔶 Faza 4 gotowa | CP4 — tryb wyboru obiektow, flow acc coloring, histogram, debounce, zoom fix |
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

### CP4 — Frontend z mapa ✅
- **Wersja:** v0.4.0
- **Zakres:** Leaflet.js, Chart.js, interaktywna mapa, panel parametrow, glassmorphism, MVT, select-stream, GUGiK WMTS

### CP5 — MVP ⏳
- **Wersja:** v1.0.0 (planowana)
- **Zakres:** Pelna integracja frontend+backend, deploy produkcyjny

## Ostatnia sesja

**Data:** 2026-02-14 (sesja 18)

### Co zrobiono

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
| flow_network | 19,667,662 | 4 progi FA, re-run z CatchmentGraph |
| stream_network | 86,898 | 100: 78186, 1000: 7812, 10000: 827, 100000: 88 (po re-run z migracja 012) |
| stream_catchments | 86,913 | 100: 78186, 1000: 7812, 10000: 827, 100000: 88 + nowe kolumny (downstream, elev, histogram) |
| depressions | 602,092 | re-run po poprawionym stream burning |

### Znane problemy (infrastruktura)
- `generate_tiles.py` wymaga tippecanoe (nie jest w pip, trzeba zainstalowac systemowo)
- FlowGraph (core/flow_graph.py) — DEPRECATED, zachowany dla skryptow CLI, nie ladowany przez API
- 15 segmentow stream_network (prog 100 m²) odrzuconych przez geohash collision — marginalny problem
- Endpoint `profile.py` wymaga pliku DEM (VRT/GeoTIFF) pod sciezka `DEM_PATH` — zwraca 503 gdy brak

### Bledy do naprawy (zgloszenie 2026-02-14)

**Status: ✅ Wszystkie 10 bugów naprawione (sesja 18)**

#### A. Frontend — interakcja z mapa

**A1. Brak odznaczania zlewni** (priorytet: wysoki)
- Po zaznaczeniu (delineate-watershed) lub wybraniu (select-stream) zlewni nie da sie jej odznaczyc
- Przycisk "×" (`results-close`) chowa panel, ale NIE czyści warstwy z mapy (`clearWatershed()` nie jest wywolywany)
- Jedyny sposob odznaczenia: przelaczenie trybu (Zlewnia ↔ Wybor) w `setClickMode()`
- **Lokalizacja:** `app.js:438` (handler `results-close`), `map.js:506-509` (`clearWatershed()`)
- **Propozycja:** Dodac przycisk "Wyczysc" w panelu wynikow LUB podpiac `clearWatershed()` pod przycisk "×"

**A2. Zaglebie widoczne jako "dziury" w poligonie zlewni** (priorytet: wysoki)
- Po wybraniu zlewni wszystkie zaglębienia sa widoczne jako odrebne poligony nakladajace sie na zlewnie
- Brak filtra minimalnej powierzchni — wyswietlane sa nawet mikroskopijne zaglębienia (<1 m²)
- **Lokalizacja:** `depressions.js` (fetchFiltered), `depressions.py` (defaults min_area=0)
- **Propozycja:** Ustawic domyslny filtr `min_area=100` m² (granica odciecia) w API lub frontendzie

**A3. Domyslny prog zlewni czastkowych i ciekow za niski** (priorytet: sredni)
- Po wlaczeniu warstw "Cieki" i "Zlewnie czastkowe" domyslny prog to 100 m² lub 10000 m² — za duzo detali
- **Lokalizacja:** `app.js:272` (fallback `10000`), `tiles.py:63,130` (default `10000`), `constants.py:26` (`DEFAULT_THRESHOLD_M2=100`)
- **Propozycja:** Zmienic domyslny prog na 100 000 m² (frontend fallback + API defaults)

**A4. Wysokosc histogramu w "Rzezba terenu" absurdalnie wysoka** (priorytet: sredni)
- Canvas `chart-hypsometric` ma `height="20"` podczas gdy inne wykresy maja 140-180
- Z `maintainAspectRatio: false` Chart.js rozciaga wykres na caly kontener
- **Lokalizacja:** `index.html:123` (`height="20"`), `charts.js:287-310` (konfiguracja Chart.js)
- **Propozycja:** Zmienic `height="20"` na `height="140"` (zgodnie z innymi wykresami)

**A5. Zbiorniki wodne widoczne przy przezroczystosci 0%** (priorytet: niski)
- Slider "Zbiorniki wodne (BDOT10k)" ustawiony na 100% przezroczystosci nie ukrywa w pelni warstwy
- `setBdotLakesOpacity()` mnozy fillOpacity * 0.4, ale moze nakladac sie z innymi warstwami wodnymi (depressions, BDOT streams)
- **Lokalizacja:** `map.js:633-640` (`setBdotLakesOpacity`), `layers.js:498` (slider config)
- **Propozycja:** Sprawdzic czy nie nakladaja sie warstwy; przy opacity=0 ukrywac warstwe calkowicie (`removeLayer`)

#### B. Backend — logika obliczen

**B1. Profil terenu nie jest generowany** (priorytet: wysoki)
- Profil w sekcji parametrow zlewni ("Ciek glowny") nie jest generowany — prawdopodobnie brak pliku DEM pod `DEM_PATH`
- Przycisk "Ciek glowny" wymaga najpierw wyznaczenia zlewni (wlacza sie dopiero po delineacji z `main_stream_geojson`)
- **Lokalizacja:** `profile.js:14-32` (auto-profile), `profile.py` (endpoint, wymaga DEM_PATH)
- **Propozycja:** Upewnic sie, ze DEM_PATH jest skonfigurowany; dodac komunikat bledu w UI gdy brak DEM

**B2. Rysowanie profilu powinno byc niezalezne od zlewni** (priorytet: sredni)
- Tryb "Rysuj linie" w profile.js (linia 37-58) technicznie dziala niezaleznie od zlewni
- Ale UX sugeruje zaleznosc — sekcja profilu jest wewnatrz panelu wynikow zlewni
- **Lokalizacja:** `profile.js:37-58` (draw mode), `index.html` (sekcja profilu w panelu)
- **Propozycja:** Wyniesc "Rysuj linie profilu" jako niezalezny tryb dostepny z toolbar (obok Zlewnia/Wybor)

**B3. Generowanie hydrogramu nie dziala** (priorytet: sredni — do tymczasowego wylaczenia)
- Przycisk "Generuj" jest widoczny po delineacji zlewni < 250 km², ale generowanie nie dziala
- Mozliwe przyczyny: brak danych opadowych IMGW, brak konfiguracji Hydrolog, blad runtime
- **Lokalizacja:** `hydrograph.js:55-99`, `hydrograph.py:70-327`, `app.js:128-144`
- **Propozycja:** Tymczasowo ukryc/zablokowac sekcje hydrogramu w UI (collapsed + disabled)

**B4. Selekcja cieku obejmuje caly ciek do zmiany rzedu Strahlera** (priorytet: sredni)
- `traverse_upstream()` w CatchmentGraph robi pelny BFS — zbiera WSZYSTKIE segmenty powyzej
- Uzytkownik chce selekcji tylko do najblizszego doplywu (konfluencji)
- **Lokalizacja:** `catchment_graph.py:278-300` (`traverse_upstream`), `select_stream.py:106-111`
- **Propozycja:** Dodac tryb "do pierwszej konfluencji" — BFS z warunkiem stopu gdy wiecej niz 1 upstream

#### C. Do usuniecia

**C1. Liczba komorek dla punktu ujsciowego** (priorytet: niski)
- Wyswietla "Liczba komórek: 0" — wartosc nieustawiana po przejsciu z FlowGraph na CatchmentGraph
- Pole `cell_count` w schema ustawiane na 0 we wszystkich endpointach (watershed, hydrograph, select-stream)
- **Lokalizacja:** `app.js:101-106` (wiersz tabeli), `schemas.py:185` (pole w modelu), endpointy: `watershed.py`, `hydrograph.py`, `select_stream.py` (cell_count=0)
- **Propozycja:** Usunac wiersz "Liczba komórek" z tabeli wynikow i pole `cell_count` z modelu

### Nastepne kroki
1. Weryfikacja podkladow GUGiK WMTS (czy URL-e dzialaja z `EPSG:3857:{z}`)
2. Instalacja tippecanoe i uruchomienie `generate_tiles.py` na danych produkcyjnych
3. Usuniecie hardcoded secrets z config.py i migrations/env.py
4. Faza 5 (opcjonalna): PMTiles, pre-computed watersheds, MapLibre GL JS
5. CP5: MVP — pelna integracja, deploy

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
- [ ] Testy scripts/ (process_dem.py, import_landcover.py — 0% coverage)
- [x] Utworzenie backend/core/constants.py (M_PER_KM, M2_PER_KM2, CRS_*)
- [ ] Usuniecie hardcoded secrets z config.py i migrations/env.py
- [x] Problem jezior bezodplywowych (endorheic basins) — ADR-020: klasyfikacja + drain points
- [x] CI/CD pipeline (GitHub Actions)
- [x] Audyt QA wydajnosci: LATERAL JOIN, cache headers, TTL cache, partial index, PG tuning, client cache, defer, structlog
- [x] Eliminacja FlowGraph z runtime API (ADR-022): RAM -96%, startup -97%, 548 testow
