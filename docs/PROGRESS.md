# PROGRESS — Hydrograf

The current state, the next steps and the questions for the author (DOC-6.1; ADR-010: PROGRESS
holds the current state, the history stays in git). The full file up to 2026-11-10, with the
logs of every session, is `git show 39849f0:docs/PROGRESS.md` (hashes there that predate
2026-10-08 belong to the history before its rewrite). Changes for users are in
[CHANGELOG.md](CHANGELOG.md), decisions in [DECISIONS.md](DECISIONS.md), open items that are not
scheduled in [BACKLOG.md](BACKLOG.md) and [TECHNICAL_DEBT.md](TECHNICAL_DEBT.md).

## Status

| Component | State | Note |
|---|---|---|
| API (FastAPI + PostGIS) | done | Routes in ARCHITECTURE §2.2; errors are `application/problem+json` with the codes of the Nogat registry and texts by `Accept-Language` (ADR-059). Delineation precomputed on the in-memory catchment graph (ADR-021, ADR-050), escalated over the thresholds of the graph above 300 sub-catchments, and precise; every worker reloads the graph when the network in the database changes (`07112ce`). „Identyfikuj” (`GET /api/identify-point`), terrain profile with the water of the analysis results, MVT tiles, admin routes. |
| Hydrographs | done | SCS-CN (AMC I–III, own rainfall series), SCS, Snyder and Nash (Lutz, urban regression) unit hydrographs of Hydrolog; tc only from Hydrolog on the inputs each method defines (C and N from the user); the hand-off to Hydrolog (ADR-068); PMAXTP design depth as the Thiessen mean of the watershed (ADR-069); limit 250 km². |
| DEM preprocessing | done | pyflwdir on one raster or by PGW units (ADR-071, opt-in `--units`, one fill of the whole grid); F1–F7 memory fixes (`652eec6`); stream burning with the directions of ADR-077; enclosed nodata filled on request (ADR-073); the bootstrap refuses NMT sheets that leave the area uncovered (ADR-076); thresholds 10 000, 100 000, 1 000 000 and 10 000 000 m²; flow path heads and channel sources measured (ADR-070). |
| Land cover, soils, CN | done | Land cover from the BDOT10k partition by its attributes (ADR-074), the soil under the wetlands is group D and the lawns of KUSK/KUKO are open space (ADR-078); the soil groups of the least permeable SoilGrids layer of 0–100 cm by default, `soil.hsg_depth_rule` (ADR-079, in `develop` since `b38b657`; Hydroni's run 4 and, since 2026-11-12, production have them); the CN is that of the soil-cover complexes from Hydrolog's TR-55 table, computed at query time (ADR-075 and its amendments of 2026-11-09; migration 006 dropped `land_cover.cn_value`). The export of catchment parameters gives CN AMC I/II/III and the control columns of the weighted runoff. |
| Producers | done | `develop` pins Nogat's release set candidate-3: Hydrolog `930915d`; Kartograf `d0990c8`, Obserwator `f9f4ee7` as in candidate-2. Production (since its update of 2026-11-11) and Hydroni run them. The network hand-offs go to Hydrolog's GUI (`127.0.0.1:8070`, its `develop` `35ba444` since 2026-11-12, which routes a reach that Muskingum-Cunge cannot grid as linear reservoirs with the warning `diffusion_dominated`, Hydrolog ADR-0026). A Kartograf store shared with Archiwista is read only through closed Archiwista sets (ADR-067). |
| Front end | done | Nogat visual identity and Archiwista's shell (ADR-065), modes Przeglądanie / Wybierz zlewnię (options „Jedna zlewnia” and „Sieć zlewni” over the map) / Profil terenu / Identyfikuj. The top-bar „Instrukcja” button opens the welcome dialog; the user guide is a scrolling page with a TOC and chapters, while `docs/Hydrograf-prezentacja.html` remains a slide deck. The welcome text and guide name the data area from `frontend/data/instance.json`; external analyses come from `frontend/data/results/index.json` (SFINCS), alongside the MZP overlay and `?v=` asset versions. On `feature/nogat-kit` (2026-11-12, not merged; Next 12): Nogat's GUI kit 0.1.0 (ADR-082), the top-bar menu „Aplikacje” of the GUIs in `HYDROGRAF_GUI` (`GET /api/gui`) and the hand-off through the kit's `nogat-handoff.js`; Hydrograf's copies of Nogat's tokens, marks, kit, schemas and registry equal Nogat `7786271`. |
| Network delineation | done | `POST /api/delineate-network` and its preview on the catchment graph `POST /api/delineate-network/preview`, the option „Sieć zlewni” of „Wybierz zlewnię” in two stages (the preview after every change of the points, then „Oblicz charakterystyki”) and one hand-off of the network to Hydrolog's Sieć (ADR-080, amended on 2026-11-11 by the plan `2026-11-11-network-nodes`: every point is a node, `J` at a confluence it is drawn to within 50 m up or down, `P` elsewhere, numbered from the closing section up, the outlet `O`; ADR-081); the plans `2026-11-10-network-delineation`, `2026-11-11-network-preview` and `2026-11-11-network-nodes` are done. Merged into `develop` with `feat/network-nodes` on 2026-11-11; networks above 60 M cells stay refused. Open methodology: Next 10. |
| Admin panel | done on `feat/admin-panel`, not merged | Step 3 of Nogat's plan `2026-11-13-admin-panel` (DEV-15.13, ECO-067, kit 0.7.0; ADR-086): `/admin/` is the kit's `<nogat-admin>` („Zgłoszenia”, „Statystyki”, „Stan”, then „Zasoby”, „Przetwarzanie NMT”, „Czyszczenie”, „Granice i kanalizacja”), `/admin` answers 308, `/admin.html` and Bootstrap are gone; `status` (database, catchment graph, data directory) replaces `dashboard`, `stats` reads `stats.jsonl`; no generated key (`admin_key_not_configured`); admin answers `no-store`, the panel's requests limited, not counted. The reports of the old form keep their `legacy` member, which the kit's view does not show (Next 15). Next 20. |
| Storm sewer | done | ADR-051, ADR-052; no data source yet (BACKLOG). |
| Provider attribution | done on `fix/provider-attribution`, not merged | The author's order of 2026-11-13, step 4 of Nogat's plan `2026-11-13-provider-attribution` (DEV §20, ECO-060; ADR-083, plan `2026-11-13-provider-attribution`): the lines the PMAXTP terms require (PS, PP, M; N, RK) from `core/attribution.py` in the hydrograph response and its hand-off, the panel, the exports, an own series copied from PMAXTP, the results manifest's layer, point card and profile, `analyze_watershed` and the guide and slides. Next 13. |
| Public service (regulamin, limit, logs, statistics, form) | done on `feature/public-gui`, not merged | The author's order of 2026-11-13, step 3 of Nogat's plan `2026-11-13-gui-terms` (DEV-15.7 to DEV-15.12, DEV-18.1, ECO-061 to ECO-063; ADR-084, plan `2026-11-13-public-gui`): Nogat's regulamin at `/regulamin.html` from `[nogat.operator]` of NOGAT_CONFIG, the footer and the menu's `terms`; 300 requests in 60 s per client address in the app (tiles 3,000, the form 5 in 5 minutes), 429 as a Polish page or `rate_limited`; nginx and API logs without addresses in the journal, at most 14 days; daily totals in `<data_dir>/hydrograf/stats.jsonl`; „Zgłoś uwagę” with the text and the view's context, migration 007; kit 0.4.0; one API process. Next 14, 15. |
| One strip of the providers' lines | done on `feature/compact-sources`, not merged | The author's request of 2026-11-13, step 4 of Nogat's plan `2026-11-13-compact-attribution` (DEV-20.5, DEV-20.7, ECO-064; ADR-083 amended, plan `2026-11-13-compact-sources`): kit 0.5.1; the map shows PS and PP once in the kit's strip `<nogat-sources>` under the map and the panels („Źródła i warunki” opens every line and the terms), no block of lines in the panel, legend, (i), card or drawer; the welcome dialog shows the full lines and terms of `GET /api/terms`; the phone sheets stop above the strip; exports, hand-off and API unchanged. Next 16. |
| The providers' terms linked, not restated | done on `fix/minimal-provider-texts`, not merged | Nogat ECO-065 (develop `b29eada`, kit 0.6.0; ADR-083 and ADR-084 amended): PMAXTP's `terms_notice` is RK alone, „Regulamin danych PMAXTP: https://klimat.imgw.pl/opady-maksymalne”, without the notice N; `core/terms.py` without `imgw-terms`; `analyze_watershed` tells terms lines by „Regulamin <whose terms>: <address>” and drops the retired lines on merge; guide, slides and PDF; kit and hand-off schema copied. Next 17. |
| Regulamin 1.0 corrected, GUGiK's and ISRIC's lines, logs of ECO-066 | done on `fix/terms-1.0`, not merged | Step 3 of Nogat's plan `2026-11-13-terms-fix` (approved 2026-11-13; ADR-085): kit 0.6.2 (Nogat `5703c53`), `BLOCKS` without `copernicus` and `esri`; G and SG in every response, export, image and hand-off of NMT, BDOT10k and SoilGrids data, dated from `sources` of `instance.json`, GK and SK in the strip; the orthophoto of GUGiK; the libraries in `frontend/vendor/`, CSP `'self'`; the logs of Nogat ECO-066 (`core/nogat_logging.py`, `<state_dir>/hydrograf/logs`, nginx without logs, Docker `local`). Next 19. |
| Tests and gate | done | `scripts/gate.sh` on the head of `feat/network-nodes` (2026-11-11): 2,225 passed, 170 deselected, coverage above the floor of 80 %; on `feature/nogat-kit` (2026-11-12, merged as `48bf24a`): 2,244 passed, 170 deselected, coverage 87.0 %; on `fix/provider-attribution` (2026-11-13): 2,260 passed, 170 deselected, coverage 87.1 %; on `feature/public-gui` (2026-11-13): 2,323 passed, 170 deselected, coverage 87.5 %; on `feature/compact-sources` (2026-11-13): 2,325 passed, 170 deselected, coverage 87.5 %; on `fix/minimal-provider-texts` (2026-11-13): 2,325 passed, 170 deselected, coverage 87.5 %; `db` tests on `b5e1154`: 158 passed, 1 skipped (the integration test of the network endpoint was updated for the plan `2026-11-11-network-nodes` and not run against PostGIS since). CI in `.github/workflows/ci.yml`. |
| Documentation | in progress | Nogat standard 2.1 in English; the documents still in Polish are listed in Next 7. |
| Release v0.5.0 | in progress | `develop` carries 0.5.0.dev0, `main` v0.4.0 (2026-03-03). The next release is v0.5.0 (the author, 2026-11-03); the author extends the candidate and sets the tag himself (2026-11-05). |
| Hydraulik integration | blocked | Paused by the author until Hydraulik works well enough (BACKLOG). |

### Production

- **Code:** checkout `~/workspace/Hydrograf`, local `develop` (0.5.0.dev0) fast-forwarded on 2026-11-11 to the merge of `feat/network-nodes` at the author's request, with a new image for `GDAL_CACHEMAX=64` (before it `894810c` since 2026-11-10 05:00 CET); the later merges of 2026-11-12 change documents only. The default compose project (`hydro_db`, `hydro_api`, `hydro_nginx`) with the development override: the code is mounted from the checkout and served with `--reload`, so an edit there reaches the live API, and the files must be readable by uid 999 (check out under `umask 022`). `docker/nginx.conf` is mounted as one file: restart `hydro_nginx` after a checkout rewrites it. Image `hydrograf-api:latest`; `.env` names `HYDROGRAF_PUBLIC_HOST=hydrograf-test.debever.pl` and the private Kartograf store (no `HYDROGRAF_KARTOGRAF_ROOT`).
- **GUI kit:** on 2026-11-12, at the author's request, `develop` took `feature/nogat-kit` (`48bf24a`, ADR-082) and the checkout followed; `.env` gained `HYDROGRAF_GUI` with the public addresses of Hydrograf, Hydrolog (`https://hydrolog-test.debever.pl/`), Archiwista (`https://archiwista-test.debever.pl/`) and Obserwator (`https://obserwator-test.debever.pl/`, a placeholder for now), and `hydro_api` was recreated (`docker compose up -d --no-deps api`). `GET /api/gui` answers the table and the public page shows „Aplikacje”.
- **Access:** `127.0.0.1:8080`; public `https://hydrograf-test.debever.pl` through a Cloudflare Tunnel. Give testers the `https://` address: the HTTP redirect is a 301, which can turn a POST into a GET.
- **Data:** the Kaczawa above the node 51.222825 N 16.179380 E; since 2026-11-12 08:35 CET the data built by the steps K0–K13 of the review instance kaczawa2 on production's inputs, accepted by the author the same day (the switch is logged in [the runbook](runbooks/2026-11-10-reprocessing.md)'s §11; kaczawa2 was then removed, its README with the steps, its helper scripts and its logs are in `/data/nmt/hydrograf-backup-2026-11-12/kaczawa2/`). Boundary `data/boundary/zlewnia_kaczawy_jednostki.gpkg`, the union of the kept units (792.009 km²; `instance.json` says 792.0, soil groups `least-permeable`); the old boundary `zlewnia_kaczawy_790km2_przyciecie.gpkg` (790.564 km²) stays beside it for comparisons. Alembic `006`; 41,515 / 4,548 / 496 / 49 segments at 1 ha / 10 ha / 1 km² / 10 km², one outlet each, and the 20 rasters of `data/nmt` unchanged since the re-cut of 2026-11-10 at 23:53 CET (31,680,357 cells; every sub-catchment equals its label raster at the four thresholds); a graph of 46,608 nodes. Land cover (BDOT10k packages 0205, 0206, 0207, 0209, 0219, 0221, 0226 and 0262), soil groups, `bdot_streams` (3,819), the overlays, the depressions (215,934) and the DEM tiles cover the whole boundary, the 1.6 km² block at 50.901 N 15.959 E included; soil groups of ADR-079 (the least permeable layer of 0–100 cm): B 90.78 / C 8.86 / D 0.36 %, CN 67.8 at the Kaczawa's outlet (67.0 before), Kamiennik 61.2 unchanged; 134,352 PMAXTP points; the SFINCS result `sfincs-kamiennik-24h-p1` under „Wyniki analiz”. The cache has the Kartograf 0.7.0 layout (`cache/bdot10k/`, no `cache/kartograf/`); `cache/soil_hsg/` holds the 0–100 cm raster of the rebuild (`hsg_least-permeable_0-100cm_275000_335000_314000_378000.tif`, from the Kartograf store `/mnt/magazyn/agent-tmp/kaczawa-hsg/store`) beside the old 0–5 cm `hsg_poland.tif`: a reprocessing passes the packages and the HSG raster explicitly and downloads nothing (runbook §0).
- **Rules:** run a bootstrap or a DEM run only in a one-off container (`docker compose run --rm --no-deps api ...`), never by `exec` in `hydro_api` (an OOM there takes the API down); `docker builder prune -f` before an image build while Docker's data root is on `/`.
- **Backup and rollback:** `/data/nmt/hydrograf-backup-2026-11-12/` (`hydro_db.dump` of production before the data switch of 2026-11-12, alembic `006`; `kaczawa2_hydro_db.dump`; `SHA256SUMS`; `frontend_data.tar.zst`; `frontend-data-pre/` with the 9 replaced files of `frontend/data`; `frontend-data-new/`; the old `hydro_merged.gpkg`; `env`; `git-head.txt` `a1b5f86`; `tiles_metadata.json`; `switch-2026-11-12.log`; `kaczawa2/`). After the author's acceptance the old database, tiles and DEM tiles were removed on 2026-11-12, so a rollback restores `hydro_db.dump` into a new database and renames it to `hydro_db` with the API stopped, unpacks `frontend_data.tar.zst` over `frontend/data`, puts the old `hydro_merged.gpkg` back and removes `data/boundary/zlewnia_kaczawy_jednostki.gpkg`; the tiles stay, since the stream tables they are made from did not change. The earlier `/data/nmt/hydrograf-backup-2026-11-10/` (alembic `004`, `94d7523`) and the image `hydrograf-api:pre-2026-11-10` stay; `data/nmt.pre-recut` holds the rasters of 2026-11-10 04:37 cut to the old boundary (runbook §11). The older backups in `/data/nmt/` (2026-11-01, the state before the cut and the source of the runbook's §4.9; 2026-11-02; 2026-11-04-handoff, -pinset, -std10; 2026-11-05-lutz, -v050; the feedback backup of 2026-11-03) stay; their images are gone.

### Hydroni instance

- **Code and stack:** worktree `~/workspace/Hydrograf-hydroni` detached at `a46adb4` of `develop` since 2026-11-11 (image `hydroni-api` rebuilt from it at 18:09; its README's `Code:` line names the commit), compose project `hydroni` (`hydroni_db`, `hydroni_api`, `hydroni_nginx`) run by `~/data/hydrograf-hydroni/dc` (system Docker, base file, prod overlay and `compose.instance.yml`); `127.0.0.1:8081`, public `https://hydrograf-hydroni.debever.pl`. Configuration outside the repository in `~/data/hydrograf-hydroni/` (README with the update and reprocessing steps, `bootstrap.sh`, `config.yaml`, `hydroni.env`, `secrets/`).
- **Storage:** `data` and `frontend/data` on the NAS (`/mnt/magazyn/agent-tmp/Hydroni/hydrograf/`, CIFS: the API and nginx run as uid 2001 because the share forces 2001/0640, and SQLite or GeoPackage files are written locally, then copied); the tiles, the cache and `data/hydro` on the local disk in `~/data/hydrograf-hydroni/`; the database in the volume `hydroni_postgres_data`.
- **Data:** area h07 (2,940.7 km²), Archiwista project `h07`, closed set `2026-4` (728 pins; `2026-3` with the soil-group raster of ADR-079; `2026-3` is `2026-2` plus the sheet N-33-118-B-a-4-2 that ADR-076 asked for). Settings: `--units` with the 223 h07 catchments (27 units), `dem.stream_burning: main`, `--waterbody-mode none` (the author: no lake is endorheic), no buildings, no inflow from outside the area (the author). Active run 4, bootstrapped on 2026-11-10 10:08–12:33 CET (`bootstrap-20261110-run4.log`; run 3 from `2026-3`: `bootstrap-20261110-run.log`): 710 sheets (20 delivered as 1 m grids and averaged to 5 m), 201,195 segments at 0.01 / 0.1 / 1 / 10 km², the soil groups of ADR-079 with 92.00 km² of wetlands made group D, 73 burned lines reversed by ADR-077.
- **Exports for the author** (parameters of the 223 catchments): v5 `/mnt/magazyn/agent-tmp/Hydroni/h07_parametry_zlewni.gpkg` (2026-11-10, set `2026-4`, with the runoff control columns), v4 `h07_parametry_zlewni_v4_2026-11-10.gpkg` (set `2026-3`) and v3 `h07_parametry_zlewni_v3_2026-11-08.gpkg` beside it, v1 and v2 in `~/data/hydrograf-hydroni/cache/`.

### Other places

- The Kartograf store shared with Archiwista, `~/data/archiwista-public/store`, is read only through the closed sets of `bootstrap --project --set` (ADR-066, ADR-067); production keeps its private store.
- `/data/nmt/` also holds the Opolskie NMT of 2026-09 (`nmt_5m/`, 3,233 sheets in the layout before Kartograf 0.7.0, not reused: ADR-061), `pilot_opolskie/` and the voivodeship boundaries (`boundaries/`).
- The SFINCS model of the Kamiennik: `~/hydraulik-work/kamiennik-12h-p1/`; the clip script of 2026-11-01: `~/scratch/hydrograf-clip/clip_hydrograf.py`; the GPT front-end test report: `~/scratch/gpt-guides/hydrograf-test-report.md`.
- `docker-compose.staging.yml` and `scripts/staging-compose.sh` stay for staging stacks; the runbook of 2026-11-10 ran its staging with plain compose files instead (its §2).

## Next

1. **Hydroni's code and README:** Hydroni still runs `a46adb4`, before the main channel and Lc
   fixes of `feat/network-nodes` that production has; updating it is the author's call. Its
   README `~/data/hydrograf-hydroni/README` still asks for `./dc restart api` after a bootstrap
   (step 2): since `894810c` the API reloads its graph by itself.
2. **Leftovers of the delineation fix** (`07112ce`, 2026-11-10):
   - `POST /api/generate-hydrograph` without `morphometry` merges the sub-catchments at
     10 000 m² with no cascade, up to the 250 km² limit (`api/endpoints/hydrograph.py`); the GUI
     does not take this path.
   - A large precomputed delineation still takes tens of seconds: the Wełna at 1 km² (500 km²,
     Hydroni) took 51.4 s: the merge 16.9 s (the union 6.0 s and the boundary smoothing of ADR-032
     9.9 s: a ±2 m buffer, three Chaikin iterations up to 128k vertices, `buffer(0)`; a faster
     smoothing changes the shape, Open questions 2), the land cover query 7.7 s (10.1 s before
     `07112ce`), the flow paths 12.9 s (raster reads from the NAS 6.1 s; `np.isin` 2.4 s, about 2 s
     less with a lookup table) and the Thiessen weighting 3.2 s (about 2.5 s less with a prepared
     geometry); a batched union is 1 s slower than `ST_UnaryUnion`.
3. **HSG from the least permeable layer of 0–100 cm** (ADR-079, in `develop` since `b38b657`):
   Hydroni's run 4 (set h07/2026-4) and, since 2026-11-12, production have the groups of the
   rule. The Kaczawa confirms the estimate of ADR-079 (B 90.78 / C 8.86 / D 0.36 %, CN 67.8 at
   the outlet against 67.0, Kamiennik 61.2 unchanged); ADR-079's Consequences still give
   estimates, and the measured groups and CN of Hydroni's run 4 and of the Kaczawa are to be
   written there.
4. **Hydroni, for the author's review:** catchment 1883617 and the 11 catchments whose
   polygon/NMT area ratio is above 1.2 (183816, 1863141, 186352, 1863561, 1865212, 186536, 18654,
   1866532, 1883613, 1883684, 188524), with `scripts/diagnose_catchment_exits.py`. The 20 sheets
   that GUGiK delivers as 1 m grids stay averaged to 5 m in the mosaic (Kartograf PROGRESS 28;
   later flights may replace them). The report to GUGiK is the author's step: the draft
   `/mnt/magazyn/agent-tmp/Hydroni/sprawdzenie/zgloszenie_gugik_nmt5m.md` (Polish, not proofread;
   the list of the 81 sheets has to be generated again before it is sent).
5. **Release v0.5.0:** a round of tests and code review; the release commit (version 0.5.0, the
   section `[0.5.0]` from `[Unreleased]`); the pins follow Nogat's release set until the producers
   have tags, then the tags (REL-5.3, REL-5.6, ADR-060, ADR-061); merge `develop` → `main`; the
   author sets the tag.
6. **After the release:** H2 and S5 of [the store migration plan](plans/2026-11-02-store-migration.md):
   the Kaczawa as an Archiwista project (`projects/kaczawa` does not exist yet) and production
   bootstrapped from its closed set instead of the private cache; Docker's data root from `/` to
   `/data` (BACKLOG, needs root and the author).
7. **Translations to English** (DEV-2.1). Still Polish, most useful first: DECISIONS (the bodies
   of ADR-001 to ADR-057, kept as records; the index and ADR-058 on are English; translating a
   heading changes its link in the index), DATA_MODEL and COMPUTATION_PIPELINE (the parts not
   rewritten since 2026-11-05), `docs/integrations/HYDROLOG.md` and `OBSERWATOR.md` (their pin
   sections are English), INFO_TEXTS_SOURCES, BENCHMARK_QUERIES, the released versions of the
   CHANGELOG (0.4.0 and older). Then the docstrings, comments and log messages of the Python code,
   and the user-facing texts into translation resources (DEV-2.3, DEV-15.2). The 40 plans of the
   ignored `notes/superpowers/plans/` move to `docs/plans/` after translation, without
   `Approved:` lines.
8. **Error registry, loose ends** (ADR-059): the admin routers document `401` only
   (`api/main.py`), so the `404` and `409` of `bootstrap/start`, `bootstrap/cancel` and the
   feedback routes are undocumented; the texts of core exceptions that reach `details.cause`
   (`invalid_parameters`, `invalid_bbox`, `invalid_boundary_file`) are the library's; the gateway
   errors of nginx are not problem documents (CLAUDE.md, AGI-6.3).
9. **Small items carried over from earlier sessions** (no other home):
   - `docker-compose.staging.yml` still publishes the staging nginx on `192.168.88.9:8081`, to be
     removed after S7 (the author's decision in S4; S7 ran in place), and
     `scripts/staging-compose.sh` accepts only the branch `feature/store-migration`.
   - „Identyfikuj” reads the water bodies from `frontend/data/bdot_lakes.geojson`
     (`core/point_info.py`), not from the database.
   - `area_km2` is rounded to 4 decimals in the precise mode (`api/endpoints/watershed.py`) and to
     2 on the graph path (`core/watershed_service.py`).
   - Snyder fails where `length_to_centroid_km` is 0 until the user gives Lc; the shape indices of
     very small catchments fall outside their ranges; `asymmetry_coefficient` is never computed
     (TECHNICAL_DEBT, TODO in `core/watershed_service.py`); the API gives no warnings about the
     applicability of the methods (the GUI has static (i) notes).
   - Report to Hydrolog: its conversion of the CN to AMC I/III rounds the CN to an integer
     (`runoff/scs_cn.py`).
   - The docstring of `api/endpoints/watershed.py` says the precise mode runs a „BFS at 1000m²”
     (the code takes `DEFAULT_THRESHOLD_M2`, 10 000); `backend/config.yaml.example` lists
     `thresholds_m2: [1000, 10000, 100000]` and `_DEFAULT_CONFIG` of `core/config.py`
     `[10000, 100000, 1000000]`, while the pipeline uses `PIPELINE_THRESHOLDS_M2`.
   - `load_bdot_streams_from_gpkg` (`core/db_bulk.py`) may stop on a feature whose geometry is
     NaN rather than None (found 2026-10-25, not checked again).
   - Bootstrap step 8 warned that `ogr2ogr` and `pmtiles` are missing from the image (the
     `.mbtiles` and `.pbf` tiles are still made; 2026-10-30, not checked again).
   - Feedback #11 (the hydraulic length): no reply to its reporter is recorded; in the precise
     mode the hydraulic length stays an approximation, measured from the outlet of the node that
     holds the clicked point (its diagnosis of 2026-08-02, not checked again).
   - Ideas without a backlog entry: the flow path downstream of the outlet, the terrain profile
     as CSV, own vector layers and WMTS or WFS services on the client (BACKLOG has the WMS and the
     inputs of the pipeline), the direct catchment of a flow-through lake, Manning's n from
     BDOT10k and the land cover at 5 m for Hydraulik.
   - Kartograf keeps the mode of a temporary file on the files it moves from `/tmp` (RCN
     `_unpack_checked_layers`, WFS `_fetch_features`), so other uids cannot read them (Nogat plan
     D10; Kartograf's to fix).
   - `docs/Hydrograf-prezentacja.pdf` predates chapter 06 „Sieć zlewni” (printed 2026-11-05);
     its HTML twin has the chapter, the PDF was not printed again.
10. **Network methodology, open** (ADR-080). Each with its proposal:
    1. *Closed by the author on 2026-11-11:* a large tributary without a point that joins a
       reach between its ends stays in the reach's przyrzecze (plan `2026-11-11-network-nodes`).
    2. A reach's length from the D8 flow distances is longer than the BDOT10k lines: the check
       lengths of the plan's Results are 4–7.1 % shorter (S2, S5), which lengthens the travel
       time as much. Proposed: the BDOT10k length where the lines run continuously along the reach.
    3. A reach's slope from the NMT at its two end cells is noisy on short or flat reaches.
       Proposed: a fit along the channel's profile.
    4. The tolerance of 50 m (`MOUTH_TOLERANCE_M`) by which a point is drawn to a node, now up
       and down (plan `2026-11-11-network-nodes`, N3), is a click's accuracy, not a measure: at
       10 ha a gully's mouth within 50 m makes the point a node with the gully as an element.
    5. An element above 250 km² is beyond the validity of SCS-CN and gets the notice
       `over_scs_cn_limit` only; the network is not refused.
11. **The cells beyond the old boundary.** Since 2026-11-12 production's boundary is the union of
    the run's kept units (792.009 km²), and the land cover, the soil groups, `bdot_streams` and
    the presented layers are cut to it, so the block of 1.604 km² at 50.901 N 15.959 E has land
    cover and soil groups and the 0.164 km² of the old boundary that drain elsewhere are outside.
    The basin of the DEM decides, so two remainders of aPGW catchments that the DEM run routes out
    of the Kaczawa stay outside: 4.3 km² of RW60000613839 „Kaczawa do Nysy Szalonej” (largest
    part 2.32 km² at 51.1546 N 15.8936 E) and 5.9 km² of RW6000031384919 (largest part 4.40 km²
    at 51.0336 N 16.2385 E; `scripts/jcwp.py` and `logs/jcwp.log` in
    `/data/nmt/hydrograf-backup-2026-11-12/kaczawa2/`). Whether they belong to the Kaczawa is
    the author's call.
12. **Nogat's GUI kit, step 5 of Nogat's stage 1 plan** (plan `2026-11-12-nogat-kit`, ADR-082):
    **done** 2026-11-12, merged into `develop` (`48bf24a`) and deployed (Production, GUI kit).
    Another deployment sets `HYDROGRAF_GUI` in its `.env` and recreates the API; without it no
    menu is drawn. With the kit a copy on a plain-HTTP address no longer tries
    `document.execCommand('copy')`: the text is selected for Ctrl+C (Nogat D6); a one-click copy
    there would be a change of the kit in Nogat.
13. **Provider attribution, to deploy** (ADR-083, plan `2026-11-13-provider-attribution`): the
    branch `fix/provider-attribution` waits for the author's merge. Production then follows
    `develop` (the mounted code and `--reload`, no image build, no new dependency) and its
    `frontend/data/results/index.json` needs `attribution` and `terms_notice` with the PMAXTP
    lines in the SFINCS entry (the command printing them is in the plan's Deployment), or the
    layer, the point card and the profile show none; Hydroni needs an image build. The GeoTIFFs
    of the SFINCS result (`max_depth.tif`, `wse_max.tif`) carry no lines: Hydraulik's publication.
14. **Public service, to deploy** (ADR-084, plan `2026-11-13-public-gui`): the branch
    `feature/public-gui` waits for the author's merge. Before `terms_effective`:
    - the operator writes `[nogat.operator]` into `~/.config/nogat/nogat.toml`, and production's
      `.env` gets `NOGAT_CONFIG=/home/claude-agent/.config/nogat/nogat.toml`;
    - as root: `install -m 644 docker/journald.conf /etc/systemd/journald.conf.d/hydrograf.conf
      && systemctl restart systemd-journald` (without it the journal keeps the logs longer than
      the regulamin says);
    - after the merge and the checkout: `docker compose up -d --no-deps api nginx`. Both are
      recreated: new mounts (the kit and `nogat.toml` into the API), environment and log driver;
      migration 007 runs when the API starts; `nginx.conf` is a single-file mount, so only a
      recreate shows nginx the new file;
    - Cloudflare Access on `/admin`, `/admin.html` and `/api/admin/*`;
    - Hydroni: a build of the image `hydroni-api`; its prod overlay now runs one API process
      (it loses its second worker); NOGAT_CONFIG and a `hydrograf` entry of its HYDROGRAF_GUI
      are its own decision (without them it has no regulamin).
15. **The reports of the old form.** Production's `hydro_db.feedback` holds 30 reports (ids
    11–40, 2026-08-02 to 2026-11-05): 3 with a contact (ids 11, 12, 13), all 30 with a User-Agent
    and a page URL, 7 with diagnostics; a backup of 26 of them (ids 11–36) is in
    `/data/nmt/hydrograf-feedback-backup-2026-11-03T2319/`; Hydroni has none. Migration 007 keeps
    their old columns (the admin list shows them as `legacy`) until the operator has handled
    them; a later migration drops `contact`, `page_url`, `user_agent` and `diagnostics`.
16. **One strip of the providers' lines, to deploy** (ADR-083 amended, plan
    `2026-11-13-compact-sources`, step 4 of Nogat's plan `2026-11-13-compact-attribution`): the
    branch `feature/compact-sources` (kit 0.5.1) waits for the author's merge after Nogat's
    `feat/compact-attribution` and its 0.5.1 fix. Production then follows `develop` (mounted
    code, `--reload`, no image build); Hydroni needs an image build.
17. **The providers' terms linked, to deploy** (Nogat ECO-065; ADR-083 and ADR-084 amended): the
    branch `fix/minimal-provider-texts` waits for the author's merge. Then production's results
    manifest `frontend/data/results/index.json` (outside Git) gets `terms_notice` of
    `sfincs-kamiennik-24h-p1` rewritten to the one line „Regulamin danych PMAXTP:
    https://klimat.imgw.pl/opady-maksymalne”, and the API restarts to fill the regulamin of kit
    0.6.0. Earlier `analyze_watershed` outputs keep N and „Regulamin: …” until rerun.
19. **Regulamin 1.0 corrected, to deploy** (ADR-085, Nogat plan `2026-11-13-terms-fix` step 3 and
    republication step 7): after the author's merge, in `~/workspace/Hydrograf`: `.env` gains
    `NOGAT_STATE_DIR=/home/claude-agent/.local/state/nogat`; once `install -d -m 0777
    ~/.local/state/nogat/hydrograf` (the API runs as UID 999); `docker compose up -d
    --force-recreate api nginx db` (the log driver, the state mount and the new command are
    set at creation; `nginx.conf` is a single-file mount). Then, in a one-off container,
    `python -m scripts.write_instance_info --area-name "zlewnia Kaczawy" --boundary-file
    /data/boundary/zlewnia_kaczawy_jednostki.gpkg --hsg-depth-rule least-permeable --nmt
    /cache/nmt/pl_1992_5m_evrf2007 --nmt-sheets /data/boundary/kaczawa_sheets.txt --bdot10k
    /cache/bdot10k/bdot10k_teryt_{0205,0206,0207,0209,0219,0221,0226,0262}.gpkg --soilgrids
    /cache/soil_hsg/hsg_least-permeable_0-100cm_275000_335000_314000_378000.tif` writes the
    dates of G (without it G reads „b.d.”); `terms_effective` of `nogat.toml` is set to the day
    of republication and the API restarted. The old journal entries of `hydro_api` and
    `hydro_nginx` stay until root removes them (Nogat plan `2026-11-13-unified-logging`).
    Hydroni: an image build, its own `NOGAT_STATE_DIR`, and the same `write_instance_info`
    with its inputs. `docs/Hydrograf-prezentacja.pdf` is not printed again (its HTML says
    „Ortofotomapa GUGiK”).
20. **Admin panel, to deploy** (ADR-086, Nogat plan `2026-11-13-admin-panel` steps 3 and 6): after
    the author's merge, production keeps its admin key (`.env`'s `ADMIN_API_KEY`, or the secret
    `${SECRETS_DIR}/admin_api_key.txt` of the prod overlay): without one the panel refuses every
    request. `docker compose up -d --no-deps api nginx` (`nginx.conf` is a single-file mount);
    Cloudflare Access moves from `/admin.html` to `/admin`, `/admin/*` and `/api/admin/*`.
    Hydroni: an image build and its key.
18. **Unscheduled:** the rest is in [BACKLOG.md](BACKLOG.md): the hardening of the public attack
    surface (three unauthenticated DoS paths first), the „brak danych” of the hyetograph that a
    tester reported, `--thresholds` of the bootstrap, building raising (ADR-033), the read
    endpoints of v0.5.x, clipping the presented data to the boundary, the GPT items B6–B15, the
    sheet selection of `--boundary-file`, SQLAlchemy 2.1, named volumes, the traffic dashboard,
    the Opolskie data (D6) and the ADR on NMT sheet versions.

## Open questions

1. D5: the HSG fallback „B” where SoilGrids has no data, and step 5 as non-critical (a failed
   step 5 still ends the bootstrap with exit 0); BACKLOG.
2. A faster boundary smoothing (ADR-032) for large watersheds changes the shape of the boundary:
   worth it for the 9.9 s of a 500 km² watershed?
3. The text of `docs/CLA.md` and how the CLA is signed (`CONTRIBUTING.md` and the pull request
   template name the file; DEV-16.2).
4. D12 of step H1: a set's pins of producers other than Kartograf (Obserwator) are skipped
   (`utils/kartograf_set.py`): keep that once sets have several producers?
5. Show the record of the set (`bootstrap_set.json`) in the admin panel?
6. The row names „Wskaźnik rzeźby” (ΔH/√A is rather the catchment slope or Melton's index) and
   „Liczba chropowatości” (no Polish source for the name; INFO_TEXTS_SOURCES).
7. `null` instead of 0.0 in `elevations_m` of `POST /api/terrain-profile` inside DEM gaps (a
   breaking change; B5 in BACKLOG).
8. Building raising (ADR-033) in the pipeline (BACKLOG: to be decided by the author).
9. Delete `/data/nmt/pilot_opolskie/` (45 MB, the pilot of 2026-09 with sheets outside Opolskie)?
10. The ADR on NMT sheet versions (BACKLOG), partly answered by the versions of the Kartograf
    store (ADR-061).
11. Who writes the providers' lines of a result in `frontend/data/results/index.json`: the
    publication script of a Hydraulik run, which makes its rasters, or the person who publishes
    it (ADR-083)? Production's SFINCS entry needs them by hand until then.
12. The reports of the old form (Next 15): are they, the backup of 2026-11-03 included, deleted
    before `terms_effective`, as Nogat's plan `2026-11-13-gui-terms` proposes (§ 8 of the
    regulamin deletes a report once it is handled)? The operator decides; until then they stay.
