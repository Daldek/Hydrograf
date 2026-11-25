# ADR-092: The map on MapLibre GL JS 6.14.0 instead of Leaflet

**Date:** 2026-11-25
**Status:** accepted (step 2 of Nogat's plan `docs/plans/2026-11-24-hydrograf-maplibre.md`,
approved by the author on 2026-11-24, its design M1 to M14 and the answers to its open
questions 1 to 8; Nogat DEV-15.7, DEV-15.13, DEV-15.15). Supersedes ADR-003; amends ADR-065,
ADR-085, ADR-086 and ADR-089.

## Context

ADR-003 (2026-01-14) chose Leaflet for the map. Since then the map grew around it: the vector
base map OpenFreeMap drawn by MapLibre GL 4.7.1 through the bridge `maplibre-gl-leaflet`
0.0.22 (ADR-065, since ADR-089 the kit's Leaflet adapter `leafletBasemap`), the streams, land
cover and storm sewer as vector tiles through Leaflet.VectorGrid 1.3.0 (its last release
2017-08-28), and seven panes for the order of the layers. Obserwator and Archiwista draw their
maps with MapLibre GL JS 6.14.0, vendored with the same four files, and Kartograf's planned map
is on it; Leaflet 2.0, in beta, would force a migration of Leaflet and its plugins. The author
asked on 2026-11-24 that Hydrograf's map move to MapLibre by a plan of its own, in a minor of
its own. Step 1 of that plan (`backend/tests/e2e/`, merged before this) tests the map by what
a person sees and the requests the page sends, read through `Hydrograf.map.describe()` as a
scale, never as a zoom number, so that the same tests hold on either library.

## Options considered

- **A. The whole map on MapLibre GL JS 6.14.0.** One map library and version in the
  ecosystem; a rewrite of the map code (about 110 calls of Leaflet in nine files, 37 CSS
  rules, the admin dialog's map); the zoom numbers, the vector tiles' levels, the WebGL 2
  requirement and the results below their first level change.
- **B. Leaflet kept, its vector base map on MapLibre 6.14.0** (`maplibre-gl-leaflet` 0.1.4).
  Small, but Leaflet, VectorGrid and a bridge stay beside MapLibre, and Leaflet 2.0 is still
  ahead. Rejected by the author, who chose A on 2026-11-24.

## Decision

A:

1. **The library.** `frontend/vendor/maplibre-gl-6.14.0/` holds Obserwator's four files byte
   for byte (`maplibre-gl.mjs`, `maplibre-gl-worker.mjs`, `maplibre-gl.css`, `LICENSE.txt`),
   their SHA-256 checked by `tests/contract/test_frontend_vendor.py`; the stylesheet keeps its
   `<link>` with `integrity`. Leaflet 1.9.4, Leaflet.VectorGrid 1.3.0, `maplibre-gl-leaflet`
   0.0.22 and MapLibre GL 4.7.1 are removed, and `js/sewer.js` with them (`js/map.js` draws
   the sewer). nginx serves `.mjs` as `application/javascript`.
2. **One owner.** `js/map.js` loads the module by `import()` from its IIFE and alone touches
   the library on the main page (`admin/processing.js` on the admin page). `Hydrograf.map.init`
   returns `Hydrograf.map.ready`, which resolves to true once the map is drawn and to false
   without one, and never rejects; the other modules wait for it and ask `Hydrograf.map` for
   overlays by id (shown, opacity, extent, filter, tiles), points, labels, controls and the
   view. `_getMap()` is gone; a new streams threshold fires `hydrograf:streams`, a result
   turned on or off `hydrograf:results`.
3. **The map.** An empty style with a `background` of `--surface-2`, centre 19.5° E 51.9° N,
   zoom 6, at most 21; no rotation or pitch; a `NavigationControl` without compass at the
   bottom right; MapLibre's credit control, compact up to 860 px; the controls' names in
   Polish. MapLibre's world is 512 px wide, so **every zoom number is one less than Leaflet's
   for the same scale**. The wheel and a pinch zoom by fractions of a level with MapLibre's
   own handler; Hydrograf's `wheelZoomHandler` is gone.
4. **The order of the layers** (M4). Empty layers name the slots, from the bottom up: base map,
   DEM, flood hazard map, land cover, results, streams, delineation preview, the overlays of
   „Warstwy” (BDOT10k lakes, soil groups, BDOT10k streams, depressions, sewer), watershed
   (boundary, main channel, longest and divide flow paths, outlet), network, drawing (the
   profile's line and vertices, the profile's marker, identify's marker). Each layer goes in
   under its group's slot, in this order within the group. The network's points and labels
   are DOM markers over the canvas, the labels under the points.
5. **Vector tiles** of the streams, land cover and sewer are `vector` sources, styled by
   expressions over the tokens; the opacity sliders set the layers' paint opacity. A vector
   source's tiles are 512 px, so MapLibre asks a tile one level lower than Leaflet did at the
   same scale. Each layer still appears at the scale it did: `scripts/generate_tiles.py`
   writes the pre-generated streams from level 7 (the threshold of 1000 m² from 13, was 8 and
   14) and the sewer's endpoint answers from level 9 (was 10). A threshold switch makes the
   streams' source anew, keeping whether it is shown and its opacity: MapLibre drops a
   vector source's new tiles of `setTiles` when a layer of the source changes before they
   load, and keeps drawing the old ones.
6. **Raster and images.** The DEM's tiles are a `raster` source of 256 px with the levels of
   their metadata, the layer from one zoom below the first level; the DEM's single PNG and
   the depressions' PNG are `image` sources, whose credit is set on the source once it is
   added (the style's image source takes no `attribution`, and a source that names one is
   refused, so the layer was never drawn). A result of an analysis is a `raster` source with
   its manifest's levels, drawn from its first level: farther out its row says „Przybliż
   mapę — wynik jest rysowany od skali ok. 1:N.” (the plan's open question 4); the manifest
   is unchanged. A tile that does not load leaves the map as it is.
7. **The flood hazard map** is a `raster` source of 512 px whose tiles are the service's GetMap
   with `{bbox-epsg-3857}`, its layer from zoom 13 (1:34 124, inside the services' 1:50 000);
   below it nothing is asked. The source takes the whole level at or below the zoom, as a
   vector source does, not the nearest, so a zoom in asks the slow service only for the view
   the map ends at. A probability switch changes the source's tiles.
8. **Pointer and drawing.** A click on a marker stays the marker's; hover tooltips are one
   MapLibre `Popup` without a close button; the network's points are draggable `Marker`s that
   pan the map while dragged within 20 px of its edge (open question 5). The profile is drawn
   with today's gestures over a GeoJSON source; the admin box is drawn with the mouse while
   the dialog's map never pans.
9. **The credit** of the map's sources is MapLibre's credit control. Once no credited source
   is left the control hides but keeps the last words it showed; the kit's `maplibreBasemap`
   and `removeMaplibreBasemap` empty them (Nogat `1a68cc7`), so the credit of a base map that
   failed or was taken off does not come back with the control.
10. **Without WebGL 2** (6.14.0 asks for `webgl2` only) the map's area says „Mapa wymaga
    przeglądarki z WebGL 2.”, `ready` resolves to false and the panels work without a map;
    the admin dialog says „Mapa wymaga przeglądarki z WebGL 2. Wpisz granice obszaru w pola
    formularza.” in place of its map. Nothing else falls back.
11. **CSP.** The page: `connect-src` adds `https://wody.isok.gov.pl` (MapLibre fetches the
    flood hazard map's tiles), and `worker-src 'self'` (MapLibre's worker, a file of
    `vendor/`) replaces `worker-src blob:; child-src blob:`. The admin page: `img-src` and
    `connect-src` are `'self'` and the origin of its base map, `worker-src 'self'`, no
    `data:`. `tests/contract/test_nginx_csp.py` checks both.

## Consequences

- A browser needs WebGL 2 (Chrome 56, Firefox 51, Edge 79, Safari 15) to show the map; one
  without it, or with WebGL 2 off, gets the panels without a map, where before it got the map
  without the vector base map.
- `params.map.zoom` in the context of „Zgłoś uwagę” is one less for the same view than in
  reports sent before.
- A deployment generates its pre-generated tiles again (`scripts/generate_tiles.py`), or its
  streams appear one scale step later than before; one with its own nginx file takes the
  `types` line of `.mjs`, `.mjs` in the location of the static code and both CSP values.
- At one scale a vector tile covers four times the ground of a Leaflet tile, so the dynamic
  tile endpoints answer a quarter of the requests, each over a larger box.
  `tests/performance/test_tile_load.py` times them at each layer's first level and at
  1:10 000 against the level above; on the synthetic data of the browser tests each ratio
  was between 0.90 and 1.68, and a run on a deployment's database is still to be made.
- MapLibre draws a remote image only with CORS: the flood hazard map's WMS, GUGiK's
  orthophoto and OSM tiles and OpenFreeMap all answered `Access-Control-Allow-Origin: *` on
  2026-11-24; a provider that drops it loses its layer.
- WebGL lines, dash patterns in line widths and fractional zoom change the look of the map,
  and so its pictures in the guide.
- The kit's `leafletBasemap` has no user in Hydrograf; Nogat's plan removes it in its step 3,
  after this is released.
- ADR-003 is superseded. ADR-065 is amended (MapLibre GL 4.7.1 and `maplibre-gl-leaflet`,
  the CSP's `blob:` workers), ADR-085 (the libraries vendored: MapLibre GL JS 6.14.0 alone
  for the map), ADR-086 (the area map and its page's CSP) and ADR-089 (the base maps drawn by
  the kit's `maplibreBasemap`, their credit in MapLibre's control, the admin page's CSP).
