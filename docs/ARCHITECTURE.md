# ARCHITECTURE.md - Architektura Systemu
## System Analizy Hydrologicznej

**Wersja:** 1.4
**Data:** 2026-02-13
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
│  │ Flow Graph   │  │Precipitation │  │   Land Cover    │   │
│  │  Traversal   │  │   Queries    │  │   Analyzer      │   │
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
│  │ flow_network   │  │precipitation_data │  │  land_cover    │  │
│  │ (Graph)        │  │                   │  │  (Polygons)    │  │
│  └────────────────┘  └───────────────────┘  └────────────────┘  │
│                                                                 │
│  ┌────────────────┐                                             │
│  │ stream_network │                                             │
│  │ (Lines)        │                                             │
│  └────────────────┘                                             │
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

---

## 2. Architektura Backendu

### 2.1 Struktura Aplikacji FastAPI

```
backend/
├── api/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app instance
│   ├── dependencies.py            # Dependency injection
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
│   ├── catchment_graph.py         # In-memory sub-catchment graph (~87k nodes, scipy CSR + BFS)
│   ├── cn_calculator.py           # Kartograf HSG-based CN calculation
│   ├── cn_tables.py               # CN lookup tables (HSG × land cover)
│   ├── config.py                  # Settings (environment variables)
│   ├── constants.py               # Project-wide constants (CRS, unit conversions, limits)
│   ├── database.py                # Database connection pool
│   ├── db_bulk.py                 # Bulk INSERT via COPY, timeout mgmt
│   ├── flow_graph.py              # In-memory flow graph (scipy sparse CSR)
│   ├── hydrology.py               # Hydrology: fill, fdir, acc, burning
│   ├── land_cover.py              # Land cover analysis, determine_cn()
│   ├── morphometry.py             # Morphometric parameters calculation
│   ├── morphometry_raster.py      # Slope, aspect, TWI, Strahler (raster)
│   ├── precipitation.py           # Precipitation queries
│   ├── raster_io.py               # Raster I/O (ASC, VRT, GeoTIFF)
│   ├── stream_extraction.py       # Stream vectorization, subcatchments
│   ├── watershed.py               # Watershed delineation logic
│   └── zonal_stats.py             # Zonal statistics (bincount, max)
│
├── models/
│   ├── __init__.py
│   └── schemas.py                 # Pydantic models
│
├── utils/
│   ├── __init__.py
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
  "threshold_m2": 10000
}

Response: 200 OK
{
  "stream": { "segment_idx": 42, "strahler_order": 3, ... },
  "upstream_segment_indices": [42, 43, 44, ...],
  "boundary_geojson": { "type": "Feature", ... },
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

**Szczegółowy przepływ:**
1. **Frontend:** Użytkownik klika punkt (lat, lon) → POST /api/delineate-watershed
2. **API (FastAPI):** Walidacja Pydantic (czy lat/lon w zakresie)
3. **Core Logic:**
   - `watershed.find_nearest_stream(lat, lon)` → SQL query do `flow_network`
   - `watershed.traverse_upstream(outlet_id)` → rekurencyjne przejście grafu
   - `watershed.build_boundary(cells)` → ST_ConvexHull lub ST_ConcaveHull
4. **Database:** Zapytania PostGIS (z indeksami GIST)
5. **Core Logic:** Konwersja do GeoJSON
6. **API:** Return JSON response
7. **Frontend:** Leaflet.js renderuje polygon na mapie

**Czas wykonania:** < 10s (95th percentile)

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
def find_nearest_stream(lat: float, lon: float) -> Optional[int]:
    """Zwraca ID najbliższej komórki cieku."""
    pass

def traverse_upstream(outlet_id: int) -> List[Cell]:
    """Rekurencyjnie znajduje wszystkie komórki upstream."""
    pass

def build_boundary(cells: List[Cell]) -> GeoJSON:
    """Tworzy boundary jako ConvexHull lub ConcaveHull."""
    pass
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
    """Buduje kompletny słownik parametrów morfometrycznych (kompatybilny z Hydrolog)."""
    pass

def find_main_stream(
    cells: list[FlowCell],
    outlet: FlowCell,
    return_coords: bool = False,
) -> tuple[float, float] | tuple[float, float, list[tuple[float, float]]]:
    """Znajduje główny ciek algorytmem reverse trace (podążając za max flow accumulation)."""
    pass
```

#### 2.4.3 Biblioteka Hydrolog (zewnetrzna)
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

#### 2.4.4 `core/precipitation.py`
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

#### 2.4.5 `core/land_cover.py`
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
│                                                                 │
│ Indexes:                                                        │
│   - idx_stream_geom (GIST on geom)                             │
└─────────────────────────────────────────────────────────────────┘
```

---

### 3.2 Przykładowe Zapytania SQL

#### Znajdź Najbliższy Ciek
```sql
SELECT 
    id, 
    geom, 
    flow_accumulation,
    ST_Distance(geom, ST_SetSRID(ST_Point($1, $2), 2180)) as distance
FROM flow_network
WHERE is_stream = TRUE
ORDER BY distance
LIMIT 1;
```

#### Znajdź Komórki Upstream (Rekurencyjne CTE)
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
    image: postgis/postgis:15-3.3
    container_name: hydro_db
    environment:
      POSTGRES_DB: hydro_db
      POSTGRES_USER: hydro_user
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init_scripts:/docker-entrypoint-initdb.d
    ports:
      - "5432:5432"
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U hydro_user -d hydro_db"]
      interval: 10s
      timeout: 5s
      retries: 5

  api:
    build: ./backend
    container_name: hydro_api
    environment:
      DATABASE_URL: postgresql://hydro_user:${DB_PASSWORD}@db:5432/hydro_db
      LOG_LEVEL: INFO
    ports:
      - "8000:8000"
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    volumes:
      - ./backend:/app/backend
    command: uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload

  nginx:
    image: nginx:alpine
    container_name: hydro_nginx
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./frontend:/usr/share/nginx/html:ro
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
    depends_on:
      - api
    restart: unless-stopped

volumes:
  postgres_data:
```

---

### 5.2 Nginx Configuration

```nginx
# nginx/nginx.conf
upstream api_backend {
    server api:8000;
}

server {
    listen 80;
    server_name localhost;

    # Frontend
    location / {
        root /usr/share/nginx/html;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # API
    location /api/ {
        proxy_pass http://api_backend/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts
        proxy_connect_timeout 30s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    location /api/ {
        limit_req zone=api_limit burst=20 nodelay;
    }
}

# HTTPS (optional for MVP, required for production)
# server {
#     listen 443 ssl;
#     server_name yourdomain.com;
#     
#     ssl_certificate /etc/nginx/ssl/cert.pem;
#     ssl_certificate_key /etc/nginx/ssl/key.pem;
#     
#     # ... rest of config
# }
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
- ✅ Rate limiting (Nginx)
- ✅ HTTPS (Certbot)
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
│  - Rate limiting (10 req/s per IP)                     │
│  - CORS headers (if needed)                            │
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

**Log Levels:**
```python
# core/config.py
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/hydro/app.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('hydro')
```

**Log Structure:**
```json
{
  "timestamp": "2026-01-14T10:30:45Z",
  "level": "INFO",
  "module": "watershed",
  "function": "delineate",
  "message": "Watershed delineated successfully",
  "data": {
    "area_km2": 45.3,
    "duration_ms": 8532,
    "outlet_id": 123456
  }
}
```

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

### 10.0 Benchmark Results (Test Sesja 9, 2026-01-20)

**Dane testowe:** Arkusz NMT N-33-131-D-a-1-4 (2177 × 2367 komórek, 1m rozdzielczość)

#### Preprocessing NMT

| Etap | Czas | Uwagi |
|------|------|-------|
| Pobieranie z GUGiK (Kartograf) | ~30s | ✅ Akceptowalne |
| Fill depressions + D8 fdir (pyflwdir) | ~8s | ✅ Świetnie |
| Flow accumulation (pyflwdir) | ~2s | ✅ Świetnie |
| Slope calculation | <1s | ✅ Świetnie |
| **Razem analiza rastrowa** | **~5s** | ✅ Świetnie |
| INSERT do flow_network (5M rekordów) | ~55 min | ⚠️ WĄSKIE GARDŁO |
| UPDATE downstream_id (5M rekordów) | ~47 min | ⚠️ WĄSKIE GARDŁO |
| **Razem import do DB** | **~102 min** | ⚠️ Do optymalizacji |

#### Runtime (API)

| Operacja | Czas | Cel |
|----------|------|-----|
| find_nearest_stream (SQL) | <100ms | < 500ms ✅ |
| traverse_upstream (CTE, 2.24 km²) | ~30s | < 10s ⚠️ |
| build_boundary (convex hull) | ~8s | < 5s ⚠️ |
| build_morphometric_params | ~4 min | < 30s ⚠️ |
| Generowanie hydrogramu (Hydrolog) | <1s | < 5s ✅ |

#### Wnioski

1. **Analiza rastrowa (pyflwdir) jest bardzo szybka** - ~27 sekund dla 5M komórek (fill + fdir + acc)
2. **Wąskie gardło to operacje bazodanowe** - INSERT/UPDATE zajmują 99% czasu preprocessingu
3. **Runtime API jest akceptowalny** dla małych zlewni, ale dla dużych (>2 km²) może przekraczać limity

#### Przetestowane optymalizacje (Sesja 10)

| ID | Opis | Testowany zysk | Status |
|----|------|----------------|--------|
| OPT-1 | COPY zamiast INSERT | **21x szybciej** (1.5 min vs 31 min) | ✅ Potwierdzone |
| OPT-2 | PostGIS Raster | - | Niski priorytet |
| OPT-3 | Lazy loading | - | Niski priorytet |
| OPT-4 | find_main_stream (reverse trace) | **257x szybciej** (1s vs 4 min) | ✅ Potwierdzone |

#### Szczegółowe wyniki benchmarków

**OPT-1: COPY vs INSERT** (100,000 rekordów)

| Metoda | Czas | Rate | Przyspieszenie |
|--------|------|------|----------------|
| Individual INSERT | 37.82s | 2,644/s | 1.0x |
| executemany | 31.29s | 3,196/s | 1.2x |
| COPY FROM | 1.82s | 55,063/s | **20.8x** |

**OPT-4: find_main_stream** (2.24 km², 835k head cells)

| Metoda | Czas | Przyspieszenie |
|--------|------|----------------|
| Original (iterate all heads) | 246.4s | 1.0x |
| Reverse trace (follow max acc) | 0.96s | **257x** |

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

**Test counts (target):**
- Unit: ~100 tests
- Integration: ~30 tests
- E2E: ~5 tests

---

### 11.2 CI/CD Pipeline

```yaml
# .github/workflows/ci.yml
name: CI

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install deps
        run: |
          cd backend
          pip install -r requirements.txt
          pip install -e ".[dev]"
      - name: Ruff check
        run: cd backend && ruff check .
      - name: Ruff format
        run: cd backend && ruff format --check .

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgis/postgis:16-3.4
        env:
          POSTGRES_DB: test_db
          POSTGRES_USER: test_user
          POSTGRES_PASSWORD: test_pass
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install deps
        run: |
          cd backend
          pip install -r requirements.txt
          pip install -e ".[dev]"
      - name: Run tests
        run: cd backend && pytest tests/ --cov=.
      - name: Upload coverage
        uses: codecov/codecov-action@v4

  build:
    runs-on: ubuntu-latest
    needs: [lint, test]
    steps:
      - uses: actions/checkout@v4
      - name: Build Docker image
        run: docker build -t hydro:latest .
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

**Wersja dokumentu:** 1.4
**Data ostatniej aktualizacji:** 2026-02-13
**Status:** Approved for implementation

**Historia zmian:**
- 1.4 (2026-02-13): Dodano catchment_graph.py i constants.py do core, zaktualizowano sygnatury morphometry.py, alfabetyczne uporządkowanie modulow core
- 1.3 (2026-02-07): Aktualizacja struktury modulow (morphometry, cn_tables, cn_calculator, raster_utils, sheet_finder), usuniecie core/hydrograph.py (przeniesiony do Hydrolog)
- 1.2 (2026-01-20): Dodano wyniki testów optymalizacji (COPY 21x, reverse trace 257x)
- 1.1 (2026-01-20): Dodano sekcję 10.0 z wynikami benchmarków z testu end-to-end
- 1.0 (2026-01-14): Wersja początkowa

---

*Ten dokument definiuje architekturę techniczną systemu. Wszelkie znaczące zmiany wymagają update tego dokumentu i review przez Tech Lead.*
