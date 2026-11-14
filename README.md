# Hydrograf: watershed delineation and design hydrographs for Poland

Hydrograf is a web application for watershed delineation and design hydrographs in Poland. Click a point on the map to get the watershed boundary and its parameters (area, slopes, land cover, SCS-CN curve number, soil groups), then generate a design hydrograph from IMGW maximum precipitation (PMAXTP). Map interface, REST API and admin panel; FastAPI over PostGIS.

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

## Run and Deploy

Requirements: Docker with Compose for the full stack; for development also Python 3.12 and
[uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Daldek/Hydrograf.git
cd Hydrograf
cp .env.example .env      # set POSTGRES_PASSWORD, and ADMIN_API_KEY for the admin panel
docker compose up -d      # PostGIS, API and web server
```

The map is at `http://localhost:8080` (the port is `HYDROGRAF_PORT`), the admin panel at
`/admin/` (it asks for the admin key; see [Admin panel](#admin-panel)), and the scrolling user guide at `/instrukcja/`
(on the test server: https://hydrograf-test.debever.pl/instrukcja). The guide is linked
from the map's top-bar "Instrukcja" button via the welcome dialog. The API is under
`/api` and the health check at `/health`. The web server listens on the loopback interface only
(`127.0.0.1:${HYDROGRAF_PORT:-8080}`); the test server is reached through a Cloudflare
Tunnel. In development `docker-compose.override.yml` is loaded automatically (hot
reload, the code mounted from `./backend`); production runs
`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` (secrets from
`SECRETS_DIR`, no reload, one API process).

A public deployment names its `nogat.toml` (Nogat DEV-18.1) in `.env`:
`NOGAT_CONFIG=/home/USER/.config/nogat/nogat.toml`, which Compose mounts read-only into the
API at `/config/nogat.toml`. With the table `[nogat.operator]` in that file Hydrograf is a
public service with its regulamin at `/regulamin.html` (see [Public service](#public-service));
without it there is no regulamin, no footer and no menu entry „Regulamin”. On the Docker
host, name the state directory of the logs in `.env` too,
`NOGAT_STATE_DIR=/home/USER/.local/state/nogat`, and create the API's directory in it once,
writable by the container's user (UID 999) as `data/` is:
`install -d -m 0777 ~/.local/state/nogat/hydrograf` (without `NOGAT_STATE_DIR` Compose
mounts `./state/hydrograf` of the checkout, which needs the same; see
[Service logs](#service-logs)).

A second instance runs beside the first on the same Docker host from its own checkout, with
its own compose project and env file:

```bash
docker compose -p NAME --env-file NAME.env up -d   # with -f ... as above for production
```

`NAME.env` holds the instance's settings (`POSTGRES_PASSWORD`, `SECRETS_DIR` and so on) and
its names: `HYDROGRAF_CONTAINER_PREFIX` (containers `<prefix>_db`, `<prefix>_api`,
`<prefix>_nginx`; default `hydro`), a free `HYDROGRAF_PORT`, and the host directories
`HYDROGRAF_CACHE_PATH`, `HYDROGRAF_DATA_PATH`, `HYDROGRAF_FRONTEND_DATA_PATH` and
`HYDROGRAF_FRONTEND_TILES_PATH` (defaults `./cache`, `./data`, `./frontend/data`,
`./frontend/tiles`), and its own `NOGAT_STATE_DIR` with a `hydrograf` directory writable by
UID 999, so that its logs stay apart from the first instance's. The database volume and the
network take the project's name (`NAME_postgres_data`, `NAME_default`). The checkout needs
the empty directories `frontend/data` and `frontend/tiles`: nginx mounts the instance's
directories there inside its read-only `./frontend`.

The API needs data before it can delineate: a one-off preprocessing of the DEM and its
derivatives for your area. The easiest way is the admin panel (in „Przetwarzanie NMT” give a
bounding box or a boundary file and press „Uruchom”); the same from the command line, which
takes a few hours for a large area:

```bash
cd backend
uv sync --locked
uv run python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4"
```

The pipeline downloads the DEM from GUGiK, land cover from BDOT10k, soil data from
SoilGrids and precipitation from IMGW, and writes `frontend/data/instance.json`, from which
the welcome dialog and the guide name the data area (`--area-name`). The
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

### Configuration

Every variable is listed in
[`.env.example`](https://github.com/Daldek/Hydrograf/blob/main/.env.example): the database
(`POSTGRES_*`, `DATABASE_URL`, `DB_STATEMENT_TIMEOUT_MS`), the API (`LOG_LEVEL`,
`CORS_ORIGINS`, `DEM_DIR`, `DEM_PATH`, `STREAM_DISTANCE_PATH`, `FRONTEND_DATA_DIR` for the
manifest of the analysis results and `instance.json`), the admin key
(`ADMIN_API_KEY` or the file named by `ADMIN_API_KEY_FILE`, read on every request; without
either, every admin route refuses with `admin_key_not_configured`), the shared Kartograf
store (`HYDROGRAF_KARTOGRAF_ROOT`, read only
through a closed set of an Archiwista project, `bootstrap --project --set`), the other GUIs of
the ecosystem that the top bar's „Aplikacje” lists (`HYDROGRAF_GUI`, a JSON object such as
`{"hydrolog": "http://127.0.0.1:8070/"}`; without it the table `gui` of `[nogat]` in the file
of `NOGAT_CONFIG`, and without both there is no menu), the public service (`NOGAT_CONFIG`, the
deployment's `nogat.toml`; `HYDROGRAF_REQUEST_LIMIT` and `HYDROGRAF_REQUEST_WINDOW`, 300
requests in 60 s per client address by default; `HYDROGRAF_DATA_DIR`, the directory of the
daily statistics, `/data` in Docker), the logs (`HYDROGRAF_STATE_DIR`, then `NOGAT_STATE_DIR`,
then `state_dir` of `[hydrograf]` or `[nogat]` in the file of `NOGAT_CONFIG`, by default
`~/.local/state/nogat`; for Docker Compose `NOGAT_STATE_DIR` is the host's directory) and
Docker Compose
(`HYDROGRAF_PORT`, `SERVER_NAME`, `SECRETS_DIR`, and the names and host paths of an instance:
`HYDROGRAF_CONTAINER_PREFIX`, `HYDROGRAF_*_PATH`). Secrets are read from the environment only
and `.env` is not committed.

### Service logs

The API writes the logs of Nogat DEV-12.4 to DEV-12.9 (`backend/core/nogat_logging.py`, a
copy of Nogat's reference module) into `<state_dir>/hydrograf/logs/`, one file per kind and
UTC day, `access-`, `app-` and `lifecycle-YYYY-MM-DD.jsonl`, and deletes a file once its date
is 14 days old, at start and at each 00:00 UTC. A record is one JSON object of the format
`nogat-log/1` (`schemas/nogat/record-1.schema.json`): an access record per request (the
method, the path with its query, a parameter that may carry personal data or a credential
keeping only its name, the status, the bytes, `duration_ms` and the class of the User-Agent:
`browser`, `bot`, `script` or `none`), the warnings and errors of the application, and the
start with a summary of the settings, the stop and the deletions. The map tiles
(`/api/tiles/`) are logged only when they fail. Each record has a random `request_id` that
is never sent to the client. No log holds the client's address, a cookie, a header other
than that class of the User-Agent, or a request body (DEV-12.5, ADR-084).

On the Docker host the files are in `<NOGAT_STATE_DIR>/hydrograf/logs/` (`.env`); without
Docker, in `~/.local/state/nogat/hydrograf/logs/` by default. The last 14 days in time
order, without the successful requests:

```bash
jq -cs 'sort_by(.time)[] | select(.kind != "access" or .status >= 500)' ~/.local/state/nogat/hydrograf/logs/*.jsonl
```

Other questions, for example the answers by status and kind of client:
`jq -r 'select(.kind == "access") | "\(.status) \(.agent)"' ~/.local/state/nogat/hydrograf/logs/access-*.jsonl | sort | uniq -c`.
jq is not installed on the host: `apt install jq` (root, once) or jq's static release
binary in `~/.local/bin` (no root). Use is counted only from
`<data_dir>/hydrograf/stats.jsonl` (DEV-15.11, see [Public service](#public-service)), never
from the logs.

The containers print only what outlives the 14 days without naming a request (DEV-12.7):
`docker logs hydro_api` shows the JSON records of the starts, stops and deletions and the
errors reduced to their type. nginx keeps no log (`access_log off`, `error_log /dev/null`):
it would name the client in an error of a request at every level, and the static files it
serves need none. uvicorn runs with `--no-access-log --log-level warning`. Every container
logs with Docker's `local` driver, at most 3 files of 1 MiB.

During tests give the tester the tunnel address that starts with `https://`. The current
Cloudflare redirect from HTTP returns 301, so a `POST` sent straight to HTTP can be
repeated as a `GET`. When a tester reports an error, ask for the approximate time and look
for the `app` records and the 5xx answers around it.

A change of the logging options needs the containers to be recreated
(`docker compose up -d --force-recreate api nginx db`); a restart does not update the log
driver. The logs hold paths and query parameters: do not share them with testers. The
separate `imgwtools-api` container (the REST server of IMGWTools 2.1, now Obserwator) is not
part of this Compose project and is not covered by these settings.

### Public service

Hydrograf is open to anyone without signing in (Nogat DEV-15.7 to DEV-15.12, ADR-084):

- **Regulamin.** With `[nogat.operator]` in the file of `NOGAT_CONFIG` the API fills Nogat's
  regulamin (`frontend/nogat/nogat-terms.html`, kit 0.7.0) once per process with the
  operator and the entry `hydrograf` of the table `gui`, and serves it at `/regulamin.html`.
  The statement of the service and the link „Regulamin” (in a new tab) are under the map and
  in the guide, and in the menu „Aplikacje”.
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
or of the file `ADMIN_API_KEY_FILE` names (the Docker secret `admin_api_key.txt` of the
production overlay), read on every request. No key is generated or logged: without one
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
with coverage, commit messages, the `?v=` versions of the front-end assets). After a
change of a JS or CSS file of `frontend/`, run `python3 scripts/bump_asset_versions.py`:
the pages load their own scripts and styles as `?v=<content hash>`, so that a deployment
gets past the Cloudflare and browser caches; the gate and the CI job `frontend-assets` run
it with `--check`.
[CLAUDE.md](https://github.com/Daldek/Hydrograf/blob/main/CLAUDE.md) has the rules for
people and agents, and
[CONTRIBUTING.md](https://github.com/Daldek/Hydrograf/blob/main/CONTRIBUTING.md) the workflow
of a pull request.

## Status, licence, author

Pre-release: `develop` carries 0.5.0.dev0, the last release is 0.4.0. Licence: MIT
([LICENSE](https://github.com/Daldek/Hydrograf/blob/main/LICENSE)). Author:
[Piotr de Bever](https://www.linkedin.com/in/piotr-de-bever/).
