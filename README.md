# Hydrograf: watershed delineation and design hydrographs for Poland

Hydrograf is a web application for watershed delineation, catchment parameters and design hydrographs in Poland. Click a point on the map to get the watershed boundary and its parameters (area, slopes, land cover, SCS-CN curve number, soil groups), then generate a design hydrograph from IMGW maximum precipitation (PMAXTP). Map interface, REST API and admin panel; FastAPI over PostGIS.

## When to use

- Delineate the watershed of a point or a stream segment in Poland from a digital elevation
  model (DEM, Polish NMT) and read its parameters: area, perimeter, slopes, hypsometric
  curve, shape indices, hydraulic length, land cover, CN and soil groups (HSG).
- Generate a design hydrograph for a catchment of up to 250 km² with the SCS-CN method and
  the antecedent moisture condition AMC I, II or III: PMAXTP design rainfall by duration and
  probability with a beta, block or Euler II hietogram, or your own rainfall series (typed,
  pasted or imported from CSV); SCS, Snyder or Nash unit hydrograph. Advanced mode lets you
  change the catchment parameters before the calculation.
- Look at streams, catchments, land cover, depressions, a storm-sewer network, the flood
  hazard map (MZP) of Wody Polskie and the results of external analyses (for example SFINCS
  flood depths from Hydraulik) on an interactive map, and cut a terrain profile along a line
  with the water level of the results you show.
- Work in a map interface in the Nogat visual identity: light and dark theme, a phone
  layout, (i) explanations with formulas next to the results, and a welcome dialog. The
  "Instrukcja" button in the top bar opens that dialog and links to the scrolling guide
  at `/instrukcja/`.
- Run your own instance, for a municipality or a consultancy: the data stay in your
  PostGIS database.

## When not to use

| Need | Use instead |
|---|---|
| Catchments above 250 km² (the limit of SCS-CN) or other rainfall-runoff methods | [Hydrolog](https://github.com/Daldek/Hydrolog) as a library, or an external model such as HEC-HMS |
| Hydraulic modelling: flood inundation maps, channel routing, reservoir retention | [Hydraulik](https://github.com/Daldek/Hydraulik) (SFINCS flood models, in research), or HEC-RAS and EPA SWMM |
| Areas outside Poland | QGIS with GRASS or WhiteboxTools on your own DEM |
| Downloading spatial data files or browsing the downloaded stores | [Kartograf](https://github.com/Daldek/Kartograf), [Archiwista](https://github.com/Daldek/Archiwista) |
| Precipitation series, station data, PMAXTP as files | [Obserwator](https://github.com/Daldek/Obserwator) |
| User accounts, saved analyses, PDF reports, real-time or forecast data | not provided |

## Run

Requirements: Docker with Compose for the full stack; for development also Python 3.12 or
newer and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Daldek/Hydrograf.git
cd Hydrograf
cp .env.example .env      # set POSTGRES_PASSWORD
docker compose up -d      # PostGIS, API and web server
```

The map is at `http://localhost:8080` (the port is `HYDROGRAF_PORT`), the admin panel at
`/admin/` (it asks for the admin key; see [Admin panel](#admin-panel)), and the scrolling user
guide at `/instrukcja/` (on the test server: https://hydrograf-test.debever.pl/instrukcja),
linked from the map's top-bar "Instrukcja" button via the welcome dialog. The API is under
`/api` and the health check at `/health`. The web server listens on the loopback interface
only (`127.0.0.1:${HYDROGRAF_PORT:-8080}`). In development `docker-compose.override.yml` is
loaded automatically (hot reload, the code mounted from `./backend`).

The API needs data before it can delineate: a one-off preprocessing of the DEM and its
derivatives for your area. The easiest way is the admin panel (in „Przetwarzanie NMT” give a
bounding box or a boundary file and press „Uruchom”); the same from the command line, which
takes a few hours for a large area:

```bash
cd backend
uv sync --locked
uv run python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4"
```

The pipeline downloads the DEM from GUGiK, land cover from the topographic database BDOT10k,
soil data from SoilGrids and precipitation from IMGW, and writes
`frontend/data/instance.json`, from which the welcome dialog and the guide name the data area
(`--area-name`). The
[scripts README](https://github.com/Daldek/Hydrograf/blob/main/backend/scripts/README.md)
describes every script.

Development without Docker for the API:

```bash
docker compose up -d db
cd backend
uv run alembic upgrade head
uv run uvicorn api.main:app --reload   # API on :8000, OpenAPI at /docs and /openapi.json
```

### First request

```bash
curl -s -X POST http://localhost:8080/api/delineate-watershed \
  -H 'Content-Type: application/json' \
  -d '{"latitude": 52.23, "longitude": 21.01, "threshold_m2": 10000}'
```

The answer holds `mode` (`precomputed` with a threshold, `precise` without), `watershed`
(`boundary_geojson`, `outlet`, `morphometry`, `land_cover_stats`, `hsg_stats` and the flow
paths), `stream` (the selected segment) and `upstream_segment_indices` (the segments above
it). A hydrograph for the same point:

```bash
curl -s -X POST http://localhost:8080/api/generate-hydrograph \
  -H 'Content-Type: application/json' \
  -d '{"latitude": 52.23, "longitude": 21.01, "duration": "1h", "probability": 10}'
```

The answer holds `precipitation` (total and effective depths), `hydrograph` (`times_min`,
`discharge_m3s`, `peak_discharge_m3s`, `time_to_peak_min`, `total_volume_m3`),
`water_balance` and `metadata` (the time of concentration and the methods used).

## Deploy

Production runs `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`: the
database password from `SECRETS_DIR`, the admin key file required, no reload, one API
process; the test server is reached through a Cloudflare Tunnel. Every variable is listed in
[`.env.example`](https://github.com/Daldek/Hydrograf/blob/main/.env.example); secrets come
from the environment or from files outside the checkout, and `.env` is not committed.
[docs/USAGE.md](https://github.com/Daldek/Hydrograf/blob/main/docs/USAGE.md) has the
details:

- the variables by group;
- the admin key in one host file, `~/.config/nogat/keys/hydrograf-admin.key`, named in `.env`
  by `ADMIN_API_KEY_HOST_FILE` with the group `HYDROGRAF_SECRETS_GID`, never as a value;
- `NOGAT_CONFIG`, the deployment's `nogat.toml`, whose table `[nogat.operator]` makes
  Hydrograf a [public service](#public-service), and `NOGAT_STATE_DIR`, the directory of the
  logs;
- a second instance beside the first on the same Docker host, with its own compose project
  and env file;
- the service logs in `<state_dir>/hydrograf/logs/` (Nogat DEV-12.4 to DEV-12.9): 14 days,
  no client address (ADR-084), and how to read them.

### Public service

Hydrograf is open to anyone without signing in (Nogat DEV-15.7 to DEV-15.12, ADR-084):

- **Regulamin.** With `[nogat.operator]` in the file of `NOGAT_CONFIG` the API fills Nogat's
  regulamin (`frontend/nogat/nogat-terms.html`, kit 1.0.0) once per process with the
  operator and the entry `hydrograf` of the table `gui`, and serves it at `/regulamin.html`.
  The link „Regulamin” (in a new tab) is at the bottom of the left rail, under the guide's
  table of contents, in the welcome window and in the menu „Aplikacje”.
- **Request limit.** Pages and API routes: 300 requests in 60 s per client address
  (`HYDROGRAF_REQUEST_LIMIT`, `HYDROGRAF_REQUEST_WINDOW`). The map's vector tiles
  (`/api/tiles/`) have a tile limit of their own instead: ten times the limit in the same
  window, 3,000 requests in 60 s by default, since one map move loads dozens of tiles.
  „Zgłoś uwagę” (`/api/feedback`) has besides at most 5 reports in 5 minutes. `/health` and the static
  files that nginx serves are not counted. Over a limit the answer is 429 with
  `Retry-After`: a Polish page for a page, the problem `rate_limited` for a route. The client
  address comes from Cloudflare's `CF-Connecting-IP`, believed only through private hops; it
  stays in the API's memory for its window only.
- **Statistics.** One line per UTC day in `<data_dir>/hydrograf/stats.jsonl`
  (`HYDROGRAF_DATA_DIR`; `/data` in Docker, `HYDROGRAF_DATA_PATH` on the host), rewritten every
  10 minutes, at 00:00 UTC and at shutdown: `date`, `visitors` (distinct pairs of address and
  User-Agent of the day, counted as HMAC-SHA-256 hashes under a salt drawn daily and kept in
  memory only), `page_views` (GETs of a page served: the map, the guide, the regulamin),
  `stations_opened` (always 0: Hydrograf has no stations), `analyses_run`
  (successful delineations of a watershed or a network, hydrographs and terrain profiles, not
  the previews) and `downloads` (files the interface saves: hietogram CSV and JSON, PMAXTP
  GeoJSON, the hand-off file; the interface reports each to `/api/downloads`). Nothing
  else is stored. The requests of the admin panel count in no total (Nogat DEV-15.13).
- **„Zgłoś uwagę”.** The form sends the text and the view's context (the map mode, the map and
  the analysis settings); the server adds the app version and stores no User-Agent and no
  address. It has no contact field: it says „Nie wpisuj danych osobowych. Jeśli chcesz
  odpowiedzi, napisz na” the operator's e-mail.

The limit and the visitors live in the memory of one process: run the API with one uvicorn
process (the Compose files do).

### Admin panel

The panel is Nogat's kit page at `/admin/` (Nogat DEV-15.13, ADR-086; `/admin` answers 308
to it): „Zgłoszenia”, „Statystyki” and „Stan” of the kit, then Hydrograf's „Zasoby”,
„Przetwarzanie NMT”, „Czyszczenie” and „Granice i kanalizacja”. Its API is under
`/api/admin/`; every route needs the header `X-Admin-Key` with the key of `ADMIN_API_KEY`
or of the file `ADMIN_API_KEY_FILE` names (a deployment's
`~/.config/nogat/keys/hydrograf-admin.key`, see [Deploy](#deploy)), read on
every request. No key is generated or logged: without one
every admin route answers 401 with `admin_key_not_configured`. The access paths are
`/admin`, `/admin/*` and `/api/admin/*`, nothing else; Cloudflare Access protects them
besides the key. Every admin answer is `Cache-Control: no-store`; the page has CSP
`'self'` (the tiles of GUGiK's OpenStreetMap of the area map excepted) and its requests
stay under the request limit.

A GET of `/api/admin/status` gives the app, its version, start and uptime, `data_dir`
(`HYDROGRAF_DATA_DIR`) with its free disk, and three checks: `database` (PostGIS answers),
`catchment_graph` (the graph of the delineation is in memory; `warning` when it is not)
and `data_dir` (`<data_dir>/hydrograf`, where the statistics are written, is writable).
A GET of `/api/admin/stats?from=&to=` gives the days of `stats.jsonl` between the two UTC days
(default the last 30) with the current day as counted so far, and the sums of every total
but `visitors`.

## Capabilities

| Task | Route (prefix `/api`) | Data source |
|---|---|---|
| Delineate a watershed and compute its parameters | `POST /delineate-watershed` | DEM and BDOT10k (GUGiK), SoilGrids |
| Preview of the sub-catchments of a delineation, for the animation of the interface | `POST /delineate-watershed/preview` | preprocessed data |
| Network of subcatchments, reaches and junctions at a closing section and control points above it, with its hand-off to Hydrolog | `POST /delineate-network` | preprocessed data, saved rasters, DEM (GUGiK) |
| The same network composed on the catchment graph in a fraction of a second, before its characteristics: snapped points, ids, areas, outlines, reach lengths | `POST /delineate-network/preview` | preprocessed data, saved rasters around the points |
| Design hydrograph and water balance, with AMC I to III and your own rainfall series | `POST /generate-hydrograph`, `GET /scenarios` | PMAXTP (IMGW-PIB) or your own series |
| Terrain profile along a line, with the water levels of the analysis results | `POST /terrain-profile` | DEM (GUGiK), analysis results (`frontend/data/results/`) |
| Everything known at one point of the map: coordinates, terrain, stream, land cover with its CN, soil group, sub-catchment, water of the analysis results | `GET /identify-point` | preprocessed data, analysis results |
| Optional layers that hold data (storm sewer) | `GET /layers` | database |
| Vector tiles of streams, catchments, land cover, sewer network | `GET /tiles/{layer}/{z}/{x}/{y}.pbf`, `GET /tiles/thresholds` | preprocessed data |
| Closed depressions of the terrain | `GET /depressions` | DEM (GUGiK) |
| Feedback: a text and the context of the view | `POST /feedback` | none |
| The other GUIs of the ecosystem that this deployment runs, for the top bar's menu „Aplikacje” | `GET /gui` | `HYDROGRAF_GUI` or the `nogat.toml` of `NOGAT_CONFIG` |
| The address of the regulamin and the operator's e-mail, both null without an operator | `GET /terms` | the `nogat.toml` of `NOGAT_CONFIG` |
| Count one file that the interface saved, for the daily statistics | `POST /downloads` | none |
| Administration: reports, statistics, status, resources, DEM processing, cleanup, boundary and sewer upload | `/admin/*` with the `X-Admin-Key` header (see [Admin panel](#admin-panel)) | none |

The background maps of the interface are OpenFreeMap (vector, drawn by MapLibre GL), the
grey OpenStreetMap of GUGiK and the orthophoto of GUGiK; the flood hazard map (MZP) of Wody
Polskie is an overlay from their WMS service. The results of external analyses (for
example SFINCS runs of Hydraulik) are tile layers listed in the manifest
`frontend/data/results/index.json` (schema `hydrograf-results/1`). The interface is static
vanilla JS with Leaflet, MapLibre GL and Chart.js, vendored in `frontend/vendor/` (no page
loads a script, style or font from another site), in the Nogat visual identity
(`frontend/css/tokens.css`) with Nogat's GUI kit (`frontend/nogat/`: the menu „Aplikacje”,
the hand-off, the strip of sources, the regulamin template and the admin panel). Hydrograf uses
[Hydrolog](https://github.com/Daldek/Hydrolog) for the
calculations, [Kartograf](https://github.com/Daldek/Kartograf) for the spatial data and
[Obserwator](https://github.com/Daldek/Obserwator) for the precipitation (IMGWTools until its
v3.0.0; Hydrograf imports the package `obserwator`).

## For AI agents

Hydrograf is a service with preprocessing scripts, not a command-line tool or an MCP
server, so it has no `AGENTS.md` and no `llms.txt`. The REST API is described by the
OpenAPI document (`/openapi.json` of the API, with `/docs` as the interactive page), and
the models in `backend/models/schemas.py` are the schemas of the requests and responses.
Developing this repository? Read
[CLAUDE.md](https://github.com/Daldek/Hydrograf/blob/main/CLAUDE.md).

## Related tools

- [Hydrolog](https://github.com/Daldek/Hydrolog): hydrological calculations (time of
  concentration, hietograms, unit hydrographs), used as a library.
- [Kartograf](https://github.com/Daldek/Kartograf): downloads the DEM, land cover and soil
  data that the preprocessing needs.
- [Obserwator](https://github.com/Daldek/Obserwator): the PMAXTP precipitation of IMGW-PIB.
- [Hydraulik](https://github.com/Daldek/Hydraulik): planned as a compute node for the
  hydraulic models of a catchment.
- [Archiwista](https://github.com/Daldek/Archiwista): browser of the Kartograf data stores.
- For other countries or custom terrain analysis, prefer QGIS with GRASS or WhiteboxTools.

## Errors and exit codes

Every error of the API is `application/problem+json` (RFC 9457) with `type` (the entry of
the code in the
[shared registry](https://github.com/Daldek/Nogat/blob/main/standards/ERROR_REGISTRY.md)),
`title`, `status`, `detail`, `instance`, `code`, `hint` when a fix is known, `details` (its
`reason` names the cause) and, for invalid values, `errors[]` with a JSON Pointer for each
value. The HTTP status comes from the registry: invalid requests are 400, not 422. The
texts are English, and Polish with `Accept-Language: pl` (the interface sends it); codes
and `details` do not change with the language. The five codes you meet most:

| Code | Status | When |
|---|---|---|
| `validation_error` | 400 | a value of the request is wrong; see `errors[]` |
| `not_found` | 404 | no catchment at the point, or an unknown route |
| `no_data` | 404 | the request is valid but there is no precipitation or elevation data |
| `unsupported` | 422 | the catchment is above 250 km² or lacks the parameters of the chosen model |
| `unauthorized` | 401 | the `X-Admin-Key` of the admin panel is missing or wrong, or the server has no key |

Over the request limit every route answers 429 with `Retry-After` and the problem
`rate_limited` (`details`: `reason` `request_limit`, `tile_limit` or `feedback_limit`,
`retry_after_s`, `limit`, `window_s`). Only the gateway errors of nginx (502, 504) are not
problem documents. The preprocessing scripts exit with 0 on success, 1 on failure and 2
when the command line is invalid; a refusal of the bootstrap (a set of an Archiwista
project, the shared store) exits with the code of the registry, listed in the
[scripts README](https://github.com/Daldek/Hydrograf/blob/main/backend/scripts/README.md).

## Data and licensing

| Source | Data | Licence |
|---|---|---|
| GUGiK | DEM (NMT), BDOT10k land cover and hydrography; the orthophoto (WMTS) and the grey OSM basemap of geoportal.gov.pl | GUGiK's conditions of reuse (https://www.gov.pl/web/gugik/ponowne-wykorzystanie-informacji-sektora-publicznego): every response, view, export, image and hand-off with NMT or BDOT10k data carries G, „Źródło: Główny Urząd Geodezji i Kartografii – GUGiK, `<products>` (wytworzono `<period>`, pozyskano `<date>`); dane przetworzone”, dated from the Kartograf metadata of the files the instance used (`sources` of `frontend/data/instance.json`); the orthophoto is credited „Ortofotomapa © GUGiK” on the map |
| ISRIC SoilGrids | soil texture, input of the HSG groups | CC BY 4.0: the products with soil groups carry SG, „Źródło: ISRIC – World Soil Information, SoilGrids, licencja CC BY 4.0 (…); dane przetworzone” |
| IMGW-PIB | PMAXTP maximum precipitation | the PMAXTP terms (https://klimat.imgw.pl/opady-maksymalne): the source with the PMAXTP page, the note that the data were processed and the monograph of the project, then the link to the terms. Every response, view, export and hand-off with PMAXTP data carries these lines |
| Wody Polskie (KZGW, ISOK) | flood hazard map (MZP, 2020 update): water depth of river floods, as a WMS overlay | CC BY 4.0, „MZP © Wody Polskie / ISOK (CC BY 4.0)” on the map |
| OpenStreetMap and others | background maps in the interface | the attribution shown on the map |

The lines of IMGW-PIB, GUGiK and ISRIC come from `backend/core/attribution.py` (Nogat DEV §20,
ADR-083, ADR-085) in `attribution` and `terms_notice`; the strip under the map shows
their short forms. CORINE Land Cover (Copernicus) is not used: the land cover is
BDOT10k's (ADR-074). Esri's orthophoto is no longer offered (ADR-085). The data are
downloaded by Kartograf and Obserwator, whose documentation has the details. Downloaded
and derived data are written to `data/` and `cache/` (outside Git) and to the database;
pass on the lines of `attribution` and `terms_notice` that Hydrograf gives with its
results when you publish them.

## Documentation

- [Changelog](https://github.com/Daldek/Hydrograf/blob/main/docs/CHANGELOG.md)
- [Usage: configuration, admin key, second instance, service logs](https://github.com/Daldek/Hydrograf/blob/main/docs/USAGE.md)
- [Scope](https://github.com/Daldek/Hydrograf/blob/main/docs/SCOPE.md) and
  [product requirements](https://github.com/Daldek/Hydrograf/blob/main/docs/PRD.md)
- [Architecture](https://github.com/Daldek/Hydrograf/blob/main/docs/ARCHITECTURE.md) and
  [data model](https://github.com/Daldek/Hydrograf/blob/main/docs/DATA_MODEL.md)
- [Decisions (ADR index)](https://github.com/Daldek/Hydrograf/blob/main/docs/DECISIONS.md)
- Integrations:
  [Kartograf](https://github.com/Daldek/Hydrograf/blob/main/docs/integrations/KARTOGRAF.md),
  [Hydrolog](https://github.com/Daldek/Hydrograf/blob/main/docs/integrations/HYDROLOG.md),
  [Obserwator](https://github.com/Daldek/Hydrograf/blob/main/docs/integrations/OBSERWATOR.md)
- [Current state and next steps](https://github.com/Daldek/Hydrograf/blob/main/docs/PROGRESS.md)
  and [backlog](https://github.com/Daldek/Hydrograf/blob/main/docs/BACKLOG.md)
- For users: the scrolling guide at `/instrukcja/` of a running instance
  (`frontend/instrukcja/`) and the separate
  [slide presentation](https://github.com/Daldek/Hydrograf/blob/main/docs/Hydrograf-prezentacja.html)
  (also as PDF; the PDF is not regenerated for guide edits).

## Development

`cd backend && uv sync --locked`, then `scripts/gate.sh` runs the checks (ruff, mypy, tests
with coverage, commit messages, the `?v=` versions of the front-end assets).
[CLAUDE.md](https://github.com/Daldek/Hydrograf/blob/main/CLAUDE.md) has the rules for
people and agents, and
[CONTRIBUTING.md](https://github.com/Daldek/Hydrograf/blob/main/CONTRIBUTING.md) the workflow
of a pull request.

## Status, licence, author

Alpha. Releases are the tags `vX.Y.Z` of `main`; 0.5.0 is in the first joint release of
Nogat. Licence: MIT
([LICENSE](https://github.com/Daldek/Hydrograf/blob/main/LICENSE)). Author:
[Piotr de Bever](https://www.linkedin.com/in/piotr-de-bever/).
