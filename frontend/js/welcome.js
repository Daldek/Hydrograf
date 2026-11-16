/**
 * Hydrograf Welcome — a short factual introduction (scope, methods, data area)
 * shown on the first visit and from the top-bar guide button.
 * The data area comes from /data/instance.json (Hydrograf.instance); without it the
 * paragraph keeps the neutral text of index.html.
 * Under it the full provider lines of the service's PMAXTP data and their terms, the
 * content of the dialog of the view's strip (Nogat DEV-20.5), ending on a public
 * deployment with „Regulamin serwisu” (new tab; the welcome window's link to the
 * regulamin, DEV-15.7): GET /api/terms (Hydrograf.terms) gives them, the kit's
 * fillSources (js/nogat.js) writes them.
 */
(function () {
    'use strict';

    window.Hydrograf = window.Hydrograf || {};

    // '1' = the user ticked "Nie pokazuj ponownie"
    var STORAGE_KEY = 'hydrograf-welcome-hidden';

    var els = {};

    function isHidden() {
        try { return localStorage.getItem(STORAGE_KEY) === '1'; } catch (e) { return false; }
    }

    function saveHidden(hidden) {
        try {
            if (hidden) localStorage.setItem(STORAGE_KEY, '1');
            else localStorage.removeItem(STORAGE_KEY);
        } catch (e) { /* private mode: shown again next time */ }
    }

    function openModal() {
        if (Hydrograf.map && Hydrograf.map.isDrawing && Hydrograf.map.isDrawing()) {
            Hydrograf.map.cancelDrawing();
        }
        els.hide.checked = isHidden();
        els.dialog.showModal();
        els.mapBtn.focus();
    }

    function closeModal() {
        if (els.dialog.open) els.dialog.close();
    }

    // "Obszar danych: <area>; <NMT, set>. <results caveat>" when the instance has a name
    function renderArea(info) {
        var area = Hydrograf.instance.areaLabel(info);
        if (!area) return;
        var sources = Hydrograf.instance.sourcesLabel(info);
        els.area.textContent = 'Obszar danych: ' + area + (sources ? '; ' + sources : '') +
            '. Wyniki są szacunkami do analiz wstępnych, nie prognozą hydrologiczną.';
    }

    /** The full lines, terms and regulamin in #welcome-sources; without any it stays hidden. */
    function renderSources(terms) {
        var box = document.getElementById('welcome-sources');
        if (!box) return;
        if (!terms.attribution.length && !terms.terms_notice.length && !terms.url) return;
        Hydrograf.nogat.fillSources(box, {
            attribution: terms.attribution,
            termsNotice: terms.terms_notice,
            terms: terms.url,
        });
        box.hidden = false;
    }

    function init() {
        var dialog = document.getElementById('welcome-modal');
        if (!dialog || typeof dialog.showModal !== 'function') return;

        els = {
            dialog: dialog,
            hide: document.getElementById('welcome-hide'),
            mapBtn: document.getElementById('welcome-map'),
            area: document.getElementById('welcome-area'),
        };

        if (Hydrograf.instance && els.area) Hydrograf.instance.load().then(renderArea);
        // The kit's module (js/nogat.js) defines the element and hands on fillSources in one run
        if (Hydrograf.terms) {
            Promise.all([Hydrograf.terms.ready, customElements.whenDefined('nogat-sources')])
                .then(function (done) { renderSources(done[0]); });
        }

        document.getElementById('welcome-close').addEventListener('click', closeModal);
        els.mapBtn.addEventListener('click', closeModal);
        // The guide opens in a new tab; the map stays ready behind it
        document.getElementById('welcome-guide').addEventListener('click', closeModal);
        dialog.addEventListener('click', function (e) {
            if (e.target === dialog) closeModal();
        });
        // Every way out (buttons, Esc, backdrop) keeps the checkbox choice
        dialog.addEventListener('close', function () {
            saveHidden(els.hide.checked);
        });

        // A plain click opens the introduction; modified clicks follow the guide link
        var guideLink = document.getElementById('top-guide');
        if (guideLink) {
            guideLink.addEventListener('click', function (e) {
                if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
                e.preventDefault();
                openModal();
            });
        }

        if (!isHidden()) openModal();
    }

    window.Hydrograf.welcome = {
        init: init,
    };
})();
