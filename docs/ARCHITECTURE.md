# ARCHITECTURE.md - Architektura Systemu
## System Analizy Hydrologicznej

**Wersja:** 1.6
**Data:** 2026-02-16
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
│  - Business Logic        │    │  - Bootstrap (UI)            │
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
│  │ flow_network   │  │stream_catchments  │  │  land_cover    │  │
│  │ (Cells/Graph)  │  │ (Polygons)        │  │  (Polygons)    │  │
│  └────────────────┘  └───────────────────┘  └────────────────┘  │
│  ┌────────────────┐  ┌───────────────────┐  ┌────────────────┐  │
│  │ stream_network │  │precipitation_data │  │  depressions   │  │
│  │ (Lines)        │  │ (IDW scenarios)   │  │ (Blue spots)   │  │
│  └────────────────┘  └───────────────────┘  └────────────────┘  │
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
| ADR-024 | Segmentacja konfluencyjna | Podział segmentów na konfluencjach dla precyzji selekcji |
| ADR-025 | Warunkowy próg BFS | Fine BFS tylko gdy display_threshold == finest |

---

## 2. Architektura Backendu

### 2.1 Struktura Aplikacji FastAPI

```
backend/
├── api/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app instance
│   └── endpoints/
│       ├── __init__.py
│       ├── watershed.py           # POST /delineate-watershed
│       ├── hydrograph.py          # POST /generate-hydrograph
│       ├── profile.py             # POST /terrain-profile
│       ├── depressions.py         # GET /depressions
│       ├── tiles.py               # GET /tiles/streams|catchments/{z}/{x}/{y}.pbf
│       ├── select_stream.py       # POST /select-stream
│       └── health.py              # GET /health
│
├── core/
│   ├── __init__.py
│   ├── catchment_graph.py         # In-memory sub-catchment graph (~117k nodes, scipy CSR + BFS)
│   ├── cn_calculator.py           # Kartograf HSG-based CN calculation
│   ├── cn_tables.py               # CN lookup tables (HSG × land cover)
│   ├── config.py                  # Settings (environment variables)
│   ├── constants.py               # Project-wide constants (CRS, unit conversions, limits)
│   ├── database.py                # Database connection pool
│   ├── db_bulk.py                 # Bulk INSERT via COPY, timeout mgmt
│   ├── flow_graph.py              # DEPRECATED — in-memory flow graph (CLI scripts only)
│   ├── hydrology.py               # Hydrology: fill, fdir, acc, burning
│   ├── land_cover.py              # Land cover analysis, determine_cn()
│   ├── morphometry.py             # Morphometric parameters calculation
│   ├── morphometry_raster.py      # Slope, aspect, TWI, Strahler (raster)
│   ├── precipitation.py           # Precipitation queries
│   ├── raster_io.py               # Raster I/O (ASC, VRT, GeoTIFF)
│   ├── stream_extraction.py       # Stream vectorization, subcatchments
│   ├── watershed.py               # Watershed boundary building + legacy CLI functions
│   ├── watershed_service.py       # Shared delineation logic (CatchmentGraph-based, ADR-022)
│   └── zonal_stats.py             # Zonal statistics (bincount, max)
│
├── models/
│   ├── __init__.py
│   └── schemas.py                 # Pydantic models
│
├── utils/
│   ├── __init__.py
│   ├── dem_color.py               # DEM color palette, hillshade blending
│   ├── geometry.py                # Geometric operations, CRS transforms
│   ├── raster_utils.py            # Raster tools (resample, polygonize)
│   └── sheet_finder.py            # NMT sheet code lookup
│
├── tests/
│   ├── unit/
│   ├── integration/
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

#### 2.2.2 Delineate Watershed
```
POST /api/delineate-watershed
Content-Type: application/json

Request:
{
  "latitude": 52.123456,
  "longitude": 21.123456
}

Response: 200 OK
{
  "watershed": {
    "boundary_geojson": {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[lon, lat], ...]]
      },
      "properties": {
        "area_km2": 45.3
      }
    },
    "outlet": {
      "latitude": 52.123456,
      "longitude": 21.123456
    }
  }
}

Errors:
- 404: "Nie znaleziono cieku w tym miejscu"
- 500: "Błąd serwera"
```

#### 2.2.3 Generate Hydrograph
```
POST /api/generate-hydrograph
Content-Type: application/json

Request:
{
  "latitude": 52.123456,
  "longitude": 21.123456,
  "duration": "1h",
  "probability": 10
}

Response: 200 OK (pełna struktura w DATA_MODEL.md, sekcja 6.4)
```

#### 2.2.4 List Scenarios
```
GET /api/scenarios

Response: 200 OK
{
  "durations": ["15min", "30min", "1h", "2h", "6h", "12h", "24h"],
  "probabilities": [1, 2, 5, 10, 20, 50]
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

#### 2.2.7 Select Stream
```
POST /api/select-stream
Content-Type: application/json

Request:
{
  "latitude": 52.123456,
  "longitude": 21.123456,
  "threshold_m2": 10000,
  "to_confluence": false,
  "display_threshold_m2": 10000
}

Response: 200 OK
{
  "stream": { "segment_idx": 42, "strahler_order": 3, ... },
  "upstream_segment_indices": [42, 43, 44, ...],
  "boundary_geojson": { "type": "Feature", ... },
  "display_threshold_m2": 10000,
  "watershed": { "outlet": {...}, "morphometry": {...}, ... }
}

Errors:
- 404: "Nie znaleziono cieku/segmentu"
- 422: Walidacja (niepoprawne wspolrzedne, brak threshold_m2)
```

#### 2.2.8 MVT Tiles
```
GET /api/tiles/streams/{z}/{x}/{y}.pbf?threshold_m2=10000
GET /api/tiles/catchments/{z}/{x}/{y}.pbf?threshold_m2=10000
GET /api/tiles/thresholds

Response: Mapbox Vector Tiles (PBF) / JSON
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

**Szczegółowy przepływ (ADR-022, ADR-024, ADR-025):**
1. **Frontend:** Użytkownik klika punkt (lat, lon) → POST /api/select-stream (lub /delineate-watershed)
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
3. Pobierz opad (SQL query)
4. Wygeneruj hietogram Beta (Python, SciPy)
5. Oblicz opad efektywny (SCS CN)
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
**Odpowiedzialności:**
- In-memory graf zlewni cząstkowych (scipy CSR matrix)
- BFS traversal upstream/downstream
- Agregacja pre-computed stats (area, elevation, slope, stream metrics)
- Krzywa hipsometryczna z mergowania histogramów

**Główne klasy/funkcje:**
```python
class CatchmentGraph:
    """Singleton graf ~117k wezłów, ~5 MB RAM, ~1.5s startup."""
    def load(self, db: Session) -> None: ...
    def traverse_upstream(self, node_idx: int) -> list[int]: ...
    def traverse_to_confluence(self, node_idx: int) -> list[int]: ...
    def aggregate_stats(self, indices: list[int]) -> dict: ...
    def aggregate_hypsometric(self, indices: list[int]) -> list[dict]: ...
```

#### 2.4.4 `core/watershed_service.py`
**Odpowiedzialności:**
- Współdzielona logika delineacji (snap-to-stream, merge, outlet extraction)
- Używana przez 3 endpointy: watershed, hydrograph, select_stream
- Eliminuje bezpośrednie zapytania do flow_network (~19.7M rekordów)

**Główne funkcje:**
```python
def find_nearest_stream_segment(x, y, threshold_m2, db) -> dict | None: ...
def find_stream_catchment_at_point(x, y, threshold_m2, db) -> int | None: ...
def merge_catchment_boundaries(segment_idxs, threshold_m2, db) -> Polygon: ...
def map_boundary_to_display_segments(boundary, threshold_m2, db) -> list[int]: ...
def get_main_stream_geojson(segment_idx, threshold_m2, db) -> dict | None: ...
```

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
**Odpowiedzialnosci:** (delegowane do `hydrolog` v0.5.2)
- Generowanie hietogramu (Beta, Block, Euler II)
- Model SCS CN (opad efektywny)
- Hydrogram jednostkowy SCS
- Splot numeryczny
- Czas koncentracji (Kirpich, SCS Lag, Giandotti)

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
    probability: int
) -> float:
    """Pobiera wartość opadu (wieloboki równego zadeszczenia)."""
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

## 3. Architektura Bazy Danych

### 3.1 Schema Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                          flow_network                            │
├─────────────────────────────────────────────────────────────────┤
│ id (PK)              SERIAL                                     │
│ geom                 GEOMETRY(Point, 2180)                      │
│ elevation            FLOAT                                      │
│ flow_accumulation    INT                                        │
│ slope                FLOAT                                      │
│ downstream_id (FK)   INT → flow_network(id)                    │
│ cell_area            FLOAT                                      │
│ is_stream            BOOLEAN                                    │
│ strahler_order       INT                                        │
│                                                                 │
│ Indexes:                                                        │
│   - idx_flow_geom (GIST on geom)                               │
│   - idx_downstream (on downstream_id)                          │
│   - idx_is_stream (on is_stream)                               │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     precipitation_data                          │
├─────────────────────────────────────────────────────────────────┤
│ id (PK)              SERIAL                                     │
│ geom                 GEOMETRY(Point, 2180)                      │
│ duration             VARCHAR(10)  ('15min', '1h', etc)         │
│ probability          INT          (1, 2, 5, 10, 20, 50)        │
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
> Poniższy CTE zachowany wyłącznie w skryptach CLI (`core/flow_graph.py`).

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
├── index.html               # SPA — Leaflet + Bootstrap + Chart.js (CDN)
├── css/
│   ├── glass.css             # Glassmorphism CSS variables
│   └── style.css             # Custom styles
└── js/
    ├── api.js                # API calls (fetch wrappers)
    ├── map.js                # Leaflet map, layers, drawing, MVT
    ├── draggable.js          # Pointer-event drag for floating panel
    ├── charts.js             # Chart.js: donut, histogram, profile, hydrograph
    ├── layers.js             # Layers panel: base layers, overlays, opacity
    ├── profile.js            # Terrain profile (draw line / auto)
    ├── hydrograph.js         # Hydrograph scenario form + chart
    ├── depressions.js        # Depressions (blue spots) overlay
    └── app.js                # Orchestrator: init, click routing, panel
```

---

### 4.2 Komponenty UI

#### 4.2.1 Mapa (Leaflet.js)
```javascript
// map.js
const map = L.map('map').setView([52.0, 21.0], 10);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors',
    maxZoom: 18
}).addTo(map);

// Stream network layer
const streamsLayer = L.geoJSON(null, {
    style: { color: '#0066CC', weight: 2 }
}).addTo(map);

// Watershed boundary layer
let watershedLayer = null;

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
    ports:
      - "127.0.0.1:5432:5432"
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
      DEM_PATH: ${DEM_PATH:-/data/dem/dem_mosaic.vrt}
    ports:
      - "127.0.0.1:8000:8000"
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 512M
          cpus: "2.0"
    volumes:
      - ./backend:/app
      - ./data/e2e_test:/data/dem:ro
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

  nginx:
    image: nginx:alpine
    container_name: hydro_nginx
    ports:
      - "8080:80"
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
        }

        # Frontend - static files
        location / {
            root /usr/share/nginx/html;
            index index.html;
            try_files $uri $uri/ /index.html;
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
    }
}
```

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
│  - docker compose -f docker-compose.prod.yml up         │
│  - Production-like data                                │
│  - INFO logs                                           │
│  - Manual deployment                                   │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                      PRODUCTION                         │
│  - docker compose -f docker-compose.prod.yml up -d      │
│  - Full preprocessing data                             │
│  - WARNING+ logs only                                  │
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
- ✅ Resource limits Docker (memory: 2G db, 512M api)
- ✅ No authentication needed (internal network only in MVP)

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

# Retention: 7 dni local, 30 dni remote (rsync do NAS)
```

**Application code:**
- Git repository (GitHub/GitLab)
- Tagged releases

**Preprocessing data:**
- Export `flow_network`, `precipitation, `land_cover` raz po preprocessingu
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
- Cascaded merge threshold dla dużych zlewni (>500 segmentów) — ADR-024

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
- **E2E scripts** — `process_dem.py`, `e2e_task9.py` (pełny pipeline end-to-end)
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
| **Model hydrologiczny** | SCS CN + UH | Sprawdzony, odpowiedni dla małych zlewni |
| **Hietogram** | Rozkład Beta | Realistyczny, lepszy niż blokowy |

---

**Wersja dokumentu:** 1.6
**Data ostatniej aktualizacji:** 2026-02-16
**Status:** Approved for implementation

**Historia zmian:**
- 1.6 (2026-02-16): Pełna aktualizacja — nowe tabele (stream_catchments, depressions), ADR-008..025, segmentacja konfluencyjna, Docker/Nginx zgodne z faktycznym stanem, structlog, security headers, usunięcie benchmarków liczbowych
- 1.5 (2026-02-14): Eliminacja FlowGraph z runtime (ADR-022) — diagram, moduły, przepływ danych zaktualizowane; +watershed_service.py, flow_graph.py DEPRECATED
- 1.4 (2026-02-13): Dodano catchment_graph.py i constants.py do core, zaktualizowano sygnatury morphometry.py, alfabetyczne uporządkowanie modulow core
- 1.3 (2026-02-07): Aktualizacja struktury modulow (morphometry, cn_tables, cn_calculator, raster_utils, sheet_finder), usuniecie core/hydrograph.py (przeniesiony do Hydrolog)
- 1.2 (2026-01-20): Dodano wyniki testów optymalizacji (COPY 21x, reverse trace 257x)
- 1.1 (2026-01-20): Dodano sekcję 10.0 z wynikami benchmarków z testu end-to-end
- 1.0 (2026-01-14): Wersja początkowa

---

*Ten dokument definiuje architekturę techniczną systemu. Wszelkie znaczące zmiany wymagają update tego dokumentu i review przez Tech Lead.*
