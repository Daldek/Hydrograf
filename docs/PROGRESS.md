# PROGRESS: Hydrograf

Current state only (DOC-6.1). Branch, tag and remote state: ask git (`git status`,
`git log --oneline -10`). History: the git log and [CHANGELOG](CHANGELOG.md). The Polish
session notes 1 to 97 and the former backlog are in git (`git show 704dcf7:docs/PROGRESS.md`);
sessions 98 and 99 are only on the unmerged branch `feature/kartograf-wykorzystanie`
(`git show bc0b438:docs/PROGRESS.md`). The open backlog items moved to
[BACKLOG.md](BACKLOG.md).

## Status

| Component | State | Note |
|---|---|---|
| Application (REST API, pipeline, frontend, admin panel) | done | released as 0.4.0; `develop` carries the storm-sewer integration (ADR-051, ADR-052), the feedback form (ADR-053) and the Kartograf 0.7.0 migration (ADR-057) |
| Producer pins | all three on their heads | Branch `feature/producer-heads` (ADR-060, ADR-061, REL-5.3, REL-5.6): Kartograf `45dedf4` (`feature/data-output`, 0.8.0.dev0, range `>=0.8.0.dev0,<0.9`), IMGWTools `3f7de36` (`feature/data-output`, 3.0.0, `>=3.0.0.dev0,<4`) and Hydrolog `5fa22b3` (`feature/routing-schematic`, 1.0.0.dev0, `>=1.0.0.dev0,<2`) are pinned by commit in `[tool.uv.sources]`; all three commits are on GitHub, so `uv sync --locked` resolves them anywhere; the release replaces the commits with tags and narrows the ranges |
| Branch `chore/nogat-2.1` | note | based on `develop`, not on `feature/kartograf-wykorzystanie`, which has 7 commits that `develop` lacks: `f3f23dd` (`affine>=2.4,<3`, carried here in `pyproject.toml`), a CHANGELOG line, and PROGRESS of sessions 98 and 99. Merging both needs a manual resolution of this file and of the deleted `requirements.txt` |
| Branch `feature/producer-heads` | note | from `chore/nogat-2.1` (`788c105`) and meant to merge after it; the branch is pushed. The full gate is green on every commit that changed code or the lock (the last one is `930461f`, the pin of the Kartograf and Hydrolog heads); the commits after it change documents only and were checked with the reduced gate (Gate row). The running stack keeps the image built on the old pins (Kartograf 0.7.0) and was not touched: its admin-panel bootstrap runs the scripts of this branch through the dev mount and needs a rebuilt image |
| Nogat standard 2.1, environment | done | `backend/uv.lock` replaces `requirements.txt`: seeded with the versions of the image built on 2026-10-18 (no third-party change), caps `sqlalchemy<2.1` and `affine<3` with their reasons in `pyproject.toml`; `dev` group, extra `viz`; `[tool.uv] package = false`; `develop` carries `0.5.0.dev0`, read through `core/version.py`; the Dockerfile builds with `uv sync --locked --no-dev` (GDAL's Python binding stays outside the lock); editor, git and `.env.example` files |
| Nogat standard 2.1, quality tooling | done | `ruff format` (`2347433`), the rule set of DEV-7.2 (`39eb15e`), mypy `strict` over `api core models scripts utils tests` (`98178c5`, clean, 144 files), the pytest settings (`--strict-markers`, markers `live`, `db`, `slow`, `benchmark`, `tests/contract`, coverage floor 80), the gate, CI and Dependabot |
| Nogat standard 2.1, contribution files | done, CLA text open | `SECURITY.md`, `CONTRIBUTING.md`, `CONTRIBUTORS.md` and `.github/PULL_REQUEST_TEMPLATE.md` with the CLA checkbox (DEV-13.7, DEV-16.2, DEV-16.4); `docs/CLA.md` is the author's text and does not exist yet, so `CONTRIBUTING.md` and the template name it without a link |
| Nogat standard 2.1, documentation | in progress | done: this file, [BACKLOG.md](BACKLOG.md), `CLAUDE.md` in English with the Deviations section (`docs/DEVELOPMENT_STANDARDS.md` is deleted, DEV-1.3), the README in the order of DOC-2.1 with its contract test, the ADR index and ADR-058 (the adoption), and the documents of the Kartograf migration in English (`docs/integrations/KARTOGRAF.md`, `backend/scripts/README.md`, `docs/CROSS_PROJECT_ANALYSIS.md`); the other Polish documents are still to translate (Next 1, Translations) |
| Nogat standard 2.1, error registry and REST (ERR-1 to ERR-6, DEV-11.1, AGI-6.2 to AGI-6.4) | done, see Next | the vendored registry and schemas in `schemas/nogat/`, the generated `core/_errors.py`, `HydrografError` with the message catalogue, `application/problem+json` with `Accept-Language`, OpenAPI `operationId`s, ADR-059 and the contract tests; the loose ends are in Next 1 (Error registry and REST) |
| Data output (DEV §19, ECO-051) | done | Hydrolog and IMGWTools need no call changed for it (Hydrograf writes nothing through them); the Kartograf calls are migrated (ADR-061): the store `cache/kartograf/` for the cache, a plain temporary file for the HSG raster of one analysis; the cache clean removes the directories of the 0.7.0 layout and the plain HSG raster keeps the statistics of the whole raster (ADR-061, errata of 2026-10-25). The documents that describe it are rewritten: [KARTOGRAF.md](integrations/KARTOGRAF.md), `backend/scripts/README.md`, ARCHITECTURE, SCOPE, COMPUTATION_PIPELINE (section 5), CROSS_PROJECT_ANALYSIS and the integration documents of Hydrolog and IMGWTools; DATA_MODEL says nothing about the layout |
| Gate | done | `scripts/gate.sh` and `scripts/check-commits.sh` (unchanged from Nogat). The gate runs in `backend/`: `uv sync --locked --all-extras`, `ruff format --check`, `ruff check`, `mypy`, `pytest tests -m 'not live and not db and not benchmark' --cov` (1,360 passed in 30 s, 85% covered), then the commit step from the repository root. The commit step fails on the commits of `develop` that are not on `origin/develop` (19 of them: author `agent@local`, AI trailers; the history rewrite of phase 1 is the author's), so this branch is gated with `GATE_COMMIT_RANGE=develop..HEAD scripts/gate.sh`, which checks the commits of the branch only. The `db` tests are not run here (no database). The commits after `930461f` change documents only: the first five were checked with `scripts/check-commits.sh` alone, the later ones with the reduced gate that the author decided on (`ruff format --check`, `ruff check`, `mypy`, `check-commits.sh`, plus `uv sync --locked --all-extras` when the lock changes; no pytest), and each of them says so; the last full gate run is `930461f` |
| CI | done, not run | `.github/workflows/ci.yml` is the `app` variant of `standards/ci`: the `gate` job runs `scripts/gate.sh` on Linux (Python 3.12, and 3.15 as a reported job), the `db` job runs the `db` tests against PostGIS after `alembic upgrade head`, the `audit` job runs `pip-audit` over the locked PyPI packages (not a required check). `.github/dependabot.yml` updates the actions weekly. There is no `live.yml`: no test has the `live` marker. The workflow runs on pushes to `main` and `develop`, on pull requests into them, weekly and by hand; the topic branches are pushed and have no pull request, so no job has run. All three producer pins are on GitHub, so the `gate` and `db` jobs resolve them; the `db` job and the migrations in it are unverified (no database here) |

Skipped adoption items, which need the author (DEV-3.3, ADOPTION_PLAN):

| Item | Why |
|---|---|
| History rewrite (phase 1) | the repository was rewritten once on 2026-10-08; the standard's rewrite (mailmap to `Daldek <git@debever.pl>`, AI trailers) is the author's. Commits made on this branch have the right author |
| Rulesets for `main`, `develop` and `v*` tags, private vulnerability reporting, Dependabot security updates (DEV-3.6, DEV-13.6, DEV-13.7) | GitHub settings. Required checks: the `gate` job and the `db` job of `ci.yml` |
| `docs/CLA.md` and the way the CLA is signed (DEV-16.2, DEV-16.5) | the author's legal text |
| `Approved:` lines of plans (DEV-17.4) | approval is the author's statement |
| `CROSS_PROJECT_ANALYSIS.md` into the Nogat registry and `request` issues in the producers' repositories (DEV-17.5) | needs Nogat and GitHub issues |
| Registry entry of Hydrograf in Nogat `ecosystem.yaml` | Nogat owns it: `python_manifests` lists `backend/requirements.txt`, which the uv step deletes; `uses` of Kartograf names `LandCoverManager` and `HSGCalculator`, which the migration removed (they are `download_landcover`, `calculate_hsg` and `DownloadManager` now) |
| Tags, releases, replacing producer pins by tags (REL-5.3, phases 5 and 6) | need the producers' tags and the author's approval |
| Push of `chore/nogat-2.1`, pull request, merge into `develop` | approvals (DEV-3.3) |

## Next

1. **Finish the standard 2.1 adoption on `chore/nogat-2.1`** (one commit per step, gate
   green before each; rules: `git -C ~/workspace/Nogat show feature/data-output:standards/<file>`;
   Archiwista's branch `chore/nogat-2.1` is the worked example of an `app`). Remaining
   gaps of the inventory of 2026-10-25, in this order:
   - **mypy is done**; its deviations go to the Deviations section of CLAUDE.md (DEV-7.3):
     `migrations/` is excluded; the packages without types (`affine`, `fiona`, `geopandas`,
     `pandas`, `psutil`, `pyflwdir`, `rasterio`, `scipy`, `shapely`, `yaml`) are per-module
     `ignore_missing_imports` overrides, not a global switch; Hydrolog, Kartograf and IMGWTools
     ship `py.typed` at the pinned heads (DEV-7.4), so their calls are checked;
     `tests.*` allows untyped definitions and calls and does not check the bodies of
     untyped functions (`check_untyped_defs = false`, about 1,260 unannotated tests);
     `scripts.*` allows untyped definitions and calls (46 findings) and its annotated code is
     checked. To lift an override, annotate the module and delete its line in `pyproject.toml`.
   - **Coverage** (DEV-7.5) is done: `fail_under` is 80 and the offline suite covers 85% of
     `api`, `core`, `models` and `utils` (`scripts/`, `migrations/` and `tests/` are omitted
     from the measure). Modules still below 75%: `core/watershed_service.py` 53%,
     `core/catchment_graph.py` 60%, `core/raster_io.py` 67%, `api/endpoints/hydrograph.py`
     and `watershed.py` 70%; most of what is missing is PostGIS SQL that only the `db` job
     runs.
   - **Translations** to English (DEV-2.1, ECO-005). Done: ARCHITECTURE, PRD, SCOPE,
     BACKLOG, TECHNICAL_DEBT, CROSS_PROJECT_ANALYSIS, `docs/integrations/KARTOGRAF.md`,
     `backend/scripts/README.md` and the [Unreleased] section of the CHANGELOG (sections as
     DOC-7.1). Still Polish, most useful first: DECISIONS (the bodies of ADR-001 to ADR-057,
     kept as records; the index and ADR-058 on are English), DATA_MODEL (nothing in it
     describes the Kartograf layout: a translation only), COMPUTATION_PIPELINE (its sections
     5.1 and 5.3 are English), `docs/integrations/HYDROLOG.md` and `IMGWTOOLS.md` (their pins
     are English), BENCHMARK_QUERIES, the released versions of the CHANGELOG (0.4.0 and
     older, records); QA_REPORT is English.
     After the documents: docstrings, comments and log messages of the 23,700 lines of
     Python, and user-facing texts into translation resources (DEV-2.3, DEV-15.2). The 40
     plans of the ignored `notes/superpowers/plans/` move to `docs/plans/` after
     translation, without `Approved:` lines (the author approves). The links of the ADR
     index in `docs/DECISIONS.md` follow the headings of ADR-001 to ADR-057; translating a
     heading means regenerating its link.
   - **Error registry and REST: loose ends.** Done: registry, `HydrografError`, the catalogue
     of 45 messages, problem documents, `Accept-Language`, OpenAPI ids, contract tests.
     Left: `frontend/js/admin/admin-sewer.js` (5 `fetch` calls) does not send
     `Accept-Language` yet; the admin operations document `401` only, so `404` and `409` of
     `bootstrap/start`, `bootstrap/cancel` and the feedback routes are undocumented; the 429
     of nginx (`limit_req`) and its gateway errors are plain responses, and an `error_page`
     that returns a problem document would close AGI-6.3; the validation texts in `errors[]`
     are pydantic's English; the texts of core exceptions that reach `details.cause`
     (`invalid_parameters`, `invalid_bbox`, `invalid_boundary_file`) are whatever the
     library said.
   - **Other gaps found**, not in scope of a step: logs use f-strings (DEV-12.3), 60 lines of
     JavaScript are longer than 100 columns and the modules are IIFEs, not ES modules
     (DEV-15.1), the front end has Polish text inline (DEV-15.2), `tests/performance` stands
     beside the standard tree (DEV-5.2). Deviations are recorded in CLAUDE.md. Found by mypy and
     marked `# type: ignore[...]  # stale call, PROGRESS`: `scripts/prepare_area.py` passes
     `batch_size` to `process_dem`, which has no such parameter; `scripts/analyze_watershed.py`
     passes `stream_threshold` to `process_dem` and imports `find_nearest_stream` and
     `traverse_upstream` from `core.watershed`, which has neither: those paths fail at run time.
     Found by the tests of `load_bdot_streams_from_gpkg` (`core/db_bulk.py`), not fixed: a
     feature with an empty name column gets the name `'nan'` (a pandas NaN is truthy), and a
     feature without geometry stops the load (`row.geometry` is NaN, so `.is_empty` fails).
2. **Migrate to the producers' heads** (Nogat plans `2026-10-24-data-output.md` step 8 and
   `2026-10-20-first-release-set.md` step 8; ADOPTION_PLAN 5.1). Done on `feature/producer-heads`
   (ADR-060, ADR-061): Hydrolog, IMGWTools and Kartograf, below. The method: pin the producer's
   commit while its tag is missing (REL-5.3), migrate, run the suite, then pin the tags: when a
   tag exists replace the `rev` in `[tool.uv.sources]` by it, narrow the range of `dependencies`
   (REL-5.6), run `uv lock` and the gate, and repeat the comparisons described below.
   - **IMGWTools: done on `feature/producer-heads`** (ADR-060, pinned `3f7de36`, 3.0.0).
     `fetch_pmaxtp(latitude, longitude, *, method='POT', timeout=30.0, validate_coords=True)` keeps
     its model (`result.data.get_precipitation(...)`, `ks`, `sg`, `rb`); `method` became
     keyword-only, and Hydrograf passes only `latitude=` and `longitude=`. Both call sites
     (`scripts/preprocess_precipitation.py::fetch_pmaxtp_for_point` and
     `scripts/analyze_watershed.py::fetch_precipitation_imgw`) ran offline against the real
     parsing, with a canned PMAXTP answer in place of the HTTP call: 432 scenarios without a gap,
     the nearest duration and a fractional probability. They catch only `IMGWConnectionError`,
     `IMGWDataError` and `IMGWValidationError`, and `tests/unit/test_imgw_call_sites.py` runs both
     through the real library with an `httpx.MockTransport` answer (`serve_imgw` in
     `tests/conftest.py`), also for the errors that must surface. Renames in IMGWTools that
     Hydrograf does not use: `IMGW_STORE_ROOT` is `IMGW_ROOT`, `IMGW_DATA_DIR` is
     `IMGW_REFERENCE_DIR`, store and export options are `root`, `output_dir`, `output`.
     Hydrograf's own settings `IMGW_GRID_SPACING_KM` and `IMGW_RATE_LIMIT_DELAY_S`
     (`core/config.py`, `.env.example`) share the `IMGW_` prefix of IMGWTools, which ignores the
     names it does not know. IMGWTools ships `py.typed`, so mypy checks the call. Its probability
     parameter was annotated `int` while the keys are `str(percent)` and Hydrograf asks for 0.01 to
     98.5 (a `type: ignore` in `scripts/preprocess_precipitation.py`): IMGWTools took the request
     (`9291eb3`: a `float`, one of the 27 published percentages, else `IMGWValidationError` with
     the allowed list) and the pin moved to its head, so the `type: ignore` is gone.
   - **Hydrolog: done on `feature/producer-heads`** (ADR-060, pinned `5fa22b3`, 1.0.0.dev0, the
     head of `feature/routing-schematic`, which stacks `chore/nogat-2.1` and `feature/routing-*`).
     The imports resolve and the offline suite passed unchanged at the first pin `6c9ba5a` (1,362
     tests): no test pinned a number that changed. The commits after it add the network objects
     (ADR-0012, `31bf796`) and the network schematic (ADR-0013, `5fa22b3`), which nothing in
     Hydrograf calls; the gate is green at `5fa22b3` too. mypy
     checks the calls now (Hydrolog ships `py.typed`): three errors in
     `api/endpoints/hydrograph.py` and two in `scripts/analyze_watershed.py`, fixed. The real
     endpoint (`generate_hydrograph` on the fast path with `morphometry`, only the precipitation
     lookup replaced) ran on 0.6.3 and on `6c9ba5a` over 138 combinations (three catchments, six
     concentration-time methods, three hyetograph types, the SCS and Snyder models and the three
     Nash estimations): every `tc_min` is the same (`_calculate_tc` forces the mean slope for NRCS
     and calls `ConcentrationTime.faa|kerby|kerby_kirpich` itself, so the changes of
     `calculate_tc` do not reach the API), the SCS and Nash hydrographs are the same, and the
     Snyder hydrograph differs: the peak is 11 to 12% higher and comes 25 to 70 minutes earlier at
     a time step of 5 minutes, the volume is the same (the duration correction of Snyder;
     CHANGELOG, breaking for API clients). `scripts/analyze_watershed.py` offers `nrcs` instead of
     `scs`, which Hydrolog never accepted. The CLI of Hydrolog changed (catalog,
     `hydrolog-result/1`, exit codes 13 for `calculation_error` and 12 for `forbidden`); Hydrograf
     uses the library only. Routing (`route lag|cascade|level-pool|muskingum|muskingum-cunge|
     network`, ADR-0007 to ADR-0010) is in the pinned head; nothing calls it, an option for the
     sewer and Hydraulik work. Open: the REST option `nash_estimation: "from_tc"` calls
     `NashIUH.from_tc`, which the changelog of Hydrolog announces for removal in 1.0.0 (the head
     keeps it and warns): Open questions 5.
   - **Kartograf: done on `feature/producer-heads`** (ADR-061, pinned `45dedf4`, 0.8.0.dev0).
     Every call is migrated and every migrated call runs against the real Kartograf in the tests
     (`tests/kartograf_offline.py` stubs only the provider classes: the GUGiK sheet index, BDOT10k
     and SoilGrids; `kartograf.testing` builds the stores the tests read). The cache of raw downloads
     is the store `cache/kartograf/` (NMT, BDOT10k, the HSG raster of Poland), the metadata cache is
     `cache/kartograf_meta.db`, the HSG raster of one CN calculation is a plain temporary file.
     Measured on the real library with a stubbed index: a plain directory drops a sheet that has only
     a partial flight, takes an older full flight for a sheet whose newest flight is partial, and
     refuses a second run (`conflict`, `output_exists`); the store keeps both and answers `local`.
     The documents that describe the layout and the API are rewritten in English (Status, Data
     output). Not run: a real download of the NMT, BDOT10k and SoilGrids (no network test in the
     offline suite), `bootstrap` end to end, the Docker image. Known defects that the documents
     state: `scripts/prepare_area.py` and `scripts/analyze_watershed.py --process` call
     `process_dem()` with parameters it no longer has (Next 1, Other gaps), so the DEM step of
     both fails, and no script passes `building_gpkg`, so building raising (ADR-033) does not
     run in the pipeline.
   - **Hydraulik** (`depends_on`, planned): integration halted by the author (session 99);
     nothing to migrate.
3. **Engineering items with the highest priority** from the former backlog (all of it:
   [BACKLOG.md](BACKLOG.md)): the hardening of the public attack surface, starting with three
   unauthenticated denial-of-service paths (precise delineation without an area limit, XYZ
   tiles without zoom validation, tile routes without a zoom floor and `statement_timeout`;
   spec `notes/superpowers/specs/2026-08-08-public-security-hardening-spec.md`, outside the
   repository); the hyetograph and hydrograph "no data" bug from the tester's feedback; the
   hardcoded accumulation thresholds in `scripts/bootstrap.py` (`--thresholds`); the
   decision on the NMT versioning ADR (superseded in part by Kartograf's store); hardcoded
   secrets in `core/config.py` and `migrations/env.py`.

## Open questions

1. D5 and D6 of session 97: the HSG fallback "B" and step 5 as non-critical (a failed step 5
   still ends bootstrap with exit 0); data of the 0.6.1 layout are not reused.
2. GDAL's Python binding stays outside `uv.lock` because it must equal the system library of
   the image: accept as a deviation of DEV-6.3, or install `gdal-bin` and drop the pip build
   (`generate_dem_tiles.py` runs `gdal2tiles.py`).
3. Merge of `feature/kartograf-wykorzystanie` and `chore/nogat-2.1` into `develop`: order and
   who resolves PROGRESS, CHANGELOG and `requirements.txt`.
4. Text of `docs/CLA.md` and how the CLA is signed. `CONTRIBUTING.md` describes signing by a
   comment on the pull request, as in Retman and Archiwista, and the template has the
   checkbox; both name `docs/CLA.md`, which does not exist yet.
5. `nash_estimation: "from_tc"` of `POST /api/generate-hydrograph` calls `NashIUH.from_tc`,
   deprecated since Hydrolog 0.6.2 and announced for removal in 1.0.0 (the pinned head keeps it
   and warns). Remove the REST option and the front-end choice before Hydrolog 1.0.0 (a change of
   a public interface: a plan with the author's approval, DEV-17.4), or ask Hydrolog to keep the
   method. Until then the option works.
