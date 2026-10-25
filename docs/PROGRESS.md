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
| Producer pins | Hydrolog and IMGWTools on their heads, Kartograf behind | Branch `feature/producer-heads` (ADR-060, REL-5.3): Hydrolog `6c9ba5a` (`feature/routing-network`, 1.0.0.dev0) and IMGWTools `a304521` (`feature/data-output`, 3.0.0) are pinned by commit and neither commit is pushed; Kartograf stays on `v0.7.0` until its data output is finished (Next 2); the release replaces the commits with tags |
| Branch `chore/nogat-2.1` | note | based on `develop`, not on `feature/kartograf-wykorzystanie`, which has 7 commits that `develop` lacks: `f3f23dd` (`affine>=2.4,<3`, carried here in `pyproject.toml`), a CHANGELOG line, and PROGRESS of sessions 98 and 99. Merging both needs a manual resolution of this file and of the deleted `requirements.txt` |
| Branch `feature/producer-heads` | note | from `chore/nogat-2.1` (`788c105`) and meant to merge after it; the gate is green on each of its commits. `uv sync --locked`, and so the CI jobs `gate` and `db` and the Docker build, resolve its two unpushed pins only on a machine whose uv git cache holds them (Next 2, "Resolving the pins"). The running stack keeps the image built on the old pins and was not touched |
| Nogat standard 2.1, environment | done | `backend/uv.lock` replaces `requirements.txt`: seeded with the versions of the image built on 2026-10-18 (no third-party change), caps `sqlalchemy<2.1` and `affine<3` with their reasons in `pyproject.toml`; `dev` group, extra `viz`; `[tool.uv] package = false`; `develop` carries `0.5.0.dev0`, read through `core/version.py`; the Dockerfile builds with `uv sync --locked --no-dev` (GDAL's Python binding stays outside the lock); editor, git and `.env.example` files |
| Nogat standard 2.1, quality tooling | done | `ruff format` (`2347433`), the rule set of DEV-7.2 (`39eb15e`), mypy `strict` over `api core models scripts utils tests` (`98178c5`, clean, 144 files), the pytest settings (`--strict-markers`, markers `live`, `db`, `slow`, `benchmark`, `tests/contract`, coverage floor 80), the gate, CI and Dependabot |
| Nogat standard 2.1, contribution files | done, CLA text open | `SECURITY.md`, `CONTRIBUTING.md`, `CONTRIBUTORS.md` and `.github/PULL_REQUEST_TEMPLATE.md` with the CLA checkbox (DEV-13.7, DEV-16.2, DEV-16.4); `docs/CLA.md` is the author's text and does not exist yet, so `CONTRIBUTING.md` and the template name it without a link |
| Nogat standard 2.1, documentation | in progress | done: this file, [BACKLOG.md](BACKLOG.md), `CLAUDE.md` in English with the Deviations section (`docs/DEVELOPMENT_STANDARDS.md` is deleted, DEV-1.3), the README in the order of DOC-2.1 with its contract test, the ADR index and ADR-058 (the adoption); the Polish documents are still to translate (Next 1, Translations) |
| Nogat standard 2.1, error registry and REST (ERR-1 to ERR-6, DEV-11.1, AGI-6.2 to AGI-6.4) | done, see Next | the vendored registry and schemas in `schemas/nogat/`, the generated `core/_errors.py`, `HydrografError` with the message catalogue, `application/problem+json` with `Accept-Language`, OpenAPI `operationId`s, ADR-059 and the contract tests; the loose ends are in Next 1 (Error registry and REST) |
| Data output (DEV §19, ECO-051) | partly | Hydrolog and IMGWTools need no call changed for it (Hydrograf writes nothing through them); the Kartograf calls, in store mode, wait for its finished branch; call sites in Next 2 |
| Gate | done | `scripts/gate.sh` and `scripts/check-commits.sh` (unchanged from Nogat). The gate runs in `backend/`: `uv sync --locked --all-extras`, `ruff format --check`, `ruff check`, `mypy`, `pytest tests -m 'not live and not db and not benchmark' --cov` (1,362 passed in 26 s, 85% covered), then the commit step from the repository root. The commit step fails on the commits of `develop` that are not on `origin/develop` (19 of them: author `agent@local`, AI trailers; the history rewrite of phase 1 is the author's), so this branch is gated with `GATE_COMMIT_RANGE=develop..HEAD scripts/gate.sh`, which checks the commits of the branch only. The `db` tests are not run here (no database) |
| CI | done, not run | `.github/workflows/ci.yml` is the `app` variant of `standards/ci`: the `gate` job runs `scripts/gate.sh` on Linux (Python 3.12, and 3.15 as a reported job), the `db` job runs the `db` tests against PostGIS after `alembic upgrade head`, the `audit` job runs `pip-audit` over the locked PyPI packages (not a required check). `.github/dependabot.yml` updates the actions weekly. There is no `live.yml`: no test has the `live` marker. Nothing is pushed, so no job has run, and the `gate` and `db` jobs of `feature/producer-heads` cannot resolve its unpushed pins until the producers push them; the `db` job and the migrations in it are unverified (no database here) |

Skipped adoption items, which need the author (DEV-3.3, ADOPTION_PLAN):

| Item | Why |
|---|---|
| History rewrite (phase 1) | the repository was rewritten once on 2026-10-08; the standard's rewrite (mailmap to `Daldek <git@debever.pl>`, AI trailers) is the author's. Commits made on this branch have the right author |
| Rulesets for `main`, `develop` and `v*` tags, private vulnerability reporting, Dependabot security updates (DEV-3.6, DEV-13.6, DEV-13.7) | GitHub settings. Required checks: the `gate` job and the `db` job of `ci.yml` |
| `docs/CLA.md` and the way the CLA is signed (DEV-16.2, DEV-16.5) | the author's legal text |
| `Approved:` lines of plans (DEV-17.4) | approval is the author's statement |
| `CROSS_PROJECT_ANALYSIS.md` into the Nogat registry and `request` issues in the producers' repositories (DEV-17.5) | needs Nogat and GitHub issues |
| Registry entry of Hydrograf in Nogat `ecosystem.yaml` | Nogat owns it: `python_manifests` lists `backend/requirements.txt`, which the uv step deletes; `uses` of Kartograf names `LandCoverManager` and `HSGCalculator`, which the migration of Next 2 removes |
| Tags, releases, replacing producer pins by tags (REL-5.3, phases 5 and 6) | need the producers' tags and the author's approval |
| Push of Hydrolog `feature/routing-network` (the stack that holds `chore/nogat-2.1` and the routing branches) and of IMGWTools `feature/data-output`, the commits `6c9ba5a` and `a304521` that `feature/producer-heads` pins | a push is the author's step (DEV-3.3); until then CI and the Docker build of that branch fail on the missing commits |
| `request` issue in IMGWTools: `Typing :: Typed` is declared but `py.typed` is not shipped (DEV-7.4), so the mypy override of `imgwtools` stays | needs GitHub (DEV-17.5) |
| Push of `chore/nogat-2.1`, pull request, merge into `develop` | approvals (DEV-3.3) |

## Next

1. **Finish the standard 2.1 adoption on `chore/nogat-2.1`** (one commit per step, gate
   green before each; rules: `git -C ~/workspace/Nogat show feature/data-output:standards/<file>`;
   Archiwista's branch `chore/nogat-2.1` is the worked example of an `app`). Remaining
   gaps of the inventory of 2026-10-25, in this order:
   - **mypy is done**; its deviations go to the Deviations section of CLAUDE.md (DEV-7.3):
     `migrations/` is excluded; the packages without types (`affine`, `fiona`, `geopandas`,
     `pandas`, `psutil`, `pyflwdir`, `rasterio`, `scipy`, `shapely`, `yaml`) and the producers
     that ship no `py.typed` (`imgwtools`, `kartograf`, DEV-7.4; Hydrolog ships it, so its
     calls are checked on `feature/producer-heads`) are per-module `ignore_missing_imports`
     overrides, not a global
     switch; `tests.*` allows untyped definitions and calls and does not check the bodies of
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
     BACKLOG, TECHNICAL_DEBT and the [Unreleased] section of the CHANGELOG (sections as
     DOC-7.1). Still Polish, most useful first: DECISIONS (the bodies of ADR-001 to ADR-057,
     kept as records; the index and ADR-058 on are English), DATA_MODEL,
     COMPUTATION_PIPELINE, `docs/integrations/*` (they change with the migration of Next 2),
     BENCHMARK_QUERIES, CROSS_PROJECT_ANALYSIS, `backend/scripts/README.md`, the released
     versions of the CHANGELOG (0.4.0 and older, records); QA_REPORT is English.
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
     Step 6 of the same script (`generate_hydrograph`) also builds `WatershedParameters(**morph)`
     from a dict that carries the shape and relief indices of `build_morphometric_params`
     (`TypeError: unexpected keyword argument 'compactness_coefficient'` on Hydrolog 0.6.3 and on
     the head) and filters `cn` out (so `--tc-method nrcs` would end with "CN is required for NRCS
     method"); `WatershedParameters.from_dict(morph)`, which the endpoint uses, ignores unknown keys
     and keeps `cn`. Found while migrating Hydrolog (ADR-060), not fixed: it is not about the
     producers' heads.
     Found by the tests of `load_bdot_streams_from_gpkg` (`core/db_bulk.py`), not fixed: a
     feature with an empty name column gets the name `'nan'` (a pandas NaN is truthy), and a
     feature without geometry stops the load (`row.geometry` is NaN, so `.is_empty` fails).
2. **Migrate to the producers' heads** (Nogat plans `2026-10-24-data-output.md` step 8 and
   `2026-10-20-first-release-set.md` step 8; ADOPTION_PLAN 5.1). Done on `feature/producer-heads`
   (ADR-060): Hydrolog and IMGWTools, below. Open: Kartograf. Probe of 2026-10-25 in a throwaway
   environment, committed nowhere: Kartograf `feature/data-output` @ `343d659` (0.8.0.dev0,
   `root`, store marker, `--check`), IMGWTools `feature/data-output` @ `a304521` (3.0.0),
   Hydrolog `chore/nogat-2.1` @ `d4f7282` (1.0.0.dev0). Result of `pytest tests -m 'not db and not
   benchmark'` with all three: 10 tests fail because of Kartograf, and every Kartograf call listed
   here as "untested" breaks at run time while its tests pass, because they mock Kartograf. The
   method: pin the producer's commit while its tag is missing (REL-5.3), migrate, run the suite,
   then pin the tags.
   - **Resolving the pins** of `feature/producer-heads`. Hydrolog `6c9ba5a` and IMGWTools
     `a304521` are on this machine only. `uv` keeps one git database per repository URL below
     `~/.cache/uv/git-v1/db/`, named like the folder of `~/.cache/uv/git-v1/checkouts/` that holds
     the checkout of the old pin (`cd325c3` for Hydrolog `v0.6.3`, `4bacf36` for IMGWTools
     `v2.1.0`); here `3d78e457cbd77cac` and `a7524ceee79a212b`. Fetch the commits from the local
     checkouts into them and `uv lock` and `uv sync --locked` need no network for the git part:
     `git -C <hydrolog db> fetch ~/workspace/Hydrolog-routing
     feature/routing-network:refs/heads/local-feature-routing-network` and `git -C <imgwtools db>
     fetch ~/workspace/IMGWTools feature/data-output:refs/heads/local-feature-data-output` (Retman
     did the same for IMGWTools, its PROGRESS Next 2). The refs keep the objects from `git gc`.
     Anywhere else, in CI and in the Docker build too, the producers have to push the commits
     first (Skipped adoption items). When a tag exists, replace the commit in `pyproject.toml` by
     it (REL-5.3), run `uv lock` and the gate, and repeat the comparisons described below.
   - **IMGWTools: done on `feature/producer-heads`** (ADR-060, pinned `a304521`, 3.0.0).
     `fetch_pmaxtp(latitude, longitude, *, method='POT', timeout=30.0, validate_coords=True)` keeps
     its model (`result.data.get_precipitation(...)`, `ks`, `sg`, `rb`); `method` became
     keyword-only, and Hydrograf passes only `latitude=` and `longitude=`. Both call sites
     (`scripts/preprocess_precipitation.py::fetch_pmaxtp_for_point` and
     `scripts/analyze_watershed.py::fetch_precipitation_imgw`) ran offline against the real
     parsing, with a canned PMAXTP answer in place of the HTTP call: 432 scenarios without a gap,
     the nearest duration and a fractional probability. No test covers them, and both end in
     `except Exception`, so a future change of IMGWTools would show as "no precipitation data",
     not as an error; a test with an `httpx.MockTransport` answer through the real library would
     catch it. Renames in IMGWTools that Hydrograf does not use: `IMGW_STORE_ROOT` is
     `IMGW_ROOT`, `IMGW_DATA_DIR` is `IMGW_REFERENCE_DIR`, store and export options are `root`,
     `output_dir`, `output`. Hydrograf's own settings `IMGW_GRID_SPACING_KM` and
     `IMGW_RATE_LIMIT_DELAY_S` (`core/config.py`, `.env.example`) share the `IMGW_` prefix of
     IMGWTools, which reads its settings from the environment and from a `.env` of the working
     directory when `imgwtools` is imported; it ignores the names it does not know, and the import
     and both call sites worked with the repository `.env` and with both variables exported.
     IMGWTools ships no `py.typed` (a `request` issue, Skipped adoption items).
   - **Hydrolog: done on `feature/producer-heads`** (ADR-060, pinned `6c9ba5a`, 1.0.0.dev0, the
     head of the stack `chore/nogat-2.1` and `feature/routing-*`). The imports resolve and the
     offline suite passes unchanged (1,362 tests): no test pinned a number that changed. mypy
     checks the calls now (Hydrolog ships `py.typed`): three errors in
     `api/endpoints/hydrograph.py` and two in `scripts/analyze_watershed.py`, fixed. The real
     endpoint (`generate_hydrograph` on the fast path with `morphometry`, only the precipitation
     lookup replaced) ran on 0.6.3 and on the head over 138 combinations (three catchments, six
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
     keeps it and warns): Open questions 7.
   - **Kartograf: waits for its finished `feature/data-output`** (head `40455e5e` of 2026-10-25,
     0.8.0.dev0; its PROGRESS still lists the plain tests of six tracks as open, and its CHANGELOG
     "Migration guide: data output" is the list to follow). `v0.7.0` stays pinned. The items below
     were found on `343d659`; the names they use (`calculate_hsg`, `download_landcover`,
     `DownloadManager`, `DownloadResult`, `GugikProvider`, `find_sheets_for_bbox`,
     `find_sheets_for_geometry`, `discover_teryts_for_bbox`) were checked again on `40455e5e` and
     stand, with these changes: the plain mode exists now (`output_dir=`, `--output-dir`, `-o`:
     files named as in the store, no sidecar, no `versions/`, `update="force"` replaces; PL sheets
     take the newest FULL flight) next to the store (`root=`, `--root`); `files[]` is `{unit,
     country, path, size_bytes, sha256, status}`, so the path is `files[i].path`, not
     `files[i].file.path`; `calculate_hsg` requires `depth` (0.7.0 defaulted to `"0-5cm"`).
     Every name is as of that head and can still move.
     - `core/cn_calculator.py`: `check_kartograf_available` imports
       `kartograf.hydrology.HSGCalculator` (gone, returns False, so the CN silently falls
       back); `get_hsg_from_soilgrids` calls `HSGCalculator().calculate_hsg_by_bbox(bbox,
       hsg_path)` into a temporary directory and `get_hsg_statistics(hsg_path)`: use
       `calculate_hsg(output_dir=<temporary directory>, bbox=bbox, depth="0-5cm")`, which fetches
       the SoilGrids inputs into staging and writes only the raster, and
       `hsg_statistics(report.files[0].path)` (`root=` would put a version into the store per
       request instead, Open questions 2). `hsg_statistics` now also returns a `nodata` key: skip
       it, or the dominant-group code (`max(..., key=percent)`) can pick it.
       `get_land_cover_stats` imports `LandCoverManager`, calls `download_by_teryt(teryt)` and
       `download_by_bbox(bbox)` inside `except Exception: return {}` (an ImportError becomes
       "no land cover" and the default land cover is used silently): use
       `download_landcover(product="bdot10k", root=..., teryt=...|bbox=...)`, read
       `report.files[0].path`, `report.failed` and `report.ok`.
     - `scripts/download_landcover.py`: `download_landcover` (the script's own function, same
       name as Kartograf's) imports `kartograf.landcover.LandCoverManager`, builds
       `LandCoverManager(output_dir=..., provider=...)` and calls `download_by_teryt`,
       `download_by_godlo` (`godlo` is `sheet`) and `download_by_bbox` with `output_path=`: use
       `kartograf.download_landcover(product=provider, root=..., teryt=|sheet=|bbox=,
       year=...)` (`year` only for CORINE); files are store versions, so the
       `<provider>_teryt_<T>.gpkg` names and `skip_existing` go; `merge_hydro_gpkgs` reads the
       paths of the reports. `_discover_teryts_grid` calls the private
       `Bdot10kProvider._get_teryt_for_point` (gone); Kartograf now has the public
       `discover_teryts_for_bbox(bbox, *, session=None, cache=None, timeout=30)` and
       `teryt_for_point(x, y, crs, ...)`: delete the script's WFS code (`discover_teryts_for_bbox`,
       `_discover_teryts_grid`, `_parse_teryts_from_gml`, `_generate_sample_coords`), its contract
       test `TestBdot10kPrivateApiContract` and exception (a) of ADR-057; callers:
       `bootstrap.py` (land cover steps) and `prepare_area.py`.
     - `scripts/bootstrap.py`: `step_soil_hsg` imports `HSGCalculator` inside `try/except
       ImportError` and returns "pominięto (brak kartograf HSGCalculator)" (the step is skipped
       silently), then calls `calculate_hsg_by_bbox(bbox=..., output_path=hsg_poland,
       timeout=600)`: use `calculate_hsg(root=..., bbox=bbox_poland, depth="0-5cm")` (no
       `output_path`, no `timeout`); `check_hsg_cache` reads `extra.derived` and
       `kartograf_version` of the sidecar and the `soil_hsg/hsg_poland.tif` path goes (Kartograf
       versions the raster, `update=`).
       `resolve_sheets` and `resolve_boundary_file` call `find_sheets_for_bbox(bbox, scale)` and
       `find_sheets_for_geometry(file, target_scale=scale, layer=layer)`: both need
       `sheet_system="1992"` now (`'1992'` or `'2000'`; keyword-only for geometry); they import
       `BBox` from `kartograf.core.geometry` (still importable; `kartograf.BBox` is public).
     - `scripts/download_dem.py`: `download_sheets` calls `GugikProvider(resolution=...,
       cache=cache)`: `vertical_crs="EVRF2007"` is required (matches the segment
       `pl_1992_5m_evrf2007`); `DownloadManager(output_dir=str(output_dir), provider=provider,
       resolution=..., campaigns="newest")`: `DownloadManager(provider, root=output_dir)` (no
       `resolution`, no `campaigns`: the newest flight is the default); `manager.download_sheets(
       sheets, skip_existing=...)` returned paths and set `manager.last_result`: it returns a
       `DownloadResult` now (`update=None` keeps local versions, `update="force"` replaces
       `skip_existing=False`; `succeeded` holds downloaded paths, `skipped` the sheets that were
       already local, `files[sheet][i].path` the standard paths; `no_coverage`, `hard_failures`,
       `unverified` and `errors` keep their names). `download_for_geometry` and the `--dry-run`
       branch of `main` need `sheet_system="1992"` for `find_sheets_for_geometry`;
       `utils/sheet_lookup.py::sheets_for_point_buffer` for `find_sheets_for_bbox`.
       `MetadataCache(path, on_disabled=...)` is unchanged. The CLI option `--output` of
       `download_dem` keeps meaning the Kartograf root: rename it `--root` (DEV-19.1).
     - Layout: PL sheets are `<root>/nmt/pl_1992_5m_evrf2007/<hierarchy>/<sheet>.asc` (standard
       path, a hard link) with the copies under `versions/` (0.7.0 had `kampanie/`);
       `scripts/analyze_watershed.py::find_existing_nmt_files` excludes `kampanie` only, so it
       would list the copies: exclude `versions` (and `full_sheet`); the fixtures of
       `tests/unit/test_bootstrap_nmt.py` and `test_analyze_watershed_nmt_files.py` name `kampanie`.
       A store root needs the marker `kartograf-store.json`, and a directory with foreign files
       is refused (`conflict`, `not_empty`; a layout without marker: `store_unavailable`, hint
       `kartograf store init --root <path>`). `cache/` also holds `bdot10k/`, `soil_hsg/`,
       `kartograf_meta.db*`; give Kartograf its own root (for example `cache/kartograf/`), move
       `cache/nmt` into it and run `kartograf store init --root`; pass `root=` explicitly from one
       setting rather than relying on `KARTOGRAF_ROOT`. `scripts/clean.py` (`nmt`, `bdot10k`,
       `soil_hsg`, `kartograf_meta.db*` of `cache/`), `docs/integrations/KARTOGRAF.md`, ADR-057 and
       `scripts/README.md` describe the old layout.
     - Tests that pass against the head and hide the breakage because they mock Kartograf:
       `test_download_dem_report.py` (pins `output_dir`, `resolution`, `campaigns`,
       `skip_existing`, `last_result`), `test_land_cover_stats.py` (`LandCoverManager`),
       `test_cn_calculator.py` (`kartograf.hydrology.HSGCalculator`), `test_download_landcover.py`
       (`Bdot10kProvider`). Tests that fail: `test_sheet_lookup.py` (6) and
       `test_bootstrap_bbox.py` (1) with "missing `sheet_system`", `test_cn_calculator.py` (2),
       `test_download_landcover.py::TestBdot10kPrivateApiContract` (1).
     - Errors and exit codes: exceptions are `KartografError` subclasses with a registry `code`
       (`validation_error` 2, `no_data` 14 for no coverage and years, `source_unavailable` 5,
       `store_unavailable` 8, `conflict` 4); `kartograf.ParseError` and `ValidationError` stay
       importable. The CLI answers with the `kartograf-result/1` envelope (`partial` exit 10,
       `failed` 11) and an error document on the last stderr line; Hydrograf calls the library,
       so only `except` clauses that match old messages or `RuntimeError` need a look
       (`bootstrap.py` catches `KartografParseError` and `KartografValidationError`).
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

1. Root of Kartograf's store after the migration: a dedicated `cache/kartograf/` (recommended;
   Kartograf refuses a root with foreign files) or a different place, and whether the land
   cover and HSG moves from Hydrograf's own files (`bdot10k/`, `soil_hsg/`) into that store.
2. Plain mode for the temporary HSG raster of `get_hsg_from_soilgrids`: Kartograf's head has it
   now (`calculate_hsg(output_dir=<temporary directory>, ...)`, recommended: the raster stays
   per request and out of the store); the alternative is a store version per request
   (`root=`).
3. D5 and D6 of session 97: the HSG fallback "B" and step 5 as non-critical (a failed step 5
   still ends bootstrap with exit 0); data of the 0.6.1 layout are not reused.
4. GDAL's Python binding stays outside `uv.lock` because it must equal the system library of
   the image: accept as a deviation of DEV-6.3, or install `gdal-bin` and drop the pip build
   (`generate_dem_tiles.py` runs `gdal2tiles.py`).
5. Merge of `feature/kartograf-wykorzystanie` and `chore/nogat-2.1` into `develop`: order and
   who resolves PROGRESS, CHANGELOG and `requirements.txt`.
6. Text of `docs/CLA.md` and how the CLA is signed. `CONTRIBUTING.md` describes signing by a
   comment on the pull request, as in Retman and Archiwista, and the template has the
   checkbox; both name `docs/CLA.md`, which does not exist yet.
7. `nash_estimation: "from_tc"` of `POST /api/generate-hydrograph` calls `NashIUH.from_tc`,
   deprecated since Hydrolog 0.6.2 and announced for removal in 1.0.0 (the pinned head keeps it
   and warns). Remove the REST option and the front-end choice before Hydrolog 1.0.0 (a change of
   a public interface: a plan with the author's approval, DEV-17.4), or ask Hydrolog to keep the
   method. Until then the option works.
