# Plan: one compact strip of the providers' lines in the map view

Approved: 2026-11-13, the author's request (the provider lines took too much of every GUI), as
step 4 of Nogat's plan `docs/plans/2026-11-13-compact-attribution.md` (Nogat `develop`,
kit 0.5.0 of `5406e5c` and 0.5.1 of `9940bb8`; DEV-20.5, DEV-20.7, ECO-064); the details by
delegated authority, recorded in the amendment of ADR-083.

Requirements: Nogat DEV-20.5 (one strip per view, 12 px, S, P, PS, PP and CK on screen, „Źródła
i warunki” opening a dialog with every line and the terms; the same content in a welcome window
on the first visit; files, exports, images, hand-offs and API fields unchanged), DEV-20.7,
DEV-15.6 (the kit copied byte for byte), DEV-15.7 (the regulamin opens in a new tab).

## Goal

The map is Hydrograf's one view. Its data with PMAXTP lines (the hydrograph and its hyetograph,
an own series copied from PMAXTP, the SFINCS result on the map, the water of the point card and
of the terrain profile) showed the five lines in up to six blocks of their own: 16 to 23 rows
each at 1440 px. The view now shows them once, in the kit's strip under the map and the
panels, and every product keeps the full lines.

## Audit (2026-11-13, before this plan; rows measured in Chromium)

| Surface | Lines before (1440 px / 390 px) | After |
|---|---|---|
| „Hietogram” (`#hietogram-attribution`) | PS, PP, M, N, RK: 16 / 17 rows | none; the view's strip |
| „Hydrogram” (`#hydrograph-attribution`) | the same: 16 / 17 rows | none; the view's strip |
| Own series from PMAXTP (`#custom-rain-attribution`) | the same: 16 / 17 rows | none; the view's strip while the table is shown |
| Legend of the SFINCS result | the same: 23 / 23 rows | the classes only; the view's strip while the layer is on |
| (i) of the SFINCS result | the same after „Źródła:” | description and source only |
| Point card „Woda” (`.identify-lines`) | the same: 17 / 16 rows | none; the view's strip while the card shows the water |
| Profile drawer (`#profile-attribution`) | the same: 11 / 16 rows | none; the view's strip while the drawer shows the water |
| Welcome window | none | the full lines and the terms, `fillSources()` |
| Exports, hand-off, API, `analyze_watershed`, guide, slides | the full lines | unchanged |

## Steps

1. Copy the kit byte for byte into `frontend/nogat/`: `nogat-sources.js` and `.css`,
   `nogat-app-menu.js` and `nogat-kit.json` of 0.5.1. Done.
2. `index.html`: one `<nogat-sources id="view-sources">` in the foot of the view
   (`#view-foot`, a row across the map and both panels, above the footer); the four blocks
   removed. `js/nogat.js` loads the element and hands on `fillSources`; `js/terms.js` gives the
   strip its `terms`. Done.
3. `js/attribution.js`: `show(surface, source, places)` keeps the lines of each surface and
   puts their union into the strip; lines of a part of the results panel count only while it
   is laid out (a cleared watershed, a new one loading, the network, a collapsed panel).
   `hydrograph.js`, `custom-rain.js`, `results.js`, `identify.js` and `profile.js` call it;
   the legend and the (i) lose the lines. Done.
4. `GET /api/terms` adds `attribution` and `terms_notice`, PMAXTP's lines from
   `core/attribution.py`, on every deployment (AGI-4.1, additive); `js/welcome.js` writes them
   with `fillSources()` under its text. The alternative, a copy of the lines in the front end,
   would be a second place of them (DEV-20.4). Done.
5. Phones: the sheets „Warstwy” and „Zlewnia” stop above the foot of the view
   (`--view-foot-h` from `js/shell.js`), so the strip stays in sight with the hydrograph. Done.
6. The footer's „Regulamin” opens in a new tab, on the map and in the guide (DEV-15.7). Done.
7. Gate: a contract test checks the kit's hashes against its manifest and that the map has one
   strip and no block of lines; `test_site.py` the new fields. Done.

## Verification

A smoke in Chromium on a throwaway harness (the worktree's front end and API on one origin, a
free port, a stub database): the welcome window, the strip at 1440 and 390 px in every state,
the dialog (Esc, focus back on the button), the strip following the panel's sections, and the
three rainfall exports with the full lines.
