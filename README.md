# Hydrograf: watershed delineation and design hydrographs for Poland

Hydrograf is a web application for watershed delineation and design hydrographs in Poland. Click a point on the map to get the watershed boundary and its parameters (area, slopes, land cover, SCS-CN curve number, soil groups), then generate a design hydrograph from IMGW maximum precipitation (PMAXTP). Map interface, REST API and admin panel; FastAPI over PostGIS.

## When to use

- Delineate the watershed of a point or a stream segment in Poland from a digital elevation
  model (DEM, Polish NMT) and read its parameters: area, perimeter, slopes, hypsometric
  curve, shape indices, hydraulic length, land cover, CN and soil groups (HSG).
- Generate a design hydrograph for a catchment of up to 250 km² with the SCS-CN method:
  PMAXTP design rainfall by duration and probability, beta, block or Euler II hietogram,
  SCS, Snyder or Nash unit hydrograph.
- Look at streams, catchments, land cover, depressions and a storm-sewer network on an
  interactive map, and cut a terrain profile along a line.
- Run your own instance, for a municipality or a consultancy: the data stay in your
  PostGIS database.

## When not to use

| Need | Use instead |
|---|---|
| Catchments above 250 km² (the limit of SCS-CN) or other rainfall-runoff methods | [Hydrolog](https://github.com/Daldek/Hydrolog) as a library, or an external model such as HEC-HMS |
| Hydraulic modelling: flood inundation maps, channel routing, reservoir retention | [Hydraulik](https://github.com/Daldek/Hydraulik) (SFINCS flood models, in research), or HEC-RAS and EPA SWMM |
| Areas outside Poland | QGIS with GRASS or WhiteboxTools on your own DEM |
| Downloading spatial data files or browsing the downloaded stores | [Kartograf](https://github.com/Daldek/Kartograf), [Archiwista](https://github.com/Daldek/Archiwista) |
| Precipitation series, station data, PMAXTP as files | [IMGWTools](https://github.com/Daldek/IMGWTools) |
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
`/admin` (it asks for the admin key), the API under `/api` and the health check at
`/health`. In development `docker-compose.override.yml` is loaded automatically (hot
reload, the code mounted from `./backend`); production runs
`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` (secrets from
`SECRETS_DIR`, no reload).

The API needs data before it can delineate: a one-off preprocessing of the DEM and its
derivatives for your area. The easiest way is the admin panel (give a bounding box and
press Start); the same from the command line, which takes a few hours for a large area:

```bash
cd backend
uv sync --locked
uv run python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4"
```

The pipeline downloads the DEM from GUGiK, land cover from BDOT10k, soil data from
SoilGrids and precipitation from IMGW. The
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
`CORS_ORIGINS`, `DEM_DIR`, `DEM_PATH`, `STREAM_DISTANCE_PATH`), the admin key
(`ADMIN_API_KEY` or `ADMIN_API_KEY_FILE`), the IMGW preprocessing (`IMGW_GRID_SPACING_KM`,
`IMGW_RATE_LIMIT_DELAY_S`) and Docker Compose (`HYDROGRAF_PORT`, `SERVER_NAME`,
`SECRETS_DIR`). Secrets are read from the environment only and `.env` is not committed.

## Capabilities

| Task | Route (prefix `/api`) | Data source |
|---|---|---|
| Delineate a watershed and compute its parameters | `POST /delineate-watershed` | DEM and BDOT10k (GUGiK), CORINE, SoilGrids |
| Design hydrograph and water balance | `POST /generate-hydrograph`, `GET /scenarios` | PMAXTP (IMGW-PIB) |
| Terrain profile along a line | `POST /terrain-profile` | DEM (GUGiK) |
| Vector tiles of streams, catchments, land cover, sewer network | `GET /tiles/{layer}/{z}/{x}/{y}.pbf`, `GET /tiles/thresholds` | preprocessed data |
| Closed depressions of the terrain | `GET /depressions` | DEM (GUGiK) |
| Feedback from testers | `POST /feedback` | none |
| Administration (pipeline, data cleanup, sewer network upload, feedback list) | `/admin/*` with the `X-Admin-Key` header | none |

The background maps of the interface are OpenStreetMap, Esri, OpenTopoMap and the GUGiK
WMTS services. Hydrograf uses [Hydrolog](https://github.com/Daldek/Hydrolog) for the
calculations, [Kartograf](https://github.com/Daldek/Kartograf) for the spatial data and
[IMGWTools](https://github.com/Daldek/IMGWTools) for the precipitation.

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
- [IMGWTools](https://github.com/Daldek/IMGWTools): the PMAXTP precipitation of IMGW-PIB.
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
| OpenStreetMap and others | background maps in the interface | the attribution shown on the map |

The data are downloaded by Kartograf and IMGWTools, whose documentation has the details and
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
  [IMGWTools](https://github.com/Daldek/Hydrograf/blob/main/docs/integrations/IMGWTOOLS.md)
- [Current state and next steps](https://github.com/Daldek/Hydrograf/blob/main/docs/PROGRESS.md)
  and [backlog](https://github.com/Daldek/Hydrograf/blob/main/docs/BACKLOG.md)

## Development

`cd backend && uv sync --locked`, then `scripts/gate.sh` runs the checks (ruff, mypy, tests
with coverage, commit messages).
[CLAUDE.md](https://github.com/Daldek/Hydrograf/blob/main/CLAUDE.md) has the rules for
people and agents, and
[CONTRIBUTING.md](https://github.com/Daldek/Hydrograf/blob/main/CONTRIBUTING.md) the workflow
of a pull request.

## Status, licence, author

Pre-release: `develop` carries 0.5.0.dev0, the last release is 0.4.0. Licence: MIT
([LICENSE](https://github.com/Daldek/Hydrograf/blob/main/LICENSE)). Author:
[Piotr de Bever](https://www.linkedin.com/in/piotr-de-bever/).
