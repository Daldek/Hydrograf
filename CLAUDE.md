# Hydrograf: instructions for agents developing the project

Hydrograf is a web application for watershed delineation, catchment parameters and design
hydrographs in Poland: a FastAPI service over PostGIS, a static map front end and an admin
panel, built on Hydrolog (calculations), Kartograf (spatial data) and Obserwator
(precipitation). Profile `app` (DEV-1.1; `ecosystem.yaml` is authoritative).
Introduction: [README.md](README.md). The Nogat standard 1.1 is in
[standards/](https://github.com/Daldek/Nogat/tree/main/standards)
(DEVELOPMENT_STANDARDS, DOCUMENTATION_STANDARDS, AGENT_INTERFACE, ERROR_REGISTRY, COMPUTATIONS).

## Critical rules

- Work on a topic branch `<type>/<topic>` from `develop`; Conventional Commits in English
  with a scope (`feat(api): ...`, DEV-4.1); author `Daldek <git@debever.pl>` set per
  repository (DEV-4.2); no AI attribution in messages (DEV-4.3). Without the author's
  approval in the session never merge, tag, publish or rewrite shared history (DEV-3.3);
  pushing the topic branch is allowed.
- Run `scripts/gate.sh` before every commit and do not commit while it fails (DEV-7.6).
- A change of a public interface or across modules starts with a plan in
  `docs/plans/YYYY-MM-DD-slug.md` (DEV-17.4) that the author approves (`Approved:` line);
  decisions with alternatives are ADRs in `docs/DECISIONS.md` (DEV-17.2).
- Priorities, in this order: security of data (validate inputs, parameterised SQL, no
  secrets in the repository: DEV-13.1, DEV-13.4); clarity and simplicity (no premature
  abstraction); efficiency only where a measurement shows a problem. If the simpler
  solution is slower, take it; if the safer one is less readable, take the safer one.
- The runtime path is SQL over PostGIS plus the in-memory `CatchmentGraph` (ADR-001,
  ADR-021, ADR-022); rasters are processed only by the preprocessing pipeline in
  `backend/scripts/`. PostGIS is required.
- Hydrolog, Kartograf and Obserwator are used only through their public API. They are
  pinned in `[tool.uv.sources]` of `backend/pyproject.toml`, between releases by the commit
  of Nogat's current release set, in a release by their tags, with the ranges of REL-5.6 in
  `dependencies` (REL-5.3, REL-6.4, ADR-060, ADR-061). Obserwator (IMGWTools until its
  v3.0.0) is the distribution `obserwator` (`from obserwator import fetch_pmaxtp`, the
  `Obserwator*Error` exceptions). Kartograf writes into the store `cache/kartograf/`
  (ADR-061): every script passes `root=` and `cache=` explicitly. A missing function is a
  GitHub issue labelled `request` in the producer's repository (DEV-17.5), not a workaround.
- The SCS-CN method is valid for catchments up to 250 km²; the API memory limit is 8 GB.
- Python only from `backend/.venv`, through `uv run` in `backend/` (DEV-6.2).
  `backend/uv.lock` is committed; install with `uv sync --locked` (DEV-6.3).
- Data and caches stay outside Git: `data/` and `cache/` are ignored; never put downloaded
  data or temporary files in the repository.
- Code, identifiers, comments, docstrings, logs, commit messages, ADRs, plans and documents
  are English (DEV-2.1); the user interface is Polish (DEV-2.2). New and edited text is
  English; what is still Polish is listed in `docs/PROGRESS.md`.
- Errors: raise a `HydrografError` subclass (`core/errors.py`) with a message ID of the
  catalogue `core/messages.py` (English and Polish text) and a `reason`; never an
  `HTTPException`, never a code outside the registry (ERR-1). `core/_errors.py` is generated:
  `uv run python -m scripts.generate_errors` after the registry in `schemas/nogat/` changes.
- Names carry units: `area_km2`, `elevation_m`, `discharge_m3s`, `time_concentration_min`,
  `slope_percent`, `precipitation_mm`, `length_km` (DEV-8.2).
- Front end: colours, fonts, radii and shadows come only from the variables of
  `frontend/css/tokens.css` (ADR-065). That file and `frontend/nogat/` (Nogat's GUI kit and
  marks: the menu „Aplikacje”, the hand-off, the strip of sources, the base maps, the
  regulamin template, the admin page's shell; ADR-082, ADR-089) are copies of Nogat's, never
  edited here: change them in Nogat, then copy them again byte for byte (DEV-15.6).
  Third-party scripts, styles and fonts are vendored in `frontend/vendor/<package>-<version>/`
  as published (`-text` in `.gitattributes`), with their licence files and their `integrity`,
  never loaded from another origin (DEV-15.7; `tests/contract/test_frontend_vendor.py`).
- After changing a JS or CSS file or adding a `<script>` or `<link>` to `index.html`,
  `admin/index.html` or `instrukcja/index.html`, run `python3 scripts/bump_asset_versions.py`
  before the commit (reference a new file without `?v=`; the script adds it): the pages load
  their assets as `?v=<content hash>` to get past the caches of Cloudflare and of the
  browsers. The gate and the CI job `frontend-assets` run it with `--check`.
- Public service (ADR-084): the client's address never reaches the front end or any log,
  not even in a traceback (DEV-15.10, DEV-12.5); it lives only in the memory of
  `api/traffic.py`. `core/nogat_logging.py` is a copy of Nogat's module, never edited here.
  The request limit and the daily totals are per process, so the API runs one uvicorn
  process (no `--workers`); a change that needs more processes needs a shared store first.
- A change that users see ships with its `docs/CHANGELOG.md` entry in the same commit
  (DOC-7.2); `docs/PROGRESS.md` is updated before the last commit of a session (DEV-17.3).

## Environment and commands

```bash
cd backend && uv sync --locked          # environment in backend/.venv
scripts/gate.sh                         # ruff format, ruff check, mypy, pytest + coverage, asset versions, commits
uv run pytest tests/unit -q             # in backend/: a part of the tests, no coverage
uv run pytest tests/e2e -m e2e          # in backend/: the browser tests (PostGIS; once: uv run playwright install chromium)
docker compose up -d db                 # PostGIS for development and for the `db` and `e2e` tests
uv run alembic upgrade head             # in backend/: migrations
uv run uvicorn api.main:app --reload    # in backend/: API on :8000
uv run python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4"   # one-off preprocessing
```

Python 3.12 or newer. The default run and the gate leave out the markers `live`, `db`,
`benchmark` and `e2e`; `slow` is registered and not used yet (DEV-10.1). Coverage floor:
`fail_under = 80` in `backend/pyproject.toml` (DEV-7.5).

Running the service: the stack runs on the system Docker daemon (the agent user is in the
`docker` group; rootless Docker does not start here, so leave `DOCKER_HOST` unset).
`docker compose up -d` serves the stack on port 8080 with `docker-compose.override.yml`
(`--reload`, `./backend:/app` mounted, `read_only` off); never add `user:` to the override:
it clashes with `cap_drop: ALL` and breaks file operations. Production and the other
deployment steps: README "Deploy" and `docs/USAGE.md`.

## Code map

```
backend/                 # the Python project: pyproject.toml, uv.lock, .venv (not a package)
├── api/                 # FastAPI: main.py, errors.py, traffic.py, endpoints/, dependencies/
├── core/                # business logic, config, database, errors, messages, _errors
├── models/schemas.py    # Pydantic request and response models
├── scripts/             # preprocessing CLI (bootstrap.py is the orchestrator), README.md
├── utils/               # geometry, raster, sheet and NMT-coverage helpers, the Kartograf
│                        #   store, the Archiwista project
├── migrations/          # Alembic
└── tests/               # unit, integration, contract, performance, e2e, fixtures
frontend/                # static HTML, CSS and vanilla JS (IIFE modules on window.Hydrograf);
                         #   admin/, instrukcja/, nogat/ (Nogat's copies), vendor/
docker/ docker-compose*.yml   # nginx configuration, PostGIS, API and web containers
scripts/                 # gate.sh, check-commits.sh, bump_asset_versions.py, staging-compose.sh
docs/                    # documentation
```

The full module map is in `docs/ARCHITECTURE.md` (backend §2.1, frontend §4.1).

## Documentation map

| For | Read |
|---|---|
| Current state, next steps | [docs/PROGRESS.md](docs/PROGRESS.md) |
| Configuration, admin key, second instance, service logs | [docs/USAGE.md](docs/USAGE.md) |
| Scope (in and out), product requirements | [docs/SCOPE.md](docs/SCOPE.md), [docs/PRD.md](docs/PRD.md) |
| Architecture, database schema | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DATA_MODEL.md](docs/DATA_MODEL.md) |
| Decisions | [docs/DECISIONS.md](docs/DECISIONS.md) (index; ADR-001 to 057), [docs/decisions/](docs/decisions/) (ADR-058 and later) |
| The producers | [docs/integrations/](docs/integrations/) (KARTOGRAF, HYDROLOG, OBSERWATOR), [docs/CROSS_PROJECT_ANALYSIS.md](docs/CROSS_PROJECT_ANALYSIS.md) |
| Calculations | [docs/COMPUTATION_PIPELINE.md](docs/COMPUTATION_PIPELINE.md) |
| Open items | [docs/BACKLOG.md](docs/BACKLOG.md), [docs/TECHNICAL_DEBT.md](docs/TECHNICAL_DEBT.md) |
| Preprocessing scripts | [backend/scripts/README.md](backend/scripts/README.md) |
| Changes for users | [docs/CHANGELOG.md](docs/CHANGELOG.md) |

## Session workflow

Start (DEV-17.1): read this file and `docs/PROGRESS.md`, run `git status` and
`git log --oneline -10`, confirm the branch, list the open GitHub issues labelled
`request`. End (DEV-17.3): update `docs/PROGRESS.md` (Status, Next, Open questions) before
the last commit. Change only this repository (DEV-17.5).

Large tasks are split into small logical pieces, each worked in a cycle: research the code,
implement, then run the tests and lint; the next piece starts when the tests pass. A
sub-agent gets the full context of its piece (goal, files, constraints, the `.venv` and
Docker notes above); independent pieces run in parallel.

## Cross-project context

Registry entry: [ecosystem.yaml](https://github.com/Daldek/Nogat/blob/main/ecosystem.yaml)
(Hydrograf). Kartograf (NMT download, land cover, HSG), Hydrolog (hydrographs, concentration
time) and Obserwator (PMAXTP precipitation) are runtime dependencies used as libraries
(Critical rules); Hydraulik is a planned compute node.

## Deviations

- DEV-2.1: the Python docstrings, comments and log messages, the user-facing texts of the
  API, and the documents under `docs/` that `docs/PROGRESS.md` lists are still Polish until
  they are translated.
- DEV-5.2: `tests/performance` (timing tests that need the database) and `tests/e2e` (the
  browser tests, one Chromium per package) stand beside the standard tree.
- DEV-6.2: the environment is `backend/.venv`, not `.venv` in the repository root: the
  Python project is `backend/`.
- DEV-6.3: GDAL's Python binding must equal the system library of the image, so the
  Dockerfile installs it after `uv sync --locked`; it is not in `uv.lock`.
- DEV-7.2: `E501` is off in `migrations/versions/*` (28 single-line DDL strings of
  `001_initial_schema.py`).
- DEV-7.3: `migrations/` is excluded from mypy. Packages without type information
  (`affine`, `fiona`, `geopandas`, `jsonschema`, `pandas`, `psutil`, `pyflwdir`, `rasterio`,
  `scipy`, `shapely`, `yaml`) are per-module `ignore_missing_imports` overrides; Hydrolog,
  Kartograf and Obserwator ship `py.typed` at the pinned heads, so their calls are checked.
  `tests.*` allows untyped definitions and calls and
  does not check the bodies of untyped functions (about 2,100 of them); `scripts.*` allows
  untyped definitions and calls (46 findings) and its annotated code is checked. To lift an
  override, annotate the module and delete its line in `pyproject.toml`.
- DEV-7.5: the floor of 80% measures `api`, `core`, `models` and `utils` (the offline
  suite covers 85%; the SQL over PostGIS that is left runs in the `db` job). `scripts/`
  (the preprocessing pipeline, run by hand on real data) and `migrations/` are not
  measured.
- DEV-7.7: CI runs on Linux only: Hydrograf is deployed with Docker on Linux, and an `app`
  MAY skip the platform matrix.
- DEV-10.1: markers besides `live`, `db` and `slow`: `benchmark` (`tests/performance`) and
  `e2e` (`tests/e2e`); the gate leaves them out, the `db` and `e2e` jobs of CI run theirs.
- DEV-12.3: about half of the 780 log calls use f-strings; new log calls use
  `%`-style arguments.
- DEV-14.2, DEV-15.1: the front end, nginx files and shell scripts use 4-space indentation;
  the JavaScript is IIFE modules on `window.Hydrograf`, not ES modules, but `js/nogat.js`
  (imports Nogat's kit, ADR-082), `admin/processing.js` (imports `nogat-basemaps.js`
  dynamically, ADR-089) and the kit's copies in `frontend/nogat/`, which keep Nogat's 2
  spaces; about 560 lines of its own JavaScript exceed 100 columns.
- DEV-15.2: the Polish UI text is inline in the JavaScript and HTML, not in resources.
- DEV-15.13: the admin `img-src` admits `data:`, Leaflet's removed tiles, until MapLibre.
- DEV-16.2: `docs/CLA.md` is missing until the author supplies the text.
- DEV-18, DEV-19: profile `tool` only; settings from the environment (`.env.example`) and
  from the `nogat.toml` NOGAT_CONFIG names (`[nogat.operator]`, `[nogat] gui`; `state_dir`,
  `basemaps`, `basemap_mirrors`, `basemap_extra` of `[hydrograf]` or `[nogat]`); data
  through Kartograf in the pipeline scripts.
- AGI-4.1, AGI-4.2: REST responses are the Pydantic models of the endpoints, with no
  `schema` member and no result envelope; the error document alone is
  `application/problem+json`, and the vendored `result-1`, `error-1` and `commands-1`
  schemas are unused.
- AGI-6.1, AGI-6.2: there is no command catalog; `operationId` is the route function name
  and the operations document `400`, the problems of their route and `500`.
- AGI-6.3: the gateway errors of nginx are not problem documents.
