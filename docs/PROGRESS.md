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
| Land cover, soils, CN | done | Land cover from the BDOT10k partition by its attributes (ADR-074), the soil under the wetlands is group D and the lawns of KUSK/KUKO are open space (ADR-078); the CN is that of the soil-cover complexes from Hydrolog's TR-55 table, computed at query time (ADR-075 and its amendments of 2026-11-09; migration 006 dropped `land_cover.cn_value`). The export of catchment parameters gives CN AMC I/II/III and the control columns of the weighted runoff. |
| Producers | done | `develop` pins Nogat's release set candidate-2: Kartograf `d0990c8`, Obserwator `f9f4ee7`, Hydrolog `759d7ef` (`01ab00a`, not deployed); production and Hydroni run Kartograf `9deaa31`, Obserwator `1ee5457`, Hydrolog `4fad769`. A Kartograf store shared with Archiwista is read only through closed Archiwista sets (ADR-067). |
| Front end | done | Nogat visual identity and Archiwista's shell (ADR-065), modes Przeglądanie / Wybierz zlewnię / Profil terenu / Identyfikuj, the welcome text and the guide (31 slides) name the data area from `frontend/data/instance.json`, the results of external analyses from `frontend/data/results/index.json` (SFINCS), the MZP overlay, `?v=` asset versions. |
| Admin panel | done | `/admin`: dashboard, bootstrap, resources, cleanup, storm sewer, feedback (ADR-034, ADR-051). |
| Storm sewer | done | ADR-051, ADR-052; no data source yet (BACKLOG). |
| Tests and gate | done | `scripts/gate.sh` on `6b986b0` (candidate-2): 1,970 passed, 159 deselected, coverage 85.60 % (floor 80); `db` tests on `b5e1154`: 158 passed, 1 skipped. CI in `.github/workflows/ci.yml`. |
| Documentation | in progress | Nogat standard 2.1 in English; the documents still in Polish are listed in Next 7. |
| Release v0.5.0 | in progress | `develop` carries 0.5.0.dev0, `main` v0.4.0 (2026-03-03). The next release is v0.5.0 (the author, 2026-11-03); the author extends the candidate and sets the tag himself (2026-11-05). |
| Hydraulik integration | blocked | Paused by the author until Hydraulik works well enough (BACKLOG). |

### Production

- **Code:** checkout `~/workspace/Hydrograf`, local `develop` at `894810c` (0.5.0.dev0) since 2026-11-10 05:00 CET. The default compose project (`hydro_db`, `hydro_api`, `hydro_nginx`) with the development override: the code is mounted from the checkout and served with `--reload`, so an edit there reaches the live API, and the files must be readable by uid 999 (check out under `umask 022`). `docker/nginx.conf` is mounted as one file: restart `hydro_nginx` after a checkout rewrites it. Image `hydrograf-api:latest`; `.env` names `HYDROGRAF_PUBLIC_HOST=hydrograf-test.debever.pl` and the private Kartograf store (no `HYDROGRAF_KARTOGRAF_ROOT`).
- **Access:** `127.0.0.1:8080`; public `https://hydrograf-test.debever.pl` through a Cloudflare Tunnel. Give testers the `https://` address: the HTTP redirect is a 301, which can turn a POST into a GET.
- **Data:** the Kaczawa above the node 51.222825 N 16.179380 E, boundary `data/boundary/zlewnia_kaczawy_790km2_przyciecie.gpkg` (790.564 km²; `instance.json` says 790.6), reprocessed on 2026-11-10 by [the runbook](runbooks/2026-11-10-reprocessing.md) (its §11 is the log): alembic `006`; 41,515 / 4,548 / 496 / 49 segments at 1 ha / 10 ha / 1 km² / 10 km², one outlet each; the basin of the tables is 792.009 km² (the DEM run from before the cut keeps 1.61 km² beyond the boundary); a graph of 46,608 nodes; the land cover of the BDOT10k packages 0205, 0206, 0207, 0209, 0219, 0221, 0226 and 0262; soil B 99.50 / C 0.14 / D 0.36 %; 134,352 PMAXTP points; the SFINCS result `sfincs-kamiennik-24h-p1` under „Wyniki analiz”. The cache has the Kartograf 0.7.0 layout (`cache/bdot10k/`, `cache/soil_hsg/hsg_poland.tif`, no `cache/kartograf/`): a reprocessing passes the packages and the HSG raster explicitly and downloads nothing (runbook §0).
- **Rules:** run a bootstrap or a DEM run only in a one-off container (`docker compose run --rm --no-deps api ...`), never by `exec` in `hydro_api` (an OOM there takes the API down); `docker builder prune -f` before an image build while Docker's data root is on `/`.
- **Backup and rollback:** `/data/nmt/hydrograf-backup-2026-11-10/` (`hydro_db.dump` at alembic `004` with `SHA256SUMS`, `frontend_data.tar.zst`, `frontend-data-pre/`, `env`, `git-head.txt` `94d7523`, `new-head.txt` `894810c`, `tiles_metadata.json`, `switch-2026-11-10.log`, `staging-logs.tar.zst`) and the image `hydrograf-api:pre-2026-11-10`. The quick rollback of the runbook's §8 no longer exists (its §9 removed the old database, rasters and tiles): a rollback restores the dump into a new database, checks out `94d7523` with the old image and builds the rasters and tiles of 2026-11-05 again; no backup holds them, while `/data/nmt/hydrograf-v050/precut` and `/data/nmt/hydrograf-backup-2026-11-01/` hold those from before the cut of 2026-11-01. The older backups in `/data/nmt/` (2026-11-01, the state before the cut and the source of the runbook's §4.9; 2026-11-02; 2026-11-04-handoff, -pinset, -std10; 2026-11-05-lutz, -v050; the feedback backup of 2026-11-03) stay; their images are gone.

### Hydroni instance

- **Code and stack:** worktree `~/workspace/Hydrograf-hydroni` detached at `894810c` (image `hydroni-api` built 2026-11-10 04:35 CET), compose project `hydroni` (`hydroni_db`, `hydroni_api`, `hydroni_nginx`) run by `~/data/hydrograf-hydroni/dc` (system Docker, base file, prod overlay and `compose.instance.yml`); `127.0.0.1:8081`, public `https://hydrograf-hydroni.debever.pl`. Configuration outside the repository in `~/data/hydrograf-hydroni/` (README with the update and reprocessing steps, `bootstrap.sh`, `config.yaml`, `hydroni.env`, `secrets/`).
- **Storage:** `data` and `frontend/data` on the NAS (`/mnt/magazyn/agent-tmp/Hydroni/hydrograf/`, CIFS: the API and nginx run as uid 2001 because the share forces 2001/0640, and SQLite or GeoPackage files are written locally, then copied); the tiles, the cache and `data/hydro` on the local disk in `~/data/hydrograf-hydroni/`; the database in the volume `hydroni_postgres_data`.
- **Data:** area h07 (2,940.7 km²), Archiwista project `h07`, closed set `2026-3` (728 pins; `2026-2` plus the sheet N-33-118-B-a-4-2 that ADR-076 asked for). Settings: `--units` with the 223 h07 catchments (27 units), `dem.stream_burning: main`, `--waterbody-mode none` (the author: no lake is endorheic), no buildings, no inflow from outside the area (the author). Active run 3, bootstrapped on `545f109` on 2026-11-10 00:54–03:15 CET (`bootstrap-20261110-run.log`): 710 sheets (20 delivered as 1 m grids and averaged to 5 m), 201,195 segments at 0.01 / 0.1 / 1 / 10 km², 92.01 km² of wetlands made group D, 73 burned lines reversed by ADR-077.
- **Exports for the author** (parameters of the 223 catchments): v4 `/mnt/magazyn/agent-tmp/Hydroni/h07_parametry_zlewni.gpkg` (2026-11-10, with the runoff control columns), v3 `h07_parametry_zlewni_v3_2026-11-08.gpkg` beside it, v1 and v2 in `~/data/hydrograf-hydroni/cache/`.

### Other places

- The Kartograf store shared with Archiwista, `~/data/archiwista-public/store`, is read only through the closed sets of `bootstrap --project --set` (ADR-066, ADR-067); production keeps its private store.
- `/data/nmt/` also holds the Opolskie NMT of 2026-09 (`nmt_5m/`, 3,233 sheets in the layout before Kartograf 0.7.0, not reused: ADR-061), `pilot_opolskie/` and the voivodeship boundaries (`boundaries/`).
- The SFINCS model of the Kamiennik: `~/hydraulik-work/kamiennik-12h-p1/`; the clip script of 2026-11-01: `~/scratch/hydrograf-clip/clip_hydrograf.py`; the GPT front-end test report: `~/scratch/gpt-guides/hydrograf-test-report.md`.
- `docker-compose.staging.yml` and `scripts/staging-compose.sh` stay for staging stacks; the runbook of 2026-11-10 ran its staging with plain compose files instead (its §2).

## Next

1. **Deploy `develop` to production and Hydroni** when the coordinator schedules it: the
   candidate-2 pins need new images only (no migration, no data change; the calls of Hydrograf
   are unchanged, CHANGELOG). The Hydroni README `~/data/hydrograf-hydroni/README` still asks for
   `./dc restart api` after a bootstrap (step 2) and dates the image 2026-11-09: since `894810c`
   the API reloads its graph by itself.
2. **Leftovers of the delineation fix** (`07112ce`, 2026-11-10):
   - `POST /api/generate-hydrograph` without `morphometry` merges the sub-catchments at
     10 000 m² with no cascade, up to the 250 km² limit (`api/endpoints/hydrograph.py`); the GUI
     does not take this path.
   - A large precomputed delineation still takes tens of seconds: the Wełna at 1 km² (500 km²,
     Hydroni) took 51.4 s: the merge 16.9 s (the union 6.0 s and the boundary smoothing of ADR-032
     9.9 s: a ±2 m buffer, three Chaikin iterations up to 128k vertices, `buffer(0)`; a faster
     smoothing changes the shape, Open questions 4), the land cover query 7.7 s (10.1 s before
     `07112ce`), the flow paths 12.9 s (raster reads from the NAS 6.1 s; `np.isin` 2.4 s, about 2 s
     less with a lookup table) and the Thiessen weighting 3.2 s (about 2.5 s less with a prepared
     geometry); a batched union is 1 s slower than `ST_UnaryUnion`.
3. **HSG from the least permeable layer of 0–100 cm:** the pinned Kartograf has
   `calculate_hsg(depth_rule="least-permeable")` (Kartograf ADR-061, since `e49eaad0`); bootstrap
   step 5 still asks for `depth="0-5cm"`. Using it is the author's call (Open questions 1) and
   needs step 5 again on each instance.
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
   (`invalid_parameters`, `invalid_bbox`, `invalid_boundary_file`) are the library's; the 429 and
   gateway errors of nginx are not problem documents (CLAUDE.md, AGI-6.3).
9. **Small items carried over from earlier sessions** (no other home):
   - `docker-compose.staging.yml` still publishes the staging nginx on `192.168.88.9:8081`, to be
     removed after S7 (the author's decision in S4; S7 ran in place), and
     `scripts/staging-compose.sh` accepts only the branch `feature/store-migration`.
   - The guide's slides 8, 10 and 13 (`frontend/instrukcja/Hydrograf-v2-zlewnia.png`,
     `-warstwy.png`, `-sfincs.png`, 2026-11-01) show the old rail and top bar.
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
10. **Unscheduled:** the rest is in [BACKLOG.md](BACKLOG.md): the hardening of the public attack
    surface (three unauthenticated DoS paths first), the „brak danych” of the hyetograph that a
    tester reported, `--thresholds` of the bootstrap, building raising (ADR-033), the read
    endpoints of v0.5.x, clipping the presented data to the boundary, the GPT items B6–B15, the
    sheet selection of `--boundary-file`, SQLAlchemy 2.1, named volumes, the traffic dashboard,
    the Opolskie data (D6) and the ADR on NMT sheet versions.

## Open questions

1. HSG from the least permeable layer of 0–100 cm instead of 0–5 cm (Kartograf `depth_rule`; on
   h07 B 98.5 / C 1.5 %), and whether loam, silt loam and silt are group C (open in Kartograf
   ADR-061).
2. D5: the HSG fallback „B” where SoilGrids has no data, and step 5 as non-critical (a failed
   step 5 still ends the bootstrap with exit 0); BACKLOG.
3. Production: the basin of the tables is 792.009 km² while the boundary is 790.564 km² (1.61 km²
   of the basin lies beyond it, from the DEM run before the cut): keep it, or cut the tables to the
   boundary?
4. A faster boundary smoothing (ADR-032) for large watersheds changes the shape of the boundary:
   worth it for the 9.9 s of a 500 km² watershed?
5. The text of `docs/CLA.md` and how the CLA is signed (`CONTRIBUTING.md` and the pull request
   template name the file; DEV-16.2).
6. D12 of step H1: a set's pins of producers other than Kartograf (Obserwator) are skipped
   (`utils/kartograf_set.py`): keep that once sets have several producers?
7. Show the record of the set (`bootstrap_set.json`) in the admin panel?
8. The row names „Wskaźnik rzeźby” (ΔH/√A is rather the catchment slope or Melton's index) and
   „Liczba chropowatości” (no Polish source for the name; INFO_TEXTS_SOURCES).
9. `null` instead of 0.0 in `elevations_m` of `POST /api/terrain-profile` inside DEM gaps (a
   breaking change; B5 in BACKLOG).
10. Building raising (ADR-033) in the pipeline (BACKLOG: to be decided by the author).
11. Delete `/data/nmt/pilot_opolskie/` (45 MB, the pilot of 2026-09 with sheets outside Opolskie)?
12. The ADR on NMT sheet versions (BACKLOG), partly answered by the versions of the Kartograf store
    (ADR-061).
