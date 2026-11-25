/**
 * Nogat's GUI kit for Hydrograf's scripts (ADR-082).
 *
 * The kit in nogat/ is ES modules copied byte for byte from Nogat design/kit/ (DEV-15.6:
 * never edited here). Hydrograf's scripts are IIFE modules on window.Hydrograf, so this
 * module, the only ES module of Hydrograf's own, imports the kit and hands it on:
 * - every <nogat-app-menu> of the page, the menu „Aplikacje” of the top bar (DEV-15.4),
 *   gets the deployment's GUIs from GET /api/v1/gui (HYDROGRAF_GUI) as its `apps`; without
 *   them, or without the API, the menu is not drawn;
 * - the kit's <nogat-sources> (DEV-20.5) is defined: the view's strip of provider lines
 *   (js/attribution.js), and window.Hydrograf.nogat.fillSources writes its full content
 *   into the welcome window (js/welcome.js);
 * - window.Hydrograf.nogat.handoff is the kit's hand-off module (DEV-15.5) for
 *   js/handoff.js, and window.Hydrograf.nogat.address(name) the address of a GUI of that
 *   table as the menu links it (http or https, resolved against the page), null when the
 *   table does not name it or has not come yet;
 * - the kit's <nogat-basemaps> (DEV-15.15) is defined, and window.Hydrograf.nogat.basemaps
 *   holds the kit's words (`texts`) and its functions for MapLibre GL JS: `maplibre`
 *   (maplibreBasemap), `remove` (removeMaplibreBasemap) and `repaint`
 *   (repaintMaplibreBasemap), with which js/map.js draws the base map js/layers.js's
 *   switcher shows from GET /api/v1/basemaps (ADR-089);
 * - window.Hydrograf.nogat.chart is the kit's chart module (DEV-15.16) for js/charts.js:
 *   `draw` (drawChart), `toPng` and `format`, the Polish numbers and times its charts are
 *   written in (chartFormat(); ADR-090).
 * A <script type="module"> runs in document order with the deferred scripts, so the
 * kit is on window.Hydrograf before the scripts after it run; js/charts.js, before this
 * module, reaches it only when it draws.
 */
import { entries } from '../nogat/nogat-app-menu.js?v=951a2798ee';
import {
    BASEMAP_TEXTS,
    maplibreBasemap,
    removeMaplibreBasemap,
    repaintMaplibreBasemap,
} from '../nogat/nogat-basemaps.js?v=f9df0ea391';
import { chartFormat, drawChart, toPng } from '../nogat/nogat-chart.js?v=f4a3724044';
import * as handoff from '../nogat/nogat-handoff.js?v=ee555c209f';
import { fillSources } from '../nogat/nogat-sources.js?v=47514bf6ce';

window.Hydrograf = window.Hydrograf || {};

let addresses = new Map();

fetch('/api/v1/gui')
    .then((response) => (response.ok ? response.json() : {}))
    .catch(() => ({}))
    .then((gui) => {
        addresses = new Map(entries(gui));
        document.querySelectorAll('nogat-app-menu').forEach((menu) => {
            menu.apps = gui;
        });
    });

window.Hydrograf.nogat = {
    handoff: handoff,
    fillSources: fillSources,
    address: (name) => addresses.get(name) || null,
    basemaps: {
        texts: BASEMAP_TEXTS,
        maplibre: maplibreBasemap,
        remove: removeMaplibreBasemap,
        repaint: repaintMaplibreBasemap,
    },
    chart: {
        draw: drawChart,
        toPng: toPng,
        format: chartFormat(),
    },
};
