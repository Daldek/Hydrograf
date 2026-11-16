# ADR-086: The admin panel on Nogat's kit: /admin/, the core API and Hydrograf's sections

**Date:** 2026-11-14
**Status:** accepted

## Context

Nogat's ECO-067 and DEV-15.13 (kit 0.7.0, step 3 of Nogat's plan
`docs/plans/2026-11-13-admin-panel.md`, approved by the author on 2026-11-13) give every GUI
one admin panel: the page at `/admin/` (`/admin` answers 308), the API under `/api/admin/`
and nothing else, the kit's `<nogat-admin>` with „Zgłoszenia”, „Statystyki” and „Stan”,
the key of `ADMIN_API_KEY` or `ADMIN_API_KEY_FILE` read per request, `401 unauthorized`
with `admin_key_not_configured`, `admin_key_missing` or `admin_key_invalid`, no generated
key, `Cache-Control: no-store`, CSP `'self'`, the requests limited but not counted.
Hydrograf had a Bootstrap page at `/admin.html` with a dashboard, resources, the DEM
bootstrap, cleanup, the boundary and sewer uploads and the reports, and drew and logged a
random key when none was set (ADR-034).

## Options considered

- **Where the dashboard goes.** A: its version, uptime and database state into `status`,
  its row counts and the sizes of the data directories into `resources`. B: extra members
  of `status`. B breaks the core API, which is the same in every GUI.
- **The area map of the bootstrap.** A: keep it, with the page's CSP `'self'` but for the
  images of GUGiK's OpenStreetMap tiles. B: strict `'self'` without the map. The author
  chose A (2026-11-14): a basemap from its provider is what DEV-15.7 allows.
- **The reports of the old form.** The kit shows `message` and `context`; their old fields
  stay in the list's member `legacy`, which the kit does not show. The author kept the API
  as it is (2026-11-14) and decides on those reports separately.

## Decision

A, A and the API kept.

1. `frontend/admin/index.html` is the kit's shell with four sections of Hydrograf's own,
   on the tokens and through the shell's `adminFetch`: „Zasoby” (`resources`),
   „Przetwarzanie NMT” (`bootstrap/*`, the bbox drawn on a Leaflet map), „Czyszczenie”
   (`cleanup*`) and „Granice i kanalizacja” (`bootstrap/upload-boundary`, `sewer/*`).
   Bootstrap, `/admin.html`, `js/admin/` and `css/admin.css` are gone.
2. `GET /api/admin/status` (checks `database`, `catchment_graph`, `data_dir`) replaces
   `dashboard`; `GET /api/admin/stats` reads `stats.jsonl` with the current day as counted.
3. `api/dependencies/admin_auth.py` generates no key: without one every admin route
   answers `admin_key_not_configured`.
4. `api/traffic.py` limits the page and the API of the panel, counts them in no total and
   sends each of their answers with `Cache-Control: no-store`; nginx serves the page with
   its own CSP and no fallback without the API.

## Consequences

- A deployment must set `ADMIN_API_KEY` or `ADMIN_API_KEY_FILE`, or the panel refuses.
- Cloudflare Access protects `/admin`, `/admin/*` and `/api/admin/*`; `/admin.html` is 404.
- ADR-034 is amended: the page and its sections are those above.
