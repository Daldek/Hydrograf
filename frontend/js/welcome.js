/**
 * Hydrograf Welcome — a short plain-language introduction shown on the first
 * visit and from the "Instrukcja" button in the top bar.
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

    function init() {
        var dialog = document.getElementById('welcome-modal');
        if (!dialog || typeof dialog.showModal !== 'function') return;

        els = {
            dialog: dialog,
            hide: document.getElementById('welcome-hide'),
            mapBtn: document.getElementById('welcome-map'),
        };

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

        // The top-bar link opens the introduction; modified clicks keep the plain link
        var guideLink = document.getElementById('btn-guide');
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
