# SCOPE.md - Project Scope
## Hydrological Analysis System

**Version:** 1.3
**Date:** 2026-10-25
**Status:** Approved

---

## 1. Introduction

### 1.1 Purpose of the Document
This document defines precisely:
- ✅ What **IS** in the scope of the project (In Scope)
- ❌ What is **NOT** in the scope of the project (Out of Scope)
- ⏳ What **MAY BE** in the future (Future Scope)
- 🔒 Constraints and assumptions

### 1.2 Business Context
**Problem:** There is no internal tool for fast hydrological analyses of small watersheds.

**Solution:** A web system that uses open data (GIOŚ, GUGiK, PIG, IMGW, RZGW) to delineate watersheds and to compute their parameters and hydrographs.

**Users:** Spatial planning specialists in municipalities (without advanced GIS knowledge).

---

## 2. FUNCTIONAL SCOPE

### 2.1 ✅ IN SCOPE - MVP Features

#### 2.1.1 PHASE 1: Watershed Delineation

**✅ In scope:**
- An interactive web map with base layers: OSM, ESRI Satellite, OpenTopoMap, GUGiK WMTS (orthophoto + topographic)
- Point selection by clicking on the map (polygon drawing mode + object selection mode)
- Automatic detection of the nearest stream (snap-to-stream ST_Distance + fallback ST_Contains)
- Delineation of the watershed boundary with BFS on the in-memory graph (CatchmentGraph)
- Smoothing of the watershed boundaries: `ST_SimplifyPreserveTopology` + `ST_ChaikinSmoothing` (ADR-032)
- Raising buildings in the DEM (+5 m under the BUBD footprints of BDOT10k, ADR-033)
- Showing the boundary on the map (GeoJSON polygon)
- Export of the boundary as GeoJSON
- Export of the boundary as Shapefile
- Execution time: < 10 seconds
- Selection of a stream segment with upstream traversal (POST `/api/delineate-watershed` with the parameter `threshold_m2`, ADR-050)

**Technical requirements:**
- Input data: the DEM (NMT) from GUGiK (5 m resolution, downloaded through Kartograf)
- Preprocessing: pyflwdir (D8 flow direction) → vectorization → PostGIS + in-memory CatchmentGraph
- Algorithm: D8 flow direction + BFS upstream traversal on the CatchmentGraph
- Output: GeoJSON FeatureCollection

**Error messages:**
- "No stream found at this location"
- "Point outside the data area"

---

#### 2.1.2 PHASE 2: Physiographic Parameters of the Watershed

**✅ In scope:**

**Geometric parameters:**
- Watershed area [km²]
- Watershed perimeter [km]
- Watershed length [km]
- Watershed width [km]
- Length of the main stream [km]
- Hydraulic length of the watershed (hydraulic_length_km) [km]
- Actual length of the main channel (real_channel_length_km) [km]
- Flow paths: the longest one, from the watershed divide, from the centroid [km]
- Weighted imperviousness (weighted_imperviousness) [-]

**Geometric characteristics:**
- Form factor C<sub>f</sub>
- Compactness coefficient C<sub>z</sub>
- Circularity ratio C<sub>k</sub>
- Elongation ratio C<sub>w</sub>
- Lemniscate ratio C<sub>l</sub>

**Morphometric parameters:**
- Maximum elevation of the watershed [m a.s.l.]
- Mean elevation of the watershed [m]
- Minimum elevation of the watershed [m a.s.l.]
- Relief, the elevation difference [m]
- Watershed slope [%]
- Slope of the watershed divide [%]
- Slope of the main stream [%]
- Watershed form factor (Strahler)
- Drainage density
- Lake ratio
- Afforestation ratio
- Forest development ratio
- Swampiness ratio
- Swamp development ratio

**River network (for data from MPHP):**
- Horton classification of the river network
- Strahler classification of the river network
- Law of stream numbers
- Law of stream lengths
- Law of watershed areas
- Number of source nodes
- Total number of streams of the different orders
- Bifurcation ratio
- Total length of streams of the different orders
- Mean stream length ratio
- Mean watershed area ratio
- Stream frequency
- River network structure ratio
- Stream development coefficient
- River sinuosity coefficient
- River course development coefficient

**Land cover analysis:**
- Integration with the BDOT10k data from GUGiK (import into PostGIS, 8 categories)
- Distribution of the land cover categories [%] by Corine Land Cover
- Computation of the weighted Curve Number (CN) with the HSG (Hydrologic Soil Group) taken into account
- CN mapping for each category (following USDA NRCS)
- MVT thematic layer: `/api/tiles/landcover/{z}/{x}/{y}.pbf` coloured by category

**Terrain profile:**
- Longitudinal profiles of a stream (POST /api/terrain-profile)

**Terrain depressions:**
- Endpoint GET `/api/depressions` with filters (area, depth)
- Showing the depressions as an overlay on the map

**Vector tiles (MVT):**
- Streams: GET `/api/tiles/streams/{z}/{x}/{y}.pbf` (filter by the FA threshold, style by Strahler order)
- Sub-catchments: GET `/api/tiles/catchments/{z}/{x}/{y}.pbf`
- Land cover: GET `/api/tiles/landcover/{z}/{x}/{y}.pbf`
- Available thresholds: GET `/api/tiles/thresholds`

**DEM raster tiles:**
- XYZ pyramid (zoom 8-16) with a multi-directional hillshade (4 lighting directions)

**Presentation of the results:**
- Glassmorphism side panel (draggable, floating)
- A table of the parameters in the side panel
- Tooltips that explain the technical terms
- Values can be copied
- Export of the parameters as JSON/CSV

---

#### 2.1.3 PHASE 3: Generating Runoff Hydrographs

**✅ In scope:**

**Rainfall scenarios:**
- Source: the Pmax_PT atlas of IMGW (through the API) or measurement data
- Durations: 5min, 10min, 15min, 30min, 45min, 1h, 1.5h, 2h, 3h, 6h, 12h, 18h, 24h, 36h, 48h, 72h
- Probabilities: 0.01%, 0.02%, 0.03%, 0.05%, 0.1%, 0.2%, 0.3%, 0.5%, 1%, 2%, 3%, 5%, 10%, 20%, 30%, 40%, 50%, 60%, 70%, 80%, 90%, 95%, 98%, 98.5%, 99%, 99.5%, 99.9%
- In total: 432 combinations (16 × 27)
- The user chooses a scenario (radio buttons)
- Showing the precipitation value for the centroid of the watershed

**Time of concentration (tc):**
- Kirpich formula
- NRCS formula (SCS lag)
- Giandotti formula
- FAA formula (Federal Aviation Administration)
- Kerby formula
- Kerby-Kirpich formula (composite)

**Rainfall-runoff model:**
- Hyetograph: Beta distribution (α=2, β=5)
- Time step: 5 minutes
- SCS Curve Number method:
  - Maximum retention: S = 25400/CN - 254
  - Initial abstraction: Ia = 0.2 × S
  - Effective precipitation: Pe = (P - Ia)² / (P + 0.8S) when P > Ia

**Unit hydrograph:**
- SCS Dimensionless Unit Hydrograph method:
  - Time to peak: tp = 0.6 × tc
  - Peak flow: qp = 0.208 × A / tp
  - Base time: tb = 2.67 × tp
- Nash IUH method (Instantaneous Unit Hydrograph):
  - Parameter estimation: from_lutz, from_urban_regression
  - Estimation from_tc (deprecated)
- Snyder UH method:
  - Parameters: ct (lag coefficient), cp (peak coefficient)
- Hyetograph types: Beta, Block, Euler II

**Rainfall → runoff transformation:**
- Discrete convolution: Q(t) = Pe(t) ⊗ UH(t)
- Numerical implementation of the convolution

**Results:**
- Hydrograph chart (Chart.js line chart)
- Key parameters:
  - Qmax [m³/s] - peak flow
  - Time to peak [min]
  - Total runoff volume [m³]
  - Runoff coefficient [-]
- Export of the time series (CSV):
  - Columns: time [min], flow [m³/s]
- Export of the chart (PNG - optional)

**Model assumptions:**
- Precipitation is uniform over the whole watershed
- Moisture conditions: AMC-II (average)
- No channel routing (instant aggregation)
- The SCS-CN model for ungauged watersheds up to 250 km² (a limit of the method)

---

#### 2.1.4 Admin Panel (ADR-034)

**✅ In scope:**
- A `/admin` page with API key authentication (header X-Admin-Key)
- Dashboard: system status, record counts of 6 tables, disk usage
- Resource monitoring: CPU/RAM (psutil), DB pool, CatchmentGraph cache, database size
- Running the bootstrap pipeline from the panel + real-time logs (SSE)
- Data cleanup: tiles, overlays, dem_mosaic, TRUNCATE of tables
- 8 `/api/admin/*` API endpoints

---

#### 2.1.5 Pipeline Configuration (YAML)

**✅ In scope:**
- A `config.yaml` file that configures the pipeline (database, DEM, paths, steps, custom sources)
- The `--config` flag of `bootstrap.py`
- The `--waterbody-mode` flag (3 modes: auto, none, custom) that controls the handling of water bodies (ADR-031)
- A selector of the DEM resolution in the admin panel (5 m / 1 m)
- The `--waterbody-mode` flag is also available from the admin panel

---

#### 2.1.6 Storm-Sewer Integration (ADR-051)

**✅ In scope:**
- Import of the storm-sewer network from a file (SHP/GPKG/GeoJSON), WFS, a database or a URL
- Burning the inlets into the DEM (inlet burning) + reconstruction of the flow accumulation
- FA routing through the sewer network (SewerGraph + scipy sparse)
- Database tables: `sewer_nodes` (18 columns), `sewer_network` (16 columns), the flag `is_sewer_augmented`
- MVT vector tiles of the sewer network: `/api/tiles/sewer/{z}/{x}/{y}.pbf`
- A sewer overlay on the front-end map
- Admin: management of the sewer data (upload/status/delete) — 3 `/api/admin/sewer/*` endpoints
- A `sewer` section in the pipeline YAML configuration

---

### 2.2 ❌ OUT OF SCOPE - Outside the MVP

#### 2.2.1 Advanced Functions

**NOT in the MVP:**
- ❌ Flow routing in the river network (hydraulic modelling — note: the storm-sewer integration is in scope, ADR-051)
- ❌ Modelling the retention of reservoirs/ponds
- ❌ Flood simulation (inundation maps)
- ❌ Sediment transport modelling
- ❌ Water quality modelling
- ❌ Erosion and sedimentation analysis
- ❌ Long-term simulations (time series)
- ❌ Snowmelt modelling
- ❌ Detailed infiltration (Green-Ampt)
- ❌ Groundwater modelling

#### 2.2.2 Multi-Scenario Analysis

**NOT in the MVP:**
- ❌ Comparing several rainfall scenarios at once
- ❌ Sensitivity analysis of the parameters (Monte Carlo)
- ❌ Confidence intervals of the results
- ❌ "What-if" scenarios (a change of land use)
- ❌ Optimization of the model parameters (calibration)
- ❌ Validation against field measurements

#### 2.2.3 3D and Advanced Visualizations

**NOT in the MVP:**
- ❌ 3D terrain visualization
- ❌ Animation of the water flow
- ❌ Heat maps of the rainfall intensity
- ❌ Flood depth maps
- ❌ Cross sections

> **Note:** Longitudinal profiles of a stream (`POST /api/terrain-profile`) were originally in this section. They were implemented in session 11 and moved into the MVP scope (section 2.1.2).

#### 2.2.4 Integrations and Real-Time Data

**NOT in the MVP:**
- ❌ Integration with real-time IMGW data (precipitation, water levels)
- ❌ Weather forecast as an input
- ❌ Integration with GIS systems (QGIS, ArcGIS)
- ❌ Import of the user's own data (shapefiles, rasters)
- ❌ Connection to external databases
- ❌ A public API for other systems

#### 2.2.5 User Functions

**NOT in the MVP:**
- ❌ User accounts (registration, login)
- ❌ Saving analyses to a user profile
- ❌ Analysis history
- ❌ Multi-user collaboration (sharing, comments)
- ❌ Roles and permissions (admin, user, viewer) — note: a simple admin API key authentication is implemented (ADR-034), but it is not a full role system
- ❌ Email/SMS notifications about the end of an analysis

#### 2.2.6 Reports and Exports

**NOT in the MVP:**
- ❌ Generating any reports

#### 2.2.7 Alternative Interfaces

**NOT in the MVP:**
- ❌ Mobile application
- ❌ Desktop application
- ❌ CLI (command-line interface)

---

### 2.3 ⏳ FUTURE SCOPE - Planned for the Future

#### Post-MVP Roadmap

- 📊 Export of PDF reports (with a map, charts and parameters)
- 📈 Multi-scenario analysis (comparing Q1%, Q10%, Q50%)
- ~~🎨 Configurable maps (choice of the base layer)~~ — **DONE** (CP4: OSM, ESRI, OpenTopoMap, GUGiK WMTS)
- ~~🔗 Public API (REST, OpenAPI documentation)~~ — **PARTLY DONE** (OpenAPI/Swagger documentation is available at `/docs`)
- ~~🔬 Nash IUH / Snyder UH~~ — **DONE** (CP5: 3 UH models with a selector)
- ~~🗺️ BDOT stream matching~~ — **DONE** (ADR-044: matching the DEM streams to BDOT10k)
- ~~📐 Flow paths (longest/divide/centroid)~~ — **DONE** (CP5: flow paths in the parameters)
- ~~✨ Chaikin smoothing of boundaries~~ — **DONE** (ADR-032: ST_ChaikinSmoothing)
- ~~🏛️ WFS TERYT~~ — **DONE** (CP5: integration with the TERYT register)
- ~~🔍 DEM auto-discovery~~ — **DONE** (CP5: automatic detection of the DEM sheets)
- 🧪 Calibration module (comparison with measurements)
- 🎯 Parameter optimization
- 🔄 Double DEM analysis (with and without endorheic areas) — backlog

---

## 3. DATA SCOPE

### 3.1 ✅ Input Data - In Scope

#### 3.1.1 Digital Elevation Model (DEM, Polish NMT)

**Source:** GUGiK through Kartograf v0.7.0 (`download_sheets` + `MetadataCache`, automatic download of the DEM sheets)
**Format:** ARC/INFO ASCII GRID → VRT mosaic
**Resolution:** 5 m (configured in Kartograf `GugikProvider(resolution="5m")`)
**Coordinate system:** EPSG:2180 (PL-1992)
**Spatial extent:** A bbox defined at setup (e.g. `16.9279,52.3729,17.3825,52.5870`)
**Update:** Once, at the setup of the system (or on request after the DEM is updated)

**Preprocessing (pyflwdir):**
- Raising buildings in the DEM (+5 m under BUBD of BDOT10k, ADR-033)
- Classification of water bodies (waterbody-mode: auto/none/custom, ADR-031)
- Filling depressions (sink filling)
- Computing flow directions (D8)
- Computing flow accumulation
- Computing the slope
- Vectorization of the streams (FA thresholds: 1000, 10000, 100000 m²) → PostGIS `stream_network`
- Vectorization of the sub-catchments → PostGIS `stream_catchments`
- Building the in-memory graph (CatchmentGraph, ~44k nodes, ~0.5 MB)
- Generating overlays: DEM hillshade (PNG + XYZ pyramid), streams overlay
- Generating MVT tiles (tippecanoe)

#### 3.1.2 Land Cover

**Sources:** GUGiK - BDOT10k (through Kartograf v0.7.0, automatic download by district, Polish *powiat*)
**Format:** GeoPackage
**Coordinate system:** EPSG:2180
**Extent:** The districts that cover the bbox
**Update:** Once a quarter (or on request)

**Categories (8):**
- Surface waters
- Lawns, parks
- Roads and car parks
- Industrial/service buildings
- Residential buildings
- Arable land
- Meadows and pastures
- Forests

**Preprocessing:**
- Import into PostGIS (table `land_cover`, ~112k objects)
- Mapping of the BDOT10k classes to the CN categories (`cn_tables.py`)
- Assigning a CN value to each category with the HSG taken into account
- Serving as MVT (`/api/tiles/landcover/`)

#### 3.1.3 Stream Network

**Source:** Generated automatically from the DEM (flow accumulation thresholds: 1000, 10000, 100000 m²)
**Format:** PostGIS (table `stream_network`)
**Attributes:**
- Strahler order
- Length [m]
- Upstream area [km²]
- Segment index (1-based per threshold)
- Threshold [m²]

**Matching to BDOT10k (ADR-044):**
- Matching the DEM streams to the BDOT10k reference streams
- Table `bdot_streams` — the reference streams from BDOT10k
- Naming the streams on the basis of the geometric match

**Preprocessing:**
- Vectorization of the streams from the flow accumulation raster (pyflwdir)
- Splitting into segments at confluences and at changes of the Strahler order
- Geometry simplification (`simplify_tol = 2*cellsize`)
- Import into PostGIS with spatial indexes
- Serving as MVT (`/api/tiles/streams/`)

#### 3.1.4 Precipitation Data

**Source:** IMGW - the Pmax_PT atlas through IMGWTools v2.1.0
**Format:** Points of meteorological stations
**Spatial extent:** Stations within the bbox (~192 stations)
**Parameters:**
- Duration: 15min, 30min, 1h, 2h, 6h, 12h, 24h
- Probability: 1%, 2%, 5%, 10%, 20%, 50%
- Value: precipitation [mm]

**Preprocessing:**
- Downloading all combinations (42 data sets × ~192 stations = ~8064 records)
- Import into PostGIS (table `precipitation_data`)
- Spatial indexing (GIST)
- Interpolation for the watershed centroid at runtime

**Update:** Once a year (or when IMGW publishes new data)

#### 3.1.5 Soil Data (HSG)

**Source:** PIG (the Polish Geological Institute) through Kartograf v0.7.0
**Format:** GeoPackage → raster → PostGIS (table `soil_hsg`)
**Attributes:** Hydrologic Soil Group (A/B/C/D)
**Preprocessing:**
- Rasterization onto the DEM grid
- Nearest-neighbour fill of the missing pixels (distance_transform_edt)
- Polygonization → import into PostGIS (~197 polygons)

---

### 3.2 ❌ Data Outside the MVP

**NOT in the MVP:**
- ❌ Measurement data from gauging stations
- ❌ Weather forecasts
- ❌ Data on retention reservoirs
- ❌ Data on the capacity of bridges/culverts
- ~~❌ Geological data (soil permeability)~~ — **DONE** (HSG from PIG, section 3.1.5)
- ❌ Data on historical land use (changes in time)
- ❌ Satellite data (Sentinel, Landsat)
- ❌ LiDAR (point clouds)
- ❌ Cadastral data
- ❌ High-resolution orthophotos

---

### 3.3 Output Data Formats

**✅ In scope:**
- GeoJSON (watershed boundary, main stream)
- Shapefile (watershed boundary)
- CSV (watershed parameters, hydrograph)
- JSON (the full API response)

**❌ Out of scope:**
- GeoPackage
- KML/KMZ
- DWG/DXF
- GeoTIFF (result rasters)
- NetCDF
- HDF5

---

## 4. GEOGRAPHIC SCOPE

### 4.1 ✅ Area Covered by the System

**Spatial extent:**
- **Base area:** Chosen by the user during the setup
- **Area size:** typically 50-200 km²
- **Buffer:** +1 km beyond the municipal boundary

**Limits:**
- **Minimum area:** 2 cells of the DEM raster

**Coordinate systems:**
- **Internal:** EPSG:2180 (PL-1992)
- **Frontend (map):** EPSG:4326 (WGS84) - automatic transformation
- **API input/output:** WGS84 (lat/lon)

---

### 4.2 ❌ Areas Outside the Scope

**NOT in the MVP:**
- ❌ Areas outside Poland
- ❌ Adding new areas dynamically by the user
- ~~❌ Mountain areas > 1500 m a.s.l. (limits of the SCS model)~~

---

## 5. TECHNICAL SCOPE

### 5.1 ✅ Technologies and Tools

#### Backend
**Language:** Python 3.12+
**Framework:** FastAPI
**Database:** PostgreSQL 16+ with PostGIS 3.4+
**Libraries:**
- GeoPandas, Shapely (spatial operations)
- Rasterio, GDAL (raster preprocessing)
- NumPy, SciPy (numerical computation)
- pyflwdir (hydrological analysis — D8, flow accumulation)
- Pydantic (data validation)
- SQLAlchemy (ORM)
- structlog (structured logging)
- psutil (resource monitoring — admin panel)
- Alembic (database migrations)
**Own libraries:**
- Hydrolog v0.6.3 (hydrological calculations)
- Kartograf v0.7.0 (downloading the DEM, land cover, HSG, BDOT10k)
- IMGWTools v2.1.0 (design precipitation from IMGW)

#### Frontend
**Languages:** HTML5, CSS3, JavaScript (ES6+) — Vanilla JS, no framework
**Map:** Leaflet.js 1.9.4
**Charts:** Chart.js 4.4.7
**UI framework:** Bootstrap 5.3.3 (CDN)
**Style:** Glassmorphism (CSS variables in `glass.css`), floating draggable panel
**Modules:** 10 JS modules (IIFE on `window.Hydrograf`): api, map, draggable, charts, layers, profile, hydrograph, depressions, app + 3 admin modules
**Map base layers:** OpenStreetMap, ESRI Satellite, OpenTopoMap, GUGiK WMTS (orthophoto + topographic)
**Pages:** `index.html` (main), `admin.html` (admin panel)

#### Infrastructure
**Containerization:** Docker + Docker Compose (3 containers: db, api, nginx)
**Reverse proxy:** Nginx (alpine)
**Server:** Own
**CI/CD:** GitHub Actions (or GitLab CI)
**Monitoring:** The admin panel `/admin` (CPU/RAM, DB pool, uptime) + the health check `/health`

---

### 5.2 ❌ Technologies Outside the Scope

**NOT in the MVP:**
- ❌ Kubernetes / orchestration
- ❌ Cloud hosting (AWS, Azure, GCP)
- ❌ Message queue (RabbitMQ, Kafka)
- ❌ Caching layer (Redis, Memcached)
- ❌ Load balancer
- ❌ CDN
- ❌ Elasticsearch (search)
- ❌ Microservices architecture
- ❌ GraphQL
- ❌ WebSockets (real-time updates) — note: SSE (Server-Sent Events) is used in the admin panel to stream the bootstrap logs
- ❌ Server-Side Rendering (SSR)
- ❌ Progressive Web App (PWA)

---

## 6. PERFORMANCE SCOPE

### 6.1 ✅ Guaranteed SLA (Service Level Agreement)

**API response time:**
- Watershed delineation: **< 10 seconds** (95th percentile)
- Physiographic parameters: **< 2 seconds**
- Hydrograph generation: **< 5 seconds**
- Map loading: **< 2 seconds**

**Throughput:**
- Concurrent users: **10** (MVP)
- Requests per minute: **50**

**Availability:**
- Uptime: **99%** (allowed downtime: ~7h/month)
- Planned maintenance: max 2h/week (at night)

**Data limits:**
- API timeout: **30 seconds**

---

### 6.2 ❌ Not Guaranteed

**NOT guaranteed in the MVP:**
- ❌ Support for > 10 concurrent users
- ❌ Response time < 1s for all operations
- ❌ 99.9% uptime (three nines)
- ❌ Horizontal scaling
- ❌ Disaster recovery < 1h
- ❌ Real-time backups (daily only)

---

## 7. CONSTRAINTS AND ASSUMPTIONS

### 7.1 Technical Constraints

**Preprocessing:**
- ⚠️ **One-off DEM preprocessing:** ~45 minutes (the bootstrap pipeline, measured on a bbox of ~400 km²)
- ⚠️ **Needs a server:** at least 8 GB RAM, 100 GB of disk
- ⚠️ **Can be started from the admin panel** (`/admin` → Bootstrap) or from the CLI (`bootstrap.py`)

**Hydrological model:**
- ⚠️ **SCS CN model:** For watersheds < 250 km²
- ⚠️ **Uniform precipitation:** A simplification for small watersheds
- ⚠️ **No routing:** The hydrograph is for the closing cross-section
- ⚠️ **AMC-II conditions:** Average moisture conditions

**Data:**
- ⚠️ **DEM quality:** Depends on GUGiK (artefacts are possible)
- ⚠️ **Currency of the data:** The land cover may be out of date

---

### 7.2 Business Assumptions

**Users:**
- ✓ Have a computer with a browser (Chrome, Firefox, Edge)
- ✓ Screen resolution: at least 1280 × 720 px
- ✓ Basic knowledge of maps and GIS
- ✓ Understand hydrological terms (or are willing to learn)

**Environment:**
- ✓ Internal network (LAN) - no access from the internet (MVP)
- ✓ Stable network connection (10 Mbps)
- ✓ The server runs 24/7 (except maintenance)

**Support:**
- ✓ User documentation in Polish

---

### 7.3 Legal and Licensing Assumptions

**Data:**
- ✓ GUGiK data: open licence (non-commercial use is fine)
- ✓ IMGW data: to be verified (API terms of service)
- ✓ OpenStreetMap: ODbL licence (attribution required)

**Code:**
- ✓ Source code: Proprietary (owned by the organization)
- ✓ Open-source libraries: Compliance with the licences (MIT, BSD, Apache)

**Responsibility:**
- ⚠️ The system is a tool that supports decisions
- ⚠️ The user is responsible for the interpretation of the results
- ⚠️ No guarantee of 100% accuracy (it depends on the input data)

---

## 8. SUCCESS CRITERIA

### 8.1 Definition of "Done" for the MVP

**Functionally:**
- ✅ All user stories (MUST HAVE) of PRD.md are implemented
- ✅ The system delineates a watershed for 95%+ of the clicks on streams
- ✅ It generates a hydrograph for all 432 scenarios

**Quality:**
- ✅ Unit tests: > 80% coverage
- ✅ E2E tests: 100% of the critical paths pass
- ✅ Code review: all PRs approved
- ✅ Documentation: complete (user + technical docs)

**Performance:**
- ✅ 95% of the requests are within the time targets (10s, 5s, 2s)
- ✅ The system is stable for 10 concurrent users
- ✅ No critical bugs in production for 1 week

**Acceptance:**
- ✅ 3 test users accepted the system (UAT)
- ✅ The Product Owner accepted the MVP

---

### 8.2 Post-Launch Success Metrics

**Satisfaction:**
- 🎯 < 5 critical bug reports/month

**Performance:**
- 🎯 Mean response time < 5s
- 🎯 No timeouts in more than 1% of the requests

---

## 9. DEPENDENCIES

### 9.1 External Dependencies

**Data:**
- 🔗 **GUGiK Geoportal:** Availability of the DEM and BDOT10k data
- 🔗 **IMGW:** A working API or the availability of historical data
- 🔗 **OpenStreetMap:** The map base layer

**Infrastructure:**
- 🔗 **Physical server:** Availability and operation
- 🔗 **Internet connection:** For access to the APIs and maps

**Team:**
- 🔗 **Backend developer:** Full-time availability
- 🔗 **Frontend developer:** Full-time availability
- 🔗 **GIS specialist:** Part-time availability for the preprocessing

---

### 9.2 Internal Dependencies (Between Phases)

```
PHASE 0: Preprocessing
   ↓ (data in PostGIS)
PHASE 1: Watershed delineation
   ↓ (boundary GeoJSON)
PHASE 2: Physiographic parameters
   ↓ (CN, tc)
PHASE 3: Hydrograph generation
```

**Blockers:**
- ⚠️ Phase 1 needs Phase 0 (preprocessing) to be finished
- ⚠️ Phase 2 needs a working Phase 1 (watershed boundary)
- ⚠️ Phase 3 needs Phase 2 (CN, morphometric parameters)

---

## 10. RISKS & MITIGATION

### 10.1 High Risk

**Risk 1: IMGW unavailable**
- **Probability:** Low
- **Impact:** High (no data = no hydrographs)
- **Mitigation:**
  - Plan A: Download once and store locally
  - Plan B: Values from the literature (typical values for the region)

**Risk 2: DEM data quality**
- **Probability:** Medium
- **Impact:** High (wrong watershed boundaries)
- **Mitigation:**
  - Visual validation after the preprocessing
  - Comparison with reference data (topographic map, orthophoto)
  - Documenting the limitations for the user
  - Manual correction (future scope)

---

### 10.2 Medium Risk

**Risk 3: Performance for large watersheds**
- **Probability:** High
- **Impact:** Medium (time > 10s for watersheds > 200 km²)
- **Mitigation:**
  - Optimization of the algorithms (early termination)
  - Database indexes
- **Note:** For watersheds > 250 km² the SCS-CN hydrograph is not available (a limit of the method)

**Risk 4: Users lack experience**
- **Probability:** Medium
- **Impact:** Medium (incorrect use of the system)
- **Mitigation:**
  - An intuitive interface (user testing)
  - Tooltips and help text
  - User documentation with examples
  - Webinars/training after the deployment

---

### 10.3 Low Risk

**Risk 5: Server failure**
- **Probability:** Low
- **Impact:** High (downtime)
- **Mitigation:**
  - Daily backups
  - Monitoring (Prometheus + alerting)
  - Recovery procedure (< 4h)
  - A plan to migrate to a VPS (if the current server fails)

---

## 11. ACCEPTANCE CRITERIA - MVP Acceptance Criteria

### 11.1 Functional (Must Pass)

- ✅ **F1:** The user can click a point on the map and see the watershed boundary in < 10s
- ✅ **F2:** The system shows the physiographic parameters of the watershed
- ✅ **F3:** The user can choose one of the 432 rainfall scenarios
- ✅ **F4:** The system generates a hydrograph in < 5s and shows the chart
- ✅ **F5:** The user can export the boundary as GeoJSON/Shapefile
- ✅ **F6:** The user can export the hydrograph as CSV
- ✅ **F7:** The system shows error messages for the edge cases (no stream or outside the area)

### 11.2 Non-Functional (Must Pass)

- ✅ **NF1:** The system works in Chrome, Firefox, Edge (latest versions)
- ✅ **NF2:** UI responsiveness < 100ms for interactions
- ✅ **NF3:** Test coverage > 80%
- ✅ **NF4:** The user documentation is complete (setup, usage, troubleshooting)
- ✅ **NF5:** The technical documentation is complete (architecture, API, deployment)
- ✅ **NF6:** No SQL injection vulnerabilities (security audit)
- ✅ **NF7:** Uptime > 99% in the first production week

### 11.3 User Acceptance Testing (UAT)

**Test scenarios:**
1. A new user can do a complete analysis (watershed → hydrograph) without help in < 5 minutes
2. The user can export the results and use them in another tool (QGIS)
3. The error messages are understandable and helpful

**Acceptance:**
- At least 3 test users must accept the system (rating ≥ 4/5)
- The Product Owner must accept all the functions
- Zero critical bugs in the UAT

---

## 12. HANDOFF CRITERIA

### 12.1 To Production

**Code:**
- ✅ All PRs merged into `main`
- ✅ Version tags (semantic versioning): `v1.0.0`
- ✅ CHANGELOG.md updated

**Deployment:**
- ✅ Docker images built and tested
- ✅ docker-compose.yml ready for production
- ✅ Environment variables (.env) configured
- ✅ Nginx as a reverse proxy
- ✅ HTTPS configured (Certbot)

**Database:**
- ✅ Preprocessing finished
- ✅ Backup strategy configured (cron job)
- ✅ Database migrations applied

**Monitoring:**
- ✅ Application logs work
- ✅ Health check endpoint: `/health`
- ✅ Prometheus metrics exposed (optional)

**Documentation:**
- ✅ README.md with deployment instructions
- ✅ User manual (PL) available
- ✅ API documentation (Swagger/OpenAPI)
- ✅ Runbook for operations (restart, backup, restore)

---

### 12.2 To Maintenance

**Handoff to the maintenance team:**
- 📋 A list of the known limitations and workarounds
- 📋 Contacts of the developers (email, Slack)

**Monitoring and alerts:**
- 🔔 Alert: Downtime > 5 minutes
- 🔔 Alert: Response time > 30s
- 🔔 Alert: Disk usage > 80%
- 🔔 Alert: Database connection failures

---

## 13. OUT OF SCOPE - Summary

### What Is Definitely NOT in the MVP:

**Functions:**
- ❌ Routing, retention modelling, flood maps
- ❌ Multi-scenario analysis, calibration
- ❌ 3D visualizations, animations
- ❌ Real-time integrations, a public API

**Users:**
- ❌ Accounts, history, collaboration
- ❌ Roles and permissions
- ❌ Notifications, newsletters

**Data:**
- ❌ Field measurements, forecasts, satellite data
- ❌ Multiple regions, import of own data

**Technology:**
- ❌ Cloud hosting, Kubernetes, microservices
- ❌ Mobile applications, CLI, GraphQL

**Reports:**
- ❌ PDF generation, templates, batch export

---

## 14. CHANGE MANAGEMENT

### 14.1 How to Change the Scope?

**Process:**
1. **Proposal:** An issue on GitHub/GitLab with the tag `scope-change`
2. **Analysis:** Impact assessment (time, resources, risk)
3. **Discussion:** The team + the Product Owner
4. **Decision:** Go/No-Go
5. **Documentation:** Update SCOPE.md + PRD.md + CHANGELOG.md

**Acceptance criteria of a change:**
- ✅ Business justification
- ✅ Estimate of the effort (story points)
- ✅ No conflict with the existing scope
- ✅ Acceptance by the Product Owner
- ✅ Available resources (time, people)

---

### 14.2 Scope Creep Prevention

**Rules:**
- 🛑 **No new functions without documentation in SCOPE.md**
- 🛑 **Not "just a quick addition of X"** - always through the change management process
- 🛑 **MVP = Minimum Viable Product** - resist the temptation of "nice to have"
- ✅ **Feature requests → backlog** (not the MVP)
- ✅ **Re-prioritization every 2 weeks** (sprint planning)

---

## 15. GLOSSARY

| Term | Definition |
|------|------------|
| **MVP** | Minimum Viable Product - a basic version with the key functions |
| **In Scope** | A function/element covered by the scope of the project |
| **Out of Scope** | A function/element outside the scope of the project |
| **Future Scope** | A function planned for the future (post-MVP) |
| **SLA** | Service Level Agreement - a guaranteed level of service |
| **UAT** | User Acceptance Testing |
| **NMT** | Numeryczny Model Terenu - the digital elevation model (DEM) |
| **CN** | Curve Number - a parameter of the surface runoff |
| **SCS** | Soil Conservation Service - a hydrological method |
| **Pmax_PT** | Maximum precipitation of a given probability and duration |
| **HSG** | Hydrologic Soil Group - the hydrologic group of a soil (A/B/C/D) |
| **MVT** | Mapbox Vector Tiles - a format of vector tiles |
| **BFS** | Breadth-First Search - a graph search that goes level by level |
| **SSE** | Server-Sent Events - a protocol that streams data from the server |
| **ADR** | Architecture Decision Record |

---

**Document version:** 1.3
**Date of the last update:** 2026-10-25
**Current version:** v0.4.0 (CP4 finished, 899 tests, 19 endpoints, 49 ADRs)
**Planned MVP version:** v1.0.0 (CP5)
**Status:** Approved — the project is in active development

**Change history:**
- 1.3 (2026-10-25): translated to English (DEV-2.1); the content is unchanged
- 1.2 (2026-03-25): last content update

---

*This document defines the scope of the MVP project. Every change requires a formal change management process and an update of this document.*
