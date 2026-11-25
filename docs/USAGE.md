# Operating Hydrograf

The configuration, the admin key, a second instance and the service logs of a Hydrograf
deployment. Starting the stack, the preprocessing, the first requests, the public service
and the admin panel are in [README.md](../README.md); the REST API is described by the
OpenAPI document of a running instance (`/openapi.json`, with `/docs` as the interactive
page).

## Configuration

Every variable is listed in [`.env.example`](../.env.example): the database
(`POSTGRES_*`, `DATABASE_URL`, `DB_STATEMENT_TIMEOUT_MS`), the API (`LOG_LEVEL`,
`CORS_ORIGINS`, `DEM_DIR`, `DEM_PATH`, `STREAM_DISTANCE_PATH`, `FRONTEND_DATA_DIR` for the
manifest of the analysis results and `instance.json`), the admin key
(`ADMIN_API_KEY` for development or the file named by `ADMIN_API_KEY_FILE`, read on every
request; without either, every admin route refuses with `admin_key_not_configured`; for
Docker Compose `ADMIN_API_KEY_HOST_FILE` and `HYDROGRAF_SECRETS_GID`), the shared Kartograf
store (`HYDROGRAF_KARTOGRAF_ROOT`, read only
through a closed set of an Archiwista project, `bootstrap --project --set`), the other GUIs of
the ecosystem that the top bar's „Aplikacje” lists (`HYDROGRAF_GUI`, a JSON object such as
`{"hydrolog": "http://127.0.0.1:8070/"}`; without it the table `gui` of `[nogat]` in the file
of `NOGAT_CONFIG`, and without both there is no menu), the public service (`NOGAT_CONFIG`, the
deployment's `nogat.toml`; `HYDROGRAF_REQUEST_LIMIT` and `HYDROGRAF_REQUEST_WINDOW`, 300
requests in 60 s per client address by default; `HYDROGRAF_DATA_DIR`, the directory of the
daily statistics, `/data` in Docker), the base maps (`HYDROGRAF_BASEMAPS`, `NOGAT_BASEMAPS`;
see [Base maps](#base-maps)), the logs (`HYDROGRAF_STATE_DIR`, then `NOGAT_STATE_DIR`,
then `state_dir` of `[hydrograf]` or `[nogat]` in the file of `NOGAT_CONFIG`, by default
`~/.local/state/nogat`; for Docker Compose `NOGAT_STATE_DIR` is the host's directory) and
Docker Compose
(`HYDROGRAF_PORT`, `SERVER_NAME`, `SECRETS_DIR`, `ADMIN_API_KEY_HOST_FILE`,
`HYDROGRAF_SECRETS_GID`, and the names and host paths of an instance:
`HYDROGRAF_CONTAINER_PREFIX`, `HYDROGRAF_*_PATH`). Secrets come from the environment or from
files outside the checkout (the admin key), and `.env` is not committed.

## The admin key

The admin key of a deployment lives in one file of the host, never as a value in `.env`, a
unit file or compose: `~/.config/nogat/keys/hydrograf-admin.key`, the key alone. The API's
container runs as UID 999, so the file gets mode 0640 and a group the container joins
(`install -m 0640 -g GROUP /dev/null ~/.config/nogat/keys/hydrograf-admin.key`, then write
the key into it), and `.env` names the file and the group's numeric id (`stat -c %g FILE`):
`ADMIN_API_KEY_HOST_FILE=/home/USER/.config/nogat/keys/hydrograf-admin.key` and
`HYDROGRAF_SECRETS_GID=GID`. Compose mounts the file read-only at
`/run/secrets/admin_api_key`, sets `ADMIN_API_KEY_FILE` to it and adds the group to the
container's user; the production overlay refuses to start without `ADMIN_API_KEY_HOST_FILE`
and ignores `ADMIN_API_KEY`, which is for development only (it wins over the file). The file
is read on every request, so a new key needs no restart.

## `nogat.toml` and the state directory

A public deployment names its `nogat.toml` (Nogat DEV-18.1) in `.env`:
`NOGAT_CONFIG=/home/USER/.config/nogat/nogat.toml`, which Compose mounts read-only into the
API at `/config/nogat.toml`. With the table `[nogat.operator]` in that file Hydrograf is a
public service with its regulamin at `/regulamin.html` (see
[Public service](../README.md#public-service)); without it there is no regulamin and no link
„Regulamin”. On the Docker host, name the state directory of the logs in `.env` too,
`NOGAT_STATE_DIR=/home/USER/.local/state/nogat`, and create the API's directory in it once,
writable by the container's user (UID 999) as `data/` is:
`install -d -m 0777 ~/.local/state/nogat/hydrograf` (without `NOGAT_STATE_DIR` Compose
mounts `./state/hydrograf` of the checkout, which needs the same; see
[Service logs](#service-logs)).

## Base maps

The map offers the base maps of Nogat's kit, the entries of `frontend/nogat/nogat-basemaps.json`
(`openfreemap` „OpenFreeMap szary”, the default; `gugik-osm` „OSM GUGiK szary (tylko
Polska)”; `gugik-ortho` „Ortofotomapa GUGiK”), every entry by default (Nogat DEV-15.15,
ADR-089). A deployment chooses in its `nogat.toml`, in `[hydrograf]` or, shared by the GUIs
of the deployment, in `[nogat]` (the first section that has the key wins):

```toml
[hydrograf]
# the catalogue's ids the map offers, in the catalogue's order; [] offers none
basemaps = ["openfreemap", "gugik-ortho"]
# a copy the deployment serves in a provider's place: the catalogue id to its address
basemap_mirrors = { openfreemap = "https://tiles.example.org/planet" }

# a base map of the deployment's own, after the catalogue's entries
[[hydrograf.basemap_extra]]
id = "powiat-ortho"                 # unique, not "none", not a catalogue id
name = "Ortofotomapa powiatu"       # its label in the list
kind = "wms"                        # xyz, wms or vector (a TileJSON)
url = "https://maps.example.org/wms?SERVICE=WMS&VERSION=1.3.0&LAYERS=orto&FORMAT=image/png"
attribution = "Ortofotomapa © Starostwo Powiatowe"
grayscale = false                   # optional
```

For an API run on the host, `HYDROGRAF_BASEMAPS`, then `NOGAT_BASEMAPS` (ids joined by `,`,
for example `HYDROGRAF_BASEMAPS=openfreemap,gugik-osm`) win over `basemaps` of the file; set
but empty, they offer none. Docker Compose passes neither, so a deployment sets the keys in
its `nogat.toml`; `basemap_mirrors` and `basemap_extra` are set only there. The API reads
them once at start and answers them at `GET /api/basemaps`; a change needs a restart. An
unknown id or a wrong value stops the API at start: it prints the error document
`hydrograf-error/1` on standard error (`docker logs hydro_api`), with `validation_error`
and `details` naming the option, the value, where it was read and why, for example
`basemap_unknown` for an id the catalogue lacks; an unreadable catalogue stops it too
(`basemap_catalogue_unreadable`). The regulamin keeps the block `osm` only while
`openfreemap` or `gugik-osm` is offered.

The Content-Security-Policy of `docker/nginx.conf` and `docker/nginx-ssl.conf.template` names
the catalogue's origins, `https://tiles.openfreemap.org` and `https://mapy.geoportal.gov.pl`,
whatever `basemaps` allows: nginx does not read `nogat.toml`. A deployment with a copy or an
own base map adds its origin (`https://tiles.example.org`, `https://maps.example.org` above)
to `img-src` and `connect-src` of the page's policy in the nginx file its nginx runs (Compose
mounts `docker/nginx.conf` of the checkout at `/etc/nginx/nginx.conf`; an override of the
instance may mount its own file there); without it the browser refuses its tiles.

## A second instance

A second instance runs beside the first on the same Docker host from its own checkout, with
its own compose project and env file:

```bash
docker compose -p NAME --env-file NAME.env up -d   # with -f ... as in the README for production
```

`NAME.env` holds the instance's settings (`POSTGRES_PASSWORD`, `SECRETS_DIR` and so on) and
its names: `HYDROGRAF_CONTAINER_PREFIX` (containers `<prefix>_db`, `<prefix>_api`,
`<prefix>_nginx`; default `hydro`), a free `HYDROGRAF_PORT`, and the host directories
`HYDROGRAF_CACHE_PATH`, `HYDROGRAF_DATA_PATH`, `HYDROGRAF_FRONTEND_DATA_PATH` and
`HYDROGRAF_FRONTEND_TILES_PATH` (defaults `./cache`, `./data`, `./frontend/data`,
`./frontend/tiles`), and its own `NOGAT_STATE_DIR` with a `hydrograf` directory writable by
UID 999, so that its logs stay apart from the first instance's. The database volume and the
network take the project's name (`NAME_postgres_data`, `NAME_default`). nginx mounts the
instance's directories at `frontend/data` and `frontend/tiles` inside its read-only
`./frontend`; every checkout has the two directories (each holds a tracked `.gitkeep`).

## One-off scripts in the image

The entrypoint of the image (`backend/entrypoint.sh`) waits for the database and runs
`alembic upgrade head` before its command only when the container is given a database:
`DATABASE_URL`, which Docker Compose gives the API and its one-off containers, or
`POSTGRES_HOST`. `docker compose run --rm api python -m scripts.<name>` therefore migrates
first, while `docker run --rm <image> python -m scripts.<name>` without either, for a script
that needs no database (`scripts.write_instance_info`, `--help`), starts at once.

## Service logs

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
`<data_dir>/hydrograf/stats.jsonl` (DEV-15.11, see
[Public service](../README.md#public-service)), never from the logs.

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
