# ADR-090: The charts on Nogat's kit: nogat-chart.js instead of Chart.js

**Date:** 2026-11-25
**Status:** accepted (step 5 of Nogat's plan `docs/plans/2026-11-24-unified-charts.md`,
approved by the author on 2026-11-24 with option A of its open question 3; Nogat
DEV-15.16, ECO-090, kit 1.3.0)

## Context

Obserwator's feedback #9 (2026-11-23) asked for zoom, pan and a reset of the view in the
charts of every GUI, and the author answered on 2026-11-24: one behaviour and one
implementation of charts across the GUIs. Nogat's kit 1.3.0 (already copied into
`frontend/nogat/` by ADR-089) holds that implementation, `nogat-chart.js` and
`nogat-chart.css`: `drawChart(container, spec)` draws an SVG with its axes, series,
marks, legend, a readout by pointer, finger and keys, and on a chart of a time or a value
the zoom (a drag selects a range, Ctrl with the wheel or two fingers zoom around the
cursor, Shift with a drag or the middle button pans, a double click, the key 0 and „Cały
zakres” show the whole, the bar under the chart „−”, „+”, „Cały zakres” and the range
shown, a lone „+” before a zoom); `toPng` writes a drawn chart as a PNG with the
providers' lines under it. Nogat's DEV-15.16 makes it the rule: a GUI draws its charts over
axes with the kit's module, never with a chart library.

Hydrograf drew six charts with Chart.js 4.4.7 (`frontend/vendor/chart.js-4.4.7/`,
205,615 B, `js/charts.js`, 888 lines): the hypsometric curve, the land cover and the soil
groups as one stacked bar each beside a class list, the terrain profile (its hover moved a
marker on the map), the hietogram and the hydrograph as filled lines over minutes. Their
colours were read from the tokens and set again by a styler of each chart at every change
of theme. None zoomed; none was exported as a picture.

## Options considered

- **A: the kit's module** (chosen by the author's answer to the plan's question 3): the
  same code, gestures, words and look as Obserwator, Hydrolog and Archiwista.
- **B: Chart.js with `chartjs-plugin-zoom` 3.0.2 until A.** Rejected: a second
  implementation of the same gestures that DEV-15.16 forbids, its middle button, keys, bar,
  double click and live region Hydrograf's own code, on a plugin line three days old, and a
  second migration later.
- **Chart.js without zoom.** Rejected: DEV-15.16, and feedback #9 asks for the zoom.

## Decision

1. `js/charts.js` draws every chart with the kit's `drawChart`, which `js/nogat.js` hands
   on as `Hydrograf.nogat.chart` (`draw`, `toPng`, and `format`, the kit's Polish numbers
   and times, `chartFormat()`); `nogat-chart.css` is linked before `css/app.css`. The
   charts' `<canvas>` elements are containers (`<div>`) with the same ids. Chart.js 4.4.7,
   its licence, its `<script>` and its `integrity` are removed.
2. The charts, each with a name (its `role="img"` label) and drawn at its container's
   width (`fit`), in the results panel, the profile drawer and on a phone alike, and again
   when that width changes (the kit's `ResizeObserver`: a panel resized, a section opened):
   - the hypsometric curve: x the share of the area at or above an elevation (0–100 %),
     y the elevation, an area; the readout names both;
   - the terrain profile: x the distance [km], the terrain an area broken where the DEM
     has no data; the water surface of a result shown on the map a line, filled down to
     the terrain where it lies above it (a band), a lone wet sample a dot; the readout's
     heading names the depth there; its `onReadout` puts the marker on the map at the
     sample's share of the profile's length, measured along the line drawn in metres
     (degrees of longitude shortened by the cosine of the latitude), as the API samples it;
   - the hietogram: x the time, the total and effective precipitation as bars from the
     start to the end of each step (the kit's `bar-p` and `bar-pe`), the largest step a
     `peak` mark, the readout naming the step („0:55–1:00”);
   - the hydrograph: x the time, the discharge an area, its peak a `peak` mark;
   - the land cover and the soil groups: one horizontal bar per class with its share (the
     kit's band axis), its name and its figure (the CN of the class, the area of the
     group) left of it, the share right of it: a change of their look from one stacked bar
     and a class list (the plan's C14).
3. Colours are classes in the tokens: the kit's (`s1`, `s3`, `bar-p`, `bar-pe`) and
   Hydrograf's in `css/app.css` (the land cover classes `lc-*`, the soil groups `hsg-*`,
   `share-other`, the profile's `terrain` and `water`); no styler, so a change of theme
   recolours the charts without a redraw. The overlays of the land cover and the soil
   groups on the map keep their colours from `charts.js` (`LAND_COVER`, `HSG`), mixed from
   the same tokens by the same weights as the classes, so a bar has its class's colour on
   the map.
4. Numbers in the kit's Polish (a decimal comma, the minus sign U+2212), times as h:mm; a
   time axis is labelled in minutes up to a step of an hour, else in hours (the kit's
   `time` scale), where Chart.js wrote minutes always. The charts are not animated.
5. Which charts zoom, by the plan's C9: the hypsometric curve, the profile, the hietogram
   and the hydrograph (x a share, a distance or a time); the share charts (a band axis)
   do not. A chart keeps its range while its data are the same and shows the whole when
   they change (C13); the hietogram and the hydrograph zoom apart, as their time ranges
   differ.
6. „PNG” beside each chart's title (in the profile drawer's head, its icon alone on a
   phone) saves the chart as shown (the range shown, its y fitted, without the readout)
   by the kit's `toPng`, with the lines of the response the chart is drawn from
   (`attribution`, then `terms_notice`) under it (Nogat DEV-20.5, ADR-083), named by
   Nogat's DEV-19.21: `hydrograf_hyetograph_<stem>.png` and
   `hydrograf_hydrograph_<stem>.png` with the stem of the hietogram's CSV (`24h_p1`,
   `custom`), `hydrograf_terrain-profile.png`, `hydrograf_hypsometric-curve.png`,
   `hydrograf_land-cover.png` and `hydrograf_soil-groups.png`. A failure is said under the
   chart in the kit's words. The CSV and JSON of the hietogram keep the whole series.
   `Hydrograf.api.saveFile` saves every file the page makes and counts it.

## Consequences

- Hydrograf meets DEV-15.16: its charts behave as Obserwator's, Hydrolog's and
  Archiwista's (each from its own step of the plan), read out by keys and fingers, and are
  named for screen readers with the keys and gestures in their `aria-description`. One
  vendored package less.
- A chart is a copy of the kit's code: its behaviour changes with a new kit copied byte
  for byte (DEV-15.6); a feature of a chart is a request to Nogat (DEV-17.5).
- The browser tests `backend/tests/e2e/test_charts.py` check the zoom, the pan, the
  reset, the readout, the phone, the PNG and the theme on Hydrograf's views.
- ADR-065 is amended: its Chart.js charts repainted by stylers are the kit's charts.
