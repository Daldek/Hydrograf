# Hydrograf: instructions for agents developing the project

Hydrograf is a web application for watershed delineation, catchment parameters and design
hydrographs in Poland: a FastAPI service over PostGIS, a static map front end and an admin
panel, built on Hydrolog (calculations), Kartograf (spatial data) and IMGWTools
(precipitation). Profile `app` (DEV-1.1; `ecosystem.yaml` is authoritative).
Introduction: [README.md](README.md). The Nogat standard 2.1 is in
[standards/](https://github.com/Daldek/Nogat/tree/main/standards)
(DEVELOPMENT_STANDARDS, DOCUMENTATION_STANDARDS, AGENT_INTERFACE, ERROR_REGISTRY).

## Critical rules

- Work on a topic branch `<type>/<topic>` from `develop`; Conventional Commits in English
  with a scope (`feat(api): ...`, DEV-4.1); author `Daldek <git@debever.pl>` set per
  repository (DEV-4.2); no AI attribution in messages (DEV-4.3). Without the author's
  approval in the session never merge, tag, publish or rewrite shared history (DEV-3.3);
  pushing the topic branch is allowed.
- Run `scripts/gate.sh` before every commit and do not commit while it fails (DEV-7.6).
  The commit step fails on commits of `develop` that predate the history rewrite: use
  `GATE_COMMIT_RANGE=develop..HEAD scripts/gate.sh` until the author has rewritten it.
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
- Hydrolog, Kartograf and IMGWTools are dependencies used through their public API, pinned
  by release tag in `backend/pyproject.toml` until the first release set (REL-5.1). A
  missing function is a GitHub issue labelled `request` in the producer's repository
  (DEV-17.5), not a workaround here.
- The SCS-CN method is valid for catchments up to 250 km²; the API memory limit is 8 GB.
- Python only from `backend/.venv`, through `uv run` in `backend/` (DEV-6.2).
  `backend/uv.lock` is committed; install with `uv sync --locked` (DEV-6.3).
- Data and caches stay outside Git: `data/` and `cache/` are ignored; never put downloaded
  data or temporary files in the repository.
- Code, identifiers, comments, docstrings, logs, commit messages, ADRs, plans and documents
  are English (DEV-2.1); the user interface is Polish (DEV-2.2). Much of the code and the
  documents are still Polish: `docs/PROGRESS.md` lists what remains. New and edited text is
  English.
- Names carry units: `area_km2`, `elevation_m`, `discharge_m3s`, `time_concentration_min`,
  `slope_percent`, `precipitation_mm`, `length_km` (DEV-8.2).
- A change that users see ships with its `docs/CHANGELOG.md` entry in the same commit
  (DOC-7.2); `docs/PROGRESS.md` is updated before the last commit of a session (DEV-17.3).

## Environment and commands

```bash
cd backend && uv sync --locked          # environment in backend/.venv
scripts/gate.sh                         # ruff format, ruff check, mypy, pytest + coverage, commits
uv run pytest tests/unit -q             # in backend/: a part of the tests, no coverage
docker compose up -d db                 # PostGIS for development and for the `db` tests
uv run alembic upgrade head             # in backend/: migrations
uv run uvicorn api.main:app --reload    # in backend/: API on :8000
uv run python -m scripts.bootstrap --bbox "20.8,52.1,21.2,52.4"   # one-off preprocessing
```

Python 3.12 or newer. The default run and the gate leave out the markers `live`, `db` and
`benchmark`; `slow` is registered and not used yet (DEV-10.1). Coverage floor:
`fail_under` in `backend/pyproject.toml` (see Deviations).

Running the service. The agent user is not in the `docker` group and uses rootless Docker:
start `dockerd-rootless.sh` if the daemon is down, `export
DOCKER_HOST=unix://$HOME/.docker/run/docker.sock`, then `docker compose up -d` serves the
full stack on port 8080. In development `docker-compose.override.yml` is loaded
automatically (`--reload`, `./backend:/app` mounted, `read_only` off); production uses
`docker compose -f docker-compose.yml up -d`. Never add `user:` to the override: it clashes
with `cap_drop: ALL` and breaks file operations. Access from the local network needs a UFW
rule (rootless Docker does not touch iptables); outside access goes through a Cloudflare
Tunnel (`cloudflared tunnel --url http://localhost:8080`).

## Code map

```
backend/                 # the Python project: pyproject.toml, uv.lock, .venv (not a package)
├── api/                 # FastAPI: main.py, endpoints/ (watershed, hydrograph, tiles, profile,
│                        #   depressions, feedback, health, admin), dependencies/ (admin key)
├── core/                # business logic: watershed, catchment_graph, hydrology, morphometry,
│                        #   cn_calculator, raster_service, sewer_*, config, database
├── models/schemas.py    # Pydantic request and response models
├── scripts/             # preprocessing CLI (bootstrap.py is the orchestrator), README.md
├── utils/               # geometry, raster and sheet-lookup helpers
├── migrations/          # Alembic
└── tests/               # unit, integration, contract, performance, fixtures
frontend/                # static HTML, CSS and vanilla JS (IIFE modules on window.Hydrograf)
docker/ docker-compose*.yml   # nginx configuration, PostGIS, API and web containers
scripts/                 # gate.sh, check-commits.sh, verify_cdn_hashes.sh
docs/                    # documentation
```

The full module map is in `docs/ARCHITECTURE.md` (backend §2.1, frontend §4.1).

## Documentation map

| For | Read |
|---|---|
| Current state, next steps | [docs/PROGRESS.md](docs/PROGRESS.md) |
| Scope (in and out), product requirements | [docs/SCOPE.md](docs/SCOPE.md), [docs/PRD.md](docs/PRD.md) |
| Architecture, database schema | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DATA_MODEL.md](docs/DATA_MODEL.md) |
| Decisions | [docs/DECISIONS.md](docs/DECISIONS.md) (ADR index at the top) |
| The producers | [docs/integrations/](docs/integrations/) (KARTOGRAF, HYDROLOG, IMGWTOOLS), [docs/CROSS_PROJECT_ANALYSIS.md](docs/CROSS_PROJECT_ANALYSIS.md) |
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

Registry entry:
[ecosystem.yaml](https://github.com/Daldek/Nogat/blob/main/ecosystem.yaml) (Hydrograf).
Kartograf (NMT download, land cover, HSG), Hydrolog (hydrographs, concentration time) and
IMGWTools (PMAXTP precipitation) are runtime dependencies used as libraries; Hydraulik is a
planned compute node. Their migration to the standard 2.1 heads is `docs/PROGRESS.md`
Next 2.

## Deviations

- DEV-2.1: the Python docstrings, comments and log messages, the user-facing texts of the
  API, and the documents under `docs/` that `docs/PROGRESS.md` lists are still Polish until
  they are translated.
- DEV-5.2: `tests/performance` (timing tests that need the database) stands beside the
  standard tree.
- DEV-6.2: the environment is `backend/.venv`, not `.venv` in the repository root: the
  Python project is `backend/`.
- DEV-6.3: GDAL's Python binding must equal the system library of the image, so the
  Dockerfile installs it after `uv sync --locked`; it is not in `uv.lock`.
- DEV-7.2: `E501` is off in `migrations/versions/*` (28 single-line DDL strings of
  `001_initial_schema.py`).
- DEV-7.3: `migrations/` is excluded from mypy. Packages without type information
  (`affine`, `fiona`, `geopandas`, `pandas`, `psutil`, `pyflwdir`, `rasterio`, `scipy`,
  `shapely`, `yaml`) and the producers pinned by tag (`hydrolog`, `imgwtools`, `kartograf`:
  no `py.typed` before their standard 2.1 releases, DEV-7.4) are per-module
  `ignore_missing_imports` overrides. `tests.*` allows untyped definitions and calls and
  does not check the bodies of untyped functions (about 1,260 tests); `scripts.*` allows
  untyped definitions and calls (46 findings) and its annotated code is checked. To lift an
  override, annotate the module and delete its line in `pyproject.toml`.
- DEV-7.5: `fail_under = 70`: the offline suite covers 73% of `api`, `core`, `models` and
  `utils`; the rest needs PostGIS. `scripts/` and `migrations/` are not measured.
- DEV-7.7: CI runs on Linux only: Hydrograf is deployed with Docker on Linux, and an `app`
  MAY skip the platform matrix.
- DEV-10.1: `benchmark` is a marker besides `live`, `db` and `slow` (timing tests of
  `tests/performance`); the default run and the gate leave it out. The `db` tests run in
  the `db` job of CI.
- DEV-12.3: about two thirds of the 720 log calls use f-strings; new log calls use
  `%`-style arguments.
- DEV-14.2, DEV-15.1: the front end, nginx files and shell scripts use 4-space indentation;
  the JavaScript is IIFE modules on `window.Hydrograf`, not ES modules, and about 70 lines
  exceed 100 columns.
- DEV-15.2: the Polish UI text is inline in the JavaScript and HTML, not in translation
  resources.
- DEV-16.2: `docs/CLA.md` is missing until the author supplies the text.
- DEV-18, DEV-19: profile `tool` only; Hydrograf reads its settings from the environment
  (`.env.example`) and fetches data through Kartograf in the pipeline scripts.
