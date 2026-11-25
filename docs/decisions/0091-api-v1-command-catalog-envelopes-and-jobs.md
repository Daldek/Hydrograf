# ADR-091: The API at /api/v1: a command catalog, result envelopes and jobs

**Date:** 2026-11-25
**Status:** accepted (step HG1 of Nogat's plan `docs/plans/2026-11-24-latarnik.md`, approved
by the author on 2026-11-24 with the answers to its questions 1 to 6; Nogat ECO-095 and AGI
§6 of the standard in preparation, Nogat `develop` f5f6e67). Amends ADR-050, ADR-059,
ADR-080, ADR-081, ADR-084 and ADR-086.

## Context

Hydrograf's REST API was a set of routes under `/api/` that had grown with the interface:
`POST /api/delineate-watershed`, `POST /api/generate-hydrograph`, `GET /api/scenarios`,
`GET /api/identify-point` and so on. Their answers were the Pydantic models of the
endpoints, with no `schema` member and no envelope; `operationId` was the route function's
name; there was no command catalog; a hydrograph of a large catchment ran inside one
request, under nginx's 120 s; and the client's address came from Cloudflare's
`CF-Connecting-IP`, believed only when nginx's `X-Real-IP` was a private hop. `CLAUDE.md`
listed these as deviations from AGI-4.1, AGI-4.2, AGI-6.1 and AGI-6.2.

Nogat's plan for Latarnik (the ecosystem's access point) makes every tool's server speak
one API: a catalog of `<group> <verb>` commands served at `/api/v1/<group>/<verb>` (AGI-6.1),
OpenAPI at `/api/v1/openapi.json` (AGI-6.2), `nogat-server/1` at `GET /api/v1/server`
(AGI-6.7), the client's address from the right-most `X-Forwarded-For` entry that is no
trusted proxy (AGI-6.9), and the long commands as jobs, `nogat-job/1` (AGI-6.10). Its flow F1
also needs a catchment's design depth from Hydrograf as a command of its own (the plan's
question 4), so that one point gives one design depth in the ecosystem. Step HG1 is
Hydrograf's: its catalog and `/api/v1`, the envelope, jobs, the design depth, `X-Forwarded-For`
through its nginx, the frontend on `/api/v1` and `/api` removed, in one minor after `0.6.0`.

## Options considered

- **A: `/api/v1` from a catalog, `/api` removed in the same release** (chosen, as the plan
  says): one API, the frontend moved with it, the routes of `ecosystem.yaml` changed with
  it by Nogat's N2.
- **B: `/api/v1` beside the old `/api` for a release.** Rejected: Hydrograf is `0.x`
  (a minor may break, REL-1.1); its one known client is its own frontend, which moves in
  the same commit; two route sets would double the limit's paths, the tests and the
  OpenAPI document for no user.
- **C: keep the routes and add an envelope.** Rejected: the names, the methods, the
  operation ids and the long runs would still differ from every other tool behind Latarnik.

For the client's address:

- **`X-Forwarded-For` with `$proxy_add_x_forwarded_for`, right-most non-private hop**
  (chosen, AGI-6.9): the same rule behind the Cloudflare Tunnel, behind Latarnik and alone.
- **Keep `CF-Connecting-IP`.** Rejected: only Cloudflare sends it; behind Latarnik every
  client would be one address at the limit (the plan's risk table).

For the catalog's `function` and `examples[].call` of an `app` without a command line:

- **`function` the dotted path of the backend function, `call` the HTTP call** (chosen):
  the method, the path with its query and, for a POST, the JSON body on the same line; a
  long command's example is the start of its job. An agent reads what it would send.
- **A CLI-shaped call (`hydrograf watershed delineate --latitude …`).** Rejected: there is
  no such program; an example must run as written (DOC-2.6).

## Decision

1. **The catalog** (`backend/api/catalog.py`, `hydrograf-commands/1`): 14 commands, each
   with its name, the function that runs it, the Pydantic model of its options (from which
   the options' types, units, bounds, defaults, enums and descriptions are derived), its
   domain document `hydrograf-<kind>/1`, its route, its texts in English and Polish, its
   rules, examples and the registry codes it answers. `GET /api/v1/commands/list` gives the
   summary `hydrograf-command-list/1` (each entry with its `rest`: method, path, key) and
   `GET /api/v1/commands/schema` the catalog, or one command's entry (`?command=`;
   `400 unknown_command` for a name it lacks). Every command is read-only and needs no key.

   | Command | Route (prefix `/api/v1`) | Before |
   |---|---|---|
   | `watershed delineate` | `GET /watershed/delineate` | `POST /api/delineate-watershed` |
   | `watershed preview` | `GET /watershed/preview` | `POST /api/delineate-watershed/preview` |
   | `network delineate` (long) | `POST /jobs` | `POST /api/delineate-network` |
   | `network preview` | `POST /network/preview` | `POST /api/delineate-network/preview` |
   | `hydrograph generate` (long) | `POST /jobs` | `POST /api/generate-hydrograph` |
   | `hydrograph scenarios` | `GET /hydrograph/scenarios` | `GET /api/scenarios` |
   | `precipitation depth` | `POST /precipitation/depth` | new |
   | `terrain profile` | `POST /terrain/profile` | `POST /api/terrain-profile` |
   | `point identify` | `GET /point/identify` | `GET /api/identify-point` |
   | `depressions list` | `GET /depressions/list` | `GET /api/depressions` |
   | `layers availability` | `GET /layers/availability` | `GET /api/layers` |
   | `layers thresholds` | `GET /layers/thresholds` | `GET /api/tiles/thresholds` |
   | `commands list`, `commands schema` | `GET /commands/list`, `GET /commands/schema` | new |

   The delineation and its preview are `GET` with query parameters, since a point fits in
   a URL (AGI-6.1); the network, the hydrograph, the profile and the design depth take a
   JSON body. The routes outside the catalog moved under the same base: `GET /server`
   (`nogat-server/1`), the jobs, `POST /feedback`, `GET /gui`, `GET /basemaps`,
   `GET /terms`, `POST /downloads`, and the admin API at `/api/v1/admin/*`.
2. **The envelope** (`backend/api/envelope.py`, `hydrograf-result/1`, Nogat's
   `result-1`): `{status, result, notices}`, where `result` is the former answer with its
   `schema` as the first member. The AGI-4.2 notices of the delineation and of the
   hydrograph (an outlet far from the point, Hydrolog's warnings) moved into the
   envelope's `notices`; the network keeps its own `notices` inside `result`, since they
   name its points and reaches.
3. **Jobs** (`backend/api/jobs.py`, `nogat-job/1`). `hydrograph generate` and `network
   delineate` carry `long: true`; their routes check the body and answer `409 conflict`,
   reason `run_as_job`. `POST /api/v1/jobs` with `{"command", "options"}` checks the
   options as the route would and answers `202` with the job and `Location: jobs/<id>`;
   `GET /jobs/<id>` follows it, `GET /jobs/<id>/result` gives the envelope (or the problem
   of a failed run; `409 job_running` before it ends), `POST /jobs/<id>/cancel` cancels it.
   A command that is not long answers `400 validation_error`, reason `not_a_job`. Jobs
   live in the process's memory (their options and results never on disk, ECO-059), ids
   of 128 random bits in hex; an
   ended job is kept one hour, then `404 not_found`, reason `job_expired`. At most 4 run at
   once, each in a daemon thread with its own database session; a client holds at most 2
   active jobs (`api.traffic.JobSlots`), beyond that `429 rate_limited`, reason
   `job_limit`, `Retry-After: 10`. The ids and times of the active jobs are written to
   `<state_dir>/hydrograf/jobs.json`, so that the next start marks them `interrupted`
   (their result `409 job_interrupted`). A cancelled job's result is an envelope with
   `status: cancelled` and `result: null`. The network lock waits 600 s instead of 15 s,
   since a job has no proxy timeout.
4. **The design depth** (`backend/api/endpoints/precipitation.py`, `precipitation
   depth`): `boundary` (a GeoJSON Feature, Polygon or MultiPolygon in WGS84),
   `duration_min` and `probability_percent` (the enums of the PMAXTP tables); the answer
   `hydrograf-design-depth/1` holds `pmaxtp_depth_mm` unrounded, the duration and the
   probability, `interpolation` (`thiessen`), `area_km2`, `pmaxtp_points` and the lines of PMAXTP
   (`attribution`, `terms_notice`). It is the depth `hydrograph generate` takes for the
   same watershed and scenario (`core.precipitation`'s `thiessen_cells` and
   `areal_depth`, ADR-069), so a hydrograph made from it by Hydrolog
   equals Hydrograf's own. `422 unsupported`, `boundary_too_large`, above 10 000 km²;
   `404 no_data`, `no_design_depth_data`, without PMAXTP points.
5. **OpenAPI** at `/api/v1/openapi.json`: paths relative to the base, `servers`
   `[{"url": "../v1"}]`, each command's `operationId` `hydrograf_<group>_<verb>`, its error
   responses generated from the catalog's codes. A problem document of a command route or
   a job's result carries `command`.
6. **The client's address** (`backend/api/traffic.py`, AGI-6.9): when the peer is a
   loopback or private hop, the API takes the right-most `X-Forwarded-For` address that is
   no such hop; a public peer is the client itself. `X-Real-IP` and `CF-Connecting-IP` are
   not read. nginx (`docker/nginx.conf`, `docker/nginx-ssl.conf.template`) sends
   `X-Forwarded-For $proxy_add_x_forwarded_for` on every proxied location and no
   `X-Real-IP`; its locations are `/api/v1/`, `/api/v1/admin/` (50 MB body limit),
   `= /api/v1/admin/bootstrap/stream` (the SSE, 3600 s, unbuffered), `/api/tiles/`,
   the pages and `/health`. `/api/` and `/api/admin/` are gone: no location proxies them,
   so an old route reaches the static files' rules (`try_files`, the map page).
7. **The tiles stay at `/api/tiles/{layer}/{z}/{x}/{y}.pbf`**, the one path below `/api/`
   outside `/api/v1`: they are no command (binary MVT of the map, no envelope, no options
   an agent would choose), the map's style and cache key their URLs, and they keep their
   own limit (ten times the general one) and their quiet access log. Their thresholds, data
   an agent does read, are the command `layers thresholds`.
8. **The frontend** calls `/api/v1` throughout and reads envelopes (`js/api.js`); the
   hydrograph and the network run as jobs, polled after 300 ms and then every second, and
   cancelled when a newer run replaces them. The admin page sets `api="../api/v1/admin/"`
   on the kit's `<nogat-admin>`.

## Consequences

- Hydrograf meets AGI-4.1, AGI-4.2, AGI-6.1, AGI-6.2, AGI-6.7, AGI-6.9 and AGI-6.10; the
  deviations of `CLAUDE.md` for them are gone. Only the gateway errors of nginx (502, 504)
  stay outside the problem documents (AGI-6.3).
- Breaking for every client of `/api/*` but the tiles: a `0.x` minor (REL-1.1). Nogat's N2
  changes Hydrograf's routes in `ecosystem.yaml`.
- A deployment behind Cloudflare Access protects `/api/v1/admin/*` instead of
  `/api/admin/*`, and a deployment's own nginx file needs the new locations and
  `X-Forwarded-For`; without it every client shares nginx's address and one limit.
- A hydrograph or a network no longer ends at nginx's 120 s; a server restart interrupts
  the running jobs, which the client starts again.
- Two clients behind one proxy are counted apart by the request limit and the job limit
  (`backend/tests/integration/test_traffic.py`).
- The catalog, its list, the envelopes, the server and job documents and OpenAPI are
  checked against Nogat's schemas by `backend/tests/contract/test_catalog.py` and
  `test_openapi.py`.
- ADR-050, ADR-080 and ADR-081 keep their computations; their routes are the commands
  above. ADR-059's `operationId` is the catalog's and its 429 also has `job_limit`.
  ADR-084's client address is `X-Forwarded-For`'s. ADR-086's admin paths are `/admin`,
  `/admin/` and `/api/v1/admin/*`.
