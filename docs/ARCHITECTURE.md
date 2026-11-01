# ARCHITECTURE.md - Architektura Systemu
## System Analizy Hydrologicznej

**Wersja:** 1.9
**Data:** 2026-03-27
**Status:** Approved

---

## 1. Przegląd Architektury

### 1.1 Architektura Wysokiego Poziomu

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER LAYER                               │
│                      (Web Browser)                               │
│     Chrome, Firefox, Edge, Safari (latest - 2 versions)          │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTPS
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                     PRESENTATION LAYER                           │
│                        (Nginx)                                   │
│  - Reverse Proxy                                                │
│  - Static Files Serving                                         │
│  - SSL Termination                                              │
│  - Rate Limiting                                                │
└───────────┬─────────────────────────────┬───────────────────────┘
            │                             │
            │ /api/*                      │ /
            │                             │
┌───────────▼──────────────┐    ┌────────▼──────────────────────┐
│   APPLICATION LAYER      │    │     FRONTEND LAYER            │
│      (FastAPI)           │    │  (Static HTML/CSS/JS)         │
│                          │    │                               │
│  - REST API Endpoints    │    │  - Leaflet.js (Map)          │
│  - Request Validation    │    │  - Chart.js (Plots)          │
│  - Business Logic        │    │  - Tokeny Nogata (UI)        │
│  - Error Handling        │    │  - Vanilla JavaScript        │
└───────────┬──────────────┘    └───────────────────────────────┘
            │
            │ SQL Queries
            │
┌───────────▼──────────────────────────────────────────────────┐
│                    CORE LOGIC LAYER                           │
│                     (Python Modules)                          │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │  Watershed   │  │  Parameters  │  │   Hydrograph    │   │
│  │  Delineation │  │  Calculator  │  │   Generator     │   │
│  └──────────────┘  └──────────────┘  └─────────────────┘   │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │  Catchment   │  │Precipitation │  │   Land Cover    │   │
│  │    Graph     │  │   Queries    │  │   Analyzer      │   │
│  └──────────────┘  └──────────────┘  └─────────────────┘   │
└───────────┬───────────────────────────────────────────────────┘
            │
            │ SQL (PostGIS queries)
            │
┌───────────▼─────────────────────────────────────────────────────┐
│                      DATA LAYER                                 │
│                  (PostgreSQL + PostGIS)                         │
│                                                                 │
│  ┌────────────────┐  ┌───────────────────┐  ┌────────────────┐  │
│  │  soil_hsg      │  │stream_catchments  │  │  land_cover    │  │
│  │ (HSG polygons) │  │ (Polygons)        │  │  (Polygons)    │  │
│  └────────────────┘  └───────────────────┘  └────────────────┘  │
│  ┌────────────────┐  ┌───────────────────┐  ┌────────────────┐  │
│  │ stream_network │  │precipitation_data │  │  depressions   │  │
│  │ (Lines)        │  │ (IDW scenarios)   │  │ (Blue spots)   │  │
│  └────────────────┘  └───────────────────┘  └────────────────┘  │
│  ┌────────────────┐  ┌───────────────────┐                      │
│  │ sewer_nodes    │  │  sewer_network    │                      │
│  │ (Points)       │  │  (Lines)          │                      │
│  └────────────────┘  └───────────────────┘                      │
└─────────────────────────────────────────────────────────────────┘
```

---

### 1.2 Kluczowe Decyzje Architektoniczne (ADR)

Pełny rejestr decyzji architektonicznych: [docs/DECISIONS.md](DECISIONS.md)

Podsumowanie kluczowych ADR:

| ADR | Decyzja | Uzasadnienie |
|-----|---------|--------------|
| ADR-001 | Graf w bazie zamiast rastrów runtime | Szybkość runtime (< 10s) kosztem jednorazowego preprocessingu |
| ADR-002 | Monolityczna aplikacja FastAPI | Prostota deployment dla MVP (10 użytkowników) |
| ADR-003 | Leaflet.js zamiast Google Maps | Open-source, darmowy, lekki (40KB) |
| ADR-004 | Hietogram Beta zamiast blokowego | Realistyczny rozkład opadu (α=2, β=5) |
| ADR-005 | Docker Compose dla deployment | Environment parity, izolacja zależności |
| ADR-006 | COPY zamiast INSERT | Import DEM 27x szybciej (3.8 min vs 102 min) |
| ADR-007 | Reverse trace | find_main_stream 330x szybciej (0.74s vs 246s) |
| ADR-012 | pyflwdir zamiast pysheds | Deltares — stabilny, wydajny, 3 deps |
| ADR-017 | Podział process_dem na moduły core/ | Thin orchestrator + testowalne moduły |
| ADR-021 | CatchmentGraph zamiast rastrowych operacji | BFS po grafie zlewni cząstkowych zamiast CTE po 20M+ rekordach |
| ADR-022 | Eliminacja FlowGraph z runtime | RAM z ~1 GB → ~40 MB, startup z ~90s → ~3s |
| ADR-024 | ~~Segmentacja konfluencyjna~~ | ~~SUPERSEDED by ADR-026~~ |
| ADR-025 | ~~Warunkowy próg BFS~~ | ~~SUPERSEDED by ADR-026~~ |
| ADR-026 | Lookup by segment_idx | O(1) lookup po `(threshold_m2, segment_idx)` zamiast auto-increment `id` |
| ADR-029 | trace_main_channel() | Wyznaczanie głównego cieku wg Strahlera (do channel_slope) |
| ADR-032 | Boundary smoothing | `ST_SimplifyPreserveTopology(5.0)` + `ST_ChaikinSmoothing(3)` |
| ADR-033 | Building raising | `raise_buildings_in_dem()` +5m pod footprints BUBD |
| ADR-034 | Panel administracyjny | `/admin` + 13 endpointów `/api/admin/*`, API key auth, bootstrap SSE |
| ADR-035 | Konteneryzacja multi-stage | Multi-stage Dockerfile, entrypoint z wait-for-db, override dev/prod |
| ADR-036 | Hardening kontenerów Docker | Security headers, resource limits, non-root user |
| ADR-037 | Separacja cache/data + Kartograf v0.5.0 | Rozdzielenie katalogów cache i danych generowanych |
| ADR-038 | HSG Poland-wide cache | Ogólnopolski cache HSG — brak potrzeby pobierania per-obszar |
| ADR-040 | Vector boundary file support | Obsługa GPKG/GeoJSON/SHP jako granic obszaru (zamiast tylko bbox) |
| ADR-041 | Monotoniczne wygładzanie cieków | Zapewnienie monotoniczności elevacji po smoothingu linii cieków |
| ADR-042 | Optymalizacja wydajności delineate-watershed | Cascaded merge threshold, batch ST_Union, cache grafowy |
| ADR-044 | BDOT10k stream matching | Dopasowanie cieków DEM do referencyjnych BDOT10k (is_real_stream) |
| ADR-045 | WFS PRG zamiast grid-sampling WMS | TERYT discovery z WFS PRG — szybciej i dokładniej niż WMS grid |
| ADR-046 | upstream_area_km2 w trace_main_channel | Branch selection wg upstream_area_km2 zamiast Strahlera |
| ADR-047 | Chaikin smoothing cieków w preprocessingu | Wygładzanie geometrii cieków na etapie preprocessingu |
| ADR-048 | Droga spływu z działu wód | Longest flow path + divide flow path jako parametry morfometryczne |
| ADR-049 | DEM auto-discovery z fallback chain | Automatyczne znajdowanie pliku DEM (VRT → mosaic → single TIFF) |
| ADR-050 | Unified delineate-watershed endpoint | Jeden endpoint z trybami precomputed (BFS) i precise (pyflwdir on-the-fly) |
| ADR-051 | Integracja sieci kanalizacyjnej | Inlet burning + FA routing przez sieć kanalizacyjną w preprocessingu |
| ADR-065 | Identyfikacja wizualna Nogata i powłoka Archiwisty | Spójny wygląd GUI ekosystemu (ECO-055) zamiast paneli glassmorphism; Bootstrap tylko w `/admin` |

---

## 2. Architektura Backendu

### 2.1 Struktura Aplikacji FastAPI

```
backend/
├── api/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app instance, lifespan, middleware
│   ├── dependencies/
│   │   ├── __init__.py
│   │   └── admin_auth.py          # Admin API key verification (X-Admin-Key header)
│   └── endpoints/
│       ├── __init__.py
│       ├── admin.py               # 13 endpointów /api/admin/* (dashboard, resources, cleanup, bootstrap, sewer)
│       ├── depressions.py         # GET /depressions
│       ├── health.py              # GET /health
│       ├── hydrograph.py          # POST /generate-hydrograph
│       ├── profile.py             # POST /terrain-profile
│       ├── tiles.py               # GET /tiles/streams|catchments|landcover|sewer/{z}/{x}/{y}.pbf, GET /layers
│       └── watershed.py           # POST /delineate-watershed (precomputed + precise modes), POST /delineate-watershed/preview
│
├── core/
│   ├── __init__.py
│   ├── catchment_graph.py         # In-memory sub-catchment graph (~87-285k nodes, scipy CSR + BFS, invalidate())
│   ├── cn_calculator.py           # Kartograf HSG-based CN calculation
│   ├── cn_tables.py               # CN lookup tables (HSG × land cover)
│   ├── config.py                  # YAML config loading (load_config(), get_settings(), resolve_dem_path() — DEM auto-discovery ADR-049)
│   ├── constants.py               # Project-wide constants (CRS, unit conversions, limits)
│   ├── database.py                # Database connection pool
│   ├── db_bulk.py                 # Bulk INSERT via COPY, timeout mgmt
│   ├── hydrology.py               # Hydrology: fill, fdir, acc, burning, building raising (ADR-033)
│   ├── land_cover.py              # Land cover analysis, determine_cn()
│   ├── morphometry.py             # Morphometric parameters calculation
│   ├── morphometry_raster.py      # Slope, aspect, TWI, Strahler (raster)
│   ├── precipitation.py           # Precipitation queries
│   ├── raster_io.py               # Raster I/O (ASC, VRT, GeoTIFF)
│   ├── raster_service.py          # RasterCache — lazy-loaded raster data (DEM, flow direction, accumulation)
│   ├── soil_hsg.py                # HSG soil group data (SoilGrids)
│   ├── stream_extraction.py       # Stream vectorization, subcatchments
│   ├── watershed.py               # Watershed boundary building + legacy CLI functions
│   ├── sewer_service.py            # Integracja sieci kanalizacyjnej (SewerGraph, burn inlets, FA routing, ADR-051/052)
│   ├── sewer_topology.py           # Parser + walidator topologii kanalizacji (ParsedTopology, parse_sewer_topology, validate_against_fdir, ADR-052)
│   ├── watershed_service.py       # Shared delineation logic (CatchmentGraph-based, ADR-022, Chaikin smoothing ADR-032)
│   ├── zonal_stats.py             # Zonal statistics (bincount, max)
│   └── boundary.py               # Obsługa plików wektorowych granic (GPKG/GeoJSON/SHP), walidacja, konwersja bbox (ADR-040)
│
├── models/
│   ├── __init__.py
│   └── schemas.py                 # Pydantic models
│
├── scripts/
│   ├── __init__.py
│   ├── bootstrap.py               # Orchestrator — uruchamia pełny pipeline preprocessingu
│   ├── process_dem.py             # Thin orchestrator (~700 lines) — NMT processing
│   ├── prepare_area.py            # Konfiguracja bbox i parametrów obszaru
│   ├── download_dem.py            # Pobieranie NMT z GUGiK (Kartograf 0.7.0): download_sheets() -> NmtDownloadReport / NmtDownloadError
│   │                              #   MetadataCache: <cache_dir>/kartograf_meta.db (dysk lokalny, nigdy udział sieciowy)
│   │                              #   układ: cache/nmt/pl_<uklad>_<res>_evrf2007/ (+ kampanie/); mozaika z listy kroku 2
│   │                              #   szczegóły: docs/integrations/KARTOGRAF.md §6
│   ├── download_landcover.py      # Pobieranie pokrycia terenu (BDOT10k)
│   ├── import_landcover.py        # Import land cover do PostGIS
│   ├── preprocess_precipitation.py # Import opadów z IMGW
│   ├── generate_tiles.py          # Generowanie MVT tiles (streams, catchments, landcover)
│   ├── generate_dem_overlay.py    # Overlay DEM (PNG)
│   ├── generate_dem_tiles.py      # Piramida XYZ tiles DEM (hillshade)
│   ├── generate_streams_overlay.py # Overlay cieków (PNG)
│   ├── generate_depressions.py    # Generowanie depresji (blue spots)
│   ├── analyze_watershed.py       # Analiza zlewni (CLI)
│   ├── download_sewer.py          # Pobieranie sieci kanalizacyjnej (plik/WFS/DB/URL, walidacja CRS, SSRF protection). Zwraca tuple (points_gdf, lines_gdf | None)
│   └── clean.py                  # Czyszczenie danych generowanych (rasters, tiles, DB, cache)
│
├── migrations/
│   └── versions/                  # 1 migracja (squashed initial schema)
│
├── utils/
│   ├── __init__.py
│   ├── dem_color.py               # DEM color palette, hillshade blending
│   ├── geometry.py                # Geometric operations, CRS transforms
│   ├── raster_utils.py            # Raster tools (resample, polygonize)
│   └── sheet_lookup.py            # NMT sheet lookup, thin wrapper over kartograf.find_sheets_for_bbox (ADR-057)
│
├── tests/
│   ├── unit/                      # 45+ plików testów jednostkowych
│   ├── integration/               # 8+ plików testów integracyjnych
│   ├── performance/               # Testy wydajnościowe (benchmarki)
│   └── conftest.py
│
├── requirements.txt
└── Dockerfile
```

---

### 2.2 API Endpoints

#### 2.2.1 Health Check
```
GET /health
Response: 200 OK
{
  "status": "healthy",
  "database": "connected",
  "version": "1.0.0"
}
```

#### 2.2.2 Delineate Watershed (ADR-050)
```
POST /api/delineate-watershed
Content-Type: application/json

Tryb precomputed (z threshold_m2 — snap-to-stream + BFS po grafie):
Request:
{
  "latitude": 52.123456,
  "longitude": 21.123456,
  "threshold_m2": 10000,
  "display_threshold_m2": 10000
}

Tryb precise (bez threshold_m2 — delimitacja rastrowa pyflwdir on-the-fly):
Request:
{
  "latitude": 52.123456,
  "longitude": 21.123456
}

Response: 200 OK
{
  "mode": "precomputed",  // lub "precise"
  "stream": { "segment_idx": 42, "strahler_order": 3, ... },
  "upstream_segment_indices": [42, 43, 44, ...],
  "boundary_geojson": { "type": "Feature", ... },
  "display_threshold_m2": 10000,
  "watershed": { "outlet": {...}, "morphometry": {...}, ... }
}

Errors:
- 404: "Nie znaleziono cieku w tym miejscu"
- 422: Walidacja (niepoprawne wspolrzedne)
- 500: "Błąd serwera"
```

#### 2.2.2a Delineation Preview
```
POST /api/delineate-watershed/preview
Content-Type: application/json

Request (jak tryb precomputed; threshold_m2 wymagany — tryb precise nie ma podglądu):
{
  "latitude": 50.929,
  "longitude": 16.119,
  "threshold_m2": 10000
}

Response: 200 OK
{
  "threshold_m2": 100000,      // próg zlewni cząstkowych po progu minimalnym i kaskadzie
  "segment_count": 289,        // ile zlewni cząstkowych scala delineate-watershed
  "catchments": {              // GeoJSON FeatureCollection (WGS84), rosnąco po depth
    "type": "FeatureCollection",
    "features": [
      { "type": "Feature", "geometry": { "type": "MultiPolygon", ... }, "properties": { "depth": 0 } },
      ...
    ]
  }
}

Errors:
- 404: "Nie znaleziono zlewni cząstkowej w tym punkcie. ..."
- 422: Walidacja (współrzędne, brak lub niedodatni threshold_m2)
- 503: Graf zlewni niezaładowany
```

Podgląd dla animacji w GUI, zanim `POST /api/delineate-watershed` scali granicę. Wybór zlewni cząstkowych jest wspólny z trybem precomputed (`_select_precomputed`: próg minimalny `DEFAULT_THRESHOLD_M2`, zlewnia cząstkowa w punkcie, BFS, kaskada przy > 300 segmentach), więc podgląd pokrywa ten sam obszar co wynik. `depth` to liczba połączeń w górę od zlewni ujściowej (`CatchmentGraph.upstream_segments_by_depth`); każda głębokość to jeden MultiPolygon zebrany przez `ST_Collect` (bez scalania), wielokąty uproszczone `ST_Simplify` z tolerancją √A / 500 m (ok. piksel po dopasowaniu mapy do zlewni, min. 1 m), współrzędne z dokładnością 5 miejsc. Najwyżej 5000 zlewni cząstkowych najbliżej ujścia. Czas (instancja przeglądowa): 52 km² — 25 ms wobec 4,6 s pełnego wyznaczania, 778 km² (4418 zlewni cząstkowych, 147 głębokości) — 0,15–0,24 s wobec 88 s.

#### 2.2.3 Generate Hydrograph
```
POST /api/generate-hydrograph
Content-Type: application/json

Request:
{
  "latitude": 52.123456,
  "longitude": 21.123456,
  "duration": "1h",            // wymagane bez custom_precipitation
  "probability": 10,           // wymagane bez custom_precipitation
  "amc": "II",                 // I | II | III, domyślnie II
  "custom_precipitation": {    // opcjonalnie: własna seria zamiast PMAXTP i hietogramu
    "timestep_min": 10,        // > 0 i ≤ 1440
    "depths_mm": [0.5, 2.0, 6.5, 3.0, 1.0]   // ≥ 0, 1–2000 wartości, suma > 0
  },
  "morphometry": { ... }       // opcjonalnie: szybka ścieżka (tryb zaawansowany), cn ułamkowe
}

Response: 200 OK (pełna struktura w DATA_MODEL.md, sekcja 6.4)
  precipitation.source: "pmaxtp" | "custom"; probability_percent = null dla własnej serii
  water_balance.cn_used: float (CN po przeliczeniu wg AMC)
  metadata.amc; metadata.hietogram_type = null dla własnej serii
Response: 422 — błędy walidacji (np. serii opadu) z polskim opisem
```

`GET /api/scenarios` zwraca dodatkowo `amc` (`["I", "II", "III"]`) i `custom_precipitation_max_steps` (2000).

#### 2.2.3a Layer Availability
```
GET /api/layers

Response: 200 OK
{"sewer": true}   // czy sewer_network lub sewer_nodes zawiera dane
```
Panel „Warstwy” pokazuje warstwę „Kanalizacja deszczowa” tylko przy `sewer: true`.

#### 2.2.4 List Scenarios
```
GET /api/scenarios

Response: 200 OK
{
  "durations": ["5min","10min","15min","30min","45min","1h","1.5h","2h","3h","6h","12h","18h","24h","36h","48h","72h"],
  "probabilities": [0.01,0.02,0.03,0.05,0.1,0.2,0.3,0.5,1,2,3,5,10,20,30,40,50,60,70,80,90,95,98,98.5,99,99.5,99.9],
  "tc_methods": [...],
  "hietogram_types": [...],
  "uh_models": [...],
  "snyder_defaults": {...},
  "nash_estimation_methods": [...],
  "nash_defaults": {...}
}
```

#### 2.2.5 Terrain Profile
```
POST /api/terrain-profile
Content-Type: application/json

Request:
{
  "geometry": { "type": "LineString", "coordinates": [[lon, lat], ...] },
  "n_samples": 100
}

Response: 200 OK
{
  "distances_m": [0.0, 10.5, ...],
  "elevations_m": [150.0, 151.2, ...],
  "total_length_m": 1050.0
}
```

#### 2.2.6 Depressions (Blue Spots)
```
GET /api/depressions?bbox=xmin,ymin,xmax,ymax&min_volume=0&max_volume=1000

Response: 200 OK (GeoJSON FeatureCollection)
```

#### 2.2.7 MVT Tiles
```
GET /api/tiles/streams/{z}/{x}/{y}.pbf?threshold_m2=10000
GET /api/tiles/catchments/{z}/{x}/{y}.pbf?threshold_m2=10000
GET /api/tiles/landcover/{z}/{x}/{y}.pbf
GET /api/tiles/sewer/{z}/{x}/{y}.pbf
GET /api/tiles/thresholds

Response: Mapbox Vector Tiles (PBF) / JSON
```

#### 2.2.8 Admin Panel (ADR-034)
```
Wszystkie endpointy wymagają nagłówka X-Admin-Key (lub ADMIN_API_KEY nie ustawiony).
Prefix: /api/admin

GET  /api/admin/dashboard          — statystyki tabel, uptime, wersja
GET  /api/admin/resources          — CPU, RAM, dysk (psutil)
GET  /api/admin/cleanup/estimate   — szacunek zwolnionego miejsca
POST /api/admin/cleanup            — usuwanie cache/tiles
GET  /api/admin/bootstrap/status   — status procesu bootstrap
POST /api/admin/bootstrap/start    — uruchomienie bootstrap subprocess
POST /api/admin/bootstrap/cancel   — anulowanie bootstrap
GET  /api/admin/bootstrap/stream   — SSE stream logów bootstrap (timeout 3600s)
POST /api/admin/bootstrap/upload-boundary — upload granicy zlewni

POST   /api/admin/sewer/upload     — upload pliku z siecią kanalizacyjną (ADR-051/052), auto-detect format, zwraca detected_format i layers
GET    /api/admin/sewer/status     — status danych kanalizacji
DELETE /api/admin/sewer/delete     — usunięcie danych kanalizacji
POST   /api/admin/sewer/config    — konfiguracja field_mapping, role_mapping (ADR-052)
```

---

### 2.3 Logika Biznesowa - Przepływ Danych

#### Wyznaczanie Zlewni (Sequen ce Diagram)
```
User → Frontend → API → Core Logic → Database → Core Logic → API → Frontend → User
  |       |        |         |           |          |        |       |        |
  Click   POST     Validate  Find        Query     Build    JSON    Render   See
  point   request  coords    nearest     graph     GeoJSON  response boundary boundary
                             stream      upstream
```

**Szczegółowy przepływ (ADR-022, ADR-026):**
1. **Frontend:** Użytkownik klika punkt (lat, lon) → POST /api/delineate-watershed (tryb precomputed lub precise)
2. **API (FastAPI):** Walidacja Pydantic (czy lat/lon w zakresie)
3. **Core Logic** (`watershed_service.py` + `catchment_graph.py`):
   - `find_stream_catchment_at_point(x, y, threshold)` → snap-to-stream via `ST_ClosestPoint` na `stream_network`
   - `CatchmentGraph.traverse_upstream()` → BFS po grafie zlewni cząstkowych
   - Cascaded merge threshold: jeśli >500 segmentów, kaskada do grubszego progu (1000→10000→100000)
   - `merge_catchment_boundaries()` → ST_UnaryUnion gotowych poligonów w PostGIS
   - `map_boundary_to_display_segments()` → mapowanie na próg wyświetlany dla MVT tiles
   - Agregacja pre-computed stats z numpy arrays (zero operacji rastrowych)
4. **Database:** Zapytania PostGIS do `stream_network` + `stream_catchments`
5. **Core Logic:** Konwersja do GeoJSON (EPSG:2180 → WGS84)
6. **API:** Return JSON response
7. **Frontend:** Leaflet.js renderuje polygon na mapie, MVT tiles podświetlają zlewnie cząstkowe

**Czas wykonania:** < 1s (typowy), < 5s (duże zlewnie)

---

#### Generowanie Hydrogramu (Sequence Diagram)
```
1. Wyznacz zlewnię (jak wyżej)
2. Oblicz parametry (area, length, slope, CN)
3. Pobierz opad (SQL query PMAXTP) albo przyjmij własną serię (custom_precipitation)
4. Wygeneruj hietogram (Beta / Block / Euler II; pomijany dla własnej serii)
5. Oblicz opad efektywny (SCS CN przeliczony wg AMC)
6. Oblicz tc (Kirpich)
7. Wygeneruj UH (SCS)
8. Splot Pe * UH = Q(t)
9. Return JSON z wykresem
```

**Czas wykonania:** < 5s

---

### 2.4 Moduły Core Logic

#### 2.4.1 `core/watershed.py`
**Odpowiedzialności:**
- Znajdowanie najbliższego cieku
- Traversal grafu upstream
- Budowanie granicy zlewni

**Główne funkcje:**
```python
# Legacy CLI functions (replaced by watershed_service.py for runtime API):
def find_nearest_stream(lat, lon) -> int | None: ...
def traverse_upstream(outlet_id: int) -> list[Cell]: ...

# Still used:
def build_boundary(cells: list[Cell]) -> GeoJSON: ...
```

#### 2.4.2 `core/morphometry.py`
**Odpowiedzialności:**
- Obliczanie parametrów geometrycznych (area, perimeter, length)
- Obliczanie parametrów morfometrycznych (slope, elevation)
- Współczynniki kształtu, indeksy rzeźby, krzywa hipsometryczna

**Główne funkcje:**
```python
def build_morphometric_params(
    cells: list[FlowCell],
    boundary: Polygon,
    outlet: FlowCell,
    cn: int | None = None,
    include_stream_coords: bool = False,
    db=None,
    include_hypsometric_curve: bool = False,
) -> dict:
    """Buduje kompletny słownik parametrów morfometrycznych (kompatybilny z Hydrolog).
    Uwaga: W runtime API, parametry obliczane z CatchmentGraph.aggregate_stats()."""
    pass
```

#### 2.4.3 `core/catchment_graph.py`

Singleton in-memory graf zlewni cząstkowych oparty na numpy arrays i scipy sparse CSR matrix (~87-285k węzłów w zależności od obszaru, ~0.5 MB RAM). Ładowany lazy z bazy danych przy pierwszym użyciu, invalidowany po cleanup/pipeline przez `invalidate()`.

**Kluczowe koncepty:**
- **BFS traversal** — `traverse_upstream` do wyznaczania zlewni
- **trace_main_channel** — wyznaczanie głównego cieku z branch selection wg `upstream_area_km2` (ADR-046), zwraca FeatureCollection z geometriami segmentów
- **aggregate_stats** — agregacja pre-computed zonal stats (area, elevation, slope, stream metrics) + hydraulic length relative to outlet
- **is_real_stream** — oznaczenie segmentów dopasowanych do referencyjnych cieków BDOT10k (ADR-044)
- **aggregate_hypsometric** — krzywa hipsometryczna z mergowania histogramów elevation per segment

Szczegóły: `core/catchment_graph.py`

#### 2.4.4 `core/watershed_service.py`

Współdzielona logika delineacji używana przez 2 endpointy (watershed, hydrograph). Eliminuje kosztowne operacje rastrowe w runtime — cała praca oparta na CatchmentGraph i pre-computed stats.

**Kluczowe odpowiedzialności:**
- **Merge catchment boundaries** — 3 strategie: direct (małe zlewnie), batched ST_UnaryUnion, fallback na grubszy próg. Cascade threshold escalation dla dużych zlewni (>500 segmentów: 1000 → 10000 → 100000)
- **Smoothing granic** — `ST_SimplifyPreserveTopology(5.0)` + `ST_ChaikinSmoothing(3)` (ADR-032)
- **Main channel FeatureCollection** — geometria głównego cieku z flagą `is_real_stream` per segment (ADR-044)
- **Flow path GeoJSON** — longest flow path + divide flow path (ADR-048) jako geometrie do wyświetlenia
- **Parametry morfometryczne** — `build_morph_dict_from_graph()` buduje słownik kompatybilny z Hydrolog
- **Land cover / HSG stats** — helpery do obliczania CN i pokrycia terenu w granicach zlewni

Szczegóły: `core/watershed_service.py`

#### 2.4.5 `core/db_bulk.py`
**Odpowiedzialności:**
- Bulk INSERT via PostgreSQL COPY (55k rec/s vs 2.6k rec/s z INSERT)
- Zarządzanie statement_timeout (override + restore)

#### 2.4.6 `core/stream_extraction.py`
**Odpowiedzialności:**
- Wektoryzacja cieków z rastra akumulacji
- Segmentacja na konfluencjach (ADR-024) i zmianach rzędu Strahlera
- Generowanie label raster dla `pyflwdir.basins()`

#### 2.4.7 `core/zonal_stats.py`
**Odpowiedzialności:**
- Statystyki strefowe via `np.bincount` (O(M) zamiast O(n*M) per-label masking)
- Obliczanie min/max/mean per label dla elevation, slope

#### 2.4.8 Biblioteka Hydrolog (zewnetrzna)
**Odpowiedzialnosci:** (delegowane do `hydrolog` v0.6.3)
- Generowanie hietogramu (Beta, Block, Euler II)
- Model SCS CN (opad efektywny)
- Hydrogram jednostkowy: SCS, Nash IUH, Snyder
- Splot numeryczny
- Czas koncentracji (Kirpich, NRCS, Giandotti, FAA, Kerby, Kerby-Kirpich)

Hydrograf wywoluje Hydrolog przez endpoint `api/endpoints/hydrograph.py`:
```python
from hydrolog.precipitation import BetaHietogram
from hydrolog.runoff import HydrographGenerator
from hydrolog.morphometry import WatershedParameters
```

#### 2.4.9 `core/precipitation.py`
**Odpowiedzialności:**
- Zapytania do tabeli `precipitation_data`
- Interpolacja IDW (Inverse Distance Weighting)

**Główne funkcje:**
```python
def get_precipitation(
    centroid: Point,
    duration: str,
    probability: float
) -> float:
    """Pobiera wartość opadu (interpolacja IDW z siatki punktów IMGW)."""
    pass
```

#### 2.4.10 `core/land_cover.py`
**Odpowiedzialności:**
- Intersection granicy z pokryciem terenu
- Obliczanie ważonego CN

**Główne funkcje:**
```python
def calculate_cn(boundary: GeoJSON) -> Dict:
    """
    Zwraca:
    {
        'cn': 72.4,
        'land_cover_percent': {'las': 35.2, 'pola': 42.1, ...}
    }
    """
    pass
```

---

### 2.5 Nowe koncepty (CP4+)

#### WFS TERYT discovery (ADR-045)
Automatyczne wykrywanie powiatów (TERYT) na podstawie bbox za pomocą usługi WFS PRG (Państwowy Rejestr Granic). Zastępuje wcześniejszą metodę grid-sampling WMS, dając dokładniejsze wyniki przy mniejszej liczbie zapytań sieciowych. Używane przy pobieraniu danych BDOT10k i land cover.

#### DEM auto-discovery (ADR-049)
Mechanizm automatycznego znajdowania pliku DEM z fallback chain: VRT mosaic → single GeoTIFF → katalog z plikami ASC. Konfigurowany przez `resolve_dem_path()` w `core/config.py`, eliminuje konieczność ręcznego podawania ścieżki DEM w zmiennych środowiskowych. Obsługuje też `resolve_stream_distance_path()` dla rastrów odległości od cieków.

#### Chaikin smoothing cieków (ADR-047)
Wygładzanie geometrii cieków algorytmem Chaikina na etapie preprocessingu (w `process_dem.py`). Redukuje szum z rasterowej wektoryzacji, zachowując topologię sieci. Stosowane razem z monotonic smoothing (ADR-041).

#### BDOT10k stream matching (ADR-044)
Dopasowanie cieków wyznaczonych z DEM do referencyjnych cieków z BDOT10k (baza danych obiektów topograficznych). Segmenty dopasowane oznaczane jako `is_real_stream=True` w `stream_network`. Informacja ta propagowana do CatchmentGraph i zwracana w main channel FeatureCollection.

#### Divide flow path (ADR-048)
Wyznaczanie drogi spływu z działu wód (najdłuższa ścieżka od granicy zlewni do ujścia). Uzupełnia longest flow path jako dodatkowy parametr morfometryczny. Geometrie obu ścieżek przechowywane w `stream_catchments` (kolumny `longest_flow_path_geom`, `divide_flow_path_geom`).

#### Monotoniczne wygładzanie cieków (ADR-041)
Zapewnienie monotoniczności profilu podłużnego cieków po wygładzeniu geometrii. Eliminuje artefakty, w których wygładzona linia cieku miała lokalne „podskoki" elevacji niezgodne z kierunkiem przepływu.

#### Integracja sieci kanalizacyjnej (ADR-051, ADR-052)
Uwzględnienie sieci kanalizacji deszczowej w modelu hydrologicznym. Topologia sieci definiowana jawnie przez uzytkownika (nie wykrywana heurystycznie). Dwa formaty wejsciowe: Format A (punkty z `downstream_id`) i Format B (punkty + linie z `from_node`/`to_node`). 4 role wezlow: inlet, outlet, junction, storage (kompatybilnosc SWMM/HEC-RAS).

**Pipeline dwufazowy:**
- **Faza 1 — Czysty fdir:** preprocessing DEM bez sieci kanalizacyjnej (fill → fdir → acc), walidacja petli fdir (`validate_against_fdir()`)
- **Faza 2 — Sewer burning + hydrologia:**
  - **Step 3b — Inlet burning:** wypalenie wlotów kanalizacyjnych w DEM (`burn_inlets()`) — obniżenie elevacji w komórkach wlotowych
  - **Step 4a — FA reconstruction:** rekonstrukcja flow accumulation w komórkach wlotowych (`reconstruct_inlet_fa()`)
  - **Step 4b — Sewer routing:** trasowanie flow accumulation przez sieć kanalizacyjną (`route_fa_through_sewer()`)
  - **Step 4c — FA propagation:** propagacja zmodyfikowanego FA w dół sieci cieków (`propagate_fa_downstream()`)

Dane kanalizacyjne przechowywane w tabelach `sewer_nodes` (węzły: wloty, wyloty, połączenia, zbiorniki) i `sewer_network` (odcinki rur). Import przez panel admin (`/api/admin/sewer/upload`) z walidacją CRS, auto-detekcja formatu i ochrona SSRF. Moduły: `core/sewer_topology.py` (parser + walidator topologii, 11 reguł walidacji), `core/sewer_service.py` (logika budowy grafu i routing FA), `scripts/download_sewer.py` (pobieranie danych, zwraca tuple `(points_gdf, lines_gdf | None)`).

---

## 3. Architektura Bazy Danych

### 3.1 Schema Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                          flow_network                            │
│              -- USUNIETA (ADR-028, migracja 015)                │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     precipitation_data                          │
├─────────────────────────────────────────────────────────────────┤
│ id (PK)              SERIAL                                     │
│ geom                 GEOMETRY(Point, 2180)                      │
│ duration             VARCHAR(10)  ('5min'...'72h', 16 wartości) │
│ probability          FLOAT        (0.01...99.9, 27 wartości)    │
│ precipitation_mm     FLOAT                                      │
│ source               VARCHAR(50)  ('IMGW_API')                 │
│ updated_at           TIMESTAMP                                  │
│                                                                 │
│ Indexes:                                                        │
│   - idx_precip_geom (GIST on geom)                               │
│   - idx_precip_scenario (on duration, probability)               │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                          land_cover                              │
├─────────────────────────────────────────────────────────────────┤
│ id (PK)              SERIAL                                     │
│ geom                 GEOMETRY(MultiPolygon, 2180)              │
│ category             VARCHAR(50)  ('las', 'zabudowa', etc)     │
│ cn_value             INT                                        │
│ imperviousness       FLOAT        (0.0 - 1.0)                  │
│                                                                 │
│ Indexes:                                                        │
│   - idx_landcover_geom (GIST on geom)                          │
│   - idx_category (on category)                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        stream_network                            │
├─────────────────────────────────────────────────────────────────┤
│ id (PK)              SERIAL                                     │
│ geom                 GEOMETRY(LineString, 2180)                │
│ name                 VARCHAR(100)                               │
│ length_m             FLOAT                                      │
│ strahler_order       INT                                        │
│ threshold_m2         INT                                        │
│ upstream_area_km2    FLOAT                                      │
│ mean_slope_percent   FLOAT                                      │
│ source               VARCHAR(20)  ('DEM_DERIVED', 'MPHP')      │
│ segment_idx          INTEGER  -- 1-based per threshold (migracja 014, ADR-026) │
│ is_real_stream       BOOLEAN  -- dopasowanie do BDOT10k (ADR-044)│
│ is_sewer_augmented   BOOLEAN  -- flaga modyfikacji przez sieć kanalizacyjną (ADR-051) │
│                                                                 │
│ Indexes:                                                        │
│   - idx_stream_geom (GIST on geom)                             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      stream_catchments                          │
├─────────────────────────────────────────────────────────────────┤
│ id (PK)              SERIAL                                     │
│ geom                 GEOMETRY(MultiPolygon, 2180)               │
│ segment_idx          INT                                        │
│ threshold_m2         INT                                        │
│ area_km2             FLOAT                                      │
│ mean_elevation_m     FLOAT                                      │
│ mean_slope_percent   FLOAT                                      │
│ strahler_order       INT                                        │
│ downstream_segment_idx INT                                      │
│ elevation_min_m      FLOAT                                      │
│ elevation_max_m      FLOAT                                      │
│ perimeter_km         FLOAT                                      │
│ stream_length_km     FLOAT                                      │
│ elev_histogram       JSONB                                      │
│ hydraulic_length_km  FLOAT                                      │
│ max_flow_dist_m      FLOAT                                      │
│ longest_flow_path_geom GEOMETRY(LineString, 2180)               │
│ divide_flow_path_geom  GEOMETRY(LineString, 2180)               │
│                                                                 │
│ Indexes:                                                        │
│   - idx_catchment_geom (GIST on geom)                          │
│   - idx_catchment_threshold (on threshold_m2)                  │
│   - idx_catchment_segment (on segment_idx, threshold_m2)       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                         depressions                             │
├─────────────────────────────────────────────────────────────────┤
│ id (PK)              SERIAL                                     │
│ geom                 GEOMETRY(Polygon, 2180)                    │
│ volume_m3            FLOAT                                      │
│ area_m2              FLOAT                                      │
│ max_depth_m          FLOAT                                      │
│ mean_depth_m         FLOAT                                      │
│                                                                 │
│ Indexes:                                                        │
│   - idx_depression_geom (GIST on geom)                         │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                          soil_hsg                               │
├─────────────────────────────────────────────────────────────────┤
│ id (PK)              SERIAL                                     │
│ geom                 GEOMETRY(MultiPolygon, 2180)               │
│ hsg_group            VARCHAR(1)  ('A', 'B', 'C', 'D')          │
│ area_m2              FLOAT                                      │
│                                                                 │
│ Indexes:                                                        │
│   - gist on geom (auto)                                        │
│   - idx_soil_hsg_group (on hsg_group)                          │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        bdot_streams                              │
├─────────────────────────────────────────────────────────────────┤
│ id (PK)              SERIAL                                     │
│ geom                 GEOMETRY(LineString, 2180)                 │
│ layer_type           VARCHAR(10)                                │
│ name                 VARCHAR(200)                               │
│ length_m             FLOAT                                      │
│                                                                 │
│ Indexes:                                                        │
│   - idx_bdot_streams_geom (GIST on geom)                       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        sewer_nodes                              │
├─────────────────────────────────────────────────────────────────┤
│ id (PK)              SERIAL                                     │
│ geom                 GEOMETRY(Point, 2180)                      │
│ node_type            VARCHAR(20)  ('inlet','outlet','junction','storage')  │
│ component_id         INTEGER                                    │
│ depth_m              FLOAT                                      │
│ invert_elev_m        FLOAT                                      │
│ dem_elev_m           FLOAT                                      │
│ burn_elev_m          FLOAT                                      │
│ fa_value             INTEGER                                    │
│ total_upstream_fa    INTEGER                                    │
│ root_outlet_id       INTEGER  → sewer_nodes(id)                │
│ nearest_stream_segment_idx INTEGER                              │
│ source_type          VARCHAR(20)                                │
│ rim_elev_m           FLOAT                                      │
│ max_depth_m          FLOAT                                      │
│ ponded_area_m2       FLOAT                                      │
│ outfall_type         VARCHAR(20)                                │
│ updated_at           TIMESTAMP                                  │
│                                                                 │
│ Indexes:                                                        │
│   - idx_sewer_nodes_geom (GIST on geom)                        │
│   - idx_sewer_nodes_node_type (on node_type)                   │
│   - idx_sewer_nodes_root_outlet_node_type (root_outlet_id, node_type) │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                       sewer_network                             │
├─────────────────────────────────────────────────────────────────┤
│ id (PK)              SERIAL                                     │
│ geom                 GEOMETRY(LineString, 2180)                 │
│ node_from_id         INTEGER  → sewer_nodes(id)                │
│ node_to_id           INTEGER  → sewer_nodes(id)                │
│ diameter_mm          INTEGER                                    │
│ width_mm             INTEGER                                    │
│ height_mm            INTEGER                                    │
│ cross_section_shape  VARCHAR(20)                                │
│ invert_elev_start_m  FLOAT                                      │
│ invert_elev_end_m    FLOAT                                      │
│ material             VARCHAR(50)                                │
│ manning_n            FLOAT                                      │
│ length_m             FLOAT                                      │
│ slope_percent        FLOAT                                      │
│ source               VARCHAR(50)                                │
│ updated_at           TIMESTAMP                                  │
│                                                                 │
│ Indexes:                                                        │
│   - idx_sewer_network_geom (GIST on geom)                      │
│   - idx_sewer_network_node_from_id (on node_from_id)           │
│   - idx_sewer_network_node_to_id (on node_to_id)              │
└─────────────────────────────────────────────────────────────────┘
```

---

### 3.2 Przykładowe Zapytania SQL

#### Znajdź Najbliższy Ciek (stream_network)
```sql
SELECT
    id, geom, strahler_order, length_m, threshold_m2,
    ST_Distance(geom, ST_SetSRID(ST_Point($1, $2), 2180)) as distance
FROM stream_network
WHERE threshold_m2 = $3
  AND ST_DWithin(geom, ST_SetSRID(ST_Point($1, $2), 2180), 500)
ORDER BY distance
LIMIT 1;
```

#### ~~Znajdź Komórki Upstream (Rekurencyjne CTE)~~ — DEPRECATED (ADR-022)
> **Uwaga:** Runtime API używa `CatchmentGraph.traverse_upstream()` (BFS in-memory, ~5-50ms).
> Poniższy CTE zachowany wyłącznie jako dokumentacja — `core/flow_graph.py` USUNIĘTY (ADR-028).

```sql
WITH RECURSIVE upstream AS (
    -- Base case: outlet
    SELECT 
        id, geom, cell_area, elevation, slope, downstream_id
    FROM flow_network
    WHERE id = $1
    
    UNION ALL
    
    -- Recursive case: all cells flowing to current set
    SELECT 
        f.id, f.geom, f.cell_area, f.elevation, f.slope, f.downstream_id
    FROM flow_network f
    INNER JOIN upstream u ON f.downstream_id = u.id
)
SELECT * FROM upstream;
```

#### Pobierz Opad (Wieloboki równego zadeszczenia)
```sql
WITH nearest AS (
    SELECT
        precipitation_mm,
        ST_Distance(geom, ST_SetSRID(ST_Point($1, $2), 2180)) as dist
    FROM precipitation_data
    WHERE duration = $3 AND probability = $4
    ORDER BY dist
    LIMIT 4
)
SELECT 
    SUM(precipitation_mm / POWER(dist, 2)) / 
    SUM(1 / POWER(dist, 2)) as precipitation_interpolated
FROM nearest;
```

#### Oblicz CN dla Zlewni
```sql
SELECT 
    lc.category,
    lc.cn_value,
    ST_Area(ST_Intersection(lc.geom, ST_GeomFromGeoJSON($1))) as area_m2
FROM land_cover lc
WHERE ST_Intersects(lc.geom, ST_GeomFromGeoJSON($1));
```

#### Merge Upstream Catchments (ST_Union)
```sql
SELECT ST_UnaryUnion(ST_Collect(ST_SnapToGrid(geom, 0.01))) AS boundary
FROM stream_catchments
WHERE threshold_m2 = $1
  AND segment_idx = ANY($2)
  AND ST_Area(geom) > 50;
```

#### MVT Tile Query (ST_AsMVT)
```sql
SELECT ST_AsMVT(tile, 'catchments') AS mvt
FROM (
    SELECT
        segment_idx,
        strahler_order,
        area_km2,
        ST_AsMVTGeom(geom, ST_TileEnvelope($1, $2, $3), 4096, 64, true) AS geom
    FROM stream_catchments
    WHERE threshold_m2 = $4
      AND ST_Intersects(geom, ST_Transform(ST_TileEnvelope($1, $2, $3), 2180))
      AND ST_Area(geom) > 50
) AS tile;
```

---

### 3.3 Optymalizacja Bazy Danych

#### Indeksy
- **GIST indexes** dla wszystkich kolumn geometrycznych
- **B-tree indexes** dla kluczy obcych i często filtrowanych kolumn

#### Connection Pooling
```python
# core/database.py
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,          # 10 connections
    max_overflow=5,        # +5 burst
    pool_timeout=30,       # 30s wait for connection
    pool_recycle=3600      # recycle after 1h
)
```

#### Query Optimization
- **EXPLAIN ANALYZE** dla wszystkich slow queries
- **Partial indexes** dla is_stream (tylko TRUE)
- **Materialized views** dla często używanych agregacji (future)

---

## 4. Architektura Frontendu

### 4.1 Struktura Plików

```
frontend/
├── index.html               # SPA — powłoka Archiwisty; Leaflet + MapLibre GL + Chart.js (CDN z SRI), bez Bootstrapa
├── admin.html               # Panel administracyjny (ADR-034) — powłoka + Bootstrap 5.3.3 (siatka, okna modalne)
├── img/
│   └── hydrograf.svg         # Znak Hydrografa (górny pasek, favicon)
├── instrukcja/
│   ├── index.html            # Przewodnik użytkownika (/instrukcja)
│   ├── instrukcja.css        # Style slajdów przewodnika
│   └── Hydrograf-*.png       # Zrzuty ekranu do przewodnika
├── css/
│   ├── tokens.css            # Kopia design/tokens.css Nogata (commit 29e7e1c) — NIE edytować, kopiować ponownie
│   ├── chrome.css            # Powłoka wspólna: górny pasek, szyna, panele, przyciski (index, admin, instrukcja)
│   ├── app.css               # Strona główna: mapa, panele Warstwy/Zlewnia, szuflada profilu, układ telefonu
│   └── admin.css             # Panel administracyjny (Bootstrap przekolorowany tokenami)
└── js/
    ├── theme-init.js         # Motyw z localStorage (`nogat-theme`) przed pierwszym malowaniem
    ├── theme-switch.js       # Przełącznik motywu Auto/Jasny/Ciemny w /admin i /instrukcja
    ├── shell.js              # Powłoka strony głównej: panele, uchwyty szerokości, układ telefonu, motyw
    ├── api.js                # API calls (fetch wrappers)
    ├── map.js                # Leaflet map, drawing, MVT
    ├── charts.js             # Chart.js w kolorach tokenów: hipsometria, pokrycie/HSG, hietogram, hydrogram, profil
    ├── layers.js             # Panel „Warstwy”: podkłady z nakładką mapy zagrożenia powodziowego (WMS Wód Polskich), nakładki, krycie, przybliżenie do zasięgu
    ├── profile.js            # Terrain profile (draw line / auto)
    ├── hydrograph.js         # Formularz hietogramu (AMC, źródło opadu) i hydrogramu, bilans, wykresy
    ├── custom-rain.js        # Własna seria opadu: tabela kroków, wklejanie, import CSV, kopia hietogramu
    ├── info.js               # Objaśnienia (i): znaczniki, wspólny dymek, wzory MathML, najechanie/fokus/dotknięcie, Esc
    ├── info-texts.js         # 76 objaśnień (wzór, zmienne, jednostka, znaczenie) kluczowane polem API lub id kontrolki
    ├── advanced.js           # Tryb zaawansowany: edycja morfometrii do POST /api/generate-hydrograph
    ├── depressions.js        # Depressions (blue spots) overlay
    ├── sewer.js              # Warstwa kanalizacji deszczowej (MVT overlay; tylko gdy GET /api/layers zgłasza dane)
    ├── results.js            # Wyniki analiz zewnętrznych (np. SFINCS z Hydraulika) z manifestu /data/results/index.json: kafle, legenda, (i)
    ├── diagnostics.js        # Dziennik zdarzeń sesji (ADR-053)
    ├── feedback.js           # Formularz „Zgłoś uwagę” (natywny <dialog>)
    ├── app.js                # Orchestrator: init, tryby pracy, click routing, panel Zlewnia
    └── admin/
        ├── admin-api.js      # Admin API client (fetch + X-Admin-Key header)
        ├── admin-bootstrap.js # Bootstrap SSE stream, start/cancel
        ├── admin-bbox-picker.js # Mapa do wyboru bbox obszaru
        ├── admin-sewer.js    # Karta zarządzania siecią kanalizacyjną
        ├── admin-feedback.js # Lista zgłoszeń testerów
        └── admin-app.js      # Admin panel orchestrator
```

Identyfikacja wizualna pochodzi z Nogata (standard DEV-15.3, ECO-055, ADR-065): wzorzec w `design/` Nogata, makieta `design/mockups/hydrograf/`. Kolory, czcionki, promienie i cienie wyłącznie przez zmienne z `css/tokens.css`; zmiana palety odbywa się w Nogacie i kończy ponownym skopiowaniem pliku.

---

### 4.2 Komponenty UI

#### 4.2.0 Powłoka (shell)

Strona główna używa powłoki Archiwisty (`chrome.css` + `app.css` + `shell.js`):

- **Górny pasek** — znak `img/hydrograf.svg`, wskaźnik stanu usług, przyciski „Instrukcja” (`/instrukcja/`) i „Zgłoś uwagę” oraz przełącznik motywu Auto/Jasny/Ciemny (`data-theme` na `<html>`, wybór w `localStorage` `nogat-theme`; `theme-init.js` ustawia go przed pierwszym malowaniem, więc nie ma mignięcia jasnego motywu). Przycisk „Instrukcja” jest w górnym pasku każdej strony (główna, `/admin`, `/instrukcja`).
- **Szyna nawigacji** — tylko Mapa i Administracja (`/admin`); profil terenu jest trybem paska mapy.
- **Lewy panel „Warstwy”** — podkłady (z nakładką „Mapa zagrożenia powodziowego”), nakładki z suwakiem krycia i jeden przycisk przybliżenia do zasięgu włączonych warstw.
- **Środek** — mapa z paskiem trybów Przeglądanie / Wybierz zlewnię / Profil terenu; profil terenu otwiera się w dolnej szufladzie nad mapą.
- **Prawy panel „Zlewnia”** — kluczowe wartości (kafle) i sekcje `<details>`: parametry podstawowe, wskaźniki kształtu, rzeźba terenu, sieć rzeczna, pokrycie terenu, grupy HSG, hietogram, hydrogram.
- **Objaśnienia (i)** — `info.js` dodaje znaczniki (i) w sekcjach Parametry podstawowe, Wskaźniki kształtu, Rzeźba terenu, Sieć rzeczna, Hietogram i Hydrogram; jeden wspólny dymek otwierany najechaniem, fokusem lub dotknięciem, zamykany Esc. Wpisy (64) w `info-texts.js`, kluczowane polem API lub id kontrolki formularza, mają strukturę: opis, wzór (składany jako MathML przez DOM, bez bibliotek), lista „gdzie:” ze zmiennymi i jednostkami, jednostka wyniku, osobny blok „Znaczenie dla analizy”, zakres stosowalności i uwaga. Treści oparte na Hydrologu i backendzie (np. limit hydrogramu 250 km², `HYDROGRAPH_AREA_LIMIT_KM2`). Uwagi o stosowalności pod Model UH, Metoda Tc i Estymacja Nash zmieniają się z wyborem. API nie zwraca ostrzeżeń o stosowalności, więc GUI ich nie pokazuje.
- **Hietogram: AMC i źródło opadu** — pole „Uwilgotnienie początkowe (AMC)” I / II / III (`amc` w zapytaniu, domyślnie II); bilans pokazuje użyty CN z jednym miejscem po przecinku i klasą AMC. Przełącznik „Źródło opadu” PMAXTP / Własna seria (`custom-rain.js`): „Czas trwania [min]” i „Krok czasowy [min]” tworzą tabelę kroków z edytowalnym opadem [mm]; wklejenie kolumny z arkusza wypełnia kolejne wiersze; „Importuj CSV” przyjmuje 1 kolumnę (opad, bieżący krok) albo 2 kolumny (czas, opad; równy krok ustawia krok i czas trwania); „Wczytaj z bieżącego hietogramu” kopiuje serię PMAXTP. Seria trafia do `custom_precipitation`, a hietogram PMAXTP jest wtedy pomijany.
- **Formularz hydrogramu** — siatka dwóch kolumn: „Model UH” | „Metoda Tc”, dla Nasha „Model UH” | „Estymacja Nash”; uwagi o stosowalności w równych wierszach.
- **Tryb zaawansowany** — `advanced.js` pozwala zmienić morfometrię wysyłaną do `POST /api/generate-hydrograph` (szybka ścieżka `morphometry`): powierzchnia, obwód, długość, wysokości, średni spadek, długość i spadek cieku, `length_to_centroid_km`, CN. Dokładność pól: powierzchnia 0,01 km², długości i Lc 0,01 km, wysokości 0,1 m, spadki 0,01 %, CN 0,1 (1–100). Zmienione pola są oznaczone; przywracanie pola i całości („Przywróć dane z Hydrografa”); błędy walidacji blokują zapytanie; wynik ma komunikat „Obliczono na zmienionych danych wejściowych”. Opad i AMC ustawia się w sekcji Hietogram. Część zlewni ma `length_to_centroid_km = 0` — Snyder zawodzi, dopóki użytkownik nie poda Lc.
- **CN** — API zwraca CN zlewni (`morphometry.cn`, `land_cover_stats.weighted_cn`) z dokładnością 0,1; panel pokazuje go z jednym miejscem po przecinku.
- **Warstwa kanalizacji** — wpis „Kanalizacja deszczowa” w panelu „Warstwy” powstaje tylko, gdy `GET /api/layers` zwraca `sewer: true`; bez danych brak żądań kafli `/api/tiles/sewer`.
- **Wyniki analiz zewnętrznych** — `results.js` czyta raz przy starcie manifest `/data/results/index.json` (`frontend/data/results/`, serwowany przez `location ^~ /data/`):

  ```json
  {"schema": "hydrograf-results/1",
   "results": [{"id": "sfincs-kamiennik-12h-p1", "title": "Głębokość wody — SFINCS, opad 12 h, p = 1%",
                "group": "Wyniki analiz", "kind": "raster_tiles",
                "tiles": "/data/results/sfincs-kamiennik-12h-p1/tiles/{z}/{x}/{y}.png",
                "bounds": [15.88, 50.98, 16.05, 51.06], "min_zoom": 10, "max_zoom": 16, "opacity": 0.8,
                "legend": {"title": "Maks. głębokość wody", "unit": "m",
                           "classes": [{"label": "0,05–0,2", "color": "#c6dbef"}, {"label": "> 2", "color": "#08306b"}]},
                "description": "…", "source": "Hydraulik 0.1.0.dev0 / SFINCS v2.4.1"}]}
  ```

  `bounds` to [zachód, południe, wschód, północ] w WGS84, kafle XYZ PNG z przezroczystością (`gdal2tiles --xyz`). Każdy wynik `raster_tiles` daje wiersz w grupie `group` (istniejąca „Wyniki analiz” pod „Linie spływu”; nowa grupa powstaje nad podkładami tylko, gdy wynik jej wymaga): `L.tileLayer` w panelu `resultsPane` (z-index 300: nad NMT i pokryciem terenu, pod liniami spływu) z `bounds`, `minZoom` 8, `minNativeZoom`/`maxNativeZoom` z manifestu, kryciem z `opacity`; legenda (próbki z `legend.classes`, jednostka w tytule) tylko przy włączonej warstwie; `description` i `source` w objaśnieniu (i). Zasięg wliczany do „Przybliż do zasięgu warstw”. Inne `kind` są pomijane z ostrzeżeniem; brak manifestu, błędny JSON lub inny `schema` — jedno ostrzeżenie w konsoli i brak wierszy.
- **Szerokość paneli** — uchwyty między panelami (lewy 260–560 px, prawy 340–720 px), zapamiętywane w `localStorage`; panele można zamknąć.
- **Telefon (≤ 860 px)** — mapa na pełnym ekranie, dolny pasek zamiast szyny, panele jako arkusze wysuwane od dołu.

`/admin` i `/instrukcja` używają tej samej powłoki (`chrome.css`) i przełącznika `theme-switch.js`. Formularz „Zgłoś uwagę” to natywny `<dialog>`.

#### 4.2.1 Mapa (Leaflet.js)

Podkłady (`layers.js`): **OpenFreeMap szary** (wektorowy, styl `positron` z `https://tiles.openfreemap.org`, renderowany przez MapLibre GL 4.7.1 i `@maplibre/maplibre-gl-leaflet` 0.0.22; bez MapLibre powrót do OSM GUGiK), **OSM GUGiK szary** (rastrowy, tylko Polska, odbarwiony klasą `.basemap-grey`), **Ortofotomapa ESRI**, **bez podkładu**.

**Mapa zagrożenia powodziowego (MZP)** — nakładka w grupie „Podkłady kartograficzne”, nad listą podkładów: pole wyboru niezależne od wyboru podkładu (domyślnie wyłączone), krycie 80 %, a gdy włączona — pole „Prawdopodobieństwo powodzi” (0,2 % — raz na 500 lat, 1 % — raz na 100 lat (domyślnie), 10 % — raz na 10 lat), podpowiedź o skali i legenda w lewym dolnym rogu mapy. Źródło: usługi WMS 1.3.0 (ArcGIS Server) Państwowego Gospodarstwa Wodnego Wody Polskie (KZGW, ISOK) z głębokością wody w MZP z aktualizacji 2020, dla powodzi od rzek:

| Prawdopodobieństwo | Usługa (`https://wody.isok.gov.pl/gpservices/KZGW/<usługa>/MapServer/WMSServer`) | Warstwa |
|---|---|---|
| 0,2 % (raz na 500 lat) | `MZP20_Glebokosc_NiskiePrawdopodPowodzi` | `16` |
| 1 % (raz na 100 lat) | `MZP20_Glebokosc_SredniePrawdopodPowodzi` | `16` |
| 10 % (raz na 10 lat) | `MZP20_Glebokosc_WysokiePrawdopodPowodzi` | `1` |

- `L.tileLayer.wms` w EPSG:3857, PNG z przezroczystością, obrazy 512 px (trzy razy mniej zapytań niż 256 px przy tej samej rozdzielczości); zmiana prawdopodobieństwa podmienia adres i `layers` tej samej warstwy (`setUrl`, `setParams`), więc stan włączenia i krycie zostają. Warstwy morskie tych usług (warstwa `1` dla 1 % i 0,2 %) i inne scenariusze MZP nie są pokazywane. Numery warstw ArcGIS mogą się zmienić przy ponownej publikacji usług — wtedy trzeba poprawić `MZP_SCENARIOS` w `layers.js`.
- Usługi rysują głębokości tylko w skali 1:50 000 i większej (`MaxScaleDenominator` 47 247 przy pikselu 0,28 mm), czyli od przybliżenia 14. Poniżej warstwa jest zdejmowana z mapy (bez pustych zapytań), a panel i legenda pokazują „Przybliż mapę…”. Warstwa nie ma `minZoom`: Leaflet przyjąłby go jako dolną granicę przybliżenia całej mapy, gdy to jedyna warstwa kaflowa (np. przy podkładzie OpenFreeMap).
- Panel `hazardPane` (z-index 240): nad podkładem (`tilePane`, 200), pod NMT i wszystkimi warstwami Hydrografa — wyniki analiz (np. SFINCS) leżą nad MZP. Przy włączonym NMT (krycie 70 %) MZP jest przygaszona; trzeba zmniejszyć krycie NMT.
- Legenda z klas głębokości usług (GetLegendGraphic: h ≤ 0,5 · 0,5 < h ≤ 2,0 · 2,0 < h ≤ 4,0 · h > 4,0 m) w kolorach, jakimi usługi rysują mapę (`#cfe8fa`, `#a7caf7`, `#7face3`, `#7f98b9`, sprawdzone GetFeatureInfo); obraz GetLegendGraphic (96 × 72 px na białym tle) nie jest używany, bo nie pasuje do ciemnego motywu.
- Atrybucja: „MZP © Wody Polskie / ISOK (CC BY 4.0)” z odnośnikami do Hydroportalu i licencji; licencja CC BY 4.0 według zbioru „Mapa zagrożenia powodziowego (MZP)” na dane.gov.pl (dostawca: Krajowy Zarząd Gospodarki Wodnej). Usługi REST/WMTS ArcGIS tych map zwracają 401, publiczny jest tylko WMS. Czas odpowiedzi bywa nierówny: zwykle 0,4–2 s na obraz, czasem pojedyncze obrazy 10–30 s.

```javascript
// map.js (szkic)
const map = L.map('map').setView([52.0, 21.0], 10);

// Vector basemap: OpenFreeMap through MapLibre GL
L.maplibreGL({
    style: 'https://tiles.openfreemap.org/styles/positron'
}).addTo(map);

// Click routing depends on the mode bar (browse / select / profile)
map.on('click', async (e) => {
    const { lat, lng } = e.latlng;
    await delineateWatershed(lat, lng);
});
```

#### 4.2.2 API Client
```javascript
// api.js
const API_URL = 'http://localhost:8000/api';

async function delineateWatershed(lat, lon) {
    try {
        showLoader('Wyznaczam zlewnię...');
        
        const response = await fetch(`${API_URL}/delineate-watershed`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ latitude: lat, longitude: lon })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Błąd serwera');
        }
        
        const data = await response.json();
        displayWatershed(data.watershed);
        
        hideLoader();
        return data;
        
    } catch (error) {
        hideLoader();
        showError(error.message);
        throw error;
    }
}

async function generateHydrograph(lat, lon, duration, probability) {
    // Similar structure
}
```

#### 4.2.3 Wykres Hydrogramu

Wszystkie wykresy (`charts.js`) biorą kolory, czcionkę i jej rozmiar z tokenów (`getComputedStyle`), a przy zmianie motywu (`data-theme` lub schemat systemu) przemalowują się w miejscu. Hietogram jest wykresem liniowym jak hydrogram; pokrycie terenu i grupy HSG to poziome słupki skumulowane. Poniższy szkic pokazuje sam układ Chart.js; stałe kolory w nim to tylko przykład.

```javascript
// chart.js
let hydrographChart = null;

function displayHydrograph(hydrographData) {
    const ctx = document.getElementById('hydrographChart').getContext('2d');
    
    if (hydrographChart) {
        hydrographChart.destroy(); // Cleanup previous chart
    }
    
    hydrographChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: hydrographData.time_min,
            datasets: [{
                label: 'Przepływ [m³/s]',
                data: hydrographData.discharge_m3s,
                borderColor: '#007BFF',
                backgroundColor: 'rgba(0, 123, 255, 0.1)',
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            plugins: {
                title: {
                    display: true,
                    text: `Hydrogram Odpływu (Qmax = ${hydrographData.peak_discharge_m3s.toFixed(2)} m³/s)`
                },
                legend: {
                    display: false
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: 'Czas [min]'
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Przepływ [m³/s]'
                    },
                    beginAtZero: true
                }
            }
        }
    });
}
```

---

### 4.3 State Management

**Prosty state w vanilla JS:**
```javascript
// app.js
const appState = {
    currentWatershed: null,
    currentHydrograph: null,
    selectedDuration: '1h',
    selectedProbability: 10
};

function updateState(key, value) {
    appState[key] = value;
    // Trigger UI updates if needed
}
```

---

## 5. Deployment Architecture

### 5.1 Docker Compose Stack

```yaml
# docker-compose.yml
version: '3.8'

services:
  db:
    image: postgis/postgis:16-3.4
    container_name: hydro_db
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-hydro_db}
      POSTGRES_USER: ${POSTGRES_USER:-hydro_user}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-hydro_password}
      POSTGIS_GDAL_ENABLED_DRIVERS: ENABLE_ALL
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./docker/init_scripts:/docker-entrypoint-initdb.d:ro
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: "2.0"
    shm_size: 256m
    command: >
      postgres
        -c shared_buffers=512MB
        -c work_mem=16MB
        -c maintenance_work_mem=256MB
        -c effective_cache_size=1536MB
        -c random_page_cost=1.1
        -c jit=off
        -c statement_timeout=120000
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-hydro_user} -d ${POSTGRES_DB:-hydro_db}"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: hydro_api
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-hydro_user}:${POSTGRES_PASSWORD:-hydro_password}@db:5432/${POSTGRES_DB:-hydro_db}
      LOG_LEVEL: ${LOG_LEVEL:-INFO}
      DEM_DIR: ${DEM_DIR:-/data/nmt}
      ADMIN_API_KEY: ${ADMIN_API_KEY:-}
      ADMIN_API_KEY_FILE: ${ADMIN_API_KEY_FILE:-}
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 8G
          cpus: "2.0"
    volumes:
      - ./backend:/app
      - ./data:/data
      - ./frontend/data:/frontend/data
      - ./frontend/tiles:/frontend/tiles
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

  nginx:
    image: nginx:alpine
    container_name: hydro_nginx
    ports:
      - "${HYDROGRAF_PORT:-8080}:80"
    volumes:
      - ./frontend:/usr/share/nginx/html:ro
      - ./docker/nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - api
    restart: unless-stopped

volumes:
  postgres_data:
```

---

### 5.1.1 Konteneryzacja — Multi-stage i override (ADR-035)

**Multi-stage Dockerfile** (`backend/Dockerfile`):
- **Stage 1 (builder):** instalacja zaleznosci z `requirements.txt` (gcc, git dla pip install z GitHub)
- **Stage 2 (runtime):** kopiowanie zainstalowanych pakietow z buildera — obraz bez gcc/git w produkcji

**`entrypoint.sh`:**
- Wait-for-db — petla `pg_isready` z retry (max 30 prob, 1s interwal)
- Automatyczne migracje Alembic (`alembic upgrade head`) na starcie kontenera
- Exec do procesu glownego (uvicorn)

**Override pattern (dev/prod):**
- `docker-compose.yml` — bazowy plik (db + api + nginx), bez `--reload`, bez bind mount kodu
- `docker-compose.override.yml` — automatycznie ladowany w dev: bind mount `./backend:/app`, `--reload`, `LOG_LEVEL=DEBUG`
- `docker-compose.prod.yml` — override produkcyjny: 2 workery uvicorn, `LOG_LEVEL=WARNING`, bez `--reload`

**Healthcheck API:**
- Kontener `api`: healthcheck `python -c "urllib.request.urlopen('http://localhost:8000/health')"` (30s interval)
- Kontener `nginx`: `depends_on: api: condition: service_healthy`

**Uruchomienie:**
- Dev: `docker compose up` (automatycznie laduje override.yml)
- Prod: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`

---

### 5.2 Nginx Configuration

```nginx
# docker/nginx.conf
events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    gzip on;
    gzip_types text/plain text/css application/json application/geo+json
               application/javascript text/xml application/xml application/x-protobuf;

    # Rate limiting zones
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=tile_limit:10m rate=30r/s;
    limit_req_zone $binary_remote_addr zone=general_limit:10m rate=30r/s;

    upstream api_backend {
        server api:8000;
    }

    server {
        listen 80;
        server_name localhost;

        # Security headers
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Frame-Options "DENY" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
        add_header Content-Security-Policy "default-src 'self'; ..." always;
        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

        # Tile proxy (^~ prevents regex .png match)
        location ^~ /api/tiles/ {
            limit_req zone=tile_limit burst=200 nodelay;
            proxy_pass http://api_backend/api/tiles/;
            proxy_read_timeout 15s;
            proxy_cache_valid 200 1d;
        }

        # Cache for static files
        location ~* \.(css|js|png|ico|svg|pbf|geojson)$ {
            root /usr/share/nginx/html;
            expires 1h;
            add_header Cache-Control "public, must-revalidate";
        }

        # Admin panel
        location = /admin {
            root /usr/share/nginx/html;
            try_files /admin.html =404;
        }

        # Frontend - static files
        location / {
            root /usr/share/nginx/html;
            index index.html;
            try_files $uri $uri/ /index.html;
        }

        # Admin SSE stream (longer timeout for bootstrap)
        location = /api/admin/bootstrap/stream {
            proxy_pass http://api_backend/api/admin/bootstrap/stream;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Admin-Key $http_x_admin_key;
            proxy_read_timeout 3600s;
            proxy_buffering off;
        }

        # API proxy
        location /api/ {
            limit_req zone=api_limit burst=20 nodelay;
            proxy_pass http://api_backend/api/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_read_timeout 120s;
        }

        # Health check endpoint
        location /health {
            proxy_pass http://api_backend/health;
            proxy_set_header Host $host;
        }
    }
}
```

**CSP — dozwolone hosty zewnętrzne** (`docker/nginx.conf` i `docker/nginx-ssl.conf.template`, identycznie):
- `script-src`, `style-src`: `https://unpkg.com` (Leaflet, MapLibre GL, maplibre-gl-leaflet), `https://cdn.jsdelivr.net` (Chart.js, Bootstrap w `/admin`); wszystkie biblioteki z CDN z SRI (`integrity`).
- `img-src`: `data:`, `blob:`, `https://mapy.geoportal.gov.pl` (OSM GUGiK, także mapa wyboru obszaru w `/admin`), `https://server.arcgisonline.com` (ortofotomapa ESRI), `https://wody.isok.gov.pl` (mapa zagrożenia powodziowego, WMS Wód Polskich).
- `connect-src`: `https://tiles.openfreemap.org` (styl, kafle wektorowe i glify OpenFreeMap pobierane przez MapLibre).
- `worker-src blob:`, `child-src blob:` — Web Worker MapLibre GL.

---

### 5.3 Środowiska (Environments)

```
┌─────────────────────────────────────────────────────────┐
│                      DEVELOPMENT                        │
│  - .venv + docker compose up -d db (tylko PostGIS)     │
│  - uvicorn api.main:app --reload                       │
│  - Debug logs (DEBUG level)                            │
│  - Sample data in database                             │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                       STAGING                           │
│  - docker compose -f ... -f docker-compose.prod.yml up   │
│  - Production-like data                                │
│  - INFO logs                                           │
│  - Manual deployment                                   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                      PRODUCTION                         │
│  - docker compose -f ... -f docker-compose.prod.yml up -d│
│  - Full preprocessing data                             │
│  - WARNING+ logs, 2 workery uvicorn                    │
│  - HTTPS enabled                                       │
│  - Backups configured                                  │
│  - Monitoring (Prometheus + Grafana)                   │
└─────────────────────────────────────────────────────────┘
```

---

## 6. Security Architecture

### 6.1 Threat Model

**Assets:**
- Database (NMT graf, precipitation data)
- API endpoints
- User data (minimal - tylko lokalizacje zlewni)

**Threats:**
- SQL Injection
- XSS (Cross-Site Scripting)
- CSRF (Cross-Site Request Forgery)
- DDoS
- Unauthorized access

**Mitigations:**
- ✅ Parametryzowane SQL queries (SQLAlchemy ORM)
- ✅ Input validation (Pydantic)
- ✅ Rate limiting (Nginx — 3 strefy: api_limit, tile_limit, general_limit)
- ✅ CORS z restrykcyjnymi origins (env var `CORS_ORIGINS`), `allow_credentials=False`
- ✅ GZip middleware (FastAPI)
- ✅ Request ID tracing (`X-Request-ID` header, structlog context)
- ✅ Security headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options)
- ✅ Resource limits Docker (memory: 2G db, 8G api)
- ✅ Admin API key auth (X-Admin-Key header, file-based lub env var, ADR-034)
- ✅ No user authentication needed (internal network only in MVP)

---

### 6.2 Security Layers

```
┌─────────────────────────────────────────────────────────┐
│                    NETWORK LAYER                        │
│  - Firewall (UFW): tylko porty 80, 443, 22            │
│  - Internal network only (no public internet access)    │
└─────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                 APPLICATION LAYER                       │
│  - Input validation (Pydantic)                         │
│  - Rate limiting (3 zones: api, tile, general)         │
│  - CORS (restrictive origins, no credentials)          │
│  - GZip compression, X-Request-ID tracing              │
│  - Security headers (CSP, HSTS, X-Frame-Options)       │
└─────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                   DATABASE LAYER                        │
│  - Parametryzowane queries (SQLAlchemy)               │
│  - Read-only user dla preprocessing data              │
│  - Backups encrypted                                   │
└─────────────────────────────────────────────────────────┘
```

---

## 7. Monitoring & Observability

### 7.1 Logging

**Structured Logging (structlog):**
```python
# api/main.py
import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()       # INFO+ → JSON
        if settings.log_level != "DEBUG"
        else structlog.dev.ConsoleRenderer(),     # DEBUG → human-readable
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)

# Request ID middleware
@app.middleware("http")
async def add_request_id(request, call_next):
    request_id = str(uuid.uuid4())[:8]
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response
```

**Log Levels:**

---

### 7.2 Metrics (Opcjonalnie - Prometheus)

**Metryki do zbierania:**
- Request count (by endpoint)
- Request duration (histogram)
- Active connections
- Database query duration
- Error rate (5xx responses)

**Prometheus client:**
```python
from prometheus_client import Counter, Histogram

request_count = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint'])
request_duration = Histogram('http_request_duration_seconds', 'HTTP request duration')

@app.middleware("http")
async def prometheus_middleware(request, call_next):
    with request_duration.time():
        response = await call_next(request)
    request_count.labels(method=request.method, endpoint=request.url.path).inc()
    return response
```

---

### 7.3 Health Checks

```python
# api/endpoints/health.py
from fastapi import APIRouter, Depends
from sqlalchemy import text

router = APIRouter()

@router.get("/health")
async def health_check(db = Depends(get_db)):
    try:
        # Check database
        result = db.execute(text("SELECT 1"))
        db_status = "connected" if result else "disconnected"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return {
        "status": "healthy" if db_status == "connected" else "unhealthy",
        "database": db_status,
        "version": "1.0.0"
    }
```

---

## 8. Scalability

### 8.1 Vertical Scaling (MVP Approach)

**Current specs (MVP):**
- CPU: 4 cores
- RAM: 8 GB
- Disk: 100 GB SSD
- Network: 100 Mbps

**Scale-up path:**
- CPU: 8 cores
- RAM: 16 GB
- Disk: 200 GB SSD
- Network: 1 Gbps

**Bottlenecks:**
- Database queries (resolve with indexing, query optimization)
- Hydrograph generation (CPU-bound, consider caching)

---

### 8.2 Horizontal Scaling (Future)

**When needed:** > 50 concurrent users

**Architecture changes required:**
```
┌─────────────────────────────────────────────────────────┐
│                    Load Balancer                        │
│                      (Nginx)                            │
└────────┬─────────────────────────────┬──────────────────┘
         │                             │
┌────────▼──────────┐        ┌─────────▼─────────┐
│   API Instance 1  │        │  API Instance 2   │
│    (FastAPI)      │        │    (FastAPI)      │
└────────┬──────────┘        └─────────┬─────────┘
         │                             │
         └──────────┬──────────────────┘
                    │
         ┌──────────▼──────────┐
         │   PostgreSQL        │
         │  (Primary/Replica)  │
         └─────────────────────┘
```

**Dodatkowe komponenty:**
- Redis dla cache i session storage
- Message queue (Celery + RabbitMQ) dla długich zadań
- CDN dla static assets

---

## 9. Disaster Recovery

### 9.1 Backup Strategy

**Database backups:**
```bash
# Cron job: codziennie o 2 AM
0 2 * * * docker exec hydro_db pg_dump -U hydro_user hydro_db | gzip > /backups/hydro_db_$(date +\%Y\%m\%d).sql.gz

# Retention: 7 dni local, 30 dni remote (rsync na zdalny magazyn)
```

**Application code:**
- Git repository (GitHub/GitLab)
- Tagged releases

**Preprocessing data:**
- Export `stream_network`, `stream_catchments`, `precipitation_data`, `land_cover` raz po preprocessingu
- Store na zewnętrznym dysku

---

### 9.2 Recovery Procedures

**Scenariusz 1: Database corruption**
1. Stop aplikację: `docker compose down`
2. Restore z backupu: `gunzip -c backup.sql.gz | docker exec -i hydro_db psql -U hydro_user hydro_db`
3. Restart: `docker compose up -d`
4. Verify: Check `/health` endpoint

**Scenariusz 2: Server failure**
1. Provision nowy serwer
2. Install Docker
3. Clone repo: `git clone ...`
4. Restore database z backupu
5. Deploy: `docker compose up -d`
6. Update DNS (jeśli dotyczy)

**RTO (Recovery Time Objective):** < 4 godziny  
**RPO (Recovery Point Objective):** < 24 godziny (daily backups)

---

## 10. Performance Optimization

### 10.0 Podejście do Wydajności

**Preprocessing (jednorazowy):**
- Bulk INSERT via PostgreSQL COPY (ADR-006) zamiast individual INSERT
- Numba `@njit` dla operacji na rastrach (ADR-017)
- `pyflwdir.basins()` zamiast Python loops (ADR-016)

**Runtime API:**
- CatchmentGraph BFS in-memory (milisekundy) zamiast recursive CTE na flow_network (sekundy) — ADR-021, ADR-022
- Pre-computed stats w `stream_catchments` (zero operacji rastrowych w runtime)
- Cascaded merge threshold dla dużych zlewni (>500 segmentów) — ADR-042

**Aktualne wyniki benchmarków:** patrz `docs/PROGRESS.md`

---

### 10.1 Backend Optimizations

**Database:**
- Connection pooling (10 connections + 5 overflow)
- Partial indexes (is_stream = TRUE tylko)
- Materialized views (future)

**Python:**
- Używaj NumPy vectorization zamiast Python loops
- Leniwe ładowanie danych (generator expressions)
- Async I/O dla API calls (FastAPI async endpoints)

**Example - Vectorized calculations:**
```python
# DOBRZE - vectorized
import numpy as np

def oblicz_opad_efektywny(intensywnosci, cn):
    P_cum = np.cumsum(intensywnosci)
    S = 25400 / cn - 254
    Pe_cum = np.where(P_cum > 0.2 * S, 
                      (P_cum - 0.2 * S)**2 / (P_cum + 0.8 * S), 
                      0)
    return np.diff(Pe_cum, prepend=0)

# ŹLE - Python loop (wolniejsze 10-100x)
def oblicz_opad_efektywny_slow(intensywnosci, cn):
    P_cum = []
    total = 0
    for i in intensywnosci:
        total += i
        P_cum.append(total)
    
    Pe = []
    for P in P_cum:
        if P > 0.2 * S:
            Pe.append((P - 0.2 * S)**2 / (P + 0.8 * S))
        else:
            Pe.append(0)
    return Pe
```

---

### 10.2 Frontend Optimizations

**Map:**
- Lazy loading tiles
- Simplify geometries (Douglas-Peucker) dla wyświetlania
- Use canvas renderer dla dużej liczby features

**Chart:**
- Downsampling dla > 1000 punktów (Largest Triangle Three Buckets)
- Use decimation plugin

**Network:**
- Gzip compression (Nginx)
- Cache static assets (1 year)
- Minify JS/CSS (production build)

---

## 11. Testing Strategy

### 11.1 Test Pyramid

```
         /\
        /  \  E2E Tests (10%)
       /    \  - Selenium/Playwright
      /------\  - Critical user paths
     /        \
    / Integr.  \ Integration Tests (20%)
   /   Tests    \ - API endpoints + DB
  /--------------\ - Real database
 /                \
/   Unit Tests     \ Unit Tests (70%)
/     (70%)         \ - Pure functions
/--------------------\ - Mocked dependencies
```

**Strategia testowania:**
- **Unit tests** — moduły core z mockowanymi zależnościami (pytest + fixtures)
- **Integration tests** — endpointy API z prawdziwą bazą PostGIS (test service w CI)
- **E2E scripts** — `process_dem.py` (pełny pipeline end-to-end)
- **CI:** pytest z coverage (aktualna liczba testów w wynikach CI)

---

### 11.2 CI/CD Pipeline

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  lint:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - run: pip install ruff mypy
      - name: Ruff check
        run: ruff check .
      - name: Ruff format check
        run: ruff format --check .

  test:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    services:
      postgres:
        image: postgis/postgis:16-3.4
        env:
          POSTGRES_DB: hydro_test
          POSTGRES_USER: hydro_user
          POSTGRES_PASSWORD: hydro_password
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U hydro_user -d hydro_test"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    env:
      DATABASE_URL: postgresql://hydro_user:hydro_password@localhost:5432/hydro_test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -e ".[dev]"
      - name: Run tests
        run: python -m pytest tests/ -v --tb=short

  security:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
      - run: pip install pip-audit
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Security audit
        run: pip-audit
        continue-on-error: true
```

---

## 12. Dokumentacja Architektury

### 12.1 C4 Model

**Level 1: System Context**
```
┌──────────────┐         ┌────────────────────────┐
│              │         │                        │
│  Użytkownik  ├────────►│  System Analizy        │
│  (Planista)  │  Używa  │  Hydrologicznej        │
│              │         │                        │
└──────────────┘         └───────┬────────────────┘
                                 │
                                 │ Pobiera dane
                                 │
                    ┌────────────▼────────────┐
                    │                         │
                    │  GUGIK / IMGW           │
                    │  (Źródła danych)        │
                    │                         │
                    └─────────────────────────┘
```

**Level 2: Container Diagram** - patrz sekcja 1.1

**Level 3: Component Diagram** - patrz sekcja 2.1

**Level 4: Code** - patrz DEVELOPMENT_STANDARDS.md i inline documentation

---

## 13. Podsumowanie Decyzji Architektonicznych

| Aspekt | Decyzja | Uzasadnienie |
|--------|---------|--------------|
| **Backend Framework** | FastAPI | Szybkie, async, auto docs (OpenAPI) |
| **Database** | PostgreSQL + PostGIS | Standardowe dla GIS, potężne spatial queries |
| **Frontend** | Vanilla JS + Leaflet | Prostota, brak build step dla MVP |
| **Deployment** | Docker Compose | Powtarzalność, izolacja |
| **Preprocessing** | Jednorazowy (graf) | Szybkość runtime > czas preprocessing |
| **Model hydrologiczny** | SCS CN + UH / Nash IUH / Snyder UH | Sprawdzony, odpowiedni dla małych zlewni |
| **Hietogram** | Block / Euler II / Beta | 3 metody do wyboru w zależności od zastosowania |

---

**Wersja dokumentu:** 2.3
**Data ostatniej aktualizacji:** 2026-11-01
**Status:** Approved for implementation

**Historia zmian:**
- 2.3 (2026-11-01): GUI w identyfikacji wizualnej Nogata (ADR-065) — §4.1 nowa struktura `frontend/` (`tokens.css`, `chrome.css`, `app.css`, `shell.js`, `theme-init.js`, `theme-switch.js`, `img/hydrograf.svg`; usunięte `glass.css`, `style.css`, `draggable.js`), §4.2 powłoka Archiwisty i podkłady (OpenFreeMap przez MapLibre GL), wykresy w tokenach; §5.2 hosty CSP
- 2.2 (2026-10-08): Kartograf 0.7.0 (etap K) — `download_dem.py`: `download_sheets()` zwraca `NmtDownloadReport` lub rzuca `NmtDownloadError`; `MetadataCache` w `<cache_dir>/kartograf_meta.db` (dysk lokalny, nigdy udział sieciowy); układ `cache/nmt/pl_<uklad>_<res>_evrf2007/` + `kampanie/`; mozaika z listy plików kroku 2 (szczegóły: `docs/integrations/KARTOGRAF.md` §6)
- 2.1 (2026-09-28): `utils/sheet_finder.py` → `utils/sheet_lookup.py` — pozyskiwanie danych wylacznie przez Kartograf (ADR-057), cienki wrapper na `kartograf.find_sheets_for_bbox()` zamiast wlasnej reimplementacji matematyki godel
- 2.0 (2026-03-28): Przebudowa topologii kanalizacji (ADR-052) — nowy modul sewer_topology.py (parser + walidator), jawna topologia zamiast heurystyk, 4 role wezlow (inlet/outlet/junction/storage), 2 formaty wejsciowe (A/B), pipeline dwufazowy, download_sewer.py zwraca tuple, migracja 027 (isolated->storage), admin sewer/config endpoint
- 1.9 (2026-03-27): Integracja sieci kanalizacyjnej (ADR-051) — sewer_service.py, download_sewer.py, tabele sewer_nodes/sewer_network, 3 endpointy admin sewer, MVT sewer tiles, pipeline steps 3b/4a-4c, is_sewer_augmented w stream_network
- 1.8 (2026-03-25): Aktualizacja po CP4+ — ADR 035-049 w tabeli, boundary.py i clean.py, koncepcyjne opisy CatchmentGraph/watershed_service (bez sygnatur), bdot_streams + nowe kolumny w schema, sekcja 2.5 (nowe koncepty), aktualizacja liczników (24+ migracji, 45+ unit tests, 8+ integration), modele hydrologiczne (Nash IUH, Snyder UH) i hietogramy (Block/Euler II/Beta)
- 1.7 (2026-03-01): Aktualizacja vs rzeczywisty stan kodu — dodano: panel admin (ADR-034, 8 endpointów, admin.html, 3 moduły JS admin/), landcover MVT tiles, api/dependencies/, sekcja scripts/ (16 skryptów), 17 migracji, ADR-026..034; zaktualizowano: Docker (API memory 4G, ADMIN_API_KEY, volumes), Nginx (admin, SSE, health, static cache), config.py opis YAML, security (admin auth)
- 1.6 (2026-02-16): Pełna aktualizacja — nowe tabele (stream_catchments, depressions), ADR-008..025, segmentacja konfluencyjna, Docker/Nginx zgodne z faktycznym stanem, structlog, security headers, usunięcie benchmarków liczbowych
- 1.5 (2026-02-14): Eliminacja FlowGraph z runtime (ADR-022) — diagram, moduły, przepływ danych zaktualizowane; +watershed_service.py, flow_graph.py DEPRECATED
- 1.4 (2026-02-13): Dodano catchment_graph.py i constants.py do core, zaktualizowano sygnatury morphometry.py, alfabetyczne uporządkowanie modulow core
- 1.3 (2026-02-07): Aktualizacja struktury modulow (morphometry, cn_tables, cn_calculator, raster_utils, sheet_finder), usuniecie core/hydrograph.py (przeniesiony do Hydrolog)
- 1.2 (2026-01-20): Dodano wyniki testów optymalizacji (COPY 21x, reverse trace 257x)
- 1.1 (2026-01-20): Dodano sekcję 10.0 z wynikami benchmarków z testu end-to-end
- 1.0 (2026-01-14): Wersja początkowa

---

*Ten dokument definiuje architekturę techniczną systemu. Wszelkie znaczące zmiany wymagają update tego dokumentu i review przez Tech Lead.*
