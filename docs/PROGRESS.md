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
| Producer pins | behind the heads | Kartograf `v0.7.0`, Hydrolog `v0.6.3`, IMGWTools `v2.1.0`; the heads need the migration of Next 2; pins change only after the first release set (ADOPTION_PLAN 5.1) |
| Branch `chore/nogat-2.1` | note | based on `develop`, not on `feature/kartograf-wykorzystanie`, which has 7 commits that `develop` lacks: `f3f23dd` (`affine>=2.4,<3`, carried here in `pyproject.toml`), a CHANGELOG line, and PROGRESS of sessions 98 and 99. Merging both needs a manual resolution of this file and of the deleted `requirements.txt` |
| Nogat standard 2.1, environment | done | `backend/uv.lock` replaces `requirements.txt`: seeded with the versions of the image built on 2026-10-18 (no third-party change), caps `sqlalchemy<2.1` and `affine<3` with their reasons in `pyproject.toml`; `dev` group, extra `viz`; `[tool.uv] package = false`; `develop` carries `0.5.0.dev0`, read through `core/version.py`; the Dockerfile builds with `uv sync --locked --no-dev` (GDAL's Python binding stays outside the lock); editor, git and `.env.example` files |
| Nogat standard 2.1, quality tooling | planned | ruff rule set of DEV-7.2, mypy `strict` with per-module overrides, markers and `tests/contract`, coverage floor, `scripts/gate.sh`, CI, Dependabot |
| Nogat standard 2.1, contribution files | planned | `SECURITY.md`, `CONTRIBUTING.md`, `CONTRIBUTORS.md`, pull request template (DEV-13.7, DEV-16.2, DEV-16.4) |
| Nogat standard 2.1, documentation | in progress | done: this file and [BACKLOG.md](BACKLOG.md); planned: `CLAUDE.md` in English with Deviations, README in the order of DOC-2.1, ADR index and an ADR for the adoption, `docs/DEVELOPMENT_STANDARDS.md` deleted; the Polish documents are still to translate (Next 1, Translations) |
| Nogat standard 2.1, error registry and REST (ERR-1 to ERR-6, DEV-11.1, AGI-6.2 to AGI-6.4) | planned | vendored registry and schemas, generated `core/_errors.py`, `HydrografError`, `application/problem+json`, `Accept-Language`, OpenAPI `operationId`s |
| Data output (DEV §19, ECO-051) | planned | profile `app` consumes Kartograf in store mode; waits for the first release set; call sites in Next 2 |
| Gate | not yet | `scripts/gate.sh` does not exist yet; the old checks were `ruff check`, `ruff format --check` and `pytest tests -m 'not db and not benchmark'` in `backend/` (187 ruff findings, 67 files to format, 1 failing test before this branch) |
| CI | old | `.github/workflows/ci.yml` runs lint, tests with PostGIS and the audit with uv and the lock (interim); nothing is pushed from this branch |

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
| Push of `chore/nogat-2.1`, pull request, merge into `develop` | approvals (DEV-3.3) |

## Next

1. **Finish the standard 2.1 adoption on `chore/nogat-2.1`** (one commit per step, gate
   green before each; rules: `git -C ~/workspace/Nogat show feature/data-output:standards/<file>`;
   Archiwista's branch `chore/nogat-2.1` is the worked example of an `app`). Remaining
   gaps of the inventory of 2026-10-25, in this order:
   - **Format and lint.** `ruff format` over `backend/` (67 files), then the rule set of
     DEV-7.2 (`W`, `C4`, `D` added; 187 findings today, about 70 more with `D`; tests ignore
     `D`).
   - **mypy.** `strict` over `backend/` (2,313 errors today, 426 of them outside `tests/`):
     fix what is mechanical, per-module overrides for the rest, listed in CLAUDE.md (DEV-7.3).
   - **pytest.** `--strict-markers`, markers `live`, `db`, `slow` (plus `benchmark`),
     `tests/contract`, coverage floor 80 (DEV-7.5, DEV-10.1).
   - **Gate and CI.** `scripts/gate.sh` and `scripts/check-commits.sh` (they run in
     `backend/`; the commit step in the repository root; `.pre-commit-config.yaml` goes), CI from
     `standards/ci` in the `app` variant (gate on Linux, a `db` job with PostGIS, audit),
     Dependabot (DEV-7.6, DEV-7.7, DEV-13.6).
   - **Contribution files.** `SECURITY.md`, `CONTRIBUTING.md`, `CONTRIBUTORS.md`,
     `.github/PULL_REQUEST_TEMPLATE.md` (without the CLA text).
   - **CLAUDE.md, README, ADR.** `CLAUDE.md` in English within 200 lines with the profile,
     Deviations and the code map; delete `docs/DEVELOPMENT_STANDARDS.md` (DEV-1.3); README in
     English in the order of DOC-2.1 (profile `app`: Run and Deploy), at most 400 lines; ADR
     index at the top of `docs/DECISIONS.md` and a new ADR for the adoption (DOC-8.2).
   - **Translations** to English (DEV-2.1, ECO-005), most useful first: CHANGELOG (sections
     as DOC-7.1), ARCHITECTURE, DECISIONS, DATA_MODEL, `docs/integrations/*`, SCOPE, PRD,
     COMPUTATION_PIPELINE, QA_REPORT, TECHNICAL_DEBT, BENCHMARK_QUERIES,
     CROSS_PROJECT_ANALYSIS, BACKLOG, `backend/scripts/README.md`; then docstrings, comments
     and log messages of the 23,700 lines of Python, and user-facing texts into translation
     resources (DEV-2.3, DEV-15.2). The 40 plans of the ignored `notes/superpowers/plans/`
     move to `docs/plans/` after translation, without `Approved:` lines (the author approves).
   - **Error registry and REST.** Vendored `error_registry.json` and `schemas/agent/` from
     the Nogat commit `cc656e7` in `schemas/nogat/`, `scripts/generate_errors.py`, generated
     `core/_errors.py`, `HydrografError` with `code`, `message`, `details`, `hint`
     (DEV-11.1); `application/problem+json` for every error with `type`, `title`, `status`,
     `detail`, `instance`, `code`, `hint`, `details` and `errors[]` with JSON Pointers; the
     status from the registry (validation errors become 400, not 422); English texts by
     default and Polish with `Accept-Language: pl` (the front end sends it); OpenAPI
     `operationId` from `generate_unique_id_function`; contract tests (AGI-6.2 to AGI-6.4,
     AGI-6.6, ERR-3, ERR-4). The 68 `HTTPException`s in `backend/api` are the starting point.
   - **Other gaps found**, not in scope of a step: logs use f-strings (DEV-12.3), 60 lines of
     JavaScript are longer than 100 columns and the modules are IIFEs, not ES modules
     (DEV-15.1), the front end has Polish text inline (DEV-15.2), `tests/performance` stands
     beside the standard tree (DEV-5.2). Deviations are recorded in CLAUDE.md.
2. **Migrate to the producers' heads after the first release set** (Nogat plans
   `2026-10-24-data-output.md` step 8 and `2026-10-20-first-release-set.md` step 8; pins stay
   until then). Probe of 2026-10-25 in a throwaway environment, committed nowhere: Kartograf
   `feature/data-output` @ `343d659` (0.8.0.dev0, `root`, store marker, `--check`), IMGWTools
   `feature/data-output` @ `a304521` (3.0.0), Hydrolog `chore/nogat-2.1` @ `d4f7282`
   (1.0.0.dev0). Result of `pytest tests -m 'not db and not benchmark'`: 10 tests fail because of
   Kartograf, and every call listed here as "untested" breaks at run time while its tests pass,
   because they mock Kartograf. Pin the producer's commit while its tag is missing (REL-5.3),
   migrate, run the suite, then pin the tags. Kartograf's own "Migration guide: data output"
   is written with the last step of its ADR-054: read it again before starting.
   - **Kartograf** (store mode, `root`; there is no plain mode on the head yet, ADR-054):
     - `core/cn_calculator.py`: `check_kartograf_available` imports
       `kartograf.hydrology.HSGCalculator` (gone, returns False, so the CN silently falls
       back); `get_hsg_from_soilgrids` calls `HSGCalculator().calculate_hsg_by_bbox(bbox,
       hsg_path)` into a temporary directory and `get_hsg_statistics(hsg_path)`: use
       `calculate_hsg(root=..., bbox=bbox)` and `hsg_statistics(report.files[0].file.path)`
       (`files[0].path` after the plain-mode step of ADR-054). Without a plain mode the raster
       lands in the store, not in a temporary directory. `hsg_statistics` now also returns a
       `nodata` key: skip it, or the dominant-group code (`max(..., key=percent)`) can pick it.
       `get_land_cover_stats` imports `LandCoverManager`, calls `download_by_teryt(teryt)` and
       `download_by_bbox(bbox)` inside `except Exception: return {}` (an ImportError becomes
       "no land cover" and the default land cover is used silently): use
       `download_landcover(product="bdot10k", root=..., teryt=...|bbox=...)`, read
       `report.files[0].file.path`, `report.failed` and `report.ok`.
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
       timeout=600)`: use `calculate_hsg(root=..., bbox=bbox_poland)` (no `output_path`, no
       `timeout`); `check_hsg_cache` reads `extra.derived` and `kartograf_version` of the sidecar
       and the `soil_hsg/hsg_poland.tif` path goes (Kartograf versions the raster, `update=`).
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
   - **IMGWTools** (`fetch_pmaxtp`, unchanged): `scripts/preprocess_precipitation.py` and
     `scripts/analyze_watershed.py` call `fetch_pmaxtp(latitude=..., longitude=...)` and read
     `result.data.get_precipitation(...)`, `result.data.ks|sg|rb`; signature
     `(latitude, longitude, *, method='POT', timeout=30.0, validate_coords=True)` and model
     verified on the head. Change only the pin (`v2.1.0` to the 3.0.0 tag). Renames in
     IMGWTools that Hydrograf does not use: `IMGW_STORE_ROOT` is `IMGW_ROOT`, `IMGW_DATA_DIR` is
     `IMGW_REFERENCE_DIR`, store and export options are `root`, `output_dir`, `output`. Hydrograf's
     own settings `IMGW_GRID_SPACING_KM` and `IMGW_RATE_LIMIT_DELAY_S` (`core/config.py`,
     `.env.example`) share the `IMGW_` prefix of IMGWTools, whose settings ignore unknown keys.
   - **Hydrolog** (library): the imports of `api/endpoints/hydrograph.py`,
     `scripts/analyze_watershed.py` and `core/morphometry.py` resolve and the offline suite
     passes on the head. Expect numerical changes (CHANGELOG of Hydrolog, "Breaking - changed
     numerical results"): `WatershedParameters.calculate_tc("nrcs")` took 204.8 min on 0.6.3
     and 167.2 min on the head for one test watershed (mean slope before channel slope), the
     Snyder hydrograph has a duration correction; update expected values if tests pin them.
     `calculate_tc("faa"|"kerby")` needs `overland_length_km` and `overland_slope_m_per_m`
     (`InvalidParameterError`, also a `ValueError`, so `except ValueError` still works);
     `_calculate_tc` in `api/endpoints/hydrograph.py` calls `ConcentrationTime.faa|kerby|
     kerby_kirpich` directly and is unaffected. `scripts/analyze_watershed.py` documents
     `tc_method` as `kirpich, scs, giandotti`, but `scs` was never accepted (the name is
     `nrcs`). The CLI of Hydrolog changed (catalog, `hydrolog-result/1`, exit codes 13 for
     `calculation_error` and 12 for `forbidden`); Hydrograf uses the library only. Routing
     (`route lag|cascade|level-pool|muskingum|muskingum-cunge|network`, ADR-0007, ADR-0008) is on
     the Hydrolog branches `feature/routing-*`, not merged into `develop` on 2026-10-25;
     nothing to migrate, an option for the sewer and Hydraulik work.
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
2. Plain mode for the temporary HSG raster of `get_hsg_from_soilgrids`: wait for ADR-054's plain
   mode (`output_dir`) or accept a store version per request.
3. D5 and D6 of session 97: the HSG fallback "B" and step 5 as non-critical (a failed step 5
   still ends bootstrap with exit 0); data of the 0.6.1 layout are not reused.
4. GDAL's Python binding stays outside `uv.lock` because it must equal the system library of
   the image: accept as a deviation of DEV-6.3, or install `gdal-bin` and drop the pip build
   (`generate_dem_tiles.py` runs `gdal2tiles.py`).
5. Merge of `feature/kartograf-wykorzystanie` and `chore/nogat-2.1` into `develop`: order and
   who resolves PROGRESS, CHANGELOG and `requirements.txt`.
6. Text of `docs/CLA.md` and how the CLA is signed (the pull request template has the checkbox
   that `CONTRIBUTING.md` refers to).
