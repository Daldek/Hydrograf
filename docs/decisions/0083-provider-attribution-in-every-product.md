# ADR-083: The providers' lines in every product: one module, the responses, the hand-off and the exports

**Date:** 2026-11-13
**Status:** accepted

## Context

The author ordered on 2026-11-13 that every product of the ecosystem with data of IMGW-PIB
carries the lines the provider's terms prescribe, verbatim. Nogat set them in DEV §20 of
its standard (ECO-060, commit `bbb58a8` on its branch `fix/provider-attribution`, step 1 of
its plan `docs/plans/2026-11-13-provider-attribution.md`), with the optional fields
`attribution` and `terms_notice` of `nogat-handoff/1`. Hydrograf's only provider data are
the PMAXTP quantiles of IMGW-PIB that the preprocessing fetches through Obserwator into
`precipitation_data`. The PMAXTP terms ask for the source with the address of the PMAXTP
page (PS), the note that the data were processed (PP) and the monograph of the project (M);
the IMGW-PIB terms allow free use for private purposes only, so the notice N and the
address of the PMAXTP terms (RK) go with them (DEV-20.2, DEV-20.7). Hydrograf processes
every PMAXTP value it uses: a depth becomes a watershed mean, a hyetograph and a
hydrograph.

Before this decision no product named the provider beyond „IMGW-PIB 2022 (PMAXTP)” in the
literature line of two (i) texts. The products with PMAXTP data:

- `POST /api/generate-hydrograph`: the precipitation, the hyetograph, the hydrograph, the
  water balance and the hand-off `nogat-handoff/1` to Hydrolog (ADR-068);
- the sections „Hietogram” and „Hydrogram” of the panel (charts, balance, tables) and the
  hand-off panel;
- the exports „Hietogram CSV”, „Hietogram JSON” and „Punkty PMAXTP (GeoJSON)”
  (`js/rain-export.js`);
- an own series filled by „Wczytaj z bieżącego hietogramu”: a PMAXTP hyetogram the person
  may edit, sent as `custom_precipitation`;
- the results of external analyses of the manifest `hydrograf-results/1` (the SFINCS water
  depth of the Kamiennik is driven by the PMAXTP rainfall of 24 h, p = 1 %): the layer and
  its legend, the water depth of the point card (`GET /api/identify-point`) and the water
  surface of the terrain profile (`POST /api/terrain-profile`);
- `scripts/analyze_watershed.py`, which fetches PMAXTP itself: its log, `hydrograph.png`,
  `qmax_scenarios.png` and `analysis_results.json`;
- the user guide and the slides with screenshots of these results.

The instance at `https://hydrograf-test.debever.pl` is public, without Cloudflare Access.

## Options considered

Where the lines live:

- **A1. One Python module; the responses carry the lines; the front end shows and exports
  what a response carries.** The browser never holds a copy.
- **A2. A copy in the front end** besides the backend's. Two places that can drift
  (DEV-20.4 wants one).
- **A3. A route `GET /api/attribution`** with the catalogue of the lines. One more route; every
  product with data already comes from a response that can carry its own lines.

An own series copied from a PMAXTP hyetogram:

- **B1. No lines**, since the request is an own series. The products lose the lines while
  they hold PMAXTP data: a breach of the terms.
- **B2. The client sends the lines** it received (`custom_precipitation.attribution`). Generic,
  but the API would write text of the client into its responses and hand-offs.
- **B3. The client says where the series came from** (`custom_precipitation.derived_from =
  "pmaxtp"`) and the API adds its own lines.

The results of external analyses:

- **C1. Hydrograf infers PMAXTP** from the free text `source` of the manifest. Fragile.
- **C2. The manifest entry carries the lines** its producer wrote (`attribution`,
  `terms_notice`); the API and the front end pass them on.

The guide and the slides:

- **D1. They quote the lines** under their screenshots: they are documents, the slides are
  also printed to PDF and opened outside the application.
- **D2. A script fills the guide from the API.** Only the guide could do so; the slides and
  the PDF would still quote them.

## Decision

A1, B3, C2 and D1:

1. `backend/core/attribution.py` holds PS, PP, M, N and RK byte for byte, `ProviderLines`,
   `PMAXTP` (PS, PP, M; N, RK), `NO_PROVIDER` and `merge` (each line once, in the order it
   first comes).
2. `POST /api/generate-hydrograph` answers with `attribution` and `terms_notice`, always
   present: the PMAXTP lines for a design storm and for an own series with `derived_from:
   "pmaxtp"`, none for the user's own data. The hand-off of the response has the same two
   fields, left out without lines (the schema wants at least one); the copy of Nogat's
   `schemas/exchange/handoff-1.schema.json` is taken again from `bbb58a8`.
3. The request's `custom_precipitation.derived_from` (`"pmaxtp"` or null) is set by the
   interface from „Wczytaj z bieżącego hietogramu” until „Wyczyść”, an import of a CSV file or
   a new watershed; edits keep it, as an edited copy still holds PMAXTP data.
4. `hydrograf-results/1` takes the optional arrays `attribution` and `terms_notice` per
   result. `GET /api/identify-point` and `POST /api/terrain-profile` answer with the union of
   the lines of the results whose water they return (`provider_lines` of
   `core/analysis_results.py`); the front end shows a result's lines in its legend and in its
   (i), and those of a response in the point card and the profile drawer.
5. The panel shows the lines of a response visibly with its data: in „Hietogram” and in
   „Hydrogram”, and under the table of an own series copied from PMAXTP. The exports carry
   them in the forms of DEV-20.5: CSV trailing columns `attribution` and `terms_notice`, JSON
   fields, GeoJSON foreign members.
6. `scripts/analyze_watershed.py` takes the lines from the module for its log, the footer
   of its PNGs with PMAXTP values and its JSON.
7. The guide and the slides quote the lines next to their screenshots of PMAXTP results;
   the module's docstring names them as the places that quote it.

## Consequences

- The lines are fixed by the providers; a change of them is a change of
  `core/attribution.py`, of the guide and of the slides (and a print of the PDF), nothing
  else.
- Clients of the API see two new response fields and one new optional request field
  (AGI-4.1, additive). The hand-off stays `nogat-handoff/1`; Hydrolog shows and carries the
  lines (its step 3 of Nogat's plan); the pinned Hydrolog reads them as unknown fields.
- A result of the manifest shows lines only when its producer wrote them: the entry of the
  SFINCS result in production's `frontend/data/results/index.json` (data, outside Git) must
  get the PMAXTP lines when it is deployed, and the GeoTIFFs it links carry none (their
  producer is Hydraulik).
- An own series imported from a file carries no lines: Hydrograf does not read lines from
  CSV files; a person who imports provider data answers for its terms.
