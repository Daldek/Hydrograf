# ADR-089: The base maps from Nogat's kit: its catalogue, its switcher, the settings and a static CSP

**Date:** 2026-11-25
**Status:** accepted (step 4 of Nogat's plan `docs/plans/2026-11-24-shared-base-maps.md`,
approved by the author on 2026-11-24; Nogat DEV-15.15, DEV-15.13, DEV-18.1, ECO-089, kit
1.3.0)

## Context

The author asked on 2026-11-24 for one set of base maps in every GUI with a map, with
Hydrograf's set and behaviour as the model. Nogat's kit 1.3.0 (Nogat `40bae70`, `develop`)
holds it: the catalogue `nogat-basemaps.json` (`openfreemap` „OpenFreeMap szary”, the
default; `gugik-osm` „OSM GUGiK szary (tylko Polska)”; `gugik-ortho` „Ortofotomapa GUGiK”;
each with its tile address, origin, zoom range, bounds, credit and the regulamin's blocks
its data needs), `nogat-basemaps.js` (`<nogat-basemaps>`, the Polish words, the adapters
`leafletBasemap` and `maplibreBasemap`) and `nogat-basemaps.css` (the credit and the grey
style's colours in both themes). Nogat's DEV-15.15 makes it the rule: a GUI draws its base
map only from the catalogue's entries its setting `basemaps` allows and from the
deployment's own base maps (`basemap_extra`), through the kit's module; DEV-18.1 names the
keys `basemaps`, `basemap_mirrors` and `basemap_extra` of `[<tool>]` and `[nogat]`;
DEV-15.13 lets the admin page's CSP admit its base map's origin.

Hydrograf had its own list: `BASEMAPS` of `js/layers.js` with three factories (OpenFreeMap's
hosted style `styles/positron`, with its sprites and fonts from tiles.openfreemap.org and
English names where the tiles have them; GUGiK's OSM greyed by `.basemap-grey`, falling in
for OpenFreeMap without MapLibre; GUGiK's orthophoto), its own radio list, the providers'
English credits, no memory of the choice and nothing said when a provider failed. The admin
dialog's map drew GUGiK's OSM by hand, and its page's `img-src` refused the empty `data:`
image Leaflet gives each tile it removes (known defect 4 of the browser tests).

## Options considered

- **Hydrograf's own list beside the kit's.** Rejected: three GUIs had three sets already,
  and a list kept by hand drifts.
- **OpenFreeMap's Positron, as before.** Rejected by the author's answer to the plan's open
  question 2: the kit draws OpenFreeMap in its grey style (Polish names, colours from the
  tokens in both themes) over the TileJSON, with glyphs of the GUI's own.
- **A CSP built by the API from the allowed entries.** Rejected: nginx serves the pages and
  sets their headers, so its file is the CSP; nogat.toml reaches the backend alone, and an
  nginx that read the settings would need a template or a second reader of the file.

## Decision

1. `frontend/nogat/` is the kit 1.3.0, copied whole (with `nogat-chart.*` and
   `nogat-command-form.*`, unused by Hydrograf yet). The group „Podkłady kartograficzne” of
   „Warstwy” holds the flood hazard map's row, then the kit's `<nogat-basemaps>` fed by
   `GET /api/basemaps`; `js/nogat.js` puts the kit's words, `leafletBasemap` and the
   repaint of a vector base map on `window.Hydrograf.nogat.basemaps`, and `js/layers.js`
   draws the chosen entry with them. `BASEMAPS`, its factories, the radio list,
   `.basemap-grey` and the fallback without MapLibre are gone.
2. The map stays on Leaflet: the kit's Leaflet adapter draws a raster entry as image tiles
   and OpenFreeMap through MapLibre GL 4.7.1 and `maplibre-gl-leaflet` until Hydrograf's
   map moves to MapLibre (Nogat plan `2026-11-24-hydrograf-maplibre`), which retires the
   adapter.
3. OpenFreeMap is the kit's grey style over `https://tiles.openfreemap.org/planet`, nothing
   else from OpenFreeMap; its glyphs are Noto Sans 2.0 of openmaptiles/fonts, vendored in
   `frontend/vendor/openmaptiles-fonts-2.0/noto-sans-regular/` (the ranges 0-255, 256-511,
   512-767, 1024-1279 and 8192-8447, OFL-1.1), repainted at a change of theme
   (`Hydrograf.map.onThemeChange`).
4. The choice is kept in the browser (`localStorage` `nogat-basemap`); the map opens on it
   while it is offered, else on the first default entry of the catalogue. A provider that
   does not answer is marked „Podkład nie odpowiada” in the list and said on the map
   (`#basemap-notice`); nothing switches by itself. The credit is the catalogue's Polish
   line in Leaflet's attribution corner, 12 px in `--text-3`, folded behind „i” at the
   first drag up to 860 px.
5. The settings `basemaps` (the first of `HYDROGRAF_BASEMAPS`, `NOGAT_BASEMAPS`, ids joined
   by `,`, empty for none, then `basemaps` of `[hydrograf]`, then of `[nogat]` in the
   nogat.toml of NOGAT_CONFIG; every entry by default), `basemap_mirrors` (a catalogue id
   to the address of the deployment's copy, which replaces `url` and `origin`) and
   `basemap_extra` (own base maps `{id, name, kind xyz|wms|vector, url, attribution,
   grayscale}`, a WMS made a tile template) are read by `core/basemaps.py` at the API's
   start; a wrong value stops the API with the error document `hydrograf-error/1` on
   standard error (`validation_error`, the option, value and source in `details`), and so
   does an unreadable catalogue (`basemap_catalogue_unreadable`).
6. `GET /api/basemaps` answers the allowed entries in the catalogue's order, then the own
   base maps; `[]` means no base map. The regulamin keeps `pmaxtp`, `gugik`, `isric` and
   `wody-polskie` and the blocks the allowed entries name (`osm` with `openfreemap` or
   `gugik-osm`).
7. The CSP of `docker/nginx.conf` and `docker/nginx-ssl.conf.template` is static: `img-src`
   and `connect-src` name the catalogue's origins (`https://tiles.openfreemap.org`,
   `https://mapy.geoportal.gov.pl`) and `img-src` the flood hazard map's
   `https://wody.isok.gov.pl`; `tests/contract/test_nginx_csp.py` compares them with the
   catalogue. `basemaps` narrows the switcher and the blocks, not these lines.
8. The admin dialog's map draws the first allowed raster entry (`gugik-osm` by default,
   none without one) through the kit's adapter, imported by `admin/processing.js`; a
   failure is said under the map (`#bbox-map-notice`). The admin page's `img-src` is
   `'self' data: https://mapy.geoportal.gov.pl`.

## Consequences

- The kit is 1.3.0; its regulamin template 1.1 names „podkład mapy” among the settings the
  browser keeps (§ 8 ust. 7) and the API and its programs (§ 4 ust. 2, § 6 ust. 2). A
  public deployment sets a new `terms_effective` in `[nogat.operator]` of its nogat.toml
  when it releases this, or its regulamin 1.1 carries the date of 1.0.
- A deployment with a copy (`basemap_mirrors`) or an own base map (`basemap_extra`) adds its
  origin to its own copy of the nginx file; the repository's file names the catalogue's
  origins only.
- ADR-065 is amended (the base maps and their fallback), ADR-085 (the orthophoto as a
  catalogue entry, the regulamin's blocks) and ADR-086 (the admin map and its `img-src`).
