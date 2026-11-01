/**
 * Hydrograf theme switch for the secondary pages (admin, instrukcja).
 *
 * Binds the top bar buttons #theme-auto / #theme-light / #theme-dark: the choice
 * is stored under the same key theme-init.js reads, so it applies before first
 * paint on every page. "auto" follows the OS colour scheme.
 */
(function () {
    'use strict';

    var THEME_KEY = 'nogat-theme';

    var buttons = {
        auto: document.getElementById('theme-auto'),
        light: document.getElementById('theme-light'),
        dark: document.getElementById('theme-dark'),
    };

    function applyTheme(choice) {
        if (choice === 'light' || choice === 'dark') {
            document.documentElement.dataset.theme = choice;
        } else {
            delete document.documentElement.dataset.theme;
        }
        Object.keys(buttons).forEach(function (k) {
            buttons[k].setAttribute('aria-pressed', String(k === choice));
        });
    }

    Object.keys(buttons).forEach(function (k) {
        buttons[k].addEventListener('click', function () {
            try {
                localStorage.setItem(THEME_KEY, k);
            } catch (e) {
                // Storage unavailable: the choice lasts for this page only.
            }
            applyTheme(k);
        });
    });

    var stored = null;
    try { stored = localStorage.getItem(THEME_KEY); } catch (e) { /* OS theme */ }
    applyTheme(stored === 'light' || stored === 'dark' ? stored : 'auto');
})();
