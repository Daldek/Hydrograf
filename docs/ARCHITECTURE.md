# ARCHITECTURE.md - System Architecture
## Hydrological Analysis System

**Version:** 2.6
**Date:** 2026-10-25
**Status:** Approved

---

## 1. Architecture Overview

### 1.1 High-Level Architecture

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

### 1.2 Key Architectural Decisions (ADR)

The index of all architectural decisions: [docs/DECISIONS.md](DECISIONS.md)

Summary of the key ADRs:

| ADR | Decision | Rationale |
|-----|---------|--------------|
| ADR-001 | Graph in the database instead of runtime rasters | Runtime speed (< 10 s) at the cost of one-off preprocessing |
| ADR-002 | Monolithic FastAPI application | Simple deployment for the MVP (10 users) |
| ADR-003 | Leaflet.js instead of Google Maps | Open source, free, light (40 KB) |
| ADR-004 | Beta hyetograph instead of block | Realistic rainfall distribution (α=2, β=5) |
| ADR-005 | Docker Compose for deployment | Environment parity, isolated dependencies |
| ADR-006 | COPY instead of INSERT | DEM import 27x faster (3.8 min vs 102 min) |
| ADR-007 | Reverse trace | find_main_stream 330x faster (0.74 s vs 246 s) |
| ADR-012 | pyflwdir instead of pysheds | Deltares: stable, efficient, 3 dependencies |
| ADR-017 | Split process_dem into core/ modules | Thin orchestrator + testable modules |
| ADR-021 | CatchmentGraph instead of raster operations | BFS over the graph of sub-catchments instead of a CTE over 20M+ records |
| ADR-022 | Remove FlowGraph from the runtime | RAM from ~1 GB to ~40 MB, startup from ~90 s to ~3 s |
| ADR-024 | ~~Confluence segmentation~~ | ~~SUPERSEDED by ADR-026~~ |
| ADR-025 | ~~Conditional BFS threshold~~ | ~~SUPERSEDED by ADR-026~~ |
| ADR-026 | Lookup by segment_idx | O(1) lookup by `(threshold_m2, segment_idx)` instead of the auto-increment `id` |
| ADR-029 | trace_main_channel() | Selection of the main channel by Strahler order (for channel_slope) |
| ADR-032 | Boundary smoothing | `ST_SimplifyPreserveTopology(5.0)` + `ST_ChaikinSmoothing(3)` |
| ADR-033 | Building raising | `raise_buildings_in_dem()` +5 m under the BUBD footprints |
| ADR-034 | Admin panel | `/admin` + 13 `/api/admin/*` endpoints, API key auth, bootstrap SSE |
| ADR-035 | Multi-stage containerization | Multi-stage Dockerfile, entrypoint with wait-for-db, dev/prod override |
| ADR-036 | Docker container hardening | Security headers, resource limits, non-root user |
| ADR-037 | Separation of cache and data + Kartograf v0.5.0 | Separate directories for the cache and for generated data; the cache of the downloads is the Kartograf store `cache/kartograf/` since ADR-061 |
| ADR-038 | HSG Poland-wide cache | A Poland-wide HSG cache: no need to download it per area; the raster is a version of the Kartograf store (`hsg/`) since ADR-061 |
| ADR-040 | Vector boundary file support | GPKG/GeoJSON/SHP as area boundaries (instead of a bbox only) |
| ADR-041 | Monotonic stream smoothing | Keep the elevation monotonic after the stream lines are smoothed |
| ADR-042 | delineate-watershed performance optimisation | Cascaded merge threshold, batched ST_Union, graph cache |
| ADR-044 | BDOT10k stream matching | Match the DEM streams to the BDOT10k reference streams (is_real_stream) |
| ADR-045 | WFS PRG instead of WMS grid sampling | TERYT discovery from the WFS PRG: faster and more accurate than the WMS grid; replaced by Kartograf, which finds the counties of an area itself (ADR-061) |
| ADR-046 | upstream_area_km2 in trace_main_channel | Branch selection by upstream_area_km2 instead of Strahler order |
| ADR-047 | Chaikin smoothing of streams in preprocessing | Smooth the stream geometry during preprocessing |
| ADR-048 | Flow path from the watershed divide | Longest flow path + divide flow path as morphometric parameters |
| ADR-049 | DEM auto-discovery with a fallback chain | Find the DEM file automatically (VRT → mosaic → single TIFF) |
| ADR-050 | Unified delineate-watershed endpoint | One endpoint with the modes precomputed (BFS) and precise (pyflwdir on the fly) |
| ADR-051 | Storm-sewer network integration | Inlet burning + FA routing through the sewer network in preprocessing |
| ADR-060 | Pin the Hydrolog and IMGWTools heads by commit | The producers are pinned by the commit of their head until their tags exist (REL-5.3); Kartograf joins them by ADR-061 |
| ADR-061 | Kartograf data output | The store `cache/kartograf/` for the NMT, BDOT10k and the HSG raster of Poland; plain files for the HSG raster of one analysis |

---

## 2. Backend Architecture

### 2.1 FastAPI Application Structure

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
│       ├── admin.py               # 13 /api/admin/* endpoints (dashboard, resources, cleanup, bootstrap, sewer)
│       ├── depressions.py         # GET /depressions
│       ├── health.py              # GET /health
│       ├── hydrograph.py          # POST /generate-hydrograph
│       ├── profile.py             # POST /terrain-profile
│       ├── tiles.py               # GET /tiles/streams|catchments|landcover|sewer/{z}/{x}/{y}.pbf
│       └── watershed.py           # POST /delineate-watershed (precomputed + precise modes)
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
│   ├── morphometry.py             # Shape indices (calculate_shape_indices)
│   ├── morphometry_raster.py      # Slope, aspect, TWI, Strahler (raster)
│   ├── precipitation.py           # Precipitation queries
│   ├── raster_io.py               # Raster I/O (ASC, VRT, GeoTIFF)
│   ├── raster_service.py          # RasterCache — lazy-loaded raster data (DEM, flow direction, accumulation)
│   ├── soil_hsg.py                # HSG soil group data (SoilGrids)
│   ├── stream_extraction.py       # Stream vectorization, subcatchments
│   ├── sewer_service.py            # Storm-sewer integration (SewerGraph, burn inlets, FA routing, ADR-051/052)
│   ├── sewer_topology.py           # Sewer topology parser and validator (ParsedTopology, parse_sewer_topology, validate_against_fdir, ADR-052)
│   ├── watershed_service.py       # Shared delineation logic (CatchmentGraph-based, ADR-022, Chaikin smoothing ADR-032)
│   ├── zonal_stats.py             # Zonal statistics (bincount, max)
│   └── boundary.py               # Vector boundary file handling (GPKG/GeoJSON/SHP), validation, bbox conversion (ADR-040)
│
├── models/
│   ├── __init__.py
│   └── schemas.py                 # Pydantic models
│
├── scripts/
│   ├── __init__.py
│   ├── bootstrap.py               # Orchestrator: runs the full preprocessing pipeline
│   ├── process_dem.py             # Thin orchestrator (~700 lines) — NMT processing
│   ├── prepare_area.py            # Downloads and processes the NMT of one area (point + buffer); its Kartograf store is <output>/kartograf
│   ├── download_dem.py            # Downloads the NMT (DEM) from GUGiK into the Kartograf store (ADR-061): download_sheets() -> NmtDownloadReport / NmtDownloadError
│   │                              #   store: <cache_dir>/kartograf/nmt/pl_<system>_<res>_evrf2007/ (a hard-linked standard path, versions/)
│   │                              #   MetadataCache: <cache_dir>/kartograf_meta.db (local disk, never a network share); mosaic from the step 2 list
│   │                              #   details: docs/integrations/KARTOGRAF.md §3 and §7
│   ├── download_landcover.py      # Downloads land cover (BDOT10k per county, CORINE) into the store; merge_hydro_gpkgs()
│   ├── import_landcover.py        # Imports land cover into PostGIS
│   ├── preprocess_precipitation.py # Imports precipitation from IMGW
│   ├── generate_tiles.py          # Generates MVT tiles (streams, catchments, landcover)
│   ├── generate_dem_overlay.py    # DEM overlay (PNG)
│   ├── generate_dem_tiles.py      # XYZ tile pyramid of the DEM (hillshade)
│   ├── generate_streams_overlay.py # Streams overlay (PNG)
│   ├── generate_depressions.py    # Generates depressions (blue spots)
│   ├── analyze_watershed.py       # Watershed analysis (CLI)
│   ├── download_sewer.py          # Downloads the sewer network (file/WFS/DB/URL, CRS validation, SSRF protection). Returns tuple (points_gdf, lines_gdf | None)
│   └── clean.py                  # Cleans generated data (rasters, tiles, DB, cache)
│
├── migrations/
│   └── versions/                  # 1 migration (squashed initial schema)
│
├── utils/
│   ├── __init__.py
│   ├── dem_color.py               # DEM color palette, hillshade blending
│   ├── geometry.py                # Geometric operations, CRS transforms
│   ├── kartograf_store.py         # Where Kartograf writes (store, metadata cache), describe_error(), download_bdot10k() (ADR-061)
│   ├── raster_utils.py            # Raster tools (resample, polygonize)
│   └── sheet_lookup.py            # NMT sheet lookup, thin wrapper over kartograf.find_sheets_for_bbox (ADR-057)
│
├── tests/
│   ├── unit/                      # 45+ unit test files
│   ├── integration/               # 8+ integration test files
│   ├── performance/               # Performance tests (benchmarks)
│   └── conftest.py
│
├── pyproject.toml           # dependencies (ranges), dev group, tool configuration
├── uv.lock                  # exact versions (uv sync --locked)
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

Precomputed mode (with threshold_m2: snap-to-stream + BFS over the graph):
Request:
{
  "latitude": 52.123456,
  "longitude": 21.123456,
  "threshold_m2": 10000,
  "display_threshold_m2": 10000
}

Precise mode (no threshold_m2; raster delineation with pyflwdir on the fly):
Request:
{
  "latitude": 52.123456,
  "longitude": 21.123456
}

Response: 200 OK
{
  "mode": "precomputed",  // or "precise"
  "stream": { "segment_idx": 42, "strahler_order": 3, ... },
  "upstream_segment_indices": [42, 43, 44, ...],
  "boundary_geojson": { "type": "Feature", ... },
  "display_threshold_m2": 10000,
  "watershed": { "outlet": {...}, "morphometry": {...}, ... }
}

Errors:
- 404: "No stream found at this location"
- 422: Validation (invalid coordinates)
- 500: "Server error"
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

Response: 200 OK (full structure in DATA_MODEL.md, section 6.4)
```

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
All endpoints require the X-Admin-Key header (or ADMIN_API_KEY is not set).
Prefix: /api/admin

GET  /api/admin/dashboard          — table statistics, uptime, version
GET  /api/admin/resources          — CPU, RAM, disk (psutil)
GET  /api/admin/cleanup/estimate   — estimate of the space that cleanup frees
POST /api/admin/cleanup            — delete cache/tiles
GET  /api/admin/bootstrap/status   — status of the bootstrap process
POST /api/admin/bootstrap/start    — start the bootstrap subprocess
POST /api/admin/bootstrap/cancel   — cancel bootstrap
GET  /api/admin/bootstrap/stream   — SSE stream of the bootstrap logs (timeout 3600s)
POST /api/admin/bootstrap/upload-boundary — upload a watershed boundary

POST   /api/admin/sewer/upload     — upload a sewer network file (ADR-051/052), auto-detects the format, returns detected_format and layers
GET    /api/admin/sewer/status     — status of the sewer data
DELETE /api/admin/sewer/delete     — delete the sewer data
POST   /api/admin/sewer/config    — field_mapping and role_mapping configuration (ADR-052)
```

---

### 2.3 Business Logic - Data Flow

#### Watershed Delineation (Sequence Diagram)
```
User → Frontend → API → Core Logic → Database → Core Logic → API → Frontend → User
  |       |        |         |           |          |        |       |        |
  Click   POST     Validate  Find        Query     Build    JSON    Render   See
  point   request  coords    nearest     graph     GeoJSON  response boundary boundary
                             stream      upstream
```

**Detailed flow (ADR-022, ADR-026):**
1. **Frontend:** The user clicks a point (lat, lon) → POST /api/delineate-watershed (precomputed or precise mode)
2. **API (FastAPI):** Pydantic validation (are lat/lon in range)
3. **Core Logic** (`watershed_service.py` + `catchment_graph.py`):
   - `find_stream_catchment_at_point(x, y, threshold)` → snap-to-stream via `ST_ClosestPoint` on `stream_network`
   - `CatchmentGraph.traverse_upstream()` → BFS over the graph of sub-catchments
   - Cascaded merge threshold: if there are more than 500 segments, cascade to a coarser threshold (1000→10000→100000)
   - `merge_catchment_boundaries()` → ST_UnaryUnion of the pre-computed polygons in PostGIS
   - `map_boundary_to_display_segments()` → mapping to the threshold displayed for the MVT tiles
   - Aggregation of the pre-computed stats from numpy arrays (zero raster operations)
4. **Database:** PostGIS queries to `stream_network` + `stream_catchments`
5. **Core Logic:** Conversion to GeoJSON (EPSG:2180 → WGS84)
6. **API:** Return JSON response
7. **Frontend:** Leaflet.js renders the polygon on the map, MVT tiles highlight the sub-catchments

**Execution time:** < 1s (typical), < 5s (large watersheds)

---

#### Hydrograph Generation (Sequence Diagram)
```
1. Delineate the watershed (as above)
2. Compute the parameters (area, length, slope, CN)
3. Fetch the precipitation (SQL query)
4. Generate the Beta hyetograph (Python, SciPy)
5. Compute the effective precipitation (SCS CN)
6. Compute tc (Kirpich)
7. Generate the UH (SCS)
8. Convolution Pe * UH = Q(t)
9. Return JSON with a chart
```

**Execution time:** < 5s

---

### 2.4 Core Logic Modules

#### 2.4.1 `core/morphometry.py`
**Responsibilities:**
- The shape indices of a watershed (`calculate_shape_indices`: compactness, circularity, elongation, form factor, lemniscate ratio, mean width), compatible with Hydrolog's `WatershedParameters`

It is the only function of the module. The rest of the morphometry of the runtime API (area, perimeter, length, elevation,
slope, channel, drainage indices, hypsometric curve) is computed from the catchment graph by
`build_morph_dict_from_graph()` in `core/watershed_service.py` and `CatchmentGraph.aggregate_stats()`.
The main stream is traced by `CatchmentGraph.trace_main_channel()` in `core/catchment_graph.py`.

The delineation itself (nearest catchment, upstream traversal over the catchment graph, boundary
merge) is in `core/watershed_service.py` and `core/catchment_graph.py`; the API endpoint and
`scripts/analyze_watershed.py` both run it through `POST /api/delineate-watershed`.

#### 2.4.2 `core/catchment_graph.py`

Singleton in-memory graph of sub-catchments based on numpy arrays and a scipy sparse CSR matrix (~87-285k nodes depending on the area, ~0.5 MB of RAM). Loaded lazily from the database on first use and invalidated after cleanup or the pipeline by `invalidate()`.

**Key concepts:**
- **BFS traversal** — `traverse_upstream` to delineate the watershed
- **trace_main_channel** — selects the main channel with branch selection by `upstream_area_km2` (ADR-046) and returns a FeatureCollection with the segment geometries
- **aggregate_stats** — aggregation of the pre-computed zonal stats (area, elevation, slope, stream metrics) + hydraulic length relative to the outlet
- **is_real_stream** — marks the segments matched to the BDOT10k reference streams (ADR-044)
- **aggregate_hypsometric** — hypsometric curve from merging the elevation histograms per segment

Details: `core/catchment_graph.py`

#### 2.4.3 `core/watershed_service.py`

Delineation logic shared by two endpoints (watershed, hydrograph). It avoids expensive raster operations at runtime: all work is based on CatchmentGraph and pre-computed stats.

**Key responsibilities:**
- **Merge catchment boundaries** — 3 strategies: direct (small watersheds), batched ST_UnaryUnion, fallback to a coarser threshold. Cascade threshold escalation for large watersheds (>500 segments: 1000 → 10000 → 100000)
- **Boundary smoothing** — `ST_SimplifyPreserveTopology(5.0)` + `ST_ChaikinSmoothing(3)` (ADR-032)
- **Main channel FeatureCollection** — geometry of the main channel with the `is_real_stream` flag per segment (ADR-044)
- **Flow path GeoJSON** — longest flow path + divide flow path (ADR-048) as geometries to display
- **Morphometric parameters** — `build_morph_dict_from_graph()` builds a dictionary compatible with Hydrolog
- **Land cover / HSG stats** — helpers that compute the CN and the land cover within the watershed boundary

Details: `core/watershed_service.py`

#### 2.4.4 `core/db_bulk.py`
**Responsibilities:**
- Bulk INSERT via PostgreSQL COPY (55k rec/s vs 2.6k rec/s with INSERT)
- Management of statement_timeout (override + restore)

#### 2.4.5 `core/stream_extraction.py`
**Responsibilities:**
- Vectorization of streams from the accumulation raster
- Segmentation at confluences (ADR-024) and at changes of the Strahler order
- Generation of the label raster for `pyflwdir.basins()`

#### 2.4.6 `core/zonal_stats.py`
**Responsibilities:**
- Zonal statistics via `np.bincount` (O(M) instead of O(n*M) per-label masking)
- Computing min/max/mean per label for elevation and slope

#### 2.4.7 Hydrolog library (external)
**Responsibilities:** (delegated to `hydrolog`, pinned by commit in `backend/pyproject.toml`, ADR-060)
- Hyetograph generation (Beta, Block, Euler II)
- SCS CN model (effective precipitation)
- Unit hydrograph: SCS, Nash IUH, Snyder
- Numerical convolution
- Time of concentration (Kirpich, NRCS, Giandotti, FAA, Kerby, Kerby-Kirpich)

Hydrograf calls Hydrolog through the endpoint `api/endpoints/hydrograph.py`:
```python
from hydrolog.precipitation import BetaHietogram
from hydrolog.runoff import HydrographGenerator
from hydrolog.morphometry import WatershedParameters
```

#### 2.4.8 `core/precipitation.py`
**Responsibilities:**
- Queries to the `precipitation_data` table
- IDW interpolation (Inverse Distance Weighting)

**Main functions:**
```python
def get_precipitation(
    centroid: Point,
    duration: str,
    probability: float
) -> float:
    """Returns the precipitation value (IDW interpolation of the IMGW point grid)."""
    pass
```

#### 2.4.9 `core/land_cover.py`
**Responsibilities:**
- Intersection of the boundary with the land cover
- Computing the weighted CN

**Main functions:**
```python
def calculate_cn(boundary: GeoJSON) -> Dict:
    """
    Returns:
    {
        'cn': 72.4,
        'land_cover_percent': {'las': 35.2, 'pola': 42.1, ...}
    }
    """
    pass
```

---

### 2.5 New Concepts (CP4+)

#### WFS TERYT discovery (ADR-045)
Automatic detection of districts (TERYT) from a bbox with the WFS PRG service (Państwowy Rejestr Granic, the National Register of Boundaries). It replaces the earlier WMS grid-sampling method with more accurate results and fewer network queries. Used when downloading BDOT10k and land cover data.

#### DEM auto-discovery (ADR-049)
A mechanism that finds the DEM file automatically with a fallback chain: VRT mosaic → single GeoTIFF → a directory of ASC files. It is configured by `resolve_dem_path()` in `core/config.py` and removes the need to give the DEM path in environment variables by hand. It also handles `resolve_stream_distance_path()` for the stream distance rasters.

#### Chaikin stream smoothing (ADR-047)
Smoothing of the stream geometry with the Chaikin algorithm during preprocessing (in `process_dem.py`). It reduces the noise of the raster vectorization and keeps the topology of the network. Used together with monotonic smoothing (ADR-041).

#### BDOT10k stream matching (ADR-044)
Matching of the streams derived from the DEM to the reference streams of BDOT10k (the topographic objects database). Matched segments are marked `is_real_stream=True` in `stream_network`. The flag is propagated to CatchmentGraph and returned in the main channel FeatureCollection.

#### Divide flow path (ADR-048)
Determination of the flow path from the watershed divide (the longest path from the watershed boundary to the outlet). It complements the longest flow path as an additional morphometric parameter. The geometries of both paths are stored in `stream_catchments` (columns `longest_flow_path_geom`, `divide_flow_path_geom`).

#### Monotonic stream smoothing (ADR-041)
Keeping the longitudinal profile of the streams monotonic after the geometry is smoothed. It removes artefacts where the smoothed stream line had local elevation "jumps" against the flow direction.

#### Storm-sewer network integration (ADR-051, ADR-052)
Inclusion of the storm-sewer network in the hydrological model. The network topology is defined explicitly by the user (it is not detected by heuristics). Two input formats: Format A (points with `downstream_id`) and Format B (points + lines with `from_node`/`to_node`). 4 node roles: inlet, outlet, junction, storage (compatible with SWMM/HEC-RAS).

**Two-phase pipeline:**
- **Phase 1 — Clean fdir:** DEM preprocessing without the sewer network (fill → fdir → acc), validation of the fdir loops (`validate_against_fdir()`)
- **Phase 2 — Sewer burning + hydrology:**
  - **Step 3b — Inlet burning:** burning of the sewer inlets into the DEM (`burn_inlets()`): lowering the elevation in the inlet cells
  - **Step 4a — FA reconstruction:** reconstruction of the flow accumulation in the inlet cells (`reconstruct_inlet_fa()`)
  - **Step 4b — Sewer routing:** routing of the flow accumulation through the sewer network (`route_fa_through_sewer()`)
  - **Step 4c — FA propagation:** propagation of the modified FA down the stream network (`propagate_fa_downstream()`)

Sewer data are stored in the tables `sewer_nodes` (nodes: inlets, outlets, junctions, storage) and `sewer_network` (pipe segments). They are imported through the admin panel (`/api/admin/sewer/upload`) with CRS validation, format auto-detection and SSRF protection. Modules: `core/sewer_topology.py` (parser + topology validator, 11 validation rules), `core/sewer_service.py` (graph building and FA routing logic), `scripts/download_sewer.py` (data download, returns the tuple `(points_gdf, lines_gdf | None)`).

---

## 3. Database Architecture

### 3.1 Schema Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                          flow_network                            │
│              -- REMOVED (ADR-028, migration 015)                │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     precipitation_data                          │
├─────────────────────────────────────────────────────────────────┤
│ id (PK)              SERIAL                                     │
│ geom                 GEOMETRY(Point, 2180)                      │
│ duration             VARCHAR(10)  ('5min'...'72h', 16 values)   │
│ probability          FLOAT        (0.01...99.9, 27 values)      │
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
│ segment_idx          INTEGER  -- 1-based per threshold (migration 014, ADR-026) │
│ is_real_stream       BOOLEAN  -- matched to BDOT10k (ADR-044)│
│ is_sewer_augmented   BOOLEAN  -- flag: modified by the sewer network (ADR-051) │
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

### 3.2 Example SQL Queries

#### Find the Nearest Stream (stream_network)
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

#### ~~Find Upstream Cells (Recursive CTE)~~ — DEPRECATED (ADR-022)
> **Note:** The runtime API uses `CatchmentGraph.traverse_upstream()` (in-memory BFS, ~5-50ms).
> The CTE below is kept only as documentation — `core/flow_graph.py` REMOVED (ADR-028).

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

#### Fetch Precipitation (Thiessen polygons)
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

#### Compute the CN for a Watershed
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

### 3.3 Database Optimization

#### Indexes
- **GIST indexes** for all geometry columns
- **B-tree indexes** for foreign keys and frequently filtered columns

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
- **EXPLAIN ANALYZE** for all slow queries
- **Partial indexes** for is_stream (TRUE only)
- **Materialized views** for frequently used aggregations (future)

---

## 4. Frontend Architecture

### 4.1 File Structure

```
frontend/
├── index.html               # SPA — Leaflet + Bootstrap + Chart.js (CDN)
├── admin.html               # Admin panel (ADR-034)
├── css/
│   ├── glass.css             # Glassmorphism CSS variables
│   ├── style.css             # Custom styles
│   └── admin.css             # Styles of the admin panel
└── js/
    ├── api.js                # API calls (fetch wrappers)
    ├── map.js                # Leaflet map, layers, drawing, MVT
    ├── draggable.js          # Pointer-event drag for floating panel
    ├── charts.js             # Chart.js: donut, histogram, profile, hydrograph
    ├── layers.js             # Layers panel: base layers, overlays, opacity
    ├── profile.js            # Terrain profile (draw line / auto)
    ├── hydrograph.js         # Hydrograph scenario form + chart
    ├── depressions.js        # Depressions (blue spots) overlay
    ├── sewer.js              # Storm-sewer layer (MVT overlay)
    ├── app.js                # Orchestrator: init, click routing, panel
    └── admin/
        ├── admin-api.js      # Admin API client (fetch + X-Admin-Key header)
        ├── admin-bootstrap.js # Bootstrap SSE stream, start/cancel
        ├── admin-bbox-picker.js # Map for choosing the area bbox
        ├── admin-sewer.js    # Card for managing the sewer network
        └── admin-app.js      # Admin panel orchestrator
```

---

### 4.2 UI Components

#### 4.2.1 Map (Leaflet.js)
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

#### 4.2.3 Hydrograph Chart
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

**Simple state in vanilla JS:**
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

### 5.1.1 Containerization — Multi-stage and override (ADR-035)

**Multi-stage Dockerfile** (`backend/Dockerfile`):
- **Stage 1 (builder):** installs the dependencies from `uv.lock` (`uv sync --locked --no-dev`; gcc and git for the dependencies from GitHub), then the GDAL binding that matches the system library (outside the lock)
- **Stage 2 (runtime):** copies the installed packages from the builder; the production image has no gcc/git

**`entrypoint.sh`:**
- Wait-for-db — `pg_isready` loop with retry (max 30 attempts, 1 s interval)
- Automatic Alembic migrations (`alembic upgrade head`) when the container starts
- Exec into the main process (uvicorn)

**Override pattern (dev/prod):**
- `docker-compose.yml` — base file (db + api + nginx), without `--reload`, without a code bind mount
- `docker-compose.override.yml` — loaded automatically in dev: bind mount `./backend:/app`, `--reload`, `LOG_LEVEL=DEBUG`
- `docker-compose.prod.yml` — production override: 2 uvicorn workers, `LOG_LEVEL=WARNING`, without `--reload`

**Healthcheck API:**
- Container `api`: healthcheck `python -c "urllib.request.urlopen('http://localhost:8000/health')"` (30 s interval)
- Container `nginx`: `depends_on: api: condition: service_healthy`

**Running:**
- Dev: `docker compose up` (loads override.yml automatically)
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

---

### 5.3 Environments

```
┌─────────────────────────────────────────────────────────┐
│                      DEVELOPMENT                        │
│  - .venv + docker compose up -d db (PostGIS only)      │
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
- Database (the NMT graph, precipitation data)
- API endpoints
- User data (minimal - only watershed locations)

**Threats:**
- SQL Injection
- XSS (Cross-Site Scripting)
- CSRF (Cross-Site Request Forgery)
- DDoS
- Unauthorized access

**Mitigations:**
- ✅ Parameterised SQL queries (SQLAlchemy ORM)
- ✅ Input validation (Pydantic)
- ✅ Rate limiting (Nginx — 3 zones: api_limit, tile_limit, general_limit)
- ✅ CORS with restrictive origins (env var `CORS_ORIGINS`), `allow_credentials=False`
- ✅ GZip middleware (FastAPI)
- ✅ Request ID tracing (`X-Request-ID` header, structlog context)
- ✅ Security headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options)
- ✅ Resource limits Docker (memory: 2G db, 8G api)
- ✅ Admin API key auth (X-Admin-Key header, file-based or env var, ADR-034)
- ✅ No user authentication needed (internal network only in MVP)

---

### 6.2 Security Layers

```
┌─────────────────────────────────────────────────────────┐
│                    NETWORK LAYER                        │
│  - Firewall (UFW): only ports 80, 443, 22             │
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
│  - Parameterised queries (SQLAlchemy)                 │
│  - Read-only user for preprocessing data              │
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

### 7.2 Metrics (Optional - Prometheus)

**Metrics to collect:**
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

**Additional components:**
- Redis for cache and session storage
- Message queue (Celery + RabbitMQ) for long tasks
- CDN for static assets

---

## 9. Disaster Recovery

### 9.1 Backup Strategy

**Database backups:**
```bash
# Cron job: every day at 2 AM
0 2 * * * docker exec hydro_db pg_dump -U hydro_user hydro_db | gzip > /backups/hydro_db_$(date +\%Y\%m\%d).sql.gz

# Retention: 7 days local, 30 days remote (rsync to a remote store)
```

**Application code:**
- Git repository (GitHub/GitLab)
- Tagged releases

**Preprocessing data:**
- Export `stream_network`, `stream_catchments`, `precipitation_data`, `land_cover` once after preprocessing
- Stored on an external disk

---

### 9.2 Recovery Procedures

**Scenario 1: Database corruption**
1. Stop the application: `docker compose down`
2. Restore from the backup: `gunzip -c backup.sql.gz | docker exec -i hydro_db psql -U hydro_user hydro_db`
3. Restart: `docker compose up -d`
4. Verify: Check `/health` endpoint

**Scenario 2: Server failure**
1. Provision a new server
2. Install Docker
3. Clone repo: `git clone ...`
4. Restore the database from the backup
5. Deploy: `docker compose up -d`
6. Update DNS (if applicable)

**RTO (Recovery Time Objective):** < 4 hours  
**RPO (Recovery Point Objective):** < 24 hours (daily backups)

---

## 10. Performance Optimization

### 10.0 Performance Approach

**Preprocessing (one-off):**
- Bulk INSERT via PostgreSQL COPY (ADR-006) instead of individual INSERTs
- Numba `@njit` for raster operations (ADR-017)
- `pyflwdir.basins()` instead of Python loops (ADR-016)

**Runtime API:**
- CatchmentGraph BFS in memory (milliseconds) instead of a recursive CTE on flow_network (seconds) — ADR-021, ADR-022
- Pre-computed stats in `stream_catchments` (zero raster operations at runtime)
- Cascaded merge threshold for large watersheds (>500 segments) — ADR-042

**Current benchmark results:** see `docs/PROGRESS.md`

---

### 10.1 Backend Optimizations

**Database:**
- Connection pooling (10 connections + 5 overflow)
- Partial indexes (is_stream = TRUE only)
- Materialized views (future)

**Python:**
- Use NumPy vectorization instead of Python loops
- Lazy loading of data (generator expressions)
- Async I/O for API calls (FastAPI async endpoints)

**Example - Vectorized calculations:**
```python
# GOOD - vectorized
import numpy as np

def effective_rainfall(intensities, cn):
    P_cum = np.cumsum(intensities)
    S = 25400 / cn - 254
    Pe_cum = np.where(P_cum > 0.2 * S, 
                      (P_cum - 0.2 * S)**2 / (P_cum + 0.8 * S), 
                      0)
    return np.diff(Pe_cum, prepend=0)

# BAD - Python loop (10-100x slower)
def effective_rainfall_slow(intensities, cn):
    P_cum = []
    total = 0
    for i in intensities:
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
- Simplify geometries (Douglas-Peucker) for display
- Use the canvas renderer for a large number of features

**Chart:**
- Downsampling for > 1000 points (Largest Triangle Three Buckets)
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

**Test strategy:**
- **Unit tests** — core modules with mocked dependencies (pytest + fixtures)
- **Integration tests** — API endpoints with a real PostGIS database (test service in CI)
- **E2E scripts** — `process_dem.py` (the full end-to-end pipeline)
- **CI:** pytest with coverage (the current number of tests is in the CI results)

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

## 12. Architecture Documentation

### 12.1 C4 Model

**Level 1: System Context**
```
┌──────────────┐         ┌────────────────────────┐
│              │         │                        │
│  User        ├────────►│  Hydrological          │
│  (Planner)   │  Uses   │  Analysis System       │
│              │         │                        │
└──────────────┘         └───────┬────────────────┘
                                 │
                                 │ Fetches data
                                 │
                    ┌────────────▼────────────┐
                    │                         │
                    │  GUGIK / IMGW           │
                    │  (Data sources)         │
                    │                         │
                    └─────────────────────────┘
```

**Level 2: Container Diagram** - see section 1.1

**Level 3: Component Diagram** - see section 2.1

**Level 4: Code** - see the [Nogat standard](https://github.com/Daldek/Nogat/tree/main/standards) (DEV-7 to DEV-9) and the inline documentation

---

## 13. Summary of Architectural Decisions

| Aspect | Decision | Rationale |
|--------|---------|--------------|
| **Backend Framework** | FastAPI | Fast, async, auto docs (OpenAPI) |
| **Database** | PostgreSQL + PostGIS | Standard for GIS, powerful spatial queries |
| **Frontend** | Vanilla JS + Leaflet | Simplicity, no build step for the MVP |
| **Deployment** | Docker Compose | Repeatability, isolation |
| **Preprocessing** | One-off (graph) | Runtime speed > preprocessing time |
| **Hydrological model** | SCS CN + UH / Nash IUH / Snyder UH | Proven, suitable for small watersheds |
| **Hyetograph** | Block / Euler II / Beta | 3 methods to choose from, depending on the use |

---

**Document version:** 2.6
**Date of the last update:** 2026-10-25
**Status:** Approved for implementation

**Change history:**
- 2.6 (2026-10-25): `core/watershed.py` (`FlowCell`, `build_boundary`, `build_boundary_polygonize`, `calculate_watershed_area_km2`) and the cell functions of `core/morphometry.py` are removed, nothing called them; `core/morphometry.py` keeps `calculate_shape_indices`; the sections 2.4.1 to 2.4.9 are renumbered (section 2.4.7 is the Hydrolog library, 2.4.8 in version 2.4)
- 2.5 (2026-10-25): Kartograf 0.8.0 (ADR-061): the downloads are versions of the Kartograf store `cache/kartograf/` (a hard-linked standard path, `versions/`, a sidecar per file), not the `cache/nmt/pl_<system>_<res>_evrf2007/` + `kampanie/` layout; `utils/kartograf_store.py`; `download_dem.py` writes into the store; the ADR table names ADR-060 and ADR-061 (details: `docs/integrations/KARTOGRAF.md` §3 and §7)
- 2.4 (2026-10-25): Hydrolog and IMGWTools are pinned by commit (ADR-060): section 2.4.8 names no version
- 2.3 (2026-10-25): translated to English (DEV-2.1); the content is unchanged
- 2.2 (2026-10-08): Kartograf 0.7.0 (stage K) — `download_dem.py`: `download_sheets()` returns `NmtDownloadReport` or raises `NmtDownloadError`; `MetadataCache` in `<cache_dir>/kartograf_meta.db` (local disk, never a network share); layout `cache/nmt/pl_<system>_<res>_evrf2007/` + `kampanie/`; mosaic from the file list of step 2 (details: §6 of `docs/integrations/KARTOGRAF.md` version 6.0)
- 2.1 (2026-09-28): `utils/sheet_finder.py` → `utils/sheet_lookup.py` — data acquisition only through Kartograf (ADR-057), a thin wrapper around `kartograf.find_sheets_for_bbox()` instead of our own reimplementation of the sheet-code arithmetic
- 2.0 (2026-03-28): Rebuilt sewer topology (ADR-052) — new module sewer_topology.py (parser + validator), explicit topology instead of heuristics, 4 node roles (inlet/outlet/junction/storage), 2 input formats (A/B), two-phase pipeline, download_sewer.py returns a tuple, migration 027 (isolated->storage), admin sewer/config endpoint
- 1.9 (2026-03-27): Storm-sewer network integration (ADR-051) — sewer_service.py, download_sewer.py, the tables sewer_nodes/sewer_network, 3 admin sewer endpoints, MVT sewer tiles, pipeline steps 3b/4a-4c, is_sewer_augmented in stream_network
- 1.8 (2026-03-25): Update after CP4+ — ADR 035-049 in the table, boundary.py and clean.py, conceptual descriptions of CatchmentGraph/watershed_service (without signatures), bdot_streams + new columns in the schema, section 2.5 (new concepts), updated counters (24+ migrations, 45+ unit tests, 8+ integration), hydrological models (Nash IUH, Snyder UH) and hyetographs (Block/Euler II/Beta)
- 1.7 (2026-03-01): Update against the actual state of the code — added: admin panel (ADR-034, 8 endpoints, admin.html, 3 admin/ JS modules), landcover MVT tiles, api/dependencies/, scripts/ section (16 scripts), 17 migrations, ADR-026..034; updated: Docker (API memory 4G, ADMIN_API_KEY, volumes), Nginx (admin, SSE, health, static cache), config.py YAML description, security (admin auth)
- 1.6 (2026-02-16): Full update — new tables (stream_catchments, depressions), ADR-008..025, confluence segmentation, Docker/Nginx matching the actual state, structlog, security headers, removal of numeric benchmarks
- 1.5 (2026-02-14): Removal of FlowGraph from the runtime (ADR-022) — diagram, modules and data flow updated; +watershed_service.py, flow_graph.py DEPRECATED
- 1.4 (2026-02-13): Added catchment_graph.py and constants.py to core, updated the signatures of morphometry.py, alphabetical order of the core modules
- 1.3 (2026-02-07): Update of the module structure (morphometry, cn_tables, cn_calculator, raster_utils, sheet_finder), removal of core/hydrograph.py (moved to Hydrolog)
- 1.2 (2026-01-20): Added the results of the optimization tests (COPY 21x, reverse trace 257x)
- 1.1 (2026-01-20): Added section 10.0 with the benchmark results of the end-to-end test
- 1.0 (2026-01-14): Initial version

---

*This document defines the technical architecture of the system. Every significant change requires an update of this document and a review by the Tech Lead.*
