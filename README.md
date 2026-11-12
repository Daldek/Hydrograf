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
`/admin` (it asks for the admin key), and the scrolling user guide at `/instrukcja/`
(on the test server: https://hydrograf-test.debever.pl/instrukcja). The guide is linked
from the map's top-bar "Instrukcja" button via the welcome dialog. The API is under
`/api` and the health check at `/health`. The web server listens on the loopback interface only
(`127.0.0.1:${HYDROGRAF_PORT:-8080}`); the test server is reached through a Cloudflare
Tunnel. In development `docker-compose.override.yml` is loaded automatically (hot
reload, the code mounted from `./backend`); production runs
`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` (secrets from
`SECRETS_DIR`, no reload).

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
`./frontend/tiles`). The database volume and the network take the project's name
(`NAME_postgres_data`, `NAME_default`). The checkout needs the empty directories
`frontend/data` and `frontend/tiles`: nginx mounts the instance's directories there inside
its read-only `./frontend`.

The API needs data before it can delineate: a one-off preprocessing of the DEM and its
derivatives for your area. The easiest way is the admin panel (give a bounding box and
press Start); the same from the command line, which takes a few hours for a large area:

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
paths), and `stream` with `upstream_segment_indices` for the selected segment. A hydrograph
for the same point:

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
manifest of the analysis results), the admin key
(`ADMIN_API_KEY` or `ADMIN_API_KEY_FILE`), the IMGW preprocessing (`IMGW_GRID_SPACING_KM`,
`IMGW_RATE_LIMIT_DELAY_S`), the shared Kartograf store (`HYDROGRAF_KARTOGRAF_ROOT`, read only
through a closed set of an Archiwista project, `bootstrap --project --set`), the other GUIs of
the ecosystem that the top bar's „Aplikacje” lists (`HYDROGRAF_GUI`, a JSON object such as
`{"hydrolog": "http://127.0.0.1:8070/"}`; without it there is no menu) and Docker Compose
(`HYDROGRAF_PORT`, `SERVER_NAME`, `SECRETS_DIR`, and the names and host paths of an instance:
`HYDROGRAF_CONTAINER_PREFIX`, `HYDROGRAF_*_PATH`). Secrets are read from the environment only
and `.env` is not committed.

### Service logs

Nginx writes requests and errors to stdout/stderr; the API and PostgreSQL also log to
Docker. The three services of Hydrograf rotate their `json-file` logs: at most 50 files of
10 MiB (500 MiB) **per container**. To look at them:

```bash
docker compose logs --since 10m nginx api db
```

Every nginx access entry holds `request_id` (also for static files), `request_time` and
`upstream_time` in seconds (`-` without a backend). For API requests nginx passes the same
`X-Request-ID` to FastAPI; the API returns it in the response header and writes a JSON
record `request_completed` or `request_failed` with `request_id`, `status_code` and
`duration_ms`. Look for the ID that a tester reports in both logs. The nginx time covers
the proxy and the transfer of the response, the API time the handling by the application;
the two need not be equal.

During tests give the tester the tunnel address that starts with `https://`. The current
Cloudflare redirect from HTTP returns 301, so a `POST` sent straight to HTTP can be
repeated as a `GET`. When a tester reports an error, ask for the approximate time and the
`X-Request-ID` from the diagnostics of the feedback form; the nginx log also shows the
failed loads of static files, which never reach the API. The rotation limits the size but
does not keep the entries for a set number of days.

A change of the logging options needs the containers to be recreated
(`docker compose up -d db api nginx`); a restart does not update the log driver. The logs
can hold IP addresses, paths and query parameters: do not share them with testers. The
separate `imgwtools-api` container (the REST server of IMGWTools 2.1, now Obserwator) is not
part of this Compose project and is not covered by this rotation.

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
| Feedback from testers | `POST /feedback` | none |
| The other GUIs of the ecosystem that this deployment runs, for the top bar's menu „Aplikacje” | `GET /gui` | `HYDROGRAF_GUI` |
| Administration (pipeline, data cleanup, sewer network upload, feedback list) | `/admin/*` with the `X-Admin-Key` header | none |

The background maps of the interface are OpenFreeMap (vector, drawn by MapLibre GL), the
grey OpenStreetMap of GUGiK and the Esri orthophoto; the flood hazard map (MZP) of Wody
Polskie is an overlay from their WMS service. The results of external analyses (for
example SFINCS runs of Hydraulik) are tile layers listed in the manifest
`frontend/data/results/index.json` (schema `hydrograf-results/1`). The interface is static
vanilla JS with Leaflet, MapLibre GL and Chart.js in the Nogat visual identity
(`frontend/css/tokens.css`) with Nogat's GUI kit (`frontend/nogat/`: the menu „Aplikacje” and
the hand-off); Bootstrap 5 is used only in `/admin`. Hydrograf uses
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
| `unauthorized` | 401 | the `X-Admin-Key` of the admin panel is missing or wrong |

Errors of the web server itself (429 when the rate limit is exceeded, gateway errors) are
not problem documents. The preprocessing scripts exit with 0 on success and 1 on failure,
and with 2 when the command line is invalid.

## Data and licensing

| Source | Data | Licence |
|---|---|---|
| GUGiK | DEM (NMT), BDOT10k land cover and hydrography | free reuse with attribution (Prawo geodezyjne i kartograficzne) |
| Copernicus CLMS | CORINE Land Cover | Copernicus data policy, attribution required |
| ISRIC SoilGrids | soil texture, input of the HSG groups | CC BY 4.0 |
| IMGW-PIB | PMAXTP maximum precipitation | attribution to IMGW-PIB and the PMAXTP project; terms on the IMGW pages |
| Wody Polskie (KZGW, ISOK) | flood hazard map (MZP, 2020 update): water depth of river floods, as a WMS overlay | CC BY 4.0, „MZP © Wody Polskie / ISOK (CC BY 4.0)” on the map |
| OpenStreetMap and others | background maps in the interface | the attribution shown on the map |

The data are downloaded by Kartograf and Obserwator, whose documentation has the details and
the attribution texts. Downloaded and derived data are written to `data/` and `cache/`
(outside Git) and to the database; pass on the attribution when you publish results.

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
