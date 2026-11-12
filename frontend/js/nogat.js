/**
 * Nogat's GUI kit for Hydrograf's scripts (ADR-082).
 *
 * The kit in nogat/ is ES modules copied byte for byte from Nogat design/kit/ (DEV-15.6:
 * never edited here). Hydrograf's scripts are IIFE modules on window.Hydrograf, so this
 * module, the only ES module of Hydrograf's own, imports the kit and hands it on:
 * - every <nogat-app-menu> of the page, the menu „Aplikacje” of the top bar (DEV-15.4),
 *   gets the deployment's GUIs from GET /api/gui (HYDROGRAF_GUI) as its `apps`; without
 *   them, or without the API, the menu is not drawn;
 * - window.Hydrograf.nogat.handoff is the kit's hand-off module (DEV-15.5) for
 *   js/handoff.js, and window.Hydrograf.nogat.address(name) the address of a GUI of that
 *   table as the menu links it (http or https, resolved against the page), null when the
 *   table does not name it or has not come yet.
 * A <script type="module"> runs in document order with the deferred scripts, so the
 * kit is on window.Hydrograf before the scripts after it run.
 */
import { entries } from '../nogat/nogat-app-menu.js?v=3d5ac60cb2';
import * as handoff from '../nogat/nogat-handoff.js?v=605cda9ff5';

window.Hydrograf = window.Hydrograf || {};

let addresses = new Map();

fetch('/api/gui')
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
    address: (name) => addresses.get(name) || null,
};
