# Product Requirements Document (PRD)
## Hydrological Analysis System

**Version:** 1.2
**Date:** 2026-10-25
**Status:** Approved
**Author:** Project team

---

## 1. Executive Summary

### 1.1 Product Goal
Build an internal web tool for fast delineation of watershed boundaries, physiographic parameters and runoff hydrographs. The system is meant as an alternative to commercial software and uses open data of GUGiK and IMGW. Note: hydrograph generation with the SCS-CN method is limited to watersheds ≤ 250 km² (a limit of the method).

### 1.2 Business Problem
Professional tools for hydrological analysis are currently:
- Expensive to license
- Dependent on advanced GIS knowledge
- Based on data that is not always available locally
- Unable to give full control over the data and the algorithms

### 1.3 Target Group
**Primary users:**
- Spatial planning specialists
- Municipal office staff
- Environmental consultants

**User characteristics:**
- They do not necessarily have GIS skills
- They need fast results for planning decisions

### 1.4 Key Success Metrics
- Time to delineate a watershed and a hydrograph: **< 30 seconds**
- Accuracy of watershed boundaries: **95%+ agreement with reference methods**
- System availability: **99% uptime**
- User satisfaction: **> 4/5** in surveys

---

## 2. Product Scope

### 2.1 What IS in scope (MVP)

**PHASE 1: Watershed delineation**
- Selecting a point on an interactive map
- Automatic delineation of the watershed boundary
- Showing the result as GeoJSON

**PHASE 2: Physiographic parameters**
- Area and perimeter of the watershed
- Length of the main stream
- Mean slopes (terrain and stream)
- Morphometric coefficients
- Land cover distribution
- Curve Number (CN)

**PHASE 3: Runoff hydrograph**
- Choosing a rainfall scenario (duration × probability)
- IMGW data
- Beta-distribution hyetograph
- SCS Curve Number model
- SCS unit hydrograph
- Hydrograph chart
- Parameters: Qmax, time to peak, volume

### 2.2 What is NOT in scope (MVP)

**Outside the MVP:**
- Routing (determining flow routes)
- Simulating several climate scenarios at once
- Flood risk analysis (inundation maps)
- 3D terrain visualization
- Integration with real-time measurement data
- Mobile application
- Real-time multi-user collaboration
- PDF report export (possible in the future)

### 2.3 Data Sources

**Spatial data:**
- DEM (digital elevation model, Polish NMT)
- Land cover: BDOT10k from GUGiK, or CLC
- Stream centrelines: MPHP (the Hydrographic Division Map of Poland) or own vector data

**Precipitation data:**
- IMGW pmaxpt or historical data
- All combinations:
  - Durations: 15min, 30min, 1h, 2h, 6h, 12h, 24h
  - Probabilities: 1%, 2%, 5%, 10%, 20%, 50%

**Assumptions:**
- Precipitation is uniform over the whole watershed
- Data is updated once a year

---

## 3. Functional Requirements - User Stories

### US-01: Delineating a watershed
**As a** spatial planning specialist  
**I want** to choose a point on the map and get the watershed boundary  
**So that** I can quickly determine the area of influence of a planned investment

**Acceptance criteria:**
- The user clicks a point on the map
- The system finds the nearest stream
- The system delineates the watershed in < 10 seconds
- The watershed boundary is shown on the map
- The boundary can be exported as GeoJSON/Shapefile

**Priority:** MUST HAVE  
**Story Points:** 8

---

### US-02: Showing the watershed parameters
**As a** user  
**I want** to see the key parameters of the delineated watershed  
**So that** I can assess its hydrological characteristics

**Acceptance criteria:**
- Showing the area [km²]
- Showing the length of the main stream [km]
- Showing the mean slope [%]
- Showing the land cover distribution [%]
- Showing the CN
- All parameters in a clear table

**Priority:** MUST HAVE  
**Story Points:** 5

---

### US-03: Choosing a rainfall scenario
**As a** user  
**I want** to choose the duration and the probability of the rainfall  
**So that** I can generate a hydrograph for a specific scenario

**Acceptance criteria:**
- A list of the available durations (7 options)
- A list of the available probabilities (6 options)
- Showing the precipitation value for the chosen scenario
- A "Calculate hydrograph" button

**Priority:** MUST HAVE  
**Story Points:** 3

---

### US-04: Generating a hydrograph
**As a** user  
**I want** to generate a runoff hydrograph  
**So that** I can determine the peak flows for the chosen scenario

**Acceptance criteria:**
- The hydrograph is generated in < 5 seconds
- A line chart (time vs. flow)
- Showing the key parameters:
  - Qmax [m³/s]
  - Time to peak [min]
  - Runoff volume [m³]
- The data can be exported as CSV

**Priority:** MUST HAVE  
**Story Points:** 8

---

### US-05: Exporting the results
**As a** user  
**I want** to export the results of the analysis  
**So that** I can use them in other tools or in documentation

**Acceptance criteria:**
- Export of the watershed boundary (GeoJSON/Shapefile)
- Export of the hydrograph (CSV: time, flow)
- Export of the parameters (JSON or CSV)
- Export buttons in the interface

**Priority:** SHOULD HAVE  
**Story Points:** 3

---

### US-06: Error messages
**As a** user  
**I want** to get clear error messages  
**So that** I understand what went wrong

**Acceptance criteria:**
- "Cannot find a stream at this location"
- "Error connecting to the server - try again"
- Messages are shown as a modal or a toast

**Priority:** MUST HAVE  
**Story Points:** 2

---

## 4. Non-Functional Requirements

### NFR-01: Performance
- Watershed delineation: **< 10 seconds**
- Hydrograph generation: **< 5 seconds**
- Map loading: **< 2 seconds**
- UI responsiveness: **< 100ms** for user interactions

### NFR-02: Scalability
- Support for **10 concurrent users** (MVP)
- Possible scaling to **50+ users** in the future
- An architecture that allows adding compute servers

### NFR-03: Availability
- **99% uptime** (allowed downtime: ~7h/month)
- Automatic restarts after a failure
- Database backups: daily

### NFR-04: Security
- Access to the system: **internal network only** (MVP)
- HTTPS for all connections
- Validation of all input data
- No storage of users' personal data

### NFR-05: Usability
- An intuitive interface, **no training required** for the basic functions
- Available on desktop (Chrome, Firefox, Safari, Edge)
- Responsive for screens ≥ 1280px wide
- Language: **Polish**

### NFR-06: Maintainability
- Code that follows PEP 8 (Python)
- API documentation (OpenAPI/Swagger)
- User documentation (Markdown)
- Unit tests: **> 80% coverage**

---

## 5. User Interface (UI/UX)

### 5.1 Wireframe - Main Screen

The labels in the wireframe are the texts of the Polish interface (DEV-2.2): PARAMETRY
ZLEWNI = watershed parameters, POKRYCIE TERENU = land cover, SCENARIUSZ OPADOWY =
rainfall scenario, OBLICZ HYDROGRAM = calculate hydrograph, HYDROGRAM ODPŁYWU = runoff
hydrograph, Eksport = export.

```
┌─────────────────────────────────────────────────────────────┐
│  🏞️ SYSTEM ANALIZY HYDROLOGICZNEJ                [? Pomoc]  │
├─────────────────────────────────┬───────────────────────────┤
│                                 │  PARAMETRY ZLEWNI         │
│         MAPA                    │  ─────────────────────    │
│  ┌───────────────────────────┐  │  Powierzchnia: 45.3 km²   │
│  │                           │  │  Obwód: 38.5 km           │
│  │   🗺️                      │  │  Dł. cieku: 8.2 km        │
│  │                           │  │  Spadek: 2.3%             │
│  │   📍← kliknij tu          │  │  CN: 72                   │
│  │                           │  │                           │
│  │                           │  │  POKRYCIE TERENU          │
│  │   [Granica zlewni         │  │  ─────────────────────    │
│  │    wyświetlona]           │  │  🌲 Las: 35%              │
│  │                           │  │  🌾 Pola: 42%             │
│  │                           │  │  🏡 Zabudowa: 5%          │
│  └───────────────────────────┘  │  🌿 Łąki: 18%             │
│                                 │                           │
│  Legenda:                       │  SCENARIUSZ OPADOWY       │
│  🔵 Cieki  🟢 Zlewnia          │  ─────────────────────    │
│                                 │  Czas trwania:            │
│                                 │  ○ 15min  ○ 30min         │
│                                 │  ● 1h     ○ 2h            │
│                                 │  ○ 6h     ○ 24h           │
│                                 │                           │
│                                 │  Prawdopodobieństwo:      │
│                                 │  ○ 1%   ○ 2%   ● 10%      │
│                                 │  ○ 20%  ○ 50%             │
│                                 │                           │
│                                 │  Opad: 38.5 mm            │
│                                 │                           │
│                                 │  [ OBLICZ HYDROGRAM ]     │
├─────────────────────────────────┴───────────────────────────┤
│  HYDROGRAM ODPŁYWU                                          │
│  ──────────────────────────────────────────────────────────│
│                                                             │
│   Qmax = 42.3 m³/s  │  Czas do szczytu = 75 min            │
│                                                             │
│   Q [m³/s]                                                  │
│   50 │                                                      │
│      │           ╱╲                                         │
│   40 │          ╱  ╲                                        │
│      │         ╱    ╲                                       │
│   30 │        ╱      ╲                                      │
│      │       ╱        ╲                                     │
│   20 │      ╱          ╲                                    │
│      │     ╱            ╲___                                │
│   10 │    ╱                                                 │
│      │___╱                                                  │
│    0 └──────────────────────────────────> t [min]          │
│       0    60   120   180   240   300                      │
│                                                             │
│   [📥 Eksport CSV]  [📥 Eksport GeoJSON]                   │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 Color Palette

**Main:**
- Background: `#FFFFFF` (white)
- Side panel: `#F8F9FA` (light grey)
- Primary button: `#007BFF` (blue)
- Button hover: `#0056B3` (dark blue)

**Map:**
- Streams: `#0066CC` (blue)
- Watershed boundary: `#28A745` with opacity 0.3 (green)
- Main stream: `#DC3545` (red)

**Chart:**
- Hydrograph line: `#007BFF` (blue)
- Grid: `#E0E0E0` (light grey)
- Qmax marker: `#DC3545` (red)

### 5.3 Typography

- **Headings:** Roboto Bold, 18-24px
- **Text:** Roboto Regular, 14-16px
- **Labels:** Roboto Medium, 12-14px
- **Numeric data:** Roboto Mono, 14px

---

## 6. User Flow

Interface texts are quoted in English; the Polish text of each message is in the
interface (DEV-2.2).

### 6.1 Main Flow - Generating a Hydrograph

```
START
  │
  ├─> [1] The user opens the application
  │        ↓
  │   [2] The map loads with an OSM base layer
  │        ↓
  │   [3] The user clicks a point on the map
  │        ↓
  │   [4] The system delineates the watershed (loader: "Delineating the watershed...")
  │        ↓
  │   [5] The boundary is shown on the map
  │        ↓
  │   [6] The watershed parameters are shown in the side panel
  │        │
  │        ├─> Area: 45.3 km²
  │        ├─> CN: 72
  │        ├─> Stream length: 8.2 km
  │        └─> Land cover distribution: forest 35%, fields 42%, ...
  │        ↓
  │   [7] The user chooses a rainfall scenario
  │        │
  │        ├─> Duration: [○15min ○30min ●1h ○2h ○6h ○24h]
  │        └─> Probability: [○1% ○2% ●10% ○20% ○50%]
  │        ↓
  │   [8] The system shows the precipitation value: "P = 38.5 mm"
  │        ↓
  │   [9] The user clicks "CALCULATE HYDROGRAPH"
  │        ↓
  │   [10] The system generates the hydrograph (loader: "Calculating...")
  │        ↓
  │   [11] The hydrograph chart is shown
  │        │
  │        ├─> Qmax = 42.3 m³/s
  │        ├─> Time to peak = 75 min
  │        └─> Volume = 156,780 m³
  │        ↓
  │   [12] The user can:
  │        │
  │        ├─> Change the scenario and recalculate
  │        ├─> Export the results (CSV/GeoJSON)
  │        └─> Choose a new point on the map
  │
END
```

### 6.2 Alternative Flow - Errors

```
[3] The user clicks a point
     ↓
[4a] The point is not on a stream
     ↓
     Message: "No stream was found at this location.
               Choose a point on the blue line."
     ↓
     Back to [3]

---

[4b] Watershed > 250 km²
     ↓
     The watershed is delineated correctly, but:
     - Warning message: "The watershed exceeds 250 km².
       The hydrograph calculation with the SCS-CN method is not available."
     - The "CALCULATE HYDROGRAPH" button is disabled
     - Watershed delineation and the physiographic parameters work as usual
     ↓
     The user can export the watershed boundary and the parameters

---

[10a] Server error
      ↓
      Message: "The hydrograph could not be calculated.
                Try again."
      ↓
      Back to [9]
```

---

## 7. Schedule and Milestones

### 7.1 Timeline (Gantt Chart)

```
Week:      1    2    3    4    5    6    7    8    9    10
         ────────────────────────────────────────────────────
Phase 0: ████████
Phase 1:          ████████████████████
Phase 2:                              ██████████████
Phase 3:                                            ██████████████
Phase 4:                                                          ██████
         ────────────────────────────────────────────────────
Launch:                                                            🚀
```

**Estimated total time: 10 weeks**

### 7.2 Project Phases

#### **Phase 0: Preprocessing (2 weeks)**
**Milestones:**
- ☑ Data downloaded from IMGW
- ☑ The `flow_network` table generated (REMOVED in ADR-028, migration 015 — replaced by stream_network + the in-memory CatchmentGraph)
- ☑ Land cover and streams imported
- ☑ Data validation: 100% coverage of the municipality area

#### **Phase 1: Backend MVP (3 weeks)**
**Milestones:**
- ☑ FastAPI + PostgreSQL setup
- ☑ Endpoint: POST `/api/delineate-watershed`
- ☑ Endpoint: POST `/api/select-stream` — stream segment selection + upstream traversal
- ☑ Endpoint: POST `/api/terrain-profile` — terrain profile along a polyline
- ☑ Endpoint: GET `/api/depressions` — terrain depressions with filters
- ☑ Endpoint: GET `/api/tiles/streams/{z}/{x}/{y}.pbf` — MVT tiles of streams
- ☑ Endpoint: GET `/api/tiles/catchments/{z}/{x}/{y}.pbf` — MVT tiles of sub-catchments
- ☑ Endpoint: GET `/api/tiles/landcover/{z}/{x}/{y}.pbf` — MVT tiles of BDOT10k land cover
- ☑ Endpoint: GET `/api/tiles/thresholds` — available flow accumulation thresholds
- ☑ Endpoint: GET `/api/scenarios` — list of the available rainfall scenarios
- ☑ Endpoint: GET `/health` — health check
- ☑ Watershed delineation algorithm over the graph (in-memory CatchmentGraph + BFS)
- ☑ Calculation of the physiographic parameters
- ☑ Unit tests: > 80% coverage (720 tests, 43 test files)

#### **Phase 2: Hydrological Model (2 weeks)**
**Milestones:**
- ☑ Beta hyetograph implementation
- ☑ SCS Curve Number model
- ☑ SCS unit hydrograph
- ☑ Numerical convolution
- ☑ Endpoint: POST `/api/generate-hydrograph`
- ☑ Validation on 3 sample watersheds

#### **Phase 3: Frontend (2 weeks)**
**Milestones:**
- ☑ Leaflet map with point selection (polygon drawing mode, object selection mode)
- ☑ Rainfall scenario form
- ☑ API calls with error handling
- ☑ Chart.js charts (hydrograph, histogram)
- ☑ CSV/GeoJSON export
- ☑ Glassmorphism UI with a draggable side panel
- ☑ Base layers: OSM, ESRI Satellite, OpenTopoMap, GUGiK WMTS (orthophoto + topographic)
- ☑ Thematic layers: MVT streams, MVT watersheds, MVT land cover, DEM hillshade, depressions
- ☑ Terrain profile — longitudinal profile of a stream
- ☑ 10 JS modules (IIFE on `window.Hydrograf`): api, map, draggable, charts, layers, profile, hydrograph, depressions, app

#### **Phase 3b: Admin panel (ADR-034)**
**Milestones:**
- ☑ Frontend `/admin` — glassmorphism, 4 sections (Dashboard, Bootstrap, Resources, Cleanup)
- ☑ 8 `/api/admin/*` API endpoints (dashboard, resources, cleanup estimate/execute, bootstrap start/cancel/status/stream)
- ☑ API key authentication (header X-Admin-Key, env ADMIN_API_KEY)
- ☑ Running bootstrap.py from the panel + real-time SSE logs
- ☑ Resource monitoring: CPU/RAM (psutil), DB pool, CatchmentGraph cache
- ☑ Data cleanup: tiles, overlays, dem_mosaic, TRUNCATE of tables
- ☑ 3 admin JS modules: admin-api.js, admin-app.js, admin-bootstrap.js

#### **Phase 4: Testing and Deploy (1 week)**
**Milestones:**
- ☑ Performance optimization (in-memory CatchmentGraph, O(n) downstream links, boundary smoothing)
- ☑ Docker Compose setup (db + api + nginx, 3 containers)
- ☑ Technical documentation (34 ADRs, architecture, integrations)
- ⏳ User acceptance tests (UAT) — planned for CP5
- ⏳ Production deploy — planned for CP5

---

## 8. Success Criteria and Metrics

### 8.1 Product Metrics (MVP)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Watershed delineation time | < 10s | Backend logs |
| Hydrograph generation time | < 5s | Backend logs |
| Accuracy of watershed boundaries | > 95% | Validation vs. reference methods |
| System availability | > 99% | Uptime monitoring |
| Users per month | > 20 | Analytics |
| Average number of analyses per user | > 5 | Analytics |

### 8.2 Quality Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| User satisfaction (NPS) | > 8/10 | Surveys |
| Ease of use (SUS) | > 75/100 | SUS questionnaire |
| Number of bug reports | < 5/month | Issue tracker |
| Time to resolve a critical bug | < 24h | Issue tracker |

### 8.3 Acceptance Criteria (Go/No-Go)

**The MVP is ready for deployment when:**
- ✅ All user stories (MUST HAVE) are implemented
- ✅ Unit tests: > 80% coverage
- ✅ Acceptance tests: 100% pass rate
- ✅ Performance: all operations are within their time targets
- ✅ User documentation: ready
- ✅ 3 test users have accepted the system

---

## 9. Example Usage Scenarios

### Scenario 1: Assessing the impact of an investment
> A user plans a new housing development. They want to check whether a larger impervious area changes the peak flows. They delineate the watershed, save the results, then change the CN by hand (simulating more built-up area) and generate a new hydrograph.

### Scenario 2: Verifying a bridge cross-section
> An engineer checks whether an existing bridge suits the flow Q10%. They delineate the watershed above the bridge, generate the hydrograph for p=10% and compare Qmax with the capacity of the bridge.

### Scenario 3: A report for an authority
> A consultant prepares an environmental impact report. They delineate 5 watersheds, generate a hydrograph for each, export the results (CSV + GeoJSON) and paste them into a Word report.

---

**Document version:** 1.2
**Date of the last update:** 2026-10-25
**Status:** Approved — the project is in active development (CP4 finished, CP5 MVP in preparation)

**Change history:**
- 1.2 (2026-10-25): translated to English (DEV-2.1); the content is unchanged
- 1.1 (2026-03-01): last content update

---

*This document is the basis for starting work on the hydrological analysis system. Every change of the requirements must be approved by the Product Owner and documented as an addendum to this PRD.*
