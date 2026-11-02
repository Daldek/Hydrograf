# ADR-065: Nogat visual identity and Archiwista's shell instead of glassmorphism panels

**Date:** 2026-11-01
**Status:** accepted

ADR-063 and ADR-064 are not used: when this ADR was numbered on `feature/visual-identity`,
the numbers 058 to 064 were reserved in the specifications and plans of the Kartograf work
(058 to 062 are the ADRs of `feature/producer-heads`).

## Context

The interface of Hydrograf had a style of its own: semi-transparent glassmorphism panels
(`css/glass.css`, `css/style.css`), a floating panel dragged with the mouse
(`js/draggable.js`) and Bootstrap on every page. Every application of the Nogat ecosystem
looked different, so a user moving between them learned the layout, the colours and the
controls anew. Nogat adopted a shared visual identity (decision ECO-055, standard
DEV-15.3): tokens in `design/tokens.css` (palette and font from debever.pl, density and
controls from Archiwista), Archiwista's shell as the layout pattern, and a mock-up of
Hydrograf in `design/mockups/hydrograf/`.

## Options considered

- **A. Keep the glassmorphism interface unchanged.** No work, but Hydrograf stays the only
  application of the ecosystem outside the shared look.
- **B. Only recolour the current interface with the Nogat tokens.** Shared colours, but the
  layout (floating panel, Bootstrap) still differs from the other applications of the
  ecosystem.
- **C. Nogat tokens and Archiwista's shell:** a top bar, a navigation rail, side panels of
  adjustable width, a phone layout, a light and a dark theme.

## Decision

Option C. `frontend/css/tokens.css` is a copy of Nogat's `design/tokens.css` (commit
29e7e1c, named in the file header); it is not edited in Hydrograf: a change of the palette
goes through Nogat and a fresh copy. All colours, fonts, radii and shadows come only from
the tokens, the Chart.js charts too (read through `getComputedStyle`, repainted when the
theme changes). The shell (`css/chrome.css`) is shared by the main page, `/admin` and
`/instrukcja`. The main page has a left panel „Warstwy” (260–560 px), the map with the mode
bar and a bottom drawer for the terrain profile, and a right panel „Zlewnia” (340–720 px)
with `<details>` sections; below 860 px a bottom bar and sheets that open from the bottom.
The theme Auto/Jasny/Ciemny is kept in `localStorage` (`nogat-theme`) and set before the
first paint (`js/theme-init.js`). The main page has no Bootstrap (the feedback form is a
native `<dialog>`); `/admin` keeps Bootstrap 5.3.3 for the grid and the modal dialogs,
recoloured with the tokens. The base layers suit the grey palette: OpenFreeMap grey (vector,
MapLibre GL), OSM GUGiK grey, Ortofotomapa ESRI, and no base layer.

## Consequences

- One look and layout in every GUI of the ecosystem (ECO-055): a user of Archiwista finds
  their way in Hydrograf at once.
- The dark theme, the phone layout and theme-aware charts come without separate work in
  each application.
- Less own CSS and JS: `glass.css`, `style.css` and `draggable.js` are deleted, and
  Bootstrap is gone from the main page.
- `tokens.css` is a copy, not a dependency: after the tokens change in Nogat it must be
  copied again by hand (the source commit is in the file header).
- Bootstrap stays in `/admin`: two style systems on one page, and Bootstrap must be
  recoloured with the tokens at every change of the palette.
- New libraries from a CDN (MapLibre GL 4.7.1, `@maplibre/maplibre-gl-leaflet` 0.0.22),
  loaded with SRI (`integrity` + `crossorigin`) like Leaflet and Chart.js; the CSP gains
  `https://tiles.openfreemap.org` (`connect-src`) and `blob:` (`img-src`, `worker-src`,
  `child-src`).
- The default base layer depends on the external OpenFreeMap; without MapLibre the layer
  falls back to OSM GUGiK.
- The results panel is no longer floating or draggable: the panels stay at the edges, with
  an adjustable width, and can be closed.

## Errata

None.
