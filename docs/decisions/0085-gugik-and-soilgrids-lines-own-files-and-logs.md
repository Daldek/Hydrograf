# ADR-085: GUGiK's and ISRIC's lines on every product, the orthophoto of GUGiK, no remote scripts, and the logs of ECO-066

**Date:** 2026-11-13
**Status:** accepted (step 3 of Nogat's plan `docs/plans/2026-11-13-terms-fix.md`, approved
by the author on 2026-11-13; Nogat ECO-066, ECO-068, kit 0.6.2)

## Context

The regulamin 1.0 that Hydrograf published on 2026-11-13 said untrue things (Nogat's plan,
Goal): § 5 ust. 1 promised the providers' lines on every product, while Hydrograf's
results from GUGiK's NMT and BDOT10k and from ISRIC's SoilGrids carried none; its § 5 had
the blocks `copernicus` (CORINE, which the pipeline does not use: ADR-074,
`backend/scripts/README.md`) and `esri` (Esri World Imagery, whose basemaps may be used
only with Esri software or an ArcGIS subscription); § 8 ust. 5 named only the basemap as
receiving the visitor's address, while the pages loaded Leaflet, MapLibre GL, Chart.js,
VectorGrid and Bootstrap from unpkg.com and cdn.jsdelivr.net; § 8 ust. 3 described logs
that Hydrograf did not keep (structlog lines and nginx's access log in the system
journal, with no deletion after 14 days: `docker/journald.conf` needs root and was never
installed). Nogat corrected the regulamin in place (kit 0.6.2) and set the lines G, GK,
SG and SK in DEV §20 (DEV-20.9, DEV-20.10, ECO-068) and the logging of DEV-12.4 to
DEV-12.9 (ECO-066). G names the products used, the years their data were created and the
days they were downloaded, „both from the Kartograf metadata of the files”.

## Options considered

Where the dates of G come from:

- **A1. The API reads the sidecars of the files at query time.** The API does not mount
  the cache of the pipeline, and it does not know which files the data were built from.
- **A2. The pipeline writes the products and their dates into `instance.json`**, which it
  already writes for the welcome window, and the API reads it again when it changes.
- **A3. A table in the database.** A migration for a dozen values that the pipeline writes
  once per run.

Which products carry which lines:

- **B1. Every response G and SG.** Simple, but a terrain profile (NMT only) would name
  BDOT10k and SoilGrids it does not use.
- **B2. By the kind of data each product is made of** (`ELEVATION`: NMT; `DRAINAGE`: the
  NMT burned with the BDOT10k watercourses; `TOPOGRAPHY`: BDOT10k; `SOILS`: SoilGrids with
  the BDOT10k wetlands; `CATCHMENT`: all of them), intersected with the products the
  instance names.

The scripts and styles of the front end:

- **C1. Keep the CDNs and name them in § 8 ust. 5.** Nogat's DEV-15.7 now forbids it.
- **C2. Copy them into `frontend/vendor/`** at their pinned versions with their licences.

## Decision

A2, B2 and C2:

1. `core/attribution.py` adds G (`gugik_source`, the template of DEV §20 filled with
   `<products>` joined by „, ”, `<period>` one year or the first and the last with an en
   dash, `<date>` one day or the first and the last with a spaced en dash; „b.d.” where no
   metadata gives one) and SG, the kinds of data and `data_lines`/`instance_lines`.
   Neither has a terms line (DEV-20.7).
2. `scripts/write_instance_info.py` dates the files of each product: an NMT sheet by the
   year of its flight (`extra.source.acquisition_date`), a BDOT10k package by its edition,
   else the `Last-Modified` of its download (`extra.http.last_modified`), else the newest
   `last_change` of its tables; SoilGrids states no creation time; a download by
   `downloaded_at`, and for a package without metadata by the day of its file. The
   bootstrap gathers the files steps 3 to 5 used and writes `sources` into
   `instance.json`; the script does the same from `--nmt`, `--nmt-sheets`, `--bdot10k` and
   `--soilgrids` for an existing instance; a product a run did not use keeps its entry.
   `core/data_sources.py` reads the member again when the file changes.
3. The responses of `POST /api/delineate-watershed` (and its preview),
   `POST /api/delineate-network` (and its preview), `POST /api/generate-hydrograph` (the
   rainfall's lines first, then the watershed's), `GET /api/identify-point` (by the
   members it gives), `POST /api/terrain-profile` (G of the NMT) and `GET /api/terms`
   (every line of the service, and `layers`: the lines of each kind of the map's layers)
   carry them in `attribution` and `terms_notice`; the hand-offs of the watershed, the
   hydrograph and the network carry the lines of their response. The exports of the
   panel carry what their response carries. `analyze_watershed` draws them under each of
   its four PNGs and writes them into its JSON, `ATTRIBUTION.txt` and log;
   `export_catchment_parameters` into the layer's metadata items `attribution` and
   `terms_notice` and the table `<layer>_attribution`.
4. The strip of the map view takes the lines of the watershed, the network and the
   layers of Hydrograf's data that are on (`js/app.js`, `js/network.js`, `js/layers.js`)
   besides the hydrograph, the results, the point card and the profile, grouped by
   provider in the order of DEV-20.4; kit 0.6.2 draws GK and SK. The point card names
   „ISRIC SoilGrids”.
5. The orthophoto is GUGiK's WMTS (`ORTOFOTOMAPA`, matrix set `EPSG:3857`, levels 0 to 19,
   bounds of Poland), „Ortofotomapa GUGiK”, credited „Ortofotomapa © GUGiK” on the map
   (DEV-20.9). The libraries are served from `frontend/vendor/` with `integrity`; the CSP
   allows scripts, styles and fonts from `'self'` only.
6. `BLOCKS` of `core/terms.py` drop `copernicus` and `esri`.
7. The logs follow ECO-066 with Nogat's `nogat_logging.py` (copied to
   `backend/core/nogat_logging.py`): `<state_dir>/hydrograf/logs/<kind>-YYYY-MM-DD.jsonl`,
   deleted after 14 days by the API; nginx keeps no log and passes no `X-Request-ID`;
   Docker's driver is `local` (1 MB × 3); structlog and `docker/journald.conf` are gone.

## Consequences

- A deployment must write `sources` into its `instance.json` once (the bootstrap does it
  from now on; an existing instance runs `scripts.write_instance_info` with its inputs),
  or G reads „wytworzono b.d., pozyskano b.d.” and the API logs a warning once.
- The four BDOT10k packages of production downloaded before Kartograf wrote metadata are
  dated by their files; Kartograf's 0.7.0 metadata of the others lack
  `extra.http.last_modified`, so their creation year comes from their tables.
- Clients see `attribution` and `terms_notice` on four more responses and `layers` on
  `GET /api/terms` (AGI-4.1, additive); the existing fields carry more lines.
- ADR-083's PMAXTP lines are unchanged; ADR-084's logging („logs without addresses in
  the journal, 14 days”) is replaced by point 7; ADR-065's Esri orthophoto by point 5.
- Operators set `NOGAT_STATE_DIR` and create `<state_dir>/hydrograf` writable by UID 999
  (README, Run and Deploy), and recreate the containers.
