# ADR-082: Nogat's app menu and hand-off: the GUIs from HYDROGRAF_GUI, the kit through one module

**Date:** 2026-11-12
**Status:** accepted

## Context

Nogat's ECO-058 and step 5 of its plan `docs/plans/2026-11-12-gui-links-and-handoff.md`
(stage 1 of the GUI platform, approved by the author on 2026-11-12) give every GUI of the
ecosystem two pieces of Nogat's kit (`design/kit/`, kit 0.1.0 at Nogat `7786271`), copied
byte for byte and never edited (DEV-15.6):

- the app menu `<nogat-app-menu>` in the top bar, left of the theme switch (DEV-15.4). It
  lists the GUIs that the deployment sets in the table `gui` of `[nogat]` in `nogat.toml`
  (DEV-18.1): a registry name in lower case to an address. The app hands that table to its
  page; with no other GUI, or no table, the menu is not drawn. Nogat's plan (B3, D4) says
  Hydrograf, in Docker, reads the table from an environment variable of its compose file,
  named in its own plan;
- `nogat-handoff.js` for the hand-off (DEV-15.5): the labels, the file name
  `<subject>.handoff.json`, the text, the clipboard with its fallback, the download and the
  reading. Building the document stays the API's (ADR-068, ADR-080).

Hydrograf runs as Docker Compose projects (production, Hydroni, a staging stack), each
with its own `.env` and public host; the API and nginx run read-only, nginx with
`docker/nginx.conf` mounted as one file; no container sees the host's `nogat.toml`, and
Hydrograf reads its settings from the environment only (CLAUDE.md, deviation DEV-18). The
kit is ES modules; Hydrograf's scripts are IIFE modules on `window.Hydrograf` (deviation
DEV-15.1), and the pages load them as `?v=<content hash>` because Cloudflare caches `.js`
at the edge (`scripts/bump_asset_versions.py`).

## Options considered

How the deployment gives the table:

- **A1. The API reads `nogat.toml`** mounted into the container (`NOGAT_CONFIG`). One file
  for every app of a machine, but a mount per instance, the public instances need their own
  file anyway, and Hydrograf would read a configuration file for this one key.
- **A2. nginx writes a JSON file from a template** (`envsubst` of the nginx image). No API
  code, but nginx runs read-only with its configuration mounted as one file; a template
  needs a writable output and a second way of configuring nginx, and JSON through
  `envsubst` breaks on quoting.
- **A3. A file per instance in `frontend/data/`**, like `instance.json`. No code, but the
  setting would live apart from the other settings of the deployment's `.env`, and Nogat's
  plan names an environment variable.
- **A4. An environment variable `HYDROGRAF_GUI`** (DEV-18.1's `<TOOL>_<KEY>` for the key
  `gui`) holding the table as JSON, passed by `docker-compose.yml` to the API, checked when
  the settings load and served by a route.

How the IIFE scripts reach the kit:

- **B1. `js/handoff.js` becomes an ES module** that imports the kit. The only module among
  the IIFE scripts, and every page still needs a loader for the menu.
- **B2. A dynamic `import()` in the IIFE script.** The kit arrives after the script, so the
  buttons wait for it.
- **B3. One bridge module, `js/nogat.js`, on every page.** It imports both kit modules,
  gives every `<nogat-app-menu>` its table and puts the hand-off module and the addresses on
  `window.Hydrograf.nogat`; a module script runs in document order with the deferred
  scripts, so the kit is there before the scripts after it.

## Decision

A4 and B3.

1. `HYDROGRAF_GUI` (`core/config.py`, `.env.example`, `docker-compose.yml` passes
   `${HYDROGRAF_GUI:-}` to the API) holds the table as one JSON object, e.g.
   `{"hydrolog": "http://127.0.0.1:8070/", "archiwista": "http://127.0.0.1:8090/"}`: each
   key a registry name in lower case, each address an http or https URL or a path from `/`
   on this host. `gui_table()` reads it; the settings refuse any other value when they
   load, so the API does not start with a table the menu cannot use. Empty or unset: `{}`,
   no menu. No defaults (Nogat's B2).
2. `GET /api/gui` (`api/endpoints/gui.py`) returns the table, `{}` without it.
3. `js/nogat.js`, an ES module and the only one of Hydrograf's own, is loaded by `index.html`,
   `admin.html` and `instrukcja/index.html`. It imports `nogat/nogat-app-menu.js` and
   `nogat/nogat-handoff.js`, fetches `/api/gui` once, sets it as the `apps` of every
   `<nogat-app-menu>` of the page (`current="hydrograf"`, in the top bar left of the theme
   switch) and exposes `window.Hydrograf.nogat.handoff` (the kit's module) and
   `window.Hydrograf.nogat.address(name)` (the address of a GUI as the menu links it, or
   null).
4. `js/handoff.js` keeps the documents of the API and the panel's texts, and takes from the
   kit the labels („Kopiuj do Hydrologa”, „Plik przekazania”), `copyHandoff` into the
   panel's field `#handoff-text`, `downloadHandoff` and the statuses (`TEXTS.copied`,
   `TEXTS.copyByHand`, `TEXTS.saved`), each followed by where Hydrolog opens the hand-off
   and, when the table names Hydrolog, the link „Otwórz Hydrologa” in the tab
   `nogat-hydrolog` the menu opens it in.
5. `scripts/bump_asset_versions.py` also versions the relative imports of the modules in
   `js/` (`../nogat/nogat-handoff.js?v=…` in `js/nogat.js`) before the pages, so a new copy of
   the kit changes the addresses of the kit and of the bridge. Unversioned imports stay in
   the caches of Cloudflare and of the browsers for hours (ARCHITECTURE §5.2), so a new
   bridge could meet an old kit.
6. The copies sit in `frontend/nogat/`: the four kit files and, in `nogat/marks/`, the marks
   of the four GUIs (`archiwista`, `hydrograf`, `hydrolog`, `obserwator`); the favicon and the
   brand stay `img/hydrograf.svg`, a copy of the same mark.

## Consequences

- No deployment shows the menu until its `.env` sets `HYDROGRAF_GUI` and the API is
  recreated: production, Hydroni and the public test instance each get their own table
  (the author's answer 1 of Nogat's plan: the public deployment lists Hydrograf, Hydrolog
  and Archiwista; the workstation its local ports).
- A malformed `HYDROGRAF_GUI` stops the API at its start, with the reason in the log, like
  any other invalid setting.
- The hand-off's text and the file name of a subject are those of before; the name rule also
  replaces DEL (`\u007f`). On a plain-HTTP address (or a refused clipboard) the text is
  selected in the field for Ctrl+C: Hydrograf's own attempt with `document.execCommand('copy')`
  is gone, as the kit does not make it. The statuses are the kit's („Skopiowano przekazanie
  do schowka.”, „Zapisano plik „…”.”).
- Nogat's `drift` reports the copies of `frontend/nogat/`, `frontend/css/tokens.css` and
  `schemas/nogat/` as current or behind; a new kit is copied again with the asset versions
  bumped.
- The deviation DEV-15.1 of `CLAUDE.md` names `js/nogat.js` and the kit as the ES modules of
  the front end.
