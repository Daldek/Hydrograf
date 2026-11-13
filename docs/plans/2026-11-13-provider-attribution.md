# Plan: the providers' lines in every product of Hydrograf

Approved: 2026-11-13, the author's order in session (the attribution the IMGW-PIB terms require
MUST be in every product with their data), as step 4 of Nogat's plan
`docs/plans/2026-11-13-provider-attribution.md` (Nogat `bbb58a8`, DEV §20, ECO-060); the
details by delegated authority, decided in ADR-083.

Requirements: Nogat DEV-20.2 (PMAXTP: PS, PP, M), DEV-20.4 (one place in the code, the
order), DEV-20.5 (the surfaces and file forms), DEV-20.6 (`attribution` in JSON and the
hand-off), DEV-20.7 (`terms_notice`: N, RK), DEV-15.6 (the schema copied byte for byte),
AGI-4.1 (additive fields).

## Goal

Every product of Hydrograf with PMAXTP data of IMGW-PIB, or results derived from them,
carries the five lines verbatim where a person or a program meets the data. Hydrograf has no
other provider data (no danepubliczne.imgw.pl, hydro.imgw.pl or ČHMÚ data).

## Audit (2026-11-13, before this plan)

| Product | Lines before | Change |
|---|---|---|
| `POST /api/generate-hydrograph` response | none | `attribution`, `terms_notice` |
| Its hand-off `nogat-handoff/1` (copy, file) | none | the same two fields; the schema copy of `bbb58a8` |
| Panel „Hietogram” (chart „Opad”, balance, export) | none („IMGW-PIB 2022 (PMAXTP)” only in two (i)) | the lines under the results |
| Panel „Hydrogram” (Qmax, tp, V, chart, table) | none | the lines under the results |
| Own series from „Wczytaj z bieżącego hietogramu” | none, and the request was plain user data | `derived_from: "pmaxtp"`, the lines under the table |
| „Hietogram CSV” | none | trailing columns `attribution`, `terms_notice` |
| „Hietogram JSON”, „Punkty PMAXTP (GeoJSON)” | none | fields `attribution`, `terms_notice` |
| Layer of a result of `hydrograf-results/1` (SFINCS, PMAXTP rainfall) | „opad: IMGW-PIB (PMAXTP)” in the (i) only | the manifest's lines in the legend and the (i) |
| Point card „Identyfikuj” with the water of a result; `GET /api/identify-point` | none | the lines of the result in the section „Woda” and the response |
| Terrain profile with the water surface of a result; `POST /api/terrain-profile` | none | the lines in the drawer and the response |
| `scripts/analyze_watershed.py` (log, PNG, JSON) | „Opad (IMGW)” in the log only | the lines in the log, the PNG footers, the JSON |
| User guide `frontend/instrukcja/` (screenshots of PMAXTP results) | „atlas PMAXTP (IMGW-PIB)” in the text | a block with the lines in chapters 03 and 05 |
| Slides `docs/Hydrograf-prezentacja.html` and its PDF | the same | the lines on the slides of those screenshots; the PDF printed again |
| Delineation, network and their hand-offs, `GET /api/scenarios`, the PMAXTP grid weights | no PMAXTP values | unchanged |

## Steps

1. `backend/core/attribution.py`: the lines, `ProviderLines`, `PMAXTP`, `NO_PROVIDER`, `merge`.
2. The API: the fields of the hydrograph response and its hand-off, `derived_from`, the lines
   of the manifest in the point and profile responses; the schema copy and its README.
3. The front end: `js/attribution.js` and the views, the own series, the exports, the
   results layer, the point card and the profile.
4. `scripts/analyze_watershed.py`.
5. The guide, the slides and the PDF.
6. Documents: ADR-083, ARCHITECTURE, README, CHANGELOG, PROGRESS.

## Verification

- Tests of the lines in the response and the hand-off for a PMAXTP storm, an own series and
  an own series copied from PMAXTP (`tests/unit/test_handoff.py`), of the lines of the
  manifest in the point and profile responses (`tests/integration/`), of `provider_lines`
  (`tests/unit/test_analysis_results.py`) and of the JSON of `analyze_watershed`.
- A smoke in Chromium on the branch's front end and API on one origin (not on a deployed
  instance): the lines in both panel sections, under an own series copied from PMAXTP, in
  the three exports and the hand-off file, in the legend of a result and in the point card
  and the profile.

## Deployment

- Production (`~/workspace/Hydrograf`, `docker-compose.override.yml`: the backend is mounted
  into `hydro_api`, which runs `--reload`, and nginx serves `frontend/` from the checkout):
  the checkout following `develop` is enough, without an image build; no new dependency.
- The SFINCS entry of production's `frontend/data/results/index.json` (data, outside Git)
  needs `attribution` and `terms_notice` with the PMAXTP lines, or its layer, point card and
  profile show none. The two arrays, byte for byte: `cd backend && uv run python -c 'import
  dataclasses, json; from core.attribution import PMAXTP; print(json.dumps(
  dataclasses.asdict(PMAXTP), ensure_ascii=False, indent=2))'`.
- Hydroni (`docker-compose.prod.yml`, the code in the image `hydroni-api`): a build of the
  image and the worktree's front end on the same commit; it has no results manifest.
