# ARCHITECTURE.md - System Architecture
## Hydrological Analysis System

**Version:** 2.7
**Date:** 2026-11-02
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
│  - Pages and /api/* passed to FastAPI (X-Accel-Redirect)        │
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
│  - Business Logic        │    │  - Nogat tokens (UI)         │
│  - Error Handling        │    │  - Vanilla JavaScript        │
│  - Request Limit, Stats  │    │                              │
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
| ADR-041 | Monotonic stream smoothing | Keep the elevation monotonic after the stream lines are smoothed; the direction of the lines amended by ADR-072 and ADR-077 (§2.5) |
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
| [ADR-065](decisions/0065-nogat-visual-identity-and-archiwista-shell.md) | Nogat visual identity and the Archiwista shell | A consistent GUI across the ecosystem (ECO-055) instead of glassmorphism panels; Bootstrap only in `/admin` |
| [ADR-082](decisions/0082-nogat-kit-menu-and-handoff.md) | Nogat's app menu and hand-off | The ecosystem's GUIs from `HYDROGRAF_GUI` (`GET /api/gui`) in the kit's menu „Aplikacje”; the hand-off through the kit's module, which the IIFE scripts reach through `js/nogat.js` |
| [ADR-083](decisions/0083-provider-attribution-in-every-product.md) | The providers' lines in every product | PMAXTP's lines of Nogat DEV §20 from one module (`core/attribution.py`) in the responses, the hand-off and every export; the front end shows what a response or the results manifest carries |
| [ADR-084](decisions/0084-public-service-terms-limit-and-statistics.md) | Hydrograf as a public service | Nogat's regulamin from `[nogat.operator]` of NOGAT_CONFIG; the request limit per client address and the daily totals in the API (one process), the pages through the API; logs without addresses in the journal, 14 days; the form with the text and the view's context |

---

## 2. Backend Architecture

### 2.1 FastAPI Application Structure

```
backend/
├── api/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app instance, lifespan, middleware
│   ├── traffic.py                 # Middleware of the public service (ADR-084): the client address (CF-Connecting-IP through private hops), the request limit, the 429 page or problem, the daily totals
│   ├── dependencies/
│   │   ├── __init__.py
│   │   └── admin_auth.py          # Admin API key verification (X-Admin-Key header)
│   └── endpoints/
│       ├── __init__.py
│       ├── admin.py               # 13 /api/admin/* endpoints (dashboard, resources, cleanup, bootstrap, sewer)
│       ├── depressions.py         # GET /depressions
│       ├── feedback.py            # POST /feedback (the text and the view's context), the admin list GET/PATCH/DELETE /admin/feedback
│       ├── gui.py                 # GET /gui: the ecosystem's GUIs of the deployment (HYDROGRAF_GUI, else [nogat] gui of NOGAT_CONFIG) for the app menu (ADR-082, ADR-084)
│       ├── health.py              # GET /health
│       ├── hydrograph.py          # POST /generate-hydrograph
│       ├── profile.py             # POST /terrain-profile
│       ├── identify.py            # GET /identify-point (core/point_info.py)
│       ├── network.py             # POST /delineate-network (ADR-080): the network at control points and its hand-off, one network at a time per worker; POST /delineate-network/preview (ADR-081): the same network composed on the catchment graph
│       ├── site.py                # The pages answered with X-Accel-Redirect, /regulamin.html, GET /terms, POST /downloads (ADR-084)
│       ├── tiles.py               # GET /tiles/streams|catchments|landcover|sewer/{z}/{x}/{y}.pbf, GET /layers
│       └── watershed.py           # POST /delineate-watershed (precomputed + precise modes), POST /delineate-watershed/preview
│
├── core/
│   ├── __init__.py
│   ├── analysis_results.py        # Manifest of the analysis results (frontend/data/results/index.json): water level along the terrain profile, the providers' lines of a result (provider_lines, ADR-083)
│   ├── attribution.py             # The lines the providers' terms require (Nogat DEV §20, ADR-083): PMAXTP's PS, PP, M and the terms line RK; ProviderLines, merge, is_terms
│   ├── catchment_graph.py         # In-memory sub-catchment graph (~87-285k nodes, scipy CSR + BFS), reloaded when the network in the database changes
│   ├── cell_parameters.py         # Parameters measured from the cells of a watershed on the saved rasters (area, elevations, flow paths, overland segment, main channel): the export of catchment parameters, process_dem's overland segments
│   ├── cn_calculator.py           # Kartograf HSG-based CN calculation
│   ├── cn_tables.py               # CN lookup tables (HSG × land cover)
│   ├── config.py                  # YAML config loading (load_config(), get_settings(), resolve_dem_path() — DEM auto-discovery ADR-049), gui_table() of HYDROGRAF_GUI or of nogat.toml (ADR-082, ADR-084), the request limit and the data_dir of the statistics
│   ├── constants.py               # Project-wide constants (CRS, unit conversions, limits)
│   ├── database.py                # Database connection pool
│   ├── db_bulk.py                 # Bulk INSERT via COPY, timeout mgmt
│   ├── handoff.py                 # The hand-off nogat-handoff/1 to Hydrolog's GUI: build_handoff (a watershed, ADR-068), build_network_handoff (a network, ADR-080)
│   ├── hydrology.py               # Hydrology: fill, fdir, acc, burning, building raising (ADR-033)
│   ├── land_cover.py              # Land cover analysis, determine_cn()
│   ├── morphometry.py             # Shape indices (calculate_shape_indices)
│   ├── morphometry_raster.py      # Slope, aspect, TWI, Strahler (raster)
│   ├── network_delineation.py     # Network at control points on the rasters (ADR-080): snapping, the window of the closing section's catchment, the element raster and its splits, the area check, the measures of the elements, their coverage, the reaches
│   ├── network_preview.py         # The network composed on the catchment graph (ADR-081): the full run's snapping and tree, areas exact to the cell, reach lengths, outlines from a cover of the sub-catchment polygons
│   ├── network_tree.py            # Network at control points on the catchment graph (ADR-080): the points drawn to the nodes of the network, parents, trunks, junctions, elements of the units, ids J/P/Z/R from the closing section upward in the order of the hand-off
│   ├── precipitation.py           # Precipitation queries
│   ├── raster_io.py               # Raster I/O (ASC, VRT, GeoTIFF); cells_window + read_window: a window around a query (the API)
│   ├── raster_service.py          # Precise-mode delineation (pyflwdir) in a window of the flow directions and the DEM
│   ├── request_limit.py           # Fixed windows of requests per client address, in memory; ended windows forgotten (ADR-084)
│   ├── soil_hsg.py                # HSG soil group data (SoilGrids)
│   ├── stream_extraction.py       # Stream vectorization, subcatchments
│   ├── sewer_service.py            # Storm-sewer integration (SewerGraph, burn inlets, FA routing, ADR-051/052)
│   ├── sewer_topology.py           # Sewer topology parser and validator (ParsedTopology, parse_sewer_topology, validate_against_fdir, ADR-052)
│   ├── terms.py                   # The regulamin: the kit's nogat-terms.html filled once per process from [nogat.operator] of NOGAT_CONFIG and the gui entry hydrograf (ADR-084)
│   ├── usage.py                   # The daily totals (visitors by a salted HMAC, page views, analyses, downloads) and <data_dir>/hydrograf/stats.jsonl (DEV-15.11, ADR-084)
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
│   ├── check_stream_directions.py # Diagnostic of the flow direction of the burned BDOT10k lines by the rules of ADR-077 (GeoPackage); does not change the pipeline
│   ├── diagnose_catchment_exits.py # Where the NMT D8 flow leaves given polygons: exits with destination, area, share (GeoPackage)
│   ├── export_catchment_parameters.py # The panel's basic parameters, shape indices and land cover for given polygons (GeoPackage)
│   ├── download_sewer.py          # Downloads the sewer network (file/WFS/DB/URL, CRS validation, SSRF protection). Returns tuple (points_gdf, lines_gdf | None)
│   ├── write_instance_info.py     # frontend/data/instance.json (hydrograf-instance/1): the area of the instance for the welcome screen and the guide
│   └── clean.py                  # Cleans generated data (rasters, tiles, DB, cache)
│
├── migrations/
│   └── versions/                  # 001–007: 001 the squashed initial schema, 006 drops land_cover.cn_value (ADR-075), 007 adds feedback.context (ADR-084)
│
├── utils/
│   ├── __init__.py
│   ├── dem_color.py               # DEM color palette, hillshade blending
│   ├── geometry.py                # Geometric operations, CRS transforms
│   ├── kartograf_store.py         # Where Kartograf writes (store, metadata cache), describe_error(), download_bdot10k() (ADR-061), the HSG rules of soil.hsg_depth_rule (ADR-079)
│   ├── raster_utils.py            # Raster tools (resample, polygonize)
│   ├── nmt_coverage.py            # NMT sheets that leave the area or a hole of their mosaic uncovered (ADR-076)
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
  "version": "0.5.0.dev0"
}
```
`version` is Hydrograf's version, `get_version()` of `core/version.py` (declared in `backend/pyproject.toml` only, REL-1.1); the admin dashboard (`GET /api/admin/dashboard`) reports the same.

#### 2.2.1a The Ecosystem's GUIs (ADR-082)
```
GET /api/gui
Response: 200 OK
{
  "hydrolog": "http://127.0.0.1:8070/",
  "archiwista": "http://127.0.0.1:8090/"
}
```
The table `gui` of `[nogat]` (Nogat DEV-15.4, DEV-18.1) that the deployment sets in `HYDROGRAF_GUI` (`docker-compose.yml`, `.env.example`): a registry name in lower case to an http or https URL or a path from `/` on this host; `{}` without it. The settings refuse any other value when they load (`gui_table()` of `core/config.py`), so the API does not start with it. `js/nogat.js` sets the table as the `apps` of the app menu of every page (§4.2.0).

#### 2.2.1b The Public Service (ADR-084)
```
GET /api/terms
Response: 200 OK
{"url": "/regulamin.html", "operator_email": "kontakt@debever.pl",   // both null without [nogat.operator]
 "attribution": ["Źródłem pochodzenia danych jest …", …],     // PMAXTP's lines (core/attribution.py), always
 "terms_notice": ["Regulamin danych PMAXTP: https://klimat.imgw.pl/opady-maksymalne"]}

GET /regulamin.html            — the regulamin of the deployment (text/html); 404 without an operator
POST /api/downloads            — 204: count one file the interface saved (the daily total downloads)

POST /api/feedback
{"message": "…", "context": {"view": "select", "station": null, "parameters": {...}}}
Response: 200 {"id": 41, "status": "ok"}; any other member, at the top or in context: 400 validation_error

Over a limit: 429, Retry-After: <s>; a page: a Polish HTML page; a route: the problem
rate_limited, details {reason: request_limit|tile_limit|feedback_limit, retry_after_s,
limit, window_s}
```
`core/terms.py` fills the kit's `nogat/nogat-terms.html` (mounted into the API at `/frontend/nogat`) once per process from `[nogat.operator]` of the `nogat.toml` that NOGAT_CONFIG names (`/config/nogat.toml` in Docker) and the address of the entry `hydrograf` of the table `gui`, with the blocks `pmaxtp`, `gugik`, `copernicus`, `isric`, `wody-polskie`, `osm` and `esri`. `context` of a report is the map mode (`browse`, `select`, `network`, `profile`, `identify`), `station` (always null) and `parameters` (the map, the clicked point, the watershed, the hydrograph settings, the profile line); the server adds `app_version` and stores no User-Agent.

The middleware `api/traffic.py` runs inside the request ID's. The client address is `CF-Connecting-IP`, believed only when nginx's peer (`X-Real-IP`) and the API's peer are private hops (loopback, RFC 1918, ULA, link-local); else the nearest public hop. Pages (`GET` of `/index.html`, `/admin.html`, `/instrukcja/index.html`, `/regulamin.html`) and routes count against `HYDROGRAF_REQUEST_LIMIT` in `HYDROGRAF_REQUEST_WINDOW` (300 in 60 s); `/api/tiles/` against ten times that instead; `POST /api/feedback` besides against 5 in 300 s; `/health` not at all. An address lives in memory for its window (ended windows are forgotten within 5 s) and, through the UTC day, as an HMAC-SHA-256 of the address and the User-Agent under a salt drawn daily. `core/usage.py` writes one line per UTC day to `<data_dir>/hydrograf/stats.jsonl` every 10 minutes, at 00:00 UTC and at shutdown: `visitors`, `page_views`, `stations_opened` (0), `analyses_run` (successful `POST` of delineate-watershed, delineate-network, generate-hydrograph and terrain-profile, not the previews) and `downloads`. Both need one API process.

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

Errors (application/problem+json):
- 404 not_found: no sub-catchment at this point
- 400 validation_error: coordinates, a non-positive threshold_m2; in the precise mode a point off the rasters
- 422 calculation_error: the boundary could not be built
- 422 unsupported (reason window_too_large): precise mode, the window of the rasters holds more than 40 million cells
- 503 store_unavailable: the catchment graph is not loaded; in the precise mode the DEM is not on the grid of the flow directions (reason raster_grids_differ)
- 500 internal_error: the delineation failed
```

The precise mode delineates the watershed of the point with pyflwdir on the flow directions of the preprocessing (`core/raster_service.py`), but reads them and the DEM only in a window: the bounding box of the precomputed watershed of the point at `DEFAULT_THRESHOLD_M2` (`ST_Extent` of its sub-catchments, `catchments_bounds`) plus 50 m. While the delineated watershed touches a side of the window that is not the edge of the rasters, that side moves out by half the window (at least 64 cells) and the delineation runs again, so the result is the one of the whole rasters. A window of more than 40 million cells (1000 km² of 5 m cells, about 1.5 GB at the peak of a delineation) is refused before it is read, and the DEM must have the transform and the shape of `dem_mosaic_03_flowdir.tif`.

#### 2.2.2a Delineation Preview
```
POST /api/delineate-watershed/preview
Content-Type: application/json

Request (as in the precomputed mode; threshold_m2 is required, the precise mode has no preview):
{
  "latitude": 50.929,
  "longitude": 16.119,
  "threshold_m2": 10000
}

Response: 200 OK
{
  "threshold_m2": 100000,      // threshold of the sub-catchments after the minimum threshold and the cascade
  "segment_count": 289,        // how many sub-catchments delineate-watershed merges
  "catchments": {              // GeoJSON FeatureCollection (WGS84), ascending by depth
    "type": "FeatureCollection",
    "features": [
      { "type": "Feature", "geometry": { "type": "MultiPolygon", ... }, "properties": { "depth": 0 } },
      ...
    ]
  }
}

Errors (application/problem+json):
- 404 not_found: no sub-catchment at this point
- 400 validation_error: coordinates, a missing or non-positive threshold_m2
- 503 store_unavailable: the catchment graph is not loaded
```

A preview for the animation of the GUI, before `POST /api/delineate-watershed` merges the boundary. The selection of the sub-catchments is shared with the precomputed mode (`_select_precomputed`: the minimum threshold `DEFAULT_THRESHOLD_M2`, the sub-catchment at the point, BFS, the cascade above 300 segments), so the preview covers the same area as the result. `depth` is the number of links upstream from the outlet sub-catchment (`CatchmentGraph.upstream_segments_by_depth`); each depth is one MultiPolygon collected by `ST_Collect` (no union), the polygons are simplified by `ST_Simplify` with a tolerance of √A / 500 m (about one pixel once the map fits the catchment, at least 1 m), and the coordinates have 5 decimal places. At most 5000 sub-catchments, the nearest to the outlet. Time (review instance): 52 km², 25 ms against 4.6 s of the full delineation; 778 km² (4418 sub-catchments, 147 depths), 0.15–0.24 s against 88 s.

#### 2.2.2b Delineate Network (ADR-080)
```
POST /api/delineate-network
Content-Type: application/json

Request:
{
  "outlet": {"id": "P1", "latitude": 51.128, "longitude": 15.909, "name": "Kaczawa"},  // the closing section; id required (the client's handle, no default)
  "points": [                  // 0–30 control points above it; none: the closing section alone is a network
    {"id": "P2", "latitude": 51.01538, "longitude": 15.890496, "name": "Kamiennik"},
    {"id": "P3", "latitude": 51.0712, "longitude": 15.8021}
  ],
  "threshold_m2": 100000       // the stream network the points snap to (the streams of the map), ≥ 10000
}

Response: 200 OK
{
  "threshold_m2": 100000,
  "unit_threshold_m2": 10000,  // the sub-catchments the elements are made of
  "area_km2": 238.712375,      // the closing section's catchment, exact to the cell
  "area_check": {"watershed_km2": 238.712375, "elements_km2": 238.712375},
  "boundary_geojson": {"type": "Feature", ...},   // the closing section's boundary (WGS84)
  "points": [                  // the closing section, then the points in the order of the request
    {"id": "P1", "name": "Kaczawa", "latitude": 51.12801, "longitude": 15.90897,
     "snap_distance_m": 7.1, "at_node": false, "node": "P1"},   // id: the handle; node: J<n> or P<n>
    {"id": "P2", "name": "Kamiennik", "latitude": 51.0155, "longitude": 15.88991,
     "snap_distance_m": 4.0, "at_node": true, "node": "J1"}, ...
  ],
  "subcatchments": [           // Z1, Z2, … in the order of the hand-off
    {"id": "Z1", "kind": "headwater", "to": "J1", "point": "P2", "reach": null,   // point: the handle of the person's point at `to`
     "watershed": {...}}       // a WatershedResponse, as for a delineated watershed
  ],
  "reaches": [
    {"id": "R1", "from": "J1", "to": "P1", "length_km": 5.0712, "slope_m_per_m": 0.00981,
     "slope_method": "nmt", "upstream_elevation_m": 281.4, "downstream_elevation_m": 231.66,
     "vector_length_km": 4.87, "geojson": {"type": "Feature", ...}}
  ],
  "junctions": [               // the nodes: J<n> at a confluence, P<n> elsewhere
    {"id": "J1", "kind": "point", "point": "P2", "name": "Kamiennik", "latitude": 51.0157,
     "longitude": 15.8901, "inflows": ["Z1", "Z2"]}
  ],
  "notices": [                // one per reach shorter than 200 m or of the minimum slope (D10a)
    {"code": "reach_short_or_flat", "ids": ["R2"], "reach": {"length_m": 50.4,
     "slope_minimum": true, "upper_point": "P3", "lower": "J1",   // upper_point: the handle at the upper node
     "move_to": {"latitude": 50.9197045, "longitude": 15.9542906},  // the cell above J1 on P3's branch
     "lag_min": 2}}           // the lag the hand-off writes for a flat reach; null otherwise
  ],
  "handoff": {"schema": "nogat-handoff/1", ...}   // the network for Hydrolog's „Sieć i trasowanie”
}

Errors (application/problem+json; details.point_id or details.point_ids name the point):
- 400 validation_error: coordinates, more than 30 points, an outlet without an id, an id not ^[A-Za-z0-9][A-Za-z0-9_-]{0,15}$, two ids equal without regard to case, a name with control characters, threshold_m2 below 10000 (reason invalid_request, errors[].pointer); a point that does not drain to the closing section (network_point_outside); two points on one node or stream cell, the closing section included (network_points_coincide: „Punkty {point_ids} trafiają w ten sam węzeł sieci: …”)
- 404 not_found (network_point_off_stream): no stream cell of threshold_m2 within 100 m of a point, or a point off the rasters
- 422 unsupported (network_window_too_large): the window of the closing section's catchment holds more than 60 million cells (details cells, max_cells)
- 503 store_unavailable: the catchment graph is not loaded (catchment_graph_unavailable); a raster missing (network_rasters_missing) or not on the grid of the others (raster_grids_differ); another network of this worker still running after 15 s (network_delineation_busy, details.wait_s)
- 500 internal_error: the elements do not add up to the closing section's catchment (network_area_mismatch); any other failure (network_delineation_failed)
```

The network of a closing section and the control points above it (plans `docs/plans/2026-11-10-network-delineation.md` and `docs/plans/2026-11-11-network-nodes.md`; `api/endpoints/network.py`, `core/network_tree.py`, `core/network_delineation.py`, §2.4.10). Each point, the closing section included, snaps to the nearest stream cell of `threshold_m2` within 100 m, then moves to the nearest node of the network (a stream cell of `threshold_m2` into which two or more such streams drain) within 50 m of flow distance below or above it (`at_node`). Every point is a node: `points[].node` is `J<n>` at a confluence and `P<n>` elsewhere. The ids of the request are only the client's handles (`details.point_id` and `details.point_ids` name them); the ids of the response and the hand-off are the network's, numbered by a walk from the closing section (`J1` or `P1`) upward, each kind on its own, and the same points in any order give the same ids. `subcatchments[].kind` is `headwater` (a river entering a node with no reach, also one without a point; `point` the handle of the person's point at its node, else null) or `intermediate` (the przyrzecze of the reach `reach`); `reaches[].from` is the JSON name of the field `from_node`, and `slope_method` is `minimum` where the NMT does not fall between the ends of a reach (0.0001); `junctions[]` are the nodes, `kind` `confluence` (one the network made, `point` and `name` null), `point` (a person's point, a `J` or a `P`) or `outlet` (the closing section, which flows into `O`), with the `name` of its point. `notices` lists `over_scs_cn_limit` (the subcatchments whose `hydrograph_available` is false, above 250 km²) (each only when it has ids) and one `reach_short_or_flat` for every reach shorter than 200 m (`SHORT_REACH_M`) or of the minimum slope (ADR-080 D10a): its length, whether it is flat, the point at its upper end, the junction below, `move_to` (from a point into a confluence: the outlet cell above the confluence on the reach's branch, from where the point is drawn to the node; the map mode's „Przesuń P… do zbiegu”) and `lag_min`, the lag of a flat reach; the front end words them. A reach of the minimum slope is a `lag` reach of `lag_min` = max(1, round(length / 0.5 m/s / 60)) in the hand-off, with `method_reason: "flat"` and its length and slope in `node_provenance`: Hydrolog's Muskingum-Cunge cannot route a flat reach. `handoff` is one `nogat-handoff/1` with `node_provenance` around one `hydrolog-network/1` (`build_network_handoff`, `docs/integrations/HYDROLOG.md`).

A network reads the saved rasters of the closing section's whole catchment and holds at most 21 bytes a cell of them (the slope only for the statistics of the elements, the labels only until the element raster: about 1.3 GB at the cap of 60 M cells; production's whole grid of 58.6 M cells peaks at 1.77 GB with the interpreter), so each worker process delineates one network at a time: the route holds a `threading.Lock` of its process, and a request waits for it at most `NETWORK_LOCK_WAIT_S` (15 s), then gets 503 `network_delineation_busy`. With production's two workers at most two networks run at once. The router registers the problems 404 and 503 of the watershed routes and the route its 422, besides 400 and 500; any exception that is not a `HydrografError` is logged and becomes 500 `network_delineation_failed`.

#### 2.2.2c Network Preview (ADR-081)
```
POST /api/delineate-network/preview
Content-Type: application/json

Request: the request of POST /api/delineate-network (§2.2.2b)

Response: 200 OK
{
  "threshold_m2": 100000,
  "unit_threshold_m2": 10000,
  "area_km2": 240.328025,      // the closing section's catchment, exact to the cell: the full run's
  "points": [                  // as the full run's, and whether a raster splits the point's unit
    {"id": "P1", "name": "Kaczawa", "latitude": 51.12801, "longitude": 15.90897,
     "snap_distance_m": 11.8, "at_node": false, "node": "P1", "inside_unit": true}, ...
  ],
  "subcatchments": [           // the full run's ids, kinds and nodes
    {"id": "Z1", "kind": "headwater", "to": "J1", "point": null, "reach": null,
     "area_km2": 71.87555,     // exact to the cell: the full run's
     "outline_approximate": false,   // it holds a part of a unit that a point splits
     "boundary_geojson": {"type": "Feature", ...}}   // null without a polygon of its own
  ],
  "reaches": [                 // the full run's length; the stream lines between its ends
    {"id": "R1", "from": "J1", "to": "P1", "length_km": 1.2969, "geojson": {"type": "Feature", ...}}
  ],
  "junctions": [...],          // as the full run's
  "notices": [{"code": "over_scs_cn_limit", "ids": ["Z1"], "reach": null}]   // and the full run's reach_short_or_flat
}

Errors: those of POST /api/delineate-network but 422 and network_delineation_busy (no window,
no lock); any other failure is 500 internal_error (network_preview_failed)
```

The option „Sieć zlewni” of „Wybierz zlewnię” asks for it after every change of its points (ADR-081, plan `docs/plans/2026-11-11-network-preview.md`; `core/network_preview.py`, §2.4.10). The points snap as for the full run (`snap_point`, the windows around the clicks) and `build_network_tree` builds the same tree, so the ids, the places of the points and junctions and the errors of the composition are the full run's. The areas are the cells of the units, a unit split by a point counted from the accumulation at the point; the reach lengths are the differences of the flow distances; the outlines unite on a grid of 10 m the largest sub-catchment of any threshold that one element holds whole, the units of 1 ha only around the outlets of the elements (production's whole area: 91 polygons); a unit split by a point goes whole to the element with most of its cells (`inside_unit`, `outline_approximate`). No window of the closing section's catchment is read and no lock is taken: on production 0.08 s for the Kamiennik and 0.37 s for the whole area of 792 km².

#### 2.2.3 Generate Hydrograph
```
POST /api/generate-hydrograph
Content-Type: application/json

Request:
{
  "latitude": 52.123456,
  "longitude": 21.123456,
  "duration": "1h",            // required without custom_precipitation
  "probability": 10,           // required without custom_precipitation
  "amc": "II",                 // I | II | III, II by default
  "custom_precipitation": {    // optional: your own series instead of PMAXTP and the hietogram
    "timestep_min": 10,        // > 0 and ≤ 1440
    "depths_mm": [0.5, 2.0, 6.5, 3.0, 1.0],  // ≥ 0, 1–2000 values, sum > 0
    "derived_from": null       // "pmaxtp": a copy of a PMAXTP hyetogram (ADR-083)
  },
  "morphometry": { ... }       // optional: the fast path (advanced mode), fractional cn
}

Response: 200 OK (full structure in DATA_MODEL.md, section 6.4)
  precipitation.source: "pmaxtp" | "custom"; probability_percent = null for your own series
  water_balance.cn_used: float (the CN after the AMC conversion)
  metadata.amc; metadata.hietogram_type = null for your own series
  attribution: [PS, PP, M], terms_notice: [RK] for PMAXTP and a series derived from it;
  [] and [] for your own data (ADR-083); the hand-off has the same fields, without them
  when they are empty
Response: 400 validation_error (application/problem+json), e.g. for the rainfall series
Response: 422 unsupported (catchment_too_large) above area_limit_km2 (250 km²), for a
          delineated catchment and for one given in morphometry alike
```

`attribution` and `terms_notice` are the lines of Nogat DEV-20.2 and DEV-20.7 for PMAXTP data, byte for byte from `core/attribution.py`: the source with the address of the PMAXTP page (PS), the note that the data were processed (PP), the monograph of the project (M) and the link to the PMAXTP terms (RK, „Regulamin danych PMAXTP: https://klimat.imgw.pl/opady-maksymalne”); no summary of the terms (Nogat ECO-065). A product made with the result shows them visibly and carries them on (ADR-083).

`GET /api/scenarios` also returns `amc` (`["I", "II", "III"]`), `custom_precipitation_max_steps` (2000) and `area_limit_km2` (250). The messages of `errors[]` of a 400 follow `Accept-Language` like `detail`: pydantic's English without the header, a Polish text of the error type with its limits for `pl` (e.g. `/body/hietogram_alpha`: „Wartość nie może być większa niż 20.”); pointers and types do not change.

#### 2.2.3a Layer Availability
```
GET /api/layers

Response: 200 OK
{"sewer": true}   // whether sewer_network or sewer_nodes holds data
```
The „Warstwy” panel shows the layer „Kanalizacja deszczowa” only with `sewer: true`.

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
  "nash_estimation_methods": [...]
}
```

#### 2.2.5 Terrain Profile
```
POST /api/terrain-profile
Content-Type: application/json

Request:
{
  "geometry": { "type": "LineString", "coordinates": [[lon, lat], ...] },
  "n_samples": 100,
  "result_ids": ["sfincs-kamiennik-24h-p1"]
}

Response: 200 OK
{
  "distances_m": [0.0, 10.5, ...],
  "elevations_m": [150.0, 151.2, ..., 0.0],
  "dem_gaps": [false, false, ..., true],
  "total_length_m": 1050.0,
  "water_levels": [{"result_id": "sfincs-kamiennik-24h-p1", "levels_m": [null, 152.4, ..., null]}],
  "attribution": ["Źródłem pochodzenia danych jest …", …],
  "terms_notice": ["Regulamin danych PMAXTP: https://klimat.imgw.pl/opady-maksymalne"]
}
Response: 404 no_data (no_elevation_data) when no sample has DEM data
```

`dem_gaps` marks the samples where the DEM has no data (off its extent, e.g. past the boundary of the clipped data); `elevations_m` holds 0.0 there, so a client must read the mask, not the value (the frontend draws a gap, B5).

`result_ids` (optional, up to 20 ids) are analysis results of the manifest `/data/results/index.json` (§4.2.0). For each result with a `water_level` raster that at least one point of the profile hits, `water_levels` gives the maximum water level [m a.s.l.] at the same points as `elevations_m`; `null` where it is dry, outside the raster or without DEM data. Unknown ids, results without `water_level` and rasters off the line are skipped; without `result_ids` the list is empty. `core/analysis_results.py` reads the manifest and the rasters from `FRONTEND_DATA_DIR` (§4.2.0). `attribution` and `terms_notice` are the lines the manifest gives the results of `water_levels`, each once (ADR-083); empty without them.

#### 2.2.5a Identify Point
```
GET /api/identify-point?latitude=51.0158&longitude=15.9042&threshold_m2=100000&result_ids=sfincs-kamiennik-24h-p1
```
Everything Hydrograf knows at one point, for the mode „Identyfikuj”: `coordinates` (WGS84; PL-1992 `easting_m`/`northing_m`; `pl2000` with `zone`, `epsg`, `easting_m` and `northing_m` in the PL-2000 zone of the longitude, EPSG:2176–2179; only the Polish systems), `elevation_m` and `slope_percent` (DEM rasters), `water` (per requested result whose `water_level` raster holds the point: `water_level_m`, `depth_m` = level − DEM, `null` where dry or below the terrain), `stream` (the nearest `bdot_streams` line up to 5 km away, a nearest-neighbour search over its GiST index, with `distance_m`), `water_body` (BDOT10k `OT_PTWP_A` polygon from `FRONTEND_DATA_DIR/bdot_lakes.geojson`, not in the database), `land_cover` (category, BDOT10k class, `cn` for AMC II as in the catchment CN, `cn_amc_i` and `cn_amc_iii` converted by Hydrolog's `SCSCN.adjust_cn_for_amc` as for the hydrograph, imperviousness), `soil_hsg`, `depression` and `subcatchment` (`stream_catchments` + `stream_network` at `threshold_m2`, floored to 10000; `channel_length_km`, the main channel at the segment's downstream end traced as for a watershed delineated there, and `distance_to_outlet_km`, the D8 flow distance from there to the outlet of the network, where the water leaves the data area, both from the in-memory `CatchmentGraph` and `null` without it). A member is `null` where its source has nothing; a point off the DEM is outside the data: 404 `no_data`; no DEM: 503 `store_unavailable`.

The query parameters: `latitude` and `longitude` (required, WGS84), `threshold_m2` (optional, > 0) and `result_ids` (repeated, `&result_ids=a&result_ids=b`, up to 20, each 1–100 characters). An invalid parameter is a `validation_error` problem (400) whose `errors[].pointer` names it, e.g. `/query/latitude` or `/query/result_ids/0`. The answer has no side effects and can be cached; the front end keeps it for 5 minutes (`js/api.js`).

`attribution` and `terms_notice` are the lines the manifest gives the results of `water`, each once (ADR-083), as in the terrain profile; empty without them.

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
DELETE /api/admin/sewer            — delete the sewer data
PUT    /api/admin/sewer/config     — enabled, source file and layers, field_mapping and role_mapping (ADR-052)

GET    /api/admin/feedback         — reports, newest first (limit, offset), with unread_count; each {id, created_at, message, context, is_read, legacy}: legacy the contact, page_url, user_agent and diagnostics of a report of the old form, null for new reports
PATCH  /api/admin/feedback/{id}    — {"is_read": true|false}: mark a report read or unread
DELETE /api/admin/feedback/{id}    — delete a report
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
   - Cascaded merge threshold: above 300 segments (`_MAX_MERGE`) the merge takes the first coarser threshold of the graph whose BFS selects at most 300 (10000 → 100000 → 1000000 → 10000000 m²), else the coarsest
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
3. Fetch the precipitation (SQL query of PMAXTP) or take your own series (custom_precipitation)
4. Generate the hyetograph (Beta / Block / Euler II; skipped for your own series)
5. Compute the effective precipitation (SCS CN converted by the AMC)
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

Singleton in-memory graph of sub-catchments based on numpy arrays and a scipy sparse CSR matrix (~87-285k nodes depending on the area, ~0.5 MB of RAM). Loaded at the start of the API and again when the network in the database changes: every request takes it from `loaded_catchment_graph()`, which reads `network_version()` (the file nodes and the write counters of `stream_catchments` and `stream_network` in PostgreSQL's cumulative statistics, under a millisecond) and, when the version differs from that of the current graph (a published run, a run of the whole raster, the BDOT10k matching after it, a clean-up), loads a new graph and makes it the current one. Each API worker reloads at its first request after the change, seconds after the writer's commit; a request keeps the graph it started with, and the requests that find the change wait for one load (about 20 s for the 201,195 nodes of Hydroni).

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
- **Merge catchment boundaries** — 3 strategies: direct (small watersheds), batched ST_UnaryUnion, fallback to a coarser snap grid. Cascade threshold escalation for large watersheds (`cascade_escalate`): above 300 segments, the first coarser threshold of the graph with at most 300, else the coarsest
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
- The design depth of a watershed: the mean of the PMAXTP grid points weighted by their
  Thiessen polygons inside it (ADR-069); IDW at a point without a boundary

**Main functions:**
```python
def thiessen_cells(boundary_2180: BaseGeometry, db: Session) -> list[ThiessenCell]:
    """Grid points whose Thiessen polygons overlap the watershed, with the overlap."""

def areal_depth(cells, duration, probability, db) -> DesignDepth | None:
    """Watershed mean of a scenario (Hydrolog's thiessen_polygons)."""

def point_depth(point, duration, probability, db) -> DesignDepth | None:
    """IDW of the 4 nearest grid points at a point (Hydrolog's inverse_distance_weighting)."""
```

#### 2.4.9 `core/land_cover.py`
**Responsibilities:**
- Intersection of the boundary with the land cover
- Computing the weighted CN

**Main functions:**
```python
def get_land_cover_for_boundary(boundary: Polygon | MultiPolygon, db: Session) -> dict | None:
    """The land cover of the watershed and the area-weighted CN of its soil-cover
    complexes (ADR-075): categories, total_area_m2, weighted_cn, weighted_imperviousness,
    forest_pct, urban_pct, hsg_assumed_pct, complexes; None without land cover."""

def determine_cn(boundary, db, config_cn=None, default_cn=75, use_kartograf=True,
                 boundary_wgs84=None, cache_dir=None, teryt=None) -> tuple[float, str, dict | None]:
    """CN by the hierarchy configuration → database → Kartograf → default (scripts/analyze_watershed.py)."""
```

#### 2.4.10 Network delineation: `core/network_tree.py`, `core/network_delineation.py`, `core/network_preview.py`, `core/handoff.py` (ADR-080, ADR-081)
**Responsibilities:**
- `core/network_tree.py` (pure, on the catchment graph; `build_network_tree(cg, outlet, points, threshold_m2)`): the nodes of the network (stream cells of `threshold_m2` into which two or more such streams drain), every control point, the closing section included, drawn to the nearest node within 50 m below or above it (`at_node`), the parent of each control point, the trunk of each control point and of each branch of points that enter a trunk through one unit by `trace_main_channel` (ADR-046), the junctions, every branch that joins at a point at a node entering it (a river without a point as a headwater of its own), the element of every unit of the closing section's catchment (`CatchmentGraph.upstream_tree`), the units split by points, the ids `J…` and `P…` of the nodes, `Z…`, `R…` and the outlet `O` (`OUTLET_ID`), numbered by a walk from the closing section upward and listed in the order of the hand-off; a `Junction` carries its `kind`, the handle of its `point` and its `inflows`, a `PointNode` the handle, the place, `at_node` and its `node`
- `core/network_delineation.py` (`delineate_network(cg, db, outlet, points, threshold_m2, settings=None) -> Network`): snapping in a window of 100 m, one window of the six saved rasters over the closing section's catchment (at most 60 M cells), the element raster with the split units (pyflwdir basins), the area check in cells (B5), the measures of every element from its cells (`core/cell_parameters.py`, a `WatershedResponse` each), the boundaries as one coverage simplified at 5 m, the reaches (length from the flow distances, slope from the NMT, the BDOT10k check length from `bdot_streams`)
- `core/network_preview.py` (`preview_network(cg, db, outlet, points, threshold_m2, settings=None) -> NetworkPreview`, ADR-081): the snapping and the tree of the full run, the areas of the elements from the cells of their units (a split unit from the accumulation at its points, `Place.accumulation_cells`), the reach lengths from the flow distances and their lines from `stream_network`, the outlines from a cover of the closing section's catchment by the largest sub-catchment of any threshold that one element holds whole (`outline_cover`, `CatchmentGraph.coarser_at_outlets`) united by element on a grid of 10 m in PostGIS; no window of the closing section's catchment
- `core/handoff.py`: `build_handoff` writes the hand-off of a watershed (ADR-068, `Z1` into `OUT`), `build_network_handoff(network, names, created_at=None)` that of a network: one `nogat-handoff/1` with `node_provenance` around one `hydrolog-network/1` with the network's ids and the outlet `O`, no id of the request, no rainfall, time step, result or reach sections (`docs/integrations/HYDROLOG.md`)

The steps and their reasons: `docs/COMPUTATION_PIPELINE.md` (Phase 7) and the plans `docs/plans/2026-11-10-network-delineation.md` (D1–D15), `docs/plans/2026-11-11-network-preview.md` (P1–P6) and `docs/plans/2026-11-11-network-nodes.md` (N1–N8).

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
Determination of the flow path from the watershed divide (the longest path from the watershed boundary to the outlet). It complements the longest flow path as an additional morphometric parameter. The geometries of both paths are stored per sub-catchment in `stream_catchments` (columns `longest_flow_path_geom`, `divide_flow_path_geom`). For a delineated watershed, `core/divide_flow_path.py` reads the cells of the watershed itself (cells of its sub-catchments in `dem_mosaic_10_subcatchments_<threshold>.tif`) once and draws both paths from them: the longest flow path starts at the cell farthest along the flow (`dem_mosaic_04b_stream_distance.tif`), the divide flow path at the farthest boundary cell (a 4-neighbour outside); both follow `dem_mosaic_03_flowdir.tif` to the outlet, so the drawn longest flow path has the length of `flow_path_length_km` (D8 steps of 5 m or 5√2 m), and the divide flow path, with the same baseline, is never longer. The lines join the cell centres where the direction changes, as `stream_network` joins them, so they lie on the streams they follow. Neither `longest_flow_path_geom` nor `divide_flow_path_geom` is read for a watershed; without the rasters the response has no flow path lines.

#### Monotonic stream smoothing (ADR-041, ADR-072, ADR-077)
The DEM along every burned BDOT10k line descends strictly in the direction of its flow (`smooth_streams_monotonic`, `core/hydrology.py`). The direction of a line is the first of: towards the mouth of its MPHP watercourse; down the DEM of its whole watercourse for the blocks of lines digitized against the rest of it (a block whose own DEM falls more than 2 m the way it is digitized keeps it); the digitized direction, reversed only where the DEM rises along the line by more than 2 m over at least 200 m (ADR-072). An artificial connector never takes its direction from the DEM along it. `classify_endorheic_lakes` takes the burned lines in the directions the smoothing returns. The diagnostic `scripts/check_stream_directions.py` writes for each line the rule that decides it and whether it is reversed (`regula`, `odwraca`, `blok_zachowany`) to a GeoPackage, without changing the pipeline.

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
│ imperviousness       FLOAT        (0.0 - 1.0)                  │
│ bdot_class           VARCHAR(20)  (source: layer[:kind])        │
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
-- The pieces of the soil-cover complexes (core/land_cover.py, _COMPLEXES_SQL, which
-- also returns the land cover whole); the CN of a piece is the TR-55 value of its
-- category or source on its soil group (core/cn_tables.py, ADR-075)
WITH soils AS (
    SELECT hsg_group, ST_Intersection(geom, ST_GeomFromGeoJSON($1)) AS geom
    FROM soil_hsg
    WHERE ST_Intersects(geom, ST_GeomFromGeoJSON($1))
)
SELECT
    lc.category,
    lc.bdot_class,
    s.hsg_group,
    SUM(ST_Area(ST_Intersection(lc.geom, s.geom))) AS area_m2
FROM soils s
JOIN land_cover lc ON ST_Intersects(lc.geom, s.geom)
GROUP BY lc.category, lc.bdot_class, s.hsg_group;
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
├── index.html               # SPA — Archiwista shell; Leaflet + MapLibre GL + Chart.js (CDN with SRI), no Bootstrap
├── admin.html               # Admin panel (ADR-034) — shell + Bootstrap 5.3.3 (grid, modal dialogs)
├── img/
│   └── hydrograf.svg         # Hydrograf mark (top bar, favicon)
├── nogat/                    # Copies of Nogat's GUI kit 0.6.0 (design/kit/, ADR-082, ADR-083, ADR-084) — do NOT edit, copy them again
│   ├── nogat-app-menu.js     # <nogat-app-menu>: the menu „Aplikacje” of the deployment's GUIs (ES module)
│   ├── nogat-app-menu.css    # Its styles, in the tokens
│   ├── nogat-sources.js      # <nogat-sources>: the view's strip of provider lines and its dialog, fillSources() for the welcome window (ES module)
│   ├── nogat-sources.css     # Its styles, in the tokens
│   ├── nogat-handoff.js      # The hand-off: labels, <subject>.handoff.json, text, clipboard with its fallback, download (ES module)
│   ├── nogat-terms.html      # The regulamin template with its blocks, which core/terms.py fills (ADR-084)
│   ├── nogat-terms.css       # Its styles, in the tokens
│   ├── nogat-terms.md        # The regulamin's text for review
│   ├── nogat-kit.json        # Kit version and SHA-256 of each file
│   └── marks/                # The marks of the four GUIs (Nogat design/marks/): archiwista, hydrograf, hydrolog, obserwator
├── instrukcja/
│   ├── index.html            # Scrolling user guide (/instrukcja/) with TOC and chapters
│   ├── instrukcja.css        # Guide layout; chrome and colours come from shared CSS
│   ├── prezentacja.css       # Separate layout for docs/Hydrograf-prezentacja.html slides
│   └── Hydrograf-*.png       # Shared 256-colour screenshots for guide and presentation
├── css/
│   ├── tokens.css            # Copy of Nogat's design/tokens.css (commit 7786271) — do NOT edit, copy it again
│   ├── chrome.css            # Shared shell: top bar, rail, panels, buttons (index, admin, instrukcja)
│   ├── app.css               # Main page: map, Warstwy/Zlewnia panels, profile drawer, phone layout
│   └── admin.css             # Admin panel (Bootstrap recoloured with the tokens)
└── js/
    ├── theme-init.js         # Theme from localStorage (`nogat-theme`) before the first paint
    ├── theme-switch.js       # Theme switch Auto/Jasny/Ciemny in /admin and /instrukcja
    ├── shell.js              # Main-page shell: panels, width handles, phone layout, theme
    ├── api.js                # API calls (fetch wrappers)
    ├── map.js                # Leaflet map, drawing, MVT; wheel zoom without the tail of a gesture or late input
    ├── coords.js             # Cursor coordinates (bottom left): WGS84, PL-1992 or PL-2000 by Gauss–Krüger in the browser; not on touch screens
    ├── charts.js             # Chart.js in the token colours: hypsometry, land cover/HSG, hietogram, hydrograph, profile
    ├── attribution.js        # The providers' lines of a response or a manifest entry (ADR-083): their union over the view's surfaces in the strip #view-sources, the trailing CSV columns and the JSON/GeoJSON fields of the exports
    ├── layers.js             # „Warstwy” panel: basemaps with the flood hazard map overlay (WMS of Wody Polskie), overlays, opacity, zoom to extent; flow accumulation threshold in ha/km²
    ├── profile.js            # Terrain profile (line drawing) with the water surface of the analysis results that are on
    ├── hydrograph.js         # Hietogram form (AMC, rainfall source) and hydrograph form, balance, charts
    ├── custom-rain.js        # Own rainfall series: table of steps, paste, CSV import, copy of the hietogram
    ├── rain-export.js        # Export of the hietogram (CSV, JSON) and of its PMAXTP points with weights (GeoJSON)
    ├── info.js               # (i) explanations: markers, shared panel, MathML formulas; opened by a click, a tap, Enter or Space, closed by the same (i), Esc or a click outside
    ├── info-texts.js         # 86 explanations (formula, variables, unit, meaning) keyed by an API field, a control id or a kind of the network's elements
    ├── advanced.js           # Advanced mode: editing of the morphometry for POST /api/generate-hydrograph
    ├── depressions.js        # Depressions (blue spots) overlay
    ├── sewer.js              # Storm-sewer layer (MVT overlay; only when GET /api/layers reports data)
    ├── results.js            # External analysis results (e.g. SFINCS of Hydraulik) from the manifest /data/results/index.json: tiles, legend, (i)
    ├── identify.js           # Mode „Identyfikuj”: marker and point card (GET /api/identify-point)
    ├── network.js            # „Wybierz zlewnię” → „Sieć zlewni”: the closing section, then the points, each marker labelled by its node's id (J<n>, P<n>) after every preview (POST /api/delineate-network/preview), the characteristics (POST /api/delineate-network), the network on the map, its tree and selection in the panel (ADR-080, ADR-081)
    ├── handoff.js            # „Przekazanie do Hydrologa”: the hand-off of the watershed or of the network through the kit's nogat-handoff.js (ADR-068, ADR-080, ADR-082)
    ├── nogat.js              # ES module (index, admin, instrukcja): imports the kit, sets GET /api/gui as the apps of <nogat-app-menu>, puts the hand-off module on window.Hydrograf.nogat (ADR-082)
    ├── terms.js              # GET /api/terms: the footer under the map and in the guide (the statement and „Regulamin”), the `terms` of the menu and of the strip, PMAXTP's lines for the welcome window, the operator's e-mail under „Zgłoś uwagę” (ADR-084)
    ├── feedback.js           # „Zgłoś uwagę” form (native <dialog>): the text and the view's context, no contact (ADR-084)
    ├── instance.js           # The area of the instance from /data/instance.json (also on /instrukcja: [data-instance-area])
    ├── welcome.js            # Welcome dialog (native <dialog>): first visit and the main-page top-bar "Instrukcja" button; the full provider lines and terms (fillSources)
    ├── app.js                # Orchestrator: init, work modes, click routing, Zlewnia panel
    └── admin/
        ├── admin-api.js      # Admin API client (fetch + X-Admin-Key header)
        ├── admin-bootstrap.js # Bootstrap SSE stream, start/cancel
        ├── admin-bbox-picker.js # Map for choosing the area bbox
        ├── admin-sewer.js    # Card for managing the sewer network
        ├── admin-feedback.js # List of the reports with their context and the old form's fields
        └── admin-app.js      # Admin panel orchestrator
```

`js/` holds 30 IIFE modules on `window.Hydrograf`, 24 for the main page and 6 in `admin/`, and one ES module, `nogat.js`, which imports Nogat's kit (`nogat/`) and puts it on `window.Hydrograf.nogat` (ADR-082); `theme-init.js` and `theme-switch.js` stay outside the namespace. ADR-065 removed `css/glass.css`, `css/style.css` and `js/draggable.js`.

The visual identity comes from Nogat (standard DEV-15.3, ECO-055, ADR-065): the pattern is in Nogat's `design/`, the mockup in `design/mockups/hydrograf/`. Colours, fonts, radii and shadows only through the variables of `css/tokens.css`; a change of the palette is made in Nogat and ends with copying the file again.

---

### 4.2 UI Components

#### 4.2.0 Shell

The main page uses the Archiwista shell (`chrome.css` + `app.css` + `shell.js`):

- **Top bar** — the mark `img/hydrograf.svg`, the buttons „Zgłoś uwagę” and „Instrukcja” (in that order), the app menu „Aplikacje” and the theme switch Auto/Jasny/Ciemny (`data-theme` on `<html>`, the choice in `localStorage` `nogat-theme`; `theme-init.js` sets it before the first paint, so the light theme does not flash). On the main page the guide button opens the welcome dialog, whose link opens `/instrukcja/` in a new tab; a modified click opens the guide directly. On `/admin` it links straight to the guide. The service status („Usługi działają”) is only in the top bar of `/admin` (`admin-app.js`: `GET /health` when the page opens, then the dashboard refresh).
- **App menu „Aplikacje”** (ADR-082, Nogat DEV-15.4) — the kit's `<nogat-app-menu current="hydrograf">` left of the theme switch on `/`, `/admin` and `/instrukcja/`: a button with a grid icon (the icon alone on phones) that opens the list of the GUIs of `GET /api/gui` (§2.2.1a), each with its mark (`nogat/marks/`), name and one line; Hydrograf marked „Ta aplikacja” and not a link, every other GUI opening in its tab `nogat-<name>`. Without `HYDROGRAF_GUI`, or with Hydrograf alone in it, the button is not drawn. After a copy or a download the hand-off's status links „Otwórz Hydrologa” to the same address and tab.
- **Welcome dialog** — `welcome.js`, a native `<dialog>` like „Zgłoś uwagę”: on the first visit two plain-language paragraphs (what Hydrograf is, that the results are estimates and not a flood forecast, the area of the data) and the buttons „Otwórz instrukcję” (new tab) and „Przejdź do mapy”. The box „Nie pokazuj ponownie” stores the choice in `localStorage` (`hydrograf-welcome-hidden`). The area of the data comes from `/data/instance.json` (`instance.js`; `frontend/data/instance.json`, served by `location ^~ /data/`, written by the bootstrap or `scripts/write_instance_info.py`): „Obszar danych: <area.name> (ok. <area_km2> km²); NMT <nmt.resolution_m> m, zestaw danych „<set.name>” (zamknięty <set.closed_at>)”. Without the file (404) or with another schema the neutral text remains.
- **Navigation rail** — Mapa and Logowanie (`/admin`); on phones it becomes a bottom bar. The terrain profile is a mode of the map bar; „Instrukcja” belongs only to the top bar.
- **Left panel „Warstwy”** — basemaps (with the overlay „Mapa zagrożenia powodziowego”), overlays with an opacity slider and one button that zooms to the extent of the layers that are on.
- **Centre** — the map with the mode bar Przeglądanie / Wybierz zlewnię / Profil terenu / Identyfikuj; the terrain profile opens in a bottom drawer over the map, the point card of „Identyfikuj” (`identify.js`, `GET /api/identify-point`, §2.2.5a) in the top right corner of the map (a sheet at the bottom of the map on phones). The cursor coordinates (`coords.js`) sit in the bottom left corner, under the legends, in the system chosen there (WGS84, PL-1992 or PL-2000, kept in localStorage); screens without a hovering pointer do not show them.
- **„Wybierz zlewnię” and its two options** (`app.js`, `setClickMode`; ADR-080, note of 2026-11-11) — while the mode is on, the radio group „Co wyznaczyć” sits at the top of the map (`#select-tools`, placed and styled like the drawing tools of „Profil terenu”, `.map-tools`, also on phones): „Jedna zlewnia” (the default; the click mode `select`) or „Sieć zlewni” (the click mode `network`). The button of the mode is on for both; it returns to the option chosen last in the page (`state.selectTarget`, not kept across reloads). Switching the option keeps both the watershed and the network.
- **„Wybierz zlewnię” → „Sieć zlewni”** (`network.js`, ADR-080, ADR-081, §2.2.2b, §2.2.2c) — the first click places the closing section and every later click a point (at most 30), as draggable markers; a marker not yet in a preview shows the first free `P<n>` among the shown ids, which is also its handle in the request, so a problem names it as the map does, and after every preview each marker shows its node's id (`points[].node`: `J<n>` at a confluence, `P<n>` elsewhere). The closing section alone is a network: „Oblicz charakterystyki” needs no other point. 300 ms after every change of the points (added, removed, dropped) or of the threshold of „Linie spływu”, `POST /api/delineate-network/preview` (`api.previewNetwork`, an `AbortController` cancels the request on its way and an answer to older points is dropped) moves the markers to their snapped cells and draws the preview: the elements by kind, dashed where the outline is approximate (a point inside its unit has a dashed marker with „≈”), the reaches, the junctions and the legend „Podgląd sieci”; the names are not sent and change no preview. While a preview is on its way, or when it failed, the network drawn before stays, faded; a failed preview shows its error under the buttons (`#network-error`) and marks the points it names, and an error of the composition disables the run. „Oblicz charakterystyki” calls `POST /api/delineate-network` with the names and draws the closing section's boundary and the legend „Sieć zlewni”; the characteristics show while they answer the snapped places and the threshold, after any change of these the preview returns with the notice that they are outdated; that notice (with its own text) and a disabled hand-off also follow a renamed point, whose name the hand-off carries, until they are computed again or the points come back. The right panel serves the view of the option (`app.js`: `data-view="network"` on `#results-panel`, each view with its own loading state, error and bin): the closing section first, then the points by their ids, each with its name field and „w węźle sieci” when it was drawn to a node (`at_node`), the check of B5, the notices and the tree from the closing section upward (a node entered without a reach as „J4 → J1”; in the preview the area and the length, „—” for CN and slope); an element chosen in the tree or by its label on the map fills the parameter sections (without the hietogram and the hydrograph), a reach its own table, in the preview a short summary; `handoff.js` hands off the network. The watershed of „Jedna zlewnia” leaves the map in the option (`map.setWatershedShown`) and returns, with its sections, after it.
- **Right panel „Zlewnia”** — key values (tiles) and `<details>` sections: basic parameters, shape indices, relief, river network, land cover, HSG groups, hietogram, hydrograph. The × of its head hides the panel and keeps the result on the map (the button „Zlewnia” of the map bar brings it back); the button with the bin („Wyczyść wynik”, disabled while the panel shows only its instruction) clears the result. Esc once hides the panel, twice clears the result.
- **(i) explanations** — `info.js` adds (i) markers in the sections Parametry podstawowe, Wskaźniki kształtu, Rzeźba terenu, Sieć rzeczna, Hietogram and Hydrogram, and in the option „Sieć zlewni” at the kinds of the network's elements and the rows of a reach; one shared panel opens on a click or a tap of the (i), or on Enter or Space when it has the focus, never on hover or focus (`aria-expanded` on the button), and closes with the same (i), Esc, a click or tap outside it or a move of the focus to another control. The 75 entries of `info-texts.js` keyed by an API field, a form control id or a kind of the network's elements (the other 11 belong to the options of the UH model, Tc method and Nash estimation selects) hold: a description, a formula (built as MathML through the DOM, without libraries), the list „gdzie:” of the variables with their units, the unit of the result, a separate block „Znaczenie dla analizy”, the range of applicability and a note. The texts rest on Hydrolog and the backend (e.g. the hydrograph limit of 250 km², `HYDROGRAPH_AREA_LIMIT_KM2`). The applicability notes under Model UH, Metoda Tc and Estymacja Nash follow the choice. The API returns no applicability warnings, so the GUI shows none.
- **Hietogram: AMC and rainfall source** — the field „Uwilgotnienie początkowe (AMC)” I / II / III (`amc` in the request, II by default); the balance shows the CN used with one decimal place and the AMC class. The switch „Źródło opadu” PMAXTP / Własna seria (`custom-rain.js`): „Czas trwania [min]” and „Krok czasowy [min]” build a table of steps with an editable depth [mm]; a column pasted from a spreadsheet fills the following rows; „Importuj CSV” takes 1 column (depth, at the current step) or 2 columns (time, depth; an even step sets the step and the duration); „Wczytaj z bieżącego hietogramu” copies the PMAXTP series. The series goes to `custom_precipitation`, and the PMAXTP hietogram is then skipped.
- **The providers' lines** (`attribution.js`, ADR-083 and its amendment, Nogat DEV-20.5) — one strip for the view, the kit's `<nogat-sources id="view-sources">` in the foot of the view (`#view-foot`, across the map and both panels, above the footer): 12 px in `--text-3`, the lines S, P, PS and PP that the shown data carry (for PMAXTP: PS and PP, two rows at 1440 px) and „Źródła i warunki”, a dialog with every line (PS, PP, M), the terms (RK) and „Regulamin serwisu” on a public deployment; without lines it is not drawn. Its lines are the union of those of the hydrograph response while „Hietogram” or „Hydrogram” is laid out, of an own series while its table is (filled by „Wczytaj z bieżącego hietogramu”, it keeps the lines of the PMAXTP result it copied and goes out with `derived_from: "pmaxtp"` through edits, pastes and changes of its size, until „Wyczyść”, an imported CSV or a new watershed), of the results whose layer is on, of the point card's water and of the profile's water. On phones the sheets stop above the foot of the view (`--view-foot-h`, `shell.js`), so the strip stays in sight. The welcome dialog shows the full lines and terms of `GET /api/terms` under its text (the kit's `fillSources`). The exports carry the lines of the response: „Hietogram CSV” the trailing columns `attribution` and `terms_notice` (one line per cell from the first row down; with fewer rows the last row holds the rest, joined by a line feed), „Hietogram JSON” and „Punkty PMAXTP (GeoJSON)” the fields of the same names (in the GeoJSON foreign members); without lines nothing is added. The hand-off file and copy are the API's document with its fields.
- **Hydrograph form** — a grid of two columns: „Model UH” | „Metoda Tc”, for Nash „Model UH” | „Estymacja Nash”; the applicability notes in even rows. Before a request `hydrograph.js` checks the number fields in use against the limits of the API (α, β in (0, 20]; C (spływ) in (0, 1], required by FAA and never derived from the CN; N (opór) in [0.02, 0.8], required by Kerby and Kerby–Kirpich; Ct > 0; Cp in (0, 1]); an empty or zero field is an error, never replaced by a default. The message stands under the field (also a server `errors[]` message, placed by its JSON Pointer), the sections Hietogram and Hydrogram name the fields to fix, and the charts and tables of the earlier calculation are hidden until the form is valid again (also while the own rainfall series or the advanced mode is invalid).
- **Advanced mode** — `advanced.js` lets the user change the morphometry sent to `POST /api/generate-hydrograph` (the fast path `morphometry`): area, perimeter, length, elevations, mean slope, stream length and slope, `length_to_centroid_km`, CN. Precision of the fields: area 0.01 km², lengths and Lc 0.01 km, elevations 0.1 m, slopes 0.01 %, CN 0.1 (1–100); the area at most `area_limit_km2` of `GET /api/scenarios` (250 km², the API refuses more as it does for a delineated catchment). Changed fields are marked; one field or all of them can be restored („Przywróć dane z Hydrografa”); validation errors block the request; the result carries the message „Obliczono na zmienionych danych wejściowych”. Rainfall and AMC are set in the Hietogram section. Some catchments have `length_to_centroid_km = 0`: Snyder fails until the user gives Lc.
- **CN** — the API returns the CN of the catchment (`morphometry.cn`, `land_cover_stats.weighted_cn`) to 0.1; the panel shows it with one decimal place.
- **Sewer layer** — the entry „Kanalizacja deszczowa” of the „Warstwy” panel appears only when `GET /api/layers` returns `sewer: true`; without data no `/api/tiles/sewer` tiles are requested.
- **External analysis results** — `results.js` reads the manifest `/data/results/index.json` once at startup (`frontend/data/results/`, served by `location ^~ /data/`):

  ```json
  {"schema": "hydrograf-results/1",
   "results": [{"id": "sfincs-kamiennik-24h-p1", "title": "Głębokość wody — SFINCS, opad 24 h, p = 1%",
                "group": "Wyniki analiz", "kind": "raster_tiles",
                "tiles": "/data/results/sfincs-kamiennik-24h-p1/tiles/{z}/{x}/{y}.png",
                "bounds": [15.887684, 50.987114, 16.047343, 51.051342], "min_zoom": 10, "max_zoom": 16, "opacity": 0.8,
                "legend": {"title": "Maks. głębokość wody", "unit": "m",
                           "classes": [{"label": "0,05–0,2", "color": "#c6dbef"}, {"label": "> 2", "color": "#08306b"}]},
                "description": "…", "source": "Hydraulik 0.1.0.dev0 / SFINCS v2.4.1; …",
                "water_level": {"path": "/data/results/sfincs-kamiennik-24h-p1/wse_max.tif",
                                "crs": "EPSG:2180", "unit": "m n.p.m."}}]}
  ```

  `bounds` is [west, south, east, north] in WGS84; the tiles are XYZ PNG with transparency (`gdal2tiles --xyz`). Every `raster_tiles` result gives a row in the group `group` (the existing „Wyniki analiz” under „Linie spływu”; a new group is created above the basemaps only when a result needs it): an `L.tileLayer` in the pane `resultsPane` (z-index 300: above the DEM and the land cover, below the flow lines) with `bounds`, `minZoom` 8, `minNativeZoom`/`maxNativeZoom` from the manifest and the opacity from `opacity`; the legend (swatches from `legend.classes`, the unit in the title) only while the layer is on; `description` and `source` in the (i) explanation. The extent counts for „Przybliż do zasięgu warstw”. Other values of `kind` are skipped with a warning; a missing manifest, invalid JSON or another `schema` give one console warning and no rows.

  `water_level` (optional; a backward-compatible extension of `hydrograf-results/1` that older clients skip) names a GeoTIFF of the maximum water surface elevation on the model grid (float32, LZW, nodata where the maximum depth is below 0.05 m, the lowest legend class); `crs` and `unit` describe the raster. The API reads it, not the browser: `POST /api/terrain-profile` with `result_ids` (§2.2.5) samples the raster at the points of the profile (`core/analysis_results.py`). The path `/data/…` names a file in `FRONTEND_DATA_DIR` (default `/frontend/data`, the directory `frontend/data` mounted in the API container) and must stay in its subdirectory `results/`; otherwise the result is skipped. The terrain profile (`profile.js`) asks for the results with `water_level` whose layer is on (`results.shownWaterLevels()`), and switching such a layer on or off redraws an open profile. The water surface is a blue area between the terrain and the water level where the water lies above the DEM; under the chart the legend „Teren” and „Zwierciadło wody — <result title>”, and the readout under the cursor (under the finger on a phone) gives the terrain, the water level and the depth (water level minus DEM). A line that does not cross a result gives an unchanged chart. The raster is made by the publication script of a Hydraulik run from `zsmax` in `sfincs_map.nc`.

  `attribution` and `terms_notice` (optional arrays of texts, ADR-083) are the lines the terms of the providers of a result's data require, written by its producer (the SFINCS result of a PMAXTP rainfall: PS, PP, M and RK of `core/attribution.py`). They go to the view's strip while the layer is on (§4.2.0); the API returns them with the result's water (§2.2.5, §2.2.5a), and the point card and the profile hand those to the strip. A value that is not a list of texts is ignored.
- **Panel width** — handles between the panels (left 260–560 px, right 340–720 px), kept in `localStorage`; the panels can be closed.
- **Phone (≤ 860 px)** — a full-screen map, a bottom bar (Mapa and Logowanie) instead of the rail, with the top-bar guide/feedback/theme icons still accessible, and panels as sheets that slide up from the bottom (a handle at the top hides them too). The map bar has two rows: „Warstwy” and „Zlewnia” („Sieć” in the option „Sieć zlewni”), then the four modes across the full width (labels may wrap), so nothing lies off a 375 px screen; the options of „Wybierz zlewnię” span the top of the map.

`/admin` and `/instrukcja` use the same shell (`chrome.css`) and the switch `theme-switch.js`. The form „Zgłoś uwagę” is a native `<dialog>` with the text only: under it „Nie wpisuj danych osobowych.” and, with an operator, „Jeśli chcesz odpowiedzi, napisz na <e-mail>”; `feedback.js` sends the view's context with the text. With `GET /api/terms` giving an address, `terms.js` shows the footer `#site-footer` under the map (and in the guide) with the statement of Nogat DEV-15.8 and the link „Regulamin”, and gives the app menu its `terms` attribute, which ends its list with „Regulamin” (ADR-084).

#### 4.2.1 Map (Leaflet.js)

Basemaps (`layers.js`): **OpenFreeMap szary** (vector, the `positron` style from `https://tiles.openfreemap.org`, rendered by MapLibre GL 4.7.1 and `@maplibre/maplibre-gl-leaflet` 0.0.22; without MapLibre it falls back to OSM GUGiK), **OSM GUGiK szary** (raster, Poland only, greyed by the class `.basemap-grey`), **Ortofotomapa ESRI**, **bez podkładu** (no basemap).

**Wheel zoom** (`map.js`, `wheelZoomHandler`): Leaflet's scroll-wheel handler (`scrollWheelZoom` is off) with two guards, because the default turned every 40 ms batch of wheel events, however small, into a whole zoom level and went on zooming after the wheel had stopped. An event weaker than half of the strongest event of its gesture is the fading tail of a touchpad, a Magic Mouse or a smooth-scrolling mouse driver and is ignored (a pause of 80 ms or a change of direction starts a new gesture), and wheel input older than 150 ms, an event or a whole batch that waited while the page was busy (e.g. MapLibre redrawing the base map), does not start a zoom step.

**Flood hazard map (MZP)** — an overlay in the group „Podkłady kartograficzne”, above the list of basemaps: a checkbox independent of the basemap choice (off by default), opacity 80 %, and while it is on, the field „Prawdopodobieństwo powodzi” (0,2 % — raz na 500 lat, 1 % — raz na 100 lat (the default), 10 % — raz na 10 lat), a hint about the scale and a legend in the lower left corner of the map. Source: the WMS 1.3.0 services (ArcGIS Server) of Państwowe Gospodarstwo Wodne Wody Polskie (KZGW, ISOK) with the water depth of the MZP of the 2020 update, for river floods:

| Probability | Service (`https://wody.isok.gov.pl/gpservices/KZGW/<service>/MapServer/WMSServer`) | Layer |
|---|---|---|
| 0.2 % (once in 500 years) | `MZP20_Glebokosc_NiskiePrawdopodPowodzi` | `16` |
| 1 % (once in 100 years) | `MZP20_Glebokosc_SredniePrawdopodPowodzi` | `16` |
| 10 % (once in 10 years) | `MZP20_Glebokosc_WysokiePrawdopodPowodzi` | `1` |

- `L.tileLayer.wms` in EPSG:3857, PNG with transparency, 512 px images (three times fewer requests than 256 px at the same resolution); a change of the probability swaps the URL and the `layers` of the same layer (`setUrl`, `setParams`), so the on state and the opacity stay. The marine layers of these services (layer `1` for 1 % and 0.2 %) and the other MZP scenarios are not shown. The ArcGIS layer numbers can change when the services are republished; then `MZP_SCENARIOS` in `layers.js` must be corrected.
- The services draw the depths only at the scale 1:50 000 and larger (`MaxScaleDenominator` 47 247 at a pixel of 0.28 mm), that is from zoom 14. Below it the layer is taken off the map (no empty requests), and the panel and the legend show „Przybliż mapę…”. The layer has no `minZoom`: Leaflet would take it as the lower zoom limit of the whole map when it is the only tile layer (e.g. with the OpenFreeMap basemap).
- The pane `hazardPane` (z-index 255): above the basemap (`tilePane`, 200) and the DEM (`demPane`, 250), below the land cover (260) and the other layers of Hydrograf; the analysis results (e.g. SFINCS) lie above the MZP. The DEM at its default opacity of 70 % does not dim the MZP.
- The legend uses the depth classes of the services (GetLegendGraphic: h ≤ 0.5 · 0.5 < h ≤ 2.0 · 2.0 < h ≤ 4.0 · h > 4.0 m) in the colours the services draw (`#cfe8fa`, `#a7caf7`, `#7face3`, `#7f98b9`, checked with GetFeatureInfo); the GetLegendGraphic image (96 × 72 px on white) is not used because it does not fit the dark theme.
- Attribution: „MZP © Wody Polskie / ISOK (CC BY 4.0)” with links to the Hydroportal and the licence; the CC BY 4.0 licence follows the dataset „Mapa zagrożenia powodziowego (MZP)” on dane.gov.pl (provider: Krajowy Zarząd Gospodarki Wodnej). The ArcGIS REST/WMTS services of these maps return 401; only the WMS is public. Response times vary: usually 0.4–2 s per image, sometimes single images take 10–30 s.

```javascript
// map.js (sketch)
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

#### 4.2.3 Hydrograph Chart

All charts (`charts.js`) take their colours, font and font size from the tokens (`getComputedStyle`) and repaint in place when the theme changes (`data-theme` or the system scheme). The hietogram is a line chart like the hydrograph; land cover and HSG groups are horizontal stacked bars. The sketch below shows only the layout of Chart.js; its fixed colours are only an example.

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
      HYDROGRAF_GUI: ${HYDROGRAF_GUI:-}
      # The public service (ADR-084): the deployment's nogat.toml, mounted below
      NOGAT_CONFIG: /config/nogat.toml
      HYDROGRAF_REQUEST_LIMIT: ${HYDROGRAF_REQUEST_LIMIT:-300}
      HYDROGRAF_REQUEST_WINDOW: ${HYDROGRAF_REQUEST_WINDOW:-60}
      # GDAL's block cache [MB]: a network reads up to 1.4 GB of rasters once
      # (ADR-080), which the default cache (5 % of the RAM) would keep a second time
      GDAL_CACHEMAX: "64"
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped
    # The host's journal keeps the logs 14 days (DEV-15.10, docker/journald.conf)
    logging:
      driver: journald
      options:
        tag: "{{.Name}}"
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
      - ./frontend/nogat:/frontend/nogat:ro              # the regulamin template
      - ${NOGAT_CONFIG:-/dev/null}:/config/nogat.toml:ro
    command: uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload --no-access-log

  nginx:
    image: nginx:alpine
    container_name: hydro_nginx
    ports:
      - "127.0.0.1:${HYDROGRAF_PORT:-8080}:80"
    volumes:
      - ./frontend:/usr/share/nginx/html:ro
      - ./docker/nginx.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - api
    restart: unless-stopped
    logging:
      driver: journald
      options:
        tag: "{{.Name}}"

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
- `docker-compose.prod.yml` — production override: one uvicorn process (the request limit and the daily totals live in its memory, ADR-084), `LOG_LEVEL=WARNING`, without `--reload`
- uvicorn always runs with `--no-access-log` (its access log would name the client); `api.main` logs every request without it

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

    # Logs without the client's address (Nogat DEV-15.10, ADR-084)
    log_format hydrograf '$time_iso8601 "$request_method $request_uri" $status '
                         '$body_bytes_sent request_time=$request_time '
                         'upstream_time=$upstream_response_time request_id=$request_id '
                         '"$http_user_agent"';
    access_log /dev/stdout hydrograf;
    error_log /dev/stderr crit;

    gzip on;
    gzip_types text/plain text/css application/json application/geo+json
               application/javascript text/xml application/xml application/x-protobuf;

    # No limit here: the API limits pages and routes per client address (api/traffic.py)

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

        # Tile proxy (^~ prevents the regex .pbf match of the data files)
        location ^~ /api/tiles/ {
            proxy_pass http://api_backend/api/tiles/;
            proxy_set_header X-Request-ID $request_id;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_read_timeout 15s;
        }

        # Own code and styles, referenced as ?v=<content hash>
        location ~* \.(css|js|ico|svg)$ {
            root /usr/share/nginx/html;
            expires 1h;
            add_header Cache-Control "public, must-revalidate";
        }

        # HTML pages pass through the API, which limits and counts them and answers
        # X-Accel-Redirect to /_site/ (or the regulamin, or 429); with the API down
        # nginx sends the file itself
        location ~* \.html$ {
            proxy_pass http://api_backend;
            proxy_set_header X-Request-ID $request_id;
            proxy_set_header X-Real-IP $remote_addr;
            error_page 502 504 = @page_file;
        }
        location ^~ /_site/ {
            internal;
            alias /usr/share/nginx/html/;
            expires -1;
        }
        location @page_file {
            root /usr/share/nginx/html;
            expires -1;
        }

        # Admin panel (Cloudflare Access in front of it, with /api/admin/)
        location = /admin {
            rewrite ^ /admin.html last;
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
            proxy_set_header X-Request-ID $request_id;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Admin-Key $http_x_admin_key;
            proxy_read_timeout 3600s;
            proxy_buffering off;
        }

        # API proxy
        location /api/ {
            proxy_pass http://api_backend/api/;
            proxy_set_header X-Request-ID $request_id;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_read_timeout 120s;
        }

        # Health check endpoint
        location /health {
            proxy_pass http://api_backend/health;
        }
    }
}
```

`X-Real-IP` is nginx's peer, never the client behind the tunnel: the API believes the client's address of `CF-Connecting-IP` only when that peer is a private hop (§2.2.1b). nginx does not read `CF-Connecting-IP` and writes no address in either log (`$remote_addr`, `$remote_user`, `$http_referer` are gone; nginx names the client in the errors of a request, which the `crit` level drops). `docker/nginx-ssl.conf.template` has the same locations and logs.

**CSP — allowed external hosts** (`docker/nginx.conf` and `docker/nginx-ssl.conf.template`, identical):
- `script-src`, `style-src`: `https://unpkg.com` (Leaflet, MapLibre GL, maplibre-gl-leaflet), `https://cdn.jsdelivr.net` (Chart.js, Bootstrap in `/admin`); every library from a CDN has SRI (`integrity`).
- `img-src`: `data:`, `blob:`, `https://mapy.geoportal.gov.pl` (OSM GUGiK, also the area selection map of `/admin`), `https://server.arcgisonline.com` (ESRI orthophoto), `https://wody.isok.gov.pl` (flood hazard map, WMS of Wody Polskie).
- `connect-src`: `https://tiles.openfreemap.org` (style, vector tiles and glyphs of OpenFreeMap, fetched by MapLibre).
- `worker-src blob:`, `child-src blob:` — the Web Worker of MapLibre GL.

**Front-end asset cache.** Cloudflare (a tunnel) stands in front of nginx; it caches the `.js`/`.css` files at the edge (`cf-cache-status: HIT`) and extends the browsers' `max-age` to 4 h (the Browser Cache TTL of the zone). Therefore:
- the HTML pages (`/`, `/admin`, `/instrukcja/`, the SPA fallback to `index.html`) are sent with `Cache-Control: no-cache` and an ETag: the browser and Cloudflare ask nginx at every visit (usually 304), and Cloudflare does not cache them (`DYNAMIC`);
- the pages reference their own JS/CSS by a URL with the version `?v=<10 characters of the SHA-256 of the content>`; a changed file gets a new URL (a new cache key of Cloudflare and of the browser), so a deployment is visible from the first reload without clearing a cache. Unchanged files keep their URL and their cache;
- the versions are set by `python3 scripts/bump_asset_versions.py` (no build step): run it after a change of JS/CSS; `scripts/gate.sh` and the CI job `frontend-assets` check them with `--check`. The relative imports of an own ES module (`js/nogat.js` imports the kit of `nogat/`) get the same `?v=`, written before the pages, so a new copy of the kit changes the URLs of the kit and of `js/nogat.js` (ADR-082). The CDN libraries carry their version in the URL and SRI; the script does not touch them.

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
│  - WARNING+ logs, one uvicorn process                  │
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
- ✅ Request limit per client address in the API (300 in 60 s, tiles 3,000, the form 5 in 5 min; ADR-084)
- ✅ CORS with restrictive origins (env var `CORS_ORIGINS`), `allow_credentials=False`
- ✅ GZip middleware (FastAPI)
- ✅ Request ID tracing (`X-Request-ID` header, structlog context)
- ✅ Security headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options)
- ✅ Resource limits Docker (memory: 2G db, 8G api)
- ✅ Admin API key auth (X-Admin-Key header, file-based or env var, ADR-034)
- ✅ No user authentication needed: a public service under its regulamin (ADR-084); Cloudflare Access in front of `/admin`, `/admin.html` and `/api/admin/*`

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
│  - Request limit per client address (FastAPI)          │
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

**Request correlation and log retention.** nginx gives every request an `X-Request-ID` and logs it with the time, method and URI, status, size, `request_time`, `upstream_time` and the User-Agent, never the client's address (DEV-15.10, ADR-084); its error log writes `crit` only. For pages and API requests nginx passes the same ID to FastAPI. The middleware `add_request_id` of `api/main.py` takes a forwarded ID of 32 hexadecimal characters (otherwise it makes `uuid4().hex`), binds it to the structlog context, returns it in the `X-Request-ID` header and writes `request_completed`, or `request_failed` when the application raises, with `method`, `path`, `status_code` and `duration_ms`, without the client; uvicorn runs with `--no-access-log`. nginx and the API log to the host's journal (Docker's `journald` driver, tag the container's name), which `docker/journald.conf` (`MaxRetentionSec=12day`, `MaxFileSec=1day`) limits to 14 days; PostgreSQL keeps Docker `json-file` logs of 10 MiB × 50 files (README, „Service logs”).

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

from core.version import get_version

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
        "version": get_version()
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
- Cascaded merge threshold for large watersheds (>300 segments) — ADR-042

**Benchmark results:** see `docs/BENCHMARK_QUERIES.md` (the PostGIS queries, ADR-039) and the timings in the CHANGELOG entries.

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
- Own JS/CSS with the version `?v=<content hash>` in the URL (see 5.2, „Front-end asset cache”)
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

**Document version:** 2.19
**Date of the last update:** 2026-11-13
**Status:** Approved for implementation

**Change history:**
- 2.19 (2026-11-13): the providers' terms linked, not restated (Nogat ECO-065; ADR-083 and ADR-084 amended): §2.1 `core/attribution.py` without N, `is_terms`; §2.2.1b and §2.2.3 `terms_notice` [RK] with RK „Regulamin danych PMAXTP: …”, `core/terms.py` without the block `imgw-terms`; §2.2.5, §2.2.5a the manifest's example; §4.1 kit 0.6.0; §4.2.0 the dialog's terms and the manifest's lines
- 2.18 (2026-11-13): one strip of the providers' lines (ADR-083 amended, plan `2026-11-13-compact-sources`): §2.2.1b `attribution` and `terms_notice` of `GET /api/terms`; §4.1 kit 0.5.1 (`nogat-sources`), `attribution.js`, `terms.js`, `welcome.js`; §4.2.0 the strip, the welcome dialog, the sheets above the foot of the view; the manifest's lines in the strip
- 2.17 (2026-11-13): the public service (ADR-084, plan `2026-11-13-public-gui`): §1.1 the pages through the API, the request limit and the totals in it; §1.2 ADR-084; §2.1 `api/traffic.py`, `api/endpoints/site.py`, `feedback.py`, `core/terms.py`, `core/request_limit.py`, `core/usage.py`, migration 007; §2.2.1b `GET /api/terms`, `/regulamin.html`, `POST /api/downloads`, `POST /api/feedback`, the 429; §2.2.8 `context` and `legacy` of the admin list; §4.1 kit 0.4.0, `js/terms.js`, without `js/diagnostics.js`; §4.2.0 the footer and the form; §5.1 NOGAT_CONFIG, journald, one process, `--no-access-log`; §5.2 nginx without `limit_req`, its logs without addresses, the pages through the API; §6 the limit in the API; §7.1 the logs and their 14 days
- 2.16 (2026-11-13): the providers' lines (ADR-083, plan `2026-11-13-provider-attribution`): §1.2 ADR-083; §2.1 `core/attribution.py`, `provider_lines` of `core/analysis_results.py`; §2.2.3 `derived_from`, `attribution` and `terms_notice` of the hydrograph and its hand-off; §2.2.5 and §2.2.5a the lines of the results' water; §4.1 `js/attribution.js`; §4.2.0 the lines in the panel, the own series and the exports, and the manifest's `attribution` and `terms_notice`
- 2.15 (2026-11-12): Nogat's GUI kit (ADR-082, plan `2026-11-12-nogat-kit`): §1.2 ADR-082; §2.1 `api/endpoints/gui.py` and `gui_table()` of `core/config.py`; §2.2.1a `GET /api/gui`; §4.1 `nogat/` (the kit and the marks), `js/nogat.js`, `js/handoff.js`, `tokens.css` of Nogat `7786271`; §4.2.0 the app menu „Aplikacje”; §5.1 `HYDROGRAF_GUI` in the environment of the API; §5.2 the versions of the imports of an ES module
- 2.14 (2026-11-11): §4 „Sieć zlewni” is an option of the mode „Wybierz zlewnię” (the author's decision, ADR-080 note): four modes on the mode bar, the radio group „Co wyznaczyć” over the map, the module map and the phone layout
- 2.13 (2026-11-11): every control point a node of the network (ADR-080 amended, plan `2026-11-11-network-nodes`): §2.1 `core/network_tree.py` draws the points to the nodes; §2.2.2b and §2.2.2c `outlet.id` required without the default `A`, `points` 0 to 30, `at_node` instead of `at_mouth`, `points[].node` and the junctions as nodes `J<n>` and `P<n>` numbered from the closing section upward, `junctions[].name`, the kinds `headwater` and `intermediate`, the outlet `O`, the new text of `network_points_coincide`; §2.4.10 the nodes and the ids of `core/network_tree.py`, the outlet `O` of `build_network_handoff`; §4 the mode „Sieć zlewni” without A, the markers labelled by their nodes' ids
- 2.12 (2026-11-11): the network preview (ADR-081, plan `2026-11-11-network-preview`): §2.1 `core/network_preview.py` and the second route of `api/endpoints/network.py`; §2.2.2c `POST /api/delineate-network/preview`; §2.2.2b the 422 is the route's, 404 and 503 the router's; §2.4.10 `core/network_preview.py`; §4 the mode „Sieć zlewni” in two stages, the preview after every change of the points and „Oblicz charakterystyki”
- 2.11 (2026-11-10): network delineation at control points (ADR-080, plan `2026-11-10-network-delineation`): §2.1 `api/endpoints/network.py` and `core/handoff.py` in the module map; §2.2.2b `POST /api/delineate-network` (request, response, errors, one network at a time per worker); §2.4.10 `core/network_tree.py`, `core/network_delineation.py` and `build_network_handoff` of `core/handoff.py`; §5.1 `GDAL_CACHEMAX: "64"` in the environment of the API
- 2.10 (2026-11-03): §2.2.1 and §7.3 — `/health` reports Hydrograf's version from `core/version.py` (it was a constant `1.0.0`), as does the admin dashboard
- 2.9 (2026-11-02): §2.2.8 — the admin endpoints address resources: `DELETE /api/admin/sewer` (was `DELETE /api/admin/sewer/delete`), `PUT /api/admin/sewer/config` (was `POST`), `PATCH /api/admin/feedback/{id}` with `{"is_read": bool}` (was `POST /api/admin/feedback/{id}/read`); the feedback endpoints are listed; CORS allows `PUT` and `PATCH`
- 2.8 (2026-11-02): fixes from the testers' feedback (`feature/store-ui`): §4.1 and §4.2 — wheel zoom without the tail of a gesture or late input, (i) explanations open on a click only, the flow accumulation threshold in ha/km², the rail Mapa · Instrukcja · Logowanie on every page, the service status only in `/admin`
- 2.7 (2026-11-02): merge of `feature/visual-identity` (its version 2.3 of 2026-11-01): GUI in the Nogat visual identity (ADR-065) — §4.1 new structure of `frontend/` (`tokens.css`, `chrome.css`, `app.css`, `shell.js`, `theme-init.js`, `theme-switch.js`, `welcome.js`, `img/hydrograf.svg`, `instrukcja/`; removed `glass.css`, `style.css`, `draggable.js`), §4.2 the Archiwista shell and basemaps (OpenFreeMap through MapLibre GL), charts in tokens, (i) explanations, AMC and your own rainfall series, advanced mode, analysis results (`hydrograf-results/1` with `water_level`), the MZP overlay; §2.2 `POST /api/delineate-watershed/preview`, `amc` and `custom_precipitation`, `GET /api/layers`, `result_ids` and `water_levels` of the terrain profile (`core/analysis_results.py`); §5.1 nginx on the loopback; §5.2 CSP hosts and the front-end asset cache (`?v=`, HTML `no-cache`); §7.1 request correlation and log rotation; ADR-065 in the table
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
