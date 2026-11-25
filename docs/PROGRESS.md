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
| Producers | done | Hydrograf 0.6.1 pins the tags of the release round of 2026-11-24: Kartograf `v0.9.0` (`>=0.9.0,<0.10`), Obserwator `v3.2.1` (`>=3.1.0,<4`) and Hydrolog `v0.9.1` (`>=0.9.0,<0.10`); during the round `develop` pinned the commits of Nogat's release set candidate-13 (branch `chore/pins-candidate-13`): Kartograf `05052b3` (0.9.0.dev0, `>=0.9.0.dev0,<0.10`), Obserwator `1ffe40d` and Hydrolog `1b25a91`. Hydrograf 0.6.0 pinned the tags of the release round of 2026-11-21: Hydrolog `v0.9.0` (`>=0.9.0,<0.10`) and Obserwator `v3.1.0` (`>=3.1.0,<4`), with Kartograf `v0.8.2` (`>=0.8.0,<0.9`); before the release `develop` pinned their development heads, `dbbbdb5` and `1a11df5` (`feat/hydrolog-0.9.0`, Next 19), then `56771c6` and `de06926` (`chore/pins-round`) and `64f6e21` and `4bf0ce3` (`chore/copies-round`, 2026-11-22), the commits of Nogat's release set candidate-11. Hydrograf 0.5.2 pinned the tags of Nogat's release set candidate-10: Kartograf `v0.8.2`, Obserwator `v3.0.1`, Hydrolog `v0.8.1`. On 2026-11-21 (read only) production's checkout was `a86e8ce` (release v0.5.1: Kartograf `v0.8.1`, Obserwator `v3.0.1`, Hydrolog `v0.8.1` in `hydro_api`) and Hydroni's `a46adb4` (candidate-3: Hydrolog `930915d`, Kartograf `d0990c8`, Obserwator `f9f4ee7`). The network hand-offs go to Hydrolog's GUI (`127.0.0.1:8070`). A Kartograf store shared with Archiwista is read only through closed Archiwista sets (ADR-067). |
| Front end | done | Nogat visual identity and Archiwista's shell (ADR-065), modes Przeglądanie / Wybierz zlewnię (options „Jedna zlewnia” and „Sieć zlewni” over the map) / Profil terenu / Identyfikuj. The top-bar „Instrukcja” button opens the welcome dialog; the user guide is a scrolling page with a TOC and chapters, while `docs/Hydrograf-prezentacja.html` remains a slide deck. The welcome text and guide name the data area from `frontend/data/instance.json`; external analyses come from `frontend/data/results/index.json` (SFINCS), alongside the MZP overlay and `?v=` asset versions. Nogat's GUI kit 1.1.0 in `frontend/nogat/` (ADR-082 to ADR-086): the top-bar menu „Aplikacje” of the GUIs in `HYDROGRAF_GUI` or the table `gui` of NOGAT_CONFIG's file (`GET /api/gui`), the hand-off through `nogat-handoff.js`, the providers' strip, the regulamin template and the admin panel. |
| Network delineation | done | `POST /api/delineate-network` and its preview on the catchment graph `POST /api/delineate-network/preview`, the option „Sieć zlewni” of „Wybierz zlewnię” in two stages (the preview after every change of the points, then „Oblicz charakterystyki”) and one hand-off of the network to Hydrolog's Sieć (ADR-080, amended on 2026-11-11 by the plan `2026-11-11-network-nodes`: every point is a node, `J` at a confluence it is drawn to within 50 m up or down, `P` elsewhere, numbered from the closing section up, the outlet `O`; ADR-081); the plans `2026-11-10-network-delineation`, `2026-11-11-network-preview` and `2026-11-11-network-nodes` are done. Merged into `develop` with `feat/network-nodes` on 2026-11-11; networks above 60 M cells stay refused. Open methodology: Next 10. |
| Admin panel | done | Step 3 of Nogat's plan `2026-11-13-admin-panel` (DEV-15.13, ECO-067, kit 0.7.0; ADR-086): `/admin/` is the kit's `<nogat-admin>` („Zgłoszenia”, „Statystyki”, „Stan”, then „Zasoby”, „Przetwarzanie NMT”, „Czyszczenie”, „Granice i kanalizacja”), `/admin` answers 308, `/admin.html` and Bootstrap are gone; `status` (database, catchment graph, data directory) replaces `dashboard`, `stats` reads `stats.jsonl`; no generated key (`admin_key_not_configured`); admin answers `no-store`, the panel's requests limited, not counted. The reports of the old form keep their `legacy` member, which the kit's view does not show (Next 14). Merged into `develop` on 2026-11-14 (`aa975b0`) and deployed; Next 13. |
| Storm sewer | done | ADR-051, ADR-052; no data source yet (BACKLOG). |
| Provider attribution | done | The author's order of 2026-11-13, step 4 of Nogat's plan `2026-11-13-provider-attribution` (DEV §20, ECO-060; ADR-083, plan `2026-11-13-provider-attribution`): the lines the PMAXTP terms require (PS, PP, M and the terms line RK) from `core/attribution.py` in the hydrograph response and its hand-off, the panel, the exports, an own series copied from PMAXTP, the results manifest's layer, point card and profile, `analyze_watershed` and the guide and slides. Merged into `develop` on 2026-11-13 (`12b2a7e`). |
| Public service (regulamin, limit, logs, statistics, form) | done | The author's order of 2026-11-13, step 3 of Nogat's plan `2026-11-13-gui-terms` (DEV-15.7 to DEV-15.12, DEV-18.1, ECO-061 to ECO-063; ADR-084, plan `2026-11-13-public-gui`): Nogat's regulamin at `/regulamin.html` from `[nogat.operator]` of NOGAT_CONFIG, the footer and the menu's `terms`; 300 requests in 60 s per client address in the app (tiles 3,000, the form 5 in 5 minutes), 429 as a Polish page or `rate_limited`; logs without addresses, at most 14 days (since ADR-085 the API's own files, below); daily totals in `<data_dir>/hydrograf/stats.jsonl`; „Zgłoś uwagę” with the text and the view's context, migration 007; one API process. Merged into `develop` on 2026-11-13 (`57d0da3`). Next 14. |
| One strip of the providers' lines | done | The author's request of 2026-11-13, step 4 of Nogat's plan `2026-11-13-compact-attribution` (DEV-20.5, DEV-20.7, ECO-064; ADR-083 amended, plan `2026-11-13-compact-sources`): the map shows PS and PP once in the kit's strip `<nogat-sources>` under the map and the panels („Źródła i warunki” opens every line and the terms), no block of lines in the panel, legend, (i), card or drawer; the welcome dialog shows the full lines and terms of `GET /api/terms`; the phone sheets stop above the strip; exports, hand-off and API unchanged. Merged into `develop` on 2026-11-13 (`6615439`). |
| The providers' terms linked, not restated | done | Nogat ECO-065 (Nogat's develop `b29eada`; ADR-083 and ADR-084 amended): PMAXTP's `terms_notice` is RK alone, „Regulamin danych PMAXTP: https://klimat.imgw.pl/opady-maksymalne”, without the notice N; `core/terms.py` without `imgw-terms`; `analyze_watershed` tells terms lines by „Regulamin <whose terms>: <address>” and drops the retired lines on merge; guide, slides and PDF; kit and hand-off schema copied. Merged into `develop` on 2026-11-13 (`d515aad`). |
| Regulamin 1.0 corrected, GUGiK's and ISRIC's lines, logs of ECO-066 | done | Step 3 of Nogat's plan `2026-11-13-terms-fix` (approved 2026-11-13; ADR-085): kit 0.6.2 (Nogat `5703c53`), `BLOCKS` without `copernicus` and `esri`; G and SG in every response, export, image and hand-off of NMT, BDOT10k and SoilGrids data, dated from `sources` of `instance.json`, GK and SK in the strip; the orthophoto of GUGiK; the libraries in `frontend/vendor/`, CSP `'self'`; the logs of Nogat ECO-066 (`core/nogat_logging.py`, `<state_dir>/hydrograf/logs`, nginx without logs, Docker `local`). Merged into `develop` on 2026-11-14 (`f3a6c0e`) and deployed; Next 13. |
| CI of 2026-11-14 | done | The `audit` job: opentelemetry-api 1.45.2 for CVE-2026-126360 (`pip-audit` clean). The `gate` job of Python 3.15 (reported only): Fiona 1.10.1 has no 3.15 wheel, so the job installs `libgdal-dev` and uv builds Fiona from the sdist (checked locally: Fiona on the system GDAL beside rasterio's bundled GDAL on 3.15). When Fiona publishes 3.15 wheels the step can go. Merged into `develop` on 2026-11-14 (`58d5238`). |
| Dead and duplicated code | done | The author's request of 2026-11-14: functions without callers or only with their own tests, the re-exports of `scripts/process_dem.py`, settings and `config.yaml` keys that nothing read, the staging LAN binding of S7 and front-end functions and exports without callers removed (CHANGELOG, Removed); the rmtree helper, the sheet box and the map colour helpers have one implementation. Kept on purpose: the routes, validators and response fields that vulture flags, the reference functions of the equivalence tests (`zonal_min`, `zonal_elevation_histogram`, `normalize_elevation`), the CRS constants of TECHNICAL_DEBT and the old columns of the feedback (Next 14). `stream_catchments.hydraulic_length_km` is now written and never read: dropping it needs a migration. Merged into `develop` on 2026-11-14 (`f6f689e`). |
| No footer | done | The author's decision of 2026-11-14 (Nogat DEV-15.7, DEV-15.8; ADR-084 amended): the footer and its statement are gone from the map and the guide; „Regulamin” is the last item of the rail (the bottom bar on phones) and of the guide's table of contents, besides the menu and the welcome window's „Regulamin serwisu”. `scripts/gate.sh` on `feat/no-footer`: 2,379 passed, 170 deselected, coverage 87.2 %. Merged into `develop` on 2026-11-14 (`bbd3792`) and deployed (production `1577dbc`). |
| Tests and gate | done | `scripts/gate.sh` on the head of `feat/network-nodes` (2026-11-11): 2,225 passed, 170 deselected, coverage above the floor of 80 %; on `feature/nogat-kit` (2026-11-12, merged as `48bf24a`): 2,244 passed, 170 deselected, coverage 87.0 %; on `fix/provider-attribution` (2026-11-13): 2,260 passed, 170 deselected, coverage 87.1 %; on `feature/public-gui` (2026-11-13): 2,323 passed, 170 deselected, coverage 87.5 %; on `feature/compact-sources` (2026-11-13): 2,325 passed, 170 deselected, coverage 87.5 %; on `fix/minimal-provider-texts` (2026-11-13): 2,325 passed, 170 deselected, coverage 87.5 %; `db` tests on `b5e1154`: 158 passed, 1 skipped (the integration test of the network endpoint was updated for the plan `2026-11-11-network-nodes` and not run against PostGIS since). CI in `.github/workflows/ci.yml`. |
| Documentation | in progress | Guide and slide screenshots refreshed from the current live UI on 2026-11-14; the documents of release v0.5.0 (CHANGELOG `[Unreleased]`, the pins → tags in CLAUDE.md, the integration documents and CROSS_PROJECT_ANALYSIS) on 2026-11-16, when README and CLAUDE.md were also brought within their budgets (DOC-1.7) by moving the deployment reference to `docs/USAGE.md`; the documents of release 0.6.0 checked against its code on 2026-11-22 (README, CLAUDE.md, the CHANGELOG, ARCHITECTURE, SCOPE, PRD, the integrations, INFO_TEXTS_SOURCES, the guide and the slides). The documents still in Polish are listed in Next 7, the local paths in Next 18. |
| Release v0.5.0 | done | Released on 2026-11-16 as a member of the first joint release of the ecosystem (Nogat release set candidate-6; ECO-074): tag `v0.5.0` on `main` (`634fce6`). Its deployment to production is a separate step of the author's. |
| Releases v0.5.1 and v0.5.2 | done | v0.5.1, defect fixes only (the author's approval of 2026-11-17; Next 5): tag `v0.5.1` (`a86e8ce`), 2026-11-18. v0.5.2, nginx 1.31.9 with the pinned images and Kartograf `v0.8.2` of Nogat's release set candidate-10: tag `v0.5.2` (`2f6da1d`), 2026-11-20. |
| Release v0.6.0 | done | The adaptation to Hydrolog 0.9.0 with Nogat's kit 1.1.0, the file names of DEV-19.21, the standard 1.1 and the tags Hydrolog `v0.9.0`, Obserwator `v3.1.0` and Kartograf `v0.8.2` (Next 19); a member of Nogat's release set 0.2.0. The author decided on 2026-11-21 that 0.6.0 holds only this; what was planned for 0.6.0 before is 0.7.0 (Next 5). |
| Hydraulik integration | blocked | Paused by the author until Hydraulik works well enough (BACKLOG). |

### Production

- **Code:** checkout `~/workspace/Hydrograf`, detached at `a86e8ce` (release v0.5.1) when read on 2026-11-21 (read only); before, its local `develop` (0.5.0.dev0) was fast-forwarded on 2026-11-15 to `1577dbc` (the merge of `fix/nginx-resolve`, which gives `resolve` in the nginx upstream to pick up new IPs without reloading the server) with a new image `hydrograf-api:latest` built from it. The default compose project (`hydro_db`, `hydro_api`, `hydro_nginx`) with the development override: the code is mounted from the checkout and served with `--reload`, so an edit there reaches the live API, and the files must be readable by uid 999 (check out under `umask 022`). `docker/nginx.conf` is mounted as one file.
- **GUI kit:** on 2026-11-12, at the author's request, `develop` took `feature/nogat-kit` (`48bf24a`, ADR-082) and the checkout followed; `.env` gained `HYDROGRAF_GUI` with the public addresses of Hydrograf, Hydrolog (`https://hydrolog-test.debever.pl/`), Archiwista (`https://archiwista-test.debever.pl/`) and Obserwator (`https://obserwator-test.debever.pl/`, a placeholder for now), and `hydro_api` was recreated (`docker compose up -d --no-deps api`). `GET /api/gui` answers the table and the public page shows „Aplikacje”.
- **Hydrolog:** develop `e5df06d` (version 0.8.0.dev0, the author's decision 2026-11-14) in production's image and served at `127.0.0.1:8070`; `develop` pins `3ce7ee8` of candidate-5 since 2026-11-15 (the hand-off from Hydrograf routes the network; Hydrolog ADR-0026 warns `diffusion_dominated` where Muskingum-Cunge cannot grid a reach as linear reservoirs).
- **Public service:** `.env` names `NOGAT_CONFIG` and `NOGAT_STATE_DIR`; `~/.config/nogat/nogat.toml` has `[nogat.operator]` with `terms_effective = 2026-11-14`, mounted into the API at `/config/nogat.toml`; the API writes its access and lifecycle records to `~/.local/state/nogat/hydrograf/logs/` (`/state/hydrograf` in the container); `frontend/data/instance.json` was written again on 2026-11-14 at 08:32 UTC with the `sources` that date G; the SFINCS entry of `frontend/data/results/index.json` carries PS, PP, M and RK.
- **Admin key:** since `chore/admin-key-file` (2026-11-14, the author's decision) Compose takes the key from the host file of `ADMIN_API_KEY_HOST_FILE`, `~/.config/nogat/keys/hydrograf-admin.key` (uid 2001, group `hydro-readers` 1002, mode 0640), with `HYDROGRAF_SECRETS_GID=1002`; production's `.env` gets those two lines and an empty `ADMIN_API_KEY` when the branch is checked out, then `hydro_api` is recreated. Hydroni (prod overlay, `user: "2001:2001"`) needs `ADMIN_API_KEY_HOST_FILE` in `hydroni.env` once it moves past this commit: the overlay no longer has the secret `admin_api_key`.
- **Access:** `127.0.0.1:8080`; public `https://hydrograf-test.debever.pl` through a Cloudflare Tunnel. Give testers the `https://` address: the HTTP redirect is a 301, which can turn a POST into a GET.
- **Data:** the Kaczawa above the node 51.222825 N 16.179380 E; boundary `data/boundary/zlewnia_kaczawy_jednostki.gpkg`, the union of the kept units (792.009 km²; `instance.json` says 792.0, soil groups `least-permeable`); the old boundary `zlewnia_kaczawy_790km2_przyciecie.gpkg` (790.564 km²) stays beside it for comparisons. Alembic `007`. **Cache removed from live :8080 (2026-11-15).** Inputs now in the store via Archiwista project `kaczawa` set `2026-1` (194 NMT 5 m sheets, 10 BDOT10k counties, 1 HSG raster, area zlewnia_kaczawy_jednostki.gpkg 792 km²). Validation (no writes) passed: `docker compose run --rm --no-deps -T --user 999:2001 --entrypoint python -v /mnt/magazyn/agent-tmp/hydroni/kartograf:/mnt/magazyn/agent-tmp/hydroni/kartograf:ro -v /mnt/magazyn/agent-tmp/hydroni/projekty:/projekty:ro -e HYDROGRAF_KARTOGRAF_ROOT=/mnt/magazyn/agent-tmp/hydroni/kartograf api -m scripts.bootstrap --project /projekty/kaczawa --set 2026-1 --area-name "zlewnia Kaczawy" --cache-dir /tmp/kcache --skip-infra --skip-serve --dry-run` → exit 0. Real run: same without `-T --entrypoint python … --dry-run` (`api python -m scripts.bootstrap …`). Store must be mounted at its host path; `--user 999:2001` to read the CIFS share.
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
5. **Defects of the scenario test of 2026-11-15/16 left after 0.5.1.** v0.5.1, the patch of
   defect fixes only that the author approved on 2026-11-17, was released on 2026-11-18 (tag
   `v0.5.1`); 0.6.0 is the adaptation to Hydrolog 0.9.0 alone (Next 19), so what is left waits
   for 0.7.0 or later. Known defects, by the IDs of the scenario test of 2026-11-15/16
   (`~/workspace/_e2e/2026-11-15/scenario/REPORT.md` §4, owners §6; none of C1–C7 of Nogat's run
   of candidate-5 is Hydrograf's) and of the external test report of 2026-11-02 (A2, B2, B3);
   *fixed* marks what 0.5.1 fixed (CHANGELOG `[0.5.1]`), *fixed for 0.7.0* what the branch
   `fix/0.7.0-small` fixed (CHANGELOG `[Unreleased]`), *0.5.1* what was in its scope and is
   still open, *0.7.0* what is planned for 0.7.0:
   - *Large basins (with a plan):* E7-08 (a second bootstrap into an instance replaces the
     first part and mixes its cover and soils; no `--append`, no inflow from the part above),
     E7-GAP-02 (= E7-08), G07-2 = G09-2 = G09-3 (a catchment cut at the area's or the state's
     edge looks complete: H7's notice `catchment_truncated`), E7-09 and HG-E2E-04 (the
     bootstrap peaks at its memory cap; no documented rule or limit). Nogat's plan
     `docs/plans/2026-11-16-large-basins.md`, approved by the author on 2026-11-24, takes them to
     0.9.0 (its step H1 moves them here).
   - *Delineation (0.7.0, outside the large-basins plan, its topic 4):* E7-GAP-04 (*fixed for
     0.7.0*: the outlet moved to the segment's end without a notice; `POST
     /api/delineate-watershed` now gives `snap_distance_m` and, above 500 m, the notice
     `outlet_far_from_point`, which the panel shows; after a cascade the outlet is the coarser
     segment's end where the merged watershed closes, no longer the clicked segment's).
   - *Czechia (a follow-up plan of its own after large basins, D11 of Nogat's plan):* GEO-01 (no
     Czech NMT in `utils/kartograf_set.py`).
   - *Bootstrap and a second instance:* E4-01 (a bind mount under `/data/nmt` leaves step 3
     unable to write; the dry run does not check it), E4-02 (*fixed*: the dry run now refuses a
     `--units` file without `pozostale_obszary_jcwp`), E4-03 (*fixed*: a one-off script
     without `--entrypoint` waited for the database), HG-E2E-01 (*fixed*: untracked
     `frontend/data` and `frontend/tiles` stopped a second nginx), HG-E2E-02 (*fixed*: the prod
     overlay's healthcheck asked `localhost`, nginx listens on IPv4 only), HG-E2E-03 (*fixed*: the
     warning `POSTGRES_PASSWORD is empty` beside DATABASE_URL), the `dem_mosaic.vrt` a
     bootstrap leaves (*fixed*: the DEM on the grid of the flow directions now outranks it, so
     the precise mode reads the cut `dem_mosaic.tif`), Next 17 (*0.5.1*).
   - *API:* E5b-01 (*fixed*: the catchment graph loaded inside the first request, 504; it now
     loads in a thread of its own and the requests answer 503 at once until it is loaded), E5b-02
     (*fixed for 0.7.0*: `GET /api/admin/resources` walked every tile inside the request, 504;
     each data directory is now walked in a thread of its own and a request waits for it at most
     5 s), E5b-03 (the precise mode near a stream returns 0.0003 km² without a notice), E5b-04
     (0.7.0: `generate-hydrograph` with a point alone takes about 3 min, 504), E5b-08 (*fixed* on
     Hydrograf's side: the hydrograph's Hydrolog computations hold numba's compiler lock, so a
     compile no longer catches their warnings; Hydrolog 0.8.1 the other: the first network beside
     a hydrograph gave 500), E5b-10 (the network preview does not warn of a window above 60 M
     cells).
   - *Lines, rainfall and warnings (B4, B5):* E3-03 (0.7.0, waits for the author with E3-04:
     `obserwator-series-csv` is refused as an own series; the file carries IMGW-PIB's or ČHMÚ's
     lines, which a consumer carries on by Nogat DEV-20.6, while ADR-083 says an imported file
     carries no lines and `derived_from` knows PMAXTP alone, so accepting it needs the amendment
     of ADR-083 that E3-04 waits for, B2 or B3 of its options), E3-04 (*0.5.1*:
     `custom_precipitation` carries no provider lines), E5b-05
     (*fixed*: the full hydrograph path had no ISRIC line), E5b-06 (*fixed*: Hydrolog's warnings
     reached only the log; the hydrograph's response now carries them as `notices` in Polish and
     the panel shows them under „Hydrogram”), E5b-09 (*fixed*: `/api/terms` listed PMAXTP for an
     instance without it).
   - *GUI (B8):* G05-1 = B2 (*fixed*: above 250 km² a notice under the sections gives the limit of
     SCS-CN), A2 (*fixed*: with Snyder its Lc stands with Ct and Cp and the Tc method is greyed
     out), B3 (*fixed*: Esc now only hides the panel; the bin alone clears it), G06-1 and G06-2
     (reach lengths and slope of hand-placed points, to be explained), G06-3 (the clipboard of the
     test browser; environmental), G06-4 (B8: „Jedna zlewnia” at a network's P1 ends at the
     segment's end, not at P1), G07-1 = G09-1 (the map and the page title do not name the area),
     M2 and M3 of the external report (0.7.0, once confirmed).
   - *Owned elsewhere:* E2-03 (the counties of the plan's BDOT10k; Kartograf and Archiwista, B2).
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
8. **Error registry, loose ends** (ADR-059): the texts of core exceptions that reach
   `details.cause` (`invalid_parameters`, `invalid_bbox`, `invalid_boundary_file`) are the
   library's; the gateway errors of nginx are not problem documents (CLAUDE.md, AGI-6.3). The
   admin routes document their own problems since 2026-11-15 (CHANGELOG, Fixed).
9. **Small items carried over from earlier sessions** (no other home):
   - `scripts/staging-compose.sh` accepts only the branch `feature/store-migration` (the LAN
     binding of the staging nginx went on 2026-11-14, after S7).
   - „Identyfikuj” reads the water bodies from `frontend/data/bdot_lakes.geojson`
     (`core/point_info.py`), not from the database.
   - `area_km2` is rounded to 4 decimals in the precise mode (`api/endpoints/watershed.py`) and to
     2 on the graph path (`core/watershed_service.py`).
   - Snyder fails where `length_to_centroid_km` is 0 until the user gives Lc; the shape indices of
     very small catchments fall outside their ranges; `asymmetry_coefficient` is never computed
     (TECHNICAL_DEBT, TODO in `core/watershed_service.py`).
   - Report to Hydrolog: its conversion of the CN to AMC I/III rounds the CN to an integer
     (`runoff/scs_cn.py`).
   - Request to Hydrolog (DEV-17.5, label `request`; E5b-06): a public export of
     `HydrologWarning`, which lives only in its private `hydrolog._warnings`. Until then
     `core/hydrolog_notices.py` tells Hydrolog's warnings by their `code()` and `details` and the
     public registry `hydrolog.catalog.NOTICES`, and `install()` sets the filter `always` on
     `UserWarning`, the class Hydrolog documents for its warnings.
   - The image `hydrograf-api:latest` of 2026-11-14 has `ogr2ogr` (`gdal-bin`) and
     `tippecanoe` but no `pmtiles` CLI, so bootstrap step 8 makes the `.mbtiles` and `.pbf`
     tiles and no `.pmtiles` (optional in `scripts/generate_tiles.py`; checked 2026-11-15).
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
13. **The deployments of 2026-11-13 to 2026-11-15.** Production ran `1577dbc` from 2026-11-15
    and `a86e8ce` (v0.5.1) on 2026-11-21 (Producers): the providers' lines and their strip, the
    linked terms, the public service, the corrected regulamin with G and SG, the logs of
    ECO-066, the admin panel and no footer. Left:
    - Cloudflare Access on `/admin`, `/admin/*` and `/api/admin/*` (ADR-086; `/admin.html` is
      gone): the author's step, not visible from here;
    - the old journal entries of `hydro_api` and `hydro_nginx` stay until root removes them
      (Nogat plan `2026-11-13-unified-logging`);
    - `develop`'s merges after `1577dbc` (`docs/session-2026-11-15`,
      `chore/release-prep-candidate-5`) reach production with its next checkout, the
      author's step;
    - Hydroni (`a46adb4`): a build of `hydroni-api` from `develop`, its admin key, its own
      `NOGAT_STATE_DIR` and `write_instance_info` with its inputs (G reads „b.d.” without it);
      NOGAT_CONFIG and a `hydrograf` entry of its HYDROGRAF_GUI are its own decision (without
      them it has no regulamin); its prod overlay runs one API process;
    - the GeoTIFFs of the SFINCS result (`max_depth.tif`, `wse_max.tif`) carry no lines
      (Hydraulik's publication); `analyze_watershed` outputs written before 2026-11-13 keep N and
      „Regulamin: …” until rerun; `docs/Hydrograf-prezentacja.pdf` is not printed again.
14. **The reports of the old form.** Production's `hydro_db.feedback` holds 30 reports (ids
    11–40, 2026-08-02 to 2026-11-05): 3 with a contact (ids 11, 12, 13), all 30 with a User-Agent
    and a page URL, 7 with diagnostics; a backup of 26 of them (ids 11–36) is in
    `/data/nmt/hydrograf-feedback-backup-2026-11-03T2319/`; Hydroni has none. Migration 007 keeps
    their old columns (the admin list shows them as `legacy`) until the operator has handled
    them; a later migration drops `contact`, `page_url`, `user_agent` and `diagnostics`.
15. **Unscheduled:** the rest is in [BACKLOG.md](BACKLOG.md): the hardening of the public attack
    surface (three unauthenticated DoS paths first), the „brak danych” of the hyetograph that a
    tester reported, `--thresholds` of the bootstrap, building raising (ADR-033), the read
    endpoints proposed for v0.5.x, clipping the presented data to the boundary, the GPT items
    B6–B15, the sheet selection of `--boundary-file`, SQLAlchemy 2.1, named volumes, the
    Opolskie data (D6) and the ADR on NMT sheet versions.
16. **The SFINCS layer's (i) by Nogat DEV-15.14** (the author's request of 2026-11-14): the (i) of
    a result is the manifest's `description` and `source`, outside Git, so production's
    `frontend/data/results/index.json` gets, for `sfincs-kamiennik-24h-p1`, `description` „Największa
    głębokość wody w każdym miejscu w symulacji przepływu wody po terenie zlewni Kamiennika do
    ujścia do Kaczawy (37,22 km²) przy opadzie 24 h o prawdopodobieństwie przewyższenia 1 %
    (134,5 mm). Wynik jednego scenariusza, bez kalibracji, a nie oficjalna mapa zagrożenia
    powodziowego; poziom wody w zbiorniku Świerzawa jest zawyżony, bo zapora nie ma w modelu
    przelewu ani upustu dennego.” (394 characters, now 2,496) and `source` „Leijnse i in. 2021
    (SFINCS); dane: IMGW-PIB (PMAXTP), GUGiK (NMT, BDOT10k), ISRIC SoilGrids (CC BY 4.0)”. The
    assumptions of the run moved to the guide's `#sfincs`. Its `attribution` has PS, PP and M but
    not G and SG of the NMT, BDOT10k and SoilGrids the run used (Open questions 11).
17. **Admin panel re-processing from a store** (the author's decision 2026-11-15): the panel's `/bootstrap/start` refuses to run when `HYDROGRAF_KARTOGRAF_ROOT` is set, preventing re-processing from an Archiwista store. Not fixed in 0.5.1 or 0.6.0. Not urgent.
18. **Local paths in the documents** (DOC-1.4): this file (Production, Hydroni instance, Other
    places, Next 1, 4, 5, 11, 14), `docs/runbooks/`, `docs/plans/`, BACKLOG, TECHNICAL_DEBT,
    `docs/integrations/KARTOGRAF.md`, the CHANGELOG and ADR-066, ADR-067, ADR-070 and ADR-071
    name directories of the author's machines (`~/workspace/…`, `~/data/…`, `/mnt/magazyn/…`,
    `/data/nmt/…`). The accepted ADRs keep them (DOC-8.1); the other documents are to name
    such places by role, with the machine's paths kept outside Git.
19. **Deploy 0.6.0** (done, in 0.6.0; CHANGELOG 0.6.0). The author decided on 2026-11-21 that
    0.6.0 holds only the adaptation to Hydrolog 0.9.0 (step 2 of Nogat's plan
    `2026-11-19-hydrolog-0.9.0-consumers`, merged from `feat/hydrolog-0.9.0` as `d23cb02`) with
    the pins of the round, Nogat's kit 1.1.0, the sources strip folded on a phone (Nogat
    ECO-080) and the file names of DEV-19.21 (step 4 of Nogat's plans
    `2026-11-21-phone-sources-strip` and `2026-11-21-download-file-names`, merged from
    `feat/phone-sources-strip` as `3a4ecf9`); what was planned for 0.6.0 before is 0.7.0
    (Next 5). Left for the author: ADR-088 (Open questions 16) and the deployment. Lutz needs
    the saved `dem_mosaic_02_filled` of the instance's run; production and Hydroni have it on
    the grid of their labels (checked read only on 2026-11-21), so both compute Lutz once 0.6.0
    is deployed; Hydroni's parameter exports for the author lack Jg until they are made again.
    The folded strip was checked in Chromium at 390 × 844 px on the static pages (Hydrograf has
    no browser tests; `tests/contract/test_frontend_kit.py` checks the kit's hashes).

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
    it (ADR-083)? Production's SFINCS entry got them by hand.
12. The reports of the old form (Next 14): are they, the backup of 2026-11-03 included, deleted
    now that the regulamin is in effect (`terms_effective` 2026-11-14), as Nogat's plan
    `2026-11-13-gui-terms` proposes (§ 8 of the regulamin deletes a report once it is handled)?
    The operator decides; until then they stay.
13. Nogat's `handoff-1.schema.json` does not name `result.computed_with.formula_versions`,
    which Hydrograf's hand-offs carry since 0.6.0 (Next 19; the object accepts additional
    properties, so the copy validates). Should Nogat's schema describe it?
14. `negative_quantiles` (Hydrolog 0.9.0's notice of low-flow quantiles below zero) has no
    Polish text in `core/hydrolog_notices.py`: Hydrograf computes no low flows, so no request
    can get it. Confirm that it needs none.
15. A hydrograph on the fast path (the GUI sends the delineation's morphometry) lists the
    `formula_versions` of the formulas it ran, not `tr55_cn` and `equal_area_slope` of the
    delineation, which the request cannot prove (the morphometry may be the person's own).
    Should `morphometry_origin` carry them, so the hand-off names every formula of its CN and
    Jg?
16. ADR-088 (proposed): Jg measured at request time on the traced flow path, and the Euler II
    curve scaled as a whole by the own areal reduction factor (Hydrolog ADR-0042: whoever
    chooses another total scales the curve). Accept?
